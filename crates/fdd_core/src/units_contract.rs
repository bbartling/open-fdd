//! metric-c-v2 unit contract (`sql/contract/metric_units.json`).
//!
//! Conversions are driven only by `source_unit_conversions` in the contract JSON.
//! Query-time imperial admit (`units::admit_value_to_pack_v1`) stays until W2b/W5c.

use serde::Deserialize;
use std::collections::HashMap;
use thiserror::Error;

pub const METRIC_UNITS_JSON: &str = include_str!("../../../sql/contract/metric_units.json");
pub const ALIAS_NORMALIZE_GOLDENS_JSON: &str =
    include_str!("../../../sql/contract/goldens/alias_normalize_tokens.json");

#[derive(Debug, Error, PartialEq)]
pub enum ContractError {
    #[error("invalid metric units contract: {0}")]
    Invalid(String),
    #[error("unknown unit alias: {0}")]
    UnknownAlias(String),
    #[error("unsupported quantity for conversion: {0}")]
    UnsupportedQuantity(String),
    #[error("conversion quantity mismatch: alias {alias} maps to {actual}, expected {expected}")]
    QuantityMismatch {
        alias: String,
        actual: String,
        expected: String,
    },
}

#[derive(Debug, Clone, Deserialize)]
struct SourceUnitConversion {
    quantity: String,
    alias: String,
    scale: f64,
    offset: f64,
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
    source_unit_conversions: Vec<SourceUnitConversion>,
}

#[derive(Debug, Clone)]
struct ConversionEntry {
    quantity: String,
    scale: f64,
    offset: f64,
}

#[derive(Debug, Clone)]
pub struct MetricUnitsContract {
    conversions_by_token: HashMap<String, ConversionEntry>,
    quantities: HashMap<String, QuantityDef>,
}

/// Normalize a declared source-unit alias to a lookup token (shared with Python CI).
pub fn normalize_alias(alias: &str) -> String {
    let trimmed = alias.trim();
    if trimmed == "%" {
        return "percent".to_string();
    }
    let raw = trimmed
        .to_ascii_lowercase()
        .replace('°', "deg")
        .replace('δ', "delta")
        .replace('%', "percent");
    let is_rate = (raw.contains("/h") || raw.contains("per_h") || raw.contains("perh"))
        && (raw.contains("delta")
            || raw.contains("deg")
            || alias.contains('°')
            || alias.contains('Δ'));
    let is_delta = raw.contains("delta") || alias.contains('Δ') || alias.contains('δ');
    let cleaned: String = raw.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
    let mut out = if is_delta && !cleaned.starts_with("delta") && !cleaned.contains("delta") {
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
        let mut quantities = HashMap::new();
        for q in &file.quantities {
            quantities.insert(q.id.clone(), q.clone());
        }
        let mut conversions_by_token = HashMap::new();
        for row in &file.source_unit_conversions {
            if !quantities.contains_key(&row.quantity) {
                return Err(ContractError::Invalid(format!(
                    "source_unit_conversions references unknown quantity {}",
                    row.quantity
                )));
            }
            let tok = normalize_alias(&row.alias);
            if tok.is_empty() {
                return Err(ContractError::Invalid(format!(
                    "empty token for alias {}",
                    row.alias
                )));
            }
            let entry = ConversionEntry {
                quantity: row.quantity.clone(),
                scale: row.scale,
                offset: row.offset,
            };
            if let Some(existing) = conversions_by_token.get(&tok) {
                if existing.quantity != entry.quantity
                    || (existing.scale - entry.scale).abs() > f64::EPSILON
                    || (existing.offset - entry.offset).abs() > f64::EPSILON
                {
                    return Err(ContractError::Invalid(format!(
                        "conflicting conversion for token {tok}"
                    )));
                }
                continue;
            }
            conversions_by_token.insert(tok, entry);
        }
        for q in &file.quantities {
            if q.id == "occupancy_mode" {
                continue;
            }
            for alias in &q.aliases {
                let tok = normalize_alias(alias);
                if !conversions_by_token.contains_key(&tok) {
                    return Err(ContractError::Invalid(format!(
                        "quantity {} alias {alias} (token {tok}) has no source_unit_conversions row"
                    )));
                }
            }
        }
        Ok(Self {
            conversions_by_token,
            quantities,
        })
    }

    pub fn load_embedded() -> Result<Self, ContractError> {
        Self::from_json(METRIC_UNITS_JSON)
    }

    fn conversion_for_alias(&self, source_unit: &str) -> Result<&ConversionEntry, ContractError> {
        let tok = normalize_alias(source_unit);
        if tok.is_empty() {
            return Err(ContractError::UnknownAlias(source_unit.to_string()));
        }
        self.conversions_by_token
            .get(&tok)
            .ok_or_else(|| ContractError::UnknownAlias(source_unit.to_string()))
    }

    pub fn resolve_alias(&self, alias: &str) -> Result<&str, ContractError> {
        Ok(self.conversion_for_alias(alias)?.quantity.as_str())
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
        if quantity_id == "occupancy_mode" {
            return Err(ContractError::UnsupportedQuantity(
                "occupancy_mode".to_string(),
            ));
        }
        let entry = self.conversion_for_alias(source_unit)?;
        if entry.quantity != quantity_id {
            return Err(ContractError::QuantityMismatch {
                alias: source_unit.to_string(),
                actual: entry.quantity.clone(),
                expected: quantity_id.to_string(),
            });
        }
        Ok(value * entry.scale + entry.offset)
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
    fn alias_normalize_golden_tokens() {
        let body: Value =
            serde_json::from_str(ALIAS_NORMALIZE_GOLDENS_JSON).expect("alias normalize goldens");
        for case in body["cases"].as_array().expect("cases") {
            let input = case["input"].as_str().expect("input");
            let want = case["token"].as_str().expect("token");
            let got = normalize_alias(input);
            assert_eq!(got, want, "normalize_alias({input:?})");
        }
    }

    #[test]
    fn k_diff_not_treated_as_fahrenheit_delta() {
        let c = MetricUnitsContract::load_embedded().expect("contract");
        let got = c
            .convert_to_canonical("temperature_difference", 3.0, "K_diff")
            .expect("K_diff scale 1");
        assert!((got - 3.0).abs() < 1e-12);
    }

    #[test]
    fn m3_per_s_to_lps() {
        let c = MetricUnitsContract::load_embedded().expect("contract");
        let got = c
            .convert_to_canonical("volumetric_flow", 1.0, "m3/s")
            .expect("m3/s");
        assert!((got - 1000.0).abs() < 1e-9);
    }

    #[test]
    fn percent_alias_resolves() {
        let c = MetricUnitsContract::load_embedded().expect("contract");
        assert_eq!(c.resolve_alias("%").expect("pct"), "percent");
    }

    #[test]
    fn goldens_round_trip() {
        let raw = include_str!("../../../sql/contract/goldens/unit_vectors.json");
        let body: Value = serde_json::from_str(raw).expect("goldens json");
        let contract = MetricUnitsContract::load_embedded().expect("contract");
        for case in body["cases"].as_array().expect("cases") {
            let kind = case["kind"].as_str().unwrap_or("");
            if kind == "alias_normalize" {
                continue;
            }
            if let (Some(qty), Some(src), Some(input), Some(want)) = (
                case.get("quantity").and_then(|v| v.as_str()),
                case.get("source_unit").and_then(|v| v.as_str()),
                case.get("input").and_then(|v| v.as_f64()),
                case.get("metric").and_then(|v| v.as_f64()),
            ) {
                let got = contract
                    .convert_to_canonical(qty, input, src)
                    .unwrap_or_else(|e| panic!("{:?} {qty} {src}", e));
                assert!(
                    (got - want).abs() < case.get("tol").and_then(|v| v.as_f64()).unwrap_or(1e-9),
                    "case {} got {got} want {want}",
                    case["id"]
                );
            }
        }
    }
}
