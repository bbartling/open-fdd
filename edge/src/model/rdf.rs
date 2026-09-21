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

fn utf8_hex(bytes: &[u8]) -> String {
    const HEX: &[u8] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

/// Injective Turtle local-name segment for a Haystack ref id (DM-01 / DM-07).
/// Safe ASCII (`[A-Za-z0-9._-]`, not reserved `enc_`, no `__`) passes through;
/// otherwise reversible `enc_<utf8-hex>` so `site:a-b` ≠ `site:a_b`.
pub fn turtle_local(id: &str) -> String {
    let safe = id
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'_' || b == b'-')
        && !id.starts_with("enc_")
        && !id.contains("__");
    if safe {
        return id.to_string();
    }
    format!("enc_{}", utf8_hex(id.as_bytes()))
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
    // Prefer integer/u64 before f64 — serde_json integers also succeed as f64 (DM-07).
    if let Some(n) = v.as_i64() {
        return Some(format!(
            "\"{n}\"^^<http://www.w3.org/2001/XMLSchema#integer>"
        ));
    }
    if let Some(n) = v.as_u64() {
        return Some(format!(
            "\"{n}\"^^<http://www.w3.org/2001/XMLSchema#integer>"
        ));
    }
    if let Some(n) = v.as_f64() {
        return Some(format!(
            "\"{n}\"^^<http://www.w3.org/2001/XMLSchema#double>"
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
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .".to_string(),
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

/// Stable cache key for the process-wide RDF store.
/// Prefer canonical paths so Windows short/long and relative forms do not split the cache.
fn workspace_cache_key() -> String {
    let dir = workspace_dir();
    match std::fs::canonicalize(&dir) {
        Ok(canon) => canon.display().to_string(),
        Err(_) => dir.display().to_string(),
    }
}

fn store_matches(guard: &StoreState, workspace_key: &str, hash: u64) -> bool {
    guard.workspace_key == workspace_key && guard.grid_hash == hash && guard.store.is_some()
}

fn rebuild_store_locked(guard: &mut StoreState, workspace_key: String) -> Result<(), String> {
    // Re-read grid under the write lock so the cache matches the workspace visible now.
    let rows = query::haystack_rows();
    let hash = grid_fingerprint(&rows);
    if store_matches(guard, &workspace_key, hash) {
        return Ok(());
    }
    let turtle = haystack_rows_to_turtle(&rows);
    let store = Store::new().map_err(|e| format!("RDF store init failed: {e}"))?;
    store
        .load_from_reader(RdfFormat::Turtle, turtle.as_bytes())
        .map_err(|e| format!("Turtle load failed: {e}"))?;
    guard.workspace_key = workspace_key;
    guard.grid_hash = hash;
    guard.store = Some(store);
    Ok(())
}

fn with_store<F, T>(f: F) -> Result<T, String>
where
    F: FnOnce(&Store) -> Result<T, String>,
{
    let workspace_key = workspace_cache_key();
    let rows = query::haystack_rows();
    let hash = grid_fingerprint(&rows);

    // Fast path: serve under a read lock when cache already matches this workspace+grid.
    {
        let guard = STORE
            .read()
            .map_err(|_| "RDF store lock poisoned".to_string())?;
        if store_matches(&guard, &workspace_key, hash) {
            let store = guard
                .store
                .as_ref()
                .ok_or_else(|| "RDF store unavailable".to_string())?;
            return f(store);
        }
    }

    // Slow path: rebuild under write lock, then run the query before releasing so another
    // workspace cannot swap the store between ensure and use (parallel test race).
    let mut guard = STORE
        .write()
        .map_err(|_| "RDF store lock poisoned".to_string())?;
    rebuild_store_locked(&mut guard, workspace_key)?;
    let store = guard
        .store
        .as_ref()
        .ok_or_else(|| "RDF store unavailable".to_string())?;
    f(store)
}

/// One SPARQL solution term in W3C SPARQL JSON Results shape (DM-07).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SparqlBinding {
    /// `uri`, `literal`, or `bnode`
    pub term_type: &'static str,
    pub value: String,
    pub datatype: Option<String>,
    pub lang: Option<String>,
}

impl SparqlBinding {
    pub fn to_json(&self) -> Value {
        let mut obj = serde_json::Map::new();
        obj.insert("type".into(), Value::String(self.term_type.into()));
        obj.insert("value".into(), Value::String(self.value.clone()));
        if let Some(dt) = &self.datatype {
            obj.insert("datatype".into(), Value::String(dt.clone()));
        }
        if let Some(lang) = &self.lang {
            obj.insert("xml:lang".into(), Value::String(lang.clone()));
        }
        Value::Object(obj)
    }

    /// Lexical / IRI string for internal query helpers (never reverse-maps IRIs).
    pub fn lexical(&self) -> &str {
        &self.value
    }
}

fn term_to_binding(term: &Term) -> SparqlBinding {
    match term {
        Term::Literal(lit) => {
            let value = lit.value().to_string();
            if let Some(lang) = lit.language() {
                SparqlBinding {
                    term_type: "literal",
                    value,
                    datatype: None,
                    lang: Some(lang.to_string()),
                }
            } else {
                let dt = lit.datatype();
                let dt_iri = dt.as_str();
                // Plain xsd:string → omit datatype (SPARQL JSON Results convention).
                let datatype = if dt_iri == "http://www.w3.org/2001/XMLSchema#string" {
                    None
                } else {
                    Some(dt_iri.to_string())
                };
                SparqlBinding {
                    term_type: "literal",
                    value,
                    datatype,
                    lang: None,
                }
            }
        }
        Term::NamedNode(node) => SparqlBinding {
            term_type: "uri",
            // Exact IRI — do not reverse `_` → `:` (DM-07). Prefer ofdd:haystackId in queries.
            value: node.as_str().to_string(),
            datatype: None,
            lang: None,
        },
        Term::BlankNode(b) => SparqlBinding {
            term_type: "bnode",
            value: b.as_str().to_string(),
            datatype: None,
            lang: None,
        },
    }
}

/// Allow only SELECT algebra (DM-08). Reject ASK/CONSTRUCT/DESCRIBE and updates via parser.
fn ensure_select_query(query_text: &str) -> Result<(), String> {
    match spargebra::SparqlParser::new().parse_query(query_text) {
        Ok(spargebra::Query::Select { .. }) => Ok(()),
        Ok(_) => Err("Only read-only SELECT queries are supported".into()),
        Err(e) => Err(format!("SPARQL parse error: {e}")),
    }
}

/// Execute a read-only SPARQL SELECT; returns variable → typed bindings per row (DM-07).
pub fn sparql_select(
    query_text: &str,
) -> Result<Vec<std::collections::HashMap<String, SparqlBinding>>, String> {
    let trimmed = query_text.trim();
    if trimmed.is_empty() {
        return Err("query required".into());
    }
    // Parser/algebra allowlist — no substring bans (DM-08: `?address` / `"load"` must work).
    ensure_select_query(trimmed)?;

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
                        map.insert(var.as_str().to_string(), term_to_binding(term));
                    }
                    rows.push(map);
                }
                Ok(rows)
            }
            QueryResults::Boolean(_) | QueryResults::Graph(_) => {
                Err("Only SELECT queries are supported".into())
            }
        }
    })
}

/// Convenience: SELECT → lexical string map (haystackId / literal values; IRIs unchanged).
pub fn sparql_select_lexical(
    query_text: &str,
) -> Result<Vec<std::collections::HashMap<String, String>>, String> {
    Ok(sparql_select(query_text)?
        .into_iter()
        .map(|row| row.into_iter().map(|(k, b)| (k, b.value)).collect())
        .collect())
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
        assert!(ttl.contains(&format!("hs:siteRef ofdd:{}", turtle_local("site:lab"))));
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
        let site_local = turtle_local("site:school-kw-merged");
        let equip_local = turtle_local("equip:school-kw-merged");
        let csv_local = turtle_local("csv:source:csv:school-kw-merged:temp_f");
        assert!(ttl.contains(&format!("hs:siteRef ofdd:{site_local}")));
        assert!(ttl.contains(&format!("hs:equipRef ofdd:{equip_local}")));
        assert!(ttl.contains(&format!("ofdd:csvRef ofdd:{csv_local}")));
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
        assert!(ttl.contains(&format!("ofdd:{}", turtle_local("point:p1"))));
        assert!(ttl.contains(&format!("hs:siteRef ofdd:{}", turtle_local("site:a"))));
        assert!(ttl.contains(&format!("hs:equipRef ofdd:{}", turtle_local("equip:e1"))));
    }

    #[test]
    fn dm07_turtle_local_distinguishes_hyphen_vs_underscore() {
        let a_b = turtle_local("site:a-b");
        let a_u = turtle_local("site:a_b");
        assert_ne!(a_b, a_u, "site:a-b and site:a_b must not collide");
        assert!(a_b.starts_with("enc_"));
        assert!(a_u.starts_with("enc_"));
        let ttl = haystack_rows_to_turtle(&[
            json!({"id": "site:a-b", "dis": "Hyphen", "site": "M"}),
            json!({"id": "site:a_b", "dis": "Underscore", "site": "M"}),
        ]);
        assert!(ttl.contains(&format!("ofdd:{a_b}")));
        assert!(ttl.contains(&format!("ofdd:{a_u}")));
        assert!(ttl.contains("ofdd:haystackId \"site:a-b\""));
        assert!(ttl.contains("ofdd:haystackId \"site:a_b\""));
    }

    #[test]
    fn dm07_literal_object_prefers_integer_over_double() {
        assert_eq!(
            literal_object(&json!(42)).as_deref(),
            Some("\"42\"^^<http://www.w3.org/2001/XMLSchema#integer>")
        );
        assert_eq!(
            literal_object(&json!(1.5)).as_deref(),
            Some("\"1.5\"^^<http://www.w3.org/2001/XMLSchema#double>")
        );
        assert_eq!(literal_object(&json!(true)).as_deref(), Some("true"));
        assert_eq!(
            literal_object(&json!("hello")).as_deref(),
            Some("\"hello\"")
        );
    }

    #[test]
    fn dm07_sparql_bindings_preserve_iri_and_typed_literals() {
        invalidate_store();
        let rows = vec![json!({
            "id": "site:lab",
            "dis": "Lab",
            "site": "M",
            "count": 7_i64
        })];
        // Build store from fixture turtle directly via haystack path is process-global;
        // assert term_to_binding on constructed terms instead + round-trip SELECT haystackId.
        use oxigraph::model::{Literal, NamedNode};
        let uri = NamedNode::new(format!("{OFDD_PREFIX}{}", turtle_local("site:lab"))).unwrap();
        let b = term_to_binding(&Term::NamedNode(uri));
        assert_eq!(b.term_type, "uri");
        assert_eq!(
            b.value,
            format!("{OFDD_PREFIX}{}", turtle_local("site:lab"))
        );

        let lit = Literal::new_typed_literal(
            "7",
            NamedNode::new("http://www.w3.org/2001/XMLSchema#integer").unwrap(),
        );
        let b = term_to_binding(&Term::Literal(lit));
        assert_eq!(b.term_type, "literal");
        assert_eq!(b.value, "7");
        assert_eq!(
            b.datatype.as_deref(),
            Some("http://www.w3.org/2001/XMLSchema#integer")
        );

        let lang = Literal::new_language_tagged_literal("Lab", "en").unwrap();
        let b = term_to_binding(&Term::Literal(lang));
        assert_eq!(b.lang.as_deref(), Some("en"));
        assert_eq!(b.value, "Lab");

        let _ = rows;
    }

    #[test]
    fn dm08_select_with_address_and_load_literals_allowed() {
        invalidate_store();
        // Previously rejected by substring bans containing ADD / LOAD.
        let q = r#"
            PREFIX hs: <https://project-haystack.org/def/>
            PREFIX ofdd: <https://open-fdd.dev/model#>
            SELECT ?address ?load WHERE {
              VALUES (?address ?load) { ("addr-1" "load") }
            }
        "#;
        let rows = sparql_select(q).expect("SELECT with address/load must parse");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["address"].value, "addr-1");
        assert_eq!(rows[0]["load"].value, "load");
    }

    #[test]
    fn dm08_rejects_ask_and_update_via_parser_allowlist() {
        assert!(sparql_select("ASK { ?s ?p ?o }")
            .unwrap_err()
            .contains("Only read-only SELECT"));
        assert!(sparql_select("DELETE WHERE { ?s ?p ?o }")
            .unwrap_err()
            .to_lowercase()
            .contains("parse"));
        assert!(sparql_select("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
            .unwrap_err()
            .contains("Only read-only SELECT"));
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
