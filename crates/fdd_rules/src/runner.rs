use std::collections::HashMap;
use std::path::Path;

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, register_weather_if_present, run_sql};
use serde::Serialize;

use crate::params::{read_poll_from_cache, rule_params, substitute_sql};
use crate::registry::RuleRegistry;
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
    run_all_rules_with_overrides(parquet_root, registry, out_dir, &HashMap::new(), None, None).await
}

/// Run registry rules with request/session parameter overrides.
///
/// Keys are canonical rule IDs and registry parameter names. This keeps the
/// HTTP layer typed: arbitrary SQL is never accepted from the dashboard.
///
/// ``weather_root`` defaults to ``parquet_root``. When history is scoped to
/// ``building={id}/``, pass the parent parquet cache so ``weather/`` still registers.
pub async fn run_all_rules_with_overrides(
    parquet_root: &Path,
    registry: &RuleRegistry,
    out_dir: &Path,
    overrides: &HashMap<String, HashMap<String, f64>>,
    equipment_filter: Option<&str>,
    weather_root: Option<&Path>,
) -> Result<RuleRunReport> {
    let started = std::time::Instant::now();
    std::fs::create_dir_all(out_dir)?;
    let poll_seconds = read_poll_from_cache(parquet_root)
        .or_else(|| weather_root.and_then(read_poll_from_cache))
        .unwrap_or(300.0);
    let rules_dir = Path::new(&registry.rules_dir);
    let tuning = load_tuning_profiles(rules_dir)?;

    let ctx = SessionContext::new();
    register_parquet_tree(&ctx, parquet_root).await?;
    let wx_root = weather_root.unwrap_or(parquet_root);
    register_weather_if_present(&ctx, wx_root).await?;

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
        let confirm_secs = rule.confirm_seconds;
        let mut params = rule_params(poll_seconds, confirm_secs);
        let session_override = overrides.get(&rule.rule_id);
        if let Ok(tuned) = effective_param_strings(rule, &tuning, None, None, session_override) {
            for (k, v) in tuned {
                // Do not let registry parameter defaults for CONFIRM_* wipe the
                // confirm window already applied via rule.confirm_seconds /
                // confirm_min (soak BUG-2). Session overrides for confirm_seconds
                // are already merged into rule.confirm_seconds by the API layer.
                if k == "CONFIRM_SECONDS" || k == "CONFIRM_ROWS" {
                    continue;
                }
                params.insert(k, v);
            }
        }
        // Always re-assert confirm from the (possibly mutated) rule spec.
        let confirm_params = rule_params(poll_seconds, rule.confirm_seconds);
        for (k, v) in confirm_params {
            params.insert(k, v);
        }
        let mut sql = substitute_sql(&raw_sql, &params);
        if let Some(equipment_id) = equipment_filter {
            let escaped = equipment_id.replace('\'', "''");
            sql = format!(
                "SELECT * FROM ({}) filtered_rule WHERE equipment_id = '{}'",
                sql.trim().trim_end_matches(';'),
                escaped
            );
        }
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
