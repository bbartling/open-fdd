//! Host-side Open-FDD login helpers for MCP agents (never log passwords).

use reqwest::blocking::Client;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub fn credentials_hint() -> Value {
    let workspace = workspace_dir();
    let auth_file = workspace.join("auth.env.local");
    let handoff = workspace.join("bootstrap_credentials.once.txt");
    json!({
        "ok": true,
        "workspace": workspace.display().to_string(),
        "auth_env_local": auth_file.display().to_string(),
        "bootstrap_credentials_once": handoff.display().to_string(),
        "bootstrap_handoff_exists": handoff.is_file(),
        "auth_env_exists": auth_file.is_file(),
        "roles": {
            "integrator": "MCP JWT + dashboard admin — preferred for OPENFDD_MCP_TOKEN",
            "agent": "AI write tools (assignments, CSV execute, reports)",
            "operator": "Dashboard operator",
            "admin": "Full admin"
        },
        "password_resolution_order": [
            "OPENFDD_<ROLE>_PASSWORD env var",
            "workspace/bootstrap_credentials.once.txt (role: password lines)",
            "OFDD_<ROLE>_PASSWORD= in auth.env.local (plaintext lab only — hashes are NOT passwords)"
        ],
        "login": {
            "endpoint": "POST /api/auth/login",
            "body": {"username": "<role>", "password": "<from handoff or env>"},
            "token_fields": ["token", "access_token"]
        },
        "shell_helper": "scripts/openfdd_auth_lib.sh → openfdd_auth_login_token",
        "mcp_tool": "openfdd_auth_login — returns JWT without echoing password",
        "never": "Do not commit bootstrap_credentials.once.txt or paste bcrypt hashes as passwords"
    })
}

pub fn login_role(role: &str, base: &str) -> Result<Value, String> {
    let role = role.trim().to_ascii_lowercase();
    if !matches!(role.as_str(), "integrator" | "agent" | "operator" | "admin") {
        return Err(format!("unsupported role: {role}"));
    }
    let auth_file = workspace_dir().join("auth.env.local");
    let username = read_env_username(&auth_file, &role).unwrap_or(role.clone());
    let password = resolve_plaintext_password(&auth_file, &role)?;
    let client = Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|e| e.to_string())?;
    let url = format!("{}/api/auth/login", base.trim_end_matches('/'));
    let resp = client
        .post(&url)
        .json(&json!({"username": username, "password": password}))
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let body: Value = resp.json().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(body
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("login failed")
            .to_string());
    }
    let token = body
        .get("token")
        .or_else(|| body.get("access_token"))
        .and_then(|v| v.as_str())
        .ok_or("login response missing token")?;
    Ok(json!({
        "ok": true,
        "role": role,
        "username": username,
        "token": token,
        "expires_hint": "JWT session — set OPENFDD_MCP_TOKEN for MCP sidecar",
        "password_source": password_source_label(&auth_file, &role)
    }))
}

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn read_env_username(auth_file: &Path, role: &str) -> Option<String> {
    let key = format!("OFDD_{}_USER", role.to_ascii_uppercase());
    read_env_line(auth_file, &key)
}

fn resolve_plaintext_password(auth_file: &Path, role: &str) -> Result<String, String> {
    let role_upper = role.to_ascii_uppercase();
    if let Ok(pw) = env::var(format!("OPENFDD_{role_upper}_PASSWORD")) {
        if !pw.is_empty() && !pw.starts_with("$2b$") {
            return Ok(pw);
        }
    }
    let handoff = auth_file
        .parent()
        .unwrap_or_else(|| Path::new("workspace"))
        .join("bootstrap_credentials.once.txt");
    if handoff.is_file() {
        if let Ok(text) = fs::read_to_string(&handoff) {
            for line in text.lines() {
                if line.starts_with('#') || !line.contains(':') {
                    continue;
                }
                let (k, v) = line.split_once(':').unwrap_or(("", ""));
                if k.trim().eq_ignore_ascii_case(role) {
                    let pw = v.trim().to_string();
                    if !pw.is_empty() && !pw.starts_with("$2b$") {
                        return Ok(pw);
                    }
                }
            }
        }
    }
    let plain_key = format!("OFDD_{role_upper}_PASSWORD");
    if let Some(pw) = read_env_line(auth_file, &plain_key) {
        if !pw.starts_with("$2b$") {
            return Ok(pw);
        }
    }
    Err(format!(
        "no plaintext password for role '{role}'. See workspace/bootstrap_credentials.once.txt or run ./scripts/openfdd_auth_init.sh --rotate --all --show-secrets"
    ))
}

fn password_source_label(auth_file: &Path, role: &str) -> &'static str {
    let role_upper = role.to_ascii_uppercase();
    if env::var(format!("OPENFDD_{role_upper}_PASSWORD")).is_ok() {
        return "OPENFDD_*_PASSWORD env";
    }
    let handoff = auth_file
        .parent()
        .unwrap_or_else(|| Path::new("workspace"))
        .join("bootstrap_credentials.once.txt");
    if handoff.is_file() {
        return "bootstrap_credentials.once.txt";
    }
    "auth.env.local plaintext"
}

fn read_env_line(path: &Path, key: &str) -> Option<String> {
    let text = fs::read_to_string(path).ok()?;
    for line in text.lines() {
        if let Some(rest) = line.strip_prefix(&format!("{key}=")) {
            let v = rest.trim().trim_matches('"').to_string();
            if !v.is_empty() {
                return Some(v);
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hint_never_includes_passwords() {
        let h = credentials_hint();
        let s = h.to_string();
        assert!(!s.contains("integrator:"));
        assert!(!s.contains("$2b$"));
        assert!(h.get("bootstrap_handoff_exists").is_some());
    }
}
