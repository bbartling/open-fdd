//! Haystack-grid SPARQL facade (predefined SELECT queries; read-only).
//!
//! Full RDF/SPARQL engine deferred — executes equivalent Haystack row filters and
//! returns SPARQL-style bindings for the dashboard panel.

use crate::model::query;
use serde_json::{json, Value};
use std::collections::HashMap;

const MAX_ROWS: usize = 500;

pub fn predefined() -> Value {
    let queries = catalog();
    let default = queries
        .first()
        .map(|q| q["query"].as_str().unwrap_or(""))
        .unwrap_or("");
    json!({
        "ok": true,
        "default_query": default,
        "queries": queries,
        "query_engine": "haystack",
        "note": "Predefined queries run against the Haystack grid; custom SPARQL subset limited to exact predefined text."
    })
}

pub fn execute(body: &Value) -> Value {
    let query_text = body
        .get("query")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    if query_text.is_empty() {
        return json!({"ok": false, "error": "query required", "bindings": []});
    }

    let handler = resolve_handler(query_text);
    let bindings = match handler {
        Some(h) => h(),
        None => {
            return json!({
                "ok": false,
                "error": "Unsupported SPARQL — pick a predefined query or use POST /api/model/query for raw Haystack rows",
                "bindings": [],
                "query_engine": "haystack"
            });
        }
    };

    let truncated = bindings.len() > MAX_ROWS;
    let rows: Vec<Value> = bindings
        .into_iter()
        .take(MAX_ROWS)
        .map(|m| {
            let obj: serde_json::Map<String, Value> = m
                .into_iter()
                .map(|(k, v)| (k, Value::String(v)))
                .collect();
            Value::Object(obj)
        })
        .collect();
    let count = rows.len();
    json!({
        "ok": true,
        "bindings": rows,
        "row_count": count,
        "truncated": truncated,
        "query_engine": "haystack"
    })
}

fn resolve_handler(query: &str) -> Option<fn() -> Vec<HashMap<String, String>>> {
    for item in catalog() {
        for key in ["query", "query_with_bacnet"] {
            if item.get(key).and_then(|v| v.as_str()) == Some(query) {
                let id = item.get("id").and_then(|v| v.as_str()).unwrap_or("");
                return handler_for_id(id);
            }
        }
    }
    handler_for_id(query)
}

fn handler_for_id(id: &str) -> Option<fn() -> Vec<HashMap<String, String>>> {
    match id {
        "hvac_equipment" => Some(bind_equipment),
        "hvac_equipment_types" => Some(bind_equipment_types),
        "hvac_points" => Some(bind_points),
        "hvac_points_bacnet" => Some(bind_points_bacnet),
        "hvac_unmapped_points" => Some(bind_unmapped_points),
        "hvac_feeds" => Some(bind_feeds),
        "eng_sites" => Some(bind_sites),
        _ => None,
    }
}

fn catalog() -> Vec<Value> {
    vec![
        json!({
            "id": "hvac_equipment",
            "label": "All equipment",
            "short_label": "Equipment",
            "category": "hvac",
            "query": "SELECT ?equip ?dis ?equipType WHERE { ?equip a haystack:Equip . OPTIONAL { ?equip haystack:dis ?dis } }",
            "query_with_bacnet": "SELECT ?equip ?dis ?equipType ?bacnetRef WHERE { ?equip a haystack:Equip . OPTIONAL { ?equip haystack:dis ?dis } . OPTIONAL { ?point haystack:equipRef ?equip . ?point haystack:bacnetRef ?bacnetRef } }"
        }),
        json!({
            "id": "hvac_equipment_types",
            "label": "Equipment by HVAC type",
            "short_label": "Equip types",
            "category": "hvac",
            "query": "SELECT ?equipType (COUNT(?equip) AS ?count) WHERE { ?equip a haystack:Equip . BIND(haystack:inferType(?equip) AS ?equipType) } GROUP BY ?equipType"
        }),
        json!({
            "id": "hvac_points",
            "label": "All points",
            "short_label": "Points",
            "category": "hvac",
            "query": "SELECT ?point ?dis ?equipRef ?fddInput WHERE { ?point a haystack:Point . OPTIONAL { ?point haystack:dis ?dis } . OPTIONAL { ?point haystack:equipRef ?equipRef } . OPTIONAL { ?point haystack:fddInput ?fddInput } }"
        }),
        json!({
            "id": "hvac_points_bacnet",
            "label": "BACnet-mapped points",
            "short_label": "BACnet pts",
            "category": "hvac",
            "query": "SELECT ?point ?dis ?equipRef ?bacnetRef WHERE { ?point a haystack:Point . ?point haystack:bacnetRef ?bacnetRef . OPTIONAL { ?point haystack:dis ?dis } . OPTIONAL { ?point haystack:equipRef ?equipRef } }",
            "query_with_bacnet": "SELECT ?point ?dis ?equipRef ?bacnetRef ?objectIdentifier WHERE { ?point a haystack:Point . ?point haystack:bacnetRef ?bacnetRef . OPTIONAL { ?point haystack:dis ?dis } . OPTIONAL { ?point haystack:equipRef ?equipRef } }"
        }),
        json!({
            "id": "hvac_unmapped_points",
            "label": "Unmapped points (no fddInput / driver ref)",
            "short_label": "Unmapped",
            "category": "engineering",
            "query": "SELECT ?point ?dis ?equipRef WHERE { ?point a haystack:Point . FILTER NOT EXISTS { ?point haystack:fddInput ?x } FILTER NOT EXISTS { ?point haystack:bacnetRef ?y } }"
        }),
        json!({
            "id": "hvac_feeds",
            "label": "Equipment feeds relationships",
            "short_label": "Feeds",
            "category": "hvac",
            "query": "SELECT ?from ?to ?fromLabel ?toLabel WHERE { ?to haystack:feedRef ?from . OPTIONAL { ?from haystack:dis ?fromLabel } . OPTIONAL { ?to haystack:dis ?toLabel } }"
        }),
        json!({
            "id": "eng_sites",
            "label": "Sites",
            "short_label": "Sites",
            "category": "engineering",
            "query": "SELECT ?site ?dis WHERE { ?site a haystack:Site . OPTIONAL { ?site haystack:dis ?dis } }"
        }),
    ]
}

fn bind_equipment() -> Vec<HashMap<String, String>> {
    let summary = query::equipment_model_summary();
    let mut labels: HashMap<String, String> = HashMap::new();
    let mut types: HashMap<String, String> = HashMap::new();
    for row in query::haystack_rows() {
        if row.get("equip").and_then(|v| v.as_str()) != Some("M") {
            continue;
        }
        let id = row
            .get("id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();
        if id.is_empty() {
            continue;
        }
        labels.insert(
            id.clone(),
            row.get("dis")
                .and_then(|v| v.as_str())
                .unwrap_or(&id)
                .to_string(),
        );
        types.insert(id, infer_equip_type_label(&row));
    }
    let _ = summary;
    labels
        .into_iter()
        .map(|(equip, dis)| {
            let mut m = HashMap::new();
            m.insert("equip".into(), equip.clone());
            m.insert("dis".into(), dis);
            m.insert(
                "equipType".into(),
                types
                    .get(&equip)
                    .cloned()
                    .unwrap_or_else(|| "generic".into()),
            );
            m
        })
        .collect()
}

fn bind_equipment_types() -> Vec<HashMap<String, String>> {
    let summary = query::equipment_model_summary();
    summary
        .get("equipment_by_type")
        .and_then(|v| v.as_object())
        .map(|obj| {
            obj.iter()
                .map(|(etype, count)| {
                    let mut m = HashMap::new();
                    m.insert("equipType".into(), etype.clone());
                    m.insert("count".into(), count.to_string());
                    m
                })
                .collect()
        })
        .unwrap_or_default()
}

fn bind_points() -> Vec<HashMap<String, String>> {
    query::haystack_rows()
        .into_iter()
        .filter(|r| r.get("point").and_then(|v| v.as_str()) == Some("M"))
        .map(|row| {
            let mut m = HashMap::new();
            m.insert(
                "point".into(),
                row.get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "dis".into(),
                row.get("dis")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "equipRef".into(),
                row.get("equipRef")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "fddInput".into(),
                row.get("fddInput")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m
        })
        .collect()
}

fn bind_points_bacnet() -> Vec<HashMap<String, String>> {
    query::haystack_rows()
        .into_iter()
        .filter(|r| {
            r.get("point").and_then(|v| v.as_str()) == Some("M") && r.get("bacnetRef").is_some()
        })
        .map(|row| {
            let mut m = HashMap::new();
            m.insert(
                "point".into(),
                row.get("id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "dis".into(),
                row.get("dis")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "equipRef".into(),
                row.get("equipRef")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "bacnetRef".into(),
                row.get("bacnetRef")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m
        })
        .collect()
}

fn bind_unmapped_points() -> Vec<HashMap<String, String>> {
    let unmapped = query::unmapped_points();
    unmapped
        .get("points")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|p| {
            let mut m = HashMap::new();
            m.insert(
                "point".into(),
                p.get("point_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "dis".into(),
                p.get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "equipRef".into(),
                p.get("equip_ref")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m
        })
        .collect()
}

fn bind_feeds() -> Vec<HashMap<String, String>> {
    let summary = query::equipment_model_summary();
    let mut labels: HashMap<String, String> = HashMap::new();
    for row in query::haystack_rows() {
        if row.get("equip").and_then(|v| v.as_str()) == Some("M") {
            let id = row.get("id").and_then(|v| v.as_str()).unwrap_or("");
            labels.insert(
                id.to_string(),
                row.get("dis")
                    .and_then(|v| v.as_str())
                    .unwrap_or(id)
                    .to_string(),
            );
        }
    }
    let mut out = Vec::new();
    for row in query::haystack_rows() {
        if let Some(from) = row.get("feedRef").and_then(|v| v.as_str()) {
            let to = row.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let mut m = HashMap::new();
            m.insert("from".into(), from.to_string());
            m.insert("to".into(), to.to_string());
            m.insert(
                "fromLabel".into(),
                labels
                    .get(from)
                    .cloned()
                    .unwrap_or_else(|| from.to_string()),
            );
            m.insert(
                "toLabel".into(),
                labels.get(to).cloned().unwrap_or_else(|| to.to_string()),
            );
            out.push(m);
        }
    }
    if out.is_empty() {
        if let Some(chains) = summary.get("feeds_chains").and_then(|v| v.as_array()) {
            for chain in chains {
                if let Some(s) = chain.as_str() {
                    let mut m = HashMap::new();
                    m.insert("feeds_chain".into(), s.to_string());
                    out.push(m);
                }
            }
        }
    }
    out
}

fn bind_sites() -> Vec<HashMap<String, String>> {
    query::list_sites()
        .get("sites")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|s| {
            let mut m = HashMap::new();
            m.insert(
                "site".into(),
                s.get("site_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m.insert(
                "dis".into(),
                s.get("name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
            );
            m
        })
        .collect()
}

fn infer_equip_type_label(row: &Value) -> String {
    if row.get("ahu").is_some() {
        "ahu".into()
    } else if row.get("vav").is_some() {
        "vav".into()
    } else if row.get("chiller").is_some() {
        "chiller".into()
    } else if row.get("boiler").is_some() {
        "boiler".into()
    } else {
        "generic".into()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn predefined_catalog_non_empty() {
        let p = predefined();
        assert!(p.get("queries").and_then(|v| v.as_array()).unwrap().len() >= 5);
    }

    #[test]
    fn execute_known_query() {
        let cat = catalog();
        let q = cat[0]["query"].as_str().unwrap();
        let out = execute(&json!({"query": q}));
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
    }
}
