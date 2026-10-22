//! Central REST + OpenAPI routes.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use axum::extract::{DefaultBodyLimit, Extension, Path, Query, Request, State};
use axum::http::{header, HeaderMap, HeaderValue, StatusCode};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, post};
use axum::{Json, Router};
use bytes::Bytes;
use chrono::Utc;
#[cfg(test)]
use openfdd_contracts::ConnectorScope;
use serde::Deserialize;
use serde_json::{json, Value};
use tower::limit::ConcurrencyLimitLayer;

use crate::actions;
use crate::analytics::{self, AnalyticsRequest};
use crate::auth;
use crate::engineering_bundle;
use crate::eplus_runner;
use crate::fuel::{self, FuelRequest};
use crate::ingest_queue;
use crate::jobs;
use crate::models::{
    AgentTool, AgentToolsResponse, AuthAgentTokenRequest, AuthLoginRequest, AuthLoginResponse,
    AuthMeResponse, AuthStatusResponse, FddRunRequest, FddStatusResponse, IngestStatsResponse,
    OkHealthResponse, TenantSelectRequest, TenantSelectResponse,
};
use crate::providers;
use crate::state::AppState;
use crate::wattlab_dump;

pub fn router(state: Arc<AppState>) -> Router {
    let public = Router::new()
        .route("/api/health", get(health))
        .route("/api/version", get(version_public))
        .route("/health", get(health))
        .route("/api/auth/status", get(auth_status))
        .route("/api/auth/me", get(auth_me))
        .route("/api/auth/login", post(auth_login));
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
        .route("/api/health/stack", get(health_stack))
        .route("/api/providers/health", get(providers::providers_health))
        .route("/api/providers/sites", get(providers::providers_sites))
        .route("/api/ingest/jobs", get(ingest_queue::http::list_jobs))
        .route(
            "/api/ingest/jobs/{job_id}",
            get(ingest_queue::http::get_job),
        )
        .route(
            "/api/ingest/jobs/{job_id}/retry",
            post(ingest_queue::http::retry_job),
        )
        .route(
            "/api/ingest/receipts",
            get(ingest_queue::http::list_receipts),
        )
        .route(
            "/api/ingest/receipts/{receipt_id}",
            get(ingest_queue::http::get_receipt),
        )
        .route("/api/ingest/gaps", get(ingest_queue::http::list_gaps))
        .route("/api/ingest/queue", get(ingest_queue::http::queue_metrics))
        .route(
            "/api/ingest/queue/scale-preview",
            get(ingest_queue::http::scale_preview),
        )
        .route("/api/ingest/backfill", post(ingest_queue::http::backfill))
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
        .route("/api/ingest/stats", get(ingest_stats))
        .route("/api/agent/tools", get(agent_tools))
        // C13: playground-style free-form SPARQL + templates + consumers.
        .route("/api/model/sparql", post(central_package_sparql))
        .route(
            "/api/model/sparql/predefined",
            get(central_package_sparql_catalog),
        )
        .route(
            "/api/model/sparql/query",
            post(central_package_sparql_query),
        )
        .route(
            "/api/model/sparql/upload",
            post(central_package_sparql_upload),
        )
        .route(
            "/api/model/sparql/consumers",
            post(central_package_sparql_consumers),
        )
        // Soft-OPEN R5: opaque point IRI → openfdd_key (+ optional Timescale history).
        .route("/api/model/point-resolve", get(model_point_resolve))
        // Soft-OPEN: BPS-compatible TTL alias → strict Haystack projection Turtle.
        .route(
            "/api/model/ttl",
            get(csv_import_package_mapping_haystack_ttl),
        )
        // Soft-OPEN: revisioned semantic_meta CRUD (dry_run + expected_revision CAS).
        .route(
            "/api/model/semantic-meta",
            get(csv_import_package_mapping_semantic_meta).put(model_semantic_meta_put),
        )
        // Soft-OPEN: BPS-compatible Turtle overlay GET/PUT (dry_run + CAS; SPARQL unions pack ∪ overlay).
        .route(
            "/api/model/overlay",
            get(model_overlay_get).put(model_overlay_put),
        )
        // Soft-OPEN: BPS model_crud equip/point upsert + tombstones (overlay sidecar).
        .route(
            "/api/model/equip",
            post(model_equip_post).delete(model_equip_delete),
        )
        .route(
            "/api/model/point",
            post(model_point_post).delete(model_point_delete),
        )
        // Soft-OPEN: BPS-compatible agent recipe bundle (overlay + equip/point CRUD).
        .route("/api/model/agent-context", get(model_agent_context))
        // Soft-OPEN R8a: tip-safe read-only schema/contract probe (no migrator apply).
        .route(
            "/api/admin/schema-contract",
            get(admin_schema_contract_softopen),
        )
        .route("/api/fdd/rules", get(fdd_registry_rules))
        .route("/api/fdd/rules/{rule_id}/params", get(fdd_rule_params))
        .route("/api/fdd/cache/status", get(fdd_cache_status))
        .route("/api/fdd/equipment", get(fdd_equipment))
        .route("/api/fdd/results", get(fdd_results))
        .route("/api/fdd/results/readiness", get(fdd_results_readiness))
        .route("/api/fdd/series", get(fdd_series))
        .route("/api/fdd/plot", get(fdd_plot))
        .route("/api/fdd/plots-by-rule", get(fdd_plots_by_rule))
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
        .route("/api/fuel/campus/import", post(fuel_campus_import))
        .route("/api/fuel/campus", get(fuel_campus_list))
        .route(
            "/api/fuel/campus/weather/fetch",
            post(fuel_campus_weather_fetch),
        )
        .merge(csv)
        // Remaining protected POSTs (FDD run, fuel, admin) stay bounded well
        // below the CSV nest. Analytics no longer inherit 128 MiB (#1169).
        .layer(DefaultBodyLimit::max(16 * 1024 * 1024));

    // #1169: analytics family is isolated from the 128 MiB CSV limit. ZAP AF
    // activeScan must not buffer huge bodies or run unbounded concurrent DF work.
    let analytics = Router::new()
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
        .layer(DefaultBodyLimit::max(analytics_body_limit_bytes()))
        .layer(ConcurrencyLimitLayer::new(analytics_http_max_inflight()));

    let protected = Router::new()
        .merge(protected)
        .merge(analytics)
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            protected_admission_middleware,
        ))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ));

    Router::new()
        .merge(public)
        .merge(protected)
        .with_state(state)
}

/// Authenticated-path admission: mutation rate shed + try_acquire HTTP concurrency.
/// Health/version stay on the public router. Fail-closed 429/503 — never wait and
/// never treat this as an OOM/memory-spike cure (#1127 / #1169 / Q1a logging).
async fn protected_admission_middleware(
    State(state): State<Arc<AppState>>,
    req: Request,
    next: Next,
) -> Response {
    let path = req.uri().path();
    let mutation_kind = match path {
        "/api/commands" => Some("commands"),
        "/api/auth/agent-token" => Some("agent_token"),
        _ => None,
    };
    if let Some(kind) = mutation_kind {
        if state.mutation_rate_limited(kind) {
            return (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({
                    "ok": false,
                    "error": format!(
                        "authenticated {kind} rate budget exceeded; retry later (AF storm shed)"
                    ),
                    "shed": true,
                })),
            )
                .into_response();
        }
    }
    let Some(permit) = state.try_http_permit() else {
        tracing::warn!(
            target: "security_audit",
            event = "http_inflight_shed",
            path,
            "OPENFDD_HTTP_MAX_INFLIGHT saturated; shedding with 503 (fail-closed)"
        );
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(json!({
                "ok": false,
                "error": "authenticated HTTP concurrency limit reached (OPENFDD_HTTP_MAX_INFLIGHT); retry later",
                "shed": true,
            })),
        )
            .into_response();
    };
    let response = next.run(req).await;
    drop(permit);
    response
}

/// Bounded Timescale ping for `/api/health`. A wedged pool must not stall liveness.
async fn timescale_ping_ok() -> bool {
    if !crate::timescale_historian::historian_is_timescale() {
        return false;
    }
    let Ok(tsdb) = fdd_tsdb::Tsdb::connect_from_env().await else {
        return false;
    };
    matches!(
        tokio::time::timeout(std::time::Duration::from_secs(2), tsdb.health_ping()).await,
        Ok(Ok(()))
    )
}

fn analytics_body_limit_bytes() -> usize {
    std::env::var("OPENFDD_ANALYTICS_BODY_LIMIT_BYTES")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0)
        .unwrap_or(2 * 1024 * 1024)
}

fn analytics_http_max_inflight() -> usize {
    std::env::var("OPENFDD_ANALYTICS_HTTP_MAX_INFLIGHT")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0)
        .unwrap_or(2)
}

/// Public liveness body. No historian locks, so a wedged query cannot stall it.
pub fn version_body() -> Value {
    json!({
        "ok": true,
        "service": "openfdd-central",
        "version": resolve_build_version(),
        "historian": "timescale",
        "fdd_engine": "postgres-sql",
        "dual_write": false,
        "ingest": ["nf_portal", "csv"],
        "wave": "Wave-X-3.6.0",
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
    let timescale_ok = timescale_ping_ok().await;
    let starter_seed = {
        let label = crate::starter_seed::status_label();
        if label.is_empty() {
            None
        } else {
            Some(label)
        }
    };
    let ledger = state.receipt_ledger_stats().await;
    let ingest_backpressure = state
        .ingest_backpressure
        .load(std::sync::atomic::Ordering::Relaxed);
    // #1168: never hard-code ok when the durable receipt ledger is saturated.
    let ok = !ledger.high_water;
    Json(OkHealthResponse {
        ok,
        service: "openfdd-central".into(),
        version: resolve_build_version(),
        portal_providers: state.providers.sites.len(),
        csv_ingest: "ready".into(),
        ingest_backpressure,
        receipts_len: ledger.len,
        receipts_capacity: ledger.capacity,
        receipts_pending: ledger.pending,
        receipts_pending_capacity: ledger.pending_capacity,
        multi_tenant: crate::tenant::multi_tenant_enabled(),
        started_at: state
            .started_at
            .to_rfc3339_opts(chrono::SecondsFormat::Secs, true),
        uptime_secs,
        last_ingest_at,
        historian_present,
        historian: Some("timescale".into()),
        timescale_ok,
        starter_seed,
        fdd_engine: Some("postgres-sql".into()),
        dual_write: false,
        memory_budget: Some(fdd_resources::memory_budget_json()),
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
        user_id: String::new(),
        role: body.role,
        tenant_ids: body.tenant_ids,
        password_env: body.password_env,
        password: body.password,
        disabled: body.disabled,
        session_version: 0,
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
    let store = crate::user_store::UserStore::load_or_empty(&ws);
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

    let outcome = match crate::lifecycle::delete_user_cascade(&ws, &username).await {
        Ok(outcome) => outcome,
        Err(crate::lifecycle::UserCascadeError::NotFound(error)) => {
            return Err((
                StatusCode::NOT_FOUND,
                Json(json!({"ok": false, "error": error})),
            ));
        }
        Err(crate::lifecycle::UserCascadeError::Store(error)) => {
            return Err((
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": error})),
            ));
        }
        Err(crate::lifecycle::UserCascadeError::Partial(partial)) => {
            return Err((
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({
                    "ok": false,
                    "error": "cascade purge failed; user not removed",
                    "plan": partial.plan,
                    "purged": partial.purged_json(),
                    "purge_errors": partial.errors,
                })),
            ));
        }
    };
    let store = crate::user_store::UserStore::load_or_empty(&ws);
    tracing::info!(
        target: "security_audit",
        event = "admin_user_delete",
        actor = %admin.sub,
        username = %username,
        purged = outcome.purged.len(),
        skipped_shared = outcome.plan.buildings_shared_skipped.len(),
        "control-plane user deleted with cascade"
    );
    Ok(Json(json!({
        "ok": true,
        "plan": outcome.plan,
        "purged": outcome.purged_json(),
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

/// Operator or admin role. Checked before a dataset write reads an archive
/// or touches files, the historian, or the audit log.
fn require_dataset_writer(
    state: &AppState,
    headers: &HeaderMap,
) -> Result<auth::AuthUser, (StatusCode, Json<Value>)> {
    let user = state.auth.user_from_headers(headers).map_err(|detail| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": detail})),
        )
    })?;
    if !user.role.can_issue_commands() {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "operator or admin role required"
            })),
        ));
    }
    Ok(user)
}

/// Tenant building scope for a dataset write.
///
/// Denial returns 403 and does not append an audit record. Callers must run
/// this before file, historian, or audit side effects.
fn dataset_building_scope_denial(
    user: &auth::AuthUser,
    building_id: Option<&str>,
) -> Option<(StatusCode, Json<Value>)> {
    if !crate::tenant::multi_tenant_enabled() {
        return None;
    }
    let ctx = resolve_tenant_context_for_user(user);
    match building_id.map(str::trim).filter(|s| !s.is_empty()) {
        Some(bid) if ctx.allow_building(bid) => None,
        Some(bid) => Some((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "building not in tenant scope",
                "building_id": bid,
            })),
        )),
        None if ctx.hub_admin => None,
        None => Some((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "building_id required in multi-tenant mode",
            })),
        )),
    }
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

/// Field-protocol scope check retained for unit tests of the archived
/// connector authorization rules. The product router does not expose it.
#[cfg(test)]
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

#[cfg(test)]
fn request_scope_allowed(ctx: &crate::tenant::TenantContext, scope: &ConnectorScope) -> bool {
    ctx.allow_building(&scope.building_id)
        && (ctx.hub_admin || ctx.tenant_id.as_deref() == Some(scope.tenant_id.as_str()))
}

/// Login throttle source IP.
///
/// Default: ignore `X-Forwarded-For` (account key uses `direct`) so rotating a
/// spoofed leftmost hop cannot reset the failure window. When
/// `OPENFDD_TRUST_X_FORWARDED_FOR=1`, use the **rightmost** hop (immediate
/// client of the last trusted appender), never the caller-controlled leftmost.
pub(crate) fn login_throttle_ip(headers: &HeaderMap) -> String {
    let trust = matches!(
        std::env::var("OPENFDD_TRUST_X_FORWARDED_FOR")
            .ok()
            .as_deref()
            .map(str::trim),
        Some("1") | Some("true") | Some("yes") | Some("on")
    );
    if !trust {
        return "direct".into();
    }
    let Some(raw) = headers.get("x-forwarded-for").and_then(|v| v.to_str().ok()) else {
        return "direct".into();
    };
    raw.split(',')
        .map(str::trim)
        .rev()
        .find(|s| !s.is_empty())
        .unwrap_or("direct")
        .to_string()
}

#[cfg(test)]
fn connector_proxy_role_allowed(role: auth::Role) -> bool {
    matches!(
        role,
        auth::Role::Viewer | auth::Role::Operator | auth::Role::Admin
    )
}

#[cfg(test)]
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
    let username = body.username.trim().to_string();
    // Never key throttle on caller-controlled leftmost X-Forwarded-For by default
    // (S06). Optional trusted-proxy mode uses the rightmost hop only.
    let ip = login_throttle_ip(&headers);
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
        active_tenant_id: tenant_ids.first().cloned(),
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
    // S09: child TTL cannot exceed parent bearer remaining lifetime.
    let mut ttl = body.ttl_secs.unwrap_or(3600).clamp(60, 86_400);
    if state.auth.required() {
        let auth_header = headers
            .get(axum::http::header::AUTHORIZATION)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        let parent_token = auth_header
            .strip_prefix("Bearer ")
            .or_else(|| auth_header.strip_prefix("bearer "))
            .map(str::trim)
            .filter(|s| !s.is_empty());
        if let Some(parent_token) = parent_token {
            match state.auth.decode_claims(parent_token) {
                Ok(parent) => {
                    let now = chrono::Utc::now().timestamp();
                    let remaining = parent.exp - now;
                    if remaining < 60 {
                        return Err((
                            axum::http::StatusCode::FORBIDDEN,
                            Json(json!({
                                "ok": false,
                                "error": "parent token near expiry; remint admin session first"
                            })),
                        ));
                    }
                    ttl = ttl.min(remaining);
                }
                Err(detail) => {
                    return Err((
                        axum::http::StatusCode::UNAUTHORIZED,
                        Json(json!({"ok": false, "error": detail})),
                    ));
                }
            }
        }
    }
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

/// Tenant segment formerly written into local fieldbus receipts.
/// Tests keep the header precedence; the product router does not.
#[cfg(test)]
fn local_ingest_receipt_tenant(headers: &HeaderMap) -> String {
    if let Ok(raw) = std::env::var("OPENFDD_TENANT_ID") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            return trimmed.to_string();
        }
    }
    if let Some(raw) = headers
        .get("x-openfdd-tenant-id")
        .and_then(|value| value.to_str().ok())
    {
        let trimmed = raw.trim();
        if !trimmed.is_empty() && trimmed != "-" {
            return trimmed.to_string();
        }
    }
    "-".into()
}

#[utoipa::path(
    get,
    path = "/api/ingest/stats",
    tag = "central",
    security(("bearerAuth" = [])),
    responses((status = 200, description = "Portal ingest counters", body = IngestStatsResponse))
)]
pub async fn ingest_stats(State(state): State<Arc<AppState>>) -> Json<IngestStatsResponse> {
    let ledger = state.receipt_ledger_stats().await;
    Json(IngestStatsResponse {
        ok: !ledger.high_water,
        ingest_ok: *state
            .ingest_ok
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner),
        ingest_dup: *state
            .ingest_dup
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner),
        ingest_reject: *state
            .ingest_reject
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner),
        ingest_backpressure: state
            .ingest_backpressure
            .load(std::sync::atomic::Ordering::Relaxed),
        receipts_len: ledger.len,
        receipts_capacity: ledger.capacity,
        receipts_pending: ledger.pending,
        live_writer_queue_bytes: crate::live_historian::live_writer_queue_bytes(),
        reject_buckets: state
            .ingest_reject_buckets
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone(),
        dead_letters: state
            .dead_letters
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .len(),
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
    let ot = ingest_queue::http::ot_discovery_enabled();
    let tools = ingest_queue::http::discovery_tools(ot)
        .into_iter()
        .map(|(name, method, path)| AgentTool {
            name: name.into(),
            method: method.into(),
            path: path.into(),
        })
        .collect();
    Json(AgentToolsResponse {
        ok: true,
        product_surface: Some("portal-4.0".into()),
        ot_discovery: Some(if ot { "archive-lane" } else { "retired" }.into()),
        tools,
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
    let force_new_data = body.force_new_data
        || body
            .params
            .get("force_new_data")
            .and_then(Value::as_bool)
            .unwrap_or(false);
    // Soft-OPEN write-once (BPS parity / R8f): batch run-all returns cached cohort
    // when results already on file unless force_new_data or a single-rule update.
    let single_update = rule_ids.as_ref().is_some_and(|r| r.len() == 1) && !run_all;
    if crate::timescale_historian::historian_is_timescale()
        && run_all
        && !force_new_data
        && !single_update
    {
        if let Some(bid) = building_id.as_deref() {
            if let Some(cached) = crate::timescale_product::cached_run_all_if_present(bid) {
                return Ok(Json(cached));
            }
        }
    }
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

    // Wave-X Timescale product path — never call DataFusion run_registry.
    if crate::timescale_historian::historian_is_timescale() {
        let mut ts_payload = payload.clone();
        if let Some(obj) = ts_payload.as_object_mut() {
            if let Some(eq) = body.equipment_id.clone() {
                obj.insert("equipment_id".into(), json!(eq));
            }
        }
        let mut result = match tokio::time::timeout(Duration::from_secs(fdd_timeout_secs), async {
            crate::timescale_product::run_fdd_registry(&ts_payload).await
        })
        .await
        {
            Ok(Ok(v)) => v,
            Ok(Err(e)) => json!({
                "ok": false,
                "engine": "postgres-sql",
                "error": e.to_string(),
            }),
            Err(_) => json!({
                "ok": false,
                "timeout": true,
                "engine": "postgres-sql",
                "error": format!(
                    "Timescale FDD run timed out after {fdd_timeout_secs}s (OPENFDD_FDD_RUN_TIMEOUT_SECS)"
                ),
            }),
        };
        if let (Some(bid), Some(obj)) = (echo_building_id, result.as_object_mut()) {
            let missing = obj.get("building_id").map(|v| v.is_null()).unwrap_or(true);
            if missing {
                obj.insert("building_id".into(), json!(bid));
            }
        }
        if let Some(ref aid) = action_id {
            let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
            let run_status = result.get("run_status").and_then(|v| v.as_str());
            let status = match run_status {
                Some("complete") => "ok",
                Some("partial") => "partial",
                Some("failed") => "fail",
                _ => {
                    if ok {
                        "ok"
                    } else {
                        "fail"
                    }
                }
            };
            let detail = json!({
                "ok": ok,
                "run_status": result.get("run_status"),
                "run_id": result.get("run_id"),
                "result_count": result.get("result_count"),
                "rules_succeeded": result.get("rules_succeeded"),
                "rules_failed": result.get("rules_failed"),
                "rules_skipped": result.get("rules_skipped"),
                "total_ms": result.get("total_ms"),
                "error": result.get("error"),
                "engine": "postgres-sql",
            });
            let _ = actions::finish_action(aid, status, Some(detail));
            if let Some(obj) = result.as_object_mut() {
                obj.insert("action_id".into(), json!(aid));
            }
        }
        return Ok(Json(result));
    }

    let compute =
        fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::ManualFdd).ok_or_else(
            || {
                tracing::warn!(
                    target: "security_audit",
                    event = "compute_admission_shed",
                    class = "manual_fdd",
                    "OPENFDD_COMPUTE_MAX_INFLIGHT saturated; FDD deferred with 429"
                );
                (
                    StatusCode::TOO_MANY_REQUESTS,
                    Json(json!({
                        "ok": false,
                        "error": "compute admission limit reached (OPENFDD_COMPUTE_MAX_INFLIGHT); retry later",
                        "shed": true,
                    })),
                )
            },
        )?;
    // Permit + cancel flag move into the worker so HTTP timeout / Actions clear
    // cannot release admission while the registry run still holds pool/CPU
    // (#1127 P1/P2). Timeout alone does not prove cancellation completed.
    let cancel = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let cancel_worker = cancel.clone();
    let mut join = tokio::task::spawn_blocking(move || {
        let _compute = compute;
        open_fdd_edge_prototype::fdd::registry_api::run_registry_with_cancel(
            &payload,
            Some(cancel_worker),
        )
    });
    let mut deferred_action_finish = false;
    let mut result = match tokio::time::timeout(Duration::from_secs(fdd_timeout_secs), &mut join)
        .await
    {
        Ok(Ok(v)) => v,
        Ok(Err(e)) => json!({"ok": false, "error": format!("fdd run task failed: {e}")}),
        Err(_) => {
            cancel.store(true, std::sync::atomic::Ordering::SeqCst);
            let aid = action_id.clone();
            tokio::spawn(async move {
                let outcome = join.await;
                if let Some(aid) = aid {
                    let detail = match outcome {
                        Ok(v) => json!({
                            "ok": false,
                            "timeout": true,
                            "cancel_requested": true,
                            "worker_completed_after_timeout": true,
                            "cancelled": v.get("cancelled"),
                            "rules_succeeded": v.get("rules_succeeded"),
                            "rules_failed": v.get("rules_failed"),
                            "error": v.get("error"),
                        }),
                        Err(e) => json!({
                            "ok": false,
                            "timeout": true,
                            "cancel_requested": true,
                            "worker_completed_after_timeout": true,
                            "error": format!("fdd run task failed after timeout: {e}"),
                        }),
                    };
                    let _ = actions::finish_action(&aid, "fail", Some(detail));
                }
            });
            deferred_action_finish = true;
            json!({
                "ok": false,
                "timeout": true,
                "cancel_requested": true,
                "worker_completion": "pending",
                "error": format!(
                    "fdd run timed out after {fdd_timeout_secs}s (OPENFDD_FDD_RUN_TIMEOUT_SECS); cancel requested — worker completion pending (timeout ≠ cancelled)"
                ),
            })
        }
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
        if !deferred_action_finish {
            let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
            let status = if ok { "ok" } else { "fail" };
            let detail = json!({
                "ok": ok,
                "rules_succeeded": result.get("rules_succeeded"),
                "rules_failed": result.get("rules_failed"),
                "rules_skipped": result.get("rules_skipped"),
                "total_ms": result.get("total_ms"),
                "cancelled": result.get("cancelled"),
                "error": result.get("error"),
            });
            let _ = actions::finish_action(aid, status, Some(detail));
        }
        if let Some(obj) = result.as_object_mut() {
            obj.insert("action_id".into(), json!(aid));
        }
    }

    Ok(Json(result))
}

pub async fn fdd_registry_rules() -> Json<Value> {
    if crate::timescale_historian::historian_is_timescale() {
        match fdd_tsdb::Tsdb::connect_from_env().await {
            Ok(tsdb) => match crate::timescale_analytics::fdd_registry(&tsdb).await {
                Ok(v) => return Json(v),
                Err(e) => {
                    return Json(
                        json!({"ok": false, "error": e.to_string(), "engine": "postgres-sql"}),
                    )
                }
            },
            Err(e) => {
                return Json(json!({"ok": false, "error": e.to_string(), "engine": "postgres-sql"}))
            }
        }
    }
    Json(open_fdd_edge_prototype::fdd::registry_api::list_registry_rules())
}

pub async fn fdd_rule_params(Path(rule_id): Path<String>) -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::rule_params_with_quantity(&rule_id))
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
    if crate::timescale_historian::historian_is_timescale() {
        return match crate::timescale_product::equipment_from_timescale(q.scoped()).await {
            Ok(v) => Ok(Json(v)),
            Err(e) => Ok(Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
                "equipment": [],
                "count": 0,
            }))),
        };
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
    // Soft-OPEN P0-2: kind filter must use Timescale equipment stamps, not
    // Parquet-era equipment_types.json (empty → every rule NOT_APPLICABLE).
    if crate::timescale_historian::historian_is_timescale() {
        let types = crate::timescale_product::type_map_for_building(q.scoped())
            .await
            .unwrap_or_default();
        return Ok(Json(
            open_fdd_edge_prototype::fdd::registry_api::results_response_with_types(
                q.scoped(),
                &types,
                "timescale_equipment",
            ),
        ));
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
    #[serde(default)]
    max_points: Option<usize>,
    #[serde(default)]
    window_start: Option<String>,
    #[serde(default)]
    window_end: Option<String>,
}

pub async fn fdd_series(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<FddSeriesQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    fdd_plot_inner(state, headers, query).await
}

/// C12 lean Plotly: one visible rule+equip → catalog roles → Timescale downsample.
pub async fn fdd_plot(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(query): Query<FddSeriesQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    fdd_plot_inner(state, headers, query).await
}

async fn fdd_plot_inner(
    state: Arc<AppState>,
    headers: HeaderMap,
    query: FddSeriesQuery,
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
            "series": {},
            "building_id": query.building_id,
            "equipment_id": query.equipment_id,
            "rule_id": query.rule_id,
        })));
    };
    let equipment_id = equipment_id.to_string();
    let rule_id = rule_id.to_string();
    let building_id = query.building_id.clone();
    if crate::timescale_historian::historian_is_timescale() {
        return match crate::timescale_product::fdd_plot(
            building_id.as_deref(),
            &equipment_id,
            &rule_id,
            query.max_points,
            query.window_start.as_deref(),
            query.window_end.as_deref(),
        )
        .await
        {
            Ok(v) => Ok(Json(v)),
            Err(e) => Ok(Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
                "equipment_id": equipment_id,
                "rule_id": rule_id,
                "rows": [],
                "series": {},
            }))),
        };
    }
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

/// Soft-OPEN R4: catalog lean-plot roles per rule (Timescale path).
pub async fn fdd_plots_by_rule() -> Json<Value> {
    if crate::timescale_historian::historian_is_timescale() {
        return match crate::timescale_product::plots_by_rule_catalog() {
            Ok(v) => Json(v),
            Err(e) => Json(json!({
                "ok": false,
                "error": e.to_string(),
                "engine": "timescale-sql",
                "rules": [],
            })),
        };
    }
    Json(json!({
        "ok": false,
        "error": "plots-by-rule Soft-OPEN requires Timescale product historian",
        "rules": [],
    }))
}

#[derive(Debug, Deserialize)]
pub struct PointResolveQuery {
    /// Opaque `urn:openfdd:site/{bid}/equip/{eid}/point/{key}` Soft-OPEN R5.
    pub point_iri: Option<String>,
    /// When true (default false), attach bounded Timescale `sample` history.
    pub include_history: Option<bool>,
    pub max_points: Option<usize>,
}

/// Soft-OPEN R5: opaque point IRI → building/equip/point_key + openfdd_key (+ optional history).
pub async fn model_point_resolve(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<PointResolveQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let iri = q
        .point_iri
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| {
            (
                StatusCode::BAD_REQUEST,
                Json(json!({
                    "ok": false,
                    "error": "point_iri query parameter required",
                    "soft_open_neq_fq": true,
                })),
            )
        })?;
    let parsed =
        open_fdd_edge_prototype::csv_ingest::haystack_projection::parse_opaque_point_iri(iri)
            .map_err(|e| {
                (
                    StatusCode::BAD_REQUEST,
                    Json(json!({
                        "ok": false,
                        "error": e,
                        "soft_open_neq_fq": true,
                    })),
                )
            })?;
    if let Some(deny) =
        deny_if_building_out_of_scope(&state, &headers, Some(parsed.building_id.as_str()))
    {
        return Err(deny);
    }
    let openfdd_key = parsed.openfdd_key();
    let candidate_keys = crate::timescale_product::candidate_openfdd_keys_for_point(
        &parsed.building_id,
        &parsed.equipment_id,
        &parsed.point_key,
    );
    let mut body = json!({
        "ok": true,
        "point_iri": iri,
        "building_id": parsed.building_id,
        "equipment_id": parsed.equipment_id,
        "point_key": parsed.point_key,
        "openfdd_key": openfdd_key,
        "candidate_openfdd_keys": candidate_keys,
        "soft_open_neq_fq": true,
        "note": "Soft-OPEN opaque point resolve (#1278 column≠role candidates) — Soft-OPEN ≠ FQ",
    });
    if q.include_history.unwrap_or(false) {
        let history = if !crate::timescale_historian::historian_is_timescale() {
            json!({
                "ok": false,
                "error": "opaque point history Soft-OPEN requires Timescale product historian",
                "soft_open_neq_fq": true,
            })
        } else {
            let max_pts = q.max_points.unwrap_or(500);
            match crate::timescale_product::opaque_point_history_softopen(
                &parsed.building_id,
                &openfdd_key,
                max_pts,
            )
            .await
            {
                Ok(hist) => {
                    // Prefer the key that actually had samples (role key when column≠role).
                    if let Some(resolved) = hist.get("openfdd_key").and_then(Value::as_str) {
                        if let Some(obj) = body.as_object_mut() {
                            obj.insert("openfdd_key".into(), json!(resolved));
                            obj.insert("requested_openfdd_key".into(), json!(openfdd_key));
                        }
                    }
                    hist
                }
                Err(e) => json!({
                    "ok": false,
                    "error": e.to_string(),
                    "soft_open_neq_fq": true,
                }),
            }
        };
        if let Some(obj) = body.as_object_mut() {
            obj.insert("history".into(), history);
        }
    }
    Ok(Json(body))
}

/// Soft-OPEN R8a: hub-admin tip-safe schema/contract read (no migrator apply / no volume destroy).
pub async fn admin_schema_contract_softopen(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let _admin = require_hub_admin(&state, &headers)?;
    if !crate::timescale_historian::historian_is_timescale() {
        return Ok(Json(json!({
            "ok": true,
            "probe": "schema_contract_softopen",
            "engine": "not-timescale",
            "migrator": {"applied": false},
            "soft_open_neq_fq": true,
            "note": "Soft-OPEN schema-contract probe N/A without Timescale historian — Soft-OPEN ≠ FQ",
        })));
    }
    match crate::timescale_product::schema_contract_softopen().await {
        Ok(v) => Ok(Json(v)),
        Err(e) => Ok(Json(json!({
            "ok": false,
            "error": e.to_string(),
            "soft_open_neq_fq": true,
        }))),
    }
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

pub async fn list_actions(
    Extension(user): Extension<auth::AuthUser>,
    Query(q): Query<ActionsQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    crate::actions_scope::list_actions(&user, q.limit).await
}

pub async fn delete_one_action(
    Extension(user): Extension<auth::AuthUser>,
    Path(id): Path<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    crate::actions_scope::delete_action(&user, &id).await
}

pub async fn clear_actions(
    Extension(user): Extension<auth::AuthUser>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    crate::actions_scope::clear_actions(&user).await
}

#[derive(Debug, Deserialize)]
pub struct SessionConfigQuery {
    #[serde(default)]
    pub building_id: Option<String>,
}

impl SessionConfigQuery {
    fn scoped(&self) -> Option<&str> {
        self.building_id
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
    }
}

/// `openfdd_session_v1` session/fault settings (#515) — tenant/building scoped.
/// Wave O9: `building_id` query/body is ACL-gated when multi-tenant is on.
/// S03: bytes are stored under the authoritative tenant+building path.
pub async fn fdd_session_config_get(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<SessionConfigQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, q.building_id.as_deref()) {
        return Err(deny);
    }
    if crate::tenant::multi_tenant_enabled() && q.scoped().is_none() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id is required for session-config under multi-tenant mode"
            })),
        ));
    }
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, q.scoped());
    let scope = open_fdd_edge_prototype::fdd::session_config::SessionConfigScope::new(
        preferred.as_deref(),
        q.scoped(),
    );
    Ok(Json(
        open_fdd_edge_prototype::fdd::session_config::get_session_config_scoped(&scope),
    ))
}

pub async fn fdd_session_config_put(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(mut body): Json<Value>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let user = state.auth.user_from_headers(&headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    if matches!(user.role, auth::Role::Viewer) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "viewer role cannot mutate session-config"
            })),
        ));
    }
    let building_id = body
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    if crate::tenant::multi_tenant_enabled() && building_id.is_none() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id is required for session-config under multi-tenant mode"
            })),
        ));
    }
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, building_id.as_deref()) {
        return Err(deny);
    }
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, building_id.as_deref());
    // Server-derived tenant only — ignore any client-supplied tenant_id.
    if let Some(obj) = body.as_object_mut() {
        match preferred.as_deref() {
            Some(tid) => {
                obj.insert("tenant_id".into(), json!(tid));
            }
            None => {
                obj.remove("tenant_id");
            }
        }
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
        rules_dir,
        rules_dir_exists,
        rule_count: count,
        hint: if count == 0 {
            Some("set OPENFDD_SQL_RULES_DIR or ship sql_rules/ in the image".into())
        } else {
            Some("POST /api/fdd/run with mode=registry (typed params; no raw SQL)".into())
        },
    })
}

// --- CSV import (UT3) — same handlers as edge lib; execute also fills the Timescale historian ---

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
    // Role before admission, archive parse, files, historian, or audit.
    let writer = require_dataset_writer(&state, &headers)?;
    // Admit before peek/decompress (#1127 P1). Body bytes are already buffered by
    // axum; do not start zip work until import + compute slots are held.
    let compute = fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::Import)
        .ok_or_else(|| {
            (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({
                    "ok": false,
                    "error": "compute admission limit reached (OPENFDD_COMPUTE_MAX_INFLIGHT); retry later"
                })),
            )
        })?;
    let import_slot = crate::historian_limits::acquire_import_slot()
        .await
        .map_err(|e| {
            (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"ok": false, "error": e})),
            )
        })?;
    let ct = content_type(&headers);
    let peeked_building =
        match open_fdd_edge_prototype::csv_ingest::package::peek_package_building_id(&ct, &body) {
            Ok(bid) => {
                if let Some(deny) = dataset_building_scope_denial(&writer, Some(&bid)) {
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
    let action_id = actions::start_action(
        "package_import",
        "Package import",
        Some(json!({ "content_type": ct.clone() })),
    )
    .ok();
    let mut result = tokio::task::spawn_blocking(move || {
        let _compute = compute;
        let _import_slot = import_slot;
        open_fdd_edge_prototype::csv_ingest::package::import_package_handler(&ct, &body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package import task: {e}")}));
    let ok = result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
    if ok {
        // Wave-X: seed Timescale from materialized package_root (no Parquet).
        if crate::timescale_historian::historian_is_timescale()
            && result
                .get("needs_timescale_seed")
                .and_then(|v| v.as_bool())
                .unwrap_or(true)
        {
            if let (Some(bid), Some(root)) = (
                result
                    .get("building_id")
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
                    .or(peeked_building.clone()),
                result
                    .get("package_root")
                    .and_then(|v| v.as_str())
                    .map(str::to_string),
            ) {
                let sql_root =
                    std::env::var("OPENFDD_SQL_ROOT").unwrap_or_else(|_| "sql/fdd".into());
                match fdd_tsdb::Tsdb::connect_from_env().await {
                    Ok(tsdb) => {
                        match fdd_tsdb::seed_package_dir(
                            &tsdb,
                            std::path::Path::new(&root),
                            &bid,
                            std::path::Path::new(&sql_root),
                        )
                        .await
                        {
                            Ok(n) => {
                                if let Some(obj) = result.as_object_mut() {
                                    obj.insert("timescale_samples_upserted".into(), json!(n));
                                    obj.insert("historian".into(), json!("timescale"));
                                    obj.insert("dual_write".into(), json!(false));
                                    obj.insert("total_rows".into(), json!(n));
                                }
                            }
                            Err(e) => {
                                return Err((
                                    StatusCode::INTERNAL_SERVER_ERROR,
                                    Json(json!({
                                        "ok": false,
                                        "error": format!("timescale package seed: {e:#}"),
                                        "package_root": root,
                                        "building_id": bid,
                                    })),
                                ));
                            }
                        }
                    }
                    Err(e) => {
                        return Err((
                            StatusCode::SERVICE_UNAVAILABLE,
                            Json(json!({
                                "ok": false,
                                "error": format!("timescale connect: {e}"),
                                "hint": "OPENFDD_DATABASE_URL required",
                            })),
                        ));
                    }
                }
            }
        }
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
    // Role before archive parse, files, historian, or audit.
    let writer = require_dataset_writer(&state, &headers)?;
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
    if let Some(deny) = dataset_building_scope_denial(&writer, building_id.as_deref()) {
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
    // Admit compute before merge/parse (M70-04) — body limits alone do not
    // bound existing history streams. Match seed ordering: compute then import.
    let compute = fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::Import)
        .ok_or_else(|| {
            tracing::warn!(
                target: "security_audit",
                event = "compute_admission_shed",
                class = "import_append",
                "OPENFDD_COMPUTE_MAX_INFLIGHT saturated; package append deferred with 429"
            );
            (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({
                    "ok": false,
                    "error": "compute admission limit reached (OPENFDD_COMPUTE_MAX_INFLIGHT); retry later",
                    "shed": true,
                })),
            )
        })?;
    let import_slot = crate::historian_limits::acquire_import_slot()
        .await
        .map_err(|e| {
            (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({"ok": false, "error": e})),
            )
        })?;
    let mut result = tokio::task::spawn_blocking(move || {
        let _compute = compute;
        let _import_slot = import_slot;
        open_fdd_edge_prototype::csv_ingest::package::append_package_handler(&ct, &body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package append task: {e}")}));
    // Wave-X C4: CSV merge alone is not success — commit Timescale upsert first.
    if result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false)
        && crate::timescale_historian::historian_is_timescale()
        && result
            .get("needs_timescale_seed")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
    {
        let bid = result
            .get("building_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or(building_id.clone());
        let root = result
            .get("package_root")
            .and_then(|v| v.as_str())
            .map(str::to_string);
        let touched: Vec<String> = result
            .get("scoped_equipment")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default();
        if let (Some(bid), Some(root)) = (bid, root) {
            let sql_root = std::env::var("OPENFDD_SQL_ROOT").unwrap_or_else(|_| "sql/fdd".into());
            match fdd_tsdb::Tsdb::connect_from_env().await {
                Ok(tsdb) => {
                    match fdd_tsdb::append_package_equipment(
                        &tsdb,
                        std::path::Path::new(&root),
                        &bid,
                        std::path::Path::new(&sql_root),
                        &touched,
                    )
                    .await
                    {
                        Ok(n) => {
                            if let Some(obj) = result.as_object_mut() {
                                obj.insert("timescale_samples_upserted".into(), json!(n));
                                obj.insert("total_rows".into(), json!(n));
                                obj.insert("historian".into(), json!("timescale"));
                                obj.insert("needs_timescale_seed".into(), json!(false));
                                obj.insert(
                                    "warnings".into(),
                                    json!(["Wave-X: Timescale append committed before success"]),
                                );
                            }
                        }
                        Err(e) => {
                            result = json!({
                                "ok": false,
                                "building_id": bid,
                                "error": format!("timescale append failed (CSV merge rolled back from client view): {e:#}"),
                                "historian": "timescale",
                                "needs_timescale_seed": true,
                            });
                        }
                    }
                }
                Err(e) => {
                    result = json!({
                        "ok": false,
                        "error": format!("timescale connect for append: {e}"),
                        "historian": "timescale",
                    });
                }
            }
        }
    }
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
    let user = state.auth.user_from_headers(&headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    // Scope alone is not mutation permission — viewers may read mapping, not rewrite roles.
    if matches!(user.role, auth::Role::Viewer) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "viewer role cannot mutate package roles"
            })),
        ));
    }
    let building_id = body
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::to_string);
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, building_id.as_deref()) {
        return Err(deny);
    }
    // Wave-X C4: mapping edits update columns.csv then Timescale remap (no Parquet).
    let compute = fdd_resources::try_acquire_compute(fdd_resources::ComputeClass::Import)
        .ok_or_else(|| {
            tracing::warn!(
                target: "security_audit",
                event = "compute_admission_shed",
                class = "import_roles",
                "OPENFDD_COMPUTE_MAX_INFLIGHT saturated; package roles deferred with 429"
            );
            (
                StatusCode::TOO_MANY_REQUESTS,
                Json(json!({
                    "ok": false,
                    "error": "compute admission limit reached (OPENFDD_COMPUTE_MAX_INFLIGHT); retry later",
                    "shed": true,
                })),
            )
        })?;
    let mut result = tokio::task::spawn_blocking(move || {
        let _compute = compute;
        open_fdd_edge_prototype::csv_ingest::package::update_package_roles_handler(&body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package roles task: {e}")}));
    if result.get("ok").and_then(|v| v.as_bool()).unwrap_or(false)
        && crate::timescale_historian::historian_is_timescale()
    {
        let bid = result
            .get("building_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or(building_id.clone());
        let eid = result
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .map(str::to_string);
        let root = result
            .get("package_root")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or_else(|| {
                bid.as_ref().map(|b| {
                    format!(
                        "{}/data/csv_buildings/{b}",
                        std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into())
                    )
                })
            });
        if let (Some(bid), Some(eid), Some(root)) = (bid, eid, root) {
            let sql_root = std::env::var("OPENFDD_SQL_ROOT").unwrap_or_else(|_| "sql/fdd".into());
            match fdd_tsdb::Tsdb::connect_from_env().await {
                Ok(tsdb) => {
                    match fdd_tsdb::remap_equipment_roles(
                        &tsdb,
                        std::path::Path::new(&root),
                        &bid,
                        &eid,
                        std::path::Path::new(&sql_root),
                    )
                    .await
                    {
                        Ok(n) => {
                            if let Some(obj) = result.as_object_mut() {
                                obj.insert("timescale_samples_upserted".into(), json!(n));
                                obj.insert("historian".into(), json!("timescale"));
                                obj.insert("parquet_ingest".into(), json!(false));
                            }
                        }
                        Err(e) => {
                            result = json!({
                                "ok": false,
                                "building_id": bid,
                                "equipment_id": eid,
                                "error": format!("timescale remap failed: {e:#}"),
                                "historian": "timescale",
                            });
                        }
                    }
                }
                Err(e) => {
                    result = json!({
                        "ok": false,
                        "error": format!("timescale connect for remap: {e}"),
                    });
                }
            }
        }
    }
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
    let disk_building = building_id.clone();
    let disk_equipment = equipment_id.clone();
    let mut result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::get_package_mapping_handler_scoped(
            &disk_building,
            disk_equipment.as_deref(),
            preferred.as_deref(),
        )
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package mapping task: {e}")}));
    let disk_equipment_count = result
        .get("equipment")
        .and_then(Value::as_array)
        .map(|rows| rows.len())
        .unwrap_or(0);
    let disk_ok = result.get("ok").and_then(Value::as_bool).unwrap_or(false);
    if crate::timescale_historian::historian_is_timescale()
        && (!disk_ok || disk_equipment_count == 0)
    {
        if let Ok(mapped) = crate::timescale_product::package_mapping_from_samples(
            &building_id,
            equipment_id.as_deref(),
        )
        .await
        {
            if mapped.get("ok").and_then(Value::as_bool) == Some(true) {
                result = mapped;
            }
        }
    }
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
            Ok(Some(meta)) => {
                let revision = meta.revision.clone();
                json!({
                    "ok": true,
                    "present": true,
                    "schema": open_fdd_edge_prototype::csv_ingest::semantic_meta::SCHEMA,
                    "building_id": building_id,
                    "revision": revision,
                    "meta": meta,
                    "soft_open_neq_fq": true,
                })
            }
            Ok(None) => json!({
                "ok": true,
                "present": false,
                "schema": open_fdd_edge_prototype::csv_ingest::semantic_meta::SCHEMA,
                "building_id": building_id,
                "revision": Value::Null,
                "soft_open_neq_fq": true,
                "note": "Soft-OPEN tip-safe: missing semantic_meta is an honest present=false (≠ FQ RDF/SPARQL site proof)",
            }),
            Err(e) => json!({"ok": false, "error": e, "soft_open_neq_fq": true}),
        }
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("semantic-meta task: {e}")}));
    if result.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        return Err((StatusCode::BAD_REQUEST, Json(result)));
    }
    Ok(Json(result))
}

#[derive(Debug, Deserialize)]
pub struct SemanticMetaPutBody {
    /// Target building (must match `meta.building_id` when set).
    pub building_id: String,
    /// Native `openfdd_semantic_meta_v1` (or C1 sketch upgraded on parse).
    pub meta: Value,
    /// CAS precondition against tip revision (BPS `expected_revision` analogue).
    pub expected_revision: Option<String>,
    /// When true, validate + CAS-check without publishing (BPS `dry_run`).
    #[serde(default)]
    pub dry_run: bool,
}

/// Soft-OPEN: revisioned semantic_meta PUT with dry_run + expected_revision CAS (#997/#1123).
///
/// Authority stays `openfdd_semantic_meta_v1` (not BPS Turtle overlay). Soft-OPEN ≠ FQ —
/// overlay equip/point CRUD is a separate writable layer (`model_overlay.ttl`).
pub async fn model_semantic_meta_put(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<SemanticMetaPutBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let user = state.auth.user_from_headers(&headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e, "soft_open_neq_fq": true})),
        )
    })?;
    if matches!(user.role, auth::Role::Viewer) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "viewer role cannot mutate semantic_meta",
                "soft_open_neq_fq": true,
            })),
        ));
    }
    let building_id = body.building_id.trim().to_string();
    if building_id.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id required",
                "soft_open_neq_fq": true,
            })),
        ));
    }
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }

    let expected = body
        .expected_revision
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let dry_run = body.dry_run;
    let meta_raw = body.meta;
    let cache = state.haystack_rdf.clone();

    let result = tokio::task::spawn_blocking(move || {
        let root = open_fdd_edge_prototype::historian::store::workspace_dir()
            .join("data")
            .join("csv_buildings")
            .join(&building_id);
        std::fs::create_dir_all(&root).map_err(|e| {
            json!({
                "ok": false,
                "error": format!("create building root: {e}"),
                "soft_open_neq_fq": true,
            })
        })?;

        let mut meta =
            open_fdd_edge_prototype::csv_ingest::semantic_meta::parse_semantic_meta(&meta_raw)
                .map_err(|e| {
                    json!({
                        "ok": false,
                        "error": e,
                        "soft_open_neq_fq": true,
                    })
                })?;
        if meta.building_id != building_id {
            return Err(json!({
                "ok": false,
                "error": format!(
                    "meta.building_id {:?} does not match request building_id {building_id:?}",
                    meta.building_id
                ),
                "soft_open_neq_fq": true,
            }));
        }
        // Tip revision for CAS / dry_run response (None when no head yet).
        let current = open_fdd_edge_prototype::csv_ingest::semantic_meta::load_persisted(&root)
            .map_err(|e| json!({"ok": false, "error": e, "soft_open_neq_fq": true}))?;
        let current_rev = current
            .as_ref()
            .and_then(|m| m.revision.clone())
            .unwrap_or_default();

        if let Some(want) = expected.as_deref() {
            let have = current.as_ref().and_then(|m| m.revision.as_deref());
            let ok = match have {
                Some(cur) => cur == want,
                None => want.is_empty(),
            };
            if !ok {
                return Err(json!({
                    "ok": false,
                    "conflict": true,
                    "error": "semantic meta revision conflict (reload and retry)",
                    "building_id": building_id,
                    "revision": if current_rev.is_empty() {
                        Value::Null
                    } else {
                        json!(current_rev)
                    },
                    "expected_revision": want,
                    "soft_open_neq_fq": true,
                }));
            }
        }

        if dry_run {
            return Ok(json!({
                "ok": true,
                "dry_run": true,
                "building_id": building_id,
                "revision": if current_rev.is_empty() {
                    Value::Null
                } else {
                    json!(current_rev)
                },
                "would_publish": true,
                "schema": open_fdd_edge_prototype::csv_ingest::semantic_meta::SCHEMA,
                "soft_open_neq_fq": true,
                "note": "dry_run validated parse + CAS; no head published",
            }));
        }

        meta.building_id = building_id.clone();
        let rev = open_fdd_edge_prototype::csv_ingest::semantic_meta::persist_atomic(
            &root,
            meta,
            expected.as_deref(),
        )
        .map_err(|e| {
            let conflict = e.contains("revision conflict");
            json!({
                "ok": false,
                "conflict": conflict,
                "error": e,
                "building_id": building_id,
                "soft_open_neq_fq": true,
            })
        })?;
        cache.invalidate_building(&building_id);
        Ok(json!({
            "ok": true,
            "dry_run": false,
            "building_id": building_id,
            "revision": rev.revision,
            "content_sha256": rev.content_sha256,
            "schema": rev.schema,
            "soft_open_neq_fq": true,
        }))
    })
    .await
    .unwrap_or_else(|e| {
        Err(json!({
            "ok": false,
            "error": format!("semantic-meta put task: {e}"),
            "soft_open_neq_fq": true,
        }))
    });

    match result {
        Ok(body) => Ok(Json(body)),
        Err(err) => {
            let status = if err.get("conflict") == Some(&json!(true)) {
                StatusCode::CONFLICT
            } else {
                StatusCode::BAD_REQUEST
            };
            Err((status, Json(err)))
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct AgentContextQuery {
    /// Open-FDD building scope (preferred).
    #[serde(default)]
    building_id: Option<String>,
    /// BPS alias for `building_id` (accepted when `building_id` is absent).
    #[serde(default)]
    site_id: Option<String>,
}

fn agent_context_model_tree(
    meta: Option<&open_fdd_edge_prototype::csv_ingest::semantic_meta::SemanticMetaV1>,
    inventory: &Value,
) -> Value {
    if let Some(m) = meta {
        let equipment: Vec<Value> = m
            .equipment
            .iter()
            .map(|e| {
                json!({
                    "equipment_id": e.equipment_id,
                    "display_name": e.display_name,
                    "haystack_tags": e.haystack_tags,
                })
            })
            .collect();
        let points: Vec<Value> = m
            .points
            .iter()
            .map(|p| {
                json!({
                    "equipment_id": p.equipment_id,
                    "point_id": p.point_id.as_deref().unwrap_or(p.column.as_str()),
                    "column": p.column,
                    "haystack_tags": p.haystack_tags,
                    "unit": p.unit,
                })
            })
            .collect();
        return json!({
            "source": "semantic_meta",
            "equipment": equipment,
            "points": points,
            "equipment_count": equipment.len(),
            "point_count": points.len(),
        });
    }
    let inv_ok = inventory.get("ok").and_then(|v| v.as_bool()) == Some(true);
    if inv_ok {
        let equipment_ids = inventory
            .get("equipment_ids")
            .cloned()
            .unwrap_or_else(|| json!([]));
        let eq_count = inventory
            .get("equipment")
            .and_then(|v| v.as_array())
            .map(|a| a.len())
            .or_else(|| equipment_ids.as_array().map(|a| a.len()))
            .unwrap_or(0);
        return json!({
            "source": "inventory",
            "equipment_ids": equipment_ids,
            "equipment_count": eq_count,
            "point_count": 0,
            "note": "semantic_meta absent — inventory ids only (no point overlay)",
        });
    }
    json!({
        "source": "empty",
        "equipment": [],
        "points": [],
        "equipment_count": 0,
        "point_count": 0,
    })
}

#[derive(Debug, Deserialize)]
pub struct ModelOverlayQuery {
    #[serde(default)]
    building_id: Option<String>,
    /// BPS alias for `building_id`.
    #[serde(default)]
    site_id: Option<String>,
}

fn resolve_building_or_site(building_id: Option<&str>, site_id: Option<&str>) -> Option<String> {
    building_id
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .or_else(|| site_id.map(str::trim).filter(|s| !s.is_empty()))
        .map(str::to_string)
}

/// Soft-OPEN: read writable Turtle overlay sidecar (#997/#1123).
///
/// BPS-compatible shape. Soft-OPEN ≠ FQ — SPARQL unions pack ∪ overlay (− tombstones).
pub async fn model_overlay_get(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<ModelOverlayQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(building_id) =
        resolve_building_or_site(q.building_id.as_deref(), q.site_id.as_deref())
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id (or site_id alias) query parameter required",
                "soft_open_neq_fq": true,
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
        open_fdd_edge_prototype::csv_ingest::model_overlay::get_overlay_payload(&root, &building_id)
            .unwrap_or_else(|e| {
                json!({
                    "ok": false,
                    "error": e,
                    "building_id": building_id,
                    "soft_open_neq_fq": true,
                })
            })
    })
    .await
    .unwrap_or_else(|e| {
        json!({
            "ok": false,
            "error": format!("overlay get task: {e}"),
            "soft_open_neq_fq": true,
        })
    });
    if result.get("ok").and_then(|v| v.as_bool()) == Some(false) {
        return Err((StatusCode::BAD_REQUEST, Json(result)));
    }
    Ok(Json(result))
}

#[derive(Debug, Deserialize)]
pub struct ModelOverlayPutBody {
    #[serde(default)]
    pub building_id: Option<String>,
    /// BPS alias for `building_id`.
    #[serde(default)]
    pub site_id: Option<String>,
    pub ttl: String,
    #[serde(default)]
    pub expected_revision: Option<u64>,
    #[serde(default)]
    pub dry_run: bool,
}

/// Soft-OPEN: replace Turtle overlay with dry_run + expected_revision CAS (#997/#1123).
///
/// Authority is the `model_overlay.ttl` sidecar (BPS overlay shape). Soft-OPEN ≠ FQ —
/// SPARQL query path unions pack ∪ overlay (− tombstones).
pub async fn model_overlay_put(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<ModelOverlayPutBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let user = state.auth.user_from_headers(&headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e, "soft_open_neq_fq": true})),
        )
    })?;
    if matches!(user.role, auth::Role::Viewer) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "viewer role cannot mutate model overlay",
                "soft_open_neq_fq": true,
            })),
        ));
    }
    let Some(building_id) =
        resolve_building_or_site(body.building_id.as_deref(), body.site_id.as_deref())
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id (or site_id alias) required",
                "soft_open_neq_fq": true,
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }

    let ttl = body.ttl;
    let expected = body.expected_revision;
    let dry_run = body.dry_run;

    let result = tokio::task::spawn_blocking(move || {
        let root = open_fdd_edge_prototype::historian::store::workspace_dir()
            .join("data")
            .join("csv_buildings")
            .join(&building_id);
        open_fdd_edge_prototype::csv_ingest::model_overlay::put_overlay_ttl(
            &root,
            &building_id,
            &ttl,
            expected,
            dry_run,
        )
    })
    .await
    .unwrap_or_else(|e| {
        Err(json!({
            "ok": false,
            "error": format!("overlay put task: {e}"),
            "soft_open_neq_fq": true,
        }))
    });

    match result {
        Ok(body) => Ok(Json(body)),
        Err(err) => {
            let status = if err.get("conflict") == Some(&json!(true)) {
                StatusCode::CONFLICT
            } else {
                StatusCode::BAD_REQUEST
            };
            Err((status, Json(err)))
        }
    }
}

fn deny_viewer_model_mutate(
    state: &AppState,
    headers: &HeaderMap,
) -> Result<(), (StatusCode, Json<Value>)> {
    let user = state.auth.user_from_headers(headers).map_err(|e| {
        (
            StatusCode::UNAUTHORIZED,
            Json(json!({"ok": false, "error": e, "soft_open_neq_fq": true})),
        )
    })?;
    if matches!(user.role, auth::Role::Viewer) {
        return Err((
            StatusCode::FORBIDDEN,
            Json(json!({
                "ok": false,
                "error": "viewer role cannot mutate model overlay",
                "soft_open_neq_fq": true,
            })),
        ));
    }
    Ok(())
}

fn csv_building_root(building_id: &str) -> std::path::PathBuf {
    open_fdd_edge_prototype::historian::store::workspace_dir()
        .join("data")
        .join("csv_buildings")
        .join(building_id)
}

fn overlay_mutate_result(
    result: Result<Value, Value>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    match result {
        Ok(body) => Ok(Json(body)),
        Err(err) => {
            let status = if err.get("conflict") == Some(&json!(true)) {
                StatusCode::CONFLICT
            } else {
                StatusCode::BAD_REQUEST
            };
            Err((status, Json(err)))
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct ModelEquipBody {
    #[serde(default)]
    pub building_id: Option<String>,
    #[serde(default)]
    pub site_id: Option<String>,
    pub equipment_id: String,
    #[serde(default)]
    pub dis: Option<String>,
    #[serde(default)]
    pub kind: Option<String>,
    #[serde(default)]
    pub markers: Vec<String>,
    #[serde(default)]
    pub expected_revision: Option<u64>,
    #[serde(default)]
    pub dry_run: bool,
}

#[derive(Debug, Deserialize)]
pub struct ModelPointBody {
    #[serde(default)]
    pub building_id: Option<String>,
    #[serde(default)]
    pub site_id: Option<String>,
    pub equipment_id: String,
    pub point_id: String,
    #[serde(default)]
    pub dis: Option<String>,
    #[serde(default)]
    pub openfdd_key: Option<String>,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub markers: Vec<String>,
    #[serde(default)]
    pub expected_revision: Option<u64>,
    #[serde(default)]
    pub dry_run: bool,
}

#[derive(Debug, Deserialize)]
pub struct ModelDeletePointBody {
    #[serde(default)]
    pub building_id: Option<String>,
    #[serde(default)]
    pub site_id: Option<String>,
    pub point_id: String,
    #[serde(default)]
    pub also_exclude: Vec<String>,
    #[serde(default)]
    pub expected_revision: Option<u64>,
    #[serde(default)]
    pub dry_run: bool,
}

#[derive(Debug, Deserialize)]
pub struct ModelDeleteEquipBody {
    #[serde(default)]
    pub building_id: Option<String>,
    #[serde(default)]
    pub site_id: Option<String>,
    pub equipment_id: String,
    #[serde(default)]
    pub expected_revision: Option<u64>,
    #[serde(default)]
    pub dry_run: bool,
}

/// Soft-OPEN: upsert equipment into overlay TTL (BPS `POST /api/model/equip`).
pub async fn model_equip_post(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<ModelEquipBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    deny_viewer_model_mutate(&state, &headers)?;
    let Some(building_id) =
        resolve_building_or_site(body.building_id.as_deref(), body.site_id.as_deref())
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id (or site_id alias) required",
                "soft_open_neq_fq": true,
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = body.equipment_id;
    let dis = body.dis;
    let kind = body.kind;
    let markers = body.markers;
    let expected = body.expected_revision;
    let dry_run = body.dry_run;
    let result = tokio::task::spawn_blocking(move || {
        let root = csv_building_root(&building_id);
        open_fdd_edge_prototype::csv_ingest::model_overlay::upsert_equipment(
            &root,
            &building_id,
            &equipment_id,
            open_fdd_edge_prototype::csv_ingest::model_overlay::EquipUpsertFields {
                dis: dis.as_deref(),
                kind: kind.as_deref(),
                markers: &markers,
            },
            open_fdd_edge_prototype::csv_ingest::model_overlay::OverlayCasOpts {
                expected_revision: expected,
                dry_run,
            },
        )
    })
    .await
    .unwrap_or_else(|e| {
        Err(json!({
            "ok": false,
            "error": format!("equip upsert task: {e}"),
            "soft_open_neq_fq": true,
        }))
    });
    overlay_mutate_result(result)
}

/// Soft-OPEN: upsert point into overlay TTL (BPS `POST /api/model/point`).
pub async fn model_point_post(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<ModelPointBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    deny_viewer_model_mutate(&state, &headers)?;
    let Some(building_id) =
        resolve_building_or_site(body.building_id.as_deref(), body.site_id.as_deref())
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id (or site_id alias) required",
                "soft_open_neq_fq": true,
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = body.equipment_id;
    let point_id = body.point_id;
    let dis = body.dis;
    let openfdd_key = body.openfdd_key;
    let role = body.role;
    let markers = body.markers;
    let expected = body.expected_revision;
    let dry_run = body.dry_run;
    let result = tokio::task::spawn_blocking(move || {
        let root = csv_building_root(&building_id);
        open_fdd_edge_prototype::csv_ingest::model_overlay::upsert_point(
            &root,
            &building_id,
            &equipment_id,
            &point_id,
            open_fdd_edge_prototype::csv_ingest::model_overlay::PointUpsertFields {
                dis: dis.as_deref(),
                openfdd_key: openfdd_key.as_deref(),
                role: role.as_deref(),
                markers: &markers,
            },
            open_fdd_edge_prototype::csv_ingest::model_overlay::OverlayCasOpts {
                expected_revision: expected,
                dry_run,
            },
        )
    })
    .await
    .unwrap_or_else(|e| {
        Err(json!({
            "ok": false,
            "error": format!("point upsert task: {e}"),
            "soft_open_neq_fq": true,
        }))
    });
    overlay_mutate_result(result)
}

/// Soft-OPEN: delete/hide point via overlay tombstone (BPS `DELETE /api/model/point`).
pub async fn model_point_delete(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<ModelDeletePointBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    deny_viewer_model_mutate(&state, &headers)?;
    let Some(building_id) =
        resolve_building_or_site(body.building_id.as_deref(), body.site_id.as_deref())
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id (or site_id alias) required",
                "soft_open_neq_fq": true,
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let point_id = body.point_id;
    let also_exclude = body.also_exclude;
    let expected = body.expected_revision;
    let dry_run = body.dry_run;
    let result = tokio::task::spawn_blocking(move || {
        let root = csv_building_root(&building_id);
        open_fdd_edge_prototype::csv_ingest::model_overlay::delete_point(
            &root,
            &building_id,
            &point_id,
            &also_exclude,
            expected,
            dry_run,
        )
    })
    .await
    .unwrap_or_else(|e| {
        Err(json!({
            "ok": false,
            "error": format!("point delete task: {e}"),
            "soft_open_neq_fq": true,
        }))
    });
    overlay_mutate_result(result)
}

/// Soft-OPEN: delete/hide equipment via overlay tombstone (BPS `DELETE /api/model/equip`).
pub async fn model_equip_delete(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<ModelDeleteEquipBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    deny_viewer_model_mutate(&state, &headers)?;
    let Some(building_id) =
        resolve_building_or_site(body.building_id.as_deref(), body.site_id.as_deref())
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id (or site_id alias) required",
                "soft_open_neq_fq": true,
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = body.equipment_id;
    let expected = body.expected_revision;
    let dry_run = body.dry_run;
    let result = tokio::task::spawn_blocking(move || {
        let root = csv_building_root(&building_id);
        open_fdd_edge_prototype::csv_ingest::model_overlay::delete_equipment(
            &root,
            &building_id,
            &equipment_id,
            expected,
            dry_run,
        )
    })
    .await
    .unwrap_or_else(|e| {
        Err(json!({
            "ok": false,
            "error": format!("equip delete task: {e}"),
            "soft_open_neq_fq": true,
        }))
    });
    overlay_mutate_result(result)
}

/// Soft-OPEN: BPS-compatible agent context bundle (#997/#1123).
///
/// Read-only recipe + revision + lean model tree from native
/// `openfdd_semantic_meta_v1` (primary) plus overlay / equip / point recipes.
/// Soft-OPEN ≠ FQ — SPARQL unions pack ∪ overlay (− tombstones); C2–C6 FQ remains.
pub async fn model_agent_context(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<AgentContextQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(building_id) =
        resolve_building_or_site(q.building_id.as_deref(), q.site_id.as_deref())
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "building_id (or site_id alias) query parameter required",
                "soft_open_neq_fq": true,
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let result = tokio::task::spawn_blocking(move || {
        let root = open_fdd_edge_prototype::historian::store::workspace_dir()
            .join("data")
            .join("csv_buildings")
            .join(&building_id);
        let meta = match open_fdd_edge_prototype::csv_ingest::semantic_meta::load_persisted(&root)
        {
            Ok(m) => m,
            Err(e) => {
                return json!({
                    "ok": false,
                    "error": e,
                    "building_id": building_id,
                    "soft_open_neq_fq": true,
                });
            }
        };
        let revision = meta
            .as_ref()
            .and_then(|m| m.revision.clone())
            .map(Value::String)
            .unwrap_or(Value::Null);
        let inventory =
            open_fdd_edge_prototype::csv_ingest::package::get_package_mapping_handler_scoped(
                &building_id,
                None,
                preferred.as_deref(),
            );
        let model_tree = agent_context_model_tree(meta.as_ref(), &inventory);
        let overlay_root = root;
        let overlay_rev =
            open_fdd_edge_prototype::csv_ingest::model_overlay::load_revision(&overlay_root)
                .unwrap_or(0);
        let overlay_present = overlay_root
            .join(open_fdd_edge_prototype::csv_ingest::model_overlay::OVERLAY_TTL_FILE)
            .is_file();
        let recipes = json!([{
            "id": "mutate-then-verify",
            "steps": [
                "GET /api/model/agent-context?building_id=…",
                "PUT /api/model/semantic-meta with dry_run=true",
                "PUT /api/model/semantic-meta with expected_revision (CAS)",
                "PUT /api/model/overlay with dry_run=true (Turtle)",
                "PUT /api/model/overlay with expected_revision (CAS)",
                "POST /api/model/equip or /api/model/point (dry_run=true first)",
                "POST same without dry_run with expected_revision",
                "DELETE /api/model/point or /api/model/equip (tombstone; pack immutable)",
                "GET /api/model/overlay?building_id=…",
                "GET /api/model/ttl?building_id=…",
                "POST /api/model/sparql SELECT roles/markers",
                "GET /api/fdd/equipment?building_id=…",
            ],
        }]);
        json!({
            "ok": true,
            "building_id": building_id,
            "site_id": building_id,
            "revision": revision,
            "semantic_meta_present": meta.is_some(),
            "overlay_revision": overlay_rev,
            "overlay_present": overlay_present,
            "writable_layer": "openfdd_semantic_meta_v1",
            "overlay_writable_layer": open_fdd_edge_prototype::csv_ingest::model_overlay::WRITABLE_LAYER,
            "pack_immutable": true,
            "model_tree": model_tree,
            "recipes": recipes,
            "openapi_tag": "model-crud",
            "evidence_tier": "VERIFIED_SYNTHETIC",
            "soft_open_neq_fq": true,
            "gaps": open_fdd_edge_prototype::csv_ingest::model_overlay::soft_open_gaps(),
            "note": "Soft-OPEN agent-context — semantic_meta primary + overlay equip/point CRUD; SPARQL pack ∪ overlay (− tombstones); ≠ C2–C6 FQ",
        })
    })
    .await
    .unwrap_or_else(|e| {
        json!({
            "ok": false,
            "error": format!("agent-context task: {e}"),
            "soft_open_neq_fq": true,
        })
    });
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

#[derive(Debug, Deserialize)]
pub struct CentralPackageSparqlBody {
    /// Server template id from GET /api/model/sparql/predefined.
    query_id: Option<String>,
    /// C13 playground-style free-form SELECT/ASK (read-only guard).
    query: Option<String>,
    building_id: Option<String>,
    equipment_id: Option<String>,
}

const SPARQL_UPLOAD_MAX_BYTES: usize = 200 * 1024;

/// Product-central SPARQL (C13): free-form `query` (sparql-playground style) **or**
/// template `query_id`. JWT + building scope. Mutations/SERVICE/FROM rejected.
pub async fn central_package_sparql(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<CentralPackageSparqlBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let freeform = body
        .query
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    if let Some(query) = freeform {
        return run_central_readonly_sparql(
            state,
            headers,
            &query,
            body.building_id,
            body.equipment_id,
        )
        .await;
    }
    let Some(query_id) = body
        .query_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": "query or query_id required (free-form SELECT/ASK, or GET /api/model/sparql/predefined)",
            })),
        ));
    };
    let Some(building_id) = body
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
                "error": "building_id required",
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = body
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let cache = state.haystack_rdf.clone();
    let result = tokio::task::spawn_blocking(move || {
        cache.execute_sparql_template(
            &building_id,
            equipment_id.as_deref(),
            preferred.as_deref(),
            &query_id,
        )
    })
    .await
    .unwrap_or_else(|e| Err(json!({"ok": false, "error": format!("sparql task: {e}")})));

    match result {
        Ok(body) => Ok(Json(body)),
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

async fn run_central_readonly_sparql(
    state: Arc<AppState>,
    headers: HeaderMap,
    query: &str,
    building_id: Option<String>,
    equipment_id: Option<String>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if query.len() > SPARQL_UPLOAD_MAX_BYTES {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "error": format!("query exceeds {SPARQL_UPLOAD_MAX_BYTES} byte limit"),
            })),
        ));
    }
    let Some(building_id) = building_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "building_id required"})),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let cache = state.haystack_rdf.clone();
    let query = query.to_string();
    let result = tokio::task::spawn_blocking(move || {
        cache.execute_readonly_query(
            &building_id,
            equipment_id.as_deref(),
            preferred.as_deref(),
            &query,
        )
    })
    .await
    .unwrap_or_else(|e| Err(json!({"ok": false, "error": format!("sparql task: {e}")})));
    match result {
        Ok(v) => {
            // sparql-playground shape: { results, meta } when possible.
            let meta = json!({
                "schema": v.get("schema").cloned().unwrap_or_else(|| {
                    json!(
                        open_fdd_edge_prototype::csv_ingest::haystack_sparql_bindings::READONLY_SCHEMA
                    )
                }),
                "query_engine": v.get("query_engine").cloned().unwrap_or(json!("central_package_sparql_readonly_v1")),
                "building_id": v.get("building_id").cloned().unwrap_or(Value::Null),
                "truncated": v.get("truncated").cloned().unwrap_or(json!(false)),
                "row_count": v.get("row_count").cloned().unwrap_or(Value::Null),
            });
            Ok(Json(json!({
                "ok": true,
                "results": v,
                "meta": meta,
            })))
        }
        Err(err) => Err((StatusCode::BAD_REQUEST, Json(err))),
    }
}

pub async fn central_package_sparql_catalog() -> Json<Value> {
    Json(crate::haystack_rdf::sparql_catalog())
}

#[derive(Debug, Deserialize)]
pub struct CentralPackageSparqlQueryBody {
    /// Editable SPARQL text (SELECT or ASK). Server clamps size and rejects mutations.
    query: Option<String>,
    building_id: Option<String>,
    equipment_id: Option<String>,
}

/// Alias of playground-style free-form SPARQL (same runner as POST /api/model/sparql).
pub async fn central_package_sparql_query(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<CentralPackageSparqlQueryBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(query) = body
        .query
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
    else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "query text required"})),
        ));
    };
    run_central_readonly_sparql(state, headers, &query, body.building_id, body.equipment_id).await
}

/// C13: upload UTF-8 `.rq` / `.txt` as JSON `{query, building_id}` (≤200KiB).
pub async fn central_package_sparql_upload(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<CentralPackageSparqlQueryBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    central_package_sparql_query(State(state), headers, Json(body)).await
}

/// H10/H11: typed bindings + FDD/history/ECM consumer plans (JWT + building scope).
pub async fn central_package_sparql_consumers(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(body): Json<CentralPackageSparqlBody>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if body
        .query
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .is_some()
    {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(crate::haystack_rdf::sparql_freeform_rejected()),
        ));
    }
    let query_id = body
        .query_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("fdd_role_candidates")
        .to_string();
    let Some(building_id) = body
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
                "error": "building_id required",
            })),
        ));
    };
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, Some(&building_id)) {
        return Err(deny);
    }
    let equipment_id = body
        .equipment_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string);
    let ctx = resolve_tenant_context(&state, &headers);
    let preferred = preferred_tenant_for_building_read(&ctx, Some(&building_id));
    let cache = state.haystack_rdf.clone();
    let result = tokio::task::spawn_blocking(move || {
        cache.execute_binding_consumers(
            &building_id,
            equipment_id.as_deref(),
            preferred.as_deref(),
            &query_id,
        )
    })
    .await
    .unwrap_or_else(|e| Err(json!({"ok": false, "error": format!("consumers task: {e}")})));

    match result {
        Ok(body) => Ok(Json(body)),
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
async fn historian_and_provider_ids(state: &AppState) -> Vec<String> {
    let mut occupied = Vec::new();
    if let Ok(tsdb) = fdd_tsdb::Tsdb::connect_from_env().await {
        if let Ok(sites) = tsdb.list_site_ids().await {
            occupied.extend(sites);
        }
    }
    let mut ids = occupied.clone();
    for site in state.providers.sites_config() {
        let id = site.building_id.trim();
        if id.is_empty() {
            continue;
        }
        let already = occupied.iter().any(|have| have == id);
        if site.mapped_points > 0 || already {
            ids.push(id.to_string());
        }
    }
    ids.sort();
    ids.dedup();
    ids
}

async fn merge_historian_building_ids(state: &AppState, body: &mut Value) {
    let ids = historian_and_provider_ids(state).await;
    let listed: Vec<String> = body
        .get("buildings")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    for id in &ids {
        if !listed.iter().any(|have| have == id) {
            let _ = crate::starter_seed::ensure_semantic_sidecar(id).await;
        }
    }
    let Some(arr) = body.get_mut("buildings").and_then(|v| v.as_array_mut()) else {
        return;
    };
    for id in ids {
        if !arr.iter().any(|v| v.as_str() == Some(id.as_str())) {
            arr.push(json!(id));
        }
    }
}

async fn merge_historian_datasets(state: &AppState, body: &mut Value) {
    let ids = historian_and_provider_ids(state).await;
    let Some(arr) = body.get_mut("datasets").and_then(|v| v.as_array_mut()) else {
        return;
    };
    for id in ids {
        let present = arr.iter().any(|row| {
            row.get("id")
                .or_else(|| row.get("building_id"))
                .and_then(|v| v.as_str())
                == Some(id.as_str())
        });
        if !present {
            arr.push(json!({
                "id": id,
                "building_id": id,
                "source": "timescale",
            }));
        }
    }
}

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
    let mut result = result;
    merge_historian_building_ids(&state, &mut result).await;
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
    merge_historian_datasets(&state, &mut body).await;
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
    // Role and site scope before dataset files, historian purge, jobs, or actions.
    let writer = require_dataset_writer(&state, &headers)?;
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
    if let Some(deny) = dataset_building_scope_denial(&writer, Some(&id)) {
        return Err(deny);
    }
    let action_id = actions::start_action(
        "dataset_delete",
        &format!("Delete site · {id}"),
        Some(json!({ "building_id": id, "dataset_id": id })),
    )
    .ok();
    let (ok, error, jobs_deleted, job_errors, timescale_rows) =
        match crate::lifecycle::purge_site(&id).await {
            Ok(report) => (
                true,
                None,
                report.jobs_deleted,
                Vec::new(),
                report.timescale_rows_deleted,
            ),
            Err(err) => (
                false,
                Some(err.message),
                err.jobs_deleted,
                err.job_errors,
                err.timescale_rows_deleted,
            ),
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
                "timescale_rows_deleted": timescale_rows,
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
            "timescale_rows_deleted": timescale_rows,
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
    // Soft-OPEN R8d: do not present Parquet hive budget as Timescale product historian retention.
    if crate::timescale_historian::historian_is_timescale() {
        let budget = fdd_store::DataBudget::from_env();
        return Ok(Json(json!({
            "ok": true,
            "engine": "timescale-sql",
            "soft_open_neq_fq": true,
            "parquet_historian_budget": "not_applicable",
            "enabled": budget.enabled,
            "budget_bytes": budget.budget_bytes,
            "budget_gib": budget.budget_bytes / fdd_store::GIB,
            "default_budget_gib": fdd_store::DEFAULT_LOCAL_DATA_BUDGET_GIB,
            "reserved_free_percent": budget.reserved_free_percent,
            "used_bytes": 0,
            "bytes_over_budget": 0,
            "object_count": 0,
            "would_drop_count": 0,
            "would_drop_bytes": 0,
            "keep_bytes": 0,
            "policy": "Timescale product historian — Parquet oldest-first Soft-OPEN N/A (≠ FQ WAL/retention)",
            "storage_root": null,
        })));
    }
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
    if crate::timescale_historian::historian_is_timescale() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "engine": "timescale-sql",
                "soft_open_neq_fq": true,
                "parquet_historian_budget": "not_applicable",
                "error": "Parquet data-budget apply Soft-OPEN N/A when OPENFDD_HISTORIAN=timescale (≠ FQ WAL/retention)",
            })),
        ));
    }
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
    // Soft-OPEN R8d: Timescale tip must not advertise empty Parquet compaction as product.
    if crate::timescale_historian::historian_is_timescale() {
        return Ok(Json(json!({
            "ok": true,
            "engine": "timescale-sql",
            "soft_open_neq_fq": true,
            "parquet_compaction": "not_applicable",
            "note": "Product historian is Timescale; Parquet compaction Soft-OPEN N/A (≠ FQ WAL/restore)",
            "coordinator": {
                "mode": "n/a",
                "scanners": 0,
                "compacting": false,
            },
            "historian": Value::Null,
        })));
    }
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
    if crate::timescale_historian::historian_is_timescale() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "engine": "timescale-sql",
                "soft_open_neq_fq": true,
                "parquet_compaction": "not_applicable",
                "error": "Parquet historian compaction Soft-OPEN N/A when OPENFDD_HISTORIAN=timescale (≠ FQ WAL/restore)",
            })),
        ));
    }
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
    if crate::timescale_historian::historian_is_timescale() {
        match fdd_tsdb::Tsdb::connect_from_env().await {
            Ok(tsdb) => match crate::timescale_analytics::fdd_registry(&tsdb).await {
                Ok(v) => return Json(v),
                Err(e) => {
                    return Json(
                        json!({"ok": false, "error": e.to_string(), "engine": "postgres-sql"}),
                    )
                }
            },
            Err(e) => {
                return Json(json!({"ok": false, "error": e.to_string(), "engine": "postgres-sql"}))
            }
        }
    }
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
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/zip"),
    );
    let disposition = format!("attachment; filename=\"{}\"", artifact.filename);
    headers.insert(
        header::CONTENT_DISPOSITION,
        disposition.parse().map_err(|_| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(json!({"ok": false, "error": "invalid export filename"})),
            )
        })?,
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
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/zip"),
    );
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
        // Wave-X: never open DataFusion when Timescale is the product historian.
        if crate::timescale_historian::historian_is_timescale() {
            return crate::timescale_analytics::respond_query($query_id, $query_version, &$req)
                .await
                .map(Json);
        }
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
    if crate::timescale_historian::historian_is_timescale() {
        gate_analytics(&state, &headers, &mut req)?;
        let building = req.query.building_id.clone().ok_or_else(|| {
            (
                StatusCode::BAD_REQUEST,
                Json(json!({"ok": false, "error": "building_id required"})),
            )
        })?;
        match fdd_tsdb::Tsdb::connect_from_env().await {
            Ok(tsdb) => {
                let scope = crate::timescale_analytics::AnalyticsSqlScope::from_request(&req);
                match crate::timescale_analytics::motor_weekly_runtime(&tsdb, &building, &scope)
                    .await
                {
                    Ok(v) => return Ok(Json(v)),
                    Err(e) => {
                        return Err((
                            StatusCode::INTERNAL_SERVER_ERROR,
                            Json(
                                json!({"ok": false, "error": e.to_string(), "engine": "timescale-sql"}),
                            ),
                        ));
                    }
                }
            }
            Err(e) => {
                return Err((
                    StatusCode::SERVICE_UNAVAILABLE,
                    Json(json!({"ok": false, "error": e.to_string(), "engine": "timescale-sql"})),
                ));
            }
        }
    }
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
    if crate::timescale_historian::historian_is_timescale() {
        gate_analytics(&state, &headers, &mut req)?;
        let building = req.query.building_id.clone().ok_or_else(|| {
            (
                StatusCode::BAD_REQUEST,
                Json(json!({"ok": false, "error": "building_id required"})),
            )
        })?;
        match fdd_tsdb::Tsdb::connect_from_env().await {
            Ok(tsdb) => {
                let scope = crate::timescale_analytics::AnalyticsSqlScope::from_request(&req);
                match crate::timescale_analytics::bas_vs_web_oat(&tsdb, &building, &scope).await {
                    Ok(v) => return Ok(Json(v)),
                    Err(e) => {
                        return Err((
                            StatusCode::INTERNAL_SERVER_ERROR,
                            Json(
                                json!({"ok": false, "error": e.to_string(), "engine": "timescale-sql"}),
                            ),
                        ));
                    }
                }
            }
            Err(e) => {
                return Err((
                    StatusCode::SERVICE_UNAVAILABLE,
                    Json(json!({"ok": false, "error": e.to_string(), "engine": "timescale-sql"})),
                ));
            }
        }
    }
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
            // Default lookback + max-span gate (#1179); reject unbounded refresh.
            let window = analytics::historian::resolve_analytics_window(
                req.query.start,
                req.query.end,
                analytics::historian::BAS_VS_WEB_DEFAULT_LOOKBACK_DAYS,
            );
            let (start, end) = match window {
                Ok((s, e)) => (Some(s), e),
                Err(msg) => {
                    return analytics::envelope("bas-vs-web-oat-v3", &req.query, vec![msg]);
                }
            };
            match analytics::historian::bas_vs_web_from_history(
                req.query.equipment_ids.as_deref(),
                max_points,
                req.query.building_id.as_deref(),
                req.read_tenant_id.as_deref(),
                start,
                end,
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
            let scope = crate::timescale_analytics::AnalyticsSqlScope::from_request(&req);
            match analytics::historian::inspect_from_history(
                req.query.building_id.as_deref(),
                eq,
                columns.as_deref(),
                max_points,
                req.read_tenant_id.as_deref(),
                &scope,
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
            let scope = crate::timescale_analytics::AnalyticsSqlScope::from_request(&req);
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
                &scope,
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
    // The Metering demo posts inline monthly rows. Product Timescale dispatch
    // (`respond_query`) ignores that series and answers `building_id is required`
    // from the historian daily-change query. Serve the inline twin directly.
    if analytics::mv_change_point::has_inline_series(&req) {
        return Ok(Json(analytics::mv_change_point::demo_response(&req)));
    }
    let building = req
        .query
        .building_id
        .as_deref()
        .map(str::trim)
        .filter(|id| !id.is_empty());
    if building.is_none() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "ok": false,
                "code": "mv.scope_required",
                "error": "building_id is required for historian M&V, or provide inline series for the demo twin",
                "engine": "mv-change-point",
            })),
        ));
    }
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
    // Interval fuel SQL when the caller asks for the historian query.
    // Campus bill versions stay on the scoped rust-fuel path so a selected
    // site is not replaced by another campus or by an empty interval scan.
    let campus_contract = req
        .query_version
        .as_deref()
        .is_some_and(fuel::analytics::is_campus_query_version);
    if !campus_contract && crate::timescale_historian::historian_is_timescale() {
        if let Some(building) = req
            .building_id
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            match fdd_tsdb::Tsdb::connect_from_env().await {
                Ok(tsdb) => {
                    // FuelRequest has no window/equipment yet — open scope (all).
                    // Universal /api/analytics/query?query_id=fuel binds from AnalyticsRequest.
                    let scope = crate::timescale_analytics::AnalyticsSqlScope {
                        start: None,
                        end: None,
                        equipment_ids: Vec::new(),
                    };
                    match crate::timescale_analytics::fuel_daily(&tsdb, building, &scope).await {
                        Ok(mut v) => {
                            let empty = v
                                .get("rows")
                                .and_then(|rows| rows.as_array())
                                .is_some_and(|rows| rows.is_empty());
                            if empty {
                                if let Some(obj) = v.as_object_mut() {
                                    obj.insert("status".into(), json!("no_meters"));
                                    obj.insert(
                                        "reason".into(),
                                        json!("selected site has no meter rows"),
                                    );
                                }
                            }
                            let status = if empty { "no_meters" } else { "ok" };
                            return Ok(Json(json!({
                                "ok": true,
                                "status": status,
                                "analytics": v,
                                "engine": "timescale-sql",
                                "soft_open_neq_fq": true,
                                "note": "Timescale fuel_daily Soft-OPEN; campus EUI import path unchanged",
                            })));
                        }
                        Err(e) => {
                            return Err((
                                StatusCode::INTERNAL_SERVER_ERROR,
                                Json(json!({
                                    "ok": false,
                                    "error": e.to_string(),
                                    "engine": "timescale-sql",
                                })),
                            ));
                        }
                    }
                }
                Err(e) => {
                    return Err((
                        StatusCode::SERVICE_UNAVAILABLE,
                        Json(json!({
                            "ok": false,
                            "error": e.to_string(),
                            "engine": "timescale-sql",
                        })),
                    ));
                }
            }
        }
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
    let http_ok = result
        .get("ok")
        .and_then(|value| value.as_bool())
        .unwrap_or(true);
    let status = result.get("status").cloned();
    let mut body = json!({
        "ok": http_ok,
        "analytics": result,
    });
    if let Some(status) = status {
        body["status"] = status;
    }
    Ok(Json(body))
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
    #[serde(default)]
    pub building_id: Option<String>,
}

pub async fn fuel_campus_list(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Query(q): Query<FuelCampusQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    if let Some(deny) = deny_if_building_out_of_scope(&state, &headers, q.building_id.as_deref()) {
        return Err(deny);
    }
    let campus_id = q.campus_id.clone();
    let building_id = q.building_id.clone();
    let result = tokio::task::spawn_blocking(move || {
        fuel::import::campus_catalog(building_id.as_deref(), campus_id.as_deref()).unwrap_or_else(
            |err| {
                json!({
                    "ok": false,
                    "status": "unavailable",
                    "error": err.to_string(),
                    "campuses": [],
                    "count": 0,
                    "active": null,
                })
            },
        )
    })
    .await
    .unwrap_or_else(|err| {
        json!({
            "ok": false,
            "status": "unavailable",
            "error": format!("fuel campus list task: {err}"),
            "campuses": [],
            "count": 0,
            "active": null,
        })
    });
    Ok(Json(result))
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
        connector_trigger_role_allowed, login_throttle_ip, request_scope_allowed,
        resolve_build_version, router,
    };
    use crate::capabilities::{CapabilitiesAggregator, ConfiguredUpstream};
    use crate::state::AppState;
    use axum::body::Body;
    use axum::http::{HeaderMap, HeaderValue, Request, StatusCode};
    use std::sync::Arc;
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
        reason = "serialize OPENFDD_WORKSPACE with file-plane token checks"
    )]
    async fn package_roles_http_denies_viewer_before_mutation() {
        let _env_lock = crate::test_env_lock::lock_env();
        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some("package-roles-viewer-deny-test-secret".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = router(Arc::clone(&state));
        let viewer = state
            .auth
            .issue_token_with_tenants("viewer-roles-deny", crate::auth::Role::Viewer, 60, &[])
            .unwrap();
        let body = serde_json::json!({
            "building_id": "SYNTHETIC_ROLES_DENY",
            "equipment_id": "AHU_1",
            "roles": {"fan_cmd": "fan-cmd"}
        });
        let request = Request::post("/api/csv/import/package/roles")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {viewer}"))
            .body(Body::from(body.to_string()))
            .unwrap();
        let response = app.oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::FORBIDDEN);
        let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(json.get("ok").and_then(|v| v.as_bool()), Some(false));
        assert!(
            json.get("error")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .contains("viewer role cannot mutate package roles"),
            "unexpected body: {json}"
        );
    }

    fn sample_semantic_meta_body(building_id: &str) -> serde_json::Value {
        serde_json::json!({
            "schema": "openfdd_point_metadata_v1_sketch",
            "building_id": building_id,
            "points": [{
                "equipment_id": "AHU_1",
                "column": "SAT",
                "haystack_tags": ["sensor", "point", "air", "temp"],
                "unit": "°F",
                "unit_source": "package_map"
            }],
            "equipment": [{
                "equipment_id": "AHU_1",
                "haystack_tags": ["ahu", "equip"],
                "display_name": "AHU 1"
            }]
        })
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE while exercising semantic-meta HTTP CAS"
    )]
    async fn semantic_meta_put_dry_run_conflict_and_viewer_deny() {
        let _env_lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", workspace.path());

        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some("semantic-meta-cas-test-secret".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = router(Arc::clone(&state));
        let bid = "SYNTH_SEMANTIC_META_CAS";
        let meta = sample_semantic_meta_body(bid);

        let viewer = state
            .auth
            .issue_token_with_tenants("viewer-meta", crate::auth::Role::Viewer, 60, &[])
            .unwrap();
        let viewer_req = Request::builder()
            .method("PUT")
            .uri("/api/model/semantic-meta")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {viewer}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "meta": meta,
                    "dry_run": true
                })
                .to_string(),
            ))
            .unwrap();
        let viewer_resp = app.clone().oneshot(viewer_req).await.unwrap();
        assert_eq!(viewer_resp.status(), StatusCode::FORBIDDEN);

        let op = state
            .auth
            .issue_token_with_tenants("operator-meta", crate::auth::Role::Operator, 60, &[])
            .unwrap();

        // dry_run must not publish a head
        let dry_req = Request::builder()
            .method("PUT")
            .uri("/api/model/semantic-meta")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "meta": meta,
                    "dry_run": true
                })
                .to_string(),
            ))
            .unwrap();
        let dry_resp = app.clone().oneshot(dry_req).await.unwrap();
        assert_eq!(dry_resp.status(), StatusCode::OK);
        let dry_bytes = axum::body::to_bytes(dry_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let dry_json: serde_json::Value = serde_json::from_slice(&dry_bytes).unwrap();
        assert_eq!(dry_json.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(
            dry_json.get("dry_run").and_then(|v| v.as_bool()),
            Some(true)
        );
        let tip = workspace
            .path()
            .join("data/csv_buildings")
            .join(bid)
            .join("semantic_meta.json");
        assert!(!tip.is_file(), "dry_run must not write semantic_meta.json");

        // first publish
        let put1 = Request::builder()
            .method("PUT")
            .uri("/api/model/semantic-meta")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "meta": meta
                })
                .to_string(),
            ))
            .unwrap();
        let put1_resp = app.clone().oneshot(put1).await.unwrap();
        assert_eq!(put1_resp.status(), StatusCode::OK);
        let put1_bytes = axum::body::to_bytes(put1_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let put1_json: serde_json::Value = serde_json::from_slice(&put1_bytes).unwrap();
        let rev = put1_json
            .get("revision")
            .and_then(|v| v.as_str())
            .expect("revision")
            .to_string();
        assert!(tip.is_file());

        // stale expected_revision → 409
        let conflict = Request::builder()
            .method("PUT")
            .uri("/api/model/semantic-meta")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "meta": meta,
                    "expected_revision": "stale-rev-not-current"
                })
                .to_string(),
            ))
            .unwrap();
        let conflict_resp = app.clone().oneshot(conflict).await.unwrap();
        assert_eq!(conflict_resp.status(), StatusCode::CONFLICT);
        let conflict_bytes = axum::body::to_bytes(conflict_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let conflict_json: serde_json::Value = serde_json::from_slice(&conflict_bytes).unwrap();
        assert_eq!(
            conflict_json.get("conflict").and_then(|v| v.as_bool()),
            Some(true)
        );

        // matching CAS succeeds (idempotent same content still ok)
        let put2 = Request::builder()
            .method("PUT")
            .uri("/api/model/semantic-meta")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "meta": meta,
                    "expected_revision": rev
                })
                .to_string(),
            ))
            .unwrap();
        let put2_resp = app.oneshot(put2).await.unwrap();
        assert_eq!(put2_resp.status(), StatusCode::OK);

        std::env::remove_var("OPENFDD_WORKSPACE");
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE while exercising agent-context GET"
    )]
    async fn agent_context_get_present_and_site_id_alias() {
        let _env_lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", workspace.path());

        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some("agent-context-test-secret".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = router(Arc::clone(&state));
        let bid = "SYNTH_AGENT_CONTEXT";
        let meta = sample_semantic_meta_body(bid);
        let op = state
            .auth
            .issue_token_with_tenants("operator-ctx", crate::auth::Role::Operator, 60, &[])
            .unwrap();

        // empty building — honest present=false + empty tree
        let empty_req = Request::builder()
            .method("GET")
            .uri(format!("/api/model/agent-context?building_id={bid}"))
            .header("authorization", format!("Bearer {op}"))
            .body(Body::empty())
            .unwrap();
        let empty_resp = app.clone().oneshot(empty_req).await.unwrap();
        assert_eq!(empty_resp.status(), StatusCode::OK);
        let empty_bytes = axum::body::to_bytes(empty_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let empty_json: serde_json::Value = serde_json::from_slice(&empty_bytes).unwrap();
        assert_eq!(empty_json.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(
            empty_json
                .get("semantic_meta_present")
                .and_then(|v| v.as_bool()),
            Some(false)
        );
        assert_eq!(
            empty_json.get("writable_layer").and_then(|v| v.as_str()),
            Some("openfdd_semantic_meta_v1")
        );
        assert!(empty_json
            .get("recipes")
            .and_then(|v| v.as_array())
            .is_some());

        // publish meta then re-read via BPS site_id alias
        let put = Request::builder()
            .method("PUT")
            .uri("/api/model/semantic-meta")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "meta": meta
                })
                .to_string(),
            ))
            .unwrap();
        let put_resp = app.clone().oneshot(put).await.unwrap();
        assert_eq!(put_resp.status(), StatusCode::OK);
        let put_bytes = axum::body::to_bytes(put_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let put_json: serde_json::Value = serde_json::from_slice(&put_bytes).unwrap();
        let rev = put_json
            .get("revision")
            .and_then(|v| v.as_str())
            .expect("revision")
            .to_string();

        let alias_req = Request::builder()
            .method("GET")
            .uri(format!("/api/model/agent-context?site_id={bid}"))
            .header("authorization", format!("Bearer {op}"))
            .body(Body::empty())
            .unwrap();
        let alias_resp = app.oneshot(alias_req).await.unwrap();
        assert_eq!(alias_resp.status(), StatusCode::OK);
        let alias_bytes = axum::body::to_bytes(alias_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let alias_json: serde_json::Value = serde_json::from_slice(&alias_bytes).unwrap();
        assert_eq!(alias_json.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(
            alias_json
                .get("semantic_meta_present")
                .and_then(|v| v.as_bool()),
            Some(true)
        );
        assert_eq!(
            alias_json.get("revision").and_then(|v| v.as_str()),
            Some(rev.as_str())
        );
        assert_eq!(
            alias_json
                .pointer("/model_tree/source")
                .and_then(|v| v.as_str()),
            Some("semantic_meta")
        );
        assert_eq!(
            alias_json
                .pointer("/model_tree/equipment_count")
                .and_then(|v| v.as_u64()),
            Some(1)
        );
        assert_eq!(
            alias_json.get("soft_open_neq_fq").and_then(|v| v.as_bool()),
            Some(true)
        );

        std::env::remove_var("OPENFDD_WORKSPACE");
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE while exercising overlay Turtle PUT CAS"
    )]
    async fn model_overlay_put_dry_run_conflict_and_viewer_deny() {
        let _env_lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", workspace.path());

        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some("overlay-cas-test-secret".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = router(Arc::clone(&state));
        let bid = "SYNTH_MODEL_OVERLAY";
        let sample_ttl = r#"
@prefix ph: <https://project-haystack.org/def/ph#> .
<urn:openfdd:site/SYNTH_MODEL_OVERLAY#equip-AHU_1> a ph:equip ;
  ph:dis "AHU 1" .
"#;

        let viewer = state
            .auth
            .issue_token_with_tenants("viewer-overlay", crate::auth::Role::Viewer, 60, &[])
            .unwrap();
        let viewer_req = Request::builder()
            .method("PUT")
            .uri("/api/model/overlay")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {viewer}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "ttl": sample_ttl,
                    "dry_run": true
                })
                .to_string(),
            ))
            .unwrap();
        let viewer_resp = app.clone().oneshot(viewer_req).await.unwrap();
        assert_eq!(viewer_resp.status(), StatusCode::FORBIDDEN);

        let op = state
            .auth
            .issue_token_with_tenants("operator-overlay", crate::auth::Role::Operator, 60, &[])
            .unwrap();

        let dry_req = Request::builder()
            .method("PUT")
            .uri("/api/model/overlay")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "ttl": sample_ttl,
                    "dry_run": true
                })
                .to_string(),
            ))
            .unwrap();
        let dry_resp = app.clone().oneshot(dry_req).await.unwrap();
        assert_eq!(dry_resp.status(), StatusCode::OK);
        let dry_bytes = axum::body::to_bytes(dry_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let dry_json: serde_json::Value = serde_json::from_slice(&dry_bytes).unwrap();
        assert_eq!(dry_json.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(
            dry_json.get("dry_run").and_then(|v| v.as_bool()),
            Some(true)
        );
        let tip = workspace
            .path()
            .join("data/csv_buildings")
            .join(bid)
            .join("model_overlay.ttl");
        assert!(!tip.is_file(), "dry_run must not write model_overlay.ttl");

        let bad_req = Request::builder()
            .method("PUT")
            .uri("/api/model/overlay")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "site_id": bid,
                    "ttl": "not turtle {{{"
                })
                .to_string(),
            ))
            .unwrap();
        let bad_resp = app.clone().oneshot(bad_req).await.unwrap();
        assert_eq!(bad_resp.status(), StatusCode::BAD_REQUEST);

        let put1 = Request::builder()
            .method("PUT")
            .uri("/api/model/overlay")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "site_id": bid,
                    "ttl": sample_ttl,
                    "expected_revision": 0
                })
                .to_string(),
            ))
            .unwrap();
        let put1_resp = app.clone().oneshot(put1).await.unwrap();
        assert_eq!(put1_resp.status(), StatusCode::OK);
        let put1_bytes = axum::body::to_bytes(put1_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let put1_json: serde_json::Value = serde_json::from_slice(&put1_bytes).unwrap();
        assert_eq!(put1_json.get("revision").and_then(|v| v.as_u64()), Some(1));
        assert!(tip.is_file());

        let conflict = Request::builder()
            .method("PUT")
            .uri("/api/model/overlay")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "ttl": sample_ttl,
                    "expected_revision": 0
                })
                .to_string(),
            ))
            .unwrap();
        let conflict_resp = app.clone().oneshot(conflict).await.unwrap();
        assert_eq!(conflict_resp.status(), StatusCode::CONFLICT);

        let get_req = Request::builder()
            .method("GET")
            .uri(format!("/api/model/overlay?site_id={bid}"))
            .header("authorization", format!("Bearer {op}"))
            .body(Body::empty())
            .unwrap();
        let get_resp = app.oneshot(get_req).await.unwrap();
        assert_eq!(get_resp.status(), StatusCode::OK);
        let get_bytes = axum::body::to_bytes(get_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let get_json: serde_json::Value = serde_json::from_slice(&get_bytes).unwrap();
        assert_eq!(get_json.get("revision").and_then(|v| v.as_u64()), Some(1));
        assert!(get_json
            .get("ttl")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .contains("AHU_1"));

        std::env::remove_var("OPENFDD_WORKSPACE");
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE while exercising equip/point overlay CRUD"
    )]
    async fn model_equip_point_upsert_tombstone_and_viewer_deny() {
        let _env_lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", workspace.path());

        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some("equip-point-crud-secret".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = router(Arc::clone(&state));
        let bid = "SYNTH_EQUIP_POINT_CRUD";

        let viewer = state
            .auth
            .issue_token_with_tenants("viewer-equip", crate::auth::Role::Viewer, 60, &[])
            .unwrap();
        let viewer_req = Request::builder()
            .method("POST")
            .uri("/api/model/equip")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {viewer}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "equipment_id": "AHU_1",
                    "kind": "ahu",
                    "dry_run": true
                })
                .to_string(),
            ))
            .unwrap();
        let viewer_resp = app.clone().oneshot(viewer_req).await.unwrap();
        assert_eq!(viewer_resp.status(), StatusCode::FORBIDDEN);

        let op = state
            .auth
            .issue_token_with_tenants("operator-equip", crate::auth::Role::Operator, 60, &[])
            .unwrap();

        let upsert_eq = Request::builder()
            .method("POST")
            .uri("/api/model/equip")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "site_id": bid,
                    "equipment_id": "AHU_1",
                    "dis": "AHU 1",
                    "kind": "ahu",
                    "expected_revision": 0
                })
                .to_string(),
            ))
            .unwrap();
        let eq_resp = app.clone().oneshot(upsert_eq).await.unwrap();
        assert_eq!(eq_resp.status(), StatusCode::OK);
        let eq_bytes = axum::body::to_bytes(eq_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let eq_json: serde_json::Value = serde_json::from_slice(&eq_bytes).unwrap();
        assert_eq!(eq_json.get("revision").and_then(|v| v.as_u64()), Some(1));

        let upsert_pt = Request::builder()
            .method("POST")
            .uri("/api/model/point")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "equipment_id": "AHU_1",
                    "point_id": "SAT",
                    "role": "discharge-air-temp",
                    "openfdd_key": "AHU_1.discharge-air-temp",
                    "expected_revision": 1
                })
                .to_string(),
            ))
            .unwrap();
        let pt_resp = app.clone().oneshot(upsert_pt).await.unwrap();
        assert_eq!(pt_resp.status(), StatusCode::OK);

        let del_pt = Request::builder()
            .method("DELETE")
            .uri("/api/model/point")
            .header("content-type", "application/json")
            .header("authorization", format!("Bearer {op}"))
            .body(Body::from(
                serde_json::json!({
                    "building_id": bid,
                    "point_id": "SAT",
                    "also_exclude": ["AHU_1.discharge-air-temp"],
                    "expected_revision": 2
                })
                .to_string(),
            ))
            .unwrap();
        let del_resp = app.clone().oneshot(del_pt).await.unwrap();
        assert_eq!(del_resp.status(), StatusCode::OK);

        let get_req = Request::builder()
            .method("GET")
            .uri(format!("/api/model/overlay?building_id={bid}"))
            .header("authorization", format!("Bearer {op}"))
            .body(Body::empty())
            .unwrap();
        let get_resp = app.oneshot(get_req).await.unwrap();
        assert_eq!(get_resp.status(), StatusCode::OK);
        let get_bytes = axum::body::to_bytes(get_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let get_json: serde_json::Value = serde_json::from_slice(&get_bytes).unwrap();
        assert_eq!(get_json.get("revision").and_then(|v| v.as_u64()), Some(3));
        let tombs = get_json
            .get("tombstones")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));
        let points = tombs
            .get("points")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(
            points.iter().any(|v| v.as_str() == Some("SAT")),
            "tombstones={tombs}"
        );

        std::env::remove_var("OPENFDD_WORKSPACE");
    }

    #[test]
    fn login_throttle_ignores_spoofed_xff_by_default() {
        let _env_lock = crate::test_env_lock::lock_env();
        std::env::remove_var("OPENFDD_TRUST_X_FORWARDED_FOR");
        let mut headers = HeaderMap::new();
        headers.insert(
            "x-forwarded-for",
            HeaderValue::from_static("1.2.3.4, 10.0.0.1"),
        );
        assert_eq!(login_throttle_ip(&headers), "direct");

        std::env::set_var("OPENFDD_TRUST_X_FORWARDED_FOR", "1");
        // Trusted mode uses rightmost hop, not the spoofable leftmost value.
        assert_eq!(login_throttle_ip(&headers), "10.0.0.1");
        std::env::remove_var("OPENFDD_TRUST_X_FORWARDED_FOR");
    }

    #[test]
    fn login_failure_map_is_bounded() {
        let state = AppState::new();
        for i in 0..12_000 {
            state.login_record_failure(&format!("spoof-{i}:user"));
        }
        let len = state.login_failures.lock().unwrap().len();
        assert!(len <= 10_000, "login_failures grew to {len}");
    }

    #[test]
    fn local_receipt_tenant_echoes_header_when_central_env_unset() {
        let _env_lock = crate::test_env_lock::lock_env();
        std::env::remove_var("OPENFDD_TENANT_ID");
        let mut headers = HeaderMap::new();
        headers.insert("x-openfdd-tenant-id", HeaderValue::from_static("acme"));
        assert_eq!(super::local_ingest_receipt_tenant(&headers), "acme");
        std::env::set_var("OPENFDD_TENANT_ID", "hub-tenant");
        assert_eq!(super::local_ingest_receipt_tenant(&headers), "hub-tenant");
        std::env::remove_var("OPENFDD_TENANT_ID");
        assert_eq!(super::local_ingest_receipt_tenant(&HeaderMap::new()), "-");
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

    /// Import, append, and dataset delete (workspace delete + historian purge)
    /// require operator or admin and the caller's site. Denial leaves files,
    /// the actions log, the audit log, and — when a test database is configured —
    /// Timescale rows unchanged.
    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_WORKSPACE for the dataset write role matrix"
    )]
    async fn dataset_writes_require_role_and_site_scope() {
        let _env_lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().unwrap();
        let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
        let pg_url = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty());
        let parquet = workspace.path().join(".cache/parquet");
        let audit_path = workspace.path().join("logs/security_audit.jsonl");
        let _historian =
            HistorianEnv::isolate(parquet.to_str().unwrap(), audit_path.to_str().unwrap());

        let tenant_a = "w1b_tenant_a";
        let plane = crate::tenant::ControlPlane {
            tenants: vec![
                crate::tenant::TenantRecord {
                    id: tenant_a.into(),
                    name: "A".into(),
                    building_ids: vec![
                        "W1B_VIEW".into(),
                        "W1B_OWN".into(),
                        "W1B_ADMIN".into(),
                        "W1B_PG_VIEW".into(),
                        "W1B_PG_OWN".into(),
                    ],
                },
                crate::tenant::TenantRecord {
                    id: "w1b_tenant_b".into(),
                    name: "B".into(),
                    building_ids: vec!["W1B_FOREIGN".into(), "W1B_PG_FOREIGN".into()],
                },
            ],
        };
        plane.save(workspace.path()).unwrap();
        for id in ["W1B_VIEW", "W1B_FOREIGN", "W1B_PG_VIEW", "W1B_PG_FOREIGN"] {
            write_sentinel(workspace.path(), id);
        }

        let mut state = AppState::new();
        state.auth = crate::auth::AuthConfig {
            secret: Some("dataset-write-role-matrix-test-secret".into()),
            admin_password: None,
            agent_password: None,
            viewer_password: None,
            viewer_tenant_ids: Vec::new(),
        };
        let state = Arc::new(state);
        let app = router(Arc::clone(&state));
        let membership = vec![tenant_a.to_string()];
        let viewer = state
            .auth
            .issue_token_with_tenants("w1b-viewer", crate::auth::Role::Viewer, 600, &membership)
            .unwrap();
        let operator = state
            .auth
            .issue_token_with_tenants(
                "w1b-operator",
                crate::auth::Role::Operator,
                600,
                &membership,
            )
            .unwrap();
        let admin = state
            .auth
            .issue_token_with_tenants("w1b-admin", crate::auth::Role::Admin, 600, &membership)
            .unwrap();

        let before = workspace_fingerprint(workspace.path());
        let denials = [
            (crate::auth::Role::Viewer, &viewer, "W1B_VIEW", "own"),
            (crate::auth::Role::Viewer, &viewer, "W1B_FOREIGN", "foreign"),
            (
                crate::auth::Role::Operator,
                &operator,
                "W1B_FOREIGN",
                "foreign",
            ),
            (crate::auth::Role::Admin, &admin, "W1B_FOREIGN", "foreign"),
        ];
        for (role, token, building, scope) in denials {
            for op in [WriteOp::Import, WriteOp::Append, WriteOp::Delete] {
                let (status, body) = dispatch(&app, token, op, building).await;
                assert_eq!(
                    status,
                    StatusCode::FORBIDDEN,
                    "{role:?} {scope} {op:?} body={body}"
                );
                assert_eq!(body.get("ok").and_then(|v| v.as_bool()), Some(false));
                let err = body.get("error").and_then(|v| v.as_str()).unwrap_or("");
                if role == crate::auth::Role::Viewer {
                    assert!(
                        err.contains("operator or admin role required"),
                        "{role:?} {scope} {op:?} error={err}"
                    );
                } else {
                    assert!(
                        err.contains("building not in tenant scope"),
                        "{role:?} {scope} {op:?} error={err}"
                    );
                }
                assert_eq!(
                    workspace_fingerprint(workspace.path()),
                    before,
                    "{role:?} {scope} {op:?} wrote a file, action, or audit record"
                );
            }
        }
        assert_eq!(
            std::fs::read_to_string(
                workspace
                    .path()
                    .join("data/csv_buildings/W1B_VIEW/sentinel.txt")
            )
            .unwrap(),
            "W1B_VIEW"
        );
        assert_eq!(
            std::fs::read_to_string(
                workspace
                    .path()
                    .join("data/csv_buildings/W1B_FOREIGN/sentinel.txt")
            )
            .unwrap(),
            "W1B_FOREIGN"
        );

        let (status, body) = dispatch(&app, &operator, WriteOp::Import, "W1B_OWN").await;
        assert_eq!(status, StatusCode::OK, "operator own import {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );
        assert!(
            workspace
                .path()
                .join("data/csv_buildings/W1B_OWN/AHU_1/history_wide.csv")
                .is_file(),
            "operator import did not materialize the package"
        );

        let (status, body) = dispatch(&app, &operator, WriteOp::Append, "W1B_OWN").await;
        assert_eq!(status, StatusCode::OK, "operator own append {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );

        let (status, body) = dispatch(&app, &admin, WriteOp::Import, "W1B_ADMIN").await;
        assert_eq!(status, StatusCode::OK, "admin own import {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );

        let (status, body) = dispatch(&app, &admin, WriteOp::Append, "W1B_ADMIN").await;
        assert_eq!(status, StatusCode::OK, "admin own append {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );

        // Delete is the purge entry point: workspace files and historian rows.
        let (status, body) = dispatch(&app, &operator, WriteOp::Delete, "W1B_OWN").await;
        assert_eq!(status, StatusCode::OK, "operator own delete {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );
        assert!(
            !workspace.path().join("data/csv_buildings/W1B_OWN").exists(),
            "operator delete left the package directory"
        );

        let (status, body) = dispatch(&app, &admin, WriteOp::Delete, "W1B_ADMIN").await;
        assert_eq!(status, StatusCode::OK, "admin own delete {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );
        assert!(!workspace
            .path()
            .join("data/csv_buildings/W1B_ADMIN")
            .exists());

        assert_eq!(
            std::fs::read_to_string(
                workspace
                    .path()
                    .join("data/csv_buildings/W1B_VIEW/sentinel.txt")
            )
            .unwrap(),
            "W1B_VIEW"
        );
        assert_eq!(
            std::fs::read_to_string(
                workspace
                    .path()
                    .join("data/csv_buildings/W1B_FOREIGN/sentinel.txt")
            )
            .unwrap(),
            "W1B_FOREIGN"
        );

        let hub = state
            .auth
            .issue_token_with_tenants("admin", crate::auth::Role::Admin, 600, &[])
            .unwrap();
        let (status, body) = dispatch(&app, &hub, WriteOp::Import, "W1B_HUB").await;
        assert_eq!(status, StatusCode::OK, "hub admin import {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );

        if let Some(url) = pg_url {
            assert_timescale_purge_gate(&app, &viewer, &operator, &url).await;
        }
    }

    async fn dispatch(
        app: &axum::Router,
        token: &str,
        op: WriteOp,
        building: &str,
    ) -> (StatusCode, serde_json::Value) {
        let request = match op {
            WriteOp::Import => Request::post("/api/csv/import/package")
                .header("content-type", "application/zip")
                .header("authorization", format!("Bearer {token}"))
                .body(Body::from(package_zip(building)))
                .unwrap(),
            WriteOp::Append => {
                let payload = serde_json::json!({
                    "confirm": true,
                    "building_id": building,
                    "equipment_id": "AHU_1",
                    "csv": "timestamp_utc,SF_SPD,DA_P,DA_P_SP\n2024-01-01T01:00:00Z,80,1.1,1.0\n"
                });
                Request::post("/api/csv/import/package/append")
                    .header("content-type", "application/json")
                    .header("authorization", format!("Bearer {token}"))
                    .body(Body::from(payload.to_string()))
                    .unwrap()
            }
            WriteOp::Delete => Request::delete(format!("/api/datasets?id={building}"))
                .header("authorization", format!("Bearer {token}"))
                .body(Body::empty())
                .unwrap(),
        };
        let response = app.clone().oneshot(request).await.unwrap();
        let status = response.status();
        let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .unwrap();
        let body = serde_json::from_slice(&bytes).unwrap_or_else(
            |_| serde_json::json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }),
        );
        (status, body)
    }

    async fn assert_timescale_purge_gate(
        app: &axum::Router,
        viewer: &str,
        operator: &str,
        url: &str,
    ) {
        std::env::set_var("OPENFDD_DATABASE_URL", url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(url)
            .await
            .unwrap();
        sqlx::query(
            "CREATE TABLE IF NOT EXISTS sample (
                ts timestamptz NOT NULL,
                site_id text NOT NULL,
                openfdd_key text NOT NULL,
                val double precision,
                PRIMARY KEY (site_id, openfdd_key, ts)
            )",
        )
        .execute(&pool)
        .await
        .unwrap();
        for site in ["W1B_PG_OWN", "W1B_PG_VIEW", "W1B_PG_FOREIGN"] {
            sqlx::query("DELETE FROM sample WHERE site_id = $1")
                .bind(site)
                .execute(&pool)
                .await
                .unwrap();
            sqlx::query(
                "INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, 'marker', 1.0)",
            )
            .bind(chrono::Utc::now())
            .bind(site)
            .execute(&pool)
            .await
            .unwrap();
        }

        let cases = [
            (viewer, "W1B_PG_VIEW", "viewer own"),
            (viewer, "W1B_PG_FOREIGN", "viewer foreign"),
            (operator, "W1B_PG_FOREIGN", "operator foreign"),
        ];
        for (token, building, label) in cases {
            for op in [WriteOp::Import, WriteOp::Append, WriteOp::Delete] {
                let before = sample_count(&pool, building).await;
                assert_eq!(before, 1, "{label} seed");
                let (status, body) = dispatch(app, token, op, building).await;
                assert_eq!(status, StatusCode::FORBIDDEN, "{label} {op:?} {body}");
                assert_eq!(
                    sample_count(&pool, building).await,
                    before,
                    "{label} {op:?} changed historian rows"
                );
            }
        }

        let (status, body) = dispatch(app, operator, WriteOp::Delete, "W1B_PG_OWN").await;
        assert_eq!(status, StatusCode::OK, "operator purge {body}");
        assert_eq!(
            body.get("ok").and_then(|v| v.as_bool()),
            Some(true),
            "{body}"
        );
        assert_eq!(sample_count(&pool, "W1B_PG_OWN").await, 0);
        assert_eq!(sample_count(&pool, "W1B_PG_VIEW").await, 1);
        assert_eq!(sample_count(&pool, "W1B_PG_FOREIGN").await, 1);

        for site in ["W1B_PG_OWN", "W1B_PG_VIEW", "W1B_PG_FOREIGN"] {
            sqlx::query("DELETE FROM sample WHERE site_id = $1")
                .bind(site)
                .execute(&pool)
                .await
                .unwrap();
        }
    }

    async fn sample_count(pool: &sqlx::PgPool, site: &str) -> i64 {
        sqlx::query_scalar("SELECT COUNT(*)::bigint FROM sample WHERE site_id = $1")
            .bind(site)
            .fetch_one(pool)
            .await
            .unwrap()
    }

    #[derive(Clone, Copy, Debug)]
    enum WriteOp {
        Import,
        Append,
        Delete,
    }

    struct HistorianEnv {
        prev: Vec<(&'static str, Option<String>)>,
    }

    impl HistorianEnv {
        fn isolate(parquet: &str, audit: &str) -> Self {
            let keys = [
                ("OPENFDD_MULTI_TENANT", Some("1")),
                ("OPENFDD_HISTORIAN", Some("parquet")),
                ("OPENFDD_STORAGE_URL", None),
                ("OPENFDD_DATABASE_URL", None),
                ("OPENFDD_PARQUET_ROOT", Some(parquet)),
                ("OPENFDD_AUDIT_LOG_PATH", Some(audit)),
            ];
            let prev = keys
                .into_iter()
                .map(|(key, value)| {
                    let old = std::env::var(key).ok();
                    match value {
                        Some(v) => std::env::set_var(key, v),
                        None => std::env::remove_var(key),
                    }
                    (key, old)
                })
                .collect();
            Self { prev }
        }
    }

    impl Drop for HistorianEnv {
        fn drop(&mut self) {
            for (key, old) in self.prev.drain(..) {
                match old {
                    Some(v) => std::env::set_var(key, v),
                    None => std::env::remove_var(key),
                }
            }
        }
    }

    fn write_sentinel(root: &std::path::Path, id: &str) {
        let dir = root.join("data/csv_buildings").join(id);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("sentinel.txt"), id).unwrap();
    }

    fn workspace_fingerprint(root: &std::path::Path) -> String {
        let mut files = Vec::new();
        let mut stack = vec![root.to_path_buf()];
        while let Some(dir) = stack.pop() {
            let Ok(entries) = std::fs::read_dir(&dir) else {
                continue;
            };
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    stack.push(path);
                    continue;
                }
                let Ok(meta) = entry.metadata() else {
                    continue;
                };
                let rel = path.strip_prefix(root).unwrap_or(&path);
                files.push(format!("{}:{}", rel.display(), meta.len()));
            }
        }
        files.sort();
        files.join("\n")
    }

    fn package_zip(building_id: &str) -> Vec<u8> {
        use std::io::Write;
        let manifest = format!(
            r#"{{"schema_version":"openfdd_package_v1","building_id":"{building_id}","grid_minutes":5,"timezone":"UTC"}}"#
        );
        let map = r#"{"equipType":"ahu","points":{"fan-cmd":"SF_SPD","duct-static-pressure":"DA_P","duct-static-pressure-sp":"DA_P_SP"}}"#;
        let mut history = String::from("timestamp_utc,SF_SPD,DA_P,DA_P_SP\n");
        for minute in [0, 5, 10, 15, 20, 25] {
            history.push_str(&format!("2024-01-01T00:{minute:02}:00Z,0.95,0.4,1.4\n"));
        }
        let mut cursor = std::io::Cursor::new(Vec::new());
        {
            let mut zw = zip::ZipWriter::new(&mut cursor);
            let opts = zip::write::SimpleFileOptions::default();
            for (name, content) in [
                ("manifest.json", manifest.as_str()),
                ("AHU_1/history_wide.json", map),
                ("AHU_1/history_wide.csv", history.as_str()),
            ] {
                zw.start_file(name, opts).unwrap();
                zw.write_all(content.as_bytes()).unwrap();
            }
            zw.finish().unwrap();
        }
        cursor.into_inner()
    }
}
