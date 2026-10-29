//! In-process ASAP catch-up telemetry for `GET /api/ingest/catchup`.

use std::collections::HashMap;
use std::sync::RwLock;

use chrono::{DateTime, Duration, Utc};

use super::asap_mode::CatchupMode;
use super::binding_state::DeviceBindingKey;

#[derive(Debug, Clone)]
pub struct DeviceCatchupUpdate {
    pub mode: CatchupMode,
    pub missing_windows: u32,
    pub last_stored_ts: Option<DateTime<Utc>>,
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
}

impl CatchupRegistry {
    pub fn new() -> Self {
        Self::default()
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
        entry.sample_times.retain(|(ts, _)| *ts >= cutoff);
        let total: u64 = entry.sample_times.iter().map(|(_, n)| n).sum();
        let minutes = 5_f64;
        entry.rows_per_minute = (total as f64) / minutes;
    }

    pub fn update_device(&mut self, key: &DeviceBindingKey, update: DeviceCatchupUpdate) {
        let entry = self.devices.entry(key.clone()).or_default();
        entry.mode = update.mode;
        entry.missing_windows = update.missing_windows;
        entry.last_stored_ts = update.last_stored_ts;
        entry.eta_seconds = update.eta_seconds;
        entry.throttle_paused_until = update.throttle_paused_until;
        entry.throttle_tokens_remaining = update.throttle_tokens_remaining;
    }

    pub fn rows_per_minute(&self, key: &DeviceBindingKey) -> f64 {
        self.devices
            .get(key)
            .map(|entry| entry.rows_per_minute)
            .unwrap_or(0.0)
    }
}

pub type SharedCatchupRegistry = std::sync::Arc<RwLock<CatchupRegistry>>;

pub fn shared_registry() -> SharedCatchupRegistry {
    std::sync::Arc::new(RwLock::new(CatchupRegistry::new()))
}
