//! Shared typed models and validation for vibe19 CSV FDD data trees.

pub mod columns;
pub mod error;
pub mod models;
pub mod role_rank;
pub mod sensor_sweep;
pub mod units;
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
pub use units::{
    admit_value_to_pack_v1, celsius_to_fahrenheit, delta_c_to_delta_f, delta_f_to_delta_c,
    fahrenheit_to_celsius, is_flow_role, is_metric_unit_system, is_pressure_role,
    is_temperature_role, lps_to_cfm, metric_select_list, pa_to_in_wc, sql_admit_val_expr,
    sql_temp_to_fahrenheit, sql_with_metric_to_imperial, FLOW_ROLES, PRESSURE_ROLES,
    TEMPERATURE_ROLES,
};
pub use validate::{validate_building, ValidationReport};
