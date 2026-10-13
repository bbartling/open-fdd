//! Historian analytics — Timescale product default vs legacy DataFusion.
//!
//! Default (`legacy-datafusion` OFF): stub fail-closed, **no** `SessionContext`.
//! Enable `legacy-datafusion` to compile `historian_datafusion.rs`.

#[cfg(feature = "legacy-datafusion")]
#[path = "historian_datafusion.rs"]
mod imp;

#[cfg(not(feature = "legacy-datafusion"))]
#[path = "historian_stub.rs"]
mod imp;

pub use imp::*;
