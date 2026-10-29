//! In-process ASAP catch-up telemetry for `GET /api/ingest/catchup`.

use std::collections::HashMap;
use std::sync::RwLock;

use chrono::{DateTime, Duration, Utc};

use super::asap_mode::CatchupMode;
use super::binding_state::DeviceBindingKey;

#[derive(Debug, Clone)]
pub struct DeviceCatchupSnapshot {
    pub mode: CatchupMode,
    pub last_stored_ts: Option<DateTime<Utc>>,
    pub missing_windows: u32,
    pub rows_per_minute: f64,
    pub eta_seconds: Option<i64>,
    pub throttle_paused_until: Option<DateTime<Utc>>,
    pub throttle_tokens_remaining: Option<i32>,
}

#[derive(Debug, Default)]
struct DeviceRuntime {
    mode: CatchupMode,
    missing_windows: u32,
    last_stored_ts: Option<DateTime<Utc>>,
    rows_per_minute: f64,
    eta_seconds: Option<i64>,
    throttle_paused_until: Option<DateTime<Utc>>,
    throttle_tokens_remaining: Option<i32>,
    sample_times: Vec<(DateTime<Utc>, u64)>,
}

#[derive(Debug, Default)]
pub struct CatchupRegistry {
    devices: HashMap<DeviceBindingKey, DeviceRuntime>,
    sites_fingerprint: u64,
}

impl CatchupRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn sites_fingerprint(&self) -> u64 {
        self.sites_fingerprint
    }

    pub fn set_sites_fingerprint(&mut self, fp: u64) {
        self.sites_fingerprint = fp;
    }

    pub fn record_finish(
        &mut self,
        key: &DeviceBindingKey,
        finished_at: DateTime<Utc>,
        rows_written: u64,
    ) {
        let entry = self.devices.entry(key.clone()).or_default();
        entry.sample_times.push((finished_at, rows_written));
        let cutoff = finished_at - Duration::minutes(5);
        entry
            .sample_times
            .retain(|(ts, _)| *ts >= cutoff);
        let total: u64 = entry.sample_times.iter().map(|(_, n)| n).sum();
        let minutes = 5_f64;
        entry.rows_per_minute = (total as f64) / minutes;
    }

    pub fn update_device(
        &mut self,
        key: &DeviceBindingKey,
        mode: CatchupMode,
        missing_windows: u32,
        last_stored_ts: Option<DateTime<Utc>>,
        eta_seconds: Option<i64>,
        throttle_paused_until: Option<DateTime<Utc>>,
        throttle_tokens_remaining: Option<i32>,
    ) {
        let entry = self.devices.entry(key.clone()).or_default();
        entry.mode = mode;
        entry.missing_windows = missing_windows;
        entry.last_stored_ts = last_stored_ts;
        entry.eta_seconds = eta_seconds;
        entry.throttle_paused_until = throttle_paused_until;
        entry.throttle_tokens_remaining = throttle_tokens_remaining;
    }

    pub fn snapshot(&self, key: &DeviceBindingKey) -> Option<DeviceCatchupSnapshot> {
        self.devices.get(key).map(|entry| DeviceCatchupSnapshot {
            mode: entry.mode,
            last_stored_ts: entry.last_stored_ts,
            missing_windows: entry.missing_windows,
            rows_per_minute: entry.rows_per_minute,
            eta_seconds: entry.eta_seconds,
            throttle_paused_until: entry.throttle_paused_until,
            throttle_tokens_remaining: entry.throttle_tokens_remaining,
        })
    }
}

pub type SharedCatchupRegistry = std::sync::Arc<RwLock<CatchupRegistry>>;

pub fn shared_registry() -> SharedCatchupRegistry {
    std::sync::Arc::new(RwLock::new(CatchupRegistry::new()))
}
