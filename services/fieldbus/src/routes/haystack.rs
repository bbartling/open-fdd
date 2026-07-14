use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde_json::{json, Value};

use crate::error::{validate, ApiError, ApiResult};
use crate::models::*;
use crate::services::haystack::grid_to_json;
use crate::state::AppState;

async fn haystack_about(State(state): State<AppState>) -> ApiResult<Json<Value>> {
    let grid = state.haystack.about().await.map_err(ApiError::Upstream)?;
    Ok(Json(json!({ "ok": true, "about": grid_to_json(&grid) })))
}

async fn haystack_read(
    State(state): State<AppState>,
    Json(body): Json<HaystackReadRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let grid = state.haystack.read(&body.filter).await.map_err(|e| {
        if e.contains("not allowlisted") {
            ApiError::Forbidden(e)
        } else {
            ApiError::Upstream(e)
        }
    })?;
    Ok(Json(json!({ "ok": true, "grid": grid_to_json(&grid) })))
}

async fn haystack_nav(
    State(state): State<AppState>,
    Json(body): Json<HaystackNavRequest>,
) -> ApiResult<Json<Value>> {
    let grid = state
        .haystack
        .nav(body.nav_id.as_deref())
        .await
        .map_err(ApiError::Upstream)?;
    Ok(Json(json!({ "ok": true, "grid": grid_to_json(&grid) })))
}

async fn haystack_his_read(
    State(state): State<AppState>,
    Json(body): Json<HaystackHisReadRequest>,
) -> ApiResult<Json<Value>> {
    validate(&body)?;
    let result = state
        .haystack
        .his_read(
            &body.ids,
            body.range_start.as_deref(),
            body.range_end.as_deref(),
        )
        .await
        .map_err(ApiError::Upstream)?;
    let mapped: std::collections::HashMap<_, _> = result
        .iter()
        .map(|(k, g)| (k.clone(), grid_to_json(g)))
        .collect();
    Ok(Json(json!({ "ok": true, "result": mapped })))
}

pub fn router() -> Router<AppState> {
    Router::new()
        .route("/haystack/about", get(haystack_about))
        .route("/haystack/read", post(haystack_read))
        .route("/haystack/nav", post(haystack_nav))
        .route("/haystack/his-read", post(haystack_his_read))
}
