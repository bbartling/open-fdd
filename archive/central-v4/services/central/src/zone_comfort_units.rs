//! Zone comfort band limits use the canonical stored temperature (°C).

use fdd_core::units_contract::MetricUnitsContract;

/// True when the binding declares an absolute temperature unit (not silent default).
pub fn zone_temperature_unit_assessable(unit: Option<&str>) -> bool {
    let raw = unit.map(str::trim).unwrap_or("");
    !raw.is_empty()
        && MetricUnitsContract::load_embedded()
            .and_then(|contract| contract.resolve_alias(raw).map(str::to_owned))
            .is_ok_and(|quantity| quantity == "absolute_temperature")
}

/// Keep the SI comfort band in canonical storage units after validating source metadata.
/// Samples are converted once at ingest; a retained `degF` source label does not
/// mean the stored `sample.val` is still Fahrenheit.
pub fn comfort_band_si_for_source_unit(
    lo_c: f64,
    hi_c: f64,
    source_unit: Option<&str>,
) -> Option<(f64, f64)> {
    if !lo_c.is_finite() || !hi_c.is_finite() || lo_c > hi_c {
        return None;
    }
    if !zone_temperature_unit_assessable(source_unit) {
        return None;
    }
    Some((lo_c, hi_c))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_fahrenheit_does_not_convert_canonical_band_twice() {
        let band = comfort_band_si_for_source_unit(21.0, 24.0, Some("degF")).expect("band");
        assert_eq!(band, (21.0, 24.0));
    }

    #[test]
    fn si_source_keeps_band_canonical() {
        assert_eq!(
            comfort_band_si_for_source_unit(21.0, 24.0, Some("degC")),
            Some((21.0, 24.0))
        );
    }

    #[test]
    fn empty_unit_not_assessable() {
        assert!(!zone_temperature_unit_assessable(None));
        assert!(!zone_temperature_unit_assessable(Some("  ")));
        assert!(comfort_band_si_for_source_unit(21.0, 24.0, Some("unknown")).is_none());
        assert!(comfort_band_si_for_source_unit(24.0, 21.0, Some("degC")).is_none());
    }
}
