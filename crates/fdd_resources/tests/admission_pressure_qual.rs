//! Isolated qualification: admission + pressure policy (#1127 P4).
//!
//! Does not claim Railway live survival. Proves process-local contracts:
//! saturated compute admission refuses new work; critical pressure defers
//! expensive compute while protect_ingest stays true.

use fdd_resources::{
    evaluate_pressure, try_acquire_compute, CapacityDiscovery, ComputeClass, CpuDiscovery,
    MemoryDiscovery, PressureState,
};

fn disc(hard: u64, current: u64) -> CapacityDiscovery {
    CapacityDiscovery {
        memory: MemoryDiscovery {
            available: true,
            hard_limit_bytes: Some(hard),
            current_bytes: Some(current),
            high_bytes: None,
            source: "qual_fixture".into(),
            hierarchy_complete: true,
            notes: vec![],
        },
        cpu: CpuDiscovery {
            logical_cores: 2,
            cpuset_cores: Some(2),
            quota_cores: Some(2.0),
            effective_cores: 2,
            source: "qual_fixture".into(),
            notes: vec![],
        },
    }
}

#[test]
fn pressure_critical_defers_compute_and_protects_ingest() {
    let snap = evaluate_pressure(&disc(10_000, 9_500));
    assert_eq!(snap.state, PressureState::Critical);
    assert!(snap.defer_expensive_compute);
    assert!(snap.protect_ingest);
}

#[tokio::test]
async fn admission_saturates_across_classes() {
    let mut held = Vec::new();
    loop {
        match try_acquire_compute(ComputeClass::ManualFdd) {
            Some(p) => held.push(p),
            None => break,
        }
        assert!(held.len() <= 64, "semaphore did not saturate");
    }
    assert!(try_acquire_compute(ComputeClass::ScheduledAfdd).is_none());
    assert!(try_acquire_compute(ComputeClass::Analytics).is_none());
    assert!(try_acquire_compute(ComputeClass::Import).is_none());
    drop(held);
    assert!(try_acquire_compute(ComputeClass::Series).is_some());
}
