//! Deterministic continuous-AFDD scheduler planning primitives.
//!
//! This module is intentionally runtime-neutral: Central owns timers, locking,
//! persistence, and execution, while this crate defines the restart-safe policy
//! for rolling windows, one-shot catch-up, checkpoints, and bounded backfill.

use anyhow::{bail, Context, Result};
use chrono::{DateTime, Duration, LocalResult, NaiveDate, NaiveDateTime, TimeZone, Utc};
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};

use crate::afdd::{parse_wall_clock_hhmm, parse_wall_clock_timezone};
use crate::{AfddConfig, AfddScheduleKind};

pub const AFDD_SCHEDULER_CHECKPOINT_PATH: &str = "state/afdd/scheduler-checkpoint.json";
pub const AFDD_SCHEDULER_RUNTIME_CONFIG_PATH: &str = "state/afdd/scheduler-runtime-config.json";

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
///
/// Interval mode is `last_completed_at + interval` (or `now` with no checkpoint).
/// Wall-clock mode is the next local `HH:MM` that has not already completed.
/// A missed local day stays one due instant — planning still emits one cycle.
pub fn next_due_at(
    checkpoint: Option<&AfddSchedulerCheckpoint>,
    now: DateTime<Utc>,
    config: &AfddConfig,
) -> Result<DateTime<Utc>> {
    config.validate()?;
    if config.schedule_kind == AfddScheduleKind::WallClock {
        return wall_clock_due(checkpoint, now, config);
    }
    let interval = Duration::minutes(i64::try_from(config.interval_minutes)?);
    Ok(match checkpoint {
        Some(checkpoint) => checkpoint.last_completed_at_utc + interval,
        None => now,
    })
}

fn wall_clock_due(
    checkpoint: Option<&AfddSchedulerCheckpoint>,
    now: DateTime<Utc>,
    config: &AfddConfig,
) -> Result<DateTime<Utc>> {
    let hhmm = parse_wall_clock_hhmm(config.wall_clock_hhmm.as_deref().unwrap_or(""))?;
    let tz = parse_wall_clock_timezone(config.wall_clock_timezone.as_deref().unwrap_or(""))?;
    let today = now.with_timezone(&tz).date_naive();
    let today_due = civil_slot_utc(today, hhmm, tz);
    let completed = checkpoint.map(|cp| cp.last_completed_at_utc);
    if completed.is_some_and(|done| done >= today_due) {
        let tomorrow = today
            .checked_add_signed(Duration::days(1))
            .context("wall-clock date overflow")?;
        return Ok(civil_slot_utc(tomorrow, hhmm, tz));
    }
    Ok(today_due)
}

/// Map a civil local time to UTC. DST gaps walk forward to the next valid
/// minute. Ambiguous fold times use the earlier offset so the slot fires once.
fn civil_slot_utc(date: NaiveDate, time: chrono::NaiveTime, tz: Tz) -> DateTime<Utc> {
    let start = date.and_time(time);
    let mut naive: NaiveDateTime = start;
    for _ in 0..180 {
        match tz.from_local_datetime(&naive) {
            LocalResult::Single(dt) => return dt.with_timezone(&Utc),
            LocalResult::Ambiguous(early, late) => {
                let chosen = if early <= late { early } else { late };
                return chosen.with_timezone(&Utc);
            }
            LocalResult::None => {
                naive += Duration::minutes(1);
            }
        }
    }
    start.and_utc()
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
    // Wall-clock with no checkpoint waits for the local slot. Interval with no
    // checkpoint uses `due == now`, so this does not delay the first interval run.
    if now < due {
        return Ok(None);
    }

    // Do not run again when telemetry has not advanced beyond the last
    // successfully analyzed watermark.
    if checkpoint.is_some_and(|cp| end_utc <= cp.analyzed_through_utc) {
        return Ok(None);
    }

    let lookback_seconds = i64::try_from(config.lookback_seconds()?)?;
    let start_utc = end_utc - Duration::seconds(lookback_seconds);
    // Daily wall-clock cadence is one local day. Downtime still yields one
    // lookback-sized window (`catch_up`), not one cycle per missed day.
    let cadence = match config.schedule_kind {
        AfddScheduleKind::WallClock => Duration::hours(24),
        AfddScheduleKind::Interval => Duration::minutes(i64::try_from(config.interval_minutes)?),
    };
    let catch_up = checkpoint.is_some_and(|cp| now >= cp.last_completed_at_utc + cadence * 2);

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

/// Explicit backfill plan with a chunk fan-out cap.
///
/// Callers reject missing bounds and epoch-to-now before this. The cap here
/// rejects a request that would launch dozens of registry passes.
pub fn plan_bounded_backfill(
    start_utc: DateTime<Utc>,
    end_utc: DateTime<Utc>,
    chunk_hours: u64,
) -> Result<Vec<AfddBackfillChunk>> {
    let chunks = plan_backfill_chunks(start_utc, end_utc, chunk_hours)?;
    if chunks.len() > crate::MAX_AFDD_BACKFILL_CHUNKS {
        bail!(
            "backfill would create {} chunks (max {}); raise chunk_hours or narrow the range",
            chunks.len(),
            crate::MAX_AFDD_BACKFILL_CHUNKS
        );
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
            ..AfddConfig::default()
        }
    }

    fn wall_config() -> AfddConfig {
        AfddConfig {
            mode: AfddMode::Continuous,
            interval_minutes: 1440,
            lookback_value: 24,
            lookback_unit: AfddLookbackUnit::Hours,
            schedule_kind: crate::AfddScheduleKind::WallClock,
            wall_clock_hhmm: Some("05:00".into()),
            wall_clock_timezone: Some("America/Chicago".into()),
        }
    }

    fn utc(y: i32, m: u32, d: u32, h: u32, min: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, h, min, 0).unwrap()
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
            plan_continuous_cycle(
                Some(&checkpoint),
                ts(8) + Duration::minutes(30),
                Some(ts(9)),
                &config(),
            )
            .unwrap(),
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

    #[test]
    fn bounded_backfill_rejects_chunk_fanout() {
        let start = utc(2026, 1, 1, 0, 0);
        let end =
            start + Duration::hours(i64::try_from(crate::MAX_AFDD_BACKFILL_CHUNKS).unwrap() + 1);
        let err = plan_bounded_backfill(start, end, 1).unwrap_err();
        assert!(err.to_string().contains("chunks"));
        let ok = plan_bounded_backfill(start, start + Duration::hours(48), 24).unwrap();
        assert_eq!(ok.len(), 2);
    }

    #[test]
    fn wall_clock_waits_until_0500_chicago_summer_and_winter() {
        let summer_before = utc(2026, 9, 29, 9, 59);
        assert_eq!(
            plan_continuous_cycle(None, summer_before, Some(summer_before), &wall_config())
                .unwrap(),
            None
        );
        let summer_due = utc(2026, 9, 29, 10, 0);
        let summer = plan_continuous_cycle(None, summer_due, Some(summer_due), &wall_config())
            .unwrap()
            .unwrap();
        assert_eq!(summer.scheduled_for_utc, summer_due);
        assert_eq!(summer.end_utc, summer_due);
        assert_eq!(summer.start_utc, summer_due - Duration::hours(24));
        assert!(!summer.catch_up);

        let winter_before = utc(2026, 1, 15, 10, 59);
        assert_eq!(
            plan_continuous_cycle(None, winter_before, Some(winter_before), &wall_config())
                .unwrap(),
            None
        );
        let winter_due = utc(2026, 1, 15, 11, 0);
        let winter = plan_continuous_cycle(None, winter_due, Some(winter_due), &wall_config())
            .unwrap()
            .unwrap();
        assert_eq!(winter.scheduled_for_utc, winter_due);
        assert_eq!(winter.start_utc, winter_due - Duration::hours(24));
    }

    #[test]
    fn wall_clock_downtime_is_one_lookback_window() {
        let checkpoint = AfddSchedulerCheckpoint {
            last_completed_at_utc: utc(2026, 9, 25, 10, 30),
            analyzed_through_utc: utc(2026, 9, 25, 10, 0),
        };
        let now = utc(2026, 9, 29, 16, 0);
        let watermark = utc(2026, 9, 29, 15, 50);
        let cycle = plan_continuous_cycle(Some(&checkpoint), now, Some(watermark), &wall_config())
            .unwrap()
            .unwrap();
        assert!(cycle.catch_up);
        assert_eq!(cycle.scheduled_for_utc, utc(2026, 9, 29, 10, 0));
        assert_eq!(cycle.end_utc, watermark);
        assert_eq!(cycle.start_utc, watermark - Duration::hours(24));
        assert_ne!(
            cycle.end_utc - cycle.start_utc,
            now - checkpoint.last_completed_at_utc
        );
    }

    #[test]
    fn wall_clock_completed_today_waits_until_tomorrow() {
        let checkpoint = AfddSchedulerCheckpoint {
            last_completed_at_utc: utc(2026, 9, 29, 10, 5),
            analyzed_through_utc: utc(2026, 9, 29, 10, 0),
        };
        let now = utc(2026, 9, 29, 18, 0);
        assert_eq!(
            plan_continuous_cycle(
                Some(&checkpoint),
                now,
                Some(utc(2026, 9, 29, 17, 0)),
                &wall_config(),
            )
            .unwrap(),
            None
        );
        assert_eq!(
            next_due_at(Some(&checkpoint), now, &wall_config()).unwrap(),
            utc(2026, 9, 30, 10, 0)
        );
    }

    #[test]
    fn wall_clock_spring_forward_gap_does_not_panic() {
        // 2026-03-08 02:30 America/Chicago does not exist. 03:00 CDT is 08:00 UTC.
        let before_gap = utc(2026, 3, 8, 7, 30);
        let mut early = wall_config();
        early.wall_clock_hhmm = Some("02:30".into());
        assert_eq!(
            plan_continuous_cycle(None, before_gap, Some(before_gap), &early).unwrap(),
            None
        );
        let due = next_due_at(None, before_gap, &early).unwrap();
        assert_eq!(due, utc(2026, 3, 8, 8, 0));
        let cycle = plan_continuous_cycle(None, due, Some(due), &early)
            .unwrap()
            .unwrap();
        assert_eq!(cycle.scheduled_for_utc, utc(2026, 3, 8, 8, 0));
        assert_eq!(cycle.start_utc, due - Duration::hours(24));
    }

    #[test]
    fn wall_clock_fall_back_runs_once() {
        // 2026-11-01 01:30 America/Chicago happens twice. The earlier offset is 06:30 UTC.
        let mut slot = wall_config();
        slot.wall_clock_hhmm = Some("01:30".into());
        let first = utc(2026, 11, 1, 6, 30);
        let cycle = plan_continuous_cycle(None, first, Some(first), &slot)
            .unwrap()
            .unwrap();
        assert_eq!(cycle.scheduled_for_utc, first);
        let checkpoint = AfddSchedulerCheckpoint {
            last_completed_at_utc: utc(2026, 11, 1, 6, 31),
            analyzed_through_utc: first,
        };
        let second_civil = utc(2026, 11, 1, 7, 30);
        assert_eq!(
            plan_continuous_cycle(Some(&checkpoint), second_civil, Some(second_civil), &slot)
                .unwrap(),
            None
        );
    }
}
