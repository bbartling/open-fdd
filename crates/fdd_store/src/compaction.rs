//! Bounded-memory compaction for canonical local historian Parquet parts.
//!
//! Compaction is deliberately partition-local. Small immutable files are grouped
//! only within one canonical building/equipment/year/month Hive partition. A
//! replacement is written and validated while the source files remain untouched.
//! Source files are then renamed out of the `.parquet` query surface, the
//! replacement is published atomically, and retired files are deleted last.
//! This keeps write/validation failures non-destructive and avoids materializing
//! an entire partition in memory.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;

use anyhow::{anyhow, bail, Context, Result};
use arrow::array::{new_null_array, ArrayRef};
use arrow::datatypes::{FieldRef, Schema, SchemaRef};
use arrow::record_batch::RecordBatch;
use chrono::Utc;
use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
use parquet::arrow::ArrowWriter;
use parquet::basic::Compression;
use parquet::file::properties::{EnabledStatistics, WriterProperties};
use serde::Serialize;
use uuid::Uuid;

use crate::historian::{HistorianConfig, LocalStorage, ObjectMetadata, StorageUrl};
use crate::parquet_parts::DEFAULT_ROW_GROUP_ROWS;

const BYTES_PER_MIB: u64 = 1024 * 1024;

#[derive(Debug, Clone, Serialize)]
pub struct CompactionPlan {
    pub partition_path: String,
    pub input_paths: Vec<String>,
    pub input_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct CompactionResult {
    pub partition_path: String,
    pub input_files: usize,
    pub input_bytes: u64,
    pub output_path: String,
    pub output_bytes: u64,
    pub rows: u64,
    pub cleanup_pending: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct CompactionSummary {
    pub partitions: usize,
    pub input_files: usize,
    pub input_bytes: u64,
    pub output_files: usize,
    pub output_bytes: u64,
    pub rows: u64,
    pub cleanup_pending_files: usize,
}

#[derive(Debug, Clone)]
pub struct ParquetCompactor {
    storage: LocalStorage,
    min_files: usize,
    target_file_bytes: u64,
    row_group_rows: usize,
}

impl ParquetCompactor {
    pub fn new(storage: LocalStorage, min_files: usize, target_file_mb: u64) -> Result<Self> {
        if min_files < 2 {
            bail!("compaction requires at least two source files");
        }
        if target_file_mb == 0 {
            bail!("compaction target file size must be greater than zero");
        }
        let target_file_bytes = target_file_mb
            .checked_mul(BYTES_PER_MIB)
            .ok_or_else(|| anyhow!("compaction target file size is too large"))?;
        Ok(Self {
            storage,
            min_files,
            target_file_bytes,
            row_group_rows: DEFAULT_ROW_GROUP_ROWS,
        })
    }

    pub fn from_config(config: &HistorianConfig) -> Result<Self> {
        let StorageUrl::File { root } = &config.storage_url else {
            bail!("H4 local compaction requires file:// storage; object-store compaction arrives in H5");
        };
        Self::new(
            LocalStorage::new(root.clone()),
            config.compaction_min_files,
            config.target_file_mb,
        )
    }

    pub fn with_row_group_rows(mut self, rows: usize) -> Result<Self> {
        if rows == 0 {
            bail!("row group size must be greater than zero");
        }
        self.row_group_rows = rows;
        Ok(self)
    }

    pub fn storage(&self) -> &LocalStorage {
        &self.storage
    }

    /// Discover small canonical historian files partition-by-partition.
    ///
    /// Plans never cross a monthly Hive partition. Only files smaller than the
    /// target compacted-file size participate. Groups are emitted after they
    /// reach both the configured minimum file count and approximately the target
    /// compressed input size. A final group below the minimum is intentionally
    /// left for a future compaction cycle.
    pub fn plan_history(&self) -> Result<Vec<CompactionPlan>> {
        let objects = self.storage.list_recursive(Path::new("history"))?;
        let mut partitions: BTreeMap<String, Vec<ObjectMetadata>> = BTreeMap::new();

        for object in objects {
            if !object.relative_path.ends_with(".parquet") {
                continue;
            }
            let path = Path::new(&object.relative_path);
            let Some(parent) = path.parent() else {
                continue;
            };
            if !is_canonical_history_partition(parent) {
                continue;
            }
            if object.size_bytes >= self.target_file_bytes {
                continue;
            }
            partitions
                .entry(slash_path(parent))
                .or_default()
                .push(object);
        }

        let mut plans = Vec::new();
        for (partition_path, mut files) in partitions {
            files.sort_by(|a, b| a.relative_path.cmp(&b.relative_path));
            let mut current = Vec::new();
            let mut current_bytes = 0_u64;

            for file in files {
                current_bytes = current_bytes
                    .checked_add(file.size_bytes)
                    .ok_or_else(|| anyhow!("compaction input byte count overflow"))?;
                current.push(file.relative_path);

                if current.len() >= self.min_files && current_bytes >= self.target_file_bytes {
                    plans.push(CompactionPlan {
                        partition_path: partition_path.clone(),
                        input_paths: std::mem::take(&mut current),
                        input_bytes: current_bytes,
                    });
                    current_bytes = 0;
                }
            }

            if current.len() >= self.min_files {
                plans.push(CompactionPlan {
                    partition_path,
                    input_paths: current,
                    input_bytes: current_bytes,
                });
            }
        }
        Ok(plans)
    }

    /// Compact one validated plan without loading the whole partition in memory.
    pub fn compact_plan(&self, plan: &CompactionPlan) -> Result<CompactionResult> {
        validate_plan(plan)?;
        let partition = PathBuf::from(&plan.partition_path);
        if !is_canonical_history_partition(&partition) {
            bail!("compaction plan is not a canonical history month partition");
        }
        if plan.input_paths.len() < 2 {
            bail!("compaction requires at least two source files");
        }

        let mut schemas = Vec::with_capacity(plan.input_paths.len());
        let mut expected_rows = 0_u64;
        for input in &plan.input_paths {
            let relative = Path::new(input);
            ensure_input_in_partition(relative, &partition)?;
            let file = fs::File::open(resolve_storage_path(&self.storage, relative)?)
                .with_context(|| format!("open compaction input {input}"))?;
            let builder = ParquetRecordBatchReaderBuilder::try_new(file)
                .with_context(|| format!("read Parquet metadata for {input}"))?;
            let rows = u64::try_from(builder.metadata().file_metadata().num_rows())
                .map_err(|_| anyhow!("negative Parquet row count for {input}"))?;
            expected_rows = expected_rows
                .checked_add(rows)
                .ok_or_else(|| anyhow!("compaction row count overflow"))?;
            schemas.push(builder.schema().clone());
        }
        let merged_schema = merge_schemas(&schemas)?;

        let op_id = Uuid::new_v4().simple().to_string();
        let candidate = partition.join(format!(".compact-{op_id}.pending"));
        let final_path = partition.join(format!(
            "compact-{}-{op_id}.parquet",
            Utc::now().format("%Y%m%dT%H%M%SZ")
        ));

        write_atomic_file(&self.storage, &candidate, |file| {
            let props = WriterProperties::builder()
                .set_compression(Compression::SNAPPY)
                .set_statistics_enabled(EnabledStatistics::Page)
                .set_max_row_group_size(self.row_group_rows)
                .set_created_by(format!("open-fdd/{} compactor", env!("CARGO_PKG_VERSION")))
                .build();
            let mut writer = ArrowWriter::try_new(file, merged_schema.clone(), Some(props))?;

            for input in &plan.input_paths {
                let source = fs::File::open(resolve_storage_path(&self.storage, Path::new(input))?)
                    .with_context(|| format!("reopen compaction input {input}"))?;
                let reader = ParquetRecordBatchReaderBuilder::try_new(source)?.build()?;
                for batch in reader {
                    let batch = batch?;
                    let aligned = align_batch(&batch, &merged_schema)?;
                    writer.write(&aligned)?;
                }
            }
            writer.close()?;
            Ok(())
        })?;

        if let Err(error) =
            validate_replacement(&self.storage, &candidate, &merged_schema, expected_rows)
        {
            let _ = self.storage.delete(&candidate);
            return Err(error.context("compacted replacement validation failed"));
        }

        let mut retired = Vec::with_capacity(plan.input_paths.len());
        for input in &plan.input_paths {
            let original = PathBuf::from(input);
            let tombstone = retired_path(&original, &op_id)?;
            if let Err(error) = rename_storage_path(&self.storage, &original, &tombstone) {
                rollback_retired(&self.storage, &retired);
                let _ = self.storage.delete(&candidate);
                return Err(error.context("retire compaction inputs before publish"));
            }
            retired.push((original, tombstone));
        }

        if let Err(error) = rename_storage_path(&self.storage, &candidate, &final_path) {
            rollback_retired(&self.storage, &retired);
            let _ = self.storage.delete(&candidate);
            return Err(error.context("publish compacted replacement"));
        }

        let output_bytes = fs::metadata(resolve_storage_path(&self.storage, &final_path)?)?.len();
        let mut cleanup_pending = Vec::new();
        for (_, tombstone) in &retired {
            if self.storage.delete(tombstone).is_err() {
                cleanup_pending.push(slash_path(tombstone));
            }
        }

        Ok(CompactionResult {
            partition_path: plan.partition_path.clone(),
            input_files: plan.input_paths.len(),
            input_bytes: plan.input_bytes,
            output_path: slash_path(&final_path),
            output_bytes,
            rows: expected_rows,
            cleanup_pending,
        })
    }

    pub fn compact_history(&self) -> Result<(Vec<CompactionResult>, CompactionSummary)> {
        let plans = self.plan_history()?;
        let mut results = Vec::with_capacity(plans.len());
        let mut summary = CompactionSummary::default();

        for plan in plans {
            let result = self.compact_plan(&plan)?;
            summary.partitions += 1;
            summary.input_files += result.input_files;
            summary.input_bytes = summary
                .input_bytes
                .checked_add(result.input_bytes)
                .ok_or_else(|| anyhow!("compaction summary input byte count overflow"))?;
            summary.output_files += 1;
            summary.output_bytes = summary
                .output_bytes
                .checked_add(result.output_bytes)
                .ok_or_else(|| anyhow!("compaction summary output byte count overflow"))?;
            summary.rows = summary
                .rows
                .checked_add(result.rows)
                .ok_or_else(|| anyhow!("compaction summary row count overflow"))?;
            summary.cleanup_pending_files += result.cleanup_pending.len();
            results.push(result);
        }

        Ok((results, summary))
    }
}

fn validate_plan(plan: &CompactionPlan) -> Result<()> {
    if plan.partition_path.trim().is_empty() {
        bail!("compaction partition path cannot be empty");
    }
    if plan.input_paths.is_empty() {
        bail!("compaction plan has no source files");
    }
    Ok(())
}

fn ensure_input_in_partition(input: &Path, partition: &Path) -> Result<()> {
    if input.extension().and_then(|v| v.to_str()) != Some("parquet") {
        bail!(
            "compaction input must be a .parquet file: {}",
            input.display()
        );
    }
    if input.parent() != Some(partition) {
        bail!(
            "compaction input {} does not belong to partition {}",
            input.display(),
            partition.display()
        );
    }
    Ok(())
}

fn is_canonical_history_partition(path: &Path) -> bool {
    let parts: Vec<String> = path
        .components()
        .filter_map(|component| match component {
            Component::Normal(value) => value.to_str().map(str::to_owned),
            _ => None,
        })
        .collect();
    parts.len() == 5
        && parts[0] == "history"
        && parts[1].starts_with("building_id=")
        && parts[2].starts_with("equipment_id=")
        && parts[3].starts_with("year=")
        && parts[4].starts_with("month=")
}

fn merge_schemas(schemas: &[SchemaRef]) -> Result<SchemaRef> {
    let Some(first) = schemas.first() else {
        bail!("cannot compact Parquet files without a schema");
    };
    let mut fields: Vec<FieldRef> = Vec::new();

    for schema in schemas {
        for field in schema.fields() {
            if let Some(index) = fields
                .iter()
                .position(|existing| existing.name() == field.name())
            {
                let existing = &fields[index];
                if existing.data_type() != field.data_type() {
                    bail!(
                        "schema conflict for {}: {:?} vs {:?}",
                        field.name(),
                        existing.data_type(),
                        field.data_type()
                    );
                }
                if field.is_nullable() && !existing.is_nullable() {
                    fields[index] = Arc::new(existing.as_ref().clone().with_nullable(true));
                }
            } else {
                fields.push(field.clone());
            }
        }
    }

    for field in &mut fields {
        if schemas
            .iter()
            .any(|schema| schema.index_of(field.name()).is_err())
            && !field.is_nullable()
        {
            *field = Arc::new(field.as_ref().clone().with_nullable(true));
        }
    }

    Ok(Arc::new(Schema::new_with_metadata(
        fields,
        first.metadata().clone(),
    )))
}

fn align_batch(batch: &RecordBatch, target: &SchemaRef) -> Result<RecordBatch> {
    let source_schema = batch.schema();
    let mut columns: Vec<ArrayRef> = Vec::with_capacity(target.fields().len());
    for field in target.fields() {
        match source_schema.index_of(field.name()) {
            Ok(index) => {
                let source = source_schema.field(index);
                if source.data_type() != field.data_type() {
                    bail!(
                        "schema conflict for {} while compacting: {:?} vs {:?}",
                        field.name(),
                        source.data_type(),
                        field.data_type()
                    );
                }
                columns.push(batch.column(index).clone());
            }
            Err(_) if field.is_nullable() => {
                columns.push(new_null_array(field.data_type(), batch.num_rows()));
            }
            Err(_) => bail!(
                "required column {} is missing during compaction",
                field.name()
            ),
        }
    }
    Ok(RecordBatch::try_new(target.clone(), columns)?)
}

fn validate_replacement(
    storage: &LocalStorage,
    relative: &Path,
    expected_schema: &SchemaRef,
    expected_rows: u64,
) -> Result<()> {
    let file = fs::File::open(resolve_storage_path(storage, relative)?)?;
    let builder = ParquetRecordBatchReaderBuilder::try_new(file)?;
    let rows = u64::try_from(builder.metadata().file_metadata().num_rows())
        .map_err(|_| anyhow!("negative row count in compacted replacement"))?;
    if rows != expected_rows {
        bail!("compacted replacement row count changed: expected {expected_rows}, got {rows}");
    }
    if !same_logical_schema(builder.schema(), expected_schema) {
        bail!("compacted replacement schema changed during write");
    }
    Ok(())
}

fn same_logical_schema(left: &SchemaRef, right: &SchemaRef) -> bool {
    left.fields().len() == right.fields().len()
        && left.fields().iter().zip(right.fields()).all(|(a, b)| {
            a.name() == b.name()
                && a.data_type() == b.data_type()
                && a.is_nullable() == b.is_nullable()
        })
}

fn write_atomic_file<F>(storage: &LocalStorage, relative: &Path, write: F) -> Result<()>
where
    F: FnOnce(&mut fs::File) -> Result<()>,
{
    let final_path = resolve_storage_path(storage, relative)?;
    let parent = final_path
        .parent()
        .ok_or_else(|| anyhow!("compaction output path has no parent"))?;
    fs::create_dir_all(parent)?;
    let file_name = final_path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| anyhow!("invalid compaction output file name"))?;
    let tmp = parent.join(format!(".{file_name}.tmp-{}", Uuid::new_v4().simple()));

    let result = (|| -> Result<()> {
        let mut file = fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&tmp)?;
        write(&mut file)?;
        file.sync_all()?;
        Ok(())
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&tmp);
        return Err(error);
    }
    fs::rename(&tmp, &final_path)
        .with_context(|| format!("publish {} -> {}", tmp.display(), final_path.display()))?;
    Ok(())
}

fn retired_path(original: &Path, op_id: &str) -> Result<PathBuf> {
    let parent = original
        .parent()
        .ok_or_else(|| anyhow!("compaction input has no parent"))?;
    let file_name = original
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| anyhow!("invalid compaction input file name"))?;
    Ok(parent.join(format!(".{file_name}.retired-{op_id}")))
}

fn rename_storage_path(storage: &LocalStorage, from: &Path, to: &Path) -> Result<()> {
    let from = resolve_storage_path(storage, from)?;
    let to = resolve_storage_path(storage, to)?;
    if let Some(parent) = to.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::rename(&from, &to)
        .with_context(|| format!("rename {} -> {}", from.display(), to.display()))?;
    Ok(())
}

fn rollback_retired(storage: &LocalStorage, retired: &[(PathBuf, PathBuf)]) {
    for (original, tombstone) in retired.iter().rev() {
        let _ = rename_storage_path(storage, tombstone, original);
    }
}

fn resolve_storage_path(storage: &LocalStorage, relative: &Path) -> Result<PathBuf> {
    if relative.is_absolute() {
        bail!("compaction storage path must be relative");
    }
    for component in relative.components() {
        if matches!(
            component,
            Component::ParentDir | Component::RootDir | Component::Prefix(_)
        ) {
            bail!("compaction storage path traversal rejected");
        }
    }
    Ok(storage.root().join(relative))
}

fn slash_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use arrow::array::{Array, Float64Array, StringArray, TimestampNanosecondArray};
    use arrow::datatypes::{DataType, Field, Schema, TimeUnit};
    use chrono::DateTime;
    use parquet::arrow::arrow_reader::ParquetRecordBatchReaderBuilder;
    use tempfile::TempDir;

    use crate::parquet_parts::ParquetPartWriter;

    fn timestamp_values(times: &[&str]) -> Vec<i64> {
        times
            .iter()
            .map(|raw| {
                DateTime::parse_from_rfc3339(raw)
                    .unwrap()
                    .with_timezone(&Utc)
                    .timestamp_nanos_opt()
                    .unwrap()
            })
            .collect()
    }

    fn numeric_batch(times: &[&str], include_rat: bool) -> RecordBatch {
        let mut fields = vec![
            Field::new(
                "timestamp_utc",
                DataType::Timestamp(TimeUnit::Nanosecond, None),
                false,
            ),
            Field::new("sat", DataType::Float64, true),
        ];
        let mut columns: Vec<ArrayRef> = vec![
            Arc::new(TimestampNanosecondArray::from(timestamp_values(times))),
            Arc::new(Float64Array::from(
                (0..times.len())
                    .map(|index| Some(50.0 + index as f64))
                    .collect::<Vec<_>>(),
            )),
        ];
        if include_rat {
            fields.push(Field::new("rat", DataType::Float64, true));
            columns.push(Arc::new(Float64Array::from(vec![Some(70.0); times.len()])));
        }
        RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap()
    }

    fn string_sat_batch(time: &str) -> RecordBatch {
        RecordBatch::try_new(
            Arc::new(Schema::new(vec![
                Field::new(
                    "timestamp_utc",
                    DataType::Timestamp(TimeUnit::Nanosecond, None),
                    false,
                ),
                Field::new("sat", DataType::Utf8, true),
            ])),
            vec![
                Arc::new(TimestampNanosecondArray::from(timestamp_values(&[time]))),
                Arc::new(StringArray::from(vec![Some("bad-type")])),
            ],
        )
        .unwrap()
    }

    fn write_part(writer: &ParquetPartWriter, time: &str) -> String {
        writer
            .write_history_batch("B1", "AHU_1", &numeric_batch(&[time], false))
            .unwrap()[0]
            .relative_path
            .clone()
    }

    #[test]
    fn planner_groups_small_files_within_one_month_only() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        let writer = ParquetPartWriter::new(storage.clone());
        write_part(&writer, "2026-08-20T12:00:00Z");
        write_part(&writer, "2026-08-20T12:05:00Z");
        write_part(&writer, "2026-08-20T12:10:00Z");
        write_part(&writer, "2026-09-01T00:00:00Z");
        write_part(&writer, "2026-09-01T00:05:00Z");

        let plans = ParquetCompactor::new(storage, 3, 128)
            .unwrap()
            .plan_history()
            .unwrap();
        assert_eq!(plans.len(), 1);
        assert_eq!(plans[0].input_paths.len(), 3);
        assert!(plans[0].partition_path.ends_with("year=2026/month=08"));
    }

    #[test]
    fn compaction_preserves_rows_and_replaces_visible_sources() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        let writer = ParquetPartWriter::new(storage.clone());
        let originals = vec![
            write_part(&writer, "2026-08-20T12:00:00Z"),
            write_part(&writer, "2026-08-20T12:05:00Z"),
            write_part(&writer, "2026-08-20T12:10:00Z"),
        ];
        let compactor = ParquetCompactor::new(storage.clone(), 3, 128).unwrap();
        let plan = compactor.plan_history().unwrap().remove(0);
        let result = compactor.compact_plan(&plan).unwrap();

        assert_eq!(result.rows, 3);
        assert!(result.cleanup_pending.is_empty());
        for original in originals {
            assert!(!storage.exists(Path::new(&original)).unwrap());
        }
        assert!(storage.exists(Path::new(&result.output_path)).unwrap());

        let visible: Vec<_> = storage
            .list_recursive(Path::new(&plan.partition_path))
            .unwrap()
            .into_iter()
            .filter(|object| object.relative_path.ends_with(".parquet"))
            .collect();
        assert_eq!(visible.len(), 1);

        let file = fs::File::open(tmp.path().join(&result.output_path)).unwrap();
        let reader = ParquetRecordBatchReaderBuilder::try_new(file)
            .unwrap()
            .build()
            .unwrap();
        let rows = reader.map(|batch| batch.unwrap().num_rows()).sum::<usize>();
        assert_eq!(rows, 3);
    }

    #[test]
    fn compaction_unions_nullable_schema_evolution_without_row_loss() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        let writer = ParquetPartWriter::new(storage.clone());
        writer
            .write_history_batch(
                "B1",
                "AHU_1",
                &numeric_batch(&["2026-08-20T12:00:00Z"], false),
            )
            .unwrap();
        writer
            .write_history_batch(
                "B1",
                "AHU_1",
                &numeric_batch(&["2026-08-20T12:05:00Z"], true),
            )
            .unwrap();

        let compactor = ParquetCompactor::new(storage.clone(), 2, 128).unwrap();
        let plan = compactor.plan_history().unwrap().remove(0);
        let result = compactor.compact_plan(&plan).unwrap();

        let file = fs::File::open(tmp.path().join(result.output_path)).unwrap();
        let reader = ParquetRecordBatchReaderBuilder::try_new(file)
            .unwrap()
            .build()
            .unwrap();
        let mut rows = 0;
        let mut rat_nulls = 0;
        for batch in reader {
            let batch = batch.unwrap();
            rows += batch.num_rows();
            let rat = batch.column(batch.schema().index_of("rat").unwrap());
            rat_nulls += rat.null_count();
            assert!(batch.schema().field_with_name("rat").unwrap().is_nullable());
        }
        assert_eq!(rows, 2);
        assert_eq!(rat_nulls, 1);
    }

    #[test]
    fn schema_conflict_fails_before_sources_are_retired() {
        let tmp = TempDir::new().unwrap();
        let storage = LocalStorage::new(tmp.path());
        let writer = ParquetPartWriter::new(storage.clone());
        let first = writer
            .write_history_batch(
                "B1",
                "AHU_1",
                &numeric_batch(&["2026-08-20T12:00:00Z"], false),
            )
            .unwrap()[0]
            .relative_path
            .clone();
        let second = writer
            .write_history_batch("B1", "AHU_1", &string_sat_batch("2026-08-20T12:05:00Z"))
            .unwrap()[0]
            .relative_path
            .clone();

        let compactor = ParquetCompactor::new(storage.clone(), 2, 128).unwrap();
        let plan = compactor.plan_history().unwrap().remove(0);
        let error = compactor.compact_plan(&plan).unwrap_err();
        assert!(error.to_string().contains("schema conflict"));
        assert!(storage.exists(Path::new(&first)).unwrap());
        assert!(storage.exists(Path::new(&second)).unwrap());
        let objects = storage
            .list_recursive(Path::new(&plan.partition_path))
            .unwrap();
        assert_eq!(
            objects
                .iter()
                .filter(|object| object.relative_path.ends_with(".parquet"))
                .count(),
            2
        );
        assert!(!objects.iter().any(|object| {
            object.relative_path.contains(".pending") || object.relative_path.contains(".retired-")
        }));
    }
}
