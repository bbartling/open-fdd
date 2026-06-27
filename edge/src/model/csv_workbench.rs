//! UT3-style CSV workbench: preview, quality, recipes, column mappings, rule drafts, source purge.

use super::{assignments, csv_import, persist, query};
use crate::fdd::execution;
use crate::fdd::rules;
use crate::historian::store;
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;

fn workbench_dir() -> PathBuf {
    crate::validation::profile::workspace_dir().join("data/csv_workbench")
}

fn recipes_dir() -> PathBuf {
    workbench_dir().join("recipes")
}

fn column_mappings_path() -> PathBuf {
    workbench_dir().join("column_mappings.json")
}

pub fn known_fdd_inputs() -> Value {
    execution::fdd_inputs_json()
}

pub fn load_column_mappings() -> HashMap<String, HashMap<String, String>> {
    let path = column_mappings_path();
    let Ok(text) = fs::read_to_string(path) else {
        return HashMap::new();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

pub fn resolve_fdd_input(
    header: &str,
    slug: &str,
    mappings: &HashMap<String, HashMap<String, String>>,
) -> String {
    if let Some(map) = mappings.get("_global") {
        if let Some(v) = map.get(header) {
            return v.clone();
        }
    }
    csv_import::pivot_alias(slug)
        .map(str::to_string)
        .unwrap_or_else(|| slug.to_string())
}

pub fn save_column_mappings(body: &Value) -> Value {
    let source_id = body
        .get("source_id")
        .and_then(|v| v.as_str())
        .unwrap_or("_global");
    let mappings = body.get("mappings").and_then(|v| v.as_object());
    let Some(mappings) = mappings else {
        return json!({"ok": false, "error": "mappings object required"});
    };
    let mut all = load_column_mappings();
    let mut entry = HashMap::new();
    for (k, v) in mappings {
        if let Some(s) = v.as_str() {
            entry.insert(k.clone(), s.to_string());
        }
    }
    all.insert(source_id.to_string(), entry);
    if let Some(parent) = column_mappings_path().parent() {
        let _ = fs::create_dir_all(parent);
    }
    match fs::write(
        column_mappings_path(),
        serde_json::to_string_pretty(&all).unwrap_or_else(|_| "{}".into()),
    ) {
        Ok(()) => {
            json!({"ok": true, "source_id": source_id, "count": all.get(source_id).map(|m| m.len()).unwrap_or(0)})
        }
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

pub fn get_column_mappings(source_id: Option<&str>) -> Value {
    let all = load_column_mappings();
    if let Some(sid) = source_id {
        json!({
            "ok": true,
            "source_id": sid,
            "mappings": all.get(sid).cloned().unwrap_or_default()
        })
    } else {
        json!({"ok": true, "mappings": all})
    }
}

pub fn preview_model(body: &Value) -> Value {
    let filename = body
        .get("source_filename")
        .and_then(|v| v.as_str())
        .unwrap_or("import.csv");
    let headers: Vec<String> = body
        .get("headers")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    if headers.is_empty() {
        return json!({"ok": false, "error": "headers array required"});
    }
    let (site_id, equip_id, source_id, display_name) = csv_import::ids_from_filename(filename);
    let ts_idx = csv_import::find_timestamp_column(&headers);
    let all_maps = load_column_mappings();
    let source_maps = all_maps.get(&source_id).cloned().unwrap_or_default();
    let mut combined = HashMap::new();
    combined.extend(all_maps.get("_global").cloned().unwrap_or_default());
    combined.extend(source_maps);

    let mut points = Vec::new();
    for (i, header) in headers.iter().enumerate() {
        if i == ts_idx {
            continue;
        }
        let trimmed = header.trim();
        if trimmed.is_empty() {
            continue;
        }
        let slug = csv_import::column_slug(trimmed);
        if slug.is_empty() {
            continue;
        }
        let auto = csv_import::pivot_alias(&slug).map(str::to_string);
        let fdd_input = combined
            .get(trimmed)
            .cloned()
            .or_else(|| auto.clone())
            .unwrap_or_else(|| slug.clone());
        let base = csv_import::slug_from_filename(filename);
        points.push(json!({
            "header": trimmed,
            "column_slug": slug,
            "point_id": format!("point:{base}-{slug}"),
            "fdd_input": fdd_input,
            "auto_fdd_input": auto,
            "mapped_override": combined.contains_key(trimmed)
        }));
    }

    json!({
        "ok": true,
        "source_filename": filename,
        "display_name": display_name,
        "site_id": site_id,
        "equipment_id": equip_id,
        "source_id": source_id,
        "timestamp_column": headers.get(ts_idx),
        "point_count": points.len(),
        "points": points,
        "known_fdd_inputs": execution::fdd_inputs_json().get("fdd_inputs").cloned().unwrap_or(json!([]))
    })
}

pub fn analyze_quality(body: &Value) -> Value {
    let headers: Vec<String> = body
        .get("headers")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let rows: Vec<Vec<String>> = body
        .get("rows")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|r| {
                    r.as_array().map(|cells| {
                        cells
                            .iter()
                            .map(|c| c.as_str().unwrap_or("").to_string())
                            .collect()
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    if headers.is_empty() {
        return json!({"ok": false, "error": "headers required"});
    }
    let ts_idx = csv_import::find_timestamp_column(&headers);
    let mut warnings = Vec::new();
    let mut duplicate_timestamps = 0usize;
    let mut seen_ts = HashSet::new();
    let mut null_by_col: HashMap<usize, usize> = HashMap::new();
    for col in 0..headers.len() {
        null_by_col.insert(col, 0);
    }
    for row in &rows {
        for (i, cell) in row.iter().enumerate() {
            if cell.trim().is_empty() {
                *null_by_col.entry(i).or_insert(0) += 1;
            }
        }
        if let Some(ts) = row.get(ts_idx) {
            if !seen_ts.insert(ts.clone()) {
                duplicate_timestamps += 1;
            }
        }
    }
    let row_count = rows.len();
    let mut sparse_columns = Vec::new();
    for (i, header) in headers.iter().enumerate() {
        let nulls = null_by_col.get(&i).copied().unwrap_or(0);
        if row_count > 0 && nulls * 2 > row_count {
            sparse_columns.push(json!({"header": header, "empty_or_null_pct": (nulls as f64 / row_count as f64) * 100.0}));
        }
    }
    if duplicate_timestamps > 0 {
        warnings.push(json!({
            "severity": "warning",
            "code": "duplicate_timestamps",
            "message": format!("{duplicate_timestamps} duplicate timestamp value(s) in sample")
        }));
    }
    if !sparse_columns.is_empty() {
        warnings.push(json!({
            "severity": "info",
            "code": "sparse_columns",
            "message": format!("{} column(s) are >50% empty in sample", sparse_columns.len()),
            "columns": sparse_columns
        }));
    }
    let sample_ts = rows
        .first()
        .and_then(|r| r.get(ts_idx))
        .map(|s| s.as_str())
        .unwrap_or("");
    if sample_ts.contains('/') && !sample_ts.contains('T') && !sample_ts.contains('+') {
        warnings.push(json!({
            "severity": "info",
            "code": "timezone_ambiguous",
            "message": "Timestamps look like local US-style dates without explicit timezone — historian stores as parsed local strings"
        }));
    }
    json!({
        "ok": true,
        "row_count_sampled": row_count,
        "duplicate_timestamps": duplicate_timestamps,
        "timestamp_column": headers.get(ts_idx),
        "warnings": warnings,
        "ready_to_commit": duplicate_timestamps == 0 || row_count == 0
    })
}

pub fn list_recipes() -> Value {
    let dir = recipes_dir();
    let _ = fs::create_dir_all(&dir);
    let mut recipes = Vec::new();
    if let Ok(entries) = fs::read_dir(&dir) {
        for entry in entries.flatten() {
            if entry.path().extension().and_then(|e| e.to_str()) != Some("json") {
                continue;
            }
            if let Ok(text) = fs::read_to_string(entry.path()) {
                if let Ok(recipe) = serde_json::from_str::<Value>(&text) {
                    recipes.push(recipe);
                }
            }
        }
    }
    json!({"ok": true, "recipes": recipes, "count": recipes.len()})
}

pub fn save_recipe(body: &Value) -> Value {
    let id = body.get("id").and_then(|v| v.as_str()).unwrap_or("");
    let name = body
        .get("name")
        .and_then(|v| v.as_str())
        .unwrap_or("Recipe");
    if id.trim().is_empty() {
        return json!({"ok": false, "error": "id required"});
    }
    let dir = recipes_dir();
    let _ = fs::create_dir_all(&dir);
    let mut recipe = body.clone();
    recipe["updated_at"] = json!(chrono::Utc::now().to_rfc3339());
    if recipe.get("name").is_none() {
        recipe["name"] = json!(name);
    }
    let path = dir.join(format!("{id}.json"));
    match fs::write(
        &path,
        serde_json::to_string_pretty(&recipe).unwrap_or_else(|_| "{}".into()),
    ) {
        Ok(()) => json!({"ok": true, "id": id, "path": path.display().to_string()}),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

pub fn delete_recipe(recipe_id: &str) -> Value {
    let path = recipes_dir().join(format!("{recipe_id}.json"));
    if path.exists() {
        match fs::remove_file(&path) {
            Ok(()) => json!({"ok": true, "deleted": recipe_id}),
            Err(e) => json!({"ok": false, "error": e.to_string()}),
        }
    } else {
        json!({"ok": false, "error": "recipe not found"})
    }
}

pub fn draft_rule(body: &Value, actor: &str) -> Value {
    let equipment_id = body
        .get("equipment_id")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .or_else(|| super::scope::first_equipment_id())
        .unwrap_or_else(|| "equip:unknown".to_string());
    let fdd_input = body
        .get("fdd_input")
        .and_then(|v| v.as_str())
        .unwrap_or("oa_t");
    let operator = body.get("operator").and_then(|v| v.as_str()).unwrap_or(">");
    let threshold = body
        .get("threshold")
        .and_then(|v| v.as_f64())
        .unwrap_or(100.0);
    let rule_id = body
        .get("rule_id")
        .and_then(|v| v.as_str())
        .unwrap_or("csv_workbench_rule");
    let sql = format!(
        "SELECT timestamp, equipment_id, {fdd_input}, CASE WHEN {fdd_input} IS NULL THEN false WHEN {fdd_input} {operator} {threshold} THEN true ELSE false END AS fault_raw FROM telemetry_pivot WHERE equipment_id = '{equipment_id}'"
    );
    let rule = json!({
        "rule_id": rule_id,
        "name": body.get("name").and_then(|v| v.as_str()).unwrap_or("CSV workbench rule"),
        "description": format!("Draft from CSV workbench — {fdd_input} {operator} {threshold}"),
        "sql": sql,
        "required_inputs": [fdd_input],
        "equipment_filter": equipment_id,
        "review_status": "draft",
        "source": "csv_workbench",
        "confirmation_seconds": body.get("confirmation_seconds").and_then(|v| v.as_i64()).unwrap_or(300)
    });
    rules::save_rule(&rule, actor)
}

pub fn purge_source_preview(source_id: &str) -> Value {
    let historian_rows = store::load_pivot_rows().unwrap_or_default();
    let hist_matched = historian_rows
        .iter()
        .filter(|r| {
            r.get("source")
                .and_then(|v| v.as_str())
                .is_some_and(|s| s.contains(source_id))
        })
        .count();
    let grid_rows = query::haystack_rows();
    let model_matched = grid_rows
        .iter()
        .filter(|r| {
            r.get("sourceRef").and_then(|v| v.as_str()) == Some(source_id)
                || r.get("id").and_then(|v| v.as_str()) == Some(source_id)
        })
        .count();
    json!({
        "ok": true,
        "source_id": source_id,
        "historian_rows_matched": hist_matched,
        "model_entities_matched": model_matched,
        "requires_confirmation": "PURGE HISTORIAN DATA"
    })
}

pub fn purge_source_execute(source_id: &str, confirm: &str) -> Value {
    if confirm != "PURGE HISTORIAN DATA" {
        return json!({"ok": false, "error": "confirmation phrase required"});
    }
    let rows = store::load_pivot_rows().unwrap_or_default();
    let kept: Vec<Value> = rows
        .into_iter()
        .filter(|r| {
            !r.get("source")
                .and_then(|v| v.as_str())
                .is_some_and(|s| s.contains(source_id))
        })
        .collect();
    let removed_hist = store::row_count().saturating_sub(kept.len());
    if let Err(e) = store::rewrite_all(&kept) {
        return json!({"ok": false, "error": e});
    }

    let grid = persist::haystack_model_value();
    let existing: Vec<Value> = grid
        .get("rows")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let filtered: Vec<Value> = existing
        .into_iter()
        .filter(|r| {
            let id = r.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let source_ref = r.get("sourceRef").and_then(|v| v.as_str()).unwrap_or("");
            id != source_id && source_ref != source_id
        })
        .collect();
    let removed_model = grid
        .get("rows")
        .and_then(|v| v.as_array())
        .map(|a| a.len())
        .unwrap_or(0)
        .saturating_sub(filtered.len());
    let new_grid = json!({
        "meta": grid.get("meta").cloned().unwrap_or(json!({"ver":"3.0"})),
        "cols": grid.get("cols").cloned().unwrap_or(json!([])),
        "rows": filtered
    });
    let _ = persist::save_haystack_grid(&new_grid);

    let mut assign = assignments::load_assignments_value();
    if let Some(pts) = assign.get_mut("points").and_then(|v| v.as_array_mut()) {
        pts.retain(|p| {
            !p.get("driver_bindings")
                .and_then(|v| v.as_array())
                .is_some_and(|arr| {
                    arr.iter().any(|b| {
                        b.get("ref")
                            .and_then(|v| v.as_str())
                            .is_some_and(|r| r.contains(source_id))
                    })
                })
        });
    }
    let _ = assignments::save_assignments_value(&assign);

    json!({
        "ok": true,
        "source_id": source_id,
        "historian_rows_removed": removed_hist,
        "model_entities_removed": removed_model
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::with_temp_workspace;

    #[test]
    fn preview_from_headers() {
        with_temp_workspace(|_| {
            let out = preview_model(&json!({
                "source_filename": "plant-ahu.csv",
                "headers": ["Date", "Outdoor Air Temp", "SAT"]
            }));
            assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
            assert_eq!(
                out.get("site_id").and_then(|v| v.as_str()),
                Some("site:plant-ahu")
            );
            let pts = out.get("points").and_then(|v| v.as_array()).unwrap();
            assert!(!pts.is_empty());
        });
    }

    #[test]
    fn column_mapping_overrides_auto() {
        with_temp_workspace(|_| {
            save_column_mappings(&json!({
                "source_id": "source:csv:plant-ahu",
                "mappings": {"Custom Temp": "zn_t"}
            }));
            let out = preview_model(&json!({
                "source_filename": "plant-ahu.csv",
                "headers": ["Date", "Custom Temp"]
            }));
            let pts = out.get("points").and_then(|v| v.as_array()).unwrap();
            assert_eq!(
                pts[0].get("fdd_input").and_then(|v| v.as_str()),
                Some("zn_t")
            );
        });
    }

    #[test]
    fn quality_flags_duplicates() {
        let out = analyze_quality(&json!({
            "headers": ["Date", "Val"],
            "rows": [["1/1/2024", "1"], ["1/1/2024", "2"], ["1/2/2024", "3"]]
        }));
        assert!(
            out.get("duplicate_timestamps")
                .and_then(|v| v.as_u64())
                .unwrap_or(0)
                >= 1
        );
    }
}
