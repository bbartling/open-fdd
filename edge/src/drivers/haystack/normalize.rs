//! Normalize Haystack grid rows into Open-FDD model entities and telemetry samples.

use serde_json::{json, Value};
use std::collections::BTreeMap;

pub fn grid_rows(records: &Value) -> Vec<Value> {
    records
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .or_else(|| {
            records
                .get("records")
                .and_then(|r| r.get("rows"))
                .and_then(|v| v.as_array())
                .cloned()
        })
        .unwrap_or_default()
}

pub fn rows_to_model_grid(rows: &[Value], source_id: &str, site_id: &str) -> Value {
    let mut out_rows: Vec<Value> = rows.to_vec();
    if !out_rows
        .iter()
        .any(|r| r.get("site").and_then(|v| v.as_str()) == Some("M"))
    {
        out_rows.insert(
            0,
            json!({"id": site_id, "dis": "Imported site", "site": "M"}),
        );
    }
    json!({
        "meta": {"ver": "3.0", "mode": "import", "source_id": source_id},
        "cols": [
            {"name": "id"},
            {"name": "dis"},
            {"name": "site"},
            {"name": "equip"},
            {"name": "point"},
            {"name": "sensor"},
            {"name": "kind"},
            {"name": "unit"},
            {"name": "curVal"},
            {"name": "source_id"}
        ],
        "rows": out_rows.iter().map(|row| {
            let mut r = row.clone();
            if let Some(obj) = r.as_object_mut() {
                obj.entry("source_id".to_string())
                    .or_insert(json!(source_id));
            }
            r
        }).collect::<Vec<_>>()
    })
}

pub fn normalize_sources(rows: &[Value], source_id: &str, source_type: &str) -> Vec<Value> {
    vec![json!({
        "id": source_id,
        "type": source_type,
        "label": "Haystack source",
        "point_count": rows.iter().filter(|r| r.get("point").and_then(|v| v.as_str()) == Some("M")).count()
    })]
}

pub fn normalize_equipment(rows: &[Value], site_id: &str) -> Vec<Value> {
    rows.iter()
        .filter(|r| r.get("equip").and_then(|v| v.as_str()) == Some("M"))
        .map(|r| {
            json!({
                "id": r.get("id").cloned().unwrap_or(json!(null)),
                "dis": r.get("dis").cloned().unwrap_or(json!(null)),
                "site_id": site_id,
                "siteRef": r.get("siteRef").cloned().unwrap_or(json!(site_id))
            })
        })
        .collect()
}

pub fn normalize_points(rows: &[Value], source_id: &str) -> Vec<Value> {
    rows.iter()
        .filter(|r| r.get("point").and_then(|v| v.as_str()) == Some("M"))
        .map(|r| {
            let id = r.get("id").and_then(|v| v.as_str()).unwrap_or("");
            json!({
                "id": id,
                "dis": r.get("dis").cloned().unwrap_or(json!(id)),
                "haystack_id": id,
                "kind": r.get("kind").cloned().unwrap_or(json!(null)),
                "unit": r.get("unit").cloned().unwrap_or(json!(null)),
                "curVal": r.get("curVal").cloned().unwrap_or(json!(null)),
                "equipRef": r.get("equipRef").cloned().unwrap_or(json!(null)),
                "source_id": source_id,
                "mapping_status": if r.get("bacnetRef").is_some() || r.get("fddInput").is_some() {
                    "mapped"
                } else {
                    "unmapped"
                },
                "tags": r
            })
        })
        .collect()
}

pub fn build_driver_tree(rows: &[Value], source_id: &str, base_url: &str) -> Value {
    let points = normalize_points(rows, source_id);
    let mut sites: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for pt in points {
        let site = pt
            .get("equipRef")
            .and_then(|v| v.as_str())
            .unwrap_or("site:local")
            .to_string();
        sites.entry(site).or_default().push(pt);
    }
    let devices: Vec<Value> = sites
        .into_iter()
        .map(|(site_id, pts)| {
            json!({
                "device_key": site_id.clone(),
                "host": base_url,
                "site_id": site_id,
                "point_count": pts.len(),
                "poll_count": 0,
                "points": pts
            })
        })
        .collect();
    json!({
        "ok": true,
        "enabled": true,
        "source_id": source_id,
        "devices": devices
    })
}

pub fn poll_samples(rows: &[Value], source_id: &str) -> Vec<Value> {
    let now = chrono::Utc::now().to_rfc3339();
    rows.iter()
        .filter(|r| r.get("point").and_then(|v| v.as_str()) == Some("M"))
        .filter_map(|r| {
            let id = r.get("id").and_then(|v| v.as_str())?;
            let val = r.get("curVal").cloned().or_else(|| r.get("val").cloned())?;
            Some(json!({
                "source_id": source_id,
                "point_id": id,
                "haystack_id": id,
                "value": val,
                "unit": r.get("unit").cloned().unwrap_or(json!(null)),
                "timestamp": now
            }))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::drivers::haystack::fixture;

    #[test]
    fn normalize_points_from_fixture() {
        let rows = grid_rows(&fixture::fixture_grid());
        let pts = normalize_points(&rows, "source:test");
        assert_eq!(pts.len(), 4);
        assert_eq!(pts[0]["mapping_status"], "mapped");
    }

    #[test]
    fn build_tree_groups_by_equip_ref() {
        let rows = grid_rows(&fixture::fixture_grid());
        let tree = build_driver_tree(&rows, "source:test", "http://example/haystack");
        assert!(tree["devices"].as_array().unwrap().len() >= 1);
    }
}
