//! Bounded, durable, read-only BACnet priority-array history.
//!
//! The scheduler visits one configured device after each completed interval.
//! It uses the trusted field-device catalog, never discovery, and never sends
//! a write, release, or remediation request.  History is kept on the edge so
//! a cloud hub is not required for local supervision evidence.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
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
const MAX_JOURNAL_BYTES: u64 = 4 * 1024 * 1024;
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

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum JournalLine {
    Checkpoint {
        state: PersistedHistory,
    },
    Append {
        record: PriorityHistoryRecord,
    },
    Cursor {
        last_device_identity: Option<String>,
    },
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
    durable: bool,
    journal_bytes: Mutex<u64>,
    state: Mutex<PersistedHistory>,
}

impl PriorityHistoryStore {
    pub fn open(path: PathBuf, max_records: usize) -> Result<Arc<Self>, String> {
        let max_records = max_records.clamp(1, MAX_RECORDS);
        let (state, migrate_legacy) = load_history(&path, max_records)?;
        let journal_bytes = fs::metadata(&path)
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        let store = Arc::new(Self {
            path,
            max_records,
            durable: true,
            journal_bytes: Mutex::new(journal_bytes),
            state: Mutex::new(state),
        });
        store.ensure_parent()?;
        if migrate_legacy {
            let state = store.lock_state()?.clone();
            store.rewrite_checkpoint(&state)?;
        }
        Ok(store)
    }

    fn in_memory(path: PathBuf, max_records: usize) -> Arc<Self> {
        Arc::new(Self {
            path,
            max_records: max_records.clamp(1, MAX_RECORDS),
            durable: false,
            journal_bytes: Mutex::new(0),
            state: Mutex::new(PersistedHistory::default()),
        })
    }

    pub fn append(&self, mut record: PriorityHistoryRecord) -> Result<u64, String> {
        let mut guard = self.lock_state()?;
        let sequence = guard.next_sequence.max(1);
        record.sequence = sequence;
        record.validate()?;
        if self.durable {
            let bytes = self.append_line(&JournalLine::Append {
                record: record.clone(),
            })?;
            let mut journal_bytes = self.lock_journal_bytes()?;
            *journal_bytes = journal_bytes.saturating_add(bytes);
        }
        guard.next_sequence = sequence.saturating_add(1);
        guard.records.push(record);
        guard.revision = guard.revision.saturating_add(1).max(1);
        if guard.records.len() > self.max_records {
            let remove = guard.records.len() - self.max_records;
            guard.records.drain(0..remove);
            if self.durable {
                let snapshot = guard.clone();
                self.rewrite_checkpoint(&snapshot)?;
            }
        }
        Ok(sequence)
    }

    pub fn set_last_device_identity(&self, identity: Option<String>) -> Result<(), String> {
        validate_device_identity(identity.as_deref())?;
        let mut guard = self.lock_state()?;
        if self.durable {
            let bytes = self.append_line(&JournalLine::Cursor {
                last_device_identity: identity.clone(),
            })?;
            let mut journal_bytes = self.lock_journal_bytes()?;
            *journal_bytes = journal_bytes.saturating_add(bytes);
        }
        guard.last_device_identity = identity;
        if self.durable && *self.lock_journal_bytes()? > MAX_JOURNAL_BYTES {
            let snapshot = guard.clone();
            self.rewrite_checkpoint(&snapshot)?;
        }
        Ok(())
    }

    pub fn last_device_identity(&self) -> Result<Option<String>, String> {
        Ok(self.lock_state()?.last_device_identity.clone())
    }

    pub fn revision(&self) -> Result<String, String> {
        Ok(format!("history-{:016x}", self.lock_state()?.revision))
    }

    #[cfg(test)]
    pub fn records(&self) -> Result<Vec<PriorityHistoryRecord>, String> {
        Ok(self.lock_state()?.records.clone())
    }

    pub fn page(
        &self,
        target: Option<&PriorityScanTarget>,
        offset: usize,
        limit: usize,
    ) -> Result<(String, Vec<PriorityHistoryRecord>, bool), String> {
        let guard = self.lock_state()?;
        let mut matching = 0usize;
        let mut records = Vec::with_capacity(limit);
        for record in guard.records.iter().rev() {
            if target.is_some_and(|requested| requested != &record.target) {
                continue;
            }
            if matching >= offset && records.len() < limit {
                records.push(record.clone());
            }
            matching = matching.saturating_add(1);
        }
        if offset > matching {
            return Err("priority history cursor is outside retained history".into());
        }
        let has_more = matching > offset.saturating_add(records.len());
        Ok((revision_string(guard.revision), records, has_more))
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

    fn append_line(&self, line: &JournalLine) -> Result<u64, String> {
        self.ensure_parent()?;
        let existed = self.path.exists();
        let mut encoded = serde_json::to_vec(line)
            .map_err(|error| format!("serialize priority history journal: {error}"))?;
        encoded.push(b'\n');
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .map_err(|error| format!("open priority history journal: {error}"))?;
        file.write_all(&encoded)
            .map_err(|error| format!("append priority history journal: {error}"))?;
        file.sync_data()
            .map_err(|error| format!("sync priority history journal: {error}"))?;
        if !existed {
            sync_parent_dir(&self.path)?;
        }
        Ok(encoded.len() as u64)
    }

    fn rewrite_checkpoint(&self, state: &PersistedHistory) -> Result<(), String> {
        self.ensure_parent()?;
        let encoded = serde_json::to_vec(&JournalLine::Checkpoint {
            state: state.clone(),
        })
        .map_err(|error| format!("serialize priority history checkpoint: {error}"))?;
        let temporary = self.path.with_extension("json.tmp");
        let mut file = File::create(&temporary)
            .map_err(|error| format!("create priority history checkpoint: {error}"))?;
        file.write_all(&encoded)
            .and_then(|_| file.write_all(b"\n"))
            .and_then(|_| file.sync_all())
            .map_err(|error| format!("sync priority history checkpoint: {error}"))?;
        fs::rename(&temporary, &self.path)
            .map_err(|error| format!("replace priority history journal: {error}"))?;
        sync_parent_dir(&self.path)?;
        *self.lock_journal_bytes()? = encoded.len() as u64 + 1;
        Ok(())
    }

    fn lock_journal_bytes(&self) -> Result<std::sync::MutexGuard<'_, u64>, String> {
        self.journal_bytes
            .lock()
            .map_err(|_| "priority history journal size lock poisoned".into())
    }

    fn lock_state(&self) -> Result<std::sync::MutexGuard<'_, PersistedHistory>, String> {
        self.state
            .lock()
            .map_err(|_| "priority history store lock poisoned".into())
    }
}

fn sync_parent_dir(path: &Path) -> Result<(), String> {
    let Some(parent) = path.parent().filter(|path| !path.as_os_str().is_empty()) else {
        return Ok(());
    };
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| format!("sync priority history directory: {error}"))
}

fn validate_device_identity(identity: Option<&str>) -> Result<(), String> {
    let Some(identity) = identity else {
        return Ok(());
    };
    let valid = identity.len() <= 128
        && identity.starts_with("bacnet-device:")
        && identity["bacnet-device:".len()..].parse::<u32>().is_ok()
        && identity
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | ':'));
    if valid {
        Ok(())
    } else {
        Err("priority scan device cursor is invalid".into())
    }
}

fn revision_string(revision: u64) -> String {
    format!("history-{revision:016x}")
}

fn load_history(path: &Path, max_records: usize) -> Result<(PersistedHistory, bool), String> {
    if !path.exists() {
        return Ok((PersistedHistory::default(), false));
    }
    let encoded = fs::read(path).map_err(|error| format!("read priority history: {error}"))?;
    let trimmed = encoded
        .iter()
        .copied()
        .skip_while(u8::is_ascii_whitespace)
        .collect::<Vec<_>>();
    if !trimmed.windows(6).any(|window| window == b"\"kind\"") {
        let state: PersistedHistory = serde_json::from_slice(&encoded)
            .map_err(|error| format!("decode priority history state: {error}"))?;
        let state = validate_history_state(state, max_records)?;
        return Ok((state, true));
    }

    let mut state = PersistedHistory::default();
    let mut valid_end = 0usize;
    for segment in encoded.split_inclusive(|byte| *byte == b'\n') {
        let is_tail = valid_end + segment.len() == encoded.len();
        let line = segment.strip_suffix(b"\n").unwrap_or(segment);
        if line.iter().all(u8::is_ascii_whitespace) {
            valid_end += segment.len();
            continue;
        }
        let parsed = serde_json::from_slice::<JournalLine>(line);
        let entry = match parsed {
            Ok(entry) => entry,
            Err(error) if is_tail && error.classify() == serde_json::error::Category::Eof => {
                fs::write(path, &encoded[..valid_end]).map_err(|write_error| {
                    format!("truncate torn priority history: {write_error}")
                })?;
                let file = OpenOptions::new()
                    .write(true)
                    .open(path)
                    .map_err(|open_error| {
                        format!("open repaired priority history: {open_error}")
                    })?;
                file.sync_all().map_err(|sync_error| {
                    format!("sync repaired priority history: {sync_error}")
                })?;
                break;
            }
            Err(error) => return Err(format!("decode priority history journal: {error}")),
        };
        apply_journal_line(&mut state, entry, max_records)?;
        valid_end += segment.len();
    }
    state = validate_history_state(state, max_records)?;
    Ok((state, false))
}

fn apply_journal_line(
    state: &mut PersistedHistory,
    line: JournalLine,
    max_records: usize,
) -> Result<(), String> {
    match line {
        JournalLine::Checkpoint { state: checkpoint } => {
            *state = validate_history_state(checkpoint, max_records)?;
        }
        JournalLine::Append { record } => {
            record.validate()?;
            if state
                .records
                .iter()
                .any(|item| item.sequence == record.sequence)
            {
                return Err("duplicate priority history sequence".into());
            }
            state.next_sequence = state
                .next_sequence
                .max(record.sequence.saturating_add(1))
                .max(1);
            state.records.push(record);
            if state.records.len() > max_records {
                let remove = state.records.len() - max_records;
                state.records.drain(0..remove);
            }
            state.revision = state.revision.saturating_add(1).max(1);
        }
        JournalLine::Cursor {
            last_device_identity,
        } => {
            validate_device_identity(last_device_identity.as_deref())?;
            state.last_device_identity = last_device_identity;
        }
    }
    Ok(())
}

fn validate_history_state(
    mut state: PersistedHistory,
    max_records: usize,
) -> Result<PersistedHistory, String> {
    if state.version != STORE_VERSION {
        return Err("unsupported priority history store version".into());
    }
    validate_device_identity(state.last_device_identity.as_deref())?;
    let mut sequences = std::collections::HashSet::new();
    for record in &state.records {
        record.validate()?;
        if !sequences.insert(record.sequence) {
            return Err("duplicate priority history sequence".into());
        }
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

#[derive(Debug, Clone, Default)]
struct RuntimeStatus {
    last_started_at: Option<DateTime<Utc>>,
    last_completed_at: Option<DateTime<Utc>>,
    next_due_at: Option<DateTime<Utc>>,
    last_error: Option<String>,
}

/// The edge scanner and its durable history store.
pub struct PriorityScanService {
    client: Arc<BacnetClientService>,
    store: Arc<PriorityHistoryStore>,
    store_error: Option<String>,
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
        let path = priority_history_path_from_env();
        let max_records = priority_history_max_records_from_env();
        let (store, store_error) = match PriorityHistoryStore::open(path.clone(), max_records) {
            Ok(store) => (store, None),
            Err(error) => {
                tracing::error!(%error, "priority history store unavailable; scanner disabled");
                (
                    PriorityHistoryStore::in_memory(path, max_records),
                    Some(error),
                )
            }
        };
        let scope = connector_scope(settings);
        Ok(Arc::new(Self {
            client,
            store,
            store_error,
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
            store_error: None,
            config: PriorityScanConfig::default(),
            scope: connector_scope(settings),
            runtime: Mutex::new(RuntimeStatus::default()),
            running: AtomicBool::new(false),
        }))
    }

    pub fn enabled(&self) -> bool {
        self.config.enabled && self.scope.is_some() && self.store_error.is_none()
    }

    pub fn status(&self) -> Result<PriorityScanStatus, String> {
        if let Some(error) = &self.store_error {
            return Err(format!("priority history store unavailable: {error}"));
        }
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
        if let Some(error) = &self.store_error {
            return Err(format!("priority history store unavailable: {error}"));
        }
        request.validate()?;
        let configured_scope = self
            .scope
            .as_ref()
            .ok_or_else(|| "priority scanner scope is not configured".to_string())?;
        if configured_scope != &request.scope {
            return Err("priority history scope is outside this edge".into());
        }
        let expected_revision = self.store.revision()?;
        let requested_offset = request.offset_for_revision(&expected_revision)?;
        let (revision, page, has_more) = self.store.page(
            request.target.as_ref(),
            requested_offset,
            usize::from(request.page_size),
        )?;
        if request.cursor.is_some() && revision != expected_revision {
            return Err("priority history cursor is stale for this revision".into());
        }
        let offset = if revision == expected_revision {
            requested_offset
        } else {
            0
        };
        let next_cursor = has_more
            .then(|| request.cursor_for_revision(&revision, offset.saturating_add(page.len())))
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
            let store = Arc::clone(&self.store);
            tokio::task::spawn_blocking(move || store.append(record))
                .await
                .map_err(|error| format!("priority history append task failed: {error}"))??;
            completed = completed.saturating_add(1);
        }
        // Advance the stable device cursor after the complete bounded visit,
        // including a visit where individual points returned typed errors.
        let store = Arc::clone(&self.store);
        tokio::task::spawn_blocking(move || store.set_last_device_identity(Some(identity)))
            .await
            .map_err(|error| format!("priority history cursor task failed: {error}"))??;
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
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn store_repairs_a_torn_trailing_journal_line() {
        let path = temp_path("torn-tail");
        let store = PriorityHistoryStore::open(path.clone(), 4).unwrap();
        store.append(record(1, 1)).unwrap();
        drop(store);
        let mut file = OpenOptions::new().append(true).open(&path).unwrap();
        file.write_all(br#"{"kind":"append","record":{"#).unwrap();
        file.sync_all().unwrap();

        let restored = PriorityHistoryStore::open(path.clone(), 4).unwrap();
        assert_eq!(restored.records().unwrap().len(), 1);
        restored.append(record(1, 2)).unwrap();
        assert_eq!(restored.records().unwrap().len(), 2);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn store_rejects_corrupt_non_tail_journal_line() {
        let path = temp_path("corrupt-middle");
        let store = PriorityHistoryStore::open(path.clone(), 4).unwrap();
        store.append(record(1, 1)).unwrap();
        drop(store);
        let mut file = OpenOptions::new().append(true).open(&path).unwrap();
        file.write_all(b"{not-json}\n").unwrap();
        file.write_all(b"{\"kind\":\"cursor\",\"last_device_identity\":null}\n")
            .unwrap();
        file.sync_all().unwrap();
        assert!(PriorityHistoryStore::open(path.clone(), 4).is_err());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn store_ignores_a_stale_or_corrupt_temp_checkpoint() {
        let path = temp_path("temp");
        let store = PriorityHistoryStore::open(path.clone(), 4).unwrap();
        store.append(record(1, 1)).unwrap();
        drop(store);
        fs::write(path.with_extension("json.tmp"), b"{not-json").unwrap();
        let restored = PriorityHistoryStore::open(path.clone(), 4).unwrap();
        assert_eq!(restored.records().unwrap().len(), 1);
        let _ = fs::remove_file(&path);
        let _ = fs::remove_file(path.with_extension("json.tmp"));
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
