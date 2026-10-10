//! Adaptive pressure signals for admission/deferral (#1127 P4 / #1179 R4).
//!
//! Protect ingest/control by refusing/deferring expensive compute when the
//! cgroup is near its hard limit. Does **not** claim confirmed OOM.
//!
//! Shed/abort fractions are portable shares of the detected hard limit
//! (`OPENFDD_MEMORY_SHED_FRACTION` / `OPENFDD_MEMORY_ABORT_FRACTION`), not
//! Railway-hardcoded GB.

use serde::Serialize;

use crate::cgroup::{discover_capacity, CapacityDiscovery};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PressureState {
    Ok,
    Elevated,
    Critical,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ShedState {
    Ok,
    Shed,
    Abort,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PressureSnapshot {
    pub state: PressureState,
    pub shed_state: ShedState,
    pub percent_used: Option<f64>,
    pub defer_expensive_compute: bool,
    pub abort_in_flight: bool,
    pub protect_ingest: bool,
    pub hard_limit_bytes: Option<u64>,
    pub current_bytes: Option<u64>,
    pub peak_bytes: Option<u64>,
    pub shed_bytes: Option<u64>,
    pub abort_bytes: Option<u64>,
    pub source: String,
    pub notes: Vec<String>,
}

/// Default shed = 0.75 × hard; abort = 0.85 × hard (#1179).
fn shed_fraction() -> f64 {
    std::env::var("OPENFDD_MEMORY_SHED_FRACTION")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0.0 && *value < 1.0)
        .unwrap_or(0.75)
}

fn abort_fraction() -> f64 {
    let shed = shed_fraction();
    std::env::var("OPENFDD_MEMORY_ABORT_FRACTION")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > shed && *value <= 1.0)
        .unwrap_or(0.85_f64.max(shed))
}

/// High watermark defaults (percent of hard cgroup limit).
/// Align elevated/critical with shed/abort fractions when unset.
fn elevated_pct() -> f64 {
    std::env::var("OPENFDD_PRESSURE_ELEVATED_PCT")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0.0 && *value < 100.0)
        .unwrap_or(shed_fraction() * 100.0)
}

fn critical_pct() -> f64 {
    std::env::var("OPENFDD_PRESSURE_CRITICAL_PCT")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0.0 && *value <= 100.0)
        .unwrap_or(abort_fraction() * 100.0)
}

pub fn sample_pressure() -> PressureSnapshot {
    evaluate_pressure(&discover_capacity())
}

pub fn evaluate_pressure(discovery: &CapacityDiscovery) -> PressureSnapshot {
    let mut notes = discovery.memory.notes.clone();
    let hard = discovery.memory.hard_limit_bytes;
    let current = discovery.memory.current_bytes;
    // M70-09: peak is memory.peak / max_usage only — never memory.high or current.
    let peak = discovery.memory.peak_bytes;
    let high = discovery.memory.high_bytes;
    if peak.is_none() {
        notes.push("peak_bytes unavailable (not substituted from memory.high/current)".into());
    }
    if high.is_some() {
        notes.push("memory.high is a throttle threshold, reported separately from peak".into());
    }
    let shed_f = shed_fraction();
    let abort_f = abort_fraction();
    let shed_bytes = hard.map(|h| ((h as f64) * shed_f).round() as u64);
    let abort_bytes = hard.map(|h| ((h as f64) * abort_f).round() as u64);
    let percent = match (hard, current) {
        (Some(h), Some(cur)) if h > 0 => Some((cur as f64 / h as f64) * 100.0),
        _ => {
            notes.push("no hard limit+current pair; pressure state stays ok/unknown".into());
            None
        }
    };
    let elevated = elevated_pct();
    let critical = critical_pct().max(elevated);
    let state = match percent {
        Some(p) if p >= critical => PressureState::Critical,
        Some(p) if p >= elevated => PressureState::Elevated,
        _ => PressureState::Ok,
    };
    let shed_state = match (current, shed_bytes, abort_bytes) {
        (Some(cur), _, Some(abort)) if cur >= abort => ShedState::Abort,
        (Some(cur), Some(shed), _) if cur >= shed => ShedState::Shed,
        _ => ShedState::Ok,
    };
    notes.push(format!(
        "memory shed/abort fractions = {shed_f}/{abort_f} of detected hard limit (portable)"
    ));
    PressureSnapshot {
        defer_expensive_compute: matches!(shed_state, ShedState::Shed | ShedState::Abort)
            || matches!(state, PressureState::Elevated | PressureState::Critical),
        abort_in_flight: matches!(shed_state, ShedState::Abort),
        protect_ingest: true,
        state,
        shed_state,
        percent_used: percent.map(|p| (p * 10.0).round() / 10.0),
        hard_limit_bytes: hard,
        current_bytes: current,
        peak_bytes: peak,
        shed_bytes,
        abort_bytes,
        source: discovery.memory.source.clone(),
        notes,
    }
}

/// Compact memory_budget object for `/api/health` (#1179 R4).
pub fn memory_budget_json() -> serde_json::Value {
    let discovery = discover_capacity();
    let pressure = evaluate_pressure(&discovery);
    let budget = crate::budget::ComputeBudget::resolve(&discovery, 512).ok();
    let last_trip = crate::in_flight::last_memory_trip();
    serde_json::json!({
        "hard_limit_bytes": pressure.hard_limit_bytes,
        "pool_bytes": budget.as_ref().map(|b| b.compute_memory_bytes),
        "query_bytes": budget.as_ref().map(|b| b.query_memory_bytes),
        // query_bytes is an advertised per-run ceiling; DataFusion intermediates
        // are enforced via shared FairSpillPool + materialization budgets until
        // a dedicated per-run pool limiter lands (M70-03 residual).
        "query_bytes_enforced": "materialization_and_shared_pool",
        "current_bytes": pressure.current_bytes,
        "peak_bytes": pressure.peak_bytes,
        "high_bytes": discovery.memory.high_bytes,
        "peak_available": pressure.peak_bytes.is_some(),
        "shed_bytes": pressure.shed_bytes,
        "abort_bytes": pressure.abort_bytes,
        "shed_state": pressure.shed_state,
        "sample_ms": crate::in_flight::memory_sample_ms(),
        "last_trip": last_trip,
        "source": pressure.source,
        "compute_origin": budget.as_ref().map(|b| &b.compute_origin),
        "hierarchy_complete": discovery.memory.hierarchy_complete,
        "notes": pressure.notes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cgroup::{CpuDiscovery, MemoryDiscovery};

    fn disc(hard: u64, current: u64) -> CapacityDiscovery {
        CapacityDiscovery {
            memory: MemoryDiscovery {
                available: true,
                hard_limit_bytes: Some(hard),
                current_bytes: Some(current),
                high_bytes: None,
                peak_bytes: None,
                source: "test".into(),
                hierarchy_complete: true,
                notes: vec![],
            },
            cpu: CpuDiscovery {
                logical_cores: 2,
                cpuset_cores: Some(2),
                quota_cores: Some(2.0),
                effective_cores: 2,
                source: "test".into(),
                notes: vec![],
            },
        }
    }

    #[test]
    fn critical_defers_expensive_compute() {
        std::env::remove_var("OPENFDD_MEMORY_SHED_FRACTION");
        std::env::remove_var("OPENFDD_MEMORY_ABORT_FRACTION");
        std::env::remove_var("OPENFDD_PRESSURE_ELEVATED_PCT");
        std::env::remove_var("OPENFDD_PRESSURE_CRITICAL_PCT");
        // 850/1000 = 85% → abort fraction default.
        let snap = evaluate_pressure(&disc(1000, 850));
        assert_eq!(snap.shed_state, ShedState::Abort);
        assert!(snap.defer_expensive_compute);
        assert!(snap.abort_in_flight);
        assert!(snap.protect_ingest);
    }

    #[test]
    fn elevated_defers_at_shed_fraction() {
        std::env::remove_var("OPENFDD_MEMORY_SHED_FRACTION");
        std::env::remove_var("OPENFDD_MEMORY_ABORT_FRACTION");
        std::env::remove_var("OPENFDD_PRESSURE_ELEVATED_PCT");
        std::env::remove_var("OPENFDD_PRESSURE_CRITICAL_PCT");
        // 760/1000 = 76% → shed (0.75) but below abort (0.85).
        let snap = evaluate_pressure(&disc(1000, 760));
        assert_eq!(snap.shed_state, ShedState::Shed);
        assert!(snap.defer_expensive_compute);
        assert!(!snap.abort_in_flight);
    }

    #[test]
    fn low_usage_allows_compute() {
        let snap = evaluate_pressure(&disc(1000, 100));
        assert_eq!(snap.shed_state, ShedState::Ok);
        assert!(!snap.defer_expensive_compute);
        assert!(!snap.abort_in_flight);
    }

    #[test]
    fn peak_not_substituted_from_high_or_current() {
        let mut d = disc(1000, 500);
        d.memory.high_bytes = Some(700);
        d.memory.peak_bytes = Some(900);
        let snap = evaluate_pressure(&d);
        assert_eq!(snap.peak_bytes, Some(900));
        d.memory.peak_bytes = None;
        let snap2 = evaluate_pressure(&d);
        assert_eq!(snap2.peak_bytes, None, "must not fall back to current/high");
    }
}
