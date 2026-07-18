//! `openfdd_session_v1` session / fault settings save-load (#515).
//!
//! Mirrors the vibe19 Streamlit `session_config.json` contract (vibe19
//! `docs/PACKAGE_SPEC.md`): `unit_system`, `prefer_web_oat`, `chw_leave_max_f`,
//! per-equipment `role_map`, per-rule `params`. Unknown keys are ignored with a
//! warning; the deprecated `include_ahu_chw_valve` is always coerced off.
//!
//! The config persists at `workspace/data/session_config.json`, seeds the Lab
//! rule sliders on load, and — when a `building_id` is supplied — applies the
//! `role_map` to the ingested package via `columns.csv` rewrite + re-ingest.

use crate::historian::store::workspace_dir;
use serde_json::{json, Map, Value};
use std::path::PathBuf;

pub const SESSION_SCHEMA: &str = "openfdd_session_v1";

fn session_config_path() -> PathBuf {
    workspace_dir().join("data").join("session_config.json")
}

fn default_config() -> Value {
    json!({
        "schema_version": SESSION_SCHEMA,
        "unit_system": "imperial",
        "prefer_web_oat": true,
        "role_map": {},
        "params": {},
    })
}

/// `GET /api/fdd/session-config` — persisted session config or defaults.
pub fn get_session_config() -> Value {
    let path = session_config_path();
    let (config, persisted) = match std::fs::read_to_string(&path) {
        Ok(text) => match serde_json::from_str::<Value>(&text) {
            Ok(v) => (v, true),
            Err(_) => (default_config(), false),
        },
        Err(_) => (default_config(), false),
    };
    json!({
        "ok": true,
        "persisted": persisted,
        "path": path.display().to_string(),
        "config": config,
    })
}

/// Normalize an incoming session config: keep known keys, warn on unknown ones,
/// coerce the deprecated `include_ahu_chw_valve` off, validate value shapes.
pub fn normalize_session_config(raw: &Value) -> Result<(Value, Vec<String>), String> {
    let obj = raw
        .as_object()
        .ok_or("session config must be a JSON object")?;
    let schema = obj
        .get("schema_version")
        .and_then(|v| v.as_str())
        .unwrap_or(SESSION_SCHEMA);
    if schema != SESSION_SCHEMA {
        return Err(format!(
            "schema_version must be {SESSION_SCHEMA:?}, got {schema:?}"
        ));
    }

    let mut warnings = Vec::new();
    let mut out = Map::new();
    out.insert("schema_version".into(), json!(SESSION_SCHEMA));

    let unit = obj
        .get("unit_system")
        .and_then(|v| v.as_str())
        .unwrap_or("imperial")
        .to_lowercase();
    if !matches!(unit.as_str(), "imperial" | "metric" | "si") {
        return Err(format!(
            "unit_system must be imperial|metric|si, got {unit:?}"
        ));
    }
    out.insert("unit_system".into(), json!(unit));

    if let Some(v) = obj.get("prefer_web_oat").and_then(|v| v.as_bool()) {
        out.insert("prefer_web_oat".into(), json!(v));
    }
    if let Some(v) = obj.get("chw_leave_max_f").and_then(|v| v.as_f64()) {
        out.insert("chw_leave_max_f".into(), json!(v));
    }
    if obj.get("include_ahu_chw_valve").and_then(|v| v.as_bool()) == Some(true) {
        warnings.push(
            "include_ahu_chw_valve is deprecated and always treated as false (coerced off)".into(),
        );
    }

    // role_map: equipment_id -> role -> column (all strings).
    let mut role_map = Map::new();
    if let Some(rm) = obj.get("role_map").and_then(|v| v.as_object()) {
        for (equip, roles) in rm {
            let Some(roles) = roles.as_object() else {
                warnings.push(format!("role_map.{equip}: not an object — skipped"));
                continue;
            };
            let mut clean = Map::new();
            for (role, col) in roles {
                match col.as_str() {
                    Some(c) if !c.trim().is_empty() => {
                        clean.insert(role.clone(), json!(c.trim()));
                    }
                    _ => warnings.push(format!("role_map.{equip}.{role}: not a string — skipped")),
                }
            }
            if !clean.is_empty() {
                role_map.insert(equip.clone(), Value::Object(clean));
            }
        }
    }
    out.insert("role_map".into(), Value::Object(role_map));

    // params: rule_id -> param key -> number. Clamp to registry slider ranges when known.
    let registry = crate::fdd::registry_api::load_registry_rules_map();
    let mut params = Map::new();
    if let Some(pm) = obj.get("params").and_then(|v| v.as_object()) {
        for (rule_id, rule_params) in pm {
            let Some(rule_params) = rule_params.as_object() else {
                warnings.push(format!("params.{rule_id}: not an object — skipped"));
                continue;
            };
            let spec = registry.get(rule_id.as_str());
            if spec.is_none() {
                warnings.push(format!("params.{rule_id}: unknown rule id (kept as-is)"));
            }
            let mut clean = Map::new();
            for (key, val) in rule_params {
                let Some(n) = val.as_f64() else {
                    warnings.push(format!("params.{rule_id}.{key}: not a number — skipped"));
                    continue;
                };
                let n = match spec.and_then(|s| s.parameters.get(key)) {
                    Some(def) if n < def.min || n > def.max => {
                        let clamped = n.clamp(def.min, def.max);
                        warnings.push(format!(
                            "params.{rule_id}.{key}: {n} outside slider range {}..{} — clamped to {clamped}",
                            def.min, def.max
                        ));
                        clamped
                    }
                    _ => n,
                };
                clean.insert(key.clone(), json!(n));
            }
            if !clean.is_empty() {
                params.insert(rule_id.clone(), Value::Object(clean));
            }
        }
    }
    out.insert("params".into(), Value::Object(params));

    let known = [
        "schema_version",
        "unit_system",
        "prefer_web_oat",
        "chw_leave_max_f",
        "include_ahu_chw_valve",
        "role_map",
        "params",
    ];
    for key in obj.keys() {
        if !known.contains(&key.as_str()) {
            warnings.push(format!("unknown key {key:?} ignored"));
        }
    }

    Ok((Value::Object(out), warnings))
}

/// Persist a normalized session config to the workspace. Returns warnings.
pub fn save_session_config(config: &Value) -> Result<(), String> {
    let path = session_config_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(config).unwrap_or_default(),
    )
    .map_err(|e| format!("write {}: {e}", path.display()))
}

/// `PUT /api/fdd/session-config` — validate, persist, optionally apply the
/// role_map to an ingested building (`{"building_id": "...", "config": {…}}`
/// or the config object directly).
pub fn put_session_config(body: &Value) -> Value {
    let (raw, building_id) = match body.get("config") {
        Some(cfg) => (
            cfg,
            body.get("building_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        ),
        None => (body, String::new()),
    };
    let (config, mut warnings) = match normalize_session_config(raw) {
        Ok(v) => v,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    if let Err(e) = save_session_config(&config) {
        return json!({"ok": false, "error": e});
    }

    let mut applied_role_map = Vec::new();
    if !building_id.is_empty() {
        if let Some(role_map) = config.get("role_map").and_then(|v| v.as_object()) {
            for (equip, roles) in role_map {
                // Session role_map is role -> column; the roles endpoint wants column -> role.
                let mut column_roles = Map::new();
                if let Some(roles) = roles.as_object() {
                    for (role, col) in roles {
                        if let Some(c) = col.as_str() {
                            column_roles.insert(c.to_string(), json!(role));
                        }
                    }
                }
                if column_roles.is_empty() {
                    continue;
                }
                let out = crate::csv_ingest::package::update_package_roles_handler(&json!({
                    "building_id": building_id,
                    "equipment_id": equip,
                    "roles": Value::Object(column_roles),
                }));
                if out.get("ok") == Some(&json!(true)) {
                    applied_role_map.push(json!({"equipment_id": equip, "ok": true}));
                } else {
                    warnings.push(format!(
                        "role_map.{equip}: not applied — {}",
                        out.get("error").and_then(|v| v.as_str()).unwrap_or("error")
                    ));
                    applied_role_map.push(json!({"equipment_id": equip, "ok": false}));
                }
            }
        }
    }

    json!({
        "ok": true,
        "config": config,
        "warnings": warnings,
        "applied_role_map": applied_role_map,
        "path": session_config_path().display().to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_wrong_schema_and_bad_units() {
        let err = normalize_session_config(&json!({"schema_version": "v2"})).unwrap_err();
        assert!(err.contains("schema_version"), "{err}");
        let err = normalize_session_config(&json!({"unit_system": "cubits"})).unwrap_err();
        assert!(err.contains("unit_system"), "{err}");
    }

    #[test]
    fn coerces_deprecated_flag_and_warns_unknown_keys() {
        let (cfg, warnings) = normalize_session_config(&json!({
            "schema_version": SESSION_SCHEMA,
            "unit_system": "imperial",
            "include_ahu_chw_valve": true,
            "mystery_key": 1,
        }))
        .unwrap();
        assert!(cfg.get("include_ahu_chw_valve").is_none());
        assert!(warnings.iter().any(|w| w.contains("include_ahu_chw_valve")));
        assert!(warnings.iter().any(|w| w.contains("mystery_key")));
    }

    #[test]
    fn keeps_role_map_and_numeric_params_only() {
        let (cfg, warnings) = normalize_session_config(&json!({
            "unit_system": "metric",
            "role_map": {
                "AHU_1": {"fan_status": "supply_fan_status", "bad": 7},
            },
            "params": {
                "FC1": {"eps_dsp": 0.2, "junk": "nope"},
                "NOT-A-RULE": {"x": 1.0},
            },
        }))
        .unwrap();
        assert_eq!(cfg["unit_system"], json!("metric"));
        assert_eq!(
            cfg["role_map"]["AHU_1"]["fan_status"],
            json!("supply_fan_status")
        );
        assert!(cfg["role_map"]["AHU_1"].get("bad").is_none());
        assert_eq!(cfg["params"]["FC1"]["eps_dsp"], json!(0.2));
        assert!(cfg["params"]["FC1"].get("junk").is_none());
        assert!(warnings.iter().any(|w| w.contains("NOT-A-RULE")));
    }

    #[test]
    fn save_and_get_round_trip() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!("openfdd_session_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);

        let before = get_session_config();
        assert_eq!(before["persisted"], json!(false));
        assert_eq!(before["config"]["unit_system"], json!("imperial"));

        let out = put_session_config(&json!({
            "schema_version": SESSION_SCHEMA,
            "unit_system": "metric",
            "params": {"FC1": {"eps_dsp": 0.25}},
        }));
        assert_eq!(out["ok"], json!(true), "{out}");

        let after = get_session_config();
        assert_eq!(after["persisted"], json!(true));
        assert_eq!(after["config"]["unit_system"], json!("metric"));
        assert_eq!(after["config"]["params"]["FC1"]["eps_dsp"], json!(0.25));

        std::env::remove_var("OPENFDD_WORKSPACE");
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
