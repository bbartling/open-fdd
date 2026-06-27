//! JSON API driver — real HTTP fetch via reqwest; no synthetic point fabrication.

use reqwest::blocking::Client;
use reqwest::StatusCode;
use serde_json::{json, Value};
use std::env;
use std::time::Duration;

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

fn http_client() -> Result<Client, String> {
    Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|e| format!("HTTP client build failed: {e}"))
}

fn extract_points(body: &Value) -> Vec<Value> {
    if let Some(arr) = body.as_array() {
        return arr.iter().filter_map(normalize_point).collect();
    }
    if let Some(points) = body.get("points").and_then(|v| v.as_array()) {
        return points.iter().filter_map(normalize_point).collect();
    }
    if let Some(data) = body.get("data").and_then(|v| v.as_array()) {
        return data.iter().filter_map(normalize_point).collect();
    }
    if body.is_object() {
        if let Some(p) = normalize_point(body) {
            return vec![p];
        }
    }
    Vec::new()
}

fn normalize_point(item: &Value) -> Option<Value> {
    let id = item
        .get("id")
        .or_else(|| item.get("point_id"))
        .and_then(|v| v.as_str())?;
    let value = item
        .get("value")
        .or_else(|| item.get("curVal"))
        .or_else(|| item.get("val"))
        .cloned()
        .unwrap_or(json!(null));
    Some(json!({
        "id": id,
        "value": value,
        "unit": item.get("unit").cloned().unwrap_or(json!(null)),
        "quality": item.get("quality").cloned().unwrap_or(json!("good"))
    }))
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
    let client = match http_client() {
        Ok(c) => c,
        Err(err) => {
            return json!({
                "ok": false,
                "source_id": source_id,
                "url": url,
                "response_time_ms": started.elapsed().as_millis() as u64,
                "parsed_points_count": 0,
                "error": err,
                "source_driver": "json-api"
            });
        }
    };

    match client.get(url).send() {
        Ok(resp) => {
            let response_time_ms = started.elapsed().as_millis() as u64;
            let http_status = resp.status().as_u16();
            let ok = resp.status() == StatusCode::OK;
            let body_text = resp.text().unwrap_or_default();
            let points = if ok {
                serde_json::from_str::<Value>(&body_text)
                    .map(|body| extract_points(&body))
                    .unwrap_or_default()
            } else {
                Vec::new()
            };
            json!({
                "ok": ok,
                "source_id": source_id,
                "url": url,
                "http_status": http_status,
                "response_time_ms": response_time_ms,
                "parsed_points_count": points.len(),
                "points": points,
                "source_driver": "json-api",
                "message": if ok {
                    if points.is_empty() {
                        "HTTP 200 OK — no mappable points in JSON body"
                    } else {
                        "HTTP 200 OK"
                    }
                } else {
                    "unexpected status"
                }
            })
        }
        Err(err) => json!({
            "ok": false,
            "source_id": source_id,
            "url": url,
            "response_time_ms": started.elapsed().as_millis() as u64,
            "parsed_points_count": 0,
            "error": err.to_string(),
            "source_driver": "json-api"
        }),
    }
}

pub fn poll_once_value(body: &Value) -> Value {
    if let Some(url) = body.get("url").and_then(|v| v.as_str()) {
        return poll_url(url);
    }
    poll_test_source()
}

pub fn refresh_point(body: &Value) -> Value {
    let point_id = body.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
    let sources: Vec<Value> = serde_json::from_str(SOURCES_JSON).unwrap_or_default();
    if point_id.is_empty() {
        let poll = poll_test_source();
        return json!({
            "ok": poll.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
            "present_value": poll.get("points").and_then(|v| v.as_array()).and_then(|a| a.first()).and_then(|p| p.get("value")).cloned().unwrap_or(Value::Null)
        });
    }
    for src in sources {
        if src.get("maps_to").and_then(|v| v.as_str()) != Some(point_id) {
            continue;
        }
        let url = src.get("url").and_then(|v| v.as_str()).unwrap_or("");
        if url.is_empty() {
            continue;
        }
        let poll = poll_url(url);
        let present = poll
            .get("points")
            .and_then(|v| v.as_array())
            .and_then(|a| a.first())
            .and_then(|p| p.get("value"))
            .cloned()
            .unwrap_or(Value::Null);
        return json!({
            "ok": poll.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
            "point_id": json!(point_id),
            "present_value": present,
            "url": url,
            "source_driver": "json-api"
        });
    }
    json!({"ok": false, "error": "point not found", "point_id": point_id})
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
    let sample = poll_once_value(&json!({}));
    json!({
        "ok": true,
        "enabled": true,
        "service": "json-api-poll",
        "status": "ready",
        "enabled_points": sources.len(),
        "samples": sample.get("parsed_points_count").cloned().unwrap_or(json!(0)),
        "last_poll": sample
    })
    .to_string()
}

pub fn driver_tree_json() -> String {
    super::tree::json_api_driver_tree_json()
}
