//! Generic backfill job system for connector historical ingest.

use crate::connectors::historian;
use crate::connectors::json_api;
use crate::connectors::postgres;
use crate::connectors::registry::{read_registry, write_registry};
use crate::connectors::simulation;
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Value};
use std::path::PathBuf;
use uuid::Uuid;

pub fn start_backfill(
    source_id: &str,
    source_type: &str,
    body: &Value,
    requested_by: &str,
) -> Value {
    let start_ts = body.get("start_ts").and_then(|v| v.as_str()).unwrap_or("");
    let end_ts = body.get("end_ts").and_then(|v| v.as_str()).unwrap_or("");
    if start_ts.is_empty() || end_ts.is_empty() {
        return json!({"ok": false, "error": "start_ts and end_ts required"});
    }
    let start = match DateTime::parse_from_rfc3339(start_ts) {
        Ok(v) => v.with_timezone(&Utc),
        Err(_) => return json!({"ok": false, "error": "invalid start_ts"}),
    };
    let end = match DateTime::parse_from_rfc3339(end_ts) {
        Ok(v) => v.with_timezone(&Utc),
        Err(_) => return json!({"ok": false, "error": "invalid end_ts"}),
    };
    if end <= start {
        return json!({"ok": false, "error": "end_ts must be after start_ts"});
    }
    let chunk_hours = body
        .get("chunk_hours")
        .and_then(|v| v.as_u64())
        .unwrap_or(6)
        .max(1);
    let job_id = format!("backfill-{}", Uuid::new_v4());
    let mut job = json!({
        "job_id": job_id,
        "source_id": source_id,
        "source_type": source_type,
        "site_id": body.get("site_id").cloned().unwrap_or(json!("site:demo")),
        "building_id": body.get("building_id").cloned().unwrap_or(json!("building:main")),
        "requested_by": requested_by,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "chunk_hours": chunk_hours,
        "status": "running",
        "rows_read": 0,
        "rows_written": 0,
        "errors": [],
        "started_at": Utc::now().to_rfc3339(),
        "completed_at": null,
        "output_feather_path": historian::arrow_path().display().to_string()
    });
    let (rows_read, rows_written, errors) =
        execute_backfill(source_id, source_type, start, end, chunk_hours, &job_id);
    job["rows_read"] = json!(rows_read);
    job["rows_written"] = json!(rows_written);
    job["errors"] = json!(errors);
    job["status"] = if errors.is_empty() {
        json!("complete")
    } else {
        json!("complete_with_errors")
    };
    job["completed_at"] = json!(Utc::now().to_rfc3339());
    persist_job(&job);
    update_source_backfill_time(source_id);
    job
}

pub fn get_job(source_id: &str, job_id: &str) -> Value {
    let reg = read_registry();
    let jobs = reg
        .get("backfill_jobs")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    if let Some(job) = jobs.iter().find(|j| {
        j.get("job_id").and_then(|v| v.as_str()) == Some(job_id)
            && j.get("source_id").and_then(|v| v.as_str()) == Some(source_id)
    }) {
        return json!({"ok": true, "job": job});
    }
    json!({"ok": false, "error": "job not found"})
}

pub fn list_jobs(source_id: &str) -> Value {
    let reg = read_registry();
    let jobs: Vec<Value> = reg
        .get("backfill_jobs")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .filter(|j| j.get("source_id").and_then(|v| v.as_str()) == Some(source_id))
        .collect();
    json!({"ok": true, "jobs": jobs})
}

fn execute_backfill(
    source_id: &str,
    source_type: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    chunk_hours: u64,
    run_id: &str,
) -> (u64, u64, Vec<String>) {
    let mut cursor = start;
    let chunk = Duration::hours(chunk_hours as i64);
    let mut rows_read = 0u64;
    let mut rows_written = 0u64;
    let mut errors = Vec::new();
    while cursor < end {
        let chunk_end = (cursor + chunk).min(end);
        let chunk_run = format!("{run_id}-{}", cursor.timestamp());
        let result = match source_type {
            "json_api" => json_api::poll_once(source_id, &chunk_run),
            "postgres_readonly" => postgres::poll_demo_values(source_id, &chunk_run),
            "simulation" => simulation::poll_once(source_id, &chunk_run),
            _ => json!({"ok": false, "error": format!("backfill unsupported for {source_type}")}),
        };
        rows_read += result
            .get("points_extracted")
            .and_then(|v| v.as_u64())
            .unwrap_or(1);
        rows_written += result
            .get("rows_written")
            .and_then(|v| v.as_u64())
            .unwrap_or(0);
        if result.get("ok").and_then(|v| v.as_bool()) != Some(true) {
            if let Some(err) = result.get("error").and_then(|v| v.as_str()) {
                errors.push(format!(
                    "{}..{}: {err}",
                    cursor.to_rfc3339(),
                    chunk_end.to_rfc3339()
                ));
            }
        }
        cursor = chunk_end;
    }
    (rows_read, rows_written, errors)
}

fn persist_job(job: &Value) {
    let mut reg = read_registry();
    let jobs = reg
        .as_object_mut()
        .and_then(|o| o.get_mut("backfill_jobs"))
        .and_then(|v| v.as_array_mut());
    if let Some(arr) = jobs {
        arr.push(job.clone());
    }
    let _ = write_registry(&reg);
}

fn update_source_backfill_time(source_id: &str) {
    let mut reg = read_registry();
    if let Some(sources) = reg.get_mut("sources").and_then(|v| v.as_array_mut()) {
        for s in sources.iter_mut() {
            if s.get("source_id").and_then(|v| v.as_str()) == Some(source_id) {
                s["last_backfill_at"] = json!(Utc::now().to_rfc3339());
                break;
            }
        }
    }
    let _ = write_registry(&reg);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chunks_time_range_in_backfill() {
        let tmp = std::env::temp_dir().join(format!("ofdd-backfill-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", &tmp);
        std::env::set_var(
            "OPENFDD_REPO_ROOT",
            PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .display()
                .to_string(),
        );
        std::env::set_var("OPENFDD_CONNECTOR_DEMO_MODE", "1");
        let start = DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let end = DateTime::parse_from_rfc3339("2024-01-01T18:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let (read, written, errs) = execute_backfill(
            "demo_building_json_feed",
            "json_api",
            start,
            end,
            6,
            "test-job",
        );
        assert!(read >= 1);
        assert!(written >= 0);
        assert!(errs.is_empty());
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
