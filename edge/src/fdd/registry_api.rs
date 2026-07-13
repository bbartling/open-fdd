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
) -> Value {
    let mut params = Vec::new();
    for (key, def) in &rule.parameters {
        let effective_val = effective
            .and_then(|m| m.get(&def.sql_placeholder))
            .and_then(|s| s.parse::<f64>().ok())
            .unwrap_or(def.default);
        params.push(json!({
            "key": key,
            "label": def.label,
            "default": def.default,
            "min": def.min,
            "max": def.max,
            "step": def.step,
            "unit": def.unit,
            "control": def.frontend_control,
            "sql_placeholder": def.sql_placeholder,
            "effective": effective_val,
        }));
    }
    json!({
        "rule_id": rule.rule_id,
        "sql_file": rule.sql_file,
        "description": rule.description,
        "required_roles": rule.required_roles,
        "optional_roles": rule.optional_roles,
        "output_columns": rule.output_columns,
        "confirm_seconds": rule.confirm_seconds,
        "parity_status": rule.parity_status,
        "dashboard_wired": rule.dashboard_wired,
        "parameters": params,
        "engine": "sql_datafusion",
    })
}

pub fn list_rules_response() -> Value {
    match load_rules() {
        Ok(reg) => {
            let rules_dir = sql_rules_dir();
            let tuning = load_tuning_profiles(&rules_dir).unwrap_or_default();
            let rules: Vec<Value> = reg
                .rules
                .iter()
                .map(|rule| {
                    let effective = effective_param_strings(rule, &tuning, None, None, None).ok();
                    rule_to_json(rule, effective.as_ref())
                })
                .collect();
            json!({
                "ok": true,
                "rules_dir": rules_dir.display().to_string(),
                "rule_count": rules.len(),
                "rules": rules,
                "engine": "sql_datafusion",
            })
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
            let tuning = load_tuning_profiles(&rules_dir).unwrap_or_default();
            let effective = effective_param_strings(rule, &tuning, None, None, None).ok();
            json!({
                "ok": true,
                "rule": rule_to_json(rule, effective.as_ref()),
            })
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
