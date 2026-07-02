//! Modbus driver facade — live TCP only (rusty-modbus).

use super::live_gate;
use super::modbus_live;
use crate::historian::store;
use crate::model::scope;
use crate::validation::profile::{active_profile, is_modbus_configured};
use chrono::Utc;
use serde_json::{json, Value};
use std::env;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

static MODBUS_SAMPLES: AtomicU64 = AtomicU64::new(0);
static MODBUS_POLL_CYCLES: AtomicU64 = AtomicU64::new(0);
static MODBUS_LAST_POLL: Mutex<Option<String>> = Mutex::new(None);
static MODBUS_LAST_ERROR: Mutex<Option<String>> = Mutex::new(None);

struct PollCycleDetail {
    reads_ok: u64,
    reads_failed: u64,
    samples_written: u64,
    append_error: Option<String>,
}

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
    let mut points = points;
    if p.modbus_register > 0 {
        let reg = p.modbus_register;
        let func = if (30001..40001).contains(&reg) {
            "input_register"
        } else {
            "holding_register"
        };
        let id = format!("modbus:tcp:{unit}:{reg}");
        if !points
            .iter()
            .any(|pt| pt.get("register").and_then(|v| v.as_u64()) == Some(reg as u64))
        {
            points.push(json!({
                "id": id,
                "name": "Profile register",
                "register": reg,
                "function": func,
                "scale": 0.1,
                "unit": "°F",
                "address": addr,
                "unit_id": unit,
                "haystack_id": "point:modbus-profile"
            }));
        }
    }
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
        (
            String::new(),
            1502,
            "not_configured",
            "Modbus live mode required".into(),
        )
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
    let last_poll = MODBUS_LAST_POLL.lock().ok().and_then(|g| g.clone());
    let last_error = MODBUS_LAST_ERROR.lock().ok().and_then(|g| g.clone());
    json!({
        "ok": true,
        "enabled": true,
        "service": "modbus-poll",
        "status": commission_status_mode(),
        "enabled_points": points.len(),
        "samples": MODBUS_SAMPLES.load(Ordering::Relaxed),
        "poll_cycles": MODBUS_POLL_CYCLES.load(Ordering::Relaxed),
        "last_poll": last_poll.clone().map(Value::String).unwrap_or(Value::Null),
        "at": last_poll.map(Value::String).unwrap_or(Value::Null),
        "last_error": last_error.clone().map(Value::String).unwrap_or(Value::Null),
        "error": last_error.map(Value::String).unwrap_or(Value::Null),
        "interval_s": poll_interval_s(),
        "config": cfg
    })
    .to_string()
}

pub fn poll_interval_s() -> u64 {
    if let Ok(v) = env::var("OPENFDD_MODBUS_POLL_INTERVAL_SECONDS") {
        if let Ok(s) = v.parse() {
            return s;
        }
    }
    let p = active_profile();
    if p.modbus_poll_interval_seconds > 0 {
        p.modbus_poll_interval_seconds
    } else {
        60
    }
}

fn poll_cycle_and_persist_detail() -> PollCycleDetail {
    let points: Vec<Value> = serde_json::from_str(&live_points_from_profile()).unwrap_or_default();
    if points.is_empty() {
        return PollCycleDetail {
            reads_ok: 0,
            reads_failed: 0,
            samples_written: 0,
            append_error: Some("no poll points configured".into()),
        };
    }
    let profile = active_profile();
    let equipment_id = scope::resolve_equipment_id(Some(profile.equipment_id.as_str()))
        .unwrap_or_else(|| "equip:local-default".to_string());
    if equipment_id.is_empty() {
        return PollCycleDetail {
            reads_ok: 0,
            reads_failed: 0,
            samples_written: 0,
            append_error: Some("equipment_id unresolved".into()),
        };
    }
    let ts = Utc::now().to_rfc3339();
    let mut oa_t = None::<f64>;
    let mut oa_h = None::<f64>;
    let mut reads_ok = 0_u64;
    let mut reads_failed = 0_u64;

    for pt in &points {
        let register = pt
            .get("register")
            .and_then(|v| v.as_u64())
            .map(|v| v as u16);
        let function = pt
            .get("function")
            .and_then(|v| v.as_str())
            .unwrap_or("holding_register");
        let scale = pt.get("scale").and_then(|v| v.as_f64()).unwrap_or(0.1);
        let unit = pt.get("unit").and_then(|v| v.as_str()).unwrap_or("raw");
        let Some(reg) = register else {
            reads_failed += 1;
            continue;
        };
        match modbus_live::read_scaled_register(reg, function, scale, unit) {
            Ok(v) => {
                reads_ok += 1;
                let value = v.get("value").and_then(|x| x.as_f64());
                let haystack = pt.get("haystack_id").and_then(|x| x.as_str()).unwrap_or("");
                if haystack.contains("temp")
                    || haystack.contains("oa")
                    || reg == profile.modbus_register
                {
                    oa_t = value.or(oa_t);
                } else if haystack.contains("rh") || haystack.contains("humidity") {
                    oa_h = value.or(oa_h);
                }
            }
            Err(_) => reads_failed += 1,
        }
    }

    if oa_t.is_none() && oa_h.is_none() {
        return PollCycleDetail {
            reads_ok,
            reads_failed,
            samples_written: 0,
            append_error: if reads_ok == 0 {
                Some("all register reads failed".into())
            } else {
                Some("no telemetry columns mapped from reads".into())
            },
        };
    }

    let row = store::make_pivot_row(store::PivotSample {
        timestamp: &ts,
        equipment_id: &equipment_id,
        oa_t: oa_t.unwrap_or(0.0),
        oa_h: oa_h.unwrap_or(0.0),
        duct_t: 0.0,
        zn_t: 0.0,
        source: "source:modbus:poll",
        source_driver: "modbus",
        is_simulated: false,
    });
    match store::append_pivot_row(&row) {
        Ok(()) => PollCycleDetail {
            reads_ok,
            reads_failed,
            samples_written: 1,
            append_error: None,
        },
        Err(e) => PollCycleDetail {
            reads_ok,
            reads_failed,
            samples_written: 0,
            append_error: Some(e),
        },
    }
}

fn record_poll_cycle(detail: &PollCycleDetail) {
    MODBUS_POLL_CYCLES.fetch_add(1, Ordering::Relaxed);
    if detail.samples_written > 0 {
        MODBUS_SAMPLES.fetch_add(detail.samples_written, Ordering::Relaxed);
        if let Ok(mut g) = MODBUS_LAST_POLL.lock() {
            *g = Some(Utc::now().to_rfc3339());
        }
        if let Ok(mut e) = MODBUS_LAST_ERROR.lock() {
            *e = None;
        }
    } else if let Some(ref err) = detail.append_error {
        if let Ok(mut e) = MODBUS_LAST_ERROR.lock() {
            *e = Some(err.clone());
        }
    }
}

pub fn poll_once_value() -> Value {
    if let Some(err) = live_gate::modbus_live_required("poll-once") {
        return err;
    }
    let cfg = modbus_config_value();
    if cfg.get("status").and_then(|v| v.as_str()) == Some("not_configured") {
        return json!({
            "ok": false,
            "error": "Modbus not configured",
            "config": cfg
        });
    }
    let detail = poll_cycle_and_persist_detail();
    record_poll_cycle(&detail);
    json!({
        "ok": true,
        "polled": 1,
        "samples_written": detail.samples_written,
        "samples": MODBUS_SAMPLES.load(Ordering::Relaxed),
        "points_read": detail.reads_ok,
        "reads_ok": detail.reads_ok,
        "reads_failed": detail.reads_failed,
        "append_error": detail.append_error,
        "poll_cycles": MODBUS_POLL_CYCLES.load(Ordering::Relaxed),
    })
}

pub fn start_modbus_poll_loop(service_mode: String) {
    if service_mode != "bridge" && service_mode != "commission" {
        return;
    }
    thread::spawn(|| loop {
        if modbus_live::is_live_mode() && protocol_enabled("OPENFDD_MODBUS_ENABLED") {
            let cfg = modbus_config_value();
            if cfg.get("status").and_then(|v| v.as_str()) != Some("not_configured") {
                let detail = poll_cycle_and_persist_detail();
                record_poll_cycle(&detail);
            }
        }
        thread::sleep(Duration::from_secs(poll_interval_s()));
    });
}

pub fn driver_tree_json() -> String {
    super::tree::modbus_driver_tree_json()
}
