//! Session-scoped building residency.
//!
//! CSV / package buildings are guests: a DataFusion historian working set may
//! be loaded for a job, then dropped when that job's parquet results are
//! durable. An interactive lease can remain until the operator leaves or the
//! idle timeout fires (30–120s). Live MQTTS sessions keep a small row buffer
//! only — never the full historian.
//!
//! Hub catalog listing does not open sessions. Interactive leases default to
//! two concurrent buildings.

use std::collections::BTreeMap;

pub const DEFAULT_MAX_INTERACTIVE_SESSIONS: usize = 2;
pub const DEFAULT_IDLE_TIMEOUT_SECS: u64 = 60;
pub const MIN_IDLE_TIMEOUT_SECS: u64 = 30;
pub const MAX_IDLE_TIMEOUT_SECS: u64 = 120;
pub const DEFAULT_MQTT_BUFFER_ROWS: usize = 256;
pub const DEFAULT_MAX_MQTT_BUFFERS: usize = 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionKind {
    CsvGuest,
    MqttLive,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionRecord {
    pub building_id: String,
    pub kind: SessionKind,
    pub last_active_ms: u64,
    pub job_running: bool,
    /// True only while a CSV/package job has the historian working set loaded.
    pub historian_loaded: bool,
    pub mqtt_buffered_rows: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionLimits {
    pub max_interactive: usize,
    pub idle_timeout_ms: u64,
    pub mqtt_buffer_rows: usize,
    pub max_mqtt_buffers: usize,
}

impl Default for SessionLimits {
    fn default() -> Self {
        Self {
            max_interactive: DEFAULT_MAX_INTERACTIVE_SESSIONS,
            idle_timeout_ms: DEFAULT_IDLE_TIMEOUT_SECS * 1000,
            mqtt_buffer_rows: DEFAULT_MQTT_BUFFER_ROWS,
            max_mqtt_buffers: DEFAULT_MAX_MQTT_BUFFERS,
        }
    }
}

impl SessionLimits {
    pub fn from_env() -> Self {
        let max_interactive = std::env::var("OPENFDD_MAX_BUILDING_SESSIONS")
            .ok()
            .and_then(|s| s.trim().parse::<usize>().ok())
            .map(clamp_max_interactive)
            .unwrap_or(DEFAULT_MAX_INTERACTIVE_SESSIONS);
        let idle_secs = std::env::var("OPENFDD_BUILDING_SESSION_IDLE_SECS")
            .ok()
            .and_then(|s| s.trim().parse::<u64>().ok())
            .map(clamp_idle_secs)
            .unwrap_or(DEFAULT_IDLE_TIMEOUT_SECS);
        let mqtt_rows = std::env::var("OPENFDD_MQTT_INGEST_BUFFER_ROWS")
            .ok()
            .and_then(|s| s.trim().parse::<usize>().ok())
            .filter(|n| *n > 0)
            .map(|n| n.min(4096))
            .unwrap_or(DEFAULT_MQTT_BUFFER_ROWS);
        let max_mqtt = std::env::var("OPENFDD_MAX_MQTT_BUILDING_BUFFERS")
            .ok()
            .and_then(|s| s.trim().parse::<usize>().ok())
            .filter(|n| *n > 0)
            .map(|n| n.min(256))
            .unwrap_or(DEFAULT_MAX_MQTT_BUFFERS);
        Self {
            max_interactive,
            idle_timeout_ms: idle_secs * 1000,
            mqtt_buffer_rows: mqtt_rows,
            max_mqtt_buffers: max_mqtt,
        }
    }
}

pub fn clamp_idle_secs(secs: u64) -> u64 {
    secs.clamp(MIN_IDLE_TIMEOUT_SECS, MAX_IDLE_TIMEOUT_SECS)
}

pub fn clamp_max_interactive(n: usize) -> usize {
    n.clamp(1, 8)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SessionError {
    AtCapacity { max: usize },
    UnsafeBuildingId,
}

#[derive(Debug, Default)]
pub struct SessionBook {
    limits: SessionLimits,
    sessions: BTreeMap<String, SessionRecord>,
}

impl SessionBook {
    pub fn new(limits: SessionLimits) -> Self {
        Self {
            limits,
            sessions: BTreeMap::new(),
        }
    }

    pub fn limits(&self) -> &SessionLimits {
        &self.limits
    }

    /// Catalog / dataset listing must not create a resident building.
    pub fn note_catalog_list(&mut self) {}

    pub fn open(
        &mut self,
        building_id: &str,
        kind: SessionKind,
        now_ms: u64,
    ) -> Result<(), SessionError> {
        let building_id = require_building_id(building_id)?;
        if let Some(existing) = self.sessions.get_mut(&building_id) {
            existing.last_active_ms = now_ms;
            if kind == SessionKind::CsvGuest {
                existing.kind = SessionKind::CsvGuest;
            }
            return Ok(());
        }
        match kind {
            SessionKind::CsvGuest => self.evict_interactive_overflow(now_ms)?,
            SessionKind::MqttLive => self.evict_mqtt_overflow(),
        }
        self.sessions.insert(
            building_id.clone(),
            SessionRecord {
                building_id,
                kind,
                last_active_ms: now_ms,
                job_running: false,
                historian_loaded: false,
                mqtt_buffered_rows: 0,
            },
        );
        Ok(())
    }

    pub fn begin_job(&mut self, building_id: &str, now_ms: u64) -> Result<(), SessionError> {
        self.open(building_id, SessionKind::CsvGuest, now_ms)?;
        if let Some(rec) = self.sessions.get_mut(building_id) {
            rec.kind = SessionKind::CsvGuest;
            rec.job_running = true;
            rec.historian_loaded = true;
            rec.last_active_ms = now_ms;
            rec.mqtt_buffered_rows = 0;
        }
        Ok(())
    }

    /// Drop the historian working set after durable parquet results exist.
    /// The interactive lease stays until leave or idle so the active CSV
    /// building can remain the warm slot without holding Arrow tables.
    pub fn finish_job(&mut self, building_id: &str, now_ms: u64) {
        if let Some(rec) = self.sessions.get_mut(building_id) {
            rec.job_running = false;
            rec.historian_loaded = false;
            rec.last_active_ms = now_ms;
        }
    }

    pub fn leave(&mut self, building_id: &str) -> bool {
        self.sessions.remove(building_id).is_some()
    }

    pub fn evict_idle(&mut self, now_ms: u64) -> Vec<String> {
        let timeout = self.limits.idle_timeout_ms;
        let stale: Vec<String> = self
            .sessions
            .iter()
            .filter(|(_, rec)| {
                rec.kind == SessionKind::CsvGuest
                    && !rec.job_running
                    && now_ms.saturating_sub(rec.last_active_ms) >= timeout
            })
            .map(|(id, _)| id.clone())
            .collect();
        for id in &stale {
            self.sessions.remove(id);
        }
        stale
    }

    /// Record a live ingest buffer. Does not load historian parquet.
    pub fn note_mqtt(&mut self, building_id: &str, pending_rows: usize, now_ms: u64) -> Result<usize, SessionError> {
        let building_id = require_building_id(&building_id)?;
        if self
            .sessions
            .get(&building_id)
            .is_some_and(|rec| rec.kind == SessionKind::CsvGuest && rec.job_running)
        {
            return Ok(0);
        }
        self.open(&building_id, SessionKind::MqttLive, now_ms)?;
        let capped = pending_rows.min(self.limits.mqtt_buffer_rows);
        if let Some(rec) = self.sessions.get_mut(&building_id) {
            if rec.kind != SessionKind::CsvGuest {
                rec.kind = SessionKind::MqttLive;
            }
            rec.historian_loaded = false;
            rec.mqtt_buffered_rows = capped;
            rec.last_active_ms = now_ms;
        }
        Ok(capped)
    }

    pub fn interactive_slots(&self) -> Vec<String> {
        self.sessions
            .values()
            .filter(|rec| rec.kind == SessionKind::CsvGuest)
            .map(|rec| rec.building_id.clone())
            .collect()
    }

    pub fn historian_resident(&self) -> Vec<String> {
        self.sessions
            .values()
            .filter(|rec| rec.historian_loaded)
            .map(|rec| rec.building_id.clone())
            .collect()
    }

    /// Buildings whose working set should still occupy RAM: a loaded CSV
    /// historian, or a live MQTT buffer. Idle catalog packages are absent.
    pub fn ram_resident(&self) -> Vec<String> {
        self.sessions
            .values()
            .filter(|rec| rec.historian_loaded || rec.kind == SessionKind::MqttLive)
            .map(|rec| rec.building_id.clone())
            .collect()
    }

    fn evict_interactive_overflow(&mut self, _now_ms: u64) -> Result<(), SessionError> {
        while self.interactive_count() >= self.limits.max_interactive {
            let victim = self
                .sessions
                .values()
                .filter(|rec| rec.kind == SessionKind::CsvGuest && !rec.job_running)
                .min_by_key(|rec| rec.last_active_ms)
                .map(|rec| rec.building_id.clone());
            let Some(victim) = victim else {
                return Err(SessionError::AtCapacity {
                    max: self.limits.max_interactive,
                });
            };
            self.sessions.remove(&victim);
        }
        Ok(())
    }

    fn evict_mqtt_overflow(&mut self) {
        while self.mqtt_count() >= self.limits.max_mqtt_buffers {
            let victim = self
                .sessions
                .values()
                .filter(|rec| rec.kind == SessionKind::MqttLive && !rec.job_running)
                .min_by_key(|rec| rec.last_active_ms)
                .map(|rec| rec.building_id.clone());
            let Some(victim) = victim else {
                break;
            };
            self.sessions.remove(&victim);
        }
    }

    fn interactive_count(&self) -> usize {
        self.sessions
            .values()
            .filter(|rec| rec.kind == SessionKind::CsvGuest)
            .count()
    }

    fn mqtt_count(&self) -> usize {
        self.sessions
            .values()
            .filter(|rec| rec.kind == SessionKind::MqttLive)
            .count()
    }
}

fn require_building_id(building_id: &str) -> Result<String, SessionError> {
    let id = building_id.trim();
    if id.is_empty()
        || id.contains('/')
        || id.contains('\\')
        || id.contains("..")
        || id.contains('\0')
    {
        return Err(SessionError::UnsafeBuildingId);
    }
    Ok(id.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn book() -> SessionBook {
        SessionBook::new(SessionLimits::default())
    }

    #[test]
    fn catalog_list_does_not_open_sessions() {
        let mut book = book();
        book.note_catalog_list();
        assert!(book.interactive_slots().is_empty());
        assert!(book.ram_resident().is_empty());
    }

    #[test]
    fn interactive_cap_drops_the_oldest_csv_guest() {
        let mut book = book();
        book.open("site-a", SessionKind::CsvGuest, 1_000).unwrap();
        book.open("site-b", SessionKind::CsvGuest, 2_000).unwrap();
        book.open("site-c", SessionKind::CsvGuest, 3_000).unwrap();
        let slots = book.interactive_slots();
        assert_eq!(slots.len(), 2);
        assert!(!slots.iter().any(|id| id == "site-a"));
        assert!(book.historian_resident().is_empty());
    }

    #[test]
    fn job_finish_unloads_historian_and_leave_drops_the_lease() {
        let mut book = book();
        book.begin_job("site-a", 1_000).unwrap();
        assert_eq!(book.historian_resident(), vec!["site-a".to_string()]);
        assert_eq!(book.ram_resident(), vec!["site-a".to_string()]);
        book.finish_job("site-a", 1_500);
        assert!(book.historian_resident().is_empty());
        assert!(
            book.ram_resident().is_empty(),
            "finished CSV job must not keep historian RAM"
        );
        assert_eq!(book.interactive_slots(), vec!["site-a".to_string()]);
        assert!(book.leave("site-a"));
        assert!(book.interactive_slots().is_empty());
    }

    #[test]
    fn idle_timeout_drops_csv_lease_inside_30_to_120s_band() {
        let mut book = book();
        assert_eq!(book.limits().idle_timeout_ms, 60_000);
        book.open("site-a", SessionKind::CsvGuest, 0).unwrap();
        assert!(book.evict_idle(59_999).is_empty());
        assert_eq!(book.evict_idle(60_000), vec!["site-a".to_string()]);
        assert!(book.interactive_slots().is_empty());
    }

    #[test]
    fn running_job_is_not_idle_evicted() {
        let mut book = book();
        book.begin_job("site-a", 0).unwrap();
        assert!(book.evict_idle(120_000).is_empty());
        assert_eq!(book.historian_resident(), vec!["site-a".to_string()]);
    }

    #[test]
    fn mqtt_buffer_is_capped_and_does_not_load_historian() {
        let mut book = book();
        let capped = book.note_mqtt("site-live", 10_000, 5_000).unwrap();
        assert_eq!(capped, DEFAULT_MQTT_BUFFER_ROWS);
        assert!(book.historian_resident().is_empty());
        assert_eq!(book.ram_resident(), vec!["site-live".to_string()]);
        let rec = book.sessions.get("site-live").unwrap();
        assert_eq!(rec.kind, SessionKind::MqttLive);
        assert_eq!(rec.mqtt_buffered_rows, DEFAULT_MQTT_BUFFER_ROWS);
        assert!(!rec.historian_loaded);
        book.open("site-a", SessionKind::CsvGuest, 0).unwrap();
        assert!(book.evict_idle(120_000).contains(&"site-a".to_string()) || book.interactive_slots().is_empty());
        assert!(book.ram_resident().iter().any(|id| id == "site-live"));
    }

    #[test]
    fn hundreds_of_catalog_ids_are_not_resident() {
        let mut book = book();
        for i in 0..200 {
            let _ = i;
            book.note_catalog_list();
        }
        book.open("only-active", SessionKind::CsvGuest, 1).unwrap();
        assert_eq!(book.interactive_slots(), vec!["only-active".to_string()]);
        assert!(book.ram_resident().is_empty());
    }

    #[test]
    fn clamp_idle_band_and_interactive_default() {
        assert_eq!(clamp_idle_secs(1), 30);
        assert_eq!(clamp_idle_secs(90), 90);
        assert_eq!(clamp_idle_secs(500), 120);
        assert_eq!(clamp_max_interactive(0), 1);
        assert_eq!(DEFAULT_MAX_INTERACTIVE_SESSIONS, 2);
    }
}
