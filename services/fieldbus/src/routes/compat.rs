use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};

use crate::config::git_sha;
use crate::error::{validate, ApiError, ApiResult};
use crate::models::DeviceInstanceRequest;
use crate::state::AppState;

async fn api_health(State(state): State<AppState>) -> Json<Value> {
    let poll = state.poll_engine.status().await;
    Json(json!({
        "ok": true,
        "service": "openfdd-fieldbus",
        "version": env!("CARGO_PKG_VERSION"),
        "git_sha": git_sha(),
        "poll_running": poll["running"].as_bool().unwrap_or(false),
        "bacnet_server_instance": state.settings.bacnet_server.device_instance,
    }))
}

async fn api_point_discovery(
    State(state): State<AppState>,
    Json(body): Json<DeviceInstanceRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .bacnet_client
        .point_discovery(body.device_instance)
        .await
        .map_err(ApiError::Bacnet)?;
    Ok(Json(merge_discovery_ok(result)))
}

fn merge_discovery_ok(result: Value) -> Value {
    let mut v = json!({ "ok": true });
    if let Some(obj) = v.as_object_mut() {
        if let Some(r) = result.as_object() {
            for (k, val) in r {
                obj.insert(k.clone(), val.clone());
            }
        }
    }
    v
}

async fn api_server_points(State(state): State<AppState>) -> ApiResult<Json<Value>> {
    let objects = state
        .bacnet_server
        .list_objects()
        .await
        .map_err(ApiError::BadRequest)?;
    Ok(Json(json!({ "ok": true, "objects": objects })))
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/health", get(api_health))
        .route("/api/bacnet/point-discovery", post(api_point_discovery))
        .route("/api/bacnet/server/points", get(api_server_points))
}
