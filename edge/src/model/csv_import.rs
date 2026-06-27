//! Auto-build Haystack grid + assignments from CSV headers (filename-derived IDs).

use super::{assignments, persist};
use serde_json::{json, Value};
use std::collections::HashMap;

pub fn slugify(s: &str) -> String {
    let mut out = String::new();
    let mut prev_dash = false;
    for c in s.to_lowercase().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c);
            prev_dash = false;
        } else if !prev_dash {
            out.push('-');
            prev_dash = true;
        }
    }
    out.trim_matches('-').to_string()
}

pub fn slug_from_filename(name: &str) -> String {
    let base = name.rsplit(['/', '\\']).next().unwrap_or(name).trim();
    let stem = base
        .strip_suffix(".csv")
        .or_else(|| base.strip_suffix(".CSV"))
        .unwrap_or(base);
    let slug = slugify(stem);
    if slug.is_empty() {
        "csv-import".into()
    } else {
        slug
    }
}

pub fn ids_from_filename(filename: &str) -> (String, String, String, String) {
    let slug = slug_from_filename(filename);
    let display = filename
        .rsplit(['/', '\\'])
        .next()
        .unwrap_or(filename)
        .strip_suffix(".csv")
        .or_else(|| filename.strip_suffix(".CSV"))
        .unwrap_or(filename)
        .to_string();
    (
        format!("site:{slug}"),
        format!("equip:{slug}"),
        format!("source:csv:{slug}"),
        display,
    )
}

pub fn column_slug(header: &str) -> String {
    let mut out = String::new();
    let mut prev_us = false;
    for c in header.trim().to_lowercase().chars() {
        if c.is_ascii_alphanumeric() {
            out.push(c);
            prev_us = false;
        } else if !prev_us {
            out.push('_');
            prev_us = true;
        }
    }
    out.trim_matches('_').to_string()
}

fn is_timestamp_header(header: &str) -> bool {
    let lower = header.trim().to_lowercase();
    ["datetime", "date", "timestamp", "time", "ts"]
        .iter()
        .any(|t| lower == *t || lower.contains("date") || lower.contains("time"))
}

pub fn find_timestamp_column(headers: &[String]) -> usize {
    headers
        .iter()
        .position(|h| is_timestamp_header(h))
        .unwrap_or(0)
}

fn infer_unit(slug: &str) -> &'static str {
    if slug.contains("humid") || slug.ends_with("_h") || slug.contains("_rh") {
        "%RH"
    } else if slug.contains("percent") || slug.ends_with("_pct") || slug.contains("cmd") {
        "%"
    } else if slug.contains("kw") || slug.contains("power") {
        "kW"
    } else if slug.contains("cfm") || slug.contains("flow") {
        "cfm"
    } else {
        "°F"
    }
}

fn pivot_alias(slug: &str) -> Option<&'static str> {
    match slug {
        "oa_t" | "oat" | "outside_air_temp" | "outside_air_temperature" | "outdoor_air_temp" => {
            Some("oa_t")
        }
        "oa_h" | "outside_air_humidity" | "outdoor_air_humidity" => Some("oa_h"),
        "sat" | "supply_air_temp" | "sa_t" => Some("sat"),
        "duct_t" | "discharge_air_temp" => Some("duct_t"),
        "zn_t" | "zone_temp" | "zone_temperature" | "space_temp" => Some("zn_t"),
        "sat_sp" | "supply_air_temp_sp" | "sat_setpoint" => Some("sat_sp"),
        "fan_cmd" | "fan_status" | "fan" => Some("fan_cmd"),
        "duct_static" | "static_pressure" => Some("duct_static"),
        "occ" | "occupancy" | "occupancy_mode_indicator" => Some("occ"),
        _ => pivot_alias_fuzzy(slug),
    }
}

fn pivot_alias_fuzzy(slug: &str) -> Option<&'static str> {
    if slug.contains("outdoor_air_temp") || slug.contains("outside_air_temp") {
        return Some("oa_t");
    }
    if slug.contains("supply_air_temp") && slug.contains("set") {
        return Some("sat_sp");
    }
    if slug.contains("supply_air_temp") {
        return Some("sat");
    }
    if slug.contains("duct_static") && slug.contains("set") {
        return Some("duct_static_sp");
    }
    if slug.contains("duct_static") || slug.contains("static_pressure") {
        return Some("duct_static");
    }
    if slug.contains("fan_status") || slug.contains("fan_speed") || slug.ends_with("_fan_status") {
        return Some("fan_cmd");
    }
    if slug.contains("occupancy") {
        return Some("occ");
    }
    if slug.contains("return_air_temp") || slug.contains("mixed_air_temp") {
        return Some("duct_t");
    }
    None
}

pub fn apply_pivot_aliases(row: &mut Value, slug: &str, value: f64) {
    if let Some(alias) = pivot_alias(slug) {
        if let Some(obj) = row.as_object_mut() {
            obj.insert(alias.to_string(), json!(value));
        }
    }
}

fn merge_grid_rows(existing: &[Value], incoming: &[Value]) -> Vec<Value> {
    let mut by_id: HashMap<String, Value> = HashMap::new();
    for row in existing {
        if let Some(id) = row.get("id").and_then(|v| v.as_str()) {
            by_id.insert(id.to_string(), row.clone());
        }
    }
    for row in incoming {
        if let Some(id) = row.get("id").and_then(|v| v.as_str()) {
            by_id.insert(id.to_string(), row.clone());
        }
    }
    by_id.into_values().collect()
}

fn merge_assignment_points(existing: &[Value], incoming: &[Value]) -> Vec<Value> {
    let mut by_id: HashMap<String, Value> = HashMap::new();
    for pt in existing {
        if let Some(id) = pt.get("haystack_id").and_then(|v| v.as_str()) {
            by_id.insert(id.to_string(), pt.clone());
        }
    }
    for pt in incoming {
        if let Some(id) = pt.get("haystack_id").and_then(|v| v.as_str()) {
            by_id.insert(id.to_string(), pt.clone());
        }
    }
    by_id.into_values().collect()
}

pub fn import_from_csv_commit(headers: &[String], filename: &str, job_id: &str) -> Value {
    let (site_id, equip_id, source_id, display_name) = ids_from_filename(filename);
    let ts_idx = find_timestamp_column(headers);
    let mut value_headers: Vec<(String, String)> = Vec::new();
    for (i, header) in headers.iter().enumerate() {
        if i == ts_idx {
            continue;
        }
        let trimmed = header.trim();
        if trimmed.is_empty() {
            continue;
        }
        let slug = column_slug(trimmed);
        if slug.is_empty() {
            continue;
        }
        value_headers.push((trimmed.to_string(), slug));
    }

    let mut rows: Vec<Value> = vec![
        json!({
            "id": site_id,
            "dis": display_name.clone(),
            "site": "M"
        }),
        json!({
            "id": equip_id,
            "dis": display_name,
            "equip": "M",
            "siteRef": site_id,
            "sourceRef": source_id
        }),
        json!({
            "id": source_id,
            "dis": format!("CSV source ({})", slug_from_filename(filename)),
            "source": "M",
            "protocol": "csv",
            "importJob": job_id
        }),
    ];

    let base = slug_from_filename(filename);
    let mut assignment_points: Vec<Value> = Vec::new();
    for (header, slug) in &value_headers {
        let point_id = format!("point:{base}-{slug}");
        rows.push(json!({
            "id": point_id,
            "dis": header,
            "point": "M",
            "sensor": "M",
            "kind": "Number",
            "unit": infer_unit(slug),
            "equipRef": equip_id,
            "sourceRef": source_id,
            "fddInput": slug,
            "csvRef": format!("csv:{source_id}:{slug}")
        }));
        assignment_points.push(json!({
            "haystack_id": point_id,
            "dis": header,
            "kind": "sensor",
            "equip_ref": equip_id,
            "unit": infer_unit(slug),
            "driver_bindings": [{
                "driver": "csv",
                "ref": format!("csv:{source_id}:{slug}"),
                "priority": 1
            }],
            "storage_ref": format!("arrow://csv/{base}/{slug}"),
            "external_refs": [{
                "system": "csv",
                "ref": format!("{}/{header}", filename.rsplit(['/', '\\']).next().unwrap_or(filename))
            }]
        }));
    }

    let existing_grid = persist::haystack_model_value();
    let existing_rows = existing_grid
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let merged_rows = merge_grid_rows(&existing_rows, &rows);
    let grid = json!({
        "meta": {
            "ver": "3.0",
            "mode": "csv-import",
            "source_filename": filename,
            "job_id": job_id
        },
        "cols": [],
        "rows": merged_rows
    });

    let grid_save = persist::save_haystack_grid(&grid);
    let mut current = assignments::load_assignments_value();
    let existing_pts = current
        .get("points")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let merged_pts = merge_assignment_points(&existing_pts, &assignment_points);
    current["points"] = json!(merged_pts);
    let assign_save = assignments::save_assignments_value(&current);

    json!({
        "ok": grid_save.is_ok() && assign_save.is_ok(),
        "site_id": site_id,
        "equipment_id": equip_id,
        "source_id": source_id,
        "points_added": assignment_points.len(),
        "columns_modeled": value_headers.len(),
        "grid_path": grid_save.as_ref().ok().map(|p| p.display().to_string()),
        "assignments_path": assign_save.as_ref().ok().map(|p| p.display().to_string()),
        "error": grid_save
            .as_ref()
            .err()
            .or(assign_save.as_ref().err())
            .map(|e| e.to_string())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_from_ahu_filename() {
        assert_eq!(slug_from_filename("ahu_mzvav_1.csv"), "ahu-mzvav-1");
    }

    #[test]
    fn ids_from_filename_shape() {
        let (site, equip, source, _) = ids_from_filename("trend_export.csv");
        assert_eq!(site, "site:trend-export");
        assert_eq!(equip, "equip:trend-export");
        assert_eq!(source, "source:csv:trend-export");
    }

    #[test]
    fn pivot_alias_maps_mzvav_headers() {
        let slug = column_slug("AHU: Supply Air Temperature");
        let mut row = json!({});
        apply_pivot_aliases(&mut row, &slug, 75.0);
        assert_eq!(row.get("sat").and_then(|v| v.as_f64()), Some(75.0));
    }

    #[test]
    fn timestamp_column_detection() {
        let headers = vec!["Date".into(), "SAT".into()];
        assert_eq!(find_timestamp_column(&headers), 0);
    }
}
