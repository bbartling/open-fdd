//! Historian analytics — Timescale product path (Wave-X C2).
//!
//! DataFusion / Parquet historian bridge deleted. Stub fail-closed unless
//! Timescale helpers handle the request.

#[path = "historian_stub.rs"]
mod imp;

pub use imp::*;
