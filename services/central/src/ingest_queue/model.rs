//! Durable ingest job identity shared with Wave-B hourly records.

use chrono::{DateTime, Timelike, Utc};
use serde::Serialize;
use uuid::Uuid;

pub const COVERAGE_NOT_ASSESSED: &str = "not_assessed";
pub const MODEL_REVISION_BOOTSTRAP: &str = "bootstrap";
pub const MAX_CATCHUP_HOURS: u32 = 48;
pub const MAX_LIST: u32 = 200;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JobState {
    Queued,
    Leased,
    RetryWait,
    Committed,
    Partial,
    PermanentFailure,
    Cancelled,
}

impl JobState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Leased => "leased",
            Self::RetryWait => "retry_wait",
            Self::Committed => "committed",
            Self::Partial => "partial",
            Self::PermanentFailure => "permanent_failure",
            Self::Cancelled => "cancelled",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw {
            "queued" => Some(Self::Queued),
            "leased" => Some(Self::Leased),
            "retry_wait" => Some(Self::RetryWait),
            "committed" => Some(Self::Committed),
            "partial" => Some(Self::Partial),
            "permanent_failure" => Some(Self::PermanentFailure),
            "cancelled" => Some(Self::Cancelled),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct JobKey {
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
    pub logical_window_start: DateTime<Utc>,
    pub logical_window_end: DateTime<Utc>,
    pub shard: String,
}

#[derive(Debug, Clone)]
pub struct NewJob {
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
    pub logical_window_start: DateTime<Utc>,
    pub logical_window_end: DateTime<Utc>,
    pub shard: String,
    pub not_before: DateTime<Utc>,
    pub estimated_cost: u32,
    pub requested_points_digest: Option<String>,
}

impl NewJob {
    pub fn key(&self) -> JobKey {
        JobKey {
            tenant_id: self.tenant_id.clone(),
            canonical_site: self.canonical_site.clone(),
            provider_instance_id: self.provider_instance_id.clone(),
            device_id: self.device_id.clone(),
            model_revision: self.model_revision.clone(),
            logical_window_start: self.logical_window_start,
            logical_window_end: self.logical_window_end,
            shard: self.shard.clone(),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, Serialize)]
pub struct JobCounts {
    pub fetched: u32,
    pub accepted: u32,
    pub rejected: u32,
    pub inserted: u32,
    pub updated: u32,
    pub unchanged: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct JobView {
    pub job_id: Uuid,
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
    pub logical_window_start: DateTime<Utc>,
    pub logical_window_end: DateTime<Utc>,
    pub shard: String,
    pub state: String,
    pub attempt: u32,
    pub not_before: DateTime<Utc>,
    pub lease_owner: Option<String>,
    pub lease_expiry: Option<DateTime<Utc>>,
    pub fencing_token: u64,
    pub estimated_cost: u32,
    pub safe_error_code: Option<String>,
    pub receipt_id: Option<Uuid>,
    pub coverage: String,
    pub counts: JobCounts,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReceiptView {
    pub receipt_id: Uuid,
    pub job_id: Uuid,
    pub tenant_id: String,
    pub canonical_site: String,
    pub fencing_token: u64,
    pub committed_at: DateTime<Utc>,
    pub counts: JobCounts,
    pub safe_error_code: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct PortalInFlight {
    pub provider_instance_id: String,
    pub in_flight: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct QueueMetrics {
    pub ready_backlog: u64,
    pub oldest_ready_age_secs: Option<u64>,
    pub leased: u64,
    pub retry_wait: u64,
    pub partial: u64,
    pub permanent_failure: u64,
    pub committed: u64,
    pub scheduler_owner: Option<String>,
    pub portal_in_flight: Vec<PortalInFlight>,
}

#[derive(Debug, Clone)]
pub struct ClaimRequest {
    pub owner: String,
    pub limit: usize,
    pub now: DateTime<Utc>,
    pub lease_for: chrono::Duration,
}

#[derive(Debug, Clone)]
pub enum FinishOutcome {
    Committed {
        counts: JobCounts,
    },
    Partial {
        counts: JobCounts,
        code: String,
    },
    Retry {
        code: String,
        not_before: DateTime<Utc>,
    },
    Permanent {
        code: String,
    },
}

#[derive(Debug, Clone)]
pub struct FinishRequest {
    pub owner: String,
    pub job_id: Uuid,
    pub fencing_token: u64,
    pub now: DateTime<Utc>,
    pub outcome: FinishOutcome,
}

#[derive(Debug, Clone, Copy)]
pub struct BudgetDefaults {
    pub max_in_flight: u32,
    pub max_per_minute: u32,
}

impl Default for BudgetDefaults {
    fn default() -> Self {
        Self {
            max_in_flight: 2,
            max_per_minute: 30,
        }
    }
}

#[derive(Debug, Clone)]
pub struct SchedulerGrant {
    pub owner: String,
    pub fencing_token: u64,
    pub expires_at: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct ListFilter {
    pub sites: Option<Vec<String>>,
    pub state: Option<String>,
    pub limit: u32,
}

#[derive(Debug)]
pub enum EnqueueOutcome {
    Created(JobView),
    Existing(JobView),
}

#[derive(Debug)]
pub enum QueueError {
    StaleFence,
    NotFound,
    Invalid(String),
    Db(String),
}

pub fn redact_db_text(detail: &str) -> String {
    let mut text = detail.to_string();
    if let Some(idx) = text.find("postgres://") {
        text.truncate(idx);
        text.push_str("postgres://redacted");
    }
    truncate_chars(&text, 180)
}

impl std::fmt::Display for QueueError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::StaleFence => write!(f, "stale fence"),
            Self::NotFound => write!(f, "not found"),
            Self::Invalid(msg) => write!(f, "{msg}"),
            Self::Db(_) => write!(f, "queue database unavailable"),
        }
    }
}

pub fn bounded_id(value: &str) -> bool {
    let n = value.chars().count();
    (1..=128).contains(&n)
        && value
            .chars()
            .all(|c| !c.is_control() && c != ' ' && c != '\u{00a0}')
}

pub fn is_hour_window(start: DateTime<Utc>, end: DateTime<Utc>) -> bool {
    end == start + chrono::Duration::hours(1)
        && start.minute() == 0
        && start.second() == 0
        && start.timestamp_subsec_micros() == 0
}

/// Queue jobs accept the configured window length (60..=3600 seconds), aligned
/// to that length. A 3600-second window is still an exact UTC hour.
pub fn is_aligned_window(start: DateTime<Utc>, end: DateTime<Utc>) -> bool {
    if start.timestamp_subsec_micros() != 0 {
        return false;
    }
    let secs = (end - start).num_seconds();
    (60..=3600).contains(&secs) && start.timestamp().rem_euclid(secs) == 0
}

pub fn operator_retry_allowed(state: &str, code: Option<&str>) -> bool {
    if matches!(
        code,
        Some("unrecoverable" | "retention_exceeded" | "not_implemented")
    ) {
        return false;
    }
    matches!(
        state,
        "partial" | "permanent_failure" | "retry_wait" | "cancelled"
    )
}

pub fn gap_recoverable(code: Option<&str>) -> bool {
    !matches!(code, Some("unrecoverable" | "retention_exceeded"))
}

pub fn truncate_chars(value: &str, max: usize) -> String {
    let mut out = String::new();
    for (i, ch) in value.chars().enumerate() {
        if i >= max {
            out.push('…');
            break;
        }
        out.push(ch);
    }
    out
}
