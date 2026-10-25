//! Security audit log for operator review (no secrets).
//!
//! Dual sink:
//! - One JSONL file under `$OPENFDD_WORKSPACE/logs/security_audit.jsonl`
//!   (size-rotated; written on a dedicated std thread via a bounded queue)
//! - `tracing` target `security_audit` so a platform log scraper can read stdout
//!
//! Durability (`openfdd.audit.durability.v1`):
//! - Acknowledged mutations and denials fsync the JSONL line before
//!   [`log_event_acknowledged`] returns. SIGINT and SIGTERM stop admission,
//!   wait for in-flight enqueues, drain the writer, and fsync within a deadline.
//! - Best-effort lines (successful reads) are written without a per-line fsync.
//!   Graceful shutdown flushes them. They are not an acknowledged record.
//! - A hard kill (SIGKILL, power loss) can drop the line inside the current
//!   `write`/`fsync` and any best-effort lines not yet flushed. That residual
//!   window is not a graceful-shutdown guarantee. There is no second durable
//!   outbox for this file.
//! - Queue overflow drops best-effort lines immediately and, after a bounded
//!   wait, acknowledged lines. Both increment the loss ledger. Best-effort
//!   bursts sample the file and fsync it on shutdown. An acknowledged loss
//!   fsyncs before return. `degraded` stays set while a drop or write failure
//!   is recorded. A later successful write clears `last_write_error` only.
//! - Stdout is a second copy for scrapers. It is not the durability boundary.
//! - Retention is size rotation (`OPENFDD_AUDIT_LOG_MAX_BYTES`,
//!   `OPENFDD_AUDIT_LOG_KEEP`). Removing a generation increments `rotated_out`.
//!   [`export_retained`] copies the files still on disk plus the loss ledger.
//!
//! Env (copied onto each queued line; a later change does not retarget that line):
//! - `OPENFDD_AUDIT_LOG_PATH` — override file path (default `workspace/logs/security_audit.jsonl`)
//! - `OPENFDD_AUDIT_LOG_MAX_BYTES` — rotate threshold (default 10485760 = 10 MiB)
//! - `OPENFDD_AUDIT_LOG_KEEP` — rotated files to keep (default 5)
//! - `OPENFDD_AUDIT_QUEUE_CAP` — bounded enqueue capacity (default 1024, clamped 32..=16384)
//! - `OPENFDD_AUDIT_ACK_MS` — acknowledged enqueue wait (default 2000, clamped 50..=5000)

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
#[cfg(test)]
use std::sync::mpsc::TryRecvError;
use std::sync::mpsc::{sync_channel, Receiver, RecvTimeoutError, SyncSender, TrySendError};
use std::sync::Mutex;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

/// Stable write-failure codes for `/api/health` (never a path or payload).
pub const ERR_UNWRITABLE: &str = "unwritable";
pub const ERR_IO: &str = "io";

/// Ledger schema written beside the JSONL file.
pub const LOSS_SCHEMA: &str = "openfdd.audit.loss.v1";
/// Export directory schema.
pub const EXPORT_SCHEMA: &str = "openfdd.audit.export.v1";

const DEFAULT_QUEUE_CAP: usize = 1024;
const MIN_QUEUE_CAP: usize = 32;
const MAX_QUEUE_CAP: usize = 16_384;
const DEFAULT_ACK: Duration = Duration::from_millis(2000);
const MAX_LOST_IDS: usize = 64;

static ADMISSION_OPEN: AtomicBool = AtomicBool::new(true);
static IN_FLIGHT: AtomicU64 = AtomicU64::new(0);
static SINK: Mutex<Option<AuditSink>> = Mutex::new(None);
static LEDGER: std::sync::OnceLock<Mutex<LossLedger>> = std::sync::OnceLock::new();
/// Serializes env-mutating unit tests that share process-global sink state.
#[cfg(test)]
static TEST_LOCK: std::sync::OnceLock<Mutex<()>> = std::sync::OnceLock::new();

struct AuditSink {
    tx: SyncSender<WriterCmd>,
    thread: Option<JoinHandle<()>>,
}

struct QueuedLine {
    body: String,
    /// Destination captured on the caller. The writer must not re-read the
    /// process environment: another test or request may already have changed it.
    path: PathBuf,
    max_bytes: u64,
    keep: usize,
    durable: bool,
    ack: Option<SyncSender<bool>>,
}

enum WriterCmd {
    Line(Box<QueuedLine>),
    /// Barrier: writer replies after every earlier `Line` has been written (or failed).
    Flush(SyncSender<()>),
    Shutdown(SyncSender<()>),
}

impl Drop for AuditSink {
    fn drop(&mut self) {
        // Best-effort stop. Never join: the writer can block on an unwritable
        // path or FIFO open; detaching keeps reset/tests from hanging.
        let _ = self.tx.try_send(WriterCmd::Shutdown(sync_channel(1).0));
        let _ = self.thread.take();
    }
}

fn default_loss_schema() -> String {
    LOSS_SCHEMA.to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LossLedger {
    #[serde(default = "default_loss_schema")]
    schema: String,
    #[serde(default)]
    dropped_queue: u64,
    #[serde(default)]
    dropped_shutdown: u64,
    #[serde(default)]
    write_failures: u64,
    #[serde(default)]
    rotated_out: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    last_write_error: Option<String>,
    #[serde(default)]
    lost_request_ids: Vec<String>,
}

impl LossLedger {
    fn empty() -> Self {
        Self {
            schema: LOSS_SCHEMA.to_string(),
            dropped_queue: 0,
            dropped_shutdown: 0,
            write_failures: 0,
            rotated_out: 0,
            last_write_error: None,
            lost_request_ids: Vec::new(),
        }
    }

    fn is_blank(&self) -> bool {
        self.dropped_queue == 0
            && self.dropped_shutdown == 0
            && self.write_failures == 0
            && self.rotated_out == 0
            && self.last_write_error.is_none()
            && self.lost_request_ids.is_empty()
    }

    fn degraded(&self) -> bool {
        self.last_write_error.is_some()
            || self.dropped_queue > 0
            || self.dropped_shutdown > 0
            || self.write_failures > 0
    }
}

/// Snapshot for central `/api/health` (`audit_sink`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditSinkStatus {
    /// True after a dropped enqueue or a writer I/O failure.
    /// Stays true while those counters are non-zero. A later successful write
    /// clears `last_write_error` only.
    pub degraded: bool,
    /// Best-effort or acknowledged events dropped because the queue was full.
    /// Reloaded from the loss ledger after process restart.
    pub dropped: u64,
    /// Events refused because shutdown had already closed admission.
    pub dropped_shutdown: u64,
    /// Writer failures (unwritable path or I/O).
    pub write_failures: u64,
    /// Events removed when a rotated generation exceeded the keep count.
    pub rotated_out: u64,
    /// Short stable code when the last write failed (`unwritable` | `io`), else null.
    pub last_write_error: Option<&'static str>,
}

/// Result of [`shutdown_for_signal`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ShutdownReport {
    pub signal: &'static str,
    pub drained: bool,
    pub timed_out: bool,
}

/// Request ids found in retained JSONL files versus the caller’s list.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Reconciliation {
    pub present: Vec<String>,
    pub missing: Vec<String>,
    /// Missing ids that the loss ledger recorded when an acknowledged write did not land.
    pub missing_recorded_as_loss: Vec<String>,
}

/// Files copied by [`export_retained`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AuditExport {
    pub schema: &'static str,
    pub files_copied: usize,
    pub events: u64,
    pub dropped_queue: u64,
    pub dropped_shutdown: u64,
    pub write_failures: u64,
    pub rotated_out: u64,
}

/// Current file-sink health. Counters are the in-memory ledger, which is
/// reloaded from disk when the writer starts.
pub fn sink_status() -> AuditSinkStatus {
    let ledger = ledger_lock();
    AuditSinkStatus {
        degraded: ledger.degraded(),
        dropped: ledger.dropped_queue,
        dropped_shutdown: ledger.dropped_shutdown,
        write_failures: ledger.write_failures,
        rotated_out: ledger.rotated_out,
        last_write_error: static_code(ledger.last_write_error.as_deref()),
    }
}

fn static_code(code: Option<&str>) -> Option<&'static str> {
    match code {
        Some(ERR_UNWRITABLE) => Some(ERR_UNWRITABLE),
        Some(_) => Some(ERR_IO),
        None => None,
    }
}

fn ledger_lock() -> std::sync::MutexGuard<'static, LossLedger> {
    LEDGER
        .get_or_init(|| Mutex::new(LossLedger::empty()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn sink_lock() -> std::sync::MutexGuard<'static, Option<AuditSink>> {
    SINK.lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn audit_log_path() -> PathBuf {
    if let Ok(p) = std::env::var("OPENFDD_AUDIT_LOG_PATH") {
        let trimmed = p.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
    std::env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
        .join("logs")
        .join("security_audit.jsonl")
}

fn loss_path_for(audit: &Path) -> PathBuf {
    audit.with_file_name("security_audit.loss.json")
}

fn loss_path() -> PathBuf {
    loss_path_for(&audit_log_path())
}

fn max_bytes() -> u64 {
    std::env::var("OPENFDD_AUDIT_LOG_MAX_BYTES")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(10 * 1024 * 1024)
}

fn keep_count() -> usize {
    std::env::var("OPENFDD_AUDIT_LOG_KEEP")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(5)
        .clamp(1, 32)
}

fn queue_capacity() -> usize {
    std::env::var("OPENFDD_AUDIT_QUEUE_CAP")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(DEFAULT_QUEUE_CAP)
        .clamp(MIN_QUEUE_CAP, MAX_QUEUE_CAP)
}

fn ack_wait() -> Duration {
    std::env::var("OPENFDD_AUDIT_ACK_MS")
        .ok()
        .and_then(|s| s.parse().ok())
        .map(Duration::from_millis)
        .unwrap_or(DEFAULT_ACK)
        .clamp(Duration::from_millis(50), Duration::from_millis(5000))
}

fn load_ledger() -> LossLedger {
    let Ok(text) = fs::read_to_string(loss_path()) else {
        return LossLedger::empty();
    };
    serde_json::from_str(&text).unwrap_or_else(|_| LossLedger::empty())
}

fn persist_ledger_at(audit_path: &Path, ledger: &LossLedger, sync: bool) {
    let path = loss_path_for(audit_path);
    if let Some(parent) = path.parent() {
        if fs::create_dir_all(parent).is_err() {
            return;
        }
    }
    let Ok(body) = serde_json::to_vec(ledger) else {
        return;
    };
    let Ok(mut file) = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&path)
    else {
        return;
    };
    if file.write_all(&body).is_ok() && sync {
        let _ = file.sync_data();
    }
}

fn persist_ledger(ledger: &LossLedger, sync: bool) {
    persist_ledger_at(&audit_log_path(), ledger, sync);
}

fn mutate_ledger(update: impl FnOnce(&mut LossLedger)) {
    let mut ledger = ledger_lock();
    update(&mut ledger);
    persist_ledger(&ledger, true);
}

fn note_lost_id(ledger: &mut LossLedger, detail: &Value) {
    let Some(raw) = detail.get("request_id").and_then(Value::as_str) else {
        return;
    };
    let id = super::redact::bounded(raw, 64);
    if id.is_empty() || ledger.lost_request_ids.iter().any(|have| have == &id) {
        return;
    }
    ledger.lost_request_ids.insert(0, id);
    ledger.lost_request_ids.truncate(MAX_LOST_IDS);
}

fn set_write_error(code: &'static str) {
    mutate_ledger(|ledger| {
        ledger.write_failures = ledger.write_failures.saturating_add(1);
        ledger.last_write_error = Some(code.to_string());
    });
}

fn set_write_error_at(audit_path: &Path, code: &'static str) {
    let mut ledger = ledger_lock();
    ledger.write_failures = ledger.write_failures.saturating_add(1);
    ledger.last_write_error = Some(code.to_string());
    persist_ledger_at(audit_path, &ledger, true);
}

fn clear_write_error_at(audit_path: &Path) {
    let mut ledger = ledger_lock();
    if ledger.last_write_error.is_none() {
        return;
    }
    ledger.last_write_error = None;
    persist_ledger_at(audit_path, &ledger, true);
}

fn note_queue_drop(detail: &Value) {
    // Best-effort drops must not fsync on the caller. The loss file is sampled
    // during a burst and fsynced on shutdown or on an acknowledged loss.
    record_queue_drop(detail, false);
}

fn note_acknowledged_queue_drop(detail: &Value) {
    record_queue_drop(detail, true);
}

fn record_queue_drop(detail: &Value, sync: bool) {
    let n = {
        let mut ledger = ledger_lock();
        ledger.dropped_queue = ledger.dropped_queue.saturating_add(1);
        note_lost_id(&mut ledger, detail);
        let n = ledger.dropped_queue;
        if sync || n == 1 || n.is_multiple_of(64) {
            persist_ledger(&ledger, sync);
        }
        n
    };
    tracing::error!(
        target: "security_audit",
        alert = "audit_sink",
        dropped = n,
        "audit sink queue full; event dropped"
    );
}

fn note_shutdown_drop(detail: &Value) {
    let n = {
        let mut ledger = ledger_lock();
        ledger.dropped_shutdown = ledger.dropped_shutdown.saturating_add(1);
        note_lost_id(&mut ledger, detail);
        let n = ledger.dropped_shutdown;
        persist_ledger(&ledger, true);
        n
    };
    tracing::error!(
        target: "security_audit",
        alert = "audit_sink",
        dropped_shutdown = n,
        "audit sink closed; event dropped"
    );
}

fn note_rotated(audit_path: &Path, lines: u64) {
    if lines == 0 {
        return;
    }
    let mut ledger = ledger_lock();
    ledger.rotated_out = ledger.rotated_out.saturating_add(lines);
    persist_ledger_at(audit_path, &ledger, true);
}

fn enter() -> bool {
    if !ADMISSION_OPEN.load(Ordering::Acquire) {
        return false;
    }
    IN_FLIGHT.fetch_add(1, Ordering::AcqRel);
    if !ADMISSION_OPEN.load(Ordering::Acquire) {
        IN_FLIGHT.fetch_sub(1, Ordering::AcqRel);
        return false;
    }
    true
}

fn leave() {
    IN_FLIGHT.fetch_sub(1, Ordering::AcqRel);
}

enum SendWaitError {
    Timeout,
    Disconnected,
}

/// Poll interval for the acknowledged enqueue wait. `SyncSender::send_timeout`
/// is unstable, so the wait is a short park plus `try_send`.
const ACK_POLL: Duration = Duration::from_millis(5);

#[cfg(test)]
static MANUAL_ACK_WAIT: AtomicBool = AtomicBool::new(false);
#[cfg(test)]
static VIRTUAL_ACK_WAIT_NS: AtomicU64 = AtomicU64::new(0);

/// Virtual clock for [`send_until`] and the writer-reply wait.
///
/// Production code and every other test keep `Instant` and `thread::sleep`.
/// One test installs this so the ack budget is exact: a wall-clock cap also
/// counts ledger fsync time and scheduler delay on a loaded runner.
#[cfg(test)]
#[must_use]
struct ManualAckWait;

#[cfg(test)]
fn manual_ack_wait() -> ManualAckWait {
    VIRTUAL_ACK_WAIT_NS.store(0, Ordering::Release);
    MANUAL_ACK_WAIT.store(true, Ordering::Release);
    ManualAckWait
}

#[cfg(test)]
impl Drop for ManualAckWait {
    fn drop(&mut self) {
        MANUAL_ACK_WAIT.store(false, Ordering::Release);
    }
}

#[cfg(test)]
fn manual_ack_wait_active() -> bool {
    MANUAL_ACK_WAIT.load(Ordering::Acquire)
}

#[cfg(test)]
fn virtual_ack_wait_ns() -> u64 {
    VIRTUAL_ACK_WAIT_NS.load(Ordering::Acquire)
}

#[cfg(test)]
fn advance_manual_ack_wait(slice: Duration) {
    let add = u64::try_from(slice.as_nanos()).unwrap_or(u64::MAX);
    VIRTUAL_ACK_WAIT_NS.fetch_add(add, Ordering::AcqRel);
}

#[cfg(test)]
fn manual_ack_wait_elapsed() -> Duration {
    Duration::from_nanos(virtual_ack_wait_ns())
}

struct WaitOrigin {
    wall: Instant,
    #[cfg(test)]
    virtual_ns: u64,
}

fn wait_origin() -> WaitOrigin {
    WaitOrigin {
        wall: Instant::now(),
        #[cfg(test)]
        virtual_ns: virtual_ack_wait_ns(),
    }
}

fn wait_elapsed(origin: &WaitOrigin) -> Duration {
    #[cfg(test)]
    if manual_ack_wait_active() {
        return Duration::from_nanos(virtual_ack_wait_ns().saturating_sub(origin.virtual_ns));
    }
    origin.wall.elapsed()
}

fn wait_park(slice: Duration) {
    #[cfg(test)]
    if manual_ack_wait_active() {
        advance_manual_ack_wait(slice);
        return;
    }
    std::thread::sleep(slice);
}

/// Park one poll slice inside `budget`. `false` means the budget is spent.
fn park_within(origin: &WaitOrigin, budget: Duration) -> bool {
    let waited = wait_elapsed(origin);
    if waited >= budget {
        return false;
    }
    let slice = ACK_POLL.min(budget.saturating_sub(waited));
    if slice.is_zero() {
        return false;
    }
    wait_park(slice);
    true
}

/// `SyncSender::send_timeout` is unstable. Poll `try_send` until `budget` elapses.
fn send_until(
    tx: &SyncSender<WriterCmd>,
    mut value: WriterCmd,
    budget: Duration,
) -> Result<(), SendWaitError> {
    let origin = wait_origin();
    loop {
        match tx.try_send(value) {
            Ok(()) => return Ok(()),
            Err(TrySendError::Disconnected(_)) => return Err(SendWaitError::Disconnected),
            Err(TrySendError::Full(returned)) => {
                value = returned;
                if !park_within(&origin, budget) {
                    return Err(SendWaitError::Timeout);
                }
            }
        }
    }
}

fn recv_ack(rx: &Receiver<bool>, budget: Duration) -> Result<bool, RecvTimeoutError> {
    #[cfg(test)]
    if manual_ack_wait_active() {
        return recv_ack_virtual(rx, budget);
    }
    rx.recv_timeout(budget)
}

#[cfg(test)]
fn recv_ack_virtual(rx: &Receiver<bool>, budget: Duration) -> Result<bool, RecvTimeoutError> {
    let origin = wait_origin();
    loop {
        match rx.try_recv() {
            Ok(wrote) => return Ok(wrote),
            Err(TryRecvError::Disconnected) => return Err(RecvTimeoutError::Disconnected),
            Err(TryRecvError::Empty) => {
                if !park_within(&origin, budget) {
                    return Err(RecvTimeoutError::Timeout);
                }
            }
        }
    }
}

fn ensure_sink() -> Option<SyncSender<WriterCmd>> {
    if !ADMISSION_OPEN.load(Ordering::Acquire) {
        return None;
    }
    let mut guard = sink_lock();
    if guard.is_none() {
        {
            let mut ledger = ledger_lock();
            if ledger.is_blank() {
                *ledger = load_ledger();
            }
        }
        let cap = queue_capacity();
        let (tx, rx) = sync_channel(cap);
        let spawn = std::thread::Builder::new()
            .name("openfdd-audit-writer".into())
            .spawn(move || writer_loop(rx));
        match spawn {
            Ok(thread) => {
                *guard = Some(AuditSink {
                    tx: tx.clone(),
                    thread: Some(thread),
                });
                return Some(tx);
            }
            Err(_) => {
                drop(guard);
                set_write_error(ERR_IO);
                tracing::error!(
                    target: "security_audit",
                    alert = "audit_sink",
                    error_code = ERR_IO,
                    "audit sink writer thread failed to start"
                );
                return None;
            }
        }
    }
    guard.as_ref().map(|s| s.tx.clone())
}

fn writer_loop(rx: Receiver<WriterCmd>) {
    let mut dirty: Vec<PathBuf> = Vec::new();
    while let Ok(cmd) = rx.recv() {
        match cmd {
            WriterCmd::Shutdown(ack) => {
                sync_paths(&dirty);
                let _ = ack.send(());
                break;
            }
            WriterCmd::Flush(ack) => {
                sync_paths(&dirty);
                let _ = ack.send(());
            }
            WriterCmd::Line(line) => {
                let ok = match append_line(&line) {
                    Ok(()) => {
                        clear_write_error_at(&line.path);
                        true
                    }
                    Err(code) => {
                        set_write_error_at(&line.path, code);
                        tracing::error!(
                            target: "security_audit",
                            alert = "audit_sink",
                            error_code = code,
                            "audit sink write failed"
                        );
                        false
                    }
                };
                remember_path(&mut dirty, &line.path);
                if let Some(ack) = line.ack {
                    let _ = ack.send(ok);
                }
            }
        }
    }
}

fn remember_path(paths: &mut Vec<PathBuf>, path: &Path) {
    if paths.iter().any(|have| have == path) {
        return;
    }
    paths.push(path.to_path_buf());
}

fn sync_paths(paths: &[PathBuf]) {
    for path in paths {
        sync_log_file(path);
    }
}

fn sync_log_file(path: &Path) {
    if let Ok(file) = OpenOptions::new().append(true).open(path) {
        let _ = file.sync_data();
    }
}

fn queued_line(body: String, durable: bool, ack: Option<SyncSender<bool>>) -> WriterCmd {
    WriterCmd::Line(Box::new(QueuedLine {
        body,
        path: audit_log_path(),
        max_bytes: max_bytes(),
        keep: keep_count(),
        durable,
        ack,
    }))
}

/// Block until every previously enqueued audit line has been processed.
/// Used by unit tests that assert on the JSONL file contents.
pub fn flush_sink() {
    let (ack_tx, ack_rx) = sync_channel(1);
    let Some(tx) = ensure_sink() else {
        return;
    };
    if tx.send(WriterCmd::Flush(ack_tx)).is_err() {
        return;
    }
    let _ = ack_rx.recv_timeout(Duration::from_secs(5));
}

fn flush_ledger() {
    let ledger = ledger_lock();
    persist_ledger(&ledger, true);
}

/// Stop admission, finish in-flight enqueues, then drain and fsync the writer.
///
/// `signal` is recorded on the report (`SIGINT`, `SIGTERM`, or another name).
/// A hard kill does not call this function.
pub fn shutdown_for_signal(signal: &'static str, deadline: Duration) -> ShutdownReport {
    ADMISSION_OPEN.store(false, Ordering::Release);
    let start = Instant::now();
    while IN_FLIGHT.load(Ordering::Acquire) > 0 && start.elapsed() < deadline {
        std::thread::sleep(Duration::from_millis(5));
    }
    let mut guard = sink_lock();
    let Some(sink) = guard.as_mut() else {
        drop(guard);
        flush_ledger();
        return ShutdownReport {
            signal,
            drained: true,
            timed_out: false,
        };
    };
    let (ack_tx, ack_rx) = sync_channel(1);
    let send_budget = deadline
        .saturating_sub(start.elapsed())
        .max(Duration::from_millis(1));
    if send_until(&sink.tx, WriterCmd::Shutdown(ack_tx), send_budget).is_err() {
        if let Some(handle) = sink.thread.take() {
            drop(handle);
        }
        *guard = None;
        drop(guard);
        flush_ledger();
        return ShutdownReport {
            signal,
            drained: false,
            timed_out: true,
        };
    }
    let ack_budget = deadline
        .saturating_sub(start.elapsed())
        .max(Duration::from_millis(1));
    let drained = match ack_rx.recv_timeout(ack_budget) {
        Ok(()) => true,
        Err(RecvTimeoutError::Timeout) => false,
        Err(RecvTimeoutError::Disconnected) => false,
    };
    if drained {
        if let Some(handle) = sink.thread.take() {
            let _ = handle.join();
        }
    } else if let Some(handle) = sink.thread.take() {
        drop(handle);
    }
    *guard = None;
    drop(guard);
    flush_ledger();
    ShutdownReport {
        signal,
        drained,
        timed_out: !drained,
    }
}

/// Start the writer again after a simulated process restart.
/// Reloads the loss ledger from disk when the in-memory ledger is blank.
pub fn reopen_after_restart() {
    ADMISSION_OPEN.store(true, Ordering::Release);
    let _ = ensure_sink();
}

fn classify_open_err(err: &io::Error) -> &'static str {
    match err.kind() {
        io::ErrorKind::PermissionDenied | io::ErrorKind::NotFound => ERR_UNWRITABLE,
        _ => ERR_IO,
    }
}

fn append_line(line: &QueuedLine) -> Result<(), &'static str> {
    let path = &line.path;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|_| ERR_UNWRITABLE)?;
    }
    rotate_if_needed(path, line.max_bytes, line.keep)?;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| classify_open_err(&e))?;
    // One write keeps a JSONL record intact if another writer appends too.
    let mut record = Vec::with_capacity(line.body.len() + 1);
    record.extend_from_slice(line.body.as_bytes());
    record.push(b'\n');
    file.write_all(&record).map_err(|_| ERR_IO)?;
    if line.durable {
        file.sync_data().map_err(|_| ERR_IO)?;
    }
    Ok(())
}

fn count_lines(path: &Path) -> u64 {
    let Ok(mut file) = fs::File::open(path) else {
        return 0;
    };
    let mut buf = Vec::new();
    if file.read_to_end(&mut buf).is_err() {
        return 0;
    }
    buf.iter().filter(|byte| **byte == b'\n').count() as u64
}

fn rotate_if_needed(path: &Path, max_bytes: u64, keep: usize) -> Result<(), &'static str> {
    let meta = match fs::metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(ERR_IO),
    };
    if meta.len() < max_bytes {
        return Ok(());
    }
    let oldest = path.with_extension(format!("jsonl.{keep}"));
    if oldest.exists() {
        let removed = count_lines(&oldest);
        match fs::remove_file(&oldest) {
            Ok(()) => note_rotated(path, removed),
            Err(e) if e.kind() == io::ErrorKind::NotFound => {}
            Err(_) => return Err(ERR_IO),
        }
    }
    for i in (1..keep).rev() {
        let from = path.with_extension(format!("jsonl.{i}"));
        let to = path.with_extension(format!("jsonl.{}", i + 1));
        match fs::rename(&from, &to) {
            Ok(()) => {}
            Err(e) if e.kind() == io::ErrorKind::NotFound => {}
            Err(_) => return Err(ERR_IO),
        }
    }
    let first = path.with_extension("jsonl.1");
    fs::rename(path, &first).map_err(|_| ERR_IO)?;
    Ok(())
}

fn retained_files() -> Vec<PathBuf> {
    let path = audit_log_path();
    let mut out = Vec::new();
    if path.is_file() {
        out.push(path.clone());
    }
    for i in 1..=32 {
        let rotated = path.with_extension(format!("jsonl.{i}"));
        if rotated.is_file() {
            out.push(rotated);
        }
    }
    out
}

fn envelope(event: &str, detail: Value) -> Value {
    serde_json::json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "channel": "security_audit",
        "event": event,
        "detail": sanitize(detail),
    })
}

fn trace_line(event: &str, line: &Value) {
    tracing::info!(
        target: "security_audit",
        event = %event,
        detail = %line["detail"],
        "security_audit"
    );
}

/// Append one sanitized security event. Never panics; never logs secrets.
/// Best-effort: callers enqueue and return. A full queue drops the file copy.
pub fn log_event(event: &str, detail: Value) {
    let line = envelope(event, detail.clone());
    trace_line(event, &line);
    if !enter() {
        note_shutdown_drop(&detail);
        return;
    }
    let Some(tx) = ensure_sink() else {
        leave();
        note_queue_drop(&detail);
        return;
    };
    let payload = line.to_string();
    match tx.try_send(queued_line(payload, false, None)) {
        Ok(()) => {}
        Err(TrySendError::Full(_)) => note_queue_drop(&detail),
        Err(TrySendError::Disconnected(_)) => {
            set_write_error(ERR_IO);
            tracing::error!(
                target: "security_audit",
                alert = "audit_sink",
                error_code = ERR_IO,
                "audit sink writer disconnected; event dropped"
            );
        }
    }
    leave();
}

/// Fsync one sanitized event before returning.
///
/// `false` means the line is not durable. The loss ledger records the failure
/// and, when the detail has `request_id`, that id. Callers that already
/// committed a mutation still return their own result; health stays degraded.
pub fn log_event_acknowledged(event: &str, detail: Value) -> bool {
    let line = envelope(event, detail.clone());
    trace_line(event, &line);
    if !enter() {
        note_shutdown_drop(&detail);
        return false;
    }
    let Some(tx) = ensure_sink() else {
        leave();
        note_acknowledged_queue_drop(&detail);
        return false;
    };
    let (ack_tx, ack_rx) = sync_channel(1);
    let payload = line.to_string();
    let queued = send_until(&tx, queued_line(payload, true, Some(ack_tx)), ack_wait());
    leave();
    match queued {
        Ok(()) => match recv_ack(&ack_rx, ack_wait()) {
            Ok(true) => true,
            Ok(false) => {
                mutate_ledger(|ledger| note_lost_id(ledger, &detail));
                false
            }
            Err(_) => {
                note_acknowledged_queue_drop(&detail);
                false
            }
        },
        Err(SendWaitError::Timeout) => {
            note_acknowledged_queue_drop(&detail);
            false
        }
        Err(SendWaitError::Disconnected) => {
            set_write_error(ERR_IO);
            mutate_ledger(|ledger| note_lost_id(ledger, &detail));
            tracing::error!(
                target: "security_audit",
                alert = "audit_sink",
                error_code = ERR_IO,
                "audit sink writer disconnected; acknowledged event dropped"
            );
            false
        }
    }
}

/// Copy retained JSONL generations and the loss ledger into `dest`.
pub fn export_retained(dest: &Path) -> Result<AuditExport, &'static str> {
    flush_sink();
    fs::create_dir_all(dest).map_err(|_| ERR_UNWRITABLE)?;
    let files = retained_files();
    let mut events = 0u64;
    for path in &files {
        let name = path.file_name().ok_or(ERR_IO)?.to_str().ok_or(ERR_IO)?;
        let target = dest.join(name);
        fs::copy(path, &target).map_err(|_| ERR_IO)?;
        events = events.saturating_add(count_lines(&target));
    }
    let ledger = ledger_lock().clone();
    let loss_body = serde_json::to_vec(&ledger).map_err(|_| ERR_IO)?;
    let mut loss_file = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(dest.join("security_audit.loss.json"))
        .map_err(|_| ERR_IO)?;
    loss_file.write_all(&loss_body).map_err(|_| ERR_IO)?;
    let _ = loss_file.sync_data();
    Ok(AuditExport {
        schema: EXPORT_SCHEMA,
        files_copied: files.len(),
        events,
        dropped_queue: ledger.dropped_queue,
        dropped_shutdown: ledger.dropped_shutdown,
        write_failures: ledger.write_failures,
        rotated_out: ledger.rotated_out,
    })
}

/// Compare `request_id` values with the JSONL files still retained.
pub fn reconcile_request_ids(ids: &[String]) -> Reconciliation {
    let mut found = std::collections::BTreeSet::new();
    for path in retained_files() {
        let Ok(text) = fs::read_to_string(&path) else {
            continue;
        };
        for line in text.lines() {
            let Ok(value) = serde_json::from_str::<Value>(line) else {
                continue;
            };
            if let Some(id) = value
                .get("detail")
                .and_then(|detail| detail.get("request_id"))
                .and_then(Value::as_str)
            {
                found.insert(id.to_string());
            }
        }
    }
    let lost: std::collections::BTreeSet<String> =
        ledger_lock().lost_request_ids.iter().cloned().collect();
    let mut present = Vec::new();
    let mut missing = Vec::new();
    let mut missing_recorded_as_loss = Vec::new();
    for id in ids {
        if found.contains(id) {
            present.push(id.clone());
        } else {
            missing.push(id.clone());
            if lost.contains(id) {
                missing_recorded_as_loss.push(id.clone());
            }
        }
    }
    Reconciliation {
        present,
        missing,
        missing_recorded_as_loss,
    }
}

fn sanitize(value: Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, v) in map {
                let lower = k.to_ascii_lowercase();
                if lower.contains("password")
                    || lower.contains("secret")
                    || lower.contains("token")
                    || lower.contains("authorization")
                    || lower == "jwt"
                    || lower.contains("api_key")
                    || lower.contains("apikey")
                {
                    out.insert(k, Value::String("***REDACTED***".to_string()));
                } else {
                    out.insert(k, sanitize(v));
                }
            }
            Value::Object(out)
        }
        Value::Array(items) => Value::Array(
            items
                .into_iter()
                .take(MAX_DETAIL_ITEMS)
                .map(sanitize)
                .collect(),
        ),
        Value::String(text) => Value::String(super::redact::bounded(&text, MAX_DETAIL_CHARS)),
        other => other,
    }
}

/// Per-string budget for free-form detail values. Typed `openfdd.audit.v1`
/// events are already bounded far below this.
const MAX_DETAIL_CHARS: usize = 1024;
const MAX_DETAIL_ITEMS: usize = 64;

#[cfg(test)]
fn test_lock() -> std::sync::MutexGuard<'static, ()> {
    TEST_LOCK
        .get_or_init(|| Mutex::new(()))
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(test)]
fn stop_writer_for_test() {
    ADMISSION_OPEN.store(false, Ordering::Release);
    let start = Instant::now();
    while IN_FLIGHT.load(Ordering::Acquire) > 0 && start.elapsed() < Duration::from_secs(2) {
        std::thread::sleep(Duration::from_millis(5));
    }
    let Some(mut sink) = sink_lock().take() else {
        return;
    };
    let (ack_tx, ack_rx) = sync_channel(1);
    if send_until(
        &sink.tx,
        WriterCmd::Shutdown(ack_tx),
        Duration::from_secs(5),
    )
    .is_ok()
        && ack_rx.recv_timeout(Duration::from_secs(5)).is_ok()
    {
        if let Some(handle) = sink.thread.take() {
            let _ = handle.join();
        }
    }
}

#[cfg(test)]
fn reset_sink_for_test() {
    // `AuditSink::drop` detaches the writer so a blocked FIFO cannot hang a
    // process exit. Unit tests share that thread and the process environment,
    // so stop it and join when the shutdown ack arrives before the next test
    // replaces the log path.
    stop_writer_for_test();
    ADMISSION_OPEN.store(true, Ordering::Release);
    IN_FLIGHT.store(0, Ordering::Release);
    *ledger_lock() = LossLedger::empty();
    std::env::remove_var("OPENFDD_AUDIT_LOG_PATH");
    std::env::remove_var("OPENFDD_AUDIT_LOG_MAX_BYTES");
    std::env::remove_var("OPENFDD_AUDIT_LOG_KEEP");
    std::env::remove_var("OPENFDD_AUDIT_QUEUE_CAP");
    std::env::remove_var("OPENFDD_AUDIT_ACK_MS");
}

/// Drop in-memory counters without deleting the JSONL or loss files.
#[cfg(test)]
fn forget_memory_for_restart() {
    *ledger_lock() = LossLedger::empty();
    ADMISSION_OPEN.store(true, Ordering::Release);
}

#[cfg(test)]
fn wait_until(mut pred: impl FnMut() -> bool, timeout: std::time::Duration) -> bool {
    let start = std::time::Instant::now();
    while start.elapsed() < timeout {
        if pred() {
            return true;
        }
        std::thread::sleep(std::time::Duration::from_millis(5));
    }
    pred()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    use tempfile::tempdir;

    #[test]
    fn redacts_password_fields_in_audit() {
        let sanitized = sanitize(serde_json::json!({
            "username": "integrator",
            "password": "secret",
            "token": "abc",
            "api_key": "k"
        }));
        assert_eq!(sanitized["password"], "***REDACTED***");
        assert_eq!(sanitized["token"], "***REDACTED***");
        assert_eq!(sanitized["api_key"], "***REDACTED***");
        assert_eq!(sanitized["username"], "integrator");
    }

    #[test]
    fn bounds_and_scrubs_free_form_detail_values() {
        let sanitized = sanitize(serde_json::json!({
            "note": format!("Bearer canary-token\n{}", "y".repeat(100 * 1024)),
            "list": (0..500).collect::<Vec<_>>(),
        }));
        let note = sanitized["note"].as_str().unwrap();
        assert!(!note.contains("canary-token"));
        assert!(!note.contains('\n'));
        assert!(note.chars().count() <= MAX_DETAIL_CHARS);
        assert_eq!(
            sanitized["list"].as_array().unwrap().len(),
            MAX_DETAIL_ITEMS
        );
    }

    #[test]
    fn rotates_when_over_max_bytes_and_keeps_only_keep_count() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let path = dir.path().join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_LOG_MAX_BYTES", "200");
        std::env::set_var("OPENFDD_AUDIT_LOG_KEEP", "2");
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "256");
        for i in 0..80 {
            log_event(
                "unit_test",
                serde_json::json!({"i": i, "pad": "xxxxxxxxxxxxxxxx"}),
            );
        }
        assert!(wait_until(
            || path.exists() || path.with_extension("jsonl.1").exists(),
            Duration::from_secs(2)
        ));
        assert!(wait_until(
            || {
                let status = sink_status();
                !status.degraded || status.last_write_error.is_none()
            },
            Duration::from_secs(2)
        ));
        std::thread::sleep(Duration::from_millis(100));
        assert!(
            !path.with_extension("jsonl.3").exists(),
            "keep=2 must not retain jsonl.3"
        );
        assert!(
            path.with_extension("jsonl.1").exists() || path.exists(),
            "active or first rotated file should exist"
        );
        let mut body = String::new();
        if path.exists() {
            fs::File::open(&path)
                .unwrap()
                .read_to_string(&mut body)
                .unwrap();
            assert!(body.contains("security_audit") || body.contains("unit_test"));
        }
        assert!(
            !dir.path().join("auth_audit.jsonl").exists(),
            "legacy dual-write must not create auth_audit.jsonl"
        );
        reset_sink_for_test();
    }

    #[test]
    fn unwritable_directory_marks_sink_degraded_without_panic() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let not_a_dir = dir.path().join("not-a-directory");
        fs::write(&not_a_dir, b"x").unwrap();
        let path = not_a_dir.join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "64");
        log_event("unit_test_unwritable", serde_json::json!({"ok": true}));
        assert!(wait_until(
            || {
                let s = sink_status();
                s.degraded && s.last_write_error == Some(ERR_UNWRITABLE) && s.write_failures > 0
            },
            Duration::from_secs(2)
        ));
        reset_sink_for_test();
    }

    #[test]
    fn full_queue_drops_without_blocking() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let fifo = dir.path().join("audit.fifo");
        let path =
            std::ffi::CString::new(fifo.to_str().expect("fifo path is utf-8")).expect("fifo path");
        let rc = unsafe { libc::mkfifo(path.as_ptr(), 0o600) };
        assert_eq!(rc, 0, "mkfifo: {}", std::io::Error::last_os_error());
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", fifo.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "32");
        log_event("unit_test_block", serde_json::json!({"n": 0}));
        std::thread::sleep(Duration::from_millis(50));
        let before = sink_status().dropped;
        let start = std::time::Instant::now();
        for i in 1..200 {
            log_event("unit_test_flood", serde_json::json!({"n": i}));
        }
        let elapsed = start.elapsed();
        assert!(
            elapsed < Duration::from_millis(500),
            "enqueue must not block on a full queue (took {elapsed:?})"
        );
        assert!(
            sink_status().dropped > before,
            "full queue must increment dropped"
        );
        assert!(sink_status().degraded);
        let _reader = fs::File::open(&fifo);
        std::thread::sleep(Duration::from_millis(50));
        reset_sink_for_test();
    }

    #[test]
    fn sigterm_shutdown_reconciles_acknowledged_ids_after_restart() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let path = dir.path().join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "64");
        let ids = ["ack-a", "ack-b", "ack-c"];
        for id in ids {
            assert!(
                log_event_acknowledged(
                    "user.delete",
                    serde_json::json!({"request_id": id, "decision": "deny"})
                ),
                "{id} was not durable"
            );
        }
        let report = shutdown_for_signal("SIGTERM", Duration::from_secs(2));
        assert_eq!(report.signal, "SIGTERM");
        assert!(report.drained, "SIGTERM drain did not finish");
        assert!(!report.timed_out);
        forget_memory_for_restart();
        reopen_after_restart();
        let found = reconcile_request_ids(&ids.map(str::to_string));
        assert_eq!(found.missing, Vec::<String>::new(), "{found:?}");
        assert_eq!(found.present.len(), ids.len());
        let interrupt = shutdown_for_signal("SIGINT", Duration::from_secs(2));
        assert_eq!(interrupt.signal, "SIGINT");
        assert!(interrupt.drained);
        reset_sink_for_test();
    }

    #[test]
    fn shutdown_persists_refused_events_across_restart() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let path = dir.path().join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        assert!(log_event_acknowledged(
            "user.disable",
            serde_json::json!({"request_id": "kept-1"})
        ));
        let report = shutdown_for_signal("SIGTERM", Duration::from_secs(2));
        assert!(report.drained);
        assert!(!log_event_acknowledged(
            "user.disable",
            serde_json::json!({"request_id": "after-close"})
        ));
        assert!(sink_status().dropped_shutdown >= 1);
        forget_memory_for_restart();
        reopen_after_restart();
        assert!(
            sink_status().dropped_shutdown >= 1,
            "shutdown drops must reload from the loss ledger"
        );
        let found = reconcile_request_ids(&["kept-1".into(), "after-close".into()]);
        assert_eq!(found.present, vec!["kept-1".to_string()]);
        assert_eq!(
            found.missing_recorded_as_loss,
            vec!["after-close".to_string()]
        );
        reset_sink_for_test();
    }

    #[test]
    fn queued_lines_keep_the_path_captured_at_enqueue() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let fifo = dir.path().join("audit.fifo");
        let c_path =
            std::ffi::CString::new(fifo.to_str().expect("fifo path is utf-8")).expect("fifo path");
        let rc = unsafe { libc::mkfifo(c_path.as_ptr(), 0o600) };
        assert_eq!(rc, 0, "mkfifo: {}", std::io::Error::last_os_error());
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", fifo.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "64");
        let opener = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(30));
            let _reader = fs::File::open(&fifo).unwrap();
            std::thread::sleep(Duration::from_millis(100));
        });
        log_event(
            "unit_test_block",
            serde_json::json!({"request_id": "blocked"}),
        );
        for i in 0..8 {
            log_event(
                "unit_test_queued",
                serde_json::json!({"request_id": format!("q-{i}")}),
            );
        }
        let real = dir.path().join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", real.to_str().unwrap());
        assert!(log_event_acknowledged(
            "user.disable",
            serde_json::json!({"request_id": "kept-1"})
        ));
        let _ = opener.join();
        let body = fs::read_to_string(&real).unwrap();
        assert!(
            body.contains("kept-1"),
            "acknowledged line must land in the path captured at enqueue"
        );
        assert!(
            !body.contains("q-0"),
            "a line queued for the previous path must not follow a later path change: {body}"
        );
        for line in body.lines() {
            assert!(
                serde_json::from_str::<serde_json::Value>(line).is_ok(),
                "audit line must stay one JSON object: {line}"
            );
        }
        reset_sink_for_test();
    }

    #[test]
    fn acknowledged_event_records_loss_when_the_queue_stays_full() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let fifo = dir.path().join("audit.fifo");
        let path =
            std::ffi::CString::new(fifo.to_str().expect("fifo path is utf-8")).expect("fifo path");
        let rc = unsafe { libc::mkfifo(path.as_ptr(), 0o600) };
        assert_eq!(rc, 0, "mkfifo: {}", std::io::Error::last_os_error());
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", fifo.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "32");
        std::env::set_var("OPENFDD_AUDIT_ACK_MS", "150");
        let budget = ack_wait();
        assert_eq!(budget, Duration::from_millis(150));
        log_event("unit_test_block", serde_json::json!({"n": 0}));
        std::thread::sleep(Duration::from_millis(50));
        let dropped_before_flood = sink_status().dropped;
        for i in 1..80 {
            log_event("unit_test_flood", serde_json::json!({"n": i}));
        }
        assert!(
            sink_status().dropped > dropped_before_flood,
            "a stuck writer must fill the queue before the acknowledged event"
        );
        let dropped_before = sink_status().dropped;
        let failures_before = sink_status().write_failures;
        // The product budget is the clock. Wall time also includes the loss
        // ledger fsync and any park overshoot, which blew an 800ms cap on a
        // loaded runner (measured 1.07s) after the same SHA had passed.
        let clock = manual_ack_wait();
        let ok = log_event_acknowledged(
            "package.import",
            serde_json::json!({"request_id": "lost-ack"}),
        );
        let waited = manual_ack_wait_elapsed();
        drop(clock);
        assert!(!ok, "a stuck sink must not report an acknowledged write");
        assert!(
            waited >= budget && waited <= budget.saturating_add(budget),
            "loss follows the product ack budget, once to enqueue and once for the writer reply (waited {waited:?}, budget {budget:?})"
        );
        let status = sink_status();
        assert!(status.degraded);
        assert!(
            status.dropped > dropped_before,
            "the bounded wait must record a queue loss"
        );
        assert_eq!(
            status.write_failures, failures_before,
            "a full queue keeps the pre-call write-failure count"
        );
        let found = reconcile_request_ids(&["lost-ack".into()]);
        assert_eq!(found.missing_recorded_as_loss, vec!["lost-ack".to_string()]);
        assert!(found.present.is_empty(), "the line must stay off disk");
        let _reader = fs::File::open(&fifo);
        std::thread::sleep(Duration::from_millis(50));
        reset_sink_for_test();
    }

    #[test]
    fn unflushed_queue_is_the_hard_kill_residual_window() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let fifo = dir.path().join("audit.fifo");
        let path =
            std::ffi::CString::new(fifo.to_str().expect("fifo path is utf-8")).expect("fifo path");
        let rc = unsafe { libc::mkfifo(path.as_ptr(), 0o600) };
        assert_eq!(rc, 0, "mkfifo: {}", std::io::Error::last_os_error());
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", fifo.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "32");
        log_event(
            "admin.read",
            serde_json::json!({"request_id": "still-queued"}),
        );
        std::thread::sleep(Duration::from_millis(40));
        assert!(
            !fifo.exists() || fs::metadata(&fifo).map(|m| m.len()).unwrap_or(0) == 0,
            "a blocked writer must not already have a durable line"
        );
        let fifo_path = fifo.clone();
        let opener = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(80));
            let _reader = fs::File::open(&fifo_path);
            std::thread::sleep(Duration::from_millis(50));
        });
        let report = shutdown_for_signal("SIGTERM", Duration::from_secs(2));
        let _ = opener.join();
        assert!(
            report.drained || fifo.is_file(),
            "SIGTERM should drain once the writer can finish"
        );
        reset_sink_for_test();
    }

    #[test]
    fn retention_export_counts_removed_generations_and_redacts_secrets() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let path = dir.path().join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_LOG_MAX_BYTES", "240");
        std::env::set_var("OPENFDD_AUDIT_LOG_KEEP", "1");
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "128");
        for i in 0..40 {
            assert!(log_event_acknowledged(
                "package.import",
                serde_json::json!({
                    "request_id": format!("row-{i}"),
                    "password": "pw-canary-hunter2",
                    "note": "Bearer opaque-bearer-canary-77"
                })
            ));
        }
        assert!(
            sink_status().rotated_out > 0,
            "keep=1 must record events removed by rotation"
        );
        assert!(
            !path.with_extension("jsonl.2").exists(),
            "keep=1 must not leave a second generation"
        );
        let export_dir = dir.path().join("export");
        let exported = export_retained(&export_dir).expect("export");
        assert!(exported.events > 0);
        assert!(exported.rotated_out > 0);
        let mut body = String::new();
        for entry in fs::read_dir(&export_dir).unwrap() {
            let entry = entry.unwrap();
            if entry.path().extension().and_then(|ext| ext.to_str()) == Some("json")
                && entry.file_name().to_string_lossy().ends_with(".loss.json")
            {
                continue;
            }
            let mut file = fs::File::open(entry.path()).unwrap();
            file.read_to_string(&mut body).unwrap();
        }
        assert!(!body.contains("pw-canary-hunter2"));
        assert!(!body.contains("opaque-bearer-canary-77"));
        assert!(body.contains("***REDACTED***"));
        reset_sink_for_test();
    }

    #[test]
    fn sink_failure_stays_degraded_after_the_error_code_is_recorded() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let blocker = dir.path().join("not-a-directory");
        fs::write(&blocker, b"x").unwrap();
        let path = blocker.join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        assert!(!log_event_acknowledged(
            "dataset.delete",
            serde_json::json!({"request_id": "disk-fail"})
        ));
        assert!(wait_until(
            || sink_status().write_failures > 0 && sink_status().degraded,
            Duration::from_secs(2)
        ));
        let status = sink_status();
        assert_eq!(status.last_write_error, Some(ERR_UNWRITABLE));
        let found = reconcile_request_ids(&["disk-fail".into()]);
        assert_eq!(found.present, Vec::<String>::new());
        reset_sink_for_test();
    }
}
