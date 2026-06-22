//! DataFusion SQL fault detection facade.
//!
//! Production direction:
//! - register Apache Arrow RecordBatches as `hvac` tables in DataFusion.
//! - save SQL rules under `workspace/data/rules/`.
//! - run `/api/rules/batch` and persist results under `workspace/data/fdd/`.

pub const RULES_JSON: &str = r#"[
  {"id":"sat_deviation","name":"SAT Deviation Detector","engine":"datafusion_sql","enabled":true,"severity":"high"},
  {"id":"duct_static_deviation","name":"Duct Static Deviation","engine":"datafusion_sql","enabled":true,"severity":"medium"},
  {"id":"override_watch","name":"Supervisory Override Watch","engine":"bacnet_priority_array","enabled":true,"severity":"advisory"}
]"#;

pub const RESULT_JSON: &str = r#"{
  "engine":"Apache Arrow + DataFusion SQL (Rust production path)",
  "sql":"SELECT equip, CASE WHEN fan_cmd > 0 AND ABS(sat - sat_sp) > 10 THEN 'SAT_DEVIATION_HIGH' WHEN fan_cmd > 0 AND ABS(duct_static - duct_static_sp) > 0.5 THEN 'DUCT_STATIC_DEVIATION' ELSE 'OK' END AS fault_code, COUNT(*) AS sample_count FROM hvac WHERE fan_cmd > 0 GROUP BY equip, fault_code HAVING fault_code <> 'OK';",
  "faults":[
    {"equip":"AHU-1","fault_code":"SAT_DEVIATION_HIGH","severity":"high","sample_count":3,"max_abs_error":12.3},
    {"equip":"AHU-1","fault_code":"DUCT_STATIC_DEVIATION","severity":"medium","sample_count":1,"max_abs_error":0.60}
  ]
}"#;

pub fn rules_json() -> &'static str {
    RULES_JSON
}

pub fn result_json() -> &'static str {
    RESULT_JSON
}

pub fn save_json() -> &'static str {
    r#"{"ok":true,"saved":true,"engine":"datafusion_sql","path":"workspace/data/rules/rule-demo.json"}"#
}

pub fn batch_json() -> &'static str {
    r#"{"ok":true,"engine":"DataFusion","rules_run":2,"faults":[{"equip":"AHU-1","fault_code":"SAT_DEVIATION_HIGH","severity":"high","sample_count":3,"max_abs_error":12.3},{"equip":"AHU-1","fault_code":"DUCT_STATIC_DEVIATION","severity":"medium","sample_count":1,"max_abs_error":0.60}]}"#
}
