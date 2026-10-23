//! Security audit log for pen-test / operator review (no secrets).
//!
//! Dual sink (independent copies):
//! - One JSONL file under `$OPENFDD_WORKSPACE/logs/security_audit.jsonl`
//!   (size-rotated; written on a dedicated std thread via a bounded queue)
//! - `tracing` target `security_audit` so Railway / AWS / docker scrape stdout
//!
//! Env:
//! - `OPENFDD_AUDIT_LOG_PATH` — override file path (default `workspace/logs/security_audit.jsonl`)
//! - `OPENFDD_AUDIT_LOG_MAX_BYTES` — rotate threshold (default 10485760 = 10 MiB)
//! - `OPENFDD_AUDIT_LOG_KEEP` — rotated files to keep (default 5)
//! - `OPENFDD_AUDIT_QUEUE_CAP` — bounded enqueue capacity (default 1024, clamped 32..=16384)

use serde_json::Value;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{sync_channel, Receiver, SyncSender, TrySendError};
use std::sync::Mutex;
use std::thread::JoinHandle;
use std::time::Duration;

/// Stable write-failure codes for `/api/health` (never a path or payload).
pub const ERR_UNWRITABLE: &str = "unwritable";
pub const ERR_IO: &str = "io";

const DEFAULT_QUEUE_CAP: usize = 1024;
const MIN_QUEUE_CAP: usize = 32;
const MAX_QUEUE_CAP: usize = 16_384;

static DEGRADED: AtomicBool = AtomicBool::new(false);
static DROPPED: AtomicU64 = AtomicU64::new(0);
static LAST_WRITE_ERROR: Mutex<Option<&'static str>> = Mutex::new(None);
static SINK: Mutex<Option<AuditSink>> = Mutex::new(None);
/// Serializes env-mutating unit tests that share process-global sink state.
#[cfg(test)]
static TEST_LOCK: std::sync::OnceLock<Mutex<()>> = std::sync::OnceLock::new();

struct AuditSink {
    tx: SyncSender<WriterCmd>,
    thread: Option<JoinHandle<()>>,
}

enum WriterCmd {
    Line(String),
    /// Barrier: writer replies after every earlier `Line` has been written (or failed).
    Flush(SyncSender<()>),
    Shutdown,
}

impl Drop for AuditSink {
    fn drop(&mut self) {
        // Best-effort stop. Never join: the writer can block on an unwritable
        // path or FIFO open; detaching keeps reset/tests from hanging.
        let _ = self.tx.try_send(WriterCmd::Shutdown);
        let _ = self.thread.take();
    }
}

/// Snapshot for central `/api/health` (`audit_sink`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AuditSinkStatus {
    pub degraded: bool,
    pub dropped: u64,
    pub last_write_error: Option<&'static str>,
}

/// Current file-sink health. `dropped` is process-lifetime; `degraded` clears
/// on the next successful write.
pub fn sink_status() -> AuditSinkStatus {
    let last_write_error = LAST_WRITE_ERROR
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .as_ref()
        .copied();
    AuditSinkStatus {
        degraded: DEGRADED.load(Ordering::Relaxed),
        dropped: DROPPED.load(Ordering::Relaxed),
        last_write_error,
    }
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

fn set_write_error(code: &'static str) {
    DEGRADED.store(true, Ordering::Relaxed);
    *LAST_WRITE_ERROR
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(code);
}

fn clear_write_error() {
    DEGRADED.store(false, Ordering::Relaxed);
    *LAST_WRITE_ERROR
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = None;
}

fn note_drop() {
    let n = DROPPED.fetch_add(1, Ordering::Relaxed) + 1;
    DEGRADED.store(true, Ordering::Relaxed);
    tracing::error!(
        target: "security_audit",
        dropped = n,
        "audit sink queue full; event dropped"
    );
}

fn ensure_sink() -> Option<SyncSender<WriterCmd>> {
    let mut guard = SINK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    if guard.is_none() {
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
                set_write_error(ERR_IO);
                tracing::error!(
                    target: "security_audit",
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
    while let Ok(cmd) = rx.recv() {
        match cmd {
            WriterCmd::Shutdown => break,
            WriterCmd::Flush(ack) => {
                let _ = ack.send(());
            }
            WriterCmd::Line(line) => match append_line(&line) {
                Ok(()) => clear_write_error(),
                Err(code) => {
                    set_write_error(code);
                    tracing::error!(
                        target: "security_audit",
                        error_code = code,
                        "audit sink write failed"
                    );
                }
            },
        }
    }
}

/// Block until every previously enqueued audit line has been processed.
/// Used by unit tests that assert on the JSONL file contents.
pub fn flush_sink() {
    let (ack_tx, ack_rx) = sync_channel(1);
    let Some(tx) = ensure_sink() else {
        return;
    };
    // Blocking send so the barrier is not dropped when the queue is briefly full.
    if tx.send(WriterCmd::Flush(ack_tx)).is_err() {
        return;
    }
    let _ = ack_rx.recv_timeout(Duration::from_secs(5));
}

fn classify_open_err(err: &io::Error) -> &'static str {
    match err.kind() {
        io::ErrorKind::PermissionDenied | io::ErrorKind::NotFound => ERR_UNWRITABLE,
        _ => ERR_IO,
    }
}

fn append_line(line: &str) -> Result<(), &'static str> {
    let path = audit_log_path();
    if let Some(parent) = path.parent() {
        // Cannot create the logs directory → path is not usable for audit.
        fs::create_dir_all(parent).map_err(|_| ERR_UNWRITABLE)?;
    }
    rotate_if_needed(&path)?;
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| classify_open_err(&e))?;
    writeln!(file, "{line}").map_err(|_| ERR_IO)?;
    Ok(())
}

fn rotate_if_needed(path: &Path) -> Result<(), &'static str> {
    let meta = match fs::metadata(path) {
        Ok(m) => m,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(_) => return Err(ERR_IO),
    };
    if meta.len() < max_bytes() {
        return Ok(());
    }
    let keep = keep_count();
    let oldest = path.with_extension(format!("jsonl.{keep}"));
    match fs::remove_file(&oldest) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::NotFound => {}
        Err(_) => return Err(ERR_IO),
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

/// Append one sanitized security event. Never panics; never logs secrets.
/// Callers enqueue and return; filesystem I/O runs on a dedicated writer thread.
pub fn log_event(event: &str, detail: Value) {
    let detail = sanitize(detail);
    let line = serde_json::json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "channel": "security_audit",
        "event": event,
        "detail": detail,
    });

    // Hosted platforms (Railway / AWS / GHCR docker) scrape stdout — second copy.
    tracing::info!(
        target: "security_audit",
        event = %event,
        detail = %line["detail"],
        "security_audit"
    );

    let Some(tx) = ensure_sink() else {
        let _ = DROPPED.fetch_add(1, Ordering::Relaxed);
        return;
    };
    let payload = line.to_string();
    match tx.try_send(WriterCmd::Line(payload)) {
        Ok(()) => {}
        Err(TrySendError::Full(_)) => note_drop(),
        Err(TrySendError::Disconnected(_)) => {
            let _ = DROPPED.fetch_add(1, Ordering::Relaxed);
            set_write_error(ERR_IO);
            tracing::error!(
                target: "security_audit",
                error_code = ERR_IO,
                "audit sink writer disconnected; event dropped"
            );
        }
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
fn reset_sink_for_test() {
    let mut guard = SINK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    *guard = None;
    DEGRADED.store(false, Ordering::Relaxed);
    DROPPED.store(0, Ordering::Relaxed);
    *LAST_WRITE_ERROR
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner) = None;
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
    use std::io::Read;
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
        // Drain writer so rotation settles.
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
        std::env::remove_var("OPENFDD_AUDIT_LOG_PATH");
        std::env::remove_var("OPENFDD_AUDIT_LOG_MAX_BYTES");
        std::env::remove_var("OPENFDD_AUDIT_LOG_KEEP");
        std::env::remove_var("OPENFDD_AUDIT_QUEUE_CAP");
        reset_sink_for_test();
    }

    #[test]
    fn unwritable_directory_marks_sink_degraded_without_panic() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        // Parent path is a regular file → create_dir_all fails (works as root too).
        let not_a_dir = dir.path().join("not-a-directory");
        fs::write(&not_a_dir, b"x").unwrap();
        let path = not_a_dir.join("security_audit.jsonl");
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", path.to_str().unwrap());
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "64");
        log_event("unit_test_unwritable", serde_json::json!({"ok": true}));
        assert!(wait_until(
            || {
                let s = sink_status();
                s.degraded && s.last_write_error == Some(ERR_UNWRITABLE)
            },
            Duration::from_secs(2)
        ));
        std::env::remove_var("OPENFDD_AUDIT_LOG_PATH");
        std::env::remove_var("OPENFDD_AUDIT_QUEUE_CAP");
        reset_sink_for_test();
    }

    #[test]
    fn full_queue_drops_without_blocking() {
        let _lock = test_lock();
        reset_sink_for_test();
        let dir = tempdir().unwrap();
        let fifo = dir.path().join("audit.fifo");
        // Writer blocks on open(append) until a reader appears — fills the queue.
        let status = std::process::Command::new("mkfifo")
            .arg(&fifo)
            .status()
            .expect("mkfifo available");
        assert!(status.success());
        std::env::set_var("OPENFDD_AUDIT_LOG_PATH", fifo.to_str().unwrap());
        // Clamp floor is 32; fill past that while the writer is stuck on the fifo.
        std::env::set_var("OPENFDD_AUDIT_QUEUE_CAP", "32");
        // Kick the writer so it blocks on the fifo open.
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
        // Unblock the writer so Drop/join can finish.
        let _reader = fs::File::open(&fifo);
        std::thread::sleep(Duration::from_millis(50));
        std::env::remove_var("OPENFDD_AUDIT_LOG_PATH");
        std::env::remove_var("OPENFDD_AUDIT_QUEUE_CAP");
        reset_sink_for_test();
    }
}
