//! In-flight cgroup memory sampler for heavy requests (#1179 / Soft-OPEN 370 T1b).
//!
//! Samples `memory.current` at `OPENFDD_MEMORY_SAMPLE_MS` (default 1000 ms)
//! while a heavy request is live; sets the request cancel flag when usage
//! crosses the abort fraction or when slope projects crossing abort before the
//! next sample.
//!
//! Cancellation authority is an explicit [`CancelToken`] owned by [`InFlightGuard`]
//! and passed into workers — not a thread-local slot. Drop stops and aborts the
//! watchdog so successful requests do not leak detached samplers (M70-01).

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tokio::task::JoinHandle;

use crate::cgroup::discover_capacity;
use crate::pressure::{evaluate_pressure, ShedState};

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct MemoryTrip {
    pub class: String,
    pub current_bytes: u64,
    pub reason: String,
    /// Wall-clock milliseconds since UNIX epoch when the trip was recorded.
    pub at_ms: u128,
}

static LAST_TRIP: OnceLock<Mutex<Option<MemoryTrip>>> = OnceLock::new();
static ACTIVE_TOKENS: OnceLock<Mutex<Vec<Arc<AtomicBool>>>> = OnceLock::new();

fn last_trip_lock() -> &'static Mutex<Option<MemoryTrip>> {
    LAST_TRIP.get_or_init(|| Mutex::new(None))
}

fn active_tokens() -> &'static Mutex<Vec<Arc<AtomicBool>>> {
    ACTIVE_TOKENS.get_or_init(|| Mutex::new(Vec::new()))
}

pub fn last_memory_trip() -> Option<MemoryTrip> {
    last_trip_lock().lock().ok().and_then(|g| g.clone())
}

/// Explicit cancel token shared across async tasks and blocking workers.
#[derive(Debug, Clone)]
pub struct CancelToken {
    cancel: Arc<AtomicBool>,
}

impl CancelToken {
    pub fn new() -> Self {
        Self {
            cancel: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn flag(&self) -> Arc<AtomicBool> {
        self.cancel.clone()
    }

    pub fn request_cancel(&self) {
        self.cancel.store(true, Ordering::SeqCst);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancel.load(Ordering::SeqCst)
    }
}

impl Default for CancelToken {
    fn default() -> Self {
        Self::new()
    }
}

/// Best-effort: true if **any** registered in-flight cancel token is set.
/// Prefer passing [`CancelToken`] / [`InFlightGuard::cancel_flag`] explicitly.
pub fn memory_abort_requested() -> bool {
    active_tokens()
        .lock()
        .ok()
        .map(|tokens| tokens.iter().any(|f| f.load(Ordering::SeqCst)))
        .unwrap_or(false)
}

/// Compatibility helper: first registered cancel flag, if any.
pub fn active_cancel_flag() -> Option<Arc<AtomicBool>> {
    active_tokens()
        .lock()
        .ok()
        .and_then(|tokens| tokens.last().cloned())
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

fn wall_clock_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

fn record_trip(class: &str, current: u64, reason: impl Into<String>) {
    let trip = MemoryTrip {
        class: class.to_string(),
        current_bytes: current,
        reason: reason.into(),
        at_ms: wall_clock_ms(),
    };
    if let Ok(mut g) = last_trip_lock().lock() {
        *g = Some(trip);
    }
}

fn register_token(flag: &Arc<AtomicBool>) {
    if let Ok(mut tokens) = active_tokens().lock() {
        tokens.push(flag.clone());
    }
}

fn unregister_token(flag: &Arc<AtomicBool>) {
    if let Ok(mut tokens) = active_tokens().lock() {
        if let Some(pos) = tokens.iter().rposition(|t| Arc::ptr_eq(t, flag)) {
            tokens.remove(pos);
        }
    }
}

/// Guard that polls cgroup memory while held; stops its watchdog on drop.
pub struct InFlightGuard {
    token: CancelToken,
    stop: Arc<AtomicBool>,
    watchdog: Option<JoinHandle<()>>,
}

impl InFlightGuard {
    pub fn spawn(class: impl Into<String>) -> Self {
        let class = class.into();
        let token = CancelToken::new();
        let cancel = token.flag();
        register_token(&cancel);
        let stop = Arc::new(AtomicBool::new(false));
        let cancel_watch = cancel.clone();
        let stop_watch = stop.clone();
        let class_watch = class.clone();
        let interval = Duration::from_millis(sample_interval_ms());
        let watchdog = tokio::spawn(async move {
            let mut prev_current: Option<u64> = None;
            let mut prev_at = Instant::now();
            loop {
                if stop_watch.load(Ordering::SeqCst) || cancel_watch.load(Ordering::SeqCst) {
                    break;
                }
                tokio::time::sleep(interval).await;
                if stop_watch.load(Ordering::SeqCst) || cancel_watch.load(Ordering::SeqCst) {
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
            token,
            stop,
            watchdog: Some(watchdog),
        }
    }

    pub fn cancel_token(&self) -> CancelToken {
        self.token.clone()
    }

    pub fn cancel_flag(&self) -> Arc<AtomicBool> {
        self.token.flag()
    }

    pub fn request_cancel(&self) {
        self.token.request_cancel();
    }

    pub fn is_cancelled(&self) -> bool {
        self.token.is_cancelled()
    }
}

impl Drop for InFlightGuard {
    fn drop(&mut self) {
        // Stop the sampler without implying a memory trip on normal completion.
        self.stop.store(true, Ordering::SeqCst);
        unregister_token(&self.token.flag());
        if let Some(handle) = self.watchdog.take() {
            handle.abort();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // ACTIVE_TOKENS is process-global; serialize lifecycle tests against
    // parallel cargo test workers (CI failed nested_guards when interleaved).
    static LIFECYCLE_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn sample_ms_default_is_one_second() {
        std::env::remove_var("OPENFDD_MEMORY_SAMPLE_MS");
        assert_eq!(memory_sample_ms(), 1000);
    }

    #[test]
    fn wall_clock_trip_timestamp_is_nonzero() {
        record_trip("test", 1, "unit");
        let trip = last_memory_trip().expect("trip");
        assert!(trip.at_ms > 1_700_000_000_000, "at_ms={}", trip.at_ms);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn drop_unregisters_token_and_stops_watchdog() {
        let _lock = LIFECYCLE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let g = InFlightGuard::spawn("lifecycle_test");
        let flag = g.cancel_flag();
        assert!(active_cancel_flag().is_some());
        assert!(!g.is_cancelled());
        drop(g);
        // Token must leave the registry so ambient abort does not stick.
        assert!(!flag.load(Ordering::SeqCst));
        assert!(!memory_abort_requested());
    }

    #[tokio::test(flavor = "current_thread")]
    async fn nested_guards_unregister_only_own_token() {
        let _lock = LIFECYCLE_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let outer = InFlightGuard::spawn("outer");
        let outer_flag = outer.cancel_flag();
        let inner = InFlightGuard::spawn("inner");
        let inner_flag = inner.cancel_flag();
        inner.request_cancel();
        assert!(inner_flag.load(Ordering::SeqCst));
        assert!(memory_abort_requested());
        drop(inner);
        // Outer still registered; its flag is still false.
        assert!(!outer_flag.load(Ordering::SeqCst));
        assert!(!outer.is_cancelled());
        assert!(!memory_abort_requested());
        drop(outer);
        assert!(!memory_abort_requested());
    }
}
