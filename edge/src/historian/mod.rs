//! Historian facade.
//!
//! Production direction:
//! - store samples as Apache Arrow RecordBatches, IPC, or Parquet.
//! - register queryable tables into DataFusion.
//! - keep protocol drivers decoupled from FDD rule execution.

pub mod bench_telemetry;
pub mod arrow_table;
