use axum::{routing::get, Json, Router};
use serde_json::{json, Value};

use crate::config::git_sha;
use crate::state::AppState;

/// Service index.
pub async fn root() -> Json<Value> {
    Json(json!({
        "service": "openfdd-fieldbus",
        "backend": "rusty-bacnet / rusty-modbus / rusty-haystack",
        "docs": "/docs",
        "health": "/health",
        "api_health": "/api/health",
        "bacnet_server": "/bacnet/server/objects",
        "poll_status": "/bacnet/poll/status",
        "weather": "/weather",
    }))
}

/// Liveness probe.
pub async fn health() -> Json<Value> {
    Json(json!({
        "ok": true,
        "service": "openfdd-fieldbus",
        "git_sha": git_sha(),
    }))
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/", get(root))
        .route("/health", get(health))
}
