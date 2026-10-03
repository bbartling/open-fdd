//! Authenticated typed Haystack routes for the compatibility process.

use axum::{extract::State, routing::post, Json, Router};
use openfdd_contracts::{
    HaystackAboutRequest, HaystackCatalogRequest, HaystackCurrentReadRequest,
    HaystackHistoryReadRequest, HaystackNavRequest,
};

use crate::error::{ApiError, ApiResult};
use crate::services::haystack::HaystackService;
use crate::state::AppState;

fn service(state: &AppState) -> ApiResult<std::sync::Arc<HaystackService>> {
    state
        .haystack
        .clone()
        .ok_or_else(|| ApiError::NotFound("Haystack connector is not active".into()))
}

fn check_scope(state: &AppState, scope: &openfdd_contracts::ConnectorScope) -> ApiResult<()> {
    scope.validate().map_err(ApiError::BadRequest)?;
    let matches = [
        (
            state.settings.connector_tenant_id.as_deref(),
            scope.tenant_id.as_str(),
        ),
        (
            state.settings.connector_building_id.as_deref(),
            scope.building_id.as_str(),
        ),
        (
            state.settings.connector_edge_id.as_deref(),
            scope.edge_id.as_str(),
        ),
    ]
    .into_iter()
    .all(|(expected, actual)| expected.is_some_and(|value| value == actual));
    if matches {
        Ok(())
    } else {
        Err(ApiError::Forbidden(
            "Haystack scope is outside this connector".into(),
        ))
    }
}

async fn catalog(
    State(state): State<AppState>,
    Json(request): Json<HaystackCatalogRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackCatalogResponse>> {
    check_scope(&state, &request.scope)?;
    Ok(Json(
        service(&state)?
            .catalog_page(&request)
            .map_err(ApiError::BadRequest)?,
    ))
}

async fn about(
    State(state): State<AppState>,
    Json(request): Json<HaystackAboutRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackAboutResponse>> {
    check_scope(&state, &request.scope)?;
    Ok(Json(
        service(&state)?
            .about_typed(&request)
            .await
            .map_err(ApiError::Upstream)?,
    ))
}

async fn current_read(
    State(state): State<AppState>,
    Json(request): Json<HaystackCurrentReadRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackCurrentReadResponse>> {
    check_scope(&state, &request.scope)?;
    Ok(Json(
        service(&state)?
            .current_read_typed(&request)
            .await
            .map_err(|error| {
                if error.contains("trusted catalog") || error.contains("public key") {
                    ApiError::Forbidden(error)
                } else {
                    ApiError::Upstream(error)
                }
            })?,
    ))
}

async fn navigation(
    State(state): State<AppState>,
    Json(request): Json<HaystackNavRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackNavResponse>> {
    check_scope(&state, &request.scope)?;
    Ok(Json(
        service(&state)?
            .nav_typed(&request)
            .await
            .map_err(ApiError::Upstream)?,
    ))
}

async fn history_read(
    State(state): State<AppState>,
    Json(request): Json<HaystackHistoryReadRequest>,
) -> ApiResult<Json<openfdd_contracts::HaystackHistoryReadResponse>> {
    check_scope(&state, &request.scope)?;
    Ok(Json(
        service(&state)?
            .history_read_typed(&request)
            .await
            .map_err(|error| {
                if error.contains("trusted catalog") || error.contains("public key") {
                    ApiError::Forbidden(error)
                } else {
                    ApiError::Upstream(error)
                }
            })?,
    ))
}

/// The compatibility process keeps the legacy path names, but their payloads
/// are the same typed requests as the split process. No raw Haystack filter,
/// URL, ref, auth field, or navigation path is accepted.
pub fn router() -> Router<AppState> {
    Router::new()
        .route("/haystack/catalog", post(catalog))
        .route("/haystack/about", post(about))
        .route("/haystack/read", post(current_read))
        .route("/haystack/nav", post(navigation))
        .route("/haystack/his-read", post(history_read))
}
