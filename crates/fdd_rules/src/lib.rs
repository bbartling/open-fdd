//! Rule registry and (optional) DataFusion SQL batch runner.
//!
//! Wave-X default: registry + params only — **no** `SessionContext`.
//! Enable feature `legacy-datafusion` for Parquet/DF rule execution.

pub mod params;
pub mod registry;
pub mod tuning;

#[cfg(feature = "legacy-datafusion")]
pub mod occupancy_schedule;
#[cfg(feature = "legacy-datafusion")]
pub mod runner;

pub use params::{poll_params, read_poll_from_cache, rule_params, substitute_sql};
pub use registry::{load_registry, RuleParameterDef, RuleRegistry, RuleSpec};
pub use tuning::{effective_param_strings, load_tuning_profiles};

#[cfg(feature = "legacy-datafusion")]
pub use runner::{
    run_all_rules, run_all_rules_with_overrides, scope_history_to_time_window, RuleRunReport,
    RunOptions,
};

/// Timescale-default stubs — signatures match `runner` so edge compiles without DF.
#[cfg(not(feature = "legacy-datafusion"))]
mod runner_stub {
    use std::collections::HashMap;
    use std::path::Path;
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;

    use anyhow::{bail, Result};
    use serde::{Deserialize, Serialize};
    use serde_json::{json, Value};

    use crate::registry::RuleRegistry;

    #[derive(Debug, Clone, Default)]
    pub struct RunOptions<'a> {
        pub equipment_filter: Option<&'a str>,
        pub weather_root: Option<&'a Path>,
        pub unit_system: Option<&'a str>,
        pub time_window: Option<(&'a str, &'a str)>,
        pub building_id: Option<&'a str>,
        pub cancel: Option<&'a Arc<AtomicBool>>,
    }

    #[derive(Debug, Clone, Serialize, Deserialize, Default)]
    pub struct RuleRunReport {
        pub rules_run: usize,
        pub rules_succeeded: usize,
        pub rules_failed: usize,
        #[serde(default)]
        pub rules_skipped: usize,
        pub poll_seconds: f64,
        pub timings: Vec<Value>,
        pub total_ms: u128,
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        pub cancelled: bool,
    }

    pub async fn run_all_rules(
        _parquet_root: &Path,
        _registry: &RuleRegistry,
        _out_dir: &Path,
    ) -> Result<RuleRunReport> {
        bail!("Wave-X 3.6.0: DataFusion rule runner retired (enable fdd_rules/legacy-datafusion)")
    }

    pub async fn run_all_rules_with_overrides(
        _parquet_root: &Path,
        _registry: &RuleRegistry,
        _out_dir: &Path,
        _overrides: &HashMap<String, HashMap<String, f64>>,
        _options: RunOptions<'_>,
    ) -> Result<RuleRunReport> {
        bail!("Wave-X 3.6.0: DataFusion rule runner retired (enable fdd_rules/legacy-datafusion)")
    }

    pub fn retired_run_json() -> Value {
        json!({
            "ok": false,
            "engine": "postgres-sql",
            "error": "Wave-X: DataFusion FDD runner retired; use Timescale sql/fdd postgres-sql path",
        })
    }
}

#[cfg(not(feature = "legacy-datafusion"))]
pub use runner_stub::{
    retired_run_json, run_all_rules, run_all_rules_with_overrides, RuleRunReport, RunOptions,
};

#[cfg(test)]
#[cfg(feature = "legacy-datafusion")]
mod econ4_confirm_test;
#[cfg(test)]
#[cfg(feature = "legacy-datafusion")]
mod fcu_parity_test;
#[cfg(test)]
#[cfg(feature = "legacy-datafusion")]
mod oat_meteo_target_test;
#[cfg(test)]
#[cfg(feature = "legacy-datafusion")]
mod oracle_harness;
#[cfg(test)]
#[cfg(feature = "legacy-datafusion")]
mod oracle_parity_test;
#[cfg(test)]
#[cfg(feature = "legacy-datafusion")]
mod poll_test;
