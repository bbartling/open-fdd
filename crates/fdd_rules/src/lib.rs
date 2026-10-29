//! Rule registry and params for the Timescale SQL product path.
//!
//! Wave-X C2: DataFusion runner deleted. Stubs keep call-site signatures.

pub mod params;
pub mod quantity;
pub mod registry;
pub mod tuning;
pub mod tuning_effects;

pub use params::{poll_params, read_poll_from_cache, rule_params, substitute_sql};
pub use quantity::{annotate_rule_param_quantities, param_quantity, ParamQuantity};
pub use tuning_effects::{annotate_rule_param_effects, derive_tuner_effect, effect_reason};
pub use registry::{load_registry, RuleParameterDef, RuleRegistry, RuleSpec};
pub use tuning::{effective_param_strings, load_tuning_profiles};

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
        bail!("Wave-X 3.6.1: DataFusion rule runner deleted; use Timescale sql/fdd")
    }

    pub async fn run_all_rules_with_overrides(
        _parquet_root: &Path,
        _registry: &RuleRegistry,
        _out_dir: &Path,
        _overrides: &HashMap<String, HashMap<String, f64>>,
        _options: RunOptions<'_>,
    ) -> Result<RuleRunReport> {
        bail!("Wave-X 3.6.1: DataFusion rule runner deleted; use Timescale sql/fdd")
    }

    pub fn retired_run_json() -> Value {
        json!({
            "ok": false,
            "engine": "postgres-sql",
            "error": "Wave-X: DataFusion FDD runner deleted; use Timescale sql/fdd postgres-sql path",
        })
    }
}

pub use runner_stub::{
    retired_run_json, run_all_rules, run_all_rules_with_overrides, RuleRunReport, RunOptions,
};
