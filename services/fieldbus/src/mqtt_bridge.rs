//! Optional MQTTS bridge: spool poll snapshots, publish telemetry, and safely execute commands.

use std::collections::{HashMap, HashSet, VecDeque};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use fdd_core::columns::haystack_point_to_role;
use openfdd_contracts::{
    CommandAck, CommandEnvelope, CommandStatus, Protocol, Quality, TelemetryEnvelope,
    TelemetryPoint, TopicBuilder, TopicKind, ValueKind,
};
use openfdd_mqtt::{
    publish_json, AsyncClient, Incoming, MqttConfig, MqttHandle, Publish, SpoolConfig, SpoolRecord,
    TelemetrySpool,
};
use tokio::sync::{mpsc, Mutex};
use tokio::task::JoinHandle;
use tracing::{info, warn};

use crate::config::{IngestMode, Settings};
use crate::services::bacnet_client::BacnetClientService;
use crate::services::mqtt_publish_ledger::MqttPublishLedger;
use crate::services::poll::PollEngine;
use crate::services::rest::RestClientService;
use crate::services::telemetry_control::{parse_telemetry_command, TelemetryControl};

const MAX_SEEN_COMMANDS: usize = 10_000;
const SINK_DRAIN_BATCH: usize = 32;
const SINK_IDLE_WAIT: Duration = Duration::from_millis(200);

#[derive(Debug)]
struct QueuedDelivery {
    topic: String,
    envelope: TelemetryEnvelope,
}

fn mqtt_publish_interval_secs(settings: &Settings) -> f64 {
    // Wave N: publish cadence matches fixed 300s poll (ignore env overrides).
    let _ = settings;
    crate::config::FIXED_POLL_INTERVAL_SECS
}

/// Site-wide and per-equipment `equipType` stamps for canonical historian typing.
#[derive(Debug, Clone, Default)]
struct EquipmentTypeStamps {
    default_type: Option<String>,
    by_equipment: HashMap<String, String>,
}

fn load_equipment_type_stamps() -> EquipmentTypeStamps {
    let default_type = std::env::var("OPENFDD_EQUIPMENT_TYPE")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    let by_equipment = std::env::var("OPENFDD_EQUIPMENT_TYPE_MAP")
        .ok()
        .and_then(|raw| serde_json::from_str::<HashMap<String, String>>(&raw).ok())
        .unwrap_or_default();
    EquipmentTypeStamps {
        default_type,
        by_equipment,
    }
}

fn row_equipment_type_stamp(row: &serde_json::Value) -> Option<String> {
    for key in ["equipment_type", "equipType"] {
        if let Some(stamp) = row.get(key).and_then(|v| v.as_str()).map(str::trim) {
            if !stamp.is_empty() {
                return Some(stamp.to_string());
            }
        }
    }
    None
}

fn equipment_type_for(
    stamps: &EquipmentTypeStamps,
    equipment_id: &str,
    row_stamp: Option<&str>,
) -> Option<String> {
    row_stamp
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .or_else(|| stamps.by_equipment.get(equipment_id).cloned())
        .or_else(|| stamps.default_type.clone())
}

fn insert_equipment_type_tag(
    tags: &mut serde_json::Map<String, serde_json::Value>,
    stamp: Option<String>,
) {
    if let Some(stamp) = stamp.filter(|value| !value.is_empty()) {
        tags.insert("equipment_type".into(), serde_json::Value::String(stamp));
    }
}

/// Split a publish batch so each MQTT envelope stays within a single equipment
/// (and thus well under typical MQTT packet caps on full-site HVAC polls).
fn chunk_points_by_equipment(points: Vec<TelemetryPoint>) -> Vec<Vec<TelemetryPoint>> {
    let mut by_equip: HashMap<String, Vec<TelemetryPoint>> = HashMap::new();
    let mut order: Vec<String> = Vec::new();
    for p in points {
        let key = p
            .tags
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if !by_equip.contains_key(&key) {
            order.push(key.clone());
        }
        by_equip.entry(key).or_default().push(p);
    }
    order
        .into_iter()
        .filter_map(|k| by_equip.remove(&k))
        .filter(|chunk| !chunk.is_empty())
        .collect()
}

pub fn mqtt_enabled() -> bool {
    matches!(
        std::env::var("OPENFDD_MQTT_ENABLED")
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "1" | "true" | "yes" | "on"
    )
}

fn mqtt_delivery_enabled(mode: IngestMode) -> bool {
    mqtt_delivery_enabled_with(mode, mqtt_enabled())
}

fn mqtt_delivery_enabled_with(mode: IngestMode, broker_enabled: bool) -> bool {
    mode.uses_mqtt() && broker_enabled
}

fn ingest_mode() -> Result<IngestMode, String> {
    IngestMode::from_env()
}

#[derive(Clone)]
struct LocalIngestClient {
    client: reqwest::Client,
    endpoint: String,
    token: Option<String>,
    tenant_id: Option<String>,
    building_id: Option<String>,
}

impl LocalIngestClient {
    fn from_env(site_id: &str) -> Result<Self, String> {
        let base = std::env::var("OPENFDD_LOCAL_CENTRAL_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8080".into());
        let endpoint = format!("{}/api/ingest/local", base.trim_end_matches('/'));
        let timeout_secs = std::env::var("OPENFDD_LOCAL_INGEST_TIMEOUT_SECS")
            .ok()
            .and_then(|raw| raw.parse::<u64>().ok())
            .unwrap_or(10)
            .clamp(1, 60);
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(timeout_secs))
            .build()
            .map_err(|error| format!("local ingest HTTP client: {error}"))?;
        Ok(Self {
            client,
            endpoint,
            token: std::env::var("OPENFDD_LOCAL_INGEST_TOKEN")
                .ok()
                .filter(|value| !value.trim().is_empty()),
            tenant_id: std::env::var("OPENFDD_TENANT_ID")
                .ok()
                .filter(|value| !value.trim().is_empty()),
            building_id: std::env::var("OPENFDD_BUILDING_ID")
                .ok()
                .filter(|value| !value.trim().is_empty())
                .or_else(|| Some(site_id.to_string())),
        })
    }

    async fn send(&self, envelope: &TelemetryEnvelope) -> Result<(), String> {
        let mut request = self
            .client
            .post(&self.endpoint)
            .header("content-type", "application/json")
            .header("x-openfdd-message-id", envelope.message_id.to_string())
            .header("x-openfdd-sequence", envelope.sequence.to_string())
            .json(envelope);
        if let Some(token) = &self.token {
            request = request.bearer_auth(token);
        }
        if let Some(tenant_id) = &self.tenant_id {
            request = request.header("x-openfdd-tenant-id", tenant_id);
        }
        if let Some(building_id) = &self.building_id {
            request = request.header("x-openfdd-building-id", building_id);
        }
        let response = request
            .send()
            .await
            .map_err(|error| format!("local ingest request: {error}"))?;
        let status = response.status();
        let body: serde_json::Value = response
            .json()
            .await
            .map_err(|error| format!("local ingest response: {error}"))?;
        if !durable_local_ack(status, &body) {
            let pending = body
                .get("pending")
                .cloned()
                .unwrap_or(serde_json::Value::Null);
            let rows = body
                .get("persisted_rows")
                .cloned()
                .unwrap_or(serde_json::Value::Null);
            return Err(format!(
                "local ingest not durable: HTTP {status} pending={pending} persisted_rows={rows}"
            ));
        }
        Ok(())
    }
}

/// 200 is success only when this message's rows are already committed.
/// 202 means the sample is still pending, so the spool must keep it.
fn durable_local_ack(status: reqwest::StatusCode, body: &serde_json::Value) -> bool {
    status == reqwest::StatusCode::OK
        && body.get("ok").and_then(|value| value.as_bool()) == Some(true)
        && body.get("pending").and_then(|value| value.as_bool()) == Some(false)
        && body
            .get("persisted_rows")
            .and_then(|value| value.as_u64())
            .unwrap_or(0)
            > 0
}

fn local_spool_dir(edge_id: &str) -> PathBuf {
    PathBuf::from(
        std::env::var("OPENFDD_LOCAL_SPOOL_DIR")
            .unwrap_or_else(|_| format!("/tmp/openfdd-local-spool-{edge_id}")),
    )
}

fn local_spool_max_records() -> usize {
    std::env::var("OPENFDD_LOCAL_SPOOL_MAX_RECORDS")
        .ok()
        .and_then(|raw| raw.parse::<usize>().ok())
        .unwrap_or(50_000)
        .clamp(1, 50_000)
}

fn mqtt_config(site_id: &str, edge_id: &str, port: u16) -> MqttConfig {
    MqttConfig {
        host: std::env::var("OPENFDD_MQTT_HOST").unwrap_or_else(|_| "127.0.0.1".into()),
        port,
        client_id: format!("edge:{site_id}:{edge_id}"),
        ca_pem: PathBuf::from(
            std::env::var("OPENFDD_MQTT_CA_PEM").unwrap_or_else(|_| "/mqtt/ca.pem".into()),
        ),
        cert_pem: PathBuf::from(
            std::env::var("OPENFDD_MQTT_CERT_PEM").unwrap_or_else(|_| "/mqtt/edge.cert.pem".into()),
        ),
        key_pem: PathBuf::from(
            std::env::var("OPENFDD_MQTT_KEY_PEM").unwrap_or_else(|_| "/mqtt/edge.key.pem".into()),
        ),
        keep_alive_secs: 30,
    }
}

struct CommandDeduper {
    order: VecDeque<uuid::Uuid>,
    seen: HashSet<uuid::Uuid>,
}

impl CommandDeduper {
    fn new() -> Self {
        Self {
            order: VecDeque::new(),
            seen: HashSet::new(),
        }
    }

    /// Returns true when the command id is new (not a duplicate).
    fn record(&mut self, id: uuid::Uuid) -> bool {
        if self.seen.contains(&id) {
            return false;
        }
        self.seen.insert(id);
        self.order.push_back(id);
        while self.order.len() > MAX_SEEN_COMMANDS {
            if let Some(old) = self.order.pop_front() {
                self.seen.remove(&old);
            }
        }
        true
    }
}

struct CommandContext {
    site_id: String,
    edge_id: String,
    bacnet_client: Arc<BacnetClientService>,
    telemetry: Arc<TelemetryControl>,
    deduper: Mutex<CommandDeduper>,
}

async fn subscribe_commands(mqtt: &MqttHandle, topics: &TopicBuilder) -> Result<(), String> {
    let bacnet = topics.topic(TopicKind::Commands, Some(Protocol::Bacnet));
    mqtt.subscribe(&bacnet).await.map_err(|e| e.to_string())?;
    let wildcard = format!("{}/commands/#", topics.base());
    mqtt.subscribe(&wildcard).await.map_err(|e| e.to_string())?;
    info!(%bacnet, %wildcard, "subscribed to command topics");
    Ok(())
}

async fn publish_ack(client: &AsyncClient, cmd: &CommandEnvelope, ack: CommandAck) {
    if let Err(err) = publish_json(client, &cmd.response_topic, &ack, false).await {
        warn!(
            command_id = %cmd.command_id,
            %err,
            "command ack publish failed"
        );
    }
}

async fn handle_command_publish(client: &AsyncClient, ctx: &CommandContext, publish: Publish) {
    if publish.retain {
        warn!(topic = %publish.topic, "ignoring retained command");
        if let Ok(cmd) = serde_json::from_slice::<CommandEnvelope>(&publish.payload) {
            let ack = CommandAck::new(
                &cmd,
                CommandStatus::Rejected,
                Some("retained command ignored".into()),
            );
            publish_ack(client, &cmd, ack).await;
        }
        return;
    }

    let cmd: CommandEnvelope = match serde_json::from_slice(&publish.payload) {
        Ok(c) => c,
        Err(err) => {
            warn!(%err, topic = %publish.topic, "invalid command payload");
            return;
        }
    };

    if let Err(err) = cmd.validate() {
        warn!(%err, command_id = %cmd.command_id, "command validation failed");
        let ack = CommandAck::new(&cmd, CommandStatus::Rejected, Some(err));
        publish_ack(client, &cmd, ack).await;
        return;
    }

    if cmd.site_id != ctx.site_id || cmd.edge_id != ctx.edge_id {
        warn!(
            command_id = %cmd.command_id,
            expected_site = %ctx.site_id,
            expected_edge = %ctx.edge_id,
            "command site/edge mismatch"
        );
        let ack = CommandAck::new(
            &cmd,
            CommandStatus::Rejected,
            Some("site_id or edge_id mismatch".into()),
        );
        publish_ack(client, &cmd, ack).await;
        return;
    }

    let now = Utc::now();
    if cmd.is_expired(now) {
        warn!(command_id = %cmd.command_id, "expired command rejected");
        let ack = CommandAck::new(&cmd, CommandStatus::Expired, None);
        publish_ack(client, &cmd, ack).await;
        return;
    }

    {
        let mut deduper = ctx.deduper.lock().await;
        if !deduper.record(cmd.command_id) {
            warn!(command_id = %cmd.command_id, "duplicate command rejected");
            let ack = CommandAck::new(
                &cmd,
                CommandStatus::Rejected,
                Some("duplicate command_id".into()),
            );
            publish_ack(client, &cmd, ack).await;
            return;
        }
    }

    publish_ack(
        client,
        &cmd,
        CommandAck::new(&cmd, CommandStatus::Accepted, None),
    )
    .await;

    let result = if cmd.target_id.starts_with("edge:telemetry") {
        execute_telemetry_command(&ctx.telemetry, &cmd).await
    } else {
        execute_bacnet_command(&ctx.bacnet_client, &cmd).await
    };

    match result {
        Ok(detail) => {
            publish_ack(
                client,
                &cmd,
                CommandAck::new(&cmd, CommandStatus::Executed, Some(detail)),
            )
            .await;
        }
        Err(err) => {
            warn!(command_id = %cmd.command_id, %err, "command execution failed");
            publish_ack(
                client,
                &cmd,
                CommandAck::new(&cmd, CommandStatus::Failed, Some(err)),
            )
            .await;
        }
    }
}

fn parse_bacnet_target(target_id: &str) -> Result<(u32, String, u32), String> {
    let parts: Vec<&str> = target_id.split(':').collect();
    if parts.len() != 4 || parts[0] != "bacnet" {
        return Err(format!(
            "target_id must be bacnet:device:object_type:instance, got {target_id}"
        ));
    }
    let device = parts[1]
        .parse::<u32>()
        .map_err(|_| format!("invalid device_instance in {target_id}"))?;
    let object_type = parts[2].replace('_', "-");
    let instance = parts[3]
        .parse::<u32>()
        .map_err(|_| format!("invalid object_instance in {target_id}"))?;
    Ok((device, object_type, instance))
}

/// Bad quality is any non-null poll error. Only a non-finite BACnet real or
/// double is the SV-RANGE marker (`non_finite_quality`).
fn poll_error_quality(error: Option<&serde_json::Value>) -> (Quality, bool) {
    let Some(error) = error else {
        return (Quality::Good, false);
    };
    if error.is_null() {
        return (Quality::Good, false);
    }
    let non_finite = error
        .as_str()
        .is_some_and(|text| text.starts_with("bad-quality: non-finite"));
    (Quality::Bad, non_finite)
}

fn stamp_non_finite_quality(
    tags: &mut serde_json::Map<String, serde_json::Value>,
    non_finite: bool,
) {
    if non_finite {
        tags.insert("non_finite_quality".into(), serde_json::Value::Bool(true));
    }
}

/// Map a poll `last_values` row into a telemetry JSON value.
fn telemetry_point_value(row: &serde_json::Value) -> serde_json::Value {
    row.get("value")
        .or_else(|| row.get("present_value"))
        .cloned()
        .unwrap_or(serde_json::Value::Null)
}

fn historian_tags(
    mut tags: serde_json::Map<String, serde_json::Value>,
    building_id: Option<&str>,
    equipment_id: &str,
    point_name: &str,
    equipment_type: Option<String>,
) -> serde_json::Map<String, serde_json::Value> {
    tags.insert(
        "equipment_id".into(),
        serde_json::Value::String(equipment_id.to_string()),
    );
    tags.insert(
        "role".into(),
        serde_json::Value::String(haystack_point_to_role(point_name)),
    );
    if let Some(building_id) = building_id {
        tags.insert(
            "building_id".into(),
            serde_json::Value::String(building_id.to_string()),
        );
    }
    insert_equipment_type_tag(&mut tags, equipment_type);
    tags
}

async fn execute_telemetry_command(
    telemetry: &TelemetryControl,
    cmd: &CommandEnvelope,
) -> Result<String, String> {
    let action = parse_telemetry_command(&cmd.target_id, &cmd.value)?;
    let label = match action {
        crate::services::telemetry_control::TelemetryAction::Suspend => "suspend",
        crate::services::telemetry_control::TelemetryAction::Resume => "resume",
    };
    let status = telemetry.apply_action(action, &cmd.approved_by).await?;
    Ok(format!(
        "telemetry {label} applied (approved by {}); status={status}",
        cmd.approved_by
    ))
}

async fn execute_bacnet_command(
    bacnet: &BacnetClientService,
    cmd: &CommandEnvelope,
) -> Result<String, String> {
    if cmd.target_id.starts_with("edge:") {
        return Err(format!(
            "unsupported edge command target_id {}",
            cmd.target_id
        ));
    }
    if cmd.protocol != Protocol::Bacnet && cmd.protocol != Protocol::Mixed {
        return Ok("queued for fieldbus write (non-bacnet protocol)".into());
    }

    let (device, object_type, instance) = parse_bacnet_target(&cmd.target_id)?;
    let value = cmd.value.clone();
    let priority = cmd.priority;

    // Dry-run validation before touching the bus (matches REST approval flow).
    bacnet
        .write_dry_run(
            device,
            &object_type,
            instance,
            Some(value.clone()),
            "present-value",
            priority,
            None,
        )
        .map_err(|e| e.to_string())?;

    let result = bacnet
        .write_property(
            device,
            &object_type,
            instance,
            Some(value),
            "present-value",
            priority,
            None,
        )
        .await
        .map_err(|e| e.to_string())?;
    if result["ok"] != serde_json::Value::Bool(true)
        || result["status"].as_str() != Some("success")
        || result["outcome"].as_str() != Some("acknowledged")
    {
        return Err(format!(
            "bacnet write outcome was not acknowledged: {}",
            result
        ));
    }

    Ok(format!(
        "bacnet write executed for {} (approved by {})",
        cmd.target_id, cmd.approved_by
    ))
}

fn spawn_command_loop(
    mut events: tokio::sync::mpsc::UnboundedReceiver<Incoming>,
    client: AsyncClient,
    ctx: Arc<CommandContext>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        while let Some(incoming) = events.recv().await {
            if let Incoming::Publish(publish) = incoming {
                handle_command_publish(&client, &ctx, publish).await;
            }
        }
        info!("mqtt command listener stopped");
    })
}

struct MqttSession {
    client: AsyncClient,
    command_task: JoinHandle<()>,
}

async fn connect_mqtt_session(
    cfg: MqttConfig,
    topics: &TopicBuilder,
    ctx: Arc<CommandContext>,
) -> Option<MqttSession> {
    let handle = MqttHandle::connect(cfg).await.ok()?;
    if let Err(err) = subscribe_commands(&handle, topics).await {
        warn!(%err, "command subscribe failed");
    }
    let status_topic = topics.topic(TopicKind::Status, None);
    let _ = handle
        .publish_json(
            &status_topic,
            &serde_json::json!({
                "schema": openfdd_contracts::STATUS_SCHEMA_V1,
                "site_id": ctx.site_id,
                "edge_id": ctx.edge_id,
                "online": true
            }),
            true,
        )
        .await;

    let (client, events) = handle.split();
    let command_task = spawn_command_loop(events, client.clone(), ctx);
    Some(MqttSession {
        client,
        command_task,
    })
}

enum DrainPace {
    Progress,
    Idle,
    Blocked,
}

async fn drain_local_spool(client: &LocalIngestClient, spool: &Mutex<TelemetrySpool>) -> DrainPace {
    let pending = {
        let guard = spool.lock().await;
        match guard.list_pending().await {
            Ok(pending) => pending
                .into_iter()
                .take(SINK_DRAIN_BATCH)
                .collect::<Vec<_>>(),
            Err(err) => {
                warn!(%err, "list local spool failed");
                return DrainPace::Blocked;
            }
        }
    };
    if pending.is_empty() {
        return DrainPace::Idle;
    }
    for rec in pending {
        match client.send(&rec.envelope).await {
            Ok(()) => {
                if let Err(err) = spool.lock().await.ack(rec.seq).await {
                    warn!(%err, "local spool ack failed");
                }
            }
            Err(err) => {
                warn!(%err, "local central delivery failed; local spool will retry");
                return DrainPace::Blocked;
            }
        }
    }
    DrainPace::Progress
}

async fn drain_mqtt_spool(
    session: &mut MqttSession,
    spool: &Mutex<TelemetrySpool>,
    publish_ledger: &MqttPublishLedger,
) -> bool {
    let pending = {
        let guard = spool.lock().await;
        match guard.list_pending().await {
            Ok(pending) => pending
                .into_iter()
                .take(SINK_DRAIN_BATCH)
                .collect::<Vec<_>>(),
            Err(_) => {
                warn!("list spool failed");
                return false;
            }
        }
    };
    for rec in pending {
        match publish_json(&session.client, &rec.topic, &rec.envelope, false).await {
            Ok(()) => {
                publish_ledger.record_ack(
                    rec.envelope.sequence,
                    u32::try_from(rec.envelope.points.len()).unwrap_or(u32::MAX),
                    &equipment_ids_in(&rec.envelope),
                );
                if let Err(err) = spool.lock().await.ack(rec.seq).await {
                    warn!(%err, "mqtt spool ack failed");
                }
            }
            Err(err) => {
                publish_ledger.record_fail(&equipment_ids_in(&rec.envelope));
                warn!(%err, "publish failed; will retry");
                session.command_task.abort();
                return true;
            }
        }
    }
    false
}

fn spawn_spool_ingress(
    mut rx: mpsc::UnboundedReceiver<QueuedDelivery>,
    spool: Arc<Mutex<TelemetrySpool>>,
    label: &'static str,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        while let Some(item) = rx.recv().await {
            if let Err(err) = spool.lock().await.enqueue(&item.topic, item.envelope).await {
                warn!(%err, label, "spool enqueue failed");
            }
        }
    })
}

async fn pace_after(pace: DrainPace) {
    if !matches!(pace, DrainPace::Progress) {
        tokio::time::sleep(SINK_IDLE_WAIT).await;
    }
}

/// Map REST poll rows into telemetry points (`rest:<device>:<point>` ids).
fn rest_telemetry_points(
    rows: &[serde_json::Value],
    building_id: Option<&str>,
    type_stamps: &EquipmentTypeStamps,
) -> Vec<TelemetryPoint> {
    rows.iter()
        .filter_map(|v| {
            let device = v.get("device")?.as_str()?;
            let point = v.get("point")?.as_str()?;
            if device.trim().is_empty() || point.trim().is_empty() {
                return None;
            }
            let equipment_type =
                equipment_type_for(type_stamps, device, row_equipment_type_stamp(v).as_deref());
            let tags = serde_json::json!({"rest": true, "device": device})
                .as_object()
                .cloned()
                .unwrap_or_default();
            let (quality, non_finite) = poll_error_quality(v.get("error"));
            let mut tags = historian_tags(tags, building_id, device, point, equipment_type);
            stamp_non_finite_quality(&mut tags, non_finite);
            Some(TelemetryPoint {
                id: format!("rest:{device}:{point}"),
                display_name: Some(point.to_string()),
                kind: Some(ValueKind::Number),
                value: v.get("value").cloned().unwrap_or(serde_json::Value::Null),
                unit: v
                    .get("units")
                    .and_then(|x| x.as_str())
                    .filter(|u| !u.is_empty())
                    .map(str::to_string),
                quality,
                tags,
            })
        })
        .collect()
}

pub async fn spawn_if_configured(
    settings: Arc<Settings>,
    poll: Arc<PollEngine>,
    bacnet_client: Arc<BacnetClientService>,
    rest: Arc<RestClientService>,
    telemetry: Arc<TelemetryControl>,
    publish_ledger: Arc<MqttPublishLedger>,
) {
    let mode = match ingest_mode() {
        Ok(mode) => mode,
        Err(error) => {
            warn!(%error, "telemetry bridge disabled because ingest mode is invalid");
            return;
        }
    };
    if !mode.uses_mqtt() && !mode.uses_local() {
        info!("telemetry bridge disabled");
        return;
    }

    let mqtt_allowed = mqtt_delivery_enabled(mode);
    if mode.uses_mqtt() && !mqtt_allowed {
        warn!("MQTT ingest is disabled; local delivery remains enabled for local_fieldbus and dual modes");
        if !mode.uses_local() {
            return;
        }
    }

    let site_id = std::env::var("OPENFDD_SITE_ID").unwrap_or_else(|_| "local".into());
    let edge_id = std::env::var("OPENFDD_EDGE_ID").unwrap_or_else(|_| "fieldbus-1".into());
    let building_id = std::env::var("OPENFDD_BUILDING_ID")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    if building_id.is_none() {
        warn!(
            "OPENFDD_BUILDING_ID is unset; MQTT telemetry will omit canonical building identity and H7 persistence will fail closed"
        );
    }
    let tenant_id = std::env::var("OPENFDD_TENANT_ID")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    let port: u16 = std::env::var("OPENFDD_MQTT_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8883);
    let mqtt_spool_dir = PathBuf::from(
        std::env::var("OPENFDD_MQTT_SPOOL_DIR")
            .unwrap_or_else(|_| format!("/tmp/openfdd-spool-{edge_id}")),
    );
    let local_client = if mode.uses_local() {
        match LocalIngestClient::from_env(&site_id) {
            Ok(client) => Some(client),
            Err(error) => {
                warn!(%error, "local fieldbus delivery disabled");
                None
            }
        }
    } else {
        None
    };
    if mode.uses_local() && local_client.is_none() && !mode.uses_mqtt() {
        return;
    }
    let interval = mqtt_publish_interval_secs(&settings);
    info!(
        publish_interval_secs = interval,
        tenant_id = tenant_id.as_deref(),
        mode = ?mode,
        "fieldbus full-snapshot delivery profile"
    );

    // Wave N: when OPENFDD_TENANT_ID is set, emit tenants/{tid}/buildings/{bid}/… topics
    // required by central MT-ON ingest. Building defaults to SITE_ID when unset.
    let topics = if let Some(tid) = tenant_id.as_ref() {
        let bid = building_id.clone().unwrap_or_else(|| site_id.clone());
        TopicBuilder::with_tenant(tid.clone(), bid, edge_id.clone())
    } else {
        TopicBuilder::new(site_id.clone(), edge_id.clone())
    };
    let command_ctx = Arc::new(CommandContext {
        site_id: site_id.clone(),
        edge_id: edge_id.clone(),
        bacnet_client,
        telemetry: Arc::clone(&telemetry),
        deduper: Mutex::new(CommandDeduper::new()),
    });

    tokio::spawn(async move {
        let local_tx = if let Some(client) = local_client {
            match TelemetrySpool::open(
                SpoolConfig::new(local_spool_dir(&edge_id))
                    .with_max_records(local_spool_max_records()),
            )
            .await
            {
                Ok(spool) => {
                    let spool = Arc::new(Mutex::new(spool));
                    let (tx, rx) = mpsc::unbounded_channel();
                    spawn_spool_ingress(rx, Arc::clone(&spool), "local");
                    tokio::spawn(async move {
                        loop {
                            let pace = drain_local_spool(&client, &spool).await;
                            pace_after(pace).await;
                        }
                    });
                    Some(tx)
                }
                Err(err) => {
                    warn!(%err, "local fieldbus spool open failed");
                    None
                }
            }
        } else {
            None
        };
        let remote_tx = if mqtt_allowed {
            match TelemetrySpool::open(SpoolConfig::new(&mqtt_spool_dir)).await {
                Ok(spool) => {
                    let spool = Arc::new(Mutex::new(spool));
                    let (tx, rx) = mpsc::unbounded_channel();
                    spawn_spool_ingress(rx, Arc::clone(&spool), "remote");
                    let remote_topics = topics.clone();
                    let remote_site = site_id.clone();
                    let remote_edge = edge_id.clone();
                    let remote_ctx = Arc::clone(&command_ctx);
                    let remote_ledger = Arc::clone(&publish_ledger);
                    tokio::spawn(async move {
                        let mut mqtt: Option<MqttSession> = None;
                        loop {
                            let pending = spool.lock().await.list_pending().await.ok();
                            let pending_count =
                                pending.as_ref().map(|rows| rows.len()).unwrap_or(0);
                            if pending_count == 0 {
                                pace_after(DrainPace::Idle).await;
                                continue;
                            }
                            if mqtt.is_none() {
                                mqtt = tokio::time::timeout(
                                    Duration::from_secs(5),
                                    connect_mqtt_session(
                                        mqtt_config(&remote_site, &remote_edge, port),
                                        &remote_topics,
                                        Arc::clone(&remote_ctx),
                                    ),
                                )
                                .await
                                .ok()
                                .flatten();
                                if mqtt.is_none() {
                                    remote_ledger.record_no_session(&equipment_ids_from_pending(
                                        pending.as_deref(),
                                    ));
                                    pace_after(DrainPace::Blocked).await;
                                    continue;
                                }
                            }
                            let failed = if let Some(session) = mqtt.as_mut() {
                                drain_mqtt_spool(session, &spool, &remote_ledger).await
                            } else {
                                false
                            };
                            if failed {
                                mqtt = None;
                                pace_after(DrainPace::Blocked).await;
                            }
                        }
                    });
                    Some(tx)
                }
                Err(err) => {
                    warn!(%err, "mqtt spool open failed");
                    None
                }
            }
        } else {
            None
        };

        let type_stamps = load_equipment_type_stamps();

        let mut seq = 0u64;
        // Publish immediately on start (after connect), then every fixed interval.
        // Sleeping first forced CI/ops to wait a full 300s for the first envelope.
        let mut first_cycle = true;
        loop {
            if !first_cycle {
                tokio::time::sleep(Duration::from_secs_f64(interval)).await;
            }
            first_cycle = false;

            if telemetry.is_suspended() {
                continue;
            }

            let status = poll.status().await;
            let last_values = status
                .get("last_values")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            let points: Vec<TelemetryPoint> = last_values
                .into_iter()
                .filter_map(|v| {
                    let device = v.get("device_instance")?.as_u64()? as u32;
                    let equipment_id = v.get("device_name")?.as_str()?.trim();
                    let point_name = v.get("point_name")?.as_str()?.trim();
                    if equipment_id.is_empty() || point_name.is_empty() {
                        return None;
                    }
                    let object_type = v.get("object_type")?.as_str()?.replace('_', "-");
                    let object_instance = v.get("object_instance")?.as_u64()? as u32;
                    // Include point_name so dual roles for one BACnet object remain
                    // distinct in every full poll snapshot.
                    let id =
                        format!("bacnet:{device}:{object_type}:{object_instance}:{point_name}");
                    let value = telemetry_point_value(&v);
                    let (quality, non_finite) = poll_error_quality(v.get("error"));
                    let equipment_type = equipment_type_for(
                        &type_stamps,
                        equipment_id,
                        row_equipment_type_stamp(&v).as_deref(),
                    );
                    let base = serde_json::json!({"bacnet": true, "device_instance": device})
                        .as_object()
                        .cloned()
                        .unwrap_or_default();
                    let mut tags = historian_tags(
                        base,
                        building_id.as_deref(),
                        equipment_id,
                        point_name,
                        equipment_type,
                    );
                    stamp_non_finite_quality(&mut tags, non_finite);
                    Some(TelemetryPoint {
                        id,
                        display_name: Some(point_name.to_string()),
                        kind: Some(ValueKind::Number),
                        value,
                        unit: v.get("units").and_then(|x| x.as_str()).map(str::to_string),
                        quality,
                        tags,
                    })
                })
                .collect();
            let rest_rows = rest.last_values().await;
            let rest_out = rest_telemetry_points(&rest_rows, building_id.as_deref(), &type_stamps);
            let bacnet_points = points;
            if bacnet_points.is_empty() && rest_out.is_empty() {
                continue;
            }
            // Chunk by equipment so one large site cannot exceed MQTT packet limits
            // (rumqttc default was 10 KiB; a full HVAC envelope can be ~20 KiB).
            if !bacnet_points.is_empty() {
                let topic = topics.topic(TopicKind::Telemetry, Some(Protocol::Bacnet));
                for chunk in chunk_points_by_equipment(bacnet_points) {
                    seq += 1;
                    let env =
                        TelemetryEnvelope::new(&site_id, &edge_id, Protocol::Bacnet, seq, chunk);
                    enqueue_isolated(local_tx.as_ref(), remote_tx.as_ref(), &topic, env);
                }
            }
            if !rest_out.is_empty() {
                let topic = topics.topic(TopicKind::Telemetry, Some(Protocol::Rest));
                for chunk in chunk_points_by_equipment(rest_out) {
                    seq += 1;
                    let env =
                        TelemetryEnvelope::new(&site_id, &edge_id, Protocol::Rest, seq, chunk);
                    enqueue_isolated(local_tx.as_ref(), remote_tx.as_ref(), &topic, env);
                }
            }
        }
    });
}

fn enqueue_isolated(
    local_tx: Option<&mpsc::UnboundedSender<QueuedDelivery>>,
    remote_tx: Option<&mpsc::UnboundedSender<QueuedDelivery>>,
    topic: &str,
    envelope: TelemetryEnvelope,
) {
    // Sends on an unbounded channel return immediately. Each sink enqueues to
    // its own spool on its own task, and publish/HTTP delivery is a second
    // task, so a remote backlog cannot stall local collection.
    if let Some(tx) = local_tx {
        if tx
            .send(QueuedDelivery {
                topic: "local".into(),
                envelope: envelope.clone(),
            })
            .is_err()
        {
            warn!("local sink worker stopped");
        }
    }
    if let Some(tx) = remote_tx {
        if tx
            .send(QueuedDelivery {
                topic: topic.to_string(),
                envelope,
            })
            .is_err()
        {
            warn!("remote sink worker stopped");
        }
    }
}

fn equipment_ids_from_pending(pending: Option<&[SpoolRecord]>) -> Vec<String> {
    let mut ids = Vec::new();
    let Some(rows) = pending else {
        return ids;
    };
    for rec in rows {
        for id in equipment_ids_in(&rec.envelope) {
            if !ids.iter().any(|seen| seen == &id) {
                ids.push(id);
            }
        }
    }
    ids
}

fn equipment_ids_in(env: &TelemetryEnvelope) -> Vec<String> {
    let mut ids = Vec::new();
    for point in &env.points {
        let Some(id) = point
            .tags
            .get("equipment_id")
            .and_then(|value| value.as_str())
            .map(str::trim)
            .filter(|id| !id.is_empty())
        else {
            continue;
        };
        if !ids.iter().any(|seen| seen == id) {
            ids.push(id.to_string());
        }
    }
    ids
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mqtt_publish_interval_fixed_300() {
        let mut s = Settings::default();
        s.poll.interval_secs = 30.0;
        assert!((mqtt_publish_interval_secs(&s) - 300.0).abs() < f64::EPSILON);
    }

    #[test]
    fn ingest_modes_are_explicit_and_non_overlapping() {
        assert_eq!(IngestMode::parse("mqtts").unwrap(), IngestMode::Mqtts);
        assert_eq!(
            IngestMode::parse("local_fieldbus").unwrap(),
            IngestMode::LocalFieldbus
        );
        assert_eq!(IngestMode::parse("dual").unwrap(), IngestMode::Dual);
        assert!(IngestMode::Mqtts.uses_mqtt());
        assert!(!IngestMode::Mqtts.uses_local());
        assert!(!IngestMode::LocalFieldbus.uses_mqtt());
        assert!(IngestMode::LocalFieldbus.uses_local());
        assert!(IngestMode::Dual.uses_mqtt());
        assert!(IngestMode::Dual.uses_local());
        assert!(IngestMode::parse("mqtt").is_err());
    }

    #[test]
    fn dual_without_broker_is_local_only() {
        assert!(!mqtt_delivery_enabled_with(IngestMode::Dual, false));
        assert!(mqtt_delivery_enabled_with(IngestMode::Dual, true));
        assert!(!mqtt_delivery_enabled_with(IngestMode::LocalFieldbus, true));
    }

    #[test]
    fn parse_bacnet_target_id() {
        let (dev, ot, inst) = parse_bacnet_target("bacnet:100:analog-value:5").unwrap();
        assert_eq!(dev, 100);
        assert_eq!(ot, "analog-value");
        assert_eq!(inst, 5);
    }

    #[test]
    fn full_snapshot_chunking_preserves_unchanged_points_every_cycle() {
        let mk = |equip: &str, id: &str| {
            let mut tags = serde_json::Map::new();
            tags.insert(
                "equipment_id".into(),
                serde_json::Value::String(equip.to_string()),
            );
            TelemetryPoint {
                id: id.to_string(),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: serde_json::json!(1.0),
                unit: None,
                quality: Quality::Good,
                tags,
            }
        };
        let snapshot = vec![
            mk("jci_vav_8", "a"),
            mk("rtu_01", "b"),
            mk("jci_vav_8", "c"),
            mk("rtu_01", "d"),
        ];
        let chunks = chunk_points_by_equipment(snapshot.clone());
        let next_cycle = chunk_points_by_equipment(snapshot);
        assert_eq!(chunks.len(), 2);
        assert_eq!(next_cycle.len(), 2);
        assert_eq!(chunks[0].len(), 2);
        assert_eq!(next_cycle[0].len(), 2);
        assert_eq!(next_cycle[1].len(), 2);
        assert_eq!(chunks[0][0].id, "a");
        assert_eq!(chunks[0][1].id, "c");
        assert_eq!(
            chunks[1][0].tags["equipment_id"],
            serde_json::json!("rtu_01")
        );
    }

    #[test]
    fn reject_invalid_target_id() {
        assert!(parse_bacnet_target("point-1").is_err());
    }

    #[test]
    fn telemetry_prefers_value_over_present_value() {
        let row = serde_json::json!({
            "value": 57.8,
            "present_value": 1.0
        });
        assert_eq!(telemetry_point_value(&row), serde_json::json!(57.8));
        let legacy = serde_json::json!({"present_value": 70.25});
        assert_eq!(telemetry_point_value(&legacy), serde_json::json!(70.25));
        let missing = serde_json::json!({"point_name": "OA-T"});
        assert_eq!(telemetry_point_value(&missing), serde_json::Value::Null);
    }

    #[test]
    fn historian_tags_use_config_metadata_not_transport_id() {
        let tags = historian_tags(
            serde_json::Map::new(),
            Some("BUILDING_100"),
            "AHU_1",
            "discharge-air-temp",
            Some("ahu".into()),
        );
        assert_eq!(tags["building_id"], serde_json::json!("BUILDING_100"));
        assert_eq!(tags["equipment_id"], serde_json::json!("AHU_1"));
        assert_eq!(tags["role"], serde_json::json!("sat"));
        assert_eq!(tags["equipment_type"], serde_json::json!("ahu"));
    }

    #[test]
    fn equipment_type_stamp_prefers_row_then_map_then_default() {
        std::env::set_var("OPENFDD_EQUIPMENT_TYPE", "zone_other");
        std::env::set_var("OPENFDD_EQUIPMENT_TYPE_MAP", r#"{"FEC_1":"cv_ahu"}"#);
        let stamps = load_equipment_type_stamps();
        assert_eq!(
            equipment_type_for(&stamps, "FEC_1", Some("vav")),
            Some("vav".into())
        );
        assert_eq!(
            equipment_type_for(&stamps, "FEC_1", None),
            Some("cv_ahu".into())
        );
        assert_eq!(
            equipment_type_for(&stamps, "OTHER", None),
            Some("zone_other".into())
        );
        std::env::remove_var("OPENFDD_EQUIPMENT_TYPE");
        std::env::remove_var("OPENFDD_EQUIPMENT_TYPE_MAP");
    }

    #[test]
    fn rest_rows_map_to_rest_telemetry_points() {
        let rows = vec![
            serde_json::json!({
                "device": "chiller-api", "point": "CHW-ST",
                "value": 44.2, "units": "°F", "error": null
            }),
            serde_json::json!({
                "device": "chiller-api", "point": "CHW-RT",
                "value": null, "units": "", "error": "circuit open"
            }),
        ];
        let points =
            rest_telemetry_points(&rows, Some("BUILDING_100"), &EquipmentTypeStamps::default());
        assert_eq!(points.len(), 2);
        assert_eq!(points[0].id, "rest:chiller-api:CHW-ST");
        assert_eq!(points[0].quality, Quality::Good);
        assert_eq!(points[0].unit.as_deref(), Some("°F"));
        assert_eq!(
            points[0].tags["building_id"],
            serde_json::json!("BUILDING_100")
        );
        assert_eq!(
            points[0].tags["equipment_id"],
            serde_json::json!("chiller-api")
        );
        assert_eq!(points[0].tags["role"], serde_json::json!("chw_supply_t"));
        assert_eq!(points[1].quality, Quality::Bad);
        assert_eq!(points[1].unit, None);
        assert!(points[1].tags.get("non_finite_quality").is_none());
    }

    #[test]
    fn non_finite_poll_error_is_the_only_range_marker() {
        let (quality, non_finite) = poll_error_quality(Some(&serde_json::json!(
            "bad-quality: non-finite BACnet real (inf)"
        )));
        assert_eq!(quality, Quality::Bad);
        assert!(non_finite);
        let (quality, non_finite) = poll_error_quality(Some(&serde_json::json!(
            "Error: class=Object code=UnknownObject"
        )));
        assert_eq!(quality, Quality::Bad);
        assert!(!non_finite);
        let (quality, non_finite) = poll_error_quality(Some(&serde_json::Value::Null));
        assert_eq!(quality, Quality::Good);
        assert!(!non_finite);
    }

    #[test]
    fn deduper_bounds_and_duplicate_detection() {
        let mut d = CommandDeduper::new();
        let id1 = uuid::Uuid::new_v4();
        let id2 = uuid::Uuid::new_v4();
        assert!(d.record(id1));
        assert!(!d.record(id1));
        assert!(d.record(id2));
    }

    #[test]
    fn local_ack_requires_committed_rows() {
        let durable = serde_json::json!({
            "ok": true,
            "duplicate": false,
            "pending": false,
            "persisted_rows": 1
        });
        assert!(durable_local_ack(reqwest::StatusCode::OK, &durable));
        let replay = serde_json::json!({
            "ok": true,
            "duplicate": true,
            "pending": false,
            "persisted_rows": 1
        });
        assert!(durable_local_ack(reqwest::StatusCode::OK, &replay));
        let pending = serde_json::json!({
            "ok": true,
            "duplicate": false,
            "pending": true,
            "persisted_rows": 0
        });
        assert!(!durable_local_ack(reqwest::StatusCode::ACCEPTED, &pending));
        assert!(!durable_local_ack(reqwest::StatusCode::OK, &pending));
        let empty = serde_json::json!({
            "ok": true,
            "pending": false,
            "persisted_rows": 0
        });
        assert!(!durable_local_ack(reqwest::StatusCode::OK, &empty));
    }

    #[tokio::test]
    async fn remote_publish_backlog_does_not_block_local_collection() {
        let local_dir =
            std::env::temp_dir().join(format!("ofdd-local-sink-{}", uuid::Uuid::new_v4()));
        let remote_dir =
            std::env::temp_dir().join(format!("ofdd-remote-sink-{}", uuid::Uuid::new_v4()));
        let local_spool = Arc::new(Mutex::new(
            TelemetrySpool::open(SpoolConfig::new(&local_dir))
                .await
                .unwrap(),
        ));
        let remote_spool = Arc::new(Mutex::new(
            TelemetrySpool::open(SpoolConfig::new(&remote_dir))
                .await
                .unwrap(),
        ));
        let (local_tx, local_rx) = mpsc::unbounded_channel();
        let (remote_tx, remote_rx) = mpsc::unbounded_channel();
        spawn_spool_ingress(local_rx, Arc::clone(&local_spool), "local");
        spawn_spool_ingress(remote_rx, Arc::clone(&remote_spool), "remote");
        let remote_held = Arc::clone(&remote_spool);
        let (held_tx, held_rx) = tokio::sync::oneshot::channel();
        let blocked = tokio::spawn(async move {
            let _guard = remote_held.lock().await;
            let _ = held_tx.send(());
            tokio::time::sleep(Duration::from_millis(400)).await;
        });
        held_rx.await.unwrap();
        let envelope = TelemetryEnvelope::new(
            "building-local",
            "edge-local",
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "point-local".into(),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: serde_json::json!(1),
                unit: None,
                quality: Quality::Good,
                tags: Default::default(),
            }],
        );
        let started = std::time::Instant::now();
        for _ in 0..5 {
            enqueue_isolated(
                Some(&local_tx),
                Some(&remote_tx),
                "remote/topic",
                envelope.clone(),
            );
        }
        let deadline = std::time::Instant::now() + Duration::from_millis(250);
        loop {
            let local_n = local_spool.lock().await.list_pending().await.unwrap().len();
            if local_n == 5 {
                break;
            }
            if std::time::Instant::now() > deadline {
                panic!("local collection stalled at {local_n} rows while remote publish held the remote spool");
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        assert!(started.elapsed() < Duration::from_millis(250));
        blocked.await.unwrap();
        let remote_deadline = std::time::Instant::now() + Duration::from_millis(500);
        loop {
            let remote_n = remote_spool
                .lock()
                .await
                .list_pending()
                .await
                .unwrap()
                .len();
            if remote_n == 5 {
                break;
            }
            if std::time::Instant::now() > remote_deadline {
                panic!(
                    "remote spool did not retain the backlog after publish unblocked: {remote_n}"
                );
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        drop(local_tx);
        drop(remote_tx);
        let _ = tokio::fs::remove_dir_all(&local_dir).await;
        let _ = tokio::fs::remove_dir_all(&remote_dir).await;
    }
}
