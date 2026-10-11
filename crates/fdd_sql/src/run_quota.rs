//! Per-run memory quota wrapper over the shared aggregate FairSpillPool.
//!
//! Soft-OPEN 371 T1c: `OPENFDD_QUERY_MEMORY_MB` / resolved `query_memory_bytes`
//! must bound DataFusion operator reservations for a single run, while still
//! charging the process-wide aggregate pool. This is not total process RSS —
//! only tracked engine allocations.

use std::fmt::{Display, Formatter};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use datafusion::common::{internal_datafusion_err, Result as DfResult};
use datafusion::execution::memory_pool::{
    MemoryConsumer, MemoryLimit, MemoryPool, MemoryReservation,
};

/// Wraps the shared aggregate [`MemoryPool`] and rejects growth that would
/// exceed `quota_bytes` for this run, while delegating every grant to the parent.
#[derive(Debug)]
pub struct RunQuotaPool {
    parent: Arc<dyn MemoryPool>,
    quota_bytes: usize,
    reserved: AtomicUsize,
    peak: AtomicUsize,
}

impl RunQuotaPool {
    pub fn new(parent: Arc<dyn MemoryPool>, quota_bytes: usize) -> Self {
        Self {
            parent,
            quota_bytes: quota_bytes.max(1),
            reserved: AtomicUsize::new(0),
            peak: AtomicUsize::new(0),
        }
    }

    pub fn parent(&self) -> &Arc<dyn MemoryPool> {
        &self.parent
    }

    pub fn quota_bytes(&self) -> usize {
        self.quota_bytes
    }

    pub fn reserved_bytes(&self) -> usize {
        self.reserved.load(Ordering::Acquire)
    }

    pub fn peak_reserved_bytes(&self) -> usize {
        self.peak.load(Ordering::Acquire)
    }

    fn record_grow(&self, additional: usize) {
        let next = self.reserved.fetch_add(additional, Ordering::AcqRel) + additional;
        self.peak.fetch_max(next, Ordering::AcqRel);
    }

    fn record_shrink(&self, shrink: usize) {
        let _ = self
            .reserved
            .try_update(Ordering::AcqRel, Ordering::Acquire, |cur| {
                Some(cur.saturating_sub(shrink))
            });
    }
}

impl Display for RunQuotaPool {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "run_quota(quota={}, reserved={}, parent={})",
            self.quota_bytes,
            self.reserved_bytes(),
            self.parent
        )
    }
}

impl MemoryPool for RunQuotaPool {
    fn name(&self) -> &str {
        "run_quota"
    }

    fn register(&self, consumer: &MemoryConsumer) {
        self.parent.register(consumer);
    }

    fn unregister(&self, consumer: &MemoryConsumer) {
        self.parent.unregister(consumer);
    }

    fn grow(&self, reservation: &MemoryReservation, additional: usize) {
        // Infallible path: still honor quota best-effort by growing parent;
        // try_grow is the fail-closed path used by operators.
        self.record_grow(additional);
        self.parent.grow(reservation, additional);
    }

    fn shrink(&self, reservation: &MemoryReservation, shrink: usize) {
        self.record_shrink(shrink);
        self.parent.shrink(reservation, shrink);
    }

    fn try_grow(&self, reservation: &MemoryReservation, additional: usize) -> DfResult<()> {
        // Reserve against the run quota first (CAS), then charge the aggregate
        // parent. Roll back the local reservation if the parent rejects.
        let mut cur = self.reserved.load(Ordering::Acquire);
        loop {
            let next = cur
                .checked_add(additional)
                .ok_or_else(|| internal_datafusion_err!("run quota reservation overflow"))?;
            if next > self.quota_bytes {
                return Err(internal_datafusion_err!(
                    "Resources exhausted: failed to allocate additional {} bytes for {} with {} bytes currently allocated for this run — run exceeds per-request quota of {} bytes (OPENFDD_QUERY_MEMORY_MB / resolved query_memory_bytes). Aggregate FairSpillPool may still have capacity for siblings.",
                    additional,
                    reservation.consumer().name(),
                    cur,
                    self.quota_bytes
                ));
            }
            match self
                .reserved
                .compare_exchange(cur, next, Ordering::AcqRel, Ordering::Acquire)
            {
                Ok(_) => {
                    self.peak.fetch_max(next, Ordering::AcqRel);
                    break;
                }
                Err(observed) => cur = observed,
            }
        }
        if let Err(err) = self.parent.try_grow(reservation, additional) {
            self.record_shrink(additional);
            return Err(err);
        }
        Ok(())
    }

    fn reserved(&self) -> usize {
        self.reserved_bytes()
    }

    fn memory_limit(&self) -> MemoryLimit {
        MemoryLimit::Finite(self.quota_bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use datafusion::execution::memory_pool::GreedyMemoryPool;

    #[test]
    fn run_quota_rejects_growth_above_quota_without_starving_parent_siblings() {
        let parent = Arc::new(GreedyMemoryPool::new(64 * 1024 * 1024));
        let run_a = Arc::new(RunQuotaPool::new(
            Arc::clone(&parent) as Arc<dyn MemoryPool>,
            8 * 1024 * 1024,
        ));
        let run_b = Arc::new(RunQuotaPool::new(
            Arc::clone(&parent) as Arc<dyn MemoryPool>,
            8 * 1024 * 1024,
        ));

        let pool_a: Arc<dyn MemoryPool> = Arc::clone(&run_a) as _;
        let pool_b: Arc<dyn MemoryPool> = Arc::clone(&run_b) as _;

        let res_a = MemoryConsumer::new("sort-a").register(&pool_a);
        let err = res_a.try_grow(9 * 1024 * 1024).unwrap_err().to_string();
        assert!(
            err.contains("per-request quota") || err.contains("Resources exhausted"),
            "unexpected: {err}"
        );
        assert_eq!(run_a.reserved_bytes(), 0);

        let res_b = MemoryConsumer::new("sibling").register(&pool_b);
        res_b.try_grow(4 * 1024 * 1024).unwrap();
        assert_eq!(run_b.reserved_bytes(), 4 * 1024 * 1024);
        assert_eq!(parent.reserved(), 4 * 1024 * 1024);
    }
}
