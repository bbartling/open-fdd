//! Database-first gap-only backfill planning (#1423 part b).
//!
//! Given stored hourly windows from Timescale, a provider data start, binding
//! creation, and the operator request, plans only missing ranges merged up to
//! the driver `max_history_span`.

use chrono::{DateTime, Duration, Utc};
use serde::Serialize;

use crate::providers::hourly::floor_to_window;
use crate::providers::http_policy::MAX_HISTORY_WINDOW;

use super::model::is_hour_start;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct WindowSpan {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GapPlanCounts {
    pub planned: u32,
    pub skipped_stored: u32,
    pub not_expected: u32,
    /// Hourly windows missing before range merge.
    pub missing_hours: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GapPlanResult {
    pub planned: Vec<WindowSpan>,
    pub skipped_stored: Vec<WindowSpan>,
    pub not_expected: Vec<WindowSpan>,
    pub counts: GapPlanCounts,
    pub expected_start: DateTime<Utc>,
    pub last_stored_ts: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GapPlanInput<'a> {
    /// Hour-aligned walk bound (outer fetch/planner range start).
    pub fetch_start: DateTime<Utc>,
    /// Hour-aligned walk bound (publication-aligned end).
    pub fetch_end: DateTime<Utc>,
    /// Semantic first instant provider data is expected (may include minutes/seconds).
    pub first_expected: DateTime<Utc>,
    pub provider_data_start: Option<DateTime<Utc>>,
    pub binding_created_at: DateTime<Utc>,
    pub stored_hour_starts: &'a [DateTime<Utc>],
    pub last_stored_ts: Option<DateTime<Utc>>,
    pub force: bool,
    pub max_span: Duration,
}

pub fn floor_to_hour(ts: DateTime<Utc>) -> DateTime<Utc> {
    floor_to_window(ts, 3600)
}

/// Split operator hour bounds from the semantic first-expected instant (#1500).
pub fn gap_plan_bounds(
    requested_start: DateTime<Utc>,
    requested_end: DateTime<Utc>,
    provider_data_start: Option<DateTime<Utc>>,
    binding_created_at: DateTime<Utc>,
) -> Result<(DateTime<Utc>, DateTime<Utc>, DateTime<Utc>), String> {
    if requested_end <= requested_start {
        return Err("backfill end must be after start".into());
    }
    if !is_hour_start(requested_start) || !is_hour_start(requested_end) {
        return Err("backfill range must use exact UTC hour boundaries".into());
    }
    let first_expected = expected_start(requested_start, provider_data_start, binding_created_at);
    let fetch_start = requested_start.max(floor_to_hour(first_expected));
    Ok((first_expected, fetch_start, requested_end))
}

pub fn gap_plan_input<'a>(
    requested_start: DateTime<Utc>,
    requested_end: DateTime<Utc>,
    provider_data_start: Option<DateTime<Utc>>,
    binding_created_at: DateTime<Utc>,
    stored_hour_starts: &'a [DateTime<Utc>],
    last_stored_ts: Option<DateTime<Utc>],
    force: bool,
    max_span: Duration,
) -> Result<GapPlanInput<'a>, String> {
    let (first_expected, fetch_start, fetch_end) = gap_plan_bounds(
        requested_start,
        requested_end,
        provider_data_start,
        binding_created_at,
    )?;
    Ok(GapPlanInput {
        fetch_start,
        fetch_end,
        first_expected,
        provider_data_start,
        binding_created_at,
        stored_hour_starts,
        last_stored_ts,
        force,
        max_span,
    })
}

pub fn expected_start(
    requested_start: DateTime<Utc>,
    provider_data_start: Option<DateTime<Utc>>,
    binding_created_at: DateTime<Utc>,
) -> DateTime<Utc> {
    let mut start = requested_start;
    if binding_created_at > start {
        start = binding_created_at;
    }
    if let Some(provider) = provider_data_start {
        if provider > start {
            start = provider;
        }
    }
    start
}

/// Plan hourly windows in `[fetch_start, fetch_end)` against stored hours.
pub fn plan_gap_windows(input: GapPlanInput<'_>) -> Result<GapPlanResult, String> {
    if input.fetch_end <= input.fetch_start {
        return Err("backfill end must be after start".into());
    }
    if !is_hour_start(input.fetch_start) || !is_hour_start(input.fetch_end) {
        return Err("backfill range must use exact UTC hour boundaries".into());
    }
    let span_cap = input.max_span.num_seconds();
    if span_cap < 60 {
        return Err("max_history_span must be at least 60 seconds".into());
    }
    let stored: std::collections::BTreeSet<DateTime<Utc>> = input
        .stored_hour_starts
        .iter()
        .copied()
        .filter(|ts| is_hour_start(*ts))
        .collect();

    let mut skipped_stored = Vec::new();
    let mut not_expected = Vec::new();
    let mut missing_hours = Vec::new();

    let mut cursor = input.fetch_start;
    while cursor < input.fetch_end {
        let next = cursor + Duration::hours(1);
        if next <= input.first_expected {
            not_expected.push(WindowSpan {
                start: cursor,
                end: next,
            });
        } else if !input.force && stored.contains(&cursor) {
            skipped_stored.push(WindowSpan {
                start: cursor,
                end: next,
            });
        } else {
            missing_hours.push(cursor);
        }
        cursor = next;
    }

    let missing_hour_count =
        u32::try_from(missing_hours.len()).map_err(|_| "missing hour count overflow")?;
    let planned = merge_missing_hours(missing_hours, span_cap)?;
    let counts = GapPlanCounts {
        planned: u32::try_from(planned.len()).map_err(|_| "planned window count overflow")?,
        skipped_stored: u32::try_from(skipped_stored.len())
            .map_err(|_| "skipped_stored count overflow")?,
        not_expected: u32::try_from(not_expected.len())
            .map_err(|_| "not_expected count overflow")?,
        missing_hours: missing_hour_count,
    };
    Ok(GapPlanResult {
        planned,
        skipped_stored,
        not_expected,
        counts,
        expected_start: input.first_expected,
        last_stored_ts: input.last_stored_ts,
    })
}

fn merge_missing_hours(
    hours: Vec<DateTime<Utc>>,
    span_cap: i64,
) -> Result<Vec<WindowSpan>, String> {
    if hours.is_empty() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    let mut run_start = hours[0];
    let mut run_end = run_start + Duration::hours(1);
    for hour in hours.into_iter().skip(1) {
        let contiguous = hour == run_end;
        let extended = (hour + Duration::hours(1) - run_start).num_seconds();
        if contiguous && extended <= span_cap {
            run_end = hour + Duration::hours(1);
            continue;
        }
        push_aligned_span(&mut out, run_start, run_end, span_cap)?;
        run_start = hour;
        run_end = hour + Duration::hours(1);
    }
    push_aligned_span(&mut out, run_start, run_end, span_cap)?;
    Ok(out)
}

fn push_aligned_span(
    out: &mut Vec<WindowSpan>,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    span_cap: i64,
) -> Result<(), String> {
    let total_secs = (end - start).num_seconds();
    if total_secs <= 0 {
        return Ok(());
    }
    if total_secs > span_cap {
        return Err("internal merge produced a span above max_history_span".into());
    }
    let mut cursor = start;
    while cursor < end {
        let remaining = (end - cursor).num_seconds();
        let cap = remaining.min(span_cap);
        let mut try_secs = cap - cap.rem_euclid(3600);
        let mut chosen = 0_i64;
        while try_secs >= 3600 {
            let candidate_end = cursor + Duration::seconds(try_secs);
            if super::model::is_aligned_window(cursor, candidate_end) {
                chosen = try_secs;
                break;
            }
            try_secs -= 3600;
        }
        if chosen == 0 {
            return Err("internal merge produced a misaligned window".into());
        }
        out.push(WindowSpan {
            start: cursor,
            end: cursor + Duration::seconds(chosen),
        });
        cursor += Duration::seconds(chosen);
    }
    Ok(())
}

pub fn default_max_span() -> Duration {
    MAX_HISTORY_WINDOW
}

#[cfg(test)]
mod tests {
    use super::*;

    fn h(n: i64) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
            + Duration::hours(n)
    }

    #[test]
    fn t1423_3_plans_only_missing_merged_ranges() {
        let stored = [h(1), h(2), h(3), h(6)];
        let plan = gap_plan_input(
            h(0),
            h(9),
            Some(h(1)),
            h(0),
            &stored,
            Some(h(6) + Duration::minutes(30)),
            false,
            Duration::hours(6),
        )
        .and_then(plan_gap_windows)
        .expect("plan");
        assert_eq!(plan.counts.not_expected, 1, "{plan:?}");
        assert_eq!(plan.counts.skipped_stored, 4, "{plan:?}");
        assert_eq!(plan.counts.planned, 3, "{plan:?}");
        assert!(plan.not_expected.iter().any(|w| w.start == h(0)));
        assert_eq!(
            plan.planned,
            vec![
                WindowSpan {
                    start: h(4),
                    end: h(6)
                },
                WindowSpan {
                    start: h(7),
                    end: h(8)
                },
                WindowSpan {
                    start: h(8),
                    end: h(9)
                }
            ]
        );
        assert_eq!(plan.expected_start, h(1));
    }

    #[test]
    fn force_replans_stored_hours() {
        let stored = [h(1)];
        let plan = gap_plan_input(
            h(1),
            h(3),
            Some(h(1)),
            h(1),
            &stored,
            Some(h(1)),
            true,
            Duration::hours(6),
        )
        .and_then(plan_gap_windows)
        .expect("plan");
        assert_eq!(plan.counts.skipped_stored, 0);
        assert_eq!(plan.counts.planned, 2);
        assert_eq!(plan.planned[0].start, h(1));
        assert_eq!(plan.planned[0].end, h(2));
        assert_eq!(plan.planned[1].start, h(2));
        assert_eq!(plan.planned[1].end, h(3));
    }

    #[test]
    fn expected_start_is_latest_of_three_anchors() {
        assert_eq!(
            expected_start(h(0), Some(h(1)), h(2)),
            h(2),
            "binding creation wins"
        );
        assert_eq!(
            expected_start(h(5), Some(h(3)), h(1)),
            h(5),
            "requested start wins"
        );
    }

    #[test]
    fn t1500_partial_first_hour_stays_plannable_with_subhour_anchor() {
        let anchor = h(1) + Duration::minutes(35) + Duration::seconds(12);
        let (first, fetch_start, fetch_end) =
            gap_plan_bounds(h(0), h(4), Some(anchor), h(0)).expect("bounds");
        assert_eq!(first, anchor);
        assert_eq!(fetch_start, h(1));
        let plan = gap_plan_input(
            h(0),
            h(4),
            Some(anchor),
            h(0),
            &[],
            None,
            false,
            Duration::hours(6),
        )
        .and_then(plan_gap_windows)
        .expect("plan");
        assert_eq!(plan.counts.not_expected, 1, "{plan:?}");
        assert!(
            plan.planned.iter().any(|w| w.start == h(1)),
            "partial first hour must plan: {plan:?}"
        );
        assert_eq!(fetch_end, h(4));
    }
}
