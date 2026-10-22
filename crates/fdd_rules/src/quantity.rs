//! Dimensional quantity for a tunable rule parameter.
//!
//! The registry `unit` token is the classifier. A key-name hint such as
//! `eps_` or `margin` selects a temperature delta only when the unit is a
//! temperature (or the unit is absent). Pressure and fraction tokens are
//! classified before that hint, so `inwc` and `frac` are not temperature
//! differences merely because those strings contain `f` or `c`.

use crate::registry::RuleSpec;
use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ParamQuantity {
    Pressure,
    Fraction,
    Temperature,
    TemperatureDelta,
    TemperatureRate,
    Minutes,
    Percent,
    VolumetricFlow,
    Hours,
    Seconds,
    Boolean,
    Dimensionless,
}

impl ParamQuantity {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pressure => "pressure",
            Self::Fraction => "fraction",
            Self::Temperature => "temperature",
            Self::TemperatureDelta => "temperature_delta",
            Self::TemperatureRate => "temperature_rate",
            Self::Minutes => "minutes",
            Self::Percent => "percent",
            Self::VolumetricFlow => "volumetric_flow",
            Self::Hours => "hours",
            Self::Seconds => "seconds",
            Self::Boolean => "boolean",
            Self::Dimensionless => "dimensionless",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw.trim().to_ascii_lowercase().as_str() {
            "pressure" | "air_pressure" => Some(Self::Pressure),
            "fraction" | "frac" => Some(Self::Fraction),
            "temperature" | "absolute_temperature" => Some(Self::Temperature),
            "temperature_delta" | "temperature_difference" => Some(Self::TemperatureDelta),
            "temperature_rate" => Some(Self::TemperatureRate),
            "minutes" | "minute" => Some(Self::Minutes),
            "percent" | "percentage" => Some(Self::Percent),
            "volumetric_flow" => Some(Self::VolumetricFlow),
            "hours" => Some(Self::Hours),
            "seconds" => Some(Self::Seconds),
            "boolean" | "bool" => Some(Self::Boolean),
            "dimensionless" | "other" => Some(Self::Dimensionless),
            _ => None,
        }
    }
}

fn unit_token(unit: &str) -> String {
    unit.trim()
        .to_ascii_lowercase()
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect()
}

fn key_suggests_temperature_delta(key: &str) -> bool {
    let k = key.to_ascii_lowercase();
    k.contains("eps_")
        || k.contains("tol")
        || k.contains("deadband")
        || k.contains("err")
        || k.contains("flatline")
        || k.ends_with("_delta")
        || k.contains("margin")
}

fn is_temperature_unit(token: &str) -> bool {
    matches!(token, "°f" | "degf" | "f" | "°c" | "degc" | "c")
}

fn is_delta_unit_token(token: &str) -> bool {
    matches!(
        token,
        "deltaf" | "deltac" | "δf" | "δc" | "Δ°f" | "Δ°c" | "degf_delta" | "degc_delta" | "k_diff"
    ) || token.contains("delta")
}

/// Quantity for one tuner parameter. `explicit` wins when it is a known token.
pub fn param_quantity(unit: &str, key: &str, explicit: Option<&str>) -> ParamQuantity {
    if let Some(raw) = explicit.map(str::trim).filter(|s| !s.is_empty()) {
        if let Some(parsed) = ParamQuantity::parse(raw) {
            return parsed;
        }
    }
    let token = unit_token(unit);
    if token.is_empty() {
        if key_suggests_temperature_delta(key) {
            return ParamQuantity::TemperatureDelta;
        }
        let k = key.to_ascii_lowercase();
        if k.ends_with("_min") || k.ends_with("_minutes") {
            return ParamQuantity::Minutes;
        }
        return ParamQuantity::Dimensionless;
    }
    if matches!(
        token.as_str(),
        "inwc" | "in_wc" | "in.w.c." | "in.wc" | "inh2o" | "psi" | "pa" | "kpa"
    ) {
        return ParamQuantity::Pressure;
    }
    if token == "frac" {
        return ParamQuantity::Fraction;
    }
    if matches!(token.as_str(), "min" | "mins" | "minute" | "minutes") {
        return ParamQuantity::Minutes;
    }
    if matches!(token.as_str(), "pct" | "%" | "percent") {
        return ParamQuantity::Percent;
    }
    if matches!(
        token.as_str(),
        "degf_per_h" | "degc_per_h" | "°f/h" | "°c/h"
    ) {
        return ParamQuantity::TemperatureRate;
    }
    if matches!(token.as_str(), "h" | "hr" | "hours") {
        return ParamQuantity::Hours;
    }
    if matches!(token.as_str(), "sec" | "secs" | "s" | "seconds") {
        return ParamQuantity::Seconds;
    }
    if matches!(token.as_str(), "bool" | "boolean" | "0/1") {
        return ParamQuantity::Boolean;
    }
    if matches!(token.as_str(), "cfm" | "l/s" | "gpm") {
        return ParamQuantity::VolumetricFlow;
    }
    if is_delta_unit_token(&token) {
        return ParamQuantity::TemperatureDelta;
    }
    if is_temperature_unit(&token) {
        if key_suggests_temperature_delta(key) {
            return ParamQuantity::TemperatureDelta;
        }
        return ParamQuantity::Temperature;
    }
    ParamQuantity::Dimensionless
}

fn explicit_quantity(rule: Option<&RuleSpec>, key: &str) -> Option<String> {
    let rule = rule?;
    let direct = rule
        .parameters
        .get(key)
        .and_then(|def| def.quantity.clone())
        .filter(|s| !s.trim().is_empty());
    if direct.is_some() {
        return direct;
    }
    if key == "confirm_min" {
        return rule
            .parameters
            .get("confirm_seconds")
            .and_then(|def| def.quantity.clone())
            .filter(|s| !s.trim().is_empty());
    }
    None
}

/// Write `quantity` onto each object in a rule-params JSON body.
pub fn annotate_rule_param_quantities(body: &mut Value, rule: Option<&RuleSpec>) {
    let Some(params) = body.get("params").and_then(Value::as_object) else {
        return;
    };
    let stamped: Vec<(String, &'static str)> = params
        .iter()
        .map(|(key, val)| {
            let unit = val.get("unit").and_then(Value::as_str).unwrap_or("");
            let explicit = explicit_quantity(rule, key);
            let quantity = param_quantity(unit, key, explicit.as_deref());
            (key.clone(), quantity.as_str())
        })
        .collect();
    let Some(params) = body.get_mut("params").and_then(Value::as_object_mut) else {
        return;
    };
    for (key, quantity) in stamped {
        if let Some(obj) = params.get_mut(&key).and_then(Value::as_object_mut) {
            obj.insert("quantity".into(), json!(quantity));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::load_registry;
    use std::path::PathBuf;

    fn registry() -> crate::registry::RuleRegistry {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../sql_rules");
        load_registry(&path).expect("load sql_rules registry")
    }

    #[test]
    fn unit_token_wins_over_eps_and_margin_key_hints() {
        assert_eq!(
            param_quantity("inwc", "eps_dsp", None),
            ParamQuantity::Pressure
        );
        assert_eq!(
            param_quantity("in_wc", "duct_high_margin", None),
            ParamQuantity::Pressure
        );
        assert_eq!(
            param_quantity("psi", "eps_head", None),
            ParamQuantity::Pressure
        );
        assert_eq!(
            param_quantity("frac", "eps_vfd_spd", None),
            ParamQuantity::Fraction
        );
        assert_eq!(
            param_quantity("min", "mode_delay_min", None),
            ParamQuantity::Minutes
        );
        assert_eq!(
            param_quantity("degF", "zone_t_lo", None),
            ParamQuantity::Temperature
        );
        assert_eq!(
            param_quantity("degF", "eps_mat", None),
            ParamQuantity::TemperatureDelta
        );
        assert_eq!(
            param_quantity("°F", "flatline_tol", None),
            ParamQuantity::TemperatureDelta
        );
        assert_eq!(
            param_quantity("degF_per_h", "steady_fault_per_hour", None),
            ParamQuantity::TemperatureRate
        );
        assert_eq!(
            param_quantity("degF", "eps_dsp", Some("pressure")),
            ParamQuantity::Pressure
        );
    }

    #[test]
    fn catalog_pressure_fraction_and_temperature_stay_distinct() {
        let reg = registry();
        let fc1 = reg
            .rules
            .iter()
            .find(|rule| rule.rule_id == "FC1")
            .expect("FC1");
        assert_eq!(
            param_quantity(
                &fc1.parameters["eps_dsp"].unit,
                "eps_dsp",
                fc1.parameters["eps_dsp"].quantity.as_deref()
            ),
            ParamQuantity::Pressure
        );
        assert_eq!(
            param_quantity(
                &fc1.parameters["eps_vfd_spd"].unit,
                "eps_vfd_spd",
                fc1.parameters["eps_vfd_spd"].quantity.as_deref()
            ),
            ParamQuantity::Fraction
        );
        assert_eq!(
            param_quantity(
                &fc1.parameters["mode_delay_min"].unit,
                "mode_delay_min",
                fc1.parameters["mode_delay_min"].quantity.as_deref()
            ),
            ParamQuantity::Minutes
        );
        let vav = reg
            .rules
            .iter()
            .find(|rule| rule.rule_id == "VAV-1")
            .expect("VAV-1");
        assert_eq!(
            param_quantity(
                &vav.parameters["zone_t_lo"].unit,
                "zone_t_lo",
                vav.parameters["zone_t_lo"].quantity.as_deref()
            ),
            ParamQuantity::Temperature
        );
        let fc2 = reg
            .rules
            .iter()
            .find(|rule| rule.rule_id == "FC2")
            .expect("FC2");
        assert_eq!(
            param_quantity(
                &fc2.parameters["eps_mat"].unit,
                "eps_mat",
                fc2.parameters["eps_mat"].quantity.as_deref()
            ),
            ParamQuantity::TemperatureDelta
        );

        for rule in &reg.rules {
            for (key, def) in &rule.parameters {
                let quantity = param_quantity(&def.unit, key, def.quantity.as_deref());
                let token = unit_token(&def.unit);
                if matches!(token.as_str(), "inwc" | "in_wc" | "psi" | "frac") {
                    assert!(
                        !matches!(
                            quantity,
                            ParamQuantity::Temperature
                                | ParamQuantity::TemperatureDelta
                                | ParamQuantity::TemperatureRate
                        ),
                        "{} {key} unit {} classified as {}",
                        rule.rule_id,
                        def.unit,
                        quantity.as_str()
                    );
                }
            }
        }
    }
}
