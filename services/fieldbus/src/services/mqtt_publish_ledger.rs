//! In-memory MQTT publish ledger for continuity triage.
//!
//! Diagnostics only. Does not filter, coalesce, or drop publishes.
//! QoS 1 ack means the broker accepted the packet. A failed ack is not a
//! Railway historian gap.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use chrono::{DateTime, Utc};
use serde_json::{json, Value};

/// ~48h of 300s publishes. Older marks fall off the ring.
const RING_CAP: usize = 576;
const MAX_EQUIPMENT_IDS: usize = 32;

#[derive(Clone, Debug)]
struct Mark {
    unix_ms: u64,
    sequence: u64,
    points: u32,
    ok: bool,
    equipment_ids: Vec<String>,
}

#[derive(Debug)]
pub struct MqttPublishLedger {
    attempts: AtomicU64,
    acks: AtomicU64,
    fails: AtomicU64,
    no_session: AtomicU64,
    last_ack_unix_ms: AtomicU64,
    last_sequence: AtomicU64,
    recent: Mutex<VecDeque<Mark>>,
}

impl Default for MqttPublishLedger {
    fn default() -> Self {
        Self {
            attempts: AtomicU64::new(0),
            acks: AtomicU64::new(0),
            fails: AtomicU64::new(0),
            no_session: AtomicU64::new(0),
            last_ack_unix_ms: AtomicU64::new(0),
            last_sequence: AtomicU64::new(0),
            recent: Mutex::new(VecDeque::with_capacity(RING_CAP)),
        }
    }
}

impl MqttPublishLedger {
    pub fn record_ack(&self, sequence: u64, points: u32, equipment_ids: &[String]) {
        let now = now_unix_ms();
        self.attempts.fetch_add(1, Ordering::Relaxed);
        self.acks.fetch_add(1, Ordering::Relaxed);
        self.last_ack_unix_ms.store(now, Ordering::Relaxed);
        self.last_sequence.store(sequence, Ordering::Relaxed);
        self.push(Mark {
            unix_ms: now,
            sequence,
            points,
            ok: true,
            equipment_ids: cap_ids(equipment_ids),
        });
    }

    pub fn record_fail(&self) {
        self.attempts.fetch_add(1, Ordering::Relaxed);
        self.fails.fetch_add(1, Ordering::Relaxed);
        self.push(Mark {
            unix_ms: now_unix_ms(),
            sequence: 0,
            points: 0,
            ok: false,
            equipment_ids: Vec::new(),
        });
    }

    /// Polled points were ready but the MQTT session was down, so nothing left the edge.
    pub fn record_no_session(&self) {
        self.no_session.fetch_add(1, Ordering::Relaxed);
    }

    pub fn snapshot(&self) -> Value {
        let recent: Vec<Value> = self
            .recent_marks()
            .into_iter()
            .map(|mark| {
                json!({
                    "at": unix_ms_to_rfc3339(mark.unix_ms),
                    "unix_ms": mark.unix_ms,
                    "sequence": mark.sequence,
                    "points": mark.points,
                    "ok": mark.ok,
                    "equipment_ids": mark.equipment_ids,
                })
            })
            .collect();
        json!({
            "ok": true,
            "publish_attempts": self.attempts.load(Ordering::Relaxed),
            "publish_acks": self.acks.load(Ordering::Relaxed),
            "publish_fails": self.fails.load(Ordering::Relaxed),
            "publish_no_session": self.no_session.load(Ordering::Relaxed),
            "last_ack_unix_ms": self.last_ack_unix_ms.load(Ordering::Relaxed),
            "last_ack_at": unix_ms_to_rfc3339(self.last_ack_unix_ms.load(Ordering::Relaxed)),
            "last_sequence": self.last_sequence.load(Ordering::Relaxed),
            "recent": recent,
            "note": "QoS 1 ack means the broker accepted the publish. This ledger does not filter publishes.",
        })
    }

    fn push(&self, mark: Mark) {
        let mut guard = self.recent.lock().unwrap_or_else(|err| err.into_inner());
        if guard.len() >= RING_CAP {
            guard.pop_front();
        }
        guard.push_back(mark);
    }

    fn recent_marks(&self) -> Vec<Mark> {
        self.recent
            .lock()
            .unwrap_or_else(|err| err.into_inner())
            .iter()
            .cloned()
            .collect()
    }
}

fn cap_ids(ids: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for id in ids {
        let trimmed = id.trim();
        if trimmed.is_empty() || out.iter().any(|seen: &String| seen == trimmed) {
            continue;
        }
        out.push(trimmed.to_string());
        if out.len() >= MAX_EQUIPMENT_IDS {
            break;
        }
    }
    out
}

fn now_unix_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .ok()
        .and_then(|d| u64::try_from(d.as_millis()).ok())
        .unwrap_or(0)
}

fn unix_ms_to_rfc3339(unix_ms: u64) -> Option<String> {
    let millis = i64::try_from(unix_ms).ok()?;
    if millis <= 0 {
        return None;
    }
    DateTime::<Utc>::from_timestamp_millis(millis).map(|ts| ts.to_rfc3339())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ack_and_fail_are_counted_separately() {
        let ledger = MqttPublishLedger::default();
        ledger.record_ack(7, 3, &["RTU_01".into(), "RTU_01".into()]);
        ledger.record_fail();
        ledger.record_no_session();
        let snap = ledger.snapshot();
        assert_eq!(snap["publish_attempts"], 2);
        assert_eq!(snap["publish_acks"], 1);
        assert_eq!(snap["publish_fails"], 1);
        assert_eq!(snap["publish_no_session"], 1);
        assert_eq!(snap["last_sequence"], 7);
        let recent = snap["recent"].as_array().unwrap();
        assert_eq!(recent.len(), 2);
        assert_eq!(recent[0]["ok"], true);
        assert_eq!(recent[0]["equipment_ids"][0], "RTU_01");
        assert_eq!(recent[1]["ok"], false);
    }
}
