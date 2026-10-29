//! Durable ingest job identity shared with Wave-B hourly records.

use chrono::{DateTime, Timelike, Utc};
use serde::Serialize;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::coverage::{CoverageReport, COMPLETE, INCOMPLETE};

pub type HourWindow = (DateTime<Utc>, DateTime<Utc>);

pub const COVERAGE_NOT_ASSESSED: &str = "not_assessed";
pub const MAX_CATCHUP_HOURS: u32 = 48;
/// Max UTC hours enqueued by one `POST /api/ingest/backfill/site` request.
pub const MAX_SITE_BACKFILL_WINDOWS: u32 = MAX_CATCHUP_HOURS;
/// Max device×hour jobs enqueued by one site backfill request.
pub const MAX_SITE_BACKFILL_JOBS: u32 = 2048;
pub const MAX_LIST: u32 = 200;
/// Revision stamped on hourly jobs before plans were content-addressed.
/// A backfill that still names it binds to the active plan.
pub const MODEL_REVISION_BOOTSTRAP: &str = "bootstrap";

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
    pub point_coverage: Vec<super::coverage::PointCoverage>,
    pub counts: JobCounts,
    /// Server request id captured when the job was created. Null for scheduler work.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_request_id: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ReceiptView {
    pub receipt_id: Uuid,
    pub job_id: Uuid,
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
    pub fencing_token: u64,
    pub committed_at: DateTime<Utc>,
    pub counts: JobCounts,
    pub safe_error_code: Option<String>,
    /// Copied from the job. Null when the job had no server request id.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server_request_id: Option<String>,
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
        coverage: CoverageReport,
    },
    Partial {
        counts: JobCounts,
        code: String,
        coverage: CoverageReport,
    },
    Retry {
        code: String,
        not_before: DateTime<Utc>,
    },
    Permanent {
        code: String,
    },
}

impl FinishOutcome {
    #[cfg(test)]
    pub fn committed_accounted(counts: JobCounts) -> Self {
        Self::Committed {
            counts,
            coverage: CoverageReport::accounted("accounted-point"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct FinishRequest {
    pub owner: String,
    pub job_id: Uuid,
    pub fencing_token: u64,
    pub now: DateTime<Utc>,
    pub outcome: FinishOutcome,
    /// Revision observed after the fetch. Commit is refused when it no longer
    /// owns the job. `None` skips the check for callers that are not a worker.
    pub active_model_revision: Option<String>,
    /// Digest of the active point set. `None` skips the check.
    pub active_points_digest: Option<String>,
    pub applied_samples: Vec<AppliedSample>,
}

impl FinishRequest {
    pub fn new(
        owner: impl Into<String>,
        job_id: Uuid,
        fencing_token: u64,
        now: DateTime<Utc>,
        outcome: FinishOutcome,
    ) -> Self {
        Self {
            owner: owner.into(),
            job_id,
            fencing_token,
            now,
            outcome,
            active_model_revision: None,
            active_points_digest: None,
            applied_samples: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppliedSample {
    pub point_id: String,
    pub ts: DateTime<Utc>,
    pub value_bits: u64,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ApplyStats {
    pub inserted: u32,
    pub unchanged: u32,
    pub conflict: u32,
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
    pub tenant_id: Option<String>,
    pub state: Option<String>,
    pub limit: u32,
}

/// Counts for one caller. `None` tenant and sites means the hub-wide total.
/// Scheduler identity is included only for that hub-wide read.
#[derive(Debug, Clone)]
pub struct MetricsScope {
    pub tenant_id: Option<String>,
    pub sites: Option<Vec<String>>,
    pub include_scheduler: bool,
}

impl MetricsScope {
    pub fn global() -> Self {
        Self {
            tenant_id: None,
            sites: None,
            include_scheduler: true,
        }
    }
}

/// Client key plus the authenticated binding that makes a replay safe.
#[derive(Debug, Clone)]
pub struct IdempotencyClaim {
    pub actor: String,
    pub tenant_id: String,
    pub client_key: String,
    pub object_id: String,
    pub payload_hash: String,
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
    Conflict(String),
    Invalid(String),
    /// The window starts before the site's applied-sample replay horizon.
    ReplayHorizon(String),
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
            Self::Conflict(msg) => write!(f, "{msg}"),
            Self::Invalid(msg) => write!(f, "{msg}"),
            Self::ReplayHorizon(msg) => write!(f, "{msg}"),
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

pub fn is_hour_start(start: DateTime<Utc>) -> bool {
    start.minute() == 0 && start.second() == 0 && start.timestamp_subsec_micros() == 0
}

pub fn is_hour_window(start: DateTime<Utc>, end: DateTime<Utc>) -> bool {
    end == start + chrono::Duration::hours(1) && is_hour_start(start)
}

/// Half-open UTC hour windows `[start, end)` aligned to exact hours.
pub fn hourly_windows_between(
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    max_windows: u32,
) -> Result<Vec<HourWindow>, QueueError> {
    if end <= start {
        return Err(QueueError::Invalid(
            "backfill end must be after start".into(),
        ));
    }
    if !is_hour_start(start) || !is_hour_start(end) {
        return Err(QueueError::Invalid(
            "backfill range must use exact UTC hour boundaries".into(),
        ));
    }
    let mut windows = Vec::new();
    let mut cursor = start;
    while cursor < end {
        if windows.len() >= max_windows as usize {
            return Err(QueueError::Invalid(format!(
                "backfill range exceeds {max_windows} hourly windows"
            )));
        }
        let next = cursor + chrono::Duration::hours(1);
        windows.push((cursor, next));
        cursor = next;
    }
    if windows.is_empty() {
        return Err(QueueError::Invalid("backfill range is empty".into()));
    }
    Ok(windows)
}

/// Queue jobs accept the configured window length (60..=3600 seconds), aligned
/// to that length. A 3600-second window is still an exact UTC hour.
pub fn revision_still_owns(job_revision: &str, active_revision: &str) -> bool {
    job_revision == active_revision || job_revision == MODEL_REVISION_BOOTSTRAP
}

pub fn points_digest(point_ids: &[String]) -> String {
    let mut ids = point_ids.to_vec();
    ids.sort();
    let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
    scoped_digest(&refs)
}

pub fn validate_new_job(job: &NewJob) -> Result<(), QueueError> {
    for value in [
        job.tenant_id.as_str(),
        job.canonical_site.as_str(),
        job.provider_instance_id.as_str(),
        job.device_id.as_str(),
        job.model_revision.as_str(),
    ] {
        if !bounded_id(value) {
            return Err(QueueError::Invalid(
                "job identity is empty or too long".into(),
            ));
        }
    }
    if !is_aligned_window(job.logical_window_start, job.logical_window_end) {
        return Err(QueueError::Invalid(
            "logical window must be a half-open aligned UTC window within the driver span cap"
                .into(),
        ));
    }
    Ok(())
}

pub fn rollup_coverage<'a>(summaries: impl IntoIterator<Item = &'a str>) -> &'static str {
    let mut saw_incomplete = false;
    let mut saw_unknown = false;
    let mut saw_any = false;
    for summary in summaries {
        saw_any = true;
        if summary == INCOMPLETE {
            saw_incomplete = true;
        } else if summary != COMPLETE {
            saw_unknown = true;
        }
    }
    if !saw_any {
        COVERAGE_NOT_ASSESSED
    } else if saw_incomplete {
        INCOMPLETE
    } else if saw_unknown {
        COVERAGE_NOT_ASSESSED
    } else {
        COMPLETE
    }
}

/// Longest logical window the NF driver accepts on one job (`MAX_HISTORY_WINDOW`).
pub fn max_logical_window_secs() -> i64 {
    crate::providers::http_policy::MAX_HISTORY_WINDOW.num_seconds()
}

pub fn is_aligned_window(start: DateTime<Utc>, end: DateTime<Utc>) -> bool {
    if start.timestamp_subsec_micros() != 0 {
        return false;
    }
    let secs = (end - start).num_seconds();
    let max = max_logical_window_secs();
    (60..=max).contains(&secs) && start.timestamp().rem_euclid(secs) == 0
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

pub fn scoped_digest(parts: &[&str]) -> String {
    let mut hasher = Sha256::new();
    for part in parts {
        let len = u32::try_from(part.len()).unwrap_or(u32::MAX);
        hasher.update(len.to_be_bytes());
        hasher.update(part.as_bytes());
    }
    hex::encode(hasher.finalize())
}

pub fn retry_object_id(job_id: Uuid) -> String {
    job_id.to_string()
}

pub fn retry_payload_hash(tenant_id: &str, job_id: Uuid) -> String {
    scoped_digest(&["retry", tenant_id, &job_id.to_string()])
}

#[derive(Debug, Clone)]
pub struct CancelFilter {
    pub tenant_id: String,
    pub canonical_site: Option<String>,
    pub provider_instance_id: Option<String>,
    pub device_id: Option<String>,
    pub window_start: Option<DateTime<Utc>>,
    pub window_end: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CancelOutcome {
    pub cancelled: u32,
    pub job_ids: Vec<Uuid>,
}

pub fn cancel_filter_digest(filter: &CancelFilter) -> String {
    let site = filter.canonical_site.as_deref().unwrap_or("");
    let provider = filter.provider_instance_id.as_deref().unwrap_or("");
    let device = filter.device_id.as_deref().unwrap_or("");
    let start = filter
        .window_start
        .map(|ts| ts.to_rfc3339())
        .unwrap_or_default();
    let end = filter
        .window_end
        .map(|ts| ts.to_rfc3339())
        .unwrap_or_default();
    scoped_digest(&[
        "cancel_filter",
        filter.tenant_id.as_str(),
        site,
        provider,
        device,
        start.as_str(),
        end.as_str(),
    ])
}

pub fn cancel_object_id(filter: &CancelFilter) -> String {
    format!("{}\n{}", filter.tenant_id, cancel_filter_digest(filter))
}

pub fn cancel_payload_hash(filter: &CancelFilter) -> String {
    scoped_digest(&[
        "cancel",
        filter.tenant_id.as_str(),
        cancel_filter_digest(filter).as_str(),
    ])
}

pub const NOT_EXPECTED_CODE: &str = "not_expected";

pub fn backfill_object_id(job: &NewJob) -> String {
    [
        job.canonical_site.as_str(),
        job.provider_instance_id.as_str(),
        job.device_id.as_str(),
        job.model_revision.as_str(),
    ]
    .join("\n")
}

pub fn site_backfill_object_id(job: &NewJob) -> String {
    [
        "site",
        job.tenant_id.as_str(),
        job.canonical_site.as_str(),
        job.provider_instance_id.as_str(),
        job.model_revision.as_str(),
    ]
    .join("\n")
}

pub fn site_backfill_payload_hash(
    tenant_id: &str,
    canonical_site: &str,
    provider_instance_id: &str,
    model_revision: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> String {
    let start_text = start.to_rfc3339();
    let end_text = end.to_rfc3339();
    scoped_digest(&[
        "site_backfill",
        tenant_id,
        canonical_site,
        provider_instance_id,
        model_revision,
        start_text.as_str(),
        end_text.as_str(),
    ])
}

pub fn backfill_payload_hash(jobs: &[NewJob]) -> Result<String, QueueError> {
    let Some(first) = jobs.first() else {
        return Err(QueueError::Invalid(
            "backfill requires 1 to 48 hourly windows".into(),
        ));
    };
    let object = backfill_object_id(first);
    if jobs
        .iter()
        .any(|job| job.tenant_id != first.tenant_id || backfill_object_id(job) != object)
    {
        return Err(QueueError::Conflict(
            "backfill windows must share one tenant and object".into(),
        ));
    }
    let mut windows: Vec<String> = jobs
        .iter()
        .map(|job| {
            format!(
                "{}|{}",
                job.logical_window_start.to_rfc3339(),
                job.logical_window_end.to_rfc3339()
            )
        })
        .collect();
    windows.sort();
    let window_text = windows.join(",");
    Ok(scoped_digest(&[
        "backfill",
        first.tenant_id.as_str(),
        first.canonical_site.as_str(),
        first.provider_instance_id.as_str(),
        first.device_id.as_str(),
        first.model_revision.as_str(),
        window_text.as_str(),
    ]))
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
