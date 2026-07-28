//! Restricted EnergyPlus runner policy + job-attached run records (Milestone D4).
//!
//! **Execution is external** (playground vibe20 / approved runner image). Central
//! does **not** open a Docker socket, does **not** parse IDF, and does **not**
//! invoke EnergyPlus in-process. This module only validates runner policy and
//! persists QUEUED / status / artifact metadata under
//! `workspace/jobs/<id>/wattlab/runs/*.json`.

use std::path::{Component, Path, PathBuf};

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::jobs::{self, JobError};

/// Constrained runner policy for an external EnergyPlus worker.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunnerPolicy {
    /// Required immutable image digest (`sha256:…`). Tags alone are rejected.
    pub image_digest: String,
    /// Absolute workspace root the runner may read/write under.
    pub workspace_root: PathBuf,
    /// CPU limit hint (cores) for the external runner.
    pub cpu_limit: f64,
    /// Memory limit hint (MiB) for the external runner.
    pub memory_limit_mib: u64,
    /// Wall-clock timeout for the external run.
    pub timeout_secs: u64,
    /// Runner must drop privileges (non-root).
    pub non_root: bool,
}

impl RunnerPolicy {
    pub fn validate_policy(&self) -> Result<(), String> {
        let digest = self.image_digest.trim();
        if digest.is_empty() {
            return Err("image_digest is required".into());
        }
        if !digest.starts_with("sha256:") || digest.len() < "sha256:".len() + 16 {
            return Err("image_digest must be a sha256:… digest (not a mutable tag)".into());
        }
        if self.workspace_root.as_os_str().is_empty() {
            return Err("workspace_root is required".into());
        }
        if !self.workspace_root.is_absolute() {
            return Err("workspace_root must be an absolute path".into());
        }
        if path_has_escape(&self.workspace_root) {
            return Err("workspace_root path escape rejected".into());
        }
        if self.cpu_limit <= 0.0 {
            return Err("cpu_limit must be > 0".into());
        }
        if self.memory_limit_mib == 0 {
            return Err("memory_limit_mib must be > 0".into());
        }
        if self.timeout_secs == 0 {
            return Err("timeout_secs must be > 0".into());
        }
        if !self.non_root {
            return Err("non_root must be true (privileged runner rejected)".into());
        }
        Ok(())
    }
}

fn path_has_escape(path: &Path) -> bool {
    path.components().any(|c| matches!(c, Component::ParentDir))
}

/// Request body for `POST /api/jobs/{id}/eplus/runs` (queue only — no execution).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobRunRequest {
    #[serde(default)]
    pub run_id: Option<String>,
    /// Relative path under the job (or approved workspace) to the IDF / model ref.
    #[serde(default)]
    pub model_ref: Option<String>,
    #[serde(default)]
    pub handoff_id: Option<String>,
    #[serde(default)]
    pub policy: Option<RunnerPolicy>,
    #[serde(default)]
    pub notes: Option<String>,
}

/// Metadata describing an artifact attached after an external run completes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AttachArtifactMeta {
    pub artifact_id: String,
    pub path: String,
    #[serde(default)]
    pub content_sha256: Option<String>,
    #[serde(default)]
    pub media_type: Option<String>,
    #[serde(default)]
    pub bytes: Option<u64>,
}

fn utc_now() -> String {
    Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

fn validate_relative_ref(rel: &str) -> Result<(), JobError> {
    if rel.is_empty() || rel.contains('\0') {
        return Err(JobError::Invalid("model_ref invalid".into()));
    }
    if rel.starts_with('/') || rel.starts_with('\\') {
        return Err(JobError::Invalid(
            "model_ref must be relative (no absolute paths)".into(),
        ));
    }
    let p = Path::new(rel);
    if path_has_escape(p) {
        return Err(JobError::Invalid("model_ref path escape rejected".into()));
    }
    Ok(())
}

/// Persist a **QUEUED** external EnergyPlus run record. Does not start a container.
pub fn queue_external_run(job_id: &str, req: JobRunRequest) -> Result<Value, JobError> {
    let _ = jobs::load_job(job_id)?;
    if let Some(ref policy) = req.policy {
        policy
            .validate_policy()
            .map_err(|e| JobError::Invalid(format!("runner policy: {e}")))?;
    }
    if let Some(ref model) = req.model_ref {
        validate_relative_ref(model)?;
    }

    let eplus_run_id = req
        .run_id
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| format!("eplus-{}", Uuid::new_v4()));
    if eplus_run_id.contains("..") || eplus_run_id.contains('/') || eplus_run_id.contains('\\') {
        return Err(JobError::Invalid("invalid eplus run_id".into()));
    }

    // Explicit: central only persists status; an external worker claims QUEUED runs.
    let payload = json!({
        "schema_version": "1",
        "kind": "eplus_external_run",
        "eplus_run_id": eplus_run_id,
        "job_id": job_id,
        "status": "QUEUED",
        "execution": "external",
        "central_executes_energyplus": false,
        "docker_socket": false,
        "model_ref": req.model_ref,
        "handoff_id": req.handoff_id,
        "notes": req.notes,
        "policy": req.policy,
        "artifacts": Value::Array(vec![]),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    });

    let path = jobs::job_dir(job_id)?
        .join("wattlab/runs")
        .join(format!("{eplus_run_id}.json"));
    jobs::atomic_write_json(&path, &payload)?;
    Ok(payload)
}

/// Attach artifact metadata to an existing external run record (no file bytes in central).
pub fn attach_artifact_meta(
    job_id: &str,
    eplus_run_id: &str,
    artifact: AttachArtifactMeta,
) -> Result<Value, JobError> {
    let _ = jobs::load_job(job_id)?;
    if eplus_run_id.contains("..") || eplus_run_id.contains('/') || eplus_run_id.contains('\\') {
        return Err(JobError::Invalid("invalid eplus run_id".into()));
    }
    validate_relative_ref(&artifact.path)?;
    let path = jobs::job_dir(job_id)?
        .join("wattlab/runs")
        .join(format!("{eplus_run_id}.json"));
    if !path.is_file() {
        return Err(JobError::NotFound(format!(
            "eplus run not found: {eplus_run_id}"
        )));
    }
    let raw = std::fs::read_to_string(&path).map_err(|e| JobError::Io(e.to_string()))?;
    let mut value: Value =
        serde_json::from_str(&raw).map_err(|e| JobError::Invalid(format!("malformed run: {e}")))?;
    let artifacts = value
        .as_object_mut()
        .ok_or_else(|| JobError::Invalid("run must be object".into()))?
        .entry("artifacts")
        .or_insert_with(|| Value::Array(vec![]));
    let list = artifacts
        .as_array_mut()
        .ok_or_else(|| JobError::Invalid("artifacts must be array".into()))?;
    list.push(serde_json::to_value(artifact).map_err(|e| JobError::Io(e.to_string()))?);
    if let Some(obj) = value.as_object_mut() {
        obj.insert("updated_at".into(), Value::String(utc_now()));
    }
    jobs::atomic_write_json(&path, &value)?;
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static LOCK: Mutex<()> = Mutex::new(());

    fn valid_policy() -> RunnerPolicy {
        RunnerPolicy {
            image_digest: "sha256:0123456789abcdef0123456789abcdef".into(),
            workspace_root: PathBuf::from("/var/openfdd/workspace"),
            cpu_limit: 2.0,
            memory_limit_mib: 4096,
            timeout_secs: 3600,
            non_root: true,
        }
    }

    #[test]
    fn policy_rejects_missing_digest() {
        let mut p = valid_policy();
        p.image_digest = String::new();
        assert!(p.validate_policy().unwrap_err().contains("image_digest"));
    }

    #[test]
    fn policy_rejects_tag_instead_of_digest() {
        let mut p = valid_policy();
        p.image_digest = "ghcr.io/example/eplus:latest".into();
        assert!(p.validate_policy().unwrap_err().contains("sha256"));
    }

    #[test]
    fn policy_rejects_path_escape() {
        let mut p = valid_policy();
        p.workspace_root = PathBuf::from("/var/openfdd/../etc");
        assert!(p.validate_policy().unwrap_err().contains("escape"));
    }

    #[test]
    fn policy_rejects_relative_workspace() {
        let mut p = valid_policy();
        p.workspace_root = PathBuf::from("workspace");
        assert!(p.validate_policy().unwrap_err().contains("absolute"));
    }

    #[test]
    fn policy_rejects_root_runner() {
        let mut p = valid_policy();
        p.non_root = false;
        assert!(p.validate_policy().unwrap_err().contains("non_root"));
    }

    #[test]
    fn policy_ok() {
        assert!(valid_policy().validate_policy().is_ok());
    }

    #[test]
    fn queue_writes_queued_json() {
        let _g = LOCK.lock().unwrap();
        let dir = std::env::temp_dir().join(format!("openfdd-eplus-{}", Uuid::new_v4()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let prev = std::env::var("OPENFDD_WORKSPACE").ok();
        std::env::set_var("OPENFDD_WORKSPACE", &dir);

        let meta = jobs::create_job("Eplus", None, None, None, None, vec![], None).unwrap();
        let out = queue_external_run(
            &meta.job_id,
            JobRunRequest {
                run_id: Some("eplus-test-1".into()),
                model_ref: Some("models/building.idf".into()),
                handoff_id: None,
                policy: Some(valid_policy()),
                notes: Some("unit".into()),
            },
        )
        .unwrap();
        assert_eq!(out["status"], "QUEUED");
        assert_eq!(out["execution"], "external");
        assert_eq!(out["central_executes_energyplus"], false);
        assert_eq!(out["docker_socket"], false);
        let path = jobs::job_dir(&meta.job_id)
            .unwrap()
            .join("wattlab/runs/eplus-test-1.json");
        assert!(path.is_file());

        let attached = attach_artifact_meta(
            &meta.job_id,
            "eplus-test-1",
            AttachArtifactMeta {
                artifact_id: "art-1".into(),
                path: "artifacts/eplus_out.zip".into(),
                content_sha256: Some("deadbeef".into()),
                media_type: Some("application/zip".into()),
                bytes: Some(12),
            },
        )
        .unwrap();
        assert_eq!(attached["artifacts"].as_array().unwrap().len(), 1);

        match prev {
            Some(v) => std::env::set_var("OPENFDD_WORKSPACE", v),
            None => std::env::remove_var("OPENFDD_WORKSPACE"),
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
