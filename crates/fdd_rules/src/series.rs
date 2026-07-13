//! Sample-level series for Plotly overlays (gate / raw / confirmed).

use std::collections::HashSet;
use std::path::Path;

use anyhow::{bail, Context, Result};
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, register_weather_if_present, run_sql};
use serde_json::{json, Value};

use crate::gate_sql::{
    inject_raw_fault_operational_gate, operational_proof_expr, should_inject_operational_gate,
    startup_delay_rows,
};
use crate::params::{read_poll_from_cache, rule_params, substitute_sql};
use crate::registry::RuleRegistry;
use crate::runner::{derive_window_rows, project_optional_roles};
use crate::tuning::{assert_sql_placeholders, effective_param_strings, load_tuning_profiles};

/// Rewrite aggregate rule SQL into a bounded per-sample series for one equipment.
pub fn rewrite_sql_for_equipment_series(sql: &str, equipment_id: &str, max_points: usize) -> Result<String> {
    if !equipment_id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        bail!("invalid equipment_id for series query");
    }
    let max_points = max_points.clamp(1, 20_000);
    // Prefer ranked CTE (has timestamp + raw_fault + streak_len).
    let marker = "final AS (";
    let Some(pos) = sql.rfind(marker) else {
        bail!("rule SQL missing final CTE — cannot emit series");
    };
    let head = &sql[..pos];
    if !head.contains("ranked AS") {
        bail!("rule SQL missing ranked CTE — cannot emit series");
    }
    let out = format!(
        "{head}\
series AS (\n  \
  SELECT\n    \
    equipment_id,\n    \
    timestamp_utc,\n    \
    raw_fault,\n    \
    CASE WHEN raw_fault = 1 AND streak_len >= {{{{CONFIRM_ROWS}}}} THEN 1 ELSE 0 END AS confirmed\n  \
  FROM ranked\n  \
  WHERE equipment_id = '{equipment_id}'\n\
)\n\
SELECT equipment_id, timestamp_utc, raw_fault, confirmed\n\
FROM series\n\
ORDER BY timestamp_utc\n\
LIMIT {max_points};\n"
    );
    // CONFIRM_ROWS already substituted in caller — fix placeholder if already numeric.
    Ok(out)
}

pub async fn run_rule_equipment_series(
    parquet_root: &Path,
    registry: &RuleRegistry,
    rule_id: &str,
    equipment_id: &str,
    max_points: usize,
) -> Result<Value> {
    let poll_seconds = read_poll_from_cache(parquet_root).unwrap_or(300.0);
    let rules_dir = Path::new(&registry.rules_dir);
    let tuning = load_tuning_profiles(rules_dir)?;
    let rule = registry
        .rules
        .iter()
        .find(|r| r.rule_id == rule_id)
        .with_context(|| format!("unknown rule_id `{rule_id}`"))?;

    let ctx = SessionContext::new();
    register_parquet_tree(&ctx, parquet_root).await?;
    register_weather_if_present(&ctx, parquet_root).await?;
    let history_columns = history_columns(&ctx).await?;

    let sql_path = rules_dir.join(&rule.sql_file);
    let raw_sql = std::fs::read_to_string(&sql_path)?;
    assert_sql_placeholders(&raw_sql, rule)?;

    let mut params = rule_params(poll_seconds, rule.confirm_seconds);
    if let Ok(tuned) = effective_param_strings(rule, &tuning, None, None, None) {
        for (k, v) in tuned {
            params.insert(k, v);
        }
        if let Some(cs) = params
            .get("CONFIRM_SECONDS")
            .and_then(|s| s.parse::<u32>().ok())
        {
            let rows = ((cs as f64 / poll_seconds.max(1.0)).ceil() as u32).max(1);
            params.insert("CONFIRM_ROWS".into(), rows.to_string());
        }
    }
    if raw_sql.contains("{{WINDOW_ROWS}}") || raw_sql.contains("{{WINDOW_ROWS_MINUS_ONE}}") {
        let window_minutes = params
            .get("WINDOW_MINUTES")
            .and_then(|s| s.parse::<f64>().ok())
            .or_else(|| rule.parameters.get("window_minutes").map(|p| p.default))
            .unwrap_or(60.0);
        let (window_rows, window_rows_minus_one) =
            derive_window_rows(window_minutes, poll_seconds);
        params.insert("WINDOW_ROWS".into(), window_rows.to_string());
        params.insert(
            "WINDOW_ROWS_MINUS_ONE".into(),
            window_rows_minus_one.to_string(),
        );
    }

    let projected = project_optional_roles(&raw_sql, rule, &history_columns);
    let mut sql = substitute_sql(&projected, &params);
    if should_inject_operational_gate(rule) {
        let predicate = rule
            .operational_gate
            .as_ref()
            .map(|g| g.predicate.as_str())
            .unwrap_or("fan_running");
        if let Some(proof) = operational_proof_expr(&history_columns, predicate) {
            let rows = startup_delay_rows(rule, poll_seconds);
            sql = inject_raw_fault_operational_gate(&sql, &proof, rows);
        }
    }

    // Confirm rows already substituted — rewrite uses literal from params.
    let confirm_rows = params
        .get("CONFIRM_ROWS")
        .cloned()
        .unwrap_or_else(|| "1".into());
    let mut series_sql = rewrite_sql_for_equipment_series(&sql, equipment_id, max_points)?;
    series_sql = series_sql.replace("{{CONFIRM_ROWS}}", &confirm_rows);

    let result = run_sql(&ctx, &series_sql).await?;
    let proof = if should_inject_operational_gate(rule) {
        let predicate = rule
            .operational_gate
            .as_ref()
            .map(|g| g.predicate.as_str())
            .unwrap_or("fan_running");
        operational_proof_expr(&history_columns, predicate)
    } else {
        None
    };

    let mut points = Vec::with_capacity(result.rows.len());
    for row in &result.rows {
        let ts = row
            .get("timestamp_utc")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        let raw = row.get("raw_fault").and_then(|v| v.as_i64().or_else(|| v.as_f64().map(|f| f as i64))).unwrap_or(0);
        let confirmed = row
            .get("confirmed")
            .and_then(|v| v.as_i64().or_else(|| v.as_f64().map(|f| f as i64)))
            .unwrap_or(0);
        points.push(json!({
            "timestamp": ts,
            "raw": raw,
            "confirmed": confirmed,
        }));
    }

    // Attach operational mask when proof columns exist (separate lightweight query).
    if let Some(proof_expr) = proof {
        let op_sql = format!(
            "SELECT timestamp_utc, CASE WHEN ({proof_expr}) > 0 THEN 1 ELSE 0 END AS operational \
             FROM history WHERE equipment_id = '{equipment_id}' ORDER BY timestamp_utc LIMIT {max_points}"
        );
        if let Ok(op) = run_sql(&ctx, &op_sql).await {
            let by_ts: std::collections::HashMap<String, i64> = op
                .rows
                .iter()
                .filter_map(|r| {
                    let ts = r.get("timestamp_utc")?.as_str()?.to_string();
                    let v = r
                        .get("operational")?
                        .as_i64()
                        .or_else(|| r.get("operational")?.as_f64().map(|f| f as i64))?;
                    Some((ts, v))
                })
                .collect();
            for p in &mut points {
                if let Some(obj) = p.as_object_mut() {
                    if let Some(ts) = obj.get("timestamp").and_then(|v| v.as_str()) {
                        if let Some(v) = by_ts.get(ts) {
                            obj.insert("operational".into(), json!(*v));
                        }
                    }
                }
            }
        }
    }

    Ok(json!({
        "ok": true,
        "rule_id": rule.rule_id,
        "equipment_id": equipment_id,
        "gate_mode": rule.gate_mode(),
        "point_count": points.len(),
        "max_points": max_points,
        "points": points,
    }))
}

async fn history_columns(ctx: &SessionContext) -> Result<HashSet<String>> {
    let df = ctx.sql("SELECT * FROM history LIMIT 0").await?;
    Ok(df
        .schema()
        .fields()
        .iter()
        .map(|f| f.name().clone())
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rewrite_keeps_ranked_and_limits() {
        let sql = "WITH base AS (SELECT 1),\nranked AS (SELECT 1),\nfinal AS (\n  SELECT equipment_id FROM ranked\n)\nSELECT equipment_id, SUM(1) FROM final GROUP BY equipment_id;";
        let out = rewrite_sql_for_equipment_series(sql, "AHU_1", 100).unwrap();
        assert!(out.contains("WHERE equipment_id = 'AHU_1'"));
        assert!(out.contains("LIMIT 100"));
        assert!(!out.contains("SUM(confirmed)"));
    }

    #[test]
    fn rejects_unsafe_equipment_id() {
        assert!(rewrite_sql_for_equipment_series(
            "WITH ranked AS (SELECT 1),\nfinal AS (SELECT 1)\nSELECT 1;",
            "AHU';DROP",
            10
        )
        .is_err());
    }
}
