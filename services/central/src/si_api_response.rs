//! Validate that numeric API outputs already use the canonical metric-c-v2 unit.

use fdd_core::units_contract::{ContractError, MetricUnitsContract};

#[derive(Debug, Clone, PartialEq)]
pub struct SiScalar {
    pub value: f64,
    pub unit: String,
    pub quantity: String,
}

/// Why a metric output could not be reported in metric-c-v2.
#[derive(Debug)]
pub enum MetricUnitError {
    /// The SQL value is not a finite f64.
    NonFiniteValue {
        rule_id: String,
        column: String,
    },
    /// Product SQL must return the canonical SI unit; source-unit conversion belongs at ingest.
    NonCanonicalOutputUnit {
        rule_id: String,
        column: String,
        declared: String,
        canonical: String,
    },
    Contract(ContractError),
}

impl std::fmt::Display for MetricUnitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NonFiniteValue { rule_id, column } => {
                write!(f, "{rule_id}.{column}: metric value is not a finite number")
            }
            Self::NonCanonicalOutputUnit {
                rule_id,
                column,
                declared,
                canonical,
            } => write!(
                f,
                "{rule_id}.{column}: SQL output unit {declared} is not canonical {canonical}"
            ),
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

/// Report a metric output after verifying that SQL already returned canonical SI.
pub fn metric_output_to_si(
    rule_id: &str,
    column: &str,
    quantity: &str,
    declared_unit: &str,
    value: f64,
) -> Result<SiScalar, MetricUnitError> {
    let contract = MetricUnitsContract::load_embedded()?;
    let canonical = contract.canonical_unit(quantity)?.to_string();
    if declared_unit != canonical {
        return Err(MetricUnitError::NonCanonicalOutputUnit {
            rule_id: rule_id.to_string(),
            column: column.to_string(),
            declared: declared_unit.to_string(),
            canonical,
        });
    }
    Ok(SiScalar {
        value,
        unit: canonical,
        quantity: quantity.to_string(),
    })
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
    fn already_si_metric_output_is_returned_unchanged() {
        let si = metric_output_to_si(
            "AVG-ZONE-TEMP",
            "avg_zone_temp",
            "absolute_temperature",
            "degC",
            22.5,
        )
        .expect("si");
        assert_eq!(si.unit, "degC");
        assert_eq!(si.value, 22.5);
    }

    #[test]
    fn imperial_metric_output_is_rejected_instead_of_converted_at_query_time() {
        let err = metric_output_to_si(
            "AVG-ZONE-TEMP",
            "avg_zone_temp",
            "absolute_temperature",
            "degF",
            50.0,
        )
        .unwrap_err();
        assert!(err.to_string().contains("not canonical degC"));
    }

    #[test]
    fn canonical_delta_unit_is_returned_unchanged() {
        let si = metric_output_to_si(
            "SV-RATE",
            "rate",
            "temperature_difference",
            "delta_degC",
            10.0,
        )
        .expect("si");
        assert_eq!(si.unit, "delta_degC");
        assert_eq!(si.value, 10.0);
    }
}
