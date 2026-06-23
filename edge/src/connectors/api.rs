//! HTTP API handlers for the generic source connector framework.

use crate::connectors::backfill;
use crate::connectors::historian;
use crate::connectors::json_api;
use crate::connectors::postgres;
use crate::connectors::registry::{get_source, list_sources, load_source_config, upsert_source};
use crate::connectors::simulation;
use crate::connectors::types::redact_config_for_api;
use chrono::Local;
use serde_json::{json, Value};
use uuid::Uuid;

const READ_ROLES: &[&str] = &["operator", "integrator", "agent"];
const MUTATE_ROLES: &[&str] = &["integrator", "agent"];

pub fn read_roles() -> &'static [&'static str] {
    READ_ROLES
}

pub fn mutate_roles() -> &'static [&'static str] {
    MUTATE_ROLES
}

pub fn list_sources_api() -> Value {
    list_sources()
}

pub fn create_source(body: &Value) -> Value {
    match upsert_source(body.clone()) {
        Ok(v) => v,
        Err(err) => json!({"ok": false, "error": err}),
    }
}

pub fn get_source_api(source_id: &str) -> Value {
    let Some(source) = get_source(source_id) else {
        return json!({"ok": false, "error": "source not found"});
    };
    let config = load_source_config(source_id)
        .map(|c| redact_config_for_api(&c))
        .unwrap_or(json!({}));
    json!({"ok": true, "source": source, "config": config})
}

pub fn test_source(source_id: &str) -> Value {
    let Some(source) = get_source(source_id) else {
        return json!({"ok": false, "error": "source not found"});
    };
    let source_type = source
        .get("source_type")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    match source_type {
        "json_api" => json_api::test_connection(source_id),
        "postgres_readonly" => postgres::test_connection(source_id),
        "simulation" => simulation::health(source_id),
        other => json!({"ok": false, "error": format!("test not implemented for {other}")}),
    }
}

pub fn discover_source(source_id: &str) -> Value {
    let Some(source) = get_source(source_id) else {
        return json!({"ok": false, "error": "source not found"});
    };
    let source_type = source
        .get("source_type")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    match source_type {
        "json_api" => json_api::discover_catalog(source_id),
        "postgres_readonly" => postgres::discover_catalog(source_id),
        "simulation" => {
            json!({"ok": true, "points": [{"point_id":"point:sim_temp","point_name":"Simulated Temp"}]})
        }
        other => json!({"ok": false, "error": format!("discover not implemented for {other}")}),
    }
}

pub fn catalog(source_id: &str) -> Value {
    discover_source(source_id)
}

pub fn poll_once(source_id: &str) -> Value {
    let Some(source) = get_source(source_id) else {
        return json!({"ok": false, "error": "source not found"});
    };
    let run_id = format!("poll-{}", Uuid::new_v4());
    let source_type = source
        .get("source_type")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    match source_type {
        "json_api" => json_api::poll_once(source_id, &run_id),
        "postgres_readonly" => postgres::poll_demo_values(source_id, &run_id),
        "simulation" => simulation::poll_once(source_id, &run_id),
        other => json!({"ok": false, "error": format!("poll not implemented for {other}")}),
    }
}

pub fn start_backfill(source_id: &str, body: &Value, requested_by: &str) -> Value {
    let Some(source) = get_source(source_id) else {
        return json!({"ok": false, "error": "source not found"});
    };
    let source_type = source
        .get("source_type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let mut payload = body.clone();
    if payload.get("start_ts").is_none() {
        payload["start_ts"] =
            json!((chrono::Utc::now() - chrono::Duration::hours(24)).to_rfc3339());
    }
    if payload.get("end_ts").is_none() {
        payload["end_ts"] = json!(chrono::Utc::now().to_rfc3339());
    }
    backfill::start_backfill(source_id, &source_type, &payload, requested_by)
}

pub fn get_backfill_job(source_id: &str, job_id: &str) -> Value {
    backfill::get_job(source_id, job_id)
}

pub fn source_health(source_id: &str) -> Value {
    let Some(source) = get_source(source_id) else {
        return json!({"ok": false, "error": "source not found"});
    };
    let health = source
        .get("health")
        .cloned()
        .unwrap_or(json!({"status":"unknown"}));
    json!({
        "ok": true,
        "source_id": source_id,
        "health": health,
        "last_poll_at": source.get("last_poll_at"),
        "last_backfill_at": source.get("last_backfill_at"),
        "historian_rows": historian::row_count_for_source(source_id)
    })
}

pub fn sample(source_id: &str) -> Value {
    let Some(source) = get_source(source_id) else {
        return json!({"ok": false, "error": "source not found"});
    };
    let source_type = source
        .get("source_type")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    match source_type {
        "json_api" => json_api::sample_payload(source_id),
        "postgres_readonly" => postgres::preview_query(source_id, "current", &json!({})),
        "simulation" => json!({"ok": true, "sample": {"point_id":"point:sim_temp","value":70.0}}),
        other => json!({"ok": false, "error": format!("sample not implemented for {other}")}),
    }
}

pub fn historian_status() -> Value {
    historian::status_json()
}

pub fn export_historian_csv() -> String {
    let header = "timestamp_utc,timestamp_local,timezone,site_id,building_id,equipment_id,source_id,source_type,source_protocol,device_id,point_id,point_name,value,units,quality,source_path,raw_ref,ingested_at,run_id";
    let mut out = String::from(header);
    out.push('\n');
    for row in historian::load_rows().unwrap_or_default() {
        out.push_str(&csv_row(&[
            strv(&row, "timestamp_utc"),
            strv(&row, "timestamp_local"),
            strv(&row, "timezone"),
            strv(&row, "site_id"),
            strv(&row, "building_id"),
            strv(&row, "equipment_id"),
            strv(&row, "source_id"),
            strv(&row, "source_type"),
            strv(&row, "source_protocol"),
            strv(&row, "device_id"),
            strv(&row, "point_id"),
            strv(&row, "point_name"),
            row.get("value").map(|v| v.to_string()).unwrap_or_default(),
            strv(&row, "units"),
            strv(&row, "quality"),
            strv(&row, "source_path"),
            strv(&row, "raw_ref"),
            strv(&row, "ingested_at"),
            strv(&row, "run_id"),
        ]));
        out.push('\n');
    }
    out
}

pub fn export_filename(prefix: &str) -> String {
    let now = Local::now();
    format!("openfdd_{}_{}.csv", prefix, now.format("%Y%m%d_%H%M"))
}

fn strv(row: &Value, key: &str) -> String {
    row.get(key)
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string()
}

fn csv_row(fields: &[String]) -> String {
    fields
        .iter()
        .map(|f| format!("\"{}\"", f.replace('"', "\"\"")))
        .collect::<Vec<_>>()
        .join(",")
}
