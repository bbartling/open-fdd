//! Static product UI model tree — SPARQL-backed typed projection (#1508 / #1516).
//!
//! Parses the Haystack RDF graph (pack ∪ overlay) via read-only SELECT; never regex-parses Turtle text.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::{json, Value};

use super::haystack_central_dataset::CentralDatasetSnapshot;
use super::haystack_sparql_bindings::{
    inventory_equip_types, inventory_role_map, select_lexical_rows_on_turtle,
};

pub const UI_MODEL_SCHEMA: &str = "ofdd_static_ui_model_projection_v1";

const EQUIP_ROWS: &str = concat!(
    "SELECT ?equipIri ?equipmentId ?label ?siteRefIri ?dis WHERE {\n",
    "  ?equip rdf:type phIoT:equip .\n",
    "  ?equip ofdd:equipmentId ?equipmentId .\n",
    "  OPTIONAL { ?equip ph:dis ?dis . }\n",
    "  OPTIONAL { ?equip ph:dis ?label . }\n",
    "  OPTIONAL { ?equip phIoT:siteRef ?site . BIND(STR(?site) AS ?siteRefIri) }\n",
    "  BIND(STR(?equip) AS ?equipIri)\n",
    "}\n",
    "ORDER BY ?equipmentId\n",
);

const EQUIP_TAG_ROWS: &str = concat!(
    "SELECT ?equipIri ?equipmentId ?tagIri ?nativeTag WHERE {\n",
    "  ?equip rdf:type phIoT:equip .\n",
    "  ?equip ofdd:equipmentId ?equipmentId .\n",
    "  BIND(STR(?equip) AS ?equipIri)\n",
    "  OPTIONAL { ?equip ph:hasTag ?tag . BIND(STR(?tag) AS ?tagIri) }\n",
    "  OPTIONAL { ?equip ofdd:nativeTag ?nativeTag . }\n",
    "}\n",
);

const POINT_ROWS: &str = concat!(
    "SELECT ?pointIri ?equipmentId ?pointId ?column ?unit ?kind ?equipRefIri ?siteRefIri ?dis WHERE {\n",
    "  ?point rdf:type phIoT:point .\n",
    "  ?point phIoT:equipRef ?equip .\n",
    "  ?equip ofdd:equipmentId ?equipmentId .\n",
    "  OPTIONAL { ?point ofdd:pointId ?pointId . }\n",
    "  OPTIONAL { ?point ofdd:column ?column . }\n",
    "  OPTIONAL { ?point ph:unit ?unit . }\n",
    "  OPTIONAL { ?point ph:kind ?kind . }\n",
    "  OPTIONAL { ?point ph:dis ?dis . }\n",
    "  OPTIONAL { ?point phIoT:siteRef ?site . BIND(STR(?site) AS ?siteRefIri) }\n",
    "  BIND(STR(?point) AS ?pointIri)\n",
    "  BIND(STR(?equip) AS ?equipRefIri)\n",
    "}\n",
    "ORDER BY ?equipmentId ?pointId ?column\n",
);

const POINT_TAG_ROWS: &str = concat!(
    "SELECT ?pointIri ?tagIri ?nativeTag WHERE {\n",
    "  ?point rdf:type phIoT:point .\n",
    "  BIND(STR(?point) AS ?pointIri)\n",
    "  OPTIONAL { ?point ph:hasTag ?tag . BIND(STR(?tag) AS ?tagIri) }\n",
    "  OPTIONAL { ?point ofdd:nativeTag ?nativeTag . }\n",
    "}\n",
);

const SITE_ROW: &str = concat!(
    "SELECT ?siteIri ?buildingId WHERE {\n",
    "  ?site rdf:type phIoT:site .\n",
    "  OPTIONAL { ?site ofdd:buildingId ?buildingId . }\n",
    "  BIND(STR(?site) AS ?siteIri)\n",
    "}\n",
    "LIMIT 1\n",
);

fn tag_local_name(tag_iri: &str) -> Option<String> {
    let s = tag_iri.trim();
    if s.is_empty() {
        return None;
    }
    let fragment = s.rsplit('#').next().unwrap_or(s);
    let local = fragment.rsplit('/').next().unwrap_or(fragment);
    if local.is_empty() {
        return None;
    }
    Some(local.to_string())
}

fn merge_tags(tag_iris: &BTreeSet<String>, native: &BTreeSet<String>) -> Vec<String> {
    let mut out = BTreeSet::new();
    for iri in tag_iris {
        if let Some(t) = tag_local_name(iri) {
            out.insert(t);
        }
    }
    for n in native {
        let t = n.trim();
        if !t.is_empty() {
            out.insert(t.to_string());
        }
    }
    out.into_iter().collect()
}

fn equip_type_from_tags(tags: &[String], inventory_type: Option<&str>) -> String {
    if let Some(t) = inventory_type {
        return t.to_string();
    }
    const KINDS: &[&str] = &[
        "ahu", "vav", "rtu", "chiller", "boiler", "pump", "fan", "meter",
    ];
    for k in KINDS {
        if tags.iter().any(|t| t.eq_ignore_ascii_case(k)) {
            return (*k).to_string();
        }
    }
    String::new()
}

fn site_id_from_scope(building_id: &str, site_ref_iri: Option<&str>) -> String {
    if let Some(iri) = site_ref_iri {
        if let Some(idx) = iri.rfind("/site/") {
            let tail = &iri[idx + 6..];
            if let Some(end) = tail.find('/') {
                return tail[..end].to_string();
            }
            return tail.to_string();
        }
    }
    building_id.to_string()
}

fn normalize_kind(raw: Option<&str>) -> Option<String> {
    let k = raw?.trim();
    if k.is_empty() {
        return None;
    }
    Some(k.to_string())
}

/// Build the static UI model envelope from a materialized central dataset snapshot.
pub fn project_ui_model_from_snapshot(
    snap: &CentralDatasetSnapshot,
    overlay_turtle: &str,
    inventory: Option<&Value>,
) -> Result<Value, String> {
    let roles = inventory_role_map(inventory);
    let inv_types = inventory_equip_types(inventory);

    let (equip_rows, _) = select_lexical_rows_on_turtle(&snap.turtle, overlay_turtle, EQUIP_ROWS)?;
    let (equip_tag_rows, _) =
        select_lexical_rows_on_turtle(&snap.turtle, overlay_turtle, EQUIP_TAG_ROWS)?;
    let (point_rows, _) = select_lexical_rows_on_turtle(&snap.turtle, overlay_turtle, POINT_ROWS)?;
    let (point_tag_rows, _) =
        select_lexical_rows_on_turtle(&snap.turtle, overlay_turtle, POINT_TAG_ROWS)?;
    let (site_rows, _) = select_lexical_rows_on_turtle(&snap.turtle, overlay_turtle, SITE_ROW)?;

    let mut equip_tags: BTreeMap<String, (BTreeSet<String>, BTreeSet<String>)> = BTreeMap::new();
    for row in equip_tag_rows {
        let Some(eid) = row.get("equipmentId").filter(|s| !s.is_empty()) else {
            continue;
        };
        let entry = equip_tags.entry(eid.clone()).or_default();
        if let Some(tag) = row.get("tagIri").filter(|s| !s.is_empty()) {
            entry.0.insert(tag.clone());
        }
        if let Some(native) = row.get("nativeTag").filter(|s| !s.is_empty()) {
            entry.1.insert(native.clone());
        }
    }

    let mut point_tags: BTreeMap<String, (BTreeSet<String>, BTreeSet<String>)> = BTreeMap::new();
    for row in point_tag_rows {
        let Some(iri) = row.get("pointIri").filter(|s| !s.is_empty()) else {
            continue;
        };
        let entry = point_tags.entry(iri.clone()).or_default();
        if let Some(tag) = row.get("tagIri").filter(|s| !s.is_empty()) {
            entry.0.insert(tag.clone());
        }
        if let Some(native) = row.get("nativeTag").filter(|s| !s.is_empty()) {
            entry.1.insert(native.clone());
        }
    }

    let site_row = site_rows.first();
    let site_iri = site_row.and_then(|r| r.get("siteIri").cloned());
    let site_id = site_row
        .and_then(|r| r.get("buildingId").cloned())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| snap.building_id.clone());

    let mut equips: Vec<Value> = Vec::new();
    for row in equip_rows {
        let Some(eid) = row.get("equipmentId").filter(|s| !s.is_empty()) else {
            continue;
        };
        let (tag_iris, native) = equip_tags.get(eid).cloned().unwrap_or_default();
        let tags = merge_tags(&tag_iris, &native);
        let label = row
            .get("dis")
            .or_else(|| row.get("label"))
            .cloned()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| eid.clone());
        let site_ref =
            site_id_from_scope(&snap.building_id, row.get("siteRefIri").map(String::as_str));
        let equip_type = equip_type_from_tags(&tags, inv_types.get(eid).map(String::as_str));
        equips.push(json!({
            "id": eid,
            "name": label,
            "tags": tags,
            "siteRef": site_ref,
            "equipType": equip_type,
            "subjectIri": row.get("equipIri"),
            "equipRefIri": row.get("equipIri"),
        }));
    }
    equips.sort_by(|a, b| {
        a.get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .cmp(b.get("id").and_then(|v| v.as_str()).unwrap_or(""))
    });

    let mut points: Vec<Value> = Vec::new();
    for row in point_rows {
        let Some(eid) = row.get("equipmentId").filter(|s| !s.is_empty()) else {
            continue;
        };
        let point_iri = row.get("pointIri").cloned().unwrap_or_default();
        let column = row
            .get("column")
            .cloned()
            .filter(|s| !s.is_empty())
            .unwrap_or_default();
        let point_id = row
            .get("pointId")
            .cloned()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| column.clone());
        if point_id.is_empty() && point_iri.is_empty() {
            continue;
        }
        let opaque_id = if point_id.is_empty() {
            point_iri.clone()
        } else {
            point_id.clone()
        };
        let (tag_iris, native) = point_tags.get(&point_iri).cloned().unwrap_or_default();
        let tags = merge_tags(&tag_iris, &native);
        let role = roles
            .get(&(eid.clone(), column.clone()))
            .cloned()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| column.clone());
        let site_ref =
            site_id_from_scope(&snap.building_id, row.get("siteRefIri").map(String::as_str));
        let dis = row
            .get("dis")
            .cloned()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| role.clone());
        let unit = row.get("unit").cloned().filter(|s| !s.is_empty());
        let kind = normalize_kind(row.get("kind").map(String::as_str));
        points.push(json!({
            "id": opaque_id,
            "pointId": point_id,
            "subjectIri": point_iri,
            "siteRef": site_ref,
            "equipRef": eid,
            "equipRefIri": row.get("equipRefIri"),
            "role": role,
            "column": column,
            "dis": dis,
            "tags": tags,
            "unit": unit,
            "kind": kind,
            "latest": null,
        }));
    }
    points.sort_by(|a, b| {
        let ae = a.get("equipRef").and_then(|v| v.as_str()).unwrap_or("");
        let be = b.get("equipRef").and_then(|v| v.as_str()).unwrap_or("");
        ae.cmp(be).then_with(|| {
            a.get("dis")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .cmp(b.get("dis").and_then(|v| v.as_str()).unwrap_or(""))
        })
    });

    Ok(json!({
        "ok": true,
        "schema": UI_MODEL_SCHEMA,
        "building_id": snap.building_id,
        "model_revision": snap.model_revision,
        "turtle_sha256": snap.turtle_sha256,
        "site": {
            "id": site_id,
            "name": site_id,
            "subjectIri": site_iri,
        },
        "equips": equips,
        "devices": [],
        "points": points,
        "equipment_count": equips.len(),
        "point_count": points.len(),
        "query_engine": "static_ui_model_sparql_v1",
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::csv_ingest::haystack_central_dataset;
    use crate::csv_ingest::haystack_projection::fixtures::{sample_inventory, sample_meta};
    use crate::csv_ingest::semantic_meta::{parse_semantic_meta, SemanticMetaV1};
    use serde_json::json;

    fn snap_from_meta(meta: &SemanticMetaV1, inventory: Option<&Value>) -> CentralDatasetSnapshot {
        haystack_central_dataset::materialize(meta, inventory, None).expect("materialize")
    }

    #[test]
    fn projection_counts_equipment_and_points_from_graph() {
        let meta = sample_meta();
        let inv = sample_inventory();
        let snap = snap_from_meta(&meta, Some(&inv));
        let body = project_ui_model_from_snapshot(&snap, "", Some(&inv)).expect("project");
        assert_eq!(body["equipment_count"], 3);
        assert_eq!(body["point_count"], 4);
        assert_eq!(body["schema"], UI_MODEL_SCHEMA);
    }

    #[test]
    fn equivalent_turtle_serializations_same_projection() {
        let meta = sample_meta();
        let inv = sample_inventory();
        let snap = snap_from_meta(&meta, Some(&inv));
        let baseline = project_ui_model_from_snapshot(&snap, "", Some(&inv)).expect("baseline");
        let mut renamed = snap.turtle.clone();
        renamed = renamed.replace(
            "urn:openfdd:site/OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1",
            "urn:openfdd:site/RENAMED_PREFIX_V1",
        );
        let renamed_snap = CentralDatasetSnapshot {
            turtle: renamed,
            ..snap
        };
        let alt = project_ui_model_from_snapshot(&renamed_snap, "", Some(&inv)).expect("renamed");
        assert_eq!(baseline["equipment_count"], alt["equipment_count"]);
        assert_eq!(baseline["point_count"], alt["point_count"]);
        let base_ids: Vec<&str> = baseline["points"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|p| p.get("pointId").and_then(|v| v.as_str()))
            .collect();
        let alt_ids: Vec<&str> = alt["points"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|p| p.get("pointId").and_then(|v| v.as_str()))
            .collect();
        assert_eq!(base_ids, alt_ids);
    }

    #[test]
    fn duplicate_same_role_sensors_keep_distinct_opaque_ids() {
        let raw = json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": "DUP_ROLE_SITE",
            "equipment": [{
                "equipment_id": "AHU_A",
                "haystack_tags": ["ahu", "equip"],
            }],
            "points": [
                {
                    "equipment_id": "AHU_A",
                    "column": "SAT",
                    "point_id": "sat-a",
                    "haystack_tags": ["sensor", "point", "temp"],
                    "kind": "Number",
                    "unit": "°F",
                },
                {
                    "equipment_id": "AHU_A",
                    "column": "SAT",
                    "point_id": "sat-b",
                    "haystack_tags": ["sensor", "point", "temp"],
                    "kind": "Number",
                    "unit": "°F",
                },
            ],
        });
        let meta = parse_semantic_meta(&raw).expect("meta");
        let body = project_ui_model_from_snapshot(&snap_from_meta(&meta, None), "", None)
            .expect("project");
        let ids: Vec<&str> = body["points"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|p| p.get("id").and_then(|v| v.as_str()))
            .collect();
        assert_eq!(ids.len(), 2);
        assert!(ids.contains(&"sat-a"));
        assert!(ids.contains(&"sat-b"));
    }

    #[test]
    fn cmd_percentage_is_number_enable_is_bool() {
        let raw = json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": "KIND_SITE",
            "equipment": [{
                "equipment_id": "AHU_A",
                "haystack_tags": ["ahu", "equip"],
            }],
            "points": [
                {
                    "equipment_id": "AHU_A",
                    "column": "SF_SPD",
                    "point_id": "fan-cmd-pct",
                    "haystack_tags": ["cmd", "point"],
                    "kind": "Number",
                    "unit": "%",
                },
                {
                    "equipment_id": "AHU_A",
                    "column": "ENABLE",
                    "point_id": "enable-bool",
                    "haystack_tags": ["cmd", "point"],
                    "kind": "Bool",
                },
            ],
        });
        let meta = parse_semantic_meta(&raw).expect("meta");
        let body = project_ui_model_from_snapshot(&snap_from_meta(&meta, None), "", None)
            .expect("project");
        let by_id: BTreeMap<String, Value> = body["points"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|p| Some((p.get("id")?.as_str()?.to_string(), p.clone())))
            .collect();
        assert_eq!(by_id["fan-cmd-pct"]["kind"], "Number");
        assert_eq!(by_id["enable-bool"]["kind"], "Bool");
        let fan_tags = by_id["fan-cmd-pct"]["tags"].as_array().unwrap();
        assert!(!fan_tags.iter().any(|t| t.as_str() == Some("sensor")));
    }

    #[test]
    fn missing_unit_and_kind_stay_absent_not_invented() {
        let raw = json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": "MISSING_META",
            "equipment": [{
                "equipment_id": "AHU_A",
                "haystack_tags": ["ahu", "equip"],
            }],
            "points": [{
                "equipment_id": "AHU_A",
                "column": "MYSTERY",
                "point_id": "m1",
                "haystack_tags": ["point", "cmd"],
            }],
        });
        let meta = parse_semantic_meta(&raw).expect("meta");
        let body = project_ui_model_from_snapshot(&snap_from_meta(&meta, None), "", None)
            .expect("project");
        let p = &body["points"][0];
        assert!(p.get("unit").is_none() || p["unit"].is_null());
        assert!(p.get("kind").is_none() || p["kind"].is_null());
    }
}
