//! Historian Parquet bridge for DataFusion analytics (Milestone D1).

use std::collections::{BTreeMap, HashSet};
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, run_sql};
use serde_json::{json, Value};

use super::{
    envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, DF_ENGINE, QV_ECONOMIZER,
    QV_MECHANICAL_COOLING, QV_RUNTIME, QV_SCHEDULE, QV_SENSOR_HEALTH,
};

/// Canonical numeric role columns that may appear as `history` columns after
/// ingest (see `fdd_core::columns::normalize_role`). `occ_mode` is Utf8 and is
/// handled separately by the schedule path.
const NUMERIC_ROLE_COLS: &[&str] = &[
    "oa_t",
    "rat",
    "mat",
    "sat",
    "zone_t",
    "fan_cmd",
    "fan_status",
    "oa_damper_pct",
    "clg_valve_pct",
    "htg_valve_pct",
    "sat_sp",
    "duct_static",
    "duct_static_sp",
    "chw_supply_t",
    "chw_return_t",
    "hw_supply_t",
    "hw_return_t",
    "oa_h",
    "return_fan",
];

/// Resolve Parquet historian root — same env fallbacks as edge FDD registry.
pub fn parquet_root() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_PARQUET_ROOT") {
        return PathBuf::from(p);
    }
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        let under_ws = PathBuf::from(&ws).join(".cache/parquet");
        if under_ws.is_dir() || PathBuf::from(&ws).is_dir() {
            return under_ws;
        }
    }
    for c in [
        PathBuf::from(".cache/parquet"),
        PathBuf::from("/var/openfdd/workspace/.cache/parquet"),
        PathBuf::from("workspace/.cache/parquet"),
    ] {
        if c.is_dir() {
            return c;
        }
    }
    PathBuf::from(".cache/parquet")
}

/// Sanitize a `building_id` for use as a Hive path segment. Rejects any value
/// with path separators or `..` so a query field can never escape the parquet
/// root; returns `None` for empty/unsafe ids (caller falls back to whole tree).
fn safe_building_segment(building_id: Option<&str>) -> Option<String> {
    let bid = building_id.map(str::trim).filter(|s| !s.is_empty())?;
    if bid.contains('/') || bid.contains('\\') || bid.contains("..") || bid.contains('\0') {
        return None;
    }
    Some(bid.to_string())
}

/// Register `history` for an optional `building_id` scope (OFDD-070).
///
/// When `building_id` is set and `building={id}/` exists under the parquet root,
/// only that site's parquet is registered (mirrors the edge FDD registry Hive
/// layout `building={id}/equipment={eq}/history.parquet`). Otherwise the whole
/// tree is registered. Returns `Ok(false)` when nothing usable is present.
pub async fn try_register_history_scoped(
    ctx: &SessionContext,
    building_id: Option<&str>,
) -> Result<bool> {
    let root = parquet_root();
    if !root.is_dir() {
        return Ok(false);
    }
    let scoped = match safe_building_segment(building_id) {
        Some(bid) => {
            let dir = root.join(format!("building={bid}"));
            if dir.is_dir() {
                Some(dir)
            } else {
                // Requested site has no parquet yet — do not silently fall back to
                // the whole tree (that would mix other buildings into the scope).
                tracing::debug!(building = %bid, "no building-scoped parquet; historian scope empty");
                return Ok(false);
            }
        }
        None => None,
    };
    let target = scoped.as_deref().unwrap_or(&root);
    match register_parquet_tree(ctx, target).await {
        Ok(_) => Ok(true),
        Err(e) => {
            tracing::debug!(error = %e, root = %target.display(), "historian parquet register skipped");
            Ok(false)
        }
    }
}

async fn history_columns_async(ctx: &SessionContext) -> Result<HashSet<String>> {
    let df = ctx
        .table("history")
        .await
        .map_err(|e| anyhow!("history table: {e}"))?;
    Ok(df
        .schema()
        .fields()
        .iter()
        .map(|f| f.name().to_string())
        .collect())
}

fn pick_ts_col(cols: &HashSet<String>) -> Option<&'static str> {
    ["timestamp_utc", "ts", "timestamp"]
        .into_iter()
        .find(|&c| cols.contains(c))
}

/// Boolean on-expression preferring fan_status, then fan_cmd (normalized > 0.05).
fn on_expr(cols: &HashSet<String>) -> Option<String> {
    let has_status = cols.contains("fan_status");
    let has_cmd = cols.contains("fan_cmd");
    if has_status && has_cmd {
        Some(
            "CASE \
               WHEN fan_status IS NOT NULL THEN \
                 CASE WHEN fan_status > 0.05 THEN true ELSE false END \
               WHEN fan_cmd IS NOT NULL THEN \
                 CASE WHEN (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.05 \
                   THEN true ELSE false END \
               ELSE false \
             END"
            .into(),
        )
    } else if has_status {
        Some(
            "CASE WHEN fan_status IS NOT NULL AND fan_status > 0.05 THEN true ELSE false END"
                .into(),
        )
    } else if has_cmd {
        Some(
            "CASE WHEN fan_cmd IS NOT NULL AND \
               (CASE WHEN fan_cmd > 1.0 THEN fan_cmd / 100.0 ELSE fan_cmd END) > 0.05 \
             THEN true ELSE false END"
                .into(),
        )
    } else {
        None
    }
}

/// Threshold on-expression for a single numeric status/amp column.
fn col_on_gt(col: &str, threshold: f64) -> String {
    format!("CASE WHEN {col} IS NOT NULL AND {col} > {threshold} THEN true ELSE false END")
}

/// Mechanical-cooling proof (never fan). Prefers chiller/compressor status, then amps.
fn cooling_on_expr(cols: &HashSet<String>) -> Option<String> {
    let status_names = [
        "chiller_status",
        "compressor_status",
        "comp_status",
        "comp_1_status",
        "comp_2_status",
        "dx_status",
    ];
    let mut parts: Vec<String> = Vec::new();
    for name in status_names {
        if cols.contains(name) {
            parts.push(col_on_gt(name, 0.05));
        }
    }
    // Any remaining column name that clearly looks like chiller/compressor status.
    for c in cols {
        let u = c.to_ascii_lowercase();
        if parts.iter().any(|p| p.contains(c.as_str())) {
            continue;
        }
        if (u.contains("chiller") && u.contains("status"))
            || (u.contains("comp") && u.contains("status") && !u.contains("occup"))
            || (u.contains("dx") && u.contains("status"))
        {
            parts.push(col_on_gt(c, 0.05));
        }
    }
    for name in ["chiller_amps", "comp_amps", "compressor_amps", "amps"] {
        if cols.contains(name) {
            parts.push(col_on_gt(name, 2.0));
        }
    }
    if parts.is_empty() {
        return None;
    }
    if parts.len() == 1 {
        return Some(parts.remove(0));
    }
    Some(format!("({})", parts.join(" OR ")))
}

/// Plant weekly / equipment runtime on-proof: fan OR chiller/boiler/pump status.
fn plant_runtime_on_expr(cols: &HashSet<String>) -> Option<String> {
    let mut parts: Vec<String> = Vec::new();
    if let Some(fan) = on_expr(cols) {
        parts.push(format!("({fan})"));
    }
    if let Some(cool) = cooling_on_expr(cols) {
        parts.push(format!("({cool})"));
    }
    for name in [
        "boiler_status",
        "boiler_cmd",
        "hwp_status",
        "hw_pump_status",
        "cwp_status",
    ] {
        if cols.contains(name) {
            parts.push(format!("({})", col_on_gt(name, 0.05)));
        }
    }
    for c in cols {
        let u = c.to_ascii_lowercase();
        if (u.contains("boiler") && u.contains("status"))
            || (u.contains("hwp") && (u.contains("status") || u.contains("_s")))
            || (u.contains("cwp") && u.contains("status"))
            || (u.contains("pump") && u.contains("status"))
        {
            let expr = col_on_gt(c, 0.05);
            if !parts.iter().any(|p| p.contains(c.as_str())) {
                parts.push(format!("({expr})"));
            }
        }
    }
    if parts.is_empty() {
        return None;
    }
    if parts.len() == 1 {
        return Some(parts.remove(0));
    }
    Some(parts.join(" OR "))
}

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

/// Map equipment_id → Overview plant chart group (air / boiler / chiller).
/// VAVs and unknown meters return `None` (excluded from plant weekly charts).
pub fn plant_group_for(equipment_id: &str) -> Option<&'static str> {
    let eq = equipment_id.to_ascii_uppercase().replace('\\', "/");
    if eq.contains("/VAV") || eq.starts_with("VAV") || eq.contains("VAVFC") || eq.contains("VAVH") {
        return None;
    }
    if eq.starts_with("AHU")
        || eq.contains("/AHU")
        || eq.contains("RTU")
        || eq.contains("MAU")
        || eq.contains("DOAS")
    {
        return Some("air");
    }
    if eq.contains("TOWER")
        || eq.starts_with("CT_")
        || eq.contains("/CT")
        || (eq.starts_with("CT") && eq.chars().nth(2).is_some_and(|c| c.is_ascii_digit()))
        || eq.contains("CHILLER")
        || eq.starts_with("CHW")
        || eq.contains("CWP")
        || eq.contains("_DX")
        || eq.starts_with("DX")
        || eq.starts_with("HP_")
        || (eq.contains("PUMP") && (eq.contains("CHW") || eq.contains("CW")))
    {
        return Some("chiller");
    }
    if eq.contains("BOILER")
        || eq.contains("HWP")
        || (eq.contains("PUMP") && eq.contains("HW") && !eq.contains("CHW"))
        || eq.contains("BOILERS")
    {
        return Some("boiler");
    }
    // Do not catch bare FAN/SUPPLY — too broad (exhaust/return/etc.).
    None
}

/// OAT for mech-cooling bins: prefer web/meteo OAT (pandas Overview default).
fn mech_oat_col(cols: &HashSet<String>) -> Option<&'static str> {
    web_oat_col(cols).or_else(|| {
        if cols.contains("oa_t") {
            Some("oa_t")
        } else {
            None
        }
    })
}

fn oat_col(cols: &HashSet<String>) -> Option<&'static str> {
    if cols.contains("oa_t") {
        Some("oa_t")
    } else if cols.contains("web_oa_t") {
        Some("web_oa_t")
    } else {
        None
    }
}

fn web_oat_col(cols: &HashSet<String>) -> Option<&'static str> {
    ["web_oa_t", "oa_t_web", "oat_meteo", "oa_t_meteo"]
        .into_iter()
        .find(|&c| cols.contains(c))
}

fn equipment_filter_sql(equipment_filter: Option<&[String]>) -> String {
    match equipment_filter {
        Some(ids) if !ids.is_empty() => {
            let list = ids
                .iter()
                .map(|id| format!("'{}'", id.replace('\'', "''")))
                .collect::<Vec<_>>()
                .join(", ");
            format!(" AND equipment_id IN ({list})")
        }
        _ => String::new(),
    }
}

/// SQL fragment restricting to chiller/DX/tower-like equipment ids.
/// Kept aligned with [`plant_group_for`] (no bare `CT%` — that matches CTRL_*).
fn chiller_like_equipment_sql() -> &'static str {
    " AND (\
        UPPER(equipment_id) LIKE '%CHILLER%' \
        OR UPPER(equipment_id) LIKE '%TOWER%' \
        OR UPPER(equipment_id) LIKE 'CT_%' \
        OR UPPER(equipment_id) LIKE '%/CT_%' \
        OR UPPER(equipment_id) LIKE '%_DX%' \
        OR UPPER(equipment_id) LIKE 'DX%' \
        OR UPPER(equipment_id) LIKE 'HP_%' \
        OR UPPER(equipment_id) LIKE '%CWP%' \
        OR UPPER(equipment_id) LIKE 'CHW%' \
     )"
}

/// Load runtime hours from historian Parquet via DataFusion.
///
/// Returns `Ok(None)` when parquet is missing/empty. When columns support Δt
/// integration (`equipment_id`, timestamp, fan/status/pump proofs), computes real
/// forward-interval run hours with gap clipping. Otherwise returns a count-based
/// envelope with `engine=datafusion` and a warning that column-mapped runtime is next.
///
/// When `building_id` is set, scopes the Parquet read like economizer (OFDD-070).
pub async fn runtime_from_history(
    equipment_filter: Option<&[String]>,
    max_gap_seconds: f64,
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let ctx = SessionContext::new();
    if !try_register_history_scoped(&ctx, building_id).await? {
        return Ok(None);
    }

    let count = run_sql(&ctx, "SELECT COUNT(*) AS n FROM history").await?;
    let n = count
        .rows
        .first()
        .and_then(|r| r.get("n"))
        .and_then(|v| v.as_i64().or_else(|| v.as_f64().map(|f| f as i64)))
        .unwrap_or(0);
    if n <= 0 {
        return Ok(None);
    }

    let cols = history_columns_async(&ctx).await?;
    let query = AnalyticsQuery::default();
    let max_gap = max_gap_seconds.max(0.0);
    let eq_filter = equipment_filter_sql(equipment_filter);

    if cols.contains("equipment_id") {
        // Fan for air handlers; chiller/boiler/pump status for plant motors.
        if let (Some(ts_col), Some(on_sql)) = (pick_ts_col(&cols), plant_runtime_on_expr(&cols)) {
            let sql = format!(
                r#"
WITH ordered AS (
  SELECT
    equipment_id,
    {ts_col} AS ts,
    {on_sql} AS is_on,
    LEAD({ts_col}) OVER (PARTITION BY equipment_id ORDER BY {ts_col}) AS next_ts
  FROM history
  WHERE equipment_id IS NOT NULL{eq_filter}
),
raw_intervals AS (
  SELECT
    equipment_id,
    is_on,
    (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 AS dt_raw
  FROM ordered
  WHERE next_ts IS NOT NULL
),
intervals AS (
  SELECT
    equipment_id,
    is_on,
    CASE
      WHEN dt_raw < 0.0 THEN 0.0
      WHEN dt_raw > {max_gap} THEN {max_gap}
      ELSE dt_raw
    END AS dt_sec
  FROM raw_intervals
),
spans AS (
  SELECT
    equipment_id,
    (CAST(MAX(ts) AS BIGINT) - CAST(MIN(ts) AS BIGINT)) / 1000000000.0 AS span_sec
  FROM ordered
  GROUP BY equipment_id
),
counts AS (
  SELECT
    equipment_id,
    COUNT(*) AS samples,
    SUM(CASE WHEN is_on THEN 1 ELSE 0 END) AS on_samples
  FROM ordered
  GROUP BY equipment_id
)
SELECT
  i.equipment_id,
  SUM(CASE WHEN i.is_on THEN i.dt_sec ELSE 0.0 END) / 3600.0 AS run_hours,
  CASE
    WHEN MAX(s.span_sec) > 0.0 THEN 100.0 * SUM(i.dt_sec) / MAX(s.span_sec)
    ELSE 0.0
  END AS coverage_pct,
  MAX(c.samples) AS samples,
  MAX(c.on_samples) AS on_samples
FROM intervals i
JOIN counts c ON c.equipment_id = i.equipment_id
JOIN spans s ON s.equipment_id = i.equipment_id
GROUP BY i.equipment_id
ORDER BY i.equipment_id
"#
            );

            match run_sql(&ctx, &sql).await {
                Ok(result) => {
                    let mut warnings = vec![
                        "runtime hours from historian Parquet via DataFusion Δt integration".into(),
                    ];
                    let mut equipment = Vec::new();
                    for row in &result.rows {
                        let eq = row
                            .get("equipment_id")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        let run_hours =
                            row.get("run_hours").and_then(|v| v.as_f64()).unwrap_or(0.0);
                        let coverage_pct = row
                            .get("coverage_pct")
                            .and_then(|v| v.as_f64())
                            .unwrap_or(0.0);
                        let samples = row
                            .get("samples")
                            .and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|i| i as u64)))
                            .unwrap_or(0);
                        let on_samples = row
                            .get("on_samples")
                            .and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|i| i as u64)))
                            .unwrap_or(0);
                        equipment.push(json!({
                            "equipment_id": eq,
                            "run_hours": round2(run_hours),
                            "coverage_pct": round2(coverage_pct),
                            "samples": samples,
                            "on_samples": on_samples,
                            "plant_group": plant_group_for(
                                row.get("equipment_id").and_then(|v| v.as_str()).unwrap_or("")
                            ),
                        }));
                    }
                    let weekly_rows = runtime_weekly_plant_rows(
                        &ctx,
                        ts_col,
                        &on_sql,
                        oat_col(&cols),
                        max_gap,
                        &eq_filter,
                    )
                    .await
                    .unwrap_or_else(|e| {
                        warnings.push(format!("weekly plant bins skipped: {e}"));
                        Vec::new()
                    });
                    if !weekly_rows.is_empty() {
                        warnings.push(
                            "rows include weekly plant_group bins (runtime-weekly-v1)".into(),
                        );
                    }
                    let mut env = envelope_with_engine(QV_RUNTIME, &query, warnings, DF_ENGINE);
                    env.equipment = equipment;
                    env.rows = if weekly_rows.is_empty() {
                        env.equipment.clone()
                    } else {
                        weekly_rows
                    };
                    env.coverage = Some(json!({
                        "equipment_count": env.equipment.len(),
                        "weekly_row_count": env.rows.len(),
                        "history_rows": n,
                        "max_gap_seconds": max_gap,
                        "source": "historian_parquet",
                        "building_id": safe_building_segment(building_id),
                        "query_versions": ["runtime-v1", "runtime-weekly-v1"],
                    }));
                    return Ok(Some(env));
                }
                Err(e) => {
                    tracing::warn!(error = %e, "historian Δt runtime SQL failed; falling back to count probe");
                }
            }
        }
    }

    // Minimum bridge: registered history with rows, engine honesty for DataFusion.
    let warnings = vec![
        "historian Parquet registered via DataFusion; column-mapped runtime Δt SQL is next \
         (need equipment_id + timestamp_utc + fan/chiller/boiler/pump on-proof)"
            .into(),
    ];
    let mut env = envelope_with_engine(QV_RUNTIME, &query, warnings, DF_ENGINE);
    env.coverage = Some(json!({
        "history_rows": n,
        "max_gap_seconds": max_gap,
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

/// Weekly plant-group run hours (Mon-start week labels) for Overview motor charts.
async fn runtime_weekly_plant_rows(
    ctx: &SessionContext,
    ts_col: &str,
    on_sql: &str,
    oat: Option<&str>,
    max_gap: f64,
    eq_filter: &str,
) -> Result<Vec<Value>> {
    let oat_sel = oat
        .map(|c| format!("{c} AS oat_f,"))
        .unwrap_or_else(|| "CAST(NULL AS FLOAT) AS oat_f,".into());
    let sql = format!(
        r#"
WITH ordered AS (
  SELECT
    equipment_id,
    {ts_col} AS ts,
    {on_sql} AS is_on,
    {oat_sel}
    LEAD({ts_col}) OVER (PARTITION BY equipment_id ORDER BY {ts_col}) AS next_ts
  FROM history
  WHERE equipment_id IS NOT NULL{eq_filter}
),
raw_intervals AS (
  SELECT
    equipment_id,
    is_on,
    oat_f,
    date_trunc('week', CAST(ts AS TIMESTAMP)) AS week_start,
    (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 AS dt_raw
  FROM ordered
  WHERE next_ts IS NOT NULL
),
intervals AS (
  SELECT
    equipment_id,
    is_on,
    oat_f,
    week_start,
    CASE
      WHEN dt_raw < 0.0 THEN 0.0
      WHEN dt_raw > {max_gap} THEN {max_gap}
      ELSE dt_raw
    END AS dt_sec
  FROM raw_intervals
)
SELECT
  equipment_id,
  CAST(week_start AS VARCHAR) AS week_label,
  SUM(CASE WHEN is_on THEN dt_sec ELSE 0.0 END) / 3600.0 AS run_hours,
  AVG(CASE WHEN is_on AND oat_f IS NOT NULL THEN oat_f ELSE NULL END) AS avg_oat_f
FROM intervals
GROUP BY equipment_id, week_start
ORDER BY week_start, equipment_id
"#
    );
    let result = run_sql(ctx, &sql).await?;
    // Aggregate equipment → plant_group per week.
    let mut agg: BTreeMap<(String, String), (f64, f64, u64)> = BTreeMap::new();
    for row in &result.rows {
        let eq = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let Some(plant) = plant_group_for(eq) else {
            continue;
        };
        let week = row
            .get("week_label")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .chars()
            .take(10)
            .collect::<String>();
        if week.is_empty() {
            continue;
        }
        let hours = row.get("run_hours").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let oat_v = row.get("avg_oat_f").and_then(|v| v.as_f64());
        let key = (plant.to_string(), week);
        let e = agg.entry(key).or_insert((0.0, 0.0, 0));
        e.0 += hours;
        if let Some(o) = oat_v {
            e.1 += o;
            e.2 += 1;
        }
    }
    let mut out = Vec::new();
    for ((plant, week), (hours, oat_sum, oat_n)) in agg {
        out.push(json!({
            "kind": "weekly_plant",
            "query_version": "runtime-weekly-v1",
            "plant_group": plant,
            "week_label": week,
            "run_hours": round2(hours),
            "avg_oat_f": if oat_n > 0 { Some(round2(oat_sum / oat_n as f64)) } else { None::<f64> },
        }));
    }
    out.sort_by(|a, b| {
        let wa = a.get("week_label").and_then(|v| v.as_str()).unwrap_or("");
        let wb = b.get("week_label").and_then(|v| v.as_str()).unwrap_or("");
        wa.cmp(wb).then_with(|| {
            let pa = a.get("plant_group").and_then(|v| v.as_str()).unwrap_or("");
            let pb = b.get("plant_group").and_then(|v| v.as_str()).unwrap_or("");
            pa.cmp(pb)
        })
    });
    Ok(out)
}

/// Register `history` and return `(ctx, columns, row_count)` when the parquet
/// tree exists and has rows; `Ok(None)` when missing/empty (caller falls back).
async fn open_history() -> Result<Option<(SessionContext, HashSet<String>, i64)>> {
    open_history_scoped(None).await
}

/// Like [`open_history`] but scoped to an optional `building_id` (OFDD-070).
async fn open_history_scoped(
    building_id: Option<&str>,
) -> Result<Option<(SessionContext, HashSet<String>, i64)>> {
    let ctx = SessionContext::new();
    if !try_register_history_scoped(&ctx, building_id).await? {
        return Ok(None);
    }
    let count = run_sql(&ctx, "SELECT COUNT(*) AS n FROM history").await?;
    let n = count
        .rows
        .first()
        .and_then(|r| r.get("n"))
        .and_then(|v| v.as_i64().or_else(|| v.as_f64().map(|f| f as i64)))
        .unwrap_or(0);
    if n <= 0 {
        return Ok(None);
    }
    let cols = history_columns_async(&ctx).await?;
    Ok(Some((ctx, cols, n)))
}

fn as_f64(v: Option<&serde_json::Value>) -> Option<f64> {
    v.and_then(|v| v.as_f64().or_else(|| v.as_i64().map(|i| i as f64)))
}

fn as_u64(v: Option<&serde_json::Value>) -> u64 {
    v.and_then(|v| v.as_u64().or_else(|| v.as_i64().map(|i| i as u64)))
        .unwrap_or(0)
}

/// Sensor health from historian Parquet via DataFusion aggregate SQL.
///
/// For each canonical numeric role column present in `history`, computes
/// per-`equipment_id` coverage, missingness, and flatline stats. Sets
/// `engine=datafusion` only when the aggregate SQL actually runs.
pub async fn sensor_health_from_history(
    equipment_filter: Option<&[String]>,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history().await? else {
        return Ok(None);
    };

    let role_cols: Vec<&str> = NUMERIC_ROLE_COLS
        .iter()
        .copied()
        .filter(|c| cols.contains(*c))
        .collect();
    if role_cols.is_empty() {
        // No usable numeric role columns — let inline/central path handle it.
        return Ok(None);
    }

    let eq_filter = equipment_filter_sql(equipment_filter);
    let selects: Vec<String> = role_cols
        .iter()
        .map(|role| {
            format!(
                "SELECT equipment_id AS equipment_id, '{role}' AS role, \
                   COUNT(*) AS n, COUNT({role}) AS n_finite, \
                   MIN({role}) AS minv, MAX({role}) AS maxv, \
                   AVG({role}) AS meanv, STDDEV_POP({role}) AS stdv \
                 FROM history \
                 WHERE equipment_id IS NOT NULL{eq_filter} \
                 GROUP BY equipment_id"
            )
        })
        .collect();
    let sql = format!(
        "{} ORDER BY equipment_id, role",
        selects.join(" UNION ALL ")
    );

    let result = run_sql(&ctx, &sql).await?;
    let min_n = super::sensor_health::DEFAULT_FLATLINE_MIN_N as u64;
    let eps = super::sensor_health::DEFAULT_FLATLINE_STD_EPS;

    let mut rows = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        let n_all = as_u64(r.get("n"));
        let n_finite = as_u64(r.get("n_finite"));
        if n_finite == 0 {
            // Drop role columns that never applied to this equipment.
            continue;
        }
        let coverage_pct = if n_all > 0 {
            100.0 * n_finite as f64 / n_all as f64
        } else {
            0.0
        };
        let missingness = if n_all > 0 {
            1.0 - (n_finite as f64 / n_all as f64)
        } else {
            0.0
        };
        let std = as_f64(r.get("stdv"));
        let flatline_flag = n_finite > min_n && std.map(|s| s <= eps).unwrap_or(false);
        let mut obj = json!({
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "role": r.get("role").cloned().unwrap_or(json!("")),
            "n": n_all,
            "n_finite": n_finite,
            "coverage_pct": round2(coverage_pct),
            "missingness": round4(missingness),
            "flatline_flag": flatline_flag,
        });
        if let Some(v) = as_f64(r.get("minv")) {
            obj["min"] = json!(round4(v));
        }
        if let Some(v) = as_f64(r.get("maxv")) {
            obj["max"] = json!(round4(v));
        }
        if let Some(v) = as_f64(r.get("meanv")) {
            obj["mean"] = json!(round4(v));
        }
        if let Some(v) = std {
            obj["std"] = json!(round6(v));
        }
        rows.push(obj);
    }

    let warnings = vec![
        "sensor_health from historian Parquet via DataFusion aggregate SQL \
         (coverage / missingness / flatline over canonical numeric roles)"
            .into(),
    ];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine(QV_SENSOR_HEALTH, &query, warnings, DF_ENGINE);
    env.rows = rows.clone();
    env.equipment = rows;
    env.coverage = Some(json!({
        "series_count": env.rows.len(),
        "history_rows": n,
        "roles": role_cols,
        "source": "historian_parquet",
    }));
    Ok(Some(env))
}

/// Boolean occupied-expression from `occ_mode` (Utf8). Unoccupied labels map to
/// false; any other non-null value is treated as occupied.
fn occupied_expr() -> &'static str {
    "CASE \
       WHEN occ_mode IS NULL THEN NULL \
       WHEN LOWER(CAST(occ_mode AS VARCHAR)) IN \
         ('unoccupied','unocc','off','0','false','night','standby','setback') THEN false \
       ELSE true \
     END"
}

/// Schedule occupied / unoccupied hours from historian Parquet via DataFusion
/// Δt integration over the `occ_mode` mask. Returns `Ok(None)` when no
/// `occ_mode` column exists (caller keeps inline central-analytics-v1).
pub async fn schedule_from_history(
    equipment_filter: Option<&[String]>,
    max_gap_seconds: f64,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history().await? else {
        return Ok(None);
    };
    if !cols.contains("occ_mode") {
        return Ok(None);
    }
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    let max_gap = max_gap_seconds.max(0.0);
    let eq_filter = equipment_filter_sql(equipment_filter);
    let occ_sql = occupied_expr();

    let sql = format!(
        r#"
WITH ordered AS (
  SELECT
    equipment_id,
    {ts_col} AS ts,
    {occ_sql} AS occ,
    LEAD({ts_col}) OVER (PARTITION BY equipment_id ORDER BY {ts_col}) AS next_ts
  FROM history
  WHERE equipment_id IS NOT NULL AND occ_mode IS NOT NULL{eq_filter}
),
intervals AS (
  SELECT
    equipment_id,
    occ,
    CASE
      WHEN (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 < 0.0 THEN 0.0
      WHEN (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 > {max_gap} THEN {max_gap}
      ELSE (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0
    END AS dt_sec
  FROM ordered
  WHERE next_ts IS NOT NULL
)
SELECT
  equipment_id,
  SUM(CASE WHEN occ THEN dt_sec ELSE 0.0 END) / 3600.0 AS occupied_hours,
  SUM(CASE WHEN occ THEN 0.0 ELSE dt_sec END) / 3600.0 AS unoccupied_hours,
  SUM(dt_sec) / 3600.0 AS coverage_hours,
  SUM(CASE WHEN occ THEN 1 ELSE 0 END) AS occupied_samples,
  COUNT(*) AS total_samples
FROM intervals
GROUP BY equipment_id
ORDER BY equipment_id
"#
    );

    let result = run_sql(&ctx, &sql).await?;
    let mut rows = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        rows.push(json!({
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "occupied_hours": round4(as_f64(r.get("occupied_hours")).unwrap_or(0.0)),
            "unoccupied_hours": round4(as_f64(r.get("unoccupied_hours")).unwrap_or(0.0)),
            "coverage_hours": round4(as_f64(r.get("coverage_hours")).unwrap_or(0.0)),
            "occupied_samples": as_u64(r.get("occupied_samples")),
            "total_samples": as_u64(r.get("total_samples")),
        }));
    }

    let warnings = vec![
        "schedule occupied/unoccupied hours from historian Parquet via DataFusion \
         Δt integration over occ_mode; after-hours fan overlay is inline-only"
            .into(),
    ];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine(QV_SCHEDULE, &query, warnings, DF_ENGINE);
    env.rows = rows.clone();
    env.equipment = rows;
    env.coverage = Some(json!({
        "equipment_count": env.equipment.len(),
        "history_rows": n,
        "max_gap_seconds": max_gap,
        "source": "historian_parquet",
    }));
    Ok(Some(env))
}

/// Economizer diagnostics from historian Parquet via DataFusion.
///
/// Requires an OAT column (`oa_t` or Liberty `web_oa_t`), plus `rat` and `mat`,
/// and a fan on-expression. Returns per-equipment fan-on / identifiable counts
/// plus downsampled fan-on points for Overview Plotly (delta scatter, MAT
/// residual, temps+damper overlay) — vibe19 chart parity without pandas.
pub async fn economizer_from_history(
    equipment_filter: Option<&[String]>,
    dt_min_f: f64,
    building_id: Option<&str>,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    // OFDD-070 / ENH-OFDD-001: Liberty packages expose web_oa_t (not oa_t).
    let oat_col = if cols.contains("oa_t") {
        "oa_t"
    } else if cols.contains("web_oa_t") {
        "web_oa_t"
    } else {
        return Ok(None);
    };
    let rat_col = if cols.contains("rat") {
        "rat"
    } else if cols.contains("web_ra_t") {
        "web_ra_t"
    } else {
        return Ok(None);
    };
    let mat_col = if cols.contains("mat") {
        "mat"
    } else if cols.contains("web_mat") || cols.contains("web_ma_t") {
        if cols.contains("web_mat") {
            "web_mat"
        } else {
            "web_ma_t"
        }
    } else {
        return Ok(None);
    };
    let Some(on_sql) = on_expr(&cols) else {
        return Ok(None);
    };
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    let dt_min = dt_min_f.max(0.0);
    let eq_filter = equipment_filter_sql(equipment_filter);
    let damper_proj = if cols.contains("oa_damper_pct") {
        "oa_damper_pct"
    } else {
        "CAST(NULL AS DOUBLE) AS oa_damper_pct"
    };
    let sat_proj = if cols.contains("sat") {
        "sat"
    } else {
        "CAST(NULL AS DOUBLE) AS sat"
    };

    let sql = format!(
        r#"
WITH base AS (
  SELECT
    equipment_id,
    {oat_col} AS oa_t,
    {rat_col} AS rat,
    {mat_col} AS mat,
    {on_sql} AS fan_on,
    {damper_proj},
    {sat_proj}
  FROM history
  WHERE equipment_id IS NOT NULL{eq_filter}
)
SELECT
  equipment_id,
  SUM(CASE WHEN fan_on THEN 1 ELSE 0 END) AS n_fan_on,
  SUM(CASE WHEN fan_on AND oa_t IS NOT NULL AND rat IS NOT NULL
             AND ABS(oa_t - rat) >= {dt_min} THEN 1 ELSE 0 END) AS n_identifiable,
  COUNT(oa_damper_pct) AS n_damper
FROM base
GROUP BY equipment_id
ORDER BY equipment_id
"#
    );

    let result = run_sql(&ctx, &sql).await?;
    let mut equipment = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        let n_fan_on = as_u64(r.get("n_fan_on"));
        if n_fan_on == 0 {
            continue;
        }
        equipment.push(json!({
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "equipment_type": "AHU",
            "n_fan_on_samples": n_fan_on,
            "n_identifiable": as_u64(r.get("n_identifiable")),
            "has_damper": as_u64(r.get("n_damper")) > 0,
            "dt_min_f": dt_min,
        }));
    }

    let limit = max_points.clamp(100, 8000);
    let points_sql = format!(
        r#"
WITH base AS (
  SELECT
    equipment_id,
    CAST({ts_col} AS VARCHAR) AS timestamp_utc,
    {oat_col} AS oat_f,
    {rat_col} AS rat_f,
    {mat_col} AS mat_f,
    {sat_proj},
    {damper_proj},
    {on_sql} AS fan_on
  FROM history
  WHERE equipment_id IS NOT NULL{eq_filter}
)
SELECT
  equipment_id,
  timestamp_utc,
  oat_f,
  rat_f,
  mat_f,
  sat AS sat_f,
  oa_damper_pct AS damper_fb_pct,
  (oat_f - rat_f) AS delta_or_f,
  (mat_f - rat_f) AS delta_mr_f,
  CASE
    WHEN oa_damper_pct IS NOT NULL AND oat_f IS NOT NULL AND rat_f IS NOT NULL THEN
      mat_f - (rat_f + (oa_damper_pct / 100.0) * (oat_f - rat_f))
    ELSE NULL
  END AS mat_resid_f,
  CASE
    WHEN oat_f IS NOT NULL AND rat_f IS NOT NULL AND ABS(oat_f - rat_f) >= {dt_min}
    THEN true ELSE false
  END AS identifiable
FROM base
WHERE fan_on
  AND oat_f IS NOT NULL AND rat_f IS NOT NULL AND mat_f IS NOT NULL
ORDER BY timestamp_utc
LIMIT {limit}
"#
    );
    let mut points = Vec::new();
    match run_sql(&ctx, &points_sql).await {
        Ok(pres) => {
            for r in &pres.rows {
                points.push(json!({
                    "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
                    "timestamp_utc": r.get("timestamp_utc").cloned().unwrap_or(json!("")),
                    "oat_f": as_f64(r.get("oat_f")),
                    "rat_f": as_f64(r.get("rat_f")),
                    "mat_f": as_f64(r.get("mat_f")),
                    "sat_f": as_f64(r.get("sat_f")),
                    "damper_fb_pct": as_f64(r.get("damper_fb_pct")),
                    "delta_or_f": as_f64(r.get("delta_or_f")),
                    "delta_mr_f": as_f64(r.get("delta_mr_f")),
                    "mat_resid_f": as_f64(r.get("mat_resid_f")),
                    "identifiable": r.get("identifiable").and_then(|v| v.as_bool()).unwrap_or(false),
                    "fan_on": true,
                }));
            }
        }
        Err(e) => {
            tracing::warn!(error = %e, "economizer plot points SQL failed; counts only");
        }
    }

    let mut warnings = vec![
        "economizer fan-on counts + free-cooling plot points from historian DataFusion \
         (vibe19 Overview chart parity)"
            .into(),
    ];
    if points.is_empty() {
        warnings.push("no fan-on economizer points available for scatter/MAT/temps plots".into());
    }
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine(QV_ECONOMIZER, &query, warnings, DF_ENGINE);
    env.equipment = equipment.clone();
    env.rows = equipment;
    env.points = points;
    env.coverage = Some(json!({
        "equipment_count": env.equipment.len(),
        "point_count": env.points.len(),
        "history_rows": n,
        "dt_min_f": dt_min,
        "max_points": limit,
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
        "oat_column": oat_col,
        "rat_column": rat_col,
        "mat_column": mat_col,
    }));
    Ok(Some(env))
}

/// Mechanical-cooling OAT bin hours (5°F bins) from historian when OAT + cooling
/// proof exist. Never uses AHU fan as mechanical cooling.
pub async fn mech_oat_bins_from_history(
    equipment_filter: Option<&[String]>,
    max_gap_seconds: f64,
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    let Some(oat) = mech_oat_col(&cols) else {
        return Ok(None);
    };
    // Require compressor/chiller proof — never fan_status/fan_cmd.
    let Some(on_sql) = cooling_on_expr(&cols) else {
        return Ok(None);
    };
    let max_gap = max_gap_seconds.max(0.0);
    let eq_filter = equipment_filter_sql(equipment_filter);
    let chiller_filter = chiller_like_equipment_sql();
    let sql = format!(
        r#"
WITH ordered AS (
  SELECT
    equipment_id,
    {ts_col} AS ts,
    {on_sql} AS is_on,
    {oat} AS oat_f,
    LEAD({ts_col}) OVER (PARTITION BY equipment_id ORDER BY {ts_col}) AS next_ts
  FROM history
  WHERE equipment_id IS NOT NULL AND {oat} IS NOT NULL{eq_filter}{chiller_filter}
),
intervals AS (
  SELECT
    equipment_id,
    is_on,
    oat_f,
    CASE
      WHEN (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 < 0.0 THEN 0.0
      WHEN (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 > {max_gap} THEN {max_gap}
      ELSE (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0
    END AS dt_sec
  FROM ordered
  WHERE next_ts IS NOT NULL AND is_on
)
SELECT
  FLOOR(oat_f / 5.0) * 5.0 AS bin_lo,
  SUM(dt_sec) / 3600.0 AS hours
FROM intervals
GROUP BY FLOOR(oat_f / 5.0) * 5.0
ORDER BY bin_lo
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    let mut rows = Vec::new();
    for r in &result.rows {
        let lo = as_f64(r.get("bin_lo")).unwrap_or(0.0);
        let hours = as_f64(r.get("hours")).unwrap_or(0.0);
        rows.push(json!({
            "kind": "oat_bin",
            "query_version": "mechanical-cooling-oat-bins-v1",
            "bin_lo_f": round2(lo),
            "bin_hi_f": round2(lo + 5.0),
            "bin_label": format!("{:.0}-{:.0}", lo, lo + 5.0),
            "hours": round2(hours),
        }));
    }
    if rows.is_empty() {
        return Ok(None);
    }
    let warnings = vec!["mechanical cooling OAT bins from historian DataFusion \
         (compressor/chiller proof × preferred web OAT; chiller-like equipment only)"
        .into()];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine(QV_MECHANICAL_COOLING, &query, warnings, DF_ENGINE);
    env.rows = rows.clone();
    env.equipment = rows;
    env.coverage = Some(json!({
        "bin_count": env.rows.len(),
        "history_rows": n,
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
        "oat_column": oat,
    }));
    Ok(Some(env))
}

/// BAS oa_t vs web OAT overlay samples + deviation histogram rows.
pub async fn bas_vs_web_from_history(
    equipment_filter: Option<&[String]>,
    max_points: usize,
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    let Some(bas) = (if cols.contains("oa_t") {
        Some("oa_t")
    } else {
        None
    }) else {
        return Ok(None);
    };
    let Some(web) = web_oat_col(&cols) else {
        return Ok(None);
    };
    if bas == web {
        // Only one OAT column — cannot compare BAS vs web.
        return Ok(None);
    }
    let eq_filter = equipment_filter_sql(equipment_filter);
    let limit = max_points.clamp(100, 5000);
    let sql = format!(
        r#"
SELECT
  CAST({ts_col} AS VARCHAR) AS timestamp_utc,
  equipment_id,
  {bas} AS bas_oat_f,
  {web} AS web_oat_f,
  ({bas} - {web}) AS delta_f
FROM history
WHERE equipment_id IS NOT NULL
  AND {bas} IS NOT NULL AND {web} IS NOT NULL{eq_filter}
ORDER BY {ts_col}
LIMIT {limit}
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    if result.rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    let mut hist: BTreeMap<i64, f64> = BTreeMap::new();
    for r in &result.rows {
        let delta = as_f64(r.get("delta_f")).unwrap_or(0.0);
        points.push(json!({
            "timestamp_utc": r.get("timestamp_utc").cloned().unwrap_or(json!("")),
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "bas_oat_f": as_f64(r.get("bas_oat_f")),
            "web_oat_f": as_f64(r.get("web_oat_f")),
            "delta_f": round2(delta),
        }));
        let bin = (delta / 1.0).floor() as i64;
        *hist.entry(bin).or_insert(0.0) += 1.0;
    }
    let rows: Vec<Value> = hist
        .into_iter()
        .map(|(bin, count)| {
            json!({
                "kind": "delta_hist",
                "bin_lo_f": bin as f64,
                "bin_hi_f": (bin + 1) as f64,
                "count": count,
            })
        })
        .collect();
    let warnings = vec!["BAS vs web OAT from historian DataFusion (oa_t vs web OAT column)".into()];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("bas-vs-web-oat-v1", &query, warnings, DF_ENGINE);
    env.points = points;
    env.rows = rows;
    env.coverage = Some(json!({
        "point_count": env.points.len(),
        "hist_bins": env.rows.len(),
        "history_rows": n,
        "bas_column": bas,
        "web_column": web,
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

/// Generic descriptive per-equipment row-count evidence from historian Parquet
/// via DataFusion. Used by families (mechanical_cooling, metering, rcx/*, plant)
/// that do not yet have a family-specific DF metric. Honest: sets
/// `engine=datafusion` only because a real `GROUP BY` count ran, and never
/// invents engineering values (kW/ton, tons, etc.).
pub async fn descriptive_counts_from_history(
    query_version: &str,
    equipment_filter: Option<&[String]>,
    note: &str,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, _cols, n)) = open_history().await? else {
        return Ok(None);
    };
    let eq_filter = equipment_filter_sql(equipment_filter);
    let sql = format!(
        "SELECT equipment_id, COUNT(*) AS history_rows FROM history \
         WHERE equipment_id IS NOT NULL{eq_filter} \
         GROUP BY equipment_id ORDER BY equipment_id"
    );
    let result = run_sql(&ctx, &sql).await?;
    let mut rows = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        rows.push(json!({
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "history_rows": as_u64(r.get("history_rows")),
            "evidence_class": "descriptive_historian_counts",
        }));
    }

    let warnings = vec![format!(
        "{note} — descriptive historian row-count evidence via DataFusion only; \
         family-specific engineering metrics are not fabricated"
    )];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine(query_version, &query, warnings, DF_ENGINE);
    env.rows = rows.clone();
    env.equipment = rows;
    env.coverage = Some(json!({
        "equipment_count": env.equipment.len(),
        "history_rows": n,
        "source": "historian_parquet",
    }));
    Ok(Some(env))
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

fn round6(x: f64) -> f64 {
    (x * 1_000_000.0).round() / 1_000_000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tokio::sync::Mutex;

    /// Serializes tests that mutate the process-global `OPENFDD_PARQUET_ROOT`.
    /// Async-aware so the guard may be held across `.await` (clippy-clean).
    static ENV_LOCK: Mutex<()> = Mutex::const_new(());

    #[tokio::test]
    async fn runtime_from_history_none_when_no_parquet() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let missing = tmp.path().join("no_such_parquet");
        std::env::set_var("OPENFDD_PARQUET_ROOT", &missing);
        let out = runtime_from_history(None, 900.0, None).await.unwrap();
        assert!(out.is_none());
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
    }

    #[tokio::test]
    async fn runtime_from_history_sets_datafusion_engine() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_TEST");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nfan_speed_pct,fan_cmd\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,fan_speed_pct").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,100").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,100").unwrap();
        writeln!(f, "2026-01-01T00:10:00Z,0").unwrap();

        let parquet = tmp.path().join("parquet");
        fdd_store::ingest_building(tmp.path(), "BUILDING_TEST", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = runtime_from_history(None, 900.0, None)
            .await
            .unwrap()
            .expect("expected historian envelope");
        assert_eq!(env.engine, DF_ENGINE);
        assert_eq!(env.query_version, QV_RUNTIME);
        assert!(!env.equipment.is_empty());
        let hours = env.equipment[0]["run_hours"].as_f64().unwrap();
        // Two on intervals of 300s → 600s = 1/6 h
        assert!((hours - (600.0 / 3600.0)).abs() < 0.02, "hours={hours}");
        let cov = env.equipment[0]["coverage_pct"].as_f64().unwrap();
        assert!((cov - 100.0).abs() < 1.0, "coverage={cov}");

        std::env::remove_var("OPENFDD_PARQUET_ROOT");
    }

    #[tokio::test]
    async fn sensor_health_from_history_none_when_no_parquet() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let missing = tmp.path().join("no_such_parquet_sh");
        std::env::set_var("OPENFDD_PARQUET_ROOT", &missing);
        let out = sensor_health_from_history(None).await.unwrap();
        assert!(out.is_none());
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
    }

    #[tokio::test]
    async fn sensor_health_from_history_sets_datafusion_engine() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SH");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = building.join("AHU_SH1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nzone_temp_f,zone_temp\nmixed_air_temp_f,mixed_air_temp\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,zone_temp_f,mixed_air_temp_f").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,72.0,55.0").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,73.0,").unwrap();
        writeln!(f, "2026-01-01T00:10:00Z,74.0,57.0").unwrap();

        let parquet = tmp.path().join("parquet_sh");
        fdd_store::ingest_building(tmp.path(), "BUILDING_SH", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = sensor_health_from_history(None)
            .await
            .unwrap()
            .expect("expected sensor_health historian envelope");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        assert_eq!(env.engine, DF_ENGINE);
        assert_eq!(env.query_version, QV_SENSOR_HEALTH);
        assert!(!env.rows.is_empty());

        let zone = env
            .rows
            .iter()
            .find(|r| r["role"] == "zone_t")
            .expect("zone_t row present");
        assert_eq!(zone["n"].as_u64().unwrap(), 3);
        assert_eq!(zone["n_finite"].as_u64().unwrap(), 3);
        assert!((zone["coverage_pct"].as_f64().unwrap() - 100.0).abs() < 1e-6);

        let mat = env
            .rows
            .iter()
            .find(|r| r["role"] == "mat")
            .expect("mat row present");
        // One of three MAT samples is missing → coverage ~66.67%.
        assert_eq!(mat["n_finite"].as_u64().unwrap(), 2);
        assert!((mat["coverage_pct"].as_f64().unwrap() - 66.67).abs() < 0.1);
    }

    #[tokio::test]
    async fn descriptive_counts_from_history_sets_datafusion_engine() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_DC");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = building.join("AHU_DC1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nfan_speed_pct,fan_cmd\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,fan_speed_pct").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,100").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,0").unwrap();

        let parquet = tmp.path().join("parquet_dc");
        fdd_store::ingest_building(tmp.path(), "BUILDING_DC", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = descriptive_counts_from_history(
            crate::analytics::QV_METERING,
            None,
            "metering test note",
        )
        .await
        .unwrap()
        .expect("expected descriptive historian envelope");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        assert_eq!(env.engine, DF_ENGINE);
        assert_eq!(env.query_version, crate::analytics::QV_METERING);
        assert!(!env.rows.is_empty());
        assert_eq!(env.rows[0]["history_rows"].as_u64().unwrap(), 2);
        assert!(env.warnings.iter().any(|w| w.contains("not fabricated")));
    }

    #[tokio::test]
    async fn economizer_from_history_is_building_scoped() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let parquet = tmp.path().join("parquet_econ");

        // Two buildings with distinct AHU ids, each with oat/rat/mat + fan.
        for (bid, eq) in [("BUILDING_50", "AHU_B50"), ("BUILDING_100", "AHU_B100")] {
            let building = tmp.path().join(bid);
            let ahu = building.join(eq);
            std::fs::create_dir_all(&ahu).unwrap();
            std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
            std::fs::write(
                ahu.join("columns.csv"),
                "col,point_role\noat,outside_air_temp\nrat,return_air_temp\n\
                 mat,mixed_air_temp\nfan,fan_status\n",
            )
            .unwrap();
            let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
            writeln!(f, "timestamp_utc,oat,rat,mat,fan").unwrap();
            writeln!(f, "2026-01-01T00:00:00Z,40,70,55,1").unwrap();
            writeln!(f, "2026-01-01T00:05:00Z,41,70,56,1").unwrap();
            fdd_store::ingest_building(tmp.path(), bid, &parquet).unwrap();
        }
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let b50 = economizer_from_history(None, 10.0, Some("BUILDING_50"), 4000)
            .await
            .unwrap()
            .expect("B50 economizer envelope");
        let b100 = economizer_from_history(None, 10.0, Some("BUILDING_100"), 4000)
            .await
            .unwrap()
            .expect("B100 economizer envelope");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        // Each scope sees only its own AHU — no cross-building bleed.
        let ids_b50: Vec<String> = b50
            .equipment
            .iter()
            .filter_map(|e| e["equipment_id"].as_str().map(str::to_string))
            .collect();
        let ids_b100: Vec<String> = b100
            .equipment
            .iter()
            .filter_map(|e| e["equipment_id"].as_str().map(str::to_string))
            .collect();
        assert_eq!(ids_b50, vec!["AHU_B50".to_string()]);
        assert_eq!(ids_b100, vec!["AHU_B100".to_string()]);
        assert_eq!(
            b50.coverage.as_ref().unwrap()["building_id"],
            serde_json::json!("BUILDING_50")
        );
    }

    #[tokio::test]
    async fn economizer_from_history_with_damper_column_ok() {
        // OFDD-070b: oa_damper_pct present on history must not schema-error.
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let parquet = tmp.path().join("parquet_econ_damp");
        let building = tmp.path().join("BUILDING_50");
        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\noat,outside_air_temp\nrat,return_air_temp\n\
             mat,mixed_air_temp\nfan,fan_status\ndamp,oa_damper_pct\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,oat,rat,mat,fan,damp").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,40,70,55,1,0.4").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,41,70,56,1,0.5").unwrap();
        fdd_store::ingest_building(tmp.path(), "BUILDING_50", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = economizer_from_history(None, 10.0, Some("BUILDING_50"), 4000)
            .await
            .unwrap()
            .expect("economizer with damper");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        assert_eq!(env.engine, DF_ENGINE);
        assert!(!env.equipment.is_empty());
        assert!(env.equipment[0]["has_damper"].as_bool().unwrap_or(false));
        assert!(!env
            .warnings
            .iter()
            .any(|w| w.contains("historian/job economizer load is next")));
    }

    #[tokio::test]
    async fn economizer_from_history_none_for_unknown_building() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let parquet = tmp.path().join("parquet_econ_missing");
        let building = tmp.path().join("BUILDING_50");
        let ahu = building.join("AHU_B50");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\noat,outside_air_temp\nrat,return_air_temp\n\
             mat,mixed_air_temp\nfan,fan_status\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,oat,rat,mat,fan").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,40,70,55,1").unwrap();
        fdd_store::ingest_building(tmp.path(), "BUILDING_50", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        // Requesting a site that was never ingested must not fall back to the
        // whole tree (that would leak BUILDING_50 into a BUILDING_999 scope).
        let out = economizer_from_history(None, 10.0, Some("BUILDING_999"), 4000)
            .await
            .unwrap();
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
        assert!(out.is_none());
    }

    #[test]
    fn plant_group_for_maps_common_ids() {
        assert_eq!(plant_group_for("AHU_1"), Some("air"));
        assert_eq!(plant_group_for("RTU_WEST"), Some("air"));
        assert_eq!(plant_group_for("MAU_1"), Some("air"));
        assert_eq!(plant_group_for("CHILLER_1"), Some("chiller"));
        assert_eq!(plant_group_for("CT_1"), Some("chiller"));
        assert_eq!(plant_group_for("HP_3"), Some("chiller"));
        assert_eq!(plant_group_for("BOILER_1"), Some("boiler"));
        assert_eq!(plant_group_for("VAV_101"), None);
        assert_eq!(plant_group_for("BUILDING/VAVFC_2"), None);
        // Bare FAN/SUPPLY must not swallow unrelated motors.
        assert_eq!(plant_group_for("EXHAUST_FAN_1"), None);
        assert_eq!(plant_group_for("SUPPLY_METER"), None);
    }

    #[test]
    fn cooling_on_expr_ignores_fan_only() {
        let mut cols = HashSet::new();
        cols.insert("fan_status".into());
        cols.insert("fan_cmd".into());
        cols.insert("oa_t".into());
        assert!(cooling_on_expr(&cols).is_none());
        assert!(on_expr(&cols).is_some());
    }

    #[test]
    fn cooling_on_expr_uses_chiller_status() {
        let mut cols = HashSet::new();
        cols.insert("chiller_status".into());
        cols.insert("web_oa_t".into());
        let expr = cooling_on_expr(&cols).expect("cooling proof");
        assert!(expr.contains("chiller_status"));
        assert!(!expr.contains("fan_"));
    }

    #[tokio::test]
    async fn mech_oat_bins_none_for_fan_only_fixture() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_FAN");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nfan_speed_pct,fan_cmd\noa_temp_f,oa_t\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,fan_speed_pct,oa_temp_f").unwrap();
        writeln!(f, "2026-07-01T00:00:00Z,100,85").unwrap();
        writeln!(f, "2026-07-01T00:05:00Z,100,86").unwrap();
        writeln!(f, "2026-07-01T00:10:00Z,100,87").unwrap();

        let parquet = tmp.path().join("parquet_fan");
        fdd_store::ingest_building(tmp.path(), "BUILDING_FAN", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let out = mech_oat_bins_from_history(None, 900.0, Some("BUILDING_FAN"))
            .await
            .unwrap();
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
        assert!(
            out.is_none(),
            "fan-only history must not produce mech oat bins"
        );
    }

    #[tokio::test]
    async fn mech_oat_bins_from_chiller_status_fixture() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_CH");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ch = building.join("CHILLER_1");
        std::fs::create_dir_all(&ch).unwrap();
        std::fs::write(
            ch.join("columns.csv"),
            "col,point_role\nchiller_status,chiller_status\nweb_oa_t,web_oa_t\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ch.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,chiller_status,web_oa_t").unwrap();
        writeln!(f, "2026-07-01T00:00:00Z,1,82").unwrap();
        writeln!(f, "2026-07-01T00:05:00Z,1,83").unwrap();
        writeln!(f, "2026-07-01T00:10:00Z,0,84").unwrap();

        let parquet = tmp.path().join("parquet_ch");
        fdd_store::ingest_building(tmp.path(), "BUILDING_CH", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = mech_oat_bins_from_history(None, 900.0, Some("BUILDING_CH"))
            .await
            .unwrap()
            .expect("chiller_status fixture should produce oat bins");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        assert_eq!(env.engine, DF_ENGINE);
        assert!(!env.rows.is_empty());
        assert_eq!(env.rows[0]["kind"], "oat_bin");
        assert!(env.coverage.as_ref().unwrap()["oat_column"] == "web_oa_t");
        let hours: f64 = env
            .rows
            .iter()
            .map(|r| r["hours"].as_f64().unwrap_or(0.0))
            .sum();
        // Two on intervals of 300s (t0→t1 and t1→t2 while status stays 1) → 600s
        assert!((hours - (600.0 / 3600.0)).abs() < 0.02, "hours={hours}");
    }

    #[test]
    fn parquet_root_respects_env() {
        let _guard = ENV_LOCK.blocking_lock();
        let tmp = tempfile::TempDir::new().unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.path());
        assert_eq!(parquet_root(), tmp.path());
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
    }
}
