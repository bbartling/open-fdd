//! Shared live-mode gates — no simulated OT data in production paths.

use serde_json::{json, Value};

pub fn bacnet_live_required(operation: &str) -> Option<Value> {
    if super::bacnet_live::is_live_mode() {
        None
    } else {
        Some(json!({
            "ok": false,
            "error": "BACnet live mode required",
            "operation": operation,
            "hint": "Set OPENFDD_BACNET_MODE=live and configure OPENFDD_BACNET_BIND"
        }))
    }
}

pub fn modbus_live_required(operation: &str) -> Option<Value> {
    if super::modbus_live::is_live_mode() {
        None
    } else {
        Some(json!({
            "ok": false,
            "error": "Modbus live mode required",
            "operation": operation,
            "hint": "Set OPENFDD_MODBUS_MODE=live and configure OPENFDD_MODBUS_HOST"
        }))
    }
}
