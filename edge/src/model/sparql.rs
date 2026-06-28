//! SPARQL query API over the Haystack RDF projection (`data_model.ttl`).

use crate::model::rdf;
use serde_json::{json, Value};
use std::collections::HashMap;

const MAX_ROWS: usize = 5000;

const PREFIXES: &str = r#"
PREFIX hs: <https://project-haystack.org/def/>
PREFIX ofdd: <https://open-fdd.dev/model#>
"#;

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
        "query_engine": "sparql",
        "rdf_source": "haystack_grid",
        "note": "SELECT queries run against the in-memory RDF graph synced from the Haystack model (Turtle)."
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

    match rdf::sparql_select(query_text) {
        Ok(bindings) => bindings_to_response(bindings),
        Err(e) => json!({
            "ok": false,
            "error": e,
            "bindings": [],
            "query_engine": "sparql"
        }),
    }
}

fn bindings_to_response(bindings: Vec<HashMap<String, String>>) -> Value {
    let truncated = bindings.len() > MAX_ROWS;
    let rows: Vec<Value> = bindings
        .into_iter()
        .take(MAX_ROWS)
        .map(|m| {
            let obj: serde_json::Map<String, Value> =
                m.into_iter().map(|(k, v)| (k, Value::String(v))).collect();
            Value::Object(obj)
        })
        .collect();
    let count = rows.len();
    json!({
        "ok": true,
        "bindings": rows,
        "row_count": count,
        "truncated": truncated,
        "query_engine": "sparql"
    })
}

pub fn catalog() -> Vec<Value> {
    vec![
        json!({
            "id": "hvac_equipment",
            "label": "All equipment",
            "short_label": "Equipment",
            "category": "hvac",
            "query": format!("{PREFIXES}\nSELECT ?equip ?dis ?equipType WHERE {{\n  ?s a hs:Equip .\n  ?s ofdd:haystackId ?equip .\n  OPTIONAL {{ ?s hs:dis ?dis . }}\n  OPTIONAL {{ ?s ofdd:equipType ?equipType . }}\n}}"),
            "query_with_bacnet": format!("{PREFIXES}\nSELECT ?equip ?dis ?equipType ?bacnetRef WHERE {{\n  ?s a hs:Equip .\n  ?s ofdd:haystackId ?equip .\n  OPTIONAL {{ ?s hs:dis ?dis . }}\n  OPTIONAL {{ ?s ofdd:equipType ?equipType . }}\n  OPTIONAL {{\n    ?p hs:equipRef ?s .\n    ?p hs:bacnetRef ?bacnetRef .\n  }}\n}}")
        }),
        json!({
            "id": "hvac_equipment_types",
            "label": "Equipment by HVAC type",
            "short_label": "Equip types",
            "category": "hvac",
            "query": format!("{PREFIXES}\nSELECT ?equipType (COUNT(?equip) AS ?count) WHERE {{\n  ?s a hs:Equip .\n  ?s ofdd:haystackId ?equip .\n  ?s ofdd:equipType ?equipType .\n}} GROUP BY ?equipType ORDER BY ?equipType")
        }),
        json!({
            "id": "hvac_points",
            "label": "All points",
            "short_label": "Points",
            "category": "hvac",
            "query": format!("{PREFIXES}\nSELECT ?point ?dis ?equipRef ?fddInput WHERE {{\n  ?p a hs:Point .\n  ?p ofdd:haystackId ?point .\n  OPTIONAL {{ ?p hs:dis ?dis . }}\n  OPTIONAL {{ ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equipRef . }}\n  OPTIONAL {{ ?p hs:fddInput ?fddInput . }}\n}}")
        }),
        json!({
            "id": "hvac_points_bacnet",
            "label": "BACnet-mapped points",
            "short_label": "BACnet pts",
            "category": "hvac",
            "query": format!("{PREFIXES}\nSELECT ?point ?dis ?equipRef ?bacnetRef WHERE {{\n  ?p a hs:Point .\n  ?p ofdd:haystackId ?point .\n  ?p hs:bacnetRef ?bacnetRef .\n  OPTIONAL {{ ?p hs:dis ?dis . }}\n  OPTIONAL {{ ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equipRef . }}\n}}"),
            "query_with_bacnet": format!("{PREFIXES}\nSELECT ?point ?dis ?equipRef ?bacnetRef WHERE {{\n  ?p a hs:Point .\n  ?p ofdd:haystackId ?point .\n  ?p hs:bacnetRef ?bacnetRef .\n  OPTIONAL {{ ?p hs:dis ?dis . }}\n  OPTIONAL {{ ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equipRef . }}\n}}")
        }),
        json!({
            "id": "hvac_unmapped_points",
            "label": "Unmapped points (no fddInput / driver ref)",
            "short_label": "Unmapped",
            "category": "engineering",
            "query": format!("{PREFIXES}\nSELECT ?point ?dis ?equipRef WHERE {{\n  ?p a hs:Point .\n  ?p ofdd:haystackId ?point .\n  OPTIONAL {{ ?p hs:dis ?dis . }}\n  OPTIONAL {{ ?p hs:equipRef ?eq . ?eq ofdd:haystackId ?equipRef . }}\n  FILTER NOT EXISTS {{ ?p hs:fddInput ?x }}\n  FILTER NOT EXISTS {{ ?p hs:bacnetRef ?y }}\n  FILTER NOT EXISTS {{ ?p hs:modbusRef ?z }}\n  FILTER NOT EXISTS {{ ?p hs:csvRef ?w }}\n}}")
        }),
        json!({
            "id": "hvac_feeds",
            "label": "Equipment feeds relationships",
            "short_label": "Feeds",
            "category": "hvac",
            "query": format!("{PREFIXES}\nSELECT ?from ?to ?fromLabel ?toLabel WHERE {{\n  ?toRes hs:feedRef ?fromRes .\n  ?fromRes ofdd:haystackId ?from .\n  ?toRes ofdd:haystackId ?to .\n  OPTIONAL {{ ?fromRes hs:dis ?fromLabel . }}\n  OPTIONAL {{ ?toRes hs:dis ?toLabel . }}\n}}")
        }),
        json!({
            "id": "eng_sites",
            "label": "Sites",
            "short_label": "Sites",
            "category": "engineering",
            "query": format!("{PREFIXES}\nSELECT ?site ?dis WHERE {{\n  ?s a hs:Site .\n  ?s ofdd:haystackId ?site .\n  OPTIONAL {{ ?s hs:dis ?dis . }}\n}}")
        }),
    ]
}

/// Run a catalog query by id (used by query layer).
pub fn run_predefined(id: &str) -> Result<Vec<HashMap<String, String>>, String> {
    let item = catalog()
        .into_iter()
        .find(|q| q.get("id").and_then(|v| v.as_str()) == Some(id))
        .ok_or_else(|| format!("unknown predefined query: {id}"))?;
    let query = item
        .get("query")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "query missing".to_string())?;
    rdf::sparql_select(query)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn predefined_catalog_non_empty() {
        let p = predefined();
        assert!(p.get("queries").and_then(|v| v.as_array()).unwrap().len() >= 5);
        assert_eq!(
            p.get("query_engine").and_then(|v| v.as_str()),
            Some("sparql")
        );
    }

    #[test]
    fn execute_known_query() {
        let cat = catalog();
        let q = cat[0]["query"].as_str().unwrap();
        let out = execute(&json!({"query": q}));
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(
            out.get("query_engine").and_then(|v| v.as_str()),
            Some("sparql")
        );
    }

    #[test]
    fn rejects_update_queries() {
        let out = execute(&json!({"query": "DELETE WHERE { ?s ?p ?o }"}));
        assert_eq!(out.get("ok").and_then(|v| v.as_bool()), Some(false));
    }
}
