//! Bounded, durable, read-only BACnet priority-array history.
//!
//! The scheduler visits one configured device after each completed interval.
//! It uses the trusted field-device catalog, never discovery, and never sends
//! a write, release, or remediation request.  History is kept on the edge so
//! a cloud hub is not required for local supervision evidence.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{DateTime, Utc};
use openfdd_contracts::{
    ConnectorReadResult, ConnectorScope, PriorityHistoryRecord, PriorityHistoryRequest,
    PriorityHistoryResponse, PriorityScanConfig, PriorityScanStatus, PriorityScanTarget,
    ReadPriorityArrayResult, ReadPrioritySlot, ReadValueState, PRIORITY_SCAN_CONTRACT_V1,
    PRIORITY_SCAN_DEFAULT_INTERVAL_SECS, PRIORITY_SCAN_DEFAULT_MAX_POINTS_PER_DEVICE,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::task::JoinHandle;

use crate::config::{FieldDevice, Settings};
use crate::services::bacnet_client::BacnetClientService;

const STORE_VERSION: u8 = 1;
const DEFAULT_MAX_RECORDS: usize = 10_000;
const MAX_RECORDS: usize = 100_000;
const DEFAULT_STORE_FILE: &str = "state/priority-history.json";
const PRIORITY_SCAN_READ_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PersistedHistory {
    version: u8,
    next_sequence: u64,
    revision: u64,
    last_device_identity: Option<String>,
    records: Vec<PriorityHistoryRecord>,
}

impl Default for PersistedHistory {
    fn default() -> Self {
        Self {
            version: STORE_VERSION,
            next_sequence: 1,
            revision: 0,
            last_device_identity: None,
            records: Vec::new(),
        }
    }
}

#[derive(Debug)]
pub struct PriorityHistoryStore {
    path: PathBuf,
    max_records: usize,
    state: Mutex<PersistedHistory>,
}

impl PriorityHistoryStore {
    pub fn open(path: PathBuf, max_records: usize) -> Result<Arc<Self>, String> {
        let max_records = max_records.clamp(1, MAX_RECORDS);
        let state = load_history(&path, max_records)?;
        let store = Arc::new(Self {
            path,
            max_records,
            state: Mutex::new(state),
        });
        store.ensure_parent()?;
        Ok(store)
    }

    pub fn append(&self, mut record: PriorityHistoryRecord) -> Result<u64, String> {
        let mut guard = self.lock_state()?;
        let mut candidate = guard.clone();
        let sequence = candidate.next_sequence.max(1);
        record.sequence = sequence;
        record.validate()?;
        candidate.next_sequence = sequence.saturating_add(1);
        candidate.records.push(record);
        if candidate.records.len() > self.max_records {
            let remove = candidate.records.len() - self.max_records;
            candidate.records.drain(0..remove);
        }
        candidate.revision = candidate.revision.saturating_add(1).max(1);
        self.persist(&candidate)?;
        *guard = candidate;
        Ok(sequence)
    }

    pub fn set_last_device_identity(&self, identity: Option<String>) -> Result<(), String> {
        if identity
            .as_deref()
            .is_some_and(|value| value.trim().is_empty() || value.len() > 128)
        {
            return Err("priority scan device cursor is invalid".into());
        }
        let mut guard = self.lock_state()?;
        let mut candidate = guard.clone();
        candidate.last_device_identity = identity;
        self.persist(&candidate)?;
        *guard = candidate;
        Ok(())
    }

    pub fn last_device_identity(&self) -> Result<Option<String>, String> {
        Ok(self.lock_state()?.last_device_identity.clone())
    }

    pub fn revision(&self) -> Result<String, String> {
        Ok(format!("history-{:016x}", self.lock_state()?.revision))
    }

    pub fn records(&self) -> Result<Vec<PriorityHistoryRecord>, String> {
        Ok(self.lock_state()?.records.clone())
    }

    pub fn records_retained(&self) -> Result<u64, String> {
        Ok(self.lock_state()?.records.len() as u64)
    }

    fn ensure_parent(&self) -> Result<(), String> {
        if let Some(parent) = self
            .path
            .parent()
            .filter(|path| !path.as_os_str().is_empty())
        {
            fs::create_dir_all(parent)
                .map_err(|error| format!("create priority history directory: {error}"))?;
        }
        Ok(())
    }

    fn persist(&self, state: &PersistedHistory) -> Result<(), String> {
        self.ensure_parent()?;
        let encoded = serde_json::to_vec_pretty(state)
            .map_err(|error| format!("serialize priority history: {error}"))?;
        let temporary = self.path.with_extension("json.tmp");
        fs::write(&temporary, encoded)
            .map_err(|error| format!("write priority history: {error}"))?;
        fs::rename(&temporary, &self.path)
            .map_err(|error| format!("replace priority history: {error}"))?;
        Ok(())
    }

    fn lock_state(&self) -> Result<std::sync::MutexGuard<'_, PersistedHistory>, String> {
        self.state
            .lock()
            .map_err(|_| "priority history store lock poisoned".into())
    }
}

fn load_history(path: &Path, max_records: usize) -> Result<PersistedHistory, String> {
    if !path.exists() {
        return Ok(PersistedHistory::default());
    }
    let encoded = fs::read(path).map_err(|error| format!("read priority history: {error}"))?;
    let mut state: PersistedHistory = serde_json::from_slice(&encoded)
        .map_err(|error| format!("decode priority history: {error}"))?;
    if state.version != STORE_VERSION {
        return Err("unsupported priority history store version".into());
    }
    for record in &state.records {
        record.validate()?;
    }
    state.records.sort_by_key(|record| record.sequence);
    if state.records.len() > max_records {
        let remove = state.records.len() - max_records;
        state.records.drain(0..remove);
    }
    let next_sequence = state
        .records
        .iter()
        .map(|record| record.sequence)
        .max()
        .unwrap_or(0)
        .saturating_add(1)
        .max(state.next_sequence)
        .max(1);
    state.next_sequence = next_sequence;
    Ok(state)
}

#[derive(Debug, Clone)]
struct RuntimeStatus {
    last_started_at: Option<DateTime<Utc>>,
    last_completed_at: Option<DateTime<Utc>>,
    next_due_at: Option<DateTime<Utc>>,
    last_error: Option<String>,
}

impl Default for RuntimeStatus {
    fn default() -> Self {
        Self {
            last_started_at: None,
            last_completed_at: None,
            next_due_at: None,
            last_error: None,
        }
    }
}

/// The edge scanner and its durable history store.
pub struct PriorityScanService {
    client: Arc<BacnetClientService>,
    store: Arc<PriorityHistoryStore>,
    config: PriorityScanConfig,
    scope: Option<ConnectorScope>,
    runtime: Mutex<RuntimeStatus>,
    running: AtomicBool,
}

impl PriorityScanService {
    pub fn from_settings(
        settings: &Settings,
        client: Arc<BacnetClientService>,
    ) -> Result<Arc<Self>, String> {
        let config = priority_scan_config_from_env();
        let store = PriorityHistoryStore::open(
            priority_history_path_from_env(),
            priority_history_max_records_from_env(),
        )?;
        let scope = connector_scope(settings);
        Ok(Arc::new(Self {
            client,
            store,
            config,
            scope,
            runtime: Mutex::new(RuntimeStatus::default()),
            running: AtomicBool::new(false),
        }))
    }

    #[cfg(test)]
    pub fn for_tests(
        settings: &Settings,
        client: Arc<BacnetClientService>,
        path: PathBuf,
    ) -> Result<Arc<Self>, String> {
        let store = PriorityHistoryStore::open(path, 100)?;
        Ok(Arc::new(Self {
            client,
            store,
            config: PriorityScanConfig::default(),
            scope: connector_scope(settings),
            runtime: Mutex::new(RuntimeStatus::default()),
            running: AtomicBool::new(false),
        }))
    }

    pub fn enabled(&self) -> bool {
        self.config.enabled && self.scope.is_some()
    }

    pub fn status(&self) -> Result<PriorityScanStatus, String> {
        let scope = self
            .scope
            .clone()
            .ok_or_else(|| "priority scanner scope is not configured".to_string())?;
        let runtime = self
            .runtime
            .lock()
            .map_err(|_| "priority scanner status lock poisoned".to_string())?
            .clone();
        let status = PriorityScanStatus {
            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
            scope,
            enabled: self.config.enabled,
            interval_secs: self.config.interval_secs,
            max_points_per_device: self.config.max_points_per_device,
            catch_up: false,
            read_only: true,
            discovery_enabled: false,
            writes_enabled: false,
            last_started_at: runtime.last_started_at,
            last_completed_at: runtime.last_completed_at,
            next_due_at: runtime.next_due_at,
            last_device_identity: self.store.last_device_identity()?,
            last_error: runtime.last_error,
            records_retained: self.store.records_retained()?,
        };
        status.validate()?;
        Ok(status)
    }

    pub fn spawn(self: &Arc<Self>) -> Option<JoinHandle<()>> {
        if !self.enabled() {
            return None;
        }
        let service = Arc::clone(self);
        Some(tokio::spawn(async move {
            // Use sleep after each completed attempt rather than an interval;
            // a slow device never creates a catch-up burst.
            loop {
                let delay = Duration::from_secs(service.config.interval_secs);
                service.set_next_due(
                    Utc::now() + chrono::Duration::from_std(delay).unwrap_or_default(),
                );
                tokio::time::sleep(delay).await;
                if let Err(error) = service.run_once().await {
                    tracing::warn!(%error, "priority history scan failed");
                    service.set_error(Some(error));
                }
            }
        }))
    }

    /// Run exactly one device visit.  This is used by deterministic tests and
    /// remains read-only; the production scheduler calls it only when enabled.
    pub async fn run_once(&self) -> Result<usize, String> {
        if !self.config.enabled {
            return Ok(0);
        }
        let scope = self
            .scope
            .clone()
            .ok_or_else(|| "priority scanner scope is not configured".to_string())?;
        if self.running.swap(true, Ordering::AcqRel) {
            return Err("priority scan already in progress".into());
        }
        let result = self.run_one_device(scope).await;
        self.running.store(false, Ordering::Release);
        result
    }

    pub fn history(
        &self,
        request: &PriorityHistoryRequest,
    ) -> Result<PriorityHistoryResponse, String> {
        request.validate()?;
        let configured_scope = self
            .scope
            .as_ref()
            .ok_or_else(|| "priority scanner scope is not configured".to_string())?;
        if configured_scope != &request.scope {
            return Err("priority history scope is outside this edge".into());
        }
        let revision = self.store.revision()?;
        let records = self.store.records()?;
        let mut filtered: Vec<_> = records
            .into_iter()
            .filter(|record| {
                request
                    .target
                    .as_ref()
                    .is_none_or(|target| target == &record.target)
            })
            .collect();
        filtered.sort_by_key(|record| std::cmp::Reverse(record.sequence));
        let offset = request.offset_for_revision(&revision)?;
        if offset > filtered.len() {
            return Err("priority history cursor is outside retained history".into());
        }
        let end = offset
            .saturating_add(usize::from(request.page_size))
            .min(filtered.len());
        let page = filtered[offset..end].to_vec();
        let next_cursor = (end < filtered.len())
            .then(|| request.cursor_for_revision(&revision, end))
            .transpose()?;
        let scanner = self.status()?;
        let response = PriorityHistoryResponse {
            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: request.scope.clone(),
            revision,
            captured_at: Utc::now(),
            records: page,
            next_cursor,
            scanner,
        };
        response.validate_for(request)?;
        Ok(response)
    }

    async fn run_one_device(&self, scope: ConnectorScope) -> Result<usize, String> {
        let started = Utc::now();
        self.set_started(started);
        let configured_devices = self.client.configured_devices();
        let devices = enabled_devices(&configured_devices);
        let Some(device) = next_device(&devices, self.store.last_device_identity()?) else {
            let error = "no enabled field-device is configured".to_string();
            self.set_completed(Utc::now(), Some(error.clone()));
            return Err(error);
        };
        let identity = device_identity(device);
        let mut targets = configured_targets(device);
        targets.sort_by_key(|(target, _)| target.identity());
        targets.truncate(usize::from(self.config.max_points_per_device));

        let mut completed = 0usize;
        let mut first_error = None;
        for (target, label) in targets {
            let snapshot = match tokio::time::timeout(
                PRIORITY_SCAN_READ_TIMEOUT,
                self.client.read_priority_array(
                    target.device_instance,
                    &target.object_type,
                    target.object_instance,
                ),
            )
            .await
            {
                Ok(Ok(raw)) => match public_snapshot(raw, &target) {
                    Ok(snapshot) => snapshot,
                    Err(_) => {
                        first_error.get_or_insert_with(|| {
                            "priority read returned invalid data".to_string()
                        });
                        error_snapshot(&target, "priority read returned invalid data")
                    }
                },
                Ok(Err(_)) => {
                    first_error.get_or_insert_with(|| "priority read failed".to_string());
                    error_snapshot(&target, "priority read failed")
                }
                Err(_) => {
                    first_error.get_or_insert_with(|| "priority read timed out".to_string());
                    error_snapshot(&target, "priority read timed out")
                }
            };
            let record = PriorityHistoryRecord {
                sequence: 0,
                target,
                snapshot,
                label,
                source: "scheduled_scan".into(),
            };
            self.store.append(record)?;
            completed = completed.saturating_add(1);
        }
        // Advance the stable device cursor after the complete bounded visit,
        // including a visit where individual points returned typed errors.
        self.store.set_last_device_identity(Some(identity))?;
        let error = first_error;
        self.set_completed(Utc::now(), error.clone());
        if let Some(error) = error {
            tracing::warn!(%error, "priority scan completed with typed read errors");
        }
        let _ = scope;
        Ok(completed)
    }

    fn set_started(&self, at: DateTime<Utc>) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.last_started_at = Some(at);
            runtime.last_error = None;
        }
    }

    fn set_completed(&self, at: DateTime<Utc>, error: Option<String>) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.last_completed_at = Some(at);
            runtime.last_error = error;
            runtime.next_due_at = None;
        }
    }

    fn set_next_due(&self, at: DateTime<Utc>) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.next_due_at = Some(at);
        }
    }

    fn set_error(&self, error: Option<String>) {
        if let Ok(mut runtime) = self.runtime.lock() {
            runtime.last_error = error;
        }
    }
}

fn connector_scope(settings: &Settings) -> Option<ConnectorScope> {
    Some(ConnectorScope {
        tenant_id: settings.connector_tenant_id.clone()?.trim().to_string(),
        building_id: settings.connector_building_id.clone()?.trim().to_string(),
        edge_id: settings.connector_edge_id.clone()?.trim().to_string(),
    })
    .filter(|scope| scope.validate().is_ok())
}

fn enabled_devices(devices: &[FieldDevice]) -> Vec<&FieldDevice> {
    let mut devices: Vec<_> = devices.iter().filter(|device| device.enabled).collect();
    devices.sort_by_key(|device| device.device_instance);
    devices
}

fn device_identity(device: &FieldDevice) -> String {
    format!("bacnet-device:{}", device.device_instance)
}

fn next_device<'a>(devices: &[&'a FieldDevice], last: Option<String>) -> Option<&'a FieldDevice> {
    if devices.is_empty() {
        return None;
    }
    let start = last
        .and_then(|last| {
            devices
                .iter()
                .position(|device| device_identity(device) == last)
        })
        .map(|index| (index + 1) % devices.len())
        .unwrap_or(0);
    devices.get(start).copied()
}

fn configured_targets(device: &FieldDevice) -> Vec<(PriorityScanTarget, Option<String>)> {
    device
        .points
        .iter()
        .map(|point| {
            (
                PriorityScanTarget {
                    device_instance: device.device_instance,
                    object_type: point.object_type.to_ascii_lowercase(),
                    object_instance: point.object_instance,
                },
                (!point.point_name.trim().is_empty()).then(|| point.point_name.clone()),
            )
        })
        .filter(|(target, _)| target.validate().is_ok())
        .collect()
}

fn public_snapshot(
    value: Value,
    target: &PriorityScanTarget,
) -> Result<ReadPriorityArrayResult, String> {
    let object = value
        .as_object()
        .ok_or_else(|| "priority response is not an object".to_string())?;
    if object.get("device_instance").and_then(Value::as_u64)
        != Some(u64::from(target.device_instance))
        || object
            .get("object_identifier")
            .and_then(Value::as_str)
            .is_none_or(|value| {
                !value.eq_ignore_ascii_case(&format!(
                    "{},{}",
                    target.object_type, target.object_instance
                ))
            })
    {
        return Err("priority response target mismatch".into());
    }
    let raw_slots = object
        .get("priority_array")
        .and_then(Value::as_array)
        .ok_or_else(|| "priority response has no slots".to_string())?;
    let slots: Vec<ReadPrioritySlot> = raw_slots
        .iter()
        .cloned()
        .map(|raw| serde_json::from_value(raw).map_err(|_| "invalid priority slot".to_string()))
        .collect::<Result<_, _>>()?;
    let state = object
        .get("priority_array_state")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let snapshot = ReadPriorityArrayResult {
        device_instance: target.device_instance,
        object_type: target.object_type.clone(),
        object_instance: target.object_instance,
        slots,
        state,
        observed_at: Utc::now(),
    };
    ConnectorReadResult::PriorityArray(snapshot.clone())
        .validate_for_target(&target.read_target())
        .map_err(|error| error.to_string())?;
    Ok(snapshot)
}

fn error_snapshot(target: &PriorityScanTarget, message: &str) -> ReadPriorityArrayResult {
    ReadPriorityArrayResult {
        device_instance: target.device_instance,
        object_type: target.object_type.clone(),
        object_instance: target.object_instance,
        slots: (1..=16)
            .map(|priority_level| ReadPrioritySlot {
                priority_level,
                state: ReadValueState::Error,
                value_type: "error".into(),
                value: None,
                error: Some(message.into()),
            })
            .collect(),
        state: "unknown".into(),
        observed_at: Utc::now(),
    }
}

pub fn priority_scan_config_from_env() -> PriorityScanConfig {
    let enabled = env_bool("OPENFDD_PRIORITY_SCAN_ENABLED", false);
    let interval_secs = std::env::var("OPENFDD_PRIORITY_SCAN_INTERVAL_SECS")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(PRIORITY_SCAN_DEFAULT_INTERVAL_SECS);
    let max_points_per_device = std::env::var("OPENFDD_PRIORITY_SCAN_MAX_POINTS_PER_DEVICE")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(PRIORITY_SCAN_DEFAULT_MAX_POINTS_PER_DEVICE);
    let config = PriorityScanConfig {
        enabled,
        interval_secs,
        max_points_per_device,
    };
    if let Err(error) = config.validate() {
        tracing::warn!(%error, "invalid priority scan configuration; scheduler disabled");
        PriorityScanConfig {
            enabled: false,
            ..PriorityScanConfig::default()
        }
    } else {
        config
    }
}

fn priority_history_path_from_env() -> PathBuf {
    std::env::var("OPENFDD_PRIORITY_HISTORY_PATH")
        .ok()
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var("OPENFDD_EDGE_STORE_DIR")
                .ok()
                .map(|dir| PathBuf::from(dir).join("priority-history.json"))
        })
        .unwrap_or_else(|| PathBuf::from(DEFAULT_STORE_FILE))
}

fn priority_history_max_records_from_env() -> usize {
    std::env::var("OPENFDD_PRIORITY_HISTORY_MAX_RECORDS")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value: &usize| (1..=MAX_RECORDS).contains(value))
        .unwrap_or(DEFAULT_MAX_RECORDS)
}

fn env_bool(name: &str, default: bool) -> bool {
    match std::env::var(name).ok().as_deref() {
        None => default,
        Some(value) => matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        ),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use openfdd_contracts::{PRIORITY_SCAN_MAX_POINTS_PER_DEVICE, PRIORITY_SCAN_MIN_INTERVAL_SECS};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_path(label: &str) -> PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!("openfdd-priority-{label}-{stamp}.json"))
    }

    fn target(device_instance: u32, object_instance: u32) -> PriorityScanTarget {
        PriorityScanTarget {
            device_instance,
            object_type: "analog-output".into(),
            object_instance,
        }
    }

    fn record(device_instance: u32, object_instance: u32) -> PriorityHistoryRecord {
        let target = target(device_instance, object_instance);
        PriorityHistoryRecord {
            sequence: 1,
            target: target.clone(),
            snapshot: error_snapshot(&target, "priority read failed"),
            label: None,
            source: "scheduled_scan".into(),
        }
    }

    #[test]
    fn store_persists_bounded_history_and_stable_cursor() {
        let path = temp_path("bounded");
        let store = PriorityHistoryStore::open(path.clone(), 2).unwrap();
        store.append(record(1, 1)).unwrap();
        store.append(record(1, 2)).unwrap();
        store.append(record(1, 3)).unwrap();
        store
            .set_last_device_identity(Some("bacnet-device:1".into()))
            .unwrap();
        drop(store);

        let restored = PriorityHistoryStore::open(path.clone(), 2).unwrap();
        assert_eq!(restored.records().unwrap().len(), 2);
        assert_eq!(restored.records().unwrap()[0].sequence, 2);
        assert_eq!(
            restored.last_device_identity().unwrap().as_deref(),
            Some("bacnet-device:1")
        );
        let _ = fs::remove_file(path);
    }

    #[test]
    fn error_snapshot_is_exactly_sixteen_typed_error_slots() {
        let snapshot = error_snapshot(&target(7, 4), "priority read failed");
        assert_eq!(snapshot.slots.len(), 16);
        assert!(snapshot
            .slots
            .iter()
            .all(|slot| matches!(slot.state, ReadValueState::Error)));
        assert!(ConnectorReadResult::PriorityArray(snapshot)
            .validate_for_target(&target(7, 4).read_target())
            .is_ok());
    }

    #[test]
    fn next_device_wraps_by_stable_device_identity_without_catchup() {
        let devices = vec![];
        assert!(next_device(&devices, None).is_none());
        assert_eq!(PRIORITY_SCAN_MIN_INTERVAL_SECS, 300);
        assert_eq!(PRIORITY_SCAN_MAX_POINTS_PER_DEVICE, 1_000);
    }
}
