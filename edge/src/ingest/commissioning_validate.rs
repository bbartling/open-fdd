//! Fail-closed validation for commissioning import payloads.

use crate::fdd::execution;
use crate::fdd::sql_safety;
use serde_json::{json, Value};
use std::collections::HashSet;

pub fn validate_commissioning(payload: &Value) -> Value {
    let mut checks: Vec<Value> = Vec::new();
    let mut hints: Vec<String> = Vec::new();

    let sites = payload.get("sites").and_then(|v| v.as_array());
    let equipment = payload.get("equipment").and_then(|v| v.as_array());
    let points = payload.get("points").and_then(|v| v.as_array());
    let assignments = payload.get("assignments").and_then(|v| v.as_array());

    if sites.is_none() && equipment.is_none() && points.is_none() {
        checks.push(err(
            "PAYLOAD_EMPTY",
            "payload must include sites, equipment, or points",
        ));
    }

    let fdd_ids: HashSet<String> = execution::fdd_inputs_json()
        .get("fdd_inputs")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|i| i.get("id").and_then(|v| v.as_str()).map(str::to_string))
                .collect()
        })
        .unwrap_or_default();

    let mut site_ids = HashSet::new();
    if let Some(sites) = sites {
        for s in sites {
            let id = entity_id(s, &["site_id", "id"]);
            if id.is_empty() {
                checks.push(err("SITE_ID_MISSING", "site missing id/site_id"));
            } else if !site_ids.insert(id.clone()) {
                checks.push(err("SITE_ID_DUPLICATE", format!("duplicate site id {id}")));
            }
        }
    }

    let mut equip_ids = HashSet::new();
    if let Some(equipment) = equipment {
        for eq in equipment {
            let id = entity_id(eq, &["equipment_id", "id"]);
            if id.is_empty() {
                checks.push(err("EQUIP_ID_MISSING", "equipment missing id"));
            } else if !equip_ids.insert(id) {
            }
        }
    }

    if let Some(points) = points {
        for pt in points {
            let id = entity_id(pt, &["point_id", "id", "haystack_id"]);
            if id.is_empty() {
                checks.push(err("POINT_ID_MISSING", "point missing id"));
            }
            if let Some(fdd) = pt.get("fdd_input").and_then(|v| v.as_str()) {
                if !fdd.is_empty() && !fdd_ids.contains(fdd) {
                    checks.push(err(
                        "FDD_INPUT_UNKNOWN",
                        format!("unknown fdd_input '{fdd}' on point {id}"),
                    ));
                }
            }
        }
    }

    if let Some(assignments) = assignments {
        for a in assignments {
            if let Some(fdd) = a.get("fdd_input").and_then(|v| v.as_str()) {
                if !fdd.is_empty() && !fdd_ids.contains(fdd) {
                    checks.push(err(
                        "FDD_INPUT_UNKNOWN",
                        format!("unknown fdd_input '{fdd}' in assignments"),
                    ));
                }
            }
        }
    }

    if let Some(rules) = payload.get("fdd_rules").and_then(|v| v.as_array()) {
        for r in rules {
            let rule_id = r.get("rule_id").and_then(|v| v.as_str()).unwrap_or("");
            if rule_id.is_empty() {
                checks.push(err("RULE_ID_MISSING", "fdd_rule missing rule_id"));
            }
            if let Some(sql) = r.get("sql").and_then(|v| v.as_str()) {
                let v = sql_safety::validate_sql(sql);
                if v.get("safe").and_then(|x| x.as_bool()) != Some(true) {
                    checks.push(err(
                        "RULE_SQL_UNSAFE",
                        format!("rule {rule_id} SQL failed safety check"),
                    ));
                    if let Some(errs) = v.get("errors").and_then(|x| x.as_array()) {
                        for e in errs {
                            hints.push(format!("rule {rule_id}: {e}"));
                        }
                    }
                }
            }
        }
    }

    let has_error = checks.iter().any(|c| c["severity"] == "error");
    let verdict = if has_error { "fail" } else { "pass" };

    json!({
        "ok": !has_error,
        "verdict": verdict,
        "checks": checks,
        "agent_hints": hints,
        "summary": {
            "sites": sites.map(|a| a.len()).unwrap_or(0),
            "equipment": equipment.map(|a| a.len()).unwrap_or(0),
            "points": points.map(|a| a.len()).unwrap_or(0),
            "assignments": assignments.map(|a| a.len()).unwrap_or(0),
            "fdd_rules": payload.get("fdd_rules").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0)
        }
    })
}

fn entity_id(obj: &Value, keys: &[&str]) -> String {
    for k in keys {
        if let Some(s) = obj.get(*k).and_then(|v| v.as_str()) {
            if !s.is_empty() {
                return s.to_string();
            }
        }
    }
    String::new()
}

fn err(code: &str, message: impl Into<String>) -> Value {
    json!({
        "code": code,
        "severity": "error",
        "message": message.into(),
        "count": 1,
        "examples": []
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_payload() {
        let out = validate_commissioning(&json!({}));
        assert_eq!(out["verdict"], "fail");
    }

    #[test]
    fn accepts_minimal_site() {
        let out = validate_commissioning(&json!({
            "sites": [{"id": "site:test", "dis": "Test", "site": "M"}]
        }));
        assert_eq!(out["verdict"], "pass");
    }
}
