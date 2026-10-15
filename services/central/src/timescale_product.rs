//! Wave-X Soft-OPEN product paths on Timescale (Inspect / RCx / FDD series / FDD run).
//! No DataFusion / Parquet. Soft-OPEN ≠ FQ.

use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use chrono::{DateTime, Utc};
use fdd_rules::{
    effective_param_strings, load_registry, load_tuning_profiles, rule_params, substitute_sql,
    RuleRegistry, RuleSpec,
};
use fdd_tsdb::Tsdb;
use serde_json::{json, Value};
use sqlx::{PgConnection, Row};

use crate::analytics::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, AnalyticsRequest};

const TS_ENGINE: &str = "timescale-sql";

fn sql_root() -> PathBuf {
    sql_root_for_registry()
}

/// Shared SQL pack root for registry.yaml (catalog aliases + plot/run).
pub(crate) fn sql_root_for_registry() -> PathBuf {
    if let Some(p) = std::env::var_os("OPENFDD_SQL_ROOT") {
        return PathBuf::from(p);
    }
    if let Some(p) = std::env::var_os("OPENFDD_SQL_RULES_DIR") {
        return PathBuf::from(p);
    }
    // Workspace root (services/central/../..) then sql/fdd — works in unit tests.
    let from_manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../sql/fdd")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../sql/fdd"));
    if from_manifest.is_dir() {
        return from_manifest;
    }
    PathBuf::from("sql/fdd")
}

fn load_reg() -> Result<RuleRegistry> {
    let root = sql_root();
    load_registry(&root).with_context(|| format!("load registry {}", root.display()))
}

fn rule_sql_path(reg: &RuleRegistry, sql_file: &str) -> PathBuf {
    let root = PathBuf::from(&reg.rules_dir);
    for c in [
        root.join("postgres/rules").join(sql_file),
        root.join("warehouse/rules").join(sql_file),
        root.join("rules").join(sql_file),
        root.join(sql_file),
    ] {
        if c.is_file() {
            return c;
        }
    }
    root.join("postgres/rules").join(sql_file)
}

fn safe_ident(name: &str) -> bool {
    !name.is_empty() && name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn kind_aliases(kind: &str) -> Vec<&'static str> {
    match kind.to_ascii_lowercase().as_str() {
        "ahu" | "rtu" | "mau" | "doas" => vec!["ahu", "rtu", "mau", "doas"],
        "vav" => vec!["vav"],
        "chiller" | "chw" | "chwplant" | "chw_plant" => {
            vec!["chiller", "chw", "chwplant", "chw_plant", "chwPlant"]
        }
        "boiler" => vec!["boiler"],
        "heatpump" | "hp" | "heat_pump" => vec!["heatpump", "hp", "heat_pump", "heatPump"],
        "weather" => vec!["weather"],
        "zone" | "zone_other" | "fcu" | "baseboard" => {
            vec!["zone", "zone_other", "fcu", "baseboard", "zone_other"]
        }
        "zone_family" => {
            vec![
                "vav",
                "fcu",
                "zone",
                "zone_other",
                "heatpump",
                "baseboard",
                "hp",
            ]
        }
        _ => vec![],
    }
}

fn equip_matches_kinds(equip_type: Option<&str>, kinds: &[&str]) -> bool {
    if kinds.is_empty() {
        return true;
    }
    let Some(raw) = equip_type.map(str::trim).filter(|s| !s.is_empty()) else {
        return false;
    };
    let raw_l = raw.to_ascii_lowercase();
    for k in kinds {
        if k.eq_ignore_ascii_case("ZONE_FAMILY") {
            if kind_aliases("zone_family").iter().any(|a| raw_l == *a) {
                return true;
            }
            continue;
        }
        if kind_aliases(k).iter().any(|a| raw_l == *a) || raw_l == k.to_ascii_lowercase() {
            return true;
        }
    }
    false
}

async fn list_equipment(tsdb: &Tsdb, building_id: &str) -> Result<Vec<(String, Option<String>)>> {
    let rows = sqlx::query(
        r#"
        SELECT equipment_id, equip_type
        FROM equipment
        WHERE building_id = $1
        ORDER BY equipment_id
        "#,
    )
    .bind(building_id)
    .fetch_all(tsdb.pool())
    .await
    .context("list_equipment")?;
    Ok(rows
        .into_iter()
        .map(|r| {
            (
                r.get::<String, _>("equipment_id"),
                r.try_get::<Option<String>, _>("equip_type").ok().flatten(),
            )
        })
        .collect())
}

async fn roles_for_equipment(
    tsdb: &Tsdb,
    building_id: &str,
    equipment_id: &str,
) -> Result<Vec<String>> {
    let rows = sqlx::query(
        r#"
        SELECT DISTINCT split_part(openfdd_key, '.', 2) AS role
        FROM sample
        WHERE site_id = $1
          AND split_part(openfdd_key, '.', 1) = $2
          AND split_part(openfdd_key, '.', 2) <> ''
        ORDER BY 1
        "#,
    )
    .bind(building_id)
    .bind(equipment_id)
    .fetch_all(tsdb.pool())
    .await
    .context("roles_for_equipment")?;
    Ok(rows
        .into_iter()
        .filter_map(|r| r.try_get::<String, _>("role").ok())
        .filter(|r| safe_ident(r))
        .collect())
}

/// Wide inspect points for one equipment (SPA equipmentInspectionChart).
pub async fn inspect_equipment(
    building_id: &str,
    equipment_id: &str,
    columns: Option<&[String]>,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let eq = equipment_id.trim();
    if eq.is_empty() || building_id.trim().is_empty() {
        return Ok(None);
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let plottable = roles_for_equipment(&tsdb, building_id, eq).await?;
    if plottable.is_empty() {
        return Ok(None);
    }
    const PREFERRED: &[&str] = &[
        "sat",
        "mat",
        "rat",
        "oa_t",
        "web_oa_t",
        "oa_damper_pct",
        "fan_status",
        "fan_cmd",
        "duct_static",
        "duct_static_sp",
        "sat_sp",
        "clg_valve_pct",
        "htg_valve_pct",
        "zone_t",
        "zone_flow",
        "chw_supply_t",
        "chw_return_t",
        "hw_supply_t",
        "hw_return_t",
        "occ_mode",
    ];
    let selected: Vec<String> = match columns {
        Some(want) if !want.is_empty() => want
            .iter()
            .filter(|c| plottable.iter().any(|p| p == *c))
            .cloned()
            .collect(),
        _ => {
            let mut picked: Vec<String> = PREFERRED
                .iter()
                .filter(|c| plottable.iter().any(|p| p == *c))
                .map(|c| (*c).to_string())
                .collect();
            if picked.is_empty() {
                picked = plottable.iter().take(8).cloned().collect();
            } else if picked.len() < 6 {
                for c in &plottable {
                    if picked.len() >= 8 {
                        break;
                    }
                    if !picked.iter().any(|p| p == c) {
                        picked.push(c.clone());
                    }
                }
            }
            picked
        }
    };
    if selected.is_empty() {
        return Ok(None);
    }
    let limit = max_points.clamp(50, 8000) as i64;
    // Pivot selected roles; span-preserving downsample via row_number.
    let mut filters = String::new();
    for (i, role) in selected.iter().enumerate() {
        if i > 0 {
            filters.push_str(" OR ");
        }
        filters.push_str(&format!("openfdd_key = '{eq}.{role}'"));
    }
    let mut max_cols = String::new();
    for role in &selected {
        max_cols.push_str(&format!(
            ", MAX(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{role}') AS \"{role}\""
        ));
    }
    let sql = format!(
        r#"
SELECT timestamp_utc {max_cols_outer}
FROM (
  SELECT
    ts AS timestamp_utc
    {max_cols},
    ROW_NUMBER() OVER (ORDER BY ts) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample
  WHERE site_id = $1 AND ({filters})
  GROUP BY ts
) s
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $2 - 1) / $2) > 1 THEN ((_cnt + $2 - 1) / $2) ELSE 1 END)) = 0
ORDER BY timestamp_utc
LIMIT $2
"#,
        max_cols_outer = selected
            .iter()
            .map(|r| format!(", \"{r}\""))
            .collect::<String>(),
        max_cols = max_cols,
        filters = filters,
    );
    let rows = sqlx::query(&sql)
        .bind(building_id)
        .bind(limit)
        .fetch_all(tsdb.pool())
        .await
        .context("inspect pivot")?;
    let mut points = Vec::with_capacity(rows.len());
    for r in &rows {
        let ts = r
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(|t| t.to_rfc3339())
            .unwrap_or_default();
        let mut row = json!({
            "timestamp_utc": ts,
            "equipment_id": eq,
        });
        if let Some(obj) = row.as_object_mut() {
            for c in &selected {
                let v = r.try_get::<Option<f64>, _>(c.as_str()).ok().flatten();
                obj.insert(c.clone(), json!(v));
            }
        }
        points.push(row);
    }
    let first = points
        .first()
        .and_then(|p| p.get("timestamp_utc").and_then(|v| v.as_str()))
        .map(str::to_string);
    let last = points
        .last()
        .and_then(|p| p.get("timestamp_utc").and_then(|v| v.as_str()))
        .map(str::to_string);
    let mut env = envelope_with_engine(
        "equipment-inspect-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["equipment inspection points from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    env.points = points;
    env.rows = selected.iter().map(|c| json!({ "column": c })).collect();
    env.coverage = Some(json!({
        "equipment_id": eq,
        "row_count": env.points.len(),
        "point_count": env.points.len(),
        "plottable_columns": plottable,
        "columns_plotted": selected,
        "first_timestamp": first,
        "last_timestamp": last,
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
    }));
    Ok(Some(env))
}

/// RCx multi-equipment role timeseries (`value_f` / optional motor).
pub async fn rcx_timeseries(
    building_id: &str,
    role_col: &str,
    overlay_col: Option<&str>,
    pair_return_col: Option<&str>,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    if !safe_ident(role_col) {
        return Ok(None);
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids: Vec<String> = equipment
        .into_iter()
        .filter(|(_, t)| equip_matches_kinds(t.as_deref(), eq_kinds))
        .map(|(id, _)| id)
        .collect();
    if ids.is_empty() {
        return Ok(None);
    }
    let limit = max_points.clamp(200, 20000) as i64;
    let pattern = format!("%.{role_col}");
    let fan_join = if filter_fan_on {
        "AND EXISTS (
            SELECT 1 FROM sample f
            WHERE f.site_id = s.site_id AND f.ts = s.ts
              AND f.openfdd_key = split_part(s.openfdd_key,'.',1) || '.fan_status'
              AND COALESCE(f.val, 0) > 0.05
          )"
    } else {
        ""
    };
    // Bound equipment via ANY($3)
    let sql = format!(
        r#"
SELECT timestamp_utc, equipment_id, value_f, motor_f
FROM (
  SELECT
    s.ts AS timestamp_utc,
    split_part(s.openfdd_key, '.', 1) AS equipment_id,
    s.val AS value_f,
    (
      SELECT CASE WHEN COALESCE(m.val, 0) > 0.05 THEN 1.0 ELSE 0.0 END
      FROM sample m
      WHERE m.site_id = s.site_id AND m.ts = s.ts
        AND m.openfdd_key = split_part(s.openfdd_key, '.', 1) || '.fan_status'
      LIMIT 1
    ) AS motor_f,
    ROW_NUMBER() OVER (ORDER BY s.ts, s.openfdd_key) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample s
  WHERE s.site_id = $1
    AND s.openfdd_key LIKE $2
    AND split_part(s.openfdd_key, '.', 1) = ANY($3)
    AND s.val IS NOT NULL
    {fan_join}
) q
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $4 - 1) / $4) > 1 THEN ((_cnt + $4 - 1) / $4) ELSE 1 END)) = 0
ORDER BY timestamp_utc, equipment_id
LIMIT $4
"#
    );
    let rows = sqlx::query(&sql)
        .bind(building_id)
        .bind(&pattern)
        .bind(&ids)
        .bind(limit)
        .fetch_all(tsdb.pool())
        .await
        .context("rcx_timeseries")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    for r in &rows {
        let ts = r
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(|t| t.to_rfc3339())
            .unwrap_or_default();
        let eq = r.try_get::<String, _>("equipment_id").unwrap_or_default();
        let value_f = r.try_get::<Option<f64>, _>("value_f").ok().flatten();
        let motor_f = r.try_get::<Option<f64>, _>("motor_f").ok().flatten();
        points.push(json!({
            "timestamp_utc": ts,
            "equipment_id": eq,
            "value_f": value_f,
            "series": "primary",
        }));
        if let Some(m) = motor_f {
            points.push(json!({
                "timestamp_utc": ts,
                "equipment_id": eq,
                "value_f": if m > 0.05 { 1.0 } else { 0.0 },
                "series": "motor",
            }));
        }
        let _ = (overlay_col, pair_return_col); // Soft-OPEN: primary + motor first
    }
    let mut env = envelope_with_engine(
        "rcx-timeseries-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["RCx role timeseries from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points;
    env.coverage = Some(json!({
        "point_count": n,
        "role_col": role_col,
        "chart_kind": "timeseries",
        "source": "timescale_sample",
        "building_id": building_id,
        "equipment_n": ids.len(),
        "engine": TS_ENGINE,
    }));
    Ok(Some(env))
}

pub async fn rcx_oat_scatter(
    building_id: &str,
    y_col: &str,
    eq_kinds: &[&str],
    prefer_wetbulb: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    if !safe_ident(y_col) {
        return Ok(None);
    }
    let _ = prefer_wetbulb;
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids: Vec<String> = equipment
        .into_iter()
        .filter(|(_, t)| equip_matches_kinds(t.as_deref(), eq_kinds))
        .map(|(id, _)| id)
        .collect();
    if ids.is_empty() {
        return Ok(None);
    }
    let limit = max_points.clamp(200, 20000) as i64;
    let y_pat = format!("%.{y_col}");
    let rows = sqlx::query(
        r#"
        WITH y AS (
          SELECT ts, split_part(openfdd_key,'.',1) AS equipment_id, val AS y_f
          FROM sample
          WHERE site_id = $1
            AND openfdd_key LIKE $2
            AND split_part(openfdd_key,'.',1) = ANY($3)
            AND val IS NOT NULL
        ),
        oat AS (
          SELECT ts, val AS oat_f
          FROM sample
          WHERE site_id = $1
            AND (openfdd_key LIKE '%.web_oa_t' OR openfdd_key LIKE '%.oa_t')
        )
        SELECT y.ts AS timestamp_utc, y.equipment_id, y.y_f, o.oat_f
        FROM y
        JOIN oat o ON o.ts = y.ts
        WHERE o.oat_f IS NOT NULL
        ORDER BY y.ts DESC
        LIMIT $4
        "#,
    )
    .bind(building_id)
    .bind(&y_pat)
    .bind(&ids)
    .bind(limit)
    .fetch_all(tsdb.pool())
    .await
    .context("rcx_oat_scatter")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    for r in &rows {
        points.push(json!({
            "timestamp_utc": r.try_get::<DateTime<Utc>, _>("timestamp_utc").ok().map(|t| t.to_rfc3339()),
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "y_f": r.try_get::<Option<f64>, _>("y_f").ok().flatten(),
            "oat_f": r.try_get::<Option<f64>, _>("oat_f").ok().flatten(),
            "dry_bulb_f": r.try_get::<Option<f64>, _>("oat_f").ok().flatten(),
        }));
    }
    let mut env = envelope_with_engine(
        "rcx-scatter-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["RCx OAT scatter from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points;
    env.coverage = Some(json!({
        "point_count": n,
        "role_col": y_col,
        "chart_kind": "scatter_oat",
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
    }));
    Ok(Some(env))
}

pub async fn rcx_box(
    building_id: &str,
    role_col: &str,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    // Soft-OPEN: reuse timeseries points; SPA box chart tolerates value_f rows.
    rcx_timeseries(
        building_id,
        role_col,
        None,
        None,
        eq_kinds,
        filter_fan_on,
        max_points,
    )
    .await
}

pub async fn rcx_zone_comfort_rank(
    building_id: &str,
    eq_kinds: &[&str],
    comfort_low_f: f64,
    comfort_high_f: f64,
) -> Result<Option<AnalyticsEnvelope>> {
    let tsdb = Tsdb::connect_from_env().await?;
    let equipment = list_equipment(&tsdb, building_id).await?;
    let ids: Vec<String> = equipment
        .into_iter()
        .filter(|(_, t)| equip_matches_kinds(t.as_deref(), eq_kinds))
        .map(|(id, _)| id)
        .collect();
    if ids.is_empty() {
        return Ok(None);
    }
    let rows = sqlx::query(
        r#"
        SELECT
          split_part(openfdd_key, '.', 1) AS equipment_id,
          100.0 * AVG(CASE WHEN val BETWEEN $2 AND $3 THEN 1.0 ELSE 0.0 END) AS comfort_pct,
          COUNT(*)::bigint AS n
        FROM sample
        WHERE site_id = $1
          AND openfdd_key LIKE '%.zone_t'
          AND split_part(openfdd_key, '.', 1) = ANY($4)
          AND val IS NOT NULL
        GROUP BY 1
        ORDER BY comfort_pct ASC
        LIMIT 200
        "#,
    )
    .bind(building_id)
    .bind(comfort_low_f)
    .bind(comfort_high_f)
    .bind(&ids)
    .fetch_all(tsdb.pool())
    .await
    .context("rcx_zone_comfort_rank")?;
    if rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    for r in &rows {
        points.push(json!({
            "equipment_id": r.try_get::<String, _>("equipment_id").unwrap_or_default(),
            "comfort_pct": r.try_get::<Option<f64>, _>("comfort_pct").ok().flatten(),
            "n": r.try_get::<i64, _>("n").unwrap_or(0),
            "value_f": r.try_get::<Option<f64>, _>("comfort_pct").ok().flatten(),
        }));
    }
    let mut env = envelope_with_engine(
        "rcx-ranking-v1",
        &AnalyticsQuery {
            building_id: Some(building_id.to_string()),
            ..Default::default()
        },
        vec!["RCx zone comfort rank from Timescale sample (Wave-X Soft-OPEN)".into()],
        TS_ENGINE,
    );
    let n = points.len();
    env.points = points.clone();
    env.rows = points;
    env.coverage = Some(json!({
        "point_count": n,
        "chart_kind": "ranking",
        "source": "timescale_sample",
        "building_id": building_id,
        "engine": TS_ENGINE,
    }));
    Ok(Some(env))
}

/// Dispatch for respond_query("equipment-inspect").
pub async fn inspect_json(req: &AnalyticsRequest) -> Result<Value> {
    let building = req
        .query
        .building_id
        .clone()
        .unwrap_or_else(|| "BUILDING_50".into());
    let eq = req
        .query
        .equipment_ids
        .as_ref()
        .and_then(|ids| ids.first())
        .map(|s| s.as_str())
        .unwrap_or("");
    let columns: Option<Vec<String>> = req.series.as_ref().and_then(|s| {
        s.get("columns").and_then(|c| c.as_array()).map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
    });
    let max_points = req.query.max_points.unwrap_or(2000);
    match inspect_equipment(&building, eq, columns.as_deref(), max_points).await? {
        Some(env) => Ok(env.to_json()),
        None => {
            let mut env = envelope_with_engine(
                "equipment-inspect-v1",
                &req.query,
                vec!["no Timescale samples for equipment".into()],
                TS_ENGINE,
            );
            env.coverage = Some(json!({
                "equipment_id": eq,
                "plottable_columns": [],
                "columns_plotted": [],
                "point_count": 0,
                "source": "timescale_sample",
                "building_id": building,
            }));
            Ok(env.to_json())
        }
    }
}

/// Cap series count for lean Plotly (C12): required ∪ limited optional, ≤6.
const LEAN_PLOT_MAX_ROLES: usize = 6;
const LEAN_PLOT_DEFAULT_POINTS: usize = 1500;
const LEAN_PLOT_HARD_CAP: usize = 5000;

/// Resolve catalog roles for a rule — never alphabetically dump point_map.
pub fn catalog_plot_roles(rule: &RuleSpec) -> Vec<String> {
    let mut roles: Vec<String> = rule.required_roles.clone();
    for r in &rule.optional_roles {
        if !roles.iter().any(|x| x == r) {
            roles.push(r.clone());
        }
    }
    roles.retain(|r| safe_ident(r));
    if roles.len() > LEAN_PLOT_MAX_ROLES {
        roles.truncate(LEAN_PLOT_MAX_ROLES);
    }
    roles
}

fn clamp_max_points(max_points: Option<usize>) -> usize {
    max_points
        .unwrap_or(LEAN_PLOT_DEFAULT_POINTS)
        .clamp(50, LEAN_PLOT_HARD_CAP)
}

/// FDD plot series: wide role columns for one equipment + rule roles.
#[allow(dead_code)]
pub async fn fdd_series(
    building_id: Option<&str>,
    equipment_id: &str,
    rule_id: &str,
) -> Result<Value> {
    fdd_plot(building_id, equipment_id, rule_id, None, None, None).await
}

/// Lean Plotly data plane (C12): catalog roles only, downsampled, optional window.
pub async fn fdd_plot(
    building_id: Option<&str>,
    equipment_id: &str,
    rule_id: &str,
    max_points: Option<usize>,
    window_start: Option<&str>,
    window_end: Option<&str>,
) -> Result<Value> {
    let bid = building_id.map(str::trim).filter(|s| !s.is_empty());
    let Some(building_id) = bid else {
        return Ok(json!({
            "ok": false,
            "error": "building_id required for Timescale FDD plot",
            "engine": TS_ENGINE,
            "rows": [],
            "series": {},
        }));
    };
    let reg = load_reg()?;
    let Some(rule) = reg
        .rules
        .iter()
        .find(|r| r.rule_id == rule_id || r.aliases.iter().any(|a| a == rule_id))
    else {
        return Ok(json!({
            "ok": false,
            "error": format!("unknown rule_id {rule_id}"),
            "rows": [],
            "series": {},
            "note": "Unknown catalog rule — no point_map LIMIT-N fallback.",
        }));
    };
    let mut roles = catalog_plot_roles(rule);
    let max_pts = clamp_max_points(max_points);
    if roles.is_empty() {
        return Ok(json!({
            "ok": true,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "site_id": building_id,
            "building_id": building_id,
            "rows": [],
            "roles": [],
            "series": {},
            "confirmed_fault": {"ts": [], "y": []},
            "point_count": 0,
            "max_points": max_pts,
            "note": "Catalog rule has no plottable roles for this equipment.",
            "engine": TS_ENGINE,
        }));
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let present = roles_for_equipment(&tsdb, building_id, equipment_id).await?;
    let present_set: BTreeSet<_> = present.iter().cloned().collect();
    let missing: Vec<String> = rule
        .required_roles
        .iter()
        .filter(|r| safe_ident(r) && !present_set.contains(r.as_str()))
        .cloned()
        .collect();
    // Soft note when optional roles missing; hard fail only if required missing.
    let mut note_parts: Vec<String> = Vec::new();
    if !missing.is_empty() {
        return Ok(json!({
            "ok": false,
            "error": format!("missing roles for rule {}: {}", rule.rule_id, missing.join(", ")),
            "missing_roles": missing,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "site_id": building_id,
            "building_id": building_id,
            "rows": [],
            "series": {},
            "engine": TS_ENGINE,
        }));
    }
    roles.retain(|r| present_set.contains(r));
    if roles.is_empty() {
        note_parts.push("No mapped roles present on this equipment.".into());
        return Ok(json!({
            "ok": true,
            "equipment_id": equipment_id,
            "rule_id": rule.rule_id,
            "site_id": building_id,
            "building_id": building_id,
            "rows": [],
            "roles": [],
            "series": {},
            "confirmed_fault": {"ts": [], "y": []},
            "point_count": 0,
            "max_points": max_pts,
            "note": note_parts.join(" "),
            "engine": TS_ENGINE,
        }));
    }
    let mut max_cols = String::new();
    for role in &roles {
        max_cols.push_str(&format!(
            ", MAX(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{role}') AS \"{role}\""
        ));
    }
    let mut filters = String::new();
    for (i, role) in roles.iter().enumerate() {
        if i > 0 {
            filters.push_str(" OR ");
        }
        filters.push_str(&format!("openfdd_key = '{equipment_id}.{role}'"));
    }
    let mut window_sql = String::new();
    if let Some(start) = window_start.map(str::trim).filter(|s| !s.is_empty()) {
        if DateTime::parse_from_rfc3339(start).is_ok() {
            window_sql.push_str(&format!(" AND ts >= '{start}'::timestamptz"));
        }
    }
    if let Some(end) = window_end.map(str::trim).filter(|s| !s.is_empty()) {
        if DateTime::parse_from_rfc3339(end).is_ok() {
            window_sql.push_str(&format!(" AND ts <= '{end}'::timestamptz"));
        }
    }
    let sql = format!(
        r#"
SELECT timestamp_utc {sel}
FROM (
  SELECT
    ts AS timestamp_utc
    {max_cols},
    ROW_NUMBER() OVER (ORDER BY ts) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM sample
  WHERE site_id = $1 AND ({filters}){window_sql}
  GROUP BY ts
) s
WHERE _rn = 1 OR _rn = _cnt
   OR (_rn % (CASE WHEN ((_cnt + $2 - 1) / $2) > 1 THEN ((_cnt + $2 - 1) / $2) ELSE 1 END)) = 0
ORDER BY timestamp_utc
LIMIT $2
"#,
        sel = roles
            .iter()
            .map(|r| format!(", \"{r}\""))
            .collect::<String>(),
        max_cols = max_cols,
        filters = filters,
        window_sql = window_sql,
    );
    let rows = sqlx::query(&sql)
        .bind(building_id)
        .bind(max_pts as i64)
        .fetch_all(tsdb.pool())
        .await
        .context("fdd_plot pivot")?;
    let mut out_rows = Vec::with_capacity(rows.len());
    let mut lean: serde_json::Map<String, Value> = serde_json::Map::new();
    for role in &roles {
        lean.insert(role.clone(), json!({"ts": [], "y": []}));
    }
    let mut fault_ts = Vec::new();
    let mut fault_y = Vec::new();
    for r in &rows {
        let ts = r
            .try_get::<DateTime<Utc>, _>("timestamp_utc")
            .ok()
            .map(|t| t.to_rfc3339());
        let mut row = json!({
            "timestamp_utc": ts,
            "equipment_id": equipment_id,
        });
        if let Some(obj) = row.as_object_mut() {
            for c in &roles {
                let v = r.try_get::<Option<f64>, _>(c.as_str()).ok().flatten();
                obj.insert(c.clone(), json!(v));
                if let Some(series) = lean.get_mut(c).and_then(|s| s.as_object_mut()) {
                    if let Some(ts_arr) = series.get_mut("ts").and_then(|x| x.as_array_mut()) {
                        ts_arr.push(json!(ts));
                    }
                    if let Some(y_arr) = series.get_mut("y").and_then(|x| x.as_array_mut()) {
                        y_arr.push(json!(v));
                    }
                }
            }
            obj.insert("confirmed_fault".into(), Value::Null);
        }
        out_rows.push(row);
    }
    if let Ok(fault_map) = load_confirmed_fault_hint(building_id, equipment_id, &rule.rule_id) {
        for row in &mut out_rows {
            let ts_owned = row
                .get("timestamp_utc")
                .and_then(|v| v.as_str())
                .map(str::to_string);
            if let Some(ts) = ts_owned {
                if let Some(flag) = fault_map.get(ts.as_str()) {
                    if let Some(obj) = row.as_object_mut() {
                        obj.insert("confirmed_fault".into(), json!(flag));
                    }
                    fault_ts.push(json!(ts));
                    fault_y.push(json!(if *flag { 1 } else { 0 }));
                }
            }
        }
    }
    let point_count = out_rows.len();
    if point_count >= max_pts {
        note_parts.push(format!("Downsampled to ≤{max_pts} pts/series for UI."));
    }
    // OAT-METEO must never fall back to duct-static via point_map dump (roles from catalog only).
    if rule.rule_id.eq_ignore_ascii_case("OAT-METEO")
        && roles
            .iter()
            .any(|r| r.contains("duct") || r.contains("static"))
    {
        note_parts.push("OAT-METEO catalog roles exclude duct-static fallback.".into());
    }
    let note = if note_parts.is_empty() {
        Value::Null
    } else {
        json!(note_parts.join(" "))
    };
    // Soft-OPEN R4: surface lean plot budgets for SPA (roles ≤6, pts hard-cap).
    let approx_bytes =
        point_count.saturating_mul(roles.len().saturating_mul(24).saturating_add(32));
    Ok(json!({
        "ok": true,
        "equipment_id": equipment_id,
        "rule_id": rule.rule_id,
        "site_id": building_id,
        "building_id": building_id,
        "roles": roles,
        "rows": out_rows,
        "series": lean,
        "confirmed_fault": {"ts": fault_ts, "y": fault_y},
        "fault_hours": Value::Null,
        "point_count": point_count,
        "downsampled": true,
        "max_points": max_pts,
        "lean_budget": {
            "max_roles": LEAN_PLOT_MAX_ROLES,
            "default_points": LEAN_PLOT_DEFAULT_POINTS,
            "hard_cap_points": LEAN_PLOT_HARD_CAP,
            "approx_payload_bytes": approx_bytes,
        },
        "note": note,
        "has_confirmed_fault": out_rows.iter().any(|r| r.get("confirmed_fault").and_then(|v| v.as_bool()).is_some()),
        "engine": TS_ENGINE,
        "source": "timescale_sample",
        "soft_open_neq_fq": true,
    }))
}

/// Soft-OPEN R4: catalog plot roles per rule (no historian read) for SPA menus.
pub fn plots_by_rule_catalog() -> Result<Value> {
    let reg = load_reg()?;
    let mut rules = Vec::with_capacity(reg.rules.len());
    for rule in &reg.rules {
        let roles = catalog_plot_roles(rule);
        rules.push(json!({
            "rule_id": rule.rule_id,
            "aliases": rule.aliases,
            "roles": roles,
            "role_count": roles.len(),
            "max_roles": LEAN_PLOT_MAX_ROLES,
            "equipment_kinds": rule.equipment_kinds,
        }));
    }
    Ok(json!({
        "ok": true,
        "engine": TS_ENGINE,
        "count": rules.len(),
        "lean_budget": {
            "max_roles": LEAN_PLOT_MAX_ROLES,
            "default_points": LEAN_PLOT_DEFAULT_POINTS,
            "hard_cap_points": LEAN_PLOT_HARD_CAP,
        },
        "rules": rules,
        "soft_open_neq_fq": true,
        "note": "Soft-OPEN catalog plot roles — Soft-OPEN ≠ FQ",
    }))
}

fn results_dir(building_id: &str) -> PathBuf {
    let base = if let Ok(p) = std::env::var("OPENFDD_RULE_RESULTS_DIR") {
        PathBuf::from(p)
    } else if let Ok(url) = std::env::var("OPENFDD_STORAGE_URL") {
        PathBuf::from(url.trim_start_matches("file://")).join("rule_results")
    } else if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        PathBuf::from(ws).join("openfdd").join("rule_results")
    } else {
        PathBuf::from(".cache/rule_results")
    };
    base.join(format!("building={building_id}"))
}

/// Soft-OPEN write-once (R8f / BPS parity): if a prior run-all left `_run_meta.json`
/// (or any rule result JSON), return it with `skipped_recompute` instead of re-running
/// the full cohort. Callers pass `force_new_data` to bypass.
pub fn cached_run_all_if_present(building_id: &str) -> Option<Value> {
    let dir = results_dir(building_id);
    let meta_path = dir.join("_run_meta.json");
    if meta_path.is_file() {
        if let Ok(text) = std::fs::read_to_string(&meta_path) {
            if let Ok(mut body) = serde_json::from_str::<Value>(&text) {
                if let Some(obj) = body.as_object_mut() {
                    obj.insert("skipped_recompute".into(), json!(true));
                    obj.insert(
                        "message".into(),
                        json!(
                            "FDD results already on file for this site — UI should read records. \
                             Use force_new_data=true only after new historian samples, \
                             or run a single rule_id from Lab / rule tuning."
                        ),
                    );
                    obj.insert("ok".into(), json!(true));
                }
                return Some(body);
            }
        }
    }
    // Any persisted rule JSON counts as "cohort has been run".
    let has_rule = std::fs::read_dir(&dir).ok()?.any(|e| {
        e.ok()
            .map(|e| {
                let name = e.file_name();
                let s = name.to_string_lossy();
                s.ends_with(".json") && !s.starts_with('_')
            })
            .unwrap_or(false)
    });
    if !has_rule {
        return None;
    }
    Some(json!({
        "ok": true,
        "engine": TS_ENGINE,
        "building_id": building_id,
        "historian": "timescale",
        "skipped_recompute": true,
        "message": "FDD results already on file for this site — UI should read records. \
                    Use force_new_data=true only after new historian samples, \
                    or run a single rule_id from Lab / rule tuning.",
    }))
}

fn load_confirmed_fault_hint(
    building_id: &str,
    equipment_id: &str,
    rule_id: &str,
) -> Result<HashMap<String, bool>> {
    let path = results_dir(building_id).join(format!("{rule_id}.json"));
    let text = std::fs::read_to_string(path)?;
    let body: Value = serde_json::from_str(&text)?;
    let mut map = HashMap::new();
    if let Some(series) = body.get("fault_series").and_then(|v| v.as_array()) {
        for row in series {
            let eq = row
                .get("equipment_id")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            if eq != equipment_id {
                continue;
            }
            let ts = row
                .get("timestamp_utc")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let flag = row
                .get("confirmed_fault")
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            if !ts.is_empty() {
                map.insert(ts.to_string(), flag);
            }
        }
    }
    Ok(map)
}

fn session_override_for_rule(
    payload: &Value,
    rule_id: &str,
) -> Option<std::collections::HashMap<String, f64>> {
    let params = payload.get("params")?.as_object()?;
    let rule_params = params.get(rule_id)?.as_object()?;
    let mut out = std::collections::HashMap::new();
    for (k, v) in rule_params {
        if let Some(n) = v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)) {
            if n.is_finite() {
                out.insert(k.clone(), n);
            }
        }
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

fn render_rule_sql(
    reg: &RuleRegistry,
    rule: &RuleSpec,
    poll: f64,
    confirm: u32,
    building_id: &str,
    equipment_id: Option<&str>,
    session_override: Option<&std::collections::HashMap<String, f64>>,
) -> Result<String> {
    let path = rule_sql_path(reg, &rule.sql_file);
    let raw = std::fs::read_to_string(&path)
        .with_context(|| format!("read rule sql {}", path.display()))?;
    let mut params = rule_params(poll, confirm);
    if let Ok(tuning) = load_tuning_profiles(Path::new(&reg.rules_dir)) {
        if let Ok(tuned) = effective_param_strings(
            rule,
            &tuning,
            Some(building_id),
            equipment_id,
            session_override,
        ) {
            for (k, v) in tuned {
                params.insert(k, v);
            }
        }
    }
    Ok(substitute_sql(&raw, &params))
}

fn rule_is_metric(rule: &RuleSpec) -> bool {
    // Diagnostic rules expose fault_hours; metric/utility analytical outputs do not.
    !rule
        .output_columns
        .iter()
        .any(|c| c == "fault_hours" || c == "fault_pct" || c == "fault_samples")
}

/// Rule SQL often yields `fault_hours` as PostgreSQL `numeric` (CASE with `0.0`).
/// sqlx `try_get::<f64>` fails on numeric → Soft-OPEN run-now reported 0h.
/// Cast through a wrapper SELECT so the product path always gets float8.
/// Metric rules keep `SELECT *` so fan_runtime_hours / avg_zone_temp survive.
fn wrap_rule_sql(sql_body: &str, rule: &RuleSpec) -> String {
    let inner = sql_body.trim().trim_end_matches(';').trim();
    if rule_is_metric(rule) {
        format!("SELECT * FROM ({inner}) AS _fdd_rule_q")
    } else {
        format!(
            "SELECT equipment_id::text AS equipment_id, \
             fault_hours::double precision AS fault_hours \
             FROM ({inner}) AS _fdd_rule_q"
        )
    }
}

fn confirm_seconds_from_payload(payload: &Value, rule: &RuleSpec) -> u32 {
    if let Some(cs) = payload
        .get("confirmation_seconds")
        .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
        .filter(|v| v.is_finite() && *v >= 0.0)
    {
        return cs.round() as u32;
    }
    if let Some(params) = payload.get("params") {
        if let Some(cs) = params
            .get("confirmation_seconds")
            .or_else(|| params.get("confirm_seconds"))
            .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
            .filter(|v| v.is_finite() && *v >= 0.0)
        {
            return cs.round() as u32;
        }
        if let Some(cm) = params
            .get("confirm_min")
            .and_then(|v| v.as_f64())
            .filter(|v| v.is_finite() && *v >= 0.0)
        {
            return (cm * 60.0).round() as u32;
        }
    }
    rule.confirm_seconds
}

/// Soft-OPEN R6: cadence from payload / session params; default 300 (no parquet poll cache).
fn poll_seconds_from_payload(payload: &Value) -> f64 {
    if let Some(ps) = payload
        .get("poll_seconds")
        .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
        .filter(|v| v.is_finite() && *v > 0.0)
    {
        return ps;
    }
    if let Some(params) = payload.get("params") {
        if let Some(ps) = params
            .get("poll_seconds")
            .and_then(|v| v.as_f64().or_else(|| v.as_u64().map(|u| u as f64)))
            .filter(|v| v.is_finite() && *v > 0.0)
        {
            return ps;
        }
    }
    300.0
}

fn is_weather_role(role: &str) -> bool {
    matches!(
        role,
        "oa_t"
            | "web_oa_t"
            | "outside_air_temp"
            | "web_outside_air_temp"
            | "web-outside-air-temp"
            | "oat"
            | "oa_rh"
            | "oa_enthalpy"
    )
}

fn row_fault_hours(row: &sqlx::postgres::PgRow) -> f64 {
    if let Ok(v) = row.try_get::<f64, _>("fault_hours") {
        return v;
    }
    if let Ok(Some(v)) = row.try_get::<Option<f64>, _>("fault_hours") {
        return v;
    }
    if let Ok(v) = row.try_get::<i64, _>("fault_hours") {
        return v as f64;
    }
    if let Ok(v) = row.try_get::<i32, _>("fault_hours") {
        return v as f64;
    }
    0.0
}

async fn ensure_history_table(conn: &mut PgConnection, roles: &[String]) -> Result<()> {
    let mut cols = String::from("equipment_id text not null, timestamp_utc timestamptz not null");
    for r in roles {
        cols.push_str(&format!(", \"{r}\" double precision"));
    }
    sqlx::query(&format!(
        "CREATE TEMP TABLE history ({cols}) ON COMMIT DROP"
    ))
    .execute(&mut *conn)
    .await
    .context("create temp history")?;
    Ok(())
}

async fn fill_history_for_equipment(
    conn: &mut PgConnection,
    building_id: &str,
    equipment_id: &str,
    roles: &[String],
    window_start: Option<&str>,
    window_end: Option<&str>,
) -> Result<i64> {
    if roles.is_empty() {
        return Ok(0);
    }
    let mut max_cols = String::new();
    for role in roles {
        max_cols.push_str(&format!(
            ", MAX(val) FILTER (WHERE split_part(openfdd_key, '.', 2) = '{role}') AS \"{role}\""
        ));
    }
    let mut filters = String::new();
    for (i, role) in roles.iter().enumerate() {
        if i > 0 {
            filters.push_str(" OR ");
        }
        filters.push_str(&format!("openfdd_key = '{equipment_id}.{role}'"));
        // Soft-OPEN R6: weather/utility roles also from stamped weather equipment.
        if is_weather_role(role) {
            filters.push_str(&format!(
                " OR (split_part(openfdd_key, '.', 2) = '{role}' \
                 AND split_part(openfdd_key, '.', 1) IN ( \
                   SELECT equipment_id FROM equipment \
                   WHERE building_id = $1 \
                     AND lower(coalesce(equip_type, '')) IN ('weather') \
                 ))"
            ));
        }
        // Soft-OPEN R6: CHW plant roles from stamped chiller/chwPlant equipment when
        // the target itself has no local key (exact role match only).
        if matches!(
            role.as_str(),
            "chw_supply_t" | "chw_return_t" | "chw_flow" | "chw_dp" | "chw_supply_sp"
        ) {
            filters.push_str(&format!(
                " OR (split_part(openfdd_key, '.', 2) = '{role}' \
                 AND split_part(openfdd_key, '.', 1) IN ( \
                   SELECT equipment_id FROM equipment \
                   WHERE building_id = $1 \
                     AND lower(coalesce(equip_type, '')) IN ( \
                       'chiller', 'chw', 'chwplant', 'chw_plant' \
                     ) \
                 ))"
            ));
        }
    }
    // Soft-OPEN R6: honor half-open [start, end) when caller supplies window.
    let mut window_sql = String::new();
    if let Some(start) = window_start.map(str::trim).filter(|s| !s.is_empty()) {
        if safe_rfc3339(start) {
            window_sql.push_str(&format!(" AND ts >= '{start}'::timestamptz"));
        }
    }
    if let Some(end) = window_end.map(str::trim).filter(|s| !s.is_empty()) {
        if safe_rfc3339(end) {
            window_sql.push_str(&format!(" AND ts < '{end}'::timestamptz"));
        }
    }
    let insert_cols = roles
        .iter()
        .map(|r| format!("\"{r}\""))
        .collect::<Vec<_>>()
        .join(", ");
    let sql = format!(
        r#"
INSERT INTO history (equipment_id, timestamp_utc, {insert_cols})
SELECT '{equipment_id}', ts {max_cols}
FROM sample
WHERE site_id = $1 AND ({filters}){window_sql}
GROUP BY ts
"#
    );
    let res = sqlx::query(&sql)
        .bind(building_id)
        .execute(&mut *conn)
        .await
        .context("fill history")?;
    Ok(res.rows_affected() as i64)
}

/// Soft-OPEN R6: required roles must have ≥1 non-null sample in TEMP history.
async fn missing_required_roles(
    conn: &mut PgConnection,
    required: &[String],
) -> Result<Vec<String>> {
    let mut missing = Vec::new();
    for role in required {
        if !safe_ident(role) {
            missing.push(role.clone());
            continue;
        }
        let sql = format!("SELECT COUNT(*)::bigint AS n FROM history WHERE \"{role}\" IS NOT NULL");
        let n: i64 = sqlx::query_scalar(&sql)
            .fetch_one(&mut *conn)
            .await
            .unwrap_or(0);
        if n == 0 {
            missing.push(role.clone());
        }
    }
    Ok(missing)
}

fn safe_rfc3339(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 40
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | ':' | 'T' | 'Z' | '+' | '.'))
}

/// Timescale postgres-sql registry run-now (Soft-OPEN).
pub async fn run_fdd_registry(payload: &Value) -> Result<Value> {
    let building_id = payload
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| anyhow!("building_id required for Timescale FDD run"))?
        .to_string();
    let rule_filter: Option<Vec<String>> = payload.get("rule_ids").and_then(|v| {
        v.as_array().map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(str::to_string))
                .collect()
        })
    });
    let equipment_filter = payload
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);

    let reg = load_reg()?;
    let mut rules: Vec<&RuleSpec> = reg.rules.iter().collect();
    if let Some(ids) = &rule_filter {
        if !ids.is_empty() {
            rules.retain(|r| {
                ids.iter()
                    .any(|id| r.rule_id == *id || r.aliases.iter().any(|a| a == id))
            });
        }
    }
    let tsdb = Tsdb::connect_from_env().await?;
    let mut equipment = list_equipment(&tsdb, &building_id).await?;
    if let Some(eq) = &equipment_filter {
        // Soft-OPEN R6: never broaden an exact equipment_id miss into all equipment.
        equipment.retain(|(id, _)| id == eq);
        if equipment.is_empty() {
            // Exact id may exist only on samples (no equipment row yet).
            let rows = sqlx::query(
                r#"
                SELECT DISTINCT split_part(openfdd_key,'.',1) AS equipment_id
                FROM sample
                WHERE site_id = $1 AND split_part(openfdd_key,'.',1) = $2
                LIMIT 1
                "#,
            )
            .bind(&building_id)
            .bind(eq)
            .fetch_all(tsdb.pool())
            .await?;
            equipment = rows
                .into_iter()
                .map(|r| (r.get::<String, _>("equipment_id"), None))
                .collect();
        }
        if equipment.is_empty() {
            return Ok(json!({
                "ok": false,
                "engine": TS_ENGINE,
                "building_id": building_id,
                "historian": "timescale",
                "error": format!("equipment_id `{eq}` not found for site"),
                "status": "INELIGIBLE_EQUIPMENT",
                "rules_run": 0,
                "rules_succeeded": 0,
                "rules_failed": 0,
                "rules_skipped": 0,
                "results": [],
            }));
        }
    } else if equipment.is_empty() {
        // No selector: inventory from sample keys (site-scoped).
        let rows = sqlx::query(
            r#"
            SELECT DISTINCT split_part(openfdd_key,'.',1) AS equipment_id
            FROM sample WHERE site_id = $1
            ORDER BY 1 LIMIT 200
            "#,
        )
        .bind(&building_id)
        .fetch_all(tsdb.pool())
        .await?;
        equipment = rows
            .into_iter()
            .map(|r| (r.get::<String, _>("equipment_id"), None))
            .collect();
    }

    let window_start = payload
        .get("start")
        .or_else(|| payload.get("window_start"))
        .and_then(|v| v.as_str());
    let window_end = payload
        .get("end")
        .or_else(|| payload.get("window_end"))
        .and_then(|v| v.as_str());

    let out_dir = results_dir(&building_id);
    std::fs::create_dir_all(&out_dir)?;
    let _ = std::fs::remove_file(out_dir.join("_dirty.json"));

    let poll = poll_seconds_from_payload(payload);
    let t0 = std::time::Instant::now();
    let mut rules_run = 0u32;
    let mut rules_succeeded = 0u32;
    let mut rules_failed = 0u32;
    let mut rules_skipped = 0u32;
    let mut all_results = Vec::new();

    for rule in rules {
        rules_run += 1;
        let kinds: Vec<&str> = rule.equipment_kinds.iter().map(String::as_str).collect();
        // Soft-OPEN R6: type-first always. Exact id is allowed only after type filter
        // when a stamp is present; missing/unrecognized stamp stays unclassified.
        let targets: Vec<(String, Option<String>)> = equipment
            .iter()
            .filter(|(id, t)| {
                if kinds.is_empty() {
                    return true;
                }
                if equip_matches_kinds(t.as_deref(), &kinds) {
                    return true;
                }
                // Exact id with no stamp: still allow (inventory from samples).
                equipment_filter.as_deref() == Some(id.as_str()) && t.is_none()
            })
            .cloned()
            .collect();
        if targets.is_empty() {
            rules_skipped += 1;
            continue;
        }

        let confirm = confirm_seconds_from_payload(payload, rule);
        let session_override = session_override_for_rule(payload, &rule.rule_id);
        let metric = rule_is_metric(rule);
        let sql_body = match render_rule_sql(
            &reg,
            rule,
            poll,
            confirm,
            &building_id,
            equipment_filter.as_deref(),
            session_override.as_ref(),
        ) {
            Ok(s) => wrap_rule_sql(&s, rule),
            Err(e) => {
                rules_failed += 1;
                tracing::warn!(rule = %rule.rule_id, error = %e, "render rule sql failed");
                continue;
            }
        };

        let mut role_set: BTreeSet<String> = rule.required_roles.iter().cloned().collect();
        for r in &rule.optional_roles {
            role_set.insert(r.clone());
        }
        // Common gate roles
        for extra in ["fan_status", "fan_cmd", "occ_mode"] {
            role_set.insert(extra.into());
        }
        // Soft-OPEN R6: weather/CHW relation roles when SQL may need them.
        for extra in [
            "oa_t",
            "web_oa_t",
            "chw_supply_t",
            "chw_return_t",
            "chw_flow",
            "chw_dp",
        ] {
            if rule.required_roles.iter().any(|r| r == extra)
                || rule.optional_roles.iter().any(|r| r == extra)
            {
                role_set.insert(extra.into());
            }
        }
        let roles: Vec<String> = role_set.into_iter().filter(|r| safe_ident(r)).collect();

        let mut rule_rows = Vec::new();
        let mut ok_any = false;
        let mut err_any = false;
        for (eq_id, _) in &targets {
            let mut tx = tsdb.pool().begin().await?;
            if let Err(e) = ensure_history_table(&mut tx, &roles).await {
                rules_failed += 1;
                err_any = true;
                tracing::warn!(rule = %rule.rule_id, error = %e, "temp history");
                break;
            }
            let n = fill_history_for_equipment(
                &mut tx,
                &building_id,
                eq_id,
                &roles,
                window_start,
                window_end,
            )
            .await?;
            if n == 0 {
                rule_rows.push(json!({
                    "equipment_id": eq_id,
                    "fault_hours": 0.0,
                    "status": "SKIP_NO_HISTORY",
                    "missing_roles": rule.required_roles,
                    "output_kind": if metric { "metric" } else { "diagnostic" },
                }));
                let _ = tx.rollback().await;
                continue;
            }
            // Soft-OPEN R6: required-role eligibility before SQL execute.
            let missing = missing_required_roles(&mut tx, &rule.required_roles).await?;
            if !missing.is_empty() {
                rule_rows.push(json!({
                    "equipment_id": eq_id,
                    "fault_hours": 0.0,
                    "status": "SKIP_MISSING_ROLES",
                    "missing_roles": missing,
                    "sample_rows": n,
                    "output_kind": if metric { "metric" } else { "diagnostic" },
                }));
                let _ = tx.rollback().await;
                continue;
            }
            match sqlx::query(&sql_body).fetch_all(&mut *tx).await {
                Ok(rows) => {
                    if metric {
                        // Preserve first row metrics; do not invent FAULT/PASS.
                        let mut row_json = json!({
                            "equipment_id": eq_id,
                            "status": "METRIC",
                            "output_kind": "metric",
                            "sample_rows": n,
                            "confirm_seconds": confirm,
                            "poll_seconds": poll,
                        });
                        if let Some(first) = rows.first() {
                            if let Ok(v) = first.try_get::<f64, _>("fan_runtime_hours") {
                                row_json["fan_runtime_hours"] = json!(v);
                            }
                            if let Ok(v) = first.try_get::<f64, _>("total_hours") {
                                row_json["total_hours"] = json!(v);
                            }
                            if let Ok(v) = first.try_get::<f64, _>("avg_zone_temp") {
                                row_json["avg_zone_temp"] = json!(v);
                            }
                            if let Ok(v) = first.try_get::<f64, _>("comfort_pct") {
                                row_json["comfort_pct"] = json!(v);
                            }
                        }
                        rule_rows.push(row_json);
                    } else {
                        let mut hours = 0.0_f64;
                        for r in &rows {
                            hours += row_fault_hours(r);
                        }
                        // Soft-OPEN R6: publish confirm detail / fault_series stub.
                        let status = if hours > 0.0 { "FAULT" } else { "PASS" };
                        rule_rows.push(json!({
                            "equipment_id": eq_id,
                            "fault_hours": hours,
                            "status": status,
                            "output_kind": "diagnostic",
                            "sample_rows": n,
                            "confirm_seconds": confirm,
                            "poll_seconds": poll,
                            "fault_series": {
                                "kind": "confirm_aggregate",
                                "fault_hours": hours,
                                "confirm_seconds": confirm,
                                "poll_seconds": poll,
                                "status": status,
                                "note": "Soft-OPEN confirm aggregate; per-sample series Soft-OPEN later"
                            },
                        }));
                    }
                    ok_any = true;
                    let _ = tx.commit().await;
                }
                Err(e) => {
                    err_any = true;
                    rule_rows.push(json!({
                        "equipment_id": eq_id,
                        "fault_hours": 0.0,
                        "status": "ERROR",
                        "output_kind": if metric { "metric" } else { "diagnostic" },
                        "notes": e.to_string(),
                    }));
                    let _ = tx.rollback().await;
                }
            }
        }
        // Soft-OPEN: partial ERROR ≠ clean success.
        if ok_any && !err_any {
            rules_succeeded += 1;
        } else if err_any || !ok_any {
            rules_failed += 1;
        }
        let body = json!({
            "rule_id": rule.rule_id,
            "engine": TS_ENGINE,
            "building_id": building_id,
            "rows": rule_rows,
            "generated_at": Utc::now().to_rfc3339(),
        });
        let path = out_dir.join(format!("{}.json", rule.rule_id));
        std::fs::write(&path, serde_json::to_vec_pretty(&body)?)?;
        all_results.extend(rule_rows.into_iter().map(|mut row| {
            if let Some(obj) = row.as_object_mut() {
                obj.insert("rule_id".into(), json!(rule.rule_id));
            }
            row
        }));
    }

    let meta = json!({
        "ok": true,
        "engine": TS_ENGINE,
        "building_id": building_id,
        "historian": "timescale",
        "dual_write": false,
        "rules_run": rules_run,
        "rules_succeeded": rules_succeeded,
        "rules_failed": rules_failed,
        "rules_skipped": rules_skipped,
        "total_ms": t0.elapsed().as_millis() as u64,
        "results_dir": out_dir.display().to_string(),
        "results": all_results,
        "note": "Wave-X Soft-OPEN Timescale postgres-sql run-now; Soft-OPEN ≠ FQ",
    });
    std::fs::write(
        out_dir.join("_run_meta.json"),
        serde_json::to_vec_pretty(&meta)?,
    )?;
    Ok(meta)
}

pub async fn equipment_from_timescale(building_id: Option<&str>) -> Result<Value> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(json!({"ok": true, "count": 0, "equipment": [], "engine": TS_ENGINE}));
    };
    let tsdb = Tsdb::connect_from_env().await?;
    let rows = list_equipment(&tsdb, bid).await?;
    let equipment: Vec<Value> = rows
        .into_iter()
        .map(|(id, typ)| {
            json!({
                "equipment_id": id,
                "equipment_type": typ.clone().unwrap_or_else(|| "unclassified".into()),
                "equipment_type_raw": typ,
                "equipment_type_source": if typ.is_some() { "timescale_equipment" } else { "missing" },
            })
        })
        .collect();
    Ok(json!({
        "ok": true,
        "count": equipment.len(),
        "equipment": equipment,
        "engine": TS_ENGINE,
        "building_id": bid,
    }))
}

#[cfg(test)]
mod plot_role_tests {
    use super::*;

    fn assert_all_rules_have_plot_roles(reg: &RuleRegistry) -> Result<()> {
        if reg.rules.len() != 77 {
            return Err(anyhow!(
                "registry has {} rules; warehouse handoff requires exactly 77",
                reg.rules.len()
            ));
        }
        let mut empty = Vec::new();
        for rule in &reg.rules {
            if catalog_plot_roles(rule).is_empty() {
                empty.push(rule.rule_id.clone());
            }
        }
        if !empty.is_empty() {
            return Err(anyhow!(
                "catalog rules missing plot roles: {}",
                empty.join(", ")
            ));
        }
        Ok(())
    }

    #[test]
    fn all_77_catalog_rules_have_plot_roles() {
        let reg = load_reg().expect("load sql/fdd registry");
        assert_all_rules_have_plot_roles(&reg).expect("77 plot roles");
    }

    #[test]
    fn oat_meteo_roles_exclude_duct_static() {
        let reg = load_reg().expect("registry");
        let rule = reg
            .rules
            .iter()
            .find(|r| r.rule_id == "OAT-METEO")
            .expect("OAT-METEO");
        let roles = catalog_plot_roles(rule);
        assert!(
            !roles
                .iter()
                .any(|r| r.contains("duct") || r.contains("static")),
            "OAT-METEO roles={roles:?}"
        );
        assert!(
            roles.iter().any(|r| r.contains("oa") || r.contains("web")),
            "OAT-METEO should include OAT/web roles, got {roles:?}"
        );
    }

    #[test]
    fn clamp_max_points_bounds() {
        assert_eq!(clamp_max_points(None), 1500);
        assert_eq!(clamp_max_points(Some(10)), 50);
        assert_eq!(clamp_max_points(Some(99_999)), 5000);
    }
}
