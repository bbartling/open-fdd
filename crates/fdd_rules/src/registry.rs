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

#[derive(Debug, Clone, Deserialize)]
pub struct RuleSpec {
    pub rule_id: String,
    pub sql_file: String,
    pub description: String,
    #[serde(default)]
    pub required_roles: Vec<String>,
    #[serde(default)]
    pub optional_roles: Vec<String>,
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
