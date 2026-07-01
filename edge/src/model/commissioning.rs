//! Commissioning export/import and model sync APIs used by the dashboard data model tab.

use super::persist;
use super::query;
use crate::drivers::bacnet;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;

fn ttl_path() -> PathBuf {
    crate::validation::profile::workspace_dir().join("data/model/data_model.ttl")
}

pub fn tree_json() -> Value {
    let sites = query::list_sites();
    let site_id = sites.get("active_site_id").and_then(|v| v.as_str());
    let equipment = site_id
        .map(query::list_equipment)
        .unwrap_or_else(|| json!({"ok": true, "equipment": [], "count": 0}));
    let points = site_id
        .map(|s| query::list_points(Some(s)))
        .unwrap_or_else(|| json!({"ok": true, "points": [], "count": 0}));
    json!({
        "ok": true,
        "site_id": site_id,
        "equipment": equipment.get("equipment").cloned().unwrap_or(json!([])),
        "points": points.get("points").cloned().unwrap_or(json!([]))
    })
}

pub fn commissioning_export_json() -> Value {
    let sites_body = query::list_sites();
    let site_id = sites_body
        .get("active_site_id")
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .or_else(|| {
            sites_body
                .get("sites")
                .and_then(|v| v.as_array())
                .and_then(|a| a.first())
                .and_then(|s| s.get("site_id").and_then(|v| v.as_str()))
                .map(str::to_string)
        });
    let equipment = site_id
        .as_deref()
        .map(query::list_equipment)
        .unwrap_or_else(|| json!({"ok": true, "equipment": [], "count": 0}));
    let points = site_id
        .as_deref()
        .map(|s| query::list_points(Some(s)))
        .unwrap_or_else(|| json!({"ok": true, "points": [], "count": 0}));
    let assignments = super::assignments::load_assignments_value();
    let fdd_rules = crate::fdd::rules::list_rules()
        .get("rules")
        .cloned()
        .unwrap_or(json!([]));
    json!({
        "ok": true,
        "version": 1,
        "exported_at": chrono::Utc::now().to_rfc3339(),
        "sites": sites_body.get("sites").cloned().unwrap_or(json!([])),
        "equipment": equipment.get("equipment").cloned().unwrap_or(json!([])),
        "points": points.get("points").cloned().unwrap_or(json!([])),
        "fdd_rules": fdd_rules,
        "assignments": assignments.get("points").cloned().unwrap_or(json!([])),
        "fault_equation_bindings": assignments.get("fault_equation_bindings").cloned().unwrap_or(json!([]))
    })
}

pub fn import_commissioning(body: &Value) -> Value {
    let payload = body.get("payload").cloned().unwrap_or_else(|| body.clone());
    let validation = crate::ingest::validate_commissioning(&payload);
    if validation.get("verdict") != Some(&json!("pass")) {
        return json!({
            "ok": false,
            "error": "commissioning import rejected — fix validation.checks before retry",
            "validation": validation,
        });
    }
    let sites = payload.get("sites").and_then(|v| v.as_array()).cloned();
    let equipment = payload.get("equipment").and_then(|v| v.as_array()).cloned();
    let points = payload.get("points").and_then(|v| v.as_array()).cloned();
    if sites.is_none() && equipment.is_none() && points.is_none() {
        return json!({"ok": false, "error": "payload must include sites, equipment, or points"});
    }

    let mut rows: Vec<Value> = Vec::new();
    if let Some(sites) = sites {
        for site in sites {
            let id = site
                .get("site_id")
                .or_else(|| site.get("id"))
                .and_then(|v| v.as_str())
                .unwrap_or("site:unknown");
            let name = site
                .get("name")
                .or_else(|| site.get("dis"))
                .and_then(|v| v.as_str());
            rows.push(json!({"id": id, "dis": name.unwrap_or(id), "site": "M"}));
        }
    }
    if let Some(equipment) = equipment {
        for eq in equipment {
            let id = eq
                .get("equipment_id")
                .or_else(|| eq.get("id"))
                .and_then(|v| v.as_str())
                .unwrap_or("equip:unknown");
            rows.push(json!({
                "id": id,
                "dis": eq.get("name").or_else(|| eq.get("dis")).cloned().unwrap_or(json!(id)),
                "equip": "M",
                "siteRef": eq.get("site_id").cloned().unwrap_or(Value::Null)
            }));
        }
    }
    if let Some(points) = points {
        for pt in points {
            let id = pt
                .get("point_id")
                .or_else(|| pt.get("id"))
                .and_then(|v| v.as_str())
                .unwrap_or("point:unknown");
            rows.push(json!({
                "id": id,
                "dis": pt.get("name").or_else(|| pt.get("dis")).cloned().unwrap_or(json!(id)),
                "point": "M",
                "equipRef": pt.get("equip_ref").cloned().unwrap_or(json!(null)),
                "fddInput": pt.get("fdd_input").cloned().unwrap_or(json!(null)),
                "bacnetRef": pt.get("bacnet_ref").cloned().unwrap_or(json!(null))
            }));
        }
    }

    let grid = json!({
        "meta": {"ver": "3.0", "mode": "commissioning-import"},
        "cols": [],
        "rows": rows
    });
    match persist::save_haystack_grid(&grid) {
        Ok(path) => {
            let mut assignments_updated = 0usize;
            if let Some(pts) = payload.get("assignments").and_then(|v| v.as_array()) {
                let mut current = super::assignments::load_assignments_value();
                current["points"] = json!(pts);
                if let Some(fdd) = payload.get("fdd_rules") {
                    current["fault_equation_bindings"] = fdd.clone();
                }
                let _ = super::assignments::save_assignments_value(&current);
                assignments_updated = pts.len();
            } else if payload.get("fdd_rules").is_some() {
                let mut current = super::assignments::load_assignments_value();
                current["fault_equation_bindings"] =
                    payload.get("fdd_rules").cloned().unwrap_or(json!([]));
                let _ = super::assignments::save_assignments_value(&current);
            }
            if let Some(rules_arr) = payload.get("fdd_rules").and_then(|v| v.as_array()) {
                for rule in rules_arr {
                    let _ = crate::fdd::rules::save_rule(rule, "commissioning-import");
                }
            }
            json!({
                "ok": true,
                "sites": payload.get("sites").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
                "equipment": payload.get("equipment").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
                "points": payload.get("points").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
                "fdd_rules_updated": payload.get("fdd_rules").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
                "assignments_updated": assignments_updated,
                "path": path.display().to_string()
            })
        }
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

fn bacnet_point_ids_from_driver() -> HashSet<String> {
    let tree: Value = serde_json::from_str(&bacnet::driver_tree_json()).unwrap_or(json!({}));
    let mut ids = HashSet::new();
    for dev in tree
        .get("devices")
        .and_then(|v| v.as_array())
        .into_iter()
        .flatten()
    {
        if dev.get("local_server").and_then(|v| v.as_bool()) == Some(true) {
            continue;
        }
        for pt in dev
            .get("points")
            .and_then(|v| v.as_array())
            .into_iter()
            .flatten()
        {
            if let Some(id) = pt
                .get("point_id")
                .or_else(|| pt.get("object_identifier"))
                .and_then(|v| v.as_str())
            {
                ids.insert(id.to_string());
            }
        }
    }
    ids
}

fn bacnet_refs_from_model() -> HashSet<String> {
    let mut refs = HashSet::new();
    for row in query::haystack_rows() {
        if row.get("point").and_then(|v| v.as_str()) != Some("M") {
            continue;
        }
        if let Some(r) = row.get("bacnetRef").and_then(|v| v.as_str()) {
            refs.insert(r.to_string());
        }
    }
    refs
}

pub fn bacnet_sync_status_json() -> Value {
    let driver_ids = bacnet_point_ids_from_driver();
    let model_refs = bacnet_refs_from_model();
    let poll_enabled = driver_ids.len();
    let model_bacnet = model_refs.len();
    let missing = driver_ids
        .iter()
        .filter(|id| !model_refs.contains(id.as_str()))
        .count();
    let extra = model_refs
        .iter()
        .filter(|r| !driver_ids.contains(r.as_str()))
        .count();
    let ttl = ttl_path();
    json!({
        "ok": true,
        "in_sync": missing == 0 && extra == 0,
        "poll_enabled_count": poll_enabled,
        "model_bacnet_count": model_bacnet,
        "missing_in_model_total": missing,
        "extra_in_model_total": extra,
        "ttl_exists": ttl.is_file(),
        "ttl_path": ttl.display().to_string()
    })
}

pub fn bacnet_sync_apply_json() -> Value {
    let sync = bacnet::sync_discovery_value(&json!({}));
    let status = bacnet_sync_status_json();
    json!({
        "ok": sync.get("ok").and_then(|v| v.as_bool()).unwrap_or(false),
        "points_added": sync.get("points").and_then(|v| v.as_u64()).unwrap_or(0),
        "points_updated": 0,
        "points_removed": 0,
        "discovery": sync,
        "sync_status": status
    })
}

/// Remove Haystack model rows bound to BACnet refs (used when clearing BACnet registry).
pub fn remove_bacnet_bindings_from_model() -> Value {
    let grid = crate::model::persist::haystack_model_value();
    let rows = grid
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut points_removed = 0_u64;
    let kept: Vec<Value> = rows
        .into_iter()
        .filter(|row| {
            let is_bacnet_point = row.get("point").and_then(|v| v.as_str()) == Some("M")
                && row.get("bacnetRef").is_some();
            if is_bacnet_point {
                points_removed += 1;
                false
            } else {
                true
            }
        })
        .collect();
    if points_removed > 0 {
        let mut new_grid = grid;
        new_grid["rows"] = json!(kept);
        if let Err(e) = crate::model::persist::save_haystack_grid(&new_grid) {
            return json!({
                "ok": false,
                "error": format!("failed to persist Haystack model after BACnet clear: {e}"),
                "points_removed": 0,
                "equipment_removed": 0
            });
        }
    }
    json!({
        "ok": true,
        "points_removed": points_removed,
        "equipment_removed": 0
    })
}

pub fn health_json() -> Value {
    let coverage = query::model_coverage();
    let score = coverage.get("model_score").and_then(|v| v.as_f64());
    let unmapped = coverage
        .get("unmapped_points")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);
    let configured = coverage
        .get("point_count")
        .and_then(|v| v.as_u64())
        .unwrap_or(0)
        > 0;
    let mut issues = Vec::new();
    if unmapped > 0 {
        issues.push(json!({
            "severity": "warning",
            "title": format!("{unmapped} Haystack point(s) missing driver mapping")
        }));
    }
    if !configured {
        issues.push(json!({
            "severity": "warning",
            "title": "Haystack knowledge graph not populated — import commissioning bundle or sync BACnet"
        }));
    }
    let status = if issues.iter().any(|i| i["severity"] == "critical") {
        "critical"
    } else if issues.is_empty() {
        "ok"
    } else {
        "warning"
    };
    json!({
        "ok": true,
        "status": status,
        "score": score,
        "configured": configured,
        "issues": issues,
        "coverage": coverage
    })
}

pub fn sync_ttl_json() -> Value {
    let path = ttl_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let rows = query::haystack_rows();
    let ttl = crate::model::rdf::haystack_rows_to_turtle(&rows);
    match fs::write(&path, &ttl) {
        Ok(()) => {
            crate::model::rdf::invalidate_store();
            json!({"ok": true, "path": path.display().to_string(), "rows": rows.len()})
        }
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fdd::rules;
    use crate::test_support::with_temp_workspace;

    #[test]
    fn commissioning_export_import_roundtrip_rules() {
        with_temp_workspace(|_| {
            let export = super::commissioning_export_json();
            assert_eq!(export.get("ok").and_then(|v| v.as_bool()), Some(true));
            let mut payload = export.clone();
            payload["points"] = json!([{
                "point_id": "point:test-oa",
                "name": "OAT",
                "equip_ref": "equip:test-1",
                "fdd_input": "oa_t"
            }]);
            payload["fdd_rules"] = json!([{
                "rule_id": "test_rule_roundtrip",
                "name": "Test",
                "sql": "SELECT timestamp, equipment_id, oa_t, false AS fault_raw FROM telemetry_pivot",
                "review_status": "draft"
            }]);
            let imported = super::import_commissioning(&json!({"payload": payload}));
            assert_eq!(imported.get("ok").and_then(|v| v.as_bool()), Some(true));
            let listed = rules::list_rules();
            assert!(listed
                .get("rules")
                .and_then(|v| v.as_array())
                .is_some_and(|a| !a.is_empty()));
        });
    }

    #[test]
    fn tree_and_export_shapes() {
        let tree = tree_json();
        assert_eq!(tree.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert!(tree.get("equipment").is_some());
        assert!(tree.get("points").is_some());
        let export = commissioning_export_json();
        assert_eq!(export.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert!(export.get("fdd_rules").is_some());
    }

    #[test]
    fn health_reports_configured_flag() {
        let body = health_json();
        assert!(body.get("status").is_some());
        assert!(body.get("issues").is_some());
    }
}
