//! Production SQL rule registry HTTP surface (`sql_rules/registry.yaml` via `fdd_rules`).

use std::path::{Path, PathBuf};

use fdd_rules::{effective_param_strings, load_registry, load_tuning_profiles, RuleSpec};
use serde_json::{json, Value};

/// Resolve directory containing `registry.yaml`.
pub fn sql_rules_dir() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_SQL_RULES_DIR") {
        return PathBuf::from(p);
    }
    let mut candidates = vec![PathBuf::from("sql_rules"), PathBuf::from("/app/sql_rules")];
    if let Ok(manifest) = std::env::var("CARGO_MANIFEST_DIR") {
        let edge_root = PathBuf::from(&manifest);
        candidates.push(edge_root.join("../sql_rules"));
        if let Some(repo) = edge_root.parent() {
            candidates.push(repo.join("sql_rules"));
        }
    }
    for candidate in candidates {
        if candidate.join("registry.yaml").is_file() {
            return candidate;
        }
    }
    PathBuf::from("sql_rules")
}

fn load_rules() -> Result<fdd_rules::RuleRegistry, String> {
    let dir = sql_rules_dir();
    load_registry(&dir).map_err(|e| format!("load registry from {}: {e}", dir.display()))
}

fn rule_to_json(
    rule: &RuleSpec,
    effective: Option<&std::collections::HashMap<String, String>>,
    include_effective: bool,
) -> Value {
    let mut params = Vec::new();
    for (key, def) in &rule.parameters {
        let mut param = json!({
            "key": key,
            "label": def.label,
            "default": def.default,
            "min": def.min,
            "max": def.max,
            "step": def.step,
            "unit": def.unit,
            "control": def.frontend_control,
            "sql_placeholder": def.sql_placeholder,
        });
        if include_effective {
            let effective_val = effective
                .and_then(|m| m.get(&def.sql_placeholder))
                .and_then(|s| s.parse::<f64>().ok())
                .unwrap_or(def.default);
            param["effective"] = json!(effective_val);
        }
        params.push(param);
    }
    json!({
        "rule_id": rule.rule_id,
        "sql_file": rule.sql_file,
        "description": rule.description,
        "required_roles": rule.required_roles,
        "optional_roles": rule.optional_roles,
        "equipment_types": rule.effective_equipment_types(),
        "gate_mode": rule.gate_mode(),
        "output_columns": rule.output_columns,
        "confirm_seconds": rule.confirm_seconds,
        "parity_status": rule.parity_status,
        "dashboard_wired": rule.dashboard_wired,
        "parameters": params,
        "engine": "sql_datafusion",
    })
}

fn tuning_or_error(rules_dir: &Path) -> Result<fdd_rules::TuningLayers, String> {
    load_tuning_profiles(rules_dir)
        .map_err(|e| format!("load tuning from {}: {e}", rules_dir.display()))
}

pub fn list_rules_response() -> Value {
    match load_rules() {
        Ok(reg) => {
            let rules_dir = sql_rules_dir();
            match tuning_or_error(&rules_dir) {
                Ok(tuning) => {
                    let rules: Vec<Value> = reg
                        .rules
                        .iter()
                        .map(|rule| {
                            let effective =
                                effective_param_strings(rule, &tuning, None, None, None).ok();
                            rule_to_json(rule, effective.as_ref(), true)
                        })
                        .collect();
                    json!({
                        "ok": true,
                        "rules_dir": rules_dir.display().to_string(),
                        "rule_count": rules.len(),
                        "rules": rules,
                        "engine": "sql_datafusion",
                        "tuning_ok": true,
                    })
                }
                Err(err) => {
                    let rules: Vec<Value> = reg
                        .rules
                        .iter()
                        .map(|rule| rule_to_json(rule, None, false))
                        .collect();
                    json!({
                        "ok": true,
                        "rules_dir": rules_dir.display().to_string(),
                        "rule_count": rules.len(),
                        "rules": rules,
                        "engine": "sql_datafusion",
                        "tuning_ok": false,
                        "tuning_error": err,
                    })
                }
            }
        }
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn rule_params_response(rule_id: &str) -> Value {
    match load_rules() {
        Ok(reg) => {
            let Some(rule) = reg.rules.iter().find(|r| r.rule_id == rule_id) else {
                return json!({"ok": false, "error": format!("unknown rule_id `{rule_id}`")});
            };
            let rules_dir = sql_rules_dir();
            match tuning_or_error(&rules_dir) {
                Ok(tuning) => {
                    let effective = effective_param_strings(rule, &tuning, None, None, None).ok();
                    json!({
                        "ok": true,
                        "tuning_ok": true,
                        "rule": rule_to_json(rule, effective.as_ref(), true),
                    })
                }
                Err(err) => json!({
                    "ok": true,
                    "tuning_ok": false,
                    "tuning_error": err,
                    "rule": rule_to_json(rule, None, false),
                }),
            }
        }
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn cache_status_response(parquet_root: &Path) -> Value {
    let manifest = parquet_root.join("manifest.json");
    let mut out = json!({
        "ok": true,
        "parquet_root": parquet_root.display().to_string(),
        "manifest_present": manifest.is_file(),
        "equipment_parquet_files": 0usize,
    });
    if manifest.is_file() {
        if let Ok(text) = std::fs::read_to_string(&manifest) {
            if let Ok(v) = serde_json::from_str::<Value>(&text) {
                out["manifest"] = v;
            }
        }
    }
    if parquet_root.is_dir() {
        let count = std::fs::read_dir(parquet_root)
            .ok()
            .map(|rd| {
                rd.filter_map(|e| e.ok())
                    .filter(|e| {
                        e.path()
                            .file_name()
                            .and_then(|n| n.to_str())
                            .map(|n| n.ends_with(".parquet"))
                            .unwrap_or(false)
                    })
                    .count()
            })
            .unwrap_or(0);
        out["equipment_parquet_files"] = json!(count);
    }
    out
}

/// Batch-execute every production registry rule against a Parquet cache.
///
/// Per-rule failures are isolated (`ERROR` / `SKIPPED_*` statuses). Callers must
/// supply a readable parquet root (typically `OPENFDD_PARQUET_CACHE`).
pub fn run_registry_batch_response(parquet_root: &Path, out_dir: &Path) -> Value {
    let rules_dir = sql_rules_dir();
    let registry = match load_registry(&rules_dir) {
        Ok(r) => r,
        Err(e) => {
            return json!({
                "ok": false,
                "error": format!("load registry from {}: {e}", rules_dir.display()),
            });
        }
    };
    if !parquet_root.exists() {
        return json!({
            "ok": false,
            "error": format!("parquet root missing: {}", parquet_root.display()),
            "hint": "Ingest a dataset first or set OPENFDD_PARQUET_CACHE",
        });
    }
    let rt = match tokio::runtime::Runtime::new() {
        Ok(rt) => rt,
        Err(e) => return json!({"ok": false, "error": format!("tokio runtime: {e}")}),
    };
    match rt.block_on(fdd_rules::run_all_rules(parquet_root, &registry, out_dir)) {
        Ok(report) => json!({
            "ok": true,
            "engine": "sql_datafusion",
            "rules_dir": rules_dir.display().to_string(),
            "parquet_root": parquet_root.display().to_string(),
            "out_dir": out_dir.display().to_string(),
            "rules_run": report.rules_run,
            "rules_succeeded": report.rules_succeeded,
            "rules_failed": report.rules_failed,
            "rules_skipped": report.rules_skipped,
            "poll_seconds": report.poll_seconds,
            "total_ms": report.total_ms,
            "timings": report.timings,
        }),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

/// Load cached per-equipment rollup JSON for one rule (`{out_dir}/{rule_id}.json`).
pub fn rule_result_response(out_dir: &Path, rule_id: &str) -> Value {
    if !rule_id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return json!({"ok": false, "error": "invalid rule_id"});
    }
    let path = out_dir.join(format!("{rule_id}.json"));
    match std::fs::read_to_string(&path) {
        Ok(text) => match serde_json::from_str::<Value>(&text) {
            Ok(body) => json!({
                "ok": true,
                "rule_id": rule_id,
                "path": path.display().to_string(),
                "result": body,
            }),
            Err(e) => json!({"ok": false, "error": format!("parse {}: {e}", path.display())}),
        },
        Err(e) => json!({
            "ok": false,
            "error": format!("read {}: {e}", path.display()),
            "hint": "Run batch analytics first (POST /api/fdd/run mode=registry)",
        }),
    }
}

/// Sample-level gate/raw/confirmed series for Plotly FaultTimeline.
pub fn rule_series_response(
    parquet_root: &Path,
    rule_id: &str,
    equipment_id: &str,
    max_points: usize,
) -> Value {
    let rules_dir = sql_rules_dir();
    let registry = match load_registry(&rules_dir) {
        Ok(r) => r,
        Err(e) => {
            return json!({
                "ok": false,
                "error": format!("load registry from {}: {e}", rules_dir.display()),
            });
        }
    };
    if !parquet_root.exists() {
        return json!({
            "ok": false,
            "error": format!("parquet root missing: {}", parquet_root.display()),
        });
    }
    let rt = match tokio::runtime::Runtime::new() {
        Ok(rt) => rt,
        Err(e) => return json!({"ok": false, "error": format!("tokio runtime: {e}")}),
    };
    match rt.block_on(fdd_rules::run_rule_equipment_series(
        parquet_root,
        &registry,
        rule_id,
        equipment_id,
        max_points,
    )) {
        Ok(v) => v,
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

/// Motor runtime hours analytics rollup (Vibe19 Overview motor_hours overlap).
pub fn motor_hours_response(parquet_root: &Path) -> Value {
    if !parquet_root.exists() {
        return json!({
            "ok": false,
            "error": format!("parquet root missing: {}", parquet_root.display()),
        });
    }
    let rt = match tokio::runtime::Runtime::new() {
        Ok(rt) => rt,
        Err(e) => return json!({"ok": false, "error": format!("tokio runtime: {e}")}),
    };
    match rt.block_on(fdd_rules::compute_motor_hours(parquet_root)) {
        Ok(rows) => fdd_rules::motor_hours_to_json(&rows),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

/// Weekly motor hours rollup (Vibe19 `motor_run_hours_weekly` overlap).
pub fn motor_weekly_response(parquet_root: &Path) -> Value {
    if !parquet_root.exists() {
        return json!({
            "ok": false,
            "error": format!("parquet root missing: {}", parquet_root.display()),
        });
    }
    let rt = match tokio::runtime::Runtime::new() {
        Ok(rt) => rt,
        Err(e) => return json!({"ok": false, "error": format!("tokio runtime: {e}")}),
    };
    match rt.block_on(fdd_rules::compute_motor_weekly(parquet_root)) {
        Ok(rows) => fdd_rules::motor_weekly_to_json(&rows),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

/// Mechanical cooling OAT bins (Vibe19 `mech_cooling_oat_bins` overlap).
pub fn mech_cooling_oat_bins_response(parquet_root: &Path) -> Value {
    if !parquet_root.exists() {
        return json!({
            "ok": false,
            "error": format!("parquet root missing: {}", parquet_root.display()),
        });
    }
    let rt = match tokio::runtime::Runtime::new() {
        Ok(rt) => rt,
        Err(e) => return json!({"ok": false, "error": format!("tokio runtime: {e}")}),
    };
    match rt.block_on(fdd_rules::compute_mech_cooling_oat_bins(parquet_root)) {
        Ok(rows) => fdd_rules::mech_cooling_oat_bins_to_json(&rows),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn list_rules_loads_from_repo_sql_rules() {
        let resp = list_rules_response();
        assert_eq!(resp.get("ok"), Some(&json!(true)), "{resp}");
        let count = resp.get("rule_count").and_then(|v| v.as_u64()).unwrap_or(0);
        assert!(
            count >= 55,
            "expected full registry (55 rules), got {count}"
        );
    }
}
