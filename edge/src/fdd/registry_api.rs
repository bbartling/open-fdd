//! Registry-backed FDD API — loads `sql_rules/registry.yaml` via `fdd_rules`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use fdd_rules::{
    effective_param_strings, load_registry, load_tuning_profiles, rule_params,
    run_all_rules_with_overrides, substitute_sql, RuleRegistry, RuleSpec,
};
use fdd_sql::{register_parquet_tree, run_sql};
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

/// Map Streamlit / pandas cookbook slider keys onto SQL registry parameter keys.
fn alias_ui_param_key<'a>(rule_id: &str, key: &'a str) -> &'a str {
    match (rule_id, key) {
        ("VAV-1", "zone_lo") => "zone_t_lo",
        ("VAV-1", "zone_hi") => "zone_t_hi",
        ("FC1", "duct_static_err") => "eps_dsp",
        (
            "SV-SPIKE",
            "spike_scale_temperature" | "spike_scale_humidity" | "spike_scale_pressure",
        ) => "spike_scale",
        _ => key,
    }
}

fn parquet_root() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_PARQUET_ROOT") {
        return PathBuf::from(p);
    }
    // Prefer workspace-relative cache so CSV ingest and /api/fdd/run agree when
    // only OPENFDD_WORKSPACE is set (standalone recipe parity with csv recipe).
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

/// Registry rules keyed by rule_id and aliases (empty map when registry is unavailable).
pub fn load_registry_rules_map() -> HashMap<String, RuleSpec> {
    let mut out = HashMap::new();
    if let Ok(reg) = load_reg() {
        for rule in reg.rules {
            for alias in &rule.aliases {
                out.insert(alias.clone(), rule.clone());
            }
            out.insert(rule.rule_id.clone(), rule);
        }
    }
    out
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

fn infer_equipment_type(equipment_id: &str) -> &'static str {
    let id = equipment_id.to_ascii_uppercase();
    if id.contains("VAV") || id.contains("ZONE") {
        "VAV"
    } else if id.contains("AHU") || id.contains("RTU") || id.contains("MAU") {
        "AHU"
    } else if id.contains("CHILL")
        || id.contains("BOILER")
        || id.contains("PUMP")
        || id.contains("TOWER")
    {
        "PLANT"
    } else if id.contains("HP") || id.contains("HEAT_PUMP") {
        "HEAT_PUMP"
    } else if id.contains("METER") {
        "METER"
    } else {
        "GENERAL"
    }
}

/// `GET /api/fdd/equipment` — equipment present in the parquet cache.
pub fn equipment_response() -> Value {
    let root = parquet_root();
    let mut ids = Vec::new();
    if root.is_dir() {
        for entry in walkdir::WalkDir::new(&root)
            .min_depth(1)
            .max_depth(3)
            .into_iter()
            .filter_map(Result::ok)
            .filter(|e| e.file_type().is_dir())
        {
            if let Some(id) = entry
                .file_name()
                .to_str()
                .and_then(|name| name.strip_prefix("equipment="))
            {
                ids.push(id.to_string());
            }
        }
    }
    ids.sort();
    ids.dedup();
    let equipment: Vec<Value> = ids
        .iter()
        .map(|id| {
            json!({
                "equipment_id": id,
                "equipment_type": infer_equipment_type(id),
            })
        })
        .collect();
    json!({"ok": true, "count": equipment.len(), "equipment": equipment})
}

/// `GET /api/fdd/results` — normalized rows from the most recent registry run.
pub fn results_response() -> Value {
    let dir = results_dir();
    let reg = load_reg().ok();
    let mut metadata = HashMap::new();
    if let Some(reg) = &reg {
        for rule in &reg.rules {
            metadata.insert(rule.rule_id.clone(), rule.description.clone());
        }
    }
    let mut rows = Vec::new();
    if dir.is_dir() {
        let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .map(|e| e.path())
            .filter(|p| p.extension().and_then(|x| x.to_str()) == Some("json"))
            .collect();
        files.sort();
        for path in files {
            let Some(rule_id) = path.file_stem().and_then(|x| x.to_str()) else {
                continue;
            };
            let Ok(text) = std::fs::read_to_string(&path) else {
                continue;
            };
            let Ok(body) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            for row in body
                .get("rows")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let equipment_id = row
                    .get("equipment_id")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown");
                let fault_hours = row
                    .get("fault_hours")
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0);
                rows.push(json!({
                    "rule_id": rule_id,
                    "title": metadata.get(rule_id).cloned().unwrap_or_default(),
                    "equipment_id": equipment_id,
                    "equipment_type": infer_equipment_type(equipment_id),
                    "status": if fault_hours > 0.0 { "FAULT" } else { "PASS" },
                    "fault_hours": fault_hours,
                    "fault_pct": row.get("fault_pct").and_then(Value::as_f64),
                    "missing_roles": [],
                    "notes": row.get("notes").cloned().unwrap_or(Value::Null),
                }));
            }
        }
    }
    json!({"ok": true, "count": rows.len(), "results": rows})
}

/// Downsampled history series for one equipment/rule. Rule math continues to
/// use full-resolution parquet; only this display response is capped.
pub fn series_response(equipment_id: &str, rule_id: &str) -> Value {
    let reg = match load_reg() {
        Ok(r) => r,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let Some(rule) = reg
        .rules
        .iter()
        .find(|r| r.rule_id == rule_id || r.aliases.iter().any(|a| a == rule_id))
    else {
        return json!({"ok": false, "error": format!("unknown rule_id {rule_id}")});
    };
    let columns: Vec<&str> = rule
        .required_roles
        .iter()
        .map(String::as_str)
        .filter(|name| name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_'))
        .collect();
    if columns.is_empty() {
        return json!({"ok": true, "equipment_id": equipment_id, "rule_id": rule.rule_id, "rows": []});
    }
    let escaped_equipment = equipment_id.replace('\'', "''");
    let sql = format!(
        "SELECT timestamp_utc, equipment_id, {} FROM history WHERE equipment_id = '{}' ORDER BY timestamp_utc LIMIT 5000",
        columns.join(", "),
        escaped_equipment
    );
    let root = parquet_root();
    let rt = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(rt) => rt,
        Err(e) => return json!({"ok": false, "error": format!("runtime: {e}")}),
    };
    rt.block_on(async {
        let ctx = datafusion::prelude::SessionContext::new();
        if let Err(e) = register_parquet_tree(&ctx, &root).await {
            return json!({"ok": false, "error": e.to_string()});
        }
        match run_sql(&ctx, &sql).await {
            Ok(result) => json!({
                "ok": true,
                "equipment_id": equipment_id,
                "equipment_type": infer_equipment_type(equipment_id),
                "rule_id": rule.rule_id,
                "roles": columns,
                "rows": result.rows,
                "downsampled": result.row_count >= 5000,
                "max_points": 5000,
            }),
            Err(e) => json!({"ok": false, "error": e.to_string()}),
        }
    })
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
        clone.rules.retain(|r| {
            ids.iter()
                .any(|id| id == &r.rule_id || r.aliases.iter().any(|a| a == id))
        });
        clone
    } else {
        reg
    };

    if filtered.rules.is_empty() {
        return json!({"ok": false, "error": "no matching rules to run"});
    }

    // Normalize aliases and pass typed request overrides into the runner.
    let mut effective = filtered.clone();
    let mut session_overrides: HashMap<String, HashMap<String, f64>> = HashMap::new();
    if let Some(params_by_rule) = payload.get("params").and_then(|v| v.as_object()) {
        for rule in &mut effective.rules {
            let supplied = params_by_rule.get(&rule.rule_id).or_else(|| {
                rule.aliases
                    .iter()
                    .find_map(|alias| params_by_rule.get(alias))
            });
            if let Some(p) = supplied.and_then(|v| v.as_object()) {
                // UI vibe19 sliders store confirm_min (minutes). Always fold into
                // rule.confirm_seconds AND typed overrides so parameter-default
                // CONFIRM_SECONDS cannot wipe the slider (soak BUG-2).
                let mut confirm_override: Option<f64> = None;
                if let Some(cm) = p.get("confirm_min").and_then(|v| v.as_f64()) {
                    rule.confirm_seconds = (cm * 60.0).round() as u32;
                    confirm_override = Some(rule.confirm_seconds as f64);
                }
                if let Some(cs) = p.get("confirm_seconds").and_then(|v| v.as_f64()) {
                    rule.confirm_seconds = cs.round() as u32;
                    confirm_override = Some(rule.confirm_seconds as f64);
                }
                let mut typed = HashMap::new();
                for (key, value) in p {
                    if key == "confirm_min" {
                        continue;
                    }
                    let Some(mut number) = value.as_f64() else {
                        continue;
                    };
                    // FC1 legacy fan_hi (fan-on frac) → eps_vfd_spd = 1 - fan_hi
                    let mut mapped = alias_ui_param_key(&rule.rule_id, key).to_string();
                    if rule.rule_id == "FC1" && key == "fan_hi" {
                        if p.get("eps_vfd_spd").and_then(|v| v.as_f64()).is_some() {
                            continue;
                        }
                        mapped = "eps_vfd_spd".into();
                        number = (1.0 - number).clamp(0.0, 1.0);
                    }
                    if rule.parameters.contains_key(&mapped) {
                        typed.insert(mapped, number);
                    } else if rule.parameters.contains_key(key) {
                        typed.insert(key.clone(), number);
                    } else if let Some((param_key, _)) = rule.parameters.iter().find(|(_, def)| {
                        def.sql_placeholder == *key || def.sql_placeholder == mapped
                    }) {
                        typed.insert(param_key.clone(), number);
                    }
                }
                if let Some(cs) = confirm_override {
                    if rule.parameters.contains_key("confirm_seconds") {
                        typed.insert("confirm_seconds".into(), cs);
                    }
                }
                if !typed.is_empty() {
                    session_overrides.insert(rule.rule_id.clone(), typed);
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
    match rt.block_on(run_all_rules_with_overrides(
        &pq,
        &effective,
        &out,
        &session_overrides,
        payload.get("equipment_id").and_then(Value::as_str),
    )) {
        Ok(report) => {
            let normalized = results_response();
            json!({
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
                "results": normalized.get("results").cloned().unwrap_or_else(|| json!([])),
            })
        }
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
