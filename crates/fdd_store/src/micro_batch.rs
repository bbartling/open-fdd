//! Bounded in-memory micro-batching for canonical Parquet historian writes.
//!
//! This module is deliberately transport-agnostic. Fieldbus/MQTT integration is
//! a later cutover phase; callers provide already-normalized Arrow batches plus
//! trusted building/equipment identity. Pending rows flush when either the row
//! threshold or elapsed-time threshold is reached, and `shutdown_flush` drains
//! every remaining batch before a clean process exit.

use std::collections::BTreeMap;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Result};
use arrow::compute::concat_batches;
use arrow::record_batch::RecordBatch;
use serde::Serialize;

use crate::parquet_parts::{ParquetPart, ParquetPartWriter};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct HistorianBatchKey {
    pub building_id: String,
    pub equipment_id: String,
}

impl HistorianBatchKey {
    pub fn new(building_id: impl Into<String>, equipment_id: impl Into<String>) -> Self {
        Self {
            building_id: building_id.into(),
            equipment_id: equipment_id.into(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FlushReason {
    RowThreshold,
    TimeThreshold,
    Shutdown,
}

#[derive(Debug, Clone, Serialize)]
pub struct MicroBatchFlush {
    pub building_id: String,
    pub equipment_id: String,
    pub rows: usize,
    pub reason: FlushReason,
    pub parts: Vec<ParquetPart>,
}

#[derive(Debug, Clone)]
struct PendingBatch {
    batches: Vec<RecordBatch>,
    rows: usize,
    first_buffered_at: Instant,
}

/// In-memory bounded accumulator that flushes complete Arrow batches into
/// immutable Parquet parts.
///
/// The accumulator does not spawn timers or background tasks. The owning runtime
/// calls `flush_due()` from its existing interval loop and `shutdown_flush()`
/// during graceful shutdown. This keeps lifecycle ownership explicit and avoids
/// hidden tasks inside the storage crate.
#[derive(Debug, Clone)]
pub struct MicroBatchHistorian {
    writer: ParquetPartWriter,
    flush_rows: usize,
    flush_after: Duration,
    pending: BTreeMap<HistorianBatchKey, PendingBatch>,
}

impl MicroBatchHistorian {
    pub fn new(
        writer: ParquetPartWriter,
        flush_rows: usize,
        flush_after: Duration,
    ) -> Result<Self> {
        if flush_rows == 0 {
            bail!("micro-batch flush_rows must be greater than zero");
        }
        if flush_after.is_zero() {
            bail!("micro-batch flush_after must be greater than zero");
        }
        Ok(Self {
            writer,
            flush_rows,
            flush_after,
            pending: BTreeMap::new(),
        })
    }

    pub fn writer(&self) -> &ParquetPartWriter {
        &self.writer
    }

    pub fn pending_rows(&self) -> usize {
        self.pending.values().map(|pending| pending.rows).sum()
    }

    pub fn pending_keys(&self) -> usize {
        self.pending.len()
    }

    pub fn push(
        &mut self,
        building_id: impl Into<String>,
        equipment_id: impl Into<String>,
        batch: RecordBatch,
    ) -> Result<Vec<MicroBatchFlush>> {
        self.push_at(building_id, equipment_id, batch, Instant::now())
    }

    /// Deterministic variant used by runtimes/tests that already own a clock.
    pub fn push_at(
        &mut self,
        building_id: impl Into<String>,
        equipment_id: impl Into<String>,
        batch: RecordBatch,
        now: Instant,
    ) -> Result<Vec<MicroBatchFlush>> {
        if batch.num_rows() == 0 {
            return Ok(Vec::new());
        }

        let key = HistorianBatchKey::new(building_id, equipment_id);
        if let Some(existing) = self.pending.get(&key) {
            if existing
                .batches
                .first()
                .is_some_and(|first| first.schema() != batch.schema())
            {
                bail!(
                    "micro-batch schema changed before flush for {}/{}",
                    key.building_id,
                    key.equipment_id
                );
            }
        }

        let rows = batch.num_rows();
        let pending = self
            .pending
            .entry(key.clone())
            .or_insert_with(|| PendingBatch {
                batches: Vec::new(),
                rows: 0,
                first_buffered_at: now,
            });
        pending.rows += rows;
        pending.batches.push(batch);

        if pending.rows >= self.flush_rows {
            return Ok(vec![self.flush_key(&key, FlushReason::RowThreshold)?]);
        }
        Ok(Vec::new())
    }

    /// Flush keys whose oldest pending batch has reached the configured time
    /// threshold. A failed write leaves that key buffered for an explicit retry.
    pub fn flush_due(&mut self) -> Result<Vec<MicroBatchFlush>> {
        self.flush_due_at(Instant::now())
    }

    pub fn flush_due_at(&mut self, now: Instant) -> Result<Vec<MicroBatchFlush>> {
        let due: Vec<HistorianBatchKey> = self
            .pending
            .iter()
            .filter_map(|(key, pending)| {
                now.checked_duration_since(pending.first_buffered_at)
                    .filter(|elapsed| *elapsed >= self.flush_after)
                    .map(|_| key.clone())
            })
            .collect();

        let mut reports = Vec::with_capacity(due.len());
        for key in due {
            reports.push(self.flush_key(&key, FlushReason::TimeThreshold)?);
        }
        Ok(reports)
    }

    /// Drain every pending key. The owning service should call this from its
    /// graceful-shutdown path before terminating the process.
    pub fn shutdown_flush(&mut self) -> Result<Vec<MicroBatchFlush>> {
        let keys: Vec<HistorianBatchKey> = self.pending.keys().cloned().collect();
        let mut reports = Vec::with_capacity(keys.len());
        for key in keys {
            reports.push(self.flush_key(&key, FlushReason::Shutdown)?);
        }
        Ok(reports)
    }

    fn flush_key(
        &mut self,
        key: &HistorianBatchKey,
        reason: FlushReason,
    ) -> Result<MicroBatchFlush> {
        let pending = self
            .pending
            .get(key)
            .ok_or_else(|| anyhow!("micro-batch key is not pending"))?;
        let rows = pending.rows;
        let combined = match pending.batches.as_slice() {
            [only] => only.clone(),
            batches => {
                let schema = batches
                    .first()
                    .ok_or_else(|| anyhow!("pending micro-batch has no record batches"))?
                    .schema();
                concat_batches(&schema, batches)?
            }
        };

        let parts =
            self.writer
                .write_history_batch(&key.building_id, &key.equipment_id, &combined)?;

        // Remove only after every immutable part was successfully published.
        self.pending.remove(key);
        Ok(MicroBatchFlush {
            building_id: key.building_id.clone(),
            equipment_id: key.equipment_id.clone(),
            rows,
            reason,
            parts,
        })
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow::array::{Float64Array, StringArray, TimestampNanosecondArray};
    use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
    use arrow::record_batch::RecordBatch;
    use chrono::{DateTime, Utc};
    use tempfile::TempDir;

    use super::*;
    use crate::historian::LocalStorage;

    fn batch(times: &[&str]) -> RecordBatch {
        batch_for_equipment(times, "AHU_1")
    }

    fn batch_for_equipment(times: &[&str], equipment_id: &str) -> RecordBatch {
        let timestamps: Vec<i64> = times
            .iter()
            .map(|raw| {
                DateTime::parse_from_rfc3339(raw)
                    .unwrap()
                    .with_timezone(&Utc)
                    .timestamp_nanos_opt()
                    .unwrap()
            })
            .collect();
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                DataType::Timestamp(TimeUnit::Nanosecond, None),
                false,
            ),
            Field::new("sat", DataType::Float64, true),
            Field::new("equipment_id", DataType::Utf8, false),
        ]));
        RecordBatch::try_new(
            schema,
            vec![
                Arc::new(TimestampNanosecondArray::from(timestamps)),
                Arc::new(Float64Array::from(vec![Some(55.0); times.len()])),
                Arc::new(StringArray::from(vec![equipment_id; times.len()])),
            ],
        )
        .unwrap()
    }

    fn historian(tmp: &TempDir, flush_rows: usize, flush_after: Duration) -> MicroBatchHistorian {
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        MicroBatchHistorian::new(writer, flush_rows, flush_after).unwrap()
    }

    #[test]
    fn row_threshold_flushes_and_clears_pending_rows() {
        let tmp = TempDir::new().unwrap();
        let start = Instant::now();
        let mut historian = historian(&tmp, 2, Duration::from_secs(60));
        assert!(historian
            .push_at(
                "BUILDING_100",
                "AHU_1",
                batch(&["2026-08-20T12:00:00Z"]),
                start,
            )
            .unwrap()
            .is_empty());
        let flushed = historian
            .push_at(
                "BUILDING_100",
                "AHU_1",
                batch(&["2026-08-20T12:05:00Z"]),
                start + Duration::from_secs(1),
            )
            .unwrap();
        assert_eq!(flushed.len(), 1);
        assert_eq!(flushed[0].reason, FlushReason::RowThreshold);
        assert_eq!(flushed[0].rows, 2);
        assert_eq!(historian.pending_rows(), 0);
        assert_eq!(flushed[0].parts.len(), 1);
    }

    #[test]
    fn time_threshold_flushes_small_batch() {
        let tmp = TempDir::new().unwrap();
        let start = Instant::now();
        let mut historian = historian(&tmp, 100, Duration::from_secs(30));
        historian
            .push_at(
                "BUILDING_100",
                "AHU_1",
                batch(&["2026-08-20T12:00:00Z"]),
                start,
            )
            .unwrap();
        assert!(historian
            .flush_due_at(start + Duration::from_secs(29))
            .unwrap()
            .is_empty());
        let flushed = historian
            .flush_due_at(start + Duration::from_secs(30))
            .unwrap();
        assert_eq!(flushed.len(), 1);
        assert_eq!(flushed[0].reason, FlushReason::TimeThreshold);
        assert_eq!(historian.pending_keys(), 0);
    }

    #[test]
    fn shutdown_flush_drains_all_keys() {
        let tmp = TempDir::new().unwrap();
        let mut historian = historian(&tmp, 100, Duration::from_secs(60));
        historian
            .push("BUILDING_100", "AHU_1", batch(&["2026-08-20T12:00:00Z"]))
            .unwrap();
        historian
            .push(
                "BUILDING_100",
                "AHU_2",
                batch_for_equipment(&["2026-08-20T12:00:00Z"], "AHU_2"),
            )
            .unwrap();
        let flushed = historian.shutdown_flush().unwrap();
        assert_eq!(flushed.len(), 2);
        assert!(flushed
            .iter()
            .all(|report| report.reason == FlushReason::Shutdown));
        assert_eq!(historian.pending_rows(), 0);
    }

    #[test]
    fn schema_change_is_rejected_without_losing_pending_rows() {
        let tmp = TempDir::new().unwrap();
        let mut historian = historian(&tmp, 100, Duration::from_secs(60));
        historian
            .push("BUILDING_100", "AHU_1", batch(&["2026-08-20T12:00:00Z"]))
            .unwrap();

        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                DataType::Timestamp(TimeUnit::Nanosecond, None),
                false,
            ),
            Field::new("different_role", DataType::Float64, true),
        ]));
        let changed = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(TimestampNanosecondArray::from(vec![0_i64])),
                Arc::new(Float64Array::from(vec![Some(1.0)])),
            ],
        )
        .unwrap();
        assert!(historian.push("BUILDING_100", "AHU_1", changed).is_err());
        assert_eq!(historian.pending_rows(), 1);
    }

    #[test]
    fn failed_flush_keeps_rows_buffered_for_retry() {
        let tmp = TempDir::new().unwrap();
        let mut historian = historian(&tmp, 1, Duration::from_secs(60));
        assert!(historian
            .push(
                "../unsafe-building",
                "AHU_1",
                batch(&["2026-08-20T12:00:00Z"]),
            )
            .is_err());
        assert_eq!(historian.pending_rows(), 1);
        assert_eq!(historian.pending_keys(), 1);
    }
}
