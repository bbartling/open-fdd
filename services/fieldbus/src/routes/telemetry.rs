//! Per-edge telemetry suspend / resume (poll + weather + MQTT publish gate; BACnet server kept).

use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

use crate::state::AppState;

#[derive(Debug, Deserialize)]
struct TelemetryActionBody {
    #[serde(default)]
    approved_by: Option<String>,
}

async fn get_status(State(state): State<AppState>) -> Json<Value> {
    Json(state.telemetry.status().await)
}

async fn suspend(
    State(state): State<AppState>,
    Json(body): Json<TelemetryActionBody>,
) -> Json<Value> {
    let by = body
        .approved_by
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "fieldbus-api".into());
    match state.telemetry.suspend(&by).await {
        Ok(status) => Json(status),
        Err(err) => Json(json!({ "ok": false, "error": err })),
    }
}

async fn resume(
    State(state): State<AppState>,
    Json(body): Json<TelemetryActionBody>,
) -> Json<Value> {
    let by = body
        .approved_by
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "fieldbus-api".into());
    match state.telemetry.resume(&by).await {
        Ok(status) => Json(status),
        Err(err) => Json(json!({ "ok": false, "error": err })),
    }
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/telemetry/status", get(get_status))
        .route("/telemetry/suspend", post(suspend))
        .route("/telemetry/resume", post(resume))
}
