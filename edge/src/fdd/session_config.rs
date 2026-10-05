//! `openfdd_session_v1` session / fault settings save-load (#515).
//!
//! Mirrors the vibe19 `session_config.json` contract (vibe19
//! `docs/PACKAGE_SPEC.md`): `unit_system`, `prefer_web_oat`, `chw_leave_max_f`,
//! per-equipment `role_map`, per-rule `params`. Unknown keys are ignored with a
//! warning; the deprecated `include_ahu_chw_valve` is always coerced off.
//!
//! Persistence is scoped by optional tenant + building:
//! - `workspace/data/tenants/{tid}/buildings/{bid}/session_config.json`
//! - `workspace/data/buildings/{bid}/session_config.json` (no tenant)
//! - legacy hub-global `workspace/data/session_config.json` (read fallback when
//!   unscoped / building-only; never shared across tenants)

use crate::historian::store::workspace_dir;
use serde_json::{json, Map, Value};
use std::path::PathBuf;

pub const SESSION_SCHEMA: &str = "openfdd_session_v1";

/// Authoritative scope for session-config bytes (S03).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SessionConfigScope {
    pub tenant_id: Option<String>,
    pub building_id: Option<String>,
}

impl SessionConfigScope {
    pub fn new(tenant_id: Option<&str>, building_id: Option<&str>) -> Self {
        Self {
            tenant_id: sanitize_scope_id(tenant_id),
            building_id: sanitize_scope_id(building_id),
        }
    }
}

fn sanitize_scope_id(raw: Option<&str>) -> Option<String> {
    let s = raw?.trim();
    if s.is_empty() {
        return None;
    }
    if s.contains('/') || s.contains('\\') || s.contains("..") || s.contains('\0') {
        return None;
    }
    Some(s.to_string())
}

fn legacy_session_config_path() -> PathBuf {
    workspace_dir().join("data").join("session_config.json")
}

fn session_config_path_for(scope: &SessionConfigScope) -> PathBuf {
    match (scope.tenant_id.as_deref(), scope.building_id.as_deref()) {
        (Some(tid), Some(bid)) => workspace_dir()
            .join("data")
            .join("tenants")
            .join(tid)
            .join("buildings")
            .join(bid)
            .join("session_config.json"),
        (None, Some(bid)) => workspace_dir()
            .join("data")
            .join("buildings")
            .join(bid)
            .join("session_config.json"),
        _ => legacy_session_config_path(),
    }
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

fn read_config_file(path: &std::path::Path) -> Option<Value> {
    let text = std::fs::read_to_string(path).ok()?;
    serde_json::from_str::<Value>(&text).ok()
}

/// `GET /api/fdd/session-config` — unscoped / legacy hub-global.
pub fn get_session_config() -> Value {
    get_session_config_scoped(&SessionConfigScope::default())
}

/// Scoped session config. Tenant-scoped reads never fall back to hub-global
/// bytes (prevents A reading B's settings via a shared file). Building-only
/// (no tenant) may migrate from the legacy path for single-tenant hubs.
pub fn get_session_config_scoped(scope: &SessionConfigScope) -> Value {
    let path = session_config_path_for(scope);
    if let Some(config) = read_config_file(&path) {
        return json!({
            "ok": true,
            "persisted": true,
            "path": path.display().to_string(),
            "scope": {
                "tenant_id": scope.tenant_id,
                "building_id": scope.building_id,
            },
            "legacy_fallback": false,
            "config": config,
        });
    }

    let allow_legacy = scope.tenant_id.is_none();
    if allow_legacy {
        let legacy = legacy_session_config_path();
        if legacy != path {
            if let Some(config) = read_config_file(&legacy) {
                return json!({
                    "ok": true,
                    "persisted": true,
                    "path": legacy.display().to_string(),
                    "scope": {
                        "tenant_id": scope.tenant_id,
                        "building_id": scope.building_id,
                    },
                    "legacy_fallback": true,
                    "config": config,
                });
            }
        }
    }

    json!({
        "ok": true,
        "persisted": false,
        "path": path.display().to_string(),
        "scope": {
            "tenant_id": scope.tenant_id,
            "building_id": scope.building_id,
        },
        "legacy_fallback": false,
        "config": default_config(),
    })
}

/// Persisted `unit_system` (imperial|metric|si). Defaults to imperial.
pub fn unit_system_from_session() -> String {
    get_session_config()
        .get("config")
        .and_then(|c| c.get("unit_system"))
        .and_then(|v| v.as_str())
        .unwrap_or("imperial")
        .to_string()
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

    // Weekly occupancy calendar (Overview / WattLab parity). Exact shape:
    // { timezone, days: { mon..sun: { occupied, start, end } } }
    if let Some(sched) = obj.get("occupancy_schedule") {
        if sched.is_object() {
            out.insert("occupancy_schedule".into(), sched.clone());
        } else {
            warnings.push("occupancy_schedule: not an object — skipped".into());
        }
    }

    let known = [
        "schema_version",
        "unit_system",
        "prefer_web_oat",
        "chw_leave_max_f",
        "include_ahu_chw_valve",
        "role_map",
        "params",
        "occupancy_schedule",
        "use_mech_cooling_status_proof",
    ];
    for key in obj.keys() {
        if !known.contains(&key.as_str()) {
            warnings.push(format!("unknown key {key:?} ignored"));
        }
    }

    Ok((Value::Object(out), warnings))
}

/// Persist a normalized session config to the legacy hub-global path.
pub fn save_session_config(config: &Value) -> Result<(), String> {
    save_session_config_scoped(&SessionConfigScope::default(), config)
}

/// Persist under the authoritative tenant/building path.
pub fn save_session_config_scoped(
    scope: &SessionConfigScope,
    config: &Value,
) -> Result<(), String> {
    let path = session_config_path_for(scope);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    std::fs::write(
        &path,
        serde_json::to_string_pretty(config).unwrap_or_default(),
    )
    .map_err(|e| format!("write {}: {e}", path.display()))
}

fn strip_site_from_path(
    path: &std::path::Path,
    building_id: &str,
    equipment_ids: &[String],
) -> Result<usize, String> {
    if !path.is_file() {
        return Ok(0);
    }
    let text =
        std::fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let mut config: Value =
        serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))?;
    let mut removed = 0usize;
    if let Some(rm) = config.get_mut("role_map").and_then(|v| v.as_object_mut()) {
        for equip in equipment_ids {
            if rm.remove(equip).is_some() {
                removed += 1;
            }
        }
        if rm.remove(building_id).is_some() {
            removed += 1;
        }
    }
    if let Some(params) = config.get_mut("params").and_then(|v| v.as_object_mut()) {
        let drop_keys: Vec<String> = params
            .keys()
            .filter(|k| *k == building_id || k.starts_with(&format!("{building_id}::")))
            .cloned()
            .collect();
        for k in drop_keys {
            if params.remove(&k).is_some() {
                removed += 1;
            }
        }
    }
    if removed > 0 {
        std::fs::write(
            path,
            serde_json::to_string_pretty(&config).unwrap_or_default(),
        )
        .map_err(|e| format!("write {}: {e}", path.display()))?;
    }
    Ok(removed)
}

/// Remove equipment role_map entries for a deleted site; drop params keyed by building id.
/// Does not wipe global unit_system / other sites' equipment.
pub fn strip_site_from_session_config(
    building_id: &str,
    equipment_ids: &[String],
) -> Result<usize, String> {
    strip_site_from_session_config_scoped(
        &SessionConfigScope::new(None, Some(building_id)),
        building_id,
        equipment_ids,
    )
}

/// Strip site keys from the scoped config file (and legacy hub file when present).
pub fn strip_site_from_session_config_scoped(
    scope: &SessionConfigScope,
    building_id: &str,
    equipment_ids: &[String],
) -> Result<usize, String> {
    let mut removed =
        strip_site_from_path(&session_config_path_for(scope), building_id, equipment_ids)?;
    // Also clean legacy hub-global leftovers for single-tenant migrations.
    if scope.tenant_id.is_none() {
        removed += strip_site_from_path(&legacy_session_config_path(), building_id, equipment_ids)?;
    }
    Ok(removed)
}

/// `PUT /api/fdd/session-config` — validate, persist, optionally apply the
/// role_map to an ingested building (`{"building_id": "...", "config": {…}}`
/// or the config object directly). Optional `tenant_id` is server-supplied.
pub fn put_session_config(body: &Value) -> Value {
    let (raw, building_id, tenant_id) = match body.get("config") {
        Some(cfg) => (
            cfg,
            body.get("building_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            body.get("tenant_id")
                .and_then(|v| v.as_str())
                .map(str::to_string),
        ),
        None => (
            body,
            body.get("building_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            body.get("tenant_id")
                .and_then(|v| v.as_str())
                .map(str::to_string),
        ),
    };
    let scope = SessionConfigScope::new(
        tenant_id.as_deref(),
        if building_id.is_empty() {
            None
        } else {
            Some(building_id.as_str())
        },
    );
    let (config, mut warnings) = match normalize_session_config(raw) {
        Ok(v) => v,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    if let Err(e) = save_session_config_scoped(&scope, &config) {
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
        "path": session_config_path_for(&scope).display().to_string(),
        "scope": {
            "tenant_id": scope.tenant_id,
            "building_id": scope.building_id,
        },
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
    fn keeps_occupancy_schedule_calendar() {
        let (cfg, warnings) = normalize_session_config(&json!({
            "schema_version": SESSION_SCHEMA,
            "unit_system": "imperial",
            "occupancy_schedule": {
                "timezone": "America/Chicago",
                "days": {
                    "mon": {"occupied": true, "start": "07:00", "end": "17:00"},
                    "sat": {"occupied": false, "start": "07:00", "end": "17:00"}
                }
            }
        }))
        .unwrap();
        assert_eq!(
            cfg["occupancy_schedule"]["timezone"],
            json!("America/Chicago")
        );
        assert_eq!(
            cfg["occupancy_schedule"]["days"]["mon"]["start"],
            json!("07:00")
        );
        assert!(!warnings.iter().any(|w| w.contains("occupancy_schedule")));
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

    #[test]
    fn strip_site_removes_equipment_role_map_only() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp =
            std::env::temp_dir().join(format!("openfdd_session_strip_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(tmp.join("data")).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);

        save_session_config(&json!({
            "schema_version": SESSION_SCHEMA,
            "unit_system": "imperial",
            "prefer_web_oat": true,
            "role_map": {
                "AHU_1": {"fan_status": "fs"},
                "AHU_KEEP": {"fan_status": "fs"},
            },
            "params": {
                "FC1": {"eps_dsp": 0.2},
                "BUILDING_50": {"x": 1},
            },
        }))
        .unwrap();

        let n = strip_site_from_session_config("BUILDING_50", &["AHU_1".to_string()]).unwrap();
        assert!(n >= 2, "expected role_map + params strip, got {n}");

        let after = get_session_config();
        assert!(after["config"]["role_map"].get("AHU_1").is_none());
        assert!(after["config"]["role_map"].get("AHU_KEEP").is_some());
        assert!(after["config"]["params"].get("BUILDING_50").is_none());
        assert_eq!(after["config"]["params"]["FC1"]["eps_dsp"], json!(0.2));

        std::env::remove_var("OPENFDD_WORKSPACE");
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn tenant_scoped_configs_do_not_collide() {
        let _env = crate::test_support::workspace_env_lock();
        let tmp = std::env::temp_dir().join(format!(
            "openfdd_session_tenant_{}_{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);

        let scope_a = SessionConfigScope::new(Some("tenant_a"), Some("SHARED_BLDG"));
        let scope_b = SessionConfigScope::new(Some("tenant_b"), Some("SHARED_BLDG"));

        save_session_config_scoped(
            &scope_a,
            &json!({
                "schema_version": SESSION_SCHEMA,
                "unit_system": "metric",
                "params": {"FC1": {"eps_dsp": 0.11}},
            }),
        )
        .unwrap();
        save_session_config_scoped(
            &scope_b,
            &json!({
                "schema_version": SESSION_SCHEMA,
                "unit_system": "imperial",
                "params": {"FC1": {"eps_dsp": 0.99}},
            }),
        )
        .unwrap();

        let a = get_session_config_scoped(&scope_a);
        let b = get_session_config_scoped(&scope_b);
        assert_eq!(a["config"]["unit_system"], json!("metric"));
        assert_eq!(a["config"]["params"]["FC1"]["eps_dsp"], json!(0.11));
        assert_eq!(b["config"]["unit_system"], json!("imperial"));
        assert_eq!(b["config"]["params"]["FC1"]["eps_dsp"], json!(0.99));
        assert_ne!(a["path"], b["path"]);
        // Tenant-scoped reads must not leak hub-global leftovers.
        save_session_config(&json!({
            "schema_version": SESSION_SCHEMA,
            "unit_system": "si",
            "params": {"FC1": {"eps_dsp": 7.0}},
        }))
        .unwrap();
        let a2 = get_session_config_scoped(&scope_a);
        assert_eq!(a2["config"]["unit_system"], json!("metric"));
        assert_eq!(a2["legacy_fallback"], json!(false));

        std::env::remove_var("OPENFDD_WORKSPACE");
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
