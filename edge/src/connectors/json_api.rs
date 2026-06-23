//! Multi-source JSON API connector driver.

use crate::connectors::historian;
use crate::connectors::json_path;
use crate::connectors::registry::{
    load_source_config, update_source_health, update_source_poll_time,
};
use crate::connectors::secrets::resolve_secret;
use crate::connectors::types::{JsonApiConfig, NormalizedRow, SourceHealth};
use chrono::{Local, Utc};
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

pub fn parse_config(raw: &Value) -> Result<JsonApiConfig, String> {
    serde_json::from_value(raw.clone()).map_err(|e| e.to_string())
}

pub fn test_connection(source_id: &str) -> Value {
    match load_source_config(source_id) {
        Ok(cfg) => match parse_config(&cfg) {
            Ok(parsed) => {
                let demo = use_demo_mode(&parsed);
                if demo {
                    json!({
                        "ok": true,
                        "source_id": source_id,
                        "mode": "demo",
                        "message": "Demo fixture mode (no live HTTP or secret required)"
                    })
                } else {
                    match http_get(
                        &parsed,
                        &parsed
                            .endpoints
                            .first()
                            .map(|e| e.path.clone())
                            .unwrap_or_else(|| "/".into()),
                    ) {
                        Ok(resp) => {
                            json!({"ok": true, "source_id": source_id, "http_status": resp.status, "mode": "live"})
                        }
                        Err(err) => json!({"ok": false, "source_id": source_id, "error": err}),
                    }
                }
            }
            Err(err) => json!({"ok": false, "error": err}),
        },
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn discover_catalog(source_id: &str) -> Value {
    let Ok(cfg_raw) = load_source_config(source_id) else {
        return json!({"ok": false, "error": "config load failed"});
    };
    let Ok(cfg) = parse_config(&cfg_raw) else {
        return json!({"ok": false, "error": "invalid config"});
    };
    let mut points = Vec::new();
    for ep in &cfg.endpoints {
        for p in &ep.points {
            points.push(json!({
                "point_id": p.point_id,
                "point_name": p.point_name,
                "endpoint_id": ep.endpoint_id,
                "value_path": p.value_path,
                "units": p.units.clone().unwrap_or_default(),
                "mapped": false
            }));
        }
    }
    json!({"ok": true, "source_id": source_id, "points": points, "point_count": points.len()})
}

pub fn poll_once(source_id: &str, run_id: &str) -> Value {
    let Ok(cfg_raw) = load_source_config(source_id) else {
        return json!({"ok": false, "error": "config load failed"});
    };
    let Ok(cfg) = parse_config(&cfg_raw) else {
        return json!({"ok": false, "error": "invalid config"});
    };
    let payload = match fetch_payload(&cfg, source_id) {
        Ok(p) => p,
        Err(err) => {
            let _ = update_source_health(
                source_id,
                SourceHealth {
                    status: "offline".into(),
                    message: err.clone(),
                    last_error: Some(err.clone()),
                },
                None,
            );
            return json!({"ok": false, "source_id": source_id, "error": err});
        }
    };
    let mut normalized = Vec::new();
    for ep in &cfg.endpoints {
        let maps: Vec<_> = ep
            .points
            .iter()
            .map(|p| {
                (
                    p.point_id.clone(),
                    p.point_name.clone(),
                    p.value_path.clone(),
                    p.units_path.clone(),
                    p.units.clone(),
                )
            })
            .collect();
        let data_root = ep
            .path
            .trim_start_matches('/')
            .split('/')
            .next()
            .unwrap_or("");
        let extracted =
            json_path::extract_points_from_payload(&payload, &ep.shape, data_root, &maps);
        for (point_id, point_name, vpath, val, units, quality) in extracted {
            if let Some(value) = val {
                normalized.push(build_row(
                    &cfg,
                    source_id,
                    run_id,
                    &point_id,
                    &point_name,
                    value,
                    &units,
                    &quality,
                    &format!("{}{}", cfg.base_url, ep.path),
                    &vpath,
                ));
            }
        }
    }
    let (written, skipped) = historian::append_rows(&normalized).unwrap_or((0, 0));
    let count = historian::row_count_for_source(source_id);
    let health = if normalized.is_empty() {
        SourceHealth {
            status: "degraded".into(),
            message: "poll succeeded but no points extracted".into(),
            last_error: None,
        }
    } else {
        SourceHealth {
            status: "online".into(),
            message: format!("{written} rows written, {skipped} deduped"),
            last_error: None,
        }
    };
    let _ = update_source_health(source_id, health, Some(count));
    let _ = update_source_poll_time(source_id);
    json!({
        "ok": true,
        "source_id": source_id,
        "rows_written": written,
        "rows_deduped": skipped,
        "points_extracted": normalized.len(),
        "historian_rows": count,
        "run_id": run_id
    })
}

pub fn sample_payload(source_id: &str) -> Value {
    let Ok(cfg_raw) = load_source_config(source_id) else {
        return json!({"ok": false, "error": "config load failed"});
    };
    let Ok(cfg) = parse_config(&cfg_raw) else {
        return json!({"ok": false, "error": "invalid config"});
    };
    match fetch_payload(&cfg, source_id) {
        Ok(payload) => json!({"ok": true, "source_id": source_id, "sample": payload}),
        Err(err) => json!({"ok": false, "error": err}),
    }
}

fn fetch_payload(cfg: &JsonApiConfig, source_id: &str) -> Result<Value, String> {
    if use_demo_mode(cfg) {
        return load_demo_fixture(source_id);
    }
    let path = cfg
        .endpoints
        .first()
        .map(|e| e.path.clone())
        .unwrap_or_else(|| "/".into());
    let resp = http_get(cfg, &path)?;
    serde_json::from_str(&resp.body).map_err(|e| format!("invalid JSON: {e}"))
}

fn use_demo_mode(cfg: &JsonApiConfig) -> bool {
    if env::var("OPENFDD_CONNECTOR_DEMO_MODE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
    {
        return true;
    }
    if cfg.base_url.contains("example.invalid") || cfg.base_url.contains("demo.local") {
        return true;
    }
    if cfg.auth.secret_ref.is_some()
        && resolve_secret(cfg.auth.secret_ref.as_deref().unwrap_or("")).is_none()
    {
        return true;
    }
    false
}

fn load_demo_fixture(source_id: &str) -> Result<Value, String> {
    let path = match source_id {
        "openweathermap_oat" => repo_path("examples/connectors/demo_weather_response.json"),
        _ => repo_path("examples/connectors/demo_building_points.json"),
    };
    let text = fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

fn repo_path(rel: &str) -> PathBuf {
    for root in candidate_repo_roots() {
        let path = root.join(rel);
        if path.exists() {
            return path;
        }
    }
    PathBuf::from(rel)
}

fn candidate_repo_roots() -> Vec<PathBuf> {
    crate::connectors::registry::repo_roots()
}

struct HttpResponse {
    status: u16,
    body: String,
}

fn http_get(cfg: &JsonApiConfig, path: &str) -> Result<HttpResponse, String> {
    let url = join_url(&cfg.base_url, path);
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(cfg.timeout_s.max(1)))
        .build();
    let mut req = agent.get(&url);
    if let Some(secret_ref) = &cfg.auth.secret_ref {
        if let Some(token) = resolve_secret(secret_ref) {
            req = req.set("Authorization", &format!("Bearer {token}"));
        }
    }
    match req.call() {
        Ok(resp) => {
            let status = resp.status();
            let body = resp.into_string().map_err(|e| e.to_string())?;
            Ok(HttpResponse { status, body })
        }
        Err(ureq::Error::Status(code, resp)) => {
            let body = resp.into_string().unwrap_or_default();
            Err(format!("HTTP {code}: {body}"))
        }
        Err(ureq::Error::Transport(err)) => Err(err.to_string()),
    }
}

fn join_url(base: &str, path: &str) -> String {
    if path.starts_with("http") {
        return path.to_string();
    }
    let base = base.trim_end_matches('/');
    let path = if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    format!("{base}{path}")
}

fn build_row(
    cfg: &JsonApiConfig,
    source_id: &str,
    run_id: &str,
    point_id: &str,
    point_name: &str,
    value: f64,
    units: &str,
    quality: &str,
    source_path: &str,
    raw_ref: &str,
) -> NormalizedRow {
    let now = Utc::now();
    let tz = env::var("TZ").unwrap_or_else(|_| "UTC".to_string());
    NormalizedRow {
        timestamp_utc: now.to_rfc3339(),
        timestamp_local: now
            .with_timezone(&Local)
            .format("%Y-%m-%d %H:%M:%S")
            .to_string(),
        timezone: tz,
        site_id: cfg.site_id.clone(),
        building_id: cfg.building_id.clone(),
        equipment_id: "equip:weather".into(),
        source_id: source_id.into(),
        source_type: "json_api".into(),
        source_protocol: "json_api".into(),
        device_id: format!("json-api:{source_id}"),
        point_id: point_id.into(),
        point_name: point_name.into(),
        value: Some(value),
        value_text: value.to_string(),
        units: units.to_string(),
        quality: quality.into(),
        source_path: source_path.into(),
        raw_ref: raw_ref.into(),
        ingested_at: now.to_rfc3339(),
        run_id: run_id.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_example_json_api_config_shape() {
        let raw = json!({
            "source_id": "demo",
            "display_name": "Demo",
            "base_url": "https://demo.local",
            "endpoints": [{
                "endpoint_id": "points",
                "path": "/points",
                "shape": "array",
                "points": [{"point_id":"oat","point_name":"OAT","value_path":"value","units":"degF"}]
            }]
        });
        assert!(parse_config(&raw).is_ok());
    }
}
