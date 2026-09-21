//! Runtime coordinator that serializes H4 compaction against DataFusion scans.
//!
//! Local filesystems cannot atomically swap an arbitrary set of Parquet parts
//! for one compacted replacement. Overlapping a DataFusion scan with
//! retire-then-publish creates a short read gap; publish-then-retire creates a
//! duplicate-row window. This coordinator enforces mutual exclusion:
//!
//! - many concurrent **scan** permits, **or**
//! - one exclusive **compact** permit,
//!
//! never both. Callers may **fail closed** (`try_*`) or **wait** (`*_wait`).

use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use serde::Serialize;

#[derive(Debug, Default)]
struct CoordState {
    scanners: u32,
    compacting: bool,
}

/// Process-wide historian IO fence for local Parquet compaction vs DF reads.
#[derive(Debug)]
pub struct CompactionCoordinator {
    state: Mutex<CoordState>,
    cv: Condvar,
}

/// Snapshot for admin/capacity surfaces.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CompactionCoordinatorStatus {
    pub scanners: u32,
    pub compacting: bool,
    pub mode: &'static str,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HistorianIoBusy {
    CompactionInProgress,
    ScansInProgress { scanners: u32 },
}

impl std::fmt::Display for HistorianIoBusy {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::CompactionInProgress => {
                write!(f, "historian compaction in progress; scan refused")
            }
            Self::ScansInProgress { scanners } => {
                write!(
                    f,
                    "historian DataFusion scan(s) in progress ({scanners}); compaction refused"
                )
            }
        }
    }
}

impl std::error::Error for HistorianIoBusy {}

/// RAII scan (shared) lease. Drop releases the slot and wakes waiters.
#[derive(Debug)]
pub struct ScanPermit {
    coord: Arc<CompactionCoordinator>,
}

/// RAII compaction (exclusive) lease. Drop clears the compacting flag.
#[derive(Debug)]
pub struct CompactPermit {
    coord: Arc<CompactionCoordinator>,
}

impl CompactionCoordinator {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new(CoordState::default()),
            cv: Condvar::new(),
        })
    }

    pub fn status(self: &Arc<Self>) -> CompactionCoordinatorStatus {
        let state = self.state.lock().expect("compaction coordinator poisoned");
        CompactionCoordinatorStatus {
            scanners: state.scanners,
            compacting: state.compacting,
            mode: if state.compacting {
                "compacting"
            } else if state.scanners > 0 {
                "scanning"
            } else {
                "idle"
            },
        }
    }

    /// Fail closed: refuse a scan while compaction holds the exclusive lease.
    pub fn try_begin_scan(self: &Arc<Self>) -> Result<ScanPermit, HistorianIoBusy> {
        let mut state = self.state.lock().expect("compaction coordinator poisoned");
        if state.compacting {
            return Err(HistorianIoBusy::CompactionInProgress);
        }
        state.scanners = state.scanners.saturating_add(1);
        Ok(ScanPermit {
            coord: Arc::clone(self),
        })
    }

    /// Wait until compaction finishes, then take a scan lease.
    pub fn begin_scan_wait(self: &Arc<Self>) -> ScanPermit {
        let mut state = self.state.lock().expect("compaction coordinator poisoned");
        while state.compacting {
            state = self
                .cv
                .wait(state)
                .expect("compaction coordinator poisoned");
        }
        state.scanners = state.scanners.saturating_add(1);
        ScanPermit {
            coord: Arc::clone(self),
        }
    }

    /// Fail closed: refuse compaction while any scan lease is held.
    pub fn try_begin_compact(self: &Arc<Self>) -> Result<CompactPermit, HistorianIoBusy> {
        let mut state = self.state.lock().expect("compaction coordinator poisoned");
        if state.compacting {
            return Err(HistorianIoBusy::CompactionInProgress);
        }
        if state.scanners > 0 {
            return Err(HistorianIoBusy::ScansInProgress {
                scanners: state.scanners,
            });
        }
        state.compacting = true;
        Ok(CompactPermit {
            coord: Arc::clone(self),
        })
    }

    /// Wait until all scanners drain, then take the exclusive compaction lease.
    pub fn begin_compact_wait(self: &Arc<Self>) -> CompactPermit {
        let mut state = self.state.lock().expect("compaction coordinator poisoned");
        while state.compacting || state.scanners > 0 {
            state = self
                .cv
                .wait(state)
                .expect("compaction coordinator poisoned");
        }
        state.compacting = true;
        CompactPermit {
            coord: Arc::clone(self),
        }
    }

    /// Wait up to `timeout` for an exclusive compaction lease; else fail closed.
    pub fn try_begin_compact_timeout(
        self: &Arc<Self>,
        timeout: Duration,
    ) -> Result<CompactPermit, HistorianIoBusy> {
        let deadline = Instant::now() + timeout;
        let mut state = self.state.lock().expect("compaction coordinator poisoned");
        loop {
            if !state.compacting && state.scanners == 0 {
                state.compacting = true;
                return Ok(CompactPermit {
                    coord: Arc::clone(self),
                });
            }
            let now = Instant::now();
            if now >= deadline {
                return if state.compacting {
                    Err(HistorianIoBusy::CompactionInProgress)
                } else {
                    Err(HistorianIoBusy::ScansInProgress {
                        scanners: state.scanners,
                    })
                };
            }
            let wait = deadline.saturating_duration_since(now);
            let (next, _) = self
                .cv
                .wait_timeout(state, wait)
                .expect("compaction coordinator poisoned");
            state = next;
        }
    }
}

impl Drop for ScanPermit {
    fn drop(&mut self) {
        let mut state = self
            .coord
            .state
            .lock()
            .expect("compaction coordinator poisoned");
        state.scanners = state.scanners.saturating_sub(1);
        self.coord.cv.notify_all();
    }
}

impl Drop for CompactPermit {
    fn drop(&mut self) {
        let mut state = self
            .coord
            .state
            .lock()
            .expect("compaction coordinator poisoned");
        state.compacting = false;
        self.coord.cv.notify_all();
    }
}

static SHARED: OnceLock<Arc<CompactionCoordinator>> = OnceLock::new();

/// Process-global coordinator (one local historian per Central/CLI process).
pub fn shared_compaction_coordinator() -> Arc<CompactionCoordinator> {
    SHARED.get_or_init(CompactionCoordinator::new).clone()
}

/// Run compaction under an exclusive coordinator lease (fail closed if busy).
pub fn compact_history_fail_closed(
    compactor: &crate::ParquetCompactor,
) -> Result<(Vec<crate::CompactionResult>, crate::CompactionSummary)> {
    let coord = shared_compaction_coordinator();
    let _permit = coord
        .try_begin_compact()
        .map_err(|busy| anyhow::anyhow!(busy))?;
    compactor.compact_history()
}

/// Run compaction after waiting for scanners to drain.
pub fn compact_history_wait(
    compactor: &crate::ParquetCompactor,
) -> Result<(Vec<crate::CompactionResult>, crate::CompactionSummary)> {
    let coord = shared_compaction_coordinator();
    let _permit = coord.begin_compact_wait();
    compactor.compact_history()
}

/// Acquire a fail-closed scan lease for DataFusion work against the historian.
pub fn try_historian_scan_permit() -> Result<ScanPermit> {
    shared_compaction_coordinator()
        .try_begin_scan()
        .map_err(|busy| anyhow::anyhow!(busy))
}

/// Acquire a waiting scan lease (blocks while compaction runs).
pub fn historian_scan_permit_wait() -> ScanPermit {
    shared_compaction_coordinator().begin_scan_wait()
}

/// Refuse overlapping scan+compact without waiting (operator honesty helper).
pub fn assert_compaction_safe_for_offline() -> Result<()> {
    let status = shared_compaction_coordinator().status();
    if status.scanners > 0 || status.compacting {
        bail!(
            "historian IO busy (mode={}, scanners={}); stop DataFusion scans before offline H4",
            status.mode,
            status.scanners
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Barrier;
    use std::thread;
    use std::time::Duration;

    #[test]
    fn concurrent_scan_and_compact_fails_closed() {
        let coord = CompactionCoordinator::new();
        let scan = coord.try_begin_scan().expect("scan should start");
        let busy = coord
            .try_begin_compact()
            .expect_err("compact must refuse while scanning");
        assert!(matches!(
            busy,
            HistorianIoBusy::ScansInProgress { scanners: 1 }
        ));
        drop(scan);
        let compact = coord.try_begin_compact().expect("compact after scan drop");
        let scan_busy = coord
            .try_begin_scan()
            .expect_err("scan must refuse while compacting");
        assert_eq!(scan_busy, HistorianIoBusy::CompactionInProgress);
        drop(compact);
        let _ = coord.try_begin_scan().expect("scan after compact drop");
    }

    #[test]
    fn multiple_scans_allowed_until_compact() {
        let coord = CompactionCoordinator::new();
        let a = coord.try_begin_scan().unwrap();
        let b = coord.try_begin_scan().unwrap();
        assert_eq!(coord.status().scanners, 2);
        assert!(coord.try_begin_compact().is_err());
        drop(a);
        drop(b);
        assert_eq!(coord.status().mode, "idle");
    }

    #[test]
    fn compact_wait_unblocks_after_scan_drains() {
        let coord = CompactionCoordinator::new();
        let barrier = Arc::new(Barrier::new(2));
        let scan_hold = coord.try_begin_scan().unwrap();

        let coord_bg = Arc::clone(&coord);
        let barrier_bg = Arc::clone(&barrier);
        let handle = thread::spawn(move || {
            barrier_bg.wait();
            let permit = coord_bg.begin_compact_wait();
            drop(permit);
        });

        barrier.wait();
        thread::sleep(Duration::from_millis(50));
        assert!(coord.status().compacting || coord.status().scanners > 0);
        drop(scan_hold);
        handle.join().expect("compact wait thread");
        assert_eq!(coord.status().mode, "idle");
    }

    #[test]
    fn try_compact_timeout_fails_while_scan_held() {
        let coord = CompactionCoordinator::new();
        let _scan = coord.try_begin_scan().unwrap();
        let err = coord
            .try_begin_compact_timeout(Duration::from_millis(30))
            .expect_err("timeout must fail closed");
        assert!(matches!(err, HistorianIoBusy::ScansInProgress { .. }));
    }
}
