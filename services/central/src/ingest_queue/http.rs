//! Scoped ingest queue HTTP. Tenant filtering happens before rows are returned.

use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Extension;
use axum::Json;
use chrono::{DateTime, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::auth::{AuthUser, Role};
use crate::contract::{self, json_error};
use crate::providers::config::SiteConfig;
use crate::providers::http_policy::provider_ids_equivalent;
use crate::state::AppState;
use crate::tenant::TenantContext;

use super::client::QueueClient;
use super::model::*;
use super::scale::{self, ScalePolicy, ScaleSample};

#[derive(Debug, Deserialize)]
pub struct ListQuery {
    pub site_id: Option<String>,
    pub state: Option<String>,
    pub limit: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct RetryBody {
    pub idempotency_key: String,
}

#[derive(Debug, Deserialize)]
pub struct WindowBody {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

#[derive(Debug, Deserialize)]
pub struct BackfillBody {
    pub idempotency_key: String,
    pub tenant_id: Option<String>,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: Option<String>,
    pub windows: Vec<WindowBody>,
}

pub async fn list_jobs(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Query(query): Query<ListQuery>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    let Some(filter) = scoped_filter(&ctx, &query, &request_id) else {
        return empty_list(&request_id, &ctx);
    };
    match state.ingest_queue.list_jobs(&filter).await {
        Ok(jobs) => Json(json!({
            "ok": true,
            "request_id": request_id,
            "scope": scope_json(&ctx),
            "coverage": rollup_coverage(jobs.iter().map(|job| job.coverage.as_str())),
            "jobs": jobs,
        }))
        .into_response(),
        Err(err) => queue_err(&err, &request_id),
    }
}

pub async fn get_job(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Path(job_id): Path<Uuid>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    match state.ingest_queue.get_job(job_id).await {
        Ok(Some(job)) if job_in_scope(&ctx, &job) => Json(json!({
            "ok": true,
            "request_id": request_id,
            "scope": scope_json(&ctx),
            "job": job,
        }))
        .into_response(),
        Ok(_) => json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "job not found",
            &request_id,
            false,
        ),
        Err(err) => queue_err(&err, &request_id),
    }
}

pub async fn list_receipts(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Query(query): Query<ListQuery>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    let Some(filter) = scoped_filter(&ctx, &query, &request_id) else {
        return empty_named(&request_id, &ctx, "receipts");
    };
    match state.ingest_queue.list_receipts(&filter).await {
        Ok(receipts) => Json(json!({
            "ok": true,
            "request_id": request_id,
            "scope": scope_json(&ctx),
            "receipts": receipts,
        }))
        .into_response(),
        Err(err) => queue_err(&err, &request_id),
    }
}

pub async fn get_receipt(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Path(receipt_id): Path<Uuid>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    match state.ingest_queue.get_receipt(receipt_id).await {
        Ok(Some(receipt)) if receipt_in_scope(&ctx, &receipt) => Json(json!({
            "ok": true,
            "request_id": request_id,
            "scope": scope_json(&ctx),
            "receipt": receipt,
        }))
        .into_response(),
        Ok(_) => json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "receipt not found",
            &request_id,
            false,
        ),
        Err(err) => queue_err(&err, &request_id),
    }
}

pub async fn list_gaps(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Query(query): Query<ListQuery>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    let Some(filter) = scoped_filter(&ctx, &query, &request_id) else {
        return empty_named(&request_id, &ctx, "gaps");
    };
    match state.ingest_queue.list_gaps(&filter).await {
        Ok(gaps) => {
            let coverage = if gaps.is_empty() {
                COVERAGE_NOT_ASSESSED
            } else {
                rollup_coverage(gaps.iter().map(|job| job.coverage.as_str()))
            };
            let rows: Vec<Value> = gaps
                .into_iter()
                .map(|job| {
                    let recoverable = gap_recoverable(job.safe_error_code.as_deref());
                    json!({
                        "job": job,
                        "recoverable": recoverable,
                    })
                })
                .collect();
            Json(json!({
                "ok": true,
                "request_id": request_id,
                "scope": scope_json(&ctx),
                "guarantee": "bounded_windows_only",
                "update_log": "not_claimed",
                "coverage": coverage,
                "gaps": rows,
            }))
            .into_response()
        }
        Err(err) => queue_err(&err, &request_id),
    }
}

#[derive(Debug, Deserialize)]
pub struct StatusQuery {
    pub site_id: String,
}

/// Schedule and verified-coverage status for one site, per provider.
pub async fn coverage_status(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Query(query): Query<StatusQuery>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    let site = query.site_id.trim();
    let not_found = || {
        json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "site not found",
            &request_id,
            false,
        )
    };
    if site.is_empty() || !ctx.allow_building(site) {
        return not_found();
    }
    let scoped_tenant = if ctx.multi_tenant && !ctx.hub_admin {
        match ctx.tenant_id.clone() {
            Some(tenant_id) => Some(tenant_id),
            None => return not_found(),
        }
    } else {
        None
    };
    let configs: Vec<&SiteConfig> = state
        .providers
        .sites
        .iter()
        .filter(|row| {
            row.building_id == site
                && scoped_tenant
                    .as_deref()
                    .is_none_or(|tenant_id| row.tenant_id == tenant_id)
        })
        .collect();
    if configs.is_empty() {
        return not_found();
    }
    let now = Utc::now();
    let delay = chrono::Duration::seconds(super::worker::publication_delay_secs() as i64);
    let window_secs = crate::providers::hourly::HourlyPolicy::from_env().window_secs;
    let mut overall = super::status::VERIFIED;
    let mut providers = Vec::with_capacity(configs.len());
    for config in configs {
        let tenant_id = config.tenant_id.as_str();
        let plan = {
            let models = state
                .providers
                .models
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            models.active_plan(tenant_id, site).cloned()
        };
        let cursors = match state.ingest_queue.list_cursors(tenant_id, site).await {
            Ok(rows) => rows,
            Err(err) => return queue_err(&err, &request_id),
        };
        let filter = ListFilter {
            sites: Some(vec![site.to_string()]),
            tenant_id: Some(tenant_id.to_string()),
            state: None,
            limit: MAX_LIST,
        };
        let gaps = match state.ingest_queue.list_gaps(&filter).await {
            Ok(rows) => rows,
            Err(err) => return queue_err(&err, &request_id),
        };
        let horizon = super::schedule::planned_horizon(config.schedule, now, delay, window_secs);
        let (planned_through, next_run, schedule_error) = match horizon {
            Ok((planned, next)) => (Some(planned), Some(next), None),
            Err(err) => (None, None, Some(err.to_string())),
        };
        let status = super::status::provider_status(
            &config.provider_instance_id,
            plan.as_ref(),
            &cursors,
            &gaps,
            planned_through.unwrap_or(DateTime::<Utc>::MAX_UTC),
        );
        overall = super::status::worse(overall, status.state);
        let gap_scan_truncated = status.oldest_gap.is_none() && gaps.len() >= MAX_LIST as usize;
        let (mode, timezone) = match config.schedule {
            super::schedule::IngestSchedule::Periodic => ("periodic", None),
            super::schedule::IngestSchedule::Daily { tz } => ("daily", Some(tz.name())),
        };
        providers.push(json!({
            "tenant_id": tenant_id,
            "schedule": { "mode": mode, "timezone": timezone },
            "planned_through": planned_through,
            "next_run": next_run,
            "schedule_error": schedule_error,
            "gap_scan_truncated": gap_scan_truncated,
            "status": status,
        }));
    }
    Json(json!({
        "ok": true,
        "request_id": request_id,
        "scope": scope_json(&ctx),
        "site_id": site,
        "generated_at": now,
        "state": overall,
        "providers": providers,
    }))
    .into_response()
}

pub async fn queue_metrics(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    let Some(scope) = metrics_scope_for(&ctx) else {
        return json_error(
            StatusCode::FORBIDDEN,
            "forbidden",
            "no site scope",
            &request_id,
            false,
        );
    };
    match state.ingest_queue.metrics(Utc::now(), &scope).await {
        Ok(metrics) => Json(json!({
            "ok": true,
            "request_id": request_id,
            "scope": scope_json(&ctx),
            "coordination": coordination_name(),
            "kubernetes_required": false,
            "live_autoscaler": false,
            "stage3": scale::stage3_status(),
            "metrics": metrics,
        }))
        .into_response(),
        Err(err) => queue_err(&err, &request_id),
    }
}

pub async fn scale_preview(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    let ctx = tenant_ctx(&state, &user).await;
    let Some(scope) = metrics_scope_for(&ctx) else {
        return json_error(
            StatusCode::FORBIDDEN,
            "forbidden",
            "no site scope",
            &request_id,
            false,
        );
    };
    let metrics = match state.ingest_queue.metrics(Utc::now(), &scope).await {
        Ok(metrics) => metrics,
        Err(err) => return queue_err(&err, &request_id),
    };
    let now = Utc::now();
    let sample = ScaleSample {
        now,
        current_replicas: 1,
        ready_backlog: metrics.ready_backlog,
        oldest_ready_age: metrics
            .oldest_ready_age_secs
            .map(std::time::Duration::from_secs),
        mean_job_secs: Some(2.0),
        new_jobs_per_sec: 0.0,
        source_saturated: false,
        db_saturated: false,
        metrics_ok: true,
        breach_since: metrics
            .oldest_ready_age_secs
            .filter(|age| *age >= 15 * 60)
            .map(|_| now - chrono::Duration::minutes(6)),
        quiet_since: (metrics.ready_backlog == 0).then_some(now - chrono::Duration::minutes(31)),
    };
    let decision = scale::decide(&ScalePolicy::default(), &sample);
    Json(json!({
        "ok": true,
        "request_id": request_id,
        "scope": scope_json(&ctx),
        "live_control": false,
        "stage3": scale::stage3_status(),
        "decision": decision,
        "note": "dry-run only; this process does not change replica counts",
    }))
    .into_response()
}

pub async fn retry_job(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Path(job_id): Path<Uuid>,
    Json(body): Json<RetryBody>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    if viewer_cannot_mutate(user.role) {
        return json_error(
            StatusCode::FORBIDDEN,
            "forbidden",
            "operator role required",
            &request_id,
            false,
        );
    }
    if !valid_idempotency(&body.idempotency_key) {
        return json_error(
            StatusCode::BAD_REQUEST,
            "invalid_idempotency_key",
            "idempotency_key must be 8 to 128 visible characters",
            &request_id,
            false,
        );
    }
    let ctx = tenant_ctx(&state, &user).await;
    let existing = match state.ingest_queue.get_job(job_id).await {
        Ok(Some(job)) if job_in_scope(&ctx, &job) => job,
        Ok(_) => {
            return json_error(
                StatusCode::NOT_FOUND,
                "not_found",
                "job not found",
                &request_id,
                false,
            )
        }
        Err(err) => return queue_err(&err, &request_id),
    };
    let tenant_id = if ctx.multi_tenant && !ctx.hub_admin {
        ctx.tenant_id.clone().unwrap_or_default()
    } else {
        existing.tenant_id.clone()
    };
    if tenant_id != existing.tenant_id {
        return json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "job not found",
            &request_id,
            false,
        );
    }
    let claim = IdempotencyClaim {
        actor: user.sub.clone(),
        tenant_id: tenant_id.clone(),
        client_key: body.idempotency_key.clone(),
        object_id: retry_object_id(existing.job_id),
        payload_hash: retry_payload_hash(&tenant_id, existing.job_id),
    };
    match state
        .ingest_queue
        .retry_job(existing.job_id, Utc::now(), &claim)
        .await
    {
        Ok(job) if job_in_scope(&ctx, &job) && job.tenant_id == tenant_id => Json(json!({
            "ok": true,
            "request_id": request_id,
            "scope": scope_json(&ctx),
            "idempotency_key": body.idempotency_key,
            "job": job,
        }))
        .into_response(),
        Ok(_) => json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "job not found",
            &request_id,
            false,
        ),
        Err(QueueError::Invalid(msg)) => json_error(
            StatusCode::CONFLICT,
            "not_retryable",
            &msg,
            &request_id,
            false,
        ),
        Err(err) => queue_err(&err, &request_id),
    }
}

pub async fn backfill(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<AuthUser>,
    headers: HeaderMap,
    Json(body): Json<BackfillBody>,
) -> Response {
    let request_id = contract::ensure_request_id(&headers);
    if viewer_cannot_mutate(user.role) {
        return json_error(
            StatusCode::FORBIDDEN,
            "forbidden",
            "operator role required",
            &request_id,
            false,
        );
    }
    if !valid_idempotency(&body.idempotency_key) {
        return json_error(
            StatusCode::BAD_REQUEST,
            "invalid_idempotency_key",
            "idempotency_key must be 8 to 128 visible characters",
            &request_id,
            false,
        );
    }
    let ctx = tenant_ctx(&state, &user).await;
    if !ctx.allow_building(&body.canonical_site) {
        return json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "site not found",
            &request_id,
            false,
        );
    }
    if body.windows.is_empty() || body.windows.len() > MAX_CATCHUP_HOURS as usize {
        return json_error(
            StatusCode::BAD_REQUEST,
            "bound_exceeded",
            "backfill accepts 1 to 48 hourly windows",
            &request_id,
            false,
        );
    }
    let plane = state.control_plane.read().await.clone();
    let tenant_id = match derive_backfill_tenant(
        &ctx,
        &plane,
        &state.providers.sites,
        body.tenant_id.as_deref(),
        &body.canonical_site,
    ) {
        Ok(tenant_id) => tenant_id,
        Err(IdentityError::TenantRequired) => {
            return json_error(
                StatusCode::BAD_REQUEST,
                "tenant_required",
                "hub admin must name the tenant",
                &request_id,
                false,
            )
        }
        Err(IdentityError::Mismatch | IdentityError::PlanMissing) => {
            return json_error(
                StatusCode::CONFLICT,
                "identity_mismatch",
                "backfill identity does not match the caller",
                &request_id,
                false,
            )
        }
    };
    let plan = {
        let models = state
            .providers
            .models
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        models
            .active_plan(&tenant_id, &body.canonical_site)
            .cloned()
    };
    let mut identity = match resolve_plan_identity(&tenant_id, &body, plan.as_ref()) {
        Ok(identity) => identity,
        Err(IdentityError::PlanMissing) => {
            return json_error(
                StatusCode::CONFLICT,
                "plan_not_committed",
                "no committed ingest plan for this site",
                &request_id,
                false,
            )
        }
        Err(_) => {
            return json_error(
                StatusCode::CONFLICT,
                "identity_mismatch",
                "backfill identity does not match the committed plan",
                &request_id,
                false,
            )
        }
    };
    identity.provider_instance_id = bound_provider_id(
        &state.providers.sites,
        &identity.tenant_id,
        &body.canonical_site,
        &body.provider_instance_id,
        &identity.provider_instance_id,
    );
    let mut jobs = Vec::new();
    for window in &body.windows {
        if !is_hour_window(window.start, window.end) {
            return json_error(
                StatusCode::BAD_REQUEST,
                "invalid_window",
                "each window must be one exact UTC hour",
                &request_id,
                false,
            );
        }
        jobs.push(super::model::NewJob {
            tenant_id: identity.tenant_id.clone(),
            canonical_site: body.canonical_site.clone(),
            provider_instance_id: identity.provider_instance_id.clone(),
            device_id: identity.device_id.clone(),
            model_revision: identity.model_revision.clone(),
            logical_window_start: window.start,
            logical_window_end: window.end,
            shard: String::new(),
            not_before: Utc::now(),
            estimated_cost: 1,
            requested_points_digest: None,
        });
    }
    let claim = match backfill_claim(&user.sub, &body.idempotency_key, &jobs) {
        Ok(claim) => claim,
        Err(err) => return queue_err(&err, &request_id),
    };
    match state.ingest_queue.backfill(jobs, Utc::now(), &claim).await {
        Ok(created)
            if created
                .iter()
                .all(|job| job_in_scope(&ctx, job) && job.tenant_id == identity.tenant_id) =>
        {
            (
                StatusCode::ACCEPTED,
                Json(json!({
                    "ok": true,
                    "request_id": request_id,
                    "scope": scope_json(&ctx),
                    "idempotency_key": body.idempotency_key,
                    "jobs": created,
                })),
            )
                .into_response()
        }
        Ok(_) => json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "job not found",
            &request_id,
            false,
        ),
        Err(QueueError::Invalid(msg)) => json_error(
            StatusCode::BAD_REQUEST,
            "invalid_job",
            &msg,
            &request_id,
            false,
        ),
        Err(err) => queue_err(&err, &request_id),
    }
}

pub fn discovery_tools(ot_enabled: bool) -> Vec<(&'static str, &'static str, &'static str)> {
    let mut tools = vec![
        ("health", "GET", "/api/health"),
        ("providers.health", "GET", "/api/providers/health"),
        ("providers.sites", "GET", "/api/providers/sites"),
        ("ingest.jobs", "GET", "/api/ingest/jobs"),
        ("ingest.receipts", "GET", "/api/ingest/receipts"),
        ("ingest.gaps", "GET", "/api/ingest/gaps"),
        (
            "ingest.coverage_status",
            "GET",
            "/api/ingest/coverage-status",
        ),
        ("ingest.queue", "GET", "/api/ingest/queue"),
        ("ingest.stats", "GET", "/api/ingest/stats"),
        ("fdd.run", "POST", "/api/fdd/run"),
        ("fdd.status", "GET", "/api/fdd/status"),
        ("csv.import.preview", "POST", "/api/csv/import/preview"),
        (
            "csv.import.package.append",
            "POST",
            "/api/csv/import/package/append",
        ),
        ("datasets.list", "GET", "/api/datasets"),
        ("model.agent_context", "GET", "/api/model/agent-context"),
        ("model.sparql", "POST", "/api/model/sparql"),
        // Model writes: operator/admin, `confirm: true` (or `dry_run`), audited.
        ("model.semantic_meta.put", "PUT", "/api/model/semantic-meta"),
        ("model.overlay.put", "PUT", "/api/model/overlay"),
        ("model.equip.upsert", "POST", "/api/model/equip"),
        ("model.equip.delete", "DELETE", "/api/model/equip"),
        ("model.point.upsert", "POST", "/api/model/point"),
        ("model.point.delete", "DELETE", "/api/model/point"),
        (
            "csv.import.package.roles",
            "POST",
            "/api/csv/import/package/roles",
        ),
        ("historian.points", "GET", "/api/historian/points"),
        ("historian.orphans", "GET", "/api/historian/orphans"),
        ("historian.purge", "POST", "/api/historian/purge"),
    ];
    if ot_enabled {
        tools.extend([
            ("edges.list", "GET", "/api/edges"),
            ("edges.get", "GET", "/api/edges/{edge_id}"),
            ("commands.issue", "POST", "/api/commands"),
            ("commands.ack", "GET", "/api/commands/{command_id}/ack"),
        ]);
    }
    tools
}

pub fn ot_discovery_enabled() -> bool {
    std::env::var("OPENFDD_OT_TOOLS")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
}

async fn tenant_ctx(state: &AppState, user: &AuthUser) -> TenantContext {
    TenantContext::resolve_fail_closed(user, &state.control_plane.read().await.clone())
}

fn scoped_filter(ctx: &TenantContext, query: &ListQuery, request_id: &str) -> Option<ListFilter> {
    let _ = request_id;
    if ctx.multi_tenant && !ctx.hub_admin && ctx.building_ids.is_empty() {
        return None;
    }
    let sites = if ctx.multi_tenant && !ctx.hub_admin {
        let mut allowed = ctx.building_ids.clone();
        if let Some(site) = query.site_id.as_deref() {
            if !ctx.allow_building(site) {
                allowed.clear();
            } else {
                allowed = vec![site.to_string()];
            }
        }
        if allowed.is_empty() {
            return None;
        }
        Some(allowed)
    } else {
        query.site_id.clone().map(|site| vec![site])
    };
    let state = query
        .state
        .clone()
        .filter(|value| JobState::parse(value).is_some());
    let tenant_id = if ctx.multi_tenant && !ctx.hub_admin {
        Some(ctx.tenant_id.clone()?)
    } else {
        None
    };
    Some(ListFilter {
        sites,
        tenant_id,
        state,
        limit: query.limit.unwrap_or(50).clamp(1, MAX_LIST),
    })
}

fn empty_list(request_id: &str, ctx: &TenantContext) -> Response {
    empty_named(request_id, ctx, "jobs")
}

fn empty_named(request_id: &str, ctx: &TenantContext, field: &str) -> Response {
    Json(json!({
        "ok": true,
        "request_id": request_id,
        "scope": scope_json(ctx),
        field: [],
    }))
    .into_response()
}

fn scope_json(ctx: &TenantContext) -> Value {
    json!({
        "tenant_id": ctx.tenant_id,
        "hub_admin": ctx.hub_admin,
        "multi_tenant": ctx.multi_tenant,
    })
}

fn coordination_name() -> &'static str {
    match QueueClient::coordination() {
        super::client::Coordination::Postgres => "postgres",
        super::client::Coordination::ExplicitMemory => "memory",
        super::client::Coordination::Unavailable => "unavailable",
    }
}

fn queue_err(err: &super::model::QueueError, request_id: &str) -> Response {
    match err {
        QueueError::Conflict(msg) => json_error(
            StatusCode::CONFLICT,
            "idempotency_conflict",
            msg,
            request_id,
            false,
        ),
        QueueError::NotFound => json_error(
            StatusCode::NOT_FOUND,
            "not_found",
            "not found",
            request_id,
            false,
        ),
        QueueError::StaleFence => json_error(
            StatusCode::CONFLICT,
            "stale_fence",
            "lease fence rejected the write",
            request_id,
            true,
        ),
        QueueError::Invalid(msg) => json_error(
            StatusCode::BAD_REQUEST,
            "invalid_job",
            msg,
            request_id,
            false,
        ),
        QueueError::Db(detail) => {
            tracing::debug!(
                error = %super::model::redact_db_text(detail),
                "ingest queue database error"
            );
            json_error(
                StatusCode::SERVICE_UNAVAILABLE,
                "queue_unavailable",
                "shared ingest queue is unavailable",
                request_id,
                true,
            )
        }
    }
}

fn valid_idempotency(value: &str) -> bool {
    let n = value.chars().count();
    (8..=128).contains(&n) && value.chars().all(|ch| !ch.is_control() && ch != ' ')
}

pub fn viewer_cannot_mutate(role: Role) -> bool {
    !role.can_issue_commands()
}

struct PlanIdentity {
    tenant_id: String,
    provider_instance_id: String,
    device_id: String,
    model_revision: String,
}

enum IdentityError {
    TenantRequired,
    Mismatch,
    PlanMissing,
}

fn configured_site_tenants<'a>(sites: &'a [SiteConfig], site: &str) -> Vec<&'a str> {
    let mut ids: Vec<&str> = sites
        .iter()
        .filter(|row| row.building_id == site)
        .map(|row| row.tenant_id.as_str())
        .filter(|id| !id.is_empty())
        .collect();
    ids.sort_unstable();
    ids.dedup();
    ids
}

fn derive_backfill_tenant(
    ctx: &TenantContext,
    plane: &crate::tenant::ControlPlane,
    sites: &[SiteConfig],
    requested: Option<&str>,
    site: &str,
) -> Result<String, IdentityError> {
    let configured = configured_site_tenants(sites, site);
    if !ctx.multi_tenant {
        // Env-configured portal tenants are not written into tenants.json.
        // A single-hub upgrade keeps the site tenant (`lab`) instead of `legacy`.
        let tenant = match configured.as_slice() {
            [only] => (*only).to_string(),
            _ => ctx
                .tenant_id
                .clone()
                .filter(|id| !id.is_empty())
                .unwrap_or_else(|| "legacy".into()),
        };
        if let Some(named) = requested {
            if named != tenant {
                if configured.contains(&named) {
                    return Ok(named.to_string());
                }
                return Err(IdentityError::Mismatch);
            }
        }
        return Ok(tenant);
    }
    if ctx.hub_admin {
        let Some(requested) = requested.filter(|id| !id.is_empty()) else {
            return Err(IdentityError::TenantRequired);
        };
        let in_plane = plane.tenants.iter().any(|tenant| tenant.id == requested)
            && plane
                .buildings_for_tenant(requested)
                .iter()
                .any(|building| building == site);
        let configured_here = configured.contains(&requested);
        if !in_plane && !configured_here {
            return Err(IdentityError::Mismatch);
        }
        return Ok(requested.to_string());
    }
    let Some(tenant) = ctx.tenant_id.clone().filter(|id| !id.is_empty()) else {
        return Err(IdentityError::Mismatch);
    };
    if requested.is_some_and(|id| id != tenant) {
        return Err(IdentityError::Mismatch);
    }
    Ok(tenant)
}

fn resolve_plan_identity(
    tenant_id: &str,
    body: &BackfillBody,
    plan: Option<&crate::providers::committed_model::IngestPlan>,
) -> Result<PlanIdentity, IdentityError> {
    let Some(plan) = plan else {
        return Err(IdentityError::PlanMissing);
    };
    if plan.tenant_id != tenant_id || plan.site_id != body.canonical_site {
        return Err(IdentityError::Mismatch);
    }
    let Some(group) = plan.groups.iter().find(|group| {
        group.equipment_id == body.device_id
            && provider_ids_equivalent(&group.provider_instance_id, &body.provider_instance_id)
    }) else {
        return Err(IdentityError::Mismatch);
    };
    if let Some(revision) = body.model_revision.as_deref() {
        if revision != plan.revision_id && revision != MODEL_REVISION_BOOTSTRAP {
            return Err(IdentityError::Mismatch);
        }
    }
    Ok(PlanIdentity {
        tenant_id: tenant_id.to_string(),
        provider_instance_id: group.provider_instance_id.clone(),
        device_id: group.equipment_id.clone(),
        model_revision: plan.revision_id.clone(),
    })
}

fn bound_provider_id(
    sites: &[SiteConfig],
    tenant_id: &str,
    site_id: &str,
    requested: &str,
    plan_provider: &str,
) -> String {
    sites
        .iter()
        .find(|site| {
            site.tenant_id == tenant_id
                && site.building_id == site_id
                && provider_ids_equivalent(&site.provider_instance_id, plan_provider)
                && provider_ids_equivalent(&site.provider_instance_id, requested)
        })
        .map(|site| site.provider_instance_id.clone())
        .unwrap_or_else(|| plan_provider.to_string())
}

fn backfill_claim(
    actor: &str,
    client_key: &str,
    jobs: &[NewJob],
) -> Result<IdempotencyClaim, QueueError> {
    let Some(first) = jobs.first() else {
        return Err(QueueError::Invalid(
            "backfill requires 1 to 48 hourly windows".into(),
        ));
    };
    Ok(IdempotencyClaim {
        actor: actor.to_string(),
        tenant_id: first.tenant_id.clone(),
        client_key: client_key.to_string(),
        object_id: backfill_object_id(first),
        payload_hash: backfill_payload_hash(jobs)?,
    })
}

fn metrics_scope_for(ctx: &TenantContext) -> Option<MetricsScope> {
    if !ctx.multi_tenant || ctx.hub_admin {
        return Some(MetricsScope::global());
    }
    match &ctx.tenant_id {
        Some(tenant_id) if !tenant_id.is_empty() && !ctx.building_ids.is_empty() => {
            Some(MetricsScope {
                tenant_id: Some(tenant_id.clone()),
                sites: Some(ctx.building_ids.clone()),
                include_scheduler: false,
            })
        }
        _ => None,
    }
}

fn job_in_scope(ctx: &TenantContext, job: &JobView) -> bool {
    if !ctx.allow_building(&job.canonical_site) {
        return false;
    }
    if ctx.multi_tenant && !ctx.hub_admin {
        return ctx.tenant_id.as_deref() == Some(job.tenant_id.as_str());
    }
    true
}

fn receipt_in_scope(ctx: &TenantContext, receipt: &ReceiptView) -> bool {
    if !ctx.allow_building(&receipt.canonical_site) {
        return false;
    }
    if ctx.multi_tenant && !ctx.hub_admin {
        return ctx.tenant_id.as_deref() == Some(receipt.tenant_id.as_str());
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::auth::Role;

    fn scoped_user_ctx(buildings: &[&str]) -> TenantContext {
        TenantContext {
            tenant_id: Some("tenant-a".into()),
            building_ids: buildings.iter().map(|id| (*id).to_string()).collect(),
            hub_admin: false,
            multi_tenant: true,
        }
    }

    #[test]
    fn tenant_scope_hides_foreign_sites_and_empty_membership() {
        let ctx = scoped_user_ctx(&["site-a"]);
        let query = ListQuery {
            site_id: Some("site-b".into()),
            state: None,
            limit: None,
        };
        assert!(scoped_filter(&ctx, &query, "req").is_none());
        let own = ListQuery {
            site_id: Some("site-a".into()),
            state: Some("queued".into()),
            limit: Some(10),
        };
        let filter = scoped_filter(&ctx, &own, "req").unwrap();
        assert_eq!(filter.sites.unwrap(), vec!["site-a".to_string()]);
        assert_eq!(filter.state.as_deref(), Some("queued"));

        let empty = scoped_user_ctx(&[]);
        assert!(scoped_filter(
            &empty,
            &ListQuery {
                site_id: None,
                state: None,
                limit: None
            },
            "req"
        )
        .is_none());
    }

    #[test]
    fn viewers_cannot_retry_or_backfill() {
        assert!(viewer_cannot_mutate(Role::Viewer));
        assert!(!viewer_cannot_mutate(Role::Operator));
        assert!(!viewer_cannot_mutate(Role::Admin));
    }

    #[test]
    fn normal_discovery_omits_ot_commands() {
        let names: Vec<_> = discovery_tools(false)
            .into_iter()
            .map(|tool| tool.0)
            .collect();
        assert!(names.contains(&"ingest.jobs"));
        assert!(names.contains(&"ingest.gaps"));
        assert!(!names.contains(&"commands.issue"));
        assert!(!names.contains(&"edges.list"));
        assert!(discovery_tools(true)
            .iter()
            .any(|tool| tool.0 == "edges.list"));
    }
}
