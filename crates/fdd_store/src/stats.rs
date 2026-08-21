//! Lightweight local historian statistics for operator health reporting.
//!
//! The stats pass lists canonical Parquet objects and reads only Parquet footer
//! metadata for row counts. It does not scan telemetry columns. The small-file
//! threshold is the same target file size used by H4 compaction.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Component, Path};

use anyhow::{anyhow, bail, Context, Result};
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use serde::Serialize;

use crate::historian::{HistorianConfig, LocalStorage, StorageUrl};

const BYTES_PER_MIB: u64 = 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HistorianStats {
    pub root: String,
    pub target_file_mb: u64,
    pub parquet_files: usize,
    pub total_bytes: u64,
    pub rows: u64,
    pub small_files: usize,
    pub small_file_bytes: u64,
    pub partitions: usize,
    pub buildings: usize,
    pub equipment: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub earliest_month: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latest_month: Option<String>,
    pub invalid_layout_files: usize,
}

pub fn local_historian_stats(storage: &LocalStorage, target_file_mb: u64) -> Result<HistorianStats> {
    if target_file_mb == 0 {
        bail!("historian stats target file size must be greater than zero");
    }
    let target_file_bytes = target_file_mb
        .checked_mul(BYTES_PER_MIB)
        .ok_or_else(|| anyhow!("historian stats target file size is too large"))?;

    let objects = storage.list_recursive(Path::new("history"))?;
    let mut parquet_files = 0usize;
    let mut total_bytes = 0u64;
    let mut rows = 0u64;
    let mut small_files = 0usize;
    let mut small_file_bytes = 0u64;
    let mut invalid_layout_files = 0usize;
    let mut partitions = BTreeSet::new();
    let mut buildings = BTreeSet::new();
    let mut equipment = BTreeSet::new();
    let mut months = BTreeSet::new();

    for object in objects {
        if !object.relative_path.ends_with(".parquet") {
            continue;
        }
        parquet_files += 1;
        total_bytes = total_bytes
            .checked_add(object.size_bytes)
            .ok_or_else(|| anyhow!("historian byte count overflow"))?;
        if object.size_bytes < target_file_bytes {
            small_files += 1;
            small_file_bytes = small_file_bytes
                .checked_add(object.size_bytes)
                .ok_or_else(|| anyhow!("historian small-file byte count overflow"))?;
        }

        let Some(identity) = canonical_history_identity(Path::new(&object.relative_path)) else {
            invalid_layout_files += 1;
            continue;
        };
        buildings.insert(identity.building.to_string());
        equipment.insert((identity.building.to_string(), identity.equipment.to_string()));
        partitions.insert((
            identity.building.to_string(),
            identity.equipment.to_string(),
            identity.year,
            identity.month,
        ));
        months.insert(format!("{:04}-{:02}", identity.year, identity.month));

        let file = fs::File::open(storage.root().join(&object.relative_path))
            .with_context(|| format!("open historian Parquet {}", object.relative_path))?;
        let builder = ParquetRecordBatchReaderBuilder::try_new(file)
            .with_context(|| format!("read historian Parquet footer {}", object.relative_path))?;
        let file_rows = builder.metadata().file_metadata().num_rows();
        rows = rows
            .checked_add(u64::try_from(file_rows).context("negative Parquet row count")?)
            .ok_or_else(|| anyhow!("historian row count overflow"))?;
    }

    Ok(HistorianStats {
        root: storage.root().display().to_string(),
        target_file_mb,
        parquet_files,
        total_bytes,
        rows,
        small_files,
        small_file_bytes,
        partitions: partitions.len(),
        buildings: buildings.len(),
        equipment: equipment.len(),
        earliest_month: months.first().cloned(),
        latest_month: months.last().cloned(),
        invalid_layout_files,
    })
}

pub fn local_historian_stats_from_config(config: &HistorianConfig) -> Result<HistorianStats> {
    let StorageUrl::File { root } = &config.storage_url else {
        bail!("local historian stats require file:// storage");
    };
    local_historian_stats(&LocalStorage::new(root), config.target_file_mb)
}

#[derive(Debug, Clone, Copy)]
struct CanonicalHistoryIdentity<'a> {
    building: &'a str,
    equipment: &'a str,
    year: i32,
    month: u32,
}

fn canonical_history_identity(path: &Path) -> Option<CanonicalHistoryIdentity<'_>> {
    let components = path.components().collect::<Vec<_>>();
    if components.len() != 6 || components.iter().any(|c| !matches!(c, Component::Normal(_))) {
        return None;
    }
    let text = components
        .iter()
        .map(|component| component.as_os_str().to_str())
        .collect::<Option<Vec<_>>>()?;
    if text[0] != "history" || !text[5].ends_with(".parquet") {
        return None;
    }
    let building = text[1].strip_prefix("building_id=")?;
    let equipment = text[2].strip_prefix("equipment_id=")?;
    if building.is_empty()
        || equipment.is_empty()
        || building.contains('/')
        || building.contains('\\')
        || building.contains('=')
        || building.contains("..")
        || equipment.contains('/')
        || equipment.contains('\\')
        || equipment.contains('=')
        || equipment.contains("..")
    {
        return None;
    }
    let year_raw = text[3].strip_prefix("year=")?;
    let month_raw = text[4].strip_prefix("month=")?;
    if year_raw.len() != 4 || month_raw.len() != 2 {
        return None;
    }
    let year = year_raw.parse::<i32>().ok()?;
    let month = month_raw.parse::<u32>().ok()?;
    if !(1..=12).contains(&month) {
        return None;
    }
    Some(CanonicalHistoryIdentity {
        building,
        equipment,
        year,
        month,
    })
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use arrow::array::{Float64Array, TimestampNanosecondArray};
    use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
    use arrow::record_batch::RecordBatch;
    use chrono::{DateTime, Utc};
    use tempfile::TempDir;

    use crate::parquet_parts::ParquetPartWriter;

    fn batch(times: &[&str]) -> RecordBatch {
        let timestamps = times
            .iter()
            .map(|raw| {
                DateTime::parse_from_rfc3339(raw)
                    .unwrap()
                    .with_timezone(&Utc)
                    .timestamp_nanos_opt()
                    .unwrap()
            })
            .collect::<Vec<_>>();
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                DataType::Timestamp(TimeUnit::Nanosecond, None),
                false,
            ),
            Field::new("sat", DataType::Float64, true),
        ]));
        RecordBatch::try_new(
            schema,
            vec![
                Arc::new(TimestampNanosecondArray::from(timestamps)),
                Arc::new(Float64Array::from(vec![Some(55.0); times.len()])),
            ],
        )
        .unwrap()
    }

    #[test]
    fn stats_use_footer_rows_and_canonical_partitions() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        let writer = ParquetPartWriter::new(storage.clone());
        writer
            .write_history_batch(
                "BLDG_1",
                "AHU_1",
                &batch(&["2026-08-20T12:00:00Z", "2026-09-01T00:00:00Z"]),
            )
            .unwrap();
        writer
            .write_history_batch(
                "BLDG_1",
                "VAV_1",
                &batch(&["2026-09-01T00:05:00Z"]),
            )
            .unwrap();

        let stats = local_historian_stats(&storage, 128).unwrap();
        assert_eq!(stats.parquet_files, 3);
        assert_eq!(stats.rows, 3);
        assert_eq!(stats.partitions, 3);
        assert_eq!(stats.buildings, 1);
        assert_eq!(stats.equipment, 2);
        assert_eq!(stats.small_files, 3);
        assert_eq!(stats.earliest_month.as_deref(), Some("2026-08"));
        assert_eq!(stats.latest_month.as_deref(), Some("2026-09"));
        assert_eq!(stats.invalid_layout_files, 0);
    }

    #[test]
    fn malformed_history_parquet_is_counted_but_not_trusted_as_canonical() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        fs::create_dir_all(tmp.path().join("history/junk")).unwrap();
        fs::write(tmp.path().join("history/junk/bad.parquet"), b"not parquet").unwrap();

        let stats = local_historian_stats(&storage, 128).unwrap();
        assert_eq!(stats.parquet_files, 1);
        assert_eq!(stats.invalid_layout_files, 1);
        assert_eq!(stats.rows, 0);
    }
}
