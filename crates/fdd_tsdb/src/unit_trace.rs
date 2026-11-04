//! Unit binding trace for historian / UI readback (#1513).

use fdd_core::units_contract::MetricUnitsContract;

use crate::ingest_si::{PointMapBinding, SampleDeclaredContext, QUALITY_UNIT_UNDECLARED};

pub const UNIT_ASSESSED: &str = "assessed";
pub const UNIT_NOT_ASSESSED: &str = "not_assessed";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnitBindingTrace {
    pub declared_unit: Option<String>,
    pub source_unit: Option<String>,
    pub quantity: Option<String>,
    pub canonical_unit: Option<String>,
    pub storage_unit: Option<String>,
    pub unit_assessment: String,
    pub unit_assessment_reason: Option<String>,
}

fn non_empty(s: Option<&str>) -> Option<&str> {
    s.map(str::trim).filter(|t| !t.is_empty())
}

/// Engineer-visible declared unit: overlay `unit`, then NF/source tag on the binding.
pub fn declared_unit_for_display(
    overlay_unit: Option<&str>,
    source_unit: Option<&str>,
) -> Option<String> {
    non_empty(overlay_unit)
        .or(non_empty(source_unit))
        .map(str::to_string)
}

/// Trace declared source unit, canonical storage unit, and assessment for one series binding.
pub fn trace_unit_binding(
    contract: &MetricUnitsContract,
    role: Option<&str>,
    overlay_unit: Option<&str>,
    source_unit: Option<&str>,
    quantity: Option<&str>,
    storage_unit: Option<&str>,
    sample_quality: Option<&str>,
) -> UnitBindingTrace {
    let declared = declared_unit_for_display(overlay_unit, source_unit);
    let qty = non_empty(quantity).map(str::to_string).or_else(|| {
        role.and_then(fdd_core::quantity_for_sql_role)
            .map(str::to_string)
    });

    if non_empty(sample_quality) == Some(QUALITY_UNIT_UNDECLARED) {
        let canonical_unit = qty
            .as_deref()
            .and_then(|q| contract.canonical_unit(q).ok())
            .map(str::to_string);
        return UnitBindingTrace {
            declared_unit: declared,
            source_unit: source_unit.map(str::to_string),
            quantity: qty,
            canonical_unit,
            storage_unit: storage_unit.map(str::to_string),
            unit_assessment: UNIT_NOT_ASSESSED.into(),
            unit_assessment_reason: Some("unit_undeclared".into()),
        };
    }

    let map = PointMapBinding {
        unit: non_empty(overlay_unit),
        source_unit: non_empty(source_unit),
        quantity: qty.as_deref(),
    };
    let ctx = SampleDeclaredContext {
        role,
        sample_unit: None,
        sample_source_unit: None,
        sample_quantity: None,
        csv_column_unit: None,
        unit_system: None,
    };
    let resolved_declared = crate::ingest_si::resolve_declared_source_unit(map, ctx);

    let canonical = match qty.as_deref() {
        Some(q) => contract.canonical_unit(q).ok().map(str::to_string),
        None => None,
    };

    if qty.is_none() {
        return UnitBindingTrace {
            declared_unit: declared,
            source_unit: source_unit.map(str::to_string),
            quantity: None,
            canonical_unit: None,
            storage_unit: storage_unit.map(str::to_string),
            unit_assessment: UNIT_NOT_ASSESSED.into(),
            unit_assessment_reason: Some("missing_quantity".into()),
        };
    }

    if resolved_declared.is_none() {
        return UnitBindingTrace {
            declared_unit: declared,
            source_unit: source_unit.map(str::to_string),
            quantity: qty,
            canonical_unit: canonical,
            storage_unit: storage_unit.map(str::to_string),
            unit_assessment: UNIT_NOT_ASSESSED.into(),
            unit_assessment_reason: Some("missing_declaration".into()),
        };
    }

    let Some(canonical_unit) = canonical.clone() else {
        return UnitBindingTrace {
            declared_unit: declared,
            source_unit: source_unit.map(str::to_string),
            quantity: qty,
            canonical_unit: None,
            storage_unit: storage_unit.map(str::to_string),
            unit_assessment: UNIT_NOT_ASSESSED.into(),
            unit_assessment_reason: Some("unsupported_quantity".into()),
        };
    };

    let storage = non_empty(storage_unit);
    if storage.is_none() {
        return UnitBindingTrace {
            declared_unit: declared,
            source_unit: source_unit.map(str::to_string),
            quantity: qty,
            canonical_unit: Some(canonical_unit),
            storage_unit: None,
            unit_assessment: UNIT_NOT_ASSESSED.into(),
            unit_assessment_reason: Some("legacy_unconverted".into()),
        };
    }

    if storage == Some(canonical_unit.as_str()) {
        return UnitBindingTrace {
            declared_unit: declared,
            source_unit: source_unit.map(str::to_string),
            quantity: qty,
            canonical_unit: Some(canonical_unit),
            storage_unit: storage.map(str::to_string),
            unit_assessment: UNIT_ASSESSED.into(),
            unit_assessment_reason: None,
        };
    }

    UnitBindingTrace {
        declared_unit: declared,
        source_unit: source_unit.map(str::to_string),
        quantity: qty,
        canonical_unit: Some(canonical_unit),
        storage_unit: storage.map(str::to_string),
        unit_assessment: UNIT_NOT_ASSESSED.into(),
        unit_assessment_reason: Some("storage_not_canonical".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inwc_declared_converts_to_pa_storage_is_assessed() {
        let contract = MetricUnitsContract::load_embedded().expect("contract");
        let trace = trace_unit_binding(
            &contract,
            Some("duct_static"),
            None,
            Some("inH2O"),
            Some("air_pressure"),
            Some("Pa"),
            None,
        );
        assert_eq!(trace.unit_assessment, UNIT_ASSESSED);
        assert_eq!(trace.declared_unit.as_deref(), Some("inH2O"));
        assert_eq!(trace.canonical_unit.as_deref(), Some("Pa"));
    }

    #[test]
    fn legacy_empty_storage_unit_is_not_assessed() {
        let contract = MetricUnitsContract::load_embedded().expect("contract");
        let trace = trace_unit_binding(
            &contract,
            Some("duct_static"),
            Some("inH2O"),
            None,
            Some("air_pressure"),
            None,
            None,
        );
        assert_eq!(trace.unit_assessment, UNIT_NOT_ASSESSED);
        assert_eq!(
            trace.unit_assessment_reason.as_deref(),
            Some("legacy_unconverted")
        );
    }

    #[test]
    fn missing_declaration_is_not_assessed() {
        let contract = MetricUnitsContract::load_embedded().expect("contract");
        let trace = trace_unit_binding(
            &contract,
            Some("duct_static"),
            None,
            None,
            Some("air_pressure"),
            Some("Pa"),
            None,
        );
        assert_eq!(trace.unit_assessment, UNIT_NOT_ASSESSED);
        assert_eq!(
            trace.unit_assessment_reason.as_deref(),
            Some("missing_declaration")
        );
    }

    #[test]
    fn one_inwc_is_contract_pa() {
        let contract = MetricUnitsContract::load_embedded().expect("contract");
        let pa = contract
            .convert_to_canonical("air_pressure", 1.0, "inH2O")
            .expect("convert");
        assert!((pa - 248.84).abs() < 1e-6);
        assert!(
            (pa - 249.0889).abs() > 0.2,
            "product uses PA_PER_IN_WC 248.84"
        );
    }
}
