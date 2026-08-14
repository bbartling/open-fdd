use std::collections::HashMap;
use std::path::Path;

use anyhow::Result;
use datafusion::prelude::*;
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
    /// Rules skipped because required roles/columns (or the weather table) were
    /// absent — a pandas-style skip, not a hard failure (OFDD-066/068).
    #[serde(default)]
    pub rules_skipped: usize,
    pub poll_seconds: f64,
    pub timings: Vec<RuleTiming>,
    pub total_ms: u128,
}

/// Classify a DataFusion error string as a missing-schema (skip) condition
/// rather than a genuine rule failure. Covers missing history columns and a
/// missing/unregistered `weather` table.
fn is_missing_schema_error(msg: &str) -> bool {
    let m = msg.to_ascii_lowercase();
    m.contains("no field named")
        || m.contains("schema error")
        || m.contains("column") && m.contains("not found")
        || m.contains("table 'weather'")
        || m.contains("table \"weather\"")
        || m.contains("'weather' not found")
        || (m.contains("weather") && m.contains("not found"))
}

/// Write a pandas-shaped SKIPPED_MISSING_ROLES marker for a rule that could not
/// run because required roles/columns were absent.
fn write_skip_marker(out_path: &Path, missing_roles: &[String], note: &str) -> std::io::Result<()> {
    let body = serde_json::json!({
        "rows": [{
            "status": "SKIPPED_MISSING_ROLES",
            "missing_roles": missing_roles,
            "notes": note,
        }],
        "status": "SKIPPED_MISSING_ROLES",
        "missing_roles": missing_roles,
        "skipped": true,
    });
    std::fs::write(out_path, serde_json::to_string_pretty(&body)?)
}

/// Inject NULL columns for optional roles missing from history via a WITH CTE
/// (TEMP VIEW is not available in all DataFusion builds used by tests).
/// String roles such as `occ_mode` use VARCHAR; numeric proof roles use DOUBLE.
fn sql_with_optional_null_roles(
    rule_id: &str,
    sql: &str,
    optional_roles: &[String],
    history_columns: &std::collections::HashSet<String>,
    history_table: &str,
) -> String {
    let missing: Vec<String> = optional_roles
        .iter()
        .filter(|role| !history_columns.contains(&role.to_ascii_lowercase()))
        .cloned()
        .collect();
    if missing.is_empty() {
        return sql.to_string();
    }
    let _ = rule_id;
    let null_cols: String = missing
        .iter()
        .map(|r| {
            let ty = if r.eq_ignore_ascii_case("occ_mode") {
                "VARCHAR"
            } else {
                "DOUBLE"
            };
            format!("CAST(NULL AS {ty}) AS \"{r}\"")
        })
        .collect::<Vec<_>>()
        .join(", ");
    let cte =
        format!("history_opt AS (SELECT {history_table}.*, {null_cols} FROM {history_table})");
    let from = format!(" FROM {history_table}");
    let from_nl = format!("\nFROM {history_table}");
    let rewritten = sql
        .replace(&from, " FROM history_opt")
        .replace(&from.to_ascii_lowercase(), " FROM history_opt")
        .replace(&from_nl, "\nFROM history_opt")
        .replace(&from_nl.to_ascii_lowercase(), "\nFROM history_opt");
    if let Some(idx) = rewritten.find("WITH ") {
        let (pre, rest) = rewritten.split_at(idx);
        let rest = rest.trim_start_matches("WITH ");
        format!("{pre}WITH {cte}, {rest}")
    } else if let Some(idx) = rewritten.find("with ") {
        let (pre, rest) = rewritten.split_at(idx);
        let rest = rest.trim_start_matches("with ");
        format!("{pre}WITH {cte}, {rest}")
    } else {
        format!("WITH {cte} {rewritten}")
    }
}

pub async fn run_all_rules(
    parquet_root: &Path,
    registry: &RuleRegistry,
    out_dir: &Path,
) -> Result<RuleRunReport> {
    run_all_rules_with_overrides(
        parquet_root,
        registry,
        out_dir,
        &HashMap::new(),
        None,
        None,
        None,
    )
    .await
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
    unit_system: Option<&str>,
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

    // History columns for preflighting required_roles (case-insensitive). When
    // history cannot be described we fall back to per-rule SQL error classifying.
    let history_names: Vec<String> = match ctx.table("history").await {
        Ok(df) => df
            .schema()
            .fields()
            .iter()
            .map(|f| f.name().to_string())
            .collect(),
        Err(_) => Vec::new(),
    };
    let history_columns: std::collections::HashSet<String> = history_names
        .iter()
        .map(|n| n.to_ascii_lowercase())
        .collect();
    let weather_names: Vec<String> = match ctx.table("weather").await {
        Ok(df) => df
            .schema()
            .fields()
            .iter()
            .map(|f| f.name().to_string())
            .collect(),
        Err(_) => Vec::new(),
    };

    let mut timings = Vec::new();
    let mut rules_succeeded = 0usize;
    let mut rules_failed = 0usize;
    let mut rules_skipped = 0usize;
    for rule in &registry.rules {
        let sql_path = rules_dir.join(&rule.sql_file);
        let t0 = std::time::Instant::now();
        let out_path = out_dir.join(format!("{}.json", rule.rule_id));

        // Preflight: skip (do not fail) when required roles are absent from the
        // history schema. Weather-only misses surface via SQL error classifying.
        if !history_columns.is_empty() {
            let missing: Vec<String> = rule
                .required_roles
                .iter()
                .filter(|role| !history_columns.contains(&role.to_ascii_lowercase()))
                .cloned()
                .collect();
            if !missing.is_empty() {
                let note = format!("missing roles/columns in history: {}", missing.join(", "));
                let _ = write_skip_marker(&out_path, &missing, &note);
                timings.push(RuleTiming {
                    rule_id: rule.rule_id.clone(),
                    row_count: 0,
                    elapsed_ms: t0.elapsed().as_millis(),
                    output_path: out_path.display().to_string(),
                    error: Some(format!("SKIPPED_MISSING_ROLES: {note}")),
                });
                rules_skipped += 1;
                continue;
            }
        }
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
        let units = unit_system.unwrap_or("imperial");
        sql = fdd_core::sql_with_metric_to_imperial(&sql, &history_names, &weather_names, units);
        let history_table = if fdd_core::is_metric_unit_system(units) {
            "history_si"
        } else {
            "history"
        };
        sql = sql_with_optional_null_roles(
            &rule.rule_id,
            &sql,
            &rule.optional_roles,
            &history_columns,
            history_table,
        );
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
                let msg = e.to_string();
                if is_missing_schema_error(&msg) {
                    // Schema/weather miss classified at runtime → skip, not fail
                    // (OFDD-066/068). Keeps Liberty runs at rules_failed == 0.
                    let note = format!("schema miss: {msg}");
                    let _ = write_skip_marker(&out_path, &rule.required_roles, &note);
                    timings.push(RuleTiming {
                        rule_id: rule.rule_id.clone(),
                        row_count: 0,
                        elapsed_ms: t0.elapsed().as_millis(),
                        output_path: out_path.display().to_string(),
                        error: Some(format!("SKIPPED_MISSING_ROLES: {note}")),
                    });
                    rules_skipped += 1;
                } else {
                    let err_body = serde_json::json!({"rows": [], "error": msg});
                    let _ = std::fs::write(&out_path, serde_json::to_string_pretty(&err_body)?);
                    timings.push(RuleTiming {
                        rule_id: rule.rule_id.clone(),
                        row_count: 0,
                        elapsed_ms: t0.elapsed().as_millis(),
                        output_path: out_path.display().to_string(),
                        error: Some(msg),
                    });
                    rules_failed += 1;
                }
            }
        }
    }

    Ok(RuleRunReport {
        rules_run: timings.len(),
        rules_succeeded,
        rules_failed,
        rules_skipped,
        poll_seconds,
        timings,
        total_ms: started.elapsed().as_millis(),
    })
}
