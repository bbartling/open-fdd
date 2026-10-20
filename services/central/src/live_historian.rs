//! Live telemetry normalization into the Timescale writer.
//!
//! Portal and CSV samples are accepted for canonical history only when the
//! point carries explicit `building_id`, `equipment_id`, and `role` tags.

use std::sync::atomic::{AtomicUsize, Ordering};

use anyhow::{anyhow, bail, Result};
use chrono::{DateTime, Utc};
use openfdd_contracts::TelemetryEnvelope;
use tracing::warn;
use uuid::Uuid;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DuplicateRole {
    pub building_id: String,
    pub equipment_id: String,
    pub role: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LiveHistorianIngest {
    pub eligible_points: usize,
    pub skipped_points: usize,
    pub flushes: usize,
    pub persisted_rows: usize,
    /// Rows inserted by the Timescale upsert. Zero on paths that do not report it.
    pub inserted_rows: usize,
    /// Rows that already existed and were updated (overlap). Not the input length.
    pub updated_rows: usize,
    pub latest_persisted_timestamp_utc: Option<DateTime<Utc>>,
    /// Later points with a canonical role already present in the same equipment
    /// envelope. The first point wins deterministically; unique points remain valid.
    pub duplicate_roles: Vec<DuplicateRole>,
    /// Message ids whose rows were included in an atomically published part.
    /// A receipt stays pending until its id appears here, including time and
    /// shutdown flushes.
    pub persisted_message_ids: Vec<Uuid>,
    /// Exact message/equipment provenance for each published row group. A
    /// message is complete only after every eligible equipment group is
    /// published, even when one group flushes earlier than the others.
    pub persisted_message_groups: Vec<PersistedMessageGroup>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PersistedMessageGroup {
    pub message_id: Uuid,
    pub scope: String,
    pub edge_id: String,
    pub building_id: String,
    pub equipment_id: String,
    pub rows: usize,
}

enum WriterCommand {
    Ingest {
        scope: String,
        envelope: TelemetryEnvelope,
        /// Soft-OPEN 371 T1e: bytes reserved before clone; released after ingest.
        queued_bytes: usize,
        reply: tokio::sync::oneshot::Sender<Result<LiveHistorianIngest>>,
    },
    Flush {
        graceful: bool,
        reply: tokio::sync::oneshot::Sender<Result<LiveHistorianIngest>>,
    },
    Shutdown,
}

/// Owns the Timescale live historian and writes it on one blocking thread.
/// Request handlers await the reply; they do not publish from the async runtime.
///
/// Soft-OPEN 370 T1e / M70-05: the command queue is a bounded `sync_channel`.
/// Soft-OPEN 371 T1e: also byte-admitted before clone — count-full or byte-full
/// returns honest backpressure instead of growing RAM unboundedly.
pub struct LiveWriter {
    tx: std::sync::mpsc::SyncSender<WriterCommand>,
    thread: Option<std::thread::JoinHandle<()>>,
}

/// Estimated bytes currently reserved for envelopes queued on the live writer.
static LIVE_WRITER_QUEUE_BYTES: AtomicUsize = AtomicUsize::new(0);

fn writer_queue_capacity() -> usize {
    std::env::var("OPENFDD_LIVE_WRITER_QUEUE_CAP")
        .ok()
        .and_then(|raw| raw.parse().ok())
        .filter(|n| *n > 0)
        .unwrap_or(64)
}

fn writer_queue_max_bytes() -> usize {
    std::env::var("OPENFDD_LIVE_WRITER_QUEUE_MAX_BYTES")
        .ok()
        .and_then(|raw| raw.parse().ok())
        .filter(|n| *n > 0)
        .unwrap_or(64 * 1024 * 1024)
}

/// Conservative pre-clone size estimate for an ingest envelope (no serialization).
pub fn estimate_envelope_queue_bytes(envelope: &TelemetryEnvelope) -> usize {
    const BASE: usize = 256;
    const PER_POINT: usize = 128;
    let mut bytes = BASE
        .saturating_add(envelope.site_id.len())
        .saturating_add(envelope.edge_id.len())
        .saturating_add(envelope.schema.len());
    if let Some(device_id) = envelope.device_id.as_ref() {
        bytes = bytes.saturating_add(device_id.len());
    }
    for point in &envelope.points {
        bytes = bytes
            .saturating_add(PER_POINT)
            .saturating_add(point.id.len())
            .saturating_add(point.display_name.as_ref().map(|s| s.len()).unwrap_or(0))
            .saturating_add(point.unit.as_ref().map(|s| s.len()).unwrap_or(0));
        for (key, value) in &point.tags {
            bytes = bytes
                .saturating_add(key.len())
                .saturating_add(value.to_string().len());
        }
        bytes = bytes.saturating_add(point.value.to_string().len());
    }
    bytes.max(1)
}

pub fn live_writer_queue_bytes() -> usize {
    LIVE_WRITER_QUEUE_BYTES.load(Ordering::Acquire)
}

fn try_reserve_queue_bytes(additional: usize) -> Result<()> {
    let limit = writer_queue_max_bytes();
    let mut cur = LIVE_WRITER_QUEUE_BYTES.load(Ordering::Acquire);
    loop {
        let next = cur
            .checked_add(additional)
            .ok_or_else(|| anyhow!("live writer queue byte overflow"))?;
        if next > limit {
            bail!(
                "live historian writer queue byte budget exceeded ({cur} + {additional} > {limit}; OPENFDD_LIVE_WRITER_QUEUE_MAX_BYTES)"
            );
        }
        match LIVE_WRITER_QUEUE_BYTES.compare_exchange(
            cur,
            next,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => return Ok(()),
            Err(observed) => cur = observed,
        }
    }
}

fn release_queue_bytes(bytes: usize) {
    let _ = LIVE_WRITER_QUEUE_BYTES.try_update(Ordering::AcqRel, Ordering::Acquire, |cur| {
        Some(cur.saturating_sub(bytes))
    });
}

impl LiveWriter {
    pub fn start() -> Self {
        let (tx, rx) = std::sync::mpsc::sync_channel(writer_queue_capacity());
        let thread = std::thread::Builder::new()
            .name("openfdd-live-writer".into())
            .spawn(move || writer_loop(rx))
            .expect("openfdd live writer thread");
        Self {
            tx,
            thread: Some(thread),
        }
    }

    fn enqueue(&self, command: WriterCommand) -> Result<()> {
        match self.tx.try_send(command) {
            Ok(()) => Ok(()),
            Err(std::sync::mpsc::TrySendError::Full(_)) => {
                bail!("live historian writer queue full (OPENFDD_LIVE_WRITER_QUEUE_CAP)")
            }
            Err(std::sync::mpsc::TrySendError::Disconnected(_)) => {
                bail!("live historian writer stopped")
            }
        }
    }

    /// Reserve queue bytes from `&envelope`, then clone into the bounded channel.
    fn enqueue_ingest(
        &self,
        scope: String,
        envelope: &TelemetryEnvelope,
        reply: tokio::sync::oneshot::Sender<Result<LiveHistorianIngest>>,
    ) -> Result<()> {
        let queued_bytes = estimate_envelope_queue_bytes(envelope);
        try_reserve_queue_bytes(queued_bytes)?;
        let command = WriterCommand::Ingest {
            scope,
            envelope: envelope.clone(),
            queued_bytes,
            reply,
        };
        match self.tx.try_send(command) {
            Ok(()) => Ok(()),
            Err(std::sync::mpsc::TrySendError::Full(cmd)) => {
                if let WriterCommand::Ingest { queued_bytes, .. } = cmd {
                    release_queue_bytes(queued_bytes);
                }
                bail!("live historian writer queue full (OPENFDD_LIVE_WRITER_QUEUE_CAP)")
            }
            Err(std::sync::mpsc::TrySendError::Disconnected(cmd)) => {
                if let WriterCommand::Ingest { queued_bytes, .. } = cmd {
                    release_queue_bytes(queued_bytes);
                }
                bail!("live historian writer stopped")
            }
        }
    }

    pub async fn ingest(
        &self,
        scope: &str,
        envelope: &TelemetryEnvelope,
    ) -> Result<LiveHistorianIngest> {
        let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
        self.enqueue_ingest(scope.to_string(), envelope, reply_tx)?;
        reply_rx
            .await
            .map_err(|_| anyhow!("live historian writer dropped the reply"))?
    }

    pub async fn flush(&self, graceful: bool) -> Result<LiveHistorianIngest> {
        let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
        self.enqueue(WriterCommand::Flush {
            graceful,
            reply: reply_tx,
        })?;
        reply_rx
            .await
            .map_err(|_| anyhow!("live historian writer dropped the reply"))?
    }
}

impl Drop for LiveWriter {
    fn drop(&mut self) {
        // Shutdown may block briefly so the worker can drain; try_send would
        // drop Shutdown under load and leave the thread running.
        let _ = self.tx.send(WriterCommand::Shutdown);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

fn reply_timescale_unavailable(command: WriterCommand) {
    let err = anyhow!("timescale_unavailable");
    match command {
        WriterCommand::Shutdown => {}
        WriterCommand::Ingest {
            queued_bytes,
            reply,
            ..
        } => {
            release_queue_bytes(queued_bytes);
            let _ = reply.send(Err(err));
        }
        WriterCommand::Flush { reply, .. } => {
            let _ = reply.send(Err(err));
        }
    }
}

fn timescale_writer_loop(rx: std::sync::mpsc::Receiver<WriterCommand>) {
    let mut gate = crate::timescale_historian::TimescaleConnectGate::new();
    while let Ok(command) = rx.recv() {
        if matches!(command, WriterCommand::Shutdown) {
            break;
        }
        if !gate.is_connected() {
            match crate::timescale_historian::TimescaleLiveHistorian::connect() {
                Ok(historian) => gate.insert(historian),
                Err(_) => {
                    warn!(
                        "Timescale live historian connect failed; will retry on the next command"
                    );
                    reply_timescale_unavailable(command);
                    continue;
                }
            }
        }
        let drop_conn =
            {
                let Some(historian) = gate.get_mut() else {
                    reply_timescale_unavailable(command);
                    continue;
                };
                match command {
                    WriterCommand::Shutdown => break,
                    WriterCommand::Ingest {
                        scope,
                        envelope,
                        queued_bytes,
                        reply,
                    } => {
                        let result = historian.ingest_envelope(&scope, &envelope);
                        let drop_conn = result.as_ref().err().is_some_and(
                            crate::timescale_historian::historian_error_drops_connection,
                        );
                        release_queue_bytes(queued_bytes);
                        let _ = reply.send(result);
                        drop_conn
                    }
                    WriterCommand::Flush { graceful, reply } => {
                        let result = historian.flush_all(graceful);
                        let drop_conn = result.as_ref().err().is_some_and(
                            crate::timescale_historian::historian_error_drops_connection,
                        );
                        let _ = reply.send(result);
                        drop_conn
                    }
                }
            };
        if drop_conn {
            gate.disconnect();
        }
    }
}

fn writer_loop(rx: std::sync::mpsc::Receiver<WriterCommand>) {
    if crate::timescale_historian::historian_is_timescale() {
        timescale_writer_loop(rx);
        return;
    }
    warn!("Timescale historian is not configured; set OPENFDD_DATABASE_URL");
    while let Ok(command) = rx.recv() {
        match command {
            WriterCommand::Shutdown => break,
            WriterCommand::Ingest {
                queued_bytes,
                reply,
                ..
            } => {
                release_queue_bytes(queued_bytes);
                let _ = reply.send(Err(anyhow!(
                    "Timescale historian is not configured; set OPENFDD_DATABASE_URL"
                )));
            }
            WriterCommand::Flush { reply, .. } => {
                let _ = reply.send(Err(anyhow!(
                    "Timescale historian is not configured; set OPENFDD_DATABASE_URL"
                )));
            }
        }
    }
}
