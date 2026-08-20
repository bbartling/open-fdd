//! Canonical historian registration and DataFusion runtime configuration.
//!
//! H3 makes the logical `history` table independent from the legacy recursive
//! `**/*.parquet` glob contract. Canonical local datasets are registered at the
//! `history/` root with Hive partition columns. Legacy sidecars remain readable
//! until H6 migration tooling is complete.

use std::path::Path;

use anyhow::{anyhow, bail, Context, Result};
use datafusion::arrow::datatypes::DataType;
use datafusion::execution::runtime_env::RuntimeEnvBuilder;
use datafusion::prelude::{ParquetReadOptions, SessionConfig, SessionContext};
use fdd_store::HistorianConfig;
use serde::Serialize;
use walkdir::WalkDir;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum HistorianDatasetKind {
    CanonicalHive,
    LegacySidecar,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HistorianRegistration {
    pub kind: HistorianDatasetKind,
    pub root: String,
}

/// Create a DataFusion session using the historian resource settings from H1.
///
/// `OPENFDD_QUERY_MEMORY_MB` becomes a process-local DataFusion memory pool
/// limit for this context. When `OPENFDD_DATAFUSION_SPILL_DIR` is configured,
/// DataFusion temporary spill files are rooted there.
pub fn new_historian_session(config: &HistorianConfig) -> Result<SessionContext> {
    let memory_bytes = config
        .query_memory_mb
        .checked_mul(1024 * 1024)
        .ok_or_else(|| anyhow!("OPENFDD_QUERY_MEMORY_MB is too large"))?;
    let memory_bytes = usize::try_from(memory_bytes)
        .map_err(|_| anyhow!("OPENFDD_QUERY_MEMORY_MB exceeds platform address space"))?;

    let mut runtime = RuntimeEnvBuilder::new().with_memory_limit(memory_bytes, 1.0);
    if let Some(spill_dir) = &config.spill_directory {
        std::fs::create_dir_all(spill_dir)
            .with_context(|| format!("create DataFusion spill dir {}", spill_dir.display()))?;
        runtime = runtime.with_temp_file_path(spill_dir);
    }

    let runtime = runtime.build_arc().context("build DataFusion runtime")?;
    Ok(SessionContext::new_with_config_rt(
        SessionConfig::new(),
        runtime,
    ))
}

/// Register the canonical local historian when present, otherwise fall back to
/// the legacy sidecar tree.
///
/// Canonical local layout:
///
/// ```text
/// <storage_root>/history/
///   building_id=<id>/equipment_id=<id>/year=<yyyy>/month=<mm>/part-*.parquet
/// ```
///
/// The identity/date partition columns are supplied by DataFusion from the
/// path. H2 deliberately keeps them out of the physical Parquet payload.
pub async fn register_historian_dataset(
    ctx: &SessionContext,
    storage_root: &Path,
) -> Result<HistorianRegistration> {
    let canonical_root = storage_root.join("history");
    if contains_parquet(&canonical_root) {
        register_canonical_history(ctx, &canonical_root).await?;
        return Ok(HistorianRegistration {
            kind: HistorianDatasetKind::CanonicalHive,
            root: canonical_root.to_string_lossy().to_string(),
        });
    }

    register_legacy_history(ctx, storage_root).await?;
    Ok(HistorianRegistration {
        kind: HistorianDatasetKind::LegacySidecar,
        root: storage_root.to_string_lossy().to_string(),
    })
}

/// Compatibility entry point retained for existing CLI/rule/analytics callers.
///
/// A canonical storage root is detected automatically. Existing callers that
/// pass a legacy `building=<id>` directory keep their old recursive behavior.
pub async fn register_parquet_tree(ctx: &SessionContext, parquet_root: &Path) -> Result<usize> {
    register_historian_dataset(ctx, parquet_root).await?;
    Ok(1)
}

async fn register_canonical_history(ctx: &SessionContext, history_root: &Path) -> Result<()> {
    // Keep all Hive partition columns as strings. In DataFusion 43, zero-padded
    // path values such as `month=08` are represented reliably as Utf8 and prune
    // correctly when compared to their canonical path literals. This also keeps
    // the logical partition contract identical across local and object stores.
    let options = ParquetReadOptions::new()
        .table_partition_cols(vec![
            ("building_id".to_string(), DataType::Utf8),
            ("equipment_id".to_string(), DataType::Utf8),
            ("year".to_string(), DataType::Utf8),
            ("month".to_string(), DataType::Utf8),
        ])
        .parquet_pruning(true);
    let root = history_root.to_string_lossy().to_string();
    ctx.register_parquet("history", root.as_str(), options)
        .await
        .with_context(|| format!("register canonical history from {root}"))
}

async fn register_legacy_history(ctx: &SessionContext, parquet_root: &Path) -> Result<()> {
    if !contains_parquet(parquet_root) {
        bail!("no Parquet history found under {}", parquet_root.display());
    }
    let glob = parquet_root.join("**/*.parquet");
    let glob_str = glob.to_string_lossy().to_string();
    ctx.register_parquet("history", glob_str.as_str(), ParquetReadOptions::default())
        .await
        .with_context(|| format!("register legacy history from {glob_str}"))
}

fn contains_parquet(root: &Path) -> bool {
    if !root.is_dir() {
        return false;
    }
    WalkDir::new(root)
        .follow_links(false)
        .into_iter()
        .filter_map(|entry| entry.ok())
        .any(|entry| {
            entry.file_type().is_file()
                && entry
                    .path()
                    .extension()
                    .and_then(|ext| ext.to_str())
                    .is_some_and(|ext| ext.eq_ignore_ascii_case("parquet"))
        })
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use chrono::{DateTime, Utc};
    use datafusion::arrow::array::{
        Float64Array, Int64Array, StringArray, TimestampNanosecondArray,
    };
    use datafusion::arrow::datatypes::{DataType as ArrowDataType, Field, Schema, TimeUnit};
    use datafusion::arrow::record_batch::RecordBatch;
    use datafusion::physical_plan::displayable;
    use fdd_store::{LocalStorage, ParquetPartWriter, StorageUrl};
    use tempfile::TempDir;

    use super::*;

    fn canonical_batch(equipment_id: &str, timestamp: &str, sat: f64) -> RecordBatch {
        let ts = DateTime::parse_from_rfc3339(timestamp)
            .unwrap()
            .with_timezone(&Utc)
            .timestamp_nanos_opt()
            .unwrap();
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                ArrowDataType::Timestamp(TimeUnit::Nanosecond, None),
                false,
            ),
            Field::new("sat", ArrowDataType::Float64, true),
            Field::new("equipment_id", ArrowDataType::Utf8, false),
        ]));
        RecordBatch::try_new(
            schema,
            vec![
                Arc::new(TimestampNanosecondArray::from(vec![ts])),
                Arc::new(Float64Array::from(vec![sat])),
                Arc::new(StringArray::from(vec![equipment_id])),
            ],
        )
        .unwrap()
    }

    fn canonical_batch_with_zone(
        equipment_id: &str,
        timestamp: &str,
        sat: f64,
        zone_t: f64,
    ) -> RecordBatch {
        let ts = DateTime::parse_from_rfc3339(timestamp)
            .unwrap()
            .with_timezone(&Utc)
            .timestamp_nanos_opt()
            .unwrap();
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "timestamp_utc",
                ArrowDataType::Timestamp(TimeUnit::Nanosecond, None),
                false,
            ),
            Field::new("sat", ArrowDataType::Float64, true),
            Field::new("zone_t", ArrowDataType::Float64, true),
            Field::new("equipment_id", ArrowDataType::Utf8, false),
        ]));
        RecordBatch::try_new(
            schema,
            vec![
                Arc::new(TimestampNanosecondArray::from(vec![ts])),
                Arc::new(Float64Array::from(vec![sat])),
                Arc::new(Float64Array::from(vec![zone_t])),
                Arc::new(StringArray::from(vec![equipment_id])),
            ],
        )
        .unwrap()
    }

    #[tokio::test]
    async fn canonical_registration_exposes_hive_partition_columns() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        writer
            .write_history_batch(
                "BUILDING_100",
                "AHU_1",
                &canonical_batch("AHU_1", "2026-08-20T12:00:00Z", 55.0),
            )
            .unwrap();
        writer
            .write_history_batch(
                "BUILDING_200",
                "AHU_2",
                &canonical_batch("AHU_2", "2026-09-01T00:00:00Z", 57.0),
            )
            .unwrap();

        let ctx = SessionContext::new();
        let registration = register_historian_dataset(&ctx, tmp.path()).await.unwrap();
        assert_eq!(registration.kind, HistorianDatasetKind::CanonicalHive);

        let batches = ctx
            .sql(
                "SELECT building_id, equipment_id, year, month, sat \
                 FROM history ORDER BY building_id",
            )
            .await
            .unwrap()
            .collect()
            .await
            .unwrap();
        assert_eq!(
            batches.iter().map(|batch| batch.num_rows()).sum::<usize>(),
            2
        );

        let history = ctx.table("history").await.unwrap();
        let schema = history.schema();
        assert!(schema.field_with_unqualified_name("building_id").is_ok());
        assert!(schema.field_with_unqualified_name("equipment_id").is_ok());
        assert!(schema.field_with_unqualified_name("year").is_ok());
        assert!(schema.field_with_unqualified_name("month").is_ok());
    }

    #[tokio::test]
    async fn canonical_filters_by_partition_identity_and_month() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        for (building, equipment, ts, sat) in [
            ("BUILDING_100", "AHU_1", "2026-08-20T12:00:00Z", 55.0),
            ("BUILDING_100", "AHU_1", "2026-09-01T00:00:00Z", 56.0),
            ("BUILDING_200", "AHU_2", "2026-08-20T12:00:00Z", 60.0),
        ] {
            writer
                .write_history_batch(building, equipment, &canonical_batch(equipment, ts, sat))
                .unwrap();
        }

        let ctx = SessionContext::new();
        register_historian_dataset(&ctx, tmp.path()).await.unwrap();
        let df = ctx
            .sql(
                "SELECT sat FROM history \
                 WHERE building_id = 'BUILDING_100' \
                   AND equipment_id = 'AHU_1' \
                   AND year = '2026' AND month = '08'",
            )
            .await
            .unwrap();

        let physical = ctx
            .state()
            .create_physical_plan(df.logical_plan())
            .await
            .unwrap();
        let plan = displayable(physical.as_ref()).indent(false).to_string();
        assert!(
            plan.contains("building_id=BUILDING_100"),
            "expected matching building partition in physical plan: {plan}"
        );
        assert!(
            plan.contains("equipment_id=AHU_1"),
            "expected matching equipment partition in physical plan: {plan}"
        );
        assert!(
            plan.contains("month=08"),
            "expected matching month partition in physical plan: {plan}"
        );
        assert!(
            !plan.contains("BUILDING_200") && !plan.contains("month=09"),
            "partition pruning kept unrelated files in physical plan: {plan}"
        );

        let result = df.collect().await.unwrap();
        assert_eq!(
            result.iter().map(RecordBatch::num_rows).sum::<usize>(),
            1
        );
        let sat = result[0]
            .column(0)
            .as_any()
            .downcast_ref::<Float64Array>()
            .unwrap()
            .value(0);
        assert!((sat - 55.0).abs() < f64::EPSILON);
    }

    #[tokio::test]
    async fn canonical_registration_merges_evolved_parquet_schemas() {
        let tmp = TempDir::new().unwrap();
        let writer = ParquetPartWriter::new(LocalStorage::new(tmp.path()));
        writer
            .write_history_batch(
                "BUILDING_100",
                "AHU_1",
                &canonical_batch("AHU_1", "2026-08-20T12:00:00Z", 55.0),
            )
            .unwrap();
        writer
            .write_history_batch(
                "BUILDING_100",
                "AHU_2",
                &canonical_batch_with_zone("AHU_2", "2026-08-20T12:05:00Z", 57.0, 72.0),
            )
            .unwrap();

        let ctx = SessionContext::new();
        register_historian_dataset(&ctx, tmp.path()).await.unwrap();
        let history = ctx.table("history").await.unwrap();
        assert!(
            history
                .schema()
                .field_with_unqualified_name("zone_t")
                .is_ok(),
            "merged canonical schema should expose newly added role columns"
        );

        let rows = ctx
            .sql("SELECT COUNT(*) AS n, COUNT(zone_t) AS with_zone FROM history")
            .await
            .unwrap()
            .collect()
            .await
            .unwrap();
        let total = rows[0]
            .column(0)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap()
            .value(0);
        let with_zone = rows[0]
            .column(1)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap()
            .value(0);
        assert_eq!(total, 2);
        assert_eq!(with_zone, 1);
    }

    #[tokio::test]
    async fn legacy_sidecar_tree_remains_readable() {
        let tmp = TempDir::new().unwrap();
        let legacy = tmp.path().join("legacy");
        std::fs::create_dir_all(&legacy).unwrap();

        let writer_root = tmp.path().join("canonical-source");
        let writer = ParquetPartWriter::new(LocalStorage::new(&writer_root));
        let parts = writer
            .write_history_batch(
                "BUILDING_100",
                "AHU_1",
                &canonical_batch("AHU_1", "2026-08-20T12:00:00Z", 55.0),
            )
            .unwrap();
        let source = writer_root.join(&parts[0].relative_path);
        let legacy_file = legacy.join("history.parquet");
        std::fs::copy(source, legacy_file).unwrap();

        let ctx = SessionContext::new();
        let registration = register_historian_dataset(&ctx, &legacy).await.unwrap();
        assert_eq!(registration.kind, HistorianDatasetKind::LegacySidecar);
        let rows = ctx
            .sql("SELECT COUNT(*) FROM history")
            .await
            .unwrap()
            .collect()
            .await
            .unwrap();
        let n = rows[0]
            .column(0)
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap()
            .value(0);
        assert_eq!(n, 1);
    }

    #[test]
    fn historian_session_applies_memory_and_spill_configuration() {
        let tmp = TempDir::new().unwrap();
        let spill = tmp.path().join("spill");
        let config = HistorianConfig {
            storage_url: StorageUrl::File {
                root: tmp.path().join("history-root"),
            },
            flush_rows: 5_000,
            flush_seconds: 60,
            target_file_mb: 128,
            compaction_min_files: 8,
            compaction_enabled: true,
            query_memory_mb: 64,
            spill_directory: Some(spill.clone()),
            legacy_parquet_root: None,
        };
        new_historian_session(&config).unwrap();
        assert!(spill.is_dir());
    }
}
