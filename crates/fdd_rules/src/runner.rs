use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::Result;
use datafusion::prelude::SessionContext;
use fdd_sql::{register_parquet_tree, register_weather_if_present, run_sql};
use serde::Serialize;
use serde_json::{json, Value};

use crate::params::{read_poll_from_cache, rule_params, substitute_sql};
use crate::registry::{RuleRegistry, RuleSpec};
use crate::status::{equipment_is_applicable, infer_equipment_type, RuleStatus};
use crate::tuning::{assert_sql_placeholders, effective_param_strings, load_tuning_profiles};

#[derive(Debug, Clone, Serialize)]
pub struct RuleTiming {
    pub rule_id: String,
    pub row_count: usize,
    pub elapsed_ms: u128,
    pub output_path: String,
    /// Canonical result status for this rule attempt.
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuleRunReport {
    pub rules_run: usize,
    pub rules_succeeded: usize,
    pub rules_failed: usize,
    pub rules_skipped: usize,
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
    let equipment_ids = list_equipment_ids(&ctx).await.unwrap_or_default();
    let active_by_equip = active_sample_counts(&ctx, &history_columns)
        .await
        .unwrap_or_default();

    let mut timings = Vec::new();
    let mut rules_succeeded = 0usize;
    let mut rules_failed = 0usize;
    let mut rules_skipped = 0usize;
    for rule in &registry.rules {
        let sql_path = rules_dir.join(&rule.sql_file);
        let t0 = std::time::Instant::now();
        let out_path = out_dir.join(format!("{}.json", rule.rule_id));

        // 1. Validate rule metadata / SQL asset
        let raw_sql = match std::fs::read_to_string(&sql_path) {
            Ok(s) => s,
            Err(e) => {
                let _ = std::fs::write(
                    &out_path,
                    serde_json::to_string_pretty(&json!({
                        "rows": [],
                        "status": RuleStatus::Error.as_str(),
                        "error": e.to_string(),
                    }))?,
                );
                push_timing(
                    &mut timings,
                    &mut rules_failed,
                    rule,
                    &out_path,
                    t0,
                    RuleStatus::Error,
                    0,
                    Some(e.to_string()),
                );
                continue;
            }
        };
        if let Err(e) = assert_sql_placeholders(&raw_sql, rule) {
            let _ = std::fs::write(
                &out_path,
                serde_json::to_string_pretty(&json!({
                    "rows": [],
                    "status": RuleStatus::Error.as_str(),
                    "error": e.to_string(),
                }))?,
            );
            push_timing(
                &mut timings,
                &mut rules_failed,
                rule,
                &out_path,
                t0,
                RuleStatus::Error,
                0,
                Some(e.to_string()),
            );
            continue;
        }

        let rule_types = rule.effective_equipment_types();

        // 2. Equipment applicability (before missing-role skip)
        let applicable_ids: Vec<String> = equipment_ids
            .iter()
            .filter(|id| {
                let et = infer_equipment_type(id);
                equipment_is_applicable(&rule_types, &et)
            })
            .cloned()
            .collect();
        if !equipment_ids.is_empty() && applicable_ids.is_empty() {
            let body = json!({
                "rows": equipment_ids.iter().map(|id| json!({
                    "equipment_id": id,
                    "equipment_type": infer_equipment_type(id),
                    "status": RuleStatus::NotApplicableEquipmentType.as_str(),
                    "fault_hours": Value::Null,
                    "reason": format!("rule applies to {:?}, equipment is {}", rule_types, infer_equipment_type(id)),
                })).collect::<Vec<_>>(),
                "status": RuleStatus::NotApplicableEquipmentType.as_str(),
                "equipment_types": rule_types,
            });
            let _ = std::fs::write(&out_path, serde_json::to_string_pretty(&body)?);
            push_timing(
                &mut timings,
                &mut rules_skipped,
                rule,
                &out_path,
                t0,
                RuleStatus::NotApplicableEquipmentType,
                equipment_ids.len(),
                None,
            );
            continue;
        }

        // 3. Required roles
        let missing_required: Vec<&str> = rule
            .required_roles
            .iter()
            .filter(|role| !history_columns.contains(role.as_str()))
            .map(|s| s.as_str())
            .collect();
        if !missing_required.is_empty() {
            let body = json!({
                "rows": [],
                "status": RuleStatus::SkippedMissingRoles.as_str(),
                "missing_roles": missing_required,
            });
            let _ = std::fs::write(&out_path, serde_json::to_string_pretty(&body)?);
            push_timing(
                &mut timings,
                &mut rules_skipped,
                rule,
                &out_path,
                t0,
                RuleStatus::SkippedMissingRoles,
                0,
                None,
            );
            continue;
        }

        // 4–10. Optional roles → params → SQL → gate → confirm (in SQL) → aggregate
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
                let annotated = annotate_result_rows(
                    rule,
                    &rule_types,
                    &equipment_ids,
                    &applicable_ids,
                    &active_by_equip,
                    &result.rows,
                );
                let statuses: Vec<RuleStatus> = annotated
                    .iter()
                    .filter_map(|r| {
                        r.get("status")
                            .and_then(|v| v.as_str())
                            .and_then(RuleStatus::parse)
                    })
                    .collect();
                let status = RuleStatus::aggregate(&statuses);
                let body = json!({
                    "rows": annotated,
                    "status": status.as_str(),
                    "equipment_types": rule_types,
                    "gate_mode": rule.gate_mode(),
                });
                std::fs::write(&out_path, serde_json::to_string_pretty(&body)?)?;
                let counter = match status {
                    RuleStatus::Error => &mut rules_failed,
                    RuleStatus::SkippedMissingRoles
                    | RuleStatus::SkippedEquipmentOff
                    | RuleStatus::NotApplicableEquipmentType => &mut rules_skipped,
                    RuleStatus::Pass | RuleStatus::Fault => &mut rules_succeeded,
                };
                push_timing(
                    &mut timings,
                    counter,
                    rule,
                    &out_path,
                    t0,
                    status,
                    annotated.len(),
                    None,
                );
            }
            Err(e) => {
                let err_body = json!({
                    "rows": [],
                    "status": RuleStatus::Error.as_str(),
                    "error": e.to_string(),
                });
                let _ = std::fs::write(&out_path, serde_json::to_string_pretty(&err_body)?);
                push_timing(
                    &mut timings,
                    &mut rules_failed,
                    rule,
                    &out_path,
                    t0,
                    RuleStatus::Error,
                    0,
                    Some(e.to_string()),
                );
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

fn push_timing(
    timings: &mut Vec<RuleTiming>,
    counter: &mut usize,
    rule: &RuleSpec,
    out_path: &Path,
    t0: std::time::Instant,
    status: RuleStatus,
    row_count: usize,
    error: Option<String>,
) {
    timings.push(RuleTiming {
        rule_id: rule.rule_id.clone(),
        row_count,
        elapsed_ms: t0.elapsed().as_millis(),
        output_path: out_path.display().to_string(),
        status: status.as_str().to_string(),
        error,
    });
    *counter += 1;
}

/// Attach per-equipment six-status after SQL execution.
fn annotate_result_rows(
    rule: &RuleSpec,
    rule_types: &[String],
    all_equipment: &[String],
    applicable_ids: &[String],
    active_by_equip: &HashMap<String, u64>,
    sql_rows: &[Value],
) -> Vec<Value> {
    let mut by_id: HashMap<String, Value> = HashMap::new();
    for row in sql_rows {
        if let Some(id) = row.get("equipment_id").and_then(|v| v.as_str()) {
            by_id.insert(id.to_string(), row.clone());
        }
    }

    let gate = rule.gate_mode().to_ascii_uppercase();
    let mut out = Vec::new();

    // Ensure every known equipment appears once.
    let mut ids: Vec<String> = all_equipment.to_vec();
    for id in by_id.keys() {
        if !ids.iter().any(|x| x == id) {
            ids.push(id.clone());
        }
    }
    ids.sort();

    for id in ids {
        let et = infer_equipment_type(&id);
        if !equipment_is_applicable(rule_types, &et) {
            out.push(json!({
                "equipment_id": id,
                "equipment_type": et,
                "status": RuleStatus::NotApplicableEquipmentType.as_str(),
                "fault_hours": Value::Null,
                "active_samples": active_by_equip.get(&id).copied().unwrap_or(0),
                "reason": format!("rule applies to {rule_types:?}"),
            }));
            continue;
        }
        if !applicable_ids.is_empty() && !applicable_ids.iter().any(|a| a == &id) {
            out.push(json!({
                "equipment_id": id,
                "equipment_type": et,
                "status": RuleStatus::NotApplicableEquipmentType.as_str(),
                "fault_hours": Value::Null,
            }));
            continue;
        }

        let active = active_by_equip.get(&id).copied().unwrap_or(0);
        // 5–7. Operational gate / startup: RUN with zero proven-on samples → OFF
        if gate == "RUN" && active == 0 {
            out.push(json!({
                "equipment_id": id,
                "equipment_type": et,
                "status": RuleStatus::SkippedEquipmentOff.as_str(),
                "fault_hours": Value::Null,
                "active_samples": 0,
                "gate_mode": rule.gate_mode(),
                "reason": "equipment not proven operating during analysis window",
            }));
            continue;
        }

        let mut row = by_id.remove(&id).unwrap_or_else(|| {
            json!({
                "equipment_id": id,
                "fault_hours": 0.0,
            })
        });
        let fault_hours = row
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let status = if fault_hours > 0.0 {
            RuleStatus::Fault
        } else {
            RuleStatus::Pass
        };
        if let Some(obj) = row.as_object_mut() {
            obj.insert("equipment_type".into(), json!(et));
            obj.insert("status".into(), json!(status.as_str()));
            obj.insert("active_samples".into(), json!(active));
            obj.insert("gate_mode".into(), json!(rule.gate_mode()));
        }
        out.push(row);
    }
    out
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

async fn list_equipment_ids(ctx: &SessionContext) -> Result<Vec<String>> {
    let result = run_sql(
        ctx,
        "SELECT DISTINCT equipment_id FROM history ORDER BY equipment_id",
    )
    .await?;
    Ok(result
        .rows
        .iter()
        .filter_map(|r| {
            r.get("equipment_id")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
        })
        .collect())
}

/// Count samples where equipment has operational proof (fan/cmd/status heuristics).
async fn active_sample_counts(
    ctx: &SessionContext,
    columns: &HashSet<String>,
) -> Result<HashMap<String, u64>> {
    let mut expr_parts = Vec::new();
    if columns.contains("fan_cmd") {
        expr_parts.push(
            "(CASE WHEN fan_cmd IS NULL THEN 0 WHEN fan_cmd > 1.0 THEN CASE WHEN fan_cmd >= 5.0 THEN 1 ELSE 0 END ELSE CASE WHEN fan_cmd >= 0.05 THEN 1 ELSE 0 END END)",
        );
    }
    if columns.contains("fan_status") {
        expr_parts.push(
            "(CASE WHEN fan_status IS NULL THEN 0 WHEN TRIM(CAST(fan_status AS VARCHAR)) IN ('1','1.0','true','TRUE','on','ON') THEN 1 ELSE 0 END)",
        );
    }
    if columns.contains("pump_cmd") {
        expr_parts.push(
            "(CASE WHEN pump_cmd IS NULL THEN 0 WHEN pump_cmd > 1.0 THEN CASE WHEN pump_cmd >= 5.0 THEN 1 ELSE 0 END ELSE CASE WHEN pump_cmd >= 0.05 THEN 1 ELSE 0 END END)",
        );
    }
    if expr_parts.is_empty() {
        // No operational proof columns — treat all samples as active (ALWAYS-safe default).
        let result = run_sql(
            ctx,
            "SELECT equipment_id, COUNT(*) AS active_samples FROM history GROUP BY equipment_id",
        )
        .await?;
        return Ok(parse_active_map(&result.rows));
    }
    let proof = expr_parts.join(" + ");
    let sql = format!(
        "SELECT equipment_id, SUM(CASE WHEN ({proof}) > 0 THEN 1 ELSE 0 END) AS active_samples FROM history GROUP BY equipment_id"
    );
    let result = run_sql(ctx, &sql).await?;
    Ok(parse_active_map(&result.rows))
}

fn parse_active_map(rows: &[Value]) -> HashMap<String, u64> {
    let mut out = HashMap::new();
    for row in rows {
        let Some(id) = row.get("equipment_id").and_then(|v| v.as_str()) else {
            continue;
        };
        let n = row
            .get("active_samples")
            .and_then(|v| v.as_u64().or_else(|| v.as_f64().map(|f| f as u64)))
            .unwrap_or(0);
        out.insert(id.to_string(), n);
    }
    out
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
/// Other optional roles default to typed `CAST(NULL AS DOUBLE)` so window
/// arithmetic (`max - min`) type-checks when the physical column is absent.
/// Present-but-null cell semantics remain in the rule SQL.
fn project_optional_roles(sql: &str, rule: &RuleSpec, available: &HashSet<String>) -> String {
    let missing: Vec<(&str, &str)> = rule
        .optional_roles
        .iter()
        .filter(|role| !available.contains(role.as_str()))
        .map(|role| {
            let expr = if role == "loop_enabled" {
                "TRUE"
            } else {
                "CAST(NULL AS DOUBLE)"
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

    fn bare_rule(id: &str, optional: Vec<String>) -> RuleSpec {
        RuleSpec {
            rule_id: id.into(),
            sql_file: format!("{}.sql", id.to_ascii_lowercase()),
            description: "t".into(),
            required_roles: vec![],
            optional_roles: optional,
            equipment_types: vec![],
            output_columns: vec![],
            confirm_seconds: 0,
            parameters: HashMap::new(),
            parity_status: String::new(),
            dashboard_wired: false,
            operational_gate: None,
        }
    }

    #[test]
    fn injects_missing_loop_enabled_as_true() {
        let rule = RuleSpec {
            required_roles: vec!["control_output_pct".into()],
            optional_roles: vec!["loop_enabled".into()],
            ..bare_rule("PID-HUNT-1", vec!["loop_enabled".into()])
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
    fn injects_typed_null_for_missing_numeric_optional_roles() {
        let rule = bare_rule(
            "SV-FLATLINE",
            vec!["chw_supply_t".into(), "loop_enabled".into()],
        );
        let available = HashSet::from(["equipment_id".into(), "timestamp_utc".into()]);
        let sql = "SELECT chw_supply_t FROM history";
        let out = project_optional_roles(sql, &rule, &available);
        assert!(
            out.contains("CAST(NULL AS DOUBLE) AS chw_supply_t"),
            "{out}"
        );
        assert!(out.contains("TRUE AS loop_enabled"), "{out}");
    }

    #[test]
    fn window_minutes_changes_derived_row_count() {
        assert_eq!(derive_window_rows(60.0, 60.0), (60, 59));
        assert_eq!(derive_window_rows(15.0, 60.0), (15, 14));
        assert_eq!(derive_window_rows(120.0, 60.0), (120, 119));
        assert_eq!(derive_window_rows(60.0, 300.0), (12, 11));
    }

    #[test]
    fn annotate_marks_vav_not_applicable_for_ahu_rule() {
        let mut rule = bare_rule("FC8", vec![]);
        rule.equipment_types = vec!["AHU".into()];
        rule.operational_gate = Some(crate::registry::OperationalGate {
            mode: "RUN".into(),
            ..Default::default()
        });
        let rows = annotate_result_rows(
            &rule,
            &["AHU".into()],
            &["AHU_1".into(), "VAV_1".into()],
            &["AHU_1".into()],
            &HashMap::from([("AHU_1".into(), 10u64), ("VAV_1".into(), 10u64)]),
            &[json!({"equipment_id": "AHU_1", "fault_hours": 0.0})],
        );
        let vav = rows
            .iter()
            .find(|r| r.get("equipment_id").and_then(|v| v.as_str()) == Some("VAV_1"))
            .unwrap();
        assert_eq!(
            vav.get("status").and_then(|v| v.as_str()),
            Some("NOT_APPLICABLE_EQUIPMENT_TYPE")
        );
        let ahu = rows
            .iter()
            .find(|r| r.get("equipment_id").and_then(|v| v.as_str()) == Some("AHU_1"))
            .unwrap();
        assert_eq!(ahu.get("status").and_then(|v| v.as_str()), Some("PASS"));
    }

    #[test]
    fn annotate_marks_run_gate_off_when_no_active_samples() {
        let mut rule = bare_rule("FC8", vec![]);
        rule.equipment_types = vec!["AHU".into()];
        rule.operational_gate = Some(crate::registry::OperationalGate {
            mode: "RUN".into(),
            ..Default::default()
        });
        let rows = annotate_result_rows(
            &rule,
            &["AHU".into()],
            &["AHU_OFF".into()],
            &["AHU_OFF".into()],
            &HashMap::from([("AHU_OFF".into(), 0u64)]),
            &[json!({"equipment_id": "AHU_OFF", "fault_hours": 0.0})],
        );
        assert_eq!(
            rows[0].get("status").and_then(|v| v.as_str()),
            Some("SKIPPED_EQUIPMENT_OFF")
        );
    }
}
