//! Rule registry and DataFusion SQL batch runner.

pub mod params;
pub mod registry;
pub mod runner;
pub mod tuning;

pub use params::{poll_params, read_poll_from_cache, rule_params, substitute_sql};
pub use registry::{load_registry, RuleParameterDef, RuleRegistry, RuleSpec};
pub use runner::{run_all_rules, RuleRunReport};
pub use tuning::{effective_param_strings, load_tuning_profiles};

#[cfg(test)]
mod econ4_confirm_test;
#[cfg(test)]
mod oracle_harness;
#[cfg(test)]
mod oracle_parity_test;
#[cfg(test)]
mod poll_test;
