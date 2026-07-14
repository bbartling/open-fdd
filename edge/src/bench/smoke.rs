//! Live FDD validation smoke helpers (BACnet wire capture retired → fieldbus MQTTS).

use crate::drivers::{json_api, modbus};
use crate::fdd::execution;
use crate::historian::store;
use crate::validation::profile::{self, SiteConfig};
use chrono::Utc;
use serde_json::{json, Value};

pub fn confirmation_seconds() -> i64 {
    profile::active_profile().confirmation_minutes * 60
}

pub fn default_rule_sql() -> String {
    profile::fdd_sql(&profile::active_profile())
}

pub fn status_json() -> Value {
    let p = profile::active_profile();
    let rows = store::load_pivot_rows().unwrap_or_default();
    let eval = evaluate_historian_fdd();
    let data_source = detect_data_source(&rows);
    let demo_only = data_source.starts_with("demo") || rows.is_empty();
    json!({
        "ok": true,
        "run_id": "current",
        "profile": profile::profile_summary_json(),
        "smoke_device_instance": p.device_instance,
        "equipment_id": p.equipment_id,
        "source_id": p.source_id,
        "short_fdd_mode": false,
        "live_fdd_required": false,
        "data_source": data_source,
        "demo_only": demo_only,
        "historian": store::status_json(),
        "bacnet_points": bacnet_points_meta(&p),
        "modbus": modbus_probe(&p),
        "json_api": json_api_probe(&p),
        "haystack": haystack_fixture_status(&p),
        "rule_sql": default_rule_sql(),
        "fdd_eval": eval,
        "artifact_dir": artifact_dir(&p).display().to_string(),
        "proof": proof_summary(&eval, demo_only)
    })
}

fn artifact_dir(p: &SiteConfig) -> std::path::PathBuf {
    store::workspace_dir().join("logs").join(&p.artifact_subdir)
}

fn detect_data_source(rows: &[Value]) -> String {
    if rows.is_empty() {
        return "empty".to_string();
    }
    let mut live = 0;
    let mut demo = 0;
    for row in rows {
        match row.get("source").and_then(|v| v.as_str()).unwrap_or("") {
            s if s.starts_with("validation:fixture") => live += 1,
            s if s.starts_with("bacnet:live") => live += 1,
            s if s.contains("demo") => demo += 1,
            _ if !row
                .get("is_simulated")
                .and_then(|v| v.as_bool())
                .unwrap_or(false) =>
            {
                live += 1
            }
            _ => demo += 1,
        }
    }
    if live > 0 && demo == 0 {
        "bacnet:live".to_string()
    } else if demo > 0 {
        "demo:static".to_string()
    } else {
        "mixed".to_string()
    }
}

fn bacnet_points_meta(p: &SiteConfig) -> Value {
    json!(effective_points(p)
        .iter()
        .map(|pt| json!({
            "name": pt.name,
            "object_instance": pt.object_instance,
            "fdd_input": pt.fdd_input,
            "bacnet_id": format!("bacnet:{}:analog-input:{}", p.device_instance, pt.object_instance)
        }))
        .collect::<Vec<_>>())
}

fn effective_points(p: &SiteConfig) -> Vec<profile::BacnetPointRole> {
    if !p.bacnet_points.is_empty() {
        return p.bacnet_points.clone();
    }
    vec![]
}

fn modbus_probe(p: &SiteConfig) -> Value {
    if !profile::is_modbus_configured(p) {
        return json!({
            "configured": false,
            "status": "skipped",
            "message": "Modbus not configured",
            "available": false,
            "degraded": false
        });
    }
    let body = json!({
        "register": p.modbus_register,
        "function": "input_register",
        "scale": 0.1,
        "unit": "degF"
    });
    let read = modbus::read_value(&body);
    let parsed: Value = serde_json::from_str(&read).unwrap_or(json!({"ok": false}));
    json!({
        "configured_host": p.modbus_host,
        "configured_port": p.modbus_port,
        "mode": modbus::modbus_config_value().get("mode"),
        "registers_tested": [p.modbus_register],
        "last_read": parsed,
        "available": parsed.get("ok").and_then(|v| v.as_bool()).unwrap_or(parsed.get("value").is_some()),
        "degraded": parsed.get("ok").and_then(|v| v.as_bool()) != Some(true)
    })
}

fn json_api_probe(p: &SiteConfig) -> Value {
    let poll = if let Some(url) = &p.json_api_url {
        json_api::poll_url(url)
    } else {
        json_api::poll_once_value(&json!({}))
    };
    json!({
        "source_id": poll.get("source_id"),
        "url": poll.get("url"),
        "http_status": poll.get("http_status"),
        "response_time_ms": poll.get("response_time_ms"),
        "parsed_points_count": poll
            .get("parsed_points_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0),
        "ok": poll.get("ok"),
        "available": poll.get("ok").and_then(|v| v.as_bool()) == Some(true),
        "error": poll.get("error")
    })
}

fn haystack_fixture_status(p: &SiteConfig) -> Value {
    let site = crate::model::scope::active_site_id().unwrap_or_else(|| "site:unknown".to_string());
    json!({
        "mode": "fixture",
        "site": site,
        "equip": format!("equip:{}", p.equipment_id),
        "driver_tree": true
    })
}

pub fn capture_sample(_body: &Value) -> Value {
    json!({
        "ok": false,
        "error": "BACnet capture moved to openfdd-fieldbus MQTTS ingest",
        "demo_only": true,
        "hint": "Publish telemetry via fieldbus; central persists Feather/historian rows"
    })
}

pub fn evaluate_historian_fdd() -> Value {
    let rows = store::load_pivot_rows().unwrap_or_default();
    if rows.is_empty() {
        return json!({
            "ok": false,
            "error": "historian empty — capture samples first",
            "demo_only": true
        });
    }
    let data_source = detect_data_source(&rows);
    let sql = default_rule_sql();
    let mut result =
        execution::run_rule_sql_from_historian(&sql, confirmation_seconds(), &json!({}));
    if let Some(obj) = result.as_object_mut() {
        obj.insert("data_source".into(), json!(data_source));
        obj.insert(
            "demo_only".into(),
            json!(data_source.starts_with("demo") || data_source == "empty"),
        );
        obj.insert("historian_row_count".into(), json!(rows.len()));
        obj.insert("rule_sql".into(), json!(sql));
    }
    result
}

pub fn evaluate_sample(body: &Value) -> Value {
    let capture = capture_sample(body);
    if capture.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return capture;
    }
    let eval = evaluate_historian_fdd();
    json!({
        "ok": true,
        "capture": capture,
        "fdd_eval": eval,
        "proof": proof_summary(&eval, eval.get("demo_only").and_then(|v| v.as_bool()).unwrap_or(true))
    })
}

fn proof_summary(eval: &Value, demo_only: bool) -> Value {
    let rows = eval
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut raw_true = 0;
    let mut raw_false = 0;
    let mut confirmed_true = 0;
    for row in &rows {
        if row.get("raw_fault").and_then(|v| v.as_bool()) == Some(true) {
            raw_true += 1;
        } else {
            raw_false += 1;
        }
        if row.get("confirmed_fault").and_then(|v| v.as_bool()) == Some(true) {
            confirmed_true += 1;
        }
    }
    let confirmation = eval.get("confirmation").cloned().unwrap_or(json!({}));
    let confirmed_from_sql = confirmed_true >= 1;
    let confirmed_from_streak = confirmation
        .get("confirmed_fault_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
        >= 1;
    let pass = !demo_only
        && raw_false > 0
        && raw_true > 0
        && (confirmed_from_sql || confirmed_from_streak);
    json!({
        "demo_only": demo_only,
        "live_fdd_pass": pass,
        "raw_fault_samples": raw_true,
        "no_fault_samples": raw_false,
        "confirmed_fault_samples": confirmed_true,
        "raw_fault_count": confirmation.get("raw_fault_count"),
        "confirmed_fault_count": confirmation.get("confirmed_fault_count"),
        "confirmation_seconds": confirmation_seconds(),
        "confirmation_required_minutes": profile::active_profile().confirmation_minutes,
        "message": if demo_only {
            "DEMO ONLY — not a live FDD pass"
        } else if pass {
            "Live FDD proof satisfied"
        } else {
            "Collect more samples (normal → sustained fault → clear)"
        }
    })
}

pub fn inject_scenario(body: &Value) -> Value {
    let p = profile::active_profile();
    let normal_min = body
        .get("normal_minutes")
        .and_then(|v| v.as_u64())
        .unwrap_or(5);
    let fault_min = body
        .get("fault_minutes")
        .and_then(|v| v.as_u64())
        .unwrap_or(6);
    let clear_min = body
        .get("clear_minutes")
        .and_then(|v| v.as_u64())
        .unwrap_or(5);
    let _ = store::clear_rows_with_source_prefix("validation:fixture");
    let start = Utc::now();
    let rows = super::validation_fixture::inject_scenario_rows(
        &p, start, normal_min, fault_min, clear_min,
    );
    if let Err(err) = store::rewrite_all(&rows) {
        return json!({"ok": false, "error": err});
    }
    let eval = evaluate_historian_fdd();
    json!({
        "ok": true,
        "injected_rows": rows.len(),
        "data_source": "validation:fixture",
        "demo_only": false,
        "fdd_eval": eval,
        "proof": proof_summary(&eval, false)
    })
}
