//! Parquet historian and sidecar storage helpers.

pub mod afdd;
pub mod append;
pub mod compaction;
pub mod historian;
pub mod ingest;
pub(crate) mod legacy_formats;
pub mod meta;
pub mod micro_batch;
pub mod migration;
pub mod migration_exec;
pub mod parquet_parts;
pub mod stats;

pub use afdd::{
    AfddConfig, AfddLookbackUnit, AfddMode, DEFAULT_AFDD_INTERVAL_MINUTES,
    DEFAULT_AFDD_LOOKBACK_UNIT, DEFAULT_AFDD_LOOKBACK_VALUE,
};
pub use append::{merge_history_wide_csv, merge_history_wide_text, MergeReport};
pub use compaction::{CompactionPlan, CompactionResult, CompactionSummary, ParquetCompactor};
pub use historian::{
    history_partition_path, safe_partition_value, weather_partition_path, HistorianConfig,
    LocalStorage, ObjectMetadata, StorageUrl,
};
pub use ingest::{ingest_building, ingest_building_with_batch_hook, IngestReport, IngestTiming};
pub use meta::SidecarMeta;
pub use micro_batch::{FlushReason, HistorianBatchKey, MicroBatchFlush, MicroBatchHistorian};
pub use migration::{
    discover_legacy_historian, LegacyHistorianCandidate, LegacyHistorianFormat,
    MigrationDryRunReport, MigrationInventory,
};
pub use migration_exec::{
    migrate_legacy_historian, migrate_legacy_parquet, MigrationPart, MigrationRunReport,
    MigrationSourceReport, MigrationSourceStatus,
};
pub use parquet_parts::{
    CompletePartPublisher, ParquetPart, ParquetPartWriter, DEFAULT_ROW_GROUP_ROWS,
};
pub use stats::{local_historian_stats, local_historian_stats_from_config, HistorianStats};
