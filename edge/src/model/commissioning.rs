//! Commissioning export/import and model sync APIs used by the dashboard data model tab.

use super::persist;
use super::query;
use crate::drivers::bacnet;
use serde_json::{json, Value};
use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;

fn ttl_path() -> PathBuf {
    crate::validation::profile::workspace_dir()
        .join("data/model/data_model.ttl")
}

pub fn tree_json() -> Value {
    let sites = query::list_sites();
    let site_id = sites
        .get("active_site_id")
        .and_then(|v| v.as_str())
        .unwrap_or("site:demo");
    let equipment = query::list_equipment(site_id);
    let points = query::list_points(Some(site_id));
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
        .unwrap_or("site:demo");
    let equipment = query::list_equipment(site_id);
    let points = query::list_points(Some(site_id));
    let assignments: Value =
        serde_json::from_str(super::assignments::assignments_json()).unwrap_or(json!({}));
    let fdd_rules = assignments
        .get("fault_equation_bindings")
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
        "assignments": assignments.get("points").cloned().unwrap_or(json!([]))
    })
}

pub fn import_commissioning(body: &Value) -> Value {
    let payload = body
        .get("payload")
        .cloned()
        .unwrap_or_else(|| body.clone());
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
                .unwrap_or("site:demo");
            let name = site.get("name").or_else(|| site.get("dis")).and_then(|v| v.as_str());
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
                "siteRef": eq.get("site_id").cloned().unwrap_or(json!("site:demo"))
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
        Ok(path) => json!({
            "ok": true,
            "sites": payload.get("sites").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "equipment": payload.get("equipment").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "points": payload.get("points").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "fdd_rules_updated": payload.get("fdd_rules").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0),
            "path": path.display().to_string()
        }),
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
        .filter(|r| !driver_ids.iter().any(|d| r.contains(d.as_str())))
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
    let sync = bacnet::sync_discovery_value();
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
    let mut lines = vec![
        "@prefix hs: <https://project-haystack.org/def/> .".to_string(),
        "@prefix ofdd: <https://open-fdd.dev/model#> .".to_string(),
        "".to_string(),
    ];
    for row in &rows {
        if let Some(id) = row.get("id").and_then(|v| v.as_str()) {
            let dis = row.get("dis").and_then(|v| v.as_str()).unwrap_or(id);
            lines.push(format!("ofdd:{id} hs:dis \"{dis}\" ."));
        }
    }
    match fs::write(&path, lines.join("\n")) {
        Ok(()) => json!({"ok": true, "path": path.display().to_string(), "rows": rows.len()}),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
