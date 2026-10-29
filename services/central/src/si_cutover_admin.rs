//! Admin SI cutover API (#1284 W2c): dry-run, token-gated POST, session + tuning migration.

use std::collections::HashMap;
use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::Json;
use fdd_core::MetricUnitsContract;
use fdd_rules::registry::RuleParameterDef;
use fdd_tsdb::{
    apply_sample_cutover_tx, dry_run_site, ensure_si_cutover_schema, invalidate_derived_results,
    SiCutoverError,
};
use open_fdd_edge_prototype::fdd::session_config::{
    put_session_config, SessionConfigScope, SESSION_SCHEMA,
};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use sqlx::{PgPool, Postgres, Transaction};

use crate::audit::{AuditAction, AuditEvent, HandlerResult, ReasonCode, TargetType};
use crate::routes::{require_hub_admin, AppState};

const SI_CUTOVER_TOKEN_KEY: &str = "si_cutover_token";
const PARAM_RENAME_JSON: &str = include_str!("../../../sql/contract/parameter_si_rename_map.json");
const DEFAULT_TENANT: &str = "legacy";
const SESSION_CHW_LEGACY: &str = "chw_leave_max_f";
const SESSION_CHW_SI: &str = "chw_leave_max";

#[derive(Debug, Deserialize)]
struct RenameMapFile {
    renames: HashMap<String, String>,
}

#[derive(Debug, Deserialize)]
pub struct SiCutoverPostBody {
    pub confirm: bool,
    pub token: String,
    #[serde(default)]
    pub site_ids: Vec<String>,
}

#[derive(Debug, Deserialize)]
pub struct SiCutoverDryRunQuery {
    #[serde(default)]
    pub site_id: Option<String>,
}

fn rename_map() -> Result<HashMap<String, String>, String> {
    let parsed: RenameMapFile =
        serde_json::from_str(PARAM_RENAME_JSON).map_err(|e| format!("rename map: {e}"))?;
    Ok(parsed.renames)
}

fn registry_rules() -> HashMap<String, fdd_rules::registry::RuleSpec> {
    open_fdd_edge_prototype::fdd::registry_api::load_registry_rules_map()
}

fn session_config_object(cfg: &Value) -> Option<&Map<String, Value>> {
    cfg.get("config").and_then(Value::as_object)
}

fn contract_quantity(param_key: &str, def: &RuleParameterDef) -> Option<&'static str> {
    if let Some(q) = def.quantity.as_deref() {
        return match q {
            "absolute_temperature" | "temperature" => Some("absolute_temperature"),
            "temperature_difference" | "temperature_delta" => Some("temperature_difference"),
            "temperature_rate" => Some("temperature_rate"),
            "air_pressure" | "pressure" => Some("air_pressure"),
            "hydronic_pressure" => Some("hydronic_pressure"),
            "volumetric_flow" => Some("volumetric_flow"),
            "power" => Some("power"),
            "interval_energy" => Some("interval_energy"),
            "percent" => Some("percent"),
            "fraction" => Some("fraction"),
            "duration_seconds" | "seconds" | "duration_minutes" | "minutes" => None,
            "boolean" | "count" | "dimensionless" => None,
            other if other.contains("temperature") && other.contains("diff") => {
                Some("temperature_difference")
            }
            _ => None,
        };
    }
    let unit = def.unit.as_str();
    if param_key == "deadband_c" || param_key.ends_with("_delta_f") || param_key == "delta_f" {
        return Some("temperature_difference");
    }
    match unit {
        "degF" | "°F" => Some("absolute_temperature"),
        "degF_delta" | "Δ°F" => Some("temperature_difference"),
        "inH2O" | "in.w.c." | "in_wc" => Some("air_pressure"),
        "psi" => Some("hydronic_pressure"),
        "cfm" | "gpm" => Some("volumetric_flow"),
        "kWh" => Some("interval_energy"),
        "%" | "pct" => Some("percent"),
        "frac" => Some("fraction"),
        "sec" | "min" | "h" | "bool" | "count" | "x" => None,
        _ => None,
    }
}

fn convert_param_value(
    contract: &MetricUnitsContract,
    param_key: &str,
    def: Option<&RuleParameterDef>,
    value: f64,
) -> Result<(String, f64), String> {
    let renames = rename_map()?;
    let out_key = renames
        .get(param_key)
        .cloned()
        .unwrap_or_else(|| param_key.to_string());
    let Some(def) = def else {
        return Ok((out_key, value));
    };
    let Some(qty) = contract_quantity(param_key, def) else {
        return Ok((out_key, value));
    };
    let source_unit = if qty == "temperature_difference"
        && matches!(def.unit.as_str(), "degF" | "°F" | "degF_delta" | "Δ°F")
    {
        "degF_delta"
    } else {
        def.unit.as_str()
    };
    let converted = contract
        .convert_to_canonical(qty, value, source_unit)
        .map_err(|e| format!("param {param_key}: {e}"))?;
    Ok((out_key, converted))
}

pub fn count_session_params_to_convert(site_id: &str) -> Result<i64, String> {
    let scope = SessionConfigScope::new(None, Some(site_id));
    let cfg = open_fdd_edge_prototype::fdd::session_config::get_session_config_scoped(&scope);
    let Some(params) = session_config_object(&cfg)
        .and_then(|c| c.get("params"))
        .and_then(Value::as_object)
    else {
        let chw_only = session_config_object(&cfg)
            .and_then(|c| c.get(SESSION_CHW_LEGACY))
            .is_some();
        return Ok(if chw_only { 1 } else { 0 });
    };
    let rules = registry_rules();
    let contract = MetricUnitsContract::load_embedded().map_err(|e| e.to_string())?;
    let mut count = 0_i64;
    if session_config_object(&cfg)
        .and_then(|c| c.get(SESSION_CHW_LEGACY))
        .is_some()
    {
        count += 1;
    }
    for (rule_id, rule_params) in params {
        let Some(rp) = rule_params.as_object() else {
            continue;
        };
        let spec = rules.get(rule_id.as_str());
        for (key, val) in rp {
            let Some(n) = val.as_f64() else {
                continue;
            };
            let def = spec.and_then(|s| s.parameters.get(key.as_str()));
            let renames = rename_map()?;
            if renames.contains_key(key) || def.and_then(|d| contract_quantity(key, d)).is_some() {
                let _ = convert_param_value(&contract, key, def, n)?;
                count += 1;
            }
        }
    }
    Ok(count)
}

fn migrate_session_config_object(obj: &mut Map<String, Value>) -> Result<i64, String> {
    let rules = registry_rules();
    let contract = MetricUnitsContract::load_embedded().map_err(|e| e.to_string())?;
    let mut touched = 0_i64;

    if let Some(v) = obj.remove(SESSION_CHW_LEGACY) {
        let n = v.as_f64().ok_or("chw_leave_max_f must be numeric")?;
        let converted = contract
            .convert_to_canonical("absolute_temperature", n, "degF")
            .map_err(|e| e.to_string())?;
        obj.insert(SESSION_CHW_SI.into(), json!(converted));
        touched += 1;
    }
    obj.insert("unit_system".into(), json!("si"));

    let Some(params) = obj.get_mut("params").and_then(Value::as_object_mut) else {
        return Ok(touched);
    };
    let rule_ids: Vec<String> = params.keys().cloned().collect();
    for rule_id in rule_ids {
        let Some(rp) = params.get_mut(&rule_id).and_then(Value::as_object_mut) else {
            continue;
        };
        let spec = rules.get(rule_id.as_str());
        let keys: Vec<String> = rp.keys().cloned().collect();
        for key in keys {
            let Some(val) = rp.remove(&key) else {
                continue;
            };
            let Some(n) = val.as_f64() else {
                rp.insert(key, val);
                continue;
            };
            let def = spec.and_then(|s| s.parameters.get(key.as_str()));
            let (new_key, new_val) = convert_param_value(&contract, &key, def, n)?;
            if new_key != key || def.is_some() {
                touched += 1;
            }
            rp.insert(new_key, json!(new_val));
        }
    }
    Ok(touched)
}

pub fn migrate_session_config_files(site_id: &str) -> Result<i64, String> {
    let scope = SessionConfigScope::new(None, Some(site_id));
    let cfg = open_fdd_edge_prototype::fdd::session_config::get_session_config_scoped(&scope);
    let Some(mut obj) = session_config_object(&cfg).cloned() else {
        return Ok(0);
    };
    let touched = migrate_session_config_object(&mut obj)?;
    if touched == 0 {
        return Ok(0);
    }
    let body = json!({
        "schema_version": SESSION_SCHEMA,
        "building_id": site_id,
        "config": obj,
    });
    let out = put_session_config(&body);
    if out.get("ok") != Some(&json!(true)) {
        return Err(out
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("session config save failed")
            .to_string());
    }
    Ok(touched)
}

async fn next_rule_revision(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
    rule_id: &str,
) -> Result<i64, sqlx::Error> {
    let current: Option<i64> = sqlx::query_scalar(
        r#"
        SELECT max(revision) FROM fdd.rule_config_revision
        WHERE tenant_id = $1 AND site_id = $2 AND rule_id = $3 AND scope_key = 'site'
        "#,
    )
    .bind(DEFAULT_TENANT)
    .bind(site_id)
    .bind(rule_id)
    .fetch_one(&mut **tx)
    .await?;
    Ok(current.unwrap_or(0) + 1)
}

pub async fn write_si_rule_config_revisions(
    tx: &mut Transaction<'_, Postgres>,
    site_id: &str,
    actor: &str,
) -> Result<i64, sqlx::Error> {
    let scope = SessionConfigScope::new(None, Some(site_id));
    let cfg = open_fdd_edge_prototype::fdd::session_config::get_session_config_scoped(&scope);
    let Some(params) = session_config_object(&cfg)
        .and_then(|c| c.get("params"))
        .and_then(Value::as_object)
    else {
        return Ok(0);
    };
    let rules = registry_rules();
    let contract = match MetricUnitsContract::load_embedded() {
        Ok(c) => c,
        Err(_) => return Ok(0),
    };
    let mut written = 0_i64;
    for (rule_id, rule_params) in params {
        let Some(rp) = rule_params.as_object() else {
            continue;
        };
        if rp.is_empty() {
            continue;
        }
        let spec = rules.get(rule_id.as_str());
        let mut si_params = Map::new();
        for (key, val) in rp {
            let Some(n) = val.as_f64() else {
                continue;
            };
            let def = spec.and_then(|s| s.parameters.get(key.as_str()));
            if let Ok((k, v)) = convert_param_value(&contract, key, def, n) {
                si_params.insert(k, json!(v));
            }
        }
        if si_params.is_empty() {
            continue;
        }
        let revision = next_rule_revision(tx, site_id, rule_id).await?;
        sqlx::query(
            r#"
            INSERT INTO fdd.rule_config_revision
              (tenant_id, site_id, rule_id, scope_key, revision, parameters, created_by)
            VALUES ($1, $2, $3, 'site', $4, $5, $6)
            "#,
        )
        .bind(DEFAULT_TENANT)
        .bind(site_id)
        .bind(rule_id)
        .bind(revision)
        .bind(Value::Object(si_params.clone()))
        .bind(actor)
        .execute(&mut **tx)
        .await?;
        sqlx::query(
            r#"
            INSERT INTO fdd.active_rule_config
              (tenant_id, site_id, rule_id, scope_key, revision)
            VALUES ($1, $2, $3, 'site', $4)
            ON CONFLICT (tenant_id, site_id, rule_id, scope_key)
            DO UPDATE SET revision = EXCLUDED.revision
            "#,
        )
        .bind(DEFAULT_TENANT)
        .bind(site_id)
        .bind(rule_id)
        .bind(revision)
        .execute(&mut **tx)
        .await?;
        written += 1;
    }
    Ok(written)
}

async fn stored_cutover_token(pool: &PgPool) -> Result<Option<String>, sqlx::Error> {
    let value: Option<String> = sqlx::query_scalar("SELECT value FROM seed_meta WHERE key = $1")
        .bind(SI_CUTOVER_TOKEN_KEY)
        .fetch_optional(pool)
        .await?;
    Ok(value)
}

async fn record_cutover_token(pool: &PgPool, token: &str) -> Result<(), sqlx::Error> {
    sqlx::query(
        "INSERT INTO seed_meta(key, value) VALUES ($1, $2)
         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
    )
    .bind(SI_CUTOVER_TOKEN_KEY)
    .bind(token)
    .execute(pool)
    .await?;
    Ok(())
}

fn env_cutover_token() -> Option<String> {
    std::env::var("OPENFDD_SI_CUTOVER_TOKEN")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

async fn list_target_sites(pool: &PgPool, site_ids: &[String]) -> Result<Vec<String>, sqlx::Error> {
    if site_ids.is_empty() {
        return sqlx::query_scalar("SELECT site_id FROM site ORDER BY site_id")
            .fetch_all(pool)
            .await;
    }
    let mut out = Vec::new();
    for id in site_ids {
        let trimmed = id.trim();
        if !trimmed.is_empty() {
            out.push(trimmed.to_string());
        }
    }
    out.sort();
    out.dedup();
    Ok(out)
}

fn dry_run_json(report: &fdd_tsdb::SiteDryRunReport) -> Value {
    json!({
        "site_id": report.site_id,
        "series_by_quantity_unit": report.series_by_quantity_unit,
        "rows_to_convert": report.rows_to_convert,
        "unresolved_series": report.unresolved_series,
        "excluded_series": report.excluded_series,
        "saved_params_to_convert": report.saved_params_to_convert,
    })
}

pub async fn si_cutover_dry_run_handler(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<SiCutoverDryRunQuery>,
) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::AdminRead);
    audit.target(TargetType::Route, "/api/admin/si-cutover/dry-run");
    let _user = require_hub_admin(&state, &headers, &mut audit)?;
    let pool = tsdb_pool().await.map_err(|e| {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    ensure_si_cutover_schema(&pool).await.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e.to_string()})),
        )
    })?;
    let sites = if let Some(site) = query.site_id.as_deref() {
        vec![site.trim().to_string()]
    } else {
        list_target_sites(&pool, &[]).await.map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": e.to_string()})),
            )
        })?
    };
    let mut site_reports = Vec::new();
    for site_id in sites {
        let saved = count_session_params_to_convert(&site_id).unwrap_or(0);
        let report = dry_run_site(&pool, &site_id, saved)
            .await
            .map_err(map_si_err)?;
        site_reports.push(dry_run_json(&report));
    }
    audit.finish(&Ok(Json(json!({"ok": true})))).emit();
    Ok(Json(json!({
        "ok": true,
        "sites": site_reports,
    })))
}

pub async fn si_cutover_post_handler(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<SiCutoverPostBody>,
) -> HandlerResult {
    let mut audit = AuditEvent::new(AuditAction::AdminMaintenance);
    audit.target(TargetType::Route, "/api/admin/si-cutover");
    let user = require_hub_admin(&state, &headers, &mut audit)?;
    if !body.confirm {
        audit.reason(ReasonCode::ValidationFailed);
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "confirm:true required"})),
        ));
    }
    let expected = env_cutover_token().ok_or((
        StatusCode::SERVICE_UNAVAILABLE,
        Json(json!({"ok": false, "error": "OPENFDD_SI_CUTOVER_TOKEN not configured"})),
    ))?;
    if body.token.trim() != expected {
        audit.reason(ReasonCode::ValidationFailed);
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "invalid cutover token"})),
        ));
    }
    let pool = tsdb_pool().await.map_err(|e| {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    ensure_si_cutover_schema(&pool).await.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e.to_string()})),
        )
    })?;
    if let Some(consumed) = stored_cutover_token(&pool).await.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e.to_string()})),
        )
    })? {
        if consumed == expected {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({"ok": false, "error": "cutover token already used"})),
            ));
        }
    }
    let sites = list_target_sites(&pool, &body.site_ids)
        .await
        .map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": e.to_string()})),
            )
        })?;
    let mut results = Vec::new();
    for site_id in &sites {
        let saved = count_session_params_to_convert(site_id).unwrap_or(0);
        let dry = dry_run_site(&pool, site_id, saved)
            .await
            .map_err(map_si_err)?;
        let mut tx = pool.begin().await.map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": e.to_string()})),
            )
        })?;
        let mut sample_result = apply_sample_cutover_tx(&mut tx, &dry)
            .await
            .map_err(map_si_err)?;
        sample_result.params_revisions_written =
            write_si_rule_config_revisions(&mut tx, site_id, &user.username)
                .await
                .map_err(|e| {
                    (
                        StatusCode::INTERNAL_SERVER_ERROR,
                        Json(json!({"ok": false, "error": e.to_string()})),
                    )
                })?;
        invalidate_derived_results(&mut tx, site_id)
            .await
            .map_err(|e| {
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(json!({"ok": false, "error": e.to_string()})),
                )
            })?;
        tx.commit().await.map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": e.to_string()})),
            )
        })?;
        let _ = migrate_session_config_files(site_id);
        results.push(json!({
            "site_id": site_id,
            "dry_run": dry_run_json(&dry),
            "rows_converted": sample_result.rows_converted,
            "series_converted": sample_result.series_converted,
            "params_revisions_written": sample_result.params_revisions_written,
        }));
    }
    record_cutover_token(&pool, &expected).await.map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e.to_string()})),
        )
    })?;
    audit.finish(&Ok(Json(json!({"ok": true})))).emit();
    Ok(Json(json!({
        "ok": true,
        "sites": results,
    })))
}

async fn tsdb_pool() -> Result<PgPool, String> {
    fdd_tsdb::Tsdb::connect_from_env()
        .await
        .map(|t| t.pool().clone())
        .map_err(|e| e.to_string())
}

fn map_si_err(err: SiCutoverError) -> (StatusCode, Json<Value>) {
    match err {
        SiCutoverError::UnresolvedSeries { site_id, keys } => (
            StatusCode::CONFLICT,
            Json(json!({
                "ok": false,
                "error": "unresolved unit-dependent series",
                "site_id": site_id,
                "unresolved_series": keys,
            })),
        ),
        other => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": other.to_string()})),
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delta_f_param_converts_scale_only_to_si_key() {
        let contract = MetricUnitsContract::load_embedded().expect("contract");
        let def = RuleParameterDef {
            label: "delta".into(),
            default: 9.0,
            min: 0.0,
            max: 20.0,
            step: 0.5,
            unit: "degF".into(),
            quantity: Some("temperature_difference".into()),
            frontend_control: "slider".into(),
            sql_placeholder: "DELTA_F".into(),
        };
        let (key, val) = convert_param_value(&contract, "delta_f", Some(&def), 9.0).expect("convert");
        assert_eq!(key, "delta");
        assert!((val - 5.0).abs() < 1e-6, "got {val}");
    }
}
