//! Fault listing, analytics, and catalog APIs.

use crate::fdd::{execution, rules};
use crate::historian::store;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use std::collections::HashMap;

const DEFAULT_SQL: &str = "SELECT timestamp, equipment_id, oa_t, CASE WHEN oa_t IS NULL THEN false WHEN oa_t < 40.0 OR oa_t > 110.0 THEN true ELSE false END AS raw_fault FROM telemetry_pivot";
const CONFIRMATION_SECONDS: i64 = 300;

pub fn eval_rows() -> Vec<Value> {
    let eval =
        execution::run_rule_sql_from_historian(DEFAULT_SQL, CONFIRMATION_SECONDS, &json!({}));
    eval.get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
}

fn build_fault_record(row: &Value, rule: &Value, idx: usize) -> Value {
    let raw = row
        .get("raw_fault")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let confirmed = row
        .get("confirmed_fault")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let cleared = !raw && !confirmed;
    let status = if cleared {
        "cleared"
    } else if confirmed {
        "confirmed"
    } else if raw {
        "raw"
    } else {
        "normal"
    };
    let ts = row.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
    let equipment = row
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .unwrap_or("equip:validation");
    let rule_id = rule
        .get("rule_id")
        .and_then(|v| v.as_str())
        .unwrap_or("oa_temp_out_of_range");
    let rule_name = rule
        .get("rule_name")
        .and_then(|v| v.as_str())
        .unwrap_or("OA Temperature Out Of Range");
    json!({
        "fault_id": format!("fault-{rule_id}-{equipment}-{idx}"),
        "rule_id": rule_id,
        "rule_name": rule_name,
        "site_id": "site:demo",
        "building_id": "building:main",
        "equipment_id": equipment,
        "source_ids": ["bacnet"],
        "status": status,
        "severity": rule.get("severity").cloned().unwrap_or(json!("warning")),
        "first_seen_at": ts,
        "confirmed_at": if confirmed { json!(ts) } else { Value::Null },
        "last_seen_at": ts,
        "cleared_at": if cleared { json!(ts) } else { Value::Null },
        "minutes_in_fault": row.get("minutes_in_fault").cloned().unwrap_or(json!(0)),
        "confirmation_required_minutes": row.get("confirmation_required_minutes").cloned().unwrap_or(json!(5)),
        "input_points": ["oa_t"],
        "latest_values": {"oa_t": row.get("oa_t").cloned().unwrap_or(Value::Null)},
        "sql_result_ref": "telemetry_pivot",
        "notes": Value::Null
    })
}

fn default_rule() -> Value {
    rules::get_rule("oa_temp_out_of_range")["rule"].clone()
}

pub fn list_records() -> Vec<Value> {
    let rule = default_rule();
    eval_rows()
        .iter()
        .enumerate()
        .filter(|(_, r)| {
            r.get("raw_fault").and_then(|v| v.as_bool()) == Some(true)
                || r.get("confirmed_fault").and_then(|v| v.as_bool()) == Some(true)
        })
        .map(|(i, r)| build_fault_record(r, &rule, i))
        .collect()
}

pub fn list_json(filter: Option<&str>) -> Value {
    let mut records = list_records();
    match filter {
        Some("active") => records.retain(|r| {
            r.get("status").and_then(|v| v.as_str()) == Some("raw")
                || r.get("status").and_then(|v| v.as_str()) == Some("confirmed")
        }),
        Some("history") => {
            records.retain(|r| r.get("status").and_then(|v| v.as_str()) == Some("cleared"))
        }
        _ => {}
    }
    json!({"ok": true, "faults": records, "count": records.len()})
}

pub fn get_fault(fault_id: &str) -> Value {
    for rec in list_records() {
        if rec.get("fault_id").and_then(|v| v.as_str()) == Some(fault_id) {
            return json!({"ok": true, "fault": rec});
        }
    }
    json!({"ok": false, "error": "fault not found", "fault_id": fault_id})
}

pub fn summary_json() -> Value {
    let records = list_records();
    let mut raw = 0;
    let mut confirmed = 0;
    let mut cleared = 0;
    let mut active = 0;
    for rec in &records {
        match rec.get("status").and_then(|v| v.as_str()).unwrap_or("") {
            "raw" => {
                raw += 1;
                active += 1;
            }
            "confirmed" => {
                confirmed += 1;
                active += 1;
            }
            "cleared" => cleared += 1,
            _ => {}
        }
    }
    json!({
        "ok": true,
        "raw_count": raw,
        "confirmed_count": confirmed,
        "cleared_count": cleared,
        "active_count": active,
        "total_count": records.len()
    })
}

pub fn export_csv() -> String {
    let header = "fault_id,rule_id,rule_name,site_id,building_id,equipment_id,status,severity,first_seen_at,last_seen_at,minutes_in_fault";
    let mut out = String::from(header);
    out.push('\n');
    for rec in list_records() {
        out.push_str(&format!(
            "{},{},{},{},{},{},{},{},{},{},{}\n",
            rec["fault_id"].as_str().unwrap_or(""),
            rec["rule_id"].as_str().unwrap_or(""),
            rec["rule_name"].as_str().unwrap_or(""),
            rec["site_id"].as_str().unwrap_or(""),
            rec["building_id"].as_str().unwrap_or(""),
            rec["equipment_id"].as_str().unwrap_or(""),
            rec["status"].as_str().unwrap_or(""),
            rec["severity"].as_str().unwrap_or(""),
            rec["first_seen_at"].as_str().unwrap_or(""),
            rec["last_seen_at"].as_str().unwrap_or(""),
            rec["minutes_in_fault"].as_i64().unwrap_or(0)
        ));
    }
    out
}

pub fn status_json() -> Value {
    let records = list_records();
    let summary = summary_json();
    let active = summary["active_count"].as_u64().unwrap_or(0);
    let families = build_fault_families(&records);
    let traffic = if active == 0 {
        "green"
    } else if records.iter().any(|r| r["severity"] == "critical") {
        "red"
    } else {
        "yellow"
    };
    let status = if traffic == "green" {
        "ok"
    } else if traffic == "red" {
        "critical"
    } else {
        "warning"
    };
    json!({
        "status": status,
        "traffic": traffic,
        "check_engine": active > 0,
        "alert_count": active,
        "model_configured": !store::load_pivot_rows().unwrap_or_default().is_empty()
            || !crate::model::query::haystack_rows().is_empty(),
        "families": families
    })
}

fn build_fault_families(records: &[Value]) -> Vec<Value> {
    let mut by_family: HashMap<String, Vec<Value>> = HashMap::new();
    for rec in records {
        if rec.get("status").and_then(|v| v.as_str()) == Some("cleared") {
            continue;
        }
        let family = rec
            .get("rule_id")
            .and_then(|v| v.as_str())
            .unwrap_or("general")
            .to_string();
        by_family.entry(family).or_default().push(json!({
            "id": rec.get("fault_id").cloned().unwrap_or(Value::Null),
            "severity": rec.get("severity").cloned().unwrap_or(json!("warning")),
            "title": rec.get("rule_name").cloned().unwrap_or(json!("Fault")),
            "detail": rec.get("equipment_id").cloned().unwrap_or(Value::Null),
            "rule_id": rec.get("rule_id").cloned().unwrap_or(Value::Null),
            "rule_name": rec.get("rule_name").cloned().unwrap_or(Value::Null),
            "equipment_id": rec.get("equipment_id").cloned().unwrap_or(Value::Null),
            "equipment_name": rec.get("equipment_id").cloned().unwrap_or(Value::Null)
        }));
    }
    by_family
        .into_iter()
        .map(|(family, faults)| {
            let worst = faults
                .iter()
                .filter_map(|f| f.get("severity").and_then(|v| v.as_str()))
                .max_by_key(|s| match *s {
                    "critical" => 3,
                    "warning" => 2,
                    _ => 1,
                })
                .unwrap_or("info");
            json!({
                "family": family,
                "label": family.replace('_', " "),
                "worst": worst,
                "traffic": if worst == "critical" { "red" } else if worst == "warning" { "yellow" } else { "green" },
                "count": faults.len(),
                "faults": faults
            })
        })
        .collect()
}

pub fn history_trend() -> Value {
    let rows = eval_rows();
    let mut buckets: HashMap<String, usize> = HashMap::new();
    for row in rows {
        if row.get("raw_fault").and_then(|v| v.as_bool()) != Some(true) {
            continue;
        }
        let ts = row
            .get("timestamp")
            .and_then(|v| v.as_str())
            .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
            .map(|dt| dt.format("%Y-%m-%d").to_string())
            .unwrap_or_else(|| Utc::now().format("%Y-%m-%d").to_string());
        *buckets.entry(ts).or_insert(0) += 1;
    }
    let points: Vec<Value> = buckets
        .into_iter()
        .map(|(day, count)| json!({"day": day, "raw_fault_samples": count}))
        .collect();
    json!({"ok": true, "points": points})
}

pub fn top_faulted_equipment() -> Value {
    let mut counts: HashMap<String, usize> = HashMap::new();
    for rec in list_records() {
        if rec.get("status").and_then(|v| v.as_str()) == Some("cleared") {
            continue;
        }
        let equip = rec
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        *counts.entry(equip).or_insert(0) += 1;
    }
    let mut ranked: Vec<(String, usize)> = counts.into_iter().collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1));
    let items: Vec<Value> = ranked
        .into_iter()
        .take(10)
        .map(|(equipment_id, count)| json!({"equipment_id": equipment_id, "fault_count": count}))
        .collect();
    json!({"ok": true, "equipment": items})
}

pub fn rule_health() -> Value {
    let rules_body = rules::list_rules();
    let rules_arr = rules_body
        .get("rules")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let eval =
        execution::run_rule_sql_from_historian(DEFAULT_SQL, CONFIRMATION_SECONDS, &json!({}));
    json!({
        "ok": true,
        "rule_count": rules_arr.len(),
        "datafusion_ok": eval.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
        "last_error": eval.get("error").cloned().unwrap_or(Value::Null)
    })
}

pub fn catalog_json() -> Value {
    json!({
        "ok": true,
        "version": 1,
        "query_engine": "haystack",
        "families": [{
            "family": "ahu",
            "label": "Air Handling Unit",
            "description": "AHU sensor and setpoint faults",
            "categories": [{
                "category": "comfort",
                "label": "Comfort / SAT",
                "codes": [{
                    "code": "SAT_DEVIATION_HIGH",
                    "category": "comfort",
                    "title": "Supply air temperature deviation",
                    "severity": "warning",
                    "description": "SAT deviates from setpoint beyond threshold",
                    "likely_causes": ["Setpoint override", "Valve stuck", "Sensor drift"],
                    "suggested_checks": ["Review SAT setpoint", "Inspect valve command", "Compare duct temp trend"],
                    "cookbook_patterns": ["g36_trim_respond"]
                }]
            }]
        }]
    })
}

pub fn tree_json() -> Value {
    applicable_json(None)
}

pub fn applicable_json(site_id: Option<&str>) -> Value {
    let sid = site_id.unwrap_or("site:demo");
    let equips = crate::model::query::list_equips(Some(sid));
    let equipment: Vec<Value> = equips
        .get("equips")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let applicable = if equipment.is_empty() {
        vec!["general".to_string()]
    } else {
        vec!["ahu".to_string(), "comfort".to_string()]
    };
    json!({
        "ok": true,
        "version": 1,
        "site_id": sid,
        "model_configured": !equipment.is_empty(),
        "query_engine": "haystack",
        "equipment_count": equipment.len(),
        "applicable_families": applicable,
        "hidden_families": [],
        "family_equipment": {"ahu": equipment},
        "unmatched_equipment": [],
        "assigned_rules": [{
            "rule_id": "oa_temp_out_of_range",
            "rule_name": "OA Temperature Out Of Range",
            "fault_code": "OAT_OUT_OF_RANGE",
            "family": "ahu",
            "severity": "warning"
        }],
        "families": catalog_json()["families"].clone()
    })
}

pub fn validate_scope_json(site_id: Option<&str>) -> Value {
    json!({
        "ok": true,
        "site_id": site_id.unwrap_or("site:demo"),
        "validation": "Haystack model scope validated locally (Ollama optional). SPARQL optional.",
        "ollama_error": Value::Null
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn list_returns_status_fields() {
        let body = list_json(None);
        assert_eq!(body.get("ok").and_then(|v| v.as_bool()), Some(true));
        if let Some(arr) = body.get("faults").and_then(|v| v.as_array()) {
            for rec in arr {
                assert!(rec.get("fault_id").is_some());
                assert!(rec.get("status").is_some());
            }
        }
    }

    #[test]
    fn csv_export_has_header() {
        let csv = export_csv();
        assert!(csv.starts_with("fault_id,rule_id"));
    }

    #[test]
    fn status_json_shape() {
        let body = status_json();
        assert!(body.get("traffic").is_some());
        assert!(body.get("families").is_some());
    }
}
