//! HTTP bridge to local Codex CLI relay (`tools/codex-chat-relay`).

use reqwest::blocking::Client;
use reqwest::StatusCode;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

const DEFAULT_URL: &str = "http://127.0.0.1:8788";
const TIMEOUT_S: u64 = 620;

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn read_env_file(path: &PathBuf) -> HashMap<String, String> {
    let mut out = HashMap::new();
    let Ok(text) = fs::read_to_string(path) else {
        return out;
    };
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let Some((k, v)) = line.split_once('=') else {
            continue;
        };
        out.insert(k.trim().to_string(), v.trim().trim_matches('"').to_string());
    }
    out
}

fn env_or_file(key: &str) -> Option<String> {
    if let Ok(v) = env::var(key) {
        if !v.trim().is_empty() {
            return Some(v);
        }
    }
    let file = workspace_dir().join("codex.env.local");
    read_env_file(&file)
        .get(key)
        .cloned()
        .filter(|s| !s.trim().is_empty())
}

pub fn base_url() -> String {
    env_or_file("OFDD_CODEX_CHAT_URL")
        .unwrap_or_else(|| DEFAULT_URL.into())
        .trim_end_matches('/')
        .to_string()
}

fn client() -> Client {
    Client::builder()
        .timeout(Duration::from_secs(TIMEOUT_S))
        .build()
        .unwrap_or_else(|_| Client::new())
}

pub fn probe_quick() -> Option<String> {
    let url = base_url();
    let resp = client()
        .get(format!("{url}/health"))
        .send()
        .ok()?;
    if resp.status() != StatusCode::OK {
        return None;
    }
    let body: Value = resp.json().ok()?;
    if body.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return None;
    }
    if body.get("codex_logged_in").and_then(|v| v.as_bool()) == Some(false) {
        // Codex may be logged in even when doctor text does not match — still try relay.
    }
    Some(url)
}

pub fn status_json() -> Value {
    let url = base_url();
    match client().get(format!("{url}/health")).send() {
        Ok(resp) if resp.status() == StatusCode::OK => {
            let mut body: Value = resp.json().unwrap_or(json!({}));
            if let Some(obj) = body.as_object_mut() {
                obj.insert("base_url".into(), json!(url));
            }
            body
        }
        Ok(resp) => json!({
            "ok": false,
            "base_url": url,
            "error": format!("HTTP {}", resp.status())
        }),
        Err(err) => json!({
            "ok": false,
            "base_url": url,
            "error": err.to_string(),
            "hint": "Run ./scripts/openfdd_codex_chat_relay.sh after codex login"
        }),
    }
}

pub fn chat(body: &Value) -> Result<Value, String> {
    let base = probe_quick().ok_or_else(|| {
        format!(
            "Codex relay unreachable at {} — run ./scripts/openfdd_codex_chat_relay.sh",
            base_url()
        )
    })?;
    let resp = client()
        .post(format!("{base}/chat"))
        .json(body)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let parsed: Value = resp.json().map_err(|e| e.to_string())?;
    if !status.is_success() {
        let err = parsed
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("codex relay error");
        return Err(err.to_string());
    }
    Ok(parsed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_url_default() {
        assert!(!base_url().is_empty());
    }
}
