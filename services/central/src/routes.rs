//! Central REST + OpenAPI routes.

use std::sync::Arc;

use axum::extract::{DefaultBodyLimit, Path, Query, State};
use axum::http::{header, HeaderMap, StatusCode};
use axum::middleware;
use axum::routing::{get, post};
use axum::{Json, Router};
use bytes::Bytes;
use chrono::Utc;
use openfdd_contracts::{CommandEnvelope, Protocol, TopicBuilder, TopicKind};
use openfdd_mqtt::publish_json;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::analytics::{self, AnalyticsRequest};
use crate::auth;
use crate::eplus_runner;
use crate::jobs;
use crate::models::{
    AgentTool, AgentToolsResponse, AuthLoginRequest, AuthLoginResponse, AuthMeResponse,
    AuthStatusResponse, CommandAckResponse, EdgeDetailResponse, EdgePayloadResponse,
    EdgesListResponse, FddRunRequest, FddStatusResponse, IngestStatsResponse, IssueCommandRequest,
    IssueCommandResponse, OkHealthResponse,
};
use crate::state::{AppState, PendingCommand};

pub fn router(state: Arc<AppState>) -> Router {
    let public = Router::new()
        .route("/api/health", get(health))
        .route("/health", get(health))
        .route("/api/capabilities", get(capabilities))
        .route("/api/auth/status", get(auth_status))
        .route("/api/auth/me", get(auth_me))
        .route("/api/auth/login", post(auth_login))
        // Shell strip + building summary are intentionally public (UI before login).
        .route("/api/health/stack", get(health_stack))
        .route("/api/building/snapshot", get(building_snapshot));

    let csv = Router::new()
        .route("/api/csv/import/preview", post(csv_preview))
        .route("/api/csv/import/package", post(csv_import_package))
        .route(
            "/api/csv/import/package/roles",
            post(csv_import_package_roles),
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
        .route("/api/edges", get(list_edges))
        .route("/api/edges/{edge_id}", get(get_edge))
        .route("/api/edges/{edge_id}/discovery", get(get_edge_discovery))
        .route("/api/edges/{edge_id}/metadata", get(get_edge_metadata))
        .route("/api/ingest/stats", get(ingest_stats))
        .route("/api/commands", post(issue_command))
        .route("/api/commands/{command_id}/ack", get(get_ack))
        .route("/api/agent/tools", get(agent_tools))
        .route("/api/fdd/rules", get(fdd_registry_rules))
        .route("/api/fdd/rules/{rule_id}/params", get(fdd_rule_params))
        .route("/api/fdd/cache/status", get(fdd_cache_status))
        .route("/api/fdd/equipment", get(fdd_equipment))
        .route("/api/fdd/results", get(fdd_results))
        .route("/api/fdd/series", get(fdd_series))
        .route("/api/fdd/roles", get(fdd_roles))
        .route(
            "/api/fdd/session-config",
            get(fdd_session_config_get).put(fdd_session_config_put),
        )
        .route("/api/fdd/run", post(fdd_run))
        .route("/api/fdd/status", get(fdd_status))
        .route("/api/faults/status", get(faults_status))
        .route("/api/faults/summary", get(faults_summary))
        .route("/api/export/meta", get(export_meta))
        .route("/api/data-management/summary", get(data_management_summary))
        .route("/api/host/stats", get(host_stats))
        .route("/api/fdd-schema/tables", get(fdd_schema_tables))
        .route("/api/fdd-rules", get(fdd_rules_list))
        .route("/api/reports", get(reports_list))
        .route("/api/reports/templates", get(reports_templates))
        .route("/api/reports/draft", post(reports_draft))
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
        .route("/api/jobs/{job_id}", get(jobs_get).patch(jobs_patch))
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
        .route("/api/jobs/{job_id}/eplus/runs", post(jobs_queue_eplus_run))
        .route(
            "/api/jobs/{job_id}/eplus/runs/{eplus_run_id}/artifacts",
            post(jobs_attach_eplus_artifact),
        )
        .route("/api/analytics/runtime", post(analytics_runtime))
        .route(
            "/api/analytics/sensor-health",
            post(analytics_sensor_health),
        )
        .route("/api/analytics/schedule", post(analytics_schedule))
        .route(
            "/api/analytics/mechanical-cooling",
            post(analytics_mechanical_cooling),
        )
        .route("/api/analytics/economizer", post(analytics_economizer))
        .route("/api/analytics/rcx/ahu", post(analytics_rcx_ahu))
        .route("/api/analytics/rcx/vav", post(analytics_rcx_vav))
        .route("/api/analytics/rcx/chiller", post(analytics_rcx_chiller))
        .route("/api/analytics/rcx/boiler", post(analytics_rcx_boiler))
        .route("/api/analytics/metering", post(analytics_metering))
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
    Json(OkHealthResponse {
        ok: true,
        service: "openfdd-central".into(),
        version: resolve_build_version(),
        edges: state.edges.len(),
        ingest_ok: *state.ingest_ok.lock().unwrap(),
        ingest_dup: *state.ingest_dup.lock().unwrap(),
        ingest_reject: *state.ingest_reject.lock().unwrap(),
    })
}

/// Feature advertisement for UI capability gates and MCP accuracy checks.
pub async fn capabilities() -> Json<Value> {
    Json(json!({
        "ok": true,
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
            "faults": true,
            "health_stack": true,
            "fdd_rules_authoring": true,
            "fdd_schema": true,
            "analytics": true
        }
    }))
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
        Ok(user) => Ok(Json(AuthMeResponse {
            ok: true,
            username: user.sub,
            role: user.role.as_str().into(),
            auth_required: state.auth.required(),
        })),
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
    Json(body): Json<AuthLoginRequest>,
) -> Result<Json<AuthLoginResponse>, (axum::http::StatusCode, Json<Value>)> {
    if !state.auth.required() {
        // Dev open mode — mint a placeholder so the UI can store a session token.
        return Ok(Json(AuthLoginResponse {
            ok: true,
            token: "open".into(),
            access_token: "open".into(),
            token_type: "Bearer".into(),
            role: "admin".into(),
            subject: "dev".into(),
            error: None,
        }));
    }
    let (sub, role) = state
        .auth
        .authenticate_password(&body.username, &body.password)
        .map_err(|e| {
            (
                axum::http::StatusCode::UNAUTHORIZED,
                Json(json!({"ok": false, "error": e})),
            )
        })?;
    let token = state.auth.issue_token(&sub, role, 8 * 3600).map_err(|e| {
        (
            axum::http::StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": e})),
        )
    })?;
    Ok(Json(AuthLoginResponse {
        ok: true,
        token: token.clone(),
        access_token: token,
        token_type: "Bearer".into(),
        role: role.as_str().into(),
        subject: sub,
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
pub async fn list_edges(State(state): State<Arc<AppState>>) -> Json<EdgesListResponse> {
    let edges = state
        .edges
        .iter()
        .map(|e| {
            let g = e.value().lock().unwrap();
            let site_id = g
                .last_telemetry
                .as_ref()
                .map(|t| t.site_id.clone())
                .filter(|s| !s.is_empty());
            crate::models::EdgeSummary {
                edge_id: e.key().clone(),
                site_id,
                has_telemetry: g.last_telemetry.is_some(),
            }
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
    Path(edge_id): Path<String>,
) -> Json<EdgeDetailResponse> {
    match state.edges.get(&edge_id) {
        Some(e) => {
            let g = e.lock().unwrap();
            Json(EdgeDetailResponse {
                ok: true,
                edge_id,
                last_telemetry: g.last_telemetry.clone(),
                sequences: g.sequences.clone(),
                error: None,
            })
        }
        None => Json(EdgeDetailResponse {
            ok: false,
            edge_id,
            last_telemetry: None,
            sequences: Default::default(),
            error: Some("edge not found".into()),
        }),
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
    Path(edge_id): Path<String>,
) -> Json<EdgePayloadResponse> {
    match state.edges.get(&edge_id) {
        Some(e) => {
            let g = e.lock().unwrap();
            let payload = if g.last_discovery.is_empty() {
                None
            } else {
                Some(json!(g.last_discovery))
            };
            Json(EdgePayloadResponse {
                ok: true,
                edge_id,
                payload,
                error: None,
            })
        }
        None => Json(EdgePayloadResponse {
            ok: false,
            edge_id,
            payload: None,
            error: Some("edge not found".into()),
        }),
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
    Path(edge_id): Path<String>,
) -> Json<EdgePayloadResponse> {
    match state.edges.get(&edge_id) {
        Some(e) => {
            let g = e.lock().unwrap();
            let payload = if g.last_metadata.is_empty() {
                None
            } else {
                Some(json!(g.last_metadata))
            };
            Json(EdgePayloadResponse {
                ok: true,
                edge_id,
                payload,
                error: None,
            })
        }
        None => Json(EdgePayloadResponse {
            ok: false,
            edge_id,
            payload: None,
            error: Some("edge not found".into()),
        }),
    }
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
    let user = match state.auth.user_from_headers(&headers) {
        Ok(u) => u,
        Err(detail) => {
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

    let topics = TopicBuilder::new(&body.site_id, &body.edge_id);
    let response_topic = topics.topic(TopicKind::Acks, Some(Protocol::Bacnet));
    let cmd = CommandEnvelope::new(
        &body.site_id,
        &body.edge_id,
        Protocol::Bacnet,
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

    let publish_topic = topics.topic(TopicKind::Commands, Some(Protocol::Bacnet));
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
                name: "csv.import.execute".into(),
                method: "POST".into(),
                path: "/api/csv/import/execute".into(),
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
pub async fn fdd_run(Json(body): Json<FddRunRequest>) -> Json<Value> {
    let has_sql = body.sql.as_ref().is_some_and(|s| !s.trim().is_empty());
    if has_sql {
        return Json(json!({
            "ok": false,
            "error": "raw SQL rejected on /api/fdd/run; use mode=registry with typed params"
        }));
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
    let payload = json!({
        "confirmation_seconds": body.confirmation_seconds,
        "params": body.params,
        "mode": body.mode,
        "rule_ids": body.rule_ids,
        "equipment_id": body.equipment_id,
        "building_id": building_id,
    });
    let echo_building_id = building_id.clone();
    let mut result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::fdd::registry_api::run_registry(&payload)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("fdd run task failed: {e}")}));
    // Echo the requested building_id when the edge did not surface one, so the
    // UI/MCP always know which site the run was scoped to.
    if let (Some(bid), Some(obj)) = (echo_building_id, result.as_object_mut()) {
        let missing = obj.get("building_id").map(|v| v.is_null()).unwrap_or(true);
        if missing {
            obj.insert("building_id".into(), json!(bid));
        }
    }
    Json(result)
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

pub async fn fdd_equipment(Query(q): Query<BuildingScopeQuery>) -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::equipment_response(q.scoped()))
}

pub async fn fdd_results(Query(q): Query<BuildingScopeQuery>) -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::results_response(q.scoped()))
}

#[derive(Debug, Deserialize)]
pub struct FddSeriesQuery {
    equipment_id: String,
    rule_id: String,
}

pub async fn fdd_series(Query(query): Query<FddSeriesQuery>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::fdd::registry_api::series_response(
            &query.equipment_id,
            &query.rule_id,
        )
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("series task failed: {e}")}));
    Json(result)
}

pub async fn fdd_roles() -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::roles_response())
}

/// `openfdd_session_v1` session/fault settings (#515) — persisted per workspace.
pub async fn fdd_session_config_get() -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::session_config::get_session_config())
}

pub async fn fdd_session_config_put(Json(body): Json<Value>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::fdd::session_config::put_session_config(&body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("session config task: {e}")}));
    Json(result)
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
pub async fn csv_import_package(headers: HeaderMap, body: Bytes) -> Json<Value> {
    let ct = content_type(&headers);
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::import_package_handler(&ct, &body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package import task: {e}")}));
    Json(result)
}

/// Edit role assignments for an ingested package equipment, then re-ingest.
pub async fn csv_import_package_roles(Json(body): Json<Value>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::package::update_package_roles_handler(&body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("package roles task: {e}")}));
    Json(result)
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

pub async fn csv_list_datasets() -> Json<Value> {
    Json(open_fdd_edge_prototype::csv_ingest::list_datasets())
}

#[derive(Debug, Deserialize)]
pub struct DatasetIdQuery {
    pub id: Option<String>,
}

pub async fn csv_delete_dataset(
    Query(q): Query<DatasetIdQuery>,
) -> Result<Json<Value>, (StatusCode, Json<Value>)> {
    let Some(id) = q.id.as_deref().filter(|s| !s.is_empty()) else {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "id query required"})),
        ));
    };
    match open_fdd_edge_prototype::csv_ingest::delete_dataset(id) {
        Ok(()) => Ok(Json(json!({"ok": true}))),
        Err(e) => Ok(Json(json!({"ok": false, "error": e}))),
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

pub async fn host_stats() -> Json<Value> {
    Json(open_fdd_edge_prototype::ops::host_stats::stats_json())
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

pub async fn reports_list() -> Json<Value> {
    Json(open_fdd_edge_prototype::reports::list_reports())
}

pub async fn reports_templates() -> Json<Value> {
    Json(open_fdd_edge_prototype::reports::templates())
}

pub async fn reports_draft(Json(body): Json<Value>) -> Json<Value> {
    let result =
        tokio::task::spawn_blocking(move || open_fdd_edge_prototype::reports::create_draft(&body))
            .await
            .unwrap_or_else(|e| json!({"ok": false, "error": format!("reports draft task: {e}")}));
    Json(result)
}

pub async fn reports_get(Path(report_id): Path<String>) -> Json<Value> {
    Json(open_fdd_edge_prototype::reports::get_report(&report_id))
}

pub async fn reports_patch(Path(report_id): Path<String>, Json(body): Json<Value>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::reports::patch_report(&report_id, &body)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("reports patch task: {e}")}));
    Json(result)
}

pub async fn reports_delete(Path(report_id): Path<String>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::reports::delete_report(&report_id)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("reports delete task: {e}")}));
    Json(result)
}

pub async fn reports_render_pdf(Path(report_id): Path<String>) -> Json<Value> {
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::reports::render_pdf_bundle(&report_id)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("reports render task: {e}")}));
    Json(result)
}

pub async fn reports_download_pdf(
    Path(report_id): Path<String>,
) -> Result<(StatusCode, HeaderMap, Vec<u8>), (StatusCode, Json<Value>)> {
    let safe_id: String = report_id
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect();
    if safe_id.is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid report_id"})),
        ));
    }
    let report_id_for_io = report_id.clone();
    let bytes = tokio::task::spawn_blocking(move || {
        let path = open_fdd_edge_prototype::reports::download_path(&report_id_for_io, "pdf")
            .ok_or_else(|| "pdf not found — render first".to_string())?;
        std::fs::read(path).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| {
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(json!({"ok": false, "error": format!("reports download task: {e}")})),
        )
    })?
    .map_err(|e| {
        let status = if e.contains("not found") {
            StatusCode::NOT_FOUND
        } else {
            StatusCode::INTERNAL_SERVER_ERROR
        };
        (status, Json(json!({"ok": false, "error": e})))
    })?;
    let mut headers = HeaderMap::new();
    headers.insert(header::CONTENT_TYPE, "application/pdf".parse().unwrap());
    let disposition = format!("attachment; filename=\"report-{safe_id}.pdf\"");
    let disposition_value = disposition.parse().map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({"ok": false, "error": "invalid report_id for Content-Disposition"})),
        )
    })?;
    headers.insert(header::CONTENT_DISPOSITION, disposition_value);
    Ok((StatusCode::OK, headers, bytes))
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
    Json(body): Json<CreateJobBody>,
) -> Result<(StatusCode, Json<Value>), (StatusCode, Json<Value>)> {
    let meta = jobs::create_job(
        &body.job_name,
        body.site_id,
        body.site_name,
        body.building_name,
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

async fn analytics_runtime(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    let env = analytics::runtime::handle_async(&req).await;
    Json(json!({
        "ok": true,
        "analytics": env.to_json(),
    }))
}

async fn analytics_sensor_health(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::sensor_health::handle_async(&req).await.to_json(),
    }))
}

async fn analytics_schedule(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::schedule::handle_async(&req).await.to_json(),
    }))
}

async fn analytics_mechanical_cooling(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::mechanical_cooling::handle_async(&req).await.to_json(),
    }))
}

async fn analytics_economizer(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::economizer::handle_async(&req).await.to_json(),
    }))
}

async fn analytics_rcx_ahu(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::rcx::handle_ahu_async(&req).await.to_json(),
    }))
}

async fn analytics_rcx_vav(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::rcx::handle_vav_async(&req).await.to_json(),
    }))
}

async fn analytics_rcx_chiller(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant::handle_chiller_async(&req).await.to_json(),
    }))
}

async fn analytics_rcx_boiler(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::plant::handle_boiler_async(&req).await.to_json(),
    }))
}

async fn analytics_metering(Json(req): Json<AnalyticsRequest>) -> Json<Value> {
    Json(json!({
        "ok": true,
        "analytics": analytics::metering::handle_async(&req).await.to_json(),
    }))
}

#[cfg(test)]
mod version_tests {
    use super::resolve_build_version;

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
}
