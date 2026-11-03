//! Operator schedule overrides for static UI cards (model sync + history cadence).

use std::sync::Arc;

use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use serde::Deserialize;
use serde_json::json;

use crate::auth::{self, AuthUser};
use crate::contract::{self, json_error};
use crate::ingest_queue::schedule::IngestSchedule;
use crate::operator_schedule::OperatorSiteScheduleEntry;
use crate::state::AppState;
use crate::tenant::TenantContext;

#[derive(Debug, Deserialize)]
struct SiteQuery {
    building_id: String,
}

#[derive(Debug, Deserialize)]
struct ModelSyncPatch {
    building_id: String,
    poll_secs: u64,
}

#[derive(Debug, Deserialize)]
struct HistorySchedulePatch {
    building_id: String,
    schedule_mode: String,
    #[serde(default)]
    schedule_timezone: Option<String>,
}

pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/api/schedules/status", get(schedules_status))
        .route("/api/schedules/model-sync", post(update_model_sync))
        .route("/api/schedules/history", post(update_history_schedule))
        .layer(axum::middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ))
        .with_state(state)
}

async fn schedules_status(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    Query(query): Query<SiteQuery>,
) -> Response {
    let request_id = contract::ensure_request_id(&axum::http::HeaderMap::new());
    let building_id = query.building_id.trim();
    if building_id.is_empty() {
        return json_error(
            StatusCode::BAD_REQUEST,
            "invalid_request",
            "building_id is required",
            &request_id,
            false,
        );
    }
    let ctx = tenant_ctx(&state, &user).await;
    if !ctx.allow_building(building_id) {
        return json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "site not found",
            &request_id,
            false,
        );
    }
    let provider_site = state
        .providers
        .sites
        .iter()
        .find(|site| site.building_id == building_id);
    let Some(provider_site) = provider_site else {
        return Json(json!({
            "ok": true,
            "request_id": request_id,
            "building_id": building_id,
            "provider_configured": false,
            "editable": user.role.can_issue_commands(),
        }))
        .into_response();
    };
    let health = state.providers.health_snapshot().await;
    let health_row = health
        .sites
        .iter()
        .find(|row| row.building_id == building_id);
    let poll_secs = state.providers.effective_poll_secs(building_id);
    let schedule = state
        .providers
        .effective_ingest_schedule(&provider_site.tenant_id, building_id);
    let (history_mode, history_tz) = match schedule {
        IngestSchedule::Periodic => ("periodic", None),
        IngestSchedule::Daily { tz } => ("daily", Some(tz.name())),
    };
    Json(json!({
        "ok": true,
        "request_id": request_id,
        "building_id": building_id,
        "provider_configured": true,
        "editable": user.role.can_issue_commands(),
        "model_sync": {
            "poll_secs": poll_secs,
            "last_run": health_row.and_then(|row| row.last_poll_at),
            "last_error": health_row.and_then(|row| row.health.message.clone()),
            "ingested_points": health_row.map(|row| row.last_ingested_points),
        },
        "history": {
            "schedule_mode": history_mode,
            "schedule_timezone": history_tz,
        },
    }))
    .into_response()
}

async fn update_model_sync(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    Json(body): Json<ModelSyncPatch>,
) -> Response {
    let request_id = contract::ensure_request_id(&axum::http::HeaderMap::new());
    if !user.role.can_issue_commands() {
        return json_error(
            StatusCode::FORBIDDEN,
            "forbidden",
            "operator role required",
            &request_id,
            false,
        );
    }
    let building_id = body.building_id.trim();
    if building_id.is_empty() {
        return json_error(
            StatusCode::BAD_REQUEST,
            "invalid_request",
            "building_id is required",
            &request_id,
            false,
        );
    }
    let ctx = tenant_ctx(&state, &user).await;
    if !ctx.allow_building(building_id) {
        return json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "site not found",
            &request_id,
            false,
        );
    }
    match state.providers.update_operator_site_schedule(
        building_id,
        OperatorSiteScheduleEntry {
            poll_secs: Some(body.poll_secs),
            ..OperatorSiteScheduleEntry::default()
        },
    ) {
        Ok(entry) => Json(json!({
            "ok": true,
            "request_id": request_id,
            "building_id": building_id,
            "poll_secs": entry.poll_secs.unwrap_or(body.poll_secs),
        }))
        .into_response(),
        Err(error) => json_error(
            StatusCode::BAD_REQUEST,
            "invalid_request",
            &error,
            &request_id,
            false,
        ),
    }
}

async fn update_history_schedule(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    Json(body): Json<HistorySchedulePatch>,
) -> Response {
    let request_id = contract::ensure_request_id(&axum::http::HeaderMap::new());
    if !user.role.can_issue_commands() {
        return json_error(
            StatusCode::FORBIDDEN,
            "forbidden",
            "operator role required",
            &request_id,
            false,
        );
    }
    let building_id = body.building_id.trim();
    if building_id.is_empty() {
        return json_error(
            StatusCode::BAD_REQUEST,
            "invalid_request",
            "building_id is required",
            &request_id,
            false,
        );
    }
    let ctx = tenant_ctx(&state, &user).await;
    if !ctx.allow_building(building_id) {
        return json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "site not found",
            &request_id,
            false,
        );
    }
    match state.providers.update_operator_site_schedule(
        building_id,
        OperatorSiteScheduleEntry {
            schedule_mode: Some(body.schedule_mode),
            schedule_timezone: body.schedule_timezone,
            ..OperatorSiteScheduleEntry::default()
        },
    ) {
        Ok(entry) => Json(json!({
            "ok": true,
            "request_id": request_id,
            "building_id": building_id,
            "schedule_mode": entry.schedule_mode,
            "schedule_timezone": entry.schedule_timezone,
        }))
        .into_response(),
        Err(error) => json_error(
            StatusCode::BAD_REQUEST,
            "invalid_request",
            &error,
            &request_id,
            false,
        ),
    }
}

async fn tenant_ctx(state: &AppState, user: &AuthUser) -> TenantContext {
    TenantContext::resolve_fail_closed(user, &state.control_plane.read().await.clone())
}
