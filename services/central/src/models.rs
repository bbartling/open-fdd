//! OpenAPI request/response schemas for central REST handlers.

use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;

#[derive(Debug, Serialize, ToSchema)]
pub struct OkHealthResponse {
    pub ok: bool,
    pub service: String,
    pub version: String,
    pub edges: usize,
    pub ingest_ok: u64,
    pub ingest_dup: u64,
    pub ingest_reject: u64,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct EdgeSummary {
    pub edge_id: String,
    pub has_telemetry: bool,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct EdgesListResponse {
    pub ok: bool,
    pub edges: Vec<EdgeSummary>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct EdgeDetailResponse {
    pub ok: bool,
    pub edge_id: String,
    #[schema(value_type = Object, nullable = true)]
    pub last_telemetry: Option<TelemetryEnvelope>,
    #[schema(value_type = Object)]
    pub sequences: std::collections::HashMap<String, u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct IngestStatsResponse {
    pub ok: bool,
    pub ingest_ok: u64,
    pub ingest_dup: u64,
    pub ingest_reject: u64,
    pub dead_letters: usize,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct IssueCommandRequest {
    #[serde(default = "default_site")]
    pub site_id: String,
    #[serde(default = "default_edge")]
    pub edge_id: String,
    pub target_id: String,
    pub approved_by: String,
    #[schema(value_type = Object)]
    pub value: Value,
    #[serde(default = "default_ttl")]
    pub ttl_secs: i64,
}

fn default_site() -> String {
    "local".into()
}
fn default_edge() -> String {
    "fieldbus-1".into()
}
fn default_ttl() -> i64 {
    120
}

#[derive(Debug, Serialize, ToSchema)]
pub struct IssueCommandResponse {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub command: Option<CommandEnvelope>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub publish_topic: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub response_topic: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub published: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct CommandAckResponse {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ack: Option<CommandAck>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pending: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct AgentTool {
    pub name: String,
    pub method: String,
    pub path: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct AgentToolsResponse {
    pub ok: bool,
    pub tools: Vec<AgentTool>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct EdgePayloadResponse {
    pub ok: bool,
    pub edge_id: String,
    #[schema(value_type = Object, nullable = true)]
    pub payload: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct FddRunRequest {
    #[serde(default = "default_registry_mode")]
    pub mode: String,
    #[serde(default)]
    pub rule_ids: Option<Vec<String>>,
    #[serde(default)]
    pub equipment_id: Option<String>,
    #[serde(default)]
    #[schema(value_type = Object)]
    pub params: Value,
    #[serde(default)]
    pub confirmation_seconds: Option<i64>,
    #[serde(default)]
    pub sql: Option<String>,
}

fn default_registry_mode() -> String {
    "registry".into()
}

#[derive(Debug, Serialize, ToSchema)]
pub struct FddStatusResponse {
    pub ok: bool,
    pub rules_dir: String,
    pub rules_dir_exists: bool,
    pub rule_count: u64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hint: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ErrorResponse {
    pub ok: bool,
    pub error: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct AuthStatusResponse {
    pub ok: bool,
    pub auth_required: bool,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct AuthMeResponse {
    pub ok: bool,
    pub username: String,
    pub role: String,
    pub auth_required: bool,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct AuthLoginRequest {
    pub username: String,
    pub password: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct AuthLoginResponse {
    pub ok: bool,
    pub token: String,
    pub access_token: String,
    pub token_type: String,
    pub role: String,
    pub subject: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}
