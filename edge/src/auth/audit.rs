//! Security audit log (no secrets).

use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

fn audit_log_path() -> PathBuf {
    std::env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
        .join("logs")
        .join("auth_audit.jsonl")
}

pub fn log_event(event: &str, detail: Value) {
    let path = audit_log_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let line = serde_json::json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "event": event,
        "detail": sanitize(detail)
    });
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{}", line);
    }
}

fn sanitize(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, v) in map {
                if k.to_ascii_lowercase().contains("password")
                    || k.to_ascii_lowercase().contains("secret")
                    || k.to_ascii_lowercase().contains("token")
                    || k == "authorization"
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

    #[test]
    fn redacts_password_fields_in_audit() {
        let sanitized = sanitize(serde_json::json!({
            "username": "integrator",
            "password": "secret",
            "token": "abc"
        }));
        assert_eq!(sanitized["password"], "***REDACTED***");
        assert_eq!(sanitized["token"], "***REDACTED***");
        assert_eq!(sanitized["username"], "integrator");
    }
}
