//! Shared process boundaries for Open-FDD protocol connectors.
//!
//! This crate is deliberately small.  It owns the cross-service wire
//! vocabulary, management-plane authentication, and telemetry sink
//! configuration.  A connector remains responsible for its protocol I/O;
//! Central remains the only Parquet/DataFusion writer.

pub mod auth;
pub mod identity;
pub mod telemetry;

pub use auth::{auth_middleware, auth_path_exempt, require_api_key_for_bind, AuthState};
pub use identity::{
    ConnectorServiceProfile, RecipeKind, ServiceIdentity, SERVICE_IDENTITY_CONTRACT_V1,
};
pub use telemetry::{
    TelemetryBatch, TelemetrySinkConfig, TelemetrySinkMode, TelemetrySinkStatus,
    TELEMETRY_SINK_CONTRACT_V1,
};
