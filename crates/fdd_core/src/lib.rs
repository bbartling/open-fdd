//! Shared typed models and validation for vibe19 CSV FDD data trees.

pub mod columns;
pub mod error;
pub mod models;
pub mod role_rank;
pub mod sensor_sweep;
pub mod units_contract;
pub mod validate;

pub use columns::{
    cookbook_role_catalog, haystack_point_to_role, is_known_cookbook_role, load_column_role_map,
    normalize_haystack_slug, normalize_role, COOKBOOK_ROLES,
};
pub use role_rank::{is_zone_t_limit_or_alarm_column, score_column_for_role};
pub use sensor_sweep::{
    flatline_quantity_allowed, is_expected_constant_role, limits_for_haystack_role,
    limits_for_quantity, quantity_for_haystack_role, quantity_for_sql_role,
    sweep_assessable_sql_role, QuantityLimits,
};

pub use error::CoreError;
pub use models::*;
pub use units_contract::{
    normalize_alias, reject_unknown_alias, ContractError as MetricContractError,
    MetricUnitsContract, ALIAS_NORMALIZE_GOLDENS_JSON, METRIC_UNITS_JSON,
};
pub use validate::{validate_building, ValidationReport};
