//! Process-wide building session book.
//!
//! CSV guests load a historian working set only for the duration of a compute
//! job. MQTTS sites keep a capped ingest buffer and do not register the full
//! historian. Idle CSV leases expire on a timer started from `main`.

use std::sync::{Mutex, OnceLock};

use fdd_store::{SessionBook, SessionKind, SessionLimits};
use serde_json::{json, Value};

static BOOK: OnceLock<Mutex<SessionBook>> = OnceLock::new();

pub fn book() -> &'static Mutex<SessionBook> {
    BOOK.get_or_init(|| Mutex::new(SessionBook::new(SessionLimits::from_env())))
}

pub fn lock() -> std::sync::MutexGuard<'static, SessionBook> {
    book().lock().unwrap_or_else(|poison| poison.into_inner())
}

pub fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX))
        .unwrap_or(0)
}

pub fn evict_idle() {
    let now = now_ms();
    lock().evict_idle(now);
}

pub fn note_catalog_list() {
    lock().note_catalog_list();
}

pub fn note_mqtt_ingest(site_id: &str, pending_rows: usize) {
    if site_id.trim().is_empty() {
        return;
    }
    let now = now_ms();
    let _ = lock().note_mqtt(site_id, pending_rows, now);
}

pub fn leave(building_id: &str) -> bool {
    lock().leave(building_id)
}

pub fn snapshot() -> Value {
    let guard = lock();
    let limits = guard.limits();
    json!({
        "max_interactive": limits.max_interactive,
        "idle_timeout_secs": limits.idle_timeout_ms / 1000,
        "mqtt_buffer_rows": limits.mqtt_buffer_rows,
        "max_mqtt_buffers": limits.max_mqtt_buffers,
        "interactive_slots": guard.interactive_slots(),
        "historian_resident": guard.historian_resident(),
        "ram_resident": guard.ram_resident(),
        "mqtt_kind": format!("{:?}", SessionKind::MqttLive),
    })
}
