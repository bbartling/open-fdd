//! Parquet sidecar store with stale-cache metadata.

pub mod append;
pub mod ingest;
pub mod meta;

pub use append::{merge_history_wide_csv, merge_history_wide_text, MergeReport};
pub use ingest::{ingest_building, ingest_building_with_batch_hook, IngestReport, IngestTiming};
pub use meta::SidecarMeta;
