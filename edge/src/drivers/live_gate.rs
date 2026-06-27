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
