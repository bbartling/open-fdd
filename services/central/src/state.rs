//! Shared central runtime state.

use std::collections::{BTreeSet, HashMap, VecDeque};
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};
use openfdd_mqtt::AsyncClient;
use serde::Deserialize;
use serde::Serialize;
use tokio::sync::Mutex as AsyncMutex;
use tracing::warn;
use uuid::Uuid;

use crate::auth::AuthConfig;
use crate::capabilities::CapabilitiesAggregator;
use crate::live_historian::{LiveHistorianIngest, LiveWriter, PersistedMessageGroup};
use crate::tenant_budget::TenantBudgetTracker;

const MQTT_MONITOR_CAPACITY: usize = 100;
const MQTT_PREVIEW_BYTES: usize = 4096;
const LOCAL_RECEIPTS_FILE: &str = "state/local-fieldbus-receipts.jsonl";
const RECEIPT_CAPACITY: usize = 50_000;
const PENDING_RECEIPT_CAPACITY: usize = 10_000;
/// Compaction folds the append log. It does not expire committed tombstones:
/// a replay of a committed message id must stay a duplicate for the life of
/// the bounded ledger. Pending envelopes are never reduced to tombstones.
const RECEIPT_COMPACTION_BYTES: u64 = 8 * 1024 * 1024;

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
            let scalar =
                point.value.is_number() || point.value.is_boolean() || point.value.is_string();
            let quality_ok = matches!(
                point.quality,
                openfdd_contracts::Quality::Good | openfdd_contracts::Quality::Uncertain
            ) || (point
                .tags
                .get("non_finite_quality")
                .and_then(|v| v.as_bool())
                == Some(true)
                && point.value.is_number());
            (scalar
                && quality_ok
                && !building.is_empty()
                && !equipment.is_empty()
                && !role.is_empty())
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
    /// Tenant from the tenant-scoped topic or trusted local ingest binding.
    /// Kept with the edge shadow so overlapping building ids cannot authorize
    /// an edge from another tenant.
    pub registered_tenant_id: Option<String>,
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

    pub fn known_tenant_id(&self) -> Option<String> {
        self.registered_tenant_id
            .clone()
            .filter(|tenant| !tenant.is_empty())
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
    /// Explicit capability probes and scoped read proxy. Health never probes.
    pub capabilities: std::sync::Arc<CapabilitiesAggregator>,
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
    /// Last receipt-backed, persisted row observed by this process. This is
    /// the only signal used for durable delivery capability; accepts alone do
    /// not establish persistence.
    pub last_durable_at: Mutex<Option<DateTime<Utc>>>,
    pub mqtt_publisher: Mutex<Option<AsyncClient>>,
    mqtt_monitor: Mutex<MqttMonitorState>,
    /// Login failures keyed by ip+username (generic throttle; no secrets).
    pub login_failures: Mutex<HashMap<String, (u32, std::time::Instant)>>,
    /// Wave L L5 — per-tenant sliding-window budgets (noop when disabled).
    pub tenant_budgets: TenantBudgetTracker,
    /// One canonical writer shared by MQTT and local HTTP delivery.
    /// Parquet publication runs on this writer's dedicated blocking thread.
    pub live_writer: LiveWriter,
    /// Durable pending/committed receipt ledger for replay-safe local ingest.
    pub ingest_receipts: AsyncMutex<HashMap<(String, String, Uuid), IngestReceipt>>,
    pub ingest_receipts_path: PathBuf,
    recovery_started: AtomicBool,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            auth: AuthConfig::load(),
            capabilities: CapabilitiesAggregator::from_env(),
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
            last_durable_at: Mutex::new(None),
            mqtt_publisher: Mutex::new(None),
            mqtt_monitor: Mutex::new(MqttMonitorState::default()),
            login_failures: Mutex::new(HashMap::new()),
            tenant_budgets: TenantBudgetTracker::new(),
            live_writer: LiveWriter::start(),
            ingest_receipts: AsyncMutex::new(load_receipts()),
            ingest_receipts_path: receipts_path(),
            recovery_started: AtomicBool::new(false),
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

    /// Recover durable pending envelopes once after process start. Normal
    /// duplicate requests only query the receipt; this path owns the sole
    /// replay attempt after a crash.
    pub async fn recover_pending_receipts_once(&self) {
        if self.recovery_started.swap(true, Ordering::AcqRel) {
            return;
        }
        let pending: Vec<_> = self
            .ingest_receipts
            .lock()
            .await
            .values()
            .filter(|receipt| receipt.status == IngestReceiptStatus::Pending)
            .map(|receipt| (receipt.scope.clone(), receipt.envelope.clone()))
            .collect();
        for (scope, envelope) in pending {
            if self.ingest_live(&scope, &envelope).await.is_ok() {
                let _ = self.flush_live(false).await;
            }
        }
    }

    pub async fn release_receipt(&self, scope: &str, edge_id: &str, message_id: Uuid) -> bool {
        let mut receipts = self.ingest_receipts.lock().await;
        let key = (scope.to_string(), edge_id.to_string(), message_id);
        if !receipts.contains_key(&key) {
            return true;
        }
        // The delete tombstone must hit disk before the in-memory entry is
        // forgotten. A failed append leaves the pending receipt in place so
        // restart replay cannot lose it and a later retry cannot double-insert
        // around a missing tombstone.
        if !append_receipt_event(&self.ingest_receipts_path, scope, edge_id, message_id, None).await
        {
            return false;
        }
        receipts.remove(&key);
        maybe_compact_receipt_journal(&self.ingest_receipts_path, &receipts).await;
        true
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
            let durable = persisted_rows.is_some_and(|rows| rows > 0);
            drop(receipts);
            if durable {
                self.note_durable_ingest();
            }
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
            }
            updated.updated_at = Utc::now();
            let became_committed = updated.status == IngestReceiptStatus::Committed;
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
                if became_committed {
                    committed += 1;
                }
                let durable = became_committed && group.rows > 0;
                drop(receipts);
                if durable {
                    self.note_durable_ingest();
                }
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
        let report = self.live_writer.ingest(scope, env).await?;
        self.commit_published_groups(&report.persisted_message_groups)
            .await;
        Ok(report)
    }

    pub async fn flush_live(&self, graceful: bool) -> anyhow::Result<LiveHistorianIngest> {
        let report = self.live_writer.flush(graceful).await?;
        self.commit_published_groups(&report.persisted_message_groups)
            .await;
        Ok(report)
    }

    /// Publish the scope's buffered rows and commit those receipts. Local HTTP
    /// uses this so the response is not a 202 while the row waits for the
    /// shared micro-batch threshold.
    pub async fn publish_pending(&self, scope: &str) -> anyhow::Result<LiveHistorianIngest> {
        let report = self.live_writer.publish_pending(scope).await?;
        self.commit_published_groups(&report.persisted_message_groups)
            .await;
        Ok(report)
    }

    /// Commit each published group under the scope and edge carried on that
    /// group. A row-threshold flush can include an earlier edge's batch; using
    /// the triggering request's edge would leave that receipt pending after
    /// its rows were already published.
    async fn commit_published_groups(&self, groups: &[PersistedMessageGroup]) -> usize {
        let mut committed = 0;
        for group in groups {
            committed += self
                .commit_persisted_receipts_for(
                    &group.scope,
                    &group.edge_id,
                    std::slice::from_ref(group),
                )
                .await;
        }
        committed
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

    pub fn note_durable_ingest(&self) {
        *self.last_durable_at.lock().unwrap() = Some(Utc::now());
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

/// Rewrite the receipt journal from the live map once it grows beyond a fixed
/// bound. Pending receipts keep their envelopes for crash replay. Committed
/// receipts become tombstones (identity, status, and row counts, without point
/// payloads). Released ids are already absent from the map and stay absent.
/// A failed snapshot leaves the previous journal in place.
async fn maybe_compact_receipt_journal(
    path: &std::path::Path,
    receipts: &HashMap<(String, String, Uuid), IngestReceipt>,
) {
    maybe_compact_receipt_journal_at(path, receipts, RECEIPT_COMPACTION_BYTES).await;
}

async fn maybe_compact_receipt_journal_at(
    path: &std::path::Path,
    receipts: &HashMap<(String, String, Uuid), IngestReceipt>,
    min_bytes: u64,
) {
    let oversized = tokio::fs::metadata(path)
        .await
        .map(|metadata| metadata.len() >= min_bytes)
        .unwrap_or(false);
    if !oversized {
        return;
    }
    let entries = snapshot_entries(receipts);
    if entries.len() != receipts.len() {
        warn!("receipt journal compaction refused because the snapshot dropped a live receipt");
        return;
    }
    let path = path.to_path_buf();
    let compacted =
        tokio::task::spawn_blocking(move || compact_receipt_snapshot(&path, &entries)).await;
    match compacted {
        Ok(Ok(())) => {}
        Ok(Err(error)) => {
            warn!(%error, "receipt journal compaction failed; previous journal retained");
        }
        Err(error) => {
            warn!(%error, "receipt journal compaction task failed; previous journal retained");
        }
    }
}

fn snapshot_entries(
    receipts: &HashMap<(String, String, Uuid), IngestReceipt>,
) -> Vec<ReceiptJournalEntry> {
    let mut entries: Vec<ReceiptJournalEntry> = receipts
        .values()
        .map(|receipt| ReceiptJournalEntry {
            scope: receipt.scope.clone(),
            edge_id: receipt.edge_id.clone(),
            message_id: receipt.message_id,
            receipt: Some(compacted_receipt(receipt)),
        })
        .collect();
    entries.sort_by(|left, right| {
        (&left.scope, &left.edge_id, left.message_id).cmp(&(
            &right.scope,
            &right.edge_id,
            right.message_id,
        ))
    });
    entries
}

fn compacted_receipt(receipt: &IngestReceipt) -> IngestReceipt {
    let mut tombstone = receipt.clone();
    if tombstone.status == IngestReceiptStatus::Committed {
        tombstone.envelope.points.clear();
    }
    tombstone
}

fn compact_receipt_snapshot(
    path: &std::path::Path,
    entries: &[ReceiptJournalEntry],
) -> std::io::Result<()> {
    let temp = path.with_extension("jsonl.compact.tmp");
    let write_snapshot = (|| -> std::io::Result<()> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&temp)?;
        for entry in entries {
            let mut line = serde_json::to_vec(entry)
                .map_err(|error| std::io::Error::new(std::io::ErrorKind::InvalidData, error))?;
            line.push(b'\n');
            file.write_all(&line)?;
        }
        file.sync_all()?;
        std::fs::rename(&temp, path)?;
        if let Some(parent) = path.parent() {
            std::fs::File::open(parent)?.sync_all()?;
        }
        Ok(())
    })();
    if write_snapshot.is_err() {
        let _ = std::fs::remove_file(&temp);
    }
    write_snapshot
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
            scope: "tenant-a/building-local".into(),
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
        assert!(state.last_durable_at.lock().unwrap().is_none());
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
        assert!(state.last_durable_at.lock().unwrap().is_some());
    }

    fn local_envelope(edge_id: &str, equipment_id: &str) -> TelemetryEnvelope {
        TelemetryEnvelope::new(
            "building-local",
            edge_id,
            openfdd_contracts::Protocol::Bacnet,
            1,
            vec![openfdd_contracts::TelemetryPoint {
                id: format!("point-{equipment_id}"),
                display_name: None,
                kind: None,
                value: serde_json::json!(70.0),
                unit: None,
                quality: openfdd_contracts::Quality::Good,
                tags: serde_json::json!({
                    "building_id": "building-local",
                    "equipment_id": equipment_id,
                    "role": "sat"
                })
                .as_object()
                .unwrap()
                .clone(),
            }],
        )
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize process environment while the writer thread reads flush settings"
    )]
    async fn row_flush_commits_the_buffered_edge_not_only_the_triggering_edge() {
        let _env = crate::test_env_lock::lock_env();
        let temp = tempfile::tempdir().unwrap();
        std::env::set_var("OPENFDD_WORKSPACE", temp.path());
        std::env::set_var(
            "OPENFDD_STORAGE_URL",
            format!("file://{}", temp.path().join("history").display()),
        );
        std::env::set_var("OPENFDD_PARQUET_FLUSH_ROWS", "2");
        std::env::set_var("OPENFDD_PARQUET_FLUSH_SECONDS", "3600");
        std::env::set_var("OPENFDD_MULTI_TENANT", "0");
        let state = AppState::new();
        let scope = "tenant=-;building=building-local";
        let edge_a = local_envelope("edge-a", "equipment-local");
        let edge_b = local_envelope("edge-b", "equipment-local");
        let edge_a_id = edge_a.message_id;
        let edge_b_id = edge_b.message_id;
        assert!(state.reserve_receipt_at(scope, edge_a.clone()).await);
        assert!(state.reserve_receipt_at(scope, edge_b.clone()).await);
        let first = state.ingest_live(scope, &edge_a).await.unwrap();
        assert!(first.persisted_message_groups.is_empty());
        let second = state.ingest_live(scope, &edge_b).await.unwrap();
        assert_eq!(second.persisted_message_groups.len(), 2);
        assert_eq!(
            state.receipt_status(scope, "edge-a", edge_a_id).await,
            Some(IngestReceiptStatus::Committed)
        );
        assert_eq!(
            state.receipt_status(scope, "edge-b", edge_b_id).await,
            Some(IngestReceiptStatus::Committed)
        );
        assert_eq!(
            state
                .receipt_persisted_rows(scope, "edge-a", edge_a_id)
                .await,
            Some(1)
        );
        for key in [
            "OPENFDD_WORKSPACE",
            "OPENFDD_STORAGE_URL",
            "OPENFDD_PARQUET_FLUSH_ROWS",
            "OPENFDD_PARQUET_FLUSH_SECONDS",
            "OPENFDD_MULTI_TENANT",
        ] {
            std::env::remove_var(key);
        }
    }

    #[tokio::test]
    async fn compaction_keeps_pending_envelopes_and_committed_tombstones() {
        let temp = tempfile::tempdir().unwrap();
        let mut state = AppState::new();
        state.ingest_receipts_path = temp.path().join("receipts.jsonl");
        let pending = local_envelope("edge-local", "equipment-pending");
        let committed = local_envelope("edge-local", "equipment-committed");
        let released = local_envelope("edge-local", "equipment-released");
        let pending_id = pending.message_id;
        let committed_id = committed.message_id;
        let released_id = released.message_id;
        let scope = "tenant-a/building-local";
        assert!(state.reserve_receipt_at(scope, pending).await);
        assert!(state.reserve_receipt_at(scope, committed.clone()).await);
        assert!(state.reserve_receipt_at(scope, released).await);
        assert!(
            state
                .commit_receipt(scope, "edge-local", committed_id)
                .await
        );
        assert!(
            state
                .release_receipt(scope, "edge-local", released_id)
                .await
        );
        {
            let receipts = state.ingest_receipts.lock().await;
            maybe_compact_receipt_journal_at(&state.ingest_receipts_path, &receipts, 0).await;
        }
        let reloaded = load_receipts_at(&state.ingest_receipts_path).unwrap();
        let pending_key = (scope.to_string(), "edge-local".to_string(), pending_id);
        let committed_key = (scope.to_string(), "edge-local".to_string(), committed_id);
        let released_key = (scope.to_string(), "edge-local".to_string(), released_id);
        assert_eq!(
            reloaded.get(&pending_key).map(|receipt| receipt.status),
            Some(IngestReceiptStatus::Pending)
        );
        assert_eq!(
            reloaded
                .get(&pending_key)
                .map(|receipt| receipt.envelope.points.len()),
            Some(1)
        );
        let committed_receipt = reloaded.get(&committed_key).unwrap();
        assert_eq!(committed_receipt.status, IngestReceiptStatus::Committed);
        assert!(committed_receipt.envelope.points.is_empty());
        assert!(!reloaded.contains_key(&released_key));
        assert!(
            !state
                .reserve_receipt_at(scope, {
                    let mut copy = committed;
                    copy.message_id = committed_id;
                    copy
                })
                .await
        );
    }

    #[tokio::test]
    async fn failed_release_keeps_the_pending_receipt() {
        let temp = tempfile::tempdir().unwrap();
        let mut state = AppState::new();
        state.ingest_receipts_path = temp.path().join("receipts.jsonl");
        let envelope = local_envelope("edge-local", "equipment-local");
        let message_id = envelope.message_id;
        assert!(
            state
                .reserve_receipt_at("tenant-a/building-local", envelope)
                .await
        );
        state.ingest_receipts_path = PathBuf::from("/proc/openfdd-receipt-test/receipts.jsonl");
        assert!(
            !state
                .release_receipt("tenant-a/building-local", "edge-local", message_id)
                .await
        );
        assert_eq!(
            state
                .receipt_status("tenant-a/building-local", "edge-local", message_id)
                .await,
            Some(IngestReceiptStatus::Pending)
        );
    }

    #[test]
    fn failed_compaction_keeps_the_previous_journal() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("receipts.jsonl");
        let original = b"{\"scope\":\"s\",\"edge_id\":\"e\",\"message_id\":\"00000000-0000-0000-0000-000000000001\",\"receipt\":null}\n";
        std::fs::write(&path, original).unwrap();
        let blocking_temp = path.with_extension("jsonl.compact.tmp");
        std::fs::create_dir(&blocking_temp).unwrap();
        let error = compact_receipt_snapshot(&path, &[]).unwrap_err();
        assert!(
            error.kind() == std::io::ErrorKind::AlreadyExists || error.raw_os_error().is_some()
        );
        assert_eq!(std::fs::read(&path).unwrap(), original);
    }
}
