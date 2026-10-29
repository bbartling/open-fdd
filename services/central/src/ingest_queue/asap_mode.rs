//! ASAP catch-up mode (#1423 part c): enter on backlog, exit near now, live poll priority.

use chrono::{DateTime, Duration, Utc};
use tracing::info;

use crate::providers::hourly::{floor_to_window, validate_ingest_window_secs};

use super::gap_planner::{plan_gap_windows, GapPlanInput, GapPlanResult};

pub const MODE_NORMAL: &str = "normal";
pub const MODE_ASAP: &str = "asap";

const THRESHOLD_DEFAULT: u32 = 6;
const THRESHOLD_MIN: u32 = 1;
const THRESHOLD_MAX: u32 = 48;
const TICK_SECS_DEFAULT: u64 = 15;
const TICK_SECS_MIN: u64 = 5;
const TICK_SECS_MAX: u64 = 300;
const MAX_JOBS_DEFAULT: u32 = 8;
const MAX_JOBS_MIN: u32 = 1;
const MAX_JOBS_MAX: u32 = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AsapConfig {
    pub threshold_windows: u32,
    pub tick_secs: u64,
    pub max_jobs_per_tick: u32,
}

impl AsapConfig {
    pub fn from_env() -> Result<Self, String> {
        Ok(Self {
            threshold_windows: env_u32_bounded(
                "OPENFDD_INGEST_ASAP_THRESHOLD_WINDOWS",
                THRESHOLD_DEFAULT,
                THRESHOLD_MIN,
                THRESHOLD_MAX,
            )?,
            tick_secs: env_u64_bounded(
                "OPENFDD_INGEST_ASAP_TICK_SECS",
                TICK_SECS_DEFAULT,
                TICK_SECS_MIN,
                TICK_SECS_MAX,
            )?,
            max_jobs_per_tick: env_u32_bounded(
                "OPENFDD_INGEST_ASAP_MAX_JOBS_PER_TICK",
                MAX_JOBS_DEFAULT,
                MAX_JOBS_MIN,
                MAX_JOBS_MAX,
            )?,
        })
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
/// `validated_window_secs` must come from [`validate_ingest_window_secs`].
pub fn within_one_window_of_now(
    last_stored: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
    publication_delay: Duration,
    validated_window_secs: i64,
) -> bool {
    let target = floor_to_window(now - publication_delay, validated_window_secs);
    let Some(last) = last_stored else {
        return false;
    };
    last + Duration::seconds(validated_window_secs) >= target
}

pub fn decide_mode(
    plan: &GapPlanResult,
    last_stored: Option<DateTime<Utc>>,
    now: DateTime<Utc>,
    publication_delay: Duration,
    window_secs: i64,
    threshold_windows: u32,
) -> Result<ModeDecision, String> {
    let step = validate_ingest_window_secs(window_secs)?;
    let target_through = floor_to_window(now - publication_delay, step);
    let missing = plan.counts.missing_hours;
    let mode = if within_one_window_of_now(last_stored, now, publication_delay, step) {
        CatchupMode::Normal
    } else if missing > threshold_windows {
        CatchupMode::Asap
    } else {
        CatchupMode::Normal
    };
    Ok(ModeDecision {
        mode,
        missing_windows: missing,
        target_through,
    })
}

pub fn plan_backlog(input: GapPlanInput<'_>) -> Result<GapPlanResult, String> {
    plan_gap_windows(input)
}

pub fn eta_seconds(
    missing_windows: u32,
    window_secs: i64,
    rows_per_minute: Option<f64>,
) -> Result<Option<i64>, String> {
    if missing_windows == 0 {
        return Ok(Some(0));
    }
    let Some(rows_per_minute) = rows_per_minute else {
        return Ok(None);
    };
    if rows_per_minute <= 0.0 || !rows_per_minute.is_finite() {
        return Ok(None);
    }
    let step = validate_ingest_window_secs(window_secs)?;
    let windows_per_minute = (rows_per_minute * 60.0 / (step as f64)).max(0.01);
    let minutes = f64::from(missing_windows) / windows_per_minute;
    if !minutes.is_finite() {
        return Ok(None);
    }
    let whole_minutes = minutes.ceil() as i64;
    whole_minutes
        .checked_mul(60)
        .ok_or_else(|| "ASAP catch-up ETA seconds overflow".to_string())
        .map(Some)
}

fn env_u32_bounded(key: &str, default: u32, min: u32, max: u32) -> Result<u32, String> {
    match std::env::var(key) {
        Err(_) | Ok(ref raw) if raw.trim().is_empty() => {
            info!(env = key, default, min, max, "using default ASAP ingest config (unset)");
            Ok(default)
        }
        Ok(raw) => {
            let parsed = raw.trim().parse::<u32>().map_err(|_| {
                format!("{key}={raw:?}: invalid unsigned integer for ASAP ingest config")
            })?;
            if !(min..=max).contains(&parsed) {
                return Err(format!(
                    "{key}={parsed}: out of range (must be {min}..={max})"
                ));
            }
            Ok(parsed)
        }
    }
}

fn env_u64_bounded(key: &str, default: u64, min: u64, max: u64) -> Result<u64, String> {
    match std::env::var(key) {
        Err(_) | Ok(ref raw) if raw.trim().is_empty() => {
            info!(env = key, default, min, max, "using default ASAP ingest config (unset)");
            Ok(default)
        }
        Ok(raw) => {
            let parsed = raw.trim().parse::<u64>().map_err(|_| {
                format!("{key}={raw:?}: invalid unsigned integer for ASAP ingest config")
            })?;
            if !(min..=max).contains(&parsed) {
                return Err(format!(
                    "{key}={parsed}: out of range (must be {min}..={max})"
                ));
            }
            Ok(parsed)
        }
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
        let decision = decide_mode(&plan, Some(h(1)), h(12), Duration::seconds(300), 3600, 3)
            .expect("decide");
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
        let decision = decide_mode(&plan, Some(last), now, Duration::seconds(300), 3600, 1)
            .expect("decide");
        assert_eq!(decision.mode, CatchupMode::Normal);
    }
}
