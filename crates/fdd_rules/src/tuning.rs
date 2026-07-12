//! Typed SQL rule parameter merge (registry defaults + YAML overrides).

use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::{bail, Context, Result};
use serde::Deserialize;

use crate::registry::RuleSpec;

type RuleParamMap = HashMap<String, f64>;
type RuleOverrides = HashMap<String, RuleParamMap>;
type ScopedOverrides = HashMap<String, RuleOverrides>;

#[derive(Debug, Clone, Deserialize, Default)]
struct TuningRoot {
    #[serde(default)]
    rules: HashMap<String, HashMap<String, f64>>,
}

#[derive(Debug, Clone, Default)]
pub struct TuningLayers {
    pub global: RuleOverrides,
    /// building_id → rule_id → param → value
    pub building: ScopedOverrides,
    /// equipment_id → rule_id → param → value
    pub equipment: ScopedOverrides,
}

pub fn load_tuning_profiles(rules_dir: &Path) -> Result<TuningLayers> {
    let base = rules_dir.parent().unwrap_or(rules_dir).join("rule_tuning");
    Ok(TuningLayers {
        global: load_rules_map(&base.join("defaults.yaml"))?,
        building: load_building_map(&base.join("building_overrides.yaml"))?,
        equipment: load_building_map(&base.join("equipment_overrides.yaml"))?,
    })
}

fn load_rules_map(path: &Path) -> Result<RuleOverrides> {
    if !path.is_file() {
        return Ok(HashMap::new());
    }
    let text = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let parsed: TuningRoot = serde_yaml::from_str(&text)?;
    Ok(parsed.rules)
}

fn load_building_map(path: &Path) -> Result<ScopedOverrides> {
    if !path.is_file() {
        return Ok(HashMap::new());
    }
    let text = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    Ok(serde_yaml::from_str(&text).unwrap_or_default())
}

pub fn effective_param_strings(
    rule: &RuleSpec,
    layers: &TuningLayers,
    building_id: Option<&str>,
    equipment_id: Option<&str>,
    session_override: Option<&HashMap<String, f64>>,
) -> Result<HashMap<String, String>> {
    let mut values: HashMap<String, f64> = HashMap::new();
    for (key, def) in &rule.parameters {
        values.insert(key.clone(), def.default);
    }

    if let Some(m) = layers.global.get(&rule.rule_id) {
        for (k, v) in m {
            if rule.parameters.contains_key(k) {
                values.insert(k.clone(), *v);
            }
        }
    }
    if let Some(b) = building_id {
        if let Some(br) = layers.building.get(b) {
            if let Some(m) = br.get(&rule.rule_id) {
                for (k, v) in m {
                    if rule.parameters.contains_key(k) {
                        values.insert(k.clone(), *v);
                    }
                }
            }
        }
    }
    if let Some(eq) = equipment_id {
        if let Some(er) = layers.equipment.get(eq) {
            if let Some(m) = er.get(&rule.rule_id) {
                for (k, v) in m {
                    if rule.parameters.contains_key(k) {
                        values.insert(k.clone(), *v);
                    }
                }
            }
        }
    }
    if let Some(sess) = session_override {
        for (k, v) in sess {
            if !rule.parameters.contains_key(k) {
                bail!("unknown parameter `{k}` for rule {}", rule.rule_id);
            }
            values.insert(k.clone(), *v);
        }
    }

    let mut out = HashMap::new();
    for (key, def) in &rule.parameters {
        let raw = values.get(key).copied().unwrap_or(def.default);
        let clamped = raw.clamp(def.min, def.max);
        out.insert(def.sql_placeholder.clone(), format_number(clamped));
    }
    Ok(out)
}

pub fn assert_sql_placeholders(sql: &str, rule: &RuleSpec) -> Result<()> {
    let allowed: HashSet<String> = rule
        .parameters
        .values()
        .map(|p| p.sql_placeholder.clone())
        .chain([
            "POLL_SECONDS".into(),
            "CONFIRM_ROWS".into(),
            "CONFIRM_SECONDS".into(),
            // Derived at runtime from WINDOW_MINUTES + POLL_SECONDS in runner.
            "WINDOW_ROWS".into(),
            "WINDOW_ROWS_MINUS_ONE".into(),
        ])
        .collect();
    let mut i = 0;
    while let Some(start) = sql[i..].find("{{") {
        let abs = i + start;
        let rest = &sql[abs + 2..];
        let end = rest.find("}}").context("unclosed placeholder")?;
        let key = rest[..end].trim().to_string();
        if !allowed.contains(&key) {
            bail!(
                "undeclared SQL placeholder `{{{key}}}` in rule {}",
                rule.rule_id
            );
        }
        i = abs + 2 + end + 2;
    }
    Ok(())
}

fn format_number(v: f64) -> String {
    if (v.fract()).abs() < 1e-9 {
        format!("{:.0}", v)
    } else {
        format!("{v}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::RuleParameterDef;

    fn sample_rule() -> RuleSpec {
        RuleSpec {
            rule_id: "VAV-1".into(),
            sql_file: "vav1_comfort_fault.sql".into(),
            description: "test".into(),
            required_roles: vec![],
            output_columns: vec![],
            confirm_seconds: 900,
            parity_status: String::new(),
            dashboard_wired: true,
            parameters: HashMap::from([(
                "zone_t_lo".into(),
                RuleParameterDef {
                    label: "Low".into(),
                    default: 68.0,
                    min: 60.0,
                    max: 72.0,
                    step: 0.5,
                    unit: "degF".into(),
                    frontend_control: "slider".into(),
                    sql_placeholder: "ZONE_T_LO".into(),
                },
            )]),
            optional_roles: vec![],
        }
    }

    #[test]
    fn equipment_override_wins() {
        let rule = sample_rule();
        let mut layers = TuningLayers::default();
        layers.equipment.insert(
            "VAV_1".into(),
            HashMap::from([("VAV-1".into(), HashMap::from([("zone_t_lo".into(), 67.0)]))]),
        );
        let out = effective_param_strings(&rule, &layers, None, Some("VAV_1"), None).unwrap();
        assert_eq!(out.get("ZONE_T_LO"), Some(&"67".to_string()));
    }

    #[test]
    fn rejects_unknown_session_param() {
        let rule = sample_rule();
        let bad = HashMap::from([("nope".into(), 1.0)]);
        assert!(
            effective_param_strings(&rule, &TuningLayers::default(), None, None, Some(&bad))
                .is_err()
        );
    }
}
