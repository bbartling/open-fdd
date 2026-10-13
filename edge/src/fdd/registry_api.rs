//! Registry-backed FDD API.
//!
//! Default: Timescale path (no SessionContext).
//! `legacy-datafusion`: full Parquet/DF registry runner.

#[cfg(feature = "legacy-datafusion")]
#[path = "registry_api_df.rs"]
mod imp;

#[cfg(not(feature = "legacy-datafusion"))]
#[path = "registry_api_timescale.rs"]
mod imp;

pub use imp::*;
