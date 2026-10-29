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

static CATALOG: OnceLock<Result<HashMap<String, HashMap<String, TuningParam>>, String>> =
    OnceLock::new();

/// `sql/fdd` pack root — same env contract as openfdd-central `sql_root_for_registry` (no cwd/build fallbacks).
pub fn sql_fdd_pack_root() -> Result<PathBuf, String> {
    if let Some(p) = std::env::var_os("OPENFDD_SQL_ROOT") {
        return Ok(PathBuf::from(p));
    }
    if let Some(p) = std::env::var_os("OPENFDD_SQL_RULES_DIR") {
        return Ok(PathBuf::from(p));
    }
    Err(
        "OPENFDD_SQL_ROOT is not set (set it to the sql/fdd pack directory containing tuning_catalog.json)"
            .into(),
    )
}

/// `{OPENFDD_SQL_ROOT or OPENFDD_SQL_RULES_DIR}/tuning_catalog.json`.
pub fn tuning_catalog_path() -> Result<PathBuf, String> {
    let root = sql_fdd_pack_root()?;
    Ok(root.join("tuning_catalog.json"))
}

fn load_catalog_map() -> Result<HashMap<String, HashMap<String, TuningParam>>, String> {
    let path = tuning_catalog_path()?;
    if !path.is_file() {
        return Err(format!(
            "tuning catalog missing at {} (set OPENFDD_SQL_ROOT to the sql/fdd pack directory)",
            path.display()
        ));
    }
    let text = std::fs::read_to_string(&path)
        .map_err(|e| format!("read tuning catalog {}: {e}", path.display()))?;
    let parsed: TuningCatalog = serde_json::from_str(&text)
        .map_err(|e| format!("parse tuning catalog {}: {e}", path.display()))?;
    Ok(parsed
        .rules
        .into_iter()
        .map(|rule| (rule.rule_id, rule.parameters))
        .collect())
}

fn catalog() -> Result<&'static HashMap<String, HashMap<String, TuningParam>>, String> {
    match CATALOG.get_or_init(load_catalog_map).as_ref() {
        Ok(map) => Ok(map),
        Err(msg) => Err(msg.clone()),
    }
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

fn resolved_effect(rule_id: &str, _key: &str, tuning: Option<&TuningParam>) -> &'static str {
    if let Some(raw) = tuning.and_then(|p| p.effect.as_deref()) {
        return match raw {
            "branch_sensitive" => "branch_sensitive",
            "no_op" => "no_op",
            "unsupported" => "unsupported",
            _ => derive_tuner_effect(rule_id, tuning.and_then(|p| p.effect_in_sql)),
        };
    }
    derive_tuner_effect(rule_id, tuning.and_then(|p| p.effect_in_sql))
}

/// Stamp `effect` and optional `effect_reason` on each param object in a rule-params body.
pub fn annotate_rule_param_effects(body: &mut Value) -> Result<(), String> {
    let rule_id = body
        .get("rule_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let Some(params) = body.get_mut("params").and_then(Value::as_object_mut) else {
        return Ok(());
    };
    let rule_catalog = catalog()?.get(&rule_id);
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
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::path::PathBuf;
    use std::sync::{Mutex, Once};

    static ENV_LOCK: Mutex<()> = Mutex::new(());
    static INIT: Once = Once::new();

    fn test_sql_fdd_root() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../sql/fdd")
    }

    fn ensure_test_sql_fdd_root() {
        INIT.call_once(|| {
            if std::env::var_os("OPENFDD_SQL_ROOT").is_none()
                && std::env::var_os("OPENFDD_SQL_RULES_DIR").is_none()
            {
                std::env::set_var("OPENFDD_SQL_ROOT", test_sql_fdd_root());
            }
        });
    }

    #[test]
    fn tuning_catalog_path_uses_configured_root() {
        let _guard = ENV_LOCK.lock().expect("env lock");
        ensure_test_sql_fdd_root();
        let path = tuning_catalog_path().expect("path");
        assert!(path.ends_with("tuning_catalog.json"));
        assert!(path.is_file(), "missing {}", path.display());
    }

    #[test]
    fn missing_catalog_errors_with_path() {
        let _guard = ENV_LOCK.lock().expect("env lock");
        let tmp = std::env::temp_dir().join(format!(
            "openfdd-tuning-catalog-missing-{}",
            std::process::id()
        ));
        let _ = std::fs::create_dir_all(&tmp);
        let prev_root = std::env::var("OPENFDD_SQL_ROOT").ok();
        let prev_rules = std::env::var("OPENFDD_SQL_RULES_DIR").ok();
        std::env::set_var("OPENFDD_SQL_ROOT", &tmp);
        std::env::remove_var("OPENFDD_SQL_RULES_DIR");
        let expected = tmp.join("tuning_catalog.json");
        let err = load_catalog_map().expect_err("expected missing catalog error");
        assert!(
            err.contains(&expected.display().to_string()),
            "{err}"
        );
        match prev_root {
            Some(v) => std::env::set_var("OPENFDD_SQL_ROOT", v),
            None => std::env::remove_var("OPENFDD_SQL_ROOT"),
        }
        match prev_rules {
            Some(v) => std::env::set_var("OPENFDD_SQL_RULES_DIR", v),
            None => std::env::remove_var("OPENFDD_SQL_RULES_DIR"),
        }
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn unset_sql_root_reports_configuration_error() {
        let _guard = ENV_LOCK.lock().expect("env lock");
        let prev_root = std::env::var("OPENFDD_SQL_ROOT").ok();
        let prev_rules = std::env::var("OPENFDD_SQL_RULES_DIR").ok();
        std::env::remove_var("OPENFDD_SQL_ROOT");
        std::env::remove_var("OPENFDD_SQL_RULES_DIR");
        let err = sql_fdd_pack_root().expect_err("unset env");
        assert!(err.contains("OPENFDD_SQL_ROOT"), "{err}");
        match prev_root {
            Some(v) => std::env::set_var("OPENFDD_SQL_ROOT", v),
            None => std::env::remove_var("OPENFDD_SQL_ROOT"),
        }
        match prev_rules {
            Some(v) => std::env::set_var("OPENFDD_SQL_RULES_DIR", v),
            None => std::env::remove_var("OPENFDD_SQL_RULES_DIR"),
        }
    }

    #[test]
    fn sv_rate_tuners_are_unsupported() {
        let _guard = ENV_LOCK.lock().expect("env lock");
        ensure_test_sql_fdd_root();
        let mut body = json!({
            "ok": true,
            "rule_id": "SV-RATE",
            "params": {
                "sensor_span": { "unit": "unit", "default": 100.0 }
            }
        });
        annotate_rule_param_effects(&mut body).expect("annotate");
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
        let _guard = ENV_LOCK.lock().expect("env lock");
        ensure_test_sql_fdd_root();
        let mut body = json!({
            "ok": true,
            "rule_id": "FAN-RUNTIME-HOURS",
            "params": {
                "confirm_min": { "unit": "min", "default": 0.0 }
            }
        });
        annotate_rule_param_effects(&mut body).expect("annotate");
        assert_eq!(body["params"]["confirm_min"]["effect"], json!("no_op"));
    }
}
