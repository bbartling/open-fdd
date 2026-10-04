//! Adaptive pressure signals for admission/deferral (#1127 P4).
//!
//! Protect ingest/control by refusing/deferring expensive compute when the
//! cgroup is near its hard limit. Does **not** claim confirmed OOM.

use serde::Serialize;

use crate::cgroup::{discover_capacity, CapacityDiscovery};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PressureState {
    Ok,
    Elevated,
    Critical,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PressureSnapshot {
    pub state: PressureState,
    pub percent_used: Option<f64>,
    pub defer_expensive_compute: bool,
    pub protect_ingest: bool,
    pub source: String,
    pub notes: Vec<String>,
}

/// High watermark defaults (percent of hard cgroup limit).
const ELEVATED_PCT: f64 = 75.0;
const CRITICAL_PCT: f64 = 90.0;

pub fn sample_pressure() -> PressureSnapshot {
    evaluate_pressure(&discover_capacity())
}

pub fn evaluate_pressure(discovery: &CapacityDiscovery) -> PressureSnapshot {
    let mut notes = discovery.memory.notes.clone();
    let percent = match (discovery.memory.hard_limit_bytes, discovery.memory.current_bytes) {
        (Some(hard), Some(cur)) if hard > 0 => Some((cur as f64 / hard as f64) * 100.0),
        _ => {
            notes.push("no hard limit+current pair; pressure state stays ok/unknown".into());
            None
        }
    };
    let state = match percent {
        Some(p) if p >= CRITICAL_PCT => PressureState::Critical,
        Some(p) if p >= ELEVATED_PCT => PressureState::Elevated,
        _ => PressureState::Ok,
    };
    PressureSnapshot {
        defer_expensive_compute: matches!(state, PressureState::Elevated | PressureState::Critical),
        protect_ingest: true,
        state,
        percent_used: percent.map(|p| (p * 10.0).round() / 10.0),
        source: discovery.memory.source.clone(),
        notes,
    }
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
        let snap = evaluate_pressure(&disc(1000, 950));
        assert_eq!(snap.state, PressureState::Critical);
        assert!(snap.defer_expensive_compute);
        assert!(snap.protect_ingest);
    }

    #[test]
    fn low_usage_allows_compute() {
        let snap = evaluate_pressure(&disc(1000, 100));
        assert_eq!(snap.state, PressureState::Ok);
        assert!(!snap.defer_expensive_compute);
    }
}
