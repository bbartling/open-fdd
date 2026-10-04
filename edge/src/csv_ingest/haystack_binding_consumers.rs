//! H10/H11 — typed Haystack binding consumers (#1002 / #1017 Soft-OPEN bind).
//!
//! One DataFusion FDD path: convert `TypedBindingSet` → session `role_map` +
//! exact equipment ids (type-first callers still stamp equipType separately).
//! History bindings only allow approved provider/series ids from inventory —
//! no arbitrary URL fetch. ECM path is JSON contract for PyPI adapter.

use serde_json::{json, Map, Value};

use super::haystack_defs::DEFS_PIN;
use super::haystack_sparql_bindings::{TypedBindingSet, BINDING_SCHEMA, QUERY_ENGINE};

pub const FDD_CONSUMER_SCHEMA: &str = "ofdd_haystack_fdd_binding_plan_v1";
pub const HISTORY_CONSUMER_SCHEMA: &str = "ofdd_haystack_history_binding_plan_v1";
pub const ECM_CONSUMER_SCHEMA: &str = "ofdd_haystack_ecm_binding_plan_v1";

/// Build FDD session role_map + equipment list from typed SPARQL bindings.
/// Only `fdd_ready` points with approved canonical roles are included.
pub fn fdd_binding_plan(bindings: &TypedBindingSet) -> Value {
    let mut role_map = Map::new();
    let mut equipment_ids = Vec::new();
    let mut ready_points = 0usize;
    let mut skipped = Vec::new();

    for eq in &bindings.equipment {
        equipment_ids.push(eq.equipment_id.clone());
        let mut roles = Map::new();
        for pt in &eq.points {
            if !pt.fdd_ready {
                skipped.push(json!({
                    "equipment_id": pt.equipment_id,
                    "column": pt.column,
                    "selection_status": pt.selection_status,
                    "reason": "not_fdd_ready",
                }));
                continue;
            }
            let Some(role) = pt
                .canonical_role
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
            else {
                skipped.push(json!({
                    "equipment_id": pt.equipment_id,
                    "column": pt.column,
                    "reason": "missing_canonical_role",
                }));
                continue;
            };
            // Session role_map is role -> column.
            roles.insert(role.to_string(), json!(pt.column));
            ready_points += 1;
        }
        if !roles.is_empty() {
            role_map.insert(eq.equipment_id.clone(), Value::Object(roles));
        }
    }

    json!({
        "ok": true,
        "schema": FDD_CONSUMER_SCHEMA,
        "binding_schema": BINDING_SCHEMA,
        "query_engine": QUERY_ENGINE,
        "defs_pin": DEFS_PIN,
        "building_id": bindings.building_id,
        "model_revision": bindings.model_revision,
        "turtle_sha256": bindings.turtle_sha256,
        "query_id": bindings.query_id,
        "not_edge_prototype_graph": true,
        "equipment_ids": equipment_ids,
        "role_map": role_map,
        "ready_point_count": ready_points,
        "skipped": skipped,
        "datafusion_note": "Pass role_map into session_config and filter equipment by exact id after equipType; DataFusion reads Parquet roles only",
    })
}

/// History/#1017 Soft-OPEN bind: approved provider/series from inventory only.
pub fn history_binding_plan(bindings: &TypedBindingSet, inventory: Option<&Value>) -> Value {
    let mut series = Vec::new();
    let mut rejected = Vec::new();

    let approved = approved_history_registry(inventory);

    for eq in &bindings.equipment {
        for pt in &eq.points {
            let key = (eq.equipment_id.clone(), pt.column.clone());
            match approved.get(&key) {
                Some(entry) => {
                    series.push(json!({
                        "equipment_id": eq.equipment_id,
                        "column": pt.column,
                        "point_id": pt.point_id,
                        "canonical_role": pt.canonical_role,
                        "provider_id": entry.get("provider_id"),
                        "series_id": entry.get("series_id"),
                        "connection_ref": entry.get("connection_ref"),
                        "unit": pt.unit,
                        "tz_note": "source tz/quality retained by historian; not RDF samples",
                        "approved": true,
                    }));
                }
                None => {
                    // Points without an approved history registry entry stay unbound.
                    if pt.canonical_role.is_some() {
                        rejected.push(json!({
                            "equipment_id": eq.equipment_id,
                            "column": pt.column,
                            "reason": "no_approved_provider_series",
                        }));
                    }
                }
            }
        }
    }

    json!({
        "ok": true,
        "schema": HISTORY_CONSUMER_SCHEMA,
        "binding_schema": BINDING_SCHEMA,
        "defs_pin": DEFS_PIN,
        "building_id": bindings.building_id,
        "model_revision": bindings.model_revision,
        "not_edge_prototype_graph": true,
        "arbitrary_url_fetch": false,
        "series": series,
        "rejected": rejected,
        "note": "Only inventory-approved provider/series ids; raw observations stay out of RDF",
    })
}

fn approved_history_registry(
    inventory: Option<&Value>,
) -> std::collections::BTreeMap<(String, String), Value> {
    let mut out = std::collections::BTreeMap::new();
    let Some(inv) = inventory else {
        return out;
    };
    // Accept either top-level history_bindings[] or per-equipment history[].
    if let Some(arr) = inv.get("history_bindings").and_then(|v| v.as_array()) {
        for row in arr {
            let Some(eid) = row.get("equipment_id").and_then(|v| v.as_str()) else {
                continue;
            };
            let Some(col) = row
                .get("column")
                .or_else(|| row.get("point_column"))
                .and_then(|v| v.as_str())
            else {
                continue;
            };
            let Some(provider) = row.get("provider_id").and_then(|v| v.as_str()) else {
                continue;
            };
            let Some(series) = row.get("series_id").and_then(|v| v.as_str()) else {
                continue;
            };
            if provider.trim().is_empty() || series.trim().is_empty() {
                continue;
            }
            // Reject obvious URL-as-provider misuse.
            if provider.contains("://") {
                continue;
            }
            out.insert((eid.to_string(), col.to_string()), row.clone());
        }
    }
    if let Some(equip) = inv.get("equipment").and_then(|v| v.as_array()) {
        for eq in equip {
            let Some(eid) = eq.get("equipment_id").and_then(|v| v.as_str()) else {
                continue;
            };
            let Some(hist) = eq.get("history").and_then(|v| v.as_array()) else {
                continue;
            };
            for row in hist {
                let Some(col) = row.get("column").and_then(|v| v.as_str()) else {
                    continue;
                };
                let Some(provider) = row.get("provider_id").and_then(|v| v.as_str()) else {
                    continue;
                };
                if provider.contains("://") {
                    continue;
                }
                out.insert((eid.to_string(), col.to_string()), row.clone());
            }
        }
    }
    out
}

/// ECM consumer plan: equipment/point units for PyPI `open_fdd.ecm_engineering`.
pub fn ecm_binding_plan(bindings: &TypedBindingSet) -> Value {
    let mut assets = Vec::new();
    for eq in &bindings.equipment {
        let points: Vec<Value> = eq
            .points
            .iter()
            .filter(|p| p.selection_status.as_deref() != Some("excluded"))
            .map(|p| {
                json!({
                    "point_id": p.point_id,
                    "column": p.column,
                    "canonical_role": p.canonical_role,
                    "unit": p.unit,
                    "kind": p.kind,
                    "fdd_ready": p.fdd_ready,
                    "selection_status": p.selection_status,
                })
            })
            .collect();
        assets.push(json!({
            "equipment_id": eq.equipment_id,
            "equip_type": eq.equip_type,
            "points": points,
        }));
    }
    json!({
        "ok": true,
        "schema": ECM_CONSUMER_SCHEMA,
        "binding_schema": BINDING_SCHEMA,
        "defs_pin": DEFS_PIN,
        "building_id": bindings.building_id,
        "model_revision": bindings.model_revision,
        "not_edge_prototype_graph": true,
        "assets": assets,
        "adapter": "open_fdd.ecm_engineering.haystack_bindings.adapt_typed_bindings",
        "note": "Python ECM stays off the product request path; consume this JSON offline/agent-side",
    })
}

/// Bundle all consumer plans for one binding set (+ optional inventory for history).
pub fn consumer_bundle(bindings: &TypedBindingSet, inventory: Option<&Value>) -> Value {
    json!({
        "ok": true,
        "binding_schema": BINDING_SCHEMA,
        "defs_pin": DEFS_PIN,
        "building_id": bindings.building_id,
        "model_revision": bindings.model_revision,
        "turtle_sha256": bindings.turtle_sha256,
        "query_id": bindings.query_id,
        "fdd": fdd_binding_plan(bindings),
        "history": history_binding_plan(bindings, inventory),
        "ecm": ecm_binding_plan(bindings),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::csv_ingest::haystack_projection::fixtures::{sample_inventory, sample_meta};
    use crate::csv_ingest::haystack_sparql_bindings::execute_template_from_meta;

    #[test]
    fn fdd_plan_maps_approved_sat_role() {
        let set = execute_template_from_meta(
            &sample_meta(),
            Some(&sample_inventory()),
            None,
            "fdd_role_candidates",
        )
        .expect("bindings");
        let plan = fdd_binding_plan(&set);
        assert_eq!(plan["schema"], FDD_CONSUMER_SCHEMA);
        assert_eq!(plan["role_map"]["AHU_CASE_1"]["sat"], "SAT");
        assert!(plan["ready_point_count"].as_u64().unwrap() >= 1);
    }

    #[test]
    fn history_rejects_url_provider_and_requires_registry() {
        let set = execute_template_from_meta(
            &sample_meta(),
            Some(&sample_inventory()),
            None,
            "fdd_role_candidates",
        )
        .expect("bindings");
        let inv = json!({
            "history_bindings": [
                {
                    "equipment_id": "AHU_CASE_1",
                    "column": "SAT",
                    "provider_id": "https://evil.example/fetch",
                    "series_id": "s1"
                },
                {
                    "equipment_id": "AHU_CASE_1",
                    "column": "SAT",
                    "provider_id": "site_historian",
                    "series_id": "ahu1.sat",
                    "connection_ref": "conn:local"
                }
            ]
        });
        let plan = history_binding_plan(&set, Some(&inv));
        assert_eq!(plan["arbitrary_url_fetch"], false);
        let series = plan["series"].as_array().unwrap();
        assert_eq!(series.len(), 1);
        assert_eq!(series[0]["provider_id"], "site_historian");
        assert_eq!(series[0]["series_id"], "ahu1.sat");
    }

    #[test]
    fn ecm_plan_lists_assets() {
        let set = execute_template_from_meta(
            &sample_meta(),
            Some(&sample_inventory()),
            None,
            "fdd_role_candidates",
        )
        .expect("bindings");
        let plan = ecm_binding_plan(&set);
        assert_eq!(plan["schema"], ECM_CONSUMER_SCHEMA);
        assert!(plan["assets"]
            .as_array()
            .unwrap()
            .iter()
            .any(|a| a["equipment_id"] == "AHU_CASE_1"));
    }
}
