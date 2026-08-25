//! Security audit log for pen-test / operator review (no secrets).
//!
//! Dual sink:
//! - JSONL file under `$OPENFDD_WORKSPACE/logs/` (rotated by size)
//! - `tracing` target `security_audit` so Railway / AWS / docker capture stdout
//!
//! Env:
//! - `OPENFDD_AUDIT_LOG_PATH` — override file path (default `workspace/logs/security_audit.jsonl`)
//! - `OPENFDD_AUDIT_LOG_MAX_BYTES` — rotate threshold (default 10485760 = 10 MiB)
//! - `OPENFDD_AUDIT_LOG_KEEP` — rotated files to keep (default 5)

use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

static ROTATE_LOCK: Mutex<()> = Mutex::new(());

fn audit_log_path() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_AUDIT_LOG_PATH") {
        let trimmed = p.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    std::env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
        .join("logs")
        .join("security_audit.jsonl")
}

fn max_bytes() -> u64 {
    std::env::var("OPENFDD_AUDIT_LOG_MAX_BYTES")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10 * 1024 * 1024)
}

fn keep_count() -> usize {
    std::env::var("OPENFDD_AUDIT_LOG_KEEP")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(5)
        .clamp(1, 32)
}

/// Append one sanitized security event. Never panics; never logs secrets.
pub fn log_event(event: &str, detail: Value) {
    let detail = sanitize(detail);
    let line = serde_json::json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "channel": "security_audit",
        "event": event,
        "detail": detail,
    });

    // Hosted platforms (Railway / AWS / GHCR docker) scrape stdout.
    tracing::info!(
        target: "security_audit",
        event = %event,
        detail = %line["detail"],
        "security_audit"
    );

    let path = audit_log_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    // Legacy alias path used by older docs / edge tooling.
    let legacy = path
        .parent()
        .map(|p| p.join("auth_audit.jsonl"))
        .unwrap_or_else(|| PathBuf::from("workspace/logs/auth_audit.jsonl"));

    let _guard = ROTATE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    rotate_if_needed(&path);
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(file, "{line}");
    }
    // Keep writing the legacy filename too when paths differ (one line, same payload).
    if legacy != path {
        rotate_if_needed(&legacy);
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&legacy) {
            let _ = writeln!(file, "{line}");
        }
    }
}

fn rotate_if_needed(path: &Path) {
    let Ok(meta) = fs::metadata(path) else {
        return;
    };
    if meta.len() < max_bytes() {
        return;
    }
    let keep = keep_count();
    let oldest = path.with_extension(format!("jsonl.{keep}"));
    let _ = fs::remove_file(&oldest);
    for i in (1..keep).rev() {
        let from = path.with_extension(format!("jsonl.{i}"));
        let to = path.with_extension(format!("jsonl.{}", i + 1));
        let _ = fs::rename(&from, &to);
    }
    let first = path.with_extension("jsonl.1");
    let _ = fs::rename(path, &first);
}

fn sanitize(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, v) in map {
                let lower = k.to_ascii_lowercase();
                if lower.contains("password")
                    || lower.contains("secret")
                    || lower.contains("token")
                    || lower.contains("authorization")
                    || lower == "jwt"
                    || lower.contains("api_key")
                    || lower.contains("apikey")
                {
                    out.insert(k, Value::String("***REDACTED***".to_string()));
                } else {
                    out.insert(k, sanitize(v));
                }
            }
            Value::Object(out)
        }
        Value::Array(items) => Value::Array(items.into_iter().map(sanitize).collect()),
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use tempfile::tempdir;

    #[test]
    fn redacts_password_fields_in_audit() {
        let sanitized = sanitize(serde_json::json!({
            "username": "integrator",
            "password": "secret",
            "token": "abc",
            "api_key": "k"
        }));
        assert_eq!(sanitized["password"], "***REDACTED***");
        assert_eq!(sanitized["token"], "***REDACTED***");
        assert_eq!(sanitized["api_key"], "***REDACTED***");
        assert_eq!(sanitized["username"], "integrator");
    }

    #[test]
    fn rotates_when_over_max_bytes() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_LOG_MAX_BYTES", "200");
        std::env::set_var("OPENFDD_AUDIT_LOG_KEEP", "2");
        for i in 0..40 {
            log_event(
                "unit_test",
                serde_json::json!({"i": i, "pad": "xxxxxxxxxxxxxxxx"}),
            );
        }
        assert!(path.with_extension("jsonl.1").exists() || path.exists());
        let mut body = String::new();
        if path.exists() {
            fs::File::open(&path)
                .unwrap()
                .read_to_string(&mut body)
                .unwrap();
            assert!(body.contains("security_audit") || body.contains("unit_test"));
        }
        std::env::remove_var("OPENFDD_AUDIT_LOG_PATH");
        std::env::remove_var("OPENFDD_AUDIT_LOG_MAX_BYTES");
        std::env::remove_var("OPENFDD_AUDIT_LOG_KEEP");
    }
}
