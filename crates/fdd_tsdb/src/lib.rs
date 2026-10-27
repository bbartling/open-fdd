//! Timescale historian + SQL FDD helpers (Wave-X ADR-010).
//!
//! Product path: NF portal poll / CSV package import → [`writer`] → `sample`
//! hypertable. FDD rules live under `sql/fdd/` and execute via `sql_runner`.
//! No Parquet / DataFusion here.

mod client;
mod incremental;
mod incremental_store;
mod package_seed;
mod portal;
mod revision;
mod runner;
mod sample;
pub mod writer;

pub use client::{clear_shared_pool, database_url_from_env, SampleUpsertStats, Tsdb, TsdbError};
pub use incremental::{
    plan_dirty_buckets, BucketGrid, BucketResult, IncrementalError, IncrementalPlan, PlanInput,
    ResultScope, RuleHorizon,
};
pub use incremental_store::{
    claim, ensure_incremental_schema, load_results, publish, release, replace_scope_results_in_tx,
    run_incremental, Claim, RunReport,
};
pub use package_seed::{append_package_equipment, remap_equipment_roles, seed_package_dir};
pub use portal::{
    HistorianPoint, PortalInventoryPoint, PortalInventoryReport, PurgeReport, PurgeTarget,
};
pub use revision::{
    changed_ranges_after, current_data_revision, ensure_revision_schema, quality_keeps_sample,
    sched1_unoccupied, schema_statements, AnalysisWindow, ChangeKind, ChangedRange,
    FddResultIdentity, IdentityError, QualityPolicy, RuleParameters, SchedulePolicy,
};
pub use runner::{
    default_sql_root, load_rule_sql, render_placeholders, RuleRunRequest, RuleRunResult,
};
pub use sample::{SampleRow, UpsertBatch};
