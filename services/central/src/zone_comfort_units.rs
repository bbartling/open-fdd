//! Zone comfort band limits in the binding's declared temperature unit.

use fdd_core::units::{fahrenheit_to_celsius, unit_is_celsius, unit_is_fahrenheit_or_unset};

/// True when the binding declares an absolute temperature unit (not silent default).
pub fn zone_temperature_unit_assessable(unit: Option<&str>) -> bool {
    let raw = unit.map(str::trim).unwrap_or("");
    !raw.is_empty() && (unit_is_celsius(raw) || unit_is_fahrenheit_or_unset(raw))
}

/// Comfort band edges from UI/session °F into the sample's declared unit.
pub fn comfort_band_in_unit(lo_f: f64, hi_f: f64, unit: Option<&str>) -> Option<(f64, f64)> {
    if !zone_temperature_unit_assessable(unit) {
        return None;
    }
    let raw = unit.map(str::trim).unwrap_or("");
    if unit_is_celsius(raw) {
        Some((fahrenheit_to_celsius(lo_f), fahrenheit_to_celsius(hi_f)))
    } else {
        Some((lo_f, hi_f))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn celsius_band_from_fahrenheit_sliders() {
        let (lo, hi) = comfort_band_in_unit(70.0, 75.0, Some("degC")).expect("band");
        assert!((lo - 21.111111).abs() < 0.01);
        assert!((hi - 23.888889).abs() < 0.01);
    }

    #[test]
    fn empty_unit_not_assessable() {
        assert!(!zone_temperature_unit_assessable(None));
        assert!(!zone_temperature_unit_assessable(Some("  ")));
    }
}
