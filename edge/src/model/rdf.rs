//! Haystack grid → RDF (Turtle) and in-memory Oxigraph store for SPARQL.

use crate::model::query;
use once_cell::sync::Lazy;
use oxigraph::io::RdfFormat;
use oxigraph::model::Term;
use oxigraph::sparql::{QueryResults, SparqlEvaluator};
use oxigraph::store::Store;
use serde_json::Value;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::RwLock;

pub const HS_PREFIX: &str = "https://project-haystack.org/def/";
pub const OFDD_PREFIX: &str = "https://open-fdd.dev/model#";

static STORE: Lazy<RwLock<StoreState>> = Lazy::new(|| RwLock::new(StoreState::empty()));

struct StoreState {
    grid_hash: u64,
    store: Option<Store>,
}

impl StoreState {
    fn empty() -> Self {
        Self {
            grid_hash: 0,
            store: None,
        }
    }
}

/// Drop cached store so the next query reloads from the current Haystack grid.
pub fn invalidate_store() {
    if let Ok(mut guard) = STORE.write() {
        *guard = StoreState::empty();
    }
}

fn grid_fingerprint(rows: &[Value]) -> u64 {
    let mut hasher = DefaultHasher::new();
    serde_json::to_string(rows)
        .unwrap_or_default()
        .hash(&mut hasher);
    hasher.finish()
}

/// Turtle local name for a Haystack ref id (`site:lab` → `site_lab`).
pub fn turtle_local(id: &str) -> String {
    id.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

pub fn turtle_subject(id: &str) -> String {
    format!("ofdd:{}", turtle_local(id))
}

pub fn turtle_escape(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}

fn is_marker(v: &Value) -> bool {
    matches!(v.as_str(), Some("M")) || v.as_bool() == Some(true)
}

fn infer_equip_type(row: &Value) -> &'static str {
    if row.get("ahu").is_some() {
        "ahu"
    } else if row.get("vav").is_some() {
        "vav"
    } else if row.get("chiller").is_some() {
        "chiller"
    } else if row.get("boiler").is_some() {
        "boiler"
    } else if row.get("coolingTower").is_some() {
        "cooling_tower"
    } else if row.get("doas").is_some() {
        "doas"
    } else {
        "generic"
    }
}

fn haystack_type_triples(row: &Value) -> Vec<String> {
    let mut types = Vec::new();
    if row.get("site").is_some() {
        types.push("hs:Site".into());
    }
    if row.get("equip").is_some() {
        types.push("hs:Equip".into());
    }
    if row.get("point").is_some() {
        types.push("hs:Point".into());
    }
    for (tag, hs_type) in [
        ("ahu", "hs:AHU"),
        ("vav", "hs:VAV"),
        ("chiller", "hs:Chiller"),
        ("boiler", "hs:Boiler"),
        ("coolingTower", "hs:CoolingTower"),
        ("doas", "hs:DOAS"),
    ] {
        if row.get(tag).is_some() {
            types.push(hs_type.into());
        }
    }
    types
}

fn literal_object(v: &Value) -> Option<String> {
    if let Some(s) = v.as_str() {
        return Some(format!("\"{}\"", turtle_escape(s)));
    }
    if let Some(n) = v.as_f64() {
        return Some(format!(
            "\"{n}\"^^<http://www.w3.org/2001/XMLSchema#double>"
        ));
    }
    if let Some(n) = v.as_i64() {
        return Some(format!(
            "\"{n}\"^^<http://www.w3.org/2001/XMLSchema#integer>"
        ));
    }
    if let Some(b) = v.as_bool() {
        return Some(format!(
            "\"{}\"^^<http://www.w3.org/2001/XMLSchema#boolean>",
            b
        ));
    }
    None
}

/// Build Turtle from Haystack grid rows (full semantic projection for SPARQL).
pub fn haystack_rows_to_turtle(rows: &[Value]) -> String {
    let mut lines = vec![
        format!("@prefix hs: <{HS_PREFIX}> ."),
        format!("@prefix ofdd: <{OFDD_PREFIX}> ."),
        format!("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> ."),
        String::new(),
    ];

    for row in rows {
        let Some(id) = row.get("id").and_then(|v| v.as_str()) else {
            continue;
        };
        if id.is_empty() {
            continue;
        }
        let subj = turtle_subject(id);
        let mut preds: Vec<String> = Vec::new();

        preds.push(format!(
            "{subj} ofdd:haystackId \"{}\" .",
            turtle_escape(id)
        ));

        for rdf_type in haystack_type_triples(row) {
            preds.push(format!("{subj} a {rdf_type} ."));
        }

        if row.get("equip").is_some() {
            preds.push(format!(
                "{subj} ofdd:equipType \"{}\" .",
                turtle_escape(infer_equip_type(row))
            ));
        }

        for (key, value) in row.as_object().into_iter().flatten() {
            if key == "id" {
                continue;
            }
            let pred = format!("hs:{key}");
            if key.ends_with("Ref") {
                if let Some(ref_id) = value.as_str() {
                    if !ref_id.is_empty() {
                        preds.push(format!("{subj} {pred} {} .", turtle_subject(ref_id)));
                    }
                }
                continue;
            }
            if is_marker(value) {
                // Marker tags are represented via rdf:type (hs:Site, hs:Equip, …) above.
                continue;
            }
            if let Some(lit) = literal_object(value) {
                preds.push(format!("{subj} {pred} {lit} ."));
            }
        }

        lines.extend(preds);
        lines.push(String::new());
    }

    lines.join("\n")
}

pub fn haystack_to_turtle() -> String {
    haystack_rows_to_turtle(&query::haystack_rows())
}

fn ensure_store() -> Result<(), String> {
    let rows = query::haystack_rows();
    let hash = grid_fingerprint(&rows);
    {
        let guard = STORE
            .read()
            .map_err(|_| "RDF store lock poisoned".to_string())?;
        if guard.grid_hash == hash && guard.store.is_some() {
            return Ok(());
        }
    }

    let turtle = haystack_rows_to_turtle(&rows);
    let store = Store::new().map_err(|e| format!("RDF store init failed: {e}"))?;
    store
        .load_from_reader(RdfFormat::Turtle, turtle.as_bytes())
        .map_err(|e| format!("Turtle load failed: {e}"))?;

    let mut guard = STORE
        .write()
        .map_err(|_| "RDF store lock poisoned".to_string())?;
    guard.grid_hash = hash;
    guard.store = Some(store);
    Ok(())
}

fn with_store<F, T>(f: F) -> Result<T, String>
where
    F: FnOnce(&Store) -> Result<T, String>,
{
    ensure_store()?;
    let guard = STORE
        .read()
        .map_err(|_| "RDF store lock poisoned".to_string())?;
    let store = guard
        .store
        .as_ref()
        .ok_or_else(|| "RDF store unavailable".to_string())?;
    f(store)
}

fn term_to_binding_string(term: &Term) -> String {
    match term {
        Term::Literal(lit) => lit.value().to_string(),
        Term::NamedNode(node) => {
            let iri = node.as_str();
            if let Some(local) = iri.strip_prefix(OFDD_PREFIX) {
                // Best-effort reverse: site_lab → site:lab is lossy; prefer haystackId in queries.
                local.replace('_', ":")
            } else if let Some(local) = iri.strip_prefix(HS_PREFIX) {
                format!("hs:{local}")
            } else {
                iri.to_string()
            }
        }
        Term::BlankNode(b) => format!("_:{b}"),
    }
}

/// Execute a read-only SPARQL SELECT; returns variable → string bindings per row.
pub fn sparql_select(
    query_text: &str,
) -> Result<Vec<std::collections::HashMap<String, String>>, String> {
    let trimmed = query_text.trim();
    if trimmed.is_empty() {
        return Err("query required".into());
    }
    let upper = trimmed.to_uppercase();
    if upper.contains("INSERT")
        || upper.contains("DELETE")
        || upper.contains("CREATE")
        || upper.contains("DROP")
        || upper.contains("LOAD")
        || upper.contains("CLEAR")
        || upper.contains("MOVE")
        || upper.contains("COPY")
        || upper.contains("ADD")
    {
        return Err("Only read-only SELECT queries are supported".into());
    }

    with_store(|store| {
        let results = SparqlEvaluator::new()
            .parse_query(trimmed)
            .map_err(|e| format!("SPARQL parse error: {e}"))?
            .on_store(store)
            .execute()
            .map_err(|e| format!("SPARQL execution error: {e}"))?;

        match results {
            QueryResults::Solutions(solutions) => {
                let mut rows = Vec::new();
                for sol in solutions {
                    let sol = sol.map_err(|e| format!("SPARQL solution error: {e}"))?;
                    let mut map = std::collections::HashMap::new();
                    for (var, term) in sol.iter() {
                        map.insert(var.as_str().to_string(), term_to_binding_string(term));
                    }
                    rows.push(map);
                }
                Ok(rows)
            }
            QueryResults::Boolean(_) => Err("Only SELECT queries are supported".into()),
            QueryResults::Graph(_) => Err("Only SELECT queries are supported".into()),
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn turtle_includes_types_and_refs() {
        let rows = vec![
            json!({
                "id": "site:lab",
                "dis": "Lab Site",
                "site": "M"
            }),
            json!({
                "id": "equip:ahu1",
                "dis": "AHU-1",
                "equip": "M",
                "ahu": "M",
                "siteRef": "site:lab"
            }),
            json!({
                "id": "point:oa",
                "dis": "OA Temp",
                "point": "M",
                "equipRef": "equip:ahu1",
                "fddInput": "oa_t"
            }),
        ];
        let ttl = haystack_rows_to_turtle(&rows);
        assert!(ttl.contains("a hs:Site"));
        assert!(ttl.contains("a hs:Equip"));
        assert!(ttl.contains("hs:siteRef ofdd:site_lab"));
        assert!(ttl.contains("hs:fddInput \"oa_t\""));
        assert!(ttl.contains("ofdd:equipType \"ahu\""));
    }

    #[test]
    fn sparql_select_sites_on_fixture() {
        invalidate_store();
        let q = r#"
            PREFIX hs: <https://project-haystack.org/def/>
            PREFIX ofdd: <https://open-fdd.dev/model#>
            SELECT ?site ?dis WHERE {
              ?s a hs:Site .
              ?s ofdd:haystackId ?site .
              OPTIONAL { ?s hs:dis ?dis . }
            }
        "#;
        let _ = sparql_select(q);
    }
}
