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
        return json!({
            "ok": true,
            "sites": sites,
            "active_site_id": Value::Null
        });
    }
    json!({
        "ok": true,
        "sites": sites,
        "active_site_id": sites.first().and_then(|s| s.get("site_id").and_then(|v| v.as_str()))
    })
}

pub fn list_buildings(site_id: Option<&str>) -> Value {
    let sid = super::scope::resolve_site_id(site_id);
    json!({
        "ok": true,
        "site_id": sid,
        "buildings": if sid.is_some() {
            json!([{"building_id": "building:main", "name": "Main building", "site_id": sid}])
        } else {
            json!([])
        }
    })
}

pub fn list_equipment(site_id: &str) -> Value {
    let equips = list_equips(Some(site_id));
    let equipment: Vec<Value> = equips
        .get("equips")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|row| {
            let equipment_id = row.get("equipment_id").cloned().unwrap_or(json!(null));
            json!({
                "id": equipment_id.clone(),
                "equipment_id": equipment_id,
                "name": row.get("name").cloned().unwrap_or(json!(null)),
                "site_id": row.get("site_id").cloned().unwrap_or(json!(site_id)),
                "equipment_type": row.get("equipment_type").cloned().unwrap_or(json!(null))
            })
        })
        .collect();
    json!({
        "ok": true,
        "site_id": site_id,
        "equipment": equipment,
        "count": equipment.len()
    })
}

pub fn list_equips(site_id: Option<&str>) -> Value {
    let sid = super::scope::resolve_site_id(site_id);
    let mut equips = Vec::new();
    for row in haystack_rows() {
        if row.get("equip").and_then(|v| v.as_str()) == Some("M") {
            let row_site = row.get("siteRef").and_then(|v| v.as_str());
            if let Some(filter) = sid.as_deref() {
                if row_site != Some(filter) {
                    continue;
                }
            }
            equips.push(json!({
                "equipment_id": row.get("id").cloned().unwrap_or(json!(null)),
                "name": row.get("dis").cloned().unwrap_or(json!(null)),
                "site_id": row.get("siteRef").cloned().unwrap_or(json!(null)),
                "equipment_type": infer_equip_type(&row)
            }));
        }
    }
    json!({"ok": true, "site_id": sid, "equips": equips, "count": equips.len()})
}

pub fn list_points(site_id: Option<&str>) -> Value {
    let sid = super::scope::resolve_site_id(site_id);
    let equip_site = super::scope::equip_site_map();
    let mut points = Vec::new();
    for row in haystack_rows() {
        if row.get("point").and_then(|v| v.as_str()) == Some("M") {
            let equip_ref = row.get("equipRef").and_then(|v| v.as_str());
            let point_site = equip_ref.and_then(|e| equip_site.get(e).cloned());
            if let Some(filter) = sid.as_deref() {
                if point_site.as_deref() != Some(filter) {
                    continue;
                }
            }
            points.push(json!({
                "point_id": row.get("id").cloned().unwrap_or(json!(null)),
                "name": row.get("dis").cloned().unwrap_or(json!(null)),
                "equip_ref": row.get("equipRef").cloned().unwrap_or(json!(null)),
                "site_id": point_site,
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
        let protocol = if row.get("csvRef").is_some() {
            "csv"
        } else if row.get("bacnetRef").is_some() {
            "bacnet"
        } else if row.get("modbusRef").is_some() {
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
    use crate::model::csv_import;
    use crate::test_support::with_temp_workspace;

    #[test]
    fn list_points_filters_by_csv_import_site() {
        with_temp_workspace(|_| {
            let model = csv_import::import_from_csv_commit(
                &["Date".to_string(), "Outdoor Air Temp".to_string()],
                "Plant-A.csv",
                "job-1",
                None,
            );
            assert_eq!(model.get("ok").and_then(|v| v.as_bool()), Some(true));
            let (site, equip, _, _) = csv_import::ids_from_filename("Plant-A.csv");
            assert_eq!(
                crate::model::scope::site_for_equipment(&equip).as_deref(),
                Some(site.as_str())
            );
            let pts = list_points(Some(&site));
            assert!(
                pts.get("count").and_then(|v| v.as_u64()).unwrap_or(0) >= 1,
                "expected points for {site}: {pts}"
            );
        });
    }

    #[test]
    fn groups_equips_and_counts_unmapped() {
        let coverage = model_coverage();
        assert!(coverage
            .get("equipment_count")
            .and_then(|v| v.as_u64())
            .is_some());
        assert!(coverage
            .get("point_count")
            .and_then(|v| v.as_u64())
            .is_some());
        let unmapped = unmapped_points();
        assert!(unmapped.get("count").is_some());
        let grouped = group_points_by_equip();
        assert!(grouped.get("groups").and_then(|v| v.as_array()).is_some());
    }
}
