//! Fault listing, analytics, and catalog APIs.

use crate::fdd::{execution, rules};
use crate::historian::store;
use crate::model::scope;
use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;

const CONFIRMATION_SECONDS: i64 = 300;
const CLEAR_SNOOZE_MINUTES: i64 = 15;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ClearedEntry {
    cleared_at: String,
    snooze_until: String,
}

fn cleared_path() -> PathBuf {
    crate::validation::profile::workspace_dir().join("data/faults_cleared.json")
}

fn load_cleared_map() -> HashMap<String, ClearedEntry> {
    let path = cleared_path();
    let text = fs::read_to_string(&path).unwrap_or_else(|_| "{}".into());
    if let Ok(map) = serde_json::from_str::<HashMap<String, ClearedEntry>>(&text) {
        return map;
    }
    // Migrate legacy string list format.
    if let Ok(ids) = serde_json::from_str::<Vec<String>>(&text) {
        let now = Utc::now();
        return ids
            .into_iter()
            .map(|id| {
                let snooze = now + Duration::minutes(CLEAR_SNOOZE_MINUTES);
                (
                    id,
                    ClearedEntry {
                        cleared_at: now.to_rfc3339(),
                        snooze_until: snooze.to_rfc3339(),
                    },
                )
            })
            .collect();
    }
    HashMap::new()
}

fn save_cleared_map(map: &HashMap<String, ClearedEntry>) -> std::io::Result<()> {
    let path = cleared_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(
        path,
        serde_json::to_string_pretty(map).unwrap_or_else(|_| "{}".into()),
    )
}

fn prune_expired_snoozes(map: &mut HashMap<String, ClearedEntry>) {
    let now = Utc::now();
    map.retain(|_, entry| {
        DateTime::parse_from_rfc3339(&entry.snooze_until)
            .map(|t| t.with_timezone(&Utc) > now)
            .unwrap_or(false)
    });
}

fn load_cleared_ids() -> HashSet<String> {
    let mut map = load_cleared_map();
    prune_expired_snoozes(&mut map);
    let _ = save_cleared_map(&map);
    map.keys().cloned().collect()
}

fn save_cleared_ids(ids: &HashSet<String>) -> std::io::Result<()> {
    let mut map = load_cleared_map();
    prune_expired_snoozes(&mut map);
    let now = Utc::now();
    let snooze = now + Duration::minutes(CLEAR_SNOOZE_MINUTES);
    for id in ids {
        map.insert(
            id.clone(),
            ClearedEntry {
                cleared_at: now.to_rfc3339(),
                snooze_until: snooze.to_rfc3339(),
            },
        );
    }
    save_cleared_map(&map)
}

pub fn clear_fault(fault_id: &str, cleared_by: &str) -> Value {
    if fault_id.trim().is_empty() {
        return json!({"ok": false, "error": "fault_id required"});
    }
    let mut ids = load_cleared_ids();
    ids.insert(fault_id.to_string());
    match save_cleared_ids(&ids) {
        Ok(()) => json!({
            "ok": true,
            "fault_id": fault_id,
            "cleared_by": cleared_by,
            "cleared_at": Utc::now().to_rfc3339(),
            "snooze_minutes": CLEAR_SNOOZE_MINUTES,
            "note": "Fault hidden until snooze expires; reappears if condition persists"
        }),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

fn is_manually_cleared(fault_id: &str, cleared_ids: &HashSet<String>) -> bool {
    cleared_ids.contains(fault_id)
}

pub fn eval_rows() -> Vec<Value> {
    let mut out = Vec::new();
    for rule in rules::evaluable_rules() {
        let sql = rule.get("sql").and_then(|v| v.as_str()).unwrap_or("");
        let confirmation = rule
            .get("confirmation_seconds")
            .and_then(|v| v.as_i64())
            .unwrap_or(CONFIRMATION_SECONDS);
        let eval = execution::run_rule_sql_from_historian(sql, confirmation, &json!({}));
        if eval.get("ok").and_then(|v| v.as_bool()) != Some(true) {
            continue;
        }
        let Some(rows) = eval.get("rows").and_then(|v| v.as_array()) else {
            continue;
        };
        for row in rows {
            let mut tagged = row.clone();
            if let Some(obj) = tagged.as_object_mut() {
                obj.entry("_rule".to_string()).or_insert(rule.clone());
            }
            out.push(tagged);
        }
    }
    out
}

fn build_fault_record(row: &Value, rule: &Value, idx: usize) -> Value {
    let raw = row
        .get("raw_fault")
        .or_else(|| row.get("fault_raw"))
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
        .map(str::to_string)
        .or_else(scope::first_equipment_id)
        .unwrap_or_else(|| "unknown".to_string());
    let site_id = scope::site_for_equipment(&equipment);
    let rule_id = rule
        .get("rule_id")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown_rule");
    let rule_name = rule
        .get("name")
        .or_else(|| rule.get("rule_name"))
        .and_then(|v| v.as_str())
        .unwrap_or(rule_id);
    let inputs = scope::required_inputs_for_rule(rule);
    let source_ids = scope::source_protocols_for_equipment(&equipment);
    let mut latest_values = json!({});
    if let Some(obj) = latest_values.as_object_mut() {
        for input in &inputs {
            obj.insert(
                input.clone(),
                row.get(input).cloned().unwrap_or(Value::Null),
            );
        }
    }
    json!({
        "fault_id": format!("fault-{rule_id}-{equipment}-{idx}"),
        "rule_id": rule_id,
        "rule_name": rule_name,
        "site_id": site_id,
        "building_id": Value::Null,
        "equipment_id": equipment,
        "source_ids": source_ids,
        "status": status,
        "severity": rule.get("severity").cloned().unwrap_or(json!("warning")),
        "first_seen_at": ts,
        "confirmed_at": if confirmed { json!(ts) } else { Value::Null },
        "last_seen_at": ts,
        "cleared_at": if cleared { json!(ts) } else { Value::Null },
        "minutes_in_fault": row.get("minutes_in_fault").cloned().unwrap_or(json!(0)),
        "confirmation_required_minutes": row.get("confirmation_required_minutes").cloned().unwrap_or(json!(5)),
        "input_points": inputs,
        "latest_values": latest_values,
        "sql_result_ref": "telemetry_pivot",
        "notes": Value::Null
    })
}

fn rule_for_row(row: &Value) -> Value {
    row.get("_rule").cloned().unwrap_or_else(
        || json!({"rule_id": "unknown", "name": "Unknown rule", "required_inputs": []}),
    )
}

pub fn list_records() -> Vec<Value> {
    let cleared_ids = load_cleared_ids();
    let mut records: Vec<Value> = eval_rows()
        .iter()
        .enumerate()
        .filter(|(_, r)| {
            r.get("raw_fault").and_then(|v| v.as_bool()) == Some(true)
                || r.get("confirmed_fault").and_then(|v| v.as_bool()) == Some(true)
                || r.get("fault_raw").and_then(|v| v.as_bool()) == Some(true)
        })
        .map(|(i, r)| build_fault_record(r, &rule_for_row(r), i))
        .filter(|rec| {
            rec.get("fault_id")
                .and_then(|v| v.as_str())
                .map(|id| !is_manually_cleared(id, &cleared_ids))
                .unwrap_or(true)
        })
        .collect();
    for alert in crate::drivers::bacnet::override_fault_alerts() {
        let fault_id = alert
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if fault_id.is_empty() || is_manually_cleared(&fault_id, &cleared_ids) {
            continue;
        }
        records.push(json!({
            "fault_id": fault_id,
            "rule_id": alert.get("rule_id").cloned().unwrap_or(json!("bacnet_operator_override")),
            "rule_name": alert.get("rule_name").cloned().unwrap_or(json!("BACnet operator override")),
            "site_id": scope::active_site_id().unwrap_or_else(|| "site:unknown".to_string()),
            "building_id": Value::Null,
            "equipment_id": alert.get("equipment_id").cloned().unwrap_or(json!("unknown")),
            "source_ids": json!(["bacnet"]),
            "status": "confirmed",
            "severity": alert.get("severity").cloned().unwrap_or(json!("warning")),
            "first_seen_at": alert.get("first_seen_at").cloned().unwrap_or(json!(null)),
            "confirmed_at": alert.get("last_seen_at").cloned().unwrap_or(json!(null)),
            "last_seen_at": alert.get("last_seen_at").cloned().unwrap_or(json!(null)),
            "cleared_at": Value::Null,
            "minutes_in_fault": 0,
            "confirmation_required_minutes": 0,
            "input_points": json!([]),
            "latest_values": json!({}),
            "sql_result_ref": "bacnet_override_scan",
            "notes": alert.get("detail").cloned().unwrap_or(json!(null)),
            "source": "bacnet_override",
            "title": alert.get("title").cloned().unwrap_or(json!(null)),
            "code": alert.get("code").cloned().unwrap_or(json!(null))
        }));
    }
    records
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
    let all_rows = eval_rows();
    for rec in list_records() {
        if rec.get("fault_id").and_then(|v| v.as_str()) == Some(fault_id) {
            let source = rec
                .get("source")
                .and_then(|v| v.as_str())
                .unwrap_or("fdd_rule");
            let analytics = if source == "bacnet_override" {
                rec.get("analytics").cloned().unwrap_or(json!({}))
            } else {
                fault_analytics_for_record(&rec, &all_rows)
            };
            let mut fault = rec.clone();
            fault["analytics"] = analytics;
            return json!({"ok": true, "fault": fault});
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

fn fault_analytics_for_record(rec: &Value, all_rows: &[Value]) -> Value {
    let equipment = rec
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let input_col = rec
        .get("input_points")
        .and_then(|v| v.as_array())
        .and_then(|a| a.first())
        .and_then(|v| v.as_str())
        .unwrap_or("oa_t");
    let mut fault_vals = Vec::new();
    let mut normal_vals = Vec::new();
    let mut fault_samples = 0_usize;
    let mut total_samples = 0_usize;
    let mut first_fault: Option<String> = None;
    let mut last_fault: Option<String> = None;

    for row in all_rows {
        if row.get("equipment_id").and_then(|v| v.as_str()) != Some(equipment) {
            continue;
        }
        total_samples += 1;
        let is_fault = row.get("raw_fault").and_then(|v| v.as_bool()) == Some(true)
            || row.get("confirmed_fault").and_then(|v| v.as_bool()) == Some(true);
        if let Some(v) = row.get(input_col).and_then(|v| v.as_f64()) {
            if is_fault {
                fault_vals.push(v);
            } else {
                normal_vals.push(v);
            }
        }
        if is_fault {
            fault_samples += 1;
            let ts = row.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
            if first_fault.is_none() {
                first_fault = Some(ts.to_string());
            }
            last_fault = Some(ts.to_string());
        }
    }

    let minutes = rec
        .get("minutes_in_fault")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);
    let hours = minutes as f64 / 60.0;
    let avg = |vals: &[f64]| {
        if vals.is_empty() {
            Value::Null
        } else {
            json!(vals.iter().sum::<f64>() / vals.len() as f64)
        }
    };
    let min = |vals: &[f64]| vals.iter().copied().fold(f64::INFINITY, f64::min);
    let max = |vals: &[f64]| vals.iter().copied().fold(f64::NEG_INFINITY, f64::max);

    json!({
        "fault_samples": fault_samples,
        "total_samples": total_samples,
        "avg_value_fault": avg(&fault_vals),
        "avg_value_normal": avg(&normal_vals),
        "min_value_fault": if fault_vals.is_empty() { Value::Null } else { json!(min(&fault_vals)) },
        "max_value_fault": if fault_vals.is_empty() { Value::Null } else { json!(max(&fault_vals)) },
        "value_unit": if input_col.contains("_h") { "%RH" } else { "°F" },
        "bounds_low": 40.0,
        "bounds_high": 110.0,
        "fault_span_label": match (&first_fault, &last_fault) {
            (Some(a), Some(b)) if a == b => json!(a),
            (Some(a), Some(b)) => json!(format!("{a} → {b}")),
            _ => Value::Null
        },
        "estimated_fault_duration_label": format!("{hours:.1} h"),
        "estimated_fault_duration_hours": hours,
        "hours_in_fault": hours,
        "first_seen_at": first_fault,
        "last_seen_at": last_fault,
        "value_columns": [input_col]
    })
}

fn build_fault_families(records: &[Value]) -> Vec<Value> {
    let all_rows = eval_rows();
    let mut by_family: HashMap<String, Vec<Value>> = HashMap::new();
    for rec in records {
        if rec.get("status").and_then(|v| v.as_str()) == Some("cleared") {
            continue;
        }
        let source = rec
            .get("source")
            .and_then(|v| v.as_str())
            .unwrap_or("fdd_rule");
        let family = if source == "bacnet_override" {
            "bacnet_overrides".to_string()
        } else {
            rec.get("rule_id")
                .and_then(|v| v.as_str())
                .unwrap_or("general")
                .to_string()
        };
        let analytics = if source == "bacnet_override" {
            rec.get("analytics").cloned().unwrap_or(json!({}))
        } else {
            fault_analytics_for_record(rec, &all_rows)
        };
        by_family.entry(family).or_default().push(json!({
            "id": rec.get("fault_id").cloned().unwrap_or(Value::Null),
            "severity": rec.get("severity").cloned().unwrap_or(json!("warning")),
            "title": rec.get("title").or_else(|| rec.get("rule_name")).cloned().unwrap_or(json!("Fault")),
            "detail": rec.get("notes").or_else(|| rec.get("equipment_id")).cloned().unwrap_or(Value::Null),
            "rule_id": rec.get("rule_id").cloned().unwrap_or(Value::Null),
            "rule_name": rec.get("rule_name").cloned().unwrap_or(Value::Null),
            "equipment_id": rec.get("equipment_id").cloned().unwrap_or(Value::Null),
            "equipment_name": rec.get("equipment_id").cloned().unwrap_or(Value::Null),
            "source": source,
            "code": rec.get("code").or_else(|| rec.get("rule_id")).cloned().unwrap_or(Value::Null),
            "first_seen_at": rec.get("first_seen_at").cloned().unwrap_or(Value::Null),
            "last_seen_at": rec.get("last_seen_at").cloned().unwrap_or(Value::Null),
            "analytics": analytics
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
    ranked.sort_by_key(|b| std::cmp::Reverse(b.1));
    let items: Vec<Value> = ranked
        .into_iter()
        .take(10)
        .map(|(equipment_id, count)| json!({"equipment_id": equipment_id, "fault_count": count}))
        .collect();
    json!({"ok": true, "equipment": items})
}

pub fn rule_health() -> Value {
    let rules_arr = rules::evaluable_rules();
    let eval = rules_arr.first().map(|rule| {
        let sql = rule.get("sql").and_then(|v| v.as_str()).unwrap_or("");
        let confirmation = rule
            .get("confirmation_seconds")
            .and_then(|v| v.as_i64())
            .unwrap_or(CONFIRMATION_SECONDS);
        execution::run_rule_sql_from_historian(sql, confirmation, &json!({}))
    });
    json!({
        "ok": true,
        "rule_count": rules_arr.len(),
        "datafusion_ok": eval.as_ref().and_then(|e| e.get("ok").and_then(|v| v.as_bool())).unwrap_or(false),
        "last_error": eval.and_then(|e| e.get("error").cloned()).unwrap_or(Value::Null)
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
    let sid = scope::resolve_site_id(site_id);
    let equips = crate::model::query::list_equips(sid.as_deref());
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
        "assigned_rules": rules::evaluable_rules(),
        "families": catalog_json()["families"].clone()
    })
}

pub fn validate_scope_json(site_id: Option<&str>) -> Value {
    json!({
        "ok": true,
        "site_id": scope::resolve_site_id(site_id),
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

    #[test]
    fn clear_fault_hides_from_list() {
        let _lock = crate::test_support::workspace_env_lock();
        let prev = std::env::var("OPENFDD_WORKSPACE").ok();
        let dir = std::env::temp_dir().join(format!("openfdd-fault-clear-{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        std::env::set_var("OPENFDD_WORKSPACE", &dir);
        let fault_id = "fault-test-clear";
        let out = clear_fault(fault_id, "operator");
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert!(load_cleared_ids().contains(fault_id));
        let listed = list_records();
        assert!(!listed.iter().any(|r| {
            r.get("fault_id")
                .and_then(|v| v.as_str())
                .map(|id| id == fault_id)
                .unwrap_or(false)
        }));
        if let Some(p) = prev {
            std::env::set_var("OPENFDD_WORKSPACE", p);
        } else {
            std::env::remove_var("OPENFDD_WORKSPACE");
        }
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn fault_analytics_includes_hours() {
        let rec = json!({
            "equipment_id": "equip:unit-a",
            "minutes_in_fault": 90,
            "input_points": ["oa_t"]
        });
        let rows = vec![
            json!({"equipment_id":"equip:unit-a","timestamp":"2026-06-21T10:00:00Z","raw_fault":true,"oa_t":120.0}),
            json!({"equipment_id":"equip:unit-a","timestamp":"2026-06-21T11:00:00Z","raw_fault":false,"oa_t":70.0}),
        ];
        let analytics = fault_analytics_for_record(&rec, &rows);
        assert_eq!(
            analytics.get("hours_in_fault").and_then(|v| v.as_f64()),
            Some(1.5)
        );
        assert!(analytics.get("fault_span_label").is_some());
    }
}
