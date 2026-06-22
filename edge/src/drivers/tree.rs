//! Unified driver-tree response builder.

use super::bacnet;
use super::framework::{
    contains_demo_bacnet_marker, strip_demo_bacnet_devices, validate_driver_tree_snapshot,
    DataSource, DriverMode, TreeEnvelope, bacnet_mode, modbus_mode, now_rfc3339, workspace_dir,
};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

fn snapshot_path() -> PathBuf {
    workspace_dir()
        .join("data")
        .join("drivers")
        .join("bacnet")
        .join("driver_tree.json")
}

pub fn build_driver_tree_envelope() -> TreeEnvelope {
    let live_bacnet = bacnet_mode() == DriverMode::Live;
    let path = snapshot_path();
    let from_file = path.exists();
    let mut snapshot = bacnet::raw_registry_snapshot();
    let mut validation = validate_driver_tree_snapshot(&snapshot, live_bacnet);

    if live_bacnet {
        if let Some(drivers) = snapshot.get_mut("drivers").and_then(|v| v.as_array_mut()) {
            strip_demo_bacnet_devices(drivers, &mut validation.warnings);
        }
        if contains_demo_bacnet_marker(&snapshot) {
            validation.push_error("live BACnet tree still contains demo markers after sanitization");
        }
    }

    annotate_driver_nodes(&mut snapshot);

    let source = if live_bacnet && from_file {
        DataSource::Real
    } else if live_bacnet {
        DataSource::Imported
    } else if from_file {
        DataSource::Fixture
    } else {
        DataSource::Simulated
    };

    TreeEnvelope {
        snapshot,
        source,
        generated_from_demo_fixture: !live_bacnet,
        snapshot_path: Some(path.display().to_string()),
        validation,
        bacnet_mode: bacnet_mode(),
        modbus_mode: modbus_mode(),
    }
}

pub fn driver_tree_json() -> String {
    serde_json::to_string_pretty(&build_driver_tree_envelope().to_json())
        .unwrap_or_else(|_| "{}".to_string())
}

pub fn driver_tree_value() -> Value {
    build_driver_tree_envelope().to_json()
}

pub fn annotate_driver_nodes(snapshot: &mut Value) {
    let bacnet_live = bacnet_mode() == DriverMode::Live;
    let modbus_live = modbus_mode() == DriverMode::Live;
    let Some(drivers) = snapshot.get_mut("drivers").and_then(|v| v.as_array_mut()) else {
        return;
    };
    for driver in drivers {
        let id = driver.get("id").and_then(|v| v.as_str()).unwrap_or("");
        let (mode, source, status) = match id {
            "bacnet-ip" if bacnet_live => (DriverMode::Live, DataSource::Real, "online"),
            "bacnet-ip" => (DriverMode::Simulated, DataSource::Simulated, "online"),
            "modbus-tcp" if modbus_live => (DriverMode::Live, DataSource::Real, "online"),
            "modbus-tcp" => (DriverMode::Simulated, DataSource::Simulated, "online"),
            "json-api" => (DriverMode::Simulated, DataSource::Fixture, "online"),
            "haystack" => (DriverMode::Simulated, DataSource::Fixture, "online"),
            _ => (DriverMode::Simulated, DataSource::Fixture, "online"),
        };
        driver["mode"] = json!(mode.as_str());
        driver["source"] = json!(source.as_str());
        driver["status"] = json!(status);
        driver["last_success_at"] = json!(now_rfc3339());
        driver["generated_at"] = json!(now_rfc3339());
        driver["schema_version"] = json!(super::framework::SCHEMA_VERSION);
    }
}

pub fn read_snapshot_mtime() -> Option<String> {
    fs::metadata(snapshot_path())
        .ok()
        .and_then(|m| m.modified().ok())
        .map(|t| format!("{t:?}"))
}
