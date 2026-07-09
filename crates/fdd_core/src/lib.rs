//! Shared typed models and validation for vibe19 CSV FDD data trees.

pub mod columns;
pub mod error;
pub mod models;
pub mod role_rank;
pub mod validate;

pub use columns::{load_column_role_map, normalize_role};
pub use role_rank::{is_zone_t_limit_or_alarm_column, score_column_for_role};

pub use error::CoreError;
pub use models::*;
pub use validate::{validate_building, ValidationReport};
