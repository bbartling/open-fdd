//! Haystack grid → RDF (Turtle) and in-memory Oxigraph store for SPARQL.

use crate::model::query;
use crate::validation::profile::workspace_dir;
use once_cell::sync::Lazy;
use oxigraph::io::RdfFormat;
use oxigraph::model::Term;
use oxigraph::sparql::{QueryResults, SparqlEvaluator};
use oxigraph::store::Store;
use serde_json::Value;
use std::collections::{hash_map::DefaultHasher, HashMap};
use std::hash::{Hash, Hasher};
use std::sync::RwLock;

pub const HS_PREFIX: &str = "https://project-haystack.org/def/";
pub const OFDD_PREFIX: &str = "https://open-fdd.dev/model#";

static STORE: Lazy<RwLock<StoreState>> = Lazy::new(|| RwLock::new(StoreState::empty()));

struct StoreState {
    workspace_key: String,
    grid_hash: u64,
    store: Option<Store>,
}

impl StoreState {
    fn empty() -> Self {
        Self {
            workspace_key: String::new(),
            grid_hash: 0,
            store: None,
        }
    }
}

/// Open-FDD application metadata uses `ofdd:` in Turtle (not Project Haystack `hs:`).
const OFDD_LITERAL_KEYS: &[&str] = &["fddInput", "importJob", "protocol"];
const OFDD_REF_KEYS: &[&str] = &["csvRef"];
const TYPE_MARKER_KEYS: &[&str] = &[
    "site",
    "equip",
    "point",
    "ahu",
    "vav",
    "chiller",
    "boiler",
    "coolingTower",
    "doas",
    "source",
];
const POINT_ROLE_KEYS: &[&str] = &["sensor", "cmd", "sp", "synthetic"];

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

fn legacy_hs_custom_tags() -> bool {
    std::env::var("OPENFDD_RDF_LEGACY_HS_CUSTOM_TAGS").as_deref() == Ok("1")
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

fn is_ofdd_key(key: &str) -> bool {
    OFDD_LITERAL_KEYS.contains(&key) || OFDD_REF_KEYS.contains(&key)
}

fn predicate_for_key(key: &str) -> String {
    if is_ofdd_key(key) {
        format!("ofdd:{key}")
    } else {
        format!("hs:{key}")
    }
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
        return Some(if b { "true".into() } else { "false".into() });
    }
    None
}

fn enrich_rows(rows: &[Value]) -> Vec<Value> {
    let mut equip_site: HashMap<String, String> = HashMap::new();
    for row in rows {
        let Some(eid) = row.get("id").and_then(|v| v.as_str()) else {
            continue;
        };
        if row.get("equip").is_some() {
            if let Some(site) = row.get("siteRef").and_then(|v| v.as_str()) {
                equip_site.insert(eid.to_string(), site.to_string());
            }
        }
    }

    rows.iter()
        .map(|row| {
            if row.get("point").is_none() {
                return row.clone();
            }
            if row.get("siteRef").is_some() {
                return row.clone();
            }
            let Some(equip_ref) = row.get("equipRef").and_then(|v| v.as_str()) else {
                return row.clone();
            };
            let Some(site) = equip_site.get(equip_ref) else {
                return row.clone();
            };
            let mut obj = row
                .as_object()
                .cloned()
                .unwrap_or_else(serde_json::Map::new);
            obj.insert("siteRef".into(), Value::String(site.clone()));
            Value::Object(obj)
        })
        .collect()
}

fn point_has_role_marker(row: &Value) -> bool {
    POINT_ROLE_KEYS.iter().any(|key| row.get(*key).is_some())
}

fn format_subject_block(subj: &str, triples: &[(String, String)]) -> String {
    if triples.is_empty() {
        return String::new();
    }
    let mut lines = vec![subj.to_string()];
    for (i, (pred, obj)) in triples.iter().enumerate() {
        let end = if i + 1 == triples.len() { " ." } else { " ;" };
        lines.push(format!("  {pred} {obj}{end}"));
    }
    lines.join("\n")
}

fn push_triple(triples: &mut Vec<(String, String)>, pred: String, obj: String) {
    triples.push((pred, obj));
}

fn push_legacy_hs_triple(triples: &mut Vec<(String, String)>, key: &str, obj: String) {
    if legacy_hs_custom_tags() && is_ofdd_key(key) {
        triples.push((format!("hs:{key}"), obj));
    }
}

/// Build Turtle from Haystack grid rows (full semantic projection for SPARQL).
pub fn haystack_rows_to_turtle(rows: &[Value]) -> String {
    let rows = enrich_rows(rows);
    let mut lines = vec![
        format!("@prefix hs: <{HS_PREFIX}> ."),
        format!("@prefix ofdd: <{OFDD_PREFIX}> ."),
        format!("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> ."),
        String::new(),
    ];

    for row in &rows {
        let Some(id) = row.get("id").and_then(|v| v.as_str()) else {
            continue;
        };
        if id.is_empty() {
            continue;
        }
        let subj = turtle_subject(id);
        let mut triples: Vec<(String, String)> = Vec::new();

        for rdf_type in haystack_type_triples(row) {
            push_triple(&mut triples, "a".into(), rdf_type);
        }

        push_triple(
            &mut triples,
            "ofdd:haystackId".into(),
            format!("\"{}\"", turtle_escape(id)),
        );

        if row.get("equip").is_some() {
            push_triple(
                &mut triples,
                "ofdd:equipType".into(),
                format!("\"{}\"", turtle_escape(infer_equip_type(row))),
            );
        }

        for (key, value) in row.as_object().into_iter().flatten() {
            if key == "id" || TYPE_MARKER_KEYS.contains(&key.as_str()) {
                continue;
            }
            if POINT_ROLE_KEYS.contains(&key.as_str()) && is_marker(value) {
                push_triple(&mut triples, format!("hs:{key}"), "true".into());
                continue;
            }
            if is_marker(value) {
                continue;
            }
            if key.ends_with("Ref") {
                if let Some(ref_id) = value.as_str() {
                    if !ref_id.is_empty() {
                        let obj = turtle_subject(ref_id);
                        let pred = predicate_for_key(key);
                        push_triple(&mut triples, pred, obj.clone());
                        push_legacy_hs_triple(&mut triples, key, obj);
                    }
                }
                continue;
            }
            if let Some(lit) = literal_object(value) {
                let pred = predicate_for_key(key);
                push_triple(&mut triples, pred.clone(), lit.clone());
                push_legacy_hs_triple(&mut triples, key, lit);
            }
        }

        if row.get("point").is_some() && !point_has_role_marker(row) {
            push_triple(&mut triples, "hs:sensor".into(), "true".into());
        }

        let block = format_subject_block(&subj, &triples);
        if !block.is_empty() {
            lines.push(block);
            lines.push(String::new());
        }
    }

    lines.join("\n")
}

pub fn haystack_to_turtle() -> String {
    haystack_rows_to_turtle(&query::haystack_rows())
}

fn ensure_store() -> Result<(), String> {
    let workspace_key = workspace_dir().display().to_string();
    let rows = query::haystack_rows();
    let hash = grid_fingerprint(&rows);
    {
        let guard = STORE
            .read()
            .map_err(|_| "RDF store lock poisoned".to_string())?;
        if guard.workspace_key == workspace_key
            && guard.grid_hash == hash
            && guard.store.is_some()
        {
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
    guard.workspace_key = workspace_key;
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

    fn school_kw_fixture_rows() -> Vec<Value> {
        vec![
            json!({
                "id": "site:school-kw-merged",
                "dis": "school_kw_merged",
                "site": "M"
            }),
            json!({
                "id": "source:csv:school-kw-merged",
                "dis": "CSV source (school-kw-merged)",
                "source": "M",
                "protocol": "csv",
                "importJob": "dataset-school_kw_merged"
            }),
            json!({
                "id": "equip:school-kw-merged",
                "dis": "school_kw_merged",
                "equip": "M",
                "siteRef": "site:school-kw-merged",
                "sourceRef": "source:csv:school-kw-merged"
            }),
            json!({
                "id": "point:school-kw-merged-temp_f",
                "dis": "temp_f",
                "point": "M",
                "sensor": "M",
                "kind": "Number",
                "unit": "°F",
                "equipRef": "equip:school-kw-merged",
                "sourceRef": "source:csv:school-kw-merged",
                "fddInput": "temp_f",
                "csvRef": "csv:source:csv:school-kw-merged:temp_f"
            }),
        ]
    }

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
        assert!(ttl.contains("ofdd:fddInput \"oa_t\""));
        assert!(ttl.contains("ofdd:equipType \"ahu\""));
        assert!(ttl.contains("hs:sensor true"));
        Store::new()
            .unwrap()
            .load_from_reader(RdfFormat::Turtle, ttl.as_bytes())
            .expect("turtle parses");
    }

    #[test]
    fn csv_import_fixture_semantic_shape() {
        let ttl = haystack_rows_to_turtle(&school_kw_fixture_rows());
        assert!(ttl.contains("hs:siteRef ofdd:site_school_kw_merged"));
        assert!(ttl.contains("hs:equipRef ofdd:equip_school_kw_merged"));
        assert!(ttl.contains("ofdd:csvRef ofdd:csv_source_csv_school_kw_merged_temp_f"));
        assert!(ttl.contains("ofdd:fddInput \"temp_f\""));
        assert!(ttl.contains("ofdd:importJob \"dataset-school_kw_merged\""));
        assert!(ttl.contains("ofdd:protocol \"csv\""));
        assert!(ttl.contains("hs:sensor true"));
        assert!(!ttl.contains("hs:csvRef"));
        assert!(!ttl.contains("hs:fddInput"));
        assert!(!ttl.contains("hs:importJob"));
        assert!(!ttl.contains("hs:protocol"));

        let store = Store::new().unwrap();
        store
            .load_from_reader(RdfFormat::Turtle, ttl.as_bytes())
            .expect("fixture turtle parses");

        let q = r#"
            PREFIX hs: <https://project-haystack.org/def/>
            PREFIX ofdd: <https://open-fdd.dev/model#>
            SELECT ?point WHERE {
              ?p a hs:Point .
              ?p ofdd:haystackId ?point .
              ?p hs:siteRef ?site .
              ?p hs:equipRef ?eq .
              ?p hs:dis ?dis .
              ?p hs:sensor ?role .
              ?p ofdd:fddInput ?fdd .
              ?p ofdd:csvRef ?csv .
            }
        "#;
        let rows = SparqlEvaluator::new()
            .parse_query(q)
            .unwrap()
            .on_store(&store)
            .execute()
            .unwrap();
        match rows {
            QueryResults::Solutions(solutions) => {
                let count = solutions.into_iter().count();
                assert_eq!(count, 1);
            }
            _ => panic!("expected SELECT results"),
        }
    }

    #[test]
    fn every_point_has_site_ref_via_enrichment() {
        let rows = vec![
            json!({"id": "site:a", "dis": "A", "site": "M"}),
            json!({"id": "equip:e1", "dis": "E1", "equip": "M", "siteRef": "site:a"}),
            json!({"id": "point:p1", "dis": "P1", "point": "M", "equipRef": "equip:e1"}),
        ];
        let ttl = haystack_rows_to_turtle(&rows);
        assert!(ttl.contains("ofdd:point_p1"));
        assert!(ttl.contains("hs:siteRef ofdd:site_a"));
        assert!(ttl.contains("hs:equipRef ofdd:equip_e1"));
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
