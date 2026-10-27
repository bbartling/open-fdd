//! Sensor sweep quantity catalog and flatline eligibility (role + unit metadata).
//!
//! Unit/quantity resolution is intentionally small and binding-driven so the Wave 2c
//! point overlay can supply overrides without changing call sites.

/// Hard range / spike limits per physical quantity (imperial-f-v1 pack ABI).
#[derive(Debug, Clone, Copy)]
pub struct QuantityLimits {
    pub lo: f64,
    pub hi: f64,
    pub spike: f64,
}

const TEMP: QuantityLimits = QuantityLimits {
    lo: -60.0,
    hi: 130.0,
    spike: 36.0,
};
const TEMP_ZONE: QuantityLimits = QuantityLimits {
    lo: 40.0,
    hi: 100.0,
    spike: 12.0,
};
const TEMP_MAT: QuantityLimits = QuantityLimits {
    lo: -20.0,
    hi: 110.0,
    spike: 25.0,
};
const TEMP_SAT: QuantityLimits = QuantityLimits {
    lo: 30.0,
    hi: 150.0,
    spike: 40.0,
};
const TEMP_CHW_S: QuantityLimits = QuantityLimits {
    lo: 30.0,
    hi: 80.0,
    spike: 20.0,
};
const TEMP_CHW_R: QuantityLimits = QuantityLimits {
    lo: 30.0,
    hi: 90.0,
    spike: 20.0,
};
const TEMP_HW: QuantityLimits = QuantityLimits {
    lo: 40.0,
    hi: 220.0,
    spike: 60.0,
};
const RH: QuantityLimits = QuantityLimits {
    lo: 0.0,
    hi: 100.0,
    spike: 25.0,
};
const AIR_P: QuantityLimits = QuantityLimits {
    lo: -1.0,
    hi: 8.0,
    spike: 2.0,
};

fn norm_token(s: &str) -> String {
    s.trim()
        .to_ascii_lowercase()
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect()
}

/// Quantity id from `sql/contract/metric_units.json` (subset used on the sweep path).
pub fn quantity_for_sql_role(role: &str) -> Option<&'static str> {
    match role.trim() {
        "oa_t" => Some("absolute_temperature"),
        "rat" | "zone_t" => Some("absolute_temperature"),
        "mat" => Some("absolute_temperature"),
        "sat" => Some("absolute_temperature"),
        "chw_supply_t" | "chw_return_t" | "hw_supply_t" | "hw_return_t" => {
            Some("absolute_temperature")
        }
        "oa_h" | "ra_h" | "zone_rh" | "zone_h" | "ma_h" | "sa_h" => Some("relative_humidity"),
        "duct_static" => Some("air_pressure"),
        _ => None,
    }
}

/// Haystack cookbook slug → quantity (pandas oracle columns).
pub fn quantity_for_haystack_role(slug: &str) -> Option<&'static str> {
    let s = slug.trim();
    if s.is_empty() {
        return None;
    }
    if s.contains("humid") || s.ends_with("-rh") {
        return Some("relative_humidity");
    }
    if s.contains("static") || s.contains("pressure") || s.ends_with("-dp") {
        return Some("air_pressure");
    }
    if s.contains("temp") || s.contains("wetbulb") || s.contains("dewpoint") {
        return Some("absolute_temperature");
    }
    None
}

/// Limits for a sweep quantity (per-quantity, not per site).
pub fn limits_for_quantity(quantity: &str) -> Option<QuantityLimits> {
    match quantity {
        "absolute_temperature" => Some(TEMP),
        "relative_humidity" => Some(RH),
        "air_pressure" => Some(AIR_P),
        _ => None,
    }
}

/// Role-specific temperature limits (Haystack catalog); humidity/pressure use quantity defaults.
pub fn limits_for_haystack_role(slug: &str) -> Option<QuantityLimits> {
    match slug.trim() {
        "outside-air-temp" => Some(TEMP),
        "return-air-temp" | "zone-air-temp" => Some(TEMP_ZONE),
        "mixed-air-temp" => Some(TEMP_MAT),
        "discharge-air-temp" => Some(TEMP_SAT),
        "chilled-water-supply-temp" => Some(TEMP_CHW_S),
        "chilled-water-return-temp" => Some(TEMP_CHW_R),
        "hot-water-supply-temp" | "hot-water-return-temp" => Some(TEMP_HW),
        "outside-air-humidity"
        | "return-air-humidity"
        | "zone-air-humidity"
        | "zone-humidity"
        | "mixed-air-humidity"
        | "supply-air-humidity" => Some(RH),
        "duct-static-pressure" => Some(AIR_P),
        _ => {
            let q = quantity_for_haystack_role(slug)?;
            limits_for_quantity(q)
        }
    }
}

/// Expected-constant points (status, command, setpoint, mode) are not flatline targets.
pub fn is_expected_constant_role(role: &str) -> bool {
    let r = norm_token(role);
    if r.is_empty() {
        return false;
    }
    if r.ends_with("sp") || r.contains("setpoint") {
        return true;
    }
    if r.contains("status") || r.ends_with("cmd") || r.contains("command") {
        return true;
    }
    if r == "occmode" || r.contains("occupied") || r.contains("occupancy") {
        return true;
    }
    if r == "loopenabled" {
        return true;
    }
    false
}

/// True when the role is an analog sensor quantity and a declared unit is present.
///
/// Empty unit with no override → not assessed (never infer from magnitude).
pub fn sweep_assessable_sql_role(role: &str, unit: Option<&str>) -> bool {
    if is_expected_constant_role(role) {
        return false;
    }
    let Some(quantity) = quantity_for_sql_role(role) else {
        return false;
    };
    unit_declares_quantity(unit, quantity)
}

fn unit_declares_quantity(unit: Option<&str>, quantity: &str) -> bool {
    let raw = unit.map(str::trim).unwrap_or("");
    if raw.is_empty() {
        return false;
    }
    let t = norm_token(raw);
    match quantity {
        "absolute_temperature" => {
            matches!(
                t.as_str(),
                "f" | "degf" | "fahrenheit" | "c" | "degc" | "celsius"
            )
        }
        "relative_humidity" => {
            matches!(
                t.as_str(),
                "pct" | "percent" | "rh" | "percentrelativehumidity" | "%"
            ) || raw.contains('%')
        }
        "air_pressure" => {
            matches!(t.as_str(), "inwc" | "inh2o" | "inw.c." | "pa" | "pascal")
                || raw.contains("w.c")
        }
        _ => false,
    }
}

/// Flatline/stale sweeps skip duct static (rests at ~0 when off).
pub fn flatline_quantity_allowed(quantity: &str) -> bool {
    quantity != "air_pressure"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn humidity_sql_roles_map_to_relative_humidity() {
        assert_eq!(quantity_for_sql_role("ra_h"), Some("relative_humidity"));
        assert_eq!(quantity_for_sql_role("ma_h"), Some("relative_humidity"));
    }

    #[test]
    fn setpoint_not_flatline_eligible() {
        assert!(is_expected_constant_role("sat_sp"));
        assert!(is_expected_constant_role("fan_status"));
        assert!(!is_expected_constant_role("ra_h"));
    }

    #[test]
    fn no_unit_not_assessed() {
        assert!(!sweep_assessable_sql_role("ra_h", None));
        assert!(sweep_assessable_sql_role("ra_h", Some("%RH")));
    }
}
