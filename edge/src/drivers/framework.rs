//! Common driver-tree model, schema validation, and provenance envelope.
//!
//! JSON snapshots under `workspace/data/drivers/` are runtime/export artifacts,
//! not authoritative configuration. Callers must attach schema_version,
//! generated_at, source, and validation metadata.

use chrono::Utc;
use serde_json::{json, Map, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

pub const SCHEMA_VERSION: &str = "1.0.0";
pub const DEFAULT_STALE_AFTER_SECS: u64 = 3600;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DataSource {
    Real,
    Simulated,
    Fixture,
    Imported,
}

impl DataSource {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Real => "real",
            Self::Simulated => "simulated",
            Self::Fixture => "fixture",
            Self::Imported => "imported",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DriverMode {
    Live,
    Simulated,
    Test,
}

impl DriverMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Live => "live",
            Self::Simulated => "simulated",
            Self::Test => "test",
        }
    }

    pub fn from_env_var(key: &str) -> Self {
        match env::var(key)
            .unwrap_or_else(|_| "simulated".to_string())
            .to_ascii_lowercase()
            .as_str()
        {
            "live" => Self::Live,
            "test" => Self::Test,
            _ => Self::Simulated,
        }
    }
}

pub fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

pub fn now_rfc3339() -> String {
    Utc::now().to_rfc3339()
}

pub fn allow_simulated_fallback() -> bool {
    env::var("OPENFDD_ALLOW_SIMULATED")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}

pub fn bacnet_mode() -> DriverMode {
    DriverMode::from_env_var("OPENFDD_BACNET_MODE")
}

pub fn modbus_mode() -> DriverMode {
    DriverMode::from_env_var("OPENFDD_MODBUS_MODE")
}

pub fn is_bacnet_live() -> bool {
    bacnet_mode() == DriverMode::Live && !allow_simulated_fallback()
}

pub fn is_modbus_live() -> bool {
    modbus_mode() == DriverMode::Live && !allow_simulated_fallback()
}

/// Demo markers that must never appear in live BACnet responses.
pub fn contains_demo_bacnet_marker(value: &Value) -> bool {
    let text = value.to_string().to_ascii_lowercase();
    if text.contains("ahu-1 controller") || text.contains("192.168.1.100") {
        return true;
    }
    if text.contains("\"device_instance\":1001") || text.contains("\"instance\":1001") {
        return true;
    }
    if text.contains("bacnet-simulated") || text.contains("demo registry") {
        return true;
    }
    false
}

pub fn contains_demo_override_value(value: &Value) -> bool {
    if let Some(overrides) = value.get("overrides").and_then(|v| v.as_array()) {
        for item in overrides {
            if item.get("priority").and_then(|v| v.as_u64()) == Some(8)
                && item.get("value").and_then(|v| v.as_f64()) == Some(58.0)
            {
                return true;
            }
        }
    }
    false
}

pub fn strip_demo_bacnet_devices(drivers: &mut [Value], warnings: &mut Vec<String>) {
    for driver in drivers.iter_mut() {
        if driver.get("id").and_then(|v| v.as_str()) != Some("bacnet-ip") {
            continue;
        }
        let Some(devices) = driver.get_mut("devices").and_then(|v| v.as_array_mut()) else {
            continue;
        };
        let before = devices.len();
        devices.retain(|dev| {
            let instance = dev.get("device_instance").and_then(|v| v.as_u64()).unwrap_or(0);
            let name = dev.get("name").and_then(|v| v.as_str()).unwrap_or("");
            let address = dev.get("address").and_then(|v| v.as_str()).unwrap_or("");
            !(instance == 1001
                || name.to_ascii_lowercase().contains("ahu-1")
                || address.contains("192.168.1.100"))
        });
        if devices.len() < before {
            warnings.push(format!(
                "removed {} demo BACnet device(s) from live driver tree",
                before - devices.len()
            ));
        }
    }
}

pub struct ValidationResult {
    pub ok: bool,
    pub warnings: Vec<String>,
    pub errors: Vec<String>,
}

impl ValidationResult {
    pub fn push_warning(&mut self, msg: impl Into<String>) {
        self.warnings.push(msg.into());
    }

    pub fn push_error(&mut self, msg: impl Into<String>) {
        self.errors.push(msg.into());
        self.ok = false;
    }

    pub fn to_json(&self) -> Value {
        json!({
            "ok": self.ok,
            "warnings": self.warnings,
            "errors": self.errors
        })
    }
}

pub fn validate_driver_tree_snapshot(snapshot: &Value, live_bacnet: bool) -> ValidationResult {
    let mut result = ValidationResult {
        ok: true,
        warnings: Vec::new(),
        errors: Vec::new(),
    };

    if snapshot.get("schema_version").is_none() {
        result.push_warning("missing schema_version on snapshot (legacy file)");
    }

    let Some(drivers) = snapshot.get("drivers").and_then(|v| v.as_array()) else {
        result.push_error("drivers array missing");
        return result;
    };

    for driver in drivers {
        let id = driver.get("id").and_then(|v| v.as_str()).unwrap_or("");
        if id.is_empty() {
            result.push_error("driver missing id");
        }
        if driver.get("label").is_none() {
            result.push_warning(format!("driver {id} missing label"));
        }
    }

    if live_bacnet && contains_demo_bacnet_marker(snapshot) {
        result.push_error("live BACnet mode cannot expose demo AHU-1 / 192.168.1.100 data");
    }

    result
}

pub struct TreeEnvelope {
    pub snapshot: Value,
    pub source: DataSource,
    pub generated_from_demo_fixture: bool,
    pub snapshot_path: Option<String>,
    pub validation: ValidationResult,
    pub bacnet_mode: DriverMode,
    pub modbus_mode: DriverMode,
}

impl TreeEnvelope {
    pub fn to_json(&self) -> Value {
        let mut root = self.snapshot.clone();
        if let Some(obj) = root.as_object_mut() {
            obj.insert(
                "schema_version".to_string(),
                json!(SCHEMA_VERSION),
            );
            obj.insert("generated_at".to_string(), json!(now_rfc3339()));
            obj.insert("source".to_string(), json!(self.source.as_str()));
            obj.insert(
                "generated_from_demo_fixture".to_string(),
                json!(self.generated_from_demo_fixture),
            );
            obj.insert("stale_after_seconds".to_string(), json!(DEFAULT_STALE_AFTER_SECS));
            obj.insert("validation".to_string(), self.validation.to_json());
            obj.insert(
                "provenance".to_string(),
                json!({
                    "snapshot_path": self.snapshot_path,
                    "bacnet_mode": self.bacnet_mode.as_str(),
                    "modbus_mode": self.modbus_mode.as_str(),
                    "workspace": workspace_dir().display().to_string(),
                    "note": "Runtime JSON snapshot; rebuild via discovery/sync APIs"
                }),
            );
        }
        root
    }
}

pub fn workspace_health() -> Value {
    let root = workspace_dir();
    let writable = root.exists() && path_writable(&root);
    let overrides = root.join("overrides");
    let driver_tree = root
        .join("data")
        .join("drivers")
        .join("bacnet")
        .join("driver_tree.json");

    json!({
        "ok": writable,
        "workspace": root.display().to_string(),
        "writable": writable,
        "paths": {
            "overrides_dir": overrides.display().to_string(),
            "overrides_exists": overrides.exists(),
            "driver_tree_snapshot": driver_tree.display().to_string(),
            "driver_tree_exists": driver_tree.exists()
        },
        "bacnet_mode": bacnet_mode().as_str(),
        "modbus_mode": modbus_mode().as_str(),
        "generated_at": now_rfc3339()
    })
}

fn path_writable(path: &Path) -> bool {
    if !path.exists() {
        return fs::create_dir_all(path).is_ok();
    }
    let probe = path.join(".openfdd_write_probe");
    match fs::write(&probe, b"ok") {
        Ok(_) => {
            let _ = fs::remove_file(probe);
            true
        }
        Err(_) => false,
    }
}

pub fn driver_health_block(
    driver_id: &str,
    label: &str,
    enabled: bool,
    status: &str,
    mode: DriverMode,
    source: DataSource,
    last_success_at: Option<&str>,
    last_error_at: Option<&str>,
    last_error: Option<&str>,
) -> Map<String, Value> {
    let mut map = Map::new();
    map.insert("id".to_string(), json!(driver_id));
    map.insert("label".to_string(), json!(label));
    map.insert("enabled".to_string(), json!(enabled));
    map.insert("status".to_string(), json!(status));
    map.insert("mode".to_string(), json!(mode.as_str()));
    map.insert("source".to_string(), json!(source.as_str()));
    map.insert("config_summary".to_string(), json!({}));
    map.insert("last_success_at".to_string(), json!(last_success_at));
    map.insert("last_error_at".to_string(), json!(last_error_at));
    map.insert("last_error".to_string(), json!(last_error));
    map.insert("stale_after_seconds".to_string(), json!(DEFAULT_STALE_AFTER_SECS));
    map
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_demo_ahu1_in_live_validation() {
        let snapshot = json!({
            "drivers": [{
                "id": "bacnet-ip",
                "devices": [{
                    "device_instance": 1001,
                    "name": "AHU-1 Controller",
                    "address": "192.168.1.100:47808"
                }]
            }]
        });
        let result = validate_driver_tree_snapshot(&snapshot, true);
        assert!(!result.ok);
        assert!(result.errors.iter().any(|e| e.contains("demo")));
    }

    #[test]
    fn simulated_snapshot_passes_with_demo_data() {
        let snapshot = json!({
            "drivers": [{
                "id": "bacnet-ip",
                "devices": [{
                    "device_instance": 1001,
                    "name": "AHU-1 Controller (simulated)"
                }]
            }]
        });
        let result = validate_driver_tree_snapshot(&snapshot, false);
        assert!(result.ok);
    }

    #[test]
    fn strip_demo_bacnet_devices_removes_ahu1() {
        let mut drivers = vec![json!({
            "id": "bacnet-ip",
            "devices": [
                {"device_instance": 1001, "name": "AHU-1 Controller", "address": "192.168.1.100:47808"},
                {"device_instance": 5007, "name": "Bench", "address": "192.168.204.200:47808"}
            ]
        })];
        let mut warnings = Vec::new();
        strip_demo_bacnet_devices(&mut drivers, &mut warnings);
        let devices = drivers[0]["devices"].as_array().unwrap();
        assert_eq!(devices.len(), 1);
        assert_eq!(devices[0]["device_instance"], 5007);
    }

    #[test]
    fn envelope_includes_schema_version() {
        let envelope = TreeEnvelope {
            snapshot: json!({"drivers": []}),
            source: DataSource::Simulated,
            generated_from_demo_fixture: true,
            snapshot_path: None,
            validation: ValidationResult {
                ok: true,
                warnings: vec![],
                errors: vec![],
            },
            bacnet_mode: DriverMode::Simulated,
            modbus_mode: DriverMode::Simulated,
        };
        let out = envelope.to_json();
        assert_eq!(out["schema_version"], SCHEMA_VERSION);
        assert_eq!(out["source"], "simulated");
        assert_eq!(out["generated_from_demo_fixture"], true);
    }

    #[test]
    fn detects_demo_override_58() {
        let scan = json!({"overrides": [{"priority": 8, "value": 58.0}]});
        assert!(contains_demo_override_value(&scan));
    }
}
