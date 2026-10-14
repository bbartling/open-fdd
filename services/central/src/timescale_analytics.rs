//! Timescale analytics for Wave-X Soft-OPEN envelopes (ADR-010).
//!
//! When `OPENFDD_DATABASE_URL` is set, product analytics never open a DataFusion
//! SessionContext — all query_ids dispatch here.

use anyhow::{Context, Result};
use fdd_tsdb::Tsdb;
use serde_json::{json, Value};
use sqlx::Row;

use crate::analytics::AnalyticsRequest;

/// Soft-OPEN: SQL body from `sql/analytics` pack (hash-pinned). Bind `$1` only.
const MOTOR_WEEKLY_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/motor_weekly_runtime.sql");
const BAS_VS_WEB_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/bas_vs_web_oat.sql");
const ECONOMIZER_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/economizer_deltas.sql");
const PLANT_HEALTH_SQL: &str =
    include_str!("../../../sql/analytics/postgres/queries/plant_health_inventory.sql");

pub async fn motor_weekly_runtime(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(MOTOR_WEEKLY_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("motor_weekly_runtime")?;

    let mut out = Vec::new();
    for r in rows {
        let runtime = r.try_get::<f64, _>("runtime_hours").ok()
            .or_else(|| r.try_get::<f64, _>("run_hours").ok());
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "kind": r.try_get::<String, _>("kind").unwrap_or_else(|_| "motor".into()),
            "plant_group": r.try_get::<String, _>("plant_group").ok(),
            "week_start": r.try_get::<chrono::DateTime<chrono::Utc>, _>("week_start")
                .ok()
                .map(|t| t.to_rfc3339()),
            "week_label": r.try_get::<String, _>("week_label").ok(),
            "run_hours": runtime,
            "runtime_hours": runtime,
        }));
    }
    Ok(envelope("motor-weekly-runtime", building_id, out))
}

pub async fn bas_vs_web_oat(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(BAS_VS_WEB_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("bas_vs_web_oat")?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").ok(),
            "bas_oa_t": r.try_get::<f64, _>("bas_oa_t").ok(),
            "web_oa_t": r.try_get::<f64, _>("web_oa_t").ok(),
            "delta_f": r.try_get::<f64, _>("delta_f").ok(),
        }));
    }
    Ok(envelope("bas-vs-web-oat", building_id, out))
}

pub async fn plant_health_matrix(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let rows = sqlx::query(PLANT_HEALTH_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("plant_health_matrix")?;

    // Wave-X C6: never fabricate score=1.0. Emit unavailable until scoped
    // diagnostic SQL health is implemented per cohort (see completion audit WX12).
    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "equip_type": r.try_get::<Option<String>, _>("equip_type").ok().flatten(),
            "score": Value::Null,
            "status": "unavailable",
            "reason": "plant_health_sql_pending",
        }));
    }
    Ok(envelope("plant-health", building_id, out))
}

pub async fn role_timeseries(
    tsdb: &Tsdb,
    building_id: &str,
    role_suffix: &str,
    query_id: &str,
    limit: i64,
) -> Result<Value> {
    let pattern = format!("%.{role_suffix}");
    let rows = sqlx::query(
        r#"
        SELECT ts, openfdd_key, val,
               split_part(openfdd_key, '.', 1) AS equipment_id
        FROM sample
        WHERE site_id = $1 AND openfdd_key LIKE $2
        ORDER BY ts DESC
        LIMIT $3
        "#,
    )
    .bind(building_id)
    .bind(&pattern)
    .bind(limit)
    .fetch_all(tsdb.pool())
    .await
    .with_context(|| format!("role_timeseries {role_suffix}"))?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "openfdd_key": r.try_get::<String, _>("openfdd_key").unwrap_or_default(),
            "val": r.try_get::<f64, _>("val").ok(),
        }));
    }
    Ok(envelope(query_id, building_id, out))
}

pub async fn economizer_deltas(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    // Soft-OPEN: per-equipment pivot from analytics pack (not cross-equip GROUP BY ts).
    let rows = sqlx::query(ECONOMIZER_SQL)
        .bind(building_id)
        .fetch_all(tsdb.pool())
        .await
        .context("economizer_deltas")?;

    let mut out = Vec::new();
    for r in rows {
        out.push(json!({
            "ts": r.try_get::<chrono::DateTime<chrono::Utc>, _>("ts").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<Option<String>, _>("equipment_id").ok().flatten(),
            "oa_t": r.try_get::<f64, _>("oa_t").ok(),
            "rat": r.try_get::<f64, _>("rat").ok(),
            "mat": r.try_get::<f64, _>("mat").ok(),
            "sat": r.try_get::<f64, _>("sat").ok(),
            "oa_damper_pct": r.try_get::<f64, _>("oa_damper_pct").ok(),
            "delta_or_f": r.try_get::<f64, _>("delta_or_f").ok(),
            "delta_mr_f": r.try_get::<f64, _>("delta_mr_f").ok(),
        }));
    }
    Ok(envelope("economizer", building_id, out))
}

pub async fn fdd_registry(tsdb: &Tsdb) -> Result<Value> {
    let rows = sqlx::query(
        r#"
        SELECT rule_id, sql_file, title, enabled
        FROM fdd_rule_registry
        ORDER BY rule_id
        "#,
    )
    .fetch_all(tsdb.pool())
    .await
    .context("fdd_registry")?;

    // Wave-X C7: warehouse cases.json uses cookbook ids (e.g. FC13) while the
    // product primary id may be FC13-SAT-HIGH. Surface yaml aliases so catalog
    // presence matches /api/fdd/run + /api/fdd/plot resolution.
    let aliases_by_id: std::collections::HashMap<String, Vec<String>> = {
        let root = crate::timescale_product::sql_root_for_registry();
        match fdd_rules::load_registry(&root) {
            Ok(reg) => reg
                .rules
                .into_iter()
                .map(|r| (r.rule_id, r.aliases))
                .collect(),
            Err(e) => {
                tracing::warn!(error = %e, "fdd_registry: yaml aliases unavailable");
                std::collections::HashMap::new()
            }
        }
    };

    let mut out = Vec::new();
    let mut alias_count = 0usize;
    for r in rows {
        let rule_id = r.try_get::<String, _>("rule_id").unwrap_or_default();
        let aliases = aliases_by_id.get(&rule_id).cloned().unwrap_or_default();
        alias_count += aliases.len();
        out.push(json!({
            "rule_id": rule_id,
            "aliases": aliases,
            "sql_file": r.try_get::<String, _>("sql_file").unwrap_or_default(),
            "title": r.try_get::<Option<String>, _>("title").ok().flatten(),
            "enabled": r.try_get::<bool, _>("enabled").unwrap_or(true),
            "engine": "postgres-sql",
        }));
    }
    Ok(json!({
        "ok": true,
        "engine": "postgres-sql",
        "count": out.len(),
        "alias_count": alias_count,
        "rules": out,
    }))
}

#[allow(dead_code)]
pub async fn historian_stats(tsdb: &Tsdb, building_id: &str) -> Result<Value> {
    let samples = tsdb.sample_count(building_id).await?;
    let rules = tsdb.rule_registry_count().await?;
    Ok(json!({
        "building_id": building_id,
        "engine": "timescale",
        "sample_count": samples,
        "fdd_rule_registry": rules,
        "historian": "timescale-only",
        "dual_write": false,
    }))
}

fn envelope(query_id: &str, building_id: &str, rows: Vec<Value>) -> Value {
    json!({
        "query_id": query_id,
        "building_id": building_id,
        "engine": "timescale-sql",
        "analytics_pack": "openfdd-analytics-sql-v1",
        "pack_version": "3.6.5-softopen",
        "stale": false,
        "rows": rows,
    })
}

fn building_from(req: &AnalyticsRequest) -> Result<String, (axum::http::StatusCode, axum::Json<Value>)> {
    match req
        .query
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        Some(id) => Ok(id.to_string()),
        None => Err((
            axum::http::StatusCode::BAD_REQUEST,
            axum::Json(json!({
                "ok": false,
                "error": "building_id is required",
                "engine": "timescale-sql",
            })),
        )),
    }
}

/// Universal product dispatch — never calls DataFusion.
pub async fn respond_query(
    query_id: &str,
    _query_version: &str,
    req: &AnalyticsRequest,
) -> Result<Value, (axum::http::StatusCode, axum::Json<Value>)> {
    let building = building_from(req)?;
    let tsdb = Tsdb::connect_from_env().await.map_err(|e| {
        (
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            axum::Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
                "hint": "OPENFDD_DATABASE_URL required for Wave-X product path",
            })),
        )
    })?;

    let result = match query_id {
        "runtime" => motor_weekly_runtime(&tsdb, &building).await,
        "bas-vs-web-oat" => bas_vs_web_oat(&tsdb, &building).await,
        "ahu-health"
        | "vav-health"
        | "chiller-health"
        | "boiler-health"
        | "hp-health"
        | "zone-other-health"
        | "cooling-tower-health"
        | "sensor-health"
        | "ahu-temperature-health"
        | "ahu-pressure-health"
        | "ahu-economizer-health" => plant_health_matrix(&tsdb, &building).await,
        "economizer" | "rcx-ahu" => economizer_deltas(&tsdb, &building).await,
        "rcx-vav" => role_timeseries(&tsdb, &building, "zone_t", "rcx-vav", 2000).await,
        "rcx-chiller" => {
            role_timeseries(&tsdb, &building, "chw_supply_t", "rcx-chiller", 2000).await
        }
        "rcx-boiler" => role_timeseries(&tsdb, &building, "hw_supply_t", "rcx-boiler", 2000).await,
        "equipment-inspect" | "inspect" => {
            // Wide envelope for SPA Inspect (points + coverage), not long sample dump.
            let _ = tsdb;
            match crate::timescale_product::inspect_json(req).await {
                Ok(v) => Ok(v),
                Err(e) => Err(e),
            }
        }
        "mechanical-cooling" => {
            role_timeseries(
                &tsdb,
                &building,
                "chiller_status",
                "mechanical-cooling",
                2000,
            )
            .await
        }
        "schedule" => role_timeseries(&tsdb, &building, "occ_mode", "schedule", 2000).await,
        "sensor-faults" | "sensor-stats" | "pid-hunting" | "setpoints" | "diurnal" | "topology"
        | "sql-anomaly" | "metering" | "mv-change-point" | "fuel" => {
            // Honest thin envelope — data present, full algorithm port tracked.
            let samples = tsdb.sample_count(&building).await.unwrap_or(0);
            Ok(json!({
                "query_id": query_id,
                "building_id": building,
                "engine": "timescale-sql",
                "stale": false,
                "rows": [],
                "sample_count": samples,
                "note": format!(
                    "Wave-X Timescale path active; full {query_id} SQL port pending — no DataFusion fallback"
                ),
            }))
        }
        other => Ok(json!({
            "query_id": other,
            "building_id": building,
            "engine": "timescale-sql",
            "stale": false,
            "rows": [],
            "note": "Wave-X Timescale dispatch — query SQL port pending; DataFusion disabled",
        })),
    };

    result.map_err(|e| {
        (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            axum::Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
            })),
        )
    })
}
