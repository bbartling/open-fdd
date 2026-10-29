//! Convert pack/imperial-f-v1 numeric outputs to metric-c-v2 for JSON API responses (#1284 W5a).

use fdd_core::units_contract::{ContractError, MetricUnitsContract};

#[derive(Debug, Clone, PartialEq)]
pub struct SiScalar {
    pub value: f64,
    pub unit: String,
    pub quantity: String,
}

/// Convert one numeric from a declared source unit into canonical SI storage units.
pub fn value_to_si(quantity: &str, source_unit: &str, value: f64) -> Result<SiScalar, ContractError> {
    let contract = MetricUnitsContract::load_embedded()?;
    let converted = contract.convert_to_canonical(quantity, value, source_unit)?;
    let unit = contract.canonical_unit(quantity)?.to_string();
    Ok(SiScalar {
        value: converted,
        unit,
        quantity: quantity.to_string(),
    })
}

/// Legacy SQL/pivot outputs on pre-cutover stacks still evaluate in imperial-f-v1.
pub fn default_pack_source_unit(quantity: &str) -> &'static str {
    match quantity {
        "absolute_temperature" | "dry_bulb_temperature" | "wet_bulb_temperature" => "degF",
        "temperature_difference" | "temperature_delta" => "deltaF",
        "temperature_rate" => "degF_per_h",
        "air_pressure" => "inH2O",
        "hydronic_pressure" => "psi",
        "volumetric_flow" => "cfm",
        "percent" => "pct",
        "fraction" => "frac",
        _ => "",
    }
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
    fn ten_k_delta_to_celsius_storage() {
        let si = value_to_si("temperature_difference", "K_diff", 10.0).expect("convert");
        assert_eq!(si.unit, "delta_degC");
        assert!((si.value - 10.0).abs() < 1e-12);
    }
}
