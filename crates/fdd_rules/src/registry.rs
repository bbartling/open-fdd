//! Shared parameter metadata for SQL rules (registry + tuning).

use std::collections::HashMap;
use std::path::Path;

use anyhow::{Context, Result};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct RuleParameterDef {
    pub label: String,
    pub default: f64,
    pub min: f64,
    pub max: f64,
    pub step: f64,
    pub unit: String,
    #[serde(default = "default_control")]
    pub frontend_control: String,
    pub sql_placeholder: String,
}

fn default_control() -> String {
    "slider".into()
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct OperationalGate {
    #[serde(default)]
    pub mode: String,
    #[serde(default)]
    pub predicate: String,
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub preferred_roles: Vec<String>,
    #[serde(default)]
    pub command_fallback_allowed: bool,
    #[serde(default)]
    pub startup_delay_seconds: u32,
    #[serde(default)]
    pub minimum_active_coverage_pct: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RuleSpec {
    pub rule_id: String,
    pub sql_file: String,
    pub description: String,
    #[serde(default)]
    pub required_roles: Vec<String>,
    #[serde(default)]
    pub optional_roles: Vec<String>,
    /// Equipment classes this rule applies to (`ANY` = all). Empty → inferred from rule_id.
    #[serde(default)]
    pub equipment_types: Vec<String>,
    #[serde(default)]
    pub output_columns: Vec<String>,
    #[serde(default = "default_confirm")]
    pub confirm_seconds: u32,
    #[serde(default)]
    pub parameters: HashMap<String, RuleParameterDef>,
    #[serde(default)]
    pub parity_status: String,
    #[serde(default)]
    pub dashboard_wired: bool,
    #[serde(default)]
    pub operational_gate: Option<OperationalGate>,
}

impl RuleSpec {
    pub fn effective_equipment_types(&self) -> Vec<String> {
        if self.equipment_types.is_empty() {
            crate::status::default_equipment_types_for_rule(&self.rule_id)
        } else {
            self.equipment_types.clone()
        }
    }

    pub fn gate_mode(&self) -> &str {
        self.operational_gate
            .as_ref()
            .map(|g| g.mode.as_str())
            .unwrap_or("ALWAYS")
    }
}

fn default_confirm() -> u32 {
    300
}

#[derive(Debug, Deserialize)]
struct RegistryFile {
    rules: Vec<RuleSpec>,
}

#[derive(Debug, Clone)]
pub struct RuleRegistry {
    pub rules_dir: String,
    pub rules: Vec<RuleSpec>,
}

pub fn load_registry(rules_dir: &Path) -> Result<RuleRegistry> {
    let manifest = rules_dir.join("registry.yaml");
    let text = std::fs::read_to_string(&manifest)
        .with_context(|| format!("read {}", manifest.display()))?;
    let parsed: RegistryFile = serde_yaml::from_str(&text)?;
    Ok(RuleRegistry {
        rules_dir: rules_dir.display().to_string(),
        rules: parsed.rules,
    })
}
