//! Optional local Ollama — health probe and chat completions for the in-app agent panel.

use reqwest::blocking::Client;
use reqwest::StatusCode;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

const DEFAULT_MODEL: &str = "llama3.2";
const HEALTH_TIMEOUT_S: u64 = 2;
const CHAT_TIMEOUT_S: u64 = 120;

#[derive(Debug, Clone)]
pub struct OllamaConfig {
    pub base_url: String,
    pub model: String,
    pub chat_enabled: bool,
}

pub struct ChatResult {
    pub content: String,
    pub thinking: String,
    pub eval_count: Option<u64>,
    pub duration_ms: Option<u64>,
}

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn read_env_file(path: &PathBuf) -> std::collections::HashMap<String, String> {
    let mut out = std::collections::HashMap::new();
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
    let file = workspace_dir().join("ollama.env.local");
    let map = read_env_file(&file);
    map.get(key).cloned().filter(|s| !s.trim().is_empty())
}

pub fn load_config() -> OllamaConfig {
    let base_url = env_or_file("OFDD_OLLAMA_BASE_URL")
        .or_else(|| env_or_file("OPENFDD_OLLAMA_BASE_URL"))
        .unwrap_or_else(|| "http://127.0.0.1:11434".into());
    let model = env_or_file("OFDD_OLLAMA_MODEL")
        .or_else(|| env_or_file("OPENFDD_OLLAMA_MODEL"))
        .unwrap_or_else(|| DEFAULT_MODEL.into());
    let chat_enabled = env_or_file("OFDD_OLLAMA_CHAT_ENABLED")
        .or_else(|| env_or_file("OPENFDD_OLLAMA_CHAT_ENABLED"))
        .map(|v| matches!(v.as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(true);
    OllamaConfig {
        base_url: base_url.trim_end_matches('/').to_string(),
        model,
        chat_enabled,
    }
}

fn candidate_urls(cfg: &OllamaConfig) -> Vec<String> {
    let mut urls = vec![cfg.base_url.clone()];
    for u in ["http://127.0.0.1:11434", "http://ollama:11434"] {
        if !urls.iter().any(|x| x == u) {
            urls.push(u.into());
        }
    }
    urls
}

fn http_client(timeout_s: u64) -> Client {
    Client::builder()
        .timeout(Duration::from_secs(timeout_s))
        .build()
        .unwrap_or_else(|_| Client::new())
}

/// Fast check — configured base URL only (~1s max). Used before chat to avoid slow multi-URL probes.
pub fn probe_quick() -> Option<String> {
    let cfg = load_config();
    if !cfg.chat_enabled {
        return None;
    }
    let client = http_client(1);
    let url = format!("{}/api/tags", cfg.base_url);
    match client.get(&url).send() {
        Ok(resp) if resp.status() == StatusCode::OK => Some(cfg.base_url),
        _ => None,
    }
}

pub fn probe_status() -> Value {
    let cfg = load_config();
    let tried = candidate_urls(&cfg);
    let client = http_client(HEALTH_TIMEOUT_S);
    let mut active = None;
    let mut models: Vec<String> = Vec::new();
    let mut err = None;

    for url in &tried {
        let tags_url = format!("{url}/api/tags");
        match client.get(&tags_url).send() {
            Ok(resp) if resp.status() == StatusCode::OK => {
                active = Some(url.clone());
                if let Ok(body) = resp.json::<Value>() {
                    if let Some(arr) = body.get("models").and_then(|v| v.as_array()) {
                        for m in arr {
                            if let Some(name) = m.get("name").and_then(|v| v.as_str()) {
                                models.push(name.to_string());
                            }
                        }
                    }
                }
                break;
            }
            Ok(resp) => {
                err = Some(format!("{url} returned {}", resp.status()));
            }
            Err(e) => {
                err = Some(format!("{url}: {e}"));
            }
        }
    }

    let api_ok = active.is_some();
    let interactive = cfg.chat_enabled && api_ok;

    json!({
        "api_ok": api_ok,
        "base_url": cfg.base_url,
        "active_base_url": active,
        "tried_urls": tried,
        "configured_model": cfg.model,
        "models_installed": models,
        "interactive_chat_enabled": interactive,
        "health_timeout_s": HEALTH_TIMEOUT_S,
        "chat_timeout_s": CHAT_TIMEOUT_S,
        "error": if api_ok { Value::Null } else { json!(err.unwrap_or_else(|| "Ollama unreachable".into())) }
    })
}

pub fn chat(messages: &[Value], model: Option<&str>) -> Result<ChatResult, String> {
    let status = probe_status();
    let base = status
        .get("active_base_url")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "Ollama not reachable".to_string())?;
    chat_at(base, messages, model)
}

pub fn chat_at(base: &str, messages: &[Value], model: Option<&str>) -> Result<ChatResult, String> {
    let cfg = load_config();
    if !cfg.chat_enabled {
        return Err("Ollama chat disabled (set OFDD_OLLAMA_CHAT_ENABLED=1)".into());
    }
    let model_name = model.unwrap_or(&cfg.model);
    let client = http_client(CHAT_TIMEOUT_S);
    let body = json!({
        "model": model_name,
        "messages": messages,
        "stream": false
    });
    let resp = client
        .post(format!("{}/api/chat", base.trim_end_matches('/')))
        .json(&body)
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("Ollama chat HTTP {}", resp.status()));
    }
    let parsed: Value = resp.json().map_err(|e| e.to_string())?;
    let content = parsed
        .pointer("/message/content")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let thinking = parsed
        .pointer("/message/thinking")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let eval_count = parsed.get("eval_count").and_then(|v| v.as_u64());
    let duration_ms = parsed
        .get("eval_duration")
        .and_then(|v| v.as_u64())
        .map(|ns| ns / 1_000_000);
    Ok(ChatResult {
        content,
        thinking,
        eval_count,
        duration_ms,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn load_config_defaults() {
        let cfg = load_config();
        assert!(!cfg.base_url.is_empty());
        assert!(!cfg.model.is_empty());
    }

    #[test]
    fn probe_status_shape() {
        let body = probe_status();
        assert!(body.get("api_ok").is_some());
        assert!(body.get("configured_model").is_some());
    }
}
