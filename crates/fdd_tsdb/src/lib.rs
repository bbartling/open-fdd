//! Timescale historian + SQL FDD helpers (Wave-X ADR-010).
//!
//! Product path: MQTTS / package import → `sample` hypertable. FDD rules live
//! under `sql/fdd/` and execute via `sql_runner`. No Parquet / DataFusion here.

mod client;
mod package_seed;
mod runner;
mod sample;

pub use client::{database_url_from_env, Tsdb, TsdbError};
pub use package_seed::{append_package_equipment, remap_equipment_roles, seed_package_dir};
pub use runner::{
    default_sql_root, load_rule_sql, render_placeholders, RuleRunRequest, RuleRunResult,
};
pub use sample::{SampleRow, UpsertBatch};
