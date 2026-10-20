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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SiteProviderHealth {
    pub building_id: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub provider_instance_id: String,
    pub provider: ProviderKind,
    pub endpoint: String,
    pub poll_secs: u64,
    pub mapped_points: usize,
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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProvidersHealthBody {
    pub ok: bool,
    pub poll_enabled: bool,
    pub sites: Vec<SiteProviderHealth>,
    /// Safe configuration code when ingest config failed closed. No secrets.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub config_error: Option<String>,
}
