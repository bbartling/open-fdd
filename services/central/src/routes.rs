//! Central REST + OpenAPI routes.

use std::sync::Arc;

use axum::extract::{Path, State};
use axum::middleware;
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::Utc;
use openfdd_contracts::{CommandEnvelope, Protocol, TopicBuilder, TopicKind};
use openfdd_mqtt::publish_json;
use serde_json::{json, Value};

use crate::auth;
use crate::models::{
    AgentTool, AgentToolsResponse, CommandAckResponse, EdgeDetailResponse, EdgePayloadResponse,
    EdgesListResponse, FddRunRequest, FddStatusResponse, IngestStatsResponse, IssueCommandRequest,
    IssueCommandResponse, OkHealthResponse,
};
use crate::state::{AppState, PendingCommand};

pub fn router(state: Arc<AppState>) -> Router {
    let public = Router::new()
        .route("/api/health", get(health))
        .route("/health", get(health));

    let protected = Router::new()
        .route("/api/edges", get(list_edges))
        .route("/api/edges/{edge_id}", get(get_edge))
        .route("/api/edges/{edge_id}/discovery", get(get_edge_discovery))
        .route("/api/edges/{edge_id}/metadata", get(get_edge_metadata))
        .route("/api/ingest/stats", get(ingest_stats))
        .route("/api/commands", post(issue_command))
        .route("/api/commands/{command_id}/ack", get(get_ack))
        .route("/api/agent/tools", get(agent_tools))
        .route("/api/fdd/run", post(fdd_run))
        .route("/api/fdd/status", get(fdd_status))
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
        ],
    })
}

#[utoipa::path(
    post,
    path = "/api/fdd/run",
    tag = "central",
    security(("bearerAuth" = [])),
    request_body = FddRunRequest,
    responses((status = 200, description = "FDD batch or ad-hoc SQL run result", body = Object))
)]
pub async fn fdd_run(Json(body): Json<FddRunRequest>) -> Json<Value> {
    let payload = json!({
        "sql": body.sql,
        "confirmation_seconds": body.confirmation_seconds,
        "params": body.params,
    });
    let result = if body.sql.as_ref().is_some_and(|s| !s.trim().is_empty()) {
        open_fdd_edge_prototype::fdd::datafusion_sql::run_fdd_response(&payload)
    } else {
        open_fdd_edge_prototype::fdd::datafusion_sql::batch_run_response()
    };
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
    let rules_body = open_fdd_edge_prototype::fdd::rules::list_rules();
    let count = rules_body
        .get("count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let workspace = std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into());
    let rules_dir = format!("{workspace}/data/fdd_wires/rules");
    let rules_dir_exists = std::path::Path::new(&rules_dir).exists();
    Json(FddStatusResponse {
        ok: true,
        rules_dir,
        rules_dir_exists,
        rule_count: count,
        hint: if count == 0 {
            Some(
                "activate rules in workspace/data/fdd_wires/rules or POST /api/fdd/run with sql"
                    .into(),
            )
        } else {
            None
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
