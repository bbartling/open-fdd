//! Read-only MQTT observation API for the H9 operator monitor.

use std::sync::Arc;

use axum::extract::State;
use axum::middleware;
use axum::routing::get;
use axum::{Json, Router};

use crate::auth;
use crate::state::{AppState, MqttMonitorSnapshot};

pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/api/mqtt/monitor", get(snapshot))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ))
        .with_state(state)
}

async fn snapshot(State(state): State<Arc<AppState>>) -> Json<MqttMonitorSnapshot> {
    Json(state.mqtt_monitor_snapshot())
}
