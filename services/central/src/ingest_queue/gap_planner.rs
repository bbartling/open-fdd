//! Database-first gap-only backfill planning (#1423 part b).
//!
//! Given stored hourly windows from Timescale, a provider data start, binding
//! creation, and the operator request, plans only missing ranges merged up to
//! the driver `max_history_span`.

use chrono::{DateTime, Duration, Utc};
use serde::Serialize;

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
    pub requested_start: DateTime<Utc>,
    pub requested_end: DateTime<Utc>,
    pub provider_data_start: Option<DateTime<Utc>>,
    pub binding_created_at: DateTime<Utc>,
    pub stored_hour_starts: &'a [DateTime<Utc>],
    pub last_stored_ts: Option<DateTime<Utc>>,
    pub force: bool,
    pub max_span: Duration,
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

/// Plan hourly windows in `[requested_start, requested_end)` against stored hours.
pub fn plan_gap_windows(input: GapPlanInput<'_>) -> Result<GapPlanResult, String> {
    if input.requested_end <= input.requested_start {
        return Err("backfill end must be after start".into());
    }
    if !is_hour_start(input.requested_start) || !is_hour_start(input.requested_end) {
        return Err("backfill range must use exact UTC hour boundaries".into());
    }
    let span_cap = input.max_span.num_seconds();
    if span_cap < 60 {
        return Err("max_history_span must be at least 60 seconds".into());
    }
    let expected = expected_start(
        input.requested_start,
        input.provider_data_start,
        input.binding_created_at,
    );
    let stored: std::collections::BTreeSet<DateTime<Utc>> = input
        .stored_hour_starts
        .iter()
        .copied()
        .filter(|ts| is_hour_start(*ts))
        .collect();

    let mut skipped_stored = Vec::new();
    let mut not_expected = Vec::new();
    let mut missing_hours = Vec::new();

    let mut cursor = input.requested_start;
    while cursor < input.requested_end {
        let next = cursor + Duration::hours(1);
        if next <= expected {
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

    let planned = merge_missing_hours(missing_hours, span_cap)?;
    let counts = GapPlanCounts {
        planned: u32::try_from(planned.len()).map_err(|_| "planned window count overflow")?,
        skipped_stored: u32::try_from(skipped_stored.len())
            .map_err(|_| "skipped_stored count overflow")?,
        not_expected: u32::try_from(not_expected.len())
            .map_err(|_| "not_expected count overflow")?,
    };
    Ok(GapPlanResult {
        planned,
        skipped_stored,
        not_expected,
        counts,
        expected_start: expected,
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
        let plan = plan_gap_windows(GapPlanInput {
            requested_start: h(0),
            requested_end: h(9),
            provider_data_start: Some(h(1)),
            binding_created_at: h(0),
            stored_hour_starts: &stored,
            last_stored_ts: Some(h(6) + Duration::minutes(30)),
            force: false,
            max_span: Duration::hours(6),
        })
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
        let plan = plan_gap_windows(GapPlanInput {
            requested_start: h(1),
            requested_end: h(3),
            provider_data_start: Some(h(1)),
            binding_created_at: h(1),
            stored_hour_starts: &stored,
            last_stored_ts: Some(h(1)),
            force: true,
            max_span: Duration::hours(6),
        })
        .expect("plan");
        assert_eq!(plan.counts.skipped_stored, 0);
        assert_eq!(plan.counts.planned, 1);
        assert_eq!(plan.planned[0].start, h(1));
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
}
