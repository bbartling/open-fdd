//! Modbus driver facade (live TCP + simulated CI path).

use super::modbus_live;
use serde_json::{json, Value};
use std::env;

pub const POINTS_JSON: &str = r#"[
  {"id":"modbus:tcp:1:40001","name":"CHW Plant Supply Temp","register":40001,"function":"holding_register","value":44.8,"unit":"°F","address":"192.168.1.50:502","unit_id":1},
  {"id":"modbus:tcp:1:40002","name":"Pump Speed Command","register":40002,"function":"holding_register","value":62.0,"unit":"%","address":"192.168.1.50:502","unit_id":1}
]"#;

pub const RPI_POINTS_JSON: &str = r#"[
  {"id":"modbus:tcp:1:40001","name":"RPi Temp °F","register":40001,"function":"holding_register","scale":0.1,"unit":"°F","address":"192.168.204.14:1502","unit_id":1,"haystack_id":"point:rpi-temp-f"},
  {"id":"modbus:tcp:1:40002","name":"RPi Temp °C","register":40002,"function":"holding_register","scale":0.1,"unit":"°C","address":"192.168.204.14:1502","unit_id":1,"haystack_id":"point:rpi-temp-c"},
  {"id":"modbus:tcp:1:40003","name":"RPi Setpoint °F","register":40003,"function":"holding_register","scale":0.1,"unit":"°F","writable":true,"address":"192.168.204.14:1502","unit_id":1,"haystack_id":"point:rpi-sp-f"},
  {"id":"modbus:tcp:1:30003","name":"RPi Humidity","register":30003,"function":"input_register","scale":0.1,"unit":"%RH","address":"192.168.204.14:1502","unit_id":1,"haystack_id":"point:rpi-rh"}
]"#;

pub fn modbus_config_value() -> Value {
    let (host, port) = modbus_live::host_port();
    json!({
        "mode": env::var("OPENFDD_MODBUS_MODE").unwrap_or_else(|_| "simulated".to_string()),
        "host": host,
        "port": port.to_string(),
        "unit_id": modbus_live::unit_id().to_string(),
        "timeout_ms": modbus_live::timeout_ms().to_string()
    })
}

pub fn points_json() -> String {
    if modbus_live::is_live_mode() {
        RPI_POINTS_JSON.to_string()
    } else {
        POINTS_JSON.to_string()
    }
}

pub fn scan_value() -> Value {
    if modbus_live::is_live_mode() {
        match modbus_live::scan_device() {
            Ok(v) => v,
            Err(err) => json!({"ok": false, "error": err, "config": modbus_config_value()}),
        }
    } else {
        serde_json::from_str(&format!(
            r#"{{"ok":true,"devices":[{{"unit_id":1,"address":"192.168.1.50:502","name":"Plant Modbus Gateway"}}],"points":{},"source":"simulated"}}"#,
            POINTS_JSON
        ))
        .unwrap_or(json!({"ok": true, "source": "simulated"}))
    }
}

pub fn read_value(body: &Value) -> String {
    if modbus_live::is_live_mode() {
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
        return serde_json::to_string(
            &json!({"ok": false, "error": "register or point_id required"}),
        )
        .unwrap_or_else(|_| r#"{"ok":false}"#.to_string());
    }

    r#"{"point":"CHW Plant Supply Temp","value":44.8,"unit":"°F","source":"modbus-simulated"}"#
        .to_string()
}

pub fn commission_status_mode() -> &'static str {
    if modbus_live::is_live_mode() {
        "online"
    } else {
        "simulated"
    }
}

pub fn commission_status_json() -> String {
    json!({
        "ok": true,
        "service": "modbus-commission",
        "status": "ready",
        "config": modbus_config_value(),
        "features": ["scan", "read-holding", "read-input", "modbus-tcp-live"]
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
    let points: Vec<Value> = serde_json::from_str(&points_json()).unwrap_or_default();
    json!({
        "ok": true,
        "enabled": true,
        "service": "modbus-poll",
        "status": commission_status_mode(),
        "enabled_points": points.len(),
        "samples": 0,
        "config": modbus_config_value()
    })
    .to_string()
}

pub fn driver_tree_json() -> String {
    super::tree::modbus_driver_tree_json()
}
