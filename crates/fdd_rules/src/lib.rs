//! Rule registry and DataFusion SQL batch runner.

pub mod analytics;
pub mod gate_sql;
pub mod params;
pub mod registry;
pub mod runner;
pub mod series;
pub mod status;
pub mod tuning;

pub use analytics::{
    compute_mech_cooling_oat_bins, compute_motor_hours, compute_motor_weekly,
    mech_cooling_oat_bins_to_json, motor_hours_to_json, motor_weekly_to_json, MechCoolingOatBinRow,
    MotorHoursRow, MotorWeeklyRow,
};
pub use params::{poll_params, read_poll_from_cache, rule_params, substitute_sql};
pub use registry::{load_registry, OperationalGate, RuleParameterDef, RuleRegistry, RuleSpec};
pub use runner::{run_all_rules, RuleRunReport, RuleTiming};
pub use series::run_rule_equipment_series;
pub use status::{
    default_equipment_types_for_rule, equipment_is_applicable, infer_equipment_type, RuleStatus,
};
pub use tuning::{effective_param_strings, load_tuning_profiles, TuningLayers};

#[cfg(test)]
mod econ4_confirm_test;
#[cfg(test)]
mod fc8_gate_test;
#[cfg(test)]
mod pid_hunt_test;
#[cfg(test)]
mod poll_test;
#[cfg(test)]
mod registry_integrity_test;
#[cfg(test)]
mod sv_slew_test;
#[cfg(test)]
mod sv_stale_test;
