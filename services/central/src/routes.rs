//! Central REST + OpenAPI routes.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::{rejection::BytesRejection, DefaultBodyLimit, Extension, Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware;
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use bytes::Bytes;
use chrono::Utc;
use openfdd_contracts::{
    CommandEnvelope, LocalIngestReceipt, LocalIngestStatus, Protocol, TelemetryEnvelope,
    TopicBuilder, TopicKind, LOCAL_INGEST_RECEIPT_CONTRACT_V1,
};
use openfdd_contracts::{
    ConnectorInventoryRequest, ConnectorInventoryResponse, ConnectorReadRequest,
    ConnectorReadResponse, ConnectorScope, HaystackAboutRequest, HaystackAboutResponse,
    HaystackCatalogRequest, HaystackCatalogResponse, HaystackCurrentReadRequest,
    HaystackCurrentReadResponse, HaystackHistoryReadRequest, HaystackHistoryReadResponse,
    HaystackNavRequest, HaystackNavResponse, PriorityHistoryRequest, PriorityHistoryResponse,
    PriorityHistoryTriggerRequest, PriorityHistoryTriggerResponse,
};
use openfdd_mqtt::publish_json;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::actions;
use crate::analytics::{self, AnalyticsRequest};
use crate::auth;
use crate::engineering_bundle;
use crate::eplus_runner;
use crate::fuel::{self, FuelRequest};
use crate::jobs;
use crate::models::{
    AgentTool, AgentToolsResponse, AuthAgentTokenRequest, AuthLoginRequest, AuthLoginResponse,
    AuthMeResponse, AuthStatusResponse, CommandAckResponse, EdgeDetailResponse,
    EdgePayloadResponse, EdgesListResponse, FddRunRequest, FddStatusResponse, IngestStatsResponse,
    IssueCommandRequest, IssueCommandResponse, OkHealthResponse, TenantSelectRequest,
    TenantSelectResponse,
};
use crate::state::{AppState, PendingCommand};
use crate::wattlab_dump;

pub fn router(state: Arc<AppState>) -> Router {
    let public = Router::new()
        .route("/api/health", get(health))
        .route("/api/version", get(version_public))
        .route("/health", get(health))
        .route("/api/auth/status", get(auth_status))
        .route("/api/auth/me", get(auth_me))
        .route("/api/auth/login", post(auth_login))
        // Fieldbus local ingest authenticates with its edge-scoped bearer
        // token. It deliberately does not depend on a cloud MQTT credential
        // or a browser JWT session.
        .route(
            "/api/ingest/local",
            post(local_fieldbus_ingest).layer(DefaultBodyLimit::max(1024 * 1024)),
        );
    // Kali O2c: detailed tenants / capabilities / stack / snapshot / summary
    // require JWT when auth is ON (moved onto protected router below).

    // Admin-gated agent token mint lives on the authenticated router below.

    let csv = Router::new()
        .route("/api/csv/import/preview", post(csv_preview))
        .route("/api/csv/import/package", post(csv_import_package))
        .route(
            "/api/csv/import/package/append",
            post(csv_import_package_append),
        )
        .route(
            "/api/csv/import/package/roles",
            post(csv_import_package_roles),
        )
        .route(
            "/api/csv/import/package/mapping",
            get(csv_import_package_mapping),
        )
        .route(
            "/api/csv/import/package/mapping/ttl",
            get(csv_import_package_mapping_ttl),
        )
        .route(
            "/api/csv/import/package/mapping/haystack.ttl",
            get(csv_import_package_mapping_haystack_ttl),
        )
        .route(
            "/api/csv/import/package/mapping/haystack-projection",
            get(csv_import_package_mapping_haystack_projection),
        )
        .route(
            "/api/csv/import/package/mapping/semantic-meta",
            get(csv_import_package_mapping_semantic_meta),
        )
        .route(
            "/api/csv/import/package/mapping/haystack-dataset",
            get(csv_import_package_mapping_haystack_dataset),
        )
        .route(
            "/api/csv/import/package/buildings",
            get(csv_import_package_buildings),
        )
        .route("/api/csv/import/plan", post(csv_plan))
        .route("/api/csv/import/preflight", post(csv_preflight))
        .route("/api/csv/import/execute", post(csv_execute))
        .route("/api/csv/import/sessions", get(csv_list_sessions))
        .route(
            "/api/csv/import/sessions/latest/planned",
            get(csv_latest_planned),
        )
        .route(
            "/api/csv/import/sessions/{session_id}",
            get(csv_get_session).delete(csv_delete_session),
        )
        .route(
            "/api/csv/import/sessions/{session_id}/fusion-preview",
            get(csv_fusion_preview),
        )
        .route(
            "/api/datasets",
            get(csv_list_datasets).delete(csv_delete_dataset),
        )
        .route(
            "/api/datasets/{dataset_id}/preview",
            get(csv_preview_dataset),
        )
        .layer(DefaultBodyLimit::max(128 * 1024 * 1024));

    let protected = Router::new()
        // Kali O2c / Wave P2c: was public; leaks plane + topology when unauthenticated.
        .route("/api/capabilities", get(capabilities))
        .route(
            "/api/connectors/{edge_id}/inventory",
            post(connector_inventory),
        )
        .route("/api/connectors/{edge_id}/read", post(connector_read))
        .route(
            "/api/connectors/{edge_id}/haystack/catalog",
            post(connector_haystack_catalog),
        )
        .route(
            "/api/connectors/{edge_id}/haystack/about",
            post(connector_haystack_about),
        )
        .route(
            "/api/connectors/{edge_id}/haystack/read",
            post(connector_haystack_read),
        )
        .route(
            "/api/connectors/{edge_id}/haystack/nav",
            post(connector_haystack_nav),
        )
        .route(
            "/api/connectors/{edge_id}/haystack/his-read",
            post(connector_haystack_history),
        )
        .route(
            "/api/connectors/{edge_id}/priority-history",
            post(connector_priority_history),
        )
        .route(
            "/api/connectors/{edge_id}/priority-history/trigger",
            post(connector_priority_history_trigger),
        )
        .route("/api/health/stack", get(health_stack))
        .route("/api/building/snapshot", get(building_snapshot))
        .route("/api/dashboard/summary", get(dashboard_summary))
        .route("/api/tenants", get(list_tenants))
        .route("/api/tenants/select", post(select_tenant))
        .route("/api/tenants/budgets", get(list_tenant_budgets))
        .route("/api/auth/agent-token", post(auth_agent_token))
        .route(
            "/api/admin/users",
            get(admin_list_users).put(admin_upsert_user),
        )
        .route("/api/admin/users/{username}", delete(admin_delete_user))
        .route(
            "/api/admin/users/{username}/disabled",
            post(admin_set_user_disabled),
        )
        .route(
            "/api/admin/tenants",
            get(admin_list_tenants_cp).put(admin_upsert_tenant),
        )
        .route(
            "/api/admin/tenants/{tenant_id}",
            delete(admin_delete_tenant),
        )
        .route(
            "/api/admin/historian-limits",
            get(admin_get_historian_limits).put(admin_put_historian_limits),
        )
        .route("/api/edges", get(list_edges))
        .route("/api/edges/{edge_id}", get(get_edge))
        .route("/api/edges/{edge_id}/discovery", get(get_edge_discovery))
        .route("/api/edges/{edge_id}/metadata", get(get_edge_metadata))
        .route("/api/ingest/stats", get(ingest_stats))
        .route("/api/commands", post(issue_command))
        .route("/api/commands/{command_id}/ack", get(get_ack))
        .route("/api/agent/tools", get(agent_tools))
        // C4 honesty: registered UNAVAILABLE — Option B cannot close #1002.
        .route(
            "/api/model/sparql",
            post(central_package_sparql_unavailable),
        )
        .route(
            "/api/model/sparql/predefined",
            get(central_package_sparql_catalog_unavailable),
        )
        .route("/api/fdd/rules", get(fdd_registry_rules))
        .route("/api/fdd/rules/{rule_id}/params", get(fdd_rule_params))
        .route("/api/fdd/cache/status", get(fdd_cache_status))
        .route("/api/fdd/equipment", get(fdd_equipment))
        .route("/api/fdd/results", get(fdd_results))
        .route("/api/fdd/results/readiness", get(fdd_results_readiness))
        .route("/api/fdd/series", get(fdd_series))
        .route("/api/fdd/roles", get(fdd_roles))
        .route("/api/fdd/cookbook-roles", get(fdd_cookbook_roles))
        .route(
            "/api/fdd/session-config",
            get(fdd_session_config_get).put(fdd_session_config_put),
        )
        .route("/api/fdd/run", post(fdd_run))
        .route("/api/fdd/status", get(fdd_status))
        .route("/api/actions", get(list_actions).delete(clear_actions))
        .route("/api/actions/{id}", delete(delete_one_action))
        .route("/api/faults/status", get(faults_status))
        .route("/api/faults/summary", get(faults_summary))
        .route("/api/export/meta", get(export_meta))
        .route("/api/data-management/summary", get(data_management_summary))
        .route("/api/data-management/budget", get(data_management_budget))
        .route(
            "/api/data-management/retention/apply",
            post(data_management_retention_apply),
        )
        .route("/api/sessions/buildings", get(building_sessions_list))
        .route("/api/sessions/building/leave", post(building_session_leave))
        .route("/api/host/stats", get(host_stats))
        .route(
            "/api/historian/compaction",
            get(historian_compaction_status).post(historian_compaction_run),
        )
        .route("/api/fdd-schema/tables", get(fdd_schema_tables))
        .route("/api/fdd-rules", get(fdd_rules_list))
        .route("/api/reports", get(reports_list))
        .route("/api/reports/templates", get(reports_templates))
        .route("/api/reports/draft", post(reports_draft))
        .route(
            "/api/reports/engineering-findings",
            get(reports_engineering_findings),
        )
        .route(
            "/api/reports/{report_id}",
            get(reports_get).patch(reports_patch).delete(reports_delete),
        )
        .route(
            "/api/reports/{report_id}/render/pdf",
            post(reports_render_pdf),
        )
        .route(
            "/api/reports/{report_id}/download.pdf",
            get(reports_download_pdf),
        )
        .route("/api/jobs", get(jobs_list).post(jobs_create))
        .route(
            "/api/jobs/{job_id}",
            get(jobs_get).patch(jobs_patch).delete(jobs_delete),
        )
        .route("/api/jobs/{job_id}/duplicate", post(jobs_duplicate))
        .route("/api/jobs/{job_id}/archive", post(jobs_archive))
        .route("/api/jobs/{job_id}/restore", post(jobs_restore))
        .route("/api/jobs/{job_id}/runs", post(jobs_create_run))
        .route(
            "/api/jobs/{job_id}/runs/{run_id}",
            get(jobs_get_run).patch(jobs_patch_run),
        )
        .route(
            "/api/jobs/{job_id}/runs/{run_id}/stale",
            post(jobs_eval_stale),
        )
        .route(
            "/api/jobs/{job_id}/findings",
            get(jobs_get_findings).put(jobs_put_findings),
        )
        .route(
            "/api/jobs/{job_id}/dispositions",
            get(jobs_get_dispositions).put(jobs_put_dispositions),
        )
        .route(
            "/api/jobs/{job_id}/wattlab/handoffs",
            post(jobs_create_wattlab_handoff),
        )
        .route(
            "/api/jobs/{job_id}/exports",
            post(jobs_create_engineering_export),
        )
        .route(
            "/api/jobs/{job_id}/exports/{export_id}/download",
            get(jobs_download_engineering_export),
        )
        .route(
            "/api/jobs/{job_id}/wattlab/dumps",
            post(jobs_create_wattlab_dump),
        )
        .route(
            "/api/jobs/{job_id}/wattlab/dumps/{dump_id}/download",
            get(jobs_download_wattlab_dump),
        )
        .route("/api/jobs/{job_id}/eplus/runs", post(jobs_queue_eplus_run))
        .route(
            "/api/jobs/{job_id}/eplus/runs/{eplus_run_id}/artifacts",
            post(jobs_attach_eplus_artifact),
        )
        .route("/api/analytics/runtime", post(analytics_runtime))
        .route("/api/analytics/vav-health", post(analytics_vav_health))
        .route("/api/analytics/ahu-health", post(analytics_ahu_health))
        .route(
            "/api/analytics/ahu-temperature-health",
            post(analytics_ahu_temperature_health),
        )
        .route(
            "/api/analytics/ahu-pressure-health",
            post(analytics_ahu_pressure_health),
        )
        .route(
            "/api/analytics/ahu-economizer-health",
            post(analytics_ahu_economizer_health),
        )
        .route(
            "/api/analytics/chiller-health",
            post(analytics_chiller_health),
        )
        .route(
            "/api/analytics/cooling-tower-health",
            post(analytics_cooling_tower_health),
        )
        .route(
            "/api/analytics/sensor-faults",
            post(analytics_sensor_faults),
        )
        .route("/api/analytics/pid-hunting", post(analytics_pid_hunting))
        .route(
            "/api/analytics/boiler-health",
            post(analytics_boiler_health),
        )
        .route("/api/analytics/hp-health", post(analytics_hp_health))
        .route(
            "/api/analytics/zone-other-health",
            post(analytics_zone_other_health),
        )
        .route(
            "/api/analytics/sensor-health",
            post(analytics_sensor_health),
        )
        .route("/api/analytics/schedule", post(analytics_schedule))
        .route(
            "/api/analytics/mechanical-cooling",
            post(analytics_mechanical_cooling),
        )
        .route(
            "/api/analytics/bas-vs-web-oat",
            post(analytics_bas_vs_web_oat),
        )
        .route("/api/analytics/inspect", post(analytics_inspect))
        .route("/api/analytics/economizer", post(analytics_economizer))
        .route("/api/analytics/rcx/ahu", post(analytics_rcx_ahu))
        .route("/api/analytics/rcx/vav", post(analytics_rcx_vav))
        .route("/api/analytics/rcx/chiller", post(analytics_rcx_chiller))
        .route("/api/analytics/rcx/boiler", post(analytics_rcx_boiler))
        .route("/api/analytics/rcx/preset", post(analytics_rcx_preset))
        .route(
            "/api/analytics/rcx/presets",
            get(analytics_rcx_presets_list),
        )
        .route("/api/analytics/metering", post(analytics_metering))
        .route("/api/analytics/mv", post(analytics_mv_change_point))
        .route("/api/analytics/fuel", post(analytics_fuel))
        .route("/api/analytics/setpoints", post(analytics_setpoints))
        .route("/api/analytics/diurnal", post(analytics_diurnal))
        .route("/api/analytics/topology", post(analytics_topology))
        .route("/api/analytics/sensor-stats", post(analytics_sensor_stats))
        .route("/api/analytics/sql-anomaly", post(analytics_sql_anomaly))
        .route("/api/fuel/campus/import", post(fuel_campus_import))
        .route("/api/fuel/campus", get(fuel_campus_list))
        .route(
            "/api/fuel/campus/weather/fetch",
            post(fuel_campus_weather_fetch),
        )
        .merge(csv)
        // OFDD-075: analytics/FDD posts (building-scoped Overview samples) can
        // exceed Axum's ~2 MiB default and 413 before reaching the handler.
        // Raise the whole protected router to 128 MiB (CSV nest already sets its
        // own limit; this covers analytics + fdd/run).
        .layer(DefaultBodyLimit::max(128 * 1024 * 1024))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ));

    Router::new()
        .merge(public)
        .merge(protected)
        .with_state(state)
}

/// Public liveness body. No historian locks, so a wedged query cannot stall it.
pub fn version_body() -> Value {
    json!({
        "ok": true,
        "service": "openfdd-central",
        "version": resolve_build_version(),
    })
}

pub async fn version_public() -> Json<Value> {
    Json(version_body())
}

/// Resolve the reported build version (OFDD-071).
///
/// Preference order so `/api/health` reflects the deployed tip, not the stale
/// crate literal:
/// 1. Runtime `OPENFDD_GIT_SHA` → `{CARGO_PKG_VERSION}+{sha}` (CI/deploy stamps this).
/// 2. Compile-time `OPENFDD_BUILD_GIT_SHA` (build.rs / docker `--build-arg`).
/// 3. Bare `CARGO_PKG_VERSION` fallback.
pub fn resolve_build_version() -> String {
    let base = env!("CARGO_PKG_VERSION");
    if let Ok(sha) = std::env::var("OPENFDD_GIT_SHA") {
        let sha = sha.trim();
        if !sha.is_empty() {
            return format!("{base}+{}", short_sha(sha));
        }
    }
    if let Some(sha) = option_env!("OPENFDD_BUILD_GIT_SHA") {
        let sha = sha.trim();
        if !sha.is_empty() {
            return format!("{base}+{}", short_sha(sha));
        }
    }
    base.to_string()
}

fn short_sha(sha: &str) -> String {
    let clean: String = sha
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .take(12)
        .collect();
    if clean.is_empty() {
        "unknown".into()
    } else {
        clean
    }
}

#[utoipa::path(
    get,
    path = "/api/health",
    tag = "central",
    responses((status = 200, description = "Central health", body = OkHealthResponse))
)]
pub async fn health(State(state): State<Arc<AppState>>) -> Json<OkHealthResponse> {
    let now = chrono::Utc::now();
    let uptime_secs = (now - state.started_at).num_seconds().max(0) as u64;
    let last_ingest_at = state
        .last_ingest_at
        .lock()
        .unwrap_or_else(|poison| poison.into_inner())
        .map(|t| t.to_rfc3339_opts(chrono::SecondsFormat::Secs, true));
    let historian_present = crate::durable_storage::historian_root_present();
    Json(OkHealthResponse {
        ok: true,
        service: "openfdd-central".into(),
        version: resolve_build_version(),
        edges: state.edges.len(),
        ingest_ok: *state
            .ingest_ok
            .lock()
            .unwrap_or_else(|poison| poison.into_inner()),
        ingest_dup: *state
            .ingest_dup
            .lock()
            .unwrap_or_else(|poison| poison.into_inner()),
        ingest_reject: *state
            .ingest_reject
            .lock()
            .unwrap_or_else(|poison| poison.into_inner()),
        multi_tenant: crate::tenant::multi_tenant_enabled(),
        started_at: state
            .started_at
            .to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        uptime_secs,
        last_ingest_at,
        historian_present,
    })
}

/// Wave L — list tenants from file control plane (legacy singleton when mode OFF).
/// Kali O2c: when auth is ON this sits behind JWT middleware — never Admin-via-anonymous.
#[utoipa::path(
    get,
    path = "/api/tenants",
    tag = "central",
    responses(
        (status = 200, description = "Tenant control-plane listing", body = crate::tenant::TenantsListResponse),
        (status = 401, description = "Auth required when JWT secret is configured")
    )
)]
pub async fn list_tenants(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<crate::tenant::TenantsListResponse>, (StatusCode, Json<Value>)> {
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    // Fail closed: never fall back to Admin anonymous for tenant roster.
    let user = state.auth.user_from_headers(&headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    let ctx = match crate::tenant::TenantContext::resolve(&user, &plane) {
        Ok(ctx) => ctx,
        Err(detail) if crate::tenant::multi_tenant_enabled() => {
            return Err((
                StatusCode::FORBIDDEN,
                Json(json!({"ok": false, "error": detail})),
            ));
        }
        Err(_) => crate::tenant::TenantContext::single_tenant_passthrough(&user),
    };
    // Keep gate 11 fail-closed on mode: never advertise ON until operator enable.
    let multi_tenant = crate::tenant::multi_tenant_enabled();
    let buildings_visible: Vec<String> = plane
        .all_building_ids()
        .into_iter()
        .filter(|b| ctx.allow_building(b))
        .collect();
    let historian_prefix = ctx.historian_prefix().unwrap_or_default();
    let tenants = if !multi_tenant || ctx.hub_admin {
        plane.tenants
    } else {
        let allowed: std::collections::HashSet<&str> =
            user.tenant_ids.iter().map(String::as_str).collect();
        plane
            .tenants
            .into_iter()
            .filter(|t| allowed.contains(t.id.as_str()))
            .collect()
    };
    Ok(Json(crate::tenant::TenantsListResponse {
        ok: true,
        multi_tenant,
        active_tenant_id: ctx.tenant_id,
        buildings_visible,
        historian_prefix,
        tenants,
    }))
}

/// Wave L L4 — select active tenant for the browser session (single domain).
/// Mode OFF: no-op echo of `legacy` (no token rotation). Mode ON: membership-gated JWT remint.
#[utoipa::path(
    post,
    path = "/api/tenants/select",
    tag = "central",
    request_body = TenantSelectRequest,
    responses(
        (status = 200, description = "Active tenant selection", body = TenantSelectResponse),
        (status = 401, description = "Auth required when mode ON"),
        (status = 403, description = "Tenant not in membership")
    )
)]
pub async fn select_tenant(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<TenantSelectRequest>,
) -> Result<Json<TenantSelectResponse>, (StatusCode, Json<Value>)> {
    let tid = body.tenant_id.trim().to_string();
    if tid.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "tenant_id required"})),
        ));
    }
    let multi_tenant = crate::tenant::multi_tenant_enabled();
    if !multi_tenant {
        // OFF-safe: single-hub semantics — selection is a no-op for `legacy` only.
        if tid != "legacy" {
            return Err((
                StatusCode::BAD_REQUEST,
                Json(json!({
                    "ok": false,
                    "error": "multi-tenant mode is off; only tenant_id=legacy is valid"
                })),
            ));
        }
        return Ok(Json(TenantSelectResponse {
            ok: true,
            multi_tenant: false,
            active_tenant_id: "legacy".into(),
            token: None,
            access_token: None,
            error: None,
        }));
    }

    let user = state.auth.user_from_headers(&headers).map_err(|detail| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": detail})),
        )
    })?;
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    let hub_admin = matches!(user.role, auth::Role::Admin) && user.tenant_ids.is_empty();
    if hub_admin {
        if !plane.tenants.iter().any(|t| t.id == tid) {
            open_fdd_edge_prototype::auth::audit::log_event(
                "tenant_select_denied",
                json!({
                    "username": user.sub,
                    "tenant_id": tid,
                    "reason": "unknown_tenant",
                }),
            );
            return Err((
                StatusCode::FORBIDDEN,
                Json(json!({"ok": false, "error": "unknown tenant_id"})),
            ));
        }
    } else if !user.tenant_ids.iter().any(|t| t == &tid) {
        open_fdd_edge_prototype::auth::audit::log_event(
            "tenant_select_denied",
            json!({
                "username": user.sub,
                "tenant_id": tid,
                "reason": "not_in_membership",
                "membership": user.tenant_ids,
            }),
        );
        open_fdd_edge_prototype::auth::audit::log_event(
            "tenant_access_denied",
            json!({
                "username": user.sub,
                "tenant_id": tid,
                "surface": "tenants/select",
            }),
        );
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "tenant not in membership"})),
        ));
    }

    let token = state
        .auth
        .issue_token_with_tenants(&user.sub, user.role, 8 * 3600, std::slice::from_ref(&tid))
        .map_err(|_| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": "token mint failed"})),
            )
        })?;
    open_fdd_edge_prototype::auth::audit::log_event(
        "tenant_select",
        json!({
            "username": user.sub,
            "tenant_id": tid,
            "hub_admin": hub_admin,
        }),
    );
    Ok(Json(TenantSelectResponse {
        ok: true,
        multi_tenant: true,
        active_tenant_id: tid,
        token: Some(token.clone()),
        access_token: Some(token),
        error: None,
    }))
}

fn resolve_tenant_context_for_user(user: &auth::AuthUser) -> crate::tenant::TenantContext {
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    crate::tenant::TenantContext::resolve_fail_closed(user, &plane)
}

fn resolve_tenant_context(state: &AppState, headers: &HeaderMap) -> crate::tenant::TenantContext {
    let user = state
        .auth
        .user_from_headers(headers)
        .unwrap_or_else(|_| auth::AuthUser::dev_anonymous());
    resolve_tenant_context_for_user(&user)
}

fn authorized_edge_ids(state: &AppState, ctx: &crate::tenant::TenantContext) -> HashSet<String> {
    let mut authorized = HashSet::new();

    // A trusted configured upstream is sufficient for capability visibility
    // during broker-free commissioning. A telemetry shadow is an additional
    // consistency check, never the source of tenant/building identity.
    for edge_id in state.capabilities.authorized_edge_ids(ctx) {
        let shadow_matches = state.edges.get(&edge_id).is_none_or(|entry| {
            let shadow = entry
                .value()
                .lock()
                .unwrap_or_else(|poison| poison.into_inner());
            let known_site_matches = shadow.known_site_id().is_none_or(|site| {
                state
                    .capabilities
                    .configured_scope(&edge_id)
                    .is_some_and(|(_, building)| building == site)
            });
            let known_tenant_matches = shadow.known_tenant_id().is_none_or(|tenant| {
                state
                    .capabilities
                    .configured_scope(&edge_id)
                    .is_some_and(|(configured_tenant, _)| configured_tenant == tenant)
            });
            known_site_matches && known_tenant_matches
        });
        if shadow_matches {
            authorized.insert(edge_id);
        }
    }

    // Legacy telemetry-only edges remain visible only when their registered
    // shadow carries a complete authenticated scope.
    for entry in &state.edges {
        if state.capabilities.configured_scope(entry.key()).is_some() {
            continue;
        }
        let shadow = entry
            .value()
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let Some(known_site) = shadow.known_site_id() else {
            continue;
        };
        let known_tenant = shadow.known_tenant_id().unwrap_or_else(|| "legacy".into());
        if ctx.allow_building(&known_site)
            && (ctx.hub_admin || ctx.tenant_id.as_deref() == Some(known_tenant.as_str()))
        {
            authorized.insert(entry.key().clone());
        }
    }
    authorized
}

/// Tenant id for dual-read. The active session tenant is used when the newer
/// tree is hub-root (that call still compares hub vs tenant Parquet).
fn preferred_tenant_for_building_read(
    ctx: &crate::tenant::TenantContext,
    building_id: Option<&str>,
) -> Option<String> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return ctx.tenant_id.clone();
    };
    let hub = crate::analytics::historian::parquet_root_base();
    let from_parquet = match ctx.historian_read_root_for_building(&hub, bid) {
        Ok(resolved) => resolved.tenant_id.or_else(|| ctx.tenant_id.clone()),
        Err(_) => ctx.tenant_id.clone(),
    };
    if from_parquet.is_some() || !ctx.multi_tenant {
        return from_parquet;
    }
    // Unscoped hub admin and an ambiguous or empty resolver. The control plane
    // names the owner only when exactly one tenant lists the building.
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    plane.sole_tenant_for_building(bid)
}

fn require_hub_admin(
    state: &AppState,
    headers: &HeaderMap,
) -> Result<auth::AuthUser, (StatusCode, Json<Value>)> {
    let user = state.auth.user_from_headers(headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    let hub_admin = matches!(user.role, auth::Role::Admin) && user.tenant_ids.is_empty();
    if !hub_admin {
        tracing::info!(
            target: "security_audit",
            event = "admin_cp_denied",
            subject = %user.sub,
            "non-hub-admin blocked from /api/admin"
        );
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "hub admin required"})),
        ));
    }
    Ok(user)
}

fn workspace_path() -> std::path::PathBuf {
    std::path::PathBuf::from(
        std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into()),
    )
}

pub async fn admin_list_users(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _admin = require_hub_admin(&state, &headers)?;
    let store = crate::user_store::UserStore::load_or_empty(&workspace_path());
    Ok(Json(json!({
        "ok": true,
        "users": store.public_list(),
    })))
}

pub async fn admin_upsert_user(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<crate::admin_cp::UserUpsertRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    let ws = workspace_path();
    let mut store = crate::user_store::UserStore::load_or_empty(&ws);
    let rec = crate::user_store::UserRecord {
        username: body.username,
        role: body.role,
        tenant_ids: body.tenant_ids,
        password_env: body.password_env,
        password: body.password,
        disabled: body.disabled,
    };
    store.upsert(rec).map_err(|e| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    store.save(&ws).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    tracing::info!(
        target: "security_audit",
        event = "admin_user_upsert",
        actor = %admin.sub,
        "control-plane user upsert"
    );
    Ok(Json(json!({"ok": true, "users": store.public_list()})))
}

#[derive(Deserialize)]
pub struct AdminDisabledBody {
    pub disabled: bool,
}

pub async fn admin_set_user_disabled(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(username): Path<String>,
    Json(body): Json<AdminDisabledBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    let ws = workspace_path();
    let mut store = crate::user_store::UserStore::load_or_empty(&ws);
    store.set_disabled(&username, body.disabled).map_err(|e| {
        (
            StatusCode::NOT_FOUND,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    store.save(&ws).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    tracing::info!(
        target: "security_audit",
        event = "admin_user_disabled",
        actor = %admin.sub,
        username = %username,
        disabled = body.disabled,
        "control-plane user disabled flag"
    );
    Ok(Json(json!({"ok": true, "users": store.public_list()})))
}

#[derive(Debug, Deserialize)]
pub struct AdminDeleteUserQuery {
    /// When true, return cascade plan only (no deletes).
    #[serde(default)]
    pub dry_run: bool,
    /// Required for actual delete + cascade purge (`confirm=true`).
    #[serde(default)]
    pub confirm: bool,
}

pub async fn admin_delete_user(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(username): Path<String>,
    Query(q): Query<AdminDeleteUserQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    let ws = workspace_path();
    let mut store = crate::user_store::UserStore::load_or_empty(&ws);
    let plane = crate::tenant::ControlPlane::load_or_legacy(&ws);
    let plan =
        crate::admin_cp::plan_user_cascade_delete(&store, &plane, &username).map_err(|e| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({"ok": false, "error": e})),
            )
        })?;
    if q.dry_run || !q.confirm {
        return Ok(Json(json!({
            "ok": true,
            "dry_run": true,
            "requires_confirm": !q.confirm,
            "plan": plan,
            "users": store.public_list(),
        })));
    }

    let mut purged = Vec::new();
    let mut purge_errors = Vec::new();
    for bid in &plan.buildings_to_purge {
        let id_for_task = bid.clone();
        let outcome = tokio::task::spawn_blocking(move || {
            open_fdd_edge_prototype::csv_ingest::delete_dataset(&id_for_task)
        })
        .await
        .unwrap_or_else(|e| Err(format!("dataset delete task failed: {e}")));
        match outcome {
            Ok(()) => {
                let (n, errs) = crate::jobs::delete_jobs_for_site(bid);
                if !errs.is_empty() {
                    purge_errors.push(format!(
                        "{bid}: jobs partial ({n} deleted): {}",
                        errs.join("; ")
                    ));
                } else {
                    purged.push(json!({ "building_id": bid, "jobs_deleted": n }));
                }
            }
            Err(e) => purge_errors.push(format!("{bid}: {e}")),
        }
    }
    if !purge_errors.is_empty() {
        return Err((
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({
                "ok": false,
                "error": "cascade purge failed; user not removed",
                "plan": plan,
                "purged": purged,
                "purge_errors": purge_errors,
            })),
        ));
    }

    store.remove(&username).map_err(|e| {
        (
            StatusCode::NOT_FOUND,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    store.save(&ws).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    tracing::info!(
        target: "security_audit",
        event = "admin_user_delete",
        actor = %admin.sub,
        username = %username,
        purged = purged.len(),
        skipped_shared = plan.buildings_shared_skipped.len(),
        "control-plane user deleted with cascade"
    );
    Ok(Json(json!({
        "ok": true,
        "plan": plan,
        "purged": purged,
        "users": store.public_list(),
    })))
}

pub async fn admin_list_tenants_cp(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _admin = require_hub_admin(&state, &headers)?;
    let plane = crate::tenant::ControlPlane::load_or_legacy(&workspace_path());
    Ok(Json(json!({
        "ok": true,
        "tenants": plane.tenants,
    })))
}

pub async fn admin_upsert_tenant(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<crate::admin_cp::TenantUpsertRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    let ws = workspace_path();
    let mut plane = crate::tenant::ControlPlane::load_or_legacy(&ws);
    plane
        .upsert_tenant(crate::tenant::TenantRecord {
            id: body.id,
            name: body.name,
            building_ids: body.building_ids,
        })
        .map_err(|e| {
            (
                StatusCode::BAD_REQUEST,
                Json(json!({"ok": false, "error": e})),
            )
        })?;
    plane.save(&ws).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    tracing::info!(
        target: "security_audit",
        event = "admin_tenant_upsert",
        actor = %admin.sub,
        "control-plane tenant upsert"
    );
    Ok(Json(json!({"ok": true, "tenants": plane.tenants})))
}

pub async fn admin_delete_tenant(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Path(tenant_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    let ws = workspace_path();
    let mut plane = crate::tenant::ControlPlane::load_or_legacy(&ws);
    plane.remove_tenant(&tenant_id).map_err(|e| {
        (
            StatusCode::NOT_FOUND,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    plane.save(&ws).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    tracing::info!(
        target: "security_audit",
        event = "admin_tenant_delete",
        actor = %admin.sub,
        tenant_id = %tenant_id,
        "control-plane tenant deleted"
    );
    Ok(Json(json!({"ok": true, "tenants": plane.tenants})))
}

pub async fn admin_get_historian_limits(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _admin = require_hub_admin(&state, &headers)?;
    let lim = crate::historian_limits::HistorianLimits::load(&workspace_path());
    Ok(Json(json!({
        "ok": true,
        "limits": lim,
        "storage_root": crate::historian_limits::storage_root().display().to_string(),
    })))
}

pub async fn admin_put_historian_limits(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<crate::historian_limits::HistorianLimits>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    let ws = workspace_path();
    let mut lim = body;
    lim.sanitize();
    lim.save(&ws).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    tracing::info!(
        target: "security_audit",
        event = "admin_historian_limits_put",
        actor = %admin.sub,
        retain_days = lim.retain_days,
        size_gib = lim.size_gib,
        "historian retain/size limits updated"
    );
    open_fdd_edge_prototype::auth::audit::log_event(
        "admin_historian_limits_put",
        json!({
            "actor": admin.sub,
            "retain_days": lim.retain_days,
            "size_gib": lim.size_gib,
        }),
    );
    Ok(Json(json!({"ok": true, "limits": lim})))
}

/// Wave N: fail-closed building gate for historian/FDD/analytics when MT ON.
fn deny_if_building_out_of_scope(
    state: &AppState,
    headers: &HeaderMap,
    building_id: Option<&str>,
) -> Option<(StatusCode, Json<Value>)> {
    if !crate::tenant::multi_tenant_enabled() {
        return None;
    }
    let ctx = resolve_tenant_context(state, headers);
    let bid = building_id.map(str::trim).filter(|s| !s.is_empty());
    match bid {
        Some(b) if ctx.allow_building(b) => None,
        Some(b) => {
            open_fdd_edge_prototype::auth::audit::log_event(
                "tenant_building_denied",
                json!({
                    "building_id": b,
                    "active_tenant_id": ctx.tenant_id,
                    "hub_admin": ctx.hub_admin,
                }),
            );
            Some((
                StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "building not in tenant scope",
                    "building_id": b,
                })),
            ))
        }
        None if ctx.hub_admin => None,
        None => {
            open_fdd_edge_prototype::auth::audit::log_event(
                "tenant_building_required",
                json!({ "active_tenant_id": ctx.tenant_id }),
            );
            Some((
                StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "building_id required in multi-tenant mode",
                })),
            ))
        }
    }
}

/// MT: deny edge detail when known site is outside tenant allowlist.
fn deny_edge_out_of_scope(
    state: &AppState,
    headers: &HeaderMap,
    edge_id: &str,
) -> Option<(StatusCode, Json<Value>)> {
    if !crate::tenant::multi_tenant_enabled() {
        return None;
    }
    let ctx = resolve_tenant_context(state, headers);
    if ctx.hub_admin {
        return None;
    }
    let entry = state.edges.get(edge_id)?;
    let site = entry.lock().unwrap().known_site_id();
    match site.as_deref() {
        Some(s) if ctx.allow_building(s) => None,
        Some(s) => {
            open_fdd_edge_prototype::auth::audit::log_event(
                "tenant_edge_denied",
                json!({
                    "edge_id": edge_id,
                    "site_id": s,
                    "active_tenant_id": ctx.tenant_id,
                }),
            );
            Some((
                StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "edge not in tenant scope",
                    "edge_id": edge_id,
                })),
            ))
        }
        None => {
            // Unknown site under MT: fail closed for non-hub-admin.
            Some((
                StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "edge not in tenant scope",
                    "edge_id": edge_id,
                })),
            ))
        }
    }
}

fn resolve_request_tenant(
    state: &AppState,
    headers: &HeaderMap,
) -> (Option<String>, crate::tenant_budget::TenantBudgetConfig) {
    let cfg = crate::tenant_budget::TenantBudgetConfig::from_env();
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    let user = state
        .auth
        .user_from_headers(headers)
        .unwrap_or_else(|_| auth::AuthUser::dev_anonymous());
    let ctx = crate::tenant::TenantContext::resolve_fail_closed(&user, &plane);
    (ctx.tenant_id, cfg)
}

fn enforce_tenant_budget(
    state: &AppState,
    headers: &HeaderMap,
    kind: crate::tenant_budget::BudgetKind,
) -> Result<(), String> {
    let (tenant_id, cfg) = resolve_request_tenant(state, headers);
    if !cfg.enabled {
        return Ok(());
    }
    let tid = tenant_id.as_deref().unwrap_or("legacy");
    state.tenant_budgets.check_and_record(&cfg, tid, kind)
}

/// Wave L L5 — echo tenant budget config (disabled while mode OFF).
#[utoipa::path(
    get,
    path = "/api/tenants/budgets",
    tag = "central",
    responses((status = 200, description = "Tenant budget policy", body = crate::tenant_budget::TenantBudgetsResponse))
)]
pub async fn list_tenant_budgets(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Json<crate::tenant_budget::TenantBudgetsResponse> {
    let (active_tenant_id, budgets) = resolve_request_tenant(&state, &headers);
    Json(crate::tenant_budget::TenantBudgetsResponse {
        ok: true,
        multi_tenant: crate::tenant::multi_tenant_enabled(),
        budgets,
        active_tenant_id,
    })
}

/// Feature advertisement for UI capability gates and MCP accuracy checks.
pub async fn capabilities(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
) -> Json<Value> {
    let ctx = resolve_tenant_context_for_user(&user);
    let allowed_edges = authorized_edge_ids(&state, &ctx);
    let aggregate = state
        .capabilities
        .snapshot(crate::capabilities::central_hello(&state))
        .await;
    let aggregate = crate::capabilities::restrict_to_edges(aggregate, &allowed_edges);
    let aggregate = serde_json::to_value(aggregate).unwrap_or_else(|_| {
        json!({
            "schema": openfdd_contracts::CAPABILITIES_AGGREGATE_CONTRACT_V1,
            "error": "capability serialization failed"
        })
    });
    Json(json!({
        "ok": true,
        "contract": crate::contract::contract_capabilities_extra(),
        "connector_capabilities": aggregate,
        "capabilities": {
            "lab": true,
            "fdd_registry": true,
            "fdd_equipment": true,
            "fdd_results": true,
            "fdd_series": true,
            "session_config": true,
            "csv_package": true,
            "reports": true,
            "export": true,
            "data_management": true,
            "host_stats": true,
            "historian_compaction": true,
            "faults": true,
            "health_stack": true,
            "fdd_rules_authoring": true,
            "fdd_schema": true,
            "analytics": true,
            "jobs": true,
            "react_ui": std::env::var("OPENFDD_REACT_UI").ok().as_deref() == Some("1"),
            "ui_generation_routing": true,
            "tenant_session": true,
            "tenant_budgets": crate::tenant_budget::tenant_budgets_enabled()
        }
    }))
}

/// Forward an explicitly requested, scoped read to a configured fieldbus
/// edge. Advertised capabilities never substitute for JWT and tenant checks.
fn authorize_connector_scope(
    state: &Arc<AppState>,
    ctx: &crate::tenant::TenantContext,
    edge_id: &str,
    scope: &ConnectorScope,
) -> Result<(), (StatusCode, Json<Value>)> {
    if !request_scope_allowed(ctx, scope) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "building is outside the authenticated tenant scope"
            })),
        ));
    }
    if let Some((configured_tenant, configured_building)) =
        state.capabilities.configured_scope(edge_id)
    {
        if configured_building != scope.building_id || configured_tenant != scope.tenant_id {
            return Err((
                StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "edge is outside the trusted connector scope"
                })),
            ));
        }
        if let Some(edge) = state.edges.get(edge_id) {
            let edge_shadow = edge.lock().unwrap_or_else(|poison| poison.into_inner());
            if edge_shadow
                .known_site_id()
                .is_some_and(|known_site| known_site != scope.building_id)
                || edge_shadow
                    .known_tenant_id()
                    .is_some_and(|known_tenant| known_tenant != scope.tenant_id)
            {
                return Err((
                    StatusCode::FORBIDDEN,
                    Json(json!({
                        "ok": false,
                        "error": "edge telemetry identity conflicts with trusted connector scope"
                    })),
                ));
            }
        }
        return Ok(());
    }

    let edge = state.edges.get(edge_id).ok_or_else(|| {
        (
            StatusCode::NOT_FOUND,
            Json(json!({"ok": false, "error": "edge is not registered"})),
        )
    })?;
    let edge_shadow = edge.lock().unwrap_or_else(|poison| poison.into_inner());
    if edge_shadow.known_site_id().as_deref() != Some(scope.building_id.as_str()) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "edge is not registered for the requested building"
            })),
        ));
    }
    let known_tenant = edge_shadow
        .known_tenant_id()
        .unwrap_or_else(|| "legacy".into());
    if !ctx.hub_admin && known_tenant != scope.tenant_id {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "edge is not registered for the authenticated tenant"
            })),
        ));
    }
    Ok(())
}

pub async fn connector_read(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<ConnectorReadRequest>,
) -> Result<Json<ConnectorReadResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|error| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": error})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    // Keep the authenticated user in the handler signature so the route's
    // JWT middleware cannot be accidentally removed without a compile-time
    // use-site change. Authorization is represented by the tenant check and
    // the middleware; no advertised capability grants access.
    let _subject = user.sub;
    let response = state
        .capabilities
        .proxy_read(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

pub async fn connector_haystack_catalog(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<HaystackCatalogRequest>,
) -> Result<Json<HaystackCatalogResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid Haystack catalog request"})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let response = state
        .capabilities
        .proxy_haystack_catalog(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

pub async fn connector_haystack_about(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<HaystackAboutRequest>,
) -> Result<Json<HaystackAboutResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid Haystack about request"})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let response = state
        .capabilities
        .proxy_haystack_about(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

pub async fn connector_haystack_read(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<HaystackCurrentReadRequest>,
) -> Result<Json<HaystackCurrentReadResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid Haystack current-read request"})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let response = state
        .capabilities
        .proxy_haystack_current_read(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

pub async fn connector_haystack_nav(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<HaystackNavRequest>,
) -> Result<Json<HaystackNavResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid Haystack navigation request"})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let response = state
        .capabilities
        .proxy_haystack_nav(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

pub async fn connector_haystack_history(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<HaystackHistoryReadRequest>,
) -> Result<Json<HaystackHistoryReadResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid Haystack history request"})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let response = state
        .capabilities
        .proxy_haystack_history(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

/// Return a bounded typed inventory page from a configured connector. This
/// endpoint is authenticated and scope checked exactly like the read seam;
/// advertised capabilities do not grant access and no central MQTT map is
/// used as an inventory source.
pub async fn connector_inventory(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<ConnectorInventoryRequest>,
) -> Result<Json<ConnectorInventoryResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|error| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": error})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let _subject = user.sub;
    let response = state
        .capabilities
        .proxy_inventory(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

/// Return a bounded, authenticated priority-array history page from the
/// configured edge. The route never turns a history request into a live OT
/// read and never exposes cloud-side fieldbus credentials or URLs.
pub async fn connector_priority_history(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<PriorityHistoryRequest>,
) -> Result<Json<PriorityHistoryResponse>, (StatusCode, Json<Value>)> {
    if !connector_proxy_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "connector role is not authorized"})),
        ));
    }
    request.validate().map_err(|error| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": error})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let _subject = user.sub;
    let response = state
        .capabilities
        .proxy_priority_history(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

/// Trigger one bounded, read-only priority-array device visit. Operators and
/// admins may request it; viewers are denied before the edge proxy is called.
pub async fn connector_priority_history_trigger(
    State(state): State<Arc<AppState>>,
    Extension(user): Extension<auth::AuthUser>,
    Path(edge_id): Path<String>,
    Json(request): Json<PriorityHistoryTriggerRequest>,
) -> Result<Json<PriorityHistoryTriggerResponse>, (StatusCode, Json<Value>)> {
    if !connector_trigger_role_allowed(user.role) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({"ok": false, "error": "priority history trigger requires operator role"})),
        ));
    }
    request.validate().map_err(|error| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": error})),
        )
    })?;
    if request.scope.edge_id != edge_id {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "path edge_id and scoped edge_id differ"})),
        ));
    }
    let ctx = resolve_tenant_context_for_user(&user);
    authorize_connector_scope(&state, &ctx, &edge_id, &request.scope)?;
    let response = state
        .capabilities
        .proxy_priority_history_trigger(&edge_id, &request)
        .await
        .map_err(|error| {
            (
                error.status(),
                Json(json!({"ok": false, "error": error.message()})),
            )
        })?;
    Ok(Json(response))
}

fn request_scope_allowed(ctx: &crate::tenant::TenantContext, scope: &ConnectorScope) -> bool {
    ctx.allow_building(&scope.building_id)
        && (ctx.hub_admin || ctx.tenant_id.as_deref() == Some(scope.tenant_id.as_str()))
}

/// Connector inventory is available to every authenticated connector role
/// after tenant/building/edge authorization. Live reads remain read-only; the
/// deployment policy recommends operator/admin for them, but this route does
/// not invent a second role gate that could diverge from the auth middleware.
fn connector_proxy_role_allowed(role: auth::Role) -> bool {
    matches!(
        role,
        auth::Role::Viewer | auth::Role::Operator | auth::Role::Admin
    )
}

fn connector_trigger_role_allowed(role: auth::Role) -> bool {
    matches!(role, auth::Role::Operator | auth::Role::Admin)
}

#[utoipa::path(
    get,
    path = "/api/auth/status",
    tag = "central",
    responses((status = 200, description = "Whether UI login is required", body = AuthStatusResponse))
)]
pub async fn auth_status(State(state): State<Arc<AppState>>) -> Json<AuthStatusResponse> {
    Json(AuthStatusResponse {
        ok: true,
        auth_required: state.auth.required(),
        agent_login_configured: state.auth.agent_password.is_some(),
    })
}

#[utoipa::path(
    get,
    path = "/api/auth/me",
    tag = "central",
    responses((status = 200, description = "Current session subject", body = AuthMeResponse))
)]
pub async fn auth_me(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
) -> Result<Json<AuthMeResponse>, (axum::http::StatusCode, Json<Value>)> {
    match state.auth.user_from_headers(&headers) {
        Ok(user) => {
            let workspace =
                std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
            let plane =
                crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
            let ctx = crate::tenant::TenantContext::resolve_fail_closed(&user, &plane);
            Ok(Json(AuthMeResponse {
                ok: true,
                username: user.sub,
                role: user.role.as_str().into(),
                auth_required: state.auth.required(),
                multi_tenant: crate::tenant::multi_tenant_enabled(),
                active_tenant_id: ctx.tenant_id,
                tenant_ids: user.tenant_ids,
                hub_admin: ctx.hub_admin,
            }))
        }
        Err(detail) => Err((
            axum::http::StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": detail})),
        )),
    }
}

#[utoipa::path(
    post,
    path = "/api/auth/login",
    tag = "central",
    request_body = AuthLoginRequest,
    responses(
        (status = 200, description = "JWT for dashboard", body = AuthLoginResponse),
        (status = 401, description = "Invalid credentials")
    )
)]
pub async fn auth_login(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Json(body): Json<AuthLoginRequest>,
) -> Result<Json<AuthLoginResponse>, (axum::http::StatusCode, Json<Value>)> {
    let request_id = crate::contract::ensure_request_id(&headers);
    let ip = headers
        .get("x-forwarded-for")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("unknown")
        .split(',')
        .next()
        .unwrap_or("unknown")
        .trim();
    let username = body.username.trim().to_string();
    let throttle_key = format!("{ip}:{}", username.to_lowercase());
    if state.login_is_throttled(&throttle_key) {
        open_fdd_edge_prototype::auth::audit::log_event(
            "login_rate_limited",
            json!({
                "username": username,
                "ip": ip,
                "request_id": request_id,
            }),
        );
        return Err((
            axum::http::StatusCode::TOO_MANY_REQUESTS,
            Json(json!({"ok": false, "error": "invalid credentials"})),
        ));
    }
    if !state.auth.required() {
        open_fdd_edge_prototype::auth::audit::log_event(
            "login_open_mode",
            json!({
                "username": username,
                "ip": ip,
                "request_id": request_id,
            }),
        );
        // Dev open mode — mint a placeholder so the UI can store a session token.
        return Ok(Json(AuthLoginResponse {
            ok: true,
            token: "open".into(),
            access_token: "open".into(),
            token_type: "Bearer".into(),
            role: "admin".into(),
            subject: "dev".into(),
            multi_tenant: crate::tenant::multi_tenant_enabled(),
            active_tenant_id: Some("legacy".into()),
            error: None,
        }));
    }
    let (sub, role, tenant_ids) = match state
        .auth
        .authenticate_password(&body.username, &body.password)
    {
        Ok(v) => v,
        Err(_) => {
            state.login_record_failure(&throttle_key);
            open_fdd_edge_prototype::auth::audit::log_event(
                "login_failure",
                json!({
                    "username": username,
                    "ip": ip,
                    "request_id": request_id,
                }),
            );
            return Err((
                axum::http::StatusCode::UNAUTHORIZED,
                Json(json!({"ok": false, "error": "invalid credentials"})),
            ));
        }
    };
    state.login_record_success(&throttle_key);
    let token = state
        .auth
        .issue_token_with_tenants(&sub, role, 8 * 3600, &tenant_ids)
        .map_err(|_| {
            (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": "login failed"})),
            )
        })?;
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
    let auth_user = auth::AuthUser {
        sub: sub.clone(),
        role,
        tenant_ids: tenant_ids.clone(),
    };
    let ctx = crate::tenant::TenantContext::resolve_fail_closed(&auth_user, &plane);
    open_fdd_edge_prototype::auth::audit::log_event(
        "login_success",
        json!({
            "username": sub,
            "role": role.as_str(),
            "ip": ip,
            "request_id": request_id,
            "active_tenant_id": ctx.tenant_id,
            "tenant_ids": tenant_ids,
            "hub_admin": ctx.hub_admin,
        }),
    );
    Ok(Json(AuthLoginResponse {
        ok: true,
        token: token.clone(),
        access_token: token,
        token_type: "Bearer".into(),
        role: role.as_str().into(),
        subject: sub,
        multi_tenant: crate::tenant::multi_tenant_enabled(),
        active_tenant_id: ctx.tenant_id,
        error: None,
    }))
}

#[utoipa::path(
    post,
    path = "/api/auth/agent-token",
    tag = "central",
    request_body = AuthAgentTokenRequest,
    security(("bearerAuth" = [])),
    responses(
        (status = 200, description = "Short-lived operator JWT for FDD AI / MCP", body = AuthLoginResponse),
        (status = 401, description = "Missing or invalid admin bearer"),
        (status = 403, description = "Admin role required")
    )
)]
pub async fn auth_agent_token(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Json(body): Json<AuthAgentTokenRequest>,
) -> Result<Json<AuthLoginResponse>, (axum::http::StatusCode, Json<Value>)> {
    let request_id = crate::contract::ensure_request_id(&headers);
    let user = state.auth.user_from_headers(&headers).map_err(|detail| {
        (
            axum::http::StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": detail})),
        )
    })?;
    if state.auth.required() && user.role != auth::Role::Admin {
        return Err((
            axum::http::StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "admin role required to mint agent tokens"
            })),
        ));
    }
    let hub_admin = matches!(user.role, auth::Role::Admin) && user.tenant_ids.is_empty();
    let scoped_admin = matches!(user.role, auth::Role::Admin) && !user.tenant_ids.is_empty();
    let ttl = body.ttl_secs.unwrap_or(3600).clamp(60, 86_400);
    let requested = body
        .tenant_id
        .as_ref()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let tenant_ids: Vec<String> = if hub_admin {
        // Hub admin may mint scoped or (explicitly) empty membership agent.
        requested.map(|s| vec![s]).unwrap_or_default()
    } else if scoped_admin {
        // Scoped admin must mint only within their membership; omit/blank/foreign → 403.
        let Some(tid) = requested else {
            return Err((
                axum::http::StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "scoped admin must supply tenant_id within membership"
                })),
            ));
        };
        if !user.tenant_ids.iter().any(|t| t == &tid) {
            return Err((
                axum::http::StatusCode::FORBIDDEN,
                Json(json!({
                    "ok": false,
                    "error": "scoped admin cannot mint agent for foreign tenant"
                })),
            ));
        }
        vec![tid]
    } else {
        return Err((
            axum::http::StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "admin role required to mint agent tokens"
            })),
        ));
    };
    let active_tenant_id = tenant_ids
        .first()
        .cloned()
        .unwrap_or_else(|| "legacy".into());
    let token = state
        .auth
        .issue_token_with_tenants("agent", auth::Role::Operator, ttl, &tenant_ids)
        .map_err(|_| {
            (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": "token mint failed"})),
            )
        })?;
    open_fdd_edge_prototype::auth::audit::log_event(
        "agent_token_minted",
        json!({
            "by": user.sub,
            "role": "operator",
            "ttl_secs": ttl,
            "request_id": request_id,
            "tenant_ids": tenant_ids,
            "active_tenant_id": active_tenant_id,
            "hub_admin_mint": hub_admin,
        }),
    );
    Ok(Json(AuthLoginResponse {
        ok: true,
        token: token.clone(),
        access_token: token,
        token_type: "Bearer".into(),
        role: auth::Role::Operator.as_str().into(),
        subject: "agent".into(),
        multi_tenant: crate::tenant::multi_tenant_enabled(),
        active_tenant_id: Some(active_tenant_id),
        error: None,
    }))
}

#[utoipa::path(
    get,
    path = "/api/edges",
    tag = "central",
    security(("bearerAuth" = [])),
    responses((status = 200, description = "Registered edge shadows", body = EdgesListResponse))
)]
pub async fn list_edges(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
) -> Json<EdgesListResponse> {
    let ctx = resolve_tenant_context(&state, &headers);
    let edges = state
        .edges
        .iter()
        .filter_map(|e| {
            let g = e.value().lock().unwrap();
            let site_id = g.known_site_id();
            if ctx.multi_tenant && !ctx.hub_admin {
                match site_id.as_deref() {
                    Some(site) if ctx.allow_building(site) => {}
                    _ => return None,
                }
            }
            Some(crate::models::EdgeSummary {
                edge_id: e.key().clone(),
                site_id,
                has_telemetry: g.last_telemetry.is_some(),
            })
        })
        .collect();
    Json(EdgesListResponse { ok: true, edges })
}

#[utoipa::path(
    get,
    path = "/api/edges/{edge_id}",
    tag = "central",
    security(("bearerAuth" = [])),
    params(("edge_id" = String, Path, description = "Edge identifier")),
    responses((status = 200, description = "Edge shadow detail", body = EdgeDetailResponse))
)]
pub async fn get_edge(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Path(edge_id): Path<String>,
) -> Result<Json<EdgeDetailResponse>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_edge_out_of_scope(&state, &headers, &edge_id) {
        return Err(deny);
    }
    match state.edges.get(&edge_id) {
        Some(e) => {
            let g = e.lock().unwrap();
            Ok(Json(EdgeDetailResponse {
                ok: true,
                edge_id,
                last_telemetry: g.last_telemetry.clone(),
                sequences: g.sequences.clone(),
                error: None,
            }))
        }
        None => Ok(Json(EdgeDetailResponse {
            ok: false,
            edge_id,
            last_telemetry: None,
            sequences: Default::default(),
            error: Some("edge not found".into()),
        })),
    }
}

#[utoipa::path(
    get,
    path = "/api/edges/{edge_id}/discovery",
    tag = "central",
    security(("bearerAuth" = [])),
    params(("edge_id" = String, Path, description = "Edge identifier")),
    responses((status = 200, description = "Last discovery MQTT payloads by protocol", body = EdgePayloadResponse))
)]
pub async fn get_edge_discovery(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Path(edge_id): Path<String>,
) -> Result<Json<EdgePayloadResponse>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_edge_out_of_scope(&state, &headers, &edge_id) {
        return Err(deny);
    }
    match state.edges.get(&edge_id) {
        Some(e) => {
            let g = e.lock().unwrap();
            let payload = if g.last_discovery.is_empty() {
                None
            } else {
                Some(json!(g.last_discovery))
            };
            Ok(Json(EdgePayloadResponse {
                ok: true,
                edge_id,
                payload,
                error: None,
            }))
        }
        None => Ok(Json(EdgePayloadResponse {
            ok: false,
            edge_id,
            payload: None,
            error: Some("edge not found".into()),
        })),
    }
}

#[utoipa::path(
    get,
    path = "/api/edges/{edge_id}/metadata",
    tag = "central",
    security(("bearerAuth" = [])),
    params(("edge_id" = String, Path, description = "Edge identifier")),
    responses((status = 200, description = "Last metadata MQTT payloads by protocol", body = EdgePayloadResponse))
)]
pub async fn get_edge_metadata(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Path(edge_id): Path<String>,
) -> Result<Json<EdgePayloadResponse>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_edge_out_of_scope(&state, &headers, &edge_id) {
        return Err(deny);
    }
    match state.edges.get(&edge_id) {
        Some(e) => {
            let g = e.lock().unwrap();
            let payload = if g.last_metadata.is_empty() {
                None
            } else {
                Some(json!(g.last_metadata))
            };
            Ok(Json(EdgePayloadResponse {
                ok: true,
                edge_id,
                payload,
                error: None,
            }))
        }
        None => Ok(Json(EdgePayloadResponse {
            ok: false,
            edge_id,
            payload: None,
            error: Some("edge not found".into()),
        })),
    }
}

/// Accept one fieldbus envelope over the local, authenticated HTTP path.
///
/// The envelope is the same `TelemetryEnvelope` used by MQTTS. Message IDs
/// are reserved before persistence so dual mode is idempotent even when the
/// local and cloud copies arrive concurrently.
fn local_receipt(
    scope: &str,
    envelope: Option<&TelemetryEnvelope>,
    status: LocalIngestStatus,
    duplicate: bool,
    eligible_points: usize,
    persisted_rows: usize,
    error: Option<&str>,
) -> LocalIngestReceipt {
    LocalIngestReceipt {
        schema: LOCAL_INGEST_RECEIPT_CONTRACT_V1.into(),
        scope: if scope.trim().is_empty() {
            "unbound".into()
        } else {
            scope.to_string()
        },
        site_id: envelope
            .map(|value| value.site_id.clone())
            .unwrap_or_else(|| "unknown".into()),
        edge_id: envelope
            .map(|value| value.edge_id.clone())
            .unwrap_or_else(|| "unknown".into()),
        message_id: envelope
            .map(|value| value.message_id)
            .unwrap_or_else(uuid::Uuid::nil),
        status,
        duplicate,
        eligible_points,
        persisted_rows,
        error: error.map(str::to_string),
    }
}

#[derive(Debug)]
pub struct LocalIngestError {
    status: StatusCode,
    receipt: Box<LocalIngestReceipt>,
}

impl IntoResponse for LocalIngestError {
    fn into_response(self) -> Response {
        (self.status, Json(*self.receipt)).into_response()
    }
}

fn local_error(
    status_code: StatusCode,
    scope: &str,
    envelope: Option<&TelemetryEnvelope>,
    status: LocalIngestStatus,
    error: &'static str,
) -> Result<(StatusCode, Json<LocalIngestReceipt>), LocalIngestError> {
    Err(LocalIngestError {
        status: status_code,
        receipt: Box::new(local_receipt(
            scope,
            envelope,
            status,
            false,
            0,
            0,
            Some(error),
        )),
    })
}

pub async fn local_fieldbus_ingest(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    body: Result<Bytes, BytesRejection>,
) -> Result<(StatusCode, Json<LocalIngestReceipt>), LocalIngestError> {
    const MAX_LOCAL_PAYLOAD_BYTES: usize = 1024 * 1024;

    state.recover_pending_receipts_once().await;

    let body = match body {
        Ok(body) => body,
        Err(_) => {
            return local_error(
                StatusCode::PAYLOAD_TOO_LARGE,
                "unbound",
                None,
                LocalIngestStatus::Rejected,
                "local ingest payload exceeds 1 MiB",
            )
        }
    };

    if body.len() > MAX_LOCAL_PAYLOAD_BYTES {
        return local_error(
            StatusCode::PAYLOAD_TOO_LARGE,
            "unbound",
            None,
            LocalIngestStatus::Rejected,
            "local ingest payload exceeds 1 MiB",
        );
    }

    let expected_token = match std::env::var("OPENFDD_LOCAL_INGEST_TOKEN")
        .ok()
        .filter(|value| !value.trim().is_empty())
    {
        Some(token) => token,
        None => {
            return local_error(
                StatusCode::SERVICE_UNAVAILABLE,
                "unbound",
                None,
                LocalIngestStatus::Retryable,
                "local ingest is not configured",
            )
        }
    };
    let supplied_token = headers
        .get(header::AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
        .map(str::trim)
        .unwrap_or_default();
    if supplied_token != expected_token {
        tracing::warn!(target: "security_audit", event = "local_ingest_auth_failure", "local ingest bearer rejected");
        return local_error(
            StatusCode::UNAUTHORIZED,
            "unbound",
            None,
            LocalIngestStatus::Rejected,
            "local ingest bearer required",
        );
    }

    let envelope: TelemetryEnvelope = match serde_json::from_slice(&body) {
        Ok(envelope) => envelope,
        Err(_) => {
            return local_error(
                StatusCode::BAD_REQUEST,
                "unbound",
                None,
                LocalIngestStatus::Rejected,
                "invalid telemetry envelope",
            )
        }
    };
    if envelope.validate().is_err() {
        return local_error(
            StatusCode::BAD_REQUEST,
            "unbound",
            Some(&envelope),
            LocalIngestStatus::Rejected,
            "telemetry envelope failed validation",
        );
    }

    let message_header = match headers
        .get("x-openfdd-message-id")
        .and_then(|value| value.to_str().ok())
    {
        Some(header) => header,
        None => {
            return local_error(
                StatusCode::BAD_REQUEST,
                "unbound",
                Some(&envelope),
                LocalIngestStatus::Rejected,
                "x-openfdd-message-id required",
            )
        }
    };
    if message_header != envelope.message_id.to_string() {
        return local_error(
            StatusCode::BAD_REQUEST,
            "unbound",
            Some(&envelope),
            LocalIngestStatus::Rejected,
            "message id header does not match envelope",
        );
    }

    let trusted_building = match std::env::var("OPENFDD_BUILDING_ID")
        .ok()
        .or_else(|| std::env::var("OPENFDD_SITE_ID").ok())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    {
        Some(building) => building,
        None => {
            return local_error(
                StatusCode::SERVICE_UNAVAILABLE,
                "unbound",
                Some(&envelope),
                LocalIngestStatus::Retryable,
                "local ingest has no trusted building binding",
            )
        }
    };
    let allowed_buildings = std::env::var("OPENFDD_LOCAL_ALLOWED_BUILDINGS")
        .ok()
        .map(|raw| {
            raw.split(',')
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>()
        });
    if allowed_buildings
        .as_ref()
        .is_some_and(|allowed| !allowed.contains(&trusted_building))
    {
        return local_error(
            StatusCode::SERVICE_UNAVAILABLE,
            "unbound",
            Some(&envelope),
            LocalIngestStatus::Retryable,
            "trusted building is not in the local ingest allowlist",
        );
    }
    if envelope.site_id != trusted_building {
        return local_error(
            StatusCode::FORBIDDEN,
            "unbound",
            Some(&envelope),
            LocalIngestStatus::Rejected,
            "site/building identity mismatch",
        );
    }
    if let Some(supplied_building) = headers
        .get("x-openfdd-building-id")
        .and_then(|value| value.to_str().ok())
    {
        if supplied_building != trusted_building {
            return local_error(
                StatusCode::FORBIDDEN,
                "unbound",
                Some(&envelope),
                LocalIngestStatus::Rejected,
                "caller building is not trusted",
            );
        }
    }
    let allowed_edges_raw = std::env::var("OPENFDD_LOCAL_ALLOWED_EDGE_IDS")
        .ok()
        .or_else(|| std::env::var("OPENFDD_EDGE_ID").ok());
    let allowed_edges = match allowed_edges_raw
        .map(|raw| {
            raw.split(',')
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty())
                .collect::<Vec<_>>()
        })
        .filter(|values| !values.is_empty())
    {
        Some(edges) => edges,
        None => {
            return local_error(
                StatusCode::SERVICE_UNAVAILABLE,
                "unbound",
                Some(&envelope),
                LocalIngestStatus::Retryable,
                "local ingest has no trusted edge binding",
            )
        }
    };
    if !allowed_edges
        .iter()
        .any(|value| value == "*" || *value == envelope.edge_id)
    {
        return local_error(
            StatusCode::FORBIDDEN,
            "unbound",
            Some(&envelope),
            LocalIngestStatus::Rejected,
            "edge is not in the local ingest allowlist",
        );
    }

    if crate::tenant::multi_tenant_enabled() {
        let expected_tenant = match std::env::var("OPENFDD_TENANT_ID")
            .ok()
            .filter(|value| !value.trim().is_empty())
        {
            Some(tenant) => tenant,
            None => {
                return local_error(
                    StatusCode::SERVICE_UNAVAILABLE,
                    "unbound",
                    Some(&envelope),
                    LocalIngestStatus::Retryable,
                    "multi-tenant local ingest has no tenant binding",
                )
            }
        };
        let supplied_tenant = headers
            .get("x-openfdd-tenant-id")
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default();
        if supplied_tenant != expected_tenant {
            return local_error(
                StatusCode::FORBIDDEN,
                "unbound",
                Some(&envelope),
                LocalIngestStatus::Rejected,
                "tenant identity mismatch",
            );
        }
    }
    if envelope.points.iter().any(|point| {
        point
            .tags
            .get("building_id")
            .and_then(|value| value.as_str())
            .is_some_and(|value| value != trusted_building)
    }) {
        return local_error(
            StatusCode::FORBIDDEN,
            "unbound",
            Some(&envelope),
            LocalIngestStatus::Rejected,
            "point building identity mismatch",
        );
    }

    let receipt_scope = format!(
        "tenant={};building={}",
        std::env::var("OPENFDD_TENANT_ID").unwrap_or_else(|_| "-".into()),
        trusted_building
    );

    if envelope.points.len() > 5_000 {
        return local_error(
            StatusCode::PAYLOAD_TOO_LARGE,
            &receipt_scope,
            Some(&envelope),
            LocalIngestStatus::Rejected,
            "local ingest exceeds the 5000 point limit",
        );
    }

    if let Some(existing_status) = state
        .receipt_status(&receipt_scope, &envelope.edge_id, envelope.message_id)
        .await
    {
        *state.ingest_dup.lock().unwrap() += 1;
        if state
            .receipt_payload_matches(
                &receipt_scope,
                &envelope.edge_id,
                envelope.message_id,
                &envelope,
            )
            .await
            != Some(true)
        {
            return local_error(
                StatusCode::CONFLICT,
                &receipt_scope,
                Some(&envelope),
                LocalIngestStatus::Conflict,
                "message id is already bound to a different payload",
            );
        }
        let persisted_rows = state
            .receipt_persisted_rows(&receipt_scope, &envelope.edge_id, envelope.message_id)
            .await
            .unwrap_or_default();
        let eligible_points = state
            .receipt_eligible_points(&receipt_scope, &envelope.edge_id, envelope.message_id)
            .await
            .unwrap_or_default();
        let status = match existing_status {
            crate::state::IngestReceiptStatus::Committed => LocalIngestStatus::Committed,
            crate::state::IngestReceiptStatus::TerminalZeroEligible => {
                LocalIngestStatus::TerminalZeroEligible
            }
            crate::state::IngestReceiptStatus::Rejected => LocalIngestStatus::Rejected,
            crate::state::IngestReceiptStatus::Retryable => LocalIngestStatus::Retryable,
            crate::state::IngestReceiptStatus::Pending => LocalIngestStatus::Pending,
        };
        let done = matches!(
            status,
            LocalIngestStatus::Committed | LocalIngestStatus::TerminalZeroEligible
        );
        return Ok((
            if done {
                StatusCode::OK
            } else {
                StatusCode::ACCEPTED
            },
            Json(local_receipt(
                &receipt_scope,
                Some(&envelope),
                status,
                true,
                eligible_points,
                persisted_rows,
                None,
            )),
        ));
    }
    if crate::historian_limits::deny_building_over_size(&workspace_path(), &envelope.site_id)
        .is_some()
    {
        *state.ingest_reject.lock().unwrap() += 1;
        return local_error(
            StatusCode::PAYLOAD_TOO_LARGE,
            &receipt_scope,
            Some(&envelope),
            LocalIngestStatus::Rejected,
            "building historian limit rejected the envelope",
        );
    }
    if !state
        .reserve_receipt_at(&receipt_scope, envelope.clone())
        .await
    {
        if state
            .receipt_status(&receipt_scope, &envelope.edge_id, envelope.message_id)
            .await
            .is_none()
        {
            return local_error(
                StatusCode::SERVICE_UNAVAILABLE,
                &receipt_scope,
                Some(&envelope),
                LocalIngestStatus::Retryable,
                "local receipt ledger unavailable",
            );
        }
        if state
            .receipt_payload_matches(
                &receipt_scope,
                &envelope.edge_id,
                envelope.message_id,
                &envelope,
            )
            .await
            != Some(true)
        {
            return local_error(
                StatusCode::CONFLICT,
                &receipt_scope,
                Some(&envelope),
                LocalIngestStatus::Conflict,
                "message id is already bound to a different payload",
            );
        }
        return Ok((
            StatusCode::ACCEPTED,
            Json(local_receipt(
                &receipt_scope,
                Some(&envelope),
                LocalIngestStatus::Pending,
                true,
                0,
                0,
                None,
            )),
        ));
    }

    let report = match state.ingest_live(&receipt_scope, &envelope).await {
        Ok(report) => report,
        Err(error) => {
            state
                .release_receipt(&receipt_scope, &envelope.edge_id, envelope.message_id)
                .await;
            let _ = error;
            return local_error(
                StatusCode::SERVICE_UNAVAILABLE,
                &receipt_scope,
                Some(&envelope),
                LocalIngestStatus::Retryable,
                "local historian ingest failed",
            );
        }
    };
    if report.eligible_points == 0 {
        let _ = state
            .mark_zero_eligible(&receipt_scope, &envelope.edge_id, envelope.message_id)
            .await;
    }
    // Publish this request before the ACK. The shared row/time threshold is
    // for MQTT micro-batches; a local sample must not sit on HTTP 202 while
    // its rows are only buffered.
    if state.publish_pending(&receipt_scope).await.is_err() {
        return Ok((
            StatusCode::ACCEPTED,
            Json(local_receipt(
                &receipt_scope,
                Some(&envelope),
                LocalIngestStatus::Pending,
                false,
                report.eligible_points,
                0,
                Some("flush pending"),
            )),
        ));
    }
    let final_status = state
        .receipt_status(&receipt_scope, &envelope.edge_id, envelope.message_id)
        .await;
    let receipt_edge_id = envelope.edge_id.clone();
    let receipt_message_id = envelope.message_id;
    let persisted_rows = state
        .receipt_persisted_rows(&receipt_scope, &receipt_edge_id, receipt_message_id)
        .await
        .unwrap_or(0);
    let status = match final_status {
        Some(crate::state::IngestReceiptStatus::Committed) if persisted_rows > 0 => {
            LocalIngestStatus::Committed
        }
        Some(crate::state::IngestReceiptStatus::TerminalZeroEligible) => {
            LocalIngestStatus::TerminalZeroEligible
        }
        Some(crate::state::IngestReceiptStatus::Rejected) => LocalIngestStatus::Rejected,
        Some(crate::state::IngestReceiptStatus::Retryable) => LocalIngestStatus::Retryable,
        _ => LocalIngestStatus::Pending,
    };
    let durable = status == LocalIngestStatus::Committed;
    let entry = state.edges.entry(envelope.edge_id.clone()).or_default();
    let mut shadow = entry.lock().unwrap();
    shadow
        .sequences
        .insert(format!("{:?}", envelope.protocol), envelope.sequence);
    shadow.registered_site_id = Some(envelope.site_id.clone());
    shadow.registered_tenant_id = std::env::var("OPENFDD_TENANT_ID")
        .ok()
        .filter(|tenant| !tenant.trim().is_empty())
        .or_else(|| Some("legacy".into()));
    shadow.last_telemetry = Some(envelope.clone());
    if durable {
        state.note_ingest_ok();
        state.note_durable_ingest();
    }
    Ok((
        if durable {
            StatusCode::OK
        } else {
            StatusCode::ACCEPTED
        },
        Json(local_receipt(
            &receipt_scope,
            Some(&envelope),
            status,
            false,
            report.eligible_points,
            persisted_rows,
            None,
        )),
    ))
}

#[utoipa::path(
    get,
    path = "/api/ingest/stats",
    tag = "central",
    security(("bearerAuth" = [])),
    responses((status = 200, description = "MQTT ingest counters", body = IngestStatsResponse))
)]
pub async fn ingest_stats(State(state): State<Arc<AppState>>) -> Json<IngestStatsResponse> {
    Json(IngestStatsResponse {
        ok: true,
        ingest_ok: *state.ingest_ok.lock().unwrap(),
        ingest_dup: *state.ingest_dup.lock().unwrap(),
        ingest_reject: *state.ingest_reject.lock().unwrap(),
        reject_buckets: state.ingest_reject_buckets.lock().unwrap().clone(),
        dead_letters: state.dead_letters.lock().unwrap().len(),
    })
}

#[utoipa::path(
    post,
    path = "/api/commands",
    tag = "central",
    security(("bearerAuth" = [])),
    request_body = IssueCommandRequest,
    responses(
        (status = 200, description = "Command prepared and optionally published", body = IssueCommandResponse),
        (status = 401, description = "Missing or invalid JWT"),
        (status = 403, description = "Insufficient role (operator or admin required)")
    )
)]
pub async fn issue_command(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Json(body): Json<IssueCommandRequest>,
) -> Json<IssueCommandResponse> {
    let request_id = crate::contract::ensure_request_id(&headers);
    let user = match state.auth.user_from_headers(&headers) {
        Ok(u) => u,
        Err(detail) => {
            open_fdd_edge_prototype::auth::audit::log_event(
                "command_auth_failure",
                json!({
                    "target_id": body.target_id,
                    "request_id": request_id,
                    "reason": detail,
                }),
            );
            return Json(IssueCommandResponse {
                ok: false,
                command: None,
                publish_topic: None,
                response_topic: None,
                published: None,
                hint: None,
                error: Some(detail),
            });
        }
    };
    if state.auth.required() && !user.role.can_issue_commands() {
        open_fdd_edge_prototype::auth::audit::log_event(
            "command_forbidden",
            json!({
                "subject": user.sub,
                "role": user.role.as_str(),
                "target_id": body.target_id,
                "request_id": request_id,
            }),
        );
        return Json(IssueCommandResponse {
            ok: false,
            command: None,
            publish_topic: None,
            response_topic: None,
            published: None,
            hint: None,
            error: Some("operator or admin role required to issue commands".into()),
        });
    }

    if crate::tenant::multi_tenant_enabled() {
        let ctx = resolve_tenant_context(&state, &headers);
        let site = body.site_id.trim();
        if !ctx.allow_building(site) {
            open_fdd_edge_prototype::auth::audit::log_event(
                "tenant_building_denied",
                json!({
                    "building_id": site,
                    "active_tenant_id": ctx.tenant_id,
                    "hub_admin": ctx.hub_admin,
                    "target_id": body.target_id,
                    "edge_id": body.edge_id,
                    "request_id": request_id,
                }),
            );
            return Json(IssueCommandResponse {
                ok: false,
                command: None,
                publish_topic: None,
                response_topic: None,
                published: None,
                hint: None,
                error: Some("site not in tenant scope".into()),
            });
        }
    }

    if body.target_id.is_empty() {
        return Json(IssueCommandResponse {
            ok: false,
            command: None,
            publish_topic: None,
            response_topic: None,
            published: None,
            hint: None,
            error: Some("target_id required".into()),
        });
    }
    let approved_by = if body.approved_by.trim().is_empty() {
        user.sub.clone()
    } else {
        body.approved_by.clone()
    };

    // Wave N+ MT hubs reject sites/… ingest; command + ack topics must match the
    // edge's tenants/{tid}/buildings/{bid}/… namespace or pause/resume never acks.
    let topics = if crate::tenant::multi_tenant_enabled() {
        let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
        let plane = crate::tenant::ControlPlane::load_or_legacy(std::path::Path::new(&workspace));
        let tid = body
            .tenant_id
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .or_else(|| plane.tenant_for_building(&body.site_id));
        match tid {
            Some(tid) => TopicBuilder::with_tenant(tid, &body.site_id, &body.edge_id),
            None => {
                return Json(IssueCommandResponse {
                    ok: false,
                    command: None,
                    publish_topic: None,
                    response_topic: None,
                    published: None,
                    hint: None,
                    error: Some(format!(
                        "multi-tenant mode requires tenant_id (building {} is not mapped to a tenant)",
                        body.site_id
                    )),
                });
            }
        }
    } else {
        TopicBuilder::new(&body.site_id, &body.edge_id)
    };
    let protocol = if body.target_id.starts_with("edge:") {
        Protocol::Mixed
    } else {
        Protocol::Bacnet
    };
    let response_topic = topics.topic(TopicKind::Acks, Some(protocol));
    let cmd = CommandEnvelope::new(
        &body.site_id,
        &body.edge_id,
        protocol,
        &body.target_id,
        body.value.clone(),
        &approved_by,
        response_topic.clone(),
        body.ttl_secs,
    );
    if let Err(err) = cmd.validate() {
        return Json(IssueCommandResponse {
            ok: false,
            command: None,
            publish_topic: None,
            response_topic: None,
            published: None,
            hint: None,
            error: Some(err),
        });
    }

    let publish_topic = topics.topic(TopicKind::Commands, Some(protocol));
    let mut published = false;
    let mut hint = None;

    state.pending_commands.insert(
        cmd.command_id,
        PendingCommand {
            command: cmd.clone(),
            publish_topic: publish_topic.clone(),
            response_topic: response_topic.clone(),
            issued_at: Utc::now(),
            published: false,
        },
    );

    if mqtt_enabled() {
        let client = state.mqtt_publisher.lock().unwrap().clone();
        if let Some(client) = client {
            match publish_json(&client, &publish_topic, &cmd, false).await {
                Ok(()) => {
                    published = true;
                    if let Some(mut pending) = state.pending_commands.get_mut(&cmd.command_id) {
                        pending.published = true;
                    }
                }
                Err(err) => {
                    hint = Some(format!("mqtt publish failed: {err}"));
                }
            }
        } else {
            hint = Some("MQTT publisher not connected yet; command stored as pending".into());
        }
    } else {
        hint = Some("Set OPENFDD_MQTT_ENABLED=1 for live publish from the control plane".into());
    }

    open_fdd_edge_prototype::auth::audit::log_event(
        "command_issued",
        json!({
            "subject": approved_by,
            "role": user.role.as_str(),
            "site_id": body.site_id,
            "edge_id": body.edge_id,
            "target_id": body.target_id,
            "command_id": cmd.command_id,
            "published": published,
            "request_id": request_id,
        }),
    );

    Json(IssueCommandResponse {
        ok: true,
        command: Some(cmd),
        publish_topic: Some(publish_topic),
        response_topic: Some(response_topic),
        published: Some(published),
        hint,
        error: None,
    })
}

#[utoipa::path(
    get,
    path = "/api/commands/{command_id}/ack",
    tag = "central",
    security(("bearerAuth" = [])),
    params(("command_id" = String, Path, description = "Command UUID")),
    responses((status = 200, description = "Command acknowledgement or pending state", body = CommandAckResponse))
)]
pub async fn get_ack(
    State(state): State<Arc<AppState>>,
    Path(command_id): Path<String>,
) -> Json<CommandAckResponse> {
    let Ok(id) = uuid::Uuid::parse_str(&command_id) else {
        return Json(CommandAckResponse {
            ok: false,
            ack: None,
            pending: None,
            error: Some("invalid command_id".into()),
        });
    };
    if let Some(ack) = state.command_acks.get(&id) {
        return Json(CommandAckResponse {
            ok: true,
            ack: Some(ack.clone()),
            pending: Some(false),
            error: None,
        });
    }
    if state.pending_commands.contains_key(&id) {
        return Json(CommandAckResponse {
            ok: true,
            ack: None,
            pending: Some(true),
            error: None,
        });
    }
    Json(CommandAckResponse {
        ok: false,
        ack: None,
        pending: None,
        error: Some("ack not found".into()),
    })
}

#[utoipa::path(
    get,
    path = "/api/agent/tools",
    tag = "central",
    security(("bearerAuth" = [])),
    responses((status = 200, description = "Agent tool catalog", body = AgentToolsResponse))
)]
pub async fn agent_tools() -> Json<AgentToolsResponse> {
    Json(AgentToolsResponse {
        ok: true,
        tools: vec![
            AgentTool {
                name: "health".into(),
                method: "GET".into(),
                path: "/api/health".into(),
            },
            AgentTool {
                name: "edges.list".into(),
                method: "GET".into(),
                path: "/api/edges".into(),
            },
            AgentTool {
                name: "edges.get".into(),
                method: "GET".into(),
                path: "/api/edges/{edge_id}".into(),
            },
            AgentTool {
                name: "edges.discovery".into(),
                method: "GET".into(),
                path: "/api/edges/{edge_id}/discovery".into(),
            },
            AgentTool {
                name: "edges.metadata".into(),
                method: "GET".into(),
                path: "/api/edges/{edge_id}/metadata".into(),
            },
            AgentTool {
                name: "commands.issue".into(),
                method: "POST".into(),
                path: "/api/commands".into(),
            },
            AgentTool {
                name: "commands.ack".into(),
                method: "GET".into(),
                path: "/api/commands/{command_id}/ack".into(),
            },
            AgentTool {
                name: "ingest.stats".into(),
                method: "GET".into(),
                path: "/api/ingest/stats".into(),
            },
            AgentTool {
                name: "fdd.run".into(),
                method: "POST".into(),
                path: "/api/fdd/run".into(),
            },
            AgentTool {
                name: "fdd.status".into(),
                method: "GET".into(),
                path: "/api/fdd/status".into(),
            },
            AgentTool {
                name: "csv.import.preview".into(),
                method: "POST".into(),
                path: "/api/csv/import/preview".into(),
            },
            AgentTool {
                name: "csv.import.package.append".into(),
                method: "POST".into(),
                path: "/api/csv/import/package/append".into(),
            },
            AgentTool {
                name: "datasets.list".into(),
                method: "GET".into(),
                path: "/api/datasets".into(),
            },
        ],
    })
}

#[utoipa::path(
    post,
    path = "/api/fdd/run",
    tag = "central",
    security(("bearerAuth" = [])),
    request_body = FddRunRequest,
    responses((status = 200, description = "FDD registry or ad-hoc SQL run result", body = Object))
)]
pub async fn fdd_run(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<FddRunRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Err(err) =
        enforce_tenant_budget(&state, &headers, crate::tenant_budget::BudgetKind::FddRun)
    {
        return Ok(Json(json!({
            "ok": false,
            "error": err,
            "budget_exceeded": true
        })));
    }
    let has_sql = body.sql.as_ref().is_some_and(|s| !s.trim().is_empty());
    if has_sql {
        return Ok(Json(json!({
            "ok": false,
            "error": "raw SQL rejected on /api/fdd/run; use mode=registry with typed params"
        })));
    }
    // Resolve building_id from top-level field, or nested `params.building_id`
    // (the hunt curl nests it inside params). Trim/blank guarded so an empty
    // string never scopes to `building=/`.
    let building_id = body
        .building_id
        .as_deref()
        .or_else(|| body.params.get("building_id").and_then(Value::as_str))
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, building_id.as_deref()) {
        return Err(deny);
    }
    // Hunt / nightly bench may nest rule_ids under params; hoist so
    // run_registry's top-level filter applies (else all rules → timeout → {}).
    let rule_ids = body.rule_ids.clone().or_else(|| {
        body.params.get("rule_ids").and_then(|v| {
            v.as_array().map(|a| {
                a.iter()
                    .filter_map(|x| x.as_str().map(str::to_string))
                    .collect::<Vec<_>>()
            })
        })
    });
    let mode = body
        .params
        .get("mode")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .filter(|_| body.rule_ids.is_none())
        .map(str::to_string)
        .unwrap_or_else(|| body.mode.clone());
    let mut payload = json!({
        "confirmation_seconds": body.confirmation_seconds,
        "params": body.params,
        "mode": mode,
        "rule_ids": rule_ids,
        "equipment_id": body.equipment_id,
        "building_id": building_id,
    });
    // Wave O6: clamp AFDD/bulk start_utc to hub retain floor (never silent mid-result truncate).
    {
        let lim = crate::historian_limits::HistorianLimits::load(&workspace_path());
        let floor = lim.retain_floor_utc();
        let clamp_str = |s: &str| -> Option<String> {
            let parsed = chrono::DateTime::parse_from_rfc3339(s.trim())
                .ok()
                .map(|dt| dt.with_timezone(&Utc))
                .or_else(|| {
                    chrono::NaiveDateTime::parse_from_str(s.trim(), "%Y-%m-%dT%H:%M:%SZ")
                        .ok()
                        .map(|n| n.and_utc())
                })?;
            if parsed < floor {
                Some(floor.to_rfc3339())
            } else {
                None
            }
        };
        if let Some(obj) = payload.as_object_mut() {
            if let Some(s) = obj
                .get("start_utc")
                .and_then(|v| v.as_str())
                .map(str::to_string)
            {
                if let Some(c) = clamp_str(&s) {
                    obj.insert("start_utc".into(), json!(c));
                }
            }
            if let Some(params) = obj.get_mut("params").and_then(|v| v.as_object_mut()) {
                if let Some(s) = params
                    .get("start_utc")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                {
                    if let Some(c) = clamp_str(&s) {
                        params.insert("start_utc".into(), json!(c));
                    }
                }
            }
        }
    }
    let echo_building_id = building_id.clone();

    let run_all = rule_ids.as_ref().map(|r| r.is_empty()).unwrap_or(true);
    let (kind, label) = if run_all {
        (
            "fdd_run_all",
            format!(
                "FDD run all · {}",
                building_id.as_deref().unwrap_or("(no building)")
            ),
        )
    } else {
        let ids = rule_ids.as_ref().map(|r| r.join(",")).unwrap_or_default();
        (
            "fdd_run_rule",
            format!(
                "FDD run · {} · {}",
                building_id.as_deref().unwrap_or("(no building)"),
                if ids.len() > 48 {
                    format!("{}…", &ids[..48])
                } else {
                    ids
                }
            ),
        )
    };
    let action_id = match actions::start_action(
        kind,
        &label,
        Some(json!({
            "building_id": building_id,
            "rule_ids": rule_ids,
        })),
    ) {
        Ok(id) => Some(id),
        Err(err) if err.starts_with("busy:") => {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({
                    "ok": false,
                    "error": err,
                    "busy": true,
                })),
            ));
        }
        Err(err) => {
            tracing::warn!(%err, "actions start_action failed; continuing FDD without action id");
            None
        }
    };

    let fdd_timeout_secs: u64 = std::env::var("OPENFDD_FDD_RUN_TIMEOUT_SECS")
        .ok()
        .and_then(|s| s.parse().ok())
        .filter(|&s| s > 0)
        .unwrap_or(900);
    let join = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::fdd::registry_api::run_registry(&payload)
    });
    let mut result = match tokio::time::timeout(Duration::from_secs(fdd_timeout_secs), join).await {
        Ok(Ok(v)) => v,
        Ok(Err(e)) => json!({"ok": false, "error": format!("fdd run task failed: {e}")}),
        Err(_) => json!({
            "ok": false,
            "timeout": true,
            "error": format!(
                "fdd run timed out after {fdd_timeout_secs}s (OPENFDD_FDD_RUN_TIMEOUT_SECS)"
            ),
        }),
    };
    // Echo the requested building_id when the edge did not surface one, so the
    // UI/MCP always know which site the run was scoped to.
    if let (Some(bid), Some(obj)) = (echo_building_id, result.as_object_mut()) {
        let missing = obj.get("building_id").map(|v| v.is_null()).unwrap_or(true);
        if missing {
            obj.insert("building_id".into(), json!(bid));
        }
    }

    if let Some(ref aid) = action_id {
        let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
        let status = if ok { "ok" } else { "fail" };
        let detail = json!({
            "ok": ok,
            "rules_succeeded": result.get("rules_succeeded"),
            "rules_failed": result.get("rules_failed"),
            "rules_skipped": result.get("rules_skipped"),
            "total_ms": result.get("total_ms"),
            "error": result.get("error"),
        });
        let _ = actions::finish_action(aid, status, Some(detail));
        if let Some(obj) = result.as_object_mut() {
            obj.insert("action_id".into(), json!(aid));
        }
    }

    Ok(Json(result))
}

pub async fn fdd_registry_rules() -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::list_registry_rules())
}

pub async fn fdd_rule_params(Path(rule_id): Path<String>) -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::rule_params_response(&rule_id))
}

pub async fn fdd_cache_status() -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::cache_status())
}

#[derive(Debug, Deserialize)]
pub struct BuildingScopeQuery {
    building_id: Option<String>,
}

impl BuildingScopeQuery {
    fn scoped(&self) -> Option<&str> {
        self.building_id
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
    }
}

pub async fn fdd_equipment(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<BuildingScopeQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, q.building_id.as_deref()) {
        return Err(deny);
    }
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, q.scoped());
    Ok(Json(
        open_fdd_edge_prototype::fdd::registry_api::equipment_response_scoped(
            q.scoped(),
            preferred.as_deref(),
        ),
    ))
}

pub async fn fdd_results(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<BuildingScopeQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, q.building_id.as_deref()) {
        return Err(deny);
    }
    Ok(Json(
        open_fdd_edge_prototype::fdd::registry_api::results_response(q.scoped()),
    ))
}

pub async fn fdd_results_readiness(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<BuildingScopeQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, q.building_id.as_deref()) {
        return Err(deny);
    }
    Ok(Json(
        open_fdd_edge_prototype::fdd::registry_api::readiness_response(q.scoped()),
    ))
}

#[derive(Debug, Deserialize)]
pub struct FddSeriesQuery {
    /// Optional for MT authz probes (`?building_id=` only → empty ok envelope).
    #[serde(default)]
    equipment_id: Option<String>,
    #[serde(default)]
    rule_id: Option<String>,
    #[serde(default)]
    building_id: Option<String>,
}

pub async fn fdd_series(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<FddSeriesQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) =
        deny_if_building_out_of_scope(&state, &headers, query.building_id.as_deref())
    {
        return Err(deny);
    }
    let equipment_id = query
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let rule_id = query
        .rule_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    // Authz / inventory probes pass building_id alone — return an empty ok
    // envelope (200) rather than 400 from missing required query fields.
    let (Some(equipment_id), Some(rule_id)) = (equipment_id, rule_id) else {
        return Ok(Json(json!({
            "ok": true,
            "rows": [],
            "roles": [],
            "building_id": query.building_id,
            "equipment_id": query.equipment_id,
            "rule_id": query.rule_id,
        })));
    };
    let equipment_id = equipment_id.to_string();
    let rule_id = rule_id.to_string();
    let building_id = query.building_id.clone();
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, building_id.as_deref());
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::fdd::registry_api::series_response_scoped(
            &equipment_id,
            &rule_id,
            building_id.as_deref(),
            preferred.as_deref(),
        )
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("series task failed: {e}")}));
    Ok(Json(result))
}

pub async fn fdd_roles() -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::roles_response())
}

/// Canonical snake_case cookbook roles for Data Model Select.
pub async fn fdd_cookbook_roles() -> Json<Value> {
    let roles = fdd_core::cookbook_role_catalog();
    Json(json!({
        "ok": true,
        "roles": roles,
        "count": roles.len(),
    }))
}

#[derive(Debug, Deserialize)]
pub struct ActionsQuery {
    #[serde(default)]
    pub limit: Option<usize>,
}

pub async fn list_actions(Query(q): Query<ActionsQuery>) -> Json<Value> {
    Json(actions::list_actions(q.limit.unwrap_or(10)))
}

pub async fn delete_one_action(Path(id): Path<String>) -> (StatusCode, Json<Value>) {
    match actions::delete_action(&id) {
        Ok(v) => (StatusCode::OK, Json(v)),
        Err(e) => (
            StatusCode::NOT_FOUND,
            Json(json!({ "ok": false, "error": e })),
        ),
    }
}

pub async fn clear_actions() -> (StatusCode, Json<Value>) {
    match actions::clear_actions() {
        Ok(v) => (StatusCode::OK, Json(v)),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({ "ok": false, "error": e })),
        ),
    }
}

#[derive(Debug, Deserialize)]
pub struct SessionConfigQuery {
    #[serde(default)]
    pub building_id: Option<String>,
}

/// `openfdd_session_v1` session/fault settings (#515) — persisted per workspace.
/// Wave O9: `building_id` query/body is ACL-gated when multi-tenant is on.
pub async fn fdd_session_config_get(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<SessionConfigQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, q.building_id.as_deref()) {
        return Err(deny);
    }
    Ok(Json(
        open_fdd_edge_prototype::fdd::session_config::get_session_config(),
    ))
}

pub async fn fdd_session_config_put(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let building_id = body
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, building_id.as_deref()) {
        return Err(deny);
    }
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::fdd::session_config::put_session_config(&body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("session config task: {e}")}));
    if result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        if let Some(bid) = building_id.as_deref() {
            open_fdd_edge_prototype::fdd::registry_api::mark_building_results_dirty(
                bid,
                "session_config",
            );
        }
    }
    Ok(Json(result))
}

#[utoipa::path(
    get,
    path = "/api/fdd/status",
    tag = "central",
    security(("bearerAuth" = [])),
    responses((status = 200, description = "FDD rules workspace status", body = FddStatusResponse))
)]
pub async fn fdd_status() -> Json<FddStatusResponse> {
    let reg = open_fdd_edge_prototype::fdd::registry_api::list_registry_rules();
    let count = reg.get("count").and_then(|v| v.as_u64()).unwrap_or(0);
    let rules_dir = reg
        .get("rules_dir")
        .and_then(|v| v.as_str())
        .unwrap_or("sql_rules")
        .to_string();
    let rules_dir_exists = std::path::Path::new(&rules_dir)
        .join("registry.yaml")
        .exists();
    Json(FddStatusResponse {
        ok: true,
        rules_dir: rules_dir.clone(),
        rules_dir_exists,
        rule_count: count,
        hint: if count == 0 {
            Some("set OPENFDD_SQL_RULES_DIR or ship sql_rules/ in the image".into())
        } else {
            Some("POST /api/fdd/run with mode=registry (typed params; no raw SQL)".into())
        },
    })
}

fn mqtt_enabled() -> bool {
    matches!(
        std::env::var("OPENFDD_MQTT_ENABLED")
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "1" | "true" | "yes" | "on"
    )
}

// --- CSV import (UT3) — same handlers as edge lib; execute also fills parquet cache ---

fn content_type(headers: &HeaderMap) -> String {
    headers
        .get(header::CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string()
}

pub async fn csv_preview(headers: HeaderMap, body: Bytes) -> Json<Value> {
    let ct = content_type(&headers);
    if ct.contains("application/json") {
        let v: Value = serde_json::from_slice(&body).unwrap_or(json!({}));
        return Json(open_fdd_edge_prototype::csv_ingest::preview_json_handler(
            &v,
        ));
    }
    Json(open_fdd_edge_prototype::csv_ingest::preview_handler(
        &ct, &body, None,
    ))
}

/// `openfdd_package_v1` zip upload (#514): multipart, JSON base64, or raw zip body.
pub async fn csv_import_package(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let ct = content_type(&headers);
    let peeked_building =
        match open_fdd_edge_prototype::csv_ingest::package::peek_package_building_id(&ct, &body) {
            Ok(bid) => {
                if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&bid)) {
                    return Err(deny);
                }
                if let Some(msg) =
                    crate::historian_limits::deny_building_over_size(&workspace_path(), &bid)
                {
                    open_fdd_edge_prototype::auth::audit::log_event(
                        "historian_size_cap_deny",
                        json!({ "building_id": bid, "surface": "csv/import/package" }),
                    );
                    return Err((
                        StatusCode::FORBIDDEN,
                        Json(json!({"ok": false, "error": msg})),
                    ));
                }
                Some(bid)
            }
            Err(e) if crate::tenant::multi_tenant_enabled() => {
                return Err((
                    StatusCode::BAD_REQUEST,
                    Json(json!({"ok": false, "error": e})),
                ));
            }
            Err(_) => None,
        };
    let _import_slot = crate::historian_limits::acquire_import_slot()
        .await
        .map_err(|e| {
            (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"ok": false, "error": e})),
            )
        })?;
    let action_id = actions::start_action(
        "package_import",
        "Package import",
        Some(json!({ "content_type": ct.clone() })),
    )
    .ok();
    let mut result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::import_package_handler(&ct, &body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package import task: {e}")}));
    let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
    if ok {
        // Promote package utilities_v1 → Metering fuel campus for the imported building.
        let _ =
            tokio::task::spawn_blocking(fuel::import::sync_campuses_from_package_utilities).await;
        if let Some(bid) = result
            .get("building_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or(peeked_building)
        {
            open_fdd_edge_prototype::fdd::registry_api::mark_building_results_dirty(
                &bid,
                "package_import",
            );
        }
    }
    open_fdd_edge_prototype::auth::audit::log_event(
        "package_import",
        json!({
            "ok": ok,
            "building_id": result.get("building_id"),
            "surface": "csv/import/package",
        }),
    );
    if let Some(ref aid) = action_id {
        let status = if ok { "ok" } else { "fail" };
        let building_id = result.get("building_id").cloned().unwrap_or(Value::Null);
        let detail = json!({
            "ok": ok,
            "building_id": building_id,
            "equipment_written": result.get("equipment_written"),
            "total_rows": result.get("total_rows"),
            "total_ms": result.get("total_ms"),
            "error": result.get("error"),
        });
        let _ = actions::finish_action(aid, status, Some(detail));
        if let Some(obj) = result.as_object_mut() {
            obj.insert("action_id".into(), json!(aid));
        }
    }
    Ok(Json(result))
}

pub async fn csv_import_package_append(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let ct = content_type(&headers);
    let building_id = if ct.to_ascii_lowercase().contains("application/json") {
        serde_json::from_slice::<Value>(&body).ok().and_then(|v| {
            v.get("building_id")
                .and_then(|b| b.as_str())
                .map(str::to_string)
        })
    } else {
        open_fdd_edge_prototype::csv_ingest::package::peek_package_building_id(&ct, &body).ok()
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, building_id.as_deref()) {
        return Err(deny);
    }
    if let Some(bid) = building_id.as_deref() {
        if let Some(msg) = crate::historian_limits::deny_building_over_size(&workspace_path(), bid)
        {
            open_fdd_edge_prototype::auth::audit::log_event(
                "historian_size_cap_deny",
                json!({ "building_id": bid, "surface": "csv/import/package/append" }),
            );
            return Err((
                StatusCode::FORBIDDEN,
                Json(json!({"ok": false, "error": msg})),
            ));
        }
    }
    let _import_slot = crate::historian_limits::acquire_import_slot()
        .await
        .map_err(|e| {
            (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"ok": false, "error": e})),
            )
        })?;
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::append_package_handler(&ct, &body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package append task: {e}")}));
    if result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        if let Some(bid) = result
            .get("building_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or(building_id)
        {
            open_fdd_edge_prototype::fdd::registry_api::mark_building_results_dirty(
                &bid,
                "package_append",
            );
        }
    }
    Ok(Json(result))
}

/// Edit role assignments for an ingested package equipment, then re-ingest.
pub async fn csv_import_package_roles(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let building_id = body
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::to_string);
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, building_id.as_deref()) {
        return Err(deny);
    }
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::update_package_roles_handler(&body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package roles task: {e}")}));
    if result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        if let Some(bid) = building_id.as_deref() {
            open_fdd_edge_prototype::fdd::registry_api::mark_building_results_dirty(
                bid,
                "package_roles",
            );
        }
    }
    Ok(Json(result))
}

#[derive(Debug, Deserialize)]
pub struct PackageMappingQuery {
    building_id: Option<String>,
    equipment_id: Option<String>,
}

/// Inventory + validation for ingested package column→role maps (P1-M4-03).
pub async fn csv_import_package_mapping(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<PackageMappingQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(building_id) = q
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Ok(Json(json!({
            "ok": false,
            "error": "building_id query parameter required",
        })));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = q
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::get_package_mapping_handler_scoped(
            &building_id,
            equipment_id.as_deref(),
            preferred.as_deref(),
        )
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package mapping task: {e}")}));
    Ok(Json(result))
}

/// Derived Turtle export of package mapping inventory (Wave S). Not FDD SoT.
pub async fn csv_import_package_mapping_ttl(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<PackageMappingQuery>,
) -> Result<axum::response::Response, (StatusCode, Json<Value>)> {
    use axum::response::IntoResponse;

    let Some(building_id) = q
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id query parameter required",
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = q
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let inventory = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::get_package_mapping_handler_scoped(
            &building_id,
            equipment_id.as_deref(),
            preferred.as_deref(),
        )
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package mapping task: {e}")}));

    if inventory.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        let status = if inventory.get("error").is_some() {
            StatusCode::BAD_REQUEST
        } else {
            StatusCode::OK
        };
        return Err((status, Json(inventory)));
    }

    let ttl =
        open_fdd_edge_prototype::csv_ingest::data_model_ttl::package_mapping_to_turtle(&inventory);
    Ok((
        [
            (
                axum::http::header::CONTENT_TYPE,
                "text/turtle; charset=utf-8",
            ),
            (axum::http::header::CACHE_CONTROL, "no-store"),
        ],
        ttl,
    )
        .into_response())
}

/// Native `openfdd_semantic_meta_v1` JSON export (C3). Empty when no sidecar persisted.
pub async fn csv_import_package_mapping_semantic_meta(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<PackageMappingQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(building_id) = q
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id query parameter required",
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let result = tokio::task::spawn_blocking(move || {
        let root = open_fdd_edge_prototype::historian::store::workspace_dir()
            .join("data")
            .join("csv_buildings")
            .join(&building_id);
        match open_fdd_edge_prototype::csv_ingest::semantic_meta::load_persisted(&root) {
            Ok(Some(meta)) => json!({
                "ok": true,
                "present": true,
                "schema": open_fdd_edge_prototype::csv_ingest::semantic_meta::SCHEMA,
                "meta": meta,
            }),
            Ok(None) => json!({
                "ok": true,
                "present": false,
                "schema": open_fdd_edge_prototype::csv_ingest::semantic_meta::SCHEMA,
                "building_id": building_id,
            }),
            Err(e) => json!({"ok": false, "error": e}),
        }
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("semantic-meta task: {e}")}));
    if result.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        return Err((StatusCode::BAD_REQUEST, Json(result)));
    }
    Ok(Json(result))
}

fn project_haystack_for_building(
    building_id: String,
    equipment_id: Option<String>,
    preferred: Option<String>,
) -> Value {
    let root = open_fdd_edge_prototype::historian::store::workspace_dir()
        .join("data")
        .join("csv_buildings")
        .join(&building_id);
    let meta = match open_fdd_edge_prototype::csv_ingest::semantic_meta::load_persisted(&root) {
        Ok(Some(m)) => m,
        Ok(None) => {
            return json!({
                "ok": false,
                "error": "semantic_meta.json not present for building — strict Haystack projection requires native metadata (C2)",
                "present": false,
                "profile": open_fdd_edge_prototype::csv_ingest::haystack_projection::PROFILE,
            });
        }
        Err(e) => return json!({"ok": false, "error": e}),
    };
    // One validated scope: filter semantic meta AND inventory together (#1123 F4).
    let scoped = match open_fdd_edge_prototype::csv_ingest::semantic_meta::scope_meta(
        &meta,
        equipment_id.as_deref(),
    ) {
        Ok(m) => m,
        Err(e) => {
            return json!({
                "ok": false,
                "error": e,
                "incomplete": true,
                "profile": open_fdd_edge_prototype::csv_ingest::haystack_projection::PROFILE,
            });
        }
    };
    let inventory =
        open_fdd_edge_prototype::csv_ingest::package::get_package_mapping_handler_scoped(
            &building_id,
            equipment_id.as_deref(),
            preferred.as_deref(),
        );
    if inventory.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        return json!({
            "ok": false,
            "error": inventory.get("error").cloned().unwrap_or_else(|| json!("inventory unavailable for scoped Haystack projection")),
            "incomplete": true,
            "inventory": inventory,
            "profile": open_fdd_edge_prototype::csv_ingest::haystack_projection::PROFILE,
        });
    }
    open_fdd_edge_prototype::csv_ingest::haystack_projection::project_strict_json(
        &scoped,
        Some(&inventory),
    )
}

/// Strict Haystack Turtle (`ofdd_haystack_projection_v1`) from native semantic meta.
pub async fn csv_import_package_mapping_haystack_ttl(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<PackageMappingQuery>,
) -> Result<axum::response::Response, (StatusCode, Json<Value>)> {
    use axum::response::IntoResponse;

    let Some(building_id) = q
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id query parameter required",
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = q
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let projected = tokio::task::spawn_blocking(move || {
        project_haystack_for_building(building_id, equipment_id, preferred)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("haystack projection task: {e}")}));

    if projected.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        let status = if projected.get("present") == Some(&json!(false)) {
            StatusCode::NOT_FOUND
        } else {
            StatusCode::BAD_REQUEST
        };
        return Err((status, Json(projected)));
    }
    let ttl = projected
        .get("turtle")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    Ok((
        [
            (
                axum::http::header::CONTENT_TYPE,
                "text/turtle; charset=utf-8",
            ),
            (axum::http::header::CACHE_CONTROL, "no-store"),
        ],
        ttl,
    )
        .into_response())
}

#[derive(Debug, Deserialize)]
pub struct HaystackDatasetQuery {
    building_id: Option<String>,
    equipment_id: Option<String>,
    /// When true, include full Turtle bytes in the JSON envelope.
    #[serde(default)]
    include_turtle: Option<bool>,
}

/// Central scoped Haystack RDF dataset from committed authority + pinned defs (C4 H8).
pub async fn csv_import_package_mapping_haystack_dataset(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<HaystackDatasetQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(building_id) = q
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id query parameter required",
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = q
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let include_turtle = q.include_turtle.unwrap_or(false);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let cache = state.haystack_rdf.clone();
    let result = tokio::task::spawn_blocking(move || {
        cache.get_or_materialize(&building_id, equipment_id.as_deref(), preferred.as_deref())
    })
    .await
    .unwrap_or_else(|e| Err(json!({"ok": false, "error": format!("haystack dataset task: {e}")})));

    match result {
        Ok(snap) => Ok(Json(snap.to_json(include_turtle))),
        Err(err) => {
            let status = if err.get("present") == Some(&json!(false)) {
                StatusCode::NOT_FOUND
            } else {
                StatusCode::BAD_REQUEST
            };
            Err((status, Json(err)))
        }
    }
}

/// Product-central SPARQL honesty (C4 Option B). JWT-gated via router layer.
/// UNAVAILABLE cannot close #1002 graph-driven delivery.
pub async fn central_package_sparql_unavailable() -> (StatusCode, Json<Value>) {
    (
        StatusCode::NOT_IMPLEMENTED,
        Json(crate::haystack_rdf::sparql_unavailable()),
    )
}

pub async fn central_package_sparql_catalog_unavailable() -> (StatusCode, Json<Value>) {
    (
        StatusCode::NOT_IMPLEMENTED,
        Json(crate::haystack_rdf::sparql_unavailable()),
    )
}

/// Strict Haystack projection JSON envelope (Turtle + omission report).
pub async fn csv_import_package_mapping_haystack_projection(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<PackageMappingQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(building_id) = q
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id query parameter required",
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = q
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let projected = tokio::task::spawn_blocking(move || {
        project_haystack_for_building(building_id, equipment_id, preferred)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("haystack projection task: {e}")}));

    if projected.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        let status = if projected.get("present") == Some(&json!(false)) {
            StatusCode::NOT_FOUND
        } else {
            StatusCode::BAD_REQUEST
        };
        return Err((status, Json(projected)));
    }
    Ok(Json(projected))
}

#[derive(Debug, Deserialize)]
pub struct PackageBuildingsQuery {
    #[serde(default)]
    pub building_id: Option<String>,
}

/// List ingested package buildings under workspace csv_buildings.
/// Multi-tenant: listing without `building_id` is allowed and filtered to scope.
/// Optional `building_id` must be in scope (foreign → 403); response still filtered.
pub async fn csv_import_package_buildings(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<PackageBuildingsQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    // List endpoint: only deny when a concrete foreign building_id is supplied.
    // Missing building_id must not 403 — Sites picker has no pre-selected site.
    let bid = q
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    if let Some(b) = bid {
        if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(b)) {
            return Err(deny);
        }
    }
    let result = tokio::task::spawn_blocking(
        open_fdd_edge_prototype::csv_ingest::package::list_package_buildings_handler,
    )
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package buildings task: {e}")}));
    if !crate::tenant::multi_tenant_enabled() {
        return Ok(Json(result));
    }
    let ctx = resolve_tenant_context(&state, &headers);
    let mut filtered = result;
    if let Some(arr) = filtered.get_mut("buildings").and_then(|v| v.as_array_mut()) {
        ctx.retain_allowed_package_buildings(arr);
    }
    Ok(Json(filtered))
}

pub async fn csv_plan(Json(body): Json<Value>) -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::plan_handler(&body))
}

pub async fn csv_preflight(Json(body): Json<Value>) -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::preflight_handler(
        &body,
    ))
}

pub async fn csv_execute(Json(body): Json<Value>) -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::execute_handler(&body))
}

#[derive(Debug, Deserialize)]
pub struct SessionListQuery {
    pub limit: Option<usize>,
}

pub async fn csv_list_sessions(Query(q): Query<SessionListQuery>) -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::list_sessions_handler(
        q.limit.unwrap_or(50),
    ))
}

pub async fn csv_latest_planned() -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::latest_planned_session_handler())
}

pub async fn csv_get_session(Path(session_id): Path<String>) -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::get_session_handler(
        &session_id,
    ))
}

pub async fn csv_delete_session(Path(session_id): Path<String>) -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::delete_session_handler(
        &session_id,
    ))
}

#[derive(Debug, Deserialize)]
pub struct FusionPreviewQuery {
    pub limit: Option<usize>,
}

pub async fn csv_fusion_preview(
    Path(session_id): Path<String>,
    Query(q): Query<FusionPreviewQuery>,
) -> Json<Value> {
    let limit = open_fdd_edge_prototype::csv_ingest::fusion_preview_limit_from_query(
        q.limit.map(|n| n.to_string()).as_deref(),
    );
    Json(open_fdd_edge_prototype::csv_ingest::fusion_preview_handler(
        &session_id,
        limit,
    ))
}

#[derive(Debug, Deserialize)]
pub struct DatasetsListQuery {
    /// Optional building/site filter. Required for non-hub-admin when MT is on
    /// (via [`deny_if_building_out_of_scope`]). Foreign building → 403.
    pub building_id: Option<String>,
    /// Alias used by some clients / delete parity (`?id=`).
    pub id: Option<String>,
}

pub async fn csv_list_datasets(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<DatasetsListQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let building_id = q
        .building_id
        .as_deref()
        .or(q.id.as_deref())
        .map(str::trim)
        .filter(|s| !s.is_empty());
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, building_id) {
        return Err(deny);
    }
    crate::building_sessions::note_catalog_list();
    let mut body = open_fdd_edge_prototype::csv_ingest::list_datasets();
    // When a building filter is present, only return that building's rows
    // (defense in depth after ACL). Hub-admin unfiltered list stays full.
    if let Some(bid) = building_id {
        if let Some(arr) = body.get_mut("datasets").and_then(|v| v.as_array_mut()) {
            arr.retain(|d| {
                d.get("id")
                    .or_else(|| d.get("building_id"))
                    .or_else(|| d.get("dataset_id"))
                    .and_then(|v| v.as_str())
                    == Some(bid)
            });
        }
    } else if crate::tenant::multi_tenant_enabled() {
        // Non-admin path never reaches here (deny requires building_id).
        // Hub admin: still filter to nothing extra — leave registry as-is.
    }
    Ok(Json(body))
}

#[derive(Debug, Deserialize)]
pub struct DatasetIdQuery {
    pub id: Option<String>,
    pub building_id: Option<String>,
}

pub async fn csv_delete_dataset(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<DatasetIdQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(id) =
        q.id.as_deref()
            .or(q.building_id.as_deref())
            .filter(|s| !s.is_empty())
            .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "id query required"})),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&id)) {
        return Err(deny);
    };
    let action_id = actions::start_action(
        "dataset_delete",
        &format!("Delete site · {id}"),
        Some(json!({ "building_id": id, "dataset_id": id })),
    )
    .ok();
    let id_for_task = id.clone();
    let outcome = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::delete_dataset(&id_for_task)
    })
    .await
    .unwrap_or_else(|e| Err(format!("dataset delete task failed: {e}")));
    let mut jobs_deleted = 0usize;
    let mut job_errors: Vec<String> = Vec::new();
    if outcome.is_ok() {
        let (n, errs) = crate::jobs::delete_jobs_for_site(&id);
        jobs_deleted = n;
        job_errors = errs;
    }
    let jobs_ok = job_errors.is_empty();
    let (ok, error) = match &outcome {
        Ok(()) if jobs_ok => (true, None),
        Ok(()) => (
            false,
            Some(format!(
                "site data purged but job delete failed: {}",
                job_errors.join("; ")
            )),
        ),
        Err(e) => (false, Some(e.clone())),
    };
    if let Some(ref aid) = action_id {
        let status = if ok { "ok" } else { "fail" };
        let _ = actions::finish_action(
            aid,
            status,
            Some(json!({
                "ok": ok,
                "building_id": id,
                "dataset_id": id,
                "jobs_deleted": jobs_deleted,
                "job_errors": job_errors,
                "error": error,
            })),
        );
    }
    if ok {
        Ok(Json(json!({
            "ok": true,
            "action_id": action_id,
            "jobs_deleted": jobs_deleted,
        })))
    } else {
        Ok(Json(json!({
            "ok": false,
            "error": error,
            "action_id": action_id,
            "jobs_deleted": jobs_deleted,
            "job_errors": job_errors,
        })))
    }
}

#[derive(Debug, Deserialize)]
pub struct DatasetPreviewQuery {
    pub offset: Option<usize>,
    pub limit: Option<usize>,
}

pub async fn csv_preview_dataset(
    Path(dataset_id): Path<String>,
    Query(q): Query<DatasetPreviewQuery>,
) -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::preview_dataset(
        &dataset_id,
        q.offset.unwrap_or(0) as u64,
        q.limit.unwrap_or(100) as u64,
    ))
}

pub async fn health_stack() -> Json<Value> {
    Json(open_fdd_edge_prototype::dashboard::stack_health())
}

pub async fn building_snapshot() -> Json<Value> {
    Json(open_fdd_edge_prototype::dashboard::building_snapshot())
}

pub async fn dashboard_summary() -> Json<Value> {
    Json(open_fdd_edge_prototype::dashboard::summary())
}

pub async fn faults_status() -> Json<Value> {
    Json(open_fdd_edge_prototype::faults::status_json())
}

pub async fn faults_summary() -> Json<Value> {
    Json(open_fdd_edge_prototype::faults::summary_json())
}

pub async fn export_meta() -> Json<Value> {
    Json(open_fdd_edge_prototype::export::meta_json())
}

pub async fn data_management_summary() -> Json<Value> {
    Json(open_fdd_edge_prototype::data_management::storage_summary())
}

fn data_budget_root() -> std::path::PathBuf {
    crate::analytics::historian::parquet_root_base()
}

pub async fn data_management_budget(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _admin = require_hub_admin(&state, &headers)?;
    let budget = fdd_store::DataBudget::from_env();
    let root = data_budget_root();
    let objects = fdd_store::collect_budget_objects(&root);
    let used: u64 = objects.iter().map(|o| o.bytes).sum();
    let plan = fdd_store::plan_oldest_first(&objects, budget.budget_bytes);
    Ok(Json(json!({
        "ok": true,
        "enabled": budget.enabled,
        "budget_bytes": budget.budget_bytes,
        "budget_gib": budget.budget_bytes / fdd_store::GIB,
        "default_budget_gib": fdd_store::DEFAULT_LOCAL_DATA_BUDGET_GIB,
        "reserved_free_percent": budget.reserved_free_percent,
        "used_bytes": used,
        "bytes_over_budget": fdd_store::bytes_over_budget(used, budget.budget_bytes),
        "object_count": objects.len(),
        "would_drop_count": plan.drop.len(),
        "would_drop_bytes": plan.drop_bytes,
        "keep_bytes": plan.keep_bytes,
        "policy": "oldest-first; newest parquet kept; backups and archives excluded",
        "storage_root": root.display().to_string(),
    })))
}

#[derive(Debug, Deserialize)]
pub struct DataBudgetApplyBody {
    /// Exact confirm phrase: `APPLY DATA BUDGET`.
    #[serde(default)]
    pub confirm: String,
}

pub async fn data_management_retention_apply(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<DataBudgetApplyBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    if body.confirm.trim() != "APPLY DATA BUDGET" {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "confirm must be the phrase APPLY DATA BUDGET",
            })),
        ));
    }
    let budget = fdd_store::DataBudget::from_env();
    let root = data_budget_root();
    tracing::info!(
        target: "security_audit",
        event = "data_budget_apply",
        subject = %admin.sub,
        enabled = budget.enabled,
        budget_bytes = budget.budget_bytes,
        "hub admin requested oldest-first data budget eviction"
    );
    let report = fdd_store::apply_data_budget(&root, &budget).map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e.to_string()})),
        )
    })?;
    Ok(Json(json!({
        "ok": true,
        "applied": report.applied,
        "reason": report.reason,
        "dropped_count": report.dropped.len(),
        "dropped_bytes": report.dropped_bytes,
        "keep_bytes": report.keep_bytes,
    })))
}

pub async fn building_sessions_list(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _admin = require_hub_admin(&state, &headers)?;
    let mut body = crate::building_sessions::snapshot();
    if let Some(obj) = body.as_object_mut() {
        obj.insert("ok".into(), json!(true));
    }
    Ok(Json(body))
}

#[derive(Debug, Deserialize)]
pub struct BuildingLeaveBody {
    #[serde(default)]
    pub building_id: String,
}

pub async fn building_session_leave(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<BuildingLeaveBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _user = state.auth.user_from_headers(&headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    let building_id = body.building_id.trim();
    if building_id.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "building_id required"})),
        ));
    }
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(building_id)) {
        return Err(deny);
    }
    let left = crate::building_sessions::leave(building_id);
    Ok(Json(json!({
        "ok": true,
        "left": left,
        "building_id": building_id,
    })))
}

pub async fn host_stats() -> Json<Value> {
    let mut body = open_fdd_edge_prototype::ops::host_stats::stats_json();
    if let Some(obj) = body.as_object_mut() {
        let status = fdd_store::shared_compaction_coordinator().status();
        obj.insert(
            "compaction_coordinator".to_string(),
            json!({
                "mode": status.mode,
                "scanners": status.scanners,
                "compacting": status.compacting,
            }),
        );
        if let Some(dm) = obj
            .get_mut("data_management")
            .and_then(|v| v.as_object_mut())
        {
            if let Some(parquet) = dm.get_mut("parquet").and_then(|v| v.as_object_mut()) {
                parquet.insert("compaction_status".to_string(), json!(status.mode));
            }
        }
    }
    Json(body)
}

#[derive(Debug, Deserialize)]
pub struct HistorianCompactionBody {
    /// Required write confirm (matches other mutating admin APIs).
    #[serde(default)]
    pub confirm: bool,
    /// Wait for DataFusion scan leases to drain (default: fail closed).
    #[serde(default)]
    pub wait: bool,
    /// Plan only — do not mutate Parquet.
    #[serde(default)]
    pub plan_only: bool,
}

pub async fn historian_compaction_status(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _admin = require_hub_admin(&state, &headers)?;
    let coord = fdd_store::shared_compaction_coordinator().status();
    let stats = fdd_store::HistorianConfig::from_env()
        .ok()
        .and_then(|cfg| fdd_store::local_historian_stats_from_config(&cfg).ok());
    Ok(Json(json!({
        "ok": true,
        "coordinator": {
            "mode": coord.mode,
            "scanners": coord.scanners,
            "compacting": coord.compacting,
        },
        "historian": stats,
    })))
}

pub async fn historian_compaction_run(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<HistorianCompactionBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let admin = require_hub_admin(&state, &headers)?;
    if !body.confirm {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "confirm:true required"})),
        ));
    }
    tracing::info!(
        target: "security_audit",
        event = "historian_compaction_requested",
        subject = %admin.sub,
        plan_only = body.plan_only,
        wait = body.wait,
        "hub admin requested historian compaction"
    );

    let config = fdd_store::HistorianConfig::from_env().map_err(|e| {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({"ok": false, "error": e.to_string()})),
        )
    })?;
    let compactor = fdd_store::ParquetCompactor::from_config(&config).map_err(|e| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": e.to_string()})),
        )
    })?;

    if body.plan_only {
        let plans = compactor.plan_history().map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": e.to_string()})),
            )
        })?;
        return Ok(Json(json!({
            "ok": true,
            "plan_only": true,
            "plans": plans,
            "coordinator": fdd_store::shared_compaction_coordinator().status(),
        })));
    }

    let run = if body.wait {
        tokio::task::spawn_blocking(move || fdd_store::compact_history_wait(&compactor))
    } else {
        tokio::task::spawn_blocking(move || fdd_store::compact_history_fail_closed(&compactor))
    }
    .await
    .map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": format!("compaction join: {e}")})),
        )
    })?;

    match run {
        Ok((results, summary)) => Ok(Json(json!({
            "ok": true,
            "results": results,
            "summary": summary,
            "coordinator": fdd_store::shared_compaction_coordinator().status(),
        }))),
        Err(e) => {
            let msg = e.to_string();
            let status = if msg.contains("scan") || msg.contains("compaction in progress") {
                StatusCode::CONFLICT
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            };
            Err((status, Json(json!({"ok": false, "error": msg}))))
        }
    }
}

pub async fn fdd_schema_tables() -> Json<Value> {
    match serde_json::from_str(&open_fdd_edge_prototype::fdd::wires::api::schema_tables_json()) {
        Ok(v) => Json(v),
        Err(e) => Json(json!({"ok": false, "error": e.to_string()})),
    }
}

pub async fn fdd_rules_list() -> Json<Value> {
    match serde_json::from_str(&open_fdd_edge_prototype::fdd::wires::api::list_rules_json()) {
        Ok(v) => Json(v),
        Err(e) => Json(json!({"ok": false, "error": e.to_string()})),
    }
}

const REPORTS_ARTIFACTS_GONE: &str = "reports artifacts removed; use FDD Plots and WattLab dumps";

fn reports_artifacts_gone() -> (StatusCode, Json<Value>) {
    (
        StatusCode::GONE,
        Json(json!({"ok": false, "error": REPORTS_ARTIFACTS_GONE})),
    )
}

/// Reports list/draft/PDF surface removed; keep route so clients get 410 not 404.
pub async fn reports_list() -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_engineering_findings() -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_templates() -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_draft(Json(_body): Json<Value>) -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_get(Path(_report_id): Path<String>) -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_patch(
    Path(_report_id): Path<String>,
    Json(_body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_delete(Path(_report_id): Path<String>) -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_render_pdf(Path(_report_id): Path<String>) -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

pub async fn reports_download_pdf(Path(_report_id): Path<String>) -> (StatusCode, Json<Value>) {
    reports_artifacts_gone()
}

#[derive(Debug, Deserialize)]
struct JobsListQuery {
    #[serde(default)]
    include_archived: Option<bool>,
    status: Option<String>,
    site_id: Option<String>,
    tag: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CreateJobBody {
    job_name: String,
    #[serde(default)]
    site_id: Option<String>,
    #[serde(default)]
    site_name: Option<String>,
    /// OFDD-076b: agents may send building_id; maps to site_id when site_id empty.
    #[serde(default)]
    building_id: Option<String>,
    #[serde(default)]
    building_name: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    created_by: Option<String>,
}

#[derive(Debug, Deserialize)]
struct PatchJobBody {
    #[serde(default)]
    job_name: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    tags: Option<Vec<String>>,
    #[serde(default)]
    site_id: Option<String>,
    #[serde(default)]
    expected_meta_revision: Option<String>,
}

#[derive(Debug, Deserialize)]
struct DuplicateJobBody {
    #[serde(default)]
    new_name: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CreateRunBody {
    #[serde(default = "default_run_type")]
    run_type: String,
    #[serde(default)]
    fingerprint_components: Value,
    #[serde(default)]
    engine_version: String,
    #[serde(default)]
    rule_registry_hash: String,
}

fn default_run_type() -> String {
    "fdd_registry".into()
}

#[derive(Debug, Deserialize)]
struct StaleBody {
    fingerprint_components: Value,
}

fn job_err(e: jobs::JobError) -> (StatusCode, Json<Value>) {
    (e.status_code(), Json(e.to_json()))
}

async fn jobs_list(
    Query(q): Query<JobsListQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let include = q.include_archived.unwrap_or(true);
    let jobs = jobs::list_jobs(
        include,
        q.status.as_deref(),
        q.site_id.as_deref(),
        q.tag.as_deref(),
    );
    Ok(Json(json!({"ok": true, "jobs": jobs})))
}

async fn jobs_create(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<CreateJobBody>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    if let Err(err) = enforce_tenant_budget(
        &state,
        &headers,
        crate::tenant_budget::BudgetKind::JobCreate,
    ) {
        return Err((
            StatusCode::TOO_MANY_REQUESTS,
            Json(json!({"ok": false, "error": err, "budget_exceeded": true})),
        ));
    }
    // OFDD-076b: building_id → site_id when site_id absent; also fill building_name.
    let building_id = body
        .building_id
        .as_ref()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty());
    let site_id = body
        .site_id
        .as_ref()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .or_else(|| building_id.clone());
    let building_name = body
        .building_name
        .as_ref()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .or_else(|| building_id.clone());
    let meta = jobs::create_job(
        &body.job_name,
        site_id,
        body.site_name,
        building_name,
        body.description,
        body.tags,
        body.created_by,
    )
    .map_err(job_err)?;
    Ok((StatusCode::CREATED, Json(json!({"ok": true, "job": meta}))))
}

async fn jobs_get(Path(job_id): Path<String>) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let meta = jobs::load_job(&job_id).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "job": meta})))
}

async fn jobs_patch(
    Path(job_id): Path<String>,
    Json(body): Json<PatchJobBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let mut meta = jobs::load_job(&job_id).map_err(job_err)?;
    let expected = body
        .expected_meta_revision
        .unwrap_or_else(|| meta.meta_revision.clone());
    if let Some(name) = body.job_name {
        let n = name.trim();
        if n.is_empty() {
            return Err((
                StatusCode::BAD_REQUEST,
                Json(json!({"ok": false, "error": "job_name is required"})),
            ));
        }
        meta.job_name = n.to_string();
    }
    if let Some(d) = body.description {
        meta.description = Some(d);
    }
    if let Some(tags) = body.tags {
        meta.tags = tags;
    }
    if let Some(sid) = body.site_id {
        meta.site_id = Some(sid);
    }
    let meta = jobs::save_job(meta, Some(&expected)).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "job": meta})))
}

async fn jobs_duplicate(
    Path(job_id): Path<String>,
    body: Option<Json<DuplicateJobBody>>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let new_name = body.and_then(|Json(b)| b.new_name);
    let meta = jobs::duplicate_job(&job_id, new_name.as_deref()).map_err(job_err)?;
    Ok((StatusCode::CREATED, Json(json!({"ok": true, "job": meta}))))
}

async fn jobs_archive(
    Path(job_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let meta = jobs::archive_job(&job_id).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "job": meta})))
}

async fn jobs_restore(
    Path(job_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let meta = jobs::restore_job(&job_id).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "job": meta})))
}

async fn jobs_delete(Path(job_id): Path<String>) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    jobs::delete_job(&job_id).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "deleted": true, "job_id": job_id})))
}

async fn jobs_create_run(
    Path(job_id): Path<String>,
    Json(body): Json<CreateRunBody>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let run = jobs::create_run(
        &job_id,
        &body.run_type,
        body.fingerprint_components,
        &body.engine_version,
        &body.rule_registry_hash,
    )
    .map_err(job_err)?;
    Ok((StatusCode::CREATED, Json(json!({"ok": true, "run": run}))))
}

async fn jobs_get_run(
    Path((job_id, run_id)): Path<(String, String)>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let run = jobs::load_run(&job_id, &run_id).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "run": run})))
}

#[derive(Debug, Deserialize)]
struct PatchRunBody {
    status: String,
    #[serde(default)]
    error: Option<String>,
}

async fn jobs_patch_run(
    Path((job_id, run_id)): Path<(String, String)>,
    Json(body): Json<PatchRunBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let run =
        jobs::update_run_status(&job_id, &run_id, &body.status, body.error).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "run": run})))
}

async fn jobs_eval_stale(
    Path((job_id, run_id)): Path<(String, String)>,
    Json(body): Json<StaleBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let (stale, reasons) =
        jobs::evaluate_stale(&job_id, &run_id, &body.fingerprint_components).map_err(job_err)?;
    Ok(Json(json!({
        "ok": true,
        "stale": stale,
        "reasons": reasons,
    })))
}

#[derive(Debug, Deserialize)]
struct PutFindingsBody {
    findings: Value,
    #[serde(default)]
    findings_revision: Option<String>,
}

async fn jobs_get_findings(
    Path(job_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let findings = jobs::load_findings(&job_id).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "findings": findings})))
}

async fn jobs_put_findings(
    Path(job_id): Path<String>,
    Json(body): Json<PutFindingsBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let meta =
        jobs::save_findings(&job_id, body.findings, body.findings_revision).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "job": meta})))
}

async fn jobs_get_dispositions(
    Path(job_id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let dispositions = jobs::load_dispositions(&job_id).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "dispositions": dispositions})))
}

async fn jobs_put_dispositions(
    Path(job_id): Path<String>,
    Json(body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    jobs::save_dispositions(&job_id, body).map_err(job_err)?;
    Ok(Json(json!({"ok": true})))
}

async fn jobs_create_wattlab_handoff(
    Path(job_id): Path<String>,
    Json(body): Json<Value>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let handoff = jobs::save_wattlab_handoff(&job_id, body).map_err(job_err)?;
    Ok((
        StatusCode::CREATED,
        Json(json!({"ok": true, "handoff": handoff})),
    ))
}

async fn jobs_create_engineering_export(
    Path(job_id): Path<String>,
    Json(body): Json<engineering_bundle::CreateExportRequest>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let export = engineering_bundle::create_export(&job_id, body)
        .await
        .map_err(job_err)?;
    Ok((
        StatusCode::CREATED,
        Json(json!({"ok": true, "export": export})),
    ))
}

async fn jobs_download_engineering_export(
    Path((job_id, export_id)): Path<(String, String)>,
) -> Result<(StatusCode, HeaderMap, Vec<u8>), (StatusCode, Json<Value>)> {
    let loaded =
        tokio::task::spawn_blocking(move || engineering_bundle::load_export(&job_id, &export_id))
            .await
            .map_err(|e| {
                (
                    StatusCode::INTERNAL_SERVER_ERROR,
                    Json(json!({"ok": false, "error": format!("export download task: {e}")})),
                )
            })?
            .map_err(job_err)?;
    let (artifact, bytes) = loaded;
    let mut headers = HeaderMap::new();
    headers.insert(header::CONTENT_TYPE, "application/zip".parse().unwrap());
    headers.insert(
        header::CONTENT_DISPOSITION,
        format!("attachment; filename=\"{}\"", artifact.filename)
            .parse()
            .unwrap(),
    );
    Ok((StatusCode::OK, headers, bytes))
}

async fn jobs_create_wattlab_dump(
    Path(job_id): Path<String>,
    Json(body): Json<wattlab_dump::CreateDumpRequest>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let dump = wattlab_dump::create_dump(&job_id, body)
        .await
        .map_err(job_err)?;
    Ok((
        StatusCode::CREATED,
        Json(json!({"ok": true, "dump": dump, "export": dump})),
    ))
}

async fn jobs_download_wattlab_dump(
    Path((job_id, dump_id)): Path<(String, String)>,
) -> Result<(StatusCode, HeaderMap, Vec<u8>), (StatusCode, Json<Value>)> {
    let loaded = tokio::task::spawn_blocking(move || wattlab_dump::load_dump(&job_id, &dump_id))
        .await
        .map_err(|e| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": format!("WattLab download task: {e}")})),
            )
        })?
        .map_err(job_err)?;
    let (artifact, bytes) = loaded;
    let mut headers = HeaderMap::new();
    headers.insert(header::CONTENT_TYPE, "application/zip".parse().unwrap());
    let disposition = format!("attachment; filename=\"{}\"", artifact.filename);
    headers.insert(
        header::CONTENT_DISPOSITION,
        disposition.parse().map_err(|_| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": "invalid WattLab dump filename"})),
            )
        })?,
    );
    Ok((StatusCode::OK, headers, bytes))
}

/// Queue an external EnergyPlus run (Milestone D4).
///
/// Central **persists** `QUEUED` metadata under `wattlab/runs/*.json` only.
/// It does not attach to a Docker socket or execute EnergyPlus in-process;
/// an approved external runner claims the record and later attaches artifacts.
async fn jobs_queue_eplus_run(
    Path(job_id): Path<String>,
    Json(body): Json<eplus_runner::JobRunRequest>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let run = eplus_runner::queue_external_run(&job_id, body).map_err(job_err)?;
    Ok((StatusCode::CREATED, Json(json!({"ok": true, "run": run}))))
}

/// Record artifact metadata for an external E+ run (hashes/paths only — no bytes).
async fn jobs_attach_eplus_artifact(
    Path((job_id, eplus_run_id)): Path<(String, String)>,
    Json(body): Json<eplus_runner::AttachArtifactMeta>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let run = eplus_runner::attach_artifact_meta(&job_id, &eplus_run_id, body).map_err(job_err)?;
    Ok(Json(json!({"ok": true, "run": run})))
}

// ---------------------------------------------------------------------------
// Analytics (Milestone C) — typed envelopes, no Plotly JSON
// ---------------------------------------------------------------------------

/// Building ACL + Wave O6 retain-window clamp (start only; never silent mid-query truncate).
fn gate_analytics(
    state: &AppState,
    headers: &HeaderMap,
    req: &mut AnalyticsRequest,
) -> Result<(), (StatusCode, Json<Value>)> {
    if let Some(deny) =
        deny_if_building_out_of_scope(state, headers, req.query.building_id.as_deref())
    {
        return Err(deny);
    }
    let lim = crate::historian_limits::HistorianLimits::load(&workspace_path());
    let before = req.query.start;
    req.query.start = lim.clamp_start(req.query.start);
    if before != req.query.start {
        // Surface clamp in warnings via a light marker on the query path (handlers own envelopes).
        tracing::debug!(
            target: "openfdd_central",
            retain_days = lim.retain_days,
            "analytics start clamped to historian retain floor"
        );
    }
    Ok(())
}

macro_rules! cached_analytics {
    ($query_id:expr, $query_version:expr, $state:expr, $headers:expr, $req:expr, $compute:expr) => {{
        gate_analytics($state, $headers, &mut $req)?;
        crate::analytics::result_cache::respond($query_id, $query_version, &$req, async || {
            $compute.await
        })
        .await
    }};
}

async fn analytics_runtime(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "runtime",
        analytics::QV_RUNTIME,
        &state,
        &headers,
        req,
        analytics::runtime::handle_async(&req)
    )
}

async fn analytics_vav_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "vav-health",
        analytics::vav_health::QV_VAV_HEALTH,
        &state,
        &headers,
        req,
        analytics::vav_health::handle_async(&req)
    )
}

async fn analytics_ahu_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "ahu-health",
        analytics::plant_health::QV_AHU_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_ahu(&req)
    )
}

async fn analytics_ahu_temperature_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "ahu-temperature-health",
        analytics::plant_health::QV_AHU_TEMPERATURE_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_ahu_temperature(&req)
    )
}

async fn analytics_ahu_pressure_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "ahu-pressure-health",
        analytics::plant_health::QV_AHU_PRESSURE_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_ahu_pressure(&req)
    )
}

async fn analytics_ahu_economizer_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "ahu-economizer-health",
        analytics::plant_health::QV_AHU_ECONOMIZER_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_ahu_economizer(&req)
    )
}

async fn analytics_chiller_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "chiller-health",
        analytics::plant_health::QV_CHILLER_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_chiller(&req)
    )
}

async fn analytics_cooling_tower_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "cooling-tower-health",
        analytics::plant_health::QV_COOLING_TOWER_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_cooling_tower(&req)
    )
}

async fn analytics_sensor_faults(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "sensor-faults",
        analytics::plant_health::QV_SENSOR_FAULTS,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_sensor_faults(&req)
    )
}

async fn analytics_pid_hunting(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "pid-hunting",
        analytics::plant_health::QV_PID_HUNTING,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_pid_hunting(&req)
    )
}

async fn analytics_boiler_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "boiler-health",
        analytics::plant_health::QV_BOILER_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_boiler(&req)
    )
}

async fn analytics_hp_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "hp-health",
        analytics::plant_health::QV_HP_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_hp(&req)
    )
}

async fn analytics_zone_other_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "zone-other-health",
        analytics::plant_health::QV_ZONE_OTHER_HEALTH,
        &state,
        &headers,
        req,
        analytics::plant_health::handle_zone_other(&req)
    )
}

async fn analytics_sensor_health(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "sensor-health",
        analytics::QV_SENSOR_HEALTH,
        &state,
        &headers,
        req,
        analytics::sensor_health::handle_async(&req)
    )
}

async fn analytics_schedule(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "schedule",
        analytics::QV_SCHEDULE,
        &state,
        &headers,
        req,
        analytics::schedule::handle_async(&req)
    )
}

async fn analytics_mechanical_cooling(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "mechanical-cooling",
        analytics::QV_MECHANICAL_COOLING,
        &state,
        &headers,
        req,
        analytics::mechanical_cooling::handle_async(&req)
    )
}

async fn analytics_bas_vs_web_oat(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let ctx = resolve_tenant_context(&state, &headers);
    req.read_tenant_id = preferred_tenant_for_building_read(&ctx, req.query.building_id.as_deref());
    cached_analytics!(
        "bas-vs-web-oat",
        "bas-vs-web-oat-v3",
        &state,
        &headers,
        req,
        async {
            let max_points = req.query.max_points.unwrap_or(2000);
            match analytics::historian::bas_vs_web_from_history(
                req.query.equipment_ids.as_deref(),
                max_points,
                req.query.building_id.as_deref(),
                req.read_tenant_id.as_deref(),
            )
            .await
            {
                Ok(Some(env)) => env,
                Ok(None) => analytics::envelope_with_engine(
                    "bas-vs-web-oat-v3",
                    &req.query,
                    vec![
                        "BAS vs web OAT unavailable — need distinct oa_t and web OAT \
                         columns on historian Parquet (site-broadcast join)"
                            .into(),
                    ],
                    analytics::DF_ENGINE,
                ),
                Err(e) => {
                    tracing::warn!(error = %e, "bas-vs-web-oat historian path failed");
                    analytics::envelope(
                        "bas-vs-web-oat-v3",
                        &req.query,
                        vec![format!("bas-vs-web-oat failed: {e}")],
                    )
                }
            }
        }
    )
}

async fn analytics_inspect(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let ctx = resolve_tenant_context(&state, &headers);
    req.read_tenant_id = preferred_tenant_for_building_read(&ctx, req.query.building_id.as_deref());
    cached_analytics!(
        "equipment-inspect",
        "equipment-inspect-v1",
        &state,
        &headers,
        req,
        async {
            let eq = req
                .query
                .equipment_ids
                .as_ref()
                .and_then(|ids| ids.first())
                .map(|s| s.as_str())
                .unwrap_or("");
            let columns: Option<Vec<String>> = req.series.as_ref().and_then(|s| {
                s.get("columns").and_then(|c| c.as_array()).map(|arr| {
                    arr.iter()
                        .filter_map(|v| v.as_str().map(str::to_string))
                        .collect()
                })
            });
            let max_points = req.query.max_points.unwrap_or(2000);
            match analytics::historian::inspect_from_history(
                req.query.building_id.as_deref(),
                eq,
                columns.as_deref(),
                max_points,
                req.read_tenant_id.as_deref(),
            )
            .await
            {
                Ok(Some(env)) => env,
                Ok(None) => analytics::envelope_with_engine(
                    "equipment-inspect-v1",
                    &req.query,
                    vec![
                        "equipment inspection unavailable — need historian parquet for equipment"
                            .into(),
                    ],
                    analytics::DF_ENGINE,
                ),
                Err(e) => {
                    tracing::warn!(error = %e, "equipment inspect historian path failed");
                    analytics::envelope(
                        "equipment-inspect-v1",
                        &req.query,
                        vec![format!("inspect failed: {e}")],
                    )
                }
            }
        }
    )
}

async fn analytics_economizer(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "economizer",
        analytics::QV_ECONOMIZER,
        &state,
        &headers,
        req,
        analytics::economizer::handle_async(&req)
    )
}

async fn analytics_rcx_ahu(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "rcx-ahu",
        analytics::QV_RCX_AHU,
        &state,
        &headers,
        req,
        analytics::rcx::handle_ahu_async(&req)
    )
}

async fn analytics_rcx_vav(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "rcx-vav",
        analytics::QV_RCX_VAV,
        &state,
        &headers,
        req,
        analytics::rcx::handle_vav_async(&req)
    )
}

async fn analytics_rcx_chiller(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "rcx-chiller",
        analytics::plant::QV_RCX_CHILLER,
        &state,
        &headers,
        req,
        analytics::plant::handle_chiller_async(&req)
    )
}

async fn analytics_rcx_boiler(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "rcx-boiler",
        analytics::plant::QV_RCX_BOILER,
        &state,
        &headers,
        req,
        analytics::plant::handle_boiler_async(&req)
    )
}

async fn analytics_rcx_presets_list(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<BuildingScopeQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    // Catalog is static, but inventory policy is tenant_building_acl — foreign
    // building_id must 403 (same posture as GET /api/fdd/results).
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, q.building_id.as_deref()) {
        return Err(deny);
    }
    Ok(Json(json!({
        "ok": true,
        "presets": analytics::rcx_presets::presets_json(),
    })))
}

async fn analytics_rcx_preset(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    gate_analytics(&state, &headers, &mut req)?;
    let action_slot: std::sync::Arc<std::sync::Mutex<Option<String>>> =
        std::sync::Arc::new(std::sync::Mutex::new(None));
    let slot = action_slot.clone();
    let served = crate::analytics::result_cache::serve(
        "rcx-preset",
        "rcx-preset-v1",
        &req,
        async || {
            let preset_id = req
                .query
                .query_version
                .as_deref()
                .or_else(|| {
                    req.series
                        .as_ref()
                        .and_then(|s| s.get("preset_id"))
                        .and_then(|v| v.as_str())
                })
                .unwrap_or("")
                .to_string();
            let building_id = req.query.building_id.clone();
            let max_points = req.query.max_points.unwrap_or(8000);
            let action_id = actions::start_action(
                "analytics_rcx",
                &format!(
                    "RCx preset · {} · {}",
                    building_id.as_deref().unwrap_or("(no building)"),
                    if preset_id.is_empty() {
                        "(none)"
                    } else {
                        &preset_id
                    }
                ),
                Some(json!({
                    "building_id": building_id.clone(),
                    "preset_id": preset_id.clone(),
                })),
            )
            .ok();
            if let Ok(mut guard) = slot.lock() {
                *guard = action_id.clone();
            }
            let mut hard_fail = false;
            let env = match analytics::rcx_presets::run_preset(
                building_id.as_deref(),
                &preset_id,
                max_points,
            )
            .await
            {
                Ok(Some(env)) => env,
                Ok(None) => analytics::envelope_with_engine(
                    "rcx-preset-v1",
                    &req.query,
                    vec![format!(
                        "RCx preset '{preset_id}' unavailable — unknown id or missing historian columns"
                    )],
                    analytics::DF_ENGINE,
                ),
                Err(e) => {
                    hard_fail = true;
                    tracing::warn!(error = %e, preset = %preset_id, "rcx preset failed");
                    analytics::envelope(
                        "rcx-preset-v1",
                        &req.query,
                        vec![format!("rcx preset failed: {e}")],
                    )
                }
            };
            if let Some(ref aid) = action_id {
                let warnings = env.warnings.len();
                let status = if hard_fail { "fail" } else { "ok" };
                let _ = actions::finish_action(
                    aid,
                    status,
                    Some(json!({
                        "ok": status == "ok",
                        "building_id": building_id,
                        "preset_id": preset_id,
                        "warning_count": warnings,
                    })),
                );
            }
            env
        },
    )
    .await?;
    let action_id = action_slot
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .clone();
    let mut body = crate::analytics::result_cache::json_body(&served).0;
    if let Some(obj) = body.as_object_mut() {
        obj.insert("action_id".into(), json!(action_id));
    }
    Ok(Json(body))
}

async fn analytics_metering(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "metering",
        analytics::QV_METERING,
        &state,
        &headers,
        req,
        analytics::metering::handle_async(&req)
    )
}

async fn analytics_mv_change_point(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "mv-change-point",
        analytics::QV_MV_CHANGE_POINT,
        &state,
        &headers,
        req,
        async { analytics::mv_change_point::handle(&req) }
    )
}

async fn analytics_setpoints(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "setpoints",
        analytics::QV_SETPOINTS,
        &state,
        &headers,
        req,
        async {
            match analytics::historian::setpoints_from_history(
                req.query.equipment_ids.as_deref(),
                req.query.building_id.as_deref(),
            )
            .await
            {
                Ok(Some(env)) => analytics::finalize_historian(&req, env, analytics::QV_SETPOINTS),
                Ok(None) => analytics::envelope_with_engine(
                    analytics::QV_SETPOINTS,
                    &req.query,
                    vec!["setpoints unavailable — no setpoint columns on historian".into()],
                    analytics::DF_ENGINE,
                ),
                Err(e) => analytics::envelope(
                    analytics::QV_SETPOINTS,
                    &req.query,
                    vec![format!("setpoints failed: {e}")],
                ),
            }
        }
    )
}

async fn analytics_diurnal(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "diurnal",
        analytics::QV_DIURNAL,
        &state,
        &headers,
        req,
        async {
            match analytics::historian::diurnal_from_history(
                req.query.equipment_ids.as_deref(),
                req.query.building_id.as_deref(),
            )
            .await
            {
                Ok(Some(env)) => analytics::finalize_historian(&req, env, analytics::QV_DIURNAL),
                Ok(None) => analytics::envelope_with_engine(
                    analytics::QV_DIURNAL,
                    &req.query,
                    vec!["diurnal unavailable — no historian timestamp/roles".into()],
                    analytics::DF_ENGINE,
                ),
                Err(e) => analytics::envelope(
                    analytics::QV_DIURNAL,
                    &req.query,
                    vec![format!("diurnal failed: {e}")],
                ),
            }
        }
    )
}

async fn analytics_topology(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "topology",
        analytics::QV_TOPOLOGY,
        &state,
        &headers,
        req,
        async {
            match analytics::historian::topology_from_history(req.query.building_id.as_deref())
                .await
            {
                Ok(Some(env)) => analytics::finalize_historian(&req, env, analytics::QV_TOPOLOGY),
                Ok(None) => analytics::envelope_with_engine(
                    analytics::QV_TOPOLOGY,
                    &req.query,
                    vec!["topology unavailable — no historian equipment".into()],
                    analytics::DF_ENGINE,
                ),
                Err(e) => analytics::envelope(
                    analytics::QV_TOPOLOGY,
                    &req.query,
                    vec![format!("topology failed: {e}")],
                ),
            }
        }
    )
}

async fn analytics_sql_anomaly(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "sql-anomaly",
        analytics::QV_SQL_ANOMALY,
        &state,
        &headers,
        req,
        crate::sql_anomaly::handle_analytics(&req)
    )
}

async fn analytics_sensor_stats(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut req): Json<AnalyticsRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    cached_analytics!(
        "sensor-stats",
        analytics::QV_SENSOR_STATS,
        &state,
        &headers,
        req,
        async {
            let fan_state = req
                .series
                .as_ref()
                .and_then(|s| s.get("fan_state"))
                .and_then(|v| v.as_str())
                .map(str::to_string);
            match analytics::historian::sensor_stats_from_history(
                req.query.equipment_ids.as_deref(),
                req.query.building_id.as_deref(),
                fan_state.as_deref(),
            )
            .await
            {
                Ok(Some(env)) => {
                    analytics::finalize_historian(&req, env, analytics::QV_SENSOR_STATS)
                }
                Ok(None) => analytics::envelope_with_engine(
                    analytics::QV_SENSOR_STATS,
                    &req.query,
                    vec!["sensor-stats unavailable — no numeric roles".into()],
                    analytics::DF_ENGINE,
                ),
                Err(e) => analytics::envelope(
                    analytics::QV_SENSOR_STATS,
                    &req.query,
                    vec![format!("sensor-stats failed: {e}")],
                ),
            }
        }
    )
}

async fn analytics_fuel(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(req): Json<FuelRequest>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, req.building_id.as_deref())
    {
        return Err(deny);
    }
    let qv = req.query_version.clone().unwrap_or_else(|| "fuel".into());
    let campus = req.campus_id.clone();
    let action_id = actions::start_action(
        "analytics_fuel",
        &format!(
            "Fuel analytics · {} · {}",
            campus.as_deref().unwrap_or("(campus)"),
            qv
        ),
        Some(json!({
            "campus_id": campus,
            "query_version": qv,
            "building_id": req.building_id,
        })),
    )
    .ok();
    let body = req;
    let mut result = tokio::task::spawn_blocking(move || fuel::handle_fuel(&body))
        .await
        .unwrap_or_else(|e| json!({"ok": false, "error": format!("fuel analytics task: {e}")}));
    if let Some(ref aid) = action_id {
        let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(true);
        let status = if ok { "ok" } else { "fail" };
        let _ = actions::finish_action(
            aid,
            status,
            Some(json!({
                "ok": ok,
                "error": result.get("error"),
                "query_version": result.get("query_version"),
            })),
        );
        if let Some(obj) = result.as_object_mut() {
            obj.insert("action_id".into(), json!(aid));
        }
    }
    Ok(Json(json!({
        "ok": result.get("ok").and_then(|v| v.as_bool()).unwrap_or(true),
        "analytics": result,
    })))
}

/// Fuel campus ZIP import (campus.json + bill CSVs, or Liberty_* CSV layout).
pub async fn fuel_campus_import(headers: HeaderMap, body: Bytes) -> Json<Value> {
    let ct = content_type(&headers);
    let action_id = actions::start_action(
        "fuel_import",
        "Fuel campus import",
        Some(json!({ "content_type": ct.clone() })),
    )
    .ok();
    let result = tokio::task::spawn_blocking(move || fuel::import::import_fuel_handler(&ct, &body))
        .await
        .unwrap_or_else(|e| json!({"ok": false, "error": format!("fuel import task: {e}")}));
    if let Some(ref aid) = action_id {
        let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
        let status = if ok { "ok" } else { "fail" };
        let detail = json!({
            "ok": ok,
            "campus_id": result.get("campus_id"),
            "error": result.get("error"),
        });
        let _ = actions::finish_action(aid, status, Some(detail));
        let mut out = result;
        if let Some(obj) = out.as_object_mut() {
            obj.insert("action_id".into(), json!(aid));
        }
        return Json(out);
    }
    Json(result)
}

#[derive(Debug, Deserialize)]
pub struct FuelCampusQuery {
    #[serde(default)]
    pub campus_id: Option<String>,
}

pub async fn fuel_campus_list(Query(q): Query<FuelCampusQuery>) -> Json<Value> {
    let id = q.campus_id.clone();
    let result = tokio::task::spawn_blocking(move || {
        fuel::import::get_campus_meta(id.as_deref())
            .unwrap_or_else(|e| json!({"ok": false, "error": e.to_string()}))
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("fuel campus list task: {e}")}));
    Json(result)
}

#[derive(Debug, Deserialize)]
pub struct FuelWeatherFetchBody {
    pub campus_id: String,
}

/// Fetch Open-Meteo archive weather and cache monthly HDD/CDD (vibe20 Fuel dashboard parity).
pub async fn fuel_campus_weather_fetch(Json(body): Json<FuelWeatherFetchBody>) -> Json<Value> {
    let campus_id = body.campus_id.trim().to_string();
    if campus_id.is_empty() {
        return Json(json!({"ok": false, "error": "campus_id required"}));
    }
    let action_id = actions::start_action(
        "fuel_open_meteo",
        &format!("Open-Meteo fetch · {campus_id}"),
        Some(json!({ "campus_id": campus_id.clone() })),
    )
    .ok();
    let result = tokio::task::spawn_blocking(move || fuel::fetch_open_meteo_handler(&campus_id))
        .await
        .unwrap_or_else(|e| json!({"ok": false, "error": format!("open-meteo task: {e}")}));
    if let Some(ref aid) = action_id {
        let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
        let status = if ok { "ok" } else { "fail" };
        let _ = actions::finish_action(
            aid,
            status,
            Some(json!({
                "ok": ok,
                "error": result.get("error"),
                "months": result.get("months"),
            })),
        );
        let mut out = result;
        if let Some(obj) = out.as_object_mut() {
            obj.insert("action_id".into(), json!(aid));
        }
        return Json(out);
    }
    Json(result)
}

#[cfg(test)]
mod version_tests {
    use super::{
        authorize_connector_scope, authorized_edge_ids, connector_proxy_role_allowed,
        connector_trigger_role_allowed, local_fieldbus_ingest, request_scope_allowed,
        resolve_build_version, router,
    };
    use crate::capabilities::{CapabilitiesAggregator, ConfiguredUpstream};
    use crate::state::AppState;
    use axum::body::Body;
    use axum::extract::Query;
    use axum::http::{HeaderMap, HeaderValue, Request, StatusCode};
    use axum::response::IntoResponse;
    use axum::routing::{get, post};
    use axum::{middleware, Json, Router};
    use bytes::Bytes;
    use openfdd_connector_runtime::{auth_middleware, AuthState};
    use openfdd_contracts::{
        ConnectorInventoryRequest, ConnectorInventoryResponse, ConnectorScope,
        ConnectorServiceProfile, HaystackCurrentReadRequest, HaystackCurrentReadResponse,
        HaystackHistoryReadRequest, HaystackHistoryReadResponse, InventoryProvenance,
        LocalIngestReceipt, LocalIngestStatus, PriorityHistoryRequest, PriorityHistoryResponse,
        PriorityHistoryTriggerRequest, PriorityHistoryTriggerResponse, PriorityScanStatus,
        Protocol, Quality, RecipeKind, ServiceIdentity, TelemetryEnvelope, TelemetryPoint,
        ValueKind, CONNECTOR_INVENTORY_CONTRACT_V1, HAYSTACK_READ_CONTRACT_V1,
        PRIORITY_SCAN_CONTRACT_V1, PRIORITY_SCAN_TRIGGER_CONTRACT_V1,
    };
    use serde_json::Value;
    use std::collections::BTreeMap;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};
    use tokio::net::TcpListener;
    use tower::ServiceExt;
    use url::Url;

    #[test]
    fn connector_proxy_role_policy_is_explicit_for_inventory_and_reads() {
        assert!(connector_proxy_role_allowed(crate::auth::Role::Viewer));
        assert!(connector_proxy_role_allowed(crate::auth::Role::Operator));
        assert!(connector_proxy_role_allowed(crate::auth::Role::Admin));
    }

    #[test]
    fn connector_trigger_role_policy_excludes_viewers() {
        assert!(!connector_trigger_role_allowed(crate::auth::Role::Viewer));
        assert!(connector_trigger_role_allowed(crate::auth::Role::Operator));
        assert!(connector_trigger_role_allowed(crate::auth::Role::Admin));
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize process environment while exercising the HTTP body-limit route"
    )]
    async fn local_ingest_router_oversize_returns_typed_receipt() {
        let _env_lock = crate::test_env_lock::lock_env();
        std::env::set_var("OPENFDD_LOCAL_INGEST_TOKEN", "oversize-test-token");
        std::env::set_var("OPENFDD_BUILDING_ID", "oversize-building");
        std::env::set_var("OPENFDD_LOCAL_ALLOWED_EDGE_IDS", "oversize-edge");
        let state = Arc::new(AppState::new());
        let request = Request::post("/api/ingest/local")
            .header("authorization", "Bearer oversize-test-token")
            .header("x-openfdd-message-id", uuid::Uuid::new_v4().to_string())
            .body(Body::from(vec![b'x'; 1024 * 1024 + 1]))
            .unwrap();
        let response = router(state).oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::PAYLOAD_TOO_LARGE);
        let bytes = axum::body::to_bytes(response.into_body(), 2 * 1024 * 1024)
            .await
            .unwrap();
        let receipt: openfdd_contracts::LocalIngestReceipt =
            serde_json::from_slice(&bytes).unwrap();
        receipt.validate().unwrap();
        assert_eq!(receipt.status, LocalIngestStatus::Rejected);
        assert_eq!(
            receipt.schema,
            openfdd_contracts::LOCAL_INGEST_RECEIPT_CONTRACT_V1
        );
        for key in [
            "OPENFDD_LOCAL_INGEST_TOKEN",
            "OPENFDD_BUILDING_ID",
            "OPENFDD_LOCAL_ALLOWED_EDGE_IDS",
        ] {
            std::env::remove_var(key);
        }
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize process environment while exercising the loaded Haystack to Central path"
    )]
    async fn loaded_haystack_split_to_central_receipt_and_historian_readback() {
        let _env_lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().unwrap();
        let storage = tempfile::tempdir().unwrap();
        let catalog_path = workspace.path().join("haystack-catalog.toml");
        std::fs::write(
            &catalog_path,
            "revision = \"e2e-loaded-v1\"\n\n[[records]]\nkey = \"point:ahu-1:sat\"\nkind = \"point\"\ndisplay_name = \"Supply air temperature\"\nequipment_key = \"ahu-1\"\nrole = \"sat\"\nunit = \"°F\"\nsource_ref = \"@ahu-1-sat\"\nnav_ref = \"@ahu-1\"\n",
        )
        .unwrap();

        struct EnvSnapshot(Vec<(&'static str, Option<String>)>);
        impl Drop for EnvSnapshot {
            fn drop(&mut self) {
                for (key, value) in self.0.drain(..) {
                    match value {
                        Some(value) => std::env::set_var(key, value),
                        None => std::env::remove_var(key),
                    }
                }
            }
        }
        let env_keys = [
            "OPENFDD_WORKSPACE",
            "OPENFDD_STORAGE_URL",
            "OPENFDD_PARQUET_FLUSH_ROWS",
            "OPENFDD_PARQUET_FLUSH_SECONDS",
            "OPENFDD_LOCAL_INGEST_TOKEN",
            "OPENFDD_BUILDING_ID",
            "OPENFDD_LOCAL_ALLOWED_EDGE_IDS",
            "OPENFDD_TENANT_ID",
            "OPENFDD_MULTI_TENANT",
        ];
        let _env_snapshot = EnvSnapshot(
            env_keys
                .iter()
                .map(|key| (*key, std::env::var(key).ok()))
                .collect(),
        );
        std::env::set_var("OPENFDD_WORKSPACE", workspace.path());
        std::env::set_var(
            "OPENFDD_STORAGE_URL",
            format!("file://{}", storage.path().display()),
        );
        std::env::set_var("OPENFDD_PARQUET_FLUSH_ROWS", "1");
        std::env::set_var("OPENFDD_PARQUET_FLUSH_SECONDS", "3600");
        std::env::set_var("OPENFDD_LOCAL_INGEST_TOKEN", "loaded-e2e-token");
        std::env::set_var("OPENFDD_BUILDING_ID", "building");
        std::env::set_var("OPENFDD_LOCAL_ALLOWED_EDGE_IDS", "edge");
        std::env::remove_var("OPENFDD_TENANT_ID");
        std::env::remove_var("OPENFDD_MULTI_TENANT");

        async fn zinc_read(
            headers: HeaderMap,
            Query(query): Query<BTreeMap<String, String>>,
        ) -> axum::response::Response {
            if headers
                .get("authorization")
                .and_then(|value| value.to_str().ok())
                != Some("Basic dXNlcjpwYXNz")
            {
                return (StatusCode::UNAUTHORIZED, "").into_response();
            }
            if query.get("filter").map(String::as_str) != Some("id == @ahu-1-sat") {
                return (StatusCode::BAD_REQUEST, "unexpected ref filter").into_response();
            }
            (
                StatusCode::OK,
                "ver:\"3.0\"\nid,curVal,ts\n@ahu-1-sat \"Supply air temperature\",72.5°F,2026-10-02T12:00:00-05:00 New_York\n",
            )
                .into_response()
        }

        async fn zinc_history(
            headers: HeaderMap,
            Query(query): Query<BTreeMap<String, String>>,
        ) -> axum::response::Response {
            if headers
                .get("authorization")
                .and_then(|value| value.to_str().ok())
                != Some("Basic dXNlcjpwYXNz")
            {
                return (StatusCode::UNAUTHORIZED, "").into_response();
            }
            if query.get("id").map(String::as_str) != Some("@ahu-1-sat") {
                return (StatusCode::BAD_REQUEST, "unexpected history ref").into_response();
            }
            (
                StatusCode::OK,
                "ver:\"3.0\"\nts,val\n2026-10-02T12:00:00-05:00 New_York,72.5°F\n",
            )
                .into_response()
        }

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let upstream_address = listener.local_addr().unwrap();
        let upstream = tokio::spawn(async move {
            axum::serve(
                listener,
                Router::new()
                    .route("/read", get(zinc_read))
                    .route("/hisRead", get(zinc_history)),
            )
            .await
            .unwrap();
        });

        let fieldbus_settings = openfdd_fieldbus::Settings {
            connector_tenant_id: Some("tenant".into()),
            connector_building_id: Some("building".into()),
            connector_edge_id: Some("edge".into()),
            haystack_configured: true,
            haystack: openfdd_fieldbus::HaystackSettings {
                base_url: format!("http://{upstream_address}/"),
                username: "user".into(),
                password: "pass".into(),
                auth_mode: openfdd_fieldbus::HaystackAuthMode::Basic,
                tls_verify: true,
                catalog_path: Some(catalog_path.clone()),
            },
            ..openfdd_fieldbus::Settings::default()
        };
        let haystack = Arc::new(openfdd_fieldbus::HaystackService::new(
            fieldbus_settings.haystack.clone(),
        ));
        let split_state = openfdd_fieldbus::HaystackState {
            settings: Arc::new(fieldbus_settings),
            api_key: None,
            haystack,
            identity: ServiceIdentity::new(
                ConnectorServiceProfile::Haystack,
                "fixture",
                RecipeKind::EdgeHaystack,
            ),
            manual_sequence: Arc::new(std::sync::atomic::AtomicU64::new(0)),
            manual_spool: Arc::new(tokio::sync::Mutex::new(None)),
            manual_gate: Arc::new(tokio::sync::Mutex::new(())),
            manual_results: Arc::new(tokio::sync::Mutex::new(std::collections::BTreeMap::new())),
        };
        let split = openfdd_fieldbus::haystack_router(split_state);
        let scope = ConnectorScope {
            tenant_id: "tenant".into(),
            building_id: "building".into(),
            edge_id: "edge".into(),
        };
        let current_request = HaystackCurrentReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: uuid::Uuid::new_v4(),
            scope: scope.clone(),
            public_keys: vec!["point:ahu-1:sat".into()],
        };
        let current_response = split
            .clone()
            .oneshot(
                Request::post("/api/haystack/read")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&current_request).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(current_response.status(), StatusCode::OK);
        let current: HaystackCurrentReadResponse = serde_json::from_slice(
            &axum::body::to_bytes(current_response.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(current.values[0].unit.as_deref(), Some("°F"));

        let history_request = HaystackHistoryReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: uuid::Uuid::new_v4(),
            scope,
            public_keys: vec!["point:ahu-1:sat".into()],
            start: "2026-10-02T17:00:00Z".parse().unwrap(),
            end: "2026-10-02T18:00:00Z".parse().unwrap(),
            max_samples: 16,
        };
        let history_response = split
            .oneshot(
                Request::post("/api/haystack/his-read")
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&history_request).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(history_response.status(), StatusCode::OK);
        let history: HaystackHistoryReadResponse = serde_json::from_slice(
            &axum::body::to_bytes(history_response.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        let source = history.series[0].values[0].clone();
        assert_eq!(history.sample_count, 1);
        assert_eq!(source.value, serde_json::json!(72.5));
        assert_eq!(source.unit.as_deref(), Some("°F"));
        let source_observed_at = source.observed_at.unwrap();

        let mut envelope = TelemetryEnvelope::new(
            "building",
            "edge",
            Protocol::Haystack,
            1,
            vec![TelemetryPoint {
                id: current.values[0].key.clone(),
                display_name: Some("Supply air temperature".into()),
                kind: Some(source.kind),
                value: source.value.clone(),
                unit: source.unit.clone(),
                quality: source.quality,
                observed_at: Some(source_observed_at),
                tags: serde_json::json!({
                    "building_id": "building",
                    "equipment_id": "ahu-1",
                    "role": "sat",
                })
                .as_object()
                .cloned()
                .unwrap(),
            }],
        );
        envelope.observed_at = source_observed_at;
        envelope.validate().unwrap();
        let message_id = envelope.message_id;
        let body = serde_json::to_vec(&envelope).unwrap();
        let central_state = Arc::new(AppState::new());
        let central = router(Arc::clone(&central_state));
        let ingest_request = || {
            Request::post("/api/ingest/local")
                .header("authorization", "Bearer loaded-e2e-token")
                .header("x-openfdd-message-id", message_id.to_string())
                .header("content-type", "application/json")
                .body(Body::from(body.clone()))
                .unwrap()
        };
        let ingest_response = central.clone().oneshot(ingest_request()).await.unwrap();
        assert_eq!(ingest_response.status(), StatusCode::OK);
        let receipt: LocalIngestReceipt = serde_json::from_slice(
            &axum::body::to_bytes(ingest_response.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        receipt.validate().unwrap();
        assert_eq!(receipt.status, LocalIngestStatus::Committed);
        assert_eq!(receipt.persisted_rows, 1);
        assert_eq!(receipt.site_id, "building");
        assert_eq!(receipt.edge_id, "edge");
        assert_eq!(receipt.message_id, message_id);
        assert_eq!(receipt.scope, "tenant=-;building=building");

        let ctx = datafusion::prelude::SessionContext::new();
        fdd_sql::register_historian_building(&ctx, storage.path(), "building")
            .await
            .unwrap();
        let rows = ctx
            .sql("SELECT timestamp_utc, sat FROM history")
            .await
            .unwrap()
            .collect()
            .await
            .unwrap();
        assert_eq!(rows.len(), 1);
        let timestamp = rows[0]
            .column(0)
            .as_any()
            .downcast_ref::<datafusion::arrow::array::TimestampNanosecondArray>()
            .unwrap()
            .value(0);
        assert_eq!(timestamp, source_observed_at.timestamp_nanos_opt().unwrap());
        let value = rows[0]
            .column(1)
            .as_any()
            .downcast_ref::<datafusion::arrow::array::Float64Array>()
            .unwrap()
            .value(0);
        assert_eq!(value, 72.5);
        let shadow = central_state
            .edges
            .get("edge")
            .unwrap()
            .lock()
            .unwrap()
            .last_telemetry
            .clone()
            .unwrap();
        assert_eq!(shadow.points[0].unit.as_deref(), Some("°F"));

        let replay = central.clone().oneshot(ingest_request()).await.unwrap();
        assert_eq!(replay.status(), StatusCode::OK);
        let replay_receipt: LocalIngestReceipt = serde_json::from_slice(
            &axum::body::to_bytes(replay.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert!(replay_receipt.duplicate);
        assert_eq!(replay_receipt.status, LocalIngestStatus::Committed);

        let mut conflict = envelope;
        conflict.points[0].value = serde_json::json!(73.0);
        let conflict_response = central
            .oneshot(
                Request::post("/api/ingest/local")
                    .header("authorization", "Bearer loaded-e2e-token")
                    .header("x-openfdd-message-id", message_id.to_string())
                    .header("content-type", "application/json")
                    .body(Body::from(serde_json::to_vec(&conflict).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(conflict_response.status(), StatusCode::CONFLICT);
        let conflict_receipt: LocalIngestReceipt = serde_json::from_slice(
            &axum::body::to_bytes(conflict_response.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(conflict_receipt.status, LocalIngestStatus::Conflict);
        assert_eq!(conflict_receipt.message_id, message_id);
        upstream.abort();
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize process environment while exercising the complete manual connector path"
    )]
    async fn loaded_haystack_manual_route_to_actual_central_is_replay_safe() {
        let _env_lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().unwrap();
        let storage = tempfile::tempdir().unwrap();
        let spool = tempfile::tempdir().unwrap();
        let catalog_path = workspace.path().join("haystack-catalog.toml");
        std::fs::write(
            &catalog_path,
            "revision = \"loaded-manual-v2\"\n\n[[records]]\nkey = \"point:ahu-1:sat\"\nkind = \"point\"\ndisplay_name = \"Supply air temperature\"\nequipment_key = \"ahu-1\"\nrole = \"sat\"\nunit = \"°F\"\nsource_ref = \"@ahu-1-sat\"\nnav_ref = \"@ahu-1\"\n\n[[records]]\nkey = \"point:ahu-1:oat\"\nkind = \"point\"\ndisplay_name = \"Outdoor air temperature\"\nequipment_key = \"ahu-1\"\nrole = \"oat\"\nunit = \"°F\"\nsource_ref = \"@ahu-1-oat\"\nnav_ref = \"@ahu-1\"\n",
        )
        .unwrap();
        let env_keys = [
            "OPENFDD_WORKSPACE",
            "OPENFDD_STORAGE_URL",
            "OPENFDD_PARQUET_FLUSH_ROWS",
            "OPENFDD_PARQUET_FLUSH_SECONDS",
            "OPENFDD_LOCAL_CENTRAL_URL",
            "OPENFDD_LOCAL_INGEST_TOKEN",
            "OPENFDD_LOCAL_SPOOL_DIR",
            "OPENFDD_BUILDING_ID",
            "OPENFDD_LOCAL_ALLOWED_EDGE_IDS",
            "OPENFDD_TENANT_ID",
            "OPENFDD_MULTI_TENANT",
            "OPENFDD_LOCAL_SPOOL_MAX_COMPLETED_RECORDS",
            "OPENFDD_LOCAL_SPOOL_MAX_RETIRED_RECORDS",
        ];
        struct EnvSnapshot(Vec<(&'static str, Option<String>)>);
        impl Drop for EnvSnapshot {
            fn drop(&mut self) {
                for (key, value) in self.0.drain(..) {
                    match value {
                        Some(value) => std::env::set_var(key, value),
                        None => std::env::remove_var(key),
                    }
                }
            }
        }
        let _env_snapshot = EnvSnapshot(
            env_keys
                .iter()
                .map(|key| (*key, std::env::var(key).ok()))
                .collect(),
        );
        std::env::set_var("OPENFDD_WORKSPACE", workspace.path());
        std::env::set_var(
            "OPENFDD_STORAGE_URL",
            format!("file://{}", storage.path().display()),
        );
        std::env::set_var("OPENFDD_PARQUET_FLUSH_ROWS", "1");
        std::env::set_var("OPENFDD_PARQUET_FLUSH_SECONDS", "3600");
        std::env::set_var("OPENFDD_LOCAL_INGEST_TOKEN", "loaded-manual-token");
        std::env::set_var("OPENFDD_LOCAL_SPOOL_DIR", spool.path());
        std::env::set_var("OPENFDD_LOCAL_SPOOL_MAX_COMPLETED_RECORDS", "1");
        std::env::set_var("OPENFDD_LOCAL_SPOOL_MAX_RETIRED_RECORDS", "10");
        std::env::set_var("OPENFDD_BUILDING_ID", "building");
        std::env::set_var("OPENFDD_LOCAL_ALLOWED_EDGE_IDS", "edge");
        std::env::remove_var("OPENFDD_TENANT_ID");
        std::env::remove_var("OPENFDD_MULTI_TENANT");

        let upstream_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let upstream_address = upstream_listener.local_addr().unwrap();
        let upstream_hits = Arc::new(AtomicUsize::new(0));
        let start_upstream = |listener: TcpListener| {
            let upstream_hits = Arc::clone(&upstream_hits);
            tokio::spawn(async move {
                axum::serve(
                    listener,
                    Router::new().route(
                        "/read",
                        get(
                            move |headers: HeaderMap,
                                  Query(query): Query<BTreeMap<String, String>>| {
                                let upstream_hits = Arc::clone(&upstream_hits);
                                async move {
                                    if headers
                                        .get("authorization")
                                        .and_then(|value| value.to_str().ok())
                                        != Some("Basic dXNlcjpwYXNz")
                                        || query.get("filter").map(String::as_str)
                                            != Some(
                                                "id == @ahu-1-sat or id == @ahu-1-oat",
                                            )
                                    {
                                        return (StatusCode::UNAUTHORIZED, "").into_response();
                                    }
                                    upstream_hits.fetch_add(1, Ordering::SeqCst);
                                    // Deliberately return only SAT for a two-key
                                    // request. The typed contract permits a
                                    // bounded partial response, which must be
                                    // persisted and replayed byte-for-byte.
                                    (
                                        StatusCode::OK,
                                        "ver:\"3.0\"\nid,curVal,ts\n@ahu-1-sat \"Supply air temperature\",72.5°F,2026-10-02T12:00:00-05:00 New_York\n",
                                    )
                                        .into_response()
                                }
                            },
                        ),
                    ),
                )
                .await
                .unwrap();
            })
        };
        let mut upstream = start_upstream(upstream_listener);

        let pending_body = Arc::new(Mutex::new(None::<Bytes>));
        let pending_hits = Arc::new(AtomicUsize::new(0));
        let pending_body_for_route = Arc::clone(&pending_body);
        let pending_hits_for_route = Arc::clone(&pending_hits);
        let pending_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let pending_address = pending_listener.local_addr().unwrap();
        let pending_server = tokio::spawn(async move {
            let pending = Router::new().route(
                "/api/ingest/local",
                post(move |headers: HeaderMap, body: Bytes| {
                    let pending_body = Arc::clone(&pending_body_for_route);
                    let pending_hits = Arc::clone(&pending_hits_for_route);
                    async move {
                        assert_eq!(
                            headers
                                .get("authorization")
                                .and_then(|value| value.to_str().ok()),
                            Some("Bearer loaded-manual-token")
                        );
                        *pending_body.lock().unwrap() = Some(body.clone());
                        pending_hits.fetch_add(1, Ordering::SeqCst);
                        let envelope: TelemetryEnvelope = serde_json::from_slice(&body).unwrap();
                        (
                            StatusCode::ACCEPTED,
                            Json(LocalIngestReceipt {
                                schema: openfdd_contracts::LOCAL_INGEST_RECEIPT_CONTRACT_V1.into(),
                                scope: "tenant=-;building=building".into(),
                                site_id: envelope.site_id,
                                edge_id: envelope.edge_id,
                                message_id: envelope.message_id,
                                status: LocalIngestStatus::Pending,
                                duplicate: false,
                                eligible_points: 0,
                                persisted_rows: 0,
                                error: Some(
                                    "synthetic first response; retry through Central".into(),
                                ),
                            }),
                        )
                    }
                }),
            );
            axum::serve(pending_listener, pending).await.unwrap();
        });

        let central_state = Arc::new(AppState::new());
        let central_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let central_address = central_listener.local_addr().unwrap();
        let central_server = tokio::spawn({
            let central = router(Arc::clone(&central_state));
            async move { axum::serve(central_listener, central).await.unwrap() }
        });

        let haystack_settings = openfdd_fieldbus::HaystackSettings {
            base_url: format!("http://{upstream_address}/"),
            username: "user".into(),
            password: "pass".into(),
            auth_mode: openfdd_fieldbus::HaystackAuthMode::Basic,
            tls_verify: true,
            catalog_path: Some(catalog_path.clone()),
        };
        let fieldbus_settings = openfdd_fieldbus::Settings {
            connector_tenant_id: Some("tenant".into()),
            connector_building_id: Some("building".into()),
            connector_edge_id: Some("edge".into()),
            haystack_configured: true,
            haystack: haystack_settings.clone(),
            ..openfdd_fieldbus::Settings::default()
        };
        let fieldbus_settings = Arc::new(fieldbus_settings);
        let split_state = openfdd_fieldbus::HaystackState {
            settings: Arc::clone(&fieldbus_settings),
            api_key: Some("management-key".into()),
            haystack: Arc::new(openfdd_fieldbus::HaystackService::new(
                haystack_settings.clone(),
            )),
            identity: ServiceIdentity::new(
                ConnectorServiceProfile::Haystack,
                "fixture",
                RecipeKind::EdgeHaystack,
            ),
            manual_sequence: Arc::new(std::sync::atomic::AtomicU64::new(0)),
            manual_spool: Arc::new(tokio::sync::Mutex::new(None)),
            manual_gate: Arc::new(tokio::sync::Mutex::new(())),
            manual_results: Arc::new(tokio::sync::Mutex::new(std::collections::BTreeMap::new())),
        };
        let split =
            openfdd_fieldbus::haystack_router(split_state).layer(middleware::from_fn_with_state(
                AuthState::new(Some("management-key".into())),
                auth_middleware,
            ));
        std::env::set_var(
            "OPENFDD_LOCAL_CENTRAL_URL",
            format!("http://{pending_address}"),
        );
        let scope = ConnectorScope {
            tenant_id: "tenant".into(),
            building_id: "building".into(),
            edge_id: "edge".into(),
        };
        let request = HaystackCurrentReadRequest {
            schema: HAYSTACK_READ_CONTRACT_V1.into(),
            request_id: uuid::Uuid::new_v4(),
            scope: scope.clone(),
            public_keys: vec!["point:ahu-1:sat".into(), "point:ahu-1:oat".into()],
        };
        let body = serde_json::to_vec(&request).unwrap();
        let make_request = |body: Vec<u8>, authorization: Option<&str>| {
            let mut builder =
                Request::post("/api/haystack/telemetry").header("content-type", "application/json");
            if let Some(authorization) = authorization {
                builder = builder.header("authorization", authorization);
            }
            builder.body(Body::from(body)).unwrap()
        };
        let unauthorized = split
            .clone()
            .oneshot(make_request(body.clone(), None))
            .await
            .unwrap();
        assert_eq!(unauthorized.status(), StatusCode::UNAUTHORIZED);
        let first = split
            .clone()
            .oneshot(make_request(body.clone(), Some("Bearer management-key")))
            .await
            .unwrap();
        let first_status = first.status();
        let first_bytes = axum::body::to_bytes(first.into_body(), 1024 * 1024)
            .await
            .unwrap();
        assert_eq!(
            first_status,
            StatusCode::OK,
            "{}",
            String::from_utf8_lossy(&first_bytes)
        );
        let first_result: Value = serde_json::from_slice(&first_bytes).unwrap();
        assert_eq!(first_result["status"], "pending");
        assert_eq!(pending_hits.load(Ordering::SeqCst), 1);
        let persisted_body = pending_body.lock().unwrap().clone().unwrap();
        let persisted_envelope: TelemetryEnvelope =
            serde_json::from_slice(&persisted_body).unwrap();
        assert_eq!(request.public_keys.len(), 2);
        assert_eq!(persisted_envelope.points.len(), 1);
        assert_eq!(persisted_envelope.points[0].id, "point:ahu-1:sat");

        let mut changed = request.clone();
        changed.public_keys = vec!["point:ahu-1:other".into()];
        let changed_response = split
            .clone()
            .oneshot(make_request(
                serde_json::to_vec(&changed).unwrap(),
                Some("Bearer management-key"),
            ))
            .await
            .unwrap();
        assert_eq!(changed_response.status(), StatusCode::BAD_REQUEST);
        assert_eq!(pending_hits.load(Ordering::SeqCst), 1);

        // Prove the retry uses the durable pending envelope: stop the
        // Haystack upstream before retrying, so any upstream reread would
        // fail instead of being hidden by a still-live fixture.
        upstream.abort();
        let _ = (&mut upstream).await;
        pending_server.abort();
        std::env::set_var(
            "OPENFDD_LOCAL_CENTRAL_URL",
            format!("http://{central_address}"),
        );
        let retry = split
            .clone()
            .oneshot(make_request(body.clone(), Some("Bearer management-key")))
            .await
            .unwrap();
        assert_eq!(retry.status(), StatusCode::OK);
        let retry_result: Value = serde_json::from_slice(
            &axum::body::to_bytes(retry.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(retry_result["status"], "committed");
        assert_eq!(retry_result["message_id"], request.request_id.to_string());
        let recorded = central_state
            .edges
            .get("edge")
            .unwrap()
            .lock()
            .unwrap()
            .last_telemetry
            .clone()
            .unwrap();
        assert_eq!(recorded, persisted_envelope);

        // Bring the same bounded upstream endpoint back after the offline
        // retry. Two distinct operations are submitted concurrently; both
        // must reserve and write their own pending spool identity.
        let upstream_listener = TcpListener::bind(upstream_address).await.unwrap();
        upstream = start_upstream(upstream_listener);
        let second_request = HaystackCurrentReadRequest {
            request_id: uuid::Uuid::new_v4(),
            ..request.clone()
        };
        let third_request = HaystackCurrentReadRequest {
            request_id: uuid::Uuid::new_v4(),
            ..request.clone()
        };
        let second_body = serde_json::to_vec(&second_request).unwrap();
        let third_body = serde_json::to_vec(&third_request).unwrap();
        let (second, third) = tokio::join!(
            split.clone().oneshot(make_request(
                second_body.clone(),
                Some("Bearer management-key"),
            )),
            split.clone().oneshot(make_request(
                third_body.clone(),
                Some("Bearer management-key"),
            )),
        );
        let second = second.unwrap();
        let third = third.unwrap();
        assert_eq!(second.status(), StatusCode::OK);
        assert_eq!(third.status(), StatusCode::OK);
        let second_result: Value = serde_json::from_slice(
            &axum::body::to_bytes(second.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        let third_result: Value = serde_json::from_slice(
            &axum::body::to_bytes(third.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(second_result["status"], "committed");
        assert_eq!(third_result["status"], "committed");

        // Leave one known completed record after the two concurrent writes so
        // restart can prove both an expired tombstone and a completed replay.
        let final_request = HaystackCurrentReadRequest {
            request_id: uuid::Uuid::new_v4(),
            ..request.clone()
        };
        let final_response = split
            .clone()
            .oneshot(make_request(
                serde_json::to_vec(&final_request).unwrap(),
                Some("Bearer management-key"),
            ))
            .await
            .unwrap();
        assert_eq!(final_response.status(), StatusCode::OK);
        let final_result: Value = serde_json::from_slice(
            &axum::body::to_bytes(final_response.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(final_result["status"], "committed");
        assert_eq!(upstream_hits.load(Ordering::SeqCst), 4);
        assert_eq!(*central_state.ingest_dup.lock().unwrap(), 0);

        upstream.abort();
        drop(split);
        let restarted = openfdd_fieldbus::HaystackState {
            settings: Arc::clone(&fieldbus_settings),
            api_key: Some("management-key".into()),
            haystack: Arc::new(openfdd_fieldbus::HaystackService::new(haystack_settings)),
            identity: ServiceIdentity::new(
                ConnectorServiceProfile::Haystack,
                "fixture-restarted",
                RecipeKind::EdgeHaystack,
            ),
            manual_sequence: Arc::new(std::sync::atomic::AtomicU64::new(0)),
            manual_spool: Arc::new(tokio::sync::Mutex::new(None)),
            manual_gate: Arc::new(tokio::sync::Mutex::new(())),
            manual_results: Arc::new(tokio::sync::Mutex::new(std::collections::BTreeMap::new())),
        };
        let restarted =
            openfdd_fieldbus::haystack_router(restarted).layer(middleware::from_fn_with_state(
                AuthState::new(Some("management-key".into())),
                auth_middleware,
            ));
        let replay = restarted
            .clone()
            .oneshot(make_request(body, Some("Bearer management-key")))
            .await
            .unwrap();
        assert_eq!(replay.status(), StatusCode::OK);
        let replay_result: Value = serde_json::from_slice(
            &axum::body::to_bytes(replay.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(replay_result["status"], "expired");
        assert_eq!(*central_state.ingest_dup.lock().unwrap(), 0);
        let expired_changed = restarted
            .clone()
            .oneshot(make_request(
                serde_json::to_vec(&changed).unwrap(),
                Some("Bearer management-key"),
            ))
            .await
            .unwrap();
        assert_eq!(expired_changed.status(), StatusCode::OK);
        let expired_changed_result: Value = serde_json::from_slice(
            &axum::body::to_bytes(expired_changed.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(expired_changed_result["status"], "expired");
        let final_replay = restarted
            .oneshot(make_request(
                serde_json::to_vec(&final_request).unwrap(),
                Some("Bearer management-key"),
            ))
            .await
            .unwrap();
        assert_eq!(final_replay.status(), StatusCode::OK);
        let final_replay_result: Value = serde_json::from_slice(
            &axum::body::to_bytes(final_replay.into_body(), 1024 * 1024)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(final_replay_result["status"], "committed");
        assert_eq!(
            final_replay_result["message_id"],
            final_request.request_id.to_string()
        );
        assert_eq!(*central_state.ingest_dup.lock().unwrap(), 0);

        let ctx = datafusion::prelude::SessionContext::new();
        fdd_sql::register_historian_building(&ctx, storage.path(), "building")
            .await
            .unwrap();
        let rows = ctx
            .sql("SELECT timestamp_utc, sat FROM history")
            .await
            .unwrap()
            .collect()
            .await
            .unwrap();
        assert_eq!(rows.len(), 4);
        let timestamp = rows[0]
            .column(0)
            .as_any()
            .downcast_ref::<datafusion::arrow::array::TimestampNanosecondArray>()
            .unwrap()
            .value(0);
        assert_eq!(timestamp, 1_790_960_400_000_000_000);
        let value = rows[0]
            .column(1)
            .as_any()
            .downcast_ref::<datafusion::arrow::array::Float64Array>()
            .unwrap()
            .value(0);
        assert_eq!(value, 72.5);
        central_server.abort();
    }

    #[tokio::test]
    async fn connector_priority_history_trigger_denies_viewer_before_proxy() {
        let trigger_calls = Arc::new(AtomicUsize::new(0));
        let trigger_calls_for_route = Arc::clone(&trigger_calls);
        let upstream = Router::new().route(
            "/api/connector/priority-history/trigger",
            post(move |Json(request): Json<PriorityHistoryTriggerRequest>| {
                let trigger_calls = Arc::clone(&trigger_calls_for_route);
                async move {
                    trigger_calls.fetch_add(1, Ordering::SeqCst);
                    Json(PriorityHistoryTriggerResponse {
                        schema: PRIORITY_SCAN_TRIGGER_CONTRACT_V1.into(),
                        request_id: request.request_id,
                        scope: request.scope.clone(),
                        records_added: 0,
                        scanner: PriorityScanStatus {
                            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
                            scope: request.scope,
                            enabled: false,
                            interval_secs: 3_600,
                            max_points_per_device: 100,
                            catch_up: false,
                            read_only: true,
                            discovery_enabled: false,
                            writes_enabled: false,
                            last_started_at: None,
                            last_completed_at: None,
                            next_due_at: None,
                            last_device_identity: None,
                            last_error: None,
                            records_retained: 0,
                        },
                    })
                }
            }),
        );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, upstream).await.unwrap() });

        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some("connector-trigger-role-policy-test-secret".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        state.capabilities = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "legacy".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{address}/")).unwrap(),
            token: Some("synthetic-upstream-token".into()),
        }]);
        let state = Arc::new(state);
        let app = super::router(Arc::clone(&state));
        let viewer = state
            .auth
            .issue_token_with_tenants("connector-trigger-test", crate::auth::Role::Viewer, 60, &[])
            .unwrap();
        let body = serde_json::json!({
            "schema": PRIORITY_SCAN_TRIGGER_CONTRACT_V1,
            "request_id": uuid::Uuid::nil(),
            "scope": {
                "tenant_id": "legacy",
                "building_id": "building-a",
                "edge_id": "edge-a"
            }
        });
        let request = Request::post("/api/connectors/edge-a/priority-history/trigger")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {viewer}"))
            .body(Body::from(body.to_string()))
            .unwrap();
        let response = app.oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        assert_eq!(trigger_calls.load(Ordering::SeqCst), 0);
        server.abort();
    }

    #[tokio::test]
    async fn connector_inventory_http_enforces_jwt_roles_and_scope() {
        async fn inventory_upstream(
            Json(request): Json<ConnectorInventoryRequest>,
        ) -> Json<ConnectorInventoryResponse> {
            Json(ConnectorInventoryResponse {
                schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
                request_id: request.request_id,
                scope: request.scope,
                protocols: Vec::new(),
                revision: "config-http-test".into(),
                captured_at: chrono::Utc::now(),
                provenance: InventoryProvenance::TrustedConfiguration,
                records: Vec::new(),
                next_cursor: None,
            })
        }

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let upstream = Router::new().route("/api/connector/inventory", post(inventory_upstream));
        let server = tokio::spawn(async move { axum::serve(listener, upstream).await.unwrap() });

        let secret = "connector-http-role-policy-test-secret".to_string();
        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some(secret),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        state.capabilities = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "legacy".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{address}/")).unwrap(),
            token: Some("synthetic-upstream-token".into()),
        }]);
        let state = Arc::new(state);
        let app = super::router(Arc::clone(&state));
        let body = |tenant_id: &str| {
            serde_json::json!({
                "schema": CONNECTOR_INVENTORY_CONTRACT_V1,
                "request_id": uuid::Uuid::nil(),
                "scope": {
                    "tenant_id": tenant_id,
                    "building_id": "building-a",
                    "edge_id": "edge-a"
                },
                "protocols": ["bacnet"],
                "page_size": 10
            })
            .to_string()
        };
        let request = |token: Option<&str>, tenant_id: &str| {
            let mut builder = Request::post("/api/connectors/edge-a/inventory")
                .header("content-type", "application/json");
            if let Some(token) = token {
                builder = builder.header("authorization", format!("Bearer {token}"));
            }
            builder.body(Body::from(body(tenant_id))).unwrap()
        };

        let anonymous = app.clone().oneshot(request(None, "legacy")).await.unwrap();
        assert_eq!(anonymous.status(), StatusCode::UNAUTHORIZED);

        for role in [
            crate::auth::Role::Viewer,
            crate::auth::Role::Operator,
            crate::auth::Role::Admin,
        ] {
            let token = state
                .auth
                .issue_token_with_tenants("connector-test", role, 60, &[])
                .unwrap();
            let allowed = app
                .clone()
                .oneshot(request(Some(&token), "legacy"))
                .await
                .unwrap();
            assert_eq!(allowed.status(), StatusCode::OK, "role {role}");
        }

        let viewer = state
            .auth
            .issue_token_with_tenants("connector-test", crate::auth::Role::Viewer, 60, &[])
            .unwrap();
        let foreign = app
            .oneshot(request(Some(&viewer), "tenant-foreign"))
            .await
            .unwrap();
        assert_eq!(foreign.status(), StatusCode::FORBIDDEN);
        server.abort();
    }

    #[tokio::test]
    async fn connector_priority_history_http_enforces_jwt_roles_and_scope() {
        async fn history_upstream(
            Json(request): Json<PriorityHistoryRequest>,
        ) -> Json<PriorityHistoryResponse> {
            Json(PriorityHistoryResponse {
                schema: PRIORITY_SCAN_CONTRACT_V1.into(),
                request_id: request.request_id,
                scope: request.scope.clone(),
                revision: "history-http-test".into(),
                captured_at: chrono::Utc::now(),
                records: Vec::new(),
                next_cursor: None,
                scanner: PriorityScanStatus {
                    schema: PRIORITY_SCAN_CONTRACT_V1.into(),
                    scope: request.scope,
                    enabled: false,
                    interval_secs: 3_600,
                    max_points_per_device: 100,
                    catch_up: false,
                    read_only: true,
                    discovery_enabled: false,
                    writes_enabled: false,
                    last_started_at: None,
                    last_completed_at: None,
                    next_due_at: None,
                    last_device_identity: None,
                    last_error: None,
                    records_retained: 0,
                },
            })
        }

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let upstream =
            Router::new().route("/api/connector/priority-history", post(history_upstream));
        let server = tokio::spawn(async move { axum::serve(listener, upstream).await.unwrap() });

        let secret = "connector-history-role-policy-test-secret".to_string();
        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some(secret),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        state.capabilities = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "legacy".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{address}/")).unwrap(),
            token: Some("synthetic-upstream-token".into()),
        }]);
        let state = Arc::new(state);
        let app = super::router(Arc::clone(&state));
        let body = |tenant_id: &str| {
            serde_json::json!({
                "schema": PRIORITY_SCAN_CONTRACT_V1,
                "request_id": uuid::Uuid::nil(),
                "scope": {
                    "tenant_id": tenant_id,
                    "building_id": "building-a",
                    "edge_id": "edge-a"
                },
                "page_size": 10
            })
            .to_string()
        };
        let request = |token: Option<&str>, tenant_id: &str| {
            let mut builder = Request::post("/api/connectors/edge-a/priority-history")
                .header("content-type", "application/json");
            if let Some(token) = token {
                builder = builder.header("authorization", format!("Bearer {token}"));
            }
            builder.body(Body::from(body(tenant_id))).unwrap()
        };

        let anonymous = app.clone().oneshot(request(None, "legacy")).await.unwrap();
        assert_eq!(anonymous.status(), StatusCode::UNAUTHORIZED);

        let viewer = state
            .auth
            .issue_token_with_tenants("connector-history-test", crate::auth::Role::Viewer, 60, &[])
            .unwrap();
        let allowed = app
            .clone()
            .oneshot(request(Some(&viewer), "legacy"))
            .await
            .unwrap();
        assert_eq!(allowed.status(), StatusCode::OK);

        let foreign = app
            .oneshot(request(Some(&viewer), "tenant-foreign"))
            .await
            .unwrap();
        assert_eq!(foreign.status(), StatusCode::FORBIDDEN);
        server.abort();
    }

    #[test]
    fn configured_connector_scope_authorizes_without_telemetry_shadow_and_rejects_conflict() {
        let mut state = AppState::new();
        state.capabilities = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse("http://127.0.0.1:9").unwrap(),
            token: None,
        }]);
        let state = Arc::new(state);
        let tenant_a = crate::tenant::TenantContext {
            tenant_id: Some("tenant-a".into()),
            building_ids: vec!["building-a".into()],
            hub_admin: false,
            multi_tenant: true,
        };
        let scope = openfdd_contracts::ConnectorScope {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
        };
        assert!(authorized_edge_ids(&state, &tenant_a).contains("edge-a"));
        assert!(authorize_connector_scope(&state, &tenant_a, "edge-a", &scope).is_ok());

        let mut foreign = scope.clone();
        foreign.tenant_id = "tenant-b".into();
        assert_eq!(
            authorize_connector_scope(&state, &tenant_a, "edge-a", &foreign)
                .unwrap_err()
                .0,
            StatusCode::FORBIDDEN
        );

        let entry = state.edges.entry("edge-a".into()).or_default();
        let mut shadow = entry.lock().unwrap();
        shadow.registered_site_id = Some("building-foreign".into());
        shadow.registered_tenant_id = Some("tenant-a".into());
        drop(shadow);
        drop(entry);
        assert_eq!(
            authorize_connector_scope(&state, &tenant_a, "edge-a", &scope)
                .unwrap_err()
                .0,
            StatusCode::FORBIDDEN
        );
    }

    #[test]
    fn connector_proxy_denies_cross_tenant_scope_even_when_building_is_allowed() {
        let ctx = crate::tenant::TenantContext {
            tenant_id: Some("tenant-a".into()),
            building_ids: vec!["building-a".into()],
            hub_admin: false,
            multi_tenant: true,
        };
        let scope = openfdd_contracts::ConnectorScope {
            tenant_id: "tenant-b".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
        };
        assert!(!request_scope_allowed(&ctx, &scope));
    }

    #[test]
    fn connector_inventory_scope_requires_registered_tenant_and_building() {
        let state = Arc::new(AppState::new());
        let entry = state.edges.entry("edge-a".into()).or_default();
        let mut shadow = entry.lock().unwrap();
        shadow.registered_site_id = Some("shared-building".into());
        shadow.registered_tenant_id = Some("tenant-a".into());
        drop(shadow);
        drop(entry);

        let tenant_a = crate::tenant::TenantContext {
            tenant_id: Some("tenant-a".into()),
            building_ids: vec!["shared-building".into()],
            hub_admin: false,
            multi_tenant: true,
        };
        let allowed = openfdd_contracts::ConnectorScope {
            tenant_id: "tenant-a".into(),
            building_id: "shared-building".into(),
            edge_id: "edge-a".into(),
        };
        assert!(authorize_connector_scope(&state, &tenant_a, "edge-a", &allowed).is_ok());

        let mut foreign = allowed.clone();
        foreign.tenant_id = "tenant-b".into();
        assert_eq!(
            authorize_connector_scope(&state, &tenant_a, "edge-a", &foreign)
                .unwrap_err()
                .0,
            StatusCode::FORBIDDEN
        );
        let mut wrong_building = allowed;
        wrong_building.building_id = "other-building".into();
        assert_eq!(
            authorize_connector_scope(&state, &tenant_a, "edge-a", &wrong_building)
                .unwrap_err()
                .0,
            StatusCode::FORBIDDEN
        );
    }

    #[test]
    fn capabilities_filter_overlapping_buildings_by_authoritative_edge_tenant() {
        let state = AppState::new();
        for (edge_id, tenant_id) in [("edge-a", "tenant-a"), ("edge-b", "tenant-b")] {
            let entry = state.edges.entry(edge_id.into()).or_default();
            let mut shadow = entry.lock().unwrap();
            shadow.registered_site_id = Some("shared-building".into());
            shadow.registered_tenant_id = Some(tenant_id.into());
        }
        let ctx = crate::tenant::TenantContext {
            tenant_id: Some("tenant-a".into()),
            building_ids: vec!["shared-building".into()],
            hub_admin: false,
            multi_tenant: true,
        };
        let allowed = authorized_edge_ids(&state, &ctx);
        assert!(allowed.contains("edge-a"));
        assert!(!allowed.contains("edge-b"));
    }

    // Single test so the shared `OPENFDD_GIT_SHA` env var is never raced by a
    // parallel sibling test.
    #[test]
    fn version_prefers_runtime_git_sha_then_crate_version() {
        std::env::set_var("OPENFDD_GIT_SHA", "abcdef1234567890deadbeef");
        let v = resolve_build_version();
        assert!(v.starts_with(env!("CARGO_PKG_VERSION")), "v={v}");
        assert!(v.contains('+'), "expected version+sha, got {v}");
        // Short SHA capped at 12 alphanumerics.
        assert_eq!(v.split('+').nth(1).unwrap(), "abcdef123456");

        std::env::remove_var("OPENFDD_GIT_SHA");
        let fallback = resolve_build_version();
        // Without a runtime SHA it may still carry a compile-time build SHA;
        // at minimum it must start with the crate version.
        assert!(
            fallback.starts_with(env!("CARGO_PKG_VERSION")),
            "v={fallback}"
        );
    }

    #[test]
    fn version_route_body_names_the_build_and_no_secret() {
        let body = super::version_body();
        assert_eq!(body["ok"], true);
        assert_eq!(body["service"], "openfdd-central");
        let version = body["version"].as_str().unwrap();
        assert!(version.starts_with(env!("CARGO_PKG_VERSION")), "{version}");
        assert!(body.get("token").is_none());
        assert!(body.get("password").is_none());
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize process environment while exercising the async ingest handler"
    )]
    async fn local_ingest_own_identity_is_accepted_and_foreign_point_is_denied() {
        let _env_lock = crate::test_env_lock::lock_env();
        let temp = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_LOCAL_INGEST_TOKEN", "route-test-token");
        std::env::set_var("OPENFDD_SITE_ID", "site-http-test");
        std::env::set_var("OPENFDD_BUILDING_ID", "building-http-test");
        std::env::set_var("OPENFDD_LOCAL_ALLOWED_EDGE_IDS", "edge-http-test");
        std::env::set_var("OPENFDD_WORKSPACE", temp.path());
        std::env::set_var(
            "OPENFDD_STORAGE_URL",
            format!("file://{}", temp.path().join("history").display()),
        );
        std::env::set_var("OPENFDD_PARQUET_FLUSH_ROWS", "5000");
        std::env::set_var("OPENFDD_PARQUET_FLUSH_SECONDS", "3600");

        let state = Arc::new(AppState::new());
        let envelope = TelemetryEnvelope::new(
            "building-http-test",
            "edge-http-test",
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "point-http-test".into(),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: serde_json::json!(1.0),
                unit: None,
                quality: Quality::Good,
                observed_at: None,
                tags: serde_json::json!({
                    "building_id": "building-http-test",
                    "equipment_id": "equipment-http-test",
                    "role": "sample"
                })
                .as_object()
                .unwrap()
                .clone(),
            }],
        );
        let mut headers = HeaderMap::new();
        headers.insert(
            "authorization",
            HeaderValue::from_static("Bearer route-test-token"),
        );
        headers.insert(
            "x-openfdd-message-id",
            HeaderValue::from_str(&envelope.message_id.to_string()).unwrap(),
        );
        headers.insert(
            "x-openfdd-building-id",
            HeaderValue::from_static("building-http-test"),
        );
        let request_body = Bytes::from(serde_json::to_vec(&envelope).unwrap());
        let (status, Json(body)) = local_fieldbus_ingest(
            axum::extract::State(Arc::clone(&state)),
            headers.clone(),
            Ok(request_body.clone()),
        )
        .await
        .unwrap();
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body.status, LocalIngestStatus::Committed);
        assert!(!body.duplicate);
        assert_eq!(body.persisted_rows, 1);

        let (replay_status, Json(replay)) = local_fieldbus_ingest(
            axum::extract::State(Arc::clone(&state)),
            headers.clone(),
            Ok(request_body),
        )
        .await
        .unwrap();
        assert_eq!(replay_status, StatusCode::OK);
        assert!(replay.duplicate);
        assert_eq!(replay.status, LocalIngestStatus::Committed);
        assert_eq!(replay.persisted_rows, 1);

        let mut conflict = envelope.clone();
        conflict.points[0].value = serde_json::json!(2.0);
        let conflict = local_fieldbus_ingest(
            axum::extract::State(Arc::clone(&state)),
            headers.clone(),
            Ok(Bytes::from(serde_json::to_vec(&conflict).unwrap())),
        )
        .await
        .unwrap_err();
        assert_eq!(conflict.status, StatusCode::CONFLICT);
        assert_eq!(conflict.receipt.status, LocalIngestStatus::Conflict);

        let mut foreign = envelope;
        foreign.message_id = uuid::Uuid::new_v4();
        foreign.points[0].tags.insert(
            "building_id".into(),
            Value::String("foreign-building".into()),
        );
        headers.insert(
            "x-openfdd-message-id",
            HeaderValue::from_str(&foreign.message_id.to_string()).unwrap(),
        );
        let result = local_fieldbus_ingest(
            axum::extract::State(state),
            headers,
            Ok(Bytes::from(serde_json::to_vec(&foreign).unwrap())),
        )
        .await;
        assert_eq!(result.unwrap_err().status, StatusCode::FORBIDDEN);
        for key in [
            "OPENFDD_LOCAL_INGEST_TOKEN",
            "OPENFDD_SITE_ID",
            "OPENFDD_BUILDING_ID",
            "OPENFDD_LOCAL_ALLOWED_EDGE_IDS",
            "OPENFDD_WORKSPACE",
            "OPENFDD_STORAGE_URL",
            "OPENFDD_PARQUET_FLUSH_ROWS",
            "OPENFDD_PARQUET_FLUSH_SECONDS",
        ] {
            std::env::remove_var(key);
        }
    }
}
