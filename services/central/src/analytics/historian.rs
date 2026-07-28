//! Historian Parquet bridge for DataFusion analytics (Milestone D1).

use std::collections::HashSet;
use std::path::PathBuf;

use anyhow::{anyhow, Result};
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, run_sql};
use serde_json::json;

use super::{envelope_with_engine, AnalyticsEnvelope, AnalyticsQuery, DF_ENGINE, QV_RUNTIME};

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

/// Register `history` from parquet_root when the tree exists and has data.
/// Returns `Ok(true)` on success, `Ok(false)` when missing/empty/unusable.
pub async fn try_register_history(ctx: &SessionContext) -> Result<bool> {
    let root = parquet_root();
    if !root.is_dir() {
        return Ok(false);
    }
    match register_parquet_tree(ctx, &root).await {
        Ok(_) => Ok(true),
        Err(e) => {
            tracing::debug!(error = %e, root = %root.display(), "historian parquet register skipped");
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

fn round2(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
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

/// Load runtime hours from historian Parquet via DataFusion.
///
/// Returns `Ok(None)` when parquet is missing/empty. When columns support Δt
/// integration (`equipment_id`, timestamp, fan_status/fan_cmd), computes real
/// forward-interval run hours with gap clipping. Otherwise returns a count-based
/// envelope with `engine=datafusion` and a warning that column-mapped runtime is next.
pub async fn runtime_from_history(
    equipment_filter: Option<&[String]>,
    max_gap_seconds: f64,
) -> Result<Option<AnalyticsEnvelope>> {
    let ctx = SessionContext::new();
    if !try_register_history(&ctx).await? {
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
        if let (Some(ts_col), Some(on_sql)) = (pick_ts_col(&cols), on_expr(&cols)) {
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
                    let warnings = vec![
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
                        }));
                    }
                    let mut env = envelope_with_engine(QV_RUNTIME, &query, warnings, DF_ENGINE);
                    env.equipment = equipment.clone();
                    env.rows = equipment;
                    env.coverage = Some(json!({
                        "equipment_count": env.equipment.len(),
                        "history_rows": n,
                        "max_gap_seconds": max_gap,
                        "source": "historian_parquet",
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
         (need equipment_id + timestamp_utc + fan_status/fan_cmd)"
            .into(),
    ];
    let mut env = envelope_with_engine(QV_RUNTIME, &query, warnings, DF_ENGINE);
    env.coverage = Some(json!({
        "history_rows": n,
        "max_gap_seconds": max_gap,
        "source": "historian_parquet",
    }));
    Ok(Some(env))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[tokio::test]
    async fn runtime_from_history_none_when_no_parquet() {
        let tmp = tempfile::TempDir::new().unwrap();
        let missing = tmp.path().join("no_such_parquet");
        std::env::set_var("OPENFDD_PARQUET_ROOT", &missing);
        let out = runtime_from_history(None, 900.0).await.unwrap();
        assert!(out.is_none());
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
    }

    #[tokio::test]
    async fn runtime_from_history_sets_datafusion_engine() {
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

        let env = runtime_from_history(None, 900.0)
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

    #[test]
    fn parquet_root_respects_env() {
        let tmp = tempfile::TempDir::new().unwrap();
        std::env::set_var("OPENFDD_PARQUET_ROOT", tmp.path());
        assert_eq!(parquet_root(), tmp.path());
        std::env::remove_var("OPENFDD_PARQUET_ROOT");
    }
}
