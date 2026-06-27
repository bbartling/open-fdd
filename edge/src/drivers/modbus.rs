//! Modbus driver facade — live TCP only (rusty-modbus).

use super::live_gate;
use super::modbus_live;
use crate::validation::profile::{active_profile, is_modbus_configured};
use serde_json::{json, Value};
use std::env;

fn live_points_from_profile() -> String {
    let p = active_profile();
    if !is_modbus_configured(&p) {
        return "[]".to_string();
    }
    let addr = format!("{}:{}", p.modbus_host, p.modbus_port);
    let unit = p.modbus_unit_id;
    let points = vec![
        json!({"id":format!("modbus:tcp:{unit}:40001"),"name":"Temp °F","register":40001,"function":"holding_register","scale":0.1,"unit":"°F","address":addr,"unit_id":unit,"haystack_id":"point:modbus-temp-f"}),
        json!({"id":format!("modbus:tcp:{unit}:40002"),"name":"Temp °C","register":40002,"function":"holding_register","scale":0.1,"unit":"°C","address":addr,"unit_id":unit,"haystack_id":"point:modbus-temp-c"}),
        json!({"id":format!("modbus:tcp:{unit}:40003"),"name":"Setpoint °F","register":40003,"function":"holding_register","scale":0.1,"unit":"°F","writable":true,"address":addr,"unit_id":unit,"haystack_id":"point:modbus-sp-f"}),
        json!({"id":format!("modbus:tcp:{unit}:30003"),"name":"Humidity","register":30003,"function":"input_register","scale":0.1,"unit":"%RH","address":addr,"unit_id":unit,"haystack_id":"point:modbus-rh"}),
    ];
    serde_json::to_string(&points).unwrap_or_else(|_| "[]".to_string())
}

pub fn modbus_config_value() -> Value {
    let profile = active_profile();
    let configured = is_modbus_configured(&profile);
    let mode = if modbus_live::is_live_mode() {
        "live"
    } else {
        "disabled"
    };
    let (host, port, status, message): (String, u16, &str, String) = if configured {
        (
            profile.modbus_host.clone(),
            profile.modbus_port,
            "configured",
            String::new(),
        )
    } else if modbus_live::is_live_mode() {
        match modbus_live::host_port() {
            Ok((h, p)) => (h, p, "env", String::new()),
            Err(msg) => (String::new(), 1502, "not_configured", msg),
        }
    } else {
        (String::new(), 1502, "not_configured", "Modbus live mode required".into())
    };
    json!({
        "mode": mode,
        "host": host,
        "port": port.to_string(),
        "unit_id": modbus_live::unit_id().to_string(),
        "timeout_ms": modbus_live::timeout_ms().to_string(),
        "configured": configured || status == "env",
        "status": status,
        "message": message
    })
}

pub fn points_json() -> String {
    if let Some(err) = live_gate::modbus_live_required("points") {
        return serde_json::to_string(&err).unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }
    live_points_from_profile()
}

pub fn scan_value() -> Value {
    if let Some(err) = live_gate::modbus_live_required("scan") {
        return err;
    }
    match modbus_live::scan_device() {
        Ok(v) => v,
        Err(err) => json!({"ok": false, "error": err, "config": modbus_config_value()}),
    }
}

pub fn read_value(body: &Value) -> String {
    if let Some(err) = live_gate::modbus_live_required("read") {
        return serde_json::to_string(&err).unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }
    let register = body
        .get("register")
        .and_then(|v| v.as_u64())
        .map(|v| v as u16)
        .or_else(|| {
            body.get("point_id")
                .and_then(|v| v.as_str())
                .and_then(modbus_live::parse_point_id)
                .map(|(_, reg, _)| reg)
        });

    let function = body
        .get("function")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .or_else(|| {
            body.get("point_id")
                .and_then(|v| v.as_str())
                .and_then(modbus_live::parse_point_id)
                .map(|(_, _, func)| func)
        })
        .unwrap_or_else(|| "holding_register".to_string());

    let scale = body.get("scale").and_then(|v| v.as_f64()).unwrap_or(0.1);
    let unit = body.get("unit").and_then(|v| v.as_str()).unwrap_or("raw");

    if let Some(reg) = register {
        match modbus_live::read_scaled_register(reg, &function, scale, unit) {
            Ok(v) => return serde_json::to_string(&v).unwrap_or_else(|_| "{}".to_string()),
            Err(err) => {
                return serde_json::to_string(&json!({"ok": false, "error": err}))
                    .unwrap_or_else(|_| r#"{"ok":false}"#.to_string())
            }
        }
    }
    serde_json::to_string(&json!({"ok": false, "error": "register or point_id required"}))
        .unwrap_or_else(|_| r#"{"ok":false}"#.to_string())
}

pub fn commission_status_mode() -> &'static str {
    if modbus_live::is_live_mode() {
        "online"
    } else {
        "not_configured"
    }
}

pub fn commission_status_json() -> String {
    json!({
        "ok": true,
        "service": "modbus-commission",
        "status": "ready",
        "config": modbus_config_value(),
        "features": ["scan", "read-holding", "read-input", "rusty-modbus-live"]
    })
    .to_string()
}

fn protocol_enabled(env_key: &str) -> bool {
    env::var(env_key)
        .map(|v| v != "0" && v.to_lowercase() != "false")
        .unwrap_or(true)
}

pub fn poll_status_json() -> String {
    if !protocol_enabled("OPENFDD_MODBUS_ENABLED") {
        return json!({
            "ok": true,
            "enabled": false,
            "status": "disabled",
            "message": "Modbus is disabled or not configured"
        })
        .to_string();
    }
    if let Some(err) = live_gate::modbus_live_required("poll") {
        return serde_json::to_string(&err).unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }
    let cfg = modbus_config_value();
    if cfg.get("status").and_then(|v| v.as_str()) == Some("not_configured") {
        return json!({
            "ok": true,
            "enabled": false,
            "status": "not_configured",
            "message": "Modbus not configured — set profile [modbus] or OPENFDD_MODBUS_HOST",
            "config": cfg
        })
        .to_string();
    }
    let points: Vec<Value> = serde_json::from_str(&points_json()).unwrap_or_default();
    json!({
        "ok": true,
        "enabled": true,
        "service": "modbus-poll",
        "status": commission_status_mode(),
        "enabled_points": points.len(),
        "samples": 0,
        "config": cfg
    })
    .to_string()
}

pub fn driver_tree_json() -> String {
    super::tree::modbus_driver_tree_json()
}
