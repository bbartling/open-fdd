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

use crate::auth;
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
        .route("/api/auth/status", get(auth_status))
        .route("/api/auth/me", get(auth_me))
        .route("/api/auth/login", post(auth_login));

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
        .route("/api/fdd/roles", get(fdd_roles))
        .route("/api/fdd/run", post(fdd_run))
        .route("/api/fdd/status", get(fdd_status))
        .merge(csv)
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            auth::jwt_middleware,
        ));

    Router::new()
        .merge(public)
        .merge(protected)
        .with_state(state)
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
        version: env!("CARGO_PKG_VERSION").into(),
        edges: state.edges.len(),
        ingest_ok: *state.ingest_ok.lock().unwrap(),
        ingest_dup: *state.ingest_dup.lock().unwrap(),
        ingest_reject: *state.ingest_reject.lock().unwrap(),
    })
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
        .map(|e| crate::models::EdgeSummary {
            edge_id: e.key().clone(),
            has_telemetry: e.value().lock().unwrap().last_telemetry.is_some(),
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
    let payload = json!({
        "confirmation_seconds": body.confirmation_seconds,
        "params": body.params,
        "mode": body.params.get("mode").cloned().unwrap_or(json!("registry")),
        "rule_ids": body.params.get("rule_ids").cloned(),
    });
    let result = tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::fdd::registry_api::run_registry(&payload)
    })
    .await
    .unwrap_or_else(|e| json!({"ok": false, "error": format!("fdd run task failed: {e}")}));
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

pub async fn fdd_roles() -> Json<Value> {
    Json(open_fdd_edge_prototype::fdd::registry_api::roles_response())
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
