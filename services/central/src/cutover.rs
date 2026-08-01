//! UI generation cutover control plane (P2-M0-01).
//!
//! Default remains Streamlit. React is opt-in via cookie/header/env — never a
//! silent production default flip in this module.

use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::response::IntoResponse;
use axum::{Json, Router};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

pub const COOKIE_NAME: &str = "openfdd_ui_generation";
pub const HEADER_NAME: &str = "x-openfdd-ui-generation";
pub const ENV_DEFAULT: &str = "OPENFDD_UI_GENERATION_DEFAULT";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum UiGeneration {
    Streamlit,
    React,
}

impl UiGeneration {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Streamlit => "streamlit",
            Self::React => "react",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "streamlit" | "st" => Some(Self::Streamlit),
            "react" | "spa" => Some(Self::React),
            _ => None,
        }
    }
}

/// Safe default when config is absent/invalid: Streamlit.
pub fn default_generation() -> UiGeneration {
    match std::env::var(ENV_DEFAULT) {
        Ok(v) => UiGeneration::parse(&v).unwrap_or(UiGeneration::Streamlit),
        Err(_) => UiGeneration::Streamlit,
    }
}

pub fn resolve_generation(headers: &HeaderMap) -> (UiGeneration, &'static str) {
    if let Some(v) = headers.get(HEADER_NAME).and_then(|h| h.to_str().ok()) {
        if let Some(g) = UiGeneration::parse(v) {
            return (g, "header");
        }
    }
    if let Some(cookie) = headers.get(header::COOKIE).and_then(|h| h.to_str().ok()) {
        for part in cookie.split(';') {
            let part = part.trim();
            if let Some(rest) = part.strip_prefix(&format!("{COOKIE_NAME}=")) {
                if let Some(g) = UiGeneration::parse(rest) {
                    return (g, "cookie");
                }
            }
        }
    }
    (default_generation(), "default")
}

fn audit_path() -> PathBuf {
    let root = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    PathBuf::from(root).join(".cache").join("cutover_audit.jsonl")
}

pub fn append_audit(entry: &Value) -> Result<(), String> {
    let path = audit_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let mut f = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    writeln!(f, "{entry}").map_err(|e| e.to_string())?;
    Ok(())
}

#[derive(Debug, Serialize)]
pub struct GenerationStatus {
    pub ok: bool,
    pub generation: UiGeneration,
    pub source: String,
    pub default_generation: UiGeneration,
    pub production_default_flipped: bool,
    pub sticky_cookie: String,
}

#[derive(Debug, Deserialize)]
pub struct SetGenerationBody {
    pub generation: String,
    #[serde(default)]
    pub reason: Option<String>,
}

pub fn router() -> Router {
    Router::new().route(
        "/api/ui/generation",
        axum::routing::get(get_generation).put(put_generation),
    )
}

async fn get_generation(headers: HeaderMap) -> Json<GenerationStatus> {
    let (generation, source) = resolve_generation(&headers);
    Json(GenerationStatus {
        ok: true,
        generation,
        source: source.into(),
        default_generation: default_generation(),
        // P2-M0-01 never flips the production default.
        production_default_flipped: false,
        sticky_cookie: COOKIE_NAME.into(),
    })
}

async fn put_generation(
    headers: HeaderMap,
    Json(body): Json<SetGenerationBody>,
) -> Result<impl IntoResponse, (StatusCode, Json<Value>)> {
    let Some(generation) = UiGeneration::parse(&body.generation) else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "generation must be streamlit|react"
            })),
        ));
    };
    let (prev, prev_source) = resolve_generation(&headers);
    let entry = json!({
        "ts": Utc::now().to_rfc3339(),
        "event": "ui_generation_set",
        "from": prev.as_str(),
        "from_source": prev_source,
        "to": generation.as_str(),
        "reason": body.reason,
        "production_default_flipped": false,
    });
    if let Err(e) = append_audit(&entry) {
        tracing::warn!(error = %e, "cutover audit write failed");
    }

    let cookie = format!(
        "{COOKIE_NAME}={}; Path=/; Max-Age=31536000; SameSite=Lax",
        generation.as_str()
    );
    let mut response = Json(json!({
        "ok": true,
        "generation": generation.as_str(),
        "source": "cookie",
        "audit": entry,
        "production_default_flipped": false,
    }))
    .into_response();
    if let Ok(val) = HeaderValue::from_str(&cookie) {
        response.headers_mut().append(header::SET_COOKIE, val);
    }
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    #[test]
    fn invalid_env_defaults_to_streamlit() {
        std::env::set_var(ENV_DEFAULT, "bogus");
        assert_eq!(default_generation(), UiGeneration::Streamlit);
        std::env::remove_var(ENV_DEFAULT);
    }

    #[test]
    fn header_beats_cookie() {
        let mut headers = HeaderMap::new();
        headers.insert(
            HEADER_NAME,
            HeaderValue::from_static("react"),
        );
        headers.insert(
            header::COOKIE,
            HeaderValue::from_static("openfdd_ui_generation=streamlit"),
        );
        let (g, src) = resolve_generation(&headers);
        assert_eq!(g, UiGeneration::React);
        assert_eq!(src, "header");
    }

    #[test]
    fn cookie_used_when_no_header() {
        let mut headers = HeaderMap::new();
        headers.insert(
            header::COOKIE,
            HeaderValue::from_static("openfdd_ui_generation=react; other=1"),
        );
        let (g, src) = resolve_generation(&headers);
        assert_eq!(g, UiGeneration::React);
        assert_eq!(src, "cookie");
    }
}
