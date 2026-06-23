//! DataFusion SQL rule model persistence and lifecycle.

use crate::fdd::execution;
use crate::fdd::sql_safety;
use chrono::Utc;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;

pub fn rules_dir() -> PathBuf {
    workspace_dir().join("data/fdd_wires/rules")
}

pub fn list_rules() -> Value {
    ensure_dirs();
    let mut rules = Vec::new();
    if let Ok(entries) = fs::read_dir(rules_dir()) {
        for entry in entries.flatten() {
            if entry.path().extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            if let Ok(text) = fs::read_to_string(entry.path()) {
                if let Ok(rule) = serde_json::from_str::<Value>(&text) {
                    rules.push(rule);
                }
            }
        }
    }
    if rules.is_empty() {
        rules.push(default_oa_rule());
    }
    json!({"ok": true, "rules": rules})
}

pub fn get_rule(rule_id: &str) -> Value {
    let path = rules_dir().join(format!("{rule_id}.json"));
    if let Ok(text) = fs::read_to_string(&path) {
        if let Ok(rule) = serde_json::from_str::<Value>(&text) {
            return json!({"ok": true, "rule": rule});
        }
    }
    if rule_id == "oa_temp_out_of_range" {
        return json!({"ok": true, "rule": default_oa_rule()});
    }
    json!({"ok": false, "error": "rule not found", "rule_id": rule_id})
}

pub fn save_rule(payload: &Value, actor: &str) -> Value {
    ensure_dirs();
    let rule_id = payload
        .get("rule_id")
        .and_then(|v| v.as_str())
        .unwrap_or("rule-new");
    let mut rule = payload.clone();
    if rule.get("created_at").is_none() {
        rule["created_at"] = json!(Utc::now().to_rfc3339());
        rule["created_by"] = json!(actor);
    }
    rule["updated_at"] = json!(Utc::now().to_rfc3339());
    rule["updated_by"] = json!(actor);
    if rule.get("review_status").is_none() {
        rule["review_status"] = json!("draft");
    }
    if rule.get("source").is_none() {
        rule["source"] = json!("human_created");
    }
    let path = rules_dir().join(format!("{rule_id}.json"));
    if let Err(err) = fs::write(
        &path,
        serde_json::to_string_pretty(&rule).unwrap_or_default(),
    ) {
        return json!({"ok": false, "error": err.to_string()});
    }
    json!({"ok": true, "saved": true, "rule_id": rule_id, "path": path.display().to_string(), "review_status": rule["review_status"]})
}

pub fn validate_rule_sql(payload: &Value) -> Value {
    let sql = payload.get("sql").and_then(|v| v.as_str()).unwrap_or("");
    let mut validation = sql_safety::validate_sql(sql);
    if let Some(obj) = validation.as_object_mut() {
        obj.insert(
            "rule_id".into(),
            payload.get("rule_id").cloned().unwrap_or(json!(null)),
        );
    }
    validation
}

pub fn test_rule_sql(payload: &Value) -> Value {
    let sql = payload.get("sql").and_then(|v| v.as_str()).unwrap_or("");
    let confirmation = payload
        .get("confirmation_seconds")
        .and_then(|v| v.as_i64())
        .unwrap_or(300);
    let params = payload.get("params").cloned().unwrap_or(json!({}));
    execution::run_rule_sql(sql, confirmation, &params)
}

pub fn activate_rule(rule_id: &str, actor: &str, role: &str) -> Value {
    if role != "integrator" {
        return json!({"ok": false, "error": "integrator role required to activate rules", "role": role});
    }
    let mut rule = get_rule(rule_id);
    if rule.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return rule;
    }
    let review = rule["rule"]["review_status"].as_str().unwrap_or("draft");
    if review != "approved" && review != "active" {
        return json!({
            "ok": false,
            "error": "rule must be approved before activation",
            "review_status": review
        });
    }
    let sql = rule["rule"]["sql"].as_str().unwrap_or("");
    if !sql_safety::is_sql_safe(sql) {
        return json!({"ok": false, "error": "unsafe SQL", "validation": sql_safety::validate_sql(sql)});
    }
    let mut updated = rule["rule"].clone();
    updated["review_status"] = json!("active");
    updated["updated_at"] = json!(Utc::now().to_rfc3339());
    updated["updated_by"] = json!(actor);
    let save = save_rule(&updated, actor);
    json!({
        "ok": true,
        "activated": true,
        "rule_id": rule_id,
        "activated_by": actor,
        "save": save
    })
}

fn default_oa_rule() -> Value {
    json!({
        "rule_id": "oa_temp_out_of_range",
        "name": "OA Temperature Out Of Range",
        "description": "Outside air temperature below low limit or above high limit",
        "equipment_types": ["ahu", "bench"],
        "required_inputs": ["oa_t"],
        "optional_inputs": [],
        "sql": "SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t IS NULL THEN false WHEN oa_t < 40.0 THEN true WHEN oa_t > 110.0 THEN true ELSE false END AS fault_raw FROM telemetry_pivot WHERE equipment_id = '5007'",
        "builder_config": {"input":"oa_t","operator":"range","low":40,"high":110},
        "confirmation_seconds": 300,
        "clear_behavior": "immediate",
        "severity": "medium",
        "output_fault_code": "OA_TEMP_OUT_OF_RANGE",
        "source": "human_created",
        "review_status": "approved",
        "sql_mode": "builder"
    })
}

fn workspace_dir() -> PathBuf {
    env::var("OPENFDD_WORKSPACE")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("workspace"))
}

fn ensure_dirs() {
    let _ = fs::create_dir_all(rules_dir());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_cannot_activate() {
        let out = activate_rule("oa_temp_out_of_range", "agent", "agent");
        assert_eq!(out["ok"].as_bool(), Some(false));
    }
}
