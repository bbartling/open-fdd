//! Haystack-oriented model query layer (replaces SPARQL-only dashboard analytics).

use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

pub fn haystack_rows() -> Vec<Value> {
    crate::model::persist::haystack_model_value()
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
}

pub fn list_sites() -> Value {
    let rows = haystack_rows();
    let mut sites = Vec::new();
    for row in &rows {
        if row.get("site").and_then(|v| v.as_str()) == Some("M") {
            let site_id = row
                .get("id")
                .and_then(|v| v.as_str())
                .unwrap_or("site:unknown");
            let name = row.get("dis").and_then(|v| v.as_str()).unwrap_or(site_id);
            sites.push(json!({"site_id": site_id, "name": name}));
        }
    }
    if sites.is_empty() {
        sites.push(json!({"site_id": "site:demo", "name": "Demo Site"}));
    }
    json!({
        "ok": true,
        "sites": sites,
        "active_site_id": sites.first().and_then(|s| s.get("site_id").and_then(|v| v.as_str()))
    })
}

pub fn list_buildings(site_id: Option<&str>) -> Value {
    let sid = site_id.unwrap_or("site:demo");
    json!({
        "ok": true,
        "site_id": sid,
        "buildings": [{"building_id": "building:main", "name": "Main building", "site_id": sid}]
    })
}

pub fn list_equips(site_id: Option<&str>) -> Value {
    let sid = site_id.unwrap_or("site:demo");
    let mut equips = Vec::new();
    for row in haystack_rows() {
        if row.get("equip").and_then(|v| v.as_str()) == Some("M") {
            equips.push(json!({
                "equipment_id": row.get("id").cloned().unwrap_or(json!(null)),
                "name": row.get("dis").cloned().unwrap_or(json!(null)),
                "site_id": row.get("siteRef").cloned().unwrap_or(json!(sid)),
                "equipment_type": infer_equip_type(&row)
            }));
        }
    }
    json!({"ok": true, "site_id": sid, "equips": equips, "count": equips.len()})
}

pub fn list_points(site_id: Option<&str>) -> Value {
    let sid = site_id.unwrap_or("site:demo");
    let mut points = Vec::new();
    for row in haystack_rows() {
        if row.get("point").and_then(|v| v.as_str()) == Some("M") {
            points.push(json!({
                "point_id": row.get("id").cloned().unwrap_or(json!(null)),
                "name": row.get("dis").cloned().unwrap_or(json!(null)),
                "equip_ref": row.get("equipRef").cloned().unwrap_or(json!(null)),
                "site_id": sid,
                "mapped": is_point_mapped(&row),
                "fdd_input": row.get("fddInput").cloned().unwrap_or(json!(null))
            }));
        }
    }
    json!({"ok": true, "site_id": sid, "points": points, "count": points.len()})
}

pub fn model_coverage() -> Value {
    let rows = haystack_rows();
    let mut equipment_ids = HashSet::new();
    let mut point_count = 0_usize;
    let mut mapped = 0_usize;
    let mut unmapped = 0_usize;
    for row in &rows {
        if row.get("equip").and_then(|v| v.as_str()) == Some("M") {
            if let Some(id) = row.get("id").and_then(|v| v.as_str()) {
                equipment_ids.insert(id.to_string());
            }
        }
        if row.get("point").and_then(|v| v.as_str()) == Some("M") {
            point_count += 1;
            if is_point_mapped(row) {
                mapped += 1;
            } else {
                unmapped += 1;
            }
        }
    }
    let score = if point_count == 0 {
        0.0
    } else {
        (mapped as f64 / point_count as f64) * 100.0
    };
    json!({
        "ok": true,
        "equipment_count": equipment_ids.len(),
        "point_count": point_count,
        "mapped_points": mapped,
        "unmapped_points": unmapped,
        "model_score": (score * 10.0).round() / 10.0,
        "query_engine": "haystack"
    })
}

pub fn source_coverage() -> Value {
    let rows = haystack_rows();
    let mut by_protocol: HashMap<String, usize> = HashMap::new();
    for row in &rows {
        if row.get("point").and_then(|v| v.as_str()) != Some("M") {
            continue;
        }
        let protocol = if row.get("bacnetRef").is_some() {
            "bacnet"
        } else if row.get("modbusRef").is_some() {
            "modbus"
        } else if row.get("fddInput").is_some() {
            "json_api"
        } else {
            "unmapped"
        };
        *by_protocol.entry(protocol.to_string()).or_insert(0) += 1;
    }
    let protocols: Vec<Value> = by_protocol
        .into_iter()
        .map(|(protocol, count)| json!({"protocol": protocol, "point_count": count}))
        .collect();
    json!({"ok": true, "protocols": protocols})
}

pub fn unmapped_points() -> Value {
    let mut points = Vec::new();
    for row in haystack_rows() {
        if row.get("point").and_then(|v| v.as_str()) == Some("M") && !is_point_mapped(&row) {
            points.push(json!({
                "point_id": row.get("id").cloned().unwrap_or(json!(null)),
                "name": row.get("dis").cloned().unwrap_or(json!(null)),
                "equip_ref": row.get("equipRef").cloned().unwrap_or(json!(null))
            }));
        }
    }
    json!({"ok": true, "count": points.len(), "points": points})
}

pub fn group_points_by_equip() -> Value {
    let mut groups: HashMap<String, Vec<Value>> = HashMap::new();
    for row in haystack_rows() {
        if row.get("point").and_then(|v| v.as_str()) != Some("M") {
            continue;
        }
        let equip = row
            .get("equipRef")
            .and_then(|v| v.as_str())
            .unwrap_or("unassigned")
            .to_string();
        groups.entry(equip).or_default().push(json!({
            "point_id": row.get("id").cloned().unwrap_or(json!(null)),
            "name": row.get("dis").cloned().unwrap_or(json!(null)),
            "mapped": is_point_mapped(&row)
        }));
    }
    let grouped: Vec<Value> = groups
        .into_iter()
        .map(|(equip_ref, points)| json!({"equip_ref": equip_ref, "points": points, "count": points.len()}))
        .collect();
    json!({"ok": true, "groups": grouped})
}

fn is_point_mapped(row: &Value) -> bool {
    row.get("fddInput").is_some()
        || row.get("bacnetRef").is_some()
        || row.get("modbusRef").is_some()
}

fn infer_equip_type(row: &Value) -> &'static str {
    if row.get("ahu").is_some() {
        "ahu"
    } else if row.get("vav").is_some() {
        "vav"
    } else if row.get("chiller").is_some() {
        "chiller"
    } else {
        "generic"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn groups_equips_and_counts_unmapped() {
        let coverage = model_coverage();
        assert!(
            coverage
                .get("equipment_count")
                .and_then(|v| v.as_u64())
                .unwrap_or(0)
                >= 1
        );
        let unmapped = unmapped_points();
        assert!(unmapped.get("count").is_some());
        let grouped = group_points_by_equip();
        assert!(grouped.get("groups").and_then(|v| v.as_array()).is_some());
    }
}
