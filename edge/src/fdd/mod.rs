//! Fault detection layer.
//!
//! Wave-X default: registry / session_config / wires without DataFusion.
//! `legacy-datafusion` restores Parquet/DF SQL execution.

pub mod confirmation;
pub mod registry_api;
pub mod rules;
pub mod session_config;
pub mod sql_safety;
pub mod wires;

#[cfg(feature = "legacy-datafusion")]
pub mod datafusion_sql;
#[cfg(feature = "legacy-datafusion")]
pub mod execution;

#[cfg(not(feature = "legacy-datafusion"))]
pub mod datafusion_sql {
    use serde_json::{json, Value};

    pub fn list_rules_response() -> Value {
        crate::fdd::rules::list_rules()
    }
    pub fn save_rule_response(payload: &Value, actor: &str) -> Value {
        crate::fdd::rules::save_rule(payload, actor)
    }
    pub fn patch_rule_response(rule_id: &str, patch: &Value, actor: &str) -> Value {
        crate::fdd::rules::patch_rule(rule_id, patch, actor)
    }
    pub fn batch_run_response() -> Value {
        json!({
            "ok": false,
            "engine": "postgres-sql",
            "error": "Wave-X: DataFusion batch FDD retired; use Timescale sql/fdd",
        })
    }
    pub fn run_fdd_response(payload: &Value) -> Value {
        let _ = payload;
        json!({
            "ok": false,
            "engine": "postgres-sql",
            "error": "Wave-X: DataFusion FDD retired; use Timescale sql/fdd",
        })
    }
}

#[cfg(not(feature = "legacy-datafusion"))]
pub mod execution {
    use serde_json::{json, Value};

    pub fn schema_tables_json() -> Value {
        json!({
            "ok": true,
            "dialect": "postgres-sql",
            "engine": "timescale",
            "tables": [],
            "note": "Wave-X: DataFusion schema retired",
        })
    }

    pub fn fdd_inputs_json() -> Value {
        // Keep commissioning / package validation aware of canonical roles even
        // without DataFusion SessionContext (Wave-X Timescale product path).
        json!({
            "ok": true,
            "engine": "timescale",
            "fdd_inputs": [
                {"id":"oa_t","label":"OA temperature","unit":"degF","equipment_types":["ahu"]},
                {"id":"oa_h","label":"Outside Air Humidity","unit":"%RH","equipment_types":["ahu"]},
                {"id":"sat","label":"Supply Air Temp","unit":"degF","equipment_types":["ahu","vav"]},
                {"id":"duct_t","label":"Discharge/Duct Temp","unit":"degF","equipment_types":["ahu","vav"]},
                {"id":"zn_t","label":"Zone Temp","unit":"degF","equipment_types":["vav","zone"]},
                {"id":"sat_sp","label":"SAT Setpoint","unit":"degF","equipment_types":["ahu"]},
                {"id":"fan_cmd","label":"Fan Command","unit":"bool","equipment_types":["ahu"]},
                {"id":"occ","label":"Occupancy","unit":"bool","equipment_types":["ahu","zone"]}
            ]
        })
    }

    pub fn equipment_types_json() -> Value {
        json!({
            "ok": true,
            "engine": "timescale",
            "equipment_types": [
                {"id":"ahu","label":"Air Handling Unit"},
                {"id":"vav","label":"VAV Box"},
                {"id":"plant","label":"Central Plant"}
            ]
        })
    }

    pub fn builder_to_sql(builder: &Value) -> String {
        let _ = builder;
        String::new()
    }

    pub fn run_rule_sql_from_historian(
        _sql: &str,
        _confirmation_seconds: i64,
        _params: &Value,
    ) -> Value {
        json!({
            "ok": false,
            "engine": "postgres-sql",
            "error": "Wave-X: DataFusion SessionContext retired",
        })
    }

    pub fn run_rule_sql(sql: &str, confirmation_seconds: i64, params: &Value) -> Value {
        run_rule_sql_from_historian(sql, confirmation_seconds, params)
    }
}
