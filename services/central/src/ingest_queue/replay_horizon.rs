//! Retention for the `ingest_applied_sample` replay ledger.
//!
//! The ledger keeps the first value written for each point and timestamp so a
//! replay is counted as unchanged or a conflict. Rows older than the retention
//! are deleted per tenant and site, and the cut is stored as `pruned_before`.
//! A retry or backfill whose window starts before `pruned_before` is refused
//! with `replay_horizon_exceeded`, because the ledger can no longer tell a
//! replay from a first write there. The cut never passes the start of a
//! queued, leased, or retry-wait job for the same site.

use chrono::{DateTime, Duration, Utc};

pub const REPLAY_HORIZON_EXCEEDED: &str = "replay_horizon_exceeded";
pub const RETENTION_ENV: &str = "OPENFDD_INGEST_APPLIED_SAMPLE_RETENTION_HOURS";
/// Rows deleted per site per prune pass.
pub const PRUNE_BATCH: i64 = 50_000;
/// Margin kept beyond the longest automatic replay (source retention or
/// daily catch-up).
const MIN_MARGIN_HOURS: i64 = 48;
const DEFAULT_MARGIN_HOURS: i64 = 7 * 24;
const MAX_RETENTION_HOURS: i64 = 400 * 24;

/// Longest window age the planner may still schedule on its own.
fn automatic_replay_hours(source_retention: Duration, daily_catchup_days: u32) -> i64 {
    let source = source_retention.num_hours();
    let daily = i64::from(daily_catchup_days)
        .saturating_add(1)
        .saturating_mul(24);
    source.max(daily)
}

/// Reads the retention. Unset uses the automatic replay span plus a week. A
/// set value must be whole hours, at least the automatic span plus 48 h, and
/// at most 400 days. Anything else is an error and is not adjusted.
pub fn parse_retention(
    raw: Option<&str>,
    source_retention: Duration,
    daily_catchup_days: u32,
) -> Result<Duration, String> {
    let floor = automatic_replay_hours(source_retention, daily_catchup_days);
    let Some(raw) = raw.map(str::trim).filter(|value| !value.is_empty()) else {
        return Ok(Duration::hours(floor.saturating_add(DEFAULT_MARGIN_HOURS)));
    };
    let hours: i64 = raw
        .parse()
        .map_err(|_| format!("{RETENTION_ENV} must be whole hours"))?;
    let min = floor.saturating_add(MIN_MARGIN_HOURS);
    if hours < min || hours > MAX_RETENTION_HOURS {
        return Err(format!(
            "{RETENTION_ENV} must be between {min} and {MAX_RETENTION_HOURS} hours"
        ));
    }
    Ok(Duration::hours(hours))
}

/// The prune cut: `now - retention`, but never past a live job's start.
pub fn prune_cutoff(
    now: DateTime<Utc>,
    retention: Duration,
    oldest_live_start: Option<DateTime<Utc>>,
) -> DateTime<Utc> {
    let edge = now - retention;
    match oldest_live_start {
        Some(start) if start < edge => start,
        _ => edge,
    }
}

/// True when a replay of a window starting at `start` is refused.
pub fn replay_refused(start: DateTime<Utc>, pruned_before: Option<DateTime<Utc>>) -> bool {
    pruned_before.is_some_and(|cut| start < cut)
}

pub fn refusal_message(start: DateTime<Utc>, pruned_before: DateTime<Utc>) -> String {
    format!(
        "{REPLAY_HORIZON_EXCEEDED}: window starting {} is before the applied-sample replay horizon {}",
        start.to_rfc3339(),
        pruned_before.to_rfc3339()
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PruneReport {
    pub deleted: u64,
    pub pruned_before: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn at(h: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 20, h, 0, 0)
            .single()
            .expect("valid test instant")
    }

    #[test]
    fn retention_defaults_past_the_automatic_replay_span_and_rejects_short_values() {
        let source = Duration::hours(7 * 24);
        assert_eq!(
            parse_retention(None, source, 2),
            Ok(Duration::hours(14 * 24))
        );
        assert_eq!(
            parse_retention(Some(" "), source, 2),
            Ok(Duration::hours(14 * 24))
        );
        assert_eq!(
            parse_retention(Some("216"), source, 2),
            Ok(Duration::hours(216))
        );
        assert!(parse_retention(Some("215"), source, 2).is_err());
        assert!(parse_retention(Some("0"), source, 2).is_err());
        assert!(parse_retention(Some("-5"), source, 2).is_err());
        assert!(parse_retention(Some("1.5"), source, 2).is_err());
        assert!(parse_retention(Some("9601"), source, 2).is_err());
        // A long source retention moves the floor; the value is not raised to meet it.
        let long = Duration::hours(90 * 24);
        assert!(parse_retention(Some("336"), long, 2).is_err());
        assert_eq!(parse_retention(None, long, 2), Ok(Duration::hours(97 * 24)));
        // Seven catch-up days with a 1 h source retention still needs eight days plus margin.
        assert!(parse_retention(Some("200"), Duration::hours(1), 7).is_err());
        assert_eq!(
            parse_retention(Some("240"), Duration::hours(1), 7),
            Ok(Duration::hours(240))
        );
    }

    #[test]
    fn cutoff_never_passes_a_live_job() {
        let now = at(12);
        let retention = Duration::hours(6);
        assert_eq!(prune_cutoff(now, retention, None), at(6));
        assert_eq!(prune_cutoff(now, retention, Some(at(3))), at(3));
        assert_eq!(prune_cutoff(now, retention, Some(at(9))), at(6));
    }

    #[test]
    fn replay_before_the_horizon_is_refused() {
        assert!(!replay_refused(at(1), None));
        assert!(replay_refused(at(1), Some(at(2))));
        assert!(!replay_refused(at(2), Some(at(2))));
        assert!(refusal_message(at(1), at(2)).starts_with(REPLAY_HORIZON_EXCEEDED));
    }
}
