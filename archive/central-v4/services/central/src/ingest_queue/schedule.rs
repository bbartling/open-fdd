//! Bounded completed-window planning. This is not the N5 checkpoint walk.
//!
//! Each tick enqueues the catch-up span (`catchup_hours` × 3600 seconds) split
//! into `window_secs` slices (default 3600, clamp 60..=3600). A short window
//! still plans that whole span: a sliding batch would drop the oldest slices
//! as `now` moves. Enqueue is idempotent. Portal logins are cached on the NF
//! driver so catch-up does not authenticate once per window. Older retention
//! recovery is a backfill.
//!
//! A site can instead use the daily policy: after local midnight plus the
//! publication delay, the previous local day (23, 24, or 25 hours across DST)
//! is planned as aligned UTC slices. A daily window that is not fully
//! accounted for is retried at the next daily run while the source still
//! retains it, and becomes a persisted `retention_exceeded` gap after that.

use chrono::{DateTime, Duration, LocalResult, NaiveDate, NaiveTime, TimeZone, Utc};
use chrono_tz::Tz;

use crate::providers::hourly::floor_to_window;

use super::model::{gap_recoverable, FinishOutcome, NewJob, JOB_SHARD_LIVE, MAX_CATCHUP_HOURS};

/// Upper bound on whole local days planned per scheduler tick. Older days are
/// a backfill.
pub const MAX_DAILY_CATCHUP_DAYS: u32 = 7;

/// Per-site ingest schedule. `Periodic` is the default.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum IngestSchedule {
    #[default]
    Periodic,
    Daily {
        tz: Tz,
    },
}

impl IngestSchedule {
    /// `mode` is `periodic` (default) or `daily`. Daily needs an IANA zone.
    pub fn parse(mode: Option<&str>, timezone: Option<&str>) -> Result<Self, String> {
        let mode = mode
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .unwrap_or("periodic")
            .to_ascii_lowercase();
        let timezone = timezone.map(str::trim).filter(|value| !value.is_empty());
        match mode.as_str() {
            "periodic" => match timezone {
                Some(_) => Err("schedule_timezone_unused".into()),
                None => Ok(Self::Periodic),
            },
            "daily" => {
                let raw = timezone.ok_or_else(|| "schedule_timezone_required".to_string())?;
                let tz = raw
                    .parse::<Tz>()
                    .map_err(|_| "schedule_timezone".to_string())?;
                Ok(Self::Daily { tz })
            }
            _ => Err("schedule_mode".into()),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScheduleError {
    /// No representable local midnight within six hours of the calendar day.
    NoLocalMidnight,
}

impl std::fmt::Display for ScheduleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NoLocalMidnight => f.write_str("no_local_midnight"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct ScheduleDevice {
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
    pub estimated_cost: u32,
    pub point_ids: Vec<String>,
}

pub fn due_windows(
    now: DateTime<Utc>,
    publication_delay: Duration,
    catchup_hours: u32,
    stagger_spread_secs: u64,
    window_secs: i64,
    devices: &[ScheduleDevice],
) -> Vec<NewJob> {
    let catchup = catchup_hours.clamp(1, MAX_CATCHUP_HOURS);
    let step = window_secs.clamp(60, 3600);
    let latest_end = floor_to_window(now - publication_delay, step);
    let windows = (i64::from(catchup) * 3600 / step).max(1);
    let mut jobs = Vec::new();
    for device in devices {
        let stagger = stagger_secs(&device.device_id, stagger_spread_secs);
        for age in 0..windows {
            let logical_window_end = latest_end - Duration::seconds(age * step);
            let logical_window_start = logical_window_end - Duration::seconds(step);
            let not_before = if age == 0 {
                logical_window_end + publication_delay + Duration::seconds(stagger as i64)
            } else {
                now
            };
            jobs.push(NewJob {
                tenant_id: device.tenant_id.clone(),
                canonical_site: device.canonical_site.clone(),
                provider_instance_id: device.provider_instance_id.clone(),
                device_id: device.device_id.clone(),
                model_revision: device.model_revision.clone(),
                logical_window_start,
                logical_window_end,
                shard: JOB_SHARD_LIVE.to_string(),
                not_before,
                estimated_cost: device.estimated_cost.max(1),
                requested_points_digest: Some(super::model::points_digest(&device.point_ids)),
            });
        }
    }
    jobs
}

/// First instant of a local calendar day. A skipped midnight moves forward in
/// 15-minute steps; an ambiguous one takes the earlier instant.
pub fn local_midnight(tz: Tz, date: NaiveDate) -> Result<DateTime<Utc>, ScheduleError> {
    let mut local = date.and_time(NaiveTime::MIN);
    for _ in 0..=24 {
        match tz.from_local_datetime(&local) {
            LocalResult::Single(at) | LocalResult::Ambiguous(at, _) => {
                return Ok(at.with_timezone(&Utc));
            }
            LocalResult::None => local += Duration::minutes(15),
        }
    }
    Err(ScheduleError::NoLocalMidnight)
}

/// End of the newest local day whose publication delay has passed.
fn latest_daily_end(
    now: DateTime<Utc>,
    tz: Tz,
    publication_delay: Duration,
) -> Result<(NaiveDate, DateTime<Utc>), ScheduleError> {
    let today = now.with_timezone(&tz).date_naive();
    let midnight = local_midnight(tz, today)?;
    if now >= midnight + publication_delay {
        return Ok((today, midnight));
    }
    let yesterday = today.pred_opt().ok_or(ScheduleError::NoLocalMidnight)?;
    Ok((yesterday, local_midnight(tz, yesterday)?))
}

/// The next daily run strictly after `now`: a local midnight plus the delay.
pub fn next_daily_run(
    now: DateTime<Utc>,
    tz: Tz,
    publication_delay: Duration,
) -> Result<DateTime<Utc>, ScheduleError> {
    let (end_date, _) = latest_daily_end(now, tz, publication_delay)?;
    let next = end_date.succ_opt().ok_or(ScheduleError::NoLocalMidnight)?;
    Ok(local_midnight(tz, next)? + publication_delay)
}

/// Newest instant the schedule has planned through at `now`, and the next run
/// strictly after `now`. Periodic runs ignore the per-device stagger.
pub fn planned_horizon(
    schedule: IngestSchedule,
    now: DateTime<Utc>,
    publication_delay: Duration,
    window_secs: i64,
) -> Result<(DateTime<Utc>, DateTime<Utc>), ScheduleError> {
    match schedule {
        IngestSchedule::Periodic => {
            let step = window_secs.clamp(60, 3600);
            let latest_end = floor_to_window(now - publication_delay, step);
            Ok((
                latest_end,
                latest_end + Duration::seconds(step) + publication_delay,
            ))
        }
        IngestSchedule::Daily { tz } => {
            let (_, latest_end) = latest_daily_end(now, tz, publication_delay)?;
            Ok((latest_end, next_daily_run(now, tz, publication_delay)?))
        }
    }
}

/// Largest slice length that is at most `window_secs` and keeps both day
/// boundaries on the slice grid. One minute always qualifies for whole-minute
/// offsets.
fn daily_step(start: DateTime<Utc>, end: DateTime<Utc>, window_secs: i64) -> i64 {
    let wanted = window_secs.clamp(60, 3600);
    [wanted, 1800, 900, 300, 60]
        .into_iter()
        .filter(|step| *step <= wanted)
        .find(|step| start.timestamp() % step == 0 && end.timestamp() % step == 0)
        .unwrap_or(60)
}

/// Plan the newest `catchup_days` complete local days for daily-policy devices.
/// Slices are aligned UTC windows of at most `window_secs`; together they
/// cover exactly `[local midnight, next local midnight)`.
pub fn daily_windows(
    now: DateTime<Utc>,
    tz: Tz,
    publication_delay: Duration,
    catchup_days: u32,
    stagger_spread_secs: u64,
    window_secs: i64,
    devices: &[ScheduleDevice],
) -> Result<Vec<NewJob>, ScheduleError> {
    let (end_date, latest_end) = latest_daily_end(now, tz, publication_delay)?;
    let mut days = Vec::new();
    let mut day_end_date = end_date;
    let mut day_end = latest_end;
    for _ in 0..catchup_days.clamp(1, MAX_DAILY_CATCHUP_DAYS) {
        let start_date = day_end_date
            .pred_opt()
            .ok_or(ScheduleError::NoLocalMidnight)?;
        let day_start = local_midnight(tz, start_date)?;
        days.push((day_start, day_end));
        day_end_date = start_date;
        day_end = day_start;
    }
    let mut jobs = Vec::new();
    for device in devices {
        let stagger = stagger_secs(&device.device_id, stagger_spread_secs);
        for (age, (day_start, day_end)) in days.iter().enumerate() {
            let step = daily_step(*day_start, *day_end, window_secs);
            let not_before = if age == 0 {
                latest_end + publication_delay + Duration::seconds(stagger as i64)
            } else {
                now
            };
            let mut slice_start = *day_start;
            while slice_start < *day_end {
                let slice_end = slice_start + Duration::seconds(step);
                jobs.push(NewJob {
                    tenant_id: device.tenant_id.clone(),
                    canonical_site: device.canonical_site.clone(),
                    provider_instance_id: device.provider_instance_id.clone(),
                    device_id: device.device_id.clone(),
                    model_revision: device.model_revision.clone(),
                    logical_window_start: slice_start,
                    logical_window_end: slice_end,
                    shard: JOB_SHARD_LIVE.to_string(),
                    not_before,
                    estimated_cost: device.estimated_cost.max(1),
                    requested_points_digest: Some(super::model::points_digest(&device.point_ids)),
                });
                slice_start = slice_end;
            }
        }
    }
    Ok(jobs)
}

/// Daily-policy outcome rules. A recoverable partial window, or a source retry,
/// waits for the next daily run while the source still retains the window.
/// Past `retention` it becomes a persisted `retention_exceeded` gap. Periodic
/// sites and committed or permanent outcomes pass through unchanged.
pub fn apply_daily_policy(
    outcome: FinishOutcome,
    schedule: IngestSchedule,
    window_start: DateTime<Utc>,
    now: DateTime<Utc>,
    publication_delay: Duration,
    retention: Duration,
) -> FinishOutcome {
    let IngestSchedule::Daily { tz } = schedule else {
        return outcome;
    };
    let code = match &outcome {
        FinishOutcome::Partial { code, .. } if gap_recoverable(Some(code.as_str())) => code.clone(),
        FinishOutcome::Retry { code, .. } => code.clone(),
        FinishOutcome::Committed { .. }
        | FinishOutcome::Partial { .. }
        | FinishOutcome::Permanent { .. } => return outcome,
    };
    let next_run = match next_daily_run(now, tz, publication_delay) {
        Ok(next_run) => next_run,
        Err(err) => {
            return FinishOutcome::Permanent {
                code: err.to_string(),
            };
        }
    };
    if window_start < next_run - retention {
        return FinishOutcome::Permanent {
            code: "retention_exceeded".into(),
        };
    }
    match outcome {
        FinishOutcome::Retry { not_before, .. } if not_before < next_run => {
            FinishOutcome::Retry { code, not_before }
        }
        _ => FinishOutcome::Retry {
            code,
            not_before: next_run,
        },
    }
}

fn stagger_secs(device_id: &str, spread: u64) -> u64 {
    if spread == 0 {
        return 0;
    }
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in device_id.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash % spread
}

#[cfg(test)]
mod tests {
    use super::*;

    fn device(id: &str) -> ScheduleDevice {
        ScheduleDevice {
            tenant_id: "t".into(),
            canonical_site: "site".into(),
            provider_instance_id: "nf:site".into(),
            device_id: id.into(),
            model_revision: "rev".into(),
            estimated_cost: 3,
            point_ids: vec!["p".into()],
        }
    }

    #[test]
    fn resume_enqueues_missed_completed_hours() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:05:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let jobs = due_windows(now, Duration::minutes(5), 5, 0, 3600, &[device("ahu")]);
        let windows: Vec<_> = jobs
            .iter()
            .map(|job| {
                (
                    job.logical_window_start.to_rfc3339(),
                    job.logical_window_end.to_rfc3339(),
                )
            })
            .collect();
        assert_eq!(
            windows,
            vec![
                (
                    "2026-10-19T12:00:00+00:00".into(),
                    "2026-10-19T13:00:00+00:00".into()
                ),
                (
                    "2026-10-19T11:00:00+00:00".into(),
                    "2026-10-19T12:00:00+00:00".into()
                ),
                (
                    "2026-10-19T10:00:00+00:00".into(),
                    "2026-10-19T11:00:00+00:00".into()
                ),
                (
                    "2026-10-19T09:00:00+00:00".into(),
                    "2026-10-19T10:00:00+00:00".into()
                ),
                (
                    "2026-10-19T08:00:00+00:00".into(),
                    "2026-10-19T09:00:00+00:00".into()
                ),
            ]
        );
    }

    #[test]
    fn devices_stagger_the_newest_window_only() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:05:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let jobs = due_windows(
            now,
            Duration::minutes(5),
            2,
            300,
            3600,
            &[device("ahu-a"), device("ahu-b")],
        );
        let a = jobs.iter().find(|job| job.device_id == "ahu-a").unwrap();
        let b = jobs.iter().find(|job| job.device_id == "ahu-b").unwrap();
        assert_ne!(a.not_before, b.not_before);
        assert!(jobs
            .iter()
            .filter(|job| job.logical_window_start
                == DateTime::parse_from_rfc3339("2026-10-19T11:00:00Z")
                    .unwrap()
                    .with_timezone(&Utc))
            .all(|job| job.not_before == now));
    }

    #[test]
    fn sixty_second_windows_cover_the_catchup_span() {
        let now = DateTime::parse_from_rfc3339("2026-10-19T13:05:30Z")
            .unwrap()
            .with_timezone(&Utc);
        let jobs = due_windows(now, Duration::seconds(0), 1, 0, 60, &[device("ahu")]);
        assert_eq!(jobs.len(), 60);
        let newest_end = DateTime::parse_from_rfc3339("2026-10-19T13:05:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert_eq!(jobs[0].logical_window_end, newest_end);
        assert_eq!(
            jobs[0].logical_window_start,
            newest_end - Duration::seconds(60)
        );
        let oldest = jobs.last().expect("catchup span");
        assert_eq!(
            oldest.logical_window_start,
            DateTime::parse_from_rfc3339("2026-10-19T12:05:00Z")
                .unwrap()
                .with_timezone(&Utc)
        );
        assert!(jobs.iter().all(|job| {
            job.logical_window_end - job.logical_window_start == Duration::seconds(60)
        }));
    }

    #[test]
    fn utc_windows_stay_one_hour_across_dst_transitions() {
        let spring = DateTime::parse_from_rfc3339("2026-03-08T07:10:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let fall = DateTime::parse_from_rfc3339("2026-11-01T06:10:00Z")
            .unwrap()
            .with_timezone(&Utc);
        for now in [spring, fall] {
            let jobs = due_windows(now, Duration::minutes(5), 2, 0, 3600, &[device("ahu")]);
            assert!(jobs.iter().all(|job| {
                job.logical_window_end - job.logical_window_start == Duration::seconds(3600)
                    && job.logical_window_start < job.logical_window_end
            }));
            assert!(jobs.iter().any(|job| job.requested_points_digest.is_some()));
        }
    }

    fn at(raw: &str) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339(raw)
            .unwrap()
            .with_timezone(&Utc)
    }

    fn chicago() -> Tz {
        "America/Chicago".parse().unwrap()
    }

    fn day_span(jobs: &[NewJob], device: &str) -> (DateTime<Utc>, DateTime<Utc>, i64) {
        let mut mine: Vec<_> = jobs.iter().filter(|job| job.device_id == device).collect();
        mine.sort_by_key(|job| job.logical_window_start);
        for pair in mine.windows(2) {
            assert_eq!(pair[0].logical_window_end, pair[1].logical_window_start);
        }
        assert!(mine
            .iter()
            .all(|job| super::super::model::is_aligned_window(
                job.logical_window_start,
                job.logical_window_end
            )));
        let start = mine.first().unwrap().logical_window_start;
        let end = mine.last().unwrap().logical_window_end;
        (start, end, (end - start).num_hours())
    }

    #[test]
    fn schedule_policy_parses_and_rejects() {
        assert_eq!(
            IngestSchedule::parse(None, None).unwrap(),
            IngestSchedule::Periodic
        );
        assert_eq!(
            IngestSchedule::parse(Some("daily"), Some("America/Chicago")).unwrap(),
            IngestSchedule::Daily { tz: chicago() }
        );
        assert_eq!(
            IngestSchedule::parse(Some("daily"), None).unwrap_err(),
            "schedule_timezone_required"
        );
        assert_eq!(
            IngestSchedule::parse(Some("daily"), Some("Mars/Base")).unwrap_err(),
            "schedule_timezone"
        );
        assert_eq!(
            IngestSchedule::parse(Some("hourly-ish"), None).unwrap_err(),
            "schedule_mode"
        );
        assert_eq!(
            IngestSchedule::parse(Some("periodic"), Some("UTC")).unwrap_err(),
            "schedule_timezone_unused"
        );
    }

    #[test]
    fn daily_plans_the_previous_local_day_across_dst() {
        let tz = chicago();
        let delay = Duration::minutes(5);
        let cases = [
            ("2026-10-20T05:06:00Z", "2026-10-19T05:00:00Z", 24),
            ("2026-03-09T05:06:00Z", "2026-03-08T06:00:00Z", 23),
            ("2026-11-02T06:06:00Z", "2026-11-01T05:00:00Z", 25),
        ];
        for (now, start, hours) in cases {
            let jobs = daily_windows(at(now), tz, delay, 1, 0, 3600, &[device("ahu")]).unwrap();
            let (got_start, got_end, got_hours) = day_span(&jobs, "ahu");
            assert_eq!(got_start, at(start), "{now}");
            assert_eq!(got_hours, hours, "{now}");
            assert_eq!(jobs.len() as i64, hours);
            assert!(got_end <= at(now) - delay);
            assert!(jobs.iter().all(|job| job.not_before == got_end + delay));
        }
    }

    #[test]
    fn daily_waits_for_the_publication_delay() {
        let tz = chicago();
        let before = daily_windows(
            at("2026-10-20T05:02:00Z"),
            tz,
            Duration::minutes(5),
            1,
            0,
            3600,
            &[device("ahu")],
        )
        .unwrap();
        let (start, end, _) = day_span(&before, "ahu");
        assert_eq!(start, at("2026-10-18T05:00:00Z"));
        assert_eq!(end, at("2026-10-19T05:00:00Z"));
        assert_eq!(
            next_daily_run(at("2026-10-20T05:02:00Z"), tz, Duration::minutes(5)).unwrap(),
            at("2026-10-20T05:05:00Z")
        );
        assert_eq!(
            next_daily_run(at("2026-10-20T05:06:00Z"), tz, Duration::minutes(5)).unwrap(),
            at("2026-10-21T05:05:00Z")
        );
    }

    #[test]
    fn planned_horizon_names_the_planned_end_and_the_next_run() {
        let delay = Duration::minutes(5);
        assert_eq!(
            planned_horizon(
                IngestSchedule::Periodic,
                at("2026-10-20T13:04:00Z"),
                delay,
                3600
            )
            .unwrap(),
            (at("2026-10-20T12:00:00Z"), at("2026-10-20T13:05:00Z"))
        );
        assert_eq!(
            planned_horizon(
                IngestSchedule::Periodic,
                at("2026-10-20T13:06:00Z"),
                delay,
                3600
            )
            .unwrap(),
            (at("2026-10-20T13:00:00Z"), at("2026-10-20T14:05:00Z"))
        );
        let daily = IngestSchedule::Daily {
            tz: "America/Chicago".parse().unwrap(),
        };
        assert_eq!(
            planned_horizon(daily, at("2026-10-20T05:02:00Z"), delay, 3600).unwrap(),
            (at("2026-10-19T05:00:00Z"), at("2026-10-20T05:05:00Z"))
        );
        assert_eq!(
            planned_horizon(daily, at("2026-10-20T05:06:00Z"), delay, 3600).unwrap(),
            (at("2026-10-20T05:00:00Z"), at("2026-10-21T05:05:00Z"))
        );
    }

    #[test]
    fn daily_catchup_days_are_contiguous_and_bounded() {
        let jobs = daily_windows(
            at("2026-10-20T05:06:00Z"),
            chicago(),
            Duration::minutes(5),
            99,
            0,
            3600,
            &[device("ahu")],
        )
        .unwrap();
        let (start, end, hours) = day_span(&jobs, "ahu");
        assert_eq!(end, at("2026-10-20T05:00:00Z"));
        assert_eq!(hours, i64::from(MAX_DAILY_CATCHUP_DAYS) * 24);
        assert_eq!(start, at("2026-10-13T05:00:00Z"));
    }

    #[test]
    fn half_hour_zone_uses_aligned_half_hour_slices() {
        let kolkata: Tz = "Asia/Kolkata".parse().unwrap();
        let jobs = daily_windows(
            at("2026-10-19T18:40:00Z"),
            kolkata,
            Duration::minutes(5),
            1,
            0,
            3600,
            &[device("ahu")],
        )
        .unwrap();
        let (start, _, hours) = day_span(&jobs, "ahu");
        assert_eq!(start, at("2026-10-18T18:30:00Z"));
        assert_eq!(hours, 24);
        assert_eq!(jobs.len(), 48);
    }

    fn partial(code: &str) -> FinishOutcome {
        FinishOutcome::Partial {
            counts: super::super::model::JobCounts::default(),
            code: code.into(),
            coverage: super::super::coverage::CoverageReport::accounted("p"),
        }
    }

    #[test]
    fn daily_policy_defers_recoverable_windows_until_retention() {
        let tz = chicago();
        let now = at("2026-10-20T05:30:00Z");
        let delay = Duration::minutes(5);
        let retention = Duration::days(7);
        let next = at("2026-10-21T05:05:00Z");
        let recent = at("2026-10-19T10:00:00Z");
        let old = at("2026-10-14T04:00:00Z");
        let daily = IngestSchedule::Daily { tz };
        match apply_daily_policy(partial("genuine_gap"), daily, recent, now, delay, retention) {
            FinishOutcome::Retry { code, not_before } => {
                assert_eq!(code, "genuine_gap");
                assert_eq!(not_before, next);
            }
            other => panic!("{other:?}"),
        }
        match apply_daily_policy(partial("genuine_gap"), daily, old, now, delay, retention) {
            FinishOutcome::Permanent { code } => assert_eq!(code, "retention_exceeded"),
            other => panic!("{other:?}"),
        }
        let soon = now + Duration::seconds(60);
        let retry = FinishOutcome::Retry {
            code: "timeout".into(),
            not_before: soon,
        };
        match apply_daily_policy(retry, daily, recent, now, delay, retention) {
            FinishOutcome::Retry { not_before, .. } => assert_eq!(not_before, soon),
            other => panic!("{other:?}"),
        }
        match apply_daily_policy(
            partial("unrecoverable"),
            daily,
            recent,
            now,
            delay,
            retention,
        ) {
            FinishOutcome::Partial { code, .. } => assert_eq!(code, "unrecoverable"),
            other => panic!("{other:?}"),
        }
        match apply_daily_policy(
            partial("genuine_gap"),
            IngestSchedule::Periodic,
            recent,
            now,
            delay,
            retention,
        ) {
            FinishOutcome::Partial { code, .. } => assert_eq!(code, "genuine_gap"),
            other => panic!("{other:?}"),
        }
    }
}
