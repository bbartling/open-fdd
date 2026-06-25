//! Dev-only local validation harness (profile-driven, no bench hardcoding).

pub mod api_health;
pub mod auth_client;
pub mod browser;
pub mod fdd_analytics;
pub mod report_output;
pub mod runner;
pub mod sources;

pub use runner::{run, HarnessOptions, HarnessResult};
