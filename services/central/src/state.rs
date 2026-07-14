//! Shared central runtime state.

use std::collections::HashMap;
use std::sync::Mutex;

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use openfdd_contracts::{CommandAck, CommandEnvelope, TelemetryEnvelope};
use openfdd_mqtt::AsyncClient;
use uuid::Uuid;

use crate::auth::AuthConfig;

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
        }
    }

    pub fn set_mqtt_publisher(&self, client: AsyncClient) {
        *self.mqtt_publisher.lock().unwrap() = Some(client);
    }
}
