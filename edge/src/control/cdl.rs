//! CDL algorithm facade.

pub const STATUS_JSON: &str = r#"{
  "engine":"open-control-engine CDL facade",
  "status":"ready",
  "algorithms":[
    {"id":"g36_ahu_vav_trim_respond","name":"G36 AHU/VAV Trim & Respond","status":"ready","inputs":["zone_requests","duct_static","sat"],"outputs":["duct_static_sp","sat_sp"]},
    {"id":"g36_sat_reset","name":"G36 SAT Reset","status":"ready","inputs":["oat","zone_load"],"outputs":["sat_sp"]}
  ]
}"#;

pub const SIM_JSON: &str = r#"{
  "sequence":"Guideline 36 AHU/VAV Trim & Respond",
  "inputs":{"zonesCalling":3,"ductStatic":1.2,"sat":55.2},
  "outputs":{"ductStaticSp":1.35,"satSp":54.0,"trimRespondAction":"respond"},
  "status":"simulated"
}"#;

pub fn status_json() -> &'static str {
    STATUS_JSON
}

pub fn simulate_json() -> &'static str {
    SIM_JSON
}
