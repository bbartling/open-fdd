//! OpenAPI request/response schemas for central REST handlers.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use utoipa::ToSchema;

#[derive(Debug, Serialize, ToSchema)]
pub struct OkHealthResponse {
    pub ok: bool,
    pub service: String,
    pub version: String,
    /// Portal driver sites loaded from `OPENFDD_PROVIDER_SITES` (NF and other HTTPS providers).
    pub portal_providers: usize,
    /// CSV package import is a built-in ingest path.
    pub csv_ingest: String,
    /// Ledger-full drops after durable eviction failed (#1168).
    #[serde(default)]
    pub ingest_backpressure: u64,
    /// Live durable receipt map size (pending + committed tombstones).
    #[serde(default)]
    pub receipts_len: usize,
    #[serde(default)]
    pub receipts_capacity: usize,
    #[serde(default)]
    pub receipts_pending: usize,
    #[serde(default)]
    pub receipts_pending_capacity: usize,
    /// Wave L — multi-tenant shared-hosting mode (default false / OFF).
    #[serde(default)]
    pub multi_tenant: bool,
    /// Process start time (RFC3339 UTC). Surviving `/workspace` data is independent of this.
    pub started_at: String,
    /// Seconds since `started_at`.
    pub uptime_secs: u64,
    /// Last successful ingest timestamp this process (null right after boot until first accept).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_ingest_at: Option<String>,
    /// True when OPENFDD storage/parquet root exists on disk (durable historian, not since-boot).
    #[serde(default)]
    pub historian_present: bool,
    /// Product historian. Always `timescale`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub historian: Option<String>,
    /// True when the Timescale pool answers `SELECT 1`.
    /// Process liveness stays in `ok`; this flag is the connection the UI shows.
    #[serde(default)]
    pub timescale_ok: bool,
    /// Empty-database starter seed status (`seeded`, `skipped_existing`, …).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub starter_seed: Option<String>,
    /// Product FDD engine. Always `postgres-sql`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fdd_engine: Option<String>,
    /// Always false after Wave-X cutover (no Parquet+Timescale co-canonical).
    #[serde(default)]
    pub dual_write: bool,
    /// Portable cgroup/host memory budget (#1179): hard/pool/current/shed_state.
    /// Health stays HTTP 200 with shed_state when under memory pressure (capacity 24b).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub memory_budget: Option<Value>,
    /// Non-blocking security-audit file sink (LOG-02/03). Process-local; not Timescale.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub audit_sink: Option<AuditSinkHealth>,
}

/// `/api/health.audit_sink` — file writer queue health (no paths or payloads).
#[derive(Debug, Serialize, ToSchema)]
pub struct AuditSinkHealth {
    /// True after a dropped enqueue or a writer I/O failure; clears on next successful write.
    pub degraded: bool,
    /// Events dropped because the bounded queue was full (lifetime until process restart).
    pub dropped: u64,
    /// Short stable code when the last write failed (`unwritable` | `io`), else null.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_write_error: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct IngestStatsResponse {
    pub ok: bool,
    pub ingest_ok: u64,
    pub ingest_dup: u64,
    pub ingest_reject: u64,
    #[serde(default)]
    pub ingest_backpressure: u64,
    #[serde(default)]
    pub receipts_len: usize,
    #[serde(default)]
    pub receipts_capacity: usize,
    #[serde(default)]
    pub receipts_pending: usize,
    /// Soft-OPEN 371 T1e: estimated bytes reserved on the live-writer queue.
    #[serde(default)]
    pub live_writer_queue_bytes: usize,
    /// Operator-readable reject counts (no payload dump).
    #[serde(default, skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub reject_buckets: std::collections::BTreeMap<String, u64>,
    pub dead_letters: usize,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub product_surface: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ot_discovery: Option<String>,
    pub tools: Vec<AgentTool>,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct FddRunRequest {
    #[serde(default = "default_registry_mode")]
    pub mode: String,
    /// Prefer top-level. Nested `params.rule_ids` / `params.mode` are also
    /// accepted (hunt / nightly-ot-bench curl shape) and hoisted in `fdd_run`.
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
    /// Scope history/results/equipment to `building={id}/` (avoids cross-site
    /// bleed). May also be nested under `params.building_id` (hunt curl form).
    #[serde(default)]
    pub building_id: Option<String>,
    /// Soft-OPEN write-once (BPS parity): batch run-all returns cached results when
    /// cohort records already exist unless this is true (fresh samples / explicit force).
    #[serde(default)]
    pub force_new_data: bool,
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
    /// True when `OPENFDD_AGENT_PASSWORD` is set (username `agent` → operator JWT).
    #[serde(default)]
    pub agent_login_configured: bool,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct AuthAgentTokenRequest {
    /// Token lifetime in seconds (clamped 60..=86400). Default 3600.
    #[serde(default)]
    pub ttl_secs: Option<i64>,
    /// Optional tenant scope for Wave N MT hubs (empty = legacy / hub-wide operator).
    #[serde(default)]
    pub tenant_id: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct AuthMeResponse {
    pub ok: bool,
    pub username: String,
    pub role: String,
    pub auth_required: bool,
    /// Echo of `OPENFDD_MULTI_TENANT` (false until operator enable after Tier-2).
    pub multi_tenant: bool,
    /// Active tenant from TenantContext (`legacy` when mode OFF).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_tenant_id: Option<String>,
    /// Membership claims from JWT (empty when mode OFF / hub passwords).
    #[serde(default)]
    pub tenant_ids: Vec<String>,
    /// Hub admin may cross tenants when mode is on.
    pub hub_admin: bool,
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
    /// Echo of multi-tenant mode at login time.
    pub multi_tenant: bool,
    /// Active tenant for this session (`legacy` when mode OFF).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_tenant_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct TenantSelectRequest {
    pub tenant_id: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct TenantSelectResponse {
    pub ok: bool,
    pub multi_tenant: bool,
    pub active_tenant_id: String,
    /// New JWT when mode ON. It keeps durable membership and names the active tenant.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub access_token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}
