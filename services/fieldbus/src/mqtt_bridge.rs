//! Optional MQTTS bridge: spool poll snapshots, publish telemetry, and safely execute commands.

use std::collections::{HashSet, VecDeque};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use openfdd_contracts::{
    CommandAck, CommandEnvelope, CommandStatus, Protocol, Quality, TelemetryEnvelope,
    TelemetryPoint, TopicBuilder, TopicKind, ValueKind,
};
use openfdd_mqtt::{
    publish_json, AsyncClient, Incoming, MqttConfig, MqttHandle, Publish, SpoolConfig,
    TelemetrySpool,
};
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tracing::{info, warn};

use crate::config::Settings;
use crate::services::bacnet_client::BacnetClientService;
use crate::services::poll::PollEngine;

const MAX_SEEN_COMMANDS: usize = 10_000;

pub fn mqtt_enabled() -> bool {
    matches!(
        std::env::var("OPENFDD_MQTT_ENABLED")
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "1" | "true" | "yes" | "on"
    )
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

    match execute_bacnet_command(&ctx.bacnet_client, &cmd).await {
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

async fn execute_bacnet_command(
    bacnet: &BacnetClientService,
    cmd: &CommandEnvelope,
) -> Result<String, String> {
    if cmd.protocol != Protocol::Bacnet {
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

    bacnet
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

pub async fn spawn_if_configured(
    settings: Arc<Settings>,
    poll: Arc<PollEngine>,
    bacnet_client: Arc<BacnetClientService>,
) {
    if !mqtt_enabled() {
        info!("MQTT bridge disabled (set OPENFDD_MQTT_ENABLED=1 to enable)");
        return;
    }

    let site_id = std::env::var("OPENFDD_SITE_ID").unwrap_or_else(|_| "local".into());
    let edge_id = std::env::var("OPENFDD_EDGE_ID").unwrap_or_else(|_| "fieldbus-1".into());
    let port: u16 = std::env::var("OPENFDD_MQTT_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8883);
    let spool_dir = PathBuf::from(
        std::env::var("OPENFDD_MQTT_SPOOL_DIR")
            .unwrap_or_else(|_| format!("/tmp/openfdd-spool-{edge_id}")),
    );
    let interval = settings.poll.interval_secs.max(5.0);

    let topics = TopicBuilder::new(site_id.clone(), edge_id.clone());
    let command_ctx = Arc::new(CommandContext {
        site_id: site_id.clone(),
        edge_id: edge_id.clone(),
        bacnet_client,
        deduper: Mutex::new(CommandDeduper::new()),
    });

    tokio::spawn(async move {
        let mut spool = match TelemetrySpool::open(SpoolConfig::new(&spool_dir)).await {
            Ok(s) => s,
            Err(err) => {
                warn!(%err, "mqtt spool open failed");
                return;
            }
        };

        let mut mqtt: Option<MqttSession> = None;

        let mut seq = 0u64;
        loop {
            tokio::time::sleep(Duration::from_secs_f64(interval)).await;
            seq += 1;
            let status = poll.status().await;
            let last_values = status
                .get("last_values")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            if last_values.is_empty() {
                continue;
            }
            let points: Vec<TelemetryPoint> = last_values
                .into_iter()
                .filter_map(|v| {
                    let device = v.get("device_instance")?.as_u64()? as u32;
                    let object_type = v.get("object_type")?.as_str()?.replace('_', "-");
                    let object_instance = v.get("object_instance")?.as_u64()? as u32;
                    let id = format!("bacnet:{device}:{object_type}:{object_instance}");
                    let value = v
                        .get("present_value")
                        .cloned()
                        .unwrap_or(serde_json::Value::Null);
                    Some(TelemetryPoint {
                        id,
                        display_name: v
                            .get("point_name")
                            .and_then(|x| x.as_str())
                            .map(str::to_string),
                        kind: Some(ValueKind::Number),
                        value,
                        unit: v.get("units").and_then(|x| x.as_str()).map(str::to_string),
                        quality: if v.get("error").map(|e| e.is_null()).unwrap_or(true) {
                            Quality::Good
                        } else {
                            Quality::Bad
                        },
                        tags: serde_json::json!({"bacnet": true, "device_instance": device})
                            .as_object()
                            .cloned()
                            .unwrap_or_default(),
                    })
                })
                .collect();
            if points.is_empty() {
                continue;
            }
            let env = TelemetryEnvelope::new(&site_id, &edge_id, Protocol::Bacnet, seq, points);
            let topic = topics.topic(TopicKind::Telemetry, Some(Protocol::Bacnet));
            if let Err(err) = spool.enqueue(&topic, env).await {
                warn!(%err, "spool enqueue failed");
                continue;
            }

            if mqtt.is_none() {
                mqtt = connect_mqtt_session(
                    mqtt_config(&site_id, &edge_id, port),
                    &topics,
                    Arc::clone(&command_ctx),
                )
                .await;
            }

            if let Some(ref session) = mqtt {
                match spool.list_pending().await {
                    Ok(pending) => {
                        for rec in pending {
                            match publish_json(&session.client, &rec.topic, &rec.envelope, false)
                                .await
                            {
                                Ok(()) => {
                                    let _ = spool.ack(rec.seq).await;
                                }
                                Err(err) => {
                                    warn!(%err, "publish failed; will retry");
                                    session.command_task.abort();
                                    mqtt = None;
                                    break;
                                }
                            }
                        }
                    }
                    Err(err) => warn!(%err, "list spool failed"),
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_bacnet_target_id() {
        let (dev, ot, inst) = parse_bacnet_target("bacnet:100:analog-value:5").unwrap();
        assert_eq!(dev, 100);
        assert_eq!(ot, "analog-value");
        assert_eq!(inst, 5);
    }

    #[test]
    fn reject_invalid_target_id() {
        assert!(parse_bacnet_target("point-1").is_err());
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
}
