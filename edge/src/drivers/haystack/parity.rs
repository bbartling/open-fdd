//! Future BACnet-vs-Haystack parity comparator (unit tests only — not run against live field hardware).

use serde_json::{json, Value};

#[derive(Debug, Clone)]
pub struct ParityTolerance {
    pub temperature_f: f64,
    pub humidity_pct: f64,
    pub timestamp_skew_seconds: i64,
}

impl Default for ParityTolerance {
    fn default() -> Self {
        Self {
            temperature_f: 1.0,
            humidity_pct: 5.0,
            timestamp_skew_seconds: 120,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ParityInput {
    pub equipment_id: String,
    pub role: String,
    pub bacnet_object: String,
    pub haystack_id: String,
    pub bacnet_value: f64,
    pub haystack_value: f64,
    pub bacnet_timestamp: i64,
    pub haystack_timestamp: i64,
    pub unit: String,
}

pub fn compare_reading(input: &ParityInput, tol: &ParityTolerance) -> Value {
    let abs_delta = (input.bacnet_value - input.haystack_value).abs();
    let ts_delta = (input.bacnet_timestamp - input.haystack_timestamp).abs();
    let tolerance = if input.unit.contains('%') || input.role.ends_with("_h") {
        tol.humidity_pct
    } else {
        tol.temperature_f
    };
    let pass = abs_delta <= tolerance && ts_delta <= tol.timestamp_skew_seconds as i64;
    json!({
        "equipment_id": input.equipment_id,
        "role": input.role,
        "bacnet_object": input.bacnet_object,
        "haystack_id": input.haystack_id,
        "bacnet_value": input.bacnet_value,
        "haystack_value": input.haystack_value,
        "absolute_delta": abs_delta,
        "tolerance": tolerance,
        "pass": pass,
        "bacnet_timestamp": input.bacnet_timestamp,
        "haystack_timestamp": input.haystack_timestamp,
        "timestamp_delta_seconds": ts_delta
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parity_pass_within_temperature_tolerance() {
        let input = ParityInput {
            equipment_id: "equip:demo".into(),
            role: "oa_t".into(),
            bacnet_object: "analog-input,1001".into(),
            haystack_id: "point:oa-t".into(),
            bacnet_value: 62.0,
            haystack_value: 62.5,
            bacnet_timestamp: 1_000,
            haystack_timestamp: 1_030,
            unit: "°F".into(),
        };
        let out = compare_reading(&input, &ParityTolerance::default());
        assert_eq!(out["pass"], true);
    }

    #[test]
    fn parity_fail_outside_humidity_tolerance() {
        let input = ParityInput {
            equipment_id: "equip:demo".into(),
            role: "oa_h".into(),
            bacnet_object: "analog-input,1002".into(),
            haystack_id: "point:oa-h".into(),
            bacnet_value: 45.0,
            haystack_value: 55.0,
            bacnet_timestamp: 1_000,
            haystack_timestamp: 1_010,
            unit: "%RH".into(),
        };
        let out = compare_reading(&input, &ParityTolerance::default());
        assert_eq!(out["pass"], false);
    }
}
