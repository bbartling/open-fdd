//! Timescale historian + SQL FDD helpers (Wave-X ADR-010).
//!
//! Product path: NF portal poll / CSV package import → [`writer`] → `sample`
//! hypertable. FDD rules live under `sql/fdd/` and execute via `sql_runner`.
//! No Parquet / DataFusion here.

mod client;
mod package_seed;
mod portal;
mod runner;
mod sample;
pub mod writer;

pub use client::{clear_shared_pool, database_url_from_env, SampleUpsertStats, Tsdb, TsdbError};
pub use package_seed::{append_package_equipment, remap_equipment_roles, seed_package_dir};
pub use portal::{
    HistorianPoint, PortalInventoryPoint, PortalInventoryReport, PurgeReport, PurgeTarget,
};
pub use runner::{
    default_sql_root, load_rule_sql, render_placeholders, RuleRunRequest, RuleRunResult,
};
pub use sample::{SampleRow, UpsertBatch};
