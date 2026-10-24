//! Expected point/time coverage for one half-open UTC window.
//!
//! A provider page or a checkpoint is not coverage. Each expected point is
//! `present`, `no_sample_expected`, `no_sample_received`, `late_arrival`,
//! `source_unavailable`, `genuine_gap`, or `expectation_unspecified`.
//! Commit is allowed only when every point is accounted for by a sample, an
//! explicit late arrival, or a cadence/COV rule that expected nothing.

use chrono::{DateTime, TimeZone, Utc};
use serde::Serialize;

pub const PRESENT: &str = "present";
pub const NO_SAMPLE_EXPECTED: &str = "no_sample_expected";
pub const NO_SAMPLE_RECEIVED: &str = "no_sample_received";
pub const LATE_ARRIVAL: &str = "late_arrival";
pub const SOURCE_UNAVAILABLE: &str = "source_unavailable";
pub const GENUINE_GAP: &str = "genuine_gap";
pub const EXPECTATION_UNSPECIFIED: &str = "expectation_unspecified";
pub const COMPLETE: &str = "complete";
pub const INCOMPLETE: &str = "incomplete";

pub const MAX_POINTS: usize = 2_000;
pub const MAX_TIMESTAMPS: usize = 50_000;

const ACCOUNTED: &[&str] = &[PRESENT, NO_SAMPLE_EXPECTED, LATE_ARRIVAL];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Expectation {
    /// No cadence and no COV rule. Samples can be `present`. An explicit empty
    /// series is not treated as either "no sample expected" or "no sample received".
    Unspecified,
    /// Phase-aligned to the Unix epoch. A slot is `t` with `start <= t < end`
    /// and `t` divisible by `cadence_secs`.
    Interval { cadence_secs: i64 },
    /// An empty answered series is `no_sample_expected` unless a heartbeat
    /// falls inside the window.
    Cov {
        heartbeat_secs: Option<i64>,
        last_sample_at: Option<DateTime<Utc>>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PointExpectation {
    pub point_id: String,
    pub expectation: Expectation,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PointObservation {
    pub point_id: String,
    /// The provider included this series. An empty `timestamps` list is an
    /// answer. `returned == false` means the point was omitted.
    pub returned: bool,
    pub timestamps: Vec<DateTime<Utc>>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PointCoverage {
    pub point_id: String,
    pub disposition: String,
    pub expected_slots: u32,
    pub observed_slots: u32,
    pub late_slots: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CoverageReport {
    pub summary: String,
    pub points: Vec<PointCoverage>,
    pub duplicate_timestamps: u32,
    pub out_of_window: u32,
}

impl CoverageReport {
    #[cfg(test)]
    pub fn accounted(point_id: &str) -> Self {
        Self {
            summary: COMPLETE.to_string(),
            points: vec![PointCoverage {
                point_id: point_id.to_string(),
                disposition: PRESENT.to_string(),
                expected_slots: 1,
                observed_slots: 1,
                late_slots: 0,
            }],
            duplicate_timestamps: 0,
            out_of_window: 0,
        }
    }

    pub fn allows_commit(&self) -> bool {
        !self.points.is_empty()
            && self.summary == COMPLETE
            && self
                .points
                .iter()
                .all(|point| ACCOUNTED.contains(&point.disposition.as_str()))
    }

    /// Transport and omission can be retried. A gap, a missing expected
    /// sample, or an unspecified empty series stays partial so the window
    /// does not advance.
    pub fn retryable_source_failure(&self) -> bool {
        !self.allows_commit()
            && !self.points.is_empty()
            && self.points.iter().all(|point| {
                point.disposition == SOURCE_UNAVAILABLE
                    || ACCOUNTED.contains(&point.disposition.as_str())
            })
            && self
                .points
                .iter()
                .any(|point| point.disposition == SOURCE_UNAVAILABLE)
    }

    pub fn block_code(&self) -> String {
        const ORDER: &[&str] = &[
            SOURCE_UNAVAILABLE,
            GENUINE_GAP,
            NO_SAMPLE_RECEIVED,
            EXPECTATION_UNSPECIFIED,
        ];
        for code in ORDER {
            if self.points.iter().any(|point| point.disposition == *code) {
                return (*code).to_string();
            }
        }
        INCOMPLETE.to_string()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReconcileInput<'a> {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub expectations: &'a [PointExpectation],
    pub observations: &'a [PointObservation],
    pub prior: &'a [PointCoverage],
    /// The provider finished the page. A truncated page cannot prove a gap.
    pub response_complete: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CoverageError {
    InvalidWindow,
    PayloadBound,
}

impl std::fmt::Display for CoverageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidWindow => write!(f, "window must be half-open"),
            Self::PayloadBound => write!(f, "payload_bound"),
        }
    }
}

pub fn expectation_from_fields(
    mode: Option<&str>,
    cadence_secs: Option<u64>,
    heartbeat_secs: Option<u64>,
    last_sample_at: Option<DateTime<Utc>>,
) -> Expectation {
    match mode {
        Some("interval") => Expectation::Interval {
            cadence_secs: cadence_secs
                .and_then(|secs| i64::try_from(secs).ok())
                .unwrap_or(0),
        },
        Some("cov") => Expectation::Cov {
            heartbeat_secs: heartbeat_secs.and_then(|secs| i64::try_from(secs).ok()),
            last_sample_at,
        },
        _ => Expectation::Unspecified,
    }
}

pub fn reconcile(input: &ReconcileInput<'_>) -> Result<CoverageReport, CoverageError> {
    if input.end <= input.start {
        return Err(CoverageError::InvalidWindow);
    }
    if input.expectations.len() > MAX_POINTS {
        return Err(CoverageError::PayloadBound);
    }
    let timestamp_count: usize = input
        .observations
        .iter()
        .map(|obs| obs.timestamps.len())
        .sum();
    if timestamp_count > MAX_TIMESTAMPS {
        return Err(CoverageError::PayloadBound);
    }
    let mut duplicate_timestamps = 0u32;
    let mut out_of_window = 0u32;
    let mut points = Vec::with_capacity(input.expectations.len());
    for expected in input.expectations {
        let observation = input
            .observations
            .iter()
            .find(|obs| obs.point_id == expected.point_id);
        let (in_window, duplicates, outside) = match observation {
            Some(obs) => partition_timestamps(&obs.timestamps, input.start, input.end),
            None => (Vec::new(), 0, 0),
        };
        duplicate_timestamps = duplicate_timestamps.saturating_add(duplicates);
        out_of_window = out_of_window.saturating_add(outside);
        let returned = observation.is_some_and(|obs| obs.returned);
        let prior = input
            .prior
            .iter()
            .find(|row| row.point_id == expected.point_id);
        points.push(assess_point(
            expected,
            returned,
            &in_window,
            prior,
            input.start,
            input.end,
            input.response_complete,
        ));
    }
    let summary = if points.is_empty()
        || points
            .iter()
            .any(|point| !ACCOUNTED.contains(&point.disposition.as_str()))
    {
        INCOMPLETE
    } else {
        COMPLETE
    };
    Ok(CoverageReport {
        summary: summary.to_string(),
        points,
        duplicate_timestamps,
        out_of_window,
    })
}

fn partition_timestamps(
    timestamps: &[DateTime<Utc>],
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> (Vec<DateTime<Utc>>, u32, u32) {
    let mut in_window = Vec::new();
    let mut duplicates = 0u32;
    let mut outside = 0u32;
    for ts in timestamps {
        if *ts < start || *ts >= end {
            outside = outside.saturating_add(1);
            continue;
        }
        if in_window.contains(ts) {
            duplicates = duplicates.saturating_add(1);
            continue;
        }
        in_window.push(*ts);
    }
    (in_window, duplicates, outside)
}

fn assess_point(
    expected: &PointExpectation,
    returned: bool,
    in_window: &[DateTime<Utc>],
    prior: Option<&PointCoverage>,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    response_complete: bool,
) -> PointCoverage {
    if !returned {
        return row(expected, SOURCE_UNAVAILABLE, 0, 0, 0);
    }
    match &expected.expectation {
        Expectation::Unspecified => {
            if in_window.is_empty() {
                row(expected, EXPECTATION_UNSPECIFIED, 0, 0, 0)
            } else {
                row(expected, PRESENT, 0, u32_len(in_window.len()), 0)
            }
        }
        Expectation::Interval { cadence_secs } => assess_interval(
            expected,
            *cadence_secs,
            in_window,
            prior,
            start,
            end,
            response_complete,
        ),
        Expectation::Cov {
            heartbeat_secs,
            last_sample_at,
        } => assess_cov(
            expected,
            *heartbeat_secs,
            *last_sample_at,
            in_window,
            prior,
            start,
            end,
        ),
    }
}

fn assess_interval(
    expected: &PointExpectation,
    cadence_secs: i64,
    in_window: &[DateTime<Utc>],
    prior: Option<&PointCoverage>,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    response_complete: bool,
) -> PointCoverage {
    if cadence_secs <= 0 {
        return row(expected, EXPECTATION_UNSPECIFIED, 0, 0, 0);
    }
    let slots = interval_slots(start, end, cadence_secs);
    let expected_slots = u32_len(slots.len());
    let mut observed = 0usize;
    let mut late = 0usize;
    for slot in &slots {
        let slot_end = *slot + chrono::Duration::seconds(cadence_secs);
        let filled = in_window
            .iter()
            .any(|ts| *ts >= *slot && *ts < slot_end && *ts < end);
        if filled {
            observed += 1;
            if prior_was_missing(prior) {
                late += 1;
            }
        }
    }
    if slots.is_empty() {
        return if in_window.is_empty() {
            row(expected, NO_SAMPLE_EXPECTED, 0, 0, 0)
        } else {
            row(expected, PRESENT, 0, u32_len(in_window.len()), 0)
        };
    }
    if observed == slots.len() {
        let disposition = if late > 0 { LATE_ARRIVAL } else { PRESENT };
        return row(
            expected,
            disposition,
            expected_slots,
            u32_len(observed),
            u32_len(late),
        );
    }
    let disposition = if response_complete {
        GENUINE_GAP
    } else {
        NO_SAMPLE_RECEIVED
    };
    row(expected, disposition, expected_slots, u32_len(observed), 0)
}

fn assess_cov(
    expected: &PointExpectation,
    heartbeat_secs: Option<i64>,
    last_sample_at: Option<DateTime<Utc>>,
    in_window: &[DateTime<Utc>],
    prior: Option<&PointCoverage>,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> PointCoverage {
    if !in_window.is_empty() {
        let late = u32_len(if prior_was_missing(prior) {
            in_window.len()
        } else {
            0
        });
        let disposition = if late > 0 { LATE_ARRIVAL } else { PRESENT };
        return row(expected, disposition, 0, u32_len(in_window.len()), late);
    }
    if heartbeat_due(heartbeat_secs, last_sample_at, start, end) {
        return row(expected, NO_SAMPLE_RECEIVED, 1, 0, 0);
    }
    row(expected, NO_SAMPLE_EXPECTED, 0, 0, 0)
}

fn heartbeat_due(
    heartbeat_secs: Option<i64>,
    last_sample_at: Option<DateTime<Utc>>,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> bool {
    let (Some(heartbeat), Some(last)) = (heartbeat_secs, last_sample_at) else {
        return false;
    };
    if heartbeat <= 0 {
        return false;
    }
    let due = last + chrono::Duration::seconds(heartbeat);
    due >= start && due < end
}

fn prior_was_missing(prior: Option<&PointCoverage>) -> bool {
    matches!(
        prior.map(|row| row.disposition.as_str()),
        Some(GENUINE_GAP | NO_SAMPLE_RECEIVED)
    )
}

fn interval_slots(
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    cadence_secs: i64,
) -> Vec<DateTime<Utc>> {
    let mut slots = Vec::new();
    let start_secs = start.timestamp();
    let end_secs = end.timestamp();
    let remainder = start_secs.rem_euclid(cadence_secs);
    let mut cursor = if remainder == 0 {
        start_secs
    } else {
        start_secs + (cadence_secs - remainder)
    };
    let mut guard = 0u32;
    while cursor < end_secs && guard < 100_000 {
        if let Some(slot) = Utc.timestamp_opt(cursor, 0).single() {
            if slot >= start && slot < end {
                slots.push(slot);
            }
        }
        cursor = cursor.saturating_add(cadence_secs);
        guard = guard.saturating_add(1);
    }
    slots
}

fn row(
    expected: &PointExpectation,
    disposition: &str,
    expected_slots: u32,
    observed_slots: u32,
    late_slots: u32,
) -> PointCoverage {
    PointCoverage {
        point_id: expected.point_id.clone(),
        disposition: disposition.to_string(),
        expected_slots,
        observed_slots,
        late_slots,
    }
}

fn u32_len(len: usize) -> u32 {
    u32::try_from(len).unwrap_or(u32::MAX)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Replay {
    Insert,
    Unchanged,
    Conflict,
}

pub fn classify_replay(existing: Option<u64>, incoming: u64) -> Replay {
    match existing {
        None => Replay::Insert,
        Some(stored) if stored == incoming => Replay::Unchanged,
        Some(_) => Replay::Conflict,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(y: i32, m: u32, d: u32, h: u32, min: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, h, min, 0).unwrap()
    }

    fn interval(id: &str, cadence: i64) -> PointExpectation {
        PointExpectation {
            point_id: id.into(),
            expectation: Expectation::Interval {
                cadence_secs: cadence,
            },
        }
    }

    fn cov(id: &str, heartbeat: Option<i64>, last: Option<DateTime<Utc>>) -> PointExpectation {
        PointExpectation {
            point_id: id.into(),
            expectation: Expectation::Cov {
                heartbeat_secs: heartbeat,
                last_sample_at: last,
            },
        }
    }

    fn obs(id: &str, stamps: &[DateTime<Utc>]) -> PointObservation {
        PointObservation {
            point_id: id.into(),
            returned: true,
            timestamps: stamps.to_vec(),
        }
    }

    fn absent(id: &str) -> PointObservation {
        PointObservation {
            point_id: id.into(),
            returned: false,
            timestamps: Vec::new(),
        }
    }

    fn run(
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        expectations: &[PointExpectation],
        observations: &[PointObservation],
        prior: &[PointCoverage],
        complete: bool,
    ) -> CoverageReport {
        reconcile(&ReconcileInput {
            start,
            end,
            expectations,
            observations,
            prior,
            response_complete: complete,
        })
        .expect("reconcile")
    }

    #[test]
    fn half_open_end_is_excluded_and_start_is_kept() {
        let start = ts(2026, 10, 19, 12, 0);
        let end = ts(2026, 10, 19, 13, 0);
        let report = run(
            start,
            end,
            &[interval("p", 3600)],
            &[obs(
                "p",
                &[start, end, start - chrono::Duration::seconds(1)],
            )],
            &[],
            true,
        );
        assert!(report.allows_commit());
        assert_eq!(report.out_of_window, 2);
        assert_eq!(report.points[0].disposition, PRESENT);
        assert_eq!(report.points[0].observed_slots, 1);
    }

    #[test]
    fn duplicate_timestamps_do_not_erase_a_distinct_sample() {
        let start = ts(2026, 10, 19, 12, 0);
        let end = ts(2026, 10, 19, 13, 0);
        let first = start;
        let second = start + chrono::Duration::minutes(5);
        let report = run(
            start,
            end,
            &[interval("p", 300)],
            &[obs("p", &[first, first, second])],
            &[],
            true,
        );
        assert_eq!(report.duplicate_timestamps, 1);
        assert_eq!(report.points[0].observed_slots, 2);
        assert!(
            !report.allows_commit(),
            "ten of twelve slots are still missing"
        );
        assert_eq!(report.points[0].disposition, GENUINE_GAP);
        assert_eq!(report.points[0].expected_slots, 12);
    }

    #[test]
    fn cov_empty_is_not_a_received_gap_and_heartbeat_is() {
        let start = ts(2026, 10, 19, 12, 0);
        let end = ts(2026, 10, 19, 13, 0);
        let quiet = run(
            start,
            end,
            &[cov("damper", None, None)],
            &[obs("damper", &[])],
            &[],
            true,
        );
        assert!(quiet.allows_commit());
        assert_eq!(quiet.points[0].disposition, NO_SAMPLE_EXPECTED);

        let heartbeat = run(
            start,
            end,
            &[cov(
                "damper",
                Some(3600),
                Some(start - chrono::Duration::seconds(3600)),
            )],
            &[obs("damper", &[])],
            &[],
            true,
        );
        assert!(!heartbeat.allows_commit());
        assert_eq!(heartbeat.points[0].disposition, NO_SAMPLE_RECEIVED);

        let omitted = run(
            start,
            end,
            &[cov("damper", None, None)],
            &[absent("damper")],
            &[],
            true,
        );
        assert_eq!(omitted.points[0].disposition, SOURCE_UNAVAILABLE);
        assert!(omitted.retryable_source_failure());
    }

    #[test]
    fn unspecified_empty_is_neither_expected_nor_received() {
        let start = ts(2026, 10, 19, 12, 0);
        let end = ts(2026, 10, 19, 13, 0);
        let report = run(
            start,
            end,
            &[PointExpectation {
                point_id: "raw".into(),
                expectation: Expectation::Unspecified,
            }],
            &[obs("raw", &[])],
            &[],
            true,
        );
        assert_eq!(report.points[0].disposition, EXPECTATION_UNSPECIFIED);
        assert_ne!(report.points[0].disposition, NO_SAMPLE_EXPECTED);
        assert_ne!(report.points[0].disposition, NO_SAMPLE_RECEIVED);
        assert!(!report.allows_commit());
    }

    #[test]
    fn truncated_page_is_no_sample_received_and_complete_page_is_a_gap() {
        let start = ts(2026, 10, 19, 12, 0);
        let end = ts(2026, 10, 19, 12, 15);
        let truncated = run(
            start,
            end,
            &[interval("sat", 300)],
            &[obs("sat", &[start])],
            &[],
            false,
        );
        assert_eq!(truncated.points[0].disposition, NO_SAMPLE_RECEIVED);
        assert!(!truncated.allows_commit());
        let complete = run(
            start,
            end,
            &[interval("sat", 300)],
            &[obs("sat", &[start])],
            &[],
            true,
        );
        assert_eq!(complete.points[0].disposition, GENUINE_GAP);
        assert!(!complete.allows_commit());
    }

    #[test]
    fn late_arrival_fills_a_prior_gap_without_hiding_it() {
        let start = ts(2026, 10, 19, 12, 0);
        let end = ts(2026, 10, 19, 13, 0);
        let prior = PointCoverage {
            point_id: "sat".into(),
            disposition: GENUINE_GAP.to_string(),
            expected_slots: 1,
            observed_slots: 0,
            late_slots: 0,
        };
        let report = run(
            start,
            end,
            &[interval("sat", 3600)],
            &[obs("sat", &[start + chrono::Duration::minutes(10)])],
            &[prior],
            true,
        );
        assert!(report.allows_commit());
        assert_eq!(report.points[0].disposition, LATE_ARRIVAL);
        assert_eq!(report.points[0].late_slots, 1);
    }

    #[test]
    fn mixed_cadence_blocks_commit_when_one_interval_is_short() {
        let start = ts(2026, 10, 19, 12, 0);
        let end = ts(2026, 10, 19, 13, 0);
        let mut five_min = Vec::new();
        for step in 0..12 {
            five_min.push(start + chrono::Duration::seconds(step * 300));
        }
        five_min.remove(3);
        let report = run(
            start,
            end,
            &[
                interval("fast", 300),
                interval("hourly", 3600),
                cov("damper", None, None),
            ],
            &[
                obs("fast", &five_min),
                obs("hourly", &[start]),
                obs("damper", &[]),
            ],
            &[],
            true,
        );
        assert!(!report.allows_commit());
        assert_eq!(report.points[0].disposition, GENUINE_GAP);
        assert_eq!(report.points[0].expected_slots, 12);
        assert_eq!(report.points[0].observed_slots, 11);
        assert_eq!(report.points[1].disposition, PRESENT);
        assert_eq!(report.points[1].expected_slots, 1);
        assert_eq!(report.points[2].disposition, NO_SAMPLE_EXPECTED);
        assert_eq!(report.block_code(), GENUINE_GAP);
    }

    #[test]
    fn hourly_point_in_a_short_window_expects_nothing() {
        let start = ts(2026, 10, 19, 12, 5);
        let end = start + chrono::Duration::seconds(60);
        let report = run(
            start,
            end,
            &[interval("hourly", 3600)],
            &[obs("hourly", &[])],
            &[],
            true,
        );
        assert!(report.allows_commit());
        assert_eq!(report.points[0].disposition, NO_SAMPLE_EXPECTED);
        assert_eq!(report.points[0].expected_slots, 0);
    }

    #[test]
    fn dst_utc_windows_keep_four_fifteen_minute_slots() {
        // 2026-03-08 06:00Z is 01:00 EST; 07:00Z is 03:00 EDT. Local 02:00 is skipped.
        let spring_start = ts(2026, 3, 8, 6, 0);
        let spring_end = ts(2026, 3, 8, 7, 0);
        assert_eq!(
            (spring_end - spring_start).num_seconds(),
            3600,
            "spring-forward UTC hour stays 3600s"
        );
        let mut spring_samples = Vec::new();
        for step in 0..4 {
            spring_samples.push(spring_start + chrono::Duration::seconds(step * 900));
        }
        let spring = run(
            spring_start,
            spring_end,
            &[interval("zone", 900)],
            &[obs("zone", &spring_samples)],
            &[],
            true,
        );
        assert_eq!(spring.points[0].expected_slots, 4);
        assert!(spring.allows_commit());

        // 2026-11-01 05:00Z..06:00Z is the repeated local 01:00, still one UTC hour.
        let fall_start = ts(2026, 11, 1, 5, 0);
        let fall_end = ts(2026, 11, 1, 6, 0);
        assert_eq!((fall_end - fall_start).num_seconds(), 3600);
        let mut fall_samples = Vec::new();
        for step in 0..4 {
            fall_samples.push(fall_start + chrono::Duration::seconds(step * 900));
        }
        let fall = run(
            fall_start,
            fall_end,
            &[interval("zone", 900)],
            &[obs("zone", &fall_samples)],
            &[],
            true,
        );
        assert_eq!(fall.points[0].expected_slots, 4);
        assert!(fall.allows_commit());
        assert_ne!(spring_start, fall_start);
    }

    #[test]
    fn replay_keeps_the_first_value() {
        assert_eq!(classify_replay(None, 1), Replay::Insert);
        assert_eq!(classify_replay(Some(1), 1), Replay::Unchanged);
        assert_eq!(classify_replay(Some(1), 2), Replay::Conflict);
    }

    #[test]
    fn payload_and_inverted_window_fail() {
        let start = ts(2026, 10, 19, 12, 0);
        let expectations: Vec<_> = (0..=MAX_POINTS)
            .map(|idx| interval(&format!("p{idx}"), 3600))
            .collect();
        let err = reconcile(&ReconcileInput {
            start,
            end: start + chrono::Duration::hours(1),
            expectations: &expectations,
            observations: &[],
            prior: &[],
            response_complete: true,
        })
        .expect_err("bound");
        assert_eq!(err, CoverageError::PayloadBound);
        let err = reconcile(&ReconcileInput {
            start,
            end: start,
            expectations: &[interval("p", 3600)],
            observations: &[],
            prior: &[],
            response_complete: true,
        })
        .expect_err("window");
        assert_eq!(err, CoverageError::InvalidWindow);
    }
}
