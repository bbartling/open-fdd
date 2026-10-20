//! Timescale historian + SQL FDD helpers (Wave-X ADR-010).
//!
//! Product path: MQTTS / package import → `sample` hypertable. FDD rules live
//! under `sql/fdd/` and execute via `sql_runner`. No Parquet / DataFusion here.

mod bootstrap;
mod client;
mod package_seed;
mod runner;
mod sample;

pub use bootstrap::{
    apply_forward_schema, bootstrap_historian_from_env, classify_sql, decide_bootstrap,
    destructive_db_opt_in, plan_bundled_schema, plan_forward_schema, reset_permitted,
    BootstrapDisposition, BootstrapError, BootstrapReport, HistorianProbe, SchemaPlan, SqlClass,
};
pub use client::{database_url_from_env, SampleUpsertStats, Tsdb, TsdbError};
pub use package_seed::{append_package_equipment, remap_equipment_roles, seed_package_dir};
pub use runner::{
    default_sql_root, load_rule_sql, render_placeholders, RuleRunRequest, RuleRunResult,
};
pub use sample::{SampleRow, UpsertBatch};
