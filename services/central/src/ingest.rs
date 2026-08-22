//! MQTTS subscriber → canonical historian writer + optional compatibility mirror + edge shadow.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use openfdd_contracts::TelemetryEnvelope;
use openfdd_mqtt::{MqttConfig, MqttHandle};
use rumqttc::Incoming;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tracing::{debug, info, warn};

use crate::live_historian::LiveHistorian;
use crate::state::AppState;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TopicKind {
    Telemetry,
    Metadata,
    Discovery,
    Status,
    Acks,
    Unknown,
}

#[derive(Debug)]
struct ParsedTopic {
    site_id: String,
    edge_id: String,
    kind: TopicKind,
    protocol: Option<String>,
}

pub fn spawn_mqtt_ingest(state: Arc<AppState>) {
    let _ = spawn_mqtt_ingest_inner(state, None);
}

pub fn spawn_mqtt_ingest_with_shutdown(
    state: Arc<AppState>,
    shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    spawn_mqtt_ingest_inner(state, Some(shutdown))
}

fn spawn_mqtt_ingest_inner(
    state: Arc<AppState>,
    mut shutdown: Option<watch::Receiver<bool>>,
) -> JoinHandle<()> {
    if !matches!(
        std::env::var("OPENFDD_MQTT_ENABLED")
            .unwrap_or_default()
            .to_ascii_lowercase()
            .as_str(),
        "1" | "true" | "yes" | "on"
    ) {
        info!("central MQTT ingest disabled (OPENFDD_MQTT_ENABLED!=1)");
        return tokio::spawn(async {});
    }

    tokio::spawn(async move {
        let mut live_historian = match LiveHistorian::from_env() {
            Ok(historian) => {
                info!("H7 canonical live historian buffering enabled");
                Some(historian)
            }
            Err(err) => {
                // Canonical history is now the durability path. Do not keep
                // accepting MQTT solely into the legacy Feather/JSONL mirror.
                warn!(%err, "canonical live historian unavailable; refusing durability downgrade");
                return;
            }
        };
        let mut flush_tick = tokio::time::interval(Duration::from_secs(1));
        flush_tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);

        let site = std::env::var("OPENFDD_SITE_ID").unwrap_or_else(|_| "local".into());
        let edge = std::env::var("OPENFDD_EDGE_ID").unwrap_or_else(|_| "+".into());
        let host = std::env::var("OPENFDD_MQTT_HOST").unwrap_or_else(|_| "127.0.0.1".into());
        let port: u16 = std::env::var("OPENFDD_MQTT_PORT")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(8883);
        let cfg = MqttConfig {
            host,
            port,
            client_id: format!("central:{site}"),
            ca_pem: PathBuf::from(
                std::env::var("OPENFDD_MQTT_CA_PEM").unwrap_or_else(|_| "/mqtt/ca.pem".into()),
            ),
            cert_pem: PathBuf::from(
                std::env::var("OPENFDD_MQTT_CERT_PEM")
                    .unwrap_or_else(|_| "/mqtt/central.cert.pem".into()),
            ),
            key_pem: PathBuf::from(
                std::env::var("OPENFDD_MQTT_KEY_PEM")
                    .unwrap_or_else(|_| "/mqtt/central.key.pem".into()),
            ),
            keep_alive_secs: 30,
        };

        loop {
            let connection = tokio::select! {
                _ = wait_for_shutdown(&mut shutdown) => {
                    drain_live_historian(&mut live_historian);
                    return;
                }
                result = MqttHandle::connect(cfg.clone()) => result,
            };
            match connection {
                Ok(handle) => {
                    let base = format!("openfdd/v1/sites/{site}/edges/{edge}");
                    let topics = [
                        format!("{base}/telemetry/#"),
                        format!("{base}/metadata/#"),
                        format!("{base}/discovery/#"),
                        format!("{base}/status"),
                        format!("{base}/acks/#"),
                    ];
                    for topic in &topics {
                        if let Err(err) = handle.subscribe(topic).await {
                            warn!(%err, topic, "subscribe failed");
                        }
                    }

                    let (publisher, mut events) = handle.split();
                    state.set_mqtt_publisher(publisher);
                    info!("central MQTT ingest connected; publisher ready for commands");

                    loop {
                        tokio::select! {
                            _ = wait_for_shutdown(&mut shutdown) => {
                                *state.mqtt_publisher.lock().unwrap() = None;
                                drain_live_historian(&mut live_historian);
                                return;
                            }
                            maybe_event = events.recv() => {
                                let Some(ev) = maybe_event else {
                                    break;
                                };
                                if let Incoming::Publish(p) = ev {
                                    let topic = p.topic.clone();
                                    handle_payload(
                                        &state,
                                        live_historian.as_mut(),
                                        &topic,
                                        &p.payload,
                                    );
                                }
                            }
                            _ = flush_tick.tick() => {
                                if let Some(historian) = live_historian.as_mut() {
                                    match historian.flush_due() {
                                        Ok(report) if report.flushes > 0 => {
                                            debug!(
                                                flushes = report.flushes,
                                                persisted_rows = report.persisted_rows,
                                                latest_persisted_timestamp_utc = ?report.latest_persisted_timestamp_utc,
                                                "flushed due canonical live historian batches"
                                            );
                                        }
                                        Ok(_) => {}
                                        Err(err) => warn!(%err, "canonical live historian time flush failed; buffered rows retained for retry"),
                                    }
                                }
                            }
                        }
                    }
                    warn!("central mqtt event stream ended; reconnecting");
                    *state.mqtt_publisher.lock().unwrap() = None;
                }
                Err(err) => {
                    warn!(%err, "central mqtt connect failed; retrying");
                    tokio::select! {
                        _ = wait_for_shutdown(&mut shutdown) => {
                            drain_live_historian(&mut live_historian);
                            return;
                        }
                        _ = tokio::time::sleep(Duration::from_secs(3)) => {}
                    }
                }
            }
        }
    })
}

async fn wait_for_shutdown(shutdown: &mut Option<watch::Receiver<bool>>) {
    let Some(receiver) = shutdown.as_mut() else {
        std::future::pending::<()>().await;
        return;
    };
    if *receiver.borrow() {
        return;
    }
    let _ = receiver.changed().await;
}

fn drain_live_historian(live_historian: &mut Option<LiveHistorian>) {
    let Some(historian) = live_historian.as_mut() else {
        return;
    };
    match historian.shutdown_flush() {
        Ok(report) => info!(
            flushes = report.flushes,
            persisted_rows = report.persisted_rows,
            latest_persisted_timestamp_utc = ?report.latest_persisted_timestamp_utc,
            "drained canonical live historian on graceful shutdown"
        ),
        Err(error) => warn!(
            %error,
            pending_rows = historian.pending_rows(),
            "canonical live historian shutdown drain failed"
        ),
    }
}

fn parse_topic(topic: &str) -> Option<ParsedTopic> {
    let parts: Vec<&str> = topic.split('/').collect();
    if parts.len() < 6 {
        return None;
    }
    if parts[0] != "openfdd" || parts[1] != "v1" || parts[2] != "sites" || parts[4] != "edges" {
        return None;
    }
    let site_id = parts[3].to_string();
    let edge_id = parts[5].to_string();
    let kind = match parts.get(6).copied() {
        Some("telemetry") => TopicKind::Telemetry,
        Some("metadata") => TopicKind::Metadata,
        Some("discovery") => TopicKind::Discovery,
        Some("status") if parts.len() == 7 => TopicKind::Status,
        Some("acks") => TopicKind::Acks,
        _ => TopicKind::Unknown,
    };
    let protocol = parts.get(7).map(|s| s.to_string());
    Some(ParsedTopic {
        site_id,
        edge_id,
        kind,
        protocol,
    })
}

fn handle_payload(
    state: &AppState,
    live_historian: Option<&mut LiveHistorian>,
    topic: &str,
    payload: &[u8],
) {
    let Some(parsed) = parse_topic(topic) else {
        handle_untyped_payload(state, payload);
        return;
    };

    match parsed.kind {
        TopicKind::Telemetry => handle_telemetry(
            state,
            live_historian,
            &parsed.site_id,
            &parsed.edge_id,
            payload,
        ),
        TopicKind::Metadata => {
            if let Ok(value) = serde_json::from_slice(payload) {
                store_shadow_payload(state, &parsed.edge_id, |shadow| {
                    let key = parsed.protocol.as_deref().unwrap_or("mixed");
                    shadow.last_metadata.insert(key.to_string(), value);
                });
            } else {
                record_reject(state, payload, "metadata decode failed");
            }
        }
        TopicKind::Discovery => {
            if let Ok(value) = serde_json::from_slice(payload) {
                store_shadow_payload(state, &parsed.edge_id, |shadow| {
                    let key = parsed.protocol.as_deref().unwrap_or("mixed");
                    shadow.last_discovery.insert(key.to_string(), value);
                });
            } else {
                record_reject(state, payload, "discovery decode failed");
            }
        }
        TopicKind::Status => {
            if let Ok(value) = serde_json::from_slice(payload) {
                store_shadow_payload(state, &parsed.edge_id, |shadow| {
                    shadow.last_status = Some(value);
                });
            } else {
                record_reject(state, payload, "status decode failed");
            }
        }
        TopicKind::Acks => handle_ack(state, payload),
        TopicKind::Unknown => handle_untyped_payload(state, payload),
    }
}

fn store_shadow_payload(
    state: &AppState,
    edge_id: &str,
    update: impl FnOnce(&mut crate::state::EdgeShadow),
) {
    let entry = state.edges.entry(edge_id.to_string()).or_default();
    let mut guard = entry.lock().unwrap();
    update(&mut guard);
}

fn handle_telemetry(
    state: &AppState,
    live_historian: Option<&mut LiveHistorian>,
    topic_site: &str,
    topic_edge: &str,
    payload: &[u8],
) {
    match serde_json::from_slice::<TelemetryEnvelope>(payload) {
        Ok(env) => {
            if let Err(err) = env.validate() {
                record_reject(state, payload, &err);
                return;
            }
            if env.site_id != topic_site || env.edge_id != topic_edge {
                record_reject(
                    state,
                    payload,
                    &format!(
                        "envelope site/edge ({}/{}) does not match topic ({}/{})",
                        env.site_id, env.edge_id, topic_site, topic_edge
                    ),
                );
                return;
            }
            let key = (env.edge_id.clone(), env.message_id);
            if state.seen_messages.contains_key(&key) {
                *state.ingest_dup.lock().unwrap() += 1;
                return;
            }

            if let Some(historian) = live_historian {
                match historian.ingest_envelope(&env) {
                    Ok(report) => {
                        if report.eligible_points > 0 {
                            debug!(
                                message_id = %env.message_id,
                                eligible_points = report.eligible_points,
                                skipped_points = report.skipped_points,
                                persisted_rows = report.persisted_rows,
                                pending_rows = historian.pending_rows(),
                                latest_persisted_timestamp_utc = ?historian.latest_persisted_timestamp_utc(),
                                "accepted canonical live historian telemetry"
                            );
                        } else if report.skipped_points > 0 {
                            debug!(
                                message_id = %env.message_id,
                                skipped_points = report.skipped_points,
                                "telemetry has no explicit canonical historian identity"
                            );
                        }
                    }
                    Err(err) => {
                        record_reject(
                            state,
                            payload,
                            &format!("canonical historian ingest failed: {err}"),
                        );
                        return;
                    }
                }
            }

            // The compatibility mirror is no longer durability-critical. It is
            // available only for audited migration/interchange consumers that
            // explicitly opt in during the H7 cutover period.
            if legacy_compatibility_mirror_enabled() {
                persist_legacy_compatibility(&env);
            }
            state.seen_messages.insert(key, ());
            let entry = state.edges.entry(env.edge_id.clone()).or_default();
            let mut shadow = entry.lock().unwrap();
            shadow
                .sequences
                .insert(format!("{:?}", env.protocol), env.sequence);
            shadow.last_telemetry = Some(env);
            *state.ingest_ok.lock().unwrap() += 1;
        }
        Err(_) => handle_untyped_payload(state, payload),
    }
}

fn handle_ack(state: &AppState, payload: &[u8]) {
    if let Ok(ack) = serde_json::from_slice::<openfdd_contracts::CommandAck>(payload) {
        state.command_acks.insert(ack.command_id, ack);
    } else {
        record_reject(state, payload, "ack decode failed");
    }
}

fn handle_untyped_payload(state: &AppState, payload: &[u8]) {
    if let Ok(ack) = serde_json::from_slice::<openfdd_contracts::CommandAck>(payload) {
        state.command_acks.insert(ack.command_id, ack);
        return;
    }
    record_reject(state, payload, "decode failed");
}

fn record_reject(state: &AppState, payload: &[u8], error: &str) {
    *state.ingest_reject.lock().unwrap() += 1;
    state.dead_letters.lock().unwrap().push(serde_json::json!({
        "error": error,
        "raw": String::from_utf8_lossy(payload),
    }));
}

fn legacy_compatibility_mirror_enabled() -> bool {
    matches!(
        std::env::var("OPENFDD_LEGACY_INGEST_MIRROR")
            .unwrap_or_default()
            .trim()
            .to_ascii_lowercase()
            .as_str(),
        "1" | "true" | "yes" | "on"
    )
}

fn persist_legacy_compatibility(env: &TelemetryEnvelope) {
    use open_fdd_edge_prototype::historian::{feather_store, store};
    use std::collections::BTreeMap;

    let ts = env.observed_at.to_rfc3339();
    let mut wide: BTreeMap<String, f64> = BTreeMap::new();
    for p in &env.points {
        if let Some(n) = p.value.as_f64() {
            wide.insert(p.id.clone(), n);
        } else if let Some(n) = p.value.as_i64() {
            wide.insert(p.id.clone(), n as f64);
        }
    }
    if wide.is_empty() {
        return;
    }
    let _ = feather_store::write_wide_shard("mqtt", &env.site_id, &ts, &wide);
    let mut row = serde_json::json!({
        "timestamp": ts,
        "site_id": env.site_id,
        "edge_id": env.edge_id,
        "source": format!("{:?}", env.protocol).to_ascii_lowercase(),
        "message_id": env.message_id,
    });
    if let Some(obj) = row.as_object_mut() {
        for (k, v) in &wide {
            obj.insert(k.clone(), serde_json::json!(v));
        }
    }
    let _ = store::append_pivot_row(&row);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_telemetry_topic() {
        let p = parse_topic("openfdd/v1/sites/lab/edges/pi-1/telemetry/bacnet").unwrap();
        assert_eq!(p.site_id, "lab");
        assert_eq!(p.edge_id, "pi-1");
        assert_eq!(p.kind, TopicKind::Telemetry);
        assert_eq!(p.protocol.as_deref(), Some("bacnet"));
    }

    #[test]
    fn parse_metadata_topic() {
        let p = parse_topic("openfdd/v1/sites/lab/edges/pi-1/metadata/bacnet").unwrap();
        assert_eq!(p.kind, TopicKind::Metadata);
    }

    #[test]
    fn parse_status_topic() {
        let p = parse_topic("openfdd/v1/sites/lab/edges/pi-1/status").unwrap();
        assert_eq!(p.kind, TopicKind::Status);
    }
}
