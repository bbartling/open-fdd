//! Shared live-mode gates — no simulated OT data in production paths.

use serde_json::{json, Value};
use std::env;

/// Legacy edge field sockets (BACnet/Modbus/Haystack wire) are opt-in during cutover.
pub fn legacy_field_wire_allowed() -> bool {
    env::var("OPENFDD_ALLOW_LEGACY_FIELD_WIRE").as_deref() == Ok("1")
}

/// Central role must never open OT field sockets.
pub fn is_central_service_role() -> bool {
    env::var("OPENFDD_SERVICE_ROLE")
        .map(|v| v == "central")
        .unwrap_or(false)
        || env::var("SERVICE_MODE")
            .map(|v| v == "central")
            .unwrap_or(false)
}

pub fn field_wire_relocated_json(operation: &str, protocol: &str) -> Value {
    json!({
        "ok": false,
        "error": format!("{protocol} wire I/O moved to openfdd-fieldbus"),
        "operation": operation,
        "hint": "Run openfdd-fieldbus and ingest telemetry via MQTTS to openfdd-central",
        "mqtt_topics": format!("openfdd/v1/sites/{{site}}/edges/{{edge}}/telemetry/{protocol}")
    })
}

/// Returns relocated JSON when central role or legacy wire is not explicitly allowed.
/// Unit tests (`cfg!(test)`) keep exercising in-tree mock/fixture helpers.
pub fn field_wire_blocked(operation: &str, protocol: &str) -> Option<Value> {
    if is_central_service_role() {
        return Some(field_wire_relocated_json(operation, protocol));
    }
    if cfg!(test) || legacy_field_wire_allowed() {
        None
    } else {
        Some(field_wire_relocated_json(operation, protocol))
    }
}

/// Background BACnet/Modbus poll loops only run on legacy bridge/commission edge hosts.
pub fn should_start_field_poll_loops(service_mode: &str) -> bool {
    if is_central_service_role() {
        return false;
    }
    // Production default: no OT poll loops on the central/edge monolith.
    // Opt in with OPENFDD_ALLOW_LEGACY_FIELD_WIRE=1 for bridge/commission only.
    if !legacy_field_wire_allowed() {
        return false;
    }
    service_mode == "bridge" || service_mode == "commission"
}

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

#[cfg(test)]
mod tests {
    #[test]
    fn modbus_rejects_simulated_mode_string() {
        std::env::set_var("OPENFDD_MODBUS_MODE", "simulated");
        assert!(!super::super::modbus_live::is_live_mode());
        std::env::set_var("OPENFDD_MODBUS_MODE", "live");
    }

    #[test]
    fn bacnet_rejects_simulated_mode_string() {
        std::env::set_var("OPENFDD_BACNET_MODE", "simulated");
        assert!(!super::super::bacnet_live::is_live_mode());
        std::env::set_var("OPENFDD_BACNET_MODE", "live");
    }

    #[test]
    fn live_gate_blocks_bacnet_when_not_live() {
        std::env::set_var("OPENFDD_BACNET_MODE", "simulated");
        let err = super::bacnet_live_required("whois").expect("expected gate error");
        assert_eq!(err.get("ok").and_then(|v| v.as_bool()), Some(false));
        std::env::set_var("OPENFDD_BACNET_MODE", "live");
    }
}
