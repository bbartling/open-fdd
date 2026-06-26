//! Deterministic Haystack fixture grid for CI and disabled-mode demos.
//!
//! Does not hardcode BACnet device 5007 — use local smoke profile examples for parity mapping.

use serde_json::{json, Value};

pub fn fixture_grid() -> Value {
    json!({
        "meta": { "ver": "3.0", "mode": "fixture" },
        "cols": [
            {"name": "id"},
            {"name": "dis"},
            {"name": "site"},
            {"name": "equip"},
            {"name": "point"},
            {"name": "sensor"},
            {"name": "kind"},
            {"name": "unit"},
            {"name": "curVal"}
        ],
        "rows": [
            {"id": "site:demo", "dis": "Demo Site", "site": "M"},
            {"id": "equip:demo-ahu", "dis": "Demo AHU", "equip": "M", "siteRef": "site:demo", "ahu": "M"},
            {"id": "point:oa-t", "dis": "Outside Air Temp", "point": "M", "sensor": "M", "kind": "Number", "unit": "°F", "curVal": 62.0, "equipRef": "equip:demo-ahu", "fddInput": "oa_t"},
            {"id": "point:oa-h", "dis": "Outside Air Humidity", "point": "M", "sensor": "M", "kind": "Number", "unit": "%RH", "curVal": 45.0, "equipRef": "equip:demo-ahu", "fddInput": "oa_h"},
            {"id": "point:duct-t", "dis": "Discharge Air Temp", "point": "M", "sensor": "M", "kind": "Number", "unit": "°F", "curVal": 55.0, "equipRef": "equip:demo-ahu", "fddInput": "duct_t"},
            {"id": "point:zn-t", "dis": "Zone Temp", "point": "M", "sensor": "M", "kind": "Number", "unit": "°F", "curVal": 72.0, "equipRef": "equip:demo-ahu", "fddInput": "zn_t"}
        ]
    })
}

pub fn fixture_about() -> Value {
    json!({
        "serverName": "open-fdd-haystack-fixture",
        "haystackVersion": "3.0",
        "mode": "fixture",
        "vendorName": "Open-FDD",
        "productName": "Haystack fixture gateway"
    })
}

pub fn fixture_ops() -> Value {
    json!({
        "ops": ["about", "ops", "read", "nav"],
        "mode": "fixture"
    })
}
