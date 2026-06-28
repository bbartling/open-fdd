//! DataFusion SQL fault detection — runs saved rules against historian tables.

use crate::fdd::execution;
use crate::fdd::rules;
use serde_json::{json, Value};

pub fn list_rules_response() -> Value {
    rules::list_rules()
}

pub fn save_rule_response(payload: &Value, actor: &str) -> Value {
    rules::save_rule(payload, actor)
}

pub fn batch_run_response() -> Value {
    let evaluable = rules::evaluable_rules();
    if evaluable.is_empty() {
        return json!({
            "ok": true,
            "engine": "DataFusion",
            "rules_run": 0,
            "faults": [],
            "message": "no active rules with SQL configured"
        });
    }

    let mut faults = Vec::new();
    let mut rules_run = 0u64;
    for rule in evaluable {
        let sql = rule.get("sql").and_then(|v| v.as_str()).unwrap_or("");
        if sql.trim().is_empty() {
            continue;
        }
        let confirmation = rule
            .get("confirmation_seconds")
            .and_then(|v| v.as_i64())
            .unwrap_or(300);
        let params = rule.get("params").cloned().unwrap_or(json!({}));
        let result = execution::run_rule_sql_from_historian(sql, confirmation, &params);
        rules_run += 1;
        if result.get("ok").and_then(|v| v.as_bool()) != Some(true) {
            continue;
        }
        if let Some(rows) = result.get("rows").and_then(|v| v.as_array()) {
            for row in rows {
                let fault = row.get("fault_raw").and_then(|v| v.as_bool()) == Some(true)
                    || row.get("confirmed_fault").and_then(|v| v.as_bool()) == Some(true)
                    || row.get("fault_code").is_some();
                if fault {
                    faults.push(json!({
                        "rule_id": rule.get("rule_id"),
                        "equipment_id": row.get("equipment_id"),
                        "fault_code": rule.get("output_fault_code").or_else(|| rule.get("fault_code")),
                        "severity": rule.get("severity"),
                        "sample_count": 1,
                        "row": row
                    }));
                }
            }
        }
    }

    json!({
        "ok": true,
        "engine": "DataFusion",
        "rules_run": rules_run,
        "faults": faults
    })
}

pub fn run_fdd_response(payload: &Value) -> Value {
    let sql = payload.get("sql").and_then(|v| v.as_str()).unwrap_or("");
    if sql.trim().is_empty() {
        return json!({"ok": false, "error": "sql required"});
    }
    let confirmation = payload
        .get("confirmation_seconds")
        .and_then(|v| v.as_i64())
        .unwrap_or(300);
    let params = payload.get("params").cloned().unwrap_or(json!({}));
    execution::run_rule_sql_from_historian(sql, confirmation, &params)
}
