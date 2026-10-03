//! Disk-backed outbound telemetry spool for offline edges.

use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use openfdd_contracts::TelemetryEnvelope;
use serde::{Deserialize, Serialize};
use tokio::fs;
use tracing::{info, warn};

#[derive(Debug, Clone)]
pub struct SpoolConfig {
    pub dir: PathBuf,
    pub max_records: usize,
    pub max_quarantine_records: usize,
    pub max_completed_records: usize,
    pub max_retired_records: usize,
}

impl SpoolConfig {
    pub fn new(dir: impl Into<PathBuf>) -> Self {
        Self {
            dir: dir.into(),
            max_records: 50_000,
            max_quarantine_records: 10_000,
            max_completed_records: 1_024,
            max_retired_records: 10_000,
        }
    }

    /// Bound an edge spool for deployments with a deliberately small local
    /// disk. The default remains 50,000 records for the MQTT path.
    pub fn with_max_records(mut self, max_records: usize) -> Self {
        self.max_records = max_records.max(1);
        self
    }

    /// Bound terminal records retained for operator inspection. Quarantine
    /// names include the envelope message id, so a restarted spool cannot
    /// overwrite an earlier terminal record that reused its sequence number.
    pub fn with_max_quarantine_records(mut self, max_records: usize) -> Self {
        self.max_quarantine_records = max_records.max(1);
        self
    }

    /// Bound terminal operation receipts retained for idempotent manual
    /// operations. Retention is ordered by completion age, never UUID.
    pub fn with_max_completed_records(mut self, max_records: usize) -> Self {
        self.max_completed_records = max_records.max(1);
        self
    }

    /// Bound the durable retired-ID ledger. A completed operation is retired
    /// before its payload record is age-trimmed, so an old request ID cannot
    /// silently resurrect and reread Haystack after cache eviction. When the
    /// ledger is full, new terminal operations fail closed until an operator
    /// changes the retention policy; the connector never drops tombstone
    /// knowledge implicitly.
    pub fn with_max_retired_records(mut self, max_records: usize) -> Self {
        self.max_retired_records = max_records.max(1);
        self
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpoolRecord {
    pub seq: u64,
    pub topic: String,
    pub envelope: TelemetryEnvelope,
    /// Optional caller operation identity. MQTT records leave this unset;
    /// resumable manual operations persist their validated request signature
    /// before any upstream or Central call is attempted.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub operation_signature: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SpoolTerminalStatus {
    Committed,
    Terminal,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpoolCompletedRecord {
    pub seq: u64,
    pub topic: String,
    pub envelope: TelemetryEnvelope,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub operation_signature: Option<String>,
    pub status: SpoolTerminalStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    pub completed_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpoolRetiredRecord {
    pub message_id: uuid::Uuid,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub operation_signature: Option<String>,
    pub retired_at: DateTime<Utc>,
    pub reason: String,
}

/// A durable admission reservation for a manual operation that has not yet
/// produced its telemetry envelope. The reservation binds the caller's
/// validated request identity before any upstream read, so a full identity
/// ledger rejects a new operation without first doing work that cannot be
/// retained safely.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpoolOperationReservation {
    pub message_id: uuid::Uuid,
    pub operation_signature: String,
    pub reserved_at: DateTime<Utc>,
}

#[derive(Debug)]
pub struct TelemetrySpool {
    cfg: SpoolConfig,
    next_seq: u64,
}

impl TelemetrySpool {
    pub async fn open(cfg: SpoolConfig) -> anyhow::Result<Self> {
        fs::create_dir_all(&cfg.dir).await?;
        let mut next_seq = 1u64;
        let mut entries = fs::read_dir(&cfg.dir).await?;
        while let Some(e) = entries.next_entry().await? {
            if let Some(n) = parse_seq_name(&e.file_name()) {
                next_seq = next_seq.max(n + 1);
            }
        }
        let spool = Self { cfg, next_seq };
        spool.trim_quarantine().await?;
        spool.trim_completed().await?;
        Ok(spool)
    }

    pub fn dir(&self) -> &Path {
        &self.cfg.dir
    }

    pub async fn enqueue(
        &mut self,
        topic: &str,
        envelope: TelemetryEnvelope,
    ) -> anyhow::Result<u64> {
        self.enqueue_with_signature(topic, envelope, None).await
    }

    pub async fn enqueue_with_signature(
        &mut self,
        topic: &str,
        envelope: TelemetryEnvelope,
        operation_signature: Option<String>,
    ) -> anyhow::Result<u64> {
        let seq = self.next_seq;
        self.next_seq += 1;
        let rec = SpoolRecord {
            seq,
            topic: topic.to_string(),
            envelope,
            operation_signature,
        };
        let path = self.cfg.dir.join(format!("{seq:020}.json"));
        let body = serde_json::to_vec_pretty(&rec)?;
        fs::write(&path, body).await?;
        self.trim().await?;
        Ok(seq)
    }

    /// Move a pending record into the durable completed journal. The record is
    /// retained so a replay can return the exact prior outcome without
    /// rereading its upstream source or presenting a changed payload to
    /// Central.
    pub async fn complete(
        &self,
        seq: u64,
        status: SpoolTerminalStatus,
        reason: Option<&str>,
    ) -> anyhow::Result<()> {
        let path = self.cfg.dir.join(format!("{seq:020}.json"));
        if !path.exists() {
            return Ok(());
        }
        let completed_count = self.list_completed().await?.len();
        let retired_count = self.list_retired().await?.len();
        let pending_count = self
            .list_pending()
            .await?
            .into_iter()
            .filter(|record| record.operation_signature.is_some())
            .count();
        let reservation_count = self.list_reservations().await?.len();
        if completed_count
            .saturating_add(retired_count)
            .saturating_add(pending_count)
            .saturating_add(reservation_count)
            > self.terminal_identity_capacity()
        {
            return Err(anyhow::anyhow!(
                "terminal operation identity capacity exceeded; refusing to complete"
            ));
        }
        if completed_count >= self.cfg.max_completed_records
            && retired_count >= self.cfg.max_retired_records
        {
            return Err(anyhow::anyhow!(
                "terminal operation identity capacity exhausted; refusing to complete"
            ));
        }
        let raw = fs::read(&path).await?;
        let record: SpoolRecord = serde_json::from_slice(&raw)?;
        let completed_dir = self.cfg.dir.join("completed");
        fs::create_dir_all(&completed_dir).await?;
        let completed = SpoolCompletedRecord {
            seq,
            topic: record.topic,
            envelope: record.envelope,
            operation_signature: record.operation_signature,
            status,
            reason: reason.map(str::to_string),
            completed_at: Utc::now(),
        };
        let target =
            completed_dir.join(format!("{seq:020}-{}.json", completed.envelope.message_id));
        fs::write(target, serde_json::to_vec_pretty(&completed)?).await?;
        fs::remove_file(path).await?;
        self.trim_completed().await?;
        Ok(())
    }

    pub async fn list_completed(&self) -> anyhow::Result<Vec<SpoolCompletedRecord>> {
        let completed_dir = self.cfg.dir.join("completed");
        if !completed_dir.exists() {
            return Ok(Vec::new());
        }
        let mut records = Vec::new();
        let mut dir = fs::read_dir(completed_dir).await?;
        while let Some(entry) = dir.next_entry().await? {
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let raw = fs::read(&path).await?;
            match serde_json::from_slice::<SpoolCompletedRecord>(&raw) {
                Ok(record) => records.push(record),
                Err(err) => warn!(?path, %err, "skip corrupt completed spool record"),
            }
        }
        records.sort_by_key(|record| (record.completed_at, record.seq));
        Ok(records)
    }

    pub async fn find_completed(
        &self,
        message_id: uuid::Uuid,
    ) -> anyhow::Result<Option<SpoolCompletedRecord>> {
        Ok(self
            .list_completed()
            .await?
            .into_iter()
            .find(|record| record.envelope.message_id == message_id))
    }

    pub async fn list_retired(&self) -> anyhow::Result<Vec<SpoolRetiredRecord>> {
        let retired_dir = self.cfg.dir.join("retired");
        if !retired_dir.exists() {
            return Ok(Vec::new());
        }
        let mut records = Vec::new();
        let mut dir = fs::read_dir(retired_dir).await?;
        while let Some(entry) = dir.next_entry().await? {
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let raw = fs::read(&path).await?;
            match serde_json::from_slice::<SpoolRetiredRecord>(&raw) {
                Ok(record) => records.push(record),
                Err(err) => warn!(?path, %err, "skip corrupt retired spool record"),
            }
        }
        records.sort_by_key(|record| record.retired_at);
        Ok(records)
    }

    pub async fn find_retired(
        &self,
        message_id: uuid::Uuid,
    ) -> anyhow::Result<Option<SpoolRetiredRecord>> {
        Ok(self
            .list_retired()
            .await?
            .into_iter()
            .find(|record| record.message_id == message_id))
    }

    /// Whether a new manual operation may be admitted without exceeding the
    /// bounded completed-plus-retired identity ledger.
    pub async fn can_accept_new_terminal_operation(&self) -> anyhow::Result<bool> {
        let occupied = self.terminal_identity_count().await?;
        Ok(occupied < self.terminal_identity_capacity())
    }

    /// Reserve one bounded manual-operation identity before reading upstream.
    /// Pending signed spool records, completed receipts, retired tombstones,
    /// and reservations all consume the same durable identity capacity. This
    /// prevents generic pending-record trimming from silently losing a manual
    /// operation that has already been admitted.
    pub async fn reserve_terminal_operation(
        &self,
        message_id: uuid::Uuid,
        operation_signature: &str,
    ) -> anyhow::Result<()> {
        if operation_signature.trim().is_empty() {
            return Err(anyhow::anyhow!(
                "manual operation signature cannot be empty"
            ));
        }
        let pending = self.list_pending().await?;
        if let Some(record) = pending
            .iter()
            .find(|record| record.envelope.message_id == message_id)
        {
            if record.operation_signature.as_deref() == Some(operation_signature) {
                return Ok(());
            }
            return Err(anyhow::anyhow!(
                "request_id is already bound to different parameters"
            ));
        }
        if self
            .list_completed()
            .await?
            .iter()
            .any(|record| record.envelope.message_id == message_id)
            || self
                .list_retired()
                .await?
                .iter()
                .any(|record| record.message_id == message_id)
        {
            return Err(anyhow::anyhow!(
                "request_id already has a terminal operation record"
            ));
        }
        let reservations = self.list_reservations().await?;
        if let Some(reservation) = reservations
            .iter()
            .find(|reservation| reservation.message_id == message_id)
        {
            if reservation.operation_signature == operation_signature {
                return Ok(());
            }
            return Err(anyhow::anyhow!(
                "request_id is already bound to different parameters"
            ));
        }

        let occupied = pending
            .iter()
            .filter(|record| record.operation_signature.is_some())
            .count()
            .saturating_add(self.list_completed().await?.len())
            .saturating_add(self.list_retired().await?.len())
            .saturating_add(reservations.len());
        if occupied >= self.terminal_identity_capacity() {
            return Err(anyhow::anyhow!(
                "manual operation identity ledger is full; no new operation admitted"
            ));
        }

        let reservations_dir = self.cfg.dir.join("reservations");
        fs::create_dir_all(&reservations_dir).await?;
        let path = reservations_dir.join(format!("{message_id}.json"));
        let reservation = SpoolOperationReservation {
            message_id,
            operation_signature: operation_signature.to_string(),
            reserved_at: Utc::now(),
        };
        fs::write(path, serde_json::to_vec_pretty(&reservation)?).await?;
        Ok(())
    }

    /// Consume the admission reservation after the exact envelope is durably
    /// written to the pending spool. Missing reservations are harmless for
    /// legacy callers that already persisted a pending record.
    pub async fn release_terminal_operation(&self, message_id: uuid::Uuid) -> anyhow::Result<()> {
        let path = self
            .cfg
            .dir
            .join("reservations")
            .join(format!("{message_id}.json"));
        if path.exists() {
            fs::remove_file(path).await?;
        }
        Ok(())
    }

    pub async fn list_pending(&self) -> anyhow::Result<Vec<SpoolRecord>> {
        let mut out = Vec::new();
        let mut entries = fs::read_dir(&self.cfg.dir).await?;
        let mut names = Vec::new();
        while let Some(e) = entries.next_entry().await? {
            names.push(e.path());
        }
        names.sort();
        for path in names {
            if path.extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            let raw = fs::read(&path).await?;
            match serde_json::from_slice::<SpoolRecord>(&raw) {
                Ok(r) => out.push(r),
                Err(err) => warn!(?path, %err, "skip corrupt spool record"),
            }
        }
        Ok(out)
    }

    pub async fn ack(&self, seq: u64) -> anyhow::Result<()> {
        let path = self.cfg.dir.join(format!("{seq:020}.json"));
        if path.exists() {
            fs::remove_file(path).await?;
        }
        Ok(())
    }

    /// Move a terminally rejected record out of the retry queue while keeping
    /// the original envelope available for operator inspection. The reason is
    /// supplied by the bounded caller and is deliberately not written into
    /// the telemetry payload. Quarantine names include both the sequence and
    /// immutable envelope id; a restarted spool can therefore reuse a
    /// sequence without replacing an older terminal record.
    pub async fn quarantine(&self, seq: u64, reason: &str) -> anyhow::Result<()> {
        let path = self.cfg.dir.join(format!("{seq:020}.json"));
        if !path.exists() {
            return Ok(());
        }
        let raw = fs::read(&path).await?;
        let record: SpoolRecord = serde_json::from_slice(&raw)?;
        let quarantine_dir = self.cfg.dir.join("quarantine");
        fs::create_dir_all(&quarantine_dir).await?;
        let stem = format!("{seq:020}-{}", record.envelope.message_id);
        let target = next_quarantine_path(&quarantine_dir, &stem).await?;
        fs::rename(path, target).await?;
        self.trim_quarantine().await?;
        info!(seq, reason, "quarantined terminal telemetry spool record");
        Ok(())
    }

    async fn trim(&self) -> anyhow::Result<()> {
        let pending = self.list_pending().await?;
        if pending.len() <= self.cfg.max_records {
            return Ok(());
        }
        let drop_n = pending.len() - self.cfg.max_records;
        let candidates = pending
            .iter()
            .filter(|record| record.operation_signature.is_none())
            .collect::<Vec<_>>();
        if candidates.len() < drop_n {
            return Err(anyhow::anyhow!(
                "spool capacity would evict an admitted manual operation"
            ));
        }
        info!(drop_n, "trimming oldest spool records");
        for rec in candidates.into_iter().take(drop_n) {
            self.ack(rec.seq).await?;
        }
        Ok(())
    }

    async fn list_reservations(&self) -> anyhow::Result<Vec<SpoolOperationReservation>> {
        let reservations_dir = self.cfg.dir.join("reservations");
        if !reservations_dir.exists() {
            return Ok(Vec::new());
        }
        let mut records = Vec::new();
        let mut dir = fs::read_dir(reservations_dir).await?;
        while let Some(entry) = dir.next_entry().await? {
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let raw = fs::read(&path).await?;
            let record: SpoolOperationReservation = serde_json::from_slice(&raw)
                .map_err(|_| anyhow::anyhow!("manual operation reservation is corrupt"))?;
            records.push(record);
        }
        records.sort_by_key(|record| record.reserved_at);
        Ok(records)
    }

    async fn terminal_identity_count(&self) -> anyhow::Result<usize> {
        let pending = self
            .list_pending()
            .await?
            .into_iter()
            .filter(|record| record.operation_signature.is_some())
            .count();
        Ok(pending
            .saturating_add(self.list_completed().await?.len())
            .saturating_add(self.list_retired().await?.len())
            .saturating_add(self.list_reservations().await?.len()))
    }

    fn terminal_identity_capacity(&self) -> usize {
        self.cfg
            .max_completed_records
            .saturating_add(self.cfg.max_retired_records)
    }

    async fn trim_quarantine(&self) -> anyhow::Result<()> {
        let quarantine_dir = self.cfg.dir.join("quarantine");
        if !quarantine_dir.exists() {
            return Ok(());
        }
        let mut entries = Vec::new();
        let mut dir = fs::read_dir(&quarantine_dir).await?;
        while let Some(entry) = dir.next_entry().await? {
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let modified = entry
                .metadata()
                .await
                .and_then(|metadata| metadata.modified())
                .unwrap_or(std::time::UNIX_EPOCH);
            entries.push((modified, path));
        }
        entries.sort();
        let drop_n = entries
            .len()
            .saturating_sub(self.cfg.max_quarantine_records);
        for (_, path) in entries.into_iter().take(drop_n) {
            fs::remove_file(path).await?;
        }
        Ok(())
    }

    async fn trim_completed(&self) -> anyhow::Result<()> {
        let completed_dir = self.cfg.dir.join("completed");
        if !completed_dir.exists() {
            return Ok(());
        }
        let mut entries = Vec::new();
        let mut dir = fs::read_dir(&completed_dir).await?;
        while let Some(entry) = dir.next_entry().await? {
            let path = entry.path();
            if path.extension().and_then(|value| value.to_str()) != Some("json") {
                continue;
            }
            let raw = fs::read(&path).await?;
            if let Ok(record) = serde_json::from_slice::<SpoolCompletedRecord>(&raw) {
                entries.push((record.completed_at, record.seq, path));
            }
        }
        entries.sort_by_key(|(completed_at, seq, _)| (*completed_at, *seq));
        let drop_n = entries.len().saturating_sub(self.cfg.max_completed_records);
        for (_, _, path) in entries.into_iter().take(drop_n) {
            let raw = fs::read(&path).await?;
            let record: SpoolCompletedRecord = serde_json::from_slice(&raw)?;
            let retired_dir = self.cfg.dir.join("retired");
            fs::create_dir_all(&retired_dir).await?;
            if self
                .find_retired(record.envelope.message_id)
                .await?
                .is_none()
            {
                if self.list_retired().await?.len() >= self.cfg.max_retired_records {
                    return Err(anyhow::anyhow!(
                        "retired operation ledger is full; refusing to forget request identity"
                    ));
                }
                let retired = SpoolRetiredRecord {
                    message_id: record.envelope.message_id,
                    operation_signature: record.operation_signature,
                    retired_at: Utc::now(),
                    reason: "manual_operation_id_expired".into(),
                };
                let target =
                    next_quarantine_path(&retired_dir, &retired.message_id.to_string()).await?;
                fs::write(target, serde_json::to_vec_pretty(&retired)?).await?;
            }
            fs::remove_file(path).await?;
        }
        Ok(())
    }
}

async fn next_quarantine_path(dir: &Path, stem: &str) -> anyhow::Result<PathBuf> {
    let first = dir.join(format!("{stem}.json"));
    if !first.exists() {
        return Ok(first);
    }
    for suffix in 1..=1_000usize {
        let candidate = dir.join(format!("{stem}-{suffix}.json"));
        if !candidate.exists() {
            return Ok(candidate);
        }
    }
    Err(anyhow::anyhow!(
        "quarantine filename collision bound exceeded"
    ))
}

fn parse_seq_name(name: &std::ffi::OsString) -> Option<u64> {
    let s = name.to_str()?;
    let stem = s.strip_suffix(".json")?;
    stem.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use openfdd_contracts::{Protocol, Quality, TelemetryEnvelope, TelemetryPoint, ValueKind};

    #[tokio::test]
    async fn enqueue_and_ack() {
        let dir = std::env::temp_dir().join(format!("ofdd-spool-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir).await;
        let mut spool = TelemetrySpool::open(SpoolConfig::new(&dir)).await.unwrap();
        let env = TelemetryEnvelope::new(
            "s",
            "e",
            Protocol::Bacnet,
            1,
            vec![TelemetryPoint {
                id: "p1".into(),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: serde_json::json!(1),
                unit: None,
                quality: Quality::Good,
                observed_at: None,
                tags: Default::default(),
            }],
        );
        let seq = spool
            .enqueue("openfdd/v1/sites/s/edges/e/telemetry/bacnet", env)
            .await
            .unwrap();
        assert_eq!(spool.list_pending().await.unwrap().len(), 1);
        spool.ack(seq).await.unwrap();
        assert!(spool.list_pending().await.unwrap().is_empty());
        let _ = fs::remove_dir_all(&dir).await;
    }

    #[tokio::test]
    async fn quarantine_removes_terminal_record_from_retry_queue() {
        let dir =
            std::env::temp_dir().join(format!("ofdd-spool-quarantine-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir).await;
        let mut spool = TelemetrySpool::open(SpoolConfig::new(&dir)).await.unwrap();
        let env = TelemetryEnvelope::new("s", "e", Protocol::Bacnet, 1, Vec::new());
        let seq = spool.enqueue("local", env).await.unwrap();
        spool.quarantine(seq, "zero_eligible").await.unwrap();
        assert!(spool.list_pending().await.unwrap().is_empty());
        let mut quarantined = fs::read_dir(dir.join("quarantine")).await.unwrap();
        assert!(quarantined.next_entry().await.unwrap().is_some());
        let _ = fs::remove_dir_all(&dir).await;
    }

    #[tokio::test]
    async fn quarantine_restart_retains_seq_reuse_and_bounds_retention() {
        let dir = std::env::temp_dir().join(format!(
            "ofdd-spool-quarantine-restart-{}",
            uuid::Uuid::new_v4()
        ));
        let _ = fs::remove_dir_all(&dir).await;
        let first = TelemetryEnvelope::new("s", "e", Protocol::Bacnet, 1, Vec::new());
        let second = TelemetryEnvelope::new("s", "e", Protocol::Bacnet, 1, Vec::new());
        let first_id = first.message_id;
        let second_id = second.message_id;
        let mut spool = TelemetrySpool::open(SpoolConfig::new(&dir).with_max_quarantine_records(2))
            .await
            .unwrap();
        assert_eq!(spool.enqueue("local", first).await.unwrap(), 1);
        spool.quarantine(1, "zero_eligible").await.unwrap();
        drop(spool);

        let mut restarted =
            TelemetrySpool::open(SpoolConfig::new(&dir).with_max_quarantine_records(2))
                .await
                .unwrap();
        assert_eq!(restarted.enqueue("local", second).await.unwrap(), 1);
        restarted.quarantine(1, "rejected").await.unwrap();
        let mut entries = fs::read_dir(dir.join("quarantine")).await.unwrap();
        let mut names = Vec::new();
        while let Some(entry) = entries.next_entry().await.unwrap() {
            if entry.path().extension().and_then(|value| value.to_str()) == Some("json") {
                names.push(entry.file_name().to_string_lossy().into_owned());
            }
        }
        assert_eq!(names.len(), 2);
        assert!(names
            .iter()
            .any(|name| name.contains(&first_id.to_string())));
        assert!(names
            .iter()
            .any(|name| name.contains(&second_id.to_string())));

        let third = TelemetryEnvelope::new("s", "e", Protocol::Bacnet, 1, Vec::new());
        assert_eq!(restarted.enqueue("local", third).await.unwrap(), 2);
        assert_eq!(restarted.list_pending().await.unwrap()[0].seq, 2);
        let _ = fs::remove_dir_all(&dir).await;
    }

    #[tokio::test]
    async fn completed_manual_records_survive_restart_and_trim_by_age() {
        let dir = std::env::temp_dir().join(format!(
            "ofdd-spool-completed-restart-{}",
            uuid::Uuid::new_v4()
        ));
        let _ = fs::remove_dir_all(&dir).await;
        let config = SpoolConfig::new(&dir).with_max_completed_records(2);
        let mut spool = TelemetrySpool::open(config.clone()).await.unwrap();
        let mut ids = Vec::new();
        for seq in 1..=3 {
            let mut envelope = TelemetryEnvelope::new("s", "e", Protocol::Haystack, seq, vec![]);
            envelope.points.push(TelemetryPoint {
                id: format!("point-{seq}"),
                display_name: None,
                kind: Some(ValueKind::Number),
                value: serde_json::json!(seq),
                unit: None,
                quality: Quality::Good,
                observed_at: None,
                tags: Default::default(),
            });
            ids.push(envelope.message_id);
            let operation_signature = format!("request-{seq}");
            let record = spool
                .enqueue_with_signature("local-manual", envelope, Some(operation_signature))
                .await
                .unwrap();
            spool
                .complete(record, SpoolTerminalStatus::Committed, None)
                .await
                .unwrap();
        }
        let completed = spool.list_completed().await.unwrap();
        assert_eq!(completed.len(), 2);
        assert_eq!(completed[0].seq, 2);
        assert_eq!(completed[1].seq, 3);
        assert!(spool.find_completed(ids[0]).await.unwrap().is_none());
        let retired = spool.find_retired(ids[0]).await.unwrap().unwrap();
        assert_eq!(retired.reason, "manual_operation_id_expired");
        drop(spool);

        let restarted = TelemetrySpool::open(config).await.unwrap();
        let retired = restarted.find_retired(ids[0]).await.unwrap().unwrap();
        assert_eq!(retired.message_id, ids[0]);
        let record = restarted.find_completed(ids[2]).await.unwrap().unwrap();
        assert_eq!(record.operation_signature.as_deref(), Some("request-3"));
        assert_eq!(record.status, SpoolTerminalStatus::Committed);
        let _ = fs::remove_dir_all(&dir).await;
    }

    #[tokio::test]
    async fn manual_identity_admission_reserves_pending_capacity_across_restart() {
        let dir = std::env::temp_dir().join(format!(
            "ofdd-spool-manual-admission-{}",
            uuid::Uuid::new_v4()
        ));
        let _ = fs::remove_dir_all(&dir).await;
        let config = SpoolConfig::new(&dir)
            .with_max_completed_records(1)
            .with_max_retired_records(1)
            .with_max_records(2);
        let mut spool = TelemetrySpool::open(config.clone()).await.unwrap();
        let first = TelemetryEnvelope::new("building", "edge", Protocol::Haystack, 1, vec![]);
        let first_id = first.message_id;
        spool
            .reserve_terminal_operation(first_id, "first-request")
            .await
            .unwrap();
        let first_seq = spool
            .enqueue_with_signature("local-manual", first, Some("first-request".into()))
            .await
            .unwrap();
        spool.release_terminal_operation(first_id).await.unwrap();

        let second = TelemetryEnvelope::new("building", "edge", Protocol::Haystack, 2, vec![]);
        let second_id = second.message_id;
        spool
            .reserve_terminal_operation(second_id, "second-request")
            .await
            .unwrap();
        let second_seq = spool
            .enqueue_with_signature("local-manual", second, Some("second-request".into()))
            .await
            .unwrap();
        spool.release_terminal_operation(second_id).await.unwrap();

        let third = TelemetryEnvelope::new("building", "edge", Protocol::Haystack, 3, vec![]);
        let third_error = spool
            .reserve_terminal_operation(third.message_id, "third-request")
            .await
            .unwrap_err()
            .to_string();
        assert!(third_error.contains("identity ledger is full"));

        spool
            .complete(first_seq, SpoolTerminalStatus::Committed, None)
            .await
            .unwrap();
        assert_eq!(spool.list_pending().await.unwrap().len(), 1);
        drop(spool);

        let restarted = TelemetrySpool::open(config.clone()).await.unwrap();
        assert!(!restarted.can_accept_new_terminal_operation().await.unwrap());
        restarted
            .complete(second_seq, SpoolTerminalStatus::Committed, None)
            .await
            .unwrap();
        drop(restarted);

        let restarted = TelemetrySpool::open(config).await.unwrap();
        assert!(restarted.find_retired(first_id).await.unwrap().is_some());
        assert!(restarted.find_completed(second_id).await.unwrap().is_some());
        let third_error = restarted
            .reserve_terminal_operation(third.message_id, "third-request")
            .await
            .unwrap_err()
            .to_string();
        assert!(third_error.contains("identity ledger is full"));
        let _ = fs::remove_dir_all(&dir).await;
    }
}
