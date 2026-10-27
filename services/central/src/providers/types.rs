//! Normalized provider samples and health snapshots.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderKind {
    Nf,
    AceIot,
    OpenMeteo,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct NormalizedSample {
    pub building_id: String,
    /// Stable connection id (`kind:explicit` or `kind:building:digest`).
    pub provider_instance_id: String,
    pub equipment_id: String,
    /// Stable vendor id (NF uuid / portal id) — never a display name.
    pub provider_point_id: String,
    pub role: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub equip_type: Option<String>,
    pub ts: DateTime<Utc>,
    pub val: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    /// Canonical source quality (`good|uncertain|bad|stale`). Absent means the
    /// source did not state quality; it is not invented as good in SQL.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_quality: Option<String>,
    #[serde(default, skip_serializing_if = "serde_json::Map::is_empty")]
    pub attrs: serde_json::Map<String, serde_json::Value>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProviderHealthStatus {
    Ok,
    Degraded,
    NotConfigured,
    NotImplemented,
    AuthFailed,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProviderHealth {
    pub provider_id: String,
    pub kind: ProviderKind,
    pub status: ProviderHealthStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_success_at: Option<DateTime<Utc>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_error_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WithheldPointSummary {
    pub equipment_id: String,
    pub semantic_point_id: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SiteProviderHealth {
    pub building_id: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub provider_instance_id: String,
    pub provider: ProviderKind,
    pub endpoint: String,
    pub poll_secs: u64,
    pub mapped_points: usize,
    /// Approved points in the committed ingest plan for this connection.
    #[serde(default)]
    pub approved_points: usize,
    /// Withheld provisional or unmapped points in the committed plan.
    #[serde(default)]
    pub withheld_points: usize,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub withheld_point_reasons: Vec<WithheldPointSummary>,
    pub health: ProviderHealth,
    #[serde(default)]
    pub last_poll_at: Option<DateTime<Utc>>,
    #[serde(default)]
    pub last_ingested_points: u64,
    #[serde(default)]
    pub consecutive_errors: u32,
    /// Honest hourly coverage. Absent until the hourly scheduler has run.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hourly_coverage: Option<HourlyCoverageHealth>,
    /// Explicit driver capabilities. Empty only for a hand-built test row.
    #[serde(default)]
    pub capabilities: Vec<ProviderCapability>,
    /// N7 ledger from hourly jobs and receipts. Absent until a tick has run.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub coverage_ledger: Option<CoverageLedger>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
pub struct HourlyCoverageHealth {
    pub durable: bool,
    pub committed: u32,
    pub no_source_data: u32,
    pub failed: u32,
    pub partial: u32,
    pub unrecoverable_gaps: u32,
    pub samples_handed_off: u64,
    pub update_log_status: String,
    pub detail: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilityName {
    Authenticate,
    Latest,
    FetchHistory,
    BoundedWindows,
    UpdateLog,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapabilitySupport {
    Implemented,
    NotImplemented,
}

/// One advertised driver capability. History is never implied by `latest`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProviderCapability {
    pub name: CapabilityName,
    pub support: CapabilitySupport,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub http_method: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_window_secs: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProviderRegistration {
    pub kind: ProviderKind,
    pub capabilities: Vec<ProviderCapability>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AxisId {
    TransportProbe,
    RequestedWindowCompleteness,
    DurableCommit,
    SourceFreshness,
    LateReconciliation,
    UnrecoverableRetention,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AxisState {
    Unknown,
    Ok,
    Degraded,
    Failed,
    NotClaimed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LedgerAxis {
    pub id: AxisId,
    pub state: AxisState,
    pub detail: String,
}

/// What range polling actually guarantees. `gapless` stays false while the
/// NF update log is unavailable.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CoverageGuarantee {
    pub mode: String,
    pub history_method: String,
    pub history_path: String,
    pub update_log_method: String,
    pub update_log_path: String,
    pub update_log_observed_http: u16,
    pub update_log_called: bool,
    pub update_log_status: String,
    pub reconcile_hours: i64,
    pub gapless: bool,
    pub statement: String,
}

/// Six coverage axes derived from hourly jobs, receipts, checkpoints, and gaps.
/// A latest scrape is not an input and cannot advance any axis.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CoverageLedger {
    pub guarantee: CoverageGuarantee,
    pub axes: Vec<LedgerAxis>,
    pub windows_complete: u32,
    pub windows_incomplete: u32,
    pub windows_pending: u32,
    pub transport_failures: u32,
    pub durable_receipts: u32,
    pub reconcile_committed: u32,
    pub reconcile_open: u32,
    pub unrecoverable_gaps: u32,
    pub gapless: bool,
    pub advanced_by_latest_sample: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProvidersHealthBody {
    pub ok: bool,
    pub poll_enabled: bool,
    pub sites: Vec<SiteProviderHealth>,
    /// Safe configuration code when ingest config failed closed. No secrets.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub config_error: Option<String>,
    /// Static driver registry. Present even when no site is configured.
    #[serde(default)]
    pub registry: Vec<ProviderRegistration>,
}
