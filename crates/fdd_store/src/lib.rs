//! Parquet sidecar store with stale-cache metadata.

pub mod ingest;
pub mod meta;

pub use ingest::{ingest_building, IngestReport, IngestTiming};
pub use meta::SidecarMeta;
