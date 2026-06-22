//! Bench 5007 point definitions and alias mapping.

use bacnet_types::enums::ObjectType;
use serde_json::Value;

#[derive(Clone, Debug)]
pub struct BenchPointSpec {
    pub point_id: &'static str,
    pub fdd_input: &'static str,
    pub column: &'static str,
    pub device_instance: u32,
    pub object_type: ObjectType,
    pub object_instance: u32,
    pub simulated_default: f64,
}

pub fn bench5007_points() -> Vec<BenchPointSpec> {
    vec![
        BenchPointSpec {
            point_id: "bacnet:5007:analog-input:1173",
            fdd_input: "oa-t",
            column: "oa_t",
            device_instance: 5007,
            object_type: ObjectType::ANALOG_INPUT,
            object_instance: 1173,
            simulated_default: 72.0,
        },
        BenchPointSpec {
            point_id: "bacnet:5007:analog-input:1168",
            fdd_input: "oa-h",
            column: "oa_h",
            device_instance: 5007,
            object_type: ObjectType::ANALOG_INPUT,
            object_instance: 1168,
            simulated_default: 44.0,
        },
        BenchPointSpec {
            point_id: "bacnet:5007:analog-input:1192",
            fdd_input: "duct-t",
            column: "duct_t",
            device_instance: 5007,
            object_type: ObjectType::ANALOG_INPUT,
            object_instance: 1192,
            simulated_default: 68.0,
        },
        BenchPointSpec {
            point_id: "bacnet:5007:analog-input:10014",
            fdd_input: "stat_zn-t",
            column: "stat_zn_t",
            device_instance: 5007,
            object_type: ObjectType::ANALOG_INPUT,
            object_instance: 10014,
            simulated_default: 71.0,
        },
    ]
}

pub fn resolve_fdd_column(input: &str) -> Option<&'static str> {
    bench5007_points()
        .into_iter()
        .find(|p| p.fdd_input == input)
        .map(|p| p.column)
}

pub fn point_from_registry_value(v: &Value) -> Option<(String, f64)> {
    let fdd = v.get("fdd_input")?.as_str()?;
    let value = v
        .get("present_value")
        .or_else(|| v.get("value"))
        .and_then(|pv| pv.as_f64().or_else(|| pv.get("value").and_then(|x| x.as_f64())))?;
    Some((fdd.to_string(), value))
}
