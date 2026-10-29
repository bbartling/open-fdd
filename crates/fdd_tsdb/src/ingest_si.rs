//! Single-writer SI ingest: declared source units convert once to metric-c-v2 storage.

use fdd_core::{
    is_metric_unit_system, quantity_for_sql_role, MetricContractError, MetricUnitsContract,
};

pub const QUALITY_UNIT_UNDECLARED: &str = "unit_undeclared";

#[derive(Debug, Clone, PartialEq)]
pub struct PreparedIngestValue {
    pub val: Option<f64>,
    pub unit: Option<String>,
    pub quality: Option<String>,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct PointMapBinding<'a> {
    pub unit: Option<&'a str>,
    pub source_unit: Option<&'a str>,
    pub quantity: Option<&'a str>,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct SampleDeclaredContext<'a> {
    pub role: Option<&'a str>,
    pub sample_unit: Option<&'a str>,
    pub sample_source_unit: Option<&'a str>,
    pub sample_quantity: Option<&'a str>,
    pub csv_column_unit: Option<&'a str>,
    pub unit_system: Option<&'a str>,
}

fn non_empty(s: Option<&str>) -> Option<&str> {
    s.map(str::trim).filter(|t| !t.is_empty())
}

/// Resolution order: engineer overlay (via `point_map.unit`), NF tag, CSV column unit,
/// then package `unit_system` default for the role quantity.
pub fn resolve_declared_source_unit(
    map: PointMapBinding<'_>,
    ctx: SampleDeclaredContext<'_>,
) -> Option<String> {
    let quantity = non_empty(map.quantity)
        .or(non_empty(ctx.sample_quantity))
        .or_else(|| ctx.role.and_then(quantity_for_sql_role));
    for unit in [
        non_empty(map.unit),
        non_empty(map.source_unit),
        non_empty(ctx.sample_source_unit),
        non_empty(ctx.csv_column_unit),
        non_empty(ctx.sample_unit),
    ]
    .into_iter()
    .flatten()
    {
        return Some(unit.to_string());
    }
    if let (Some(qty), Some(sys)) = (quantity, non_empty(ctx.unit_system)) {
        return unit_system_default_declared_unit(qty, sys).map(str::to_string);
    }
    None
}

fn unit_system_default_declared_unit(quantity: &str, unit_system: &str) -> Option<&'static str> {
    let metric = is_metric_unit_system(unit_system);
    match quantity {
        "absolute_temperature" => Some(if metric { "degC" } else { "degF" }),
        "temperature_difference" => Some(if metric { "degC_delta" } else { "degF_delta" }),
        "temperature_rate" => Some(if metric { "degC_per_h" } else { "degF_per_h" }),
        "air_pressure" => Some(if metric { "Pa" } else { "inH2O" }),
        "hydronic_pressure" => Some(if metric { "kPa" } else { "psi" }),
        "volumetric_flow" => Some(if metric { "L/s" } else { "cfm" }),
        "power" => Some("kW"),
        "interval_energy" => Some("kWh"),
        "percent" | "relative_humidity" => Some("%"),
        "fraction" => Some("frac"),
        "electric_current" => Some("A"),
        _ => None,
    }
}

fn resolve_quantity<'a>(
    map: PointMapBinding<'a>,
    ctx: SampleDeclaredContext<'a>,
) -> Option<&'a str> {
    non_empty(map.quantity)
        .or(non_empty(ctx.sample_quantity))
        .or_else(|| ctx.role.and_then(quantity_for_sql_role))
}

/// Convert one numeric sample to canonical SI storage, or mark `unit_undeclared`.
pub fn prepare_numeric_sample(
    contract: &MetricUnitsContract,
    raw_val: f64,
    map: PointMapBinding<'_>,
    ctx: SampleDeclaredContext<'_>,
) -> PreparedIngestValue {
    let quantity = match resolve_quantity(map, ctx) {
        Some(q) => q,
        None => {
            return PreparedIngestValue {
                val: Some(raw_val),
                unit: None,
                quality: None,
            };
        }
    };
    if matches!(
        quantity,
        "status" | "count" | "boolean" | "occupancy_mode" | "dimensionless"
    ) {
        return PreparedIngestValue {
            val: Some(raw_val),
            unit: None,
            quality: None,
        };
    }
    let Some(declared) = resolve_declared_source_unit(map, ctx) else {
        return PreparedIngestValue {
            val: Some(raw_val),
            unit: None,
            quality: Some(QUALITY_UNIT_UNDECLARED.into()),
        };
    };
    match contract.convert_to_canonical(quantity, raw_val, &declared) {
        Ok(metric) => {
            let canonical = contract
                .canonical_unit(quantity)
                .unwrap_or("degC")
                .to_string();
            PreparedIngestValue {
                val: Some(metric),
                unit: Some(canonical),
                quality: None,
            }
        }
        Err(MetricContractError::UnknownAlias(_))
        | Err(MetricContractError::QuantityMismatch { .. }) => PreparedIngestValue {
            val: Some(raw_val),
            unit: None,
            quality: Some(QUALITY_UNIT_UNDECLARED.into()),
        },
        Err(MetricContractError::UnsupportedQuantity(_)) => PreparedIngestValue {
            val: Some(raw_val),
            unit: None,
            quality: Some(QUALITY_UNIT_UNDECLARED.into()),
        },
        Err(MetricContractError::Invalid(_)) => PreparedIngestValue {
            val: Some(raw_val),
            unit: None,
            quality: Some(QUALITY_UNIT_UNDECLARED.into()),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fifty_f_and_ten_c_both_store_ten_c() {
        let c = MetricUnitsContract::load_embedded().expect("contract");
        let ctx = SampleDeclaredContext {
            role: Some("oa_t"),
            ..Default::default()
        };
        let f = prepare_numeric_sample(
            &c,
            50.0,
            PointMapBinding::default(),
            SampleDeclaredContext {
                sample_unit: Some("degF"),
                ..ctx
            },
        );
        let si = prepare_numeric_sample(
            &c,
            10.0,
            PointMapBinding::default(),
            SampleDeclaredContext {
                sample_unit: Some("degC"),
                ..ctx
            },
        );
        assert_eq!(f.unit.as_deref(), Some("degC"));
        assert_eq!(si.unit.as_deref(), Some("degC"));
        assert!((f.val.unwrap() - si.val.unwrap()).abs() < 1e-9);
        assert!((f.val.unwrap() - 10.0).abs() < 1e-9);
    }

    #[test]
    fn missing_unit_is_unit_undeclared_without_value_change() {
        let c = MetricUnitsContract::load_embedded().expect("contract");
        let raw = 70.0;
        let out = prepare_numeric_sample(
            &c,
            raw,
            PointMapBinding::default(),
            SampleDeclaredContext {
                role: Some("sat"),
                ..Default::default()
            },
        );
        assert_eq!(out.val, Some(raw));
        assert_eq!(out.quality.as_deref(), Some(QUALITY_UNIT_UNDECLARED));
    }

    #[test]
    fn overlay_beats_nf_tag_in_resolution() {
        let unit = resolve_declared_source_unit(
            PointMapBinding {
                unit: Some("degC"),
                source_unit: Some("degF"),
                quantity: Some("absolute_temperature"),
            },
            SampleDeclaredContext {
                role: Some("sat"),
                ..Default::default()
            },
        );
        assert_eq!(unit.as_deref(), Some("degC"));
    }
}
