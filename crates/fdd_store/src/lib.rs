//! Parquet historian and sidecar storage helpers.

pub mod afdd;
pub mod afdd_scheduler;
pub mod afdd_window;
pub mod analytics_cache;
pub mod append;
pub mod building_session;
pub mod compaction;
pub mod compaction_coord;
pub mod disk_budget;
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
    wall_clock_local_rfc3339, AfddConfig, AfddLookbackUnit, AfddMode, AfddOperatorSchedule,
    AfddScheduleKind, DEFAULT_AFDD_INTERVAL_MINUTES, DEFAULT_AFDD_LOOKBACK_UNIT,
    DEFAULT_AFDD_LOOKBACK_VALUE, OPERATOR_INTERVAL_MINUTES, OPERATOR_LOOKBACK_DAYS,
};
pub use afdd_scheduler::{
    next_due_at, plan_backfill_chunks, plan_bounded_backfill, plan_continuous_cycle,
    AfddBackfillChunk, AfddCycleWindow, AfddSchedulerCheckpoint, AFDD_SCHEDULER_CHECKPOINT_PATH,
    AFDD_SCHEDULER_RUNTIME_CONFIG_PATH,
};
pub use afdd_window::{
    apply_scheduler_config_update, enforce_routine_result_scope, merge_windowed_rule_result,
    parse_backfill_request, ParsedBackfill, SchedulerConfigUpdate, MAX_AFDD_BACKFILL_CHUNKS,
    MAX_AFDD_BACKFILL_DAYS,
};
pub use analytics_cache::{
    config_hash, freshness_for_watermark, historian_watermark_order, order_key_to_rfc3339,
    read_plan, read_result, write_result, AnalyticsCacheKey, AnalyticsResultTable, CacheFreshness,
    CacheProvenance, ReadPlan, StaleAction, SCHEMA_NAME,
};
pub use append::{merge_history_wide_csv, merge_history_wide_text, MergeReport};
pub use building_session::{
    clamp_idle_secs, clamp_max_interactive, SessionBook, SessionError, SessionKind, SessionLimits,
    SessionRecord, DEFAULT_IDLE_TIMEOUT_SECS, DEFAULT_MAX_INTERACTIVE_SESSIONS,
    DEFAULT_MQTT_BUFFER_ROWS,
};
pub use compaction::{CompactionPlan, CompactionResult, CompactionSummary, ParquetCompactor};
pub use compaction_coord::{
    assert_compaction_safe_for_offline, compact_history_fail_closed, compact_history_wait,
    historian_scan_permit_wait, shared_compaction_coordinator, try_historian_scan_permit,
    CompactPermit, CompactionCoordinator, CompactionCoordinatorStatus, HistorianIoBusy, ScanPermit,
};
pub use disk_budget::{
    apply_data_budget, bytes_over_budget, collect_budget_objects, order_key_from_path,
    plan_oldest_first, preflight_update, BudgetObject, DataBudget, EvictionPlan, EvictionReport,
    PreflightDecision, PreflightInput, DEFAULT_LOCAL_DATA_BUDGET_GIB,
    DEFAULT_RESERVED_FREE_PERCENT, GIB,
};
pub use historian::{
    building_history_present, history_partition_path, list_building_ids, local_file_root_from_env,
    resolve_building_read_root, safe_partition_value, tenant_storage_prefix, tenant_storage_root,
    weather_partition_path, BuildingReadRoot, BuildingReadSource, HistorianConfig, LocalStorage,
    ObjectMetadata, StorageUrl,
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
pub use stats::{
    local_historian_stats, local_historian_stats_from_config, peek_equipment_history_columns,
    HistorianStats,
};
