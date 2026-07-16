//! Swagger UI + OpenAPI JSON for central.

use axum::Router;
use utoipa::openapi::security::{Http, HttpAuthScheme, SecurityScheme};
use utoipa::Modify;
use utoipa::OpenApi;

use crate::auth::{JwtClaims, Role};
use crate::models::*;
use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};

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
    tags((name = "central", description = "Open-FDD Central control plane"))
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
    Router::new().merge(
        utoipa_swagger_ui::SwaggerUi::new("/docs").url("/openapi.json", ApiDoc::openapi()),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn openapi_router_builds_without_overlapping_routes() {
        // Axum panics on duplicate path+method; this was the nightly central crash (#502).
        let _ = router();
    }
}
