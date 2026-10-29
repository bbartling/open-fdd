//! Tuner `effect` metadata from `sql/fdd/tuning_catalog.json` (#1284 W2a/W5a).

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::OnceLock;

use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Debug, Deserialize)]
struct TuningParam {
    #[serde(default)]
    effect: Option<String>,
    #[serde(default, rename = "effect_in_sql")]
    effect_in_sql: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct TuningRule {
    rule_id: String,
    #[serde(default)]
    parameters: HashMap<String, TuningParam>,
}

#[derive(Debug, Deserialize)]
struct TuningCatalog {
    rules: Vec<TuningRule>,
}

static CATALOG: OnceLock<HashMap<String, HashMap<String, TuningParam>>> = OnceLock::new();

fn tuning_catalog_path() -> PathBuf {
    if let Ok(dir) = std::env::var("OPENFDD_SQL_RULES_DIR") {
        let base = PathBuf::from(dir);
        if let Some(parent) = base.parent() {
            let candidate = parent.join("fdd/tuning_catalog.json");
            if candidate.is_file() {
                return candidate;
            }
        }
    }
    PathBuf::from("sql/fdd/tuning_catalog.json")
}

fn load_catalog_map() -> HashMap<String, HashMap<String, TuningParam>> {
    let path = tuning_catalog_path();
    let text =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let parsed: TuningCatalog =
        serde_json::from_str(&text).unwrap_or_else(|e| panic!("parse {}: {e}", path.display()));
    parsed
        .rules
        .into_iter()
        .map(|rule| (rule.rule_id, rule.parameters))
        .collect()
}

fn catalog() -> &'static HashMap<String, HashMap<String, TuningParam>> {
    CATALOG.get_or_init(load_catalog_map)
}

pub fn derive_tuner_effect(rule_id: &str, effect_in_sql: Option<bool>) -> &'static str {
    if rule_id == "SV-RATE" {
        return "unsupported";
    }
    if effect_in_sql == Some(true) {
        "branch_sensitive"
    } else {
        "no_op"
    }
}

pub fn effect_reason(effect: &str) -> &'static str {
    match effect {
        "unsupported" => "This control is not supported for this rule yet.",
        "no_op" => "This control does not change SQL output for this rule.",
        _ => "",
    }
}

fn resolved_effect(rule_id: &str, key: &str, tuning: Option<&TuningParam>) -> &'static str {
    if let Some(raw) = tuning.and_then(|p| p.effect.as_deref()) {
        return match raw {
            "branch_sensitive" | "no_op" | "unsupported" => raw,
            _ => derive_tuner_effect(rule_id, tuning.and_then(|p| p.effect_in_sql)),
        };
    }
    derive_tuner_effect(rule_id, tuning.and_then(|p| p.effect_in_sql))
}

/// Stamp `effect` and optional `effect_reason` on each param object in a rule-params body.
pub fn annotate_rule_param_effects(body: &mut Value) {
    let rule_id = body
        .get("rule_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let Some(params) = body.get_mut("params").and_then(Value::as_object_mut) else {
        return;
    };
    let rule_catalog = catalog().get(&rule_id);
    for (key, val) in params.iter_mut() {
        let Some(obj) = val.as_object_mut() else {
            continue;
        };
        let tuning = rule_catalog.and_then(|m| m.get(key));
        let effect = resolved_effect(&rule_id, key, tuning);
        obj.insert("effect".into(), json!(effect));
        if effect == "unsupported" || effect == "no_op" {
            let reason = effect_reason(effect);
            if !reason.is_empty() {
                obj.insert("effect_reason".into(), json!(reason));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn sv_rate_tuners_are_unsupported() {
        let mut body = json!({
            "ok": true,
            "rule_id": "SV-RATE",
            "params": {
                "sensor_span": { "unit": "unit", "default": 100.0 }
            }
        });
        annotate_rule_param_effects(&mut body);
        assert_eq!(
            body["params"]["sensor_span"]["effect"],
            json!("unsupported")
        );
        assert!(body["params"]["sensor_span"]["effect_reason"]
            .as_str()
            .unwrap_or("")
            .contains("not supported"));
    }

    #[test]
    fn fan_runtime_confirm_min_is_no_op() {
        let mut body = json!({
            "ok": true,
            "rule_id": "FAN-RUNTIME-HOURS",
            "params": {
                "confirm_min": { "unit": "min", "default": 0.0 }
            }
        });
        annotate_rule_param_effects(&mut body);
        assert_eq!(body["params"]["confirm_min"]["effect"], json!("no_op"));
    }
}
