//! Fault detection layer — DataFusion SQL over Apache Arrow telemetry.

pub mod confirmation;
pub mod datafusion_sql;
pub mod execution;
pub mod registry_api;
pub mod rules;
pub mod session_config;
pub mod sql_safety;
pub mod wires;
