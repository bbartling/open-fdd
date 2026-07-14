//! Disk-backed outbound telemetry spool for offline edges.

use std::path::{Path, PathBuf};

use openfdd_contracts::TelemetryEnvelope;
use serde::{Deserialize, Serialize};
use tokio::fs;
use tracing::{info, warn};

#[derive(Debug, Clone)]
pub struct SpoolConfig {
    pub dir: PathBuf,
    pub max_records: usize,
}

impl SpoolConfig {
    pub fn new(dir: impl Into<PathBuf>) -> Self {
        Self {
            dir: dir.into(),
            max_records: 50_000,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpoolRecord {
    pub seq: u64,
    pub topic: String,
    pub envelope: TelemetryEnvelope,
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
        Ok(Self { cfg, next_seq })
    }

    pub fn dir(&self) -> &Path {
        &self.cfg.dir
    }

    pub async fn enqueue(
        &mut self,
        topic: &str,
        envelope: TelemetryEnvelope,
    ) -> anyhow::Result<u64> {
        let seq = self.next_seq;
        self.next_seq += 1;
        let rec = SpoolRecord {
            seq,
            topic: topic.to_string(),
            envelope,
        };
        let path = self.cfg.dir.join(format!("{seq:020}.json"));
        let body = serde_json::to_vec_pretty(&rec)?;
        fs::write(&path, body).await?;
        self.trim().await?;
        Ok(seq)
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

    async fn trim(&self) -> anyhow::Result<()> {
        let pending = self.list_pending().await?;
        if pending.len() <= self.cfg.max_records {
            return Ok(());
        }
        let drop_n = pending.len() - self.cfg.max_records;
        info!(drop_n, "trimming oldest spool records");
        for rec in pending.into_iter().take(drop_n) {
            self.ack(rec.seq).await?;
        }
        Ok(())
    }
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
}
