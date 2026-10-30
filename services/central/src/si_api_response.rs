//! Convert pack/imperial-f-v1 numeric outputs to metric-c-v2 for JSON API responses (#1284 W5a).

use fdd_core::units_contract::{ContractError, MetricUnitsContract};

#[derive(Debug, Clone, PartialEq)]
pub struct SiScalar {
    pub value: f64,
    pub unit: String,
    pub quantity: String,
}

/// Convert one numeric from a declared source unit into canonical SI storage units.
pub fn value_to_si(
    quantity: &str,
    source_unit: &str,
    value: f64,
) -> Result<SiScalar, ContractError> {
    let contract = MetricUnitsContract::load_embedded()?;
    let converted = contract.convert_to_canonical(quantity, value, source_unit)?;
    let unit = contract.canonical_unit(quantity)?.to_string();
    Ok(SiScalar {
        value: converted,
        unit,
        quantity: quantity.to_string(),
    })
}

/// Why a metric output could not be reported in metric-c-v2.
#[derive(Debug)]
pub enum MetricUnitError {
    /// The rule emits a quantity-bearing column without a declared `output_units` entry.
    UndeclaredOutputUnit {
        rule_id: String,
        column: String,
    },
    /// The registry declares a kind for the column that is not the column's quantity.
    OutputKindMismatch {
        rule_id: String,
        column: String,
        declared: String,
        expected: String,
    },
    /// The SQL value is not a finite f64.
    NonFiniteValue {
        rule_id: String,
        column: String,
    },
    Contract(ContractError),
}

impl std::fmt::Display for MetricUnitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UndeclaredOutputUnit { rule_id, column } => write!(
                f,
                "{rule_id}.{column}: registry declares no output unit for a quantity-bearing metric column"
            ),
            Self::OutputKindMismatch {
                rule_id,
                column,
                declared,
                expected,
            } => write!(
                f,
                "{rule_id}.{column}: registry declares output kind {declared}, column carries {expected}"
            ),
            Self::NonFiniteValue { rule_id, column } => {
                write!(f, "{rule_id}.{column}: metric value is not a finite number")
            }
            Self::Contract(err) => write!(f, "metric unit contract: {err}"),
        }
    }
}

impl std::error::Error for MetricUnitError {}

impl From<ContractError> for MetricUnitError {
    fn from(err: ContractError) -> Self {
        Self::Contract(err)
    }
}

/// Report a metric output in metric-c-v2 given the unit the rule declares for it.
/// Output already in the canonical SI unit is returned unchanged (never converted twice).
pub fn metric_output_to_si(
    quantity: &str,
    declared_unit: &str,
    value: f64,
) -> Result<SiScalar, ContractError> {
    let contract = MetricUnitsContract::load_embedded()?;
    let canonical = contract.canonical_unit(quantity)?.to_string();
    if declared_unit == canonical {
        return Ok(SiScalar {
            value,
            unit: canonical,
            quantity: quantity.to_string(),
        });
    }
    value_to_si(quantity, declared_unit, value)
}

pub fn metric_column_quantity(column: &str) -> Option<&'static str> {
    match column {
        "avg_zone_temp" | "min_zone_temp" | "max_zone_temp" => Some("absolute_temperature"),
        "comfort_pct" => Some("percent"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn avg_zone_temp_pack_f_to_si() {
        let si = value_to_si("absolute_temperature", "degF", 72.0).expect("convert");
        assert_eq!(si.unit, "degC");
        assert!((si.value - 22.22222222222222).abs() < 1e-9);
    }

    #[test]
    fn already_si_metric_output_is_not_converted() {
        let si = metric_output_to_si("absolute_temperature", "degC", 22.5).expect("si");
        assert_eq!(si.unit, "degC");
        assert_eq!(si.value, 22.5);
    }

    #[test]
    fn declared_imperial_metric_output_converts_once() {
        let si = metric_output_to_si("absolute_temperature", "degF", 50.0).expect("si");
        assert_eq!(si.unit, "degC");
        assert!((si.value - 10.0).abs() < 1e-12);
    }

    #[test]
    fn ten_k_delta_to_celsius_storage() {
        let si = value_to_si("temperature_difference", "K_diff", 10.0).expect("convert");
        assert_eq!(si.unit, "delta_degC");
        assert!((si.value - 10.0).abs() < 1e-12);
    }
}
