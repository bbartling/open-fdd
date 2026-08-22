//! Deterministic continuous-AFDD scheduler planning primitives.
//!
//! This module is intentionally runtime-neutral: Central owns timers, locking,
//! persistence, and execution, while this crate defines the restart-safe policy
//! for rolling windows, one-shot catch-up, checkpoints, and bounded backfill.

use anyhow::{bail, Result};
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

use crate::AfddConfig;

pub const AFDD_SCHEDULER_CHECKPOINT_PATH: &str = "state/afdd/scheduler-checkpoint.json";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AfddSchedulerCheckpoint {
    pub last_completed_at_utc: DateTime<Utc>,
    pub analyzed_through_utc: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AfddCycleWindow {
    pub start_utc: DateTime<Utc>,
    pub end_utc: DateTime<Utc>,
    pub scheduled_for_utc: DateTime<Utc>,
    pub catch_up: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AfddBackfillChunk {
    pub start_utc: DateTime<Utc>,
    pub end_utc: DateTime<Utc>,
}

/// Return the next due time from the last successful scheduler checkpoint.
pub fn next_due_at(
    checkpoint: Option<&AfddSchedulerCheckpoint>,
    now: DateTime<Utc>,
    config: &AfddConfig,
) -> Result<DateTime<Utc>> {
    config.validate()?;
    let interval = Duration::minutes(i64::try_from(config.interval_minutes)?);
    Ok(match checkpoint {
        Some(checkpoint) => checkpoint.last_completed_at_utc + interval,
        None => now,
    })
}

/// Plan at most one continuous cycle.
///
/// The rolling end is the latest successfully persisted eligible telemetry,
/// never wall-clock time. If the process was down for multiple intervals, this
/// returns one catch-up cycle rather than replaying every missed timer tick.
pub fn plan_continuous_cycle(
    checkpoint: Option<&AfddSchedulerCheckpoint>,
    now: DateTime<Utc>,
    latest_persisted_telemetry: Option<DateTime<Utc>>,
    config: &AfddConfig,
) -> Result<Option<AfddCycleWindow>> {
    config.validate()?;
    let Some(end_utc) = latest_persisted_telemetry else {
        return Ok(None);
    };

    let due = next_due_at(checkpoint, now, config)?;
    if checkpoint.is_some() && now < due {
        return Ok(None);
    }

    // Do not run again when telemetry has not advanced beyond the last
    // successfully analyzed watermark.
    if checkpoint.is_some_and(|cp| end_utc <= cp.analyzed_through_utc) {
        return Ok(None);
    }

    let lookback_seconds = i64::try_from(config.lookback_seconds()?)?;
    let start_utc = end_utc - Duration::seconds(lookback_seconds);
    let interval = Duration::minutes(i64::try_from(config.interval_minutes)?);
    let catch_up = checkpoint.is_some_and(|cp| now >= cp.last_completed_at_utc + interval * 2);

    Ok(Some(AfddCycleWindow {
        start_utc,
        end_utc,
        scheduled_for_utc: due,
        catch_up,
    }))
}

/// Split an explicit historical backfill range into bounded chunks.
///
/// Backfill is deliberately separate from recurring continuous scheduling so a
/// large retained history range cannot accidentally turn into a full rescan on
/// every scheduler tick.
pub fn plan_backfill_chunks(
    start_utc: DateTime<Utc>,
    end_utc: DateTime<Utc>,
    chunk_hours: u64,
) -> Result<Vec<AfddBackfillChunk>> {
    if end_utc <= start_utc {
        bail!("AFDD backfill end must be after start");
    }
    if chunk_hours == 0 {
        bail!("AFDD backfill chunk_hours must be greater than zero");
    }
    let chunk = Duration::hours(i64::try_from(chunk_hours)?);
    let mut cursor = start_utc;
    let mut chunks = Vec::new();
    while cursor < end_utc {
        let next = (cursor + chunk).min(end_utc);
        chunks.push(AfddBackfillChunk {
            start_utc: cursor,
            end_utc: next,
        });
        cursor = next;
    }
    Ok(chunks)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{AfddLookbackUnit, AfddMode};
    use chrono::TimeZone;

    fn ts(hour: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 8, 22, hour, 0, 0).unwrap()
    }

    fn config() -> AfddConfig {
        AfddConfig {
            mode: AfddMode::Continuous,
            interval_minutes: 60,
            lookback_value: 24,
            lookback_unit: AfddLookbackUnit::Hours,
        }
    }

    #[test]
    fn no_telemetry_means_no_cycle() {
        assert_eq!(
            plan_continuous_cycle(None, ts(9), None, &config()).unwrap(),
            None
        );
    }

    #[test]
    fn first_cycle_ends_at_persisted_telemetry_and_overlaps_by_lookback() {
        let window = plan_continuous_cycle(None, ts(9), Some(ts(8)), &config())
            .unwrap()
            .unwrap();
        assert_eq!(window.end_utc, ts(8));
        assert_eq!(window.start_utc, ts(8) - Duration::hours(24));
        assert!(!window.catch_up);
    }

    #[test]
    fn not_due_does_not_run() {
        let checkpoint = AfddSchedulerCheckpoint {
            last_completed_at_utc: ts(8),
            analyzed_through_utc: ts(8),
        };
        assert_eq!(
            plan_continuous_cycle(Some(&checkpoint), ts(8) + Duration::minutes(30), Some(ts(9)), &config()).unwrap(),
            None
        );
    }

    #[test]
    fn restart_after_many_ticks_creates_one_catch_up_cycle() {
        let checkpoint = AfddSchedulerCheckpoint {
            last_completed_at_utc: ts(3),
            analyzed_through_utc: ts(3),
        };
        let cycle = plan_continuous_cycle(Some(&checkpoint), ts(9), Some(ts(8)), &config())
            .unwrap()
            .unwrap();
        assert!(cycle.catch_up);
        assert_eq!(cycle.scheduled_for_utc, ts(4));
        assert_eq!(cycle.end_utc, ts(8));
    }

    #[test]
    fn unchanged_telemetry_watermark_does_not_repeat_cycle() {
        let checkpoint = AfddSchedulerCheckpoint {
            last_completed_at_utc: ts(7),
            analyzed_through_utc: ts(8),
        };
        assert_eq!(
            plan_continuous_cycle(Some(&checkpoint), ts(9), Some(ts(8)), &config()).unwrap(),
            None
        );
    }

    #[test]
    fn backfill_is_bounded_and_covers_range_exactly() {
        let chunks = plan_backfill_chunks(ts(0), ts(8), 3).unwrap();
        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].start_utc, ts(0));
        assert_eq!(chunks[0].end_utc, ts(3));
        assert_eq!(chunks[2].start_utc, ts(6));
        assert_eq!(chunks[2].end_utc, ts(8));
    }
}
