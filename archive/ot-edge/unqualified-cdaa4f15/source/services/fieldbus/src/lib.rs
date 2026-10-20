//! Reusable fieldbus modules for the legacy sidecar and split connector
//! entrypoints.
//!
//! The legacy `openfdd-fieldbus` binary keeps its historical all-protocol
//! surface. The split binaries use [`split`] to select a smaller startup
//! graph and router, so a Haystack process never constructs a BACnet service
//! and a BACnet/Modbus process never constructs a Haystack service.

#[expect(
    dead_code,
    reason = "legacy fieldbus auth is kept for the compatibility binary"
)]
pub(crate) mod auth;
pub(crate) mod config;
pub(crate) mod error;
pub(crate) mod models;
pub(crate) mod mqtt_bridge;
pub(crate) mod openapi;
pub(crate) mod openapi_bench;
pub(crate) mod openapi_paths;
#[expect(
    dead_code,
    reason = "the split binaries mount protocol-specific route subsets"
)]
pub(crate) mod routes;
pub(crate) mod services;
pub mod split;
pub(crate) mod state;

// Small public seam for synthetic split-process integration tests. The
// production binaries still construct these types through the split module;
// callers never receive raw catalog refs or an unbounded transport API.
pub use config::{
    HaystackAuthMode, HaystackCatalog, HaystackCatalogEntry, HaystackSettings, Settings,
};
pub use services::haystack::HaystackService;
pub use split::{haystack_router, HaystackState};
