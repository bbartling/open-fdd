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
    "web_oa_t",
    "web_wb_t",
    "rat",
    "mat",
    "sat",
    "zone_t",
    "zone_flow",
    "fan_cmd",
    "fan_status",
    "oa_damper_pct",
    "clg_valve_pct",
    "htg_valve_pct",
    "damper_pct",
    "reheat_valve_pct",
    "sat_sp",
    "duct_static",
    "duct_static_sp",
    "chw_supply_t",
    "chw_return_t",
    "cw_supply_t",
    "cw_return_t",
    "hw_supply_t",
    "hw_return_t",
    "elec_power",
    "gas_flow",
    "chiller_power",
    "chiller_amps",
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

fn web_oat_col(cols: &HashSet<String>) -> Option<&'static str> {
    ["web_oa_t", "oa_t_web", "oat_meteo", "oa_t_meteo"]
        .into_iter()
        .find(|&c| cols.contains(c))
}

/// Prefer web/meteo OAT for weekly plant avg-while-on (vibe19 `prefer_web_oat`).
fn weekly_oat_col(cols: &HashSet<String>) -> Option<&'static str> {
    mech_oat_col(cols)
}

/// Short signal label for weekly chart series names (schema-level best effort).
fn plant_signal_label(cols: &HashSet<String>) -> &'static str {
    if cols.contains("fan_status") {
        "fan-status"
    } else if cols.contains("fan_cmd") {
        "fan-cmd"
    } else if cols.contains("chiller_status") {
        "chiller-status"
    } else if cols.contains("boiler_status") {
        "boiler-status"
    } else {
        "status"
    }
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
                        weekly_oat_col(&cols),
                        max_gap,
                        &eq_filter,
                        plant_signal_label(&cols),
                    )
                    .await
                    .unwrap_or_else(|e| {
                        warnings.push(format!("weekly plant bins skipped: {e}"));
                        Vec::new()
                    });
                    if !weekly_rows.is_empty() {
                        warnings.push(
                            "rows include weekly per-equipment plant bins (runtime-weekly-v2)"
                                .into(),
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

/// Weekly per-equipment run hours (Mon-start week labels) for Overview motor charts.
/// Emits `kind=weekly_equipment` rows (one series per AHU/chiller/boiler), matching
/// vibe19 `motor_run_hours_weekly` — does **not** fold equipment into plant totals.
/// Site OAT is broadcast by timestamp so avg-while-on works when OAT lives on
/// weather/web rows rather than on the motor equipment itself.
async fn runtime_weekly_plant_rows(
    ctx: &SessionContext,
    ts_col: &str,
    on_sql: &str,
    oat: Option<&str>,
    max_gap: f64,
    eq_filter: &str,
    signal_label: &str,
) -> Result<Vec<Value>> {
    let oat_by_ts_cte = match oat {
        Some(c) => format!(
            r#"
oat_by_ts AS (
  SELECT {ts_col} AS ts, AVG({c}) AS oat_f
  FROM history
  WHERE {c} IS NOT NULL
  GROUP BY {ts_col}
),"#
        ),
        None => String::new(),
    };
    let oat_join = if oat.is_some() {
        "LEFT JOIN oat_by_ts o ON h.ts = o.ts"
    } else {
        ""
    };
    let oat_sel = if oat.is_some() {
        "o.oat_f AS oat_f,"
    } else {
        "CAST(NULL AS FLOAT) AS oat_f,"
    };
    let sql = format!(
        r#"
WITH {oat_by_ts_cte}
ordered AS (
  SELECT
    h.equipment_id,
    h.ts,
    h.is_on,
    {oat_sel}
    LEAD(h.ts) OVER (PARTITION BY h.equipment_id ORDER BY h.ts) AS next_ts
  FROM (
    SELECT
      equipment_id,
      {ts_col} AS ts,
      {on_sql} AS is_on
    FROM history
    WHERE equipment_id IS NOT NULL{eq_filter}
  ) h
  {oat_join}
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
    let mut out = Vec::new();
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
        if hours <= 0.0 {
            continue;
        }
        let oat_v = row.get("avg_oat_f").and_then(|v| v.as_f64());
        let label = format!("{eq} · {signal_label}");
        out.push(json!({
            "kind": "weekly_equipment",
            "query_version": "runtime-weekly-v2",
            "equipment_id": eq,
            "label": label,
            "plant_group": plant,
            "week_label": week,
            "run_hours": round2(hours),
            "avg_oat_f": oat_v.map(round2),
        }));
    }
    out.sort_by(|a, b| {
        let wa = a.get("week_label").and_then(|v| v.as_str()).unwrap_or("");
        let wb = b.get("week_label").and_then(|v| v.as_str()).unwrap_or("");
        wa.cmp(wb).then_with(|| {
            let pa = a.get("plant_group").and_then(|v| v.as_str()).unwrap_or("");
            let pb = b.get("plant_group").and_then(|v| v.as_str()).unwrap_or("");
            pa.cmp(pb).then_with(|| {
                let ea = a.get("equipment_id").and_then(|v| v.as_str()).unwrap_or("");
                let eb = b.get("equipment_id").and_then(|v| v.as_str()).unwrap_or("");
                ea.cmp(eb)
            })
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
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
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
        "oa_damper_pct AS damper_fb_pct"
    } else {
        "CAST(NULL AS DOUBLE) AS damper_fb_pct"
    };
    let sat_proj = if cols.contains("sat") {
        "sat AS sat_f"
    } else {
        "CAST(NULL AS DOUBLE) AS sat_f"
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
  COUNT(damper_fb_pct) AS n_damper
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
    // Keep aliases consistent in the CTE (sat_f / damper_fb_pct). Avoid bare
    // `WHERE fan_on` + `THEN true/false` outer columns — those hit DataFusion
    // SanityCheckPlan on some historian schemas (Liberty BUILDING_100).
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
    CASE WHEN ({on_sql}) THEN 1 ELSE 0 END AS fan_on_i
  FROM history
  WHERE equipment_id IS NOT NULL{eq_filter}
)
SELECT
  equipment_id,
  timestamp_utc,
  oat_f,
  rat_f,
  mat_f,
  sat_f,
  damper_fb_pct,
  (oat_f - rat_f) AS delta_or_f,
  (mat_f - rat_f) AS delta_mr_f,
  CASE
    WHEN damper_fb_pct IS NOT NULL AND oat_f IS NOT NULL AND rat_f IS NOT NULL THEN
      mat_f - (rat_f + (damper_fb_pct / 100.0) * (oat_f - rat_f))
    ELSE NULL
  END AS mat_resid_f,
  CASE
    WHEN oat_f IS NOT NULL AND rat_f IS NOT NULL AND ABS(oat_f - rat_f) >= {dt_min}
    THEN 1 ELSE 0
  END AS identifiable_i
FROM base
WHERE fan_on_i = 1
  AND oat_f IS NOT NULL AND rat_f IS NOT NULL AND mat_f IS NOT NULL
ORDER BY identifiable_i DESC, timestamp_utc
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
                    "identifiable": as_u64(r.get("identifiable_i")) > 0,
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
    // Site OAT broadcast by timestamp (Liberty chillers often lack inline OAT).
    let sql = format!(
        r#"
WITH oat_by_ts AS (
  SELECT {ts_col} AS ts, AVG({oat}) AS oat_f
  FROM history
  WHERE {oat} IS NOT NULL AND {oat} >= 40.0 AND {oat} <= 110.0
  GROUP BY {ts_col}
),
chiller_samp AS (
  SELECT
    h.equipment_id,
    h.{ts_col} AS ts,
    {on_sql} AS is_on,
    o.oat_f
  FROM history h
  LEFT JOIN oat_by_ts o ON h.{ts_col} = o.ts
  WHERE h.equipment_id IS NOT NULL{eq_filter}{chiller_filter}
),
ordered AS (
  SELECT
    equipment_id,
    ts,
    is_on,
    oat_f,
    LEAD(ts) OVER (PARTITION BY equipment_id ORDER BY ts) AS next_ts
  FROM chiller_samp
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
  WHERE next_ts IS NOT NULL AND is_on AND oat_f IS NOT NULL
),
device_bins AS (
  SELECT
    equipment_id,
    FLOOR(oat_f / 5.0) * 5.0 AS bin_lo,
    SUM(dt_sec) / 3600.0 AS hours
  FROM intervals
  GROUP BY equipment_id, FLOOR(oat_f / 5.0) * 5.0
),
any_by_ts AS (
  SELECT
    ts,
    BOOL_OR(is_on) AS any_on,
    MAX(oat_f) AS oat_f
  FROM chiller_samp
  WHERE oat_f IS NOT NULL
  GROUP BY ts
),
any_ordered AS (
  SELECT
    ts,
    any_on,
    oat_f,
    LEAD(ts) OVER (ORDER BY ts) AS next_ts
  FROM any_by_ts
),
any_intervals AS (
  SELECT
    oat_f,
    CASE
      WHEN (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 < 0.0 THEN 0.0
      WHEN (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0 > {max_gap} THEN {max_gap}
      ELSE (CAST(next_ts AS BIGINT) - CAST(ts AS BIGINT)) / 1000000000.0
    END AS dt_sec
  FROM any_ordered
  WHERE next_ts IS NOT NULL AND any_on AND oat_f IS NOT NULL
),
any_bins AS (
  SELECT
    FLOOR(oat_f / 5.0) * 5.0 AS bin_lo,
    SUM(dt_sec) / 3600.0 AS hours
  FROM any_intervals
  GROUP BY FLOOR(oat_f / 5.0) * 5.0
)
SELECT
  equipment_id,
  'individual_device' AS series_kind,
  bin_lo,
  hours
FROM device_bins
UNION ALL
SELECT
  'ALL' AS equipment_id,
  'aggregate_device_hours' AS series_kind,
  bin_lo,
  SUM(hours) AS hours
FROM device_bins
GROUP BY bin_lo
UNION ALL
SELECT
  'ANY' AS equipment_id,
  'aggregate_active_hours' AS series_kind,
  bin_lo,
  hours
FROM any_bins
ORDER BY series_kind, equipment_id, bin_lo
"#
    );
    let result = match run_sql(&ctx, &sql).await {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!(error = %e, "mech oat bin SQL failed");
            return Ok(None);
        }
    };
    let mut rows = Vec::new();
    for r in &result.rows {
        let lo = as_f64(r.get("bin_lo")).unwrap_or(0.0);
        let hours = as_f64(r.get("hours")).unwrap_or(0.0);
        if hours <= 0.0 {
            continue;
        }
        let eq = r
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let series_kind = r
            .get("series_kind")
            .and_then(|v| v.as_str())
            .unwrap_or("individual_device")
            .to_string();
        rows.push(json!({
            "kind": "oat_bin",
            "query_version": "mechanical-cooling-oat-bins-v2",
            "series_kind": series_kind,
            "equipment_id": eq,
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
         (compressor/chiller proof × site-broadcast preferred web OAT; per-device + aggregates)"
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
        "oat_join": "site_broadcast_by_ts",
    }));
    Ok(Some(env))
}

/// BAS oa_t vs web OAT overlay samples + deviation histogram rows.
/// Site-broadcasts BAS and web OAT by timestamp so Liberty works when `oa_t`
/// lives on AHU rows and `web_oa_t` on weather (not co-located on one row).
/// When only `oa_t` exists (Liberty), weather equipment rows supply web OAT and
/// non-weather rows supply BAS OAT.
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
    let web_col = web_oat_col(&cols);
    let weather_split = web_col.is_none();
    if !weather_split && web_col == Some(bas) {
        return Ok(None);
    }
    let _eq_filter = equipment_filter_sql(equipment_filter);
    let limit = max_points.clamp(100, 5000);
    let (web_label, sql) = if let Some(web) = web_col {
        (
            web.to_string(),
            format!(
                r#"
WITH bas_by_ts AS (
  SELECT {ts_col} AS ts, AVG({bas}) AS bas_oat_f
  FROM history
  WHERE {bas} IS NOT NULL
  GROUP BY {ts_col}
),
web_by_ts AS (
  SELECT {ts_col} AS ts, AVG({web}) AS web_oat_f
  FROM history
  WHERE {web} IS NOT NULL
  GROUP BY {ts_col}
)
SELECT
  CAST(b.ts AS VARCHAR) AS timestamp_utc,
  'site' AS equipment_id,
  b.bas_oat_f,
  w.web_oat_f,
  (b.bas_oat_f - w.web_oat_f) AS delta_f
FROM bas_by_ts b
INNER JOIN web_by_ts w ON b.ts = w.ts
ORDER BY b.ts
LIMIT {limit}
"#
            ),
        )
    } else {
        (
            "oa_t@weather".into(),
            format!(
                r#"
WITH bas_by_ts AS (
  SELECT {ts_col} AS ts, AVG({bas}) AS bas_oat_f
  FROM history
  WHERE {bas} IS NOT NULL
    AND UPPER(CAST(equipment_id AS VARCHAR)) NOT LIKE '%WEATHER%'
  GROUP BY {ts_col}
),
web_by_ts AS (
  SELECT {ts_col} AS ts, AVG({bas}) AS web_oat_f
  FROM history
  WHERE {bas} IS NOT NULL
    AND UPPER(CAST(equipment_id AS VARCHAR)) LIKE '%WEATHER%'
  GROUP BY {ts_col}
)
SELECT
  CAST(b.ts AS VARCHAR) AS timestamp_utc,
  'site' AS equipment_id,
  b.bas_oat_f,
  w.web_oat_f,
  (b.bas_oat_f - w.web_oat_f) AS delta_f
FROM bas_by_ts b
INNER JOIN web_by_ts w ON b.ts = w.ts
ORDER BY b.ts
LIMIT {limit}
"#
            ),
        )
    };
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
    let mut warnings = vec![
        "BAS vs web OAT from historian DataFusion (site-broadcast oa_t × web OAT by timestamp)"
            .into(),
    ];
    if weather_split {
        warnings.push(
            "web OAT sourced from equipment_id matching WEATHER (single oa_t column site)".into(),
        );
    }
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("bas-vs-web-oat-v2", &query, warnings, DF_ENGINE);
    env.points = points;
    env.rows = rows;
    env.coverage = Some(json!({
        "point_count": env.points.len(),
        "hist_bins": env.rows.len(),
        "history_rows": n,
        "bas_column": bas,
        "web_column": web_label,
        "weather_equipment_split": weather_split,
        "oat_join": "site_broadcast_by_ts",
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

/// Raw equipment history for Overview data inspection (vibe19 equipment_inspection_chart).
/// Returns plottable numeric columns + downsampled wide points — no FDD rule required.
pub async fn inspect_from_history(
    building_id: Option<&str>,
    equipment_id: &str,
    columns: Option<&[String]>,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let eq = equipment_id.trim();
    if eq.is_empty() {
        return Ok(None);
    }
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    let skip = HashSet::from([
        "equipment_id".to_string(),
        "building".to_string(),
        "building_id".to_string(),
        ts_col.to_string(),
        "timestamp_utc".to_string(),
        "timestamp".to_string(),
        "ts".to_string(),
    ]);
    let mut plottable: Vec<String> = cols
        .iter()
        .filter(|c| !skip.contains(c.as_str()))
        .cloned()
        .collect();
    plottable.sort();
    if plottable.is_empty() {
        return Ok(None);
    }
    // Prefer AHU/zone roles so default inspect is useful on Liberty (not alphabetical
    // boiler_/chiller_ columns from the Hive union schema).
    const PREFERRED_INSPECT: &[&str] = &[
        "sat",
        "mat",
        "web_mat",
        "web_ma_t",
        "rat",
        "web_ra_t",
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
    ];
    let selected: Vec<String> = match columns {
        Some(want) if !want.is_empty() => want
            .iter()
            .filter(|c| plottable.iter().any(|p| p == *c))
            .cloned()
            .collect(),
        _ => {
            let mut picked: Vec<String> = PREFERRED_INSPECT
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
    let limit = max_points.clamp(50, 8000);
    let proj = selected
        .iter()
        .map(|c| c.to_string())
        .collect::<Vec<_>>()
        .join(", ");
    let eq_lit = eq.replace('\'', "''");
    let sql = format!(
        r#"
SELECT
  CAST({ts_col} AS VARCHAR) AS timestamp_utc,
  {proj}
FROM history
WHERE equipment_id = '{eq_lit}'
ORDER BY {ts_col}
LIMIT {limit}
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    let mut points = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        let mut row = json!({
            "timestamp_utc": r.get("timestamp_utc").cloned().unwrap_or(json!("")),
            "equipment_id": eq,
        });
        if let Some(obj) = row.as_object_mut() {
            for c in &selected {
                obj.insert(c.clone(), r.get(c).cloned().unwrap_or(Value::Null));
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
    let warnings = vec![
        "equipment inspection points from historian DataFusion (raw columns; no FDD rule)".into(),
    ];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("equipment-inspect-v1", &query, warnings, DF_ENGINE);
    env.points = points;
    env.rows = selected.iter().map(|c| json!({ "column": c })).collect();
    env.coverage = Some(json!({
        "equipment_id": eq,
        "row_count": n,
        "point_count": env.points.len(),
        "plottable_columns": plottable,
        "columns_plotted": selected,
        "first_timestamp": first,
        "last_timestamp": last,
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

fn rcx_eq_filter(kinds: &[&str]) -> String {
    if kinds.is_empty() {
        return String::new();
    }
    let mut parts = Vec::new();
    for k in kinds {
        let ku = k.to_ascii_uppercase();
        if ku == "VAV" {
            parts.push(
                "(UPPER(equipment_id) LIKE 'VAV%' OR UPPER(equipment_id) LIKE '%/VAV%' \
                 OR UPPER(equipment_id) LIKE '%VAVH%' OR UPPER(equipment_id) LIKE '%VAVFC%')"
                    .to_string(),
            );
        } else if ku == "CHW" || ku == "CHW_PLANT" {
            parts.push(
                "(UPPER(equipment_id) LIKE '%CHILLER%' OR UPPER(equipment_id) LIKE 'CHW%' \
                 OR UPPER(equipment_id) LIKE '%CHW_PLANT%')"
                    .to_string(),
            );
        } else if ku == "BOILER" {
            parts.push(
                "(UPPER(equipment_id) LIKE 'BOILER%' OR UPPER(equipment_id) LIKE '%/BOILER%' \
                 OR UPPER(equipment_id) LIKE '%BOILERS%')"
                    .to_string(),
            );
        } else if ku == "TOWER" || ku == "CT" || ku == "COOLING_TOWER" {
            parts.push(
                "(UPPER(equipment_id) LIKE '%TOWER%' OR UPPER(equipment_id) LIKE 'CT%' \
                 OR UPPER(equipment_id) LIKE '%COOLING_TOWER%')"
                    .to_string(),
            );
        } else if ku == "METER" {
            parts.push(
                "(UPPER(equipment_id) LIKE 'METER%' OR UPPER(equipment_id) LIKE '%/METER%' \
                 OR UPPER(equipment_id) LIKE '%_METER%')"
                    .to_string(),
            );
        } else {
            parts.push(format!(
                "(UPPER(equipment_id) LIKE '{ku}%' OR UPPER(equipment_id) LIKE '%/{ku}%')"
            ));
        }
    }
    format!(" AND ({})", parts.join(" OR "))
}

/// Multi-equipment role timeseries for RCx presets (vibe19 multi_equipment_timeseries).
pub async fn rcx_timeseries_from_history(
    building_id: Option<&str>,
    role_col: &str,
    overlay_col: Option<&str>,
    pair_return_col: Option<&str>,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    if !cols.contains(role_col) {
        return Ok(None);
    }
    let eq_filter = rcx_eq_filter(eq_kinds);
    let fan_filter = if filter_fan_on {
        match on_expr(&cols) {
            Some(expr) => format!(" AND ({expr})"),
            None => String::new(),
        }
    } else {
        String::new()
    };
    let limit = max_points.clamp(200, 20000);
    let overlay_sel = overlay_col
        .filter(|c| cols.contains(*c))
        .map(|c| format!(", {c} AS overlay_f"))
        .unwrap_or_else(|| ", CAST(NULL AS FLOAT) AS overlay_f".into());
    let return_sel = pair_return_col
        .filter(|c| cols.contains(*c))
        .map(|c| format!(", {c} AS return_f"))
        .unwrap_or_else(|| ", CAST(NULL AS FLOAT) AS return_f".into());
    // Optional motor/fan proof for vibe19 right-hand "motor on" y2 overlay.
    let motor_sel = if cols.contains("fan_status") {
        ", fan_status AS motor_f".to_string()
    } else if cols.contains("fan_cmd") {
        ", CASE WHEN fan_cmd > 0.05 THEN 1.0 ELSE 0.0 END AS motor_f".to_string()
    } else {
        ", CAST(NULL AS FLOAT) AS motor_f".into()
    };
    // Span-preserving downsample (vibe19): keep first/last + evenly spaced rows
    // across the full historian range instead of LIMIT taking only the earliest.
    // DataFusion 43 has no SQL `MOD()` / `GREATEST()` — use `%` and CASE.
    let sql = format!(
        r#"
SELECT timestamp_utc, equipment_id, value_f, overlay_f, return_f, motor_f
FROM (
  SELECT
    CAST({ts_col} AS VARCHAR) AS timestamp_utc,
    equipment_id,
    {role_col} AS value_f
    {overlay_sel}
    {return_sel}
    {motor_sel},
    ROW_NUMBER() OVER (ORDER BY {ts_col}, equipment_id) AS _rn,
    COUNT(*) OVER () AS _cnt
  FROM history
  WHERE equipment_id IS NOT NULL AND {role_col} IS NOT NULL{eq_filter}{fan_filter}
)
WHERE _rn = 1
   OR _rn = _cnt
   OR (_rn % (CASE
        WHEN CAST((_cnt + {limit} - 1) / {limit} AS BIGINT) > 1
        THEN CAST((_cnt + {limit} - 1) / {limit} AS BIGINT)
        ELSE 1
      END)) = 0
ORDER BY timestamp_utc, equipment_id
LIMIT {limit}
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    if result.rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        let row = json!({
            "timestamp_utc": r.get("timestamp_utc").cloned().unwrap_or(json!("")),
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "value_f": as_f64(r.get("value_f")),
            "series": "primary",
        });
        points.push(row.clone());
        if let Some(ov) = as_f64(r.get("overlay_f")) {
            let mut o = row.clone();
            if let Some(obj) = o.as_object_mut() {
                obj.insert("value_f".into(), json!(ov));
                obj.insert("series".into(), json!("overlay"));
            }
            points.push(o);
        }
        if let Some(ret) = as_f64(r.get("return_f")) {
            let mut rr = row.clone();
            if let Some(obj) = rr.as_object_mut() {
                obj.insert("value_f".into(), json!(ret));
                obj.insert("series".into(), json!("return"));
            }
            points.push(rr);
            if let Some(sup) = as_f64(r.get("value_f")) {
                let mut d = row.clone();
                if let Some(obj) = d.as_object_mut() {
                    obj.insert("value_f".into(), json!(round2(ret - sup)));
                    obj.insert("series".into(), json!("delta_t"));
                }
                points.push(d);
            }
        }
        if let Some(m) = as_f64(r.get("motor_f")) {
            let mut mo = row;
            if let Some(obj) = mo.as_object_mut() {
                let on = if m > 0.05 { 1.0 } else { 0.0 };
                obj.insert("value_f".into(), json!(on));
                obj.insert("series".into(), json!("motor"));
            }
            points.push(mo);
        }
    }
    let warnings = vec!["RCx role timeseries from historian DataFusion".into()];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("rcx-timeseries-v1", &query, warnings, DF_ENGINE);
    env.points = points;
    env.coverage = Some(json!({
        "history_rows": n,
        "point_count": env.points.len(),
        "role_col": role_col,
        "chart_kind": "timeseries",
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

/// OAT scatter for RCx reset charts (vibe19 oat_scatter) with site-broadcast OAT.
pub async fn rcx_oat_scatter_from_history(
    building_id: Option<&str>,
    y_col: &str,
    eq_kinds: &[&str],
    prefer_wetbulb: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    if !cols.contains(y_col) {
        return Ok(None);
    }
    let oat = if prefer_wetbulb {
        ["web_wb_t", "oa_wb_t", "wetbulb_t"]
            .into_iter()
            .find(|&c| cols.contains(c))
            .or_else(|| mech_oat_col(&cols))
    } else {
        mech_oat_col(&cols)
    };
    let Some(oat) = oat else {
        return Ok(None);
    };
    let dry_ref = if prefer_wetbulb {
        mech_oat_col(&cols).filter(|c| *c != oat)
    } else {
        None
    };
    let eq_filter = rcx_eq_filter(eq_kinds);
    // Prefixed for JOIN aliases (history AS h).
    let eq_filter_h = eq_filter.replace("equipment_id", "h.equipment_id");
    let limit = max_points.clamp(200, 12000);
    let dry_sel = if dry_ref.is_some() {
        ", d.dry_f AS dry_bulb_f".to_string()
    } else {
        ", CAST(NULL AS FLOAT) AS dry_bulb_f".into()
    };
    let dry_cte = dry_ref
        .map(|c| {
            format!(
                ", dry_by_ts AS (\n  SELECT {ts_col} AS ts, AVG({c}) AS dry_f\n  FROM history\n  WHERE {c} IS NOT NULL\n  GROUP BY {ts_col}\n)"
            )
        })
        .unwrap_or_default();
    let dry_join = if dry_ref.is_some() {
        "LEFT JOIN dry_by_ts d ON h.{ts_col} = d.ts".replace("{ts_col}", ts_col)
    } else {
        String::new()
    };
    let sql = format!(
        r#"
WITH oat_by_ts AS (
  SELECT {ts_col} AS ts, AVG({oat}) AS oat_f
  FROM history
  WHERE {oat} IS NOT NULL
  GROUP BY {ts_col}
){dry_cte}
SELECT
  CAST(h.{ts_col} AS VARCHAR) AS ts_utc,
  h.equipment_id,
  o.oat_f,
  h.{y_col} AS y_f
  {dry_sel}
FROM history h
LEFT JOIN oat_by_ts o ON h.{ts_col} = o.ts
{dry_join}
WHERE h.equipment_id IS NOT NULL
  AND h.{y_col} IS NOT NULL
  AND o.oat_f IS NOT NULL{eq_filter_h}
ORDER BY h.{ts_col}, h.equipment_id
LIMIT {limit}
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    if result.rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        let mut row = json!({
            // Alias ts_utc avoids DataFusion ambiguity when ts_col is timestamp_utc.
            "timestamp_utc": r.get("ts_utc").cloned().unwrap_or(json!("")),
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "oat_f": as_f64(r.get("oat_f")),
            "y_f": as_f64(r.get("y_f")),
        });
        if let Some(d) = as_f64(r.get("dry_bulb_f")) {
            if let Some(obj) = row.as_object_mut() {
                obj.insert("dry_bulb_f".into(), json!(d));
            }
        }
        points.push(row);
    }
    let warnings = vec!["RCx OAT scatter from historian DataFusion (site-broadcast OAT)".into()];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("rcx-oat-scatter-v1", &query, warnings, DF_ENGINE);
    env.points = points;
    env.coverage = Some(json!({
        "history_rows": n,
        "point_count": env.points.len(),
        "y_col": y_col,
        "oat_column": oat,
        "prefer_wetbulb": prefer_wetbulb,
        "chart_kind": "scatter_oat",
        "oat_join": "site_broadcast_by_ts",
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

/// Multi-equipment box-plot samples (vibe19 multi_equipment_box).
pub async fn rcx_box_from_history(
    building_id: Option<&str>,
    role_col: &str,
    eq_kinds: &[&str],
    filter_fan_on: bool,
    max_points: usize,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    if !cols.contains(role_col) {
        return Ok(None);
    }
    let eq_filter = rcx_eq_filter(eq_kinds);
    let fan_filter = if filter_fan_on {
        match on_expr(&cols) {
            Some(expr) => format!(" AND ({expr})"),
            None => String::new(),
        }
    } else {
        String::new()
    };
    let limit = max_points.clamp(200, 20000);
    let sql = format!(
        r#"
SELECT equipment_id, {role_col} AS value_f
FROM history
WHERE equipment_id IS NOT NULL AND {role_col} IS NOT NULL{eq_filter}{fan_filter}
LIMIT {limit}
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    if result.rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        points.push(json!({
            "equipment_id": r.get("equipment_id").cloned().unwrap_or(json!("")),
            "value_f": as_f64(r.get("value_f")),
        }));
    }
    let warnings = vec!["RCx box samples from historian DataFusion".into()];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("rcx-box-v1", &query, warnings, DF_ENGINE);
    env.points = points;
    env.coverage = Some(json!({
        "history_rows": n,
        "point_count": env.points.len(),
        "role_col": role_col,
        "chart_kind": "box",
        "filter_fan_on": filter_fan_on,
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

/// Zone comfort fail ranking (vibe19 zone_comfort_fail_ranking) — % of samples
/// outside [low, high] band per VAV. Uses occ_mode when present on the row.
pub async fn rcx_zone_comfort_rank_from_history(
    building_id: Option<&str>,
    eq_kinds: &[&str],
    comfort_low_f: f64,
    comfort_high_f: f64,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    if !cols.contains("zone_t") {
        return Ok(None);
    }
    let eq_filter = rcx_eq_filter(eq_kinds);
    let occ_filter = if cols.contains("occ_mode") {
        " AND (occ_mode IS NULL OR UPPER(CAST(occ_mode AS VARCHAR)) IN \
          ('OCC','OCCUPIED','TRUE','YES','1','ON'))"
            .to_string()
    } else {
        String::new()
    };
    let sql = format!(
        r#"
SELECT
  equipment_id,
  COUNT(*) AS n_samples,
  SUM(CASE WHEN zone_t < {comfort_low_f} OR zone_t > {comfort_high_f} THEN 1 ELSE 0 END) AS n_fail
FROM history
WHERE equipment_id IS NOT NULL AND zone_t IS NOT NULL{eq_filter}{occ_filter}
GROUP BY equipment_id
ORDER BY (CAST(SUM(CASE WHEN zone_t < {comfort_low_f} OR zone_t > {comfort_high_f} THEN 1 ELSE 0 END) AS FLOAT)
          / CAST(COUNT(*) AS FLOAT)) DESC
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    if result.rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::with_capacity(result.rows.len());
    let mut rows = Vec::with_capacity(result.rows.len());
    for r in &result.rows {
        let n_samples = as_u64(r.get("n_samples")) as f64;
        let n_fail = as_u64(r.get("n_fail")) as f64;
        let fail_pct = if n_samples > 0.0 {
            round2(100.0 * n_fail / n_samples)
        } else {
            0.0
        };
        let eq = r.get("equipment_id").cloned().unwrap_or(json!(""));
        let row = json!({
            "equipment_id": eq.clone(),
            "n_samples": n_samples as u64,
            "n_fail": n_fail as u64,
            "fail_pct": fail_pct,
            "comfort_low_f": comfort_low_f,
            "comfort_high_f": comfort_high_f,
        });
        rows.push(row.clone());
        points.push(json!({
            "equipment_id": eq,
            "value_f": fail_pct,
            "series": "fail_pct",
        }));
    }
    let warnings =
        vec!["RCx zone comfort ranking from historian DataFusion (default band 70–75°F)".into()];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("rcx-ranking-v1", &query, warnings, DF_ENGINE);
    env.points = points;
    env.rows = rows;
    env.coverage = Some(json!({
        "history_rows": n,
        "point_count": env.points.len(),
        "chart_kind": "ranking",
        "comfort_low_f": comfort_low_f,
        "comfort_high_f": comfort_high_f,
        "source": "historian_parquet",
        "building_id": safe_building_segment(building_id),
    }));
    Ok(Some(env))
}

/// Monthly metering vs degree-days (vibe19 metering presets) — average power ×
/// hours as kWh proxy; CDD/HDD from site-broadcast monthly mean OAT (65°F base).
pub async fn rcx_metering_from_history(
    building_id: Option<&str>,
    role_col: &str,
    eq_kinds: &[&str],
    kind: &str,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, cols, n)) = open_history_scoped(building_id).await? else {
        return Ok(None);
    };
    let Some(ts_col) = pick_ts_col(&cols) else {
        return Ok(None);
    };
    if !cols.contains(role_col) {
        return Ok(None);
    }
    let Some(oat) = mech_oat_col(&cols) else {
        return Ok(None);
    };
    let eq_filter = rcx_eq_filter(eq_kinds);
    let eq_filter_h = eq_filter.replace("equipment_id", "h.equipment_id");
    let cooling = kind != "gas";
    let sql = format!(
        r#"
WITH oat_month AS (
  SELECT
    substr(CAST({ts_col} AS VARCHAR), 1, 7) AS month,
    AVG({oat}) AS avg_oat_f,
    COUNT(*) AS oat_n
  FROM history
  WHERE {oat} IS NOT NULL
  GROUP BY substr(CAST({ts_col} AS VARCHAR), 1, 7)
),
meter_month AS (
  SELECT
    h.equipment_id,
    substr(CAST(h.{ts_col} AS VARCHAR), 1, 7) AS month,
    AVG(h.{role_col}) AS avg_rate,
    COUNT(*) AS n_samples
  FROM history h
  WHERE h.equipment_id IS NOT NULL AND h.{role_col} IS NOT NULL{eq_filter_h}
  GROUP BY h.equipment_id, substr(CAST(h.{ts_col} AS VARCHAR), 1, 7)
)
SELECT
  m.equipment_id,
  m.month,
  m.avg_rate,
  m.n_samples,
  o.avg_oat_f
FROM meter_month m
LEFT JOIN oat_month o ON m.month = o.month
ORDER BY m.equipment_id, m.month
"#
    );
    let result = run_sql(&ctx, &sql).await?;
    if result.rows.is_empty() {
        return Ok(None);
    }
    let mut points = Vec::new();
    let mut rows = Vec::new();
    for r in &result.rows {
        let avg_rate = as_f64(r.get("avg_rate")).unwrap_or(0.0);
        let n_samples = as_u64(r.get("n_samples")) as f64;
        // Assume ~5-min samples → hours ≈ n * 5/60.
        let hours = n_samples * (5.0 / 60.0);
        let energy = round2(avg_rate * hours);
        let avg_oat = as_f64(r.get("avg_oat_f")).unwrap_or(65.0);
        let days = (n_samples * 5.0 / (60.0 * 24.0)).max(1.0);
        let dd = if cooling {
            round2((avg_oat - 65.0).max(0.0) * days)
        } else {
            round2((65.0 - avg_oat).max(0.0) * days)
        };
        let eq = r.get("equipment_id").cloned().unwrap_or(json!(""));
        let month = r.get("month").cloned().unwrap_or(json!(""));
        let row = json!({
            "equipment_id": eq.clone(),
            "month": month.clone(),
            "energy": energy,
            "avg_rate": round2(avg_rate),
            "degree_days": dd,
            "avg_oat_f": round2(avg_oat),
            "n_samples": n_samples as u64,
            "kind": kind,
        });
        rows.push(row.clone());
        points.push(json!({
            "equipment_id": eq,
            "month": month,
            "energy": energy,
            "degree_days": dd,
            "oat_f": dd,
            "y_f": energy,
            "value_f": energy,
        }));
    }
    let warnings = vec![
        format!(
            "RCx metering from historian DataFusion ({kind}; energy ≈ avg_rate × sample-hours; DD base 65°F)"
        ),
    ];
    let query = AnalyticsQuery::default();
    let mut env = envelope_with_engine("rcx-metering-v1", &query, warnings, DF_ENGINE);
    env.points = points;
    env.rows = rows;
    env.coverage = Some(json!({
        "history_rows": n,
        "point_count": env.points.len(),
        "role_col": role_col,
        "chart_kind": "metering",
        "meter_kind": kind,
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
    building_id: Option<&str>,
) -> Result<Option<AnalyticsEnvelope>> {
    let Some((ctx, _cols, n)) = open_history_scoped(building_id).await? else {
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
        "building_id": safe_building_segment(building_id),
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
        let out = sensor_health_from_history(None, None).await.unwrap();
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

        let env = sensor_health_from_history(None, Some("BUILDING_SH"))
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
            Some("BUILDING_DC"),
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
        assert_eq!(env.coverage.as_ref().unwrap()["building_id"], "BUILDING_DC");
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
        let device_hours: f64 = env
            .rows
            .iter()
            .filter(|r| r["series_kind"] == "individual_device")
            .map(|r| r["hours"].as_f64().unwrap_or(0.0))
            .sum();
        // Two on intervals of 300s (t0→t1 and t1→t2 while status stays 1) → 600s
        assert!(
            (device_hours - (600.0 / 3600.0)).abs() < 0.02,
            "device_hours={device_hours}"
        );
        assert!(env
            .rows
            .iter()
            .any(|r| r["series_kind"] == "aggregate_device_hours"));
        assert!(env.rows.iter().any(|r| r["equipment_id"] == "CHILLER_1"));
    }

    #[tokio::test]
    async fn mech_oat_bins_joins_site_oat_from_weather_equipment() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SPLIT");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();

        let ch = building.join("CHILLER_2");
        std::fs::create_dir_all(&ch).unwrap();
        std::fs::write(
            ch.join("columns.csv"),
            "col,point_role\nchiller_status,chiller_status\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ch.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,chiller_status").unwrap();
        writeln!(f, "2026-07-01T00:00:00Z,1").unwrap();
        writeln!(f, "2026-07-01T00:05:00Z,1").unwrap();
        writeln!(f, "2026-07-01T00:10:00Z,0").unwrap();

        let wx = building.join("weather");
        std::fs::create_dir_all(&wx).unwrap();
        std::fs::write(
            wx.join("columns.csv"),
            "col,point_role\nweb_oa_t,web_oa_t\n",
        )
        .unwrap();
        let mut wf = std::fs::File::create(wx.join("history_wide.csv")).unwrap();
        writeln!(wf, "timestamp_utc,web_oa_t").unwrap();
        writeln!(wf, "2026-07-01T00:00:00Z,72").unwrap();
        writeln!(wf, "2026-07-01T00:05:00Z,73").unwrap();
        writeln!(wf, "2026-07-01T00:10:00Z,74").unwrap();

        let parquet = tmp.path().join("parquet_split");
        fdd_store::ingest_building(tmp.path(), "BUILDING_SPLIT", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = mech_oat_bins_from_history(None, 900.0, Some("BUILDING_SPLIT"))
            .await
            .unwrap()
            .expect("site OAT join should produce oat bins without inline chiller OAT");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        let device: Vec<_> = env
            .rows
            .iter()
            .filter(|r| r["series_kind"] == "individual_device")
            .collect();
        assert!(!device.is_empty());
        assert_eq!(device[0]["equipment_id"], "CHILLER_2");
        assert!(device.iter().any(|r| {
            let lo = r["bin_lo_f"].as_f64().unwrap_or(-1.0);
            (70.0..75.0).contains(&lo)
        }));
    }

    #[tokio::test]
    async fn runtime_weekly_emits_per_equipment_not_plant_sum() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_AIR");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();

        for (eq, fan_vals) in [("AHU_1", [1, 1, 1]), ("AHU_2", [1, 0, 1])] {
            let dir = building.join(eq);
            std::fs::create_dir_all(&dir).unwrap();
            std::fs::write(
                dir.join("columns.csv"),
                "col,point_role\nfan_status,fan_status\nweb_oa_t,web_oa_t\n",
            )
            .unwrap();
            let mut f = std::fs::File::create(dir.join("history_wide.csv")).unwrap();
            writeln!(f, "timestamp_utc,fan_status,web_oa_t").unwrap();
            writeln!(f, "2026-03-23T00:00:00Z,{},55", fan_vals[0]).unwrap();
            writeln!(f, "2026-03-23T00:05:00Z,{},56", fan_vals[1]).unwrap();
            writeln!(f, "2026-03-23T00:10:00Z,{},57", fan_vals[2]).unwrap();
        }

        let parquet = tmp.path().join("parquet_air");
        fdd_store::ingest_building(tmp.path(), "BUILDING_AIR", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = runtime_from_history(None, 900.0, Some("BUILDING_AIR"))
            .await
            .unwrap()
            .expect("runtime envelope");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        let weekly: Vec<_> = env
            .rows
            .iter()
            .filter(|r| r["kind"] == "weekly_equipment")
            .collect();
        assert!(
            weekly.len() >= 2,
            "expected per-AHU weekly rows, got {weekly:?}"
        );
        let eqs: HashSet<_> = weekly
            .iter()
            .filter_map(|r| r["equipment_id"].as_str())
            .collect();
        assert!(eqs.contains("AHU_1"));
        assert!(eqs.contains("AHU_2"));
        assert!(weekly.iter().all(|r| r.get("label").is_some()));
        // Must not emit folded plant totals as the product rows.
        assert!(env.rows.iter().all(|r| r["kind"] != "weekly_plant"));
    }

    #[tokio::test]
    async fn rcx_oat_scatter_aliases_timestamp_without_schema_clash() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_OATSC");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();

        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nsat,sat\nweb_oa_t,web_oa_t\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,sat,web_oa_t").unwrap();
        writeln!(f, "2026-07-01T00:00:00Z,55,60").unwrap();
        writeln!(f, "2026-07-01T00:05:00Z,56,61").unwrap();
        writeln!(f, "2026-07-01T00:10:00Z,57,62").unwrap();

        let wx = building.join("weather");
        std::fs::create_dir_all(&wx).unwrap();
        std::fs::write(
            wx.join("columns.csv"),
            "col,point_role\nweb_oa_t,web_oa_t\n",
        )
        .unwrap();
        let mut wf = std::fs::File::create(wx.join("history_wide.csv")).unwrap();
        writeln!(wf, "timestamp_utc,web_oa_t").unwrap();
        writeln!(wf, "2026-07-01T00:00:00Z,60").unwrap();
        writeln!(wf, "2026-07-01T00:05:00Z,61").unwrap();
        writeln!(wf, "2026-07-01T00:10:00Z,62").unwrap();

        let parquet = tmp.path().join("parquet_oatsc");
        fdd_store::ingest_building(tmp.path(), "BUILDING_OATSC", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = rcx_oat_scatter_from_history(Some("BUILDING_OATSC"), "sat", &["AHU"], false, 500)
            .await
            .unwrap()
            .expect("oat scatter envelope");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        assert!(!env.points.is_empty());
        assert!(env.points[0].get("timestamp_utc").is_some());
        assert!(env.points[0].get("oat_f").is_some());
        assert!(env.points[0].get("y_f").is_some());
        assert_eq!(env.engine, DF_ENGINE);
    }

    #[tokio::test]
    async fn bas_vs_web_joins_site_oat_across_equipment() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_BAS");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();

        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(ahu.join("columns.csv"), "col,point_role\noa_t,oa_t\n").unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,oa_t").unwrap();
        writeln!(f, "2026-07-01T00:00:00Z,70").unwrap();
        writeln!(f, "2026-07-01T00:05:00Z,71").unwrap();
        writeln!(f, "2026-07-01T00:10:00Z,72").unwrap();

        let wx = building.join("weather");
        std::fs::create_dir_all(&wx).unwrap();
        std::fs::write(
            wx.join("columns.csv"),
            "col,point_role\nweb_oa_t,web_oa_t\n",
        )
        .unwrap();
        let mut wf = std::fs::File::create(wx.join("history_wide.csv")).unwrap();
        writeln!(wf, "timestamp_utc,web_oa_t").unwrap();
        writeln!(wf, "2026-07-01T00:00:00Z,68").unwrap();
        writeln!(wf, "2026-07-01T00:05:00Z,69").unwrap();
        writeln!(wf, "2026-07-01T00:10:00Z,70").unwrap();

        let parquet = tmp.path().join("parquet_bas");
        fdd_store::ingest_building(tmp.path(), "BUILDING_BAS", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = bas_vs_web_from_history(None, 500, Some("BUILDING_BAS"))
            .await
            .unwrap()
            .expect("site BAS×web join should produce overlay points");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        assert!(!env.points.is_empty());
        assert_eq!(
            env.coverage.as_ref().unwrap()["oat_join"],
            "site_broadcast_by_ts"
        );
        assert!(env.rows.iter().any(|r| r["kind"] == "delta_hist"));
    }

    #[tokio::test]
    async fn inspect_from_history_returns_raw_columns() {
        let _guard = ENV_LOCK.lock().await;
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_INSP");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nfan_status,fan_status\noa_t,oa_t\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,fan_status,oa_t").unwrap();
        writeln!(f, "2026-07-01T00:00:00Z,1,55").unwrap();
        writeln!(f, "2026-07-01T00:05:00Z,1,56").unwrap();

        let parquet = tmp.path().join("parquet_insp");
        fdd_store::ingest_building(tmp.path(), "BUILDING_INSP", &parquet).unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", &parquet);

        let env = inspect_from_history(Some("BUILDING_INSP"), "AHU_1", None, 500)
            .await
            .unwrap()
            .expect("inspect envelope");
        std::env::remove_var("OPENFDD_PARQUET_ROOT");

        assert!(!env.points.is_empty());
        let plotted = env.coverage.as_ref().unwrap()["columns_plotted"]
            .as_array()
            .unwrap();
        assert!(!plotted.is_empty());
        assert!(env.points[0].get("timestamp_utc").is_some());
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
