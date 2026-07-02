//! Resolve site/equipment scope from the persisted Haystack model and historian — no demo IDs.

use super::{assignments, query};
use crate::historian::store;
use serde_json::{json, Value};
use std::collections::HashMap;

pub fn equip_site_map() -> HashMap<String, String> {
    let mut map = HashMap::new();
    for row in query::haystack_rows() {
        if row.get("equip").and_then(|v| v.as_str()) != Some("M") {
            continue;
        }
        if let (Some(eid), Some(site)) = (
            row.get("id").and_then(|v| v.as_str()),
            row.get("siteRef").and_then(|v| v.as_str()),
        ) {
            map.insert(eid.to_string(), site.to_string());
        }
    }
    map
}

pub fn active_site_id() -> Option<String> {
    query::list_sites()
        .get("active_site_id")
        .and_then(|v| v.as_str())
        .map(str::to_string)
}

pub fn resolve_site_id(explicit: Option<&str>) -> Option<String> {
    explicit
        .filter(|s| !s.trim().is_empty())
        .map(str::to_string)
        .or_else(active_site_id)
}

pub fn site_for_equipment(equipment_id: &str) -> Option<String> {
    equip_site_map()
        .get(equipment_id)
        .cloned()
        .or_else(active_site_id)
}

pub fn first_equipment_id() -> Option<String> {
    for row in query::haystack_rows() {
        if row.get("equip").and_then(|v| v.as_str()) == Some("M") {
            if let Some(id) = row.get("id").and_then(|v| v.as_str()) {
                return Some(id.to_string());
            }
        }
    }
    store::load_pivot_rows().ok().and_then(|rows| {
        rows.first()
            .and_then(|r| r.get("equipment_id").and_then(|v| v.as_str()))
            .map(str::to_string)
    })
}

pub fn resolve_equipment_id(explicit: Option<&str>) -> Option<String> {
    explicit
        .filter(|s| !s.trim().is_empty())
        .map(str::to_string)
        .or_else(first_equipment_id)
}

pub fn source_protocols_for_equipment(equipment_id: &str) -> Vec<String> {
    let mut out = Vec::new();
    let assign = assignments::load_assignments_value();
    let Some(points) = assign.get("points").and_then(|v| v.as_array()) else {
        return out;
    };
    for pt in points {
        if pt.get("equip_ref").and_then(|v| v.as_str()) != Some(equipment_id) {
            continue;
        }
        if let Some(bindings) = pt.get("driver_bindings").and_then(|v| v.as_array()) {
            for b in bindings {
                if let Some(driver) = b.get("driver").and_then(|v| v.as_str()) {
                    if !out.contains(&driver.to_string()) {
                        out.push(driver.to_string());
                    }
                }
            }
        }
    }
    if out.is_empty() {
        for row in query::haystack_rows() {
            if row.get("equipRef").and_then(|v| v.as_str()) != Some(equipment_id) {
                continue;
            }
            if row.get("csvRef").is_some() && !out.contains(&"csv".into()) {
                out.push("csv".into());
            }
            if row.get("bacnetRef").is_some() && !out.contains(&"bacnet".into()) {
                out.push("bacnet".into());
            }
            if row.get("modbusRef").is_some() && !out.contains(&"modbus".into()) {
                out.push("modbus".into());
            }
        }
    }
    out
}

pub fn driver_points_from_model() -> Vec<Value> {
    let mut out = Vec::new();
    for row in query::haystack_rows() {
        if row.get("point").and_then(|v| v.as_str()) != Some("M") {
            continue;
        }
        let id = row.get("id").and_then(|v| v.as_str()).unwrap_or("");
        out.push(json!({
            "id": id,
            "name": row.get("dis").cloned().unwrap_or(json!(id)),
            "haystack_id": id,
            "fdd_input": row.get("fddInput").cloned().unwrap_or(Value::Null),
            "ref": row.get("csvRef")
                .or_else(|| row.get("bacnetRef"))
                .or_else(|| row.get("modbusRef"))
                .cloned()
                .unwrap_or(Value::Null)
        }));
    }
    out
}

pub fn required_inputs_for_rule(rule: &Value) -> Vec<String> {
    rule.get("required_inputs")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::persist;
    use crate::test_support::with_temp_workspace;

    fn with_grid(rows: Vec<Value>, f: impl FnOnce()) {
        with_temp_workspace(|_| {
            let grid = json!({"meta":{"ver":"3.0","mode":"test"},"cols":[],"rows":rows});
            let _ = persist::save_haystack_grid(&grid);
            f();
        });
    }

    #[test]
    fn active_site_from_grid_not_demo() {
        with_grid(
            vec![json!({"id":"site:plant-a","dis":"Plant A","site":"M"})],
            || {
                assert_eq!(active_site_id().as_deref(), Some("site:plant-a"));
            },
        );
    }

    #[test]
    fn empty_grid_has_no_active_site() {
        with_grid(vec![], || {
            assert!(active_site_id().is_none());
        });
    }

    #[test]
    fn default_model_when_no_file_on_disk() {
        with_temp_workspace(|root| {
            let path = root.join("data/model/haystack_grid.json");
            assert!(!path.exists());
            let grid = persist::haystack_model_value();
            let rows = grid.get("rows").and_then(|v| v.as_array()).unwrap();
            assert_eq!(rows.len(), 2);
            assert_eq!(
                rows[0].get("id").and_then(|v| v.as_str()),
                Some("site:local")
            );
            assert_eq!(
                rows[1].get("id").and_then(|v| v.as_str()),
                Some("equip:local-test-equipment")
            );
        });
    }

    #[test]
    fn site_for_equipment_from_equip_row() {
        with_grid(
            vec![
                json!({"id":"site:x","dis":"X","site":"M"}),
                json!({"id":"equip:ahu-1","dis":"AHU 1","equip":"M","siteRef":"site:x"}),
            ],
            || {
                assert_eq!(site_for_equipment("equip:ahu-1").as_deref(), Some("site:x"));
            },
        );
    }
}
