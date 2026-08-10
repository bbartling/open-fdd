//! Persistent engineering Jobs under ``$OPENFDD_WORKSPACE/jobs/<job_id>/``.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

const SCHEMA_VERSION: u32 = 1;

fn is_uuid_suffix(s: &str) -> bool {
    // 8-4-4-4-12 hex with dashes
    let parts: Vec<&str> = s.split('-').collect();
    if parts.len() != 5 {
        return false;
    }
    let lens = [8usize, 4, 4, 4, 12];
    parts
        .iter()
        .zip(lens)
        .all(|(p, n)| p.len() == n && p.chars().all(|c| c.is_ascii_hexdigit()))
}

fn is_job_id(job_id: &str) -> bool {
    job_id
        .strip_prefix("job-")
        .map(is_uuid_suffix)
        .unwrap_or(false)
}

fn is_run_id(run_id: &str) -> bool {
    run_id
        .strip_prefix("run-")
        .map(is_uuid_suffix)
        .unwrap_or(false)
}

pub fn workspace_root() -> PathBuf {
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE") {
        return PathBuf::from(ws);
    }
    if let Ok(ws) = std::env::var("OPENFDD_WORKSPACE_DIR") {
        return PathBuf::from(ws);
    }
    PathBuf::from("workspace")
}

/// Serializes unit tests that mutate ``OPENFDD_WORKSPACE`` (jobs + eplus_runner).
#[cfg(test)]
pub(crate) static WORKSPACE_ENV_TEST_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

pub fn jobs_root() -> PathBuf {
    let root = workspace_root().join("jobs");
    let _ = fs::create_dir_all(&root);
    root
}

fn utc_now() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

fn new_meta_revision() -> String {
    Uuid::new_v4().simple().to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct JobRevisions {
    pub dataset: Option<String>,
    pub mapping: Option<String>,
    pub config: Option<String>,
    pub engine: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobMeta {
    pub schema_version: u32,
    pub job_id: String,
    pub job_name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default = "default_active")]
    pub status: String,
    #[serde(default)]
    pub archived: bool,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub updated_at: String,
    #[serde(default)]
    pub created_by: Option<String>,
    #[serde(default)]
    pub site_id: Option<String>,
    #[serde(default)]
    pub site_name: Option<String>,
    #[serde(default)]
    pub building_name: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub meta_revision: String,
    #[serde(default)]
    pub latest_run_id: Option<String>,
    #[serde(default)]
    pub latest_findings_revision: Option<String>,
    #[serde(default)]
    pub mapping_path: Option<String>,
    #[serde(default)]
    pub revisions: JobRevisions,
}

fn default_active() -> String {
    "active".into()
}

#[derive(Debug)]
pub enum JobError {
    NotFound(String),
    Invalid(String),
    Conflict { expected: String, current: String },
    Io(String),
}

impl JobError {
    pub fn status_code(&self) -> axum::http::StatusCode {
        match self {
            Self::NotFound(_) => axum::http::StatusCode::NOT_FOUND,
            Self::Invalid(_) => axum::http::StatusCode::BAD_REQUEST,
            Self::Conflict { .. } => axum::http::StatusCode::CONFLICT,
            Self::Io(_) => axum::http::StatusCode::INTERNAL_SERVER_ERROR,
        }
    }

    pub fn to_json(&self) -> Value {
        match self {
            Self::Conflict { expected, current } => json!({
                "ok": false,
                "error": "revision_conflict",
                "expected_revision": expected,
                "current_revision": current,
            }),
            Self::NotFound(m) => json!({"ok": false, "error": m}),
            Self::Invalid(m) => json!({"ok": false, "error": m}),
            Self::Io(m) => json!({"ok": false, "error": m}),
        }
    }
}

pub fn validate_job_id(job_id: &str) -> Result<(), JobError> {
    if !is_job_id(job_id) {
        return Err(JobError::Invalid(format!("invalid job_id: {job_id}")));
    }
    if job_id.contains("..") || job_id.contains('/') || job_id.contains('\\') {
        return Err(JobError::Invalid("path traversal rejected".into()));
    }
    Ok(())
}

pub fn job_dir(job_id: &str) -> Result<PathBuf, JobError> {
    validate_job_id(job_id)?;
    let root = jobs_root().canonicalize().unwrap_or_else(|_| jobs_root());
    let path = root.join(job_id);
    let resolved = path.canonicalize().unwrap_or(path.clone());
    if !resolved.starts_with(&root) && resolved != root {
        return Err(JobError::Invalid("path traversal rejected".into()));
    }
    Ok(path)
}

fn ensure_layout(path: &Path) -> Result<(), JobError> {
    fs::create_dir_all(path).map_err(|e| JobError::Io(e.to_string()))?;
    for name in [
        "mapping",
        "configs",
        "datasets",
        "runs",
        "findings",
        "reports",
        "wattlab",
        "artifacts",
    ] {
        fs::create_dir_all(path.join(name)).map_err(|e| JobError::Io(e.to_string()))?;
    }
    fs::create_dir_all(path.join("wattlab/handoffs")).map_err(|e| JobError::Io(e.to_string()))?;
    fs::create_dir_all(path.join("wattlab/runs")).map_err(|e| JobError::Io(e.to_string()))?;
    Ok(())
}

pub(crate) fn atomic_write_json(path: &Path, payload: &Value) -> Result<(), JobError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| JobError::Io(e.to_string()))?;
    }
    let data = serde_json::to_vec_pretty(payload).map_err(|e| JobError::Io(e.to_string()))?;
    let tmp = path.with_extension("tmp");
    {
        let mut f = fs::File::create(&tmp).map_err(|e| JobError::Io(e.to_string()))?;
        f.write_all(&data)
            .map_err(|e| JobError::Io(e.to_string()))?;
        f.write_all(b"\n")
            .map_err(|e| JobError::Io(e.to_string()))?;
        f.sync_all().map_err(|e| JobError::Io(e.to_string()))?;
    }
    fs::rename(&tmp, path).map_err(|e| JobError::Io(e.to_string()))?;
    Ok(())
}

pub fn create_job(
    job_name: &str,
    site_id: Option<String>,
    site_name: Option<String>,
    building_name: Option<String>,
    description: Option<String>,
    tags: Vec<String>,
    created_by: Option<String>,
) -> Result<JobMeta, JobError> {
    let name = job_name.trim();
    if name.is_empty() {
        return Err(JobError::Invalid("job_name is required".into()));
    }
    let now = utc_now();
    let meta = JobMeta {
        schema_version: SCHEMA_VERSION,
        job_id: format!("job-{}", Uuid::new_v4()),
        job_name: name.to_string(),
        description,
        status: "active".into(),
        archived: false,
        created_at: now.clone(),
        updated_at: now,
        created_by,
        site_id,
        site_name,
        building_name,
        tags,
        meta_revision: new_meta_revision(),
        latest_run_id: None,
        latest_findings_revision: None,
        mapping_path: None,
        revisions: JobRevisions::default(),
    };
    let path = job_dir(&meta.job_id)?;
    if path.exists() {
        return Err(JobError::Io("job directory already exists".into()));
    }
    ensure_layout(&path)?;
    let value = serde_json::to_value(&meta).map_err(|e| JobError::Io(e.to_string()))?;
    atomic_write_json(&path.join("job.json"), &value)?;
    atomic_write_json(
        &path.join("datasets/dataset_refs.json"),
        &json!({"schema_version": "1", "datasets": []}),
    )?;
    Ok(meta)
}

pub fn load_job(job_id: &str) -> Result<JobMeta, JobError> {
    let path = job_dir(job_id)?.join("job.json");
    if !path.is_file() {
        return Err(JobError::NotFound(format!("job not found: {job_id}")));
    }
    let raw = fs::read_to_string(&path).map_err(|e| JobError::Io(e.to_string()))?;
    let meta: JobMeta = serde_json::from_str(&raw)
        .map_err(|e| JobError::Invalid(format!("malformed job.json for {job_id}: {e}")))?;
    if meta.schema_version != SCHEMA_VERSION {
        return Err(JobError::Invalid(format!(
            "unsupported schema_version: {}",
            meta.schema_version
        )));
    }
    Ok(meta)
}

pub fn save_job(
    mut meta: JobMeta,
    expected_meta_revision: Option<&str>,
) -> Result<JobMeta, JobError> {
    let on_disk = load_job(&meta.job_id)?;
    if let Some(expected) = expected_meta_revision {
        if on_disk.meta_revision != expected {
            return Err(JobError::Conflict {
                expected: expected.to_string(),
                current: on_disk.meta_revision,
            });
        }
    }
    if meta.status == "archived" {
        meta.archived = true;
    }
    meta.updated_at = utc_now();
    meta.meta_revision = new_meta_revision();
    let path = job_dir(&meta.job_id)?;
    ensure_layout(&path)?;
    let value = serde_json::to_value(&meta).map_err(|e| JobError::Io(e.to_string()))?;
    atomic_write_json(&path.join("job.json"), &value)?;
    Ok(meta)
}

pub fn list_jobs(
    include_archived: bool,
    status: Option<&str>,
    site_id: Option<&str>,
    tag: Option<&str>,
) -> Vec<JobMeta> {
    let root = jobs_root();
    let mut out = Vec::new();
    let Ok(entries) = fs::read_dir(&root) else {
        return out;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let Some(name) = path.file_name().and_then(|s| s.to_str()) else {
            continue;
        };
        if !name.starts_with("job-") {
            continue;
        }
        match load_job(name) {
            Ok(meta) => {
                if let Some(st) = status {
                    if meta.status != st {
                        continue;
                    }
                } else if !include_archived && meta.status == "archived" {
                    continue;
                }
                if let Some(sid) = site_id {
                    if meta.site_id.as_deref() != Some(sid) {
                        continue;
                    }
                }
                if let Some(t) = tag {
                    if !meta.tags.iter().any(|x| x == t) {
                        continue;
                    }
                }
                out.push(meta);
            }
            Err(_) => continue, // corrupt job isolation
        }
    }
    out.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
    out
}

pub fn archive_job(job_id: &str) -> Result<JobMeta, JobError> {
    let mut meta = load_job(job_id)?;
    let expected = meta.meta_revision.clone();
    meta.status = "archived".into();
    meta.archived = true;
    save_job(meta, Some(&expected))
}

pub fn restore_job(job_id: &str) -> Result<JobMeta, JobError> {
    let mut meta = load_job(job_id)?;
    let expected = meta.meta_revision.clone();
    meta.status = "active".into();
    meta.archived = false;
    save_job(meta, Some(&expected))
}

/// Permanently remove a job workspace directory (hard delete — not archive).
pub fn delete_job(job_id: &str) -> Result<(), JobError> {
    validate_job_id(job_id)?;
    let dir = job_dir(job_id)?;
    if !dir.is_dir() {
        return Err(JobError::NotFound(format!("job not found: {job_id}")));
    }
    fs::remove_dir_all(&dir).map_err(|e| JobError::Io(e.to_string()))?;
    Ok(())
}

/// Hard-delete every job whose `site_id` matches (used by Delete site).
/// Returns `(deleted, errors)` — callers should treat non-empty errors as a failed purge.
pub fn delete_jobs_for_site(site_id: &str) -> (usize, Vec<String>) {
    let sid = site_id.trim();
    if sid.is_empty() {
        return (0, Vec::new());
    }
    let mut n = 0usize;
    let mut errors = Vec::new();
    for meta in list_jobs(true, None, Some(sid), None) {
        match delete_job(&meta.job_id) {
            Ok(()) => n += 1,
            Err(e) => errors.push(format!("{}: {:?}", meta.job_id, e)),
        }
    }
    (n, errors)
}

pub fn duplicate_job(job_id: &str, new_name: Option<&str>) -> Result<JobMeta, JobError> {
    let src = load_job(job_id)?;
    let src_dir = job_dir(job_id)?;
    let copy = create_job(
        new_name.unwrap_or(&format!("{} (copy)", src.job_name)),
        src.site_id.clone(),
        src.site_name.clone(),
        src.building_name.clone(),
        src.description.clone(),
        src.tags.clone(),
        src.created_by.clone(),
    )?;
    let dst_dir = job_dir(&copy.job_id)?;
    for rel in [
        "mapping/role_map.json",
        "mapping/equipment_map.json",
        "configs/session_config.json",
        "configs/rule_parameters.json",
        "configs/schedules.json",
        "datasets/dataset_refs.json",
    ] {
        let from = src_dir.join(rel);
        if from.is_file() {
            let to = dst_dir.join(rel);
            if let Some(parent) = to.parent() {
                let _ = fs::create_dir_all(parent);
            }
            let _ = fs::copy(&from, &to);
        }
    }
    let mut meta = load_job(&copy.job_id)?;
    let expected = meta.meta_revision.clone();
    if dst_dir.join("mapping/role_map.json").is_file() {
        meta.mapping_path = Some("mapping/role_map.json".into());
        meta.revisions.mapping = src.revisions.mapping.clone();
    }
    meta.revisions.dataset = src.revisions.dataset.clone();
    meta.revisions.config = src.revisions.config.clone();
    save_job(meta, Some(&expected))
}

/// Canonical provenance fingerprint (B3) — deterministic JSON hash components.
pub fn compute_input_fingerprint(components: &Value) -> Result<(String, Value), JobError> {
    let canonical = canonicalize_json(components);
    let human = canonical.clone();
    let bytes = serde_json::to_vec(&canonical).map_err(|e| JobError::Io(e.to_string()))?;
    let digest = sha256_hex(&bytes);
    Ok((digest, human))
}

fn canonicalize_json(v: &Value) -> Value {
    match v {
        Value::Object(map) => {
            let mut keys: Vec<_> = map.keys().cloned().collect();
            keys.sort();
            let mut out = serde_json::Map::new();
            for k in keys {
                if let Some(val) = map.get(&k) {
                    out.insert(k, canonicalize_json(val));
                }
            }
            Value::Object(out)
        }
        Value::Array(arr) => Value::Array(arr.iter().map(canonicalize_json).collect()),
        other => other.clone(),
    }
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

pub fn validate_run_id(run_id: &str) -> Result<(), JobError> {
    if !is_run_id(run_id) {
        return Err(JobError::Invalid(format!("invalid run_id: {run_id}")));
    }
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunMeta {
    pub schema_version: String,
    pub run_id: String,
    pub job_id: String,
    pub run_type: String,
    pub status: String,
    pub created_at: String,
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub input_fingerprint: String,
    #[serde(default)]
    pub fingerprint_components: Value,
    #[serde(default)]
    pub engine_version: String,
    #[serde(default)]
    pub rule_registry_hash: String,
    #[serde(default)]
    pub result_summary: Value,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub stale_reasons: Vec<String>,
}

pub fn create_run(
    job_id: &str,
    run_type: &str,
    fingerprint_components: Value,
    engine_version: &str,
    rule_registry_hash: &str,
) -> Result<RunMeta, JobError> {
    let _ = load_job(job_id)?;
    let (fp, human) = compute_input_fingerprint(&fingerprint_components)?;
    let run = RunMeta {
        schema_version: "1".into(),
        run_id: format!("run-{}", Uuid::new_v4()),
        job_id: job_id.to_string(),
        run_type: run_type.to_string(),
        status: "QUEUED".into(),
        created_at: utc_now(),
        started_at: None,
        completed_at: None,
        input_fingerprint: fp,
        fingerprint_components: human,
        engine_version: engine_version.to_string(),
        rule_registry_hash: rule_registry_hash.to_string(),
        result_summary: json!({}),
        error: None,
        stale_reasons: vec![],
    };
    let dir = job_dir(job_id)?.join("runs").join(&run.run_id);
    fs::create_dir_all(&dir).map_err(|e| JobError::Io(e.to_string()))?;
    let value = serde_json::to_value(&run).map_err(|e| JobError::Io(e.to_string()))?;
    atomic_write_json(&dir.join("run.json"), &value)?;
    let mut job = load_job(job_id)?;
    let expected = job.meta_revision.clone();
    job.latest_run_id = Some(run.run_id.clone());
    let _ = save_job(job, Some(&expected))?;
    Ok(run)
}

pub fn load_run(job_id: &str, run_id: &str) -> Result<RunMeta, JobError> {
    validate_run_id(run_id)?;
    let path = job_dir(job_id)?.join("runs").join(run_id).join("run.json");
    if !path.is_file() {
        return Err(JobError::NotFound(format!("run not found: {run_id}")));
    }
    let raw = fs::read_to_string(&path).map_err(|e| JobError::Io(e.to_string()))?;
    serde_json::from_str(&raw).map_err(|e| JobError::Invalid(format!("malformed run.json: {e}")))
}

fn save_run(run: &RunMeta) -> Result<(), JobError> {
    validate_run_id(&run.run_id)?;
    let path = job_dir(&run.job_id)?
        .join("runs")
        .join(&run.run_id)
        .join("run.json");
    let value = serde_json::to_value(run).map_err(|e| JobError::Io(e.to_string()))?;
    atomic_write_json(&path, &value)
}

/// Transition a run status. Allowed terminal statuses: SUCCEEDED, FAILED, CANCELLED, STALE.
/// `RUNNING` may be set from `QUEUED`. Interrupted `RUNNING` runs are recovered on startup.
pub fn update_run_status(
    job_id: &str,
    run_id: &str,
    status: &str,
    error: Option<String>,
) -> Result<RunMeta, JobError> {
    let allowed = [
        "QUEUED",
        "RUNNING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "STALE",
    ];
    if !allowed.contains(&status) {
        return Err(JobError::Invalid(format!("invalid run status: {status}")));
    }
    let mut run = load_run(job_id, run_id)?;
    let now = utc_now();
    if status == "RUNNING" && run.started_at.is_none() {
        run.started_at = Some(now.clone());
    }
    if matches!(status, "SUCCEEDED" | "FAILED" | "CANCELLED" | "STALE") {
        run.completed_at = Some(now);
    }
    run.status = status.to_string();
    if let Some(err) = error {
        run.error = Some(err);
    }
    save_run(&run)?;
    Ok(run)
}

/// On central restart: mark any `RUNNING` runs as `FAILED` with a restart-recovery note.
/// Policy: interrupted in-flight work is not auto-rerun; callers must create a new run.
pub fn recover_interrupted_runs() -> Result<usize, JobError> {
    let root = jobs_root();
    if !root.is_dir() {
        return Ok(0);
    }
    let mut recovered = 0usize;
    let entries = fs::read_dir(&root).map_err(|e| JobError::Io(e.to_string()))?;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(job_id) = name.to_str() else {
            continue;
        };
        if !is_job_id(job_id) {
            continue;
        }
        let runs_dir = entry.path().join("runs");
        if !runs_dir.is_dir() {
            continue;
        }
        let run_entries = match fs::read_dir(&runs_dir) {
            Ok(e) => e,
            Err(_) => continue,
        };
        for run_ent in run_entries.flatten() {
            let run_name = run_ent.file_name();
            let Some(run_id) = run_name.to_str() else {
                continue;
            };
            if !is_run_id(run_id) {
                continue;
            }
            let path = run_ent.path().join("run.json");
            if !path.is_file() {
                continue;
            }
            let Ok(raw) = fs::read_to_string(&path) else {
                continue;
            };
            let Ok(mut run) = serde_json::from_str::<RunMeta>(&raw) else {
                continue;
            };
            if run.status != "RUNNING" {
                continue;
            }
            run.status = "FAILED".into();
            run.completed_at = Some(utc_now());
            run.error = Some("interrupted by central restart; create a new run to continue".into());
            if save_run(&run).is_ok() {
                recovered += 1;
            }
        }
    }
    Ok(recovered)
}

pub fn evaluate_stale(
    job_id: &str,
    run_id: &str,
    current_components: &Value,
) -> Result<(bool, Vec<String>), JobError> {
    let run = load_run(job_id, run_id)?;
    let (current_fp, _) = compute_input_fingerprint(current_components)?;
    if current_fp == run.input_fingerprint {
        return Ok((false, vec!["CURRENT".into()]));
    }
    let mut reasons = Vec::new();
    let stored = &run.fingerprint_components;
    for key in [
        "telemetry_content_hash",
        "mapping_revision",
        "config_revision",
        "schedule_revision",
        "weather_hash",
        "rule_registry_hash",
        "rule_parameters_hash",
        "engine_version",
        "unit_normalization_version",
    ] {
        let a = stored.get(key);
        let b = current_components.get(key);
        if a != b {
            let reason = match key {
                "telemetry_content_hash" => "STALE_DATA",
                "mapping_revision" => "STALE_MAPPING",
                "config_revision" => "STALE_CONFIG",
                "schedule_revision" => "STALE_SCHEDULE",
                "weather_hash" => "STALE_WEATHER",
                "rule_registry_hash" => "STALE_RULE_REGISTRY",
                "rule_parameters_hash" => "STALE_RULE_PARAMETERS",
                "engine_version" => "STALE_ENGINE",
                "unit_normalization_version" => "STALE_UNIT_NORMALIZATION",
                _ => "STALE_UNKNOWN",
            };
            reasons.push(reason.to_string());
        }
    }
    if reasons.is_empty() {
        reasons.push("STALE_UNKNOWN".into());
    }
    Ok((true, reasons))
}

fn validate_findings_payload(payload: &Value) -> Result<(), JobError> {
    let obj = payload
        .as_object()
        .ok_or_else(|| JobError::Invalid("findings must be a JSON object".into()))?;
    if obj.get("schema_version").is_none() {
        return Err(JobError::Invalid(
            "findings must include schema_version".into(),
        ));
    }
    match obj.get("findings") {
        None => {}
        Some(Value::Array(items)) => {
            for item in items {
                let row = item.as_object().ok_or_else(|| {
                    JobError::Invalid("each finding must be a JSON object".into())
                })?;
                if row.get("correlation_key").and_then(Value::as_str).is_none() {
                    return Err(JobError::Invalid(
                        "each finding must include correlation_key".into(),
                    ));
                }
            }
        }
        Some(_) => {
            return Err(JobError::Invalid(
                "findings.findings must be an array".into(),
            ));
        }
    }
    Ok(())
}

fn validate_dispositions_payload(payload: &Value) -> Result<(), JobError> {
    let obj = payload
        .as_object()
        .ok_or_else(|| JobError::Invalid("dispositions must be a JSON object".into()))?;
    if obj.get("schema_version").is_none() {
        return Err(JobError::Invalid(
            "dispositions must include schema_version".into(),
        ));
    }
    match obj.get("dispositions") {
        None => {}
        Some(Value::Array(items)) => {
            for item in items {
                let row = item.as_object().ok_or_else(|| {
                    JobError::Invalid("each disposition must be a JSON object".into())
                })?;
                if row.get("correlation_key").and_then(Value::as_str).is_none() {
                    return Err(JobError::Invalid(
                        "each disposition must include correlation_key".into(),
                    ));
                }
            }
        }
        Some(_) => {
            return Err(JobError::Invalid(
                "dispositions.dispositions must be an array".into(),
            ));
        }
    }
    Ok(())
}

pub fn load_findings(job_id: &str) -> Result<Value, JobError> {
    let path = job_dir(job_id)?.join("findings/findings.json");
    if !path.is_file() {
        return Ok(json!({"schema_version": "1", "findings": []}));
    }
    let raw = fs::read_to_string(&path).map_err(|e| JobError::Io(e.to_string()))?;
    serde_json::from_str(&raw)
        .map_err(|e| JobError::Invalid(format!("malformed findings.json: {e}")))
}

pub fn save_findings(
    job_id: &str,
    findings: Value,
    findings_revision: Option<String>,
) -> Result<JobMeta, JobError> {
    validate_findings_payload(&findings)?;
    let mut meta = load_job(job_id)?;
    let expected = meta.meta_revision.clone();
    atomic_write_json(&job_dir(job_id)?.join("findings/findings.json"), &findings)?;
    meta.latest_findings_revision = Some(findings_revision.unwrap_or_else(utc_now));
    save_job(meta, Some(&expected))
}

pub fn load_dispositions(job_id: &str) -> Result<Value, JobError> {
    let path = job_dir(job_id)?.join("findings/dispositions.json");
    if !path.is_file() {
        return Ok(json!({"schema_version": "1", "dispositions": []}));
    }
    let raw = fs::read_to_string(&path).map_err(|e| JobError::Io(e.to_string()))?;
    serde_json::from_str(&raw)
        .map_err(|e| JobError::Invalid(format!("malformed dispositions.json: {e}")))
}

pub fn save_dispositions(job_id: &str, dispositions: Value) -> Result<(), JobError> {
    let _ = load_job(job_id)?;
    validate_dispositions_payload(&dispositions)?;
    atomic_write_json(
        &job_dir(job_id)?.join("findings/dispositions.json"),
        &dispositions,
    )
}

pub fn save_wattlab_handoff(job_id: &str, handoff: Value) -> Result<Value, JobError> {
    let _ = load_job(job_id)?;
    let obj = handoff
        .as_object()
        .ok_or_else(|| JobError::Invalid("handoff must be a JSON object".into()))?;
    let handoff_id = obj
        .get("handoff_id")
        .and_then(Value::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| format!("handoff-{}", Uuid::new_v4()));
    let meta = load_job(job_id)?;
    let mut payload = json!({
        "schema_version": "1",
        "handoff_id": handoff_id,
        "job_id": job_id,
        "run_id": obj.get("run_id").cloned().unwrap_or_else(|| {
            meta.latest_run_id
                .clone()
                .map(Value::String)
                .unwrap_or(Value::Null)
        }),
        "findings_revision": obj.get("findings_revision").cloned().unwrap_or_else(|| {
            meta.latest_findings_revision
                .clone()
                .map(Value::String)
                .unwrap_or(Value::Null)
        }),
        "created_at": utc_now(),
    });
    if let Some(map) = payload.as_object_mut() {
        for (k, v) in obj {
            if !matches!(
                k.as_str(),
                "schema_version" | "handoff_id" | "job_id" | "created_at"
            ) {
                map.insert(k.clone(), v.clone());
            }
        }
    }
    let path = job_dir(job_id)?
        .join("wattlab/handoffs")
        .join(format!("{handoff_id}.json"));
    atomic_write_json(&path, &payload)?;
    Ok(payload)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn with_tmp_ws<F: FnOnce(PathBuf)>(f: F) {
        let _g = WORKSPACE_ENV_TEST_LOCK.lock().unwrap();
        let dir = std::env::temp_dir().join(format!("openfdd-jobs-{}", Uuid::new_v4()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let prev = std::env::var("OPENFDD_WORKSPACE").ok();
        std::env::set_var("OPENFDD_WORKSPACE", &dir);
        f(dir.clone());
        match prev {
            Some(v) => std::env::set_var("OPENFDD_WORKSPACE", v),
            None => std::env::remove_var("OPENFDD_WORKSPACE"),
        }
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn create_job_persists_site_id() {
        // OFDD-076b: callers (routes) map building_id → site_id before create_job.
        with_tmp_ws(|_dir| {
            let meta = create_job(
                "Bound",
                Some("BUILDING_100".into()),
                Some("Liberty B100".into()),
                Some("BUILDING_100".into()),
                None,
                vec![],
                None,
            )
            .unwrap();
            assert_eq!(meta.site_id.as_deref(), Some("BUILDING_100"));
            assert_eq!(meta.building_name.as_deref(), Some("BUILDING_100"));
            let loaded = load_job(&meta.job_id).unwrap();
            assert_eq!(loaded.site_id.as_deref(), Some("BUILDING_100"));
        });
    }

    #[test]
    fn delete_jobs_for_site_removes_matching_only() {
        with_tmp_ws(|_dir| {
            let keep = create_job(
                "Keep",
                Some("BUILDING_100".into()),
                None,
                None,
                None,
                vec![],
                None,
            )
            .unwrap();
            let drop_a = create_job(
                "Drop A",
                Some("BUILDING_50".into()),
                None,
                None,
                None,
                vec![],
                None,
            )
            .unwrap();
            let drop_b = create_job(
                "Drop B",
                Some("BUILDING_50".into()),
                None,
                None,
                None,
                vec![],
                None,
            )
            .unwrap();
            let n = delete_jobs_for_site("BUILDING_50");
            assert_eq!(n.0, 2);
            assert!(n.1.is_empty());
            assert!(load_job(&keep.job_id).is_ok());
            assert!(matches!(
                load_job(&drop_a.job_id),
                Err(JobError::NotFound(_))
            ));
            assert!(matches!(
                load_job(&drop_b.job_id),
                Err(JobError::NotFound(_))
            ));
        });
    }

    #[test]
    fn create_list_archive_restore() {
        with_tmp_ws(|_dir| {
            let meta = create_job("Test", None, None, None, None, vec!["t".into()], None).unwrap();
            assert!(meta.job_id.starts_with("job-"));
            assert_eq!(list_jobs(true, None, None, None).len(), 1);
            archive_job(&meta.job_id).unwrap();
            assert_eq!(list_jobs(false, None, None, None).len(), 0);
            restore_job(&meta.job_id).unwrap();
            assert_eq!(list_jobs(false, None, None, None).len(), 1);
        });
    }

    #[test]
    fn hard_delete_removes_job_dir() {
        with_tmp_ws(|_dir| {
            let meta = create_job("Del", None, None, None, None, vec![], None).unwrap();
            let id = meta.job_id.clone();
            assert!(job_dir(&id).unwrap().is_dir());
            delete_job(&id).unwrap();
            assert!(!job_dir(&id).unwrap().exists());
            assert!(matches!(load_job(&id), Err(JobError::NotFound(_))));
            assert!(matches!(delete_job(&id), Err(JobError::NotFound(_))));
        });
    }

    #[test]
    fn revision_conflict() {
        with_tmp_ws(|_dir| {
            let meta = create_job("Rev", None, None, None, None, vec![], None).unwrap();
            let stale = meta.meta_revision.clone();
            let mut m2 = load_job(&meta.job_id).unwrap();
            m2.job_name = "Other".into();
            save_job(m2, Some(&stale)).unwrap();
            let mut bad = load_job(&meta.job_id).unwrap();
            bad.job_name = "Stale".into();
            let err = save_job(bad, Some(&stale)).unwrap_err();
            assert!(matches!(err, JobError::Conflict { .. }));
        });
    }

    #[test]
    fn fingerprint_order_insensitive() {
        with_tmp_ws(|_dir| {
            let a = json!({"b": 1, "a": 2});
            let b = json!({"a": 2, "b": 1});
            let (fa, _) = compute_input_fingerprint(&a).unwrap();
            let (fb, _) = compute_input_fingerprint(&b).unwrap();
            assert_eq!(fa, fb);
        });
    }

    #[test]
    fn stale_mapping_reason() {
        with_tmp_ws(|_dir| {
            let job = create_job("S", None, None, None, None, vec![], None).unwrap();
            let comps = json!({
                "mapping_revision": "m1",
                "config_revision": "c1",
                "telemetry_content_hash": "t1",
                "rule_registry_hash": "r1",
                "engine_version": "1"
            });
            let run = create_run(&job.job_id, "fdd_registry", comps.clone(), "1", "r1").unwrap();
            let mut next = comps;
            next["mapping_revision"] = json!("m2");
            let (stale, reasons) = evaluate_stale(&job.job_id, &run.run_id, &next).unwrap();
            assert!(stale);
            assert!(reasons.iter().any(|r| r == "STALE_MAPPING"));
        });
    }

    #[test]
    fn rejects_bad_job_id() {
        assert!(validate_job_id("job-../../../etc").is_err());
        assert!(validate_job_id("not-a-job").is_err());
    }

    #[test]
    fn findings_and_dispositions_roundtrip() {
        with_tmp_ws(|_dir| {
            let job = create_job("F", None, None, None, None, vec![], None).unwrap();
            let findings = json!({
                "schema_version": "1",
                "findings": [{
                    "finding_id": "finding-1",
                    "correlation_key": "rule:VAV-1:equip:AHU-1",
                    "run_id": "run-1",
                    "evidence": {"sql_row_hash": "abc"}
                }]
            });
            save_findings(&job.job_id, findings.clone(), Some("rev-1".into())).unwrap();
            assert_eq!(
                load_findings(&job.job_id).unwrap()["findings"][0]["evidence"],
                findings["findings"][0]["evidence"]
            );
            let updated = load_job(&job.job_id).unwrap();
            assert_eq!(updated.latest_findings_revision.as_deref(), Some("rev-1"));

            let dispositions = json!({
                "schema_version": "1",
                "dispositions": [{
                    "correlation_key": "rule:VAV-1:equip:AHU-1",
                    "status": "confirmed",
                    "updated_at": "2026-01-01T00:00:00Z"
                }]
            });
            save_dispositions(&job.job_id, dispositions.clone()).unwrap();
            assert_eq!(load_dispositions(&job.job_id).unwrap(), dispositions);
        });
    }

    #[test]
    fn wattlab_handoff_written() {
        with_tmp_ws(|_dir| {
            let job = create_job("W", None, None, None, None, vec![], None).unwrap();
            let out = save_wattlab_handoff(
                &job.job_id,
                json!({"portable_zip_uri": "workspace://exports/demo.zip"}),
            )
            .unwrap();
            assert!(out.get("handoff_id").is_some());
            let hid = out["handoff_id"].as_str().unwrap();
            let path = job_dir(&job.job_id)
                .unwrap()
                .join("wattlab/handoffs")
                .join(format!("{hid}.json"));
            assert!(path.is_file());
        });
    }

    #[test]
    fn recover_interrupted_running_runs() {
        with_tmp_ws(|_dir| {
            let job = create_job("R", None, None, None, None, vec![], None).unwrap();
            let comps = json!({"mapping_revision": "m1"});
            let run = create_run(&job.job_id, "fdd_registry", comps, "1", "r1").unwrap();
            update_run_status(&job.job_id, &run.run_id, "RUNNING", None).unwrap();
            assert_eq!(
                load_run(&job.job_id, &run.run_id).unwrap().status,
                "RUNNING"
            );
            let n = recover_interrupted_runs().unwrap();
            assert_eq!(n, 1);
            let after = load_run(&job.job_id, &run.run_id).unwrap();
            assert_eq!(after.status, "FAILED");
            assert!(after.error.as_deref().unwrap_or("").contains("restart"));
            assert!(after.completed_at.is_some());
        });
    }

    #[test]
    fn findings_reject_missing_correlation_key() {
        with_tmp_ws(|_dir| {
            let job = create_job("BadF", None, None, None, None, vec![], None).unwrap();
            let bad = json!({
                "schema_version": "1",
                "findings": [{"finding_id": "finding-1"}]
            });
            let err = save_findings(&job.job_id, bad, None).unwrap_err();
            assert!(matches!(err, JobError::Invalid(_)));
        });
    }
}
