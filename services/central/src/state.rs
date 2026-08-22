//! Shared central runtime state.

use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};
use openfdd_mqtt::AsyncClient;
use serde::Serialize;
use uuid::Uuid;

use crate::auth::AuthConfig;

const MQTT_MONITOR_CAPACITY: usize = 100;
const MQTT_PREVIEW_BYTES: usize = 4096;

#[derive(Debug, Default)]
pub struct EdgeShadow {
    pub last_status: Option<serde_json::Value>,
    pub last_telemetry: Option<TelemetryEnvelope>,
    /// protocol slug → last metadata payload
    pub last_metadata: HashMap<String, serde_json::Value>,
    /// protocol slug → last discovery payload
    pub last_discovery: HashMap<String, serde_json::Value>,
    pub sequences: HashMap<String, u64>,
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
    pub mqtt_publisher: Mutex<Option<AsyncClient>>,
    mqtt_monitor: Mutex<MqttMonitorState>,
    /// Login failures keyed by ip+username (generic throttle; no secrets).
    pub login_failures: Mutex<HashMap<String, (u32, std::time::Instant)>>,
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
            mqtt_publisher: Mutex::new(None),
            mqtt_monitor: Mutex::new(MqttMonitorState::default()),
            login_failures: Mutex::new(HashMap::new()),
        }
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
        let (payload_encoding, payload_preview) = match serde_json::from_slice::<serde_json::Value>(
            preview_bytes,
        ) {
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
