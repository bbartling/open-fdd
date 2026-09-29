//! Shared central runtime state.

use std::collections::{BTreeSet, HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};
use openfdd_mqtt::AsyncClient;
use serde::Deserialize;
use serde::Serialize;
use tokio::sync::{Mutex as AsyncMutex, Semaphore};
use uuid::Uuid;

use crate::auth::AuthConfig;
use crate::live_historian::{LiveHistorian, LiveHistorianIngest, PersistedMessageGroup};
use crate::tenant_budget::TenantBudgetTracker;

const MQTT_MONITOR_CAPACITY: usize = 100;
const MQTT_PREVIEW_BYTES: usize = 4096;
const LOCAL_RECEIPTS_FILE: &str = "state/local-fieldbus-receipts.jsonl";
const RECEIPT_CAPACITY: usize = 50_000;
const PENDING_RECEIPT_CAPACITY: usize = 10_000;
static LIVE_WRITER_PERMITS: std::sync::OnceLock<std::sync::Arc<Semaphore>> =
    std::sync::OnceLock::new();

fn live_writer_permits() -> std::sync::Arc<Semaphore> {
    LIVE_WRITER_PERMITS
        .get_or_init(|| std::sync::Arc::new(Semaphore::new(1)))
        .clone()
}

fn equipment_key(building_id: &str, equipment_id: &str) -> String {
    format!("{building_id}\u{1f}{equipment_id}")
}

fn eligible_equipment_keys(envelope: &TelemetryEnvelope) -> BTreeSet<String> {
    envelope
        .points
        .iter()
        .filter_map(|point| {
            let building = point.tags.get("building_id")?.as_str()?;
            let equipment = point.tags.get("equipment_id")?.as_str()?;
            let role = point.tags.get("role")?.as_str()?;
            (!building.is_empty() && !equipment.is_empty() && !role.is_empty())
                .then(|| equipment_key(building, equipment))
        })
        .collect()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum IngestReceiptStatus {
    Pending,
    Committed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestReceipt {
    pub scope: String,
    pub edge_id: String,
    pub message_id: Uuid,
    pub status: IngestReceiptStatus,
    pub envelope: TelemetryEnvelope,
    #[serde(default)]
    pub persisted_rows: usize,
    #[serde(default)]
    pub expected_equipment: BTreeSet<String>,
    #[serde(default)]
    pub persisted_equipment: BTreeSet<String>,
    #[serde(default = "default_receipt_observed_at")]
    pub observed_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ReceiptJournalEntry {
    scope: String,
    edge_id: String,
    message_id: Uuid,
    receipt: Option<IngestReceipt>,
}

#[derive(Debug, Default)]
pub struct EdgeShadow {
    pub last_status: Option<serde_json::Value>,
    pub last_telemetry: Option<TelemetryEnvelope>,
    /// Site/building from MQTT topic path (status/metadata/discovery/telemetry).
    /// Retained when `last_telemetry` is absent so `/api/edges` still attributes site.
    pub registered_site_id: Option<String>,
    /// protocol slug → last metadata payload
    pub last_metadata: HashMap<String, serde_json::Value>,
    /// protocol slug → last discovery payload
    pub last_discovery: HashMap<String, serde_json::Value>,
    pub sequences: HashMap<String, u64>,
}

impl EdgeShadow {
    /// Prefer latest telemetry site; else last known topic registration. Never invents `lab`.
    pub fn known_site_id(&self) -> Option<String> {
        self.last_telemetry
            .as_ref()
            .map(|t| t.site_id.clone())
            .filter(|s| !s.is_empty())
            .or_else(|| self.registered_site_id.clone().filter(|s| !s.is_empty()))
    }
}

#[derive(Debug, Clone)]
#[allow(dead_code)] // retained for ack correlation / audit surfaces
pub struct PendingCommand {
    pub command: CommandEnvelope,
    pub publish_topic: String,
    pub response_topic: String,
    pub issued_at: DateTime<Utc>,
    pub published: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct MqttObservedMessage {
    pub received_at_utc: DateTime<Utc>,
    pub topic: String,
    pub qos: String,
    pub retain: bool,
    pub payload_bytes: usize,
    pub payload_encoding: String,
    pub payload_preview: String,
    pub truncated: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct MqttMonitorEvent {
    pub at_utc: DateTime<Utc>,
    pub kind: String,
    pub message: String,
}

#[derive(Debug, Default)]
struct MqttMonitorState {
    connected: bool,
    client_id: Option<String>,
    subscriptions: Vec<String>,
    received_messages: u64,
    reconnects: u64,
    errors: u64,
    recent_messages: VecDeque<MqttObservedMessage>,
    recent_events: VecDeque<MqttMonitorEvent>,
}

#[derive(Debug, Clone, Serialize)]
pub struct MqttMonitorSnapshot {
    pub connected: bool,
    pub client_id: Option<String>,
    pub subscriptions: Vec<String>,
    pub received_messages: u64,
    pub reconnects: u64,
    pub errors: u64,
    pub buffer_capacity: usize,
    pub recent_messages: Vec<MqttObservedMessage>,
    pub recent_events: Vec<MqttMonitorEvent>,
    pub test_publish_enabled: bool,
}

pub struct AppState {
    pub auth: AuthConfig,
    /// (edge_id, message_id) → observed
    pub seen_messages: DashMap<(String, Uuid), ()>,
    pub edges: DashMap<String, Mutex<EdgeShadow>>,
    pub command_acks: DashMap<Uuid, CommandAck>,
    pub pending_commands: DashMap<Uuid, PendingCommand>,
    pub dead_letters: Mutex<Vec<serde_json::Value>>,
    pub ingest_ok: Mutex<u64>,
    pub ingest_dup: Mutex<u64>,
    pub ingest_reject: Mutex<u64>,
    /// Count-only reject reason buckets for `/api/ingest/stats` (no dead-letter dump).
    pub ingest_reject_buckets: Mutex<std::collections::BTreeMap<String, u64>>,
    /// Process boot instant for `/api/health` honesty after re-pin.
    pub started_at: DateTime<Utc>,
    /// Last successful ingest accept this process (MQTT/CSV paths that bump `ingest_ok`).
    pub last_ingest_at: Mutex<Option<DateTime<Utc>>>,
    pub mqtt_publisher: Mutex<Option<AsyncClient>>,
    mqtt_monitor: Mutex<MqttMonitorState>,
    /// Login failures keyed by ip+username (generic throttle; no secrets).
    pub login_failures: Mutex<HashMap<String, (u32, std::time::Instant)>>,
    /// Wave L L5 — per-tenant sliding-window budgets (noop when disabled).
    pub tenant_budgets: TenantBudgetTracker,
    /// One canonical writer shared by MQTT and local HTTP delivery.
    pub live_historian: std::sync::Arc<Mutex<Option<LiveHistorian>>>,
    /// Durable pending/committed receipt ledger for replay-safe local ingest.
    pub ingest_receipts: AsyncMutex<HashMap<(String, String, Uuid), IngestReceipt>>,
    pub ingest_receipts_path: PathBuf,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            auth: AuthConfig::load(),
            seen_messages: DashMap::new(),
            edges: DashMap::new(),
            command_acks: DashMap::new(),
            pending_commands: DashMap::new(),
            dead_letters: Mutex::new(Vec::new()),
            ingest_ok: Mutex::new(0),
            ingest_dup: Mutex::new(0),
            ingest_reject: Mutex::new(0),
            ingest_reject_buckets: Mutex::new(std::collections::BTreeMap::new()),
            started_at: Utc::now(),
            last_ingest_at: Mutex::new(None),
            mqtt_publisher: Mutex::new(None),
            mqtt_monitor: Mutex::new(MqttMonitorState::default()),
            login_failures: Mutex::new(HashMap::new()),
            tenant_budgets: TenantBudgetTracker::new(),
            live_historian: std::sync::Arc::new(Mutex::new(None)),
            ingest_receipts: AsyncMutex::new(load_receipts()),
            ingest_receipts_path: receipts_path(),
        }
    }

    pub async fn reserve_receipt_at(&self, scope: &str, envelope: TelemetryEnvelope) -> bool {
        let edge_id = envelope.edge_id.clone();
        let message_id = envelope.message_id;
        let observed_at = envelope.observed_at;
        let expected_equipment = eligible_equipment_keys(&envelope);
        let key = (scope.to_string(), edge_id.clone(), message_id);
        let mut receipts = self.ingest_receipts.lock().await;
        if receipts.contains_key(&key) {
            return false;
        }
        if receipts.len() >= RECEIPT_CAPACITY
            || receipts
                .values()
                .filter(|receipt| receipt.status == IngestReceiptStatus::Pending)
                .count()
                >= PENDING_RECEIPT_CAPACITY
        {
            return false;
        }
        receipts.insert(
            key,
            IngestReceipt {
                scope: scope.to_string(),
                edge_id: edge_id.clone(),
                message_id,
                status: IngestReceiptStatus::Pending,
                observed_at,
                envelope,
                persisted_rows: 0,
                expected_equipment,
                persisted_equipment: BTreeSet::new(),
                updated_at: Utc::now(),
            },
        );
        let receipt = receipts
            .get(&(scope.to_string(), edge_id.clone(), message_id))
            .cloned();
        if enforce_receipt_capacity(&mut receipts)
            && append_receipt_event(
                &self.ingest_receipts_path,
                scope,
                &edge_id,
                message_id,
                receipt.as_ref(),
            )
            .await
        {
            maybe_compact_receipt_journal(&self.ingest_receipts_path, &receipts).await;
            true
        } else {
            receipts.remove(&(scope.to_string(), edge_id, message_id));
            false
        }
    }

    pub async fn release_receipt(&self, scope: &str, edge_id: &str, message_id: Uuid) {
        let mut receipts = self.ingest_receipts.lock().await;
        receipts.remove(&(scope.to_string(), edge_id.to_string(), message_id));
        if append_receipt_event(&self.ingest_receipts_path, scope, edge_id, message_id, None).await
        {
            maybe_compact_receipt_journal(&self.ingest_receipts_path, &receipts).await;
        }
    }

    #[cfg(test)]
    pub async fn commit_receipt(&self, scope: &str, edge_id: &str, message_id: Uuid) -> bool {
        self.commit_receipt_rows(scope, edge_id, message_id, None)
            .await
    }

    #[cfg(test)]
    async fn commit_receipt_rows(
        &self,
        scope: &str,
        edge_id: &str,
        message_id: Uuid,
        persisted_rows: Option<usize>,
    ) -> bool {
        let mut receipts = self.ingest_receipts.lock().await;
        let key = (scope.to_string(), edge_id.to_string(), message_id);
        let Some(previous) = receipts.get(&key).cloned() else {
            return false;
        };
        let mut updated = previous.clone();
        updated.status = IngestReceiptStatus::Committed;
        if let Some(rows) = persisted_rows {
            updated.persisted_rows = rows;
        }
        updated.updated_at = Utc::now();
        receipts.insert(key.clone(), updated.clone());
        let snapshot = Some(updated);
        if append_receipt_event(
            &self.ingest_receipts_path,
            scope,
            edge_id,
            message_id,
            snapshot.as_ref(),
        )
        .await
        {
            maybe_compact_receipt_journal(&self.ingest_receipts_path, &receipts).await;
            true
        } else {
            receipts.insert(key, previous);
            false
        }
    }

    /// Apply published row provenance to one tenant/building and edge scope.
    /// A receipt is committed only after all eligible equipment groups arrive.
    pub async fn commit_persisted_receipts_for(
        &self,
        scope: &str,
        edge_id: &str,
        groups: &[PersistedMessageGroup],
    ) -> usize {
        let mut committed = 0;
        for group in groups {
            let key = (scope.to_string(), edge_id.to_string(), group.message_id);
            let mut receipts = self.ingest_receipts.lock().await;
            let Some(previous) = receipts.get(&key).cloned() else {
                continue;
            };
            if previous.status == IngestReceiptStatus::Committed {
                continue;
            }
            let mut updated = previous.clone();
            updated.persisted_rows = updated.persisted_rows.saturating_add(group.rows);
            updated
                .persisted_equipment
                .insert(equipment_key(&group.building_id, &group.equipment_id));
            if updated.expected_equipment.is_empty()
                || updated
                    .expected_equipment
                    .is_subset(&updated.persisted_equipment)
            {
                updated.status = IngestReceiptStatus::Committed;
                committed += 1;
            }
            updated.updated_at = Utc::now();
            let event = Some(updated.clone());
            if append_receipt_event(
                &self.ingest_receipts_path,
                scope,
                edge_id,
                group.message_id,
                event.as_ref(),
            )
            .await
            {
                receipts.insert(key, updated);
                maybe_compact_receipt_journal(&self.ingest_receipts_path, &receipts).await;
            }
        }
        committed
    }

    #[cfg(test)]
    pub async fn commit_persisted_receipts(&self, message_ids: &[Uuid]) -> usize {
        let mut counts = HashMap::<Uuid, usize>::new();
        for id in message_ids {
            *counts.entry(*id).or_default() += 1;
        }
        let keys: Vec<_> = self
            .ingest_receipts
            .lock()
            .await
            .iter()
            .filter(|(_, receipt)| counts.contains_key(&receipt.message_id))
            .map(|(key, _)| key.clone())
            .collect();
        let mut committed = 0;
        for (scope, edge, id) in keys {
            if self
                .commit_receipt_rows(&scope, &edge, id, counts.get(&id).copied())
                .await
            {
                committed += 1;
            }
        }
        committed
    }

    pub async fn ingest_live(
        &self,
        scope: &str,
        env: &TelemetryEnvelope,
    ) -> anyhow::Result<LiveHistorianIngest> {
        let permit = live_writer_permits()
            .acquire_owned()
            .await
            .map_err(|_| anyhow::anyhow!("live historian writer stopped"))?;
        let historian = std::sync::Arc::clone(&self.live_historian);
        let envelope = env.clone();
        let report = tokio::task::spawn_blocking(move || {
            let mut historian = historian
                .lock()
                .map_err(|_| anyhow::anyhow!("live historian writer lock poisoned"))?;
            if historian.is_none() {
                *historian = Some(LiveHistorian::from_env_scoped()?);
            }
            historian
                .as_mut()
                .expect("live historian initialized")
                .ingest_envelope(&envelope)
        })
        .await
        .map_err(|error| anyhow::anyhow!("live historian writer task failed: {error}"))??;
        drop(permit);
        self.commit_persisted_receipts_for(scope, &env.edge_id, &report.persisted_message_groups)
            .await;
        Ok(report)
    }

    pub async fn flush_live(&self, graceful: bool) -> anyhow::Result<LiveHistorianIngest> {
        let permit = live_writer_permits()
            .acquire_owned()
            .await
            .map_err(|_| anyhow::anyhow!("live historian writer stopped"))?;
        let historian = std::sync::Arc::clone(&self.live_historian);
        let report = tokio::task::spawn_blocking(move || {
            let mut historian = historian
                .lock()
                .map_err(|_| anyhow::anyhow!("live historian writer lock poisoned"))?;
            let Some(historian) = historian.as_mut() else {
                return Ok(LiveHistorianIngest::default());
            };
            if graceful {
                historian.shutdown_flush()
            } else {
                historian.flush_due()
            }
        })
        .await
        .map_err(|error| anyhow::anyhow!("live historian writer task failed: {error}"))??;
        drop(permit);
        for group in &report.persisted_message_groups {
            let scope = format!(
                "tenant={};building={}",
                std::env::var("OPENFDD_TENANT_ID").unwrap_or_else(|_| "-".into()),
                group.building_id
            );
            self.commit_persisted_receipts_for(&scope, &group.edge_id, std::slice::from_ref(group))
                .await;
        }
        Ok(report)
    }

    pub async fn receipt_status(
        &self,
        scope: &str,
        edge_id: &str,
        message_id: Uuid,
    ) -> Option<IngestReceiptStatus> {
        self.ingest_receipts
            .lock()
            .await
            .get(&(scope.to_string(), edge_id.to_string(), message_id))
            .map(|receipt| receipt.status)
    }

    pub async fn receipt_persisted_rows(
        &self,
        scope: &str,
        edge_id: &str,
        message_id: Uuid,
    ) -> Option<usize> {
        self.ingest_receipts
            .lock()
            .await
            .get(&(scope.to_string(), edge_id.to_string(), message_id))
            .map(|receipt| receipt.persisted_rows)
    }

    /// Record a successful ingest accept (bumps counter + last_ingest_at).
    pub fn note_ingest_ok(&self) {
        *self.ingest_ok.lock().unwrap() += 1;
        *self.last_ingest_at.lock().unwrap() = Some(Utc::now());
    }

    pub fn set_mqtt_publisher(&self, client: AsyncClient) {
        *self.mqtt_publisher.lock().unwrap() = Some(client);
    }

    pub fn mqtt_mark_connected(&self, client_id: String, subscriptions: Vec<String>) {
        let mut monitor = self.mqtt_monitor.lock().unwrap();
        if monitor.client_id.is_some() {
            monitor.reconnects = monitor.reconnects.saturating_add(1);
        }
        monitor.connected = true;
        monitor.client_id = Some(client_id);
        monitor.subscriptions = subscriptions;
        push_monitor_event(&mut monitor, "connected", "MQTT ingest connected");
    }

    pub fn mqtt_mark_disconnected(&self, message: impl Into<String>) {
        let mut monitor = self.mqtt_monitor.lock().unwrap();
        monitor.connected = false;
        push_monitor_event(&mut monitor, "disconnected", message.into());
    }

    pub fn mqtt_record_error(&self, message: impl Into<String>) {
        let mut monitor = self.mqtt_monitor.lock().unwrap();
        monitor.connected = false;
        monitor.errors = monitor.errors.saturating_add(1);
        push_monitor_event(&mut monitor, "error", message.into());
    }

    pub fn mqtt_observe(&self, topic: &str, payload: &[u8], qos: String, retain: bool) {
        let mut monitor = self.mqtt_monitor.lock().unwrap();
        monitor.received_messages = monitor.received_messages.saturating_add(1);
        let preview_len = payload.len().min(MQTT_PREVIEW_BYTES);
        let preview_bytes = &payload[..preview_len];
        let (payload_encoding, payload_preview) =
            match serde_json::from_slice::<serde_json::Value>(preview_bytes) {
                Ok(value) if payload.len() <= MQTT_PREVIEW_BYTES => (
                    "json".to_string(),
                    serde_json::to_string_pretty(&value).unwrap_or_default(),
                ),
                _ => match std::str::from_utf8(preview_bytes) {
                    Ok(text) => ("text".to_string(), text.to_string()),
                    Err(_) => (
                        "hex".to_string(),
                        preview_bytes
                            .iter()
                            .map(|byte| format!("{byte:02x}"))
                            .collect::<Vec<_>>()
                            .join(" "),
                    ),
                },
            };
        monitor.recent_messages.push_front(MqttObservedMessage {
            received_at_utc: Utc::now(),
            topic: topic.to_string(),
            qos,
            retain,
            payload_bytes: payload.len(),
            payload_encoding,
            payload_preview,
            truncated: payload.len() > MQTT_PREVIEW_BYTES,
        });
        monitor.recent_messages.truncate(MQTT_MONITOR_CAPACITY);
    }

    pub fn mqtt_monitor_snapshot(&self) -> MqttMonitorSnapshot {
        let monitor = self.mqtt_monitor.lock().unwrap();
        MqttMonitorSnapshot {
            connected: monitor.connected,
            client_id: monitor.client_id.clone(),
            subscriptions: monitor.subscriptions.clone(),
            received_messages: monitor.received_messages,
            reconnects: monitor.reconnects,
            errors: monitor.errors,
            buffer_capacity: MQTT_MONITOR_CAPACITY,
            recent_messages: monitor.recent_messages.iter().cloned().collect(),
            recent_events: monitor.recent_events.iter().cloned().collect(),
            test_publish_enabled: false,
        }
    }

    /// Returns true if this key is currently locked out.
    pub fn login_is_throttled(&self, key: &str) -> bool {
        const MAX_FAILS: u32 = 8;
        const WINDOW: Duration = Duration::from_secs(15 * 60);
        let mut map = self.login_failures.lock().unwrap();
        match map.get(key) {
            Some((n, at)) if *n >= MAX_FAILS && at.elapsed() < WINDOW => true,
            Some((_, at)) if at.elapsed() >= WINDOW => {
                map.remove(key);
                false
            }
            _ => false,
        }
    }

    pub fn login_record_failure(&self, key: &str) {
        let mut map = self.login_failures.lock().unwrap();
        let entry = map.entry(key.to_string()).or_insert((0, Instant::now()));
        if entry.1.elapsed() > Duration::from_secs(15 * 60) {
            *entry = (1, Instant::now());
        } else {
            entry.0 = entry.0.saturating_add(1);
            entry.1 = Instant::now();
        }
    }

    pub fn login_record_success(&self, key: &str) {
        self.login_failures.lock().unwrap().remove(key);
    }
}

fn push_monitor_event(monitor: &mut MqttMonitorState, kind: &str, message: impl Into<String>) {
    monitor.recent_events.push_front(MqttMonitorEvent {
        at_utc: Utc::now(),
        kind: kind.to_string(),
        message: message.into(),
    });
    monitor.recent_events.truncate(MQTT_MONITOR_CAPACITY);
}

fn receipts_path() -> PathBuf {
    PathBuf::from(std::env::var("OPENFDD_WORKSPACE").unwrap_or_else(|_| "workspace".into()))
        .join(LOCAL_RECEIPTS_FILE)
}

fn default_receipt_observed_at() -> DateTime<Utc> {
    Utc::now()
}

fn load_receipts() -> HashMap<(String, String, Uuid), IngestReceipt> {
    load_receipts_at(&receipts_path()).unwrap_or_else(|error| {
        panic!("local fieldbus receipt journal is corrupt; refusing startup: {error}")
    })
}

fn load_receipts_at(
    path: &std::path::Path,
) -> Result<HashMap<(String, String, Uuid), IngestReceipt>, String> {
    let Ok(bytes) = std::fs::read(path) else {
        return Ok(HashMap::new());
    };
    let mut receipts = HashMap::new();
    for line in bytes
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
    {
        let event: ReceiptJournalEntry = serde_json::from_slice(line)
            .map_err(|error| format!("decode receipt journal entry: {error}"))?;
        let key = (event.scope, event.edge_id, event.message_id);
        if let Some(receipt) = event.receipt {
            receipts.insert(key, receipt);
        } else {
            receipts.remove(&key);
        }
    }
    Ok(receipts)
}

async fn append_receipt_event(
    path: &std::path::Path,
    scope: &str,
    edge_id: &str,
    message_id: Uuid,
    receipt: Option<&IngestReceipt>,
) -> bool {
    let Some(parent) = path.parent() else {
        return false;
    };
    if tokio::fs::create_dir_all(parent).await.is_err() {
        return false;
    }
    let Ok(mut bytes) = serde_json::to_vec(&ReceiptJournalEntry {
        scope: scope.to_string(),
        edge_id: edge_id.to_string(),
        message_id,
        receipt: receipt.cloned(),
    }) else {
        return false;
    };
    bytes.push(b'\n');
    let path = path.to_path_buf();
    tokio::task::spawn_blocking(move || {
        use std::io::Write;
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .ok()?;
        file.write_all(&bytes).ok()?;
        file.sync_data().ok()?;
        Some(())
    })
    .await
    .ok()
    .flatten()
    .is_some()
}

fn enforce_receipt_capacity(receipts: &mut HashMap<(String, String, Uuid), IngestReceipt>) -> bool {
    // Replay keys are retained for the full bounded ledger horizon. Never
    // evict a committed id without a durable tombstone: once the cap is
    // reached reserve_receipt_at applies backpressure instead.
    receipts.len() <= RECEIPT_CAPACITY
}

const RECEIPT_COMPACTION_BYTES: u64 = 8 * 1024 * 1024;

/// Rewrite the receipt journal from the live map once it grows beyond a fixed
/// bound. The temporary file is fsynced before rename, so a crash leaves either
/// the old complete journal or the new complete snapshot.
async fn maybe_compact_receipt_journal(
    path: &std::path::Path,
    receipts: &HashMap<(String, String, Uuid), IngestReceipt>,
) {
    let oversized = tokio::fs::metadata(path)
        .await
        .map(|metadata| metadata.len() >= RECEIPT_COMPACTION_BYTES)
        .unwrap_or(false);
    if !oversized {
        return;
    }
    let entries: Vec<ReceiptJournalEntry> = receipts
        .values()
        .map(|receipt| ReceiptJournalEntry {
            scope: receipt.scope.clone(),
            edge_id: receipt.edge_id.clone(),
            message_id: receipt.message_id,
            receipt: Some(receipt.clone()),
        })
        .collect();
    let path = path.to_path_buf();
    let _ = tokio::task::spawn_blocking(move || {
        use std::io::Write;
        let temp = path.with_extension("jsonl.compact.tmp");
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&temp)
            .ok()?;
        for entry in entries {
            let mut line = serde_json::to_vec(&entry).ok()?;
            line.push(b'\n');
            file.write_all(&line).ok()?;
        }
        file.sync_all().ok()?;
        std::fs::rename(&temp, &path).ok()?;
        if let Some(parent) = path.parent() {
            std::fs::File::open(parent).ok()?.sync_all().ok()?;
        }
        Some(())
    })
    .await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn receipt_reservation_is_single_writer_and_restart_safe() {
        let temp = tempfile::tempdir().unwrap();
        let mut state = AppState::new();
        state.ingest_receipts_path = temp.path().join("receipts.json");
        let envelope = TelemetryEnvelope::new(
            "building-local",
            "edge-local",
            openfdd_contracts::Protocol::Bacnet,
            1,
            vec![openfdd_contracts::TelemetryPoint {
                id: "point-local".into(),
                display_name: None,
                kind: None,
                value: serde_json::json!(1),
                unit: None,
                quality: openfdd_contracts::Quality::Good,
                tags: serde_json::json!({"building_id":"building-local", "equipment_id":"equipment-local", "role":"sample"}).as_object().unwrap().clone(),
            }],
        );
        let message_id = envelope.message_id;
        let results = futures_util::future::join_all(
            (0..16).map(|_| state.reserve_receipt_at("tenant-a/building-local", envelope.clone())),
        )
        .await;
        assert_eq!(results.into_iter().filter(|accepted| *accepted).count(), 1);

        state
            .commit_receipt("tenant-a/building-local", "edge-local", message_id)
            .await;
        let restarted = load_receipts_at(&state.ingest_receipts_path).unwrap();
        assert_eq!(
            restarted
                .get(&(
                    "tenant-a/building-local".to_string(),
                    "edge-local".to_string(),
                    message_id
                ))
                .map(|receipt| receipt.status),
            Some(IngestReceiptStatus::Committed)
        );

        // A response lost after commit is a duplicate on restart, while an
        // initial write failure can be released and retried with the same ID.
        assert!(
            !state
                .reserve_receipt_at("tenant-a/building-local", envelope.clone())
                .await
        );
        let failed_id = Uuid::new_v4();
        let mut failed_state = AppState::new();
        failed_state.ingest_receipts_path = temp.path().to_path_buf();
        assert!(
            !failed_state
                .reserve_receipt_at("tenant-a/building-local", {
                    let mut copy = envelope.clone();
                    copy.message_id = failed_id;
                    copy
                })
                .await
        );
        assert!(failed_state
            .receipt_status("tenant-a/building-local", "edge-local", failed_id)
            .await
            .is_none());
        assert!(
            state
                .reserve_receipt_at("tenant-a/building-local", {
                    let mut copy = envelope.clone();
                    copy.message_id = failed_id;
                    copy
                })
                .await
        );
        state
            .release_receipt("tenant-a/building-local", "edge-local", failed_id)
            .await;
        assert!(
            state
                .reserve_receipt_at("tenant-a/building-local", {
                    let mut copy = envelope;
                    copy.message_id = failed_id;
                    copy
                })
                .await
        );

        let persisted_id = Uuid::new_v4();
        let mut persisted = TelemetryEnvelope::new(
            "building-local",
            "edge-local",
            openfdd_contracts::Protocol::Bacnet,
            2,
            Vec::new(),
        );
        persisted.message_id = persisted_id;
        assert!(
            state
                .reserve_receipt_at("tenant-a/building-local", persisted)
                .await
        );
        assert_eq!(
            state
                .commit_persisted_receipts(&[persisted_id, persisted_id])
                .await,
            1
        );
        assert_eq!(
            state
                .receipt_persisted_rows("tenant-a/building-local", "edge-local", persisted_id)
                .await,
            Some(2)
        );
    }

    #[tokio::test]
    async fn scoped_receipt_waits_for_every_equipment_group() {
        let temp = tempfile::tempdir().unwrap();
        let mut state = AppState::new();
        state.ingest_receipts_path = temp.path().join("receipts.jsonl");
        let mut envelope = TelemetryEnvelope::new(
            "building-local",
            "edge-local",
            openfdd_contracts::Protocol::Bacnet,
            1,
            vec![],
        );
        envelope.points = ["equipment-a", "equipment-b"]
            .into_iter()
            .map(|equipment| openfdd_contracts::TelemetryPoint {
                id: equipment.into(),
                display_name: None,
                kind: None,
                value: serde_json::json!(1),
                unit: None,
                quality: openfdd_contracts::Quality::Good,
                tags: serde_json::json!({
                    "building_id": "building-local",
                    "equipment_id": equipment,
                    "role": "sample"
                })
                .as_object()
                .unwrap()
                .clone(),
            })
            .collect();
        let message_id = envelope.message_id;
        assert!(
            state
                .reserve_receipt_at("tenant-a/building-local", envelope)
                .await
        );
        let first = PersistedMessageGroup {
            message_id,
            edge_id: "edge-local".into(),
            building_id: "building-local".into(),
            equipment_id: "equipment-a".into(),
            rows: 1,
        };
        assert_eq!(
            state
                .commit_persisted_receipts_for(
                    "tenant-a/building-local",
                    "edge-local",
                    std::slice::from_ref(&first)
                )
                .await,
            0
        );
        assert_eq!(
            state
                .receipt_status("tenant-a/building-local", "edge-local", message_id)
                .await,
            Some(IngestReceiptStatus::Pending)
        );
        let second = PersistedMessageGroup {
            equipment_id: "equipment-b".into(),
            ..first
        };
        assert_eq!(
            state
                .commit_persisted_receipts_for(
                    "tenant-a/building-local",
                    "edge-local",
                    std::slice::from_ref(&second)
                )
                .await,
            1
        );
        assert_eq!(
            state
                .receipt_persisted_rows("tenant-a/building-local", "edge-local", message_id)
                .await,
            Some(2)
        );
    }
}
