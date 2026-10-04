//! Process-wide weighted compute admission (#1127 P1).
//!
//! Actions rows are **not** the concurrency authority. A permit is held until
//! the owning worker drops it — clearing Actions must not release compute.

use std::sync::{Arc, OnceLock};

use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub const DEFAULT_COMPUTE_MAX_INFLIGHT: usize = 2;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ComputeClass {
    ManualFdd,
    ScheduledAfdd,
    Analytics,
    Series,
    Import,
    Compaction,
}

impl ComputeClass {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::ManualFdd => "manual_fdd",
            Self::ScheduledAfdd => "scheduled_afdd",
            Self::Analytics => "analytics",
            Self::Series => "series",
            Self::Import => "import",
            Self::Compaction => "compaction",
        }
    }

    /// Relative weight (higher = more exclusive). Import/compaction share the
    /// global pool at weight 1; heavy FDD/AFDD use weight 1 as well for P1
    /// (global cap is the primary control).
    pub fn weight(self) -> usize {
        1
    }
}

pub struct ComputePermit {
    pub class: ComputeClass,
    _permit: OwnedSemaphorePermit,
}

fn global_semaphore() -> &'static Arc<Semaphore> {
    static SEM: OnceLock<Arc<Semaphore>> = OnceLock::new();
    SEM.get_or_init(|| {
        let n = std::env::var("OPENFDD_COMPUTE_MAX_INFLIGHT")
            .ok()
            .and_then(|s| s.trim().parse::<usize>().ok())
            .filter(|n| *n > 0)
            .unwrap_or(DEFAULT_COMPUTE_MAX_INFLIGHT);
        Arc::new(Semaphore::new(n))
    })
}

/// Non-blocking admission. Returns `None` when the process-wide cap is saturated.
pub fn try_acquire_compute(class: ComputeClass) -> Option<ComputePermit> {
    let sem = global_semaphore().clone();
    match sem.try_acquire_owned() {
        Ok(permit) => Some(ComputePermit {
            class,
            _permit: permit,
        }),
        Err(_) => None,
    }
}

/// Async admission (waits). Prefer `try_acquire_compute` for HTTP 429 paths.
pub async fn acquire_compute(class: ComputeClass) -> ComputePermit {
    let sem = global_semaphore().clone();
    let permit = sem
        .acquire_owned()
        .await
        .expect("compute admission semaphore closed");
    ComputePermit {
        class,
        _permit: permit,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn global_cap_blocks_extra_workers() {
        // Isolate by using try_acquire until saturated against default/env cap.
        let mut held = Vec::new();
        loop {
            match try_acquire_compute(ComputeClass::ManualFdd) {
                Some(p) => held.push(p),
                None => break,
            }
            if held.len() > 64 {
                panic!("semaphore did not saturate");
            }
        }
        assert!(try_acquire_compute(ComputeClass::ScheduledAfdd).is_none());
        assert!(try_acquire_compute(ComputeClass::Analytics).is_none());
        drop(held);
        assert!(try_acquire_compute(ComputeClass::Series).is_some());
    }
}
