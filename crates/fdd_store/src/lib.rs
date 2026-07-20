//! Parquet sidecar store with stale-cache metadata.

pub mod ingest;
pub mod meta;

pub use ingest::{ingest_building, ingest_building_with_batch_hook, IngestReport, IngestTiming};
pub use meta::SidecarMeta;
