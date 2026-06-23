//! Protocol-agnostic Haystack assignment layer.
//!
//! This is the key design rule:
//!
//! Driver points are never bound directly to FDD equations or CDL algorithms.
//! Driver points are assigned to Haystack point refs. Fault equations,
//! historian storage, external refs, and algorithms bind to Haystack refs.
//!
//! That makes BACnet, Modbus, JSON API, and Haystack-native points
//! interchangeable for algorithms and FDD rules.

pub const ASSIGNMENTS_JSON: &str = r#"{
  "ok":true,
  "model":"haystack-only",
  "assignment_policy":"AI agents assign all driver points, rules, storage refs, external refs, and algorithms through Haystack IDs.",
  "points":[
    {
      "haystack_id":"point:sat",
      "dis":"Device 5007 Discharge Air Temp",
      "kind":"sensor",
      "equip_ref":"equip:5007",
      "unit":"degF",
      "driver_bindings":[
        {"driver":"bacnet","ref":"bacnet:5007:analog-input:1192","object_id":[0,1192],"priority":1}
      ],
      "storage_ref":"arrow://hvac/duct_t",
      "external_refs":[
        {"system":"site-docs","ref":"5007/DischargeAirTemp"}
      ]
    },
    {
      "haystack_id":"point:actuator-0",
      "dis":"Device 5007 ACTUATOR-0",
      "kind":"cmd",
      "equip_ref":"equip:5007",
      "unit":"%",
      "driver_bindings":[
        {"driver":"bacnet","ref":"bacnet:5007:analog-output:2466","object_id":[1,2466],"priority":1}
      ],
      "storage_ref":"arrow://hvac/actuator_0",
      "external_refs":[{"system":"site-docs","ref":"5007/ACTUATOR-0"}]
    },
    {
      "haystack_id":"point:sat-sp",
      "dis":"Device 5007 SAT Setpoint (bench fixture)",
      "kind":"setpoint",
      "equip_ref":"equip:5007",
      "unit":"degF",
      "driver_bindings":[
        {"driver":"bacnet","ref":"bacnet:5007:analog-value:1175","object_id":[2,1175],"priority":1}
      ],
      "storage_ref":"arrow://hvac/sat_sp",
      "external_refs":[{"system":"site-docs","ref":"5007/SAT-SP"}]
    },
    {
      "haystack_id":"point:chwst",
      "dis":"CHW Plant Supply Temp",
      "kind":"sensor",
      "equip_ref":"equip:plant",
      "unit":"degF",
      "driver_bindings":[
        {"driver":"modbus","ref":"modbus:tcp:1:40001","register":40001,"priority":1}
      ],
      "storage_ref":"arrow://plant/chwst",
      "external_refs":[{"system":"plant-json","ref":"chw.supply_temp"}]
    },
    {
      "haystack_id":"point:oat",
      "dis":"Outside Air Temp",
      "kind":"weather",
      "equip_ref":"site:demo",
      "unit":"degF",
      "driver_bindings":[
        {"driver":"json_api","ref":"json:openweather-oat:main.temp","priority":1},
        {"driver":"haystack","ref":"@weather-oat","priority":2}
      ],
      "storage_ref":"arrow://weather/oat",
      "external_refs":[{"system":"openweathermap","ref":"main.temp"}]
    }
  ],
  "fault_equation_bindings":[
    {
      "rule_id":"sat_deviation",
      "engine":"datafusion_sql",
      "inputs":{"sat":"point:sat","sat_sp":"point:sat-sp","fan_cmd":"point:fan-cmd"},
      "storage_table":"hvac",
      "output_ref":"fault:sat_deviation"
    },
    {
      "rule_id":"duct_static_deviation",
      "engine":"datafusion_sql",
      "inputs":{"duct_static":"point:duct-static","duct_static_sp":"point:duct-static-sp","fan_cmd":"point:fan-cmd"},
      "storage_table":"hvac",
      "output_ref":"fault:duct_static_deviation"
    }
  ],
  "algorithm_bindings":[
    {
      "algorithm_id":"g36_ahu_vav_trim_respond",
      "engine":"cdl",
      "protocol_agnostic":true,
      "inputs":{
        "zone_requests":"haystack://equip:5007/zone_requests",
        "duct_static":"point:duct-static",
        "sat":"point:sat"
      },
      "outputs":{
        "duct_static_sp":"point:duct-static-sp",
        "sat_sp":"point:sat-sp"
      },
      "allowed_driver_outputs":["bacnet","modbus","json_api","haystack"],
      "write_policy":"human-approved integrator JWT required"
    }
  ]
}"#;

pub fn assignments_json() -> &'static str {
    ASSIGNMENTS_JSON
}

pub fn save_assignment_json() -> &'static str {
    r#"{"ok":true,"saved":true,"scope":"haystack-assignment","path":"workspace/data/model/assignments.json"}"#
}

pub fn resolve_json() -> &'static str {
    r#"{"ok":true,"haystack_id":"point:sat","selected_binding":{"driver":"bacnet","ref":"bacnet:5007:analog-input:1192"},"storage_ref":"arrow://hvac/sat"}"#
}

pub fn algorithm_bindings_json() -> &'static str {
    r#"{"ok":true,"algorithm_id":"g36_ahu_vav_trim_respond","protocol_agnostic":true,"bindings":{"inputs":{"zone_requests":"haystack://equip:5007/zone_requests","duct_static":"point:duct-static","sat":"point:sat"},"outputs":{"duct_static_sp":"point:duct-static-sp","sat_sp":"point:sat-sp"}}}"#
}
