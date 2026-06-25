//! Login helper for dev validation harness.

use reqwest::blocking::Client;
use serde_json::{json, Value};
use std::fs;
use std::path::Path;

pub fn login(base_url: &str, auth_env: &Path, role: &str) -> Result<String, String> {
    let password = resolve_password(auth_env, role)?;
    let username = resolve_username(auth_env, role).unwrap_or_else(|| role.to_string());
    let client = Client::builder().build().map_err(|e| e.to_string())?;
    let url = format!("{}/api/auth/login", base_url.trim_end_matches('/'));
    let resp = client
        .post(url)
        .json(&json!({"username": username, "password": password}))
        .send()
        .map_err(|e| format!("login request: {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("login HTTP {}", resp.status()));
    }
    let body: Value = resp.json().map_err(|e| e.to_string())?;
    body.get("token")
        .or_else(|| body.get("access_token"))
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| "login response missing token".into())
}

fn resolve_username(auth_env: &Path, role: &str) -> Option<String> {
    let text = fs::read_to_string(auth_env).ok()?;
    let key = format!("OFDD_{}_USER", role.to_ascii_uppercase());
    for line in text.lines() {
        if let Some(val) = line.strip_prefix(&format!("{key}=")) {
            let u = val.trim().trim_matches('"').to_string();
            if !u.is_empty() {
                return Some(u);
            }
        }
    }
    None
}

fn resolve_password(auth_env: &Path, role: &str) -> Result<String, String> {
    let env_key = format!("OPENFDD_{}_PASSWORD", role.to_ascii_uppercase());
    if let Ok(v) = std::env::var(&env_key) {
        if !v.is_empty() {
            return Ok(v);
        }
    }
    let ws = auth_env.parent().unwrap_or(Path::new("workspace"));
    let handoff = ws.join("bootstrap_credentials.once.txt");
    if handoff.exists() {
        let text = fs::read_to_string(&handoff).map_err(|e| e.to_string())?;
        for line in text.lines() {
            if let Some(rest) = line.strip_prefix(&format!("{role}:")) {
                let pw = rest.trim();
                if !pw.is_empty() && !pw.starts_with("$2b$") {
                    return Ok(pw.to_string());
                }
            }
        }
    }
    Err(format!(
        "no plaintext password for role '{role}' — set {env_key} or workspace/bootstrap_credentials.once.txt"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_password_from_env() {
        std::env::set_var("OPENFDD_INTEGRATOR_PASSWORD", "test-secret");
        let pw = resolve_password(Path::new("/nonexistent/auth.env.local"), "integrator").unwrap();
        assert_eq!(pw, "test-secret");
        std::env::remove_var("OPENFDD_INTEGRATOR_PASSWORD");
    }
}
