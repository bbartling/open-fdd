//! Bounded in-memory micro-batching for canonical Parquet historian writes.
//!
//! This module is deliberately transport-agnostic. Fieldbus/MQTT integration is
//! a later cutover phase; callers provide already-normalized Arrow batches plus
//! trusted building/equipment identity. Pending rows flush when either the row
//! threshold or elapsed-time threshold is reached, and `shutdown_flush` drains
//! every remaining batch before a clean process exit.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Result};
use arrow::compute::concat_batches;
use arrow::record_batch::RecordBatch;
use serde::Serialize;

use crate::parquet_parts::{ParquetPart, ParquetPartWriter};

/// Soft-OPEN 371 T1e: aggregate pending micro-batch bytes across every
/// LiveHistorian / scope in the process (not only per-instance 32 MiB caps).
static PROCESS_PENDING_BYTES: AtomicUsize = AtomicUsize::new(0);

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

/// Identity of one input batch that was included in a successful publish.
///
/// The token is whatever the caller attached at `push`. A flush report lists
/// only the batches that were encoded into the immutable part, so durability
/// is not reconstructed from a side queue after the fact.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BatchProvenance {
    pub rows: usize,
    pub token: Option<u64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct MicroBatchFlush {
    pub building_id: String,
    pub equipment_id: String,
    pub rows: usize,
    pub reason: FlushReason,
    pub parts: Vec<ParquetPart>,
    #[serde(skip)]
    pub provenance: Vec<BatchProvenance>,
}

#[derive(Debug, Clone)]
struct PendingInput {
    batch: RecordBatch,
    token: Option<u64>,
}

#[derive(Debug, Clone)]
struct PendingBatch {
    inputs: Vec<PendingInput>,
    rows: usize,
    bytes: usize,
    first_buffered_at: Instant,
}

/// In-memory bounded accumulator that flushes complete Arrow batches into
/// immutable Parquet parts.
///
/// The accumulator does not spawn timers or background tasks. The owning runtime
/// calls `flush_due()` from its existing interval loop and `shutdown_flush()`
/// during graceful shutdown. This keeps lifecycle ownership explicit and avoids
/// hidden tasks inside the storage crate.
///
/// Soft-OPEN 370 T1e / M70-05: `max_pending_bytes` is a **per-instance** resident
/// budget across every equipment key on that historian — not only per-key row
/// thresholds. Soft-OPEN 371 T1e adds a separate process-wide aggregate
/// (`OPENFDD_MICRO_BATCH_PROCESS_MAX_PENDING_BYTES`, default 128 MiB).
#[derive(Debug)]
pub struct MicroBatchHistorian {
    writer: ParquetPartWriter,
    flush_rows: usize,
    flush_after: Duration,
    max_pending_bytes: usize,
    pending: BTreeMap<HistorianBatchKey, PendingBatch>,
    pending_bytes: usize,
}

impl MicroBatchHistorian {
    pub fn new(
        writer: ParquetPartWriter,
        flush_rows: usize,
        flush_after: Duration,
    ) -> Result<Self> {
        Self::new_with_byte_budget(writer, flush_rows, flush_after, default_max_pending_bytes())
    }

    pub fn new_with_byte_budget(
        writer: ParquetPartWriter,
        flush_rows: usize,
        flush_after: Duration,
        max_pending_bytes: usize,
    ) -> Result<Self> {
        if flush_rows == 0 {
            bail!("micro-batch flush_rows must be greater than zero");
        }
        if flush_after.is_zero() {
            bail!("micro-batch flush_after must be greater than zero");
        }
        if max_pending_bytes == 0 {
            bail!("micro-batch max_pending_bytes must be greater than zero");
        }
        Ok(Self {
            writer,
            flush_rows,
            flush_after,
            max_pending_bytes,
            pending: BTreeMap::new(),
            pending_bytes: 0,
        })
    }

    pub fn writer(&self) -> &ParquetPartWriter {
        &self.writer
    }

    pub fn pending_rows(&self) -> usize {
        self.pending.values().map(|pending| pending.rows).sum()
    }

    pub fn pending_bytes(&self) -> usize {
        self.pending_bytes
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
        self.push_with_token(building_id, equipment_id, batch, None)
    }

    /// Buffer one batch and attach the caller token returned if this push publishes.
    pub fn push_with_token(
        &mut self,
        building_id: impl Into<String>,
        equipment_id: impl Into<String>,
        batch: RecordBatch,
        token: Option<u64>,
    ) -> Result<Vec<MicroBatchFlush>> {
        self.push_at_with_token(building_id, equipment_id, batch, Instant::now(), token)
    }

    /// Deterministic variant used by runtimes/tests that already own a clock.
    pub fn push_at(
        &mut self,
        building_id: impl Into<String>,
        equipment_id: impl Into<String>,
        batch: RecordBatch,
        now: Instant,
    ) -> Result<Vec<MicroBatchFlush>> {
        self.push_at_with_token(building_id, equipment_id, batch, now, None)
    }

    pub fn push_at_with_token(
        &mut self,
        building_id: impl Into<String>,
        equipment_id: impl Into<String>,
        batch: RecordBatch,
        now: Instant,
        token: Option<u64>,
    ) -> Result<Vec<MicroBatchFlush>> {
        if batch.num_rows() == 0 {
            return Ok(Vec::new());
        }

        let key = HistorianBatchKey::new(building_id, equipment_id);
        if let Some(existing) = self.pending.get(&key) {
            if existing
                .inputs
                .first()
                .is_some_and(|first| first.batch.schema() != batch.schema())
            {
                bail!(
                    "micro-batch schema changed before flush for {}/{}",
                    key.building_id,
                    key.equipment_id
                );
            }
        }

        let rows = batch.num_rows();
        let batch_bytes = batch.get_array_memory_size().max(1);
        // Soft-OPEN 370 T1e: refuse before buffering when the instance resident
        // budget cannot accept this batch (do not erase other pending keys).
        if self.pending_bytes.saturating_add(batch_bytes) > self.max_pending_bytes {
            // Prefer flushing this key if it already has rows; otherwise fail closed.
            if self.pending.get(&key).is_some_and(|p| p.rows > 0) {
                let mut reports = vec![self.flush_key(&key, FlushReason::RowThreshold)?];
                // Retry push after freeing this key's resident bytes.
                reports.extend(self.push_at_with_token(
                    key.building_id.clone(),
                    key.equipment_id.clone(),
                    batch,
                    now,
                    token,
                )?);
                return Ok(reports);
            }
            bail!(
                "micro-batch pending byte budget exceeded ({} + {} > {})",
                self.pending_bytes,
                batch_bytes,
                self.max_pending_bytes
            );
        }
        // Soft-OPEN 371 T1e: also charge the process-wide aggregate across scopes.
        try_reserve_process_bytes(batch_bytes)?;

        let pending = self
            .pending
            .entry(key.clone())
            .or_insert_with(|| PendingBatch {
                inputs: Vec::new(),
                rows: 0,
                bytes: 0,
                first_buffered_at: now,
            });
        pending.rows += rows;
        pending.bytes += batch_bytes;
        self.pending_bytes += batch_bytes;
        pending.inputs.push(PendingInput { batch, token });

        if pending.rows >= self.flush_rows || self.pending_bytes >= self.max_pending_bytes {
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
        let provenance: Vec<BatchProvenance> = pending
            .inputs
            .iter()
            .map(|input| BatchProvenance {
                rows: input.batch.num_rows(),
                token: input.token,
            })
            .collect();
        let combined = match pending.inputs.as_slice() {
            [only] => only.batch.clone(),
            inputs => {
                let schema = inputs
                    .first()
                    .ok_or_else(|| anyhow!("pending micro-batch has no record batches"))?
                    .batch
                    .schema();
                let batches: Vec<RecordBatch> =
                    inputs.iter().map(|input| input.batch.clone()).collect();
                concat_batches(&schema, &batches)?
            }
        };

        let parts =
            self.writer
                .write_history_batch(&key.building_id, &key.equipment_id, &combined)?;

        // Remove only after every immutable part was successfully published.
        // Provenance is the input list that was encoded, not a later guess.
        if let Some(removed) = self.pending.remove(key) {
            self.pending_bytes = self.pending_bytes.saturating_sub(removed.bytes);
            release_process_bytes(removed.bytes);
        }
        Ok(MicroBatchFlush {
            building_id: key.building_id.clone(),
            equipment_id: key.equipment_id.clone(),
            rows,
            reason,
            parts,
            provenance,
        })
    }
}

impl Drop for MicroBatchHistorian {
    fn drop(&mut self) {
        // Release process-wide accounting when the instance is dropped without a
        // successful flush (failed publish / test teardown). Resident Arrow is
        // freed with `pending`; do not leave the aggregate charged.
        if self.pending_bytes > 0 {
            release_process_bytes(self.pending_bytes);
            self.pending_bytes = 0;
            self.pending.clear();
        }
    }
}

fn default_max_pending_bytes() -> usize {
    std::env::var("OPENFDD_MICRO_BATCH_MAX_PENDING_BYTES")
        .ok()
        .and_then(|raw| raw.parse().ok())
        .filter(|n| *n > 0)
        .unwrap_or(32 * 1024 * 1024)
}

fn process_max_pending_bytes() -> usize {
    std::env::var("OPENFDD_MICRO_BATCH_PROCESS_MAX_PENDING_BYTES")
        .ok()
        .and_then(|raw| raw.parse().ok())
        .filter(|n| *n > 0)
        .unwrap_or(128 * 1024 * 1024)
}

/// Current process-wide micro-batch resident bytes (all scopes).
pub fn process_pending_bytes() -> usize {
    PROCESS_PENDING_BYTES.load(Ordering::Acquire)
}

fn try_reserve_process_bytes(additional: usize) -> Result<()> {
    let limit = process_max_pending_bytes();
    let mut cur = PROCESS_PENDING_BYTES.load(Ordering::Acquire);
    loop {
        let next = cur
            .checked_add(additional)
            .ok_or_else(|| anyhow!("micro-batch process pending byte overflow"))?;
        if next > limit {
            bail!(
                "micro-batch process pending byte budget exceeded ({cur} + {additional} > {limit}; OPENFDD_MICRO_BATCH_PROCESS_MAX_PENDING_BYTES)"
            );
        }
        match PROCESS_PENDING_BYTES.compare_exchange(cur, next, Ordering::AcqRel, Ordering::Acquire)
        {
            Ok(_) => return Ok(()),
            Err(observed) => cur = observed,
        }
    }
}

fn release_process_bytes(bytes: usize) {
    let _ = PROCESS_PENDING_BYTES.try_update(Ordering::AcqRel, Ordering::Acquire, |cur| {
        Some(cur.saturating_sub(bytes))
    });
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use arrow::array::{Float64Array, StringArray, TimestampNanosecondArray};
    use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
    use arrow::record_batch::RecordBatch;
    use chrono::{DateTime, Utc};
    use tempfile::TempDir;

    use super::*;
    use crate::historian::LocalStorage;

    /// Process-wide pending-byte counter is shared; serialize these unit tests.
    static PROCESS_BYTES_TEST_LOCK: Mutex<()> = Mutex::new(());

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
    fn global_byte_budget_fails_closed_without_erasing_pending() {
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        let mut historian =
            MicroBatchHistorian::new_with_byte_budget(writer, 10_000, Duration::from_secs(60), 1)
                .unwrap();
        let start = Instant::now();
        let err = historian
            .push_at(
                "SITE_A",
                "AHU_A",
                batch_for_equipment(&["2026-08-20T12:00:00Z"], "AHU_A"),
                start,
            )
            .unwrap_err()
            .to_string();
        assert!(
            err.contains("pending byte budget exceeded"),
            "unexpected error: {err}"
        );
        assert_eq!(historian.pending_rows(), 0);
        assert_eq!(historian.pending_bytes(), 0);
    }

    #[test]
    fn row_threshold_flushes_and_clears_pending_rows() {
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
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
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
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
    fn time_and_row_flushes_return_only_the_published_batch_tokens() {
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let tmp = TempDir::new().unwrap();
        let start = Instant::now();
        let mut timed_historian = historian(&tmp, 2, Duration::from_secs(30));
        assert!(timed_historian
            .push_at_with_token(
                "building-local",
                "equipment-a",
                batch_for_equipment(&["2026-08-20T12:00:00Z"], "equipment-a"),
                start,
                Some(11),
            )
            .unwrap()
            .is_empty());
        assert!(timed_historian
            .push_at_with_token(
                "building-local",
                "equipment-b",
                batch_for_equipment(&["2026-08-20T12:00:00Z"], "equipment-b"),
                start,
                Some(22),
            )
            .unwrap()
            .is_empty());
        let timed = timed_historian
            .flush_due_at(start + Duration::from_secs(30))
            .unwrap();
        let mut tokens: Vec<_> = timed
            .iter()
            .flat_map(|flush| flush.provenance.iter().map(|item| (item.token, item.rows)))
            .collect();
        tokens.sort();
        assert_eq!(tokens, vec![(Some(11), 1), (Some(22), 1)]);
        assert!(timed.iter().all(|flush| flush
            .provenance
            .iter()
            .map(|item| item.rows)
            .sum::<usize>()
            == flush.rows));

        let mut row_historian = historian(&tmp, 2, Duration::from_secs(60));
        row_historian
            .push_at_with_token(
                "building-local",
                "equipment-a",
                batch_for_equipment(&["2026-08-20T12:00:00Z"], "equipment-a"),
                start,
                Some(1),
            )
            .unwrap();
        let flushed = row_historian
            .push_at_with_token(
                "building-local",
                "equipment-a",
                batch_for_equipment(&["2026-08-20T12:05:00Z"], "equipment-a"),
                start,
                Some(2),
            )
            .unwrap();
        assert_eq!(
            flushed[0]
                .provenance
                .iter()
                .map(|item| item.token)
                .collect::<Vec<_>>(),
            vec![Some(1), Some(2)]
        );
        assert!(row_historian
            .push_at_with_token(
                "building-local",
                "equipment-b",
                batch_for_equipment(&["2026-08-20T12:00:00Z"], "equipment-b"),
                start,
                Some(3),
            )
            .unwrap()
            .is_empty());
        assert_eq!(row_historian.pending_rows(), 1);
    }

    #[test]
    fn shutdown_flush_drains_all_keys() {
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
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
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
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
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
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

    #[test]
    fn process_pending_bytes_charge_and_release_on_flush() {
        let _guard = PROCESS_BYTES_TEST_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let tmp = TempDir::new().unwrap();
        let start = Instant::now();
        let before = process_pending_bytes();
        let mut historian = historian(&tmp, 100, Duration::from_secs(60));
        historian
            .push_at(
                "BUILDING_100",
                "AHU_1",
                batch(&["2026-08-20T12:00:00Z"]),
                start,
            )
            .unwrap();
        let charged = process_pending_bytes();
        assert!(
            charged > before,
            "process pending should rise after push (before={before} after={charged})"
        );
        let my_bytes = charged - before;
        let flushed = historian
            .flush_due_at(start + Duration::from_secs(120))
            .unwrap();
        assert_eq!(flushed.len(), 1);
        assert_eq!(historian.pending_bytes(), 0);
        assert_eq!(process_pending_bytes(), charged - my_bytes);
    }
}
