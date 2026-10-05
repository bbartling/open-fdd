//! Central package SPARQL templates → typed FDD/ECM bindings (C4 H9 / #1002 / #1123).
//!
//! Executes server-owned SELECT templates against the H8 central scoped Turtle
//! dataset (oxigraph). Free-form client SPARQL is rejected; inheritance comes
//! from pinned Haystack defs already baked into the Turtle. Inventory supplies
//! approved canonical role selections — SPARQL does not invent SQL roles.

use std::collections::BTreeMap;
use std::io::Cursor;

use oxigraph::io::RdfFormat;
use oxigraph::model::Term;
use oxigraph::sparql::{QueryResults, SparqlEvaluator};
use oxigraph::store::Store;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use spargebra::SparqlParser;

use super::haystack_central_dataset::{self, CentralDatasetSnapshot};
use super::haystack_defs::{DEFS_PIN, HAS_TAG_IRI, PHIOT_BASE, PH_BASE};
use super::haystack_projection::{OFDD_NS, PROFILE};
use super::semantic_meta::SemanticMetaV1;

pub const BINDING_SCHEMA: &str = "ofdd_haystack_typed_bindings_v1";
pub const QUERY_ENGINE: &str = "central_package_sparql_templates_v1";
pub const SPARQL_MAX_ROWS: usize = 2000;

const PREFIXES: &str = concat!(
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>\n",
    "PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>\n",
    "PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>\n",
    "PREFIX phScience: <https://project-haystack.org/def/phScience/4.0.0#>\n",
    "PREFIX ofdd: <urn:openfdd:ns#>\n",
);

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TypedPointBinding {
    pub equipment_id: String,
    pub point_id: String,
    pub column: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub canonical_role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub kind: Option<String>,
    #[serde(default)]
    pub fdd_ready: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub selection_status: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub point_iri: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evidence: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TypedEquipmentBinding {
    pub equipment_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub equip_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub equip_iri: Option<String>,
    #[serde(default)]
    pub points: Vec<TypedPointBinding>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TypedBindingSet {
    pub schema: String,
    pub profile: String,
    pub defs_pin: String,
    pub defs_sha256: String,
    pub building_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_revision: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub equipment_scope: Option<String>,
    pub turtle_sha256: String,
    pub query_id: String,
    pub query_engine: String,
    pub not_edge_prototype_graph: bool,
    pub equipment: Vec<TypedEquipmentBinding>,
    pub sparql_row_count: usize,
    pub truncated: bool,
}

#[derive(Debug, Clone)]
struct Template {
    id: &'static str,
    label: &'static str,
    category: &'static str,
    query: &'static str,
}

fn templates() -> Vec<Template> {
    vec![
        Template {
            id: "equip_by_ahu_class",
            label: "AHU-class equipment (phIoT:ahu via hasTag / type)",
            category: "selection",
            query: concat!(
                "SELECT DISTINCT ?equip ?equipmentId WHERE {\n",
                "  ?equip ofdd:equipmentId ?equipmentId .\n",
                "  {\n",
                "    ?equip rdf:type phIoT:ahu .\n",
                "  } UNION {\n",
                "    ?equip ph:hasTag phIoT:ahu .\n",
                "  }\n",
                "}\n",
                "ORDER BY ?equipmentId\n",
            ),
        },
        Template {
            id: "points_on_equipment",
            label: "Points with equipRef + column/pointId",
            category: "topology",
            query: concat!(
                "SELECT ?point ?equipmentId ?pointId ?column ?unit ?kind ?fddSelection ?fddExcluded WHERE {\n",
                "  ?point phIoT:equipRef ?equip .\n",
                "  ?equip ofdd:equipmentId ?equipmentId .\n",
                "  OPTIONAL { ?point ofdd:pointId ?pointId . }\n",
                "  OPTIONAL { ?point ofdd:column ?column . }\n",
                "  OPTIONAL { ?point ph:unit ?unit . }\n",
                "  OPTIONAL { ?point ph:kind ?kind . }\n",
                "  OPTIONAL { ?point ofdd:fddSelection ?fddSelection . }\n",
                "  OPTIONAL { ?point ofdd:fddExcluded ?fddExcluded . }\n",
                "}\n",
                "ORDER BY ?equipmentId ?column\n",
            ),
        },
        Template {
            id: "fdd_role_candidates",
            label: "Points retained for FDD role binding (exclusions flagged)",
            category: "fdd",
            query: concat!(
                "SELECT ?point ?equipmentId ?pointId ?column ?unit ?kind ?fddSelection ?fddExcluded WHERE {\n",
                "  ?point phIoT:equipRef ?equip .\n",
                "  ?equip ofdd:equipmentId ?equipmentId .\n",
                "  OPTIONAL { ?point ofdd:pointId ?pointId . }\n",
                "  OPTIONAL { ?point ofdd:column ?column . }\n",
                "  OPTIONAL { ?point ph:unit ?unit . }\n",
                "  OPTIONAL { ?point ph:kind ?kind . }\n",
                "  OPTIONAL { ?point ofdd:fddSelection ?fddSelection . }\n",
                "  OPTIONAL { ?point ofdd:fddExcluded ?fddExcluded . }\n",
                "  FILTER(!BOUND(?fddExcluded) || ?fddExcluded != \"true\")\n",
                "}\n",
                "ORDER BY ?equipmentId ?column\n",
            ),
        },
    ]
}

pub fn catalog_payload() -> Value {
    let queries: Vec<Value> = templates()
        .into_iter()
        .map(|t| {
            json!({
                "id": t.id,
                "label": t.label,
                "category": t.category,
                "query": format!("{PREFIXES}\n{}", t.query),
                "parameters": ["building_id", "equipment_id?"],
            })
        })
        .collect();
    json!({
        "ok": true,
        "schema": BINDING_SCHEMA,
        "query_engine": QUERY_ENGINE,
        "status": "AVAILABLE",
        "feature_closeable_by_unavailable": false,
        "defs_pin": DEFS_PIN,
        "profile": PROFILE,
        "not_edge_prototype_graph": true,
        "note": "Server-owned SELECT templates over central package RDF; typed bindings require inventory-approved roles",
        "dataset_route": "/api/csv/import/package/mapping/haystack-dataset",
        "queries": queries,
        "has_tag_iri": HAS_TAG_IRI,
        "ph_base": PH_BASE,
        "phiot_base": PHIOT_BASE,
        "ofdd_ns": OFDD_NS,
    })
}

fn ensure_select_query(query_text: &str) -> Result<(), String> {
    match SparqlParser::new().parse_query(query_text) {
        Ok(spargebra::Query::Select { .. }) => Ok(()),
        Ok(_) => Err("Only read-only SELECT templates are supported".into()),
        Err(e) => Err(format!("SPARQL parse error: {e}")),
    }
}

/// Cap free-form query text before parse/execute (bytes).
pub const SPARQL_MAX_QUERY_BYTES: usize = 16_384;

fn pattern_forbids_service(pattern: &spargebra::algebra::GraphPattern) -> Result<(), String> {
    use spargebra::algebra::GraphPattern as GP;
    match pattern {
        GP::Service { .. } => Err("SERVICE/federation is not allowed".into()),
        GP::Join { left, right } | GP::Union { left, right } | GP::Minus { left, right } => {
            pattern_forbids_service(left)?;
            pattern_forbids_service(right)
        }
        GP::LeftJoin { left, right, .. } => {
            pattern_forbids_service(left)?;
            pattern_forbids_service(right)
        }
        GP::Filter { inner, .. }
        | GP::Extend { inner, .. }
        | GP::Graph { inner, .. }
        | GP::OrderBy { inner, .. }
        | GP::Project { inner, .. }
        | GP::Distinct { inner }
        | GP::Reduced { inner }
        | GP::Slice { inner, .. }
        | GP::Group { inner, .. } => pattern_forbids_service(inner),
        GP::Bgp { .. } | GP::Path { .. } | GP::Values { .. } => Ok(()),
        other => {
            // Future GraphPattern variants: fail closed rather than allow SERVICE.
            let s = format!("{other:?}");
            if s.contains("Service") {
                return Err("SERVICE/federation is not allowed".into());
            }
            Ok(())
        }
    }
}

/// Parse + policy gate for product free-form SPARQL (SELECT/ASK only).
pub fn ensure_readonly_query(query_text: &str) -> Result<spargebra::Query, String> {
    let trimmed = query_text.trim();
    if trimmed.is_empty() {
        return Err("query text is required".into());
    }
    if trimmed.len() > SPARQL_MAX_QUERY_BYTES {
        return Err(format!("query exceeds {SPARQL_MAX_QUERY_BYTES} byte limit"));
    }
    let parsed = SparqlParser::new()
        .parse_query(trimmed)
        .map_err(|e| format!("SPARQL parse error: {e}"))?;
    let (dataset, pattern) = match &parsed {
        spargebra::Query::Select {
            dataset, pattern, ..
        } => (dataset, pattern),
        spargebra::Query::Ask {
            dataset, pattern, ..
        } => (dataset, pattern),
        spargebra::Query::Construct { .. } | spargebra::Query::Describe { .. } => {
            return Err("Only read-only SELECT and ASK are supported".into());
        }
    };
    if dataset.is_some() {
        return Err("FROM / FROM NAMED dataset clauses are not allowed".into());
    }
    pattern_forbids_service(pattern)?;
    Ok(parsed)
}

/// Execute a bounded read-only SELECT/ASK against a central package snapshot.
pub fn execute_readonly_on_snapshot(
    snap: &CentralDatasetSnapshot,
    query_text: &str,
) -> Result<Value, String> {
    let trimmed = query_text.trim();
    if trimmed.is_empty() {
        return Err("query text is required".into());
    }
    let full = if trimmed.to_ascii_uppercase().contains("PREFIX ") {
        trimmed.to_string()
    } else {
        format!("{PREFIXES}\n{trimmed}")
    };
    let parsed = ensure_readonly_query(&full)?;
    let store = load_store(&snap.turtle)?;
    let results = SparqlEvaluator::new()
        .parse_query(&full)
        .map_err(|e| format!("SPARQL parse error: {e}"))?
        .on_store(&store)
        .execute()
        .map_err(|e| format!("SPARQL execution error: {e}"))?;
    match (&parsed, results) {
        (spargebra::Query::Ask { .. }, QueryResults::Boolean(b)) => Ok(json!({
            "ok": true,
            "kind": "ask",
            "boolean": b,
            "schema": "ofdd_sparql_readonly_v1",
            "query_engine": "central_package_sparql_readonly_v1",
            "building_id": snap.building_id,
            "defs_pin": DEFS_PIN,
            "turtle_sha256": snap.turtle_sha256,
            "model_revision": snap.model_revision,
            "not_edge_prototype_graph": true,
        })),
        (spargebra::Query::Select { .. }, QueryResults::Solutions(solutions)) => {
            let cap = SPARQL_MAX_ROWS.saturating_add(1);
            let mut rows = Vec::new();
            let mut columns: Vec<String> = Vec::new();
            for sol in solutions {
                if rows.len() >= cap {
                    break;
                }
                let sol = sol.map_err(|e| format!("SPARQL solution error: {e}"))?;
                let mut map = BTreeMap::new();
                for (var, term) in sol.iter() {
                    let name = var.as_str().to_string();
                    if !columns.iter().any(|c| c == &name) {
                        columns.push(name.clone());
                    }
                    map.insert(name, term_lex(term));
                }
                rows.push(map);
            }
            let truncated = rows.len() > SPARQL_MAX_ROWS;
            if truncated {
                rows.truncate(SPARQL_MAX_ROWS);
            }
            Ok(json!({
                "ok": true,
                "kind": "select",
                "columns": columns,
                "rows": rows,
                "row_count": rows.len(),
                "truncated": truncated,
                "schema": "ofdd_sparql_readonly_v1",
                "query_engine": "central_package_sparql_readonly_v1",
                "building_id": snap.building_id,
                "defs_pin": DEFS_PIN,
                "turtle_sha256": snap.turtle_sha256,
                "model_revision": snap.model_revision,
                "not_edge_prototype_graph": true,
            }))
        }
        _ => Err("query kind / result mismatch".into()),
    }
}

fn load_store(turtle: &str) -> Result<Store, String> {
    let store = Store::new().map_err(|e| format!("oxigraph store: {e}"))?;
    store
        .load_from_reader(RdfFormat::Turtle, Cursor::new(turtle.as_bytes()))
        .map_err(|e| format!("load Turtle: {e}"))?;
    Ok(store)
}

fn term_lex(term: &Term) -> String {
    match term {
        Term::NamedNode(n) => n.as_str().to_string(),
        Term::BlankNode(b) => b.as_str().to_string(),
        Term::Literal(l) => l.value().to_string(),
    }
}

fn execute_select(
    store: &Store,
    query_text: &str,
) -> Result<(Vec<BTreeMap<String, String>>, bool), String> {
    ensure_select_query(query_text)?;
    let results = SparqlEvaluator::new()
        .parse_query(query_text)
        .map_err(|e| format!("SPARQL parse error: {e}"))?
        .on_store(store)
        .execute()
        .map_err(|e| format!("SPARQL execution error: {e}"))?;
    match results {
        QueryResults::Solutions(solutions) => {
            let cap = SPARQL_MAX_ROWS.saturating_add(1);
            let mut rows = Vec::new();
            for sol in solutions {
                if rows.len() >= cap {
                    break;
                }
                let sol = sol.map_err(|e| format!("SPARQL solution error: {e}"))?;
                let mut map = BTreeMap::new();
                for (var, term) in sol.iter() {
                    map.insert(var.as_str().to_string(), term_lex(term));
                }
                rows.push(map);
            }
            let truncated = rows.len() > SPARQL_MAX_ROWS;
            if truncated {
                rows.truncate(SPARQL_MAX_ROWS);
            }
            Ok((rows, truncated))
        }
        QueryResults::Boolean(_) | QueryResults::Graph(_) => {
            Err("Only SELECT queries are supported".into())
        }
    }
}

fn template_by_id(id: &str) -> Option<Template> {
    templates().into_iter().find(|t| t.id == id)
}

fn inventory_role_map(inventory: Option<&Value>) -> BTreeMap<(String, String), String> {
    let mut out = BTreeMap::new();
    let Some(equip) = inventory
        .and_then(|v| v.get("equipment"))
        .and_then(|v| v.as_array())
    else {
        return out;
    };
    for eq in equip {
        let Some(eid) = eq
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
        else {
            continue;
        };
        let Some(roles) = eq.get("roles").and_then(|v| v.as_object()) else {
            continue;
        };
        for (col, role_v) in roles {
            if let Some(role) = role_v.as_str().map(str::trim).filter(|s| !s.is_empty()) {
                out.insert((eid.to_string(), col.clone()), role.to_string());
            }
        }
    }
    out
}

fn inventory_equip_types(inventory: Option<&Value>) -> BTreeMap<String, String> {
    let mut out = BTreeMap::new();
    let Some(equip) = inventory
        .and_then(|v| v.get("equipment"))
        .and_then(|v| v.as_array())
    else {
        return out;
    };
    for eq in equip {
        let Some(eid) = eq
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
        else {
            continue;
        };
        if let Some(t) = eq
            .get("equipment_type")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            out.insert(eid.to_string(), t.to_string());
        }
    }
    out
}

fn build_typed_bindings(
    snap: &CentralDatasetSnapshot,
    query_id: &str,
    rows: Vec<BTreeMap<String, String>>,
    truncated: bool,
    inventory: Option<&Value>,
) -> TypedBindingSet {
    let roles = inventory_role_map(inventory);
    let types = inventory_equip_types(inventory);
    let mut by_equip: BTreeMap<String, TypedEquipmentBinding> = BTreeMap::new();

    for row in &rows {
        let Some(eid) = row.get("equipmentId").cloned().filter(|s| !s.is_empty()) else {
            continue;
        };
        let entry = by_equip
            .entry(eid.clone())
            .or_insert_with(|| TypedEquipmentBinding {
                equipment_id: eid.clone(),
                equip_type: types.get(&eid).cloned(),
                equip_iri: row.get("equip").cloned(),
                points: vec![],
            });
        if entry.equip_iri.is_none() {
            entry.equip_iri = row.get("equip").cloned();
        }
        let col = row
            .get("column")
            .cloned()
            .filter(|s| !s.is_empty())
            .unwrap_or_default();
        if col.is_empty() && row.get("point").is_none() {
            continue;
        }
        let point_id = row
            .get("pointId")
            .cloned()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| col.clone());
        let excluded = row.get("fddExcluded").map(|s| s == "true").unwrap_or(false);
        let unresolved = row
            .get("fddSelection")
            .map(|s| s == "unresolved")
            .unwrap_or(false);
        let canonical_role = roles.get(&(eid.clone(), col.clone())).cloned();
        let fdd_ready = canonical_role.is_some() && !excluded && !unresolved;
        let selection_status = if excluded {
            Some("excluded".into())
        } else if unresolved {
            Some("unresolved".into())
        } else if canonical_role.is_some() {
            Some("approved".into())
        } else {
            Some("unbound".into())
        };
        entry.points.push(TypedPointBinding {
            equipment_id: eid,
            point_id,
            column: col,
            canonical_role,
            unit: row.get("unit").cloned().filter(|s| !s.is_empty()),
            kind: row.get("kind").cloned().filter(|s| !s.is_empty()),
            fdd_ready,
            selection_status,
            point_iri: row.get("point").cloned(),
            evidence: Some(format!("sparql_template:{query_id}")),
        });
    }

    // Equip-only rows (AHU class template)
    for row in &rows {
        if row.get("column").is_some() || row.get("point").is_some() {
            continue;
        }
        let Some(eid) = row.get("equipmentId").cloned().filter(|s| !s.is_empty()) else {
            continue;
        };
        by_equip
            .entry(eid.clone())
            .or_insert_with(|| TypedEquipmentBinding {
                equipment_id: eid.clone(),
                equip_type: types.get(&eid).cloned(),
                equip_iri: row.get("equip").cloned(),
                points: vec![],
            });
    }

    TypedBindingSet {
        schema: BINDING_SCHEMA.to_string(),
        profile: PROFILE.to_string(),
        defs_pin: DEFS_PIN.to_string(),
        defs_sha256: snap.defs_sha256.clone(),
        building_id: snap.building_id.clone(),
        model_revision: snap.model_revision.clone(),
        equipment_scope: snap.equipment_scope.clone(),
        turtle_sha256: snap.turtle_sha256.clone(),
        query_id: query_id.to_string(),
        query_engine: QUERY_ENGINE.to_string(),
        not_edge_prototype_graph: true,
        equipment: by_equip.into_values().collect(),
        sparql_row_count: rows.len(),
        truncated,
    }
}

impl TypedBindingSet {
    pub fn to_json(&self) -> Value {
        serde_json::to_value(self).unwrap_or_else(|_| json!({"ok": false, "error": "serialize"}))
    }
}

/// Run a server template against a materialized central dataset + inventory roles.
pub fn execute_template_on_snapshot(
    snap: &CentralDatasetSnapshot,
    inventory: Option<&Value>,
    template_id: &str,
) -> Result<TypedBindingSet, String> {
    let tmpl = template_by_id(template_id)
        .ok_or_else(|| format!("unknown SPARQL template id: {template_id}"))?;
    let query = format!("{PREFIXES}\n{}", tmpl.query);
    let store = load_store(&snap.turtle)?;
    let (rows, truncated) = execute_select(&store, &query)?;
    Ok(build_typed_bindings(
        snap, tmpl.id, rows, truncated, inventory,
    ))
}

/// Materialize dataset from meta/inventory then run template (unit-test helper).
pub fn execute_template_from_meta(
    meta: &SemanticMetaV1,
    inventory: Option<&Value>,
    equipment_scope: Option<&str>,
    template_id: &str,
) -> Result<TypedBindingSet, String> {
    let snap = haystack_central_dataset::materialize(meta, inventory, equipment_scope)?;
    execute_template_on_snapshot(&snap, inventory, template_id)
}

pub fn freeform_rejected() -> Value {
    json!({
        "ok": false,
        "error": "Free-form SPARQL is not accepted; use query_id from GET /api/model/sparql/predefined",
        "status": "REJECTED",
        "query_engine": QUERY_ENGINE,
        "schema": BINDING_SCHEMA,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::csv_ingest::haystack_projection::fixtures::{sample_inventory, sample_meta};

    #[test]
    fn catalog_lists_server_templates() {
        let cat = catalog_payload();
        assert_eq!(cat["status"], "AVAILABLE");
        assert_eq!(cat["feature_closeable_by_unavailable"], false);
        assert!(cat["queries"].as_array().unwrap().len() >= 3);
        assert!(cat["not_edge_prototype_graph"].as_bool().unwrap());
    }

    #[test]
    fn ahu_template_selects_ahu_case() {
        let set = execute_template_from_meta(
            &sample_meta(),
            Some(&sample_inventory()),
            None,
            "equip_by_ahu_class",
        )
        .expect("ahu template");
        assert_eq!(set.schema, BINDING_SCHEMA);
        assert_eq!(set.defs_pin, DEFS_PIN);
        assert!(set.not_edge_prototype_graph);
        let ids: Vec<_> = set
            .equipment
            .iter()
            .map(|e| e.equipment_id.as_str())
            .collect();
        assert!(ids.contains(&"AHU_CASE_1"), "got {ids:?}");
        assert!(!ids.contains(&"VAV_CASE_1"));
    }

    #[test]
    fn points_template_binds_approved_sat_role() {
        let set = execute_template_from_meta(
            &sample_meta(),
            Some(&sample_inventory()),
            None,
            "fdd_role_candidates",
        )
        .expect("points");
        let ahu = set
            .equipment
            .iter()
            .find(|e| e.equipment_id == "AHU_CASE_1")
            .expect("ahu");
        let sat = ahu
            .points
            .iter()
            .find(|p| p.column == "SAT")
            .expect("SAT point");
        assert_eq!(sat.canonical_role.as_deref(), Some("sat"));
        assert!(sat.fdd_ready);
        assert_eq!(sat.selection_status.as_deref(), Some("approved"));
        assert_eq!(sat.unit.as_deref(), Some("°F"));
    }

    #[test]
    fn unknown_template_errors() {
        let err =
            execute_template_from_meta(&sample_meta(), Some(&sample_inventory()), None, "nope")
                .unwrap_err();
        assert!(err.contains("unknown"));
    }

    #[test]
    fn readonly_select_and_ask_policy() {
        ensure_readonly_query("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1").expect("select");
        ensure_readonly_query("ASK { ?s ?p ?o }").expect("ask");
        assert!(
            ensure_readonly_query("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
                .unwrap_err()
                .contains("SELECT and ASK")
        );
        assert!(ensure_readonly_query(
            "SELECT * WHERE { SERVICE <http://evil.example/sparql> { ?s ?p ?o } }"
        )
        .unwrap_err()
        .contains("SERVICE"));
        assert!(
            ensure_readonly_query("SELECT * FROM <http://example/g> WHERE { ?s ?p ?o }")
                .unwrap_err()
                .contains("FROM")
        );
    }

    #[test]
    fn readonly_execute_counts_equipment() {
        let snap =
            haystack_central_dataset::materialize(&sample_meta(), Some(&sample_inventory()), None)
                .expect("materialize");
        let out = execute_readonly_on_snapshot(
            &snap,
            "SELECT (COUNT(DISTINCT ?equipmentId) AS ?n) WHERE { ?e ofdd:equipmentId ?equipmentId }",
        )
        .expect("count");
        assert_eq!(out["ok"], json!(true));
        assert_eq!(out["kind"], json!("select"));
        assert!(out["row_count"].as_u64().unwrap_or(0) >= 1);
    }

    #[test]
    fn defs_pin_constant_matches_module() {
        let _ = super::super::haystack_defs::defs();
        assert_eq!(DEFS_PIN, "haystack-defs-ttl-4.0.0");
    }
}
