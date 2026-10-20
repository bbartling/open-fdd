//! Completed-hour windows for portal history.
//!
//! Each modeled device is due for the last **completed** hour after a publication
//! delay. The job copies every source sample in that hour (and a short overlap).
//! It does not average the hour down to one value.
//!
//! NF `GET /api/v1/point/updates/data` returned HTTP 403 on the 2026-10-18 lab
//! key. This mode does not call that API and does not expand permissions.
//! Bounded reconciliation re-reads a few recent committed hours. That is not a
//! gapless update-log cursor. Hours outside source retention stay explicit gaps.

use chrono::{DateTime, Duration, Utc};
use sha2::{Digest, Sha256};

use super::map::HistorySeries;

/// Short status stored on provider health. Not a claim of gapless replication.
pub const UPDATE_LOG_STATUS: &str =
    "nf_update_log_http_403; history=GET /api/v1/point/data; bounded_reconcile; not_gapless";

pub const UPDATE_LOG_HTTP: u16 = 403;
const _: () = assert!(UPDATE_LOG_HTTP == 403);

#[derive(Debug, Clone)]
pub struct HourlyPolicy {
    pub publication_delay: Duration,
    pub overlap: Duration,
    pub bootstrap: Duration,
    pub retention: Duration,
    pub reconcile_hours: i64,
    pub max_claims_per_tick: usize,
    pub stagger_spread_secs: i64,
    pub lease: Duration,
    pub max_attempts: i32,
    pub points_per_shard: usize,
    pub retry_jitter_secs: i64,
}

impl Default for HourlyPolicy {
    fn default() -> Self {
        Self {
            publication_delay: Duration::seconds(300),
            overlap: Duration::seconds(300),
            bootstrap: Duration::seconds(24 * 3600),
            retention: Duration::seconds(7 * 24 * 3600),
            reconcile_hours: 2,
            max_claims_per_tick: 4,
            stagger_spread_secs: 300,
            lease: Duration::seconds(120),
            max_attempts: 8,
            points_per_shard: 50,
            retry_jitter_secs: 30,
        }
    }
}

impl HourlyPolicy {
    pub fn from_env() -> Self {
        let mut policy = Self::default();
        if let Some(v) = env_i64("OPENFDD_HOURLY_DELAY_SECS") {
            policy.publication_delay = Duration::seconds(v.clamp(0, 3600));
        }
        if let Some(v) = env_i64("OPENFDD_HOURLY_OVERLAP_SECS") {
            policy.overlap = Duration::seconds(v.clamp(0, 3600));
        }
        if let Some(v) = env_i64("OPENFDD_HOURLY_BOOTSTRAP_HOURS") {
            policy.bootstrap = Duration::seconds(v.clamp(1, 24 * 30) * 3600);
        }
        if let Some(v) = env_i64("OPENFDD_HOURLY_RETENTION_HOURS") {
            policy.retention = Duration::seconds(v.clamp(1, 24 * 90) * 3600);
        }
        if let Some(v) = env_i64("OPENFDD_HOURLY_RECONCILE_HOURS") {
            policy.reconcile_hours = v.clamp(0, 48);
        }
        if let Some(v) = env_i64("OPENFDD_HOURLY_MAX_CLAIMS") {
            policy.max_claims_per_tick = usize::try_from(v.clamp(1, 64)).unwrap_or(4);
        }
        if let Some(v) = env_i64("OPENFDD_HOURLY_STAGGER_SECS") {
            policy.stagger_spread_secs = v.clamp(0, 3600);
        }
        if let Some(v) = env_i64("OPENFDD_HOURLY_POINTS_PER_SHARD") {
            policy.points_per_shard = usize::try_from(v.clamp(1, 500)).unwrap_or(50);
        }
        policy
    }
}

fn env_i64(key: &str) -> Option<i64> {
    std::env::var(key).ok().and_then(|v| v.trim().parse().ok())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LogicalWindow {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

pub fn floor_hour(ts: DateTime<Utc>) -> DateTime<Utc> {
    let secs = ts.timestamp();
    let floored = secs - secs.rem_euclid(3600);
    DateTime::from_timestamp(floored, 0).unwrap_or(ts)
}

/// End of the last completed hour. At 10:05 with a 5-minute delay this is 10:00,
/// so the logical window is `[09:00, 10:00)`.
pub fn completed_hour_end(now: DateTime<Utc>, publication_delay: Duration) -> DateTime<Utc> {
    floor_hour(now - publication_delay)
}

pub fn catch_up_windows(
    contiguous_end: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
    policy: &HourlyPolicy,
) -> (Vec<LogicalWindow>, Vec<LogicalWindow>) {
    let horizon = completed_hour_end(now, policy.publication_delay);
    let retention_edge = now - policy.retention;
    let bootstrap_start = floor_hour(horizon - policy.bootstrap);
    let mut cursor = match contiguous_end {
        Some(end) => floor_hour(end),
        None => {
            let mut start = bootstrap_start;
            let retention_floor = floor_hour(retention_edge);
            if start < retention_floor {
                start = retention_floor;
            }
            start
        }
    };
    let mut due = Vec::new();
    let mut unrecoverable = Vec::new();
    if horizon <= cursor {
        return (due, unrecoverable);
    }
    let mut guard = 0;
    while cursor < horizon && guard < 24 * 120 {
        let end = cursor + Duration::seconds(3600);
        let window = LogicalWindow { start: cursor, end };
        if end <= retention_edge {
            unrecoverable.push(window);
        } else {
            due.push(window);
        }
        cursor = end;
        guard += 1;
    }
    (due, unrecoverable)
}

/// Oldest backlog plus the newest due hour when the claim budget is tight.
pub fn fair_windows(due: &[LogicalWindow], limit: usize) -> Vec<LogicalWindow> {
    if limit == 0 || due.is_empty() {
        return Vec::new();
    }
    if due.len() <= limit {
        return due.to_vec();
    }
    if limit == 1 {
        return vec![due[due.len() - 1]];
    }
    let mut out = due.iter().take(limit - 1).copied().collect::<Vec<_>>();
    let live = due[due.len() - 1];
    if !out.contains(&live) {
        out.push(live);
    }
    out
}

pub fn reconciliation_windows(contiguous_end: DateTime<Utc>, hours: i64) -> Vec<LogicalWindow> {
    let mut out = Vec::new();
    let mut end = contiguous_end;
    let mut left = hours.max(0);
    while left > 0 {
        let start = end - Duration::seconds(3600);
        out.push(LogicalWindow { start, end });
        end = start;
        left -= 1;
    }
    out
}

pub fn stagger_secs(device_id: &str, spread_secs: i64) -> i64 {
    if spread_secs <= 0 {
        return 0;
    }
    let mut hasher = Sha256::new();
    hasher.update(device_id.as_bytes());
    let digest = hasher.finalize();
    let n = u64::from_be_bytes(digest[..8].try_into().unwrap_or([0; 8]));
    i64::try_from(n % u64::try_from(spread_secs).unwrap_or(1)).unwrap_or(0)
}

pub fn retry_delay_secs(attempt: i32) -> i64 {
    let shift = u32::try_from(attempt.saturating_sub(1).clamp(0, 5)).unwrap_or(0);
    let base = 30i64.saturating_mul(1_i64 << shift);
    base.min(900)
}

pub fn model_revision(device_id: &str, points: &[(String, String, Option<String>)]) -> String {
    let mut rows = points.to_vec();
    rows.sort_by(|a, b| a.0.cmp(&b.0));
    let mut hasher = Sha256::new();
    hasher.update(device_id.as_bytes());
    for (point_id, role, equip_type) in rows {
        hasher.update([0xff]);
        hasher.update(point_id.as_bytes());
        hasher.update([0xfe]);
        hasher.update(role.as_bytes());
        hasher.update([0xfd]);
        hasher.update(equip_type.unwrap_or_default().as_bytes());
    }
    hex::encode(hasher.finalize())
}

pub fn shard_ids(ids: &[String], cap: usize) -> Vec<Vec<String>> {
    let cap = cap.max(1);
    if ids.is_empty() {
        return Vec::new();
    }
    ids.chunks(cap).map(|chunk| chunk.to_vec()).collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoverageOutcome {
    Samples,
    NoSourceData,
    Partial,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PageAssessment {
    pub outcome: CoverageOutcome,
    pub fetched: usize,
    pub accepted: Vec<super::map::RawProviderPoint>,
    pub overlap_count: usize,
    pub rejected: usize,
    pub missing: Vec<String>,
}

/// Keep every in-range sample. Do not average, and do not invent values for holes.
pub fn assess_page(
    requested: &[String],
    page: &[HistorySeries],
    logical: LogicalWindow,
    overlap: Duration,
) -> PageAssessment {
    let fetch_start = logical.start - overlap;
    let mut missing = Vec::new();
    let mut accepted = Vec::new();
    let mut overlap_count = 0usize;
    let mut rejected = 0usize;
    let mut fetched = 0usize;
    for id in requested {
        let Some(series) = page.iter().find(|s| s.provider_point_id == *id) else {
            missing.push(id.clone());
            continue;
        };
        for sample in &series.samples {
            fetched += 1;
            if sample.ts >= fetch_start && sample.ts < logical.end {
                if sample.ts < logical.start {
                    overlap_count += 1;
                }
                accepted.push(sample.clone());
            } else {
                rejected += 1;
            }
        }
    }
    for series in page {
        if !requested.iter().any(|id| id == &series.provider_point_id) {
            fetched += series.samples.len();
            rejected += series.samples.len();
        }
    }
    let outcome = if !missing.is_empty() {
        CoverageOutcome::Partial
    } else if accepted.is_empty() {
        CoverageOutcome::NoSourceData
    } else {
        CoverageOutcome::Samples
    };
    PageAssessment {
        outcome,
        fetched,
        accepted,
        overlap_count,
        rejected,
        missing,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FetchError {
    Auth,
    Throttled { retry_after_secs: Option<u64> },
    Contract,
    Transport,
    Persistence,
    Unmapped,
    PartialSeries,
    NotImplemented,
}

impl FetchError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Auth => "auth",
            Self::Throttled { .. } => "throttled",
            Self::Contract => "contract",
            Self::Transport => "transport",
            Self::Persistence => "persistence",
            Self::Unmapped => "unmapped",
            Self::PartialSeries => "partial_series",
            Self::NotImplemented => "not_implemented",
        }
    }

    pub fn immediate_permanent(&self) -> bool {
        matches!(self, Self::Auth | Self::NotImplemented)
    }

    pub fn retry_after_secs(&self) -> Option<u64> {
        match self {
            Self::Throttled { retry_after_secs } => *retry_after_secs,
            _ => None,
        }
    }
}

pub fn classify_history_status(status: u16, retry_after_secs: Option<u64>) -> FetchError {
    match status {
        401 | 403 => FetchError::Auth,
        429 => FetchError::Throttled { retry_after_secs },
        400 | 404 | 422 => FetchError::Contract,
        _ => FetchError::Transport,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::map::RawProviderPoint;
    use chrono::TimeZone;

    fn ts(hour: u32, min: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 19, hour, min, 0).unwrap()
    }

    fn policy() -> HourlyPolicy {
        HourlyPolicy {
            stagger_spread_secs: 0,
            retry_jitter_secs: 0,
            ..HourlyPolicy::default()
        }
    }

    fn sample(id: &str, at: DateTime<Utc>, val: f64) -> RawProviderPoint {
        RawProviderPoint {
            provider_point_id: id.into(),
            display_name: None,
            ts: at,
            val,
            unit: Some("degF".into()),
            source_quality: None,
            attrs: serde_json::Map::new(),
        }
    }

    #[test]
    fn completed_hour_waits_for_publication_delay() {
        let delay = Duration::seconds(300);
        let at_1005 = ts(10, 5);
        assert_eq!(completed_hour_end(at_1005, delay), ts(10, 0));
        let (due, gaps) = catch_up_windows(Some(ts(9, 0)), at_1005, &policy());
        assert!(gaps.is_empty());
        assert_eq!(due.len(), 1);
        assert_eq!(due[0].start, ts(9, 0));
        assert_eq!(due[0].end, ts(10, 0));

        let at_1004 = ts(10, 4);
        assert_eq!(completed_hour_end(at_1004, delay), ts(9, 0));
        let (early, _) = catch_up_windows(Some(ts(8, 0)), at_1004, &policy());
        assert_eq!(early.len(), 1);
        assert_eq!(early[0].start, ts(8, 0));
        assert_eq!(early[0].end, ts(9, 0));
    }

    #[test]
    fn six_hour_outage_enqueues_each_completed_hour() {
        let now = ts(13, 5);
        let (due, gaps) = catch_up_windows(Some(ts(8, 0)), now, &policy());
        assert!(gaps.is_empty());
        assert_eq!(due.len(), 5);
        assert_eq!(due[0].start, ts(8, 0));
        assert_eq!(due[0].end, ts(9, 0));
        assert_eq!(due[4].start, ts(12, 0));
        assert_eq!(due[4].end, ts(13, 0));
        assert!(due
            .iter()
            .all(|w| w.end - w.start == Duration::seconds(3600)));
    }

    #[test]
    fn fair_claim_keeps_the_live_hour() {
        let now = ts(13, 5);
        let (due, _) = catch_up_windows(Some(ts(8, 0)), now, &policy());
        let picked = fair_windows(&due, 2);
        assert_eq!(picked.len(), 2);
        assert_eq!(picked[0].start, ts(8, 0));
        assert_eq!(picked[1].start, ts(12, 0));
        assert_eq!(fair_windows(&due, 1)[0].start, ts(12, 0));
    }

    #[test]
    fn retention_marks_old_hours_unrecoverable() {
        let mut policy = policy();
        policy.retention = Duration::seconds(3 * 3600);
        let now = ts(13, 5);
        let (due, gaps) = catch_up_windows(Some(ts(8, 0)), now, &policy);
        assert!(gaps.iter().any(|w| w.start == ts(8, 0)));
        assert!(due.iter().all(|w| w.end > now - policy.retention));
        assert!(!due.is_empty());
    }

    #[test]
    fn hour_keeps_every_sample() {
        let window = LogicalWindow {
            start: ts(9, 0),
            end: ts(10, 0),
        };
        let mut samples = Vec::new();
        for minute in 0..60 {
            samples.push(sample(
                "p1",
                ts(9, 0) + Duration::seconds(i64::from(minute) * 60),
                f64::from(minute),
            ));
        }
        let page = vec![HistorySeries {
            provider_point_id: "p1".into(),
            samples,
        }];
        let assessed = assess_page(&["p1".into()], &page, window, Duration::seconds(300));
        assert_eq!(assessed.outcome, CoverageOutcome::Samples);
        assert_eq!(assessed.accepted.len(), 60);
        assert!((assessed.accepted[0].val - 0.0).abs() < f64::EPSILON);
        assert!((assessed.accepted[59].val - 59.0).abs() < f64::EPSILON);
        let mean = assessed.accepted.iter().map(|s| s.val).sum::<f64>() / 60.0;
        assert!(assessed.accepted.iter().any(|s| (s.val - mean).abs() > 1.0));
    }

    #[test]
    fn overlap_is_kept_and_half_open_end_is_excluded() {
        let window = LogicalWindow {
            start: ts(9, 0),
            end: ts(10, 0),
        };
        let page = vec![HistorySeries {
            provider_point_id: "p1".into(),
            samples: vec![
                sample("p1", ts(8, 50), 1.0),
                sample("p1", ts(8, 56), 2.0),
                sample("p1", ts(9, 0), 3.0),
                sample("p1", ts(10, 0), 4.0),
            ],
        }];
        let assessed = assess_page(&["p1".into()], &page, window, Duration::seconds(300));
        assert_eq!(assessed.accepted.len(), 2);
        assert_eq!(assessed.overlap_count, 1);
        assert_eq!(assessed.rejected, 2);
        assert_eq!(assessed.outcome, CoverageOutcome::Samples);
    }

    #[test]
    fn missing_series_is_partial_and_explicit_empty_is_no_source_data() {
        let window = LogicalWindow {
            start: ts(9, 0),
            end: ts(10, 0),
        };
        let partial = assess_page(
            &["p1".into(), "p2".into()],
            &[HistorySeries {
                provider_point_id: "p1".into(),
                samples: vec![sample("p1", ts(9, 1), 1.0)],
            }],
            window,
            Duration::seconds(0),
        );
        assert_eq!(partial.outcome, CoverageOutcome::Partial);
        assert_eq!(partial.missing, vec!["p2".to_string()]);
        assert_eq!(partial.accepted.len(), 1);

        let empty = assess_page(
            &["p1".into()],
            &[HistorySeries {
                provider_point_id: "p1".into(),
                samples: Vec::new(),
            }],
            window,
            Duration::seconds(0),
        );
        assert_eq!(empty.outcome, CoverageOutcome::NoSourceData);
        assert!(empty.accepted.is_empty());
    }

    #[test]
    fn absent_page_is_not_no_source_data() {
        let window = LogicalWindow {
            start: ts(9, 0),
            end: ts(10, 0),
        };
        let assessed = assess_page(&["p1".into()], &[], window, Duration::seconds(0));
        assert_eq!(assessed.outcome, CoverageOutcome::Partial);
    }

    #[test]
    fn stagger_is_stable_and_bounded() {
        assert_eq!(stagger_secs("device-a", 0), 0);
        let a = stagger_secs("device-a", 300);
        assert_eq!(a, stagger_secs("device-a", 300));
        assert!((0..300).contains(&a));
    }

    #[test]
    fn model_revision_changes_when_bindings_change() {
        let a = model_revision("dev", &[("p1".into(), "oa_t".into(), None)]);
        let b = model_revision(
            "dev",
            &[
                ("p1".into(), "oa_t".into(), None),
                ("p2".into(), "sat".into(), None),
            ],
        );
        assert_ne!(a, b);
        let flipped = model_revision(
            "dev",
            &[
                ("p2".into(), "sat".into(), None),
                ("p1".into(), "oa_t".into(), None),
            ],
        );
        assert_eq!(b, flipped);
    }

    #[test]
    fn history_status_does_not_collapse_to_success() {
        assert!(matches!(
            classify_history_status(500, None),
            FetchError::Transport
        ));
        assert!(matches!(
            classify_history_status(401, None),
            FetchError::Auth
        ));
        assert!(matches!(
            classify_history_status(UPDATE_LOG_HTTP, None),
            FetchError::Auth
        ));
        assert!(matches!(
            classify_history_status(429, Some(12)),
            FetchError::Throttled {
                retry_after_secs: Some(12)
            }
        ));
        assert_eq!(retry_delay_secs(1), 30);
        assert_eq!(retry_delay_secs(2), 60);
        assert_eq!(retry_delay_secs(20), 900);
    }
}
