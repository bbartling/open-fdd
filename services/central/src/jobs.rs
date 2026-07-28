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
    parts.iter().zip(lens).all(|(p, n)| {
        p.len() == n && p.chars().all(|c| c.is_ascii_hexdigit())
    })
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

fn atomic_write_json(path: &Path, payload: &Value) -> Result<(), JobError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| JobError::Io(e.to_string()))?;
    }
    let data = serde_json::to_vec_pretty(payload).map_err(|e| JobError::Io(e.to_string()))?;
    let tmp = path.with_extension("tmp");
    {
        let mut f = fs::File::create(&tmp).map_err(|e| JobError::Io(e.to_string()))?;
        f.write_all(&data).map_err(|e| JobError::Io(e.to_string()))?;
        f.write_all(b"\n").map_err(|e| JobError::Io(e.to_string()))?;
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
    let meta: JobMeta = serde_json::from_str(&raw).map_err(|e| {
        JobError::Invalid(format!("malformed job.json for {job_id}: {e}"))
    })?;
    if meta.schema_version != SCHEMA_VERSION {
        return Err(JobError::Invalid(format!(
            "unsupported schema_version: {}",
            meta.schema_version
        )));
    }
    Ok(meta)
}

pub fn save_job(mut meta: JobMeta, expected_meta_revision: Option<&str>) -> Result<JobMeta, JobError> {
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

pub fn evaluate_stale(job_id: &str, run_id: &str, current_components: &Value) -> Result<(bool, Vec<String>), JobError> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static LOCK: Mutex<()> = Mutex::new(());

    fn with_tmp_ws<F: FnOnce(PathBuf)>(f: F) {
        let _g = LOCK.lock().unwrap();
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
}
