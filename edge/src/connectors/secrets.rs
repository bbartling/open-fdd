//! Resolve connector secrets from gitignored local env files.

use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::PathBuf;

pub fn secrets_path() -> PathBuf {
    workspace_dir().join("secrets/openfdd-secrets.local.env")
}

pub fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

pub fn load_secrets() -> HashMap<String, String> {
    let path = secrets_path();
    if !path.exists() {
        return HashMap::new();
    }
    let text = fs::read_to_string(&path).unwrap_or_default();
    parse_env_lines(&text)
}

pub fn resolve_secret(name: &str) -> Option<String> {
    if name.is_empty() {
        return None;
    }
    if let Ok(v) = env::var(name) {
        if !v.is_empty() {
            return Some(v);
        }
    }
    load_secrets().get(name).cloned()
}

pub fn redact_connection_string(raw: &str) -> String {
    if raw.is_empty() {
        return String::new();
    }
    if let Some(at) = raw.find('@') {
        if let Some(scheme_end) = raw.find("://") {
            let scheme = &raw[..scheme_end + 3];
            let host_part = &raw[at..];
            return format!("{scheme}***:***{host_part}");
        }
    }
    "***REDACTED***".into()
}

fn parse_env_lines(text: &str) -> HashMap<String, String> {
    let mut map = HashMap::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            map.insert(k.trim().to_string(), v.trim().trim_matches('"').to_string());
        }
    }
    map
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_postgres_dsn_password() {
        let red = redact_connection_string("postgres://user:secret@db.example.com:5432/readonly");
        assert!(!red.contains("secret"));
        assert!(red.contains("db.example.com"));
    }
}
