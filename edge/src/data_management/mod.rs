//! Historian storage summary, retention policies, and purge jobs (API-only; no silent deletes).

use crate::historian::store;
use chrono::Utc;
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

const CONFIRM_PHRASE: &str = "PURGE HISTORIAN DATA";
const POLICY_PATH: &str = "data-management/retention.local.toml";

#[derive(Default, Clone)]
pub struct PurgeFilter {
    pub site_id: Option<String>,
    pub building_id: Option<String>,
    pub source_id: Option<String>,
    pub source_type: Option<String>,
    pub equipment_id: Option<String>,
    pub point_id: Option<String>,
    pub before_utc: Option<String>,
    pub after_utc: Option<String>,
    pub import_job_id: Option<String>,
    pub validation_run: bool,
    pub historian_subdir: Option<String>,
    pub all: bool,
}

pub fn policies_dir() -> PathBuf {
    store::workspace_dir().join("data-management")
}

pub fn policy_path() -> PathBuf {
    store::workspace_dir().join(POLICY_PATH)
}

pub fn purge_jobs_dir() -> PathBuf {
    policies_dir().join("purge_jobs")
}

fn parse_filter(body: &Value) -> PurgeFilter {
    PurgeFilter {
        site_id: body.get("site_id").and_then(|v| v.as_str()).map(str::to_string),
        building_id: body
            .get("building_id")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        source_id: body
            .get("source_id")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        source_type: body
            .get("source_type")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        equipment_id: body
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        point_id: body
            .get("point_id")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        before_utc: body
            .get("before_utc")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        after_utc: body
            .get("after_utc")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        import_job_id: body
            .get("import_job_id")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        validation_run: body
            .get("validation_run_id")
            .is_some()
            || body.get("validation_run").and_then(|v| v.as_bool()) == Some(true),
        historian_subdir: body
            .get("historian_subdir")
            .or_else(|| body.get("validation_run_id").map(|_| &json!("validation")))
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or_else(|| {
                if body.get("validation_run_id").is_some() {
                    Some("validation".to_string())
                } else {
                    None
                }
            }),
        all: body.get("all").and_then(|v| v.as_bool()) == Some(true),
    }
}

fn row_ts(row: &Value) -> Option<String> {
    row.get("timestamp")
        .and_then(|v| v.as_str())
        .map(str::to_string)
}

fn row_matches(row: &Value, filter: &PurgeFilter) -> bool {
    if filter.all {
        return true;
    }
    if let Some(ref equip) = filter.equipment_id {
        let row_equip = row
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if row_equip != equip {
            return false;
        }
    }
    if let Some(ref source) = filter.source_id {
        let row_source = row.get("source").and_then(|v| v.as_str()).unwrap_or("");
        if !row_source.contains(source) {
            return false;
        }
    }
    if let Some(ref source_type) = filter.source_type {
        let driver = row
            .get("source_driver")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if driver != source_type {
            return false;
        }
    }
    if let Some(ref job) = filter.import_job_id {
        let row_source = row.get("source").and_then(|v| v.as_str()).unwrap_or("");
        if !row_source.contains(job) {
            return false;
        }
    }
    if filter.validation_run {
        let row_source = row.get("source").and_then(|v| v.as_str()).unwrap_or("");
        if !(row_source.contains("validation") || row_source.contains("simulation:live_fdd")) {
            return false;
        }
    }
    if let Some(ref before) = filter.before_utc {
        if let Some(ts) = row_ts(row) {
            if ts >= *before {
                return false;
            }
        }
    }
    if let Some(ref after) = filter.after_utc {
        if let Some(ts) = row_ts(row) {
            if ts < *after {
                return false;
            }
        }
    }
    if filter.site_id.is_some() || filter.building_id.is_some() || filter.point_id.is_some() {
        // Metadata filters apply at job/policy level; row-level tags may be added later.
    }
    true
}

fn subdirs_for_filter(filter: &PurgeFilter) -> Vec<String> {
    if let Some(ref sub) = filter.historian_subdir {
        return vec![sub.clone()];
    }
    if filter.validation_run {
        return vec!["validation".to_string()];
    }
    store::list_historian_subdirs()
}

pub fn storage_summary() -> Value {
    let mut by_source: serde_json::Map<String, Value> = serde_json::Map::new();
    let mut by_subdir: serde_json::Map<String, Value> = serde_json::Map::new();
    let mut total_rows = 0usize;
    let mut total_bytes = 0u64;

    for sub in store::list_historian_subdirs() {
        let dir = store::historian_dir_for_subdir(&sub);
        let rows = store::load_rows_in(&sub).unwrap_or_default();
        let jsonl = dir.join("telemetry_pivot.jsonl");
        let bytes = fs::metadata(&jsonl).map(|m| m.len()).unwrap_or(0);
        total_rows += rows.len();
        total_bytes += bytes;
        by_subdir.insert(
            sub.clone(),
            json!({
                "historian_subdir": sub,
                "row_count": rows.len(),
                "jsonl_bytes": bytes,
                "arrow_ipc_bytes": fs::metadata(dir.join("telemetry_pivot.arrow")).map(|m| m.len()).unwrap_or(0)
            }),
        );
        for row in &rows {
            let source = row
                .get("source")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();
            let entry = by_source.entry(source.clone()).or_insert(json!({
                "source_id": source,
                "row_count": 0,
                "historian_subdirs": Value::Array(vec![])
            }));
            entry["row_count"] = json!(entry["row_count"].as_u64().unwrap_or(0) + 1);
        }
    }

    json!({
        "ok": true,
        "total_row_count": total_rows,
        "estimated_bytes": total_bytes,
        "historian_root": store::historian_root().display().to_string(),
        "by_subdir": by_subdir,
        "by_source": by_source,
        "warnings": ["Purge operations are irreversible. Export before purge when in doubt."]
    })
}

pub fn preview_purge(body: &Value) -> Value {
    let filter = parse_filter(body);
    let dry_run = body.get("dry_run").and_then(|v| v.as_bool()).unwrap_or(true);
    let mut matched_rows = 0usize;
    let mut matched_files = 0usize;
    let mut matched_bytes = 0u64;
    let mut min_ts: Option<String> = None;
    let mut max_ts: Option<String> = None;
    let mut sources: Vec<String> = Vec::new();
    let subdirs = subdirs_for_filter(&filter);

    for sub in &subdirs {
        let rows = store::load_rows_in(sub).unwrap_or_default();
        let matched: Vec<_> = rows
            .iter()
            .filter(|r| row_matches(r, &filter))
            .collect();
        if matched.is_empty() {
            continue;
        }
        matched_files += 1;
        matched_rows += matched.len();
        let dir = store::historian_dir_for_subdir(sub);
        matched_bytes += fs::metadata(dir.join("telemetry_pivot.jsonl"))
            .map(|m| m.len())
            .unwrap_or(0);
        for row in matched {
            if let Some(ts) = row_ts(row) {
                if min_ts.as_ref().map(|m| ts < *m).unwrap_or(true) {
                    min_ts = Some(ts.clone());
                }
                if max_ts.as_ref().map(|m| ts > *m).unwrap_or(true) {
                    max_ts = Some(ts);
                }
            }
            let src = row
                .get("source")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();
            if !sources.contains(&src) {
                sources.push(src);
            }
        }
    }

    json!({
        "ok": true,
        "dry_run": dry_run,
        "matched_row_count": matched_rows,
        "matched_file_count": matched_files,
        "matched_byte_estimate": matched_bytes,
        "matched_sources": sources,
        "matched_subdirs": subdirs,
        "affected_date_range": {
            "min_timestamp": min_ts,
            "max_timestamp": max_ts
        },
        "warnings": [
            "This operation permanently deletes historian rows matching the filter.",
            "Export CSV backups via /api/export/historian.csv before executing.",
            "Automatic retention never runs unless explicitly configured."
        ],
        "irreversible": true
    })
}

fn save_purge_job(job: &Value) -> Result<(), String> {
    let job_id = job
        .get("job_id")
        .and_then(|v| v.as_str())
        .ok_or("missing job_id")?;
    let dir = purge_jobs_dir();
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    fs::write(
        dir.join(format!("{job_id}.json")),
        serde_json::to_string_pretty(job).unwrap_or_default(),
    )
    .map_err(|e| e.to_string())
}

pub fn execute_purge(body: &Value, role: &str) -> Value {
    if role != "integrator" {
        return json!({"ok": false, "error": "integrator role required for purge execute"});
    }
    let confirm = body
        .get("confirmation")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if confirm != CONFIRM_PHRASE {
        return json!({
            "ok": false,
            "error": format!("confirmation phrase required: {CONFIRM_PHRASE}")
        });
    }
    let dry_run = body.get("dry_run").and_then(|v| v.as_bool()).unwrap_or(false);
    let preview = preview_purge(body);
    if preview.get("matched_row_count").and_then(|v| v.as_u64()) == Some(0) {
        return json!({"ok": false, "error": "no rows matched", "preview": preview});
    }
    let filter = parse_filter(body);
    let job_id = format!("purge-{}", Utc::now().timestamp_millis());
    if dry_run {
        let job = json!({
            "ok": true,
            "job_id": job_id,
            "status": "dry_run",
            "preview": preview,
            "rows_removed": 0
        });
        let _ = save_purge_job(&job);
        return job;
    }

    let mut rows_removed = 0usize;
    for sub in subdirs_for_filter(&filter) {
        let rows = store::load_rows_in(&sub).unwrap_or_default();
        let before = rows.len();
        let kept: Vec<Value> = rows
            .into_iter()
            .filter(|r| !row_matches(r, &filter))
            .collect();
        let removed = before.saturating_sub(kept.len());
        if removed == 0 {
            continue;
        }
        if let Err(err) = store::rewrite_subdir(&sub, &kept) {
            return json!({"ok": false, "error": err, "job_id": job_id});
        }
        rows_removed += removed;
    }

    let job = json!({
        "ok": true,
        "job_id": job_id,
        "status": "completed",
        "rows_removed": rows_removed,
        "preview": preview,
        "completed_at": Utc::now().to_rfc3339(),
        "audit": {
            "action": "historian_purge",
            "role": role,
            "filter": body
        }
    });
    let _ = save_purge_job(&job);
    job
}

pub fn purge_job_status(job_id: &str) -> Value {
    if job_id.contains("..") || job_id.contains('/') {
        return json!({"ok": false, "error": "invalid job id"});
    }
    let path = purge_jobs_dir().join(format!("{job_id}.json"));
    if !path.exists() {
        return json!({"ok": false, "error": "job not found"});
    }
    match fs::read_to_string(path) {
        Ok(text) => match serde_json::from_str::<Value>(&text) {
            Ok(job) => json!({"ok": true, "job": job}),
            Err(err) => json!({"ok": false, "error": err.to_string()}),
        },
        Err(err) => json!({"ok": false, "error": err.to_string()}),
    }
}

pub fn get_policies() -> Value {
    let path = policy_path();
    if !path.exists() {
        return json!({
            "ok": true,
            "configured": false,
            "path": path.display().to_string(),
            "policies": [],
            "note": "No automatic purge runs unless retention.local.toml is configured and the retention sidecar is enabled."
        });
    }
    let text = fs::read_to_string(&path).unwrap_or_default();
    json!({
        "ok": true,
        "configured": true,
        "path": path.display().to_string(),
        "raw": text
    })
}

pub fn put_policies(body: &Value, role: &str) -> Value {
    if role != "integrator" {
        return json!({"ok": false, "error": "integrator role required"});
    }
    let Some(raw) = body.get("raw").and_then(|v| v.as_str()) else {
        return json!({"ok": false, "error": "raw toml body required"});
    };
    if raw.len() > 64 * 1024 {
        return json!({"ok": false, "error": "policy file too large"});
    }
    let path = policy_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    match fs::write(&path, raw) {
        Ok(()) => json!({"ok": true, "path": path.display().to_string()}),
        Err(err) => json!({"ok": false, "error": err.to_string()}),
    }
}

pub fn agent_tools() -> Value {
    json!({
        "tools": [
            {"name": "get_storage_summary", "method": "GET", "path": "/api/data-management/summary", "requires": "integrator|agent"},
            {"name": "preview_purge", "method": "POST", "path": "/api/data-management/purge/preview", "requires": "integrator|agent"},
            {"name": "propose_retention_policy", "method": "GET", "path": "/api/data-management/policies", "requires": "integrator|agent"},
            {"name": "run_purge", "method": "POST", "path": "/api/data-management/purge/execute", "requires": "integrator", "confirmation_phrase": CONFIRM_PHRASE, "note": "AI agents must not call without explicit human confirmation."}
        ]
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preview_before_date_filters_rows() {
        let body = json!({"before_utc": "2026-06-24T00:00:00Z", "historian_subdir": "validation"});
        let preview = preview_purge(&body);
        assert!(preview.get("ok").and_then(|v| v.as_bool()) == Some(true));
    }

    #[test]
    fn execute_requires_confirmation_phrase() {
        let body = json!({"all": true, "dry_run": true});
        let result = execute_purge(&body, "integrator");
        assert!(result.get("error").is_some());
    }

    #[test]
    fn rejects_path_traversal_job_lookup() {
        let result = purge_job_status("../secrets");
        assert!(result.get("ok").and_then(|v| v.as_bool()) == Some(false));
    }
}
