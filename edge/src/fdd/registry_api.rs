//! Registry-backed FDD API — loads `sql_rules/registry.yaml` via `fdd_rules`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use fdd_rules::{
    effective_param_strings, load_registry, load_tuning_profiles, rule_params, run_all_rules,
    substitute_sql, RuleRegistry, RuleSpec,
};
use serde_json::{json, Value};

fn sql_rules_dir() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_SQL_RULES_DIR") {
        return PathBuf::from(p);
    }
    for c in [
        PathBuf::from("sql_rules"),
        PathBuf::from("/app/sql_rules"),
        PathBuf::from("../sql_rules"),
    ] {
        if c.join("registry.yaml").is_file() {
            return c;
        }
    }
    PathBuf::from("sql_rules")
}

fn parquet_root() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_PARQUET_ROOT") {
        return PathBuf::from(p);
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

fn results_dir() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_RULE_RESULTS_DIR") {
        return PathBuf::from(p);
    }
    PathBuf::from(".cache/rule_results")
}

fn load_reg() -> Result<RuleRegistry, String> {
    let dir = sql_rules_dir();
    load_registry(&dir).map_err(|e| format!("load registry {}: {e}", dir.display()))
}

fn param_to_json(rule: &RuleSpec) -> Value {
    let mut params = serde_json::Map::new();
    for (key, def) in &rule.parameters {
        params.insert(
            key.clone(),
            json!({
                "key": key,
                "label": def.label,
                "default": def.default,
                "min": def.min,
                "max": def.max,
                "step": def.step,
                "unit": def.unit,
                "control": def.frontend_control,
                "sql_placeholder": def.sql_placeholder,
            }),
        );
    }
    // Always expose confirm as confirm_min (minutes) for vibe19 UI parity.
    if !params.contains_key("confirm_min") && !params.contains_key("confirm_seconds") {
        params.insert(
            "confirm_min".into(),
            json!({
                "key": "confirm_min",
                "label": "Fault confirm delay",
                "default": (rule.confirm_seconds as f64) / 60.0,
                "min": 0.0,
                "max": 120.0,
                "step": 1.0,
                "unit": "min",
                "control": "slider",
                "sql_placeholder": "CONFIRM_SECONDS",
            }),
        );
    }
    Value::Object(params)
}

fn rule_summary(rule: &RuleSpec) -> Value {
    json!({
        "rule_id": rule.rule_id,
        "sql_file": rule.sql_file,
        "description": rule.description,
        "required_roles": rule.required_roles,
        "output_columns": rule.output_columns,
        "confirm_seconds": rule.confirm_seconds,
        "confirm_min": (rule.confirm_seconds as f64) / 60.0,
        "parity_status": rule.parity_status,
        "dashboard_wired": rule.dashboard_wired,
        "parameter_count": rule.parameters.len(),
    })
}

/// `GET /api/fdd/rules` — full registry catalog.
pub fn list_registry_rules() -> Value {
    match load_reg() {
        Ok(reg) => {
            let rules: Vec<Value> = reg.rules.iter().map(rule_summary).collect();
            json!({
                "ok": true,
                "rules_dir": reg.rules_dir,
                "count": rules.len(),
                "rules": rules,
            })
        }
        Err(e) => json!({"ok": false, "error": e, "count": 0, "rules": []}),
    }
}

/// `GET /api/fdd/rules/{id}/params` — tuning schema for one rule.
pub fn rule_params_response(rule_id: &str) -> Value {
    match load_reg() {
        Ok(reg) => match reg.rules.iter().find(|r| r.rule_id == rule_id) {
            Some(rule) => json!({
                "ok": true,
                "rule_id": rule.rule_id,
                "confirm_seconds": rule.confirm_seconds,
                "required_roles": rule.required_roles,
                "params": param_to_json(rule),
            }),
            None => json!({"ok": false, "error": format!("unknown rule_id {rule_id}")}),
        },
        Err(e) => json!({"ok": false, "error": e}),
    }
}

/// `GET /api/fdd/cache/status` — parquet ingest / results status.
pub fn cache_status() -> Value {
    let pq = parquet_root();
    let results = results_dir();
    let history = pq.join("history");
    let parquet_files = walkdir_count(&pq, "parquet");
    let result_files = walkdir_count(&results, "json");
    json!({
        "ok": true,
        "parquet_root": pq.display().to_string(),
        "parquet_exists": pq.is_dir(),
        "history_exists": history.is_dir(),
        "parquet_file_count": parquet_files,
        "results_dir": results.display().to_string(),
        "result_file_count": result_files,
        "sql_rules_dir": sql_rules_dir().display().to_string(),
        "sql_rules_present": sql_rules_dir().join("registry.yaml").is_file(),
    })
}

fn walkdir_count(root: &Path, ext: &str) -> usize {
    if !root.is_dir() {
        return 0;
    }
    walkdir::WalkDir::new(root)
        .into_iter()
        .filter_map(|e| e.ok())
        .filter(|e| {
            e.file_type().is_file()
                && e.path()
                    .extension()
                    .and_then(|x| x.to_str())
                    .is_some_and(|x| x.eq_ignore_ascii_case(ext))
        })
        .count()
}

/// `GET /api/fdd/roles` — role map file if present.
pub fn roles_response() -> Value {
    let candidates = [
        PathBuf::from("configs/role_map.json"),
        PathBuf::from("workspace/data/role_map.json"),
        PathBuf::from("/app/configs/role_map.json"),
    ];
    for c in candidates {
        if c.is_file() {
            match std::fs::read_to_string(&c) {
                Ok(text) => match serde_json::from_str::<Value>(&text) {
                    Ok(v) => {
                        return json!({
                            "ok": true,
                            "path": c.display().to_string(),
                            "roles": v,
                        })
                    }
                    Err(e) => {
                        return json!({
                            "ok": false,
                            "error": format!("parse {}: {e}", c.display()),
                        })
                    }
                },
                Err(e) => {
                    return json!({"ok": false, "error": e.to_string()});
                }
            }
        }
    }
    json!({
        "ok": true,
        "path": null,
        "roles": {},
        "hint": "no role_map.json found; place under configs/ or workspace/data/"
    })
}

/// `POST /api/fdd/run` body for registry engine (typed params only — no raw SQL).
///
/// ```json
/// { "mode": "registry", "rule_ids": ["FC1","VAV-1"], "params": { "FC1": { "confirm_min": 5 } } }
/// ```
/// Omit `rule_ids` to run all. Without parquet cache, returns a clear error.
pub fn run_registry(payload: &Value) -> Value {
    let pq = parquet_root();
    if !pq.is_dir() {
        return json!({
            "ok": false,
            "error": format!(
                "parquet cache missing at {} — set OPENFDD_PARQUET_ROOT or ingest a building package first",
                pq.display()
            ),
            "cache": cache_status(),
        });
    }
    let reg = match load_reg() {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };

    let filter: Option<Vec<String>> = payload.get("rule_ids").and_then(|v| v.as_array()).map(|a| {
        a.iter()
            .filter_map(|x| x.as_str().map(str::to_string))
            .collect()
    });

    let filtered = if let Some(ids) = filter {
        let mut clone = reg.clone();
        clone
            .rules
            .retain(|r| ids.iter().any(|id| id == &r.rule_id));
        clone
    } else {
        reg
    };

    if filtered.rules.is_empty() {
        return json!({"ok": false, "error": "no matching rules to run"});
    }

    // Apply request overrides into a temp tuning overlay via env is overkill;
    // runner uses registry defaults + rule_tuning/. Request params are applied
    // by rewriting confirm_seconds on a per-rule clone when provided.
    let mut effective = filtered.clone();
    if let Some(params_by_rule) = payload.get("params").and_then(|v| v.as_object()) {
        for rule in &mut effective.rules {
            if let Some(p) = params_by_rule
                .get(&rule.rule_id)
                .and_then(|v| v.as_object())
            {
                if let Some(cm) = p.get("confirm_min").and_then(|v| v.as_f64()) {
                    rule.confirm_seconds = (cm * 60.0).round() as u32;
                }
                if let Some(cs) = p.get("confirm_seconds").and_then(|v| v.as_f64()) {
                    rule.confirm_seconds = cs.round() as u32;
                }
            }
        }
    }

    let out = results_dir();
    let rt = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build();
    let rt = match rt {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": format!("runtime: {e}")}),
    };
    match rt.block_on(run_all_rules(&pq, &effective, &out)) {
        Ok(report) => json!({
            "ok": true,
            "engine": "fdd_rules+DataFusion",
            "mode": "registry",
            "rules_run": report.rules_run,
            "rules_succeeded": report.rules_succeeded,
            "rules_failed": report.rules_failed,
            "poll_seconds": report.poll_seconds,
            "total_ms": report.total_ms,
            "timings": report.timings,
            "results_dir": out.display().to_string(),
        }),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

/// Preview substituted SQL for a rule (integrator lab only — not operator UI).
pub fn preview_sql(rule_id: &str, overrides: &Value) -> Value {
    let reg = match load_reg() {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let Some(rule) = reg.rules.iter().find(|r| r.rule_id == rule_id) else {
        return json!({"ok": false, "error": format!("unknown rule_id {rule_id}")});
    };
    let sql_path = Path::new(&reg.rules_dir).join(&rule.sql_file);
    let raw = match std::fs::read_to_string(&sql_path) {
        Ok(s) => s,
        Err(e) => return json!({"ok": false, "error": e.to_string()}),
    };
    let poll = overrides
        .get("poll_seconds")
        .and_then(|v| v.as_f64())
        .unwrap_or(300.0);
    let mut confirm = rule.confirm_seconds;
    if let Some(cm) = overrides.get("confirm_min").and_then(|v| v.as_f64()) {
        confirm = (cm * 60.0).round() as u32;
    }
    if let Some(cs) = overrides.get("confirm_seconds").and_then(|v| v.as_u64()) {
        confirm = cs as u32;
    }
    let mut params = rule_params(poll, confirm);
    if let Ok(tuning) = load_tuning_profiles(Path::new(&reg.rules_dir)) {
        if let Ok(tuned) = effective_param_strings(rule, &tuning, None, None, None) {
            for (k, v) in tuned {
                params.insert(k, v);
            }
        }
    }
    if let Some(obj) = overrides.as_object() {
        for (k, v) in obj {
            if let Some(n) = v.as_f64() {
                // Map param keys to SQL placeholders when present on the rule.
                if let Some(def) = rule.parameters.get(k) {
                    params.insert(def.sql_placeholder.clone(), n.to_string());
                }
            }
        }
    }
    let sql = substitute_sql(&raw, &params);
    json!({
        "ok": true,
        "rule_id": rule_id,
        "params": params.into_iter().collect::<HashMap<_,_>>(),
        "sql": sql,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn list_rules_loads_repo_registry() {
        let v = list_registry_rules();
        assert_eq!(v["ok"], true, "{v}");
        assert!(v["count"].as_u64().unwrap_or(0) >= 19, "{v}");
    }

    #[test]
    fn vav1_params_include_sliders() {
        let v = rule_params_response("VAV-1");
        assert_eq!(v["ok"], true, "{v}");
        assert!(v["params"]["zone_t_lo"]["control"].as_str().is_some());
    }

    #[test]
    fn cache_status_ok_shape() {
        let v = cache_status();
        assert_eq!(v["ok"], true);
        assert!(v.get("parquet_root").is_some());
    }
}
