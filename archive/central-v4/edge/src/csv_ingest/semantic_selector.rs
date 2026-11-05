//! Versioned Haystack-filter selectors for internal FDD aliases.
//!
//! A selector is a bounded conjunction of pinned marker classes, optionally
//! scoped with `equipRef == @id`. It compiles to parsed SPARQL over IRIs from
//! the shared Haystack definition resolver. Zero matches is unavailable.
//! Several matches stay unresolved until an explicit point id or the
//! `equip_scope` topology policy leaves exactly one. Ranking, `LIMIT`, and
//! Axon or RDF text search are not selection policies.
//!
//! Haystack profile issues (function, kind, unit, history metadata) are stored
//! beside rule readiness. A custom role does not make a pressure point a
//! temperature input.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use super::haystack_defs::{self, defs, HAS_TAG_IRI, OFDD_NS};
use super::haystack_sparql_bindings::execute_readonly_on_overlay;
use super::model_overlay::{load_revision, load_ttl};

pub const SELECTOR_VERSION: &str = "haystack-filter-v1";
pub const SELECTOR_SCHEMA: &str = "ofdd_semantic_selector_v1";
pub const SELECTOR_FILE: &str = "semantic_selectors.json";
pub const DISCHARGE_AIR_TEMP_SENSOR: &str = "point and discharge and air and temp and sensor";
pub const DISCHARGE_AIR_TEMP_SETPOINT: &str = "point and discharge and air and temp and sp";
const TOPOLOGY_EQUIP_SCOPE: &str = "equip_scope";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExpectedQuantity {
    Temperature,
    TemperatureDelta,
    Pressure,
    Airflow,
    Percent,
    Boolean,
    Str,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExpectedKind {
    Number,
    Bool,
    Str,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "policy", rename_all = "snake_case")]
pub enum ApprovalPolicy {
    UniqueCandidate,
    Explicit { point_id: String },
    Topology { name: String },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AliasRequest {
    pub alias: String,
    pub equipment_id: String,
    pub filter: String,
    pub quantity: ExpectedQuantity,
    pub kind: ExpectedKind,
    pub optional: bool,
    pub approval: ApprovalPolicy,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnitConversion {
    pub quantity: String,
    pub source_unit: String,
    pub canonical_unit: String,
    pub conversion: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AliasBinding {
    pub alias: String,
    pub equipment_id: String,
    pub selector: String,
    pub selector_version: String,
    pub candidate_ids: Vec<String>,
    pub approval_policy: String,
    pub selected_external_key: Option<String>,
    pub quantity: String,
    pub unit_conversion: Option<UnitConversion>,
    pub model_revision: u64,
    pub outcome: String,
    pub readiness: String,
    pub profile_status: String,
    pub profile_issues: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct SelectorFile {
    schema: String,
    building_id: String,
    model_revision: u64,
    bindings: Vec<AliasBinding>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CandidateFact {
    pub point_id: String,
    pub external_key: Option<String>,
    pub equipment_id: Option<String>,
    pub unit: Option<String>,
    pub kind: Option<String>,
    pub tz: Option<String>,
    pub his_mode: Option<String>,
    pub enum_value: Option<String>,
    pub his: bool,
    pub functions: BTreeSet<String>,
    pub markers: BTreeSet<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ParsedFilter {
    markers: Vec<String>,
    equip_ref: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompiledFilter {
    pub sparql: String,
    pub equip_ref: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum UnitClass {
    Temperature,
    TemperatureDelta,
    Pressure,
    Airflow,
    Percent,
    Fraction,
    Unknown,
}

/// Discharge sensor and setpoint selectors for each equipment id.
/// Absence is optional: a VAV with no discharge point is not a failed AHU rule.
pub fn optional_discharge_selectors<S: AsRef<str>>(equipment_ids: &[S]) -> Vec<AliasRequest> {
    let mut ids: Vec<&str> = equipment_ids.iter().map(AsRef::as_ref).collect();
    ids.sort_unstable();
    ids.dedup();
    let mut out = Vec::with_capacity(ids.len().saturating_mul(2));
    for id in ids {
        if !valid_scope_id(id) {
            continue;
        }
        out.push(discharge_request(id, "sat", DISCHARGE_AIR_TEMP_SENSOR));
        out.push(discharge_request(id, "sat_sp", DISCHARGE_AIR_TEMP_SETPOINT));
    }
    out
}

fn discharge_request(equipment_id: &str, alias: &str, filter: &str) -> AliasRequest {
    AliasRequest {
        alias: alias.to_string(),
        equipment_id: equipment_id.to_string(),
        filter: filter.to_string(),
        quantity: ExpectedQuantity::Temperature,
        kind: ExpectedKind::Number,
        optional: true,
        approval: ApprovalPolicy::UniqueCandidate,
    }
}

pub fn compile_supported_filter(filter: &str) -> Result<CompiledFilter, String> {
    let parsed = parse_filter(filter)?;
    let point_iri = class_iri("point")?;
    let mut body = vec![format!("  ?point a <{point_iri}> .")];
    for marker in &parsed.markers {
        if marker == "point" {
            continue;
        }
        let iri = class_iri(marker)?;
        body.push(format!("  ?point <{HAS_TAG_IRI}> <{iri}> ."));
    }
    let unit_iri = value_iri("unit")?;
    let kind_iri = value_iri("kind")?;
    let tz_iri = value_iri("tz")?;
    let his_mode_iri = value_iri("hisMode")?;
    let enum_iri = value_iri("enum")?;
    let equip_ref_iri = value_iri("equipRef")?;
    body.push(format!("  ?point <{OFDD_NS}pointId> ?pointId ."));
    body.push(format!(
        "  ?point <{equip_ref_iri}> ?equip .\n  ?equip <{OFDD_NS}equipmentId> ?equipId ."
    ));
    body.push(format!(
        "  OPTIONAL {{ ?point <{OFDD_NS}openfddKey> ?externalKey }}"
    ));
    body.push(format!("  OPTIONAL {{ ?point <{unit_iri}> ?unit }}"));
    body.push(format!("  OPTIONAL {{ ?point <{kind_iri}> ?kind }}"));
    body.push(format!("  OPTIONAL {{ ?point <{tz_iri}> ?tz }}"));
    body.push(format!("  OPTIONAL {{ ?point <{his_mode_iri}> ?hisMode }}"));
    body.push(format!("  OPTIONAL {{ ?point <{enum_iri}> ?enum }}"));
    // One optional binding per function. A free `?tag` join multiplies rows and
    // can truncate a unique point into a false incomplete result.
    for symbol in ["sensor", "cmd", "sp", "synthetic", "his"] {
        let iri = class_iri(symbol)?;
        let var = function_var(symbol);
        body.push(format!(
            "  OPTIONAL {{ ?point <{HAS_TAG_IRI}> <{iri}> . BIND(\"{symbol}\" AS ?{var}) }}"
        ));
    }
    let select = [
        "?pointId",
        "?externalKey",
        "?unit",
        "?kind",
        "?tz",
        "?hisMode",
        "?enum",
        "?equipId",
        "?fnSensor",
        "?fnCmd",
        "?fnSp",
        "?fnSynthetic",
        "?fnHis",
    ]
    .join(" ");
    let sparql = format!("SELECT DISTINCT {select} WHERE {{\n{}\n}}", body.join("\n"));
    if sparql_is_unbounded_search(&sparql) {
        return Err("compiled selector left the supported SPARQL subset".into());
    }
    Ok(CompiledFilter {
        sparql,
        equip_ref: parsed.equip_ref,
    })
}

fn function_var(symbol: &str) -> String {
    let mut name = String::from("fn");
    let mut chars = symbol.chars();
    if let Some(first) = chars.next() {
        name.extend(first.to_uppercase());
        name.push_str(chars.as_str());
    }
    name
}

/// Restrict a compiled filter to one exact equipment id.
///
/// The id is checked against the exact-id alphabet before it becomes a SPARQL
/// literal. The query has no LIMIT and does not rank the matches.
fn query_for_equipment(compiled: &CompiledFilter, equipment_id: &str) -> Result<String, String> {
    let literal = sparql_exact_literal(equipment_id)?;
    let scoped = compiled.sparql.replacen(
        "WHERE {",
        &format!("WHERE {{\n  VALUES ?equipId {{ {literal} }}"),
        1,
    );
    if scoped == compiled.sparql {
        return Err("compiled selector has no query body".into());
    }
    if sparql_is_unbounded_search(&scoped) {
        return Err("scoped selector left the supported SPARQL subset".into());
    }
    Ok(scoped)
}

fn sparql_exact_literal(id: &str) -> Result<String, String> {
    if !valid_scope_id(id) {
        return Err("selector scope id is not an exact equipment id".into());
    }
    Ok(format!("\"{id}\""))
}

fn sparql_is_unbounded_search(sparql: &str) -> bool {
    let upper = sparql.to_ascii_uppercase();
    upper.contains("LIMIT")
        || upper.contains("ORDER BY")
        || upper.contains("REGEX")
        || upper.contains("CONTAINS")
        || upper.contains("SERVICE")
        || upper.contains("UNION")
}

fn class_iri(symbol: &str) -> Result<String, String> {
    match haystack_defs::resolve_published_tag(symbol) {
        haystack_defs::TagVerdict::Marker { iri, .. } => Ok(iri),
        _ => Err(format!("selector marker {symbol} is not a pinned class")),
    }
}

fn value_iri(symbol: &str) -> Result<String, String> {
    defs()
        .resolve(symbol)
        .filter(|def| def.is_value_property || def.is_ref)
        .map(|def| def.iri.clone())
        .ok_or_else(|| format!("selector value {symbol} is not a pinned property"))
}

fn parse_filter(filter: &str) -> Result<ParsedFilter, String> {
    let normalized = filter.split_whitespace().collect::<Vec<_>>().join(" ");
    if normalized.is_empty() || normalized.len() > 512 {
        return Err("selector filter is empty or too long".into());
    }
    if normalized.chars().any(|c| {
        matches!(
            c,
            '(' | ')' | '{' | '}' | '<' | '>' | '*' | '|' | '?' | ';' | ','
        )
    }) {
        return Err("selector filter is outside the supported conjunction subset".into());
    }
    let tokens: Vec<&str> = normalized.split(' ').collect();
    for token in &tokens {
        if banned_token(token) {
            return Err("selector filter is outside the supported conjunction subset".into());
        }
    }
    let mut markers = Vec::new();
    let mut equip_ref = None;
    for part in normalized.split(" and ") {
        let part = part.trim();
        if part.is_empty() || part == "and" {
            return Err("selector filter has an empty conjunction term".into());
        }
        if part.contains("==") {
            let id = parse_equip_ref(part)?;
            if equip_ref.is_some() {
                return Err("selector filter has more than one equipRef".into());
            }
            equip_ref = Some(id);
            continue;
        }
        if !valid_marker_token(part) {
            return Err("selector filter has a term that is not a marker".into());
        }
        class_iri(part)?;
        if !markers.contains(&part.to_string()) {
            markers.push(part.to_string());
        }
    }
    if !markers.iter().any(|m| m == "point") {
        return Err("selector filter requires the point marker".into());
    }
    if markers.len() < 2 {
        return Err("selector filter needs a point and a function or phenomenon marker".into());
    }
    Ok(ParsedFilter { markers, equip_ref })
}

fn banned_token(token: &str) -> bool {
    matches!(
        token.to_ascii_lowercase().as_str(),
        "or" | "not"
            | "readall"
            | "regex"
            | "contains"
            | "limit"
            | "select"
            | "union"
            | "service"
            | "ask"
            | "construct"
            | "insert"
            | "delete"
            | "where"
            | "filter"
            | "optional"
            | "bind"
            | "values"
            | "graph"
            | "axon"
    )
}

fn parse_equip_ref(part: &str) -> Result<String, String> {
    let (pred, raw_id) = part
        .split_once("==")
        .ok_or_else(|| "selector equality is not supported".to_string())?;
    if pred.trim() != "equipRef" {
        return Err("only equipRef equality is supported in a selector".into());
    }
    let id = raw_id
        .trim()
        .strip_prefix('@')
        .ok_or_else(|| "equipRef equality requires @id".to_string())?
        .trim();
    if !valid_scope_id(id) {
        return Err("equipRef id is not an exact equipment id".into());
    }
    Ok(id.to_string())
}

fn valid_marker_token(token: &str) -> bool {
    let mut chars = token.chars();
    match chars.next() {
        Some(c) if c.is_ascii_alphabetic() => {}
        _ => return false,
    }
    token.len() <= 64 && token.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

fn valid_scope_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
}

fn valid_alias(alias: &str) -> bool {
    let mut chars = alias.chars();
    match chars.next() {
        Some(c) if c.is_ascii_lowercase() => {}
        _ => return false,
    }
    alias.len() <= 64
        && alias
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

pub fn facts_from_rows(rows: &[Value]) -> Vec<CandidateFact> {
    let mut grouped: BTreeMap<String, CandidateFact> = BTreeMap::new();
    for row in rows {
        let Some(point_id) = term_lex(row, "pointId") else {
            continue;
        };
        let entry = grouped
            .entry(point_id.clone())
            .or_insert_with(|| CandidateFact {
                point_id,
                external_key: None,
                equipment_id: None,
                unit: None,
                kind: None,
                tz: None,
                his_mode: None,
                enum_value: None,
                his: false,
                functions: BTreeSet::new(),
                markers: BTreeSet::new(),
            });
        if entry.external_key.is_none() {
            entry.external_key = term_lex(row, "externalKey");
        }
        if entry.equipment_id.is_none() {
            entry.equipment_id = term_lex(row, "equipId");
        }
        if entry.unit.is_none() {
            entry.unit = term_lex(row, "unit");
        }
        if entry.kind.is_none() {
            entry.kind = term_lex(row, "kind");
        }
        if entry.tz.is_none() {
            entry.tz = term_lex(row, "tz");
        }
        if entry.his_mode.is_none() {
            entry.his_mode = term_lex(row, "hisMode");
        }
        if entry.enum_value.is_none() {
            entry.enum_value = term_lex(row, "enum");
        }
        for symbol in ["sensor", "cmd", "sp", "synthetic"] {
            if term_lex(row, &function_var(symbol)).as_deref() == Some(symbol) {
                entry.functions.insert(symbol.to_string());
                entry.markers.insert(symbol.to_string());
            }
        }
        if term_lex(row, &function_var("his")).as_deref() == Some("his") {
            entry.his = true;
            entry.markers.insert("his".to_string());
        }
    }
    grouped.into_values().collect()
}

fn term_lex(row: &Value, name: &str) -> Option<String> {
    let cell = row.get(name)?;
    let raw = if let Some(text) = cell.as_str() {
        text
    } else {
        cell.get("value").and_then(Value::as_str)?
    };
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

pub fn profile_issues(fact: &CandidateFact) -> (String, Vec<String>) {
    let mut issues = Vec::new();
    match fact.functions.len() {
        0 => issues.push("missing_function".to_string()),
        1 => {}
        _ => issues.push("mixed_function".to_string()),
    }
    match fact
        .kind
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        None => issues.push("missing_kind".to_string()),
        Some("Number" | "Bool" | "Str") => {}
        Some(_) => issues.push("incompatible_kind".to_string()),
    }
    if fact.kind.as_deref() == Some("Number") {
        match fact
            .unit
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            None => issues.push("missing_unit".to_string()),
            Some(unit) if classify_unit(unit) == UnitClass::Unknown => {
                issues.push("unknown_unit".to_string());
            }
            Some(_) => {}
        }
    }
    if fact.his
        && fact
            .tz
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .is_none()
    {
        issues.push("his_missing_tz".to_string());
    }
    if fact.his
        && fact
            .his_mode
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .is_none()
    {
        issues.push("his_missing_mode".to_string());
    }
    let status = if issues
        .iter()
        .any(|issue| issue == "mixed_function" || issue == "incompatible_kind")
    {
        "invalid"
    } else if issues.is_empty() {
        "valid"
    } else {
        "incomplete"
    };
    (status.to_string(), issues)
}

pub fn decide(
    request: &AliasRequest,
    facts: &[CandidateFact],
    truncated: bool,
    model_revision: u64,
) -> AliasBinding {
    let policy = policy_label(&request.approval);
    let quantity = quantity_name(request.quantity).to_string();
    let base = |outcome: &str, readiness: &str| AliasBinding {
        alias: request.alias.clone(),
        equipment_id: request.equipment_id.clone(),
        selector: request.filter.clone(),
        selector_version: SELECTOR_VERSION.to_string(),
        candidate_ids: Vec::new(),
        approval_policy: policy.clone(),
        selected_external_key: None,
        quantity: quantity.clone(),
        unit_conversion: None,
        model_revision,
        outcome: outcome.to_string(),
        readiness: readiness.to_string(),
        profile_status: "not_applicable".to_string(),
        profile_issues: Vec::new(),
    };
    if !valid_alias(&request.alias) || !valid_scope_id(&request.equipment_id) {
        return base("schema_invalid", "schema_invalid");
    }
    if let ApprovalPolicy::Topology { name } = &request.approval {
        if name != TOPOLOGY_EQUIP_SCOPE {
            return base("schema_invalid", "schema_invalid");
        }
    }
    if let ApprovalPolicy::Explicit { point_id } = &request.approval {
        if !valid_scope_id(point_id) {
            return base("schema_invalid", "schema_invalid");
        }
    }
    if truncated {
        let mut binding = base("incomplete_candidates", "model_incomplete");
        binding.profile_status = "not_applicable".to_string();
        return binding;
    }
    let mut scoped: Vec<&CandidateFact> = facts
        .iter()
        .filter(|fact| fact.equipment_id.as_deref() == Some(request.equipment_id.as_str()))
        .collect();
    scoped.sort_by(|a, b| a.point_id.cmp(&b.point_id));
    scoped.dedup_by(|a, b| a.point_id == b.point_id);
    let candidate_ids: Vec<String> = scoped.iter().map(|fact| fact.point_id.clone()).collect();
    let chosen = match &request.approval {
        ApprovalPolicy::Explicit { point_id } => scoped
            .iter()
            .copied()
            .find(|fact| fact.point_id == *point_id),
        ApprovalPolicy::UniqueCandidate | ApprovalPolicy::Topology { .. } => {
            if scoped.len() == 1 {
                scoped.first().copied()
            } else {
                None
            }
        }
    };
    if scoped.is_empty() {
        let readiness = if request.optional {
            "not_evaluated"
        } else {
            "rule_unavailable"
        };
        let mut binding = base("unavailable", readiness);
        binding.candidate_ids = candidate_ids;
        return binding;
    }
    let Some(fact) = chosen else {
        let mut binding = base("needs_approval", "rule_unavailable");
        binding.candidate_ids = candidate_ids;
        return binding;
    };
    let (profile_status, profile_issues) = profile_issues(fact);
    let conversion = fact.unit.as_deref().and_then(conversion_for);
    let (outcome, readiness, keep_key) = selection_outcome(request, fact);
    AliasBinding {
        alias: request.alias.clone(),
        equipment_id: request.equipment_id.clone(),
        selector: request.filter.clone(),
        selector_version: SELECTOR_VERSION.to_string(),
        candidate_ids,
        approval_policy: policy,
        selected_external_key: if keep_key {
            fact.external_key.clone()
        } else {
            None
        },
        quantity,
        unit_conversion: conversion,
        model_revision,
        outcome,
        readiness,
        profile_status,
        profile_issues,
    }
}

fn selection_outcome(request: &AliasRequest, fact: &CandidateFact) -> (String, String, bool) {
    if fact.functions.len() > 1 {
        return ("mixed_function".into(), "schema_invalid".into(), true);
    }
    let kind = fact
        .kind
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let expected_kind = match request.kind {
        ExpectedKind::Number => "Number",
        ExpectedKind::Bool => "Bool",
        ExpectedKind::Str => "Str",
    };
    match kind {
        None => return ("missing_kind".into(), "model_incomplete".into(), true),
        Some(actual) if actual != expected_kind => {
            return ("incompatible_kind".into(), "rule_unavailable".into(), true);
        }
        Some(_) => {}
    }
    if request.kind != ExpectedKind::Number {
        return ("selected".into(), "runnable".into(), true);
    }
    let Some(unit) = fact
        .unit
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    else {
        return ("missing_unit".into(), "model_incomplete".into(), true);
    };
    let class = classify_unit(unit);
    if class == UnitClass::Unknown {
        return ("unknown_unit".into(), "rule_unavailable".into(), true);
    }
    if !quantity_matches(request.quantity, class) {
        return ("wrong_quantity".into(), "rule_unavailable".into(), true);
    }
    ("selected".into(), "runnable".into(), true)
}

fn quantity_matches(expected: ExpectedQuantity, class: UnitClass) -> bool {
    matches!(
        (expected, class),
        (ExpectedQuantity::Temperature, UnitClass::Temperature)
            | (
                ExpectedQuantity::TemperatureDelta,
                UnitClass::TemperatureDelta
            )
            | (ExpectedQuantity::Pressure, UnitClass::Pressure)
            | (ExpectedQuantity::Airflow, UnitClass::Airflow)
            | (
                ExpectedQuantity::Percent,
                UnitClass::Percent | UnitClass::Fraction
            )
    )
}

fn conversion_for(unit: &str) -> Option<UnitConversion> {
    let class = classify_unit(unit);
    let (quantity, canonical, conversion) = match class {
        UnitClass::Temperature => {
            let folded = fold_unit(unit);
            if matches!(folded.as_str(), "c" | "degc" | "celsius") {
                ("temperature", "°F", "celsius_to_fahrenheit")
            } else {
                ("temperature", "°F", "identity")
            }
        }
        UnitClass::TemperatureDelta => ("temperature_delta", "Δ°F", "identity"),
        UnitClass::Pressure => ("pressure", unit, "identity"),
        UnitClass::Airflow => ("airflow", unit, "identity"),
        UnitClass::Percent => ("percent", "%", "identity"),
        UnitClass::Fraction => ("percent", "%", "fraction_to_percent"),
        UnitClass::Unknown => return None,
    };
    Some(UnitConversion {
        quantity: quantity.to_string(),
        source_unit: unit.to_string(),
        canonical_unit: canonical.to_string(),
        conversion: conversion.to_string(),
    })
}

fn classify_unit(unit: &str) -> UnitClass {
    match fold_unit(unit).as_str() {
        "f" | "degf" | "fahrenheit" => UnitClass::Temperature,
        "c" | "degc" | "celsius" => UnitClass::Temperature,
        "deltaf" | "df" | "deltac" | "dc" => UnitClass::TemperatureDelta,
        "inh2o" | "inwg" | "psi" | "pa" | "kpa" | "bar" => UnitClass::Pressure,
        "cfm" => UnitClass::Airflow,
        "%" | "percent" | "pct" => UnitClass::Percent,
        "fraction" => UnitClass::Fraction,
        _ => UnitClass::Unknown,
    }
}

fn fold_unit(unit: &str) -> String {
    unit.trim()
        .chars()
        .filter_map(|c| match c {
            '₂' => Some('2'),
            '°' | '_' | '-' | ' ' => None,
            'Δ' | 'δ' => Some('d'),
            other => Some(other.to_ascii_lowercase()),
        })
        .collect()
}

fn quantity_name(quantity: ExpectedQuantity) -> &'static str {
    match quantity {
        ExpectedQuantity::Temperature => "temperature",
        ExpectedQuantity::TemperatureDelta => "temperature_delta",
        ExpectedQuantity::Pressure => "pressure",
        ExpectedQuantity::Airflow => "airflow",
        ExpectedQuantity::Percent => "percent",
        ExpectedQuantity::Boolean => "boolean",
        ExpectedQuantity::Str => "str",
    }
}

fn policy_label(policy: &ApprovalPolicy) -> String {
    match policy {
        ApprovalPolicy::UniqueCandidate => "unique_candidate".to_string(),
        ApprovalPolicy::Explicit { point_id } => format!("explicit:{point_id}"),
        ApprovalPolicy::Topology { name } => format!("topology:{name}"),
    }
}

/// Evaluate selectors against the overlay and store one record per alias.
///
/// The overlay Turtle is not rewritten. A same-schema sidecar is replaced only
/// when the binding document changes. A different schema is left in place.
pub fn bind_semantic_aliases(
    building_root: &Path,
    building_id: &str,
    requests: &[AliasRequest],
) -> Result<Vec<AliasBinding>, String> {
    let model_revision = load_revision(building_root)?;
    let turtle = load_ttl(building_root)?;
    let mut bindings = Vec::with_capacity(requests.len());
    for request in requests {
        bindings.push(bind_one(building_id, request, &turtle, model_revision)?);
    }
    bindings.sort_by(|a, b| (&a.equipment_id, &a.alias).cmp(&(&b.equipment_id, &b.alias)));
    write_sidecar(building_root, building_id, model_revision, &bindings)?;
    Ok(bindings)
}

fn bind_one(
    building_id: &str,
    request: &AliasRequest,
    turtle: &str,
    model_revision: u64,
) -> Result<AliasBinding, String> {
    let compiled = match compile_supported_filter(&request.filter) {
        Ok(compiled) => compiled,
        Err(_) => {
            return Ok(invalid_binding(request, model_revision));
        }
    };
    if let Some(named) = compiled.equip_ref.as_deref() {
        if named != request.equipment_id {
            return Ok(invalid_binding(request, model_revision));
        }
    }
    let sparql = match query_for_equipment(&compiled, &request.equipment_id) {
        Ok(sparql) => sparql,
        Err(_) => return Ok(invalid_binding(request, model_revision)),
    };
    let executed = execute_readonly_on_overlay(building_id, &sparql, turtle)?;
    if executed.get("ok").and_then(Value::as_bool) != Some(true) {
        return Err("selector query did not succeed".into());
    }
    let Some(truncated) = executed.get("truncated").and_then(Value::as_bool) else {
        return Err("selector query did not report truncation".into());
    };
    let rows = executed
        .get("rows")
        .and_then(Value::as_array)
        .ok_or_else(|| "selector query did not return rows".to_string())?;
    let facts = facts_from_rows(rows);
    Ok(decide(request, &facts, truncated, model_revision))
}

fn invalid_binding(request: &AliasRequest, model_revision: u64) -> AliasBinding {
    AliasBinding {
        alias: request.alias.clone(),
        equipment_id: request.equipment_id.clone(),
        selector: request.filter.clone(),
        selector_version: SELECTOR_VERSION.to_string(),
        candidate_ids: Vec::new(),
        approval_policy: policy_label(&request.approval),
        selected_external_key: None,
        quantity: quantity_name(request.quantity).to_string(),
        unit_conversion: None,
        model_revision,
        outcome: "schema_invalid".to_string(),
        readiness: "schema_invalid".to_string(),
        profile_status: "not_applicable".to_string(),
        profile_issues: Vec::new(),
    }
}

fn selector_path(building_root: &Path) -> std::path::PathBuf {
    building_root.join(SELECTOR_FILE)
}

fn write_sidecar(
    building_root: &Path,
    building_id: &str,
    model_revision: u64,
    bindings: &[AliasBinding],
) -> Result<(), String> {
    let path = selector_path(building_root);
    if path.is_file() {
        let existing = fs::read_to_string(&path).map_err(|e| format!("read selectors: {e}"))?;
        if let Ok(parsed) = serde_json::from_str::<SelectorFile>(&existing) {
            if parsed.schema != SELECTOR_SCHEMA {
                return Err("refusing to replace a different semantic selector schema".into());
            }
        }
    }
    let document = SelectorFile {
        schema: SELECTOR_SCHEMA.to_string(),
        building_id: building_id.to_string(),
        model_revision,
        bindings: bindings.to_vec(),
    };
    let body =
        serde_json::to_string_pretty(&document).map_err(|e| format!("encode selectors: {e}"))?;
    let body = format!("{body}\n");
    if path.is_file() {
        let existing = fs::read_to_string(&path).map_err(|e| format!("read selectors: {e}"))?;
        if existing == body {
            return Ok(());
        }
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir selectors: {e}"))?;
    }
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, &body).map_err(|e| format!("write selectors: {e}"))?;
    fs::rename(&tmp, &path).map_err(|e| format!("publish selectors: {e}"))?;
    Ok(())
}

pub fn read_semantic_selectors(building_root: &Path) -> Result<Vec<AliasBinding>, String> {
    let path = selector_path(building_root);
    if !path.is_file() {
        return Ok(Vec::new());
    }
    let raw = fs::read_to_string(&path).map_err(|e| format!("read selectors: {e}"))?;
    let parsed: SelectorFile =
        serde_json::from_str(&raw).map_err(|e| format!("parse selectors: {e}"))?;
    if parsed.schema != SELECTOR_SCHEMA {
        return Err("unsupported semantic selector schema".into());
    }
    Ok(parsed.bindings)
}

/// A role name is not a quantity. Callers pass the point's kind, unit, and markers.
pub fn quantity_conflict(
    expected: ExpectedQuantity,
    kind: &str,
    unit: &str,
) -> Option<&'static str> {
    if kind != "Number" {
        return Some("incompatible_kind");
    }
    if unit.trim().is_empty() {
        return Some("missing_unit");
    }
    let class = classify_unit(unit);
    if class == UnitClass::Unknown {
        return Some("unknown_unit");
    }
    if !quantity_matches(expected, class) {
        return Some("wrong_quantity");
    }
    None
}

#[cfg(test)]
mod tests {
    use super::super::model_overlay::{self, sync_portal_inventory, PortalEquip, PortalPoint};
    use super::*;

    fn fact(
        id: &str,
        key: &str,
        unit: Option<&str>,
        kind: &str,
        functions: &[&str],
    ) -> CandidateFact {
        let mut funcs = BTreeSet::new();
        let mut markers = BTreeSet::new();
        for function in functions {
            funcs.insert((*function).to_string());
            markers.insert((*function).to_string());
        }
        CandidateFact {
            point_id: id.to_string(),
            external_key: Some(key.to_string()),
            equipment_id: Some("AHU_1".to_string()),
            unit: unit.map(str::to_string),
            kind: Some(kind.to_string()),
            tz: Some("America/Chicago".to_string()),
            his_mode: Some("cov".to_string()),
            enum_value: None,
            his: false,
            functions: funcs,
            markers,
        }
    }

    fn sat_request(optional: bool, approval: ApprovalPolicy) -> AliasRequest {
        AliasRequest {
            alias: "sat".into(),
            equipment_id: "AHU_1".into(),
            filter: DISCHARGE_AIR_TEMP_SENSOR.into(),
            quantity: ExpectedQuantity::Temperature,
            kind: ExpectedKind::Number,
            optional,
            approval,
        }
    }

    #[test]
    fn setpoint_and_sensor_filters_compile_to_different_parsed_queries() {
        let sensor = compile_supported_filter(DISCHARGE_AIR_TEMP_SENSOR).expect("sensor");
        let setpoint = compile_supported_filter(DISCHARGE_AIR_TEMP_SETPOINT).expect("setpoint");
        let sensor_iri = class_iri("sensor").expect("sensor iri");
        let sp_iri = class_iri("sp").expect("sp iri");
        let temp_iri = class_iri("temp").expect("temp iri");
        let required_text = |sparql: &str| {
            sparql
                .lines()
                .filter(|line| !line.contains("OPTIONAL"))
                .collect::<Vec<_>>()
                .join("\n")
        };
        let sensor_required = required_text(&sensor.sparql);
        let setpoint_required = required_text(&setpoint.sparql);
        assert!(sensor_required.contains(&sensor_iri));
        assert!(!sensor_required.contains(&sp_iri));
        assert!(setpoint_required.contains(&sp_iri));
        assert!(setpoint_required.contains(&temp_iri));
        assert!(!setpoint_required.contains(&sensor_iri));
        let scoped = query_for_equipment(&setpoint, "AHU_1").expect("scope");
        assert!(scoped.contains("VALUES ?equipId { \"AHU_1\" }"));
        assert!(query_for_equipment(&setpoint, "AHU_1\" UNION { ?s ?p ?o }").is_err());
        for query in [&sensor.sparql, &setpoint.sparql, &scoped] {
            let upper = query.to_ascii_uppercase();
            assert!(!upper.contains("LIMIT"));
            assert!(!upper.contains("ORDER BY"));
            assert!(!upper.contains("REGEX"));
            assert!(!query.contains("Discharge"));
        }
        assert!(compile_supported_filter("readAll(point and sensor)").is_err());
        assert!(compile_supported_filter("point and temp and regex(?dis, \"setpoint\")").is_err());
        assert!(compile_supported_filter("sensor").is_err());
        assert!(compile_supported_filter("point and discharge or sp").is_err());
    }

    #[test]
    fn zero_several_and_explicit_approval_do_not_rank() {
        let none = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[],
            false,
            4,
        );
        assert_eq!(none.outcome, "unavailable");
        assert_eq!(none.readiness, "rule_unavailable");
        assert!(none.selected_external_key.is_none());
        let optional = decide(
            &sat_request(true, ApprovalPolicy::UniqueCandidate),
            &[],
            false,
            4,
        );
        assert_eq!(optional.readiness, "not_evaluated");

        let first = fact("pt-a", "AHU_1.a", Some("°F"), "Number", &["sensor"]);
        let second = fact("pt-b", "AHU_1.b", Some("°F"), "Number", &["sensor"]);
        let many = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[second.clone(), first.clone()],
            false,
            4,
        );
        assert_eq!(many.outcome, "needs_approval");
        assert_eq!(
            many.candidate_ids,
            vec!["pt-a".to_string(), "pt-b".to_string()]
        );
        assert!(many.selected_external_key.is_none());
        assert_eq!(many.readiness, "rule_unavailable");

        let approved = decide(
            &sat_request(
                false,
                ApprovalPolicy::Explicit {
                    point_id: "pt-b".into(),
                },
            ),
            &[first.clone(), second.clone()],
            false,
            9,
        );
        assert_eq!(approved.outcome, "selected");
        assert_eq!(approved.selected_external_key.as_deref(), Some("AHU_1.b"));
        assert_eq!(approved.approval_policy, "explicit:pt-b");
        assert_eq!(approved.candidate_ids.len(), 2);
        assert_eq!(approved.model_revision, 9);

        let missing = decide(
            &sat_request(
                false,
                ApprovalPolicy::Explicit {
                    point_id: "pt-missing".into(),
                },
            ),
            &[first.clone(), second.clone()],
            false,
            4,
        );
        assert!(missing.selected_external_key.is_none());
        assert_eq!(missing.outcome, "needs_approval");

        let topology = decide(
            &sat_request(
                false,
                ApprovalPolicy::Topology {
                    name: "equip_scope".into(),
                },
            ),
            &[first.clone(), second],
            false,
            4,
        );
        assert!(topology.selected_external_key.is_none());
        assert_eq!(topology.approval_policy, "topology:equip_scope");

        let fuzzy = decide(
            &sat_request(
                false,
                ApprovalPolicy::Topology {
                    name: "fuzzy_rank".into(),
                },
            ),
            &[first],
            false,
            4,
        );
        assert_eq!(fuzzy.outcome, "schema_invalid");
        assert!(fuzzy.selected_external_key.is_none());
        assert!(fuzzy.candidate_ids.is_empty());
    }

    #[test]
    fn quantity_kind_and_unit_outcomes_stay_distinct() {
        let pressure = fact("pt-p", "AHU_1.sat", Some("inH₂O"), "Number", &["sensor"]);
        let wrong = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[pressure],
            false,
            1,
        );
        assert_eq!(wrong.outcome, "wrong_quantity");
        assert_eq!(wrong.readiness, "rule_unavailable");
        assert_eq!(wrong.selected_external_key.as_deref(), Some("AHU_1.sat"));
        assert_eq!(
            quantity_conflict(ExpectedQuantity::Temperature, "Number", "inH₂O"),
            Some("wrong_quantity")
        );

        let missing = fact("pt-m", "k", None, "Number", &["sensor"]);
        let missing_unit = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[missing],
            false,
            1,
        );
        assert_eq!(missing_unit.outcome, "missing_unit");
        assert_eq!(missing_unit.readiness, "model_incomplete");

        let unknown = fact("pt-u", "k", Some("widgets"), "Number", &["sensor"]);
        let unknown_unit = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[unknown],
            false,
            1,
        );
        assert_eq!(unknown_unit.outcome, "unknown_unit");
        assert_eq!(unknown_unit.readiness, "rule_unavailable");

        let mut mixed = fact("pt-x", "k", Some("°F"), "Number", &["sensor", "sp"]);
        mixed.markers.insert("temp".into());
        let mixed_fn = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[mixed],
            false,
            1,
        );
        assert_eq!(mixed_fn.outcome, "mixed_function");
        assert_eq!(mixed_fn.readiness, "schema_invalid");
        assert!(mixed_fn
            .profile_issues
            .iter()
            .any(|issue| issue == "mixed_function"));

        let bool_point = fact("pt-b", "fan", None, "Bool", &["sensor"]);
        let mut bool_request = sat_request(false, ApprovalPolicy::UniqueCandidate);
        bool_request.alias = "fan_status".into();
        bool_request.kind = ExpectedKind::Bool;
        bool_request.quantity = ExpectedQuantity::Boolean;
        let ready = decide(&bool_request, &[bool_point], false, 1);
        assert_eq!(ready.outcome, "selected");
        assert_eq!(ready.readiness, "runnable");

        let celsius = fact("pt-c", "sat", Some("°C"), "Number", &["sensor"]);
        let converted = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[celsius],
            false,
            3,
        );
        assert_eq!(converted.readiness, "runnable");
        let conversion = converted.unit_conversion.expect("conversion");
        assert_eq!(conversion.conversion, "celsius_to_fahrenheit");
        assert_eq!(conversion.canonical_unit, "°F");

        let delta = fact("pt-d", "k", Some("delta_F"), "Number", &["sensor"]);
        let delta_out = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[delta],
            false,
            1,
        );
        assert_eq!(delta_out.outcome, "wrong_quantity");

        let bare = fact("pt-n", "k", Some("°F"), "Number", &[]);
        let (status, issues) = profile_issues(&bare);
        assert_eq!(status, "incomplete");
        assert!(issues.iter().any(|issue| issue == "missing_function"));
        assert!(!issues.iter().any(|issue| issue == "mixed_function"));
    }

    #[test]
    fn truncated_results_are_not_a_limit_one_selection() {
        let only = fact("pt-a", "k", Some("°F"), "Number", &["sensor"]);
        let binding = decide(
            &sat_request(false, ApprovalPolicy::UniqueCandidate),
            &[only],
            true,
            2,
        );
        assert_eq!(binding.outcome, "incomplete_candidates");
        assert!(binding.selected_external_key.is_none());
        assert!(binding.candidate_ids.is_empty());
        assert_eq!(binding.readiness, "model_incomplete");
    }

    #[test]
    fn overlay_keeps_sensor_and_setpoint_apart_from_display_names() {
        let dir = tempfile::tempdir().expect("dir");
        let root = dir.path();
        let point =
            |id: &str, role: &str, unit: Option<&str>, kind: &str, markers: &[&str], dis: &str| {
                PortalPoint {
                    point_id: id.to_string(),
                    equipment_id: "AHU_1".to_string(),
                    openfdd_key: if role.is_empty() {
                        id.to_string()
                    } else {
                        format!("AHU_1.{role}")
                    },
                    role: role.to_string(),
                    dis: Some(dis.to_string()),
                    unit: unit.map(str::to_string),
                    markers: markers.iter().map(|m| (*m).to_string()).collect(),
                    kind: Some(kind.to_string()),
                    tz: Some("America/Chicago".into()),
                    his: Some(true),
                    his_mode: Some("cov".into()),
                    enum_value: if kind == "Str" {
                        Some("off,heat,cool".into())
                    } else {
                        None
                    },
                    ref_rel: if id == "pt-ref" {
                        Some("airRef".into())
                    } else {
                        None
                    },
                    ref_id: if id == "pt-ref" {
                        Some("AHU_2".into())
                    } else {
                        None
                    },
                }
            };
        sync_portal_inventory(
            root,
            "SITE_SEL",
            "nf:sel",
            &[PortalEquip {
                equipment_id: "AHU_1".into(),
                dis: Some("Handler".into()),
                kind: Some("ahu".into()),
                markers: vec!["equip".into(), "ahu".into()],
            }],
            &[
                point(
                    "pt-sensor",
                    "",
                    Some("°F"),
                    "Number",
                    &["discharge", "air", "temp", "sensor"],
                    "Discharge Setpoint",
                ),
                point(
                    "pt-sp",
                    "",
                    Some("°C"),
                    "Number",
                    &["discharge", "air", "temp", "sp"],
                    "Discharge Air Temp",
                ),
                point(
                    "pt-pressure",
                    "sat",
                    Some("inH₂O"),
                    "Number",
                    &["sensor", "pressure", "duct"],
                    "Supply Temp",
                ),
                point("pt-ref", "", None, "Bool", &["sensor"], "Fan"),
                point("pt-str", "", None, "Str", &["sensor"], "Mode"),
            ],
            true,
        )
        .expect("sync");
        let ttl = model_overlay::load_ttl(root).expect("ttl");
        assert!(ttl.contains("Number"));
        assert!(ttl.contains("Bool"));
        assert!(ttl.contains("Str"));
        assert!(ttl.contains("America/Chicago"));
        assert!(ttl.contains("cov"));
        assert!(ttl.contains("off,heat,cool"));
        assert!(ttl.contains("airRef") || ttl.contains("AHU_2"));
        assert!(!ttl.contains("ofdd:role \"\""));
        let requests = optional_discharge_selectors(&["AHU_1".to_string()]);
        let bindings = bind_semantic_aliases(root, "SITE_SEL", &requests).expect("bind");
        let sat = bindings.iter().find(|b| b.alias == "sat").expect("sat");
        let sp = bindings.iter().find(|b| b.alias == "sat_sp").expect("sp");
        assert_eq!(sat.selector, DISCHARGE_AIR_TEMP_SENSOR);
        assert_eq!(sat.selector_version, SELECTOR_VERSION);
        assert_eq!(sat.outcome, "selected");
        assert_eq!(sat.readiness, "runnable");
        assert_eq!(sat.selected_external_key.as_deref(), Some("pt-sensor"));
        assert_eq!(sat.candidate_ids, vec!["pt-sensor".to_string()]);
        assert!(!sat.candidate_ids.iter().any(|id| id == "pt-pressure"));
        assert_eq!(sp.selected_external_key.as_deref(), Some("pt-sp"));
        assert_eq!(sp.outcome, "selected");
        let conversion = sp.unit_conversion.as_ref().expect("c to f");
        assert_eq!(conversion.conversion, "celsius_to_fahrenheit");
        assert_eq!(sat.model_revision, load_revision(root).expect("rev"));
        let again = bind_semantic_aliases(root, "SITE_SEL", &requests).expect("rebind");
        assert_eq!(again, bindings);
    }
}
