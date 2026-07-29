//! Swagger UI + OpenAPI JSON for central.

use axum::Router;
use utoipa::openapi::security::{Http, HttpAuthScheme, SecurityScheme};
use utoipa::Modify;
use utoipa::OpenApi;

use crate::auth::{JwtClaims, Role};
use crate::models::*;
use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};

/// Doc-only OpenAPI path descriptors (OFDD-071).
///
/// These functions are never invoked; they exist so the live jobs / analytics /
/// datasets / fdd-results / reports routes appear in `/openapi.json` without
/// forcing `ToSchema`/`IntoParams` derives onto every axum extractor type. Bodies
/// are documented as free-form JSON (`serde_json::Value`) because the handlers
/// return `{ "ok": true, ... }` envelopes assembled at runtime.
mod live_routes {
    #![allow(dead_code)]

    #[utoipa::path(
        get, path = "/api/jobs", tag = "jobs",
        params(
            ("include_archived" = Option<bool>, Query, description = "Include archived jobs"),
            ("status" = Option<String>, Query, description = "Filter by status"),
            ("site_id" = Option<String>, Query, description = "Filter by site id"),
            ("tag" = Option<String>, Query, description = "Filter by tag")
        ),
        responses((status = 200, description = "List analysis jobs", body = serde_json::Value))
    )]
    pub fn jobs_list() {}

    #[utoipa::path(
        post, path = "/api/jobs", tag = "jobs",
        request_body = serde_json::Value,
        responses((status = 201, description = "Create an analysis job", body = serde_json::Value))
    )]
    pub fn jobs_create() {}

    #[utoipa::path(
        get, path = "/api/jobs/{job_id}", tag = "jobs",
        params(("job_id" = String, Path, description = "Job id")),
        responses(
            (status = 200, description = "Get an analysis job", body = serde_json::Value),
            (status = 404, description = "Job not found")
        )
    )]
    pub fn jobs_get() {}

    #[utoipa::path(
        post, path = "/api/jobs/{job_id}/wattlab/handoffs", tag = "jobs",
        params(("job_id" = String, Path, description = "Job id")),
        request_body = serde_json::Value,
        responses((status = 201, description = "Create a job-native WattLab handoff", body = serde_json::Value))
    )]
    pub fn jobs_create_wattlab_handoff() {}

    #[utoipa::path(
        post, path = "/api/jobs/{job_id}/eplus/runs", tag = "jobs",
        params(("job_id" = String, Path, description = "Job id")),
        request_body = serde_json::Value,
        responses((status = 201, description = "Queue an external EnergyPlus run (central persists QUEUED only)", body = serde_json::Value))
    )]
    pub fn jobs_queue_eplus_run() {}

    #[utoipa::path(
        get, path = "/api/datasets", tag = "datasets",
        responses((status = 200, description = "List ingested datasets / sites", body = serde_json::Value))
    )]
    pub fn datasets_list() {}

    #[utoipa::path(
        delete, path = "/api/datasets", tag = "datasets",
        params(("id" = String, Query, description = "Building / dataset id to delete (Delete site)")),
        responses((status = 200, description = "Delete a site's history / results", body = serde_json::Value))
    )]
    pub fn datasets_delete() {}

    #[utoipa::path(
        get, path = "/api/fdd/results", tag = "fdd",
        params(("building_id" = Option<String>, Query, description = "Scope results to building={id}")),
        responses((status = 200, description = "Site-scoped FDD rule results", body = serde_json::Value))
    )]
    pub fn fdd_results() {}

    #[utoipa::path(
        get, path = "/api/fdd/equipment", tag = "fdd",
        params(("building_id" = Option<String>, Query, description = "Scope equipment to building={id}")),
        responses((status = 200, description = "Site-scoped equipment inventory", body = serde_json::Value))
    )]
    pub fn fdd_equipment() {}

    #[utoipa::path(
        post, path = "/api/analytics/runtime", tag = "analytics",
        request_body = serde_json::Value,
        responses((status = 200, description = "Runtime hours (historian Δt or inline)", body = serde_json::Value))
    )]
    pub fn analytics_runtime() {}

    #[utoipa::path(
        post, path = "/api/analytics/economizer", tag = "analytics",
        request_body = serde_json::Value,
        responses((status = 200, description = "Economizer diagnostics; building-scoped historian when building_id set", body = serde_json::Value))
    )]
    pub fn analytics_economizer() {}

    #[utoipa::path(
        post, path = "/api/analytics/sensor-health", tag = "analytics",
        request_body = serde_json::Value,
        responses((status = 200, description = "Sensor coverage / missingness / flatline", body = serde_json::Value))
    )]
    pub fn analytics_sensor_health() {}

    #[utoipa::path(
        post, path = "/api/analytics/mechanical-cooling", tag = "analytics",
        request_body = serde_json::Value,
        responses((status = 200, description = "Mechanical cooling diagnostics", body = serde_json::Value))
    )]
    pub fn analytics_mechanical_cooling() {}

    #[utoipa::path(
        post, path = "/api/analytics/metering", tag = "analytics",
        request_body = serde_json::Value,
        responses((status = 200, description = "Metering descriptive analytics", body = serde_json::Value))
    )]
    pub fn analytics_metering() {}

    #[utoipa::path(
        get, path = "/api/reports", tag = "reports",
        responses((status = 200, description = "List report artifacts / drafts", body = serde_json::Value))
    )]
    pub fn reports_list() {}

    #[utoipa::path(
        get, path = "/api/reports/templates", tag = "reports",
        responses((status = 200, description = "List report templates", body = serde_json::Value))
    )]
    pub fn reports_templates() {}

    #[utoipa::path(
        post, path = "/api/reports/draft", tag = "reports",
        request_body = serde_json::Value,
        responses((status = 200, description = "Create a report draft", body = serde_json::Value))
    )]
    pub fn reports_draft() {}

    #[utoipa::path(
        get, path = "/api/reports/{report_id}", tag = "reports",
        params(("report_id" = String, Path, description = "Report id")),
        responses((status = 200, description = "Get a report by id", body = serde_json::Value))
    )]
    pub fn reports_get() {}
}

#[derive(OpenApi)]
#[openapi(
    paths(
        crate::routes::health,
        crate::routes::list_edges,
        crate::routes::get_edge,
        crate::routes::get_edge_discovery,
        crate::routes::get_edge_metadata,
        crate::routes::ingest_stats,
        crate::routes::issue_command,
        crate::routes::get_ack,
        crate::routes::agent_tools,
        crate::routes::fdd_run,
        crate::routes::fdd_status,
        crate::routes::auth_status,
        crate::routes::auth_me,
        crate::routes::auth_login,
        // OFDD-071: live jobs / analytics / datasets / fdd-results / reports routes.
        live_routes::jobs_list,
        live_routes::jobs_create,
        live_routes::jobs_get,
        live_routes::jobs_create_wattlab_handoff,
        live_routes::jobs_queue_eplus_run,
        live_routes::datasets_list,
        live_routes::datasets_delete,
        live_routes::fdd_results,
        live_routes::fdd_equipment,
        live_routes::analytics_runtime,
        live_routes::analytics_economizer,
        live_routes::analytics_sensor_health,
        live_routes::analytics_mechanical_cooling,
        live_routes::analytics_metering,
        live_routes::reports_list,
        live_routes::reports_templates,
        live_routes::reports_draft,
        live_routes::reports_get,
    ),
    components(schemas(
        OkHealthResponse,
        EdgesListResponse,
        EdgeSummary,
        EdgeDetailResponse,
        EdgePayloadResponse,
        IngestStatsResponse,
        IssueCommandRequest,
        IssueCommandResponse,
        CommandAckResponse,
        AgentToolsResponse,
        AgentTool,
        FddRunRequest,
        FddStatusResponse,
        ErrorResponse,
        JwtClaims,
        Role,
        CommandEnvelope,
        CommandAck,
        TelemetryEnvelope,
        AuthStatusResponse,
        AuthMeResponse,
        AuthLoginRequest,
        AuthLoginResponse,
    )),
    modifiers(&SecurityAddon),
    info(
        title = "Open-FDD Central API",
        version = "3.3.0",
        description = "Open-FDD Central control plane — MQTTS ingest, edge shadow, commands, and FDD.\n\n\
            **Auth:** set `OPENFDD_JWT_SECRET` to require `Authorization: Bearer <JWT>` on all `/api/*` routes \
            except `/api/health` and `/api/auth/*`. When unset, the API is open for local/dev with a startup warning.\n\n\
            **Claims:** `sub` (subject), `role` one of `viewer`, `operator`, `admin`. \
            `POST /api/commands` requires `operator` or `admin` when auth is enabled."
    ),
    tags(
        (name = "central", description = "Open-FDD Central control plane"),
        (name = "jobs", description = "Persistent analysis Jobs + WattLab / EnergyPlus handoff"),
        (name = "analytics", description = "Typed analytics envelopes (historian DataFusion / inline)"),
        (name = "datasets", description = "Ingested site datasets (Delete site)"),
        (name = "fdd", description = "Site-scoped FDD rule results / equipment"),
        (name = "reports", description = "Report artifacts, templates, and drafts")
    )
)]
pub struct ApiDoc;

struct SecurityAddon;

impl Modify for SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        if let Some(components) = openapi.components.as_mut() {
            components.add_security_scheme(
                "bearerAuth",
                SecurityScheme::Http(Http::new(HttpAuthScheme::Bearer)),
            );
        }
    }
}

/// Swagger UI at `/docs`; OpenAPI JSON at `/openapi.json` (mounted once by SwaggerUi).
pub fn router() -> Router {
    Router::new()
        .merge(utoipa_swagger_ui::SwaggerUi::new("/docs").url("/openapi.json", ApiDoc::openapi()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn openapi_router_builds_without_overlapping_routes() {
        // Axum panics on duplicate path+method; this was the nightly central crash (#502).
        let _ = router();
    }

    #[test]
    fn openapi_lists_live_jobs_analytics_datasets_reports_routes() {
        // OFDD-071: /openapi.json must advertise the live routes an operator uses,
        // not just the original edge/command/auth subset.
        let doc = ApiDoc::openapi();
        let paths = doc.paths.paths;
        for expected in [
            "/api/jobs",
            "/api/jobs/{job_id}",
            "/api/datasets",
            "/api/fdd/results",
            "/api/analytics/economizer",
            "/api/reports",
        ] {
            assert!(
                paths.contains_key(expected),
                "missing OpenAPI path {expected}"
            );
        }
    }
}
