//! Local Open-FDD BACnet server status objects (BACpypes3 `server_points.py` parity).
//!
//! Exposes OpenFDD as a discoverable BACnet device (default instance 599999) with
//! diagnostic points — not field controllers.

use super::bacnet;
use serde_json::{json, Value};
use std::env;

const COMMANDABLE_TYPES: &[&str] = &[
    "analog-output",
    "analog-value",
    "binary-output",
    "binary-value",
    "multi-state-output",
    "multi-state-value",
    "integer-value",
    "large-analog-value",
    "positive-integer-value",
];

pub fn device_instance() -> u32 {
    env::var("OPENFDD_BACNET_DEVICE_INSTANCE")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(599999)
}

pub fn device_name() -> String {
    env::var("OPENFDD_BACNET_DEVICE_NAME").unwrap_or_else(|_| "OpenFDD".to_string())
}

pub fn is_commandable_object_type(object_type: &str) -> bool {
    COMMANDABLE_TYPES.contains(&object_type)
}

fn status_point(
    object_type: &str,
    instance: u32,
    name: &str,
    present_value: Value,
    units: &str,
) -> Value {
    let inst = device_instance();
    json!({
        "id": format!("bacnet:{inst}:{object_type}:{instance}"),
        "point_id": format!("bacnet:{inst}:{object_type}:{instance}"),
        "device_instance": inst,
        "object_id": [object_type_to_class(object_type), instance],
        "object_type": object_type,
        "object_identifier": format!("{object_type},{instance}"),
        "object_name": name,
        "name": name,
        "present_value": present_value,
        "units": units,
        "polling_enabled": false,
        "writable": false,
        "local_server": true,
        "commandable": is_commandable_object_type(object_type),
        "haystack_id": format!("point:openfdd-{instance}")
    })
}

fn object_type_to_class(object_type: &str) -> u8 {
    match object_type {
        "analog-input" => 0,
        "analog-output" => 1,
        "analog-value" => 2,
        "binary-input" => 3,
        "binary-output" => 4,
        "binary-value" => 5,
        "multi-state-value" => 19,
        _ => 2,
    }
}

pub fn runtime_metrics() -> Value {
    let registry = bacnet::read_registry_value();
    let device_count = bacnet::count_discovered_devices(&registry);
    let poll = bacnet::poll_metrics();
    let faults = bacnet::active_fault_count();
    json!({
        "edge_online": true,
        "commission_agent_online": true,
        "poll_sample_count": poll.get("samples").cloned().unwrap_or(json!(0)),
        "devices_discovered": device_count,
        "active_fault_count": faults
    })
}

pub fn status_points() -> Vec<Value> {
    let m = runtime_metrics();
    vec![
        status_point(
            "binary-value",
            9001,
            "openfdd-edge-online",
            m["edge_online"].clone(),
            "bool",
        ),
        status_point(
            "binary-value",
            9002,
            "openfdd-commission-agent",
            m["commission_agent_online"].clone(),
            "bool",
        ),
        status_point(
            "analog-value",
            9001,
            "openfdd-poll-sample-count",
            m["poll_sample_count"].clone(),
            "count",
        ),
        status_point(
            "analog-value",
            9002,
            "openfdd-devices-discovered",
            m["devices_discovered"].clone(),
            "count",
        ),
        status_point(
            "analog-value",
            9003,
            "openfdd-active-fault-count",
            m["active_fault_count"].clone(),
            "count",
        ),
    ]
}

pub fn local_server_device() -> Value {
    let inst = device_instance();
    json!({
        "device_instance": inst,
        "name": format!("Local {} Server", device_name()),
        "description": "Open-FDD diagnostic BACnet device — not a field controller",
        "address": "local",
        "local_server": true,
        "polling_enabled": false,
        "points": status_points()
    })
}

pub fn server_points_json() -> String {
    serde_json::to_string_pretty(&json!({
        "ok": true,
        "device_instance": device_instance(),
        "device_name": device_name(),
        "note": "Local Open-FDD BACnet status objects for discovery and diagnostics only",
        "points": status_points(),
        "metrics": runtime_metrics()
    }))
    .unwrap_or_else(|_| "{}".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_server_has_five_status_points() {
        let points = status_points();
        assert_eq!(points.len(), 5);
        let ids: Vec<String> = points
            .iter()
            .filter_map(|p| p.get("object_identifier").and_then(|v| v.as_str()))
            .map(str::to_string)
            .collect();
        assert!(ids.contains(&"binary-value,9001".to_string()));
        assert!(ids.contains(&"binary-value,9002".to_string()));
        assert!(ids.contains(&"analog-value,9001".to_string()));
        assert!(ids.contains(&"analog-value,9002".to_string()));
        assert!(ids.contains(&"analog-value,9003".to_string()));
    }

    #[test]
    fn commandable_types_match_python_era() {
        assert!(is_commandable_object_type("analog-value"));
        assert!(!is_commandable_object_type("analog-input"));
    }
}
