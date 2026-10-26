//! Read-only client for the pinned Normal Framework `PointManager` contract.
//!
//! `GetPoints`, `GetPointsById`, and `GetData` are the only RPCs this crate
//! calls. The contract note is `proto/CONTRACT.md`. Ingest wiring is separate.

mod client;
mod error;

/// Generated from the pinned `normalgw.hpl.v1` proto. The module is private,
/// so write RPCs on the generated client are not part of this crate's API.
mod proto {
    tonic::include_proto!("normalgw.hpl.v1");
}

pub use client::{
    BearerToken, HistoryPage, HistorySeries, HistoryWindow, InventoryPage, InventoryQuery, Limits,
    NfReadClient, PointRecord, Sample, SampleScalar, MAX_HISTORY_COUNT, MAX_ID_LEN, MAX_PAGE_SIZE,
    MAX_UUIDS,
};
pub use error::NfGrpcError;

/// BSR commit of `buf.build/normalframework/nf` compiled by this crate.
pub const CONTRACT_COMMIT: &str = "38f497f826214f09a483e288a78d28d4";

#[cfg(test)]
mod tests;
