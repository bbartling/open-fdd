//! Confirmation-duration logic for FDD faults.

use chrono::{DateTime, Duration, Utc};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConfirmedSample {
    pub ts: DateTime<Utc>,
    pub fault_raw: bool,
    pub fault_confirmed: bool,
    pub gap_reset: bool,
}

/// Apply confirmation to sorted fault_raw samples.
///
/// Policy:
/// - Samples must be sorted by timestamp before calling.
/// - Duplicate timestamps: caller should dedupe first (keep last).
/// - Out-of-order samples: sort before calling.
/// - Missing sample gap > max_gap_seconds resets the raw-fault streak and sets gap_reset.
/// - Confirmed fault clears immediately when fault_raw is false on the next sample.
/// - Confirmed fault becomes true only after fault_raw stays true continuously for
///   confirmation_seconds.
pub fn apply_confirmation(
    samples: &[(DateTime<Utc>, bool)],
    confirmation_seconds: i64,
    max_gap_seconds: i64,
) -> Vec<ConfirmedSample> {
    let mut out = Vec::with_capacity(samples.len());
    let mut streak_start: Option<DateTime<Utc>> = None;
    let mut prev_ts: Option<DateTime<Utc>> = None;

    for (ts, fault_raw) in samples {
        let mut gap_reset = false;
        if let Some(prev) = prev_ts {
            let gap = (*ts - prev).num_seconds();
            if gap > max_gap_seconds {
                streak_start = None;
                gap_reset = true;
            }
        }

        let fault_confirmed = if *fault_raw {
            if streak_start.is_none() {
                streak_start = Some(*ts);
            }
            streak_start
                .map(|start| (*ts - start).num_seconds() >= confirmation_seconds)
                .unwrap_or(false)
        } else {
            streak_start = None;
            false
        };

        out.push(ConfirmedSample {
            ts: *ts,
            fault_raw: *fault_raw,
            fault_confirmed,
            gap_reset,
        });
        prev_ts = Some(*ts);
    }

    out
}

pub fn first_true_ts(samples: &[ConfirmedSample], field: FaultField) -> Option<DateTime<Utc>> {
    samples
        .iter()
        .find(|s| match field {
            FaultField::Raw => s.fault_raw,
            FaultField::Confirmed => s.fault_confirmed,
        })
        .map(|s| s.ts)
}

pub fn last_true_ts(samples: &[ConfirmedSample], field: FaultField) -> Option<DateTime<Utc>> {
    samples
        .iter()
        .rev()
        .find(|s| match field {
            FaultField::Raw => s.fault_raw,
            FaultField::Confirmed => s.fault_confirmed,
        })
        .map(|s| s.ts)
}

#[derive(Clone, Copy, Debug)]
pub enum FaultField {
    Raw,
    Confirmed,
}

pub fn confirmation_lag_seconds(
    raw_at: DateTime<Utc>,
    confirmed_at: DateTime<Utc>,
) -> i64 {
    (confirmed_at - raw_at).num_seconds()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ts(minute: i64) -> DateTime<Utc> {
        Utc::now() + Duration::minutes(minute)
    }

    #[test]
    fn no_confirmed_fault_before_duration() {
        let samples: Vec<_> = (0..4)
            .map(|m| (ts(m), true))
            .collect();
        let confirmed = apply_confirmation(&samples, 300, 120);
        assert!(confirmed.iter().all(|s| !s.fault_confirmed));
    }

    #[test]
    fn confirmed_fault_at_or_after_five_minutes() {
        let samples: Vec<_> = (0..=5)
            .map(|m| (ts(m), true))
            .collect();
        let confirmed = apply_confirmation(&samples, 300, 120);
        assert!(!confirmed[4].fault_confirmed);
        assert!(confirmed[5].fault_confirmed);
    }

    #[test]
    fn fault_clears_immediately_when_raw_clears() {
        let samples = vec![
            (ts(0), true),
            (ts(1), true),
            (ts(6), true),
            (ts(7), false),
        ];
        let confirmed = apply_confirmation(&samples, 300, 120);
        assert!(confirmed.last().unwrap().fault_confirmed == false);
        assert!(!confirmed.last().unwrap().fault_raw);
    }

    #[test]
    fn gap_resets_confirmation_streak() {
        let samples = vec![(ts(0), true), (ts(10), true)];
        let confirmed = apply_confirmation(&samples, 300, 120);
        assert!(confirmed[1].gap_reset);
        assert!(!confirmed[1].fault_confirmed);
    }

    #[test]
    fn high_limit_150_no_raw_fault_for_70f() {
        assert!(!oa_t_out_of_range(70.0, 150.0, -50.0));
    }

    #[test]
    fn duplicate_timestamp_last_wins_after_sort() {
        let t0 = ts(0);
        let samples = vec![(t0, false), (t0, true)];
        let confirmed = apply_confirmation(&samples, 300, 120);
        assert_eq!(confirmed.len(), 2);
        assert!(confirmed[1].fault_raw);
    }

    #[test]
    fn out_of_order_samples_sorted_before_apply() {
        let samples = vec![(ts(2), true), (ts(0), true), (ts(1), true)];
        let mut sorted = samples;
        sorted.sort_by_key(|s| s.0);
        let confirmed = apply_confirmation(&sorted, 120, 60);
        assert!(confirmed.last().unwrap().fault_confirmed);
    }
}

pub fn oa_t_out_of_range(value: f64, high_limit: f64, low_limit: f64) -> bool {
    value > high_limit || value < low_limit
}
