//! Server-owned SPARQL compile for portal ingest plans (Wave-NF N3).
//!
//! The template is parsed and executed against an authorized named graph.
//! Callers bind tenant, site, provider instance, and graph identity. They do
//! not supply query text. Remote `SERVICE` and mutation forms are rejected.
//! Extension predicates live in `urn:openfdd:ingest:v1:` and are not Haystack tags.

use std::collections::{BTreeMap, BTreeSet};
use std::io::Cursor;
use std::time::{Duration, Instant};

use oxigraph::io::RdfFormat;
use oxigraph::model::{GraphName, GraphNameRef, NamedNode, Quad};
use oxigraph::sparql::{QueryResults, SparqlEvaluator};
use oxigraph::store::Store;

use super::haystack_sparql_bindings::ensure_readonly_query;
use crate::model::rdf::term_to_binding;

pub const INGEST_NS: &str = "urn:openfdd:ingest:v1:";
pub const MAX_SNAPSHOT_BYTES: usize = 2_000_000;
pub const MAX_ROWS: usize = 5_000;
const MAX_TIMEOUT: Duration = Duration::from_secs(30);

const FORBIDDEN_PREDICATES: &[&str] = &[
    "httpMethod",
    "httpVerb",
    "requestUrl",
    "header",
    "headers",
    "authorization",
    "credential",
    "secret",
    "sql",
    "script",
];

/// One typed binding projected by the server template.
///
/// The connection IRI is an identifier checked during compile and then dropped.
/// It is not a URL the ingest plan may execute.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestBindingRow {
    pub tenant_id: String,
    pub site_id: String,
    pub provider_instance_id: String,
    pub equipment_id: String,
    pub equip_type: String,
    pub semantic_point_id: String,
    pub source_point_id: String,
    pub canonical_role: String,
    pub selection_status: String,
    pub source_unit: Option<String>,
    pub canonical_unit: Option<String>,
    pub kind: Option<String>,
    pub provisional: bool,
    /// Binding expectation. `None` means the binding states no expectation, so
    /// coverage for the point stays not assessed.
    pub quantity: Option<String>,
    pub history_mode: Option<String>,
    pub cadence_secs: Option<u64>,
    pub heartbeat_secs: Option<u64>,
}

/// Largest interval cadence a binding may declare (one day).
pub const MAX_BINDING_CADENCE_SECS: u64 = 86_400;
/// Largest COV heartbeat a binding may declare (seven days).
pub const MAX_BINDING_HEARTBEAT_SECS: u64 = 604_800;

#[derive(Debug, Clone)]
pub struct IngestSparqlScope {
    pub tenant_id: String,
    pub site_id: String,
    pub authorized_graph: String,
    pub provider_instance_id: String,
    pub max_rows: usize,
    pub timeout: Duration,
}

impl IngestSparqlScope {
    pub fn new(
        tenant_id: impl Into<String>,
        site_id: impl Into<String>,
        authorized_graph: impl Into<String>,
        provider_instance_id: impl Into<String>,
    ) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            site_id: site_id.into(),
            authorized_graph: authorized_graph.into(),
            provider_instance_id: provider_instance_id.into(),
            max_rows: MAX_ROWS,
            timeout: Duration::from_secs(2),
        }
    }
}

pub fn validate_slug(field: &str, value: &str, max: usize) -> Result<(), String> {
    if value.is_empty() || value.len() > max {
        return Err(format!("malformed {field}"));
    }
    if !value
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        return Err(format!("malformed {field}"));
    }
    Ok(())
}

pub fn validate_semantic_point_id(value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 256
        || value.chars().any(|c| c.is_control() || c.is_whitespace())
    {
        return Err("malformed semantic point id".into());
    }
    if value
        .chars()
        .any(|c| matches!(c, '<' | '>' | '"' | '{' | '}' | '\\'))
    {
        return Err("malformed semantic point id".into());
    }
    Ok(())
}

pub fn validate_source_point_id(value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 256
        || value.chars().any(|c| c.is_control() || c.is_whitespace())
    {
        return Err("malformed source point id".into());
    }
    if value
        .chars()
        .any(|c| matches!(c, '<' | '>' | '"' | '{' | '}' | '\\' | ' '))
    {
        return Err("malformed source point id".into());
    }
    Ok(())
}

pub fn validate_unit(value: &str) -> Result<(), String> {
    if value.is_empty() || value.len() > 32 || value.chars().all(|c| c.is_whitespace()) {
        return Err("malformed unit".into());
    }
    if value.chars().any(|c| {
        c.is_control() || matches!(c, '<' | '>' | '"' | '\'' | '{' | '}' | '\\' | ';' | '`')
    }) {
        return Err("malformed unit".into());
    }
    Ok(())
}

/// Compile the server template once over `snapshot` (Turtle rehomed into the
/// authorized graph, or TriG when the document already has named graphs).
pub fn compile_bindings_from_snapshot(
    snapshot: &str,
    scope: &IngestSparqlScope,
) -> Result<Vec<IngestBindingRow>, String> {
    let started = Instant::now();
    validate_scope(scope)?;
    if snapshot.len() > MAX_SNAPSHOT_BYTES {
        return Err(format!("model snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes"));
    }
    let graph = NamedNode::new(scope.authorized_graph.as_str())
        .map_err(|e| format!("malformed authorized graph IRI: {e}"))?;
    let store = load_snapshot(snapshot, &graph)?;
    reject_executable_predicates(&store)?;
    let query = select_query(&scope.authorized_graph, scope.max_rows.saturating_add(1))?;
    ensure_readonly_query(&query)?;
    let rows = execute_select(&store, &query, scope)?;
    if started.elapsed() > scope.timeout {
        return Err("SPARQL execution time exceeded".into());
    }
    Ok(rows)
}

fn validate_scope(scope: &IngestSparqlScope) -> Result<(), String> {
    validate_slug("tenant_id", &scope.tenant_id, 128)?;
    validate_slug("site_id", &scope.site_id, 128)?;
    validate_slug("provider_instance_id", &scope.provider_instance_id, 128)?;
    if scope.authorized_graph.is_empty() || scope.authorized_graph.len() > 512 {
        return Err("malformed authorized graph IRI".into());
    }
    if scope.max_rows == 0 || scope.max_rows > MAX_ROWS {
        return Err(format!("max_rows must be 1..={MAX_ROWS}"));
    }
    if scope.timeout.is_zero() || scope.timeout > MAX_TIMEOUT {
        return Err("SPARQL timeout out of range".into());
    }
    Ok(())
}

fn select_query(graph: &str, limit: usize) -> Result<String, String> {
    NamedNode::new(graph).map_err(|e| format!("malformed authorized graph IRI: {e}"))?;
    if graph
        .chars()
        .any(|c| matches!(c, '<' | '>' | '"' | '{' | '}' | ' ' | '\\'))
    {
        return Err("malformed authorized graph IRI".into());
    }
    Ok(format!(
        r#"PREFIX ing: <urn:openfdd:ingest:v1:>
SELECT ?tenant ?site ?provider ?device ?point ?remotePoint ?role ?selection ?equipType ?sourceUnit ?kind ?canonicalUnit ?provisional ?quantity ?historyMode ?cadenceSecs ?heartbeatSecs ?connection
WHERE {{
  GRAPH <{graph}> {{
    ?binding ing:tenantRef ?tenant ;
             ing:siteRef ?site ;
             ing:providerInstanceId ?provider ;
             ing:providerInstanceRef ?connection ;
             ing:equipmentRef ?device ;
             ing:pointRef ?point ;
             ing:sourcePointId ?remotePoint ;
             ing:canonicalRole ?role ;
             ing:approvalState ?selection ;
             ing:equipType ?equipType .
    OPTIONAL {{ ?binding ing:sourceUnit ?sourceUnit }}
    OPTIONAL {{ ?binding ing:kind ?kind }}
    OPTIONAL {{ ?binding ing:canonicalUnit ?canonicalUnit }}
    OPTIONAL {{ ?binding ing:provisional ?provisional }}
    OPTIONAL {{ ?binding ing:quantity ?quantity }}
    OPTIONAL {{ ?binding ing:historyMode ?historyMode }}
    OPTIONAL {{ ?binding ing:cadenceSecs ?cadenceSecs }}
    OPTIONAL {{ ?binding ing:heartbeatSecs ?heartbeatSecs }}
  }}
}}
ORDER BY ?device ?point
LIMIT {limit}
"#
    ))
}

fn looks_like_trig(text: &str) -> bool {
    text.lines().any(|line| {
        let trimmed = line.trim();
        trimmed.ends_with('{') && (trimmed.starts_with('<') || trimmed.starts_with("GRAPH"))
    })
}

fn load_snapshot(text: &str, authorized: &NamedNode) -> Result<Store, String> {
    if looks_like_trig(text) {
        let store = Store::new().map_err(|e| format!("RDF store: {e}"))?;
        store
            .load_from_reader(RdfFormat::TriG, Cursor::new(text.as_bytes()))
            .map_err(|e| format!("invalid TriG snapshot: {e}"))?;
        return Ok(store);
    }
    let store = Store::new().map_err(|e| format!("RDF store: {e}"))?;
    store
        .load_from_reader(RdfFormat::Turtle, Cursor::new(text.as_bytes()))
        .map_err(|e| format!("invalid Turtle snapshot: {e}"))?;
    let mut default_quads = Vec::new();
    for quad in store.quads_for_pattern(None, None, None, Some(GraphNameRef::DefaultGraph)) {
        default_quads.push(quad.map_err(|e| format!("read default graph: {e}"))?);
    }
    for quad in default_quads {
        store
            .remove(&quad)
            .map_err(|e| format!("rehome snapshot: {e}"))?;
        let named = Quad::new(
            quad.subject,
            quad.predicate,
            quad.object,
            GraphName::NamedNode(authorized.clone()),
        );
        store
            .insert(&named)
            .map_err(|e| format!("rehome snapshot: {e}"))?;
    }
    Ok(store)
}

fn reject_executable_predicates(store: &Store) -> Result<(), String> {
    let mut values = String::new();
    for name in FORBIDDEN_PREDICATES {
        values.push_str("    (<");
        values.push_str(INGEST_NS);
        values.push_str(name);
        values.push_str(">)\n");
    }
    let query = format!(
        r#"ASK {{
  VALUES (?bad) {{
{values}  }}
  {{ ?s ?bad ?o }} UNION {{ GRAPH ?g {{ ?s ?bad ?o }} }}
}}"#
    );
    ensure_readonly_query(&query)?;
    let results = SparqlEvaluator::new()
        .parse_query(&query)
        .map_err(|e| format!("SPARQL parse error: {e}"))?
        .on_store(store)
        .execute()
        .map_err(|e| format!("SPARQL execution error: {e}"))?;
    match results {
        QueryResults::Boolean(true) => {
            Err("model graph must not carry executable URLs, verbs, headers, or credentials".into())
        }
        QueryResults::Boolean(false) => Ok(()),
        _ => Err("executable-predicate check returned an unexpected result".into()),
    }
}

struct TermVal {
    term_type: &'static str,
    value: String,
}

fn execute_select(
    store: &Store,
    query: &str,
    scope: &IngestSparqlScope,
) -> Result<Vec<IngestBindingRow>, String> {
    let results = SparqlEvaluator::new()
        .parse_query(query)
        .map_err(|e| format!("SPARQL parse error: {e}"))?
        .on_store(store)
        .execute()
        .map_err(|e| format!("SPARQL execution error: {e}"))?;
    let QueryResults::Solutions(solutions) = results else {
        return Err("ingest template must be a SELECT".into());
    };
    let mut rows = Vec::new();
    for solution in solutions {
        if rows.len() > scope.max_rows {
            break;
        }
        let solution = solution.map_err(|e| format!("SPARQL solution error: {e}"))?;
        let mut terms = BTreeMap::new();
        for (var, term) in solution.iter() {
            let binding = term_to_binding(term);
            terms.insert(
                var.as_str().to_string(),
                TermVal {
                    term_type: binding.term_type,
                    value: binding.value,
                },
            );
        }
        rows.push(row_from_terms(&terms, scope)?);
    }
    if rows.len() > scope.max_rows {
        return Err("truncated SPARQL export".into());
    }
    validate_binding_rows(&rows)?;
    Ok(rows)
}

fn required<'a>(terms: &'a BTreeMap<String, TermVal>, name: &str) -> Result<&'a TermVal, String> {
    terms
        .get(name)
        .filter(|t| !t.value.trim().is_empty())
        .ok_or_else(|| format!("SPARQL binding missing {name}"))
}

fn row_from_terms(
    terms: &BTreeMap<String, TermVal>,
    scope: &IngestSparqlScope,
) -> Result<IngestBindingRow, String> {
    let connection = required(terms, "connection")?;
    if connection.term_type != "uri" {
        return Err(
            "providerInstanceRef must be an IRI identifier, not an executable route".into(),
        );
    }
    let tenant = required(terms, "tenant")?.value.trim().to_string();
    let site = required(terms, "site")?.value.trim().to_string();
    let provider = required(terms, "provider")?.value.trim().to_string();
    if tenant != scope.tenant_id {
        return Err(format!(
            "wrong-tenant binding {tenant} for scope {}",
            scope.tenant_id
        ));
    }
    if site != scope.site_id {
        return Err(format!(
            "wrong-site binding {site} for scope {}",
            scope.site_id
        ));
    }
    if provider != scope.provider_instance_id {
        return Err(format!(
            "wrong-provider binding {provider} for scope {}",
            scope.provider_instance_id
        ));
    }
    let selection = selection_token(&required(terms, "selection")?.value);
    if !matches!(
        selection.as_str(),
        "approved" | "unresolved" | "ambiguous" | "excluded" | "disabled"
    ) {
        return Err(format!("malformed selection {selection}"));
    }
    let source_unit = optional_term(terms, "sourceUnit")?;
    let canonical_unit = optional_term(terms, "canonicalUnit")?;
    let row = IngestBindingRow {
        tenant_id: tenant,
        site_id: site,
        provider_instance_id: provider,
        equipment_id: required(terms, "device")?.value.trim().to_string(),
        equip_type: required(terms, "equipType")?.value.trim().to_string(),
        semantic_point_id: required(terms, "point")?.value.trim().to_string(),
        source_point_id: required(terms, "remotePoint")?.value.trim().to_string(),
        canonical_role: required(terms, "role")?.value.trim().to_string(),
        selection_status: selection,
        source_unit,
        canonical_unit,
        kind: optional_term(terms, "kind")?,
        provisional: matches!(
            terms.get("provisional").map(|t| t.value.as_str()),
            Some("true" | "1")
        ),
        quantity: optional_term(terms, "quantity")?,
        history_mode: optional_term(terms, "historyMode")?.map(|raw| selection_token(&raw)),
        cadence_secs: optional_seconds(terms, "cadenceSecs")?,
        heartbeat_secs: optional_seconds(terms, "heartbeatSecs")?,
    };
    validate_row_shape(&row)?;
    Ok(row)
}

fn optional_term(terms: &BTreeMap<String, TermVal>, name: &str) -> Result<Option<String>, String> {
    match terms.get(name) {
        None => Ok(None),
        Some(term) if term.value.trim().is_empty() => Err(format!("malformed {name}")),
        Some(term) => Ok(Some(term.value.trim().to_string())),
    }
}

/// A whole number of seconds. Anything else is malformed, never dropped.
fn optional_seconds(terms: &BTreeMap<String, TermVal>, name: &str) -> Result<Option<u64>, String> {
    let Some(raw) = optional_term(terms, name)? else {
        return Ok(None);
    };
    raw.parse::<u64>()
        .map(Some)
        .map_err(|_| format!("malformed {name}"))
}

/// Interval needs a cadence; COV may carry a heartbeat; neither number is
/// meaningful without its mode.
pub fn validate_expectation(row: &IngestBindingRow) -> Result<(), String> {
    if let Some(quantity) = row.quantity.as_deref() {
        validate_slug("quantity", quantity, 64)?;
    }
    match row.history_mode.as_deref() {
        None => {
            if row.cadence_secs.is_some() || row.heartbeat_secs.is_some() {
                return Err("cadence or heartbeat requires a history mode".into());
            }
        }
        Some("interval") => {
            match row.cadence_secs {
                Some(secs) if (1..=MAX_BINDING_CADENCE_SECS).contains(&secs) => {}
                Some(_) => return Err("malformed cadenceSecs".into()),
                None => return Err("interval history mode requires cadenceSecs".into()),
            }
            if row.heartbeat_secs.is_some() {
                return Err("heartbeatSecs applies only to cov history mode".into());
            }
        }
        Some("cov") => {
            if row.cadence_secs.is_some() {
                return Err("cadenceSecs applies only to interval history mode".into());
            }
            if let Some(secs) = row.heartbeat_secs {
                if !(1..=MAX_BINDING_HEARTBEAT_SECS).contains(&secs) {
                    return Err("malformed heartbeatSecs".into());
                }
            }
        }
        Some(other) => return Err(format!("malformed historyMode {other}")),
    }
    Ok(())
}

fn selection_token(raw: &str) -> String {
    raw.rsplit(['/', '#', ':'])
        .next()
        .unwrap_or(raw)
        .trim()
        .to_ascii_lowercase()
}

fn validate_row_shape(row: &IngestBindingRow) -> Result<(), String> {
    validate_slug("equipment_id", &row.equipment_id, 128)?;
    validate_slug("equip_type", &row.equip_type, 64)?;
    validate_slug("canonical_role", &row.canonical_role, 128)?;
    validate_semantic_point_id(&row.semantic_point_id)?;
    validate_source_point_id(&row.source_point_id)?;
    if let Some(unit) = row.source_unit.as_deref() {
        validate_unit(unit).map_err(|_| "malformed unit".to_string())?;
    }
    if let Some(unit) = row.canonical_unit.as_deref() {
        validate_unit(unit).map_err(|_| "malformed unit".to_string())?;
    }
    if row.semantic_point_id == row.source_point_id {
        return Err("semantic point id must be distinct from the provider source id".into());
    }
    validate_expectation(row)?;
    Ok(())
}

pub fn validate_binding_rows(rows: &[IngestBindingRow]) -> Result<(), String> {
    let mut semantic = BTreeSet::new();
    let mut sources = BTreeSet::new();
    let mut active_roles = BTreeSet::new();
    for row in rows {
        validate_row_shape(row)?;
        if !semantic.insert(row.semantic_point_id.clone()) {
            return Err(format!(
                "duplicate semantic point id {}",
                row.semantic_point_id
            ));
        }
        if !sources.insert(row.source_point_id.clone()) {
            return Err(format!("duplicate source point id {}", row.source_point_id));
        }
        let active = row.selection_status == "approved" && !row.provisional;
        if active && row.canonical_role.is_empty() {
            return Err("approved binding requires canonical_role".into());
        }
        if active {
            let key = format!("{}|{}", row.equipment_id, row.canonical_role);
            if !active_roles.insert(key) {
                return Err(format!(
                    "conflicting active role {} on {}",
                    row.canonical_role, row.equipment_id
                ));
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scope() -> IngestSparqlScope {
        IngestSparqlScope::new(
            "tenant-a",
            "site-a",
            "urn:openfdd:ingest:v1:graph/tenant-a/site-a",
            "nf-conn-a",
        )
    }

    fn binding(suffix: &str, role: &str, selection: &str, extra: &str) -> String {
        let extras = if extra.is_empty() {
            String::new()
        } else {
            format!(";\n  {extra}")
        };
        format!(
            r#"
<urn:openfdd:binding/{suffix}> ing:tenantRef "tenant-a" ;
  ing:siteRef "site-a" ;
  ing:providerInstanceId "nf-conn-a" ;
  ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-a> ;
  ing:equipmentRef "AHU_1" ;
  ing:pointRef "urn:openfdd:point:site-a:AHU_1:{suffix}" ;
  ing:sourcePointId "uuid-{suffix}" ;
  ing:canonicalRole "{role}" ;
  ing:approvalState "{selection}" ;
  ing:equipType "ahu"{extras} .
"#
        )
    }

    fn turtle(body: &str) -> String {
        format!("@prefix ing: <urn:openfdd:ingest:v1:> .\n{body}")
    }

    #[test]
    fn template_rejects_service_injection_in_graph_iri() {
        let mut bad = scope();
        bad.authorized_graph =
            "urn:openfdd:ok> } SERVICE <http://evil.example/sparql> { ?s ?p ?o".into();
        let err = compile_bindings_from_snapshot("", &bad).unwrap_err();
        assert!(err.contains("malformed authorized graph"), "{err}");
    }

    #[test]
    fn server_template_parses_without_service() {
        let query = select_query("urn:openfdd:ingest:v1:graph/tenant-a/site-a", 10).unwrap();
        ensure_readonly_query(&query).unwrap();
        assert!(!query.to_ascii_uppercase().contains("SERVICE"));
    }

    #[test]
    fn approved_binding_keeps_semantic_id_distinct_from_source() {
        let ttl = turtle(&binding(
            "sat",
            "sat",
            "approved",
            "ing:sourceUnit \"degF\"",
        ));
        let rows = compile_bindings_from_snapshot(&ttl, &scope()).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(
            rows[0].semantic_point_id,
            "urn:openfdd:point:site-a:AHU_1:sat"
        );
        assert_eq!(rows[0].source_point_id, "uuid-sat");
        assert_ne!(rows[0].semantic_point_id, rows[0].source_point_id);
        assert_eq!(rows[0].canonical_role, "sat");
        assert_eq!(rows[0].source_unit.as_deref(), Some("degF"));
    }

    #[test]
    fn display_name_does_not_invent_a_role() {
        let ttl = turtle(
            r#"
<urn:openfdd:binding/name-only> ing:tenantRef "tenant-a" ;
  ing:siteRef "site-a" ;
  ing:providerInstanceId "nf-conn-a" ;
  ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-a> ;
  ing:equipmentRef "AHU_1" ;
  ing:pointRef "urn:openfdd:point:site-a:AHU_1:zone" ;
  ing:sourcePointId "uuid-zone" ;
  ing:canonicalRole "zone-air-temp" ;
  ing:approvalState "approved" ;
  ing:equipType "ahu" ;
  ing:displayName "SAT sensor" .
"#,
        );
        let rows = compile_bindings_from_snapshot(&ttl, &scope()).unwrap();
        assert_eq!(rows[0].canonical_role, "zone-air-temp");
        assert!(!rows.iter().any(|r| r.canonical_role == "sat"));
    }

    #[test]
    fn wrong_site_binding_rejects_the_snapshot() {
        let ttl = turtle(
            r#"
<urn:openfdd:binding/other> ing:tenantRef "tenant-a" ;
  ing:siteRef "other-site" ;
  ing:providerInstanceId "nf-conn-a" ;
  ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-a> ;
  ing:equipmentRef "AHU_1" ;
  ing:pointRef "urn:openfdd:point:other:AHU_1:sat" ;
  ing:sourcePointId "uuid-other" ;
  ing:canonicalRole "sat" ;
  ing:approvalState "approved" ;
  ing:equipType "ahu" .
"#,
        );
        let err = compile_bindings_from_snapshot(&ttl, &scope()).unwrap_err();
        assert!(err.contains("wrong-site"), "{err}");
    }

    #[test]
    fn other_named_graph_is_not_visible() {
        let trig = r#"
@prefix ing: <urn:openfdd:ingest:v1:> .
<urn:openfdd:ingest:v1:graph/tenant-a/site-a> {
  <urn:openfdd:binding/sat> ing:tenantRef "tenant-a" ;
    ing:siteRef "site-a" ;
    ing:providerInstanceId "nf-conn-a" ;
    ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-a> ;
    ing:equipmentRef "AHU_1" ;
    ing:pointRef "urn:openfdd:point:site-a:AHU_1:sat" ;
    ing:sourcePointId "uuid-sat" ;
    ing:canonicalRole "sat" ;
    ing:approvalState "approved" ;
    ing:equipType "ahu" .
}
<urn:openfdd:ingest:v1:graph/tenant-b/site-b> {
  <urn:openfdd:binding/leak> ing:tenantRef "tenant-b" ;
    ing:siteRef "site-b" ;
    ing:providerInstanceId "nf-conn-b" ;
    ing:providerInstanceRef <urn:openfdd:provider-instance/nf-conn-b> ;
    ing:equipmentRef "AHU_9" ;
    ing:pointRef "urn:openfdd:point:site-b:AHU_9:sat" ;
    ing:sourcePointId "uuid-leak" ;
    ing:canonicalRole "sat" ;
    ing:approvalState "approved" ;
    ing:equipType "ahu" .
}
"#;
        let rows = compile_bindings_from_snapshot(trig, &scope()).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].source_point_id, "uuid-sat");
    }

    #[test]
    fn executable_http_verb_rejects_snapshot() {
        let ttl = turtle(&format!(
            "{}\n<urn:openfdd:binding/sat> ing:httpMethod \"POST\" .",
            binding("sat", "sat", "approved", "")
        ));
        let err = compile_bindings_from_snapshot(&ttl, &scope()).unwrap_err();
        assert!(err.contains("executable"), "{err}");
    }

    #[test]
    fn truncated_export_is_rejected() {
        let mut limited = scope();
        limited.max_rows = 1;
        let ttl = turtle(&format!(
            "{}\n{}",
            binding("sat", "sat", "approved", ""),
            binding("oat", "outside-air-temp", "approved", "")
        ));
        let err = compile_bindings_from_snapshot(&ttl, &limited).unwrap_err();
        assert!(err.contains("truncated"), "{err}");
    }

    #[test]
    fn conflicting_active_roles_reject() {
        let ttl = turtle(&format!(
            "{}\n{}",
            binding("sat-a", "sat", "approved", ""),
            binding("sat-b", "sat", "approved", "")
        ));
        let err = compile_bindings_from_snapshot(&ttl, &scope()).unwrap_err();
        assert!(err.contains("conflicting active role"), "{err}");
    }

    #[test]
    fn excluded_binding_does_not_become_a_second_approved_role() {
        let ttl = turtle(&format!(
            "{}\n{}",
            binding("sat", "sat", "approved", ""),
            binding("sat-x", "sat", "excluded", "")
        ));
        let rows = compile_bindings_from_snapshot(&ttl, &scope()).unwrap();
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().any(|r| r.selection_status == "excluded"));
    }

    #[test]
    fn duplicate_source_id_rejects() {
        let body = format!(
            "{}\n{}",
            binding("sat", "sat", "approved", ""),
            binding("sat", "zone-air-temp", "approved", "")
        );
        let err = compile_bindings_from_snapshot(&turtle(&body), &scope()).unwrap_err();
        assert!(err.contains("duplicate"), "{err}");
    }

    #[test]
    fn malformed_unit_rejects() {
        let ttl = turtle(&binding(
            "sat",
            "sat",
            "approved",
            "ing:sourceUnit \"degF; DROP\"",
        ));
        let err = compile_bindings_from_snapshot(&ttl, &scope()).unwrap_err();
        assert!(err.contains("malformed unit"), "{err}");
    }
}
