//! Generic REST/JSON driver routes (#540). Devices and write bindings are
//! referenced by catalog name only — no free-form URLs cross this API.

use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde_json::Value;

use crate::error::{validate, ApiError, ApiResult};
use crate::models::{RestGetRequest, RestReadRequest, RestWriteRequest};
use crate::services::rest::RestError;
use crate::state::AppState;

fn map_err(e: RestError) -> ApiError {
    match e {
        RestError::BadRequest(m) => ApiError::BadRequest(m),
        RestError::Forbidden(m) => ApiError::Forbidden(m),
        RestError::NotFound(m) => ApiError::NotFound(m),
        RestError::Upstream(m) => ApiError::Upstream(m),
    }
}

async fn rest_devices(State(state): State<AppState>) -> ApiResult<Json<Value>> {
    Ok(Json(state.rest.list_devices().await))
}

async fn rest_read(
    State(state): State<AppState>,
    Json(body): Json<RestReadRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .rest
        .read_point(&body.device, &body.point)
        .await
        .map_err(map_err)?;
    Ok(Json(result))
}

async fn rest_get(
    State(state): State<AppState>,
    Json(body): Json<RestGetRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .rest
        .raw_get(&body.device, &body.path)
        .await
        .map_err(map_err)?;
    Ok(Json(result))
}

async fn rest_write(
    State(state): State<AppState>,
    Json(body): Json<RestWriteRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .rest
        .write(&body.device, &body.name, body.value)
        .await
        .map_err(map_err)?;
    Ok(Json(result))
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/rest/devices", get(rest_devices))
        .route("/rest/read", post(rest_read))
        .route("/rest/get", post(rest_get))
        .route("/rest/write", post(rest_write))
}
