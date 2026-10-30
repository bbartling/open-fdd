//! Zone comfort band limits (session parameters in °C).

use fdd_core::units::{celsius_to_fahrenheit, unit_is_celsius, unit_is_fahrenheit_or_unset};

/// True when the binding declares an absolute temperature unit (not silent default).
pub fn zone_temperature_unit_assessable(unit: Option<&str>) -> bool {
    let raw = unit.map(str::trim).unwrap_or("");
    !raw.is_empty() && (unit_is_celsius(raw) || unit_is_fahrenheit_or_unset(raw))
}

/// Comfort band edges from UI/session °C into the sample's declared unit for assessability.
pub fn comfort_band_in_unit(lo_c: f64, hi_c: f64, unit: Option<&str>) -> Option<(f64, f64)> {
    if !zone_temperature_unit_assessable(unit) {
        return None;
    }
    let raw = unit.map(str::trim).unwrap_or("");
    if unit_is_celsius(raw) {
        Some((lo_c, hi_c))
    } else {
        Some((celsius_to_fahrenheit(lo_c), celsius_to_fahrenheit(hi_c)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn celsius_band_unchanged() {
        let (lo, hi) = comfort_band_in_unit(21.111111, 23.888889, Some("degC")).expect("band");
        assert!((lo - 21.111111).abs() < 0.01);
        assert!((hi - 23.888889).abs() < 0.01);
    }

    #[test]
    fn empty_unit_not_assessable() {
        assert!(!zone_temperature_unit_assessable(None));
        assert!(!zone_temperature_unit_assessable(Some("  ")));
    }
}
