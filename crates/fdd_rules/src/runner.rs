use std::collections::HashSet;
use std::path::Path;

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, register_weather_if_present, run_sql};
use serde::Serialize;

use crate::params::{read_poll_from_cache, rule_params, substitute_sql};
use crate::registry::{RuleRegistry, RuleSpec};
use crate::tuning::{assert_sql_placeholders, effective_param_strings, load_tuning_profiles};

#[derive(Debug, Clone, Serialize)]
pub struct RuleTiming {
    pub rule_id: String,
    pub row_count: usize,
    pub elapsed_ms: u128,
    pub output_path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuleRunReport {
    pub rules_run: usize,
    pub rules_succeeded: usize,
    pub rules_failed: usize,
    pub poll_seconds: f64,
    pub timings: Vec<RuleTiming>,
    pub total_ms: u128,
}

pub async fn run_all_rules(
    parquet_root: &Path,
    registry: &RuleRegistry,
    out_dir: &Path,
) -> Result<RuleRunReport> {
    let started = std::time::Instant::now();
    std::fs::create_dir_all(out_dir)?;
    let poll_seconds = read_poll_from_cache(parquet_root).unwrap_or(300.0);
    let rules_dir = Path::new(&registry.rules_dir);
    let tuning = load_tuning_profiles(rules_dir)?;

    let ctx = SessionContext::new();
    register_parquet_tree(&ctx, parquet_root).await?;
    register_weather_if_present(&ctx, parquet_root).await?;
    let history_columns = history_column_names(&ctx).await.unwrap_or_default();

    let mut timings = Vec::new();
    let mut rules_succeeded = 0usize;
    let mut rules_failed = 0usize;
    for rule in &registry.rules {
        let sql_path = rules_dir.join(&rule.sql_file);
        let t0 = std::time::Instant::now();
        let out_path = out_dir.join(format!("{}.json", rule.rule_id));
        let raw_sql = match std::fs::read_to_string(&sql_path) {
            Ok(s) => s,
            Err(e) => {
                timings.push(RuleTiming {
                    rule_id: rule.rule_id.clone(),
                    row_count: 0,
                    elapsed_ms: t0.elapsed().as_millis(),
                    output_path: out_path.display().to_string(),
                    error: Some(e.to_string()),
                });
                rules_failed += 1;
                continue;
            }
        };
        if let Err(e) = assert_sql_placeholders(&raw_sql, rule) {
            timings.push(RuleTiming {
                rule_id: rule.rule_id.clone(),
                row_count: 0,
                elapsed_ms: t0.elapsed().as_millis(),
                output_path: out_path.display().to_string(),
                error: Some(e.to_string()),
            });
            rules_failed += 1;
            continue;
        }
        let missing_required: Vec<&str> = rule
            .required_roles
            .iter()
            .filter(|role| !history_columns.contains(role.as_str()))
            .map(|s| s.as_str())
            .collect();
        if !missing_required.is_empty() {
            let body = serde_json::json!({
                "rows": [],
                "status": "SKIPPED_MISSING_ROLES",
                "missing_roles": missing_required,
            });
            let _ = std::fs::write(&out_path, serde_json::to_string_pretty(&body)?);
            timings.push(RuleTiming {
                rule_id: rule.rule_id.clone(),
                row_count: 0,
                elapsed_ms: t0.elapsed().as_millis(),
                output_path: out_path.display().to_string(),
                error: Some(format!(
                    "SKIPPED_MISSING_ROLES: {}",
                    missing_required.join(", ")
                )),
            });
            rules_failed += 1;
            continue;
        }
        let confirm_secs = rule.confirm_seconds;
        let mut params = rule_params(poll_seconds, confirm_secs);
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
        // Derive rolling window row counts from WINDOW_MINUTES (or default 60).
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
        let sql = substitute_sql(&projected, &params);
        match run_sql(&ctx, &sql).await {
            Ok(result) => {
                std::fs::write(
                    &out_path,
                    serde_json::to_string_pretty(&serde_json::json!({"rows": result.rows}))?,
                )?;
                timings.push(RuleTiming {
                    rule_id: rule.rule_id.clone(),
                    row_count: result.row_count,
                    elapsed_ms: t0.elapsed().as_millis(),
                    output_path: out_path.display().to_string(),
                    error: None,
                });
                rules_succeeded += 1;
            }
            Err(e) => {
                let err_body = serde_json::json!({"rows": [], "error": e.to_string()});
                let _ = std::fs::write(&out_path, serde_json::to_string_pretty(&err_body)?);
                timings.push(RuleTiming {
                    rule_id: rule.rule_id.clone(),
                    row_count: 0,
                    elapsed_ms: t0.elapsed().as_millis(),
                    output_path: out_path.display().to_string(),
                    error: Some(e.to_string()),
                });
                rules_failed += 1;
            }
        }
    }

    Ok(RuleRunReport {
        rules_run: timings.len(),
        rules_succeeded,
        rules_failed,
        poll_seconds,
        timings,
        total_ms: started.elapsed().as_millis(),
    })
}

async fn history_column_names(ctx: &SessionContext) -> Result<HashSet<String>> {
    let df = ctx.sql("SELECT * FROM history LIMIT 0").await?;
    Ok(df
        .schema()
        .fields()
        .iter()
        .map(|f| f.name().clone())
        .collect())
}

/// Map registry `window_minutes` + poll interval to SQL row-window placeholders.
pub fn derive_window_rows(window_minutes: f64, poll_seconds: f64) -> (u32, u32) {
    let window_minutes = window_minutes.max(1.0);
    let window_rows = ((window_minutes * 60.0 / poll_seconds.max(1.0)).ceil() as u32).max(2);
    (window_rows, window_rows.saturating_sub(1))
}

/// Inject missing optional roles as literals so DataFusion planning succeeds.
///
/// Policy for `loop_enabled`: missing column → `TRUE` (no enable restriction).
/// Other optional roles default to `NULL`. Present-but-null cell semantics remain
/// in the rule SQL (PID-HUNT-1 treats null enable as disabled).
fn project_optional_roles(sql: &str, rule: &RuleSpec, available: &HashSet<String>) -> String {
    let missing: Vec<(&str, &str)> = rule
        .optional_roles
        .iter()
        .filter(|role| !available.contains(role.as_str()))
        .map(|role| {
            let expr = if role == "loop_enabled" {
                "TRUE"
            } else {
                "NULL"
            };
            (role.as_str(), expr)
        })
        .collect();
    if missing.is_empty() {
        return sql.to_string();
    }
    let extras: Vec<String> = missing
        .iter()
        .map(|(role, expr)| format!("{expr} AS {role}"))
        .collect();
    let subquery = format!(
        "(SELECT history.*, {} FROM history) AS history",
        extras.join(", ")
    );
    sql.replace("FROM history", &format!("FROM {subquery}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::RuleSpec;
    use std::collections::HashMap;

    #[test]
    fn injects_missing_loop_enabled_as_true() {
        let rule = RuleSpec {
            rule_id: "PID-HUNT-1".into(),
            sql_file: "pid_hunt_1.sql".into(),
            description: "t".into(),
            required_roles: vec!["control_output_pct".into()],
            optional_roles: vec!["loop_enabled".into()],
            output_columns: vec![],
            confirm_seconds: 0,
            parameters: HashMap::new(),
            parity_status: String::new(),
            dashboard_wired: false,
        };
        let available = HashSet::from(["equipment_id".into(), "timestamp_utc".into()]);
        let sql = "WITH params AS (SELECT 1) SELECT loop_enabled FROM history";
        let out = project_optional_roles(sql, &rule, &available);
        assert!(out.contains("TRUE AS loop_enabled"), "{out}");
        assert!(
            out.contains("FROM (SELECT history.*, TRUE AS loop_enabled FROM history) AS history"),
            "{out}"
        );
    }

    #[test]
    fn window_minutes_changes_derived_row_count() {
        // 60 min @ 60s poll → 60 rows; 15 min → 15 rows; 120 min → 120 rows.
        assert_eq!(derive_window_rows(60.0, 60.0), (60, 59));
        assert_eq!(derive_window_rows(15.0, 60.0), (15, 14));
        assert_eq!(derive_window_rows(120.0, 60.0), (120, 119));
        // 60 min @ 300s poll → 12 rows.
        assert_eq!(derive_window_rows(60.0, 300.0), (12, 11));
    }
}
