//! metric-c-v2 unit contract (`sql/contract/metric_units.json`).
//!
//! W2a: parse declared aliases and convert source readings into canonical SI.
//! Query-time imperial admit (`units::admit_value_to_pack_v1`) stays until W2b/W5c.

use serde::Deserialize;
use std::collections::HashMap;
use thiserror::Error;

pub const METRIC_UNITS_JSON: &str = include_str!("../../../sql/contract/metric_units.json");

const PA_PER_IN_WC: f64 = 248.84;
const LPS_PER_CFM: f64 = 0.471947;
const KPA_PER_PSI: f64 = 6.894757;
const GPM_TO_LPS: f64 = 0.0630902;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ContractError {
    #[error("invalid metric units contract: {0}")]
    Invalid(String),
    #[error("unknown unit alias: {0}")]
    UnknownAlias(String),
    #[error("unsupported quantity for conversion: {0}")]
    UnsupportedQuantity(String),
}

#[derive(Debug, Clone, Deserialize)]
struct QuantityDef {
    id: String,
    canonical_unit: String,
    #[serde(default)]
    aliases: Vec<String>,
    #[serde(default)]
    conversion: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct MetricUnitsFile {
    quantities: Vec<QuantityDef>,
}

#[derive(Debug, Clone)]
pub struct MetricUnitsContract {
    alias_to_quantity: HashMap<String, String>,
    quantities: HashMap<String, QuantityDef>,
}

fn normalize_alias(alias: &str) -> String {
    let raw = alias
        .trim()
        .to_ascii_lowercase()
        .replace('°', "deg")
        .replace('δ', "delta");
    let is_rate = raw.contains("/h") || raw.contains("per_h") || raw.contains("perh");
    let is_delta = raw.contains("delta") || alias.contains('Δ') || alias.contains('δ');
    let cleaned: String = raw.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    let mut out = if is_delta && !cleaned.starts_with("delta") {
        format!("delta{cleaned}")
    } else {
        cleaned
    };
    if is_rate && !out.contains("perh") {
        if out.ends_with('h') {
            out.pop();
        }
        out.push_str("perh");
    }
    out
}

impl MetricUnitsContract {
    pub fn from_json(json: &str) -> Result<Self, ContractError> {
        let file: MetricUnitsFile =
            serde_json::from_str(json).map_err(|e| ContractError::Invalid(format!("json: {e}")))?;
        let mut alias_to_quantity = HashMap::new();
        let mut quantities = HashMap::new();
        for q in file.quantities {
            let mut tokens = Vec::new();
            for a in &q.aliases {
                tokens.push(normalize_alias(a));
            }
            quantities.insert(q.id.clone(), q.clone());
            for tok in tokens {
                if tok.is_empty() {
                    continue;
                }
                if let Some(existing) = alias_to_quantity.get(&tok) {
                    if existing != &q.id {
                        return Err(ContractError::Invalid(format!(
                            "duplicate alias token {tok} on {existing} and {}",
                            q.id
                        )));
                    }
                    continue;
                }
                alias_to_quantity.insert(tok, q.id.clone());
            }
        }
        Ok(Self {
            alias_to_quantity,
            quantities,
        })
    }

    pub fn load_embedded() -> Result<Self, ContractError> {
        Self::from_json(METRIC_UNITS_JSON)
    }

    pub fn resolve_alias(&self, alias: &str) -> Result<&str, ContractError> {
        let tok = normalize_alias(alias);
        if tok.is_empty() {
            return Err(ContractError::UnknownAlias(alias.to_string()));
        }
        let qid = self
            .alias_to_quantity
            .get(&tok)
            .ok_or_else(|| ContractError::UnknownAlias(alias.to_string()))?;
        Ok(qid.as_str())
    }

    pub fn canonical_unit(&self, quantity_id: &str) -> Result<&str, ContractError> {
        self.quantities
            .get(quantity_id)
            .map(|q| q.canonical_unit.as_str())
            .ok_or_else(|| ContractError::UnsupportedQuantity(quantity_id.to_string()))
    }

    pub fn convert_to_canonical(
        &self,
        quantity_id: &str,
        value: f64,
        source_unit: &str,
    ) -> Result<f64, ContractError> {
        let resolved = self.resolve_alias(source_unit)?;
        if resolved != quantity_id {
            return Err(ContractError::UnknownAlias(format!(
                "{source_unit} resolves to {resolved}, expected {quantity_id}"
            )));
        }
        let q = self
            .quantities
            .get(quantity_id)
            .ok_or_else(|| ContractError::UnsupportedQuantity(quantity_id.to_string()))?;
        let scale_only = q.conversion.as_deref() == Some("scale_only");
        let _canonical = q.canonical_unit.as_str();
        match quantity_id {
            "absolute_temperature" => {
                if scale_only {
                    return Err(ContractError::Invalid(format!(
                        "absolute_temperature cannot use scale_only conversion (canonical {_canonical})"
                    )));
                }
                let tok = normalize_alias(source_unit);
                if matches!(tok.as_str(), "f" | "degf" | "fahrenheit") {
                    Ok((value - 32.0) * 5.0 / 9.0)
                } else {
                    Ok(value)
                }
            }
            "temperature_difference" => {
                if !scale_only {
                    return Err(ContractError::Invalid(format!(
                        "temperature_difference requires scale_only (canonical {_canonical})"
                    )));
                }
                let tok = normalize_alias(source_unit);
                if tok.contains('f') || tok == "deltaf" {
                    Ok(value * 5.0 / 9.0)
                } else {
                    Ok(value)
                }
            }
            "temperature_rate" => {
                if !scale_only {
                    return Err(ContractError::Invalid(format!(
                        "temperature_rate requires scale_only (canonical {_canonical})"
                    )));
                }
                let tok = normalize_alias(source_unit);
                if tok.contains('f') {
                    Ok(value * 5.0 / 9.0)
                } else {
                    Ok(value)
                }
            }
            "air_pressure" => {
                let tok = normalize_alias(source_unit);
                if matches!(tok.as_str(), "inwc" | "inh2o") {
                    Ok(value * PA_PER_IN_WC)
                } else {
                    Ok(value)
                }
            }
            "hydronic_pressure" => {
                let tok = normalize_alias(source_unit);
                if tok == "psi" {
                    Ok(value * KPA_PER_PSI)
                } else {
                    Ok(value)
                }
            }
            "volumetric_flow" => {
                let tok = normalize_alias(source_unit);
                if tok == "cfm" {
                    Ok(value * LPS_PER_CFM)
                } else if tok == "gpm" {
                    Ok(value * GPM_TO_LPS)
                } else {
                    Ok(value)
                }
            }
            "power" => {
                let tok = normalize_alias(source_unit);
                if tok == "w" {
                    Ok(value / 1000.0)
                } else {
                    Ok(value)
                }
            }
            "interval_energy" => {
                let tok = normalize_alias(source_unit);
                if tok == "wh" {
                    Ok(value / 1000.0)
                } else {
                    Ok(value)
                }
            }
            "percent" | "fraction" | "relative_humidity" => Ok(value),
            "status" => Ok(value),
            "occupancy_mode" => Err(ContractError::UnsupportedQuantity(format!(
                "occupancy_mode (canonical {_canonical})"
            ))),
            _ => Err(ContractError::UnsupportedQuantity(format!(
                "{quantity_id} (canonical {_canonical})"
            ))),
        }
    }
}

pub fn reject_unknown_alias(alias: &str) -> Result<(), ContractError> {
    let contract = MetricUnitsContract::load_embedded()?;
    contract.resolve_alias(alias).map(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    #[test]
    fn embedded_contract_parses() {
        MetricUnitsContract::load_embedded().expect("embedded metric_units.json");
    }

    #[test]
    fn unknown_alias_rejected() {
        let c = MetricUnitsContract::load_embedded().expect("contract");
        assert_eq!(
            c.resolve_alias("not-a-real-unit"),
            Err(ContractError::UnknownAlias("not-a-real-unit".to_string()))
        );
    }

    #[test]
    fn goldens_round_trip() {
        let raw = include_str!("../../../sql/contract/goldens/unit_vectors.json");
        let body: Value = serde_json::from_str(raw).expect("goldens json");
        let contract = MetricUnitsContract::load_embedded().expect("contract");
        for case in body["cases"].as_array().expect("cases") {
            let kind = case["kind"].as_str().unwrap_or("");
            match kind {
                "absolute_temperature" => {
                    let metric = case["metric"].as_f64().expect("metric");
                    let imperial = case["imperial"].as_f64().expect("imperial");
                    let got = contract
                        .convert_to_canonical("absolute_temperature", imperial, "degF")
                        .expect("convert F");
                    assert!(
                        (got - metric).abs() < 1e-9,
                        "abs temp: got {got} expected {metric}"
                    );
                    let back = contract
                        .convert_to_canonical("absolute_temperature", metric, "degC")
                        .expect("convert C");
                    assert!((back - metric).abs() < 1e-9);
                }
                "temperature_difference" => {
                    let metric = case["metric"].as_f64().expect("metric");
                    let imperial = case["imperial"].as_f64().expect("imperial");
                    let got = contract
                        .convert_to_canonical("temperature_difference", imperial, "deltaF")
                        .expect("delta F");
                    assert!((got - metric).abs() < 1e-12);
                }
                "temperature_rate" => {
                    let metric = case["metric"].as_f64().expect("metric");
                    let imperial = case["imperial"].as_f64().expect("imperial");
                    let got = contract
                        .convert_to_canonical("temperature_rate", imperial, "degF_per_h")
                        .expect("rate");
                    assert!((got - metric).abs() < 1e-12);
                }
                "air_pressure" => {
                    let metric = case["metric"].as_f64().expect("metric");
                    let imperial = case["in_wc"].as_f64().expect("in_wc");
                    let got = contract
                        .convert_to_canonical("air_pressure", imperial, "in_wc")
                        .expect("pressure");
                    assert!((got - metric).abs() < 1e-6);
                }
                "hydronic_pressure" => {
                    let metric = case["metric"].as_f64().expect("metric");
                    let imperial = case["psi"].as_f64().expect("psi");
                    let got = contract
                        .convert_to_canonical("hydronic_pressure", imperial, "psi")
                        .expect("hydronic");
                    assert!((got - metric).abs() < 1e-6);
                }
                "volumetric_flow" => {
                    let metric = case["metric"].as_f64().expect("metric");
                    let imperial = case["cfm"].as_f64().expect("cfm");
                    let got = contract
                        .convert_to_canonical("volumetric_flow", imperial, "cfm")
                        .expect("flow");
                    assert!((got - metric).abs() < 1e-9);
                }
                "percent" | "fraction" => {}
                _ => {}
            }
        }
    }

    #[test]
    fn delta_c_alias_scale_only() {
        let c = MetricUnitsContract::load_embedded().expect("contract");
        let got = c
            .convert_to_canonical("temperature_difference", 5.0, "Δ°C")
            .expect("delta C");
        assert!((got - 5.0).abs() < 1e-12);
        let df = c
            .convert_to_canonical("temperature_difference", 9.0, "Δ°F")
            .expect("delta F");
        assert!((df - 5.0).abs() < 1e-12);
    }
}
