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
/// A site with one air handler and dozens of terminals still fits. Past this
/// cap the mark says `equipment_ids_truncated` so a missing id is not EDGE loss.
const MAX_EQUIPMENT_IDS: usize = 512;
/// Collapse session-down retries so a 200ms drain loop cannot evict the ack ring.
const NO_SESSION_COALESCE_MS: u64 = 300_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum MarkKind {
    Ack,
    Fail,
    NoSession,
}

impl MarkKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Ack => "ack",
            Self::Fail => "fail",
            Self::NoSession => "no_session",
        }
    }
}

#[derive(Clone, Debug)]
struct Mark {
    unix_ms: u64,
    sequence: u64,
    points: u32,
    ok: bool,
    kind: MarkKind,
    equipment_ids: Vec<String>,
    equipment_ids_truncated: bool,
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
        let (ids, truncated) = cap_ids(equipment_ids);
        self.push(Mark {
            unix_ms: now,
            sequence,
            points,
            ok: true,
            kind: MarkKind::Ack,
            equipment_ids: ids,
            equipment_ids_truncated: truncated,
        });
    }

    pub fn record_fail(&self, equipment_ids: &[String]) {
        self.attempts.fetch_add(1, Ordering::Relaxed);
        self.fails.fetch_add(1, Ordering::Relaxed);
        let (ids, truncated) = cap_ids(equipment_ids);
        self.push(Mark {
            unix_ms: now_unix_ms(),
            sequence: 0,
            points: 0,
            ok: false,
            kind: MarkKind::Fail,
            equipment_ids: ids,
            equipment_ids_truncated: truncated,
        });
    }

    /// Polled points were ready but the MQTT session was down, so nothing left the edge.
    ///
    /// Retries inside one poll interval update the same mark. They do not push
    /// a new ring entry on every drain tick.
    pub fn record_no_session(&self, equipment_ids: &[String]) {
        self.no_session.fetch_add(1, Ordering::Relaxed);
        let now = now_unix_ms();
        let (ids, truncated) = cap_ids(equipment_ids);
        let mut guard = self.recent.lock().unwrap_or_else(|err| err.into_inner());
        if let Some(last) = guard.back_mut() {
            if last.kind == MarkKind::NoSession
                && now.saturating_sub(last.unix_ms) < NO_SESSION_COALESCE_MS
            {
                last.unix_ms = now;
                merge_ids(last, ids, truncated);
                return;
            }
        }
        drop(guard);
        self.push(Mark {
            unix_ms: now,
            sequence: 0,
            points: 0,
            ok: false,
            kind: MarkKind::NoSession,
            equipment_ids: ids,
            equipment_ids_truncated: truncated,
        });
    }

    pub fn snapshot(&self) -> Value {
        let marks = self.recent_marks();
        let truncated = marks.iter().any(|mark| mark.equipment_ids_truncated);
        let recent: Vec<Value> = marks
            .into_iter()
            .map(|mark| {
                json!({
                    "at": unix_ms_to_rfc3339(mark.unix_ms),
                    "unix_ms": mark.unix_ms,
                    "sequence": mark.sequence,
                    "points": mark.points,
                    "ok": mark.ok,
                    "kind": mark.kind.as_str(),
                    "equipment_ids": mark.equipment_ids,
                    "equipment_ids_truncated": mark.equipment_ids_truncated,
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
            "equipment_ids_truncated": truncated,
            "equipment_id_cap": MAX_EQUIPMENT_IDS,
            "recent": recent,
            "note": "QoS 1 ack means the broker accepted the publish. This ledger does not filter publishes. equipment_ids_truncated means a mark dropped ids past the cap; a missing id on that mark is not proof the edge skipped the device.",
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

fn cap_ids(ids: &[String]) -> (Vec<String>, bool) {
    let mut out = Vec::new();
    let mut truncated = false;
    for id in ids {
        let trimmed = id.trim();
        if trimmed.is_empty() || out.iter().any(|seen: &String| seen == trimmed) {
            continue;
        }
        if out.len() >= MAX_EQUIPMENT_IDS {
            truncated = true;
            break;
        }
        out.push(trimmed.to_string());
    }
    (out, truncated)
}

fn merge_ids(mark: &mut Mark, ids: Vec<String>, truncated: bool) {
    if truncated {
        mark.equipment_ids_truncated = true;
    }
    for id in ids {
        if mark.equipment_ids.iter().any(|seen| seen == &id) {
            continue;
        }
        if mark.equipment_ids.len() >= MAX_EQUIPMENT_IDS {
            mark.equipment_ids_truncated = true;
            break;
        }
        mark.equipment_ids.push(id);
    }
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
        ledger.record_fail(&["RTU_01".into()]);
        ledger.record_no_session(&["VAV_2".into()]);
        ledger.record_no_session(&["VAV_3".into()]);
        let snap = ledger.snapshot();
        assert_eq!(snap["publish_attempts"], 2);
        assert_eq!(snap["publish_acks"], 1);
        assert_eq!(snap["publish_fails"], 1);
        assert_eq!(snap["publish_no_session"], 2);
        assert_eq!(snap["last_sequence"], 7);
        assert_eq!(snap["equipment_ids_truncated"], false);
        let recent = snap["recent"].as_array().unwrap();
        assert_eq!(recent.len(), 3);
        assert_eq!(recent[0]["ok"], true);
        assert_eq!(recent[0]["kind"], "ack");
        assert_eq!(recent[0]["equipment_ids"][0], "RTU_01");
        assert_eq!(recent[1]["ok"], false);
        assert_eq!(recent[1]["kind"], "fail");
        assert_eq!(recent[1]["equipment_ids"][0], "RTU_01");
        assert_eq!(recent[2]["kind"], "no_session");
        let no_session_ids = recent[2]["equipment_ids"].as_array().unwrap();
        assert_eq!(no_session_ids.len(), 2);
    }

    #[test]
    fn equipment_id_cap_sets_truncated_instead_of_hiding_the_drop() {
        let ledger = MqttPublishLedger::default();
        let ids: Vec<String> = (0..=MAX_EQUIPMENT_IDS).map(|i| format!("EQ_{i}")).collect();
        ledger.record_ack(1, 1, &ids);
        let snap = ledger.snapshot();
        assert_eq!(snap["equipment_ids_truncated"], true);
        let recent = snap["recent"].as_array().unwrap();
        assert_eq!(recent[0]["equipment_ids_truncated"], true);
        assert_eq!(
            recent[0]["equipment_ids"].as_array().unwrap().len(),
            MAX_EQUIPMENT_IDS
        );
        assert_eq!(recent[0]["equipment_ids"][0], "EQ_0");
    }
}
