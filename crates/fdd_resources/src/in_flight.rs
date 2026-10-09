//! In-flight cgroup memory sampler for heavy requests (#1179 S1).
//!
//! Samples `memory.current` at `OPENFDD_MEMORY_SAMPLE_MS` (default 1000 ms)
//! while a heavy request is live; sets the request cancel flag when usage
//! crosses the abort fraction or when slope projects crossing abort before the
//! next sample.

use std::cell::RefCell;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::Serialize;
use tokio::task::JoinHandle;

use crate::cgroup::discover_capacity;
use crate::pressure::{evaluate_pressure, ShedState};

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct MemoryTrip {
    pub class: String,
    pub current_bytes: u64,
    pub reason: String,
    pub at_ms: u128,
}

static LAST_TRIP: OnceLock<Mutex<Option<MemoryTrip>>> = OnceLock::new();

fn last_trip_lock() -> &'static Mutex<Option<MemoryTrip>> {
    LAST_TRIP.get_or_init(|| Mutex::new(None))
}

pub fn last_memory_trip() -> Option<MemoryTrip> {
    last_trip_lock().lock().ok().and_then(|g| g.clone())
}

thread_local! {
    static ACTIVE_CANCEL: RefCell<Option<Arc<AtomicBool>>> = const { RefCell::new(None) };
}

/// Cancel flag for the in-flight heavy request on this async task, if any.
pub fn active_cancel_flag() -> Option<Arc<AtomicBool>> {
    ACTIVE_CANCEL.with(|slot| slot.borrow().clone())
}

pub fn memory_abort_requested() -> bool {
    active_cancel_flag()
        .is_some_and(|f| f.load(Ordering::SeqCst))
}

fn sample_interval_ms() -> u64 {
    std::env::var("OPENFDD_MEMORY_SAMPLE_MS")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|v| *v >= 100 && *v <= 5000)
        .unwrap_or(1000)
}

pub fn memory_sample_ms() -> u64 {
    sample_interval_ms()
}

fn record_trip(class: &str, current: u64, reason: impl Into<String>) {
    let trip = MemoryTrip {
        class: class.to_string(),
        current_bytes: current,
        reason: reason.into(),
        at_ms: Instant::now().elapsed().as_millis(),
    };
    if let Ok(mut g) = last_trip_lock().lock() {
        *g = Some(trip);
    }
}

/// Guard that polls cgroup memory while held; drops cancel flag on the task.
pub struct InFlightGuard {
    cancel: Arc<AtomicBool>,
    _watchdog: JoinHandle<()>,
}

impl InFlightGuard {
    pub fn spawn(class: impl Into<String>) -> Self {
        let class = class.into();
        let cancel = Arc::new(AtomicBool::new(false));
        ACTIVE_CANCEL.with(|slot| {
            *slot.borrow_mut() = Some(cancel.clone());
        });
        let cancel_watch = cancel.clone();
        let class_watch = class.clone();
        let interval = Duration::from_millis(sample_interval_ms());
        let watchdog = tokio::spawn(async move {
            let mut prev_current: Option<u64> = None;
            let mut prev_at = Instant::now();
            loop {
                if cancel_watch.load(Ordering::SeqCst) {
                    break;
                }
                tokio::time::sleep(interval).await;
                if cancel_watch.load(Ordering::SeqCst) {
                    break;
                }
                let discovery = discover_capacity();
                let pressure = evaluate_pressure(&discovery);
                let current = pressure.current_bytes.unwrap_or(0);
                let now = Instant::now();
                if pressure.shed_state == ShedState::Abort {
                    record_trip(
                        &class_watch,
                        current,
                        format!("memory.current >= abort threshold ({current} bytes)"),
                    );
                    tracing::warn!(
                        target: "security_audit",
                        event = "memory_abort",
                        class = %class_watch,
                        current_bytes = current,
                        shed_state = ?pressure.shed_state,
                        "in-flight memory watchdog tripped abort"
                    );
                    cancel_watch.store(true, Ordering::SeqCst);
                    break;
                }
                if let (Some(prev), Some(abort_bytes)) = (prev_current, pressure.abort_bytes) {
                    let dt = now.duration_since(prev_at).as_secs_f64().max(0.001);
                    let rate = (current.saturating_sub(prev)) as f64 / dt;
                    if rate > 0.0 {
                        let headroom = abort_bytes.saturating_sub(current) as f64;
                        let secs_to_abort = headroom / rate;
                        if secs_to_abort <= (interval.as_secs_f64() * 2.0) {
                            record_trip(
                                &class_watch,
                                current,
                                format!(
                                    "allocation slope projects abort within {:.1}s (rate {rate:.0} B/s)",
                                    secs_to_abort
                                ),
                            );
                            tracing::warn!(
                                target: "security_audit",
                                event = "memory_abort",
                                class = %class_watch,
                                current_bytes = current,
                                projected_secs = secs_to_abort,
                                "in-flight slope abort"
                            );
                            cancel_watch.store(true, Ordering::SeqCst);
                            break;
                        }
                    }
                }
                prev_current = Some(current);
                prev_at = now;
            }
        });
        Self {
            cancel,
            _watchdog: watchdog,
        }
    }

    pub fn cancel_flag(&self) -> Arc<AtomicBool> {
        self.cancel.clone()
    }
}

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        ACTIVE_CANCEL.with(|slot| {
            *slot.borrow_mut() = None;
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sample_ms_default_is_one_second() {
        std::env::remove_var("OPENFDD_MEMORY_SAMPLE_MS");
        assert_eq!(memory_sample_ms(), 1000);
    }
}
