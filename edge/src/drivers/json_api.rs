//! JSON API driver facade.
//!
//! Production direction:
//! - register HTTP JSON sources with URL, headers, polling cadence, timestamp
//!   mapping, point mapping, and units.
//! - poll them into normalized point samples for Arrow/DataFusion.

use serde_json::{json, Value};
use std::env;
use std::process::Command;

pub const SOURCES_JSON: &str = r#"[
  {"id":"httpbin-health","url":"https://httpbin.org/get","maps_to":"json_api_health","status":"test-bench","kind":"http-get"},
  {"id":"postman-echo","url":"https://postman-echo.com/get","maps_to":"json_api_echo","status":"test-bench","kind":"http-get"},
  {"id":"plant-json-api","url":"http://edge-controller.local/api/points","maps_to":"plant telemetry","status":"optional"}
]"#;

pub fn sources_json() -> &'static str {
    SOURCES_JSON
}

pub fn register_json() -> &'static str {
    r#"{"ok":true,"status":"registered","source":"custom-json-api","runtime":"rust"}"#
}

pub fn poll_once_json() -> String {
    serde_json::to_string(&poll_test_source()).unwrap_or_else(|_| r#"{"ok":false}"#.to_string())
}

pub fn poll_test_source() -> Value {
    let url = env::var("OPENFDD_JSON_API_TEST_URL")
        .unwrap_or_else(|_| "https://httpbin.org/get".to_string());
    poll_url(&url)
}

pub fn poll_url(url: &str) -> Value {
    let source_id =
        env::var("OPENFDD_JSON_API_TEST_SOURCE").unwrap_or_else(|_| "json-api-smoke".to_string());
    let started = std::time::Instant::now();
    let output = Command::new("curl")
        .args(["-fsS", "-o", "/dev/null", "-w", "%{http_code}", url])
        .output();
    let response_time_ms = started.elapsed().as_millis() as u64;
    match output {
        Ok(out) if out.status.success() => {
            let code = String::from_utf8_lossy(&out.stdout).trim().to_string();
            let http_status = code.parse::<u64>().unwrap_or(0);
            let ok = http_status == 200;
            json!({
                "ok": ok,
                "source_id": source_id,
                "url": url,
                "http_status": http_status,
                "response_time_ms": response_time_ms,
                "parsed_points_count": if ok { 1 } else { 0 },
                "points": [{"id":"point:json-api-health","value":1,"unit":"bool","quality":"good"}],
                "source_driver": "json-api",
                "message": if ok { "HTTP 200 OK" } else { "unexpected status" }
            })
        }
        Ok(out) => json!({
            "ok": false,
            "source_id": source_id,
            "url": url,
            "response_time_ms": response_time_ms,
            "parsed_points_count": 0,
            "error": String::from_utf8_lossy(&out.stderr).to_string()
        }),
        Err(err) => json!({
            "ok": false,
            "source_id": source_id,
            "url": url,
            "response_time_ms": response_time_ms,
            "parsed_points_count": 0,
            "error": err.to_string()
        }),
    }
}

pub fn poll_once_value(body: &Value) -> Value {
    let _ = body;
    poll_test_source()
}

fn protocol_enabled(env_key: &str) -> bool {
    env::var(env_key)
        .map(|v| v != "0" && v.to_lowercase() != "false")
        .unwrap_or(true)
}

pub fn poll_status_json() -> String {
    if !protocol_enabled("OPENFDD_JSON_API_ENABLED") {
        return json!({
            "ok": true,
            "enabled": false,
            "status": "disabled",
            "message": "JSON API driver is disabled or not configured"
        })
        .to_string();
    }
    let sources: Vec<Value> = serde_json::from_str(SOURCES_JSON).unwrap_or_default();
    json!({
        "ok": true,
        "enabled": true,
        "service": "json-api-poll",
        "status": "ready",
        "enabled_points": sources.len(),
        "samples": 0
    })
    .to_string()
}

pub fn driver_tree_json() -> String {
    super::tree::json_api_driver_tree_json()
}
