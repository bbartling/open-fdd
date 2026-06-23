//! Generic source connector framework for JSON API, Postgres read-only, and backfill.

pub mod api;
pub mod backfill;
pub mod historian;
pub mod json_api;
pub mod json_path;
pub mod mapping;
pub mod postgres;
pub mod registry;
pub mod secrets;
pub mod simulation;
pub mod sql_safety;
pub mod types;
