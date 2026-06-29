//! JSON API driver — real HTTP fetch via reqwest; no synthetic point fabrication.

use chrono::Utc;
use reqwest::blocking::Client;
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use reqwest::StatusCode;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

use crate::historian::store;

pub fn sources_json() -> String {
    let endpoints = load_saved_endpoints();
    json!({
        "ok": true,
        "configured": !endpoints.is_empty(),
        "sources": endpoints
    })
    .to_string()
}

pub fn register_json() -> &'static str {
    r#"{"ok":true,"status":"registered","source":"custom-json-api","runtime":"rust"}"#
}

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

pub fn endpoints_path() -> PathBuf {
    workspace_dir().join("data/json_api/endpoints.json")
}

pub fn load_saved_endpoints() -> Vec<Value> {
    let path = endpoints_path();
    if !path.exists() {
        return Vec::new();
    }
    let text = fs::read_to_string(&path).unwrap_or_default();
    serde_json::from_str::<Value>(&text)
        .ok()
        .and_then(|v| v.get("endpoints").and_then(|e| e.as_array()).cloned())
        .unwrap_or_default()
}

fn write_saved_endpoints(endpoints: &[Value]) -> Result<(), String> {
    let path = endpoints_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let doc = json!({"ok": true, "endpoints": endpoints, "updated_at": Utc::now().to_rfc3339()});
    fs::write(
        &path,
        serde_json::to_string_pretty(&doc).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

fn host_from_url(url: &str) -> String {
    url.split('/').nth(2).unwrap_or("unknown-host").to_string()
}

fn extract_json_path(body: &Value, path: &str) -> Option<Value> {
    let path = path.trim();
    if path.is_empty() || path == "$" || path == "." {
        return Some(body.clone());
    }
    let mut cur = body;
    for part in path.split('.') {
        if part.is_empty() {
            continue;
        }
        cur = cur.get(part)?;
    }
    Some(cur.clone())
}

fn build_client(verify_tls: bool) -> Result<Client, String> {
    Client::builder()
        .timeout(Duration::from_secs(20))
        .danger_accept_invalid_certs(!verify_tls)
        .build()
        .map_err(|e| format!("HTTP client build failed: {e}"))
}

pub fn http_request(payload: &Value) -> Value {
    let url = payload.get("url").and_then(|v| v.as_str()).unwrap_or("");
    if url.is_empty() {
        return json!({"success": false, "error": "url required"});
    }
    let method = payload
        .get("method")
        .and_then(|v| v.as_str())
        .unwrap_or("GET")
        .to_uppercase();
    let json_path = payload
        .get("json_path")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let verify_tls = payload
        .get("verify_tls")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let auth_type = payload
        .get("auth_type")
        .and_then(|v| v.as_str())
        .unwrap_or("none");

    let client = match build_client(verify_tls) {
        Ok(c) => c,
        Err(err) => return json!({"success": false, "error": err}),
    };

    let mut req = if method == "POST" {
        let mut r = client.post(url);
        if let Some(body) = payload.get("body") {
            r = r.header(CONTENT_TYPE, "application/json").json(body);
        }
        r
    } else {
        client.get(url)
    };

    match auth_type {
        "bearer" => {
            if let Some(token) = payload.get("bearer_token").and_then(|v| v.as_str()) {
                if !token.is_empty() {
                    req = req.header(AUTHORIZATION, format!("Bearer {token}"));
                }
            }
        }
        "basic" => {
            let user = payload
                .get("basic_user")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            let pass = payload
                .get("basic_password")
                .and_then(|v| v.as_str())
                .unwrap_or("");
            req = req.basic_auth(user, Some(pass));
        }
        _ => {}
    }

    let started = std::time::Instant::now();
    match req.send() {
        Ok(resp) => {
            let status_code = resp.status().as_u16();
            let body_text = resp.text().unwrap_or_default();
            let parsed: Value =
                serde_json::from_str(&body_text).unwrap_or(json!({"raw": body_text}));
            let extracted = extract_json_path(&parsed, json_path).unwrap_or(Value::Null);
            let present_value = extracted.to_string();
            json!({
                "success": (200..300).contains(&status_code),
                "status_code": status_code,
                "present_value": present_value,
                "extracted": extracted,
                "response_time_ms": started.elapsed().as_millis() as u64,
                "body_preview": if body_text.len() > 500 { format!("{}…", &body_text[..500]) } else { body_text }
            })
        }
        Err(err) => json!({
            "success": false,
            "error": err.to_string(),
            "status_code": 0
        }),
    }
}

pub fn read_and_store(payload: &Value) -> Value {
    let label = payload
        .get("label")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .unwrap_or("json_value");
    let mut result = http_request(payload);
    let success = result.get("success").and_then(|v| v.as_bool()) == Some(true);
    if !success {
        result["ok"] = json!(false);
        return result;
    }

    let present = result.get("present_value").cloned().unwrap_or(json!(null));
    let numeric = present
        .as_f64()
        .or_else(|| present.as_str().and_then(|s| s.parse().ok()));

    if let Some(n) = numeric {
        let ts = Utc::now().to_rfc3339();
        let source = format!("source:json-api:{label}");
        let row = json!({
            "timestamp": ts,
            "equipment_id": "equip:json-api",
            "source": source,
            label: n
        });
        if let Err(err) = store::append_pivot_row(&row) {
            result["ingest_error"] = json!(err);
        } else {
            result["ingest"] = json!({
                "samples_appended": 1,
                "feather_source": "json_api",
                "historian_column": label
            });
        }
    }

    if payload.get("save_endpoint").and_then(|v| v.as_bool()) == Some(true) {
        let url = payload.get("url").and_then(|v| v.as_str()).unwrap_or("");
        let point_id = format!(
            "json-api:{}",
            label.replace(|c: char| !c.is_ascii_alphanumeric(), "-")
        );
        let endpoint = json!({
            "point_id": point_id,
            "label": label,
            "url": url,
            "method": payload.get("method").cloned().unwrap_or(json!("GET")),
            "json_path": payload.get("json_path").cloned().unwrap_or(json!("")),
            "auth_type": payload.get("auth_type").cloned().unwrap_or(json!("none")),
            "present_value": present,
            "enabled": false,
            "poll_interval_s": 0,
            "poll_label": "off",
            "host": host_from_url(url)
        });
        let mut endpoints = load_saved_endpoints();
        endpoints.retain(|e| e.get("point_id").and_then(|v| v.as_str()) != Some(point_id.as_str()));
        endpoints.push(endpoint);
        let _ = write_saved_endpoints(&endpoints);
        result["saved_endpoint_id"] = json!(point_id);
    }

    result["ok"] = json!(true);
    result
}

pub fn patch_endpoint_poll(payload: &Value) -> Value {
    let point_id = payload
        .get("point_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let enabled = payload
        .get("enabled")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let interval = payload
        .get("poll_interval_s")
        .and_then(|v| v.as_u64())
        .unwrap_or(300);
    let mut endpoints = load_saved_endpoints();
    let mut found = false;
    for ep in &mut endpoints {
        if ep.get("point_id").and_then(|v| v.as_str()) == Some(point_id) {
            ep["enabled"] = json!(enabled);
            ep["poll_interval_s"] = json!(if enabled { interval } else { 0 });
            ep["poll_label"] = json!(if enabled {
                format!("{interval}s")
            } else {
                "off".to_string()
            });
            found = true;
            break;
        }
    }
    if !found {
        return json!({"ok": false, "error": "endpoint not found", "point_id": point_id});
    }
    match write_saved_endpoints(&endpoints) {
        Ok(()) => {
            json!({"ok": true, "point_id": point_id, "enabled": enabled, "poll_interval_s": interval})
        }
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn delete_endpoint(point_id: &str) -> Value {
    let mut endpoints = load_saved_endpoints();
    let before = endpoints.len();
    endpoints.retain(|e| e.get("point_id").and_then(|v| v.as_str()) != Some(point_id));
    if endpoints.len() == before {
        return json!({"ok": false, "error": "endpoint not found"});
    }
    match write_saved_endpoints(&endpoints) {
        Ok(()) => json!({"ok": true, "deleted": point_id}),
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn poll_all_saved() -> Value {
    let endpoints = load_saved_endpoints();
    let enabled: Vec<&Value> = endpoints
        .iter()
        .filter(|e| e.get("enabled").and_then(|v| v.as_bool()) == Some(true))
        .collect();
    let mut polled = 0_u64;
    let mut samples = 0_u64;
    for ep in enabled {
        let req = json!({
            "url": ep.get("url"),
            "method": ep.get("method").and_then(|v| v.as_str()).unwrap_or("GET"),
            "json_path": ep.get("json_path").and_then(|v| v.as_str()).unwrap_or(""),
            "label": ep.get("label").and_then(|v| v.as_str()).unwrap_or("json_value"),
            "auth_type": ep.get("auth_type").and_then(|v| v.as_str()).unwrap_or("none"),
            "save_endpoint": false
        });
        let out = read_and_store(&req);
        polled += 1;
        if out.get("ingest").is_some() {
            samples += 1;
        }
    }
    json!({"ok": true, "polled": polled, "samples": samples, "at": Utc::now().to_rfc3339()})
}

pub fn saved_devices_for_tree() -> Vec<Value> {
    let mut by_host: std::collections::BTreeMap<String, Vec<Value>> =
        std::collections::BTreeMap::new();
    for ep in load_saved_endpoints() {
        let host = ep
            .get("host")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .unwrap_or_else(|| host_from_url(ep.get("url").and_then(|v| v.as_str()).unwrap_or("")));
        by_host.entry(host).or_default().push(ep);
    }
    by_host
        .into_iter()
        .map(|(host, points)| {
            let poll_count = points
                .iter()
                .filter(|p| p.get("enabled").and_then(|v| v.as_bool()) == Some(true))
                .count();
            json!({
                "device_key": host.clone(),
                "host": host,
                "point_count": points.len(),
                "poll_count": poll_count,
                "points": points
            })
        })
        .collect()
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

pub fn poll_url(url: &str) -> Value {
    let source_id = host_from_url(url);
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
        if !url.trim().is_empty() {
            return poll_url(url);
        }
    }
    json!({
        "ok": false,
        "configured": false,
        "error": "url required — add JSON API endpoints under Integrations"
    })
}

pub fn refresh_point(body: &Value) -> Value {
    let point_id = body.get("point_id").and_then(|v| v.as_str()).unwrap_or("");
    let sources = load_saved_endpoints();
    if point_id.is_empty() {
        return json!({
            "ok": false,
            "error": "point_id required",
            "configured": !sources.is_empty()
        });
    }
    for src in sources {
        let maps_to = src
            .get("maps_to")
            .or_else(|| src.get("point_id"))
            .and_then(|v| v.as_str());
        if maps_to != Some(point_id) {
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
    json!({"ok": false, "error": "point not found", "point_id": point_id, "configured": false})
}

fn protocol_enabled(env_key: &str) -> bool {
    env::var(env_key)
        .map(|v| v != "0" && v.to_lowercase() != "false")
        .unwrap_or(true)
}

/// Seed `workspace/data/json_api/endpoints.json` from `OPENFDD_JSON_API_URL` when empty.
pub fn seed_from_env_if_needed() {
    if !protocol_enabled("OPENFDD_JSON_API_ENABLED") {
        return;
    }
    if !load_saved_endpoints().is_empty() {
        return;
    }
    let url = match env::var("OPENFDD_JSON_API_URL") {
        Ok(v) if !v.trim().is_empty() => v,
        _ => return,
    };
    let label = env::var("OPENFDD_JSON_API_LABEL").unwrap_or_else(|_| "env-probe".into());
    let point_id = format!(
        "json-api:{}",
        label.replace(|c: char| !c.is_ascii_alphanumeric(), "-")
    );
    let endpoint = json!({
        "point_id": point_id,
        "label": label,
        "url": url,
        "method": "GET",
        "json_path": "",
        "auth_type": "none",
        "enabled": true,
        "poll_interval_s": 300,
        "poll_label": "5m",
        "host": host_from_url(&url),
        "source": "env:OPENFDD_JSON_API_URL"
    });
    let _ = write_saved_endpoints(&[endpoint]);
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
    let sources: Vec<Value> = load_saved_endpoints();
    let enabled_count = sources
        .iter()
        .filter(|s| s.get("enabled").and_then(|v| v.as_bool()) == Some(true))
        .count();
    json!({
        "ok": true,
        "enabled": !sources.is_empty(),
        "configured": !sources.is_empty(),
        "service": "json-api-poll",
        "status": if sources.is_empty() { "not_configured" } else { "ready" },
        "enabled_points": enabled_count,
        "samples": sources.len(),
        "at": Utc::now().to_rfc3339()
    })
    .to_string()
}

pub fn driver_tree_json() -> String {
    super::tree::json_api_driver_tree_json()
}
