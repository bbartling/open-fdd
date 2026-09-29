//! Shared central runtime state.

use std::collections::{HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};
use openfdd_mqtt::AsyncClient;
use serde::Deserialize;
use serde::Serialize;
use tokio::sync::Mutex as AsyncMutex;
use uuid::Uuid;

use crate::auth::AuthConfig;
use crate::live_historian::{LiveHistorian, LiveHistorianIngest};
use crate::tenant_budget::TenantBudgetTracker;

const MQTT_MONITOR_CAPACITY: usize = 100;
const MQTT_PREVIEW_BYTES: usize = 4096;
const LOCAL_RECEIPTS_FILE: &str = "state/local-fieldbus-receipts.json";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum IngestReceiptStatus {
    Pending,
    Committed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngestReceipt {
    pub edge_id: String,
    pub message_id: Uuid,
    pub status: IngestReceiptStatus,
    #[serde(default = "default_receipt_observed_at")]
    pub observed_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
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
    pub live_historian: AsyncMutex<Option<LiveHistorian>>,
    /// Durable pending/committed receipt ledger for replay-safe local ingest.
    pub ingest_receipts: AsyncMutex<HashMap<(String, Uuid), IngestReceipt>>,
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
            live_historian: AsyncMutex::new(None),
            ingest_receipts: AsyncMutex::new(load_receipts()),
            ingest_receipts_path: receipts_path(),
        }
    }

    pub async fn reserve_receipt_at(
        &self,
        edge_id: &str,
        message_id: Uuid,
        observed_at: DateTime<Utc>,
    ) -> bool {
        let key = (edge_id.to_string(), message_id);
        let mut receipts = self.ingest_receipts.lock().await;
        if receipts.contains_key(&key) {
            return false;
        }
        receipts.insert(
            key,
            IngestReceipt {
                edge_id: edge_id.to_string(),
                message_id,
                status: IngestReceiptStatus::Pending,
                observed_at,
                updated_at: Utc::now(),
            },
        );
        if persist_receipts(&self.ingest_receipts_path, &receipts).await {
            true
        } else {
            receipts.remove(&(edge_id.to_string(), message_id));
            false
        }
    }

    pub async fn release_receipt(&self, edge_id: &str, message_id: Uuid) {
        let mut receipts = self.ingest_receipts.lock().await;
        receipts.remove(&(edge_id.to_string(), message_id));
        persist_receipts(&self.ingest_receipts_path, &receipts).await;
    }

    pub async fn commit_persisted_receipts(&self, watermark: Option<DateTime<Utc>>) {
        let Some(watermark) = watermark else { return };
        let mut receipts = self.ingest_receipts.lock().await;
        let before = receipts.clone();
        let now = Utc::now();
        for receipt in receipts.values_mut() {
            if receipt.status == IngestReceiptStatus::Pending && receipt.observed_at <= watermark {
                receipt.status = IngestReceiptStatus::Committed;
                receipt.updated_at = now;
            }
        }
        if !persist_receipts(&self.ingest_receipts_path, &receipts).await {
            *receipts = before;
        }
    }

    pub async fn ingest_live(
        &self,
        env: &TelemetryEnvelope,
    ) -> anyhow::Result<LiveHistorianIngest> {
        let mut historian = self.live_historian.lock().await;
        if historian.is_none() {
            *historian = Some(LiveHistorian::from_env_scoped()?);
        }
        historian
            .as_mut()
            .expect("live historian initialized")
            .ingest_envelope(env)
            .map_err(Into::into)
    }

    pub async fn flush_live(&self, graceful: bool) -> anyhow::Result<LiveHistorianIngest> {
        let (report, watermark) = {
            let mut historian = self.live_historian.lock().await;
            let Some(historian) = historian.as_mut() else {
                return Ok(LiveHistorianIngest::default());
            };
            let report = if graceful {
                historian.shutdown_flush()?
            } else {
                historian.flush_due()?
            };
            (report, historian.latest_persisted_timestamp_utc())
        };
        self.commit_persisted_receipts(watermark).await;
        Ok(report)
    }

    pub async fn receipt_status(
        &self,
        edge_id: &str,
        message_id: Uuid,
    ) -> Option<IngestReceiptStatus> {
        self.ingest_receipts
            .lock()
            .await
            .get(&(edge_id.to_string(), message_id))
            .map(|receipt| receipt.status)
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

fn load_receipts() -> HashMap<(String, Uuid), IngestReceipt> {
    load_receipts_at(&receipts_path())
}

fn load_receipts_at(path: &std::path::Path) -> HashMap<(String, Uuid), IngestReceipt> {
    let Ok(bytes) = std::fs::read(path) else {
        return HashMap::new();
    };
    serde_json::from_slice::<Vec<IngestReceipt>>(&bytes)
        .unwrap_or_default()
        .into_iter()
        .map(|receipt| ((receipt.edge_id.clone(), receipt.message_id), receipt))
        .collect()
}

async fn persist_receipts(
    path: &std::path::Path,
    receipts: &HashMap<(String, Uuid), IngestReceipt>,
) -> bool {
    let Some(parent) = path.parent() else {
        return false;
    };
    if tokio::fs::create_dir_all(parent).await.is_err() {
        return false;
    }
    let values: Vec<_> = receipts.values().cloned().collect();
    let Ok(bytes) = serde_json::to_vec_pretty(&values) else {
        return false;
    };
    let temp = path.with_extension("json.tmp");
    tokio::fs::write(&temp, bytes).await.is_ok() && tokio::fs::rename(temp, path).await.is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn receipt_reservation_is_single_writer_and_restart_safe() {
        let temp = tempfile::tempdir().unwrap();
        let mut state = AppState::new();
        state.ingest_receipts_path = temp.path().join("receipts.json");
        let message_id = Uuid::new_v4();
        let results = futures_util::future::join_all(
            (0..16).map(|_| state.reserve_receipt_at("edge-local", message_id, Utc::now())),
        )
        .await;
        assert_eq!(results.into_iter().filter(|accepted| *accepted).count(), 1);

        state.commit_persisted_receipts(Some(Utc::now())).await;
        let bytes = tokio::fs::read(&state.ingest_receipts_path).await.unwrap();
        let receipts: Vec<IngestReceipt> = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(receipts[0].status, IngestReceiptStatus::Committed);
        let restarted = load_receipts_at(&state.ingest_receipts_path);
        assert_eq!(
            restarted
                .get(&("edge-local".to_string(), message_id))
                .map(|receipt| receipt.status),
            Some(IngestReceiptStatus::Committed)
        );

        // A response lost after commit is a duplicate on restart, while an
        // initial write failure can be released and retried with the same ID.
        assert!(
            !state
                .reserve_receipt_at("edge-local", message_id, Utc::now())
                .await
        );
        let failed_id = Uuid::new_v4();
        let mut failed_state = AppState::new();
        failed_state.ingest_receipts_path = temp.path().to_path_buf();
        assert!(
            !failed_state
                .reserve_receipt_at("edge-local", failed_id, Utc::now())
                .await
        );
        assert!(failed_state
            .receipt_status("edge-local", failed_id)
            .await
            .is_none());
        assert!(
            state
                .reserve_receipt_at("edge-local", failed_id, Utc::now())
                .await
        );
        state.release_receipt("edge-local", failed_id).await;
        assert!(
            state
                .reserve_receipt_at("edge-local", failed_id, Utc::now())
                .await
        );
    }
}
