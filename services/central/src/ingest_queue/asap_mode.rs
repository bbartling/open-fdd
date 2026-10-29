//! ASAP catch-up mode (#1423 part c): enter on backlog, exit near now, live poll priority.

use chrono::{DateTime, Duration, Utc};

use crate::providers::hourly::floor_to_window;

use super::gap_planner::{plan_gap_windows, GapPlanInput, GapPlanResult};

pub const MODE_NORMAL: &str = "normal";
pub const MODE_ASAP: &str = "asap";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AsapConfig {
    pub threshold_windows: u32,
    pub tick_secs: u64,
    pub max_jobs_per_tick: u32,
}

impl AsapConfig {
    pub fn from_env() -> Self {
        let threshold_windows = env_u32("OPENFDD_INGEST_ASAP_THRESHOLD_WINDOWS", 6).clamp(1, 48);
        let tick_secs = env_u64("OPENFDD_INGEST_ASAP_TICK_SECS", 15).clamp(5, 300);
        let max_jobs_per_tick = env_u32("OPENFDD_INGEST_ASAP_MAX_JOBS_PER_TICK", 8).clamp(1, 32);
        Self {
            threshold_windows,
            tick_secs,
            max_jobs_per_tick,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum CatchupMode {
    #[default]
    Normal,
    Asap,
}

impl CatchupMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Normal => MODE_NORMAL,
            Self::Asap => MODE_ASAP,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ModeDecision {
    pub mode: CatchupMode,
    pub missing_windows: u32,
    pub target_through: DateTime<Utc>,
}

/// Whether `last_stored_ts` is within one ingest window of the publication horizon.
pub fn within_one_window_of_now(
    last_stored: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
    publication_delay: Duration,
    window_secs: i64,
) -> bool {
    let step = window_secs.clamp(60, 3600);
    let target = floor_to_window(now - publication_delay, step);
    let Some(last) = last_stored else {
        return false;
    };
    last + Duration::seconds(step) >= target
}

pub fn decide_mode(
    plan: &GapPlanResult,
    last_stored: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
    publication_delay: Duration,
    window_secs: i64,
    threshold_windows: u32,
) -> ModeDecision {
    let step = window_secs.clamp(60, 3600);
    let target_through = floor_to_window(now - publication_delay, step);
    let missing = plan.counts.missing_hours;
    let mode = if within_one_window_of_now(last_stored, now, publication_delay, step) {
        CatchupMode::Normal
    } else if missing > threshold_windows {
        CatchupMode::Asap
    } else {
        CatchupMode::Normal
    };
    ModeDecision {
        mode,
        missing_windows: missing,
        target_through,
    }
}

pub fn plan_backlog(input: GapPlanInput<'_>) -> Result<GapPlanResult, String> {
    plan_gap_windows(input)
}

pub fn eta_seconds(missing_windows: u32, window_secs: i64, rows_per_minute: f64) -> Option<i64> {
    if missing_windows == 0 {
        return Some(0);
    }
    if rows_per_minute <= 0.0 {
        return None;
    }
    let step = window_secs.clamp(60, 3600);
    let windows_per_minute = (rows_per_minute * 60.0 / (step as f64)).max(0.01);
    let minutes = f64::from(missing_windows) / windows_per_minute;
    if !minutes.is_finite() {
        return None;
    }
    Some((minutes.ceil() as i64).saturating_mul(60))
}

fn env_u32(key: &str, default: u32) -> u32 {
    match std::env::var(key) {
        Ok(raw) if !raw.trim().is_empty() => raw.trim().parse().unwrap_or(default),
        _ => default,
    }
}

fn env_u64(key: &str, default: u64) -> u64 {
    match std::env::var(key) {
        Ok(raw) if !raw.trim().is_empty() => raw.trim().parse().unwrap_or(default),
        _ => default,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::http_policy::MAX_HISTORY_WINDOW;

    fn h(n: i64) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
            + Duration::hours(n)
    }

    #[test]
    fn enters_asap_when_missing_exceeds_threshold() {
        let stored = [h(1)];
        let plan = plan_backlog(GapPlanInput {
            requested_start: h(1),
            requested_end: h(12),
            provider_data_start: Some(h(1)),
            binding_created_at: h(1),
            stored_hour_starts: &stored,
            last_stored_ts: Some(h(1)),
            force: false,
            max_span: MAX_HISTORY_WINDOW,
        })
        .expect("plan");
        let decision = decide_mode(&plan, Some(h(1)), h(12), Duration::seconds(300), 3600, 3);
        assert_eq!(decision.mode, CatchupMode::Asap);
        assert!(decision.missing_windows > 3);
    }

    #[test]
    fn exits_asap_when_last_stored_within_one_window() {
        let now = h(10) + Duration::minutes(10);
        let last = h(9) + Duration::minutes(30);
        assert!(within_one_window_of_now(
            Some(last),
            now,
            Duration::seconds(300),
            3600
        ));
        let plan = plan_backlog(GapPlanInput {
            requested_start: h(1),
            requested_end: h(10),
            provider_data_start: Some(h(1)),
            binding_created_at: h(1),
            stored_hour_starts: &[h(1)],
            last_stored_ts: Some(last),
            force: false,
            max_span: MAX_HISTORY_WINDOW,
        })
        .expect("plan");
        let decision = decide_mode(&plan, Some(last), now, Duration::seconds(300), 3600, 1);
        assert_eq!(decision.mode, CatchupMode::Normal);
    }
}
