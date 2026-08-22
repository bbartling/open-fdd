//! Immutable canonical Parquet part writer.
//!
//! A RecordBatch may span calendar months. Rows are split by the UTC
//! `timestamp_utc` column and published as complete immutable Parquet objects
//! under the canonical monthly Hive partition. No existing part is rewritten.

use std::collections::BTreeMap;
use std::fmt;
use std::path::Path;
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use arrow::array::{Array, ArrayRef, LargeStringArray, StringArray, UInt32Array};
use arrow::compute::take;
use arrow::datatypes::{DataType, TimeUnit};
use arrow::record_batch::RecordBatch;
use chrono::{DateTime, Datelike, TimeZone, Utc};
use parquet::arrow::ArrowWriter;
use parquet::basic::Compression;
use parquet::file::properties::{EnabledStatistics, WriterProperties};
use serde::Serialize;
use uuid::Uuid;

use crate::historian::{history_partition_path, LocalStorage};

pub const DEFAULT_ROW_GROUP_ROWS: usize = 65_536;

#[derive(Debug, Clone, Serialize)]
pub struct ParquetPart {
    pub relative_path: String,
    pub rows: usize,
    pub bytes: usize,
    pub year: i32,
    pub month: u32,
    pub first_timestamp_utc: String,
    pub last_timestamp_utc: String,
}

/// Backend-neutral publication hook for immutable complete Parquet objects.
///
/// The encoder always builds the full Parquet payload in memory before invoking
/// this hook. Implementations must publish the supplied bytes at the canonical
/// relative path without exposing a partially-written object.
pub trait CompletePartPublisher: fmt::Debug + Send + Sync {
    fn publish_complete(&self, relative_path: &Path, bytes: &[u8]) -> Result<()>;
}

impl CompletePartPublisher for LocalStorage {
    fn publish_complete(&self, relative_path: &Path, bytes: &[u8]) -> Result<()> {
        self.write_atomic(relative_path, bytes)
    }
}

#[derive(Clone)]
pub struct ParquetPartWriter {
    publisher: Arc<dyn CompletePartPublisher>,
    local_storage: Option<LocalStorage>,
    row_group_rows: usize,
}

impl fmt::Debug for ParquetPartWriter {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ParquetPartWriter")
            .field("publisher", &self.publisher)
            .field("local_storage", &self.local_storage)
            .field("row_group_rows", &self.row_group_rows)
            .finish()
    }
}

impl ParquetPartWriter {
    pub fn new(storage: LocalStorage) -> Self {
        Self {
            publisher: Arc::new(storage.clone()),
            local_storage: Some(storage),
            row_group_rows: DEFAULT_ROW_GROUP_ROWS,
        }
    }

    /// Build a canonical writer on a backend that can publish complete immutable
    /// objects. This is used by live S3 ingest while preserving the same H2
    /// partitioning, validation, encoding, and micro-batch primitive.
    pub fn with_publisher(publisher: Arc<dyn CompletePartPublisher>) -> Self {
        Self {
            publisher,
            local_storage: None,
            row_group_rows: DEFAULT_ROW_GROUP_ROWS,
        }
    }

    pub fn with_row_group_rows(mut self, rows: usize) -> Result<Self> {
        if rows == 0 {
            bail!("row group size must be greater than zero");
        }
        self.row_group_rows = rows;
        Ok(self)
    }

    /// Return the local storage backend for local writers.
    ///
    /// Existing H2 callers/tests are local-only. Backend-neutral callers should
    /// not depend on this accessor.
    pub fn storage(&self) -> &LocalStorage {
        self.local_storage
            .as_ref()
            .expect("ParquetPartWriter::storage is only available for local writers")
    }

    /// Write one or more immutable canonical Parquet parts.
    ///
    /// The batch must have a non-null Arrow timestamp column named
    /// `timestamp_utc`. Rows are grouped by UTC year/month even when input is
    /// unsorted. If `building_id` or `equipment_id` columns are present, every
    /// row must agree with the trusted partition identity supplied by the caller.
    /// Those identity columns are omitted from the physical Parquet payload so
    /// DataFusion can expose them exactly once as Hive partition columns.
    /// A complete Parquet byte buffer is built before publication so the storage
    /// backend never exposes a partially written Parquet file/object.
    pub fn write_history_batch(
        &self,
        building_id: &str,
        equipment_id: &str,
        batch: &RecordBatch,
    ) -> Result<Vec<ParquetPart>> {
        if batch.num_rows() == 0 {
            return Ok(Vec::new());
        }
        validate_identity_column(batch, "building_id", building_id)?;
        validate_identity_column(batch, "equipment_id", equipment_id)?;
        for reserved in ["year", "month"] {
            if batch.schema().index_of(reserved).is_ok() {
                bail!(
                    "canonical historian input cannot contain reserved partition column {reserved}"
                );
            }
        }

        let ts_idx = batch
            .schema()
            .index_of("timestamp_utc")
            .context("canonical historian batch requires timestamp_utc")?;
        let ts_col = batch.column(ts_idx);
        ensure_timestamp_type(ts_col.data_type())?;

        let mut groups: BTreeMap<(i32, u32), Vec<u32>> = BTreeMap::new();
        for row in 0..batch.num_rows() {
            if ts_col.is_null(row) {
                bail!("timestamp_utc cannot be null in canonical historian batch");
            }
            let dt = timestamp_at(ts_col, row)?;
            groups
                .entry((dt.year(), dt.month()))
                .or_default()
                .push(u32::try_from(row).context("record batch exceeds u32 row indexing")?);
        }

        let mut out = Vec::with_capacity(groups.len());
        for ((year, month), indices) in groups {
            let subset = take_batch(batch, &indices)?;
            let payload = partition_payload_batch(&subset)?;
            let first = indices
                .iter()
                .map(|i| timestamp_at(ts_col, *i as usize))
                .collect::<Result<Vec<_>>>()?
                .into_iter()
                .min()
                .ok_or_else(|| anyhow!("empty partition subset"))?;
            let last = indices
                .iter()
                .map(|i| timestamp_at(ts_col, *i as usize))
                .collect::<Result<Vec<_>>>()?
                .into_iter()
                .max()
                .ok_or_else(|| anyhow!("empty partition subset"))?;

            let partition = history_partition_path(building_id, equipment_id, first)?;
            debug_assert_eq!(year, first.year());
            debug_assert_eq!(month, first.month());
            let file_name = part_name(first);
            let relative = partition.join(file_name);
            let bytes = encode_parquet(&payload, self.row_group_rows)?;
            self.publisher.publish_complete(&relative, &bytes)?;
            out.push(ParquetPart {
                relative_path: slash_path(&relative),
                rows: subset.num_rows(),
                bytes: bytes.len(),
                year,
                month,
                first_timestamp_utc: first.to_rfc3339(),
                last_timestamp_utc: last.to_rfc3339(),
            });
        }
        Ok(out)
    }
}

fn validate_identity_column(batch: &RecordBatch, name: &str, expected: &str) -> Result<()> {
    let Ok(index) = batch.schema().index_of(name) else {
        return Ok(());
    };
    let column = batch.column(index);
    match column.data_type() {
        DataType::Utf8 => {
            let values = column
                .as_any()
                .downcast_ref::<StringArray>()
                .ok_or_else(|| anyhow!("{name} string array downcast failed"))?;
            for row in 0..values.len() {
                if values.is_null(row) || values.value(row) != expected {
                    bail!("{name} does not match canonical partition identity {expected}");
                }
            }
        }
        DataType::LargeUtf8 => {
            let values = column
                .as_any()
                .downcast_ref::<LargeStringArray>()
                .ok_or_else(|| anyhow!("{name} large string array downcast failed"))?;
            for row in 0..values.len() {
                if values.is_null(row) || values.value(row) != expected {
                    bail!("{name} does not match canonical partition identity {expected}");
                }
            }
        }
        other => bail!("{name} must be Utf8 identity metadata when present, got {other:?}"),
    }
    Ok(())
}

fn partition_payload_batch(batch: &RecordBatch) -> Result<RecordBatch> {
    let schema = batch.schema();
    let keep: Vec<usize> = schema
        .fields()
        .iter()
        .enumerate()
        .filter_map(|(index, field)| {
            (!matches!(field.name().as_str(), "building_id" | "equipment_id")).then_some(index)
        })
        .collect();
    Ok(batch.project(&keep)?)
}

fn part_name(first: DateTime<Utc>) -> String {
    format!(
        "part-{}-{}.parquet",
        first.format("%Y%m%dT%H%M%SZ"),
        Uuid::new_v4().simple()
    )
}

fn slash_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn encode_parquet(batch: &RecordBatch, row_group_rows: usize) -> Result<Vec<u8>> {
    let props = WriterProperties::builder()
        .set_compression(Compression::SNAPPY)
        .set_statistics_enabled(EnabledStatistics::Page)
        .set_max_row_group_size(row_group_rows)
        .set_created_by(format!("open-fdd/{}", env!("CARGO_PKG_VERSION")))
        .build();
    let mut writer = ArrowWriter::try_new(Vec::new(), batch.schema(), Some(props))?;
    writer.write(batch)?;
    writer.into_inner().map_err(Into::into)
}

fn take_batch(batch: &RecordBatch, indices: &[u32]) -> Result<RecordBatch> {
    let indices = UInt32Array::from(indices.to_vec());
    let arrays: Vec<ArrayRef> = batch
        .columns()
        .iter()
        .map(|col| take(col.as_ref(), &indices, None))
        .collect::<arrow::error::Result<Vec<_>>>()?;
    Ok(RecordBatch::try_new(batch.schema(), arrays)?)
}

fn ensure_timestamp_type(data_type: &DataType) -> Result<()> {
    if matches!(data_type, DataType::Timestamp(_, _)) {
        return Ok(());
    }
    bail!("timestamp_utc must be an Arrow Timestamp, got {data_type:?}")
}

fn timestamp_at(col: &ArrayRef, row: usize) -> Result<DateTime<Utc>> {
    macro_rules! value {
        ($array_ty:ty, $scale:expr) => {{
            let a = col
                .as_any()
                .downcast_ref::<$array_ty>()
                .ok_or_else(|| anyhow!("timestamp array downcast failed"))?;
            timestamp_from_units(a.value(row), $scale)
        }};
    }

    use arrow::array::{
        TimestampMicrosecondArray, TimestampMillisecondArray, TimestampNanosecondArray,
        TimestampSecondArray,
    };

    match col.data_type() {
        DataType::Timestamp(TimeUnit::Second, _) => value!(TimestampSecondArray, 1_000_000_000_i64),
        DataType::Timestamp(TimeUnit::Millisecond, _) => {
            value!(TimestampMillisecondArray, 1_000_000_i64)
        }
        DataType::Timestamp(TimeUnit::Microsecond, _) => {
            value!(TimestampMicrosecondArray, 1_000_i64)
        }
        DataType::Timestamp(TimeUnit::Nanosecond, _) => value!(TimestampNanosecondArray, 1_i64),
        other => bail!("timestamp_utc must be an Arrow Timestamp, got {other:?}"),
    }
}

fn timestamp_from_units(value: i64, nanos_per_unit: i64) -> Result<DateTime<Utc>> {
    let nanos = value
        .checked_mul(nanos_per_unit)
        .ok_or_else(|| anyhow!("timestamp_utc is outside supported range"))?;
    let secs = nanos.div_euclid(1_000_000_000);
    let subsec = nanos.rem_euclid(1_000_000_000) as u32;
    Utc.timestamp_opt(secs, subsec)
        .single()
        .ok_or_else(|| anyhow!("timestamp_utc is outside supported range"))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use arrow::array::{Float64Array, StringArray, TimestampNanosecondArray};
    use arrow::datatypes::{Field, Schema};
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    use tempfile::TempDir;

    fn batch(times: &[&str]) -> RecordBatch {
        batch_for_equipment(times, "AHU_1")
    }

    fn batch_for_equipment(times: &[&str], equipment_id: &str) -> RecordBatch {
        let ts: Vec<i64> = times
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
                Arc::new(TimestampNanosecondArray::from(ts)),
                Arc::new(Float64Array::from(
                    (0..times.len())
                        .map(|i| Some(50.0 + i as f64))
                        .collect::<Vec<_>>(),
                )),
                Arc::new(StringArray::from(vec![equipment_id; times.len()])),
            ],
        )
        .unwrap()
    }

    #[test]
    fn append_creates_new_immutable_part_each_time() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        let first = writer
            .write_history_batch("BUILDING_100", "AHU_1", &batch(&["2026-08-20T12:00:00Z"]))
            .unwrap();
        let second = writer
            .write_history_batch("BUILDING_100", "AHU_1", &batch(&["2026-08-20T12:05:00Z"]))
            .unwrap();
        assert_eq!(first.len(), 1);
        assert_eq!(second.len(), 1);
        assert_ne!(first[0].relative_path, second[0].relative_path);
        assert!(tmp.path().join(&first[0].relative_path).is_file());
        assert!(tmp.path().join(&second[0].relative_path).is_file());
    }

    #[test]
    fn batch_is_split_across_month_partitions() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        let parts = writer
            .write_history_batch(
                "BUILDING_100",
                "AHU_1",
                &batch(&[
                    "2026-08-31T23:55:00Z",
                    "2026-09-01T00:00:00Z",
                    "2026-08-01T00:00:00Z",
                ]),
            )
            .unwrap();
        assert_eq!(parts.len(), 2);
        assert_eq!(parts.iter().map(|p| p.rows).sum::<usize>(), 3);
        assert!(parts[0].relative_path.contains("year=2026/month=08/"));
        assert!(parts[1].relative_path.contains("year=2026/month=09/"));
    }

    #[test]
    fn written_part_roundtrips_timestamp_and_roles_without_partition_identity_columns() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        let parts = writer
            .write_history_batch(
                "BUILDING_100",
                "AHU_1",
                &batch(&["2026-08-20T12:00:00Z", "2026-08-20T12:05:00Z"]),
            )
            .unwrap();
        let file = std::fs::File::open(tmp.path().join(&parts[0].relative_path)).unwrap();
        let mut reader = ParquetRecordBatchReaderBuilder::try_new(file)
            .unwrap()
            .build()
            .unwrap();
        let persisted = reader.next().unwrap().unwrap();
        assert_eq!(persisted.num_rows(), 2);
        assert!(persisted.schema().index_of("timestamp_utc").is_ok());
        assert!(persisted.schema().index_of("sat").is_ok());
        assert!(persisted.schema().index_of("equipment_id").is_err());
        assert!(persisted.schema().index_of("building_id").is_err());
        assert!(parts[0].bytes > 0);
        assert_eq!(parts[0].first_timestamp_utc, "2026-08-20T12:00:00+00:00");
        assert_eq!(parts[0].last_timestamp_utc, "2026-08-20T12:05:00+00:00");
    }

    #[test]
    fn mismatched_identity_is_rejected_before_publish() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        let wrong = batch_for_equipment(&["2026-08-20T12:00:00Z"], "AHU_2");
        assert!(writer
            .write_history_batch("BUILDING_100", "AHU_1", &wrong)
            .is_err());
        assert!(writer
            .storage()
            .list_recursive(Path::new("history"))
            .unwrap()
            .is_empty());
    }

    #[test]
    fn rejects_non_timestamp_and_null_timestamp() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        let bad_schema = Arc::new(Schema::new(vec![Field::new(
            "timestamp_utc",
            DataType::Utf8,
            false,
        )]));
        let bad = RecordBatch::try_new(
            bad_schema,
            vec![Arc::new(StringArray::from(vec!["2026-08-20T12:00:00Z"]))],
        )
        .unwrap();
        assert!(writer
            .write_history_batch("BUILDING_100", "AHU_1", &bad)
            .is_err());

        let null_schema = Arc::new(Schema::new(vec![Field::new(
            "timestamp_utc",
            DataType::Timestamp(TimeUnit::Nanosecond, None),
            true,
        )]));
        let null_batch = RecordBatch::try_new(
            null_schema,
            vec![Arc::new(TimestampNanosecondArray::from(vec![None]))],
        )
        .unwrap();
        assert!(writer
            .write_history_batch("BUILDING_100", "AHU_1", &null_batch)
            .is_err());
    }
}
