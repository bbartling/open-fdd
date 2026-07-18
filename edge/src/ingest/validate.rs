//! Strict CSV ingest validation — fail-closed gate for agent submissions.

use crate::csv_ingest::plan::{ImportPlan, PlanPreview};
use crate::model::csv_import::pivot_alias;
use serde_json::{json, Value};
use std::env;

#[derive(Debug, Clone)]
pub struct ValidationInput<'a> {
    pub session_files: &'a [Value],
    pub plan: Option<&'a ImportPlan>,
    pub preview: Option<&'a PlanPreview>,
    pub validation_report: Option<&'a Value>,
}

pub fn csv_strict_enabled() -> bool {
    match env::var("OPENFDD_CSV_STRICT") {
        Ok(v) => !matches!(v.as_str(), "0" | "false" | "no" | "off"),
        Err(_) => true,
    }
}

pub fn evaluate_csv_session(input: ValidationInput<'_>) -> Value {
    let mut checks: Vec<Value> = Vec::new();
    let mut hints: Vec<String> = Vec::new();

    let mut quarantined_total = 0u64;
    for f in input.session_files {
        let q = f
            .get("profile")
            .and_then(|p| p.get("quarantined"))
            .and_then(|v| v.as_array())
            .map(|a| a.len() as u64)
            .or_else(|| {
                f.get("profile")
                    .and_then(|p| p.get("quarantined_count"))
                    .and_then(|v| v.as_u64())
            })
            .unwrap_or(0);
        quarantined_total += q;
        if q > 0 {
            let name = f.get("filename").and_then(|v| v.as_str()).unwrap_or("?");
            let examples: Vec<Value> = f
                .get("profile")
                .and_then(|p| p.get("quarantined"))
                .and_then(|v| v.as_array())
                .map(|a| a.iter().take(3).cloned().collect())
                .unwrap_or_default();
            checks.push(check(
                "FILE_QUARANTINED",
                "error",
                format!("{name}: {q} row(s) quarantined at parse"),
                q,
                examples,
            ));
        }
    }

    let preview = input.preview;
    let row_count = preview.map(|p| p.row_count).unwrap_or(0);
    if row_count == 0 {
        checks.push(check(
            "ROW_COUNT_ZERO",
            "error",
            "Plan produced zero rows — check timestamp column and value_columns",
            0,
            vec![],
        ));
        hints
            .push("Ensure timestamp_column matches a header and value_columns are numeric.".into());
    }

    if let Some(p) = preview {
        let ta = &p.timestamp_analysis;
        if ta.failed_count > 0 {
            checks.push(check(
                "TIMESTAMP_FAILED",
                "error",
                format!("{} timestamp(s) failed to parse", ta.failed_count),
                ta.failed_count,
                vec![],
            ));
            hints.push(
                "Use consistent timestamp format; prefer naive local + timezone in plan.".into(),
            );
        }
        if ta.ambiguous_count > 0 {
            checks.push(check(
                "TIMESTAMP_AMBIGUOUS",
                "error",
                format!("{} ambiguous DST timestamp(s)", ta.ambiguous_count),
                ta.ambiguous_count,
                vec![],
            ));
        }
        if ta.duplicate_local_count > 0 {
            checks.push(check(
                "TIMESTAMP_DUPLICATE_LOCAL",
                "warn",
                format!("{} duplicate local timestamp(s)", ta.duplicate_local_count),
                ta.duplicate_local_count,
                ta.duplicate_examples
                    .iter()
                    .take(3)
                    .map(|s| json!(s))
                    .collect(),
            ));
        }
        if ta.gap_count > 0 {
            checks.push(check(
                "TIMESTAMP_GAP",
                "warn",
                format!("{} spring-forward gap(s)", ta.gap_count),
                ta.gap_count,
                ta.gap_examples.iter().take(3).map(|s| json!(s)).collect(),
            ));
        }

        // Columns explicitly mapped as equipment ids are identifiers, not values.
        let mapped_equip_cols: Vec<String> = input
            .plan
            .map(|plan| {
                plan.files
                    .iter()
                    .filter_map(|f| f.equipment_id_column.clone())
                    .filter(|c| !c.is_empty())
                    .map(|c| c.to_ascii_lowercase())
                    .collect()
            })
            .unwrap_or_default();
        let numeric_cols: Vec<String> = p
            .column_names
            .iter()
            .filter(|c| {
                let lc = c.to_ascii_lowercase();
                !is_pipeline_metadata_column(&lc)
                    && lc != "timestamp"
                    && lc != "timestamp_utc"
                    && lc != "equipment_id"
                    && lc != "site_id"
                    && !mapped_equip_cols.contains(&lc)
            })
            .cloned()
            .collect();
        if numeric_cols.is_empty() && row_count > 0 {
            checks.push(check(
                "NO_NUMERIC_COLUMNS",
                "error",
                "No value columns mapped — add numeric columns to plan value_columns",
                0,
                vec![],
            ));
        }

        let mut unknown = 0u64;
        let mut unknown_examples: Vec<Value> = Vec::new();
        for col in &numeric_cols {
            if pivot_alias(col).is_none() && !col.starts_with("equip") {
                unknown += 1;
                if unknown_examples.len() < 5 {
                    unknown_examples.push(json!(col));
                }
            }
        }
        if unknown > 0 {
            checks.push(check(
                "COLUMN_UNKNOWN",
                "warn",
                format!("{unknown} column(s) have no standard FDD alias"),
                unknown,
                unknown_examples,
            ));
        }

        let has_equip_col = p
            .column_names
            .iter()
            .any(|c| c.eq_ignore_ascii_case("equipment_id"));
        // An explicit per-file equipment_id_column mapping counts as present.
        if !has_equip_col && mapped_equip_cols.is_empty() {
            if let Some(plan) = input.plan {
                if plan.mode == crate::csv_ingest::plan::OperationMode::Single
                    && plan.files.len() == 1
                {
                    // Severity "info": this documents a defined fallback
                    // (filename-derived equip id) and must not fail-close a
                    // strict execute (#536).
                    checks.push(check(
                        "EQUIPMENT_ID_MISSING",
                        "info",
                        "Wide CSV has no equipment_id column — historian will use filename-derived equip id",
                        0,
                        vec![],
                    ));
                }
            }
        }

        let meta = [
            "ts_utc",
            "ts_local",
            "timezone",
            "source_timestamp_raw",
            "source_timestamp_parse_status",
            "source_file",
            "source_row_number",
            "fill_created",
        ];
        let has_syncable_numeric = p.sample_rows.iter().any(|row| {
            row.as_object().is_some_and(|o| {
                o.iter().any(|(k, v)| {
                    !meta.contains(&k.as_str())
                        && k != "equipment_id"
                        && k != "site_id"
                        && (v.as_f64().is_some()
                            || v.as_str().and_then(|s| s.parse::<f64>().ok()).is_some())
                })
            })
        });
        if row_count > 0
            && !numeric_cols.is_empty()
            && !p.sample_rows.is_empty()
            && !has_syncable_numeric
        {
            checks.push(check(
                "HISTORIAN_SYNC_EMPTY",
                "error",
                "Rows exist but no numeric values would sync to historian — check value_columns",
                row_count,
                vec![],
            ));
            hints.push(
                "Ensure value_columns are numeric and not empty after plan join/fill.".into(),
            );
        }
    }

    if let Some(warnings) = input
        .validation_report
        .and_then(|v| v.get("warnings"))
        .and_then(|v| v.as_array())
    {
        for w in warnings {
            if let Some(s) = w.as_str() {
                if s.contains("timestamp")
                    && !checks.iter().any(|c| c["code"] == "TIMESTAMP_FAILED")
                {
                    checks.push(check("PLAN_WARNING", "warn", s.to_string(), 1, vec![]));
                }
            }
        }
    }

    let has_error = checks.iter().any(|c| c["severity"] == "error");
    let has_warn = checks.iter().any(|c| c["severity"] == "warn");
    let verdict = if has_error {
        "fail"
    } else if has_warn {
        "warn"
    } else {
        "pass"
    };

    let equipment_ids: Vec<String> = preview
        .map(|p| {
            let mut ids = std::collections::BTreeSet::new();
            for row in &p.sample_rows {
                if let Some(id) = row.get("equipment_id").and_then(|v| v.as_str()) {
                    if !id.is_empty() {
                        ids.insert(id.to_string());
                    }
                }
            }
            ids.into_iter().collect()
        })
        .unwrap_or_default();

    json!({
        "ok": !has_error,
        "verdict": verdict,
        "strict": csv_strict_enabled(),
        "checks": checks,
        "summary": {
            "row_count": row_count,
            "quarantined_total": quarantined_total,
            "equipment_ids": equipment_ids,
            "column_count": preview.map(|p| p.column_names.len()).unwrap_or(0)
        },
        "agent_hints": hints
    })
}

/// Importer-internal columns that appear in plan preview but are never FDD roles (#529).
fn is_pipeline_metadata_column(col: &str) -> bool {
    matches!(
        col,
        "ts_utc"
            | "ts_local"
            | "timezone"
            | "source_timestamp_raw"
            | "source_timestamp_parse_status"
            | "source_timestamp_fold"
            | "source_file"
            | "source_row_number"
            | "fill_created"
    )
}

fn check(
    code: &str,
    severity: &str,
    message: impl Into<String>,
    count: u64,
    examples: Vec<Value>,
) -> Value {
    let message = message.into();
    json!({
        "code": code,
        "severity": severity,
        "message": message,
        "count": count,
        "examples": examples
    })
}

pub fn merge_validation_report(
    preview: &PlanPreview,
    session_files: &[Value],
    quarantined_from_stage: u64,
) -> Value {
    let eval = evaluate_csv_session(ValidationInput {
        session_files,
        plan: None,
        preview: Some(preview),
        validation_report: None,
    });
    json!({
        "timestamp_analysis": preview.timestamp_analysis,
        "warnings": preview.warnings,
        "row_count": preview.row_count,
        "quarantined": quarantined_from_stage,
        "verdict": eval.get("verdict"),
        "checks": eval.get("checks"),
        "agent_hints": eval.get("agent_hints")
    })
}

pub fn quarantined_count_from_session(session: &Value) -> u64 {
    let mut total = 0u64;
    if let Some(files) = session.get("files").and_then(|v| v.as_array()) {
        for f in files {
            total += f
                .get("profile")
                .and_then(|p| p.get("quarantined"))
                .and_then(|v| v.as_array())
                .map(|a| a.len() as u64)
                .or_else(|| {
                    f.get("profile")
                        .and_then(|p| p.get("quarantined_count"))
                        .and_then(|v| v.as_u64())
                })
                .unwrap_or(0);
        }
    }
    total
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::csv_ingest::timestamp::TimestampAnalysis;

    #[test]
    fn fails_on_zero_rows() {
        let preview = PlanPreview {
            row_count: 0,
            column_names: vec![],
            sample_rows: vec![],
            timestamp_analysis: TimestampAnalysis::default(),
            warnings: vec![],
            time_range: None,
        };
        let out = evaluate_csv_session(ValidationInput {
            session_files: &[],
            plan: None,
            preview: Some(&preview),
            validation_report: None,
        });
        assert_eq!(out["verdict"], "fail");
    }

    #[test]
    fn passes_clean_preview() {
        let preview = PlanPreview {
            row_count: 100,
            column_names: vec!["timestamp".into(), "oa_t".into(), "equipment_id".into()],
            sample_rows: vec![],
            timestamp_analysis: TimestampAnalysis::default(),
            warnings: vec![],
            time_range: None,
        };
        let out = evaluate_csv_session(ValidationInput {
            session_files: &[],
            plan: None,
            preview: Some(&preview),
            validation_report: None,
        });
        assert_eq!(out["verdict"], "pass");
    }

    #[test]
    fn equipment_id_missing_is_informational_not_blocking() {
        // #536: a plain wide CSV without an equipment_id column must still
        // reach verdict "pass" under strict defaults; the check documents a
        // defined fallback (filename-derived equip id).
        let preview = PlanPreview {
            row_count: 100,
            column_names: vec!["timestamp".into(), "oa_t".into(), "fan_cmd".into()],
            sample_rows: vec![],
            timestamp_analysis: TimestampAnalysis::default(),
            warnings: vec![],
            time_range: None,
        };
        let plan = ImportPlan {
            mode: crate::csv_ingest::plan::OperationMode::Single,
            files: vec![crate::csv_ingest::plan::FileMapping {
                filename: "wide.csv".into(),
                timestamp_column: "timestamp".into(),
                timezone: "UTC".into(),
                value_columns: vec!["oa_t".into(), "fan_cmd".into()],
                equipment_id_column: None,
            }],
            ..Default::default()
        };
        let out = evaluate_csv_session(ValidationInput {
            session_files: &[],
            plan: Some(&plan),
            preview: Some(&preview),
            validation_report: None,
        });
        assert_eq!(out["verdict"], "pass", "{out}");
        let checks = out["checks"].as_array().unwrap();
        let equip = checks
            .iter()
            .find(|c| c["code"] == "EQUIPMENT_ID_MISSING")
            .expect("informational check still surfaces");
        assert_eq!(equip["severity"], "info");
    }

    #[test]
    fn explicit_equipment_id_mapping_suppresses_check() {
        let preview = PlanPreview {
            row_count: 100,
            column_names: vec!["timestamp".into(), "ahu_name".into(), "oa_t".into()],
            sample_rows: vec![],
            timestamp_analysis: TimestampAnalysis::default(),
            warnings: vec![],
            time_range: None,
        };
        let plan = ImportPlan {
            mode: crate::csv_ingest::plan::OperationMode::Single,
            files: vec![crate::csv_ingest::plan::FileMapping {
                filename: "wide.csv".into(),
                timestamp_column: "timestamp".into(),
                timezone: "UTC".into(),
                value_columns: vec!["oa_t".into()],
                equipment_id_column: Some("ahu_name".into()),
            }],
            ..Default::default()
        };
        let out = evaluate_csv_session(ValidationInput {
            session_files: &[],
            plan: Some(&plan),
            preview: Some(&preview),
            validation_report: None,
        });
        assert_eq!(out["verdict"], "pass", "{out}");
        let checks = out["checks"].as_array().unwrap();
        assert!(
            !checks.iter().any(|c| c["code"] == "EQUIPMENT_ID_MISSING"),
            "{out}"
        );
    }

    #[test]
    fn pipeline_metadata_does_not_block_strict_preflight() {
        let preview = PlanPreview {
            row_count: 11,
            column_names: vec![
                "ts_utc".into(),
                "ts_local".into(),
                "timezone".into(),
                "source_file".into(),
                "source_row_number".into(),
                "source_timestamp_raw".into(),
                "source_timestamp_parse_status".into(),
                "duct_static".into(),
                "duct_static_sp".into(),
                "fan_cmd".into(),
            ],
            sample_rows: vec![json!({
                "ts_utc": "2024-01-01T12:00:00Z",
                "duct_static": "0.5",
                "duct_static_sp": "1.4",
                "fan_cmd": "1.0",
                "source_file": "fc1.csv"
            })],
            timestamp_analysis: TimestampAnalysis::default(),
            warnings: vec![],
            time_range: None,
        };
        let out = evaluate_csv_session(ValidationInput {
            session_files: &[],
            plan: None,
            preview: Some(&preview),
            validation_report: None,
        });
        assert_eq!(out["verdict"], "pass", "{out}");
        let checks = out["checks"].as_array().unwrap();
        assert!(
            !checks.iter().any(|c| c["code"] == "COLUMN_UNKNOWN"),
            "{out}"
        );
    }
}
