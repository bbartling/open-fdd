//! BACnet diagnostic status helpers (no UDP). Fieldbus owns the live device.

use serde_json::{json, Value};

pub fn device_instance() -> u32 {
    599_999
}

pub fn device_name() -> String {
    "OpenFDD".into()
}

pub fn is_commandable_object_type(object_type: &str) -> bool {
    matches!(
        object_type,
        "analog-output" | "binary-output" | "multi-state-output" | "analog-value" | "binary-value"
    )
}

pub fn runtime_metrics() -> Value {
    json!({
        "enabled": false,
        "moved_to": "openfdd-fieldbus",
        "device_instance": device_instance(),
    })
}

pub fn status_points() -> Vec<Value> {
    vec![]
}

pub fn local_server_device() -> Value {
    json!({
        "device_instance": device_instance(),
        "device_name": device_name(),
        "local_server": true,
        "note": "hosted by openfdd-fieldbus"
    })
}

pub fn server_points_json() -> String {
    json!({
        "ok": true,
        "points": [],
        "hint": "Query openfdd-fieldbus GET /api/bacnet/server/points"
    })
    .to_string()
}
