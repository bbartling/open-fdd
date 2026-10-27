//! Soft-OPEN revisioned Turtle overlay store (BPS `model_crud` shape).
//!
//! Writable sidecar under the CSV building root. Pack RDF / Haystack projection
//! stay immutable. Soft-OPEN SPARQL queries load **pack ∪ overlay** and strip
//! tombstoned equip/point ids (see [`union_pack_overlay_for_sparql`]). Soft-OPEN ≠ FQ
//! (C2–C6 Haystack binding FQ remains #997/#1123).
//!
//! Surfaces:
//! - `PUT/GET /api/model/overlay` — whole-graph Turtle import
//! - `POST/DELETE /api/model/equip|point` — equip/point upsert + tombstones
//! - SPARQL query dataset — pack ∪ overlay (− tombstones)

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};

use chrono::Utc;
use once_cell::sync::Lazy;
use oxigraph::io::{RdfFormat, RdfSerializer};
use oxigraph::model::{GraphName, GraphNameRef, Literal, NamedNode, NamedOrBlankNode, Quad, Term};
use oxigraph::store::Store;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::haystack_defs::{
    self, TagDiagnostic, HAS_TAG_IRI, NATIVE_TAG_IRI, PHICT_BASE, PHIOT_BASE, PHSCIENCE_BASE,
    PH_BASE,
};
use super::haystack_projection::OFDD_NS;

pub const OVERLAY_TTL_FILE: &str = "model_overlay.ttl";
pub const OVERLAY_META_FILE: &str = "model_overlay.meta.json";
pub const OVERLAY_TMP_SUFFIX: &str = ".tmp";
/// BPS-compatible body size cap (chars).
pub const MAX_TTL_CHARS: usize = 2_000_000;
pub const WRITABLE_LAYER: &str = "model_overlay_ttl";
/// Engineer unit / quantity / primary-reference overrides (not `ofdd:portalSource` TTL).
pub const ENGINEER_POINT_OVERLAY_FILE: &str = "model_point_engineer_overlay.json";
pub const ENGINEER_POINT_OVERLAY_SCHEMA: &str = "openfdd_model_point_engineer_overlay_v1";

const RDF_TYPE: &str = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type";
const XSD_BOOLEAN: &str = "http://www.w3.org/2001/XMLSchema#boolean";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OverlayMeta {
    pub building_id: String,
    pub revision: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ttl_sha256_16: Option<String>,
}

fn ttl_path(building_root: &Path) -> PathBuf {
    building_root.join(OVERLAY_TTL_FILE)
}

fn meta_path(building_root: &Path) -> PathBuf {
    building_root.join(OVERLAY_META_FILE)
}

fn now_rfc3339_z() -> String {
    Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

fn sha256_16(ttl: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(ttl.as_bytes());
    let full = hasher.finalize();
    hex::encode(&full[..8])
}

fn nn(iri: &str) -> Result<NamedNode, String> {
    NamedNode::new(iri.to_string()).map_err(|e| format!("invalid IRI {iri:?}: {e}"))
}

fn ofdd(local: &str) -> String {
    format!("{OFDD_NS}{local}")
}

fn pinned(symbol: &str) -> Result<String, String> {
    haystack_defs::pinned_iri(symbol)
}

/// BPS `_safe_id` — alnum / `.` / `_` / `-`, max 128.
pub fn safe_id(raw: &str) -> String {
    let s: String = raw
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') {
                c
            } else {
                '_'
            }
        })
        .take(128)
        .collect();
    if s.is_empty() {
        "_".into()
    } else {
        s
    }
}

fn site_uri(building_id: &str) -> Result<NamedNode, String> {
    nn(&format!("urn:openfdd:site/{}#site", safe_id(building_id)))
}

fn equip_uri(building_id: &str, equipment_id: &str) -> Result<NamedNode, String> {
    nn(&format!(
        "urn:openfdd:site/{}#equip-{}",
        safe_id(building_id),
        safe_id(equipment_id)
    ))
}

fn point_uri(building_id: &str, point_id: &str) -> Result<NamedNode, String> {
    nn(&format!(
        "urn:openfdd:site/{}#point-{}",
        safe_id(building_id),
        safe_id(point_id)
    ))
}

fn tombstone_uri(building_id: &str, kind: &str, entity_id: &str) -> Result<NamedNode, String> {
    nn(&format!(
        "urn:openfdd:site/{}#tombstone-{}-{}",
        safe_id(building_id),
        kind,
        safe_id(entity_id)
    ))
}

/// Validate Turtle by loading into an ephemeral oxigraph store.
pub fn validate_turtle(ttl: &str) -> Result<usize, String> {
    if ttl.len() > MAX_TTL_CHARS {
        return Err(format!(
            "ttl too large ({} chars; max {MAX_TTL_CHARS})",
            ttl.len()
        ));
    }
    let store = Store::new().map_err(|e| format!("oxigraph store: {e}"))?;
    store
        .load_from_reader(RdfFormat::Turtle, Cursor::new(ttl.as_bytes()))
        .map_err(|e| format!("invalid turtle: {e}"))?;
    let count = store.len().map_err(|e| format!("oxigraph len: {e}"))?;
    Ok(count)
}

pub fn load_revision(building_root: &Path) -> Result<u64, String> {
    let path = meta_path(building_root);
    if !path.is_file() {
        return Ok(0);
    }
    let raw = fs::read_to_string(&path).map_err(|e| format!("read overlay meta: {e}"))?;
    let meta: OverlayMeta =
        serde_json::from_str(&raw).map_err(|e| format!("parse overlay meta: {e}"))?;
    Ok(meta.revision)
}

pub fn load_ttl(building_root: &Path) -> Result<String, String> {
    let path = ttl_path(building_root);
    if !path.is_file() {
        return Ok(String::new());
    }
    fs::read_to_string(&path).map_err(|e| format!("read overlay ttl: {e}"))
}

pub fn load_meta(building_root: &Path) -> Result<Option<OverlayMeta>, String> {
    let path = meta_path(building_root);
    if !path.is_file() {
        return Ok(None);
    }
    let raw = fs::read_to_string(&path).map_err(|e| format!("read overlay meta: {e}"))?;
    let meta: OverlayMeta =
        serde_json::from_str(&raw).map_err(|e| format!("parse overlay meta: {e}"))?;
    Ok(Some(meta))
}

fn load_overlay_store(building_root: &Path) -> Result<Store, String> {
    let store = Store::new().map_err(|e| format!("oxigraph store: {e}"))?;
    let ttl = load_ttl(building_root)?;
    if !ttl.trim().is_empty() {
        store
            .load_from_reader(RdfFormat::Turtle, Cursor::new(ttl.as_bytes()))
            .map_err(|e| format!("load overlay turtle: {e}"))?;
    }
    Ok(store)
}

fn serialize_store_ttl(store: &Store) -> Result<String, String> {
    let mut buf = Vec::new();
    let serializer = RdfSerializer::from_format(RdfFormat::Turtle)
        .with_prefix("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
        .map_err(|e| format!("prefix rdf: {e}"))?
        .with_prefix("ph", PH_BASE)
        .map_err(|e| format!("prefix ph: {e}"))?
        .with_prefix("phIoT", PHIOT_BASE)
        .map_err(|e| format!("prefix phIoT: {e}"))?
        .with_prefix("phScience", PHSCIENCE_BASE)
        .map_err(|e| format!("prefix phScience: {e}"))?
        .with_prefix("phIct", PHICT_BASE)
        .map_err(|e| format!("prefix phIct: {e}"))?
        .with_prefix("ofdd", OFDD_NS)
        .map_err(|e| format!("prefix ofdd: {e}"))?;
    store
        .dump_graph_to_writer(GraphNameRef::DefaultGraph, serializer, &mut buf)
        .map_err(|e| format!("turtle serialize: {e}"))?;
    String::from_utf8(buf).map_err(|e| format!("turtle utf8: {e}"))
}

fn insert_quad(store: &Store, s: &NamedNode, p: &str, o: Term) -> Result<(), String> {
    let pred = nn(p)?;
    store
        .insert(&Quad::new(
            NamedOrBlankNode::from(s.clone()),
            pred,
            o,
            GraphName::DefaultGraph,
        ))
        .map_err(|e| format!("insert quad: {e}"))
}

fn insert_type(store: &Store, s: &NamedNode, class_iri: &str) -> Result<(), String> {
    insert_quad(store, s, RDF_TYPE, Term::from(nn(class_iri)?))
}

fn insert_str(store: &Store, s: &NamedNode, pred: &str, value: &str) -> Result<(), String> {
    insert_quad(
        store,
        s,
        pred,
        Term::from(Literal::new_simple_literal(value)),
    )
}

fn insert_ref(store: &Store, s: &NamedNode, pred: &str, target: &NamedNode) -> Result<(), String> {
    insert_quad(store, s, pred, Term::from(target.clone()))
}

fn insert_bool_true(store: &Store, s: &NamedNode, pred: &str) -> Result<(), String> {
    let dt = nn(XSD_BOOLEAN)?;
    insert_quad(
        store,
        s,
        pred,
        Term::from(Literal::new_typed_literal("true", dt)),
    )
}

fn has_type(store: &Store, s: &NamedNode, class_iri: &str) -> Result<bool, String> {
    let pred = nn(RDF_TYPE)?;
    let class = nn(class_iri)?;
    let class_term = Term::from(class);
    match store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            Some((&pred).into()),
            Some((&class_term).into()),
            None,
        )
        .next()
    {
        Some(Ok(_)) => Ok(true),
        Some(Err(e)) => Err(format!("quads: {e}")),
        None => Ok(false),
    }
}

fn has_quad(store: &Store, s: &NamedNode, p: &str, o: &Term) -> Result<bool, String> {
    let pred = nn(p)?;
    match store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            Some((&pred).into()),
            Some(o.into()),
            None,
        )
        .next()
    {
        Some(Ok(_)) => Ok(true),
        Some(Err(e)) => Err(format!("quads: {e}")),
        None => Ok(false),
    }
}

fn remove_subject(store: &Store, s: &NamedNode) -> Result<(), String> {
    let quads: Vec<Quad> = store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            None,
            None,
            None,
        )
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("quads: {e}"))?;
    for q in quads {
        store.remove(&q).map_err(|e| format!("remove quad: {e}"))?;
    }
    Ok(())
}

fn set_str(store: &Store, s: &NamedNode, pred: &str, value: &str) -> Result<(), String> {
    let pred_nn = nn(pred)?;
    let existing: Vec<Quad> = store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            Some((&pred_nn).into()),
            None,
            None,
        )
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("quads: {e}"))?;
    for q in existing {
        store.remove(&q).map_err(|e| format!("remove quad: {e}"))?;
    }
    insert_str(store, s, pred, value)
}

fn remove_pred(store: &Store, s: &NamedNode, pred: &str) -> Result<(), String> {
    let pred_nn = nn(pred)?;
    let existing: Vec<Quad> = store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            Some((&pred_nn).into()),
            None,
            None,
        )
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("quads: {e}"))?;
    for q in existing {
        store.remove(&q).map_err(|e| format!("remove quad: {e}"))?;
    }
    Ok(())
}

fn read_literal(store: &Store, s: &NamedNode, pred: &str) -> Result<Option<String>, String> {
    let pred_nn = nn(pred)?;
    for quad in store.quads_for_pattern(
        Some(NamedOrBlankNode::from(s.clone()).as_ref()),
        Some((&pred_nn).into()),
        None,
        None,
    ) {
        let quad = quad.map_err(|e| format!("quads: {e}"))?;
        if let Term::Literal(lit) = quad.object {
            return Ok(Some(lit.value().to_string()));
        }
    }
    Ok(None)
}

fn write_point_metadata(
    store: &Store,
    building_id: &str,
    node: &NamedNode,
    pt: &PortalPoint,
) -> Result<(), String> {
    set_optional_str(store, node, &pinned("kind")?, pt.kind.as_deref())?;
    set_optional_str(store, node, &pinned("tz")?, pt.tz.as_deref())?;
    set_optional_str(store, node, &pinned("hisMode")?, pt.his_mode.as_deref())?;
    set_optional_str(store, node, &pinned("enum")?, pt.enum_value.as_deref())?;
    if let Some(previous) = read_literal(store, node, &ofdd("refRel"))? {
        if let haystack_defs::TagVerdict::Value {
            iri, is_ref: true, ..
        } = haystack_defs::resolve_published_tag(&previous)
        {
            remove_pred(store, node, &iri)?;
        }
    }
    let rel = pt
        .ref_rel
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    let id = pt
        .ref_id
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty());
    set_optional_str(store, node, &ofdd("refRel"), rel)?;
    set_optional_str(store, node, &ofdd("refId"), id)?;
    if let (Some(rel), Some(id)) = (rel, id) {
        if let haystack_defs::TagVerdict::Value {
            iri, is_ref: true, ..
        } = haystack_defs::resolve_published_tag(rel)
        {
            let target = equip_uri(building_id, id)?;
            set_ref(store, node, &iri, &target)?;
        }
    }
    Ok(())
}

fn set_ref(store: &Store, s: &NamedNode, pred: &str, target: &NamedNode) -> Result<(), String> {
    let pred_nn = nn(pred)?;
    let existing: Vec<Quad> = store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            Some((&pred_nn).into()),
            None,
            None,
        )
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("quads: {e}"))?;
    for q in existing {
        store.remove(&q).map_err(|e| format!("remove quad: {e}"))?;
    }
    insert_ref(store, s, pred, target)
}

fn find_subject_by_id_literal(
    store: &Store,
    pred_local: &str,
    id: &str,
) -> Result<Option<NamedNode>, String> {
    let pred = nn(&ofdd(pred_local))?;
    let lit = Term::from(Literal::new_simple_literal(id));
    for q in store.quads_for_pattern(None, Some((&pred).into()), Some((&lit).into()), None) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        if let NamedOrBlankNode::NamedNode(n) = q.subject {
            return Ok(Some(n));
        }
    }
    Ok(None)
}

fn ensure_site(store: &Store, building_id: &str) -> Result<NamedNode, String> {
    let site = site_uri(building_id)?;
    let site_class = pinned("site")?;
    if !has_type(store, &site, &site_class)? {
        insert_type(store, &site, &site_class)?;
        insert_str(store, &site, &ofdd("siteId"), building_id)?;
    }
    Ok(site)
}

fn ensure_equip(
    store: &Store,
    building_id: &str,
    equipment_id: &str,
    site: &NamedNode,
) -> Result<NamedNode, String> {
    let equip = equip_uri(building_id, equipment_id)?;
    let equip_class = pinned("equip")?;
    if !has_type(store, &equip, &equip_class)? {
        insert_type(store, &equip, &equip_class)?;
        insert_str(store, &equip, &ofdd("equipmentId"), equipment_id)?;
        let site_ref = pinned("siteRef")?;
        insert_ref(store, &equip, &site_ref, site)?;
        insert_bool_true(store, &equip, &ofdd("overlay"))?;
    }
    Ok(equip)
}

struct ResolvedWrite {
    iris: Vec<String>,
    native: Vec<String>,
    diagnostics: Vec<TagDiagnostic>,
}

fn resolve_write_markers(raw: &[String]) -> ResolvedWrite {
    let resolved = haystack_defs::resolve_marker_list(raw);
    let mut iris = Vec::with_capacity(resolved.markers.len() + resolved.extensions.len());
    for tag in resolved.markers {
        push_iri(&mut iris, tag.iri);
    }
    for tag in resolved.extensions {
        push_iri(&mut iris, tag.iri);
    }
    ResolvedWrite {
        iris,
        native: resolved.native,
        diagnostics: resolved.diagnostics,
    }
}

/// Internal equipment alias. A published class keeps its spelling; anything else
/// stays out of the Haystack libraries.
fn kind_class(kind: &str) -> (Option<String>, Option<TagDiagnostic>) {
    let symbol = kind.trim();
    if symbol.is_empty() {
        return (None, None);
    }
    match haystack_defs::resolve_published_tag(symbol) {
        haystack_defs::TagVerdict::Marker { iri, .. } => (Some(iri), None),
        haystack_defs::TagVerdict::Value { symbol, .. } => (
            None,
            Some(TagDiagnostic {
                symbol,
                outcome: "value_not_marker",
                detail: "equipment kind is not a marker class".into(),
            }),
        ),
        haystack_defs::TagVerdict::Extension { symbol, .. } => (
            None,
            Some(TagDiagnostic {
                symbol: format!("ext:{symbol}"),
                outcome: "kind_not_marker",
                detail: "equipment kind is an extension, not a pinned class".into(),
            }),
        ),
        haystack_defs::TagVerdict::Unknown { symbol }
        | haystack_defs::TagVerdict::Absent { symbol } => (
            None,
            Some(TagDiagnostic {
                symbol,
                outcome: "kind_not_marker",
                detail: "equipment kind is not a pinned marker class".into(),
            }),
        ),
    }
}

fn push_iri(iris: &mut Vec<String>, iri: String) {
    if !iris.contains(&iri) {
        iris.push(iri);
    }
}

fn to_portal_diags(entity_id: &str, diags: &[TagDiagnostic]) -> Vec<PortalTagDiagnostic> {
    diags
        .iter()
        .map(|diag| PortalTagDiagnostic {
            entity_id: entity_id.to_string(),
            symbol: diag.symbol.clone(),
            outcome: diag.outcome.to_string(),
        })
        .collect()
}

fn attach_tag_diagnostics(mut body: Value, diags: &[PortalTagDiagnostic]) -> Value {
    if let Some(obj) = body.as_object_mut() {
        let value = serde_json::to_value(diags).unwrap_or_else(|_| json!([]));
        obj.insert("tag_diagnostics".into(), value);
    }
    body
}

fn add_point_tombstone(store: &Store, building_id: &str, point_id: &str) -> Result<(), String> {
    let t = tombstone_uri(building_id, "point", point_id)?;
    remove_subject(store, &t)?;
    insert_type(store, &t, &ofdd("Tombstone"))?;
    insert_str(store, &t, &ofdd("excludesPointId"), point_id)?;
    insert_str(store, &t, &ofdd("siteId"), building_id)?;
    Ok(())
}

fn add_equip_tombstone(store: &Store, building_id: &str, equipment_id: &str) -> Result<(), String> {
    let t = tombstone_uri(building_id, "equip", equipment_id)?;
    remove_subject(store, &t)?;
    insert_type(store, &t, &ofdd("Tombstone"))?;
    insert_str(store, &t, &ofdd("excludesEquipmentId"), equipment_id)?;
    insert_str(store, &t, &ofdd("siteId"), building_id)?;
    Ok(())
}

/// List point / equipment ids excluded via overlay tombstones.
pub fn list_tombstones(building_root: &Path) -> Result<Value, String> {
    let store = load_overlay_store(building_root)?;
    let mut points = BTreeSet::new();
    let mut equipment = BTreeSet::new();
    let p_point = nn(&ofdd("excludesPointId"))?;
    let p_equip = nn(&ofdd("excludesEquipmentId"))?;
    for q in store.quads_for_pattern(None, Some((&p_point).into()), None, None) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        if let Term::Literal(lit) = q.object {
            points.insert(lit.value().to_string());
        }
    }
    for q in store.quads_for_pattern(None, Some((&p_equip).into()), None, None) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        if let Term::Literal(lit) = q.object {
            equipment.insert(lit.value().to_string());
        }
    }
    Ok(json!({
        "points": points.into_iter().collect::<Vec<_>>(),
        "equipment": equipment.into_iter().collect::<Vec<_>>(),
    }))
}

/// Replace overlay TTL with BPS-compatible dry_run + expected_revision CAS.
pub fn put_overlay_ttl(
    building_root: &Path,
    building_id: &str,
    ttl: &str,
    expected_revision: Option<u64>,
    dry_run: bool,
) -> Result<Value, Value> {
    put_overlay_ttl_noted(
        building_root,
        building_id,
        ttl,
        expected_revision,
        dry_run,
        "put_overlay_ttl",
    )
}

fn put_overlay_ttl_noted(
    building_root: &Path,
    building_id: &str,
    ttl: &str,
    expected_revision: Option<u64>,
    dry_run: bool,
    note: &str,
) -> Result<Value, Value> {
    let quad_count = validate_turtle(ttl).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    let current = load_revision(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    if let Some(want) = expected_revision {
        if want != current {
            return Err(json!({
                "ok": false,
                "conflict": true,
                "building_id": building_id,
                "site_id": building_id,
                "revision": current,
                "expected_revision": want,
                "error": "revision mismatch (reload overlay and retry)",
                "soft_open_neq_fq": true,
            }));
        }
    }

    let digest = sha256_16(ttl);
    let next_rev = current + 1;
    if dry_run {
        return Ok(json!({
            "ok": true,
            "dry_run": true,
            "building_id": building_id,
            "site_id": building_id,
            "revision": current,
            "would_revision": next_rev,
            "ttl_sha256_16": digest,
            "ttl_chars": ttl.len(),
            "quad_count": quad_count,
            "writable_layer": WRITABLE_LAYER,
            "soft_open_neq_fq": true,
            "note": note,
            "gaps": soft_open_gaps(),
        }));
    }

    fs::create_dir_all(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("create building root: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    let ttl_dest = ttl_path(building_root);
    let ttl_tmp = building_root.join(format!("{OVERLAY_TTL_FILE}{OVERLAY_TMP_SUFFIX}"));
    fs::write(&ttl_tmp, ttl.as_bytes()).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("write overlay ttl tmp: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    fs::rename(&ttl_tmp, &ttl_dest).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("publish overlay ttl: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    let meta = OverlayMeta {
        building_id: building_id.to_string(),
        revision: next_rev,
        updated_at: Some(now_rfc3339_z()),
        note: Some(note.to_string()),
        ttl_sha256_16: Some(digest.clone()),
    };
    let meta_dest = meta_path(building_root);
    let meta_tmp = building_root.join(format!("{OVERLAY_META_FILE}{OVERLAY_TMP_SUFFIX}"));
    let meta_json = serde_json::to_string_pretty(&meta).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("serialize overlay meta: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    fs::write(&meta_tmp, format!("{meta_json}\n")).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("write overlay meta tmp: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    fs::rename(&meta_tmp, &meta_dest).map_err(|e| {
        json!({
            "ok": false,
            "error": format!("publish overlay meta: {e}"),
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;

    Ok(json!({
        "ok": true,
        "dry_run": false,
        "building_id": building_id,
        "site_id": building_id,
        "revision": next_rev,
        "overlay": ttl_dest.display().to_string(),
        "ttl_sha256_16": digest,
        "ttl_chars": ttl.len(),
        "quad_count": quad_count,
        "writable_layer": WRITABLE_LAYER,
        "pack_immutable": true,
        "soft_open_neq_fq": true,
        "note": note,
        "gaps": soft_open_gaps(),
    }))
}

fn commit_store(
    building_root: &Path,
    building_id: &str,
    store: &Store,
    expected_revision: Option<u64>,
    dry_run: bool,
    note: &str,
) -> Result<Value, Value> {
    let ttl = serialize_store_ttl(store).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    put_overlay_ttl_noted(
        building_root,
        building_id,
        &ttl,
        expected_revision,
        dry_run,
        note,
    )
}

/// CAS / dry_run options shared by overlay mutate helpers.
#[derive(Debug, Clone, Copy, Default)]
pub struct OverlayCasOpts {
    pub expected_revision: Option<u64>,
    pub dry_run: bool,
}

/// Optional fields for equipment upsert.
#[derive(Debug, Clone, Copy)]
pub struct EquipUpsertFields<'a> {
    pub dis: Option<&'a str>,
    pub kind: Option<&'a str>,
    pub markers: &'a [String],
}

/// Optional fields for point upsert.
#[derive(Debug, Clone, Copy)]
pub struct PointUpsertFields<'a> {
    pub dis: Option<&'a str>,
    pub openfdd_key: Option<&'a str>,
    pub role: Option<&'a str>,
    pub markers: &'a [String],
    pub unit: Option<&'a str>,
    pub quantity: Option<&'a str>,
    pub primary_reference: Option<bool>,
}

/// One engineer override row keyed by provider `point_id`.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct EngineerPointOverlayEntry {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub unit: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub quantity: Option<String>,
    #[serde(default)]
    pub primary_reference: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct EngineerPointOverlayStore {
    pub schema: String,
    pub building_id: String,
    #[serde(default)]
    pub points: BTreeMap<String, EngineerPointOverlayEntry>,
}

fn engineer_overlay_path(building_root: &Path) -> PathBuf {
    building_root.join(ENGINEER_POINT_OVERLAY_FILE)
}

fn norm_unit_token(raw: &str) -> String {
    raw.trim()
        .to_ascii_lowercase()
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .collect()
}

#[derive(Debug, Deserialize)]
struct MetricQuantityDef {
    id: String,
    #[serde(default)]
    canonical_unit: Option<String>,
    #[serde(default)]
    pack_v1_unit: Option<String>,
    #[serde(default)]
    aliases: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct MetricUnitsContract {
    quantities: Vec<MetricQuantityDef>,
}

fn parse_metric_units_contract(raw: &str) -> MetricUnitsContract {
    match serde_json::from_str(raw) {
        Ok(contract) => contract,
        Err(err) => {
            panic!("sql/contract/metric_units.json is invalid: {err}");
        }
    }
}

static METRIC_UNITS: Lazy<MetricUnitsContract> = Lazy::new(|| {
    parse_metric_units_contract(include_str!("../../../sql/contract/metric_units.json"))
});

fn quantity_exists(quantity: &str) -> bool {
    let q = quantity.trim();
    METRIC_UNITS.quantities.iter().any(|entry| entry.id == q)
}

fn unit_tokens_for_quantity(quantity: &str) -> Vec<String> {
    let mut out = Vec::new();
    for entry in &METRIC_UNITS.quantities {
        if entry.id != quantity {
            continue;
        }
        for alias in &entry.aliases {
            out.push(norm_unit_token(alias));
        }
        if let Some(u) = entry.canonical_unit.as_deref() {
            out.push(norm_unit_token(u));
        }
        if let Some(u) = entry.pack_v1_unit.as_deref() {
            out.push(norm_unit_token(u));
        }
    }
    out.sort();
    out.dedup();
    out
}

/// Validate engineer `unit` against `sql/contract/metric_units.json` for the declared quantity.
pub fn validate_engineer_unit_quantity(unit: &str, quantity: &str) -> Result<(), String> {
    let unit = unit.trim();
    let quantity = quantity.trim();
    if unit.is_empty() {
        return Err("unit required when quantity is set".into());
    }
    if quantity.is_empty() {
        return Err("quantity required when unit is set".into());
    }
    if !quantity_exists(quantity) {
        return Err(format!("unknown quantity {quantity}"));
    }
    let token = norm_unit_token(unit);
    if token.is_empty() {
        return Err("malformed unit".into());
    }
    let allowed = unit_tokens_for_quantity(quantity);
    if unit.contains('%') && quantity == "relative_humidity" {
        return Ok(());
    }
    if allowed.contains(&token) {
        return Ok(());
    }
    Err(format!(
        "unit {unit:?} is incompatible with quantity {quantity}"
    ))
}

fn validate_engineer_patch(
    unit: Option<&str>,
    quantity: Option<&str>,
    primary_reference: Option<bool>,
) -> Result<(), String> {
    let has_unit = unit.map(str::trim).is_some_and(|u| !u.is_empty());
    let has_quantity = quantity.map(str::trim).is_some_and(|q| !q.is_empty());
    if has_unit || has_quantity {
        let u = unit.map(str::trim).filter(|s| !s.is_empty()).unwrap_or("");
        let q = quantity
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .unwrap_or("");
        validate_engineer_unit_quantity(u, q)?;
    }
    Ok(())
}

pub fn load_engineer_point_overlay(
    building_root: &Path,
) -> Result<EngineerPointOverlayStore, String> {
    let path = engineer_overlay_path(building_root);
    if !path.is_file() {
        return Ok(EngineerPointOverlayStore {
            schema: ENGINEER_POINT_OVERLAY_SCHEMA.to_string(),
            building_id: String::new(),
            points: BTreeMap::new(),
        });
    }
    let raw = fs::read_to_string(&path).map_err(|e| format!("read engineer overlay: {e}"))?;
    let store: EngineerPointOverlayStore =
        serde_json::from_str(&raw).map_err(|e| format!("parse engineer overlay: {e}"))?;
    if store.schema != ENGINEER_POINT_OVERLAY_SCHEMA {
        return Err(format!(
            "engineer overlay schema must be {ENGINEER_POINT_OVERLAY_SCHEMA}"
        ));
    }
    Ok(store)
}

fn save_engineer_point_overlay(
    building_root: &Path,
    building_id: &str,
    store: &EngineerPointOverlayStore,
    dry_run: bool,
) -> Result<(), String> {
    if dry_run {
        return Ok(());
    }
    fs::create_dir_all(building_root).map_err(|e| format!("create building root: {e}"))?;
    let dest = engineer_overlay_path(building_root);
    let tmp = building_root.join(format!("{ENGINEER_POINT_OVERLAY_FILE}{OVERLAY_TMP_SUFFIX}"));
    let body = serde_json::to_string_pretty(store).map_err(|e| format!("serialize: {e}"))?;
    fs::write(&tmp, format!("{body}\n")).map_err(|e| format!("write engineer overlay tmp: {e}"))?;
    fs::rename(&tmp, &dest).map_err(|e| format!("publish engineer overlay: {e}"))?;
    if store.building_id != building_id {
        return Err("engineer overlay building_id mismatch".into());
    }
    Ok(())
}

fn merge_engineer_patch(
    existing: Option<&EngineerPointOverlayEntry>,
    unit: Option<&str>,
    quantity: Option<&str>,
    primary_reference: Option<bool>,
) -> EngineerPointOverlayEntry {
    let mut entry = existing.cloned().unwrap_or_default();
    if let Some(u) = unit {
        let trimmed = u.trim();
        entry.unit = if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        };
    }
    if let Some(q) = quantity {
        let trimmed = q.trim();
        entry.quantity = if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        };
    }
    if let Some(flag) = primary_reference {
        entry.primary_reference = flag;
    }
    entry
}

pub fn upsert_engineer_point_overlay(
    building_root: &Path,
    building_id: &str,
    point_id: &str,
    unit: Option<&str>,
    quantity: Option<&str>,
    primary_reference: Option<bool>,
    dry_run: bool,
) -> Result<(), String> {
    let pid = point_id.trim();
    if pid.is_empty() {
        return Err("point_id required".into());
    }
    if unit.is_none() && quantity.is_none() && primary_reference.is_none() {
        return Ok(());
    }
    validate_engineer_patch(unit, quantity, primary_reference)?;
    let mut store = load_engineer_point_overlay(building_root)?;
    if store.building_id.is_empty() {
        store.building_id = building_id.to_string();
    } else if store.building_id != building_id {
        return Err("engineer overlay building_id mismatch".into());
    }
    let merged = merge_engineer_patch(store.points.get(pid), unit, quantity, primary_reference);
    store.points.insert(pid.to_string(), merged);
    save_engineer_point_overlay(building_root, building_id, &store, dry_run)
}

pub fn remove_engineer_point_overlay(
    building_root: &Path,
    point_id: &str,
    dry_run: bool,
) -> Result<(), String> {
    let pid = point_id.trim();
    if pid.is_empty() {
        return Ok(());
    }
    let mut store = load_engineer_point_overlay(building_root)?;
    if store.points.remove(pid).is_none() {
        return Ok(());
    }
    if store.points.is_empty() && store.building_id.is_empty() {
        if dry_run {
            return Ok(());
        }
        let path = engineer_overlay_path(building_root);
        if path.is_file() {
            fs::remove_file(&path).map_err(|e| format!("remove engineer overlay: {e}"))?;
        }
        return Ok(());
    }
    save_engineer_point_overlay(building_root, &store.building_id, &store, dry_run)
}

/// Effective unit for committed ingest: engineer overlay, then NF portal tag, then none.
pub fn effective_point_unit(
    portal_unit: Option<&str>,
    entry: Option<&EngineerPointOverlayEntry>,
) -> Option<String> {
    if let Some(u) = entry
        .and_then(|e| e.unit.as_deref())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        return Some(u.to_string());
    }
    portal_unit
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

/// Effective quantity for committed ingest (overlay only; portal inventory does not supply it).
pub fn effective_point_quantity(entry: Option<&EngineerPointOverlayEntry>) -> Option<String> {
    entry
        .and_then(|e| e.quantity.as_deref())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
}

pub fn effective_primary_reference(entry: Option<&EngineerPointOverlayEntry>) -> bool {
    entry.map(|e| e.primary_reference).unwrap_or(false)
}

/// Upsert equipment into the writable overlay (BPS `POST /api/model/equip`).
pub fn upsert_equipment(
    building_root: &Path,
    building_id: &str,
    equipment_id: &str,
    fields: EquipUpsertFields<'_>,
    opts: OverlayCasOpts,
) -> Result<Value, Value> {
    let eid = equipment_id.trim();
    if eid.is_empty() {
        return Err(json!({
            "ok": false,
            "error": "equipment_id required",
            "building_id": building_id,
            "soft_open_neq_fq": true,
        }));
    }
    let store = load_overlay_store(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    let mutate = (|| -> Result<Vec<PortalTagDiagnostic>, String> {
        let site = ensure_site(&store, building_id)?;
        let equip = ensure_equip(&store, building_id, eid, &site)?;
        let dis_pred = pinned("dis")?;
        if let Some(d) = fields.dis.map(str::trim).filter(|s| !s.is_empty()) {
            set_str(&store, &equip, &dis_pred, d)?;
        }
        let mut diags = Vec::new();
        let written = resolve_write_markers(fields.markers);
        if !fields.markers.is_empty() {
            replace_tags(&store, &equip, &written.iris)?;
            replace_native_tags(&store, &equip, &written.native)?;
        }
        diags.extend(to_portal_diags(eid, &written.diagnostics));
        if let Some(k) = fields.kind.map(str::trim).filter(|s| !s.is_empty()) {
            let (iri, diag) = kind_class(k);
            if let Some(iri) = iri {
                ensure_has_tag(&store, &equip, &iri)?;
            }
            if let Some(diag) = diag {
                diags.extend(to_portal_diags(eid, &[diag]));
            }
        }
        let tomb = tombstone_uri(building_id, "equip", eid)?;
        remove_subject(&store, &tomb)?;
        Ok(diags)
    })();
    let diags = match mutate {
        Ok(diags) => diags,
        Err(e) => {
            return Err(json!({
                "ok": false,
                "error": e,
                "building_id": building_id,
                "soft_open_neq_fq": true,
            }));
        }
    };
    match commit_store(
        building_root,
        building_id,
        &store,
        opts.expected_revision,
        opts.dry_run,
        &format!("upsert_equipment:{eid}"),
    ) {
        Ok(body) => Ok(attach_tag_diagnostics(body, &diags)),
        Err(err) => Err(err),
    }
}

/// Upsert point into the writable overlay (BPS `POST /api/model/point`).
pub fn upsert_point(
    building_root: &Path,
    building_id: &str,
    equipment_id: &str,
    point_id: &str,
    fields: PointUpsertFields<'_>,
    opts: OverlayCasOpts,
) -> Result<Value, Value> {
    let eid = equipment_id.trim();
    let pid = point_id.trim();
    if eid.is_empty() || pid.is_empty() {
        return Err(json!({
            "ok": false,
            "error": "equipment_id and point_id required",
            "building_id": building_id,
            "soft_open_neq_fq": true,
        }));
    }
    let store = load_overlay_store(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    let ofk = fields
        .openfdd_key
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or(pid)
        .to_string();
    let engineer_unit = fields.unit;
    let engineer_quantity = fields.quantity;
    let engineer_primary = fields.primary_reference;
    let mutate = (|| -> Result<Vec<PortalTagDiagnostic>, String> {
        let site = ensure_site(&store, building_id)?;
        let equip = ensure_equip(&store, building_id, eid, &site)?;
        let point = point_uri(building_id, pid)?;
        let point_class = pinned("point")?;
        if !has_type(&store, &point, &point_class)? {
            insert_type(&store, &point, &point_class)?;
            insert_str(&store, &point, &ofdd("pointId"), pid)?;
            insert_str(&store, &point, &ofdd("hasTimeseriesId"), pid)?;
            insert_str(&store, &point, &ofdd("siteId"), building_id)?;
            let site_ref = pinned("siteRef")?;
            insert_ref(&store, &point, &site_ref, &site)?;
            insert_bool_true(&store, &point, &ofdd("overlay"))?;
        }
        let equip_ref = pinned("equipRef")?;
        set_ref(&store, &point, &equip_ref, &equip)?;
        set_str(&store, &point, &ofdd("openfddKey"), &ofk)?;
        let dis_pred = pinned("dis")?;
        if let Some(d) = fields.dis.map(str::trim).filter(|s| !s.is_empty()) {
            set_str(&store, &point, &dis_pred, d)?;
        }
        if let Some(r) = fields.role.map(str::trim).filter(|s| !s.is_empty()) {
            set_str(&store, &point, &ofdd("role"), r)?;
        }
        let written = resolve_write_markers(fields.markers);
        if !fields.markers.is_empty() {
            replace_tags(&store, &point, &written.iris)?;
            replace_native_tags(&store, &point, &written.native)?;
        }
        let tomb = tombstone_uri(building_id, "point", pid)?;
        remove_subject(&store, &tomb)?;
        if ofk != pid {
            let tomb_ofk = tombstone_uri(building_id, "point", &ofk)?;
            remove_subject(&store, &tomb_ofk)?;
        }
        Ok(to_portal_diags(pid, &written.diagnostics))
    })();
    let diags = match mutate {
        Ok(diags) => diags,
        Err(e) => {
            return Err(json!({
                "ok": false,
                "error": e,
                "building_id": building_id,
                "soft_open_neq_fq": true,
            }));
        }
    };
    if engineer_unit.is_some() || engineer_quantity.is_some() || engineer_primary.is_some() {
        match upsert_engineer_point_overlay(
            building_root,
            building_id,
            pid,
            engineer_unit,
            engineer_quantity,
            engineer_primary,
            opts.dry_run,
        ) {
            Ok(()) => {}
            Err(e) => {
                return Err(json!({
                    "ok": false,
                    "error": e,
                    "building_id": building_id,
                    "soft_open_neq_fq": true,
                }));
            }
        }
    }
    match commit_store(
        building_root,
        building_id,
        &store,
        opts.expected_revision,
        opts.dry_run,
        &format!("upsert_point:{pid}"),
    ) {
        Ok(body) => Ok(attach_tag_diagnostics(body, &diags)),
        Err(err) => Err(err),
    }
}

/// Delete / hide a point (overlay triples + tombstone). Pack RDF stays immutable.
pub fn delete_point(
    building_root: &Path,
    building_id: &str,
    point_id: &str,
    also_exclude: &[String],
    expected_revision: Option<u64>,
    dry_run: bool,
) -> Result<Value, Value> {
    let pid = point_id.trim();
    if pid.is_empty() {
        return Err(json!({
            "ok": false,
            "error": "point_id required",
            "building_id": building_id,
            "soft_open_neq_fq": true,
        }));
    }
    let store = load_overlay_store(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    let mutate = (|| -> Result<(), String> {
        let mut point = point_uri(building_id, pid)?;
        let any = store
            .quads_for_pattern(
                Some(NamedOrBlankNode::from(point.clone()).as_ref()),
                None,
                None,
                None,
            )
            .next()
            .is_some();
        if !any {
            if let Some(found) = find_subject_by_id_literal(&store, "pointId", pid)? {
                point = found;
            }
        }
        remove_subject(&store, &point)?;
        let mut seen = BTreeSet::new();
        let mut exclude = vec![pid.to_string()];
        for x in also_exclude {
            let t = x.trim();
            if !t.is_empty() {
                exclude.push(t.to_string());
            }
        }
        for id in exclude {
            if !seen.insert(id.clone()) {
                continue;
            }
            add_point_tombstone(&store, building_id, &id)?;
        }
        Ok(())
    })();
    if let Err(e) = mutate {
        return Err(json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        }));
    }
    if let Err(e) = remove_engineer_point_overlay(building_root, pid, dry_run) {
        return Err(json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        }));
    }
    commit_store(
        building_root,
        building_id,
        &store,
        expected_revision,
        dry_run,
        &format!("delete_point:{pid}"),
    )
}

/// Delete / hide equipment (+ child overlay points) with tombstones.
pub fn delete_equipment(
    building_root: &Path,
    building_id: &str,
    equipment_id: &str,
    expected_revision: Option<u64>,
    dry_run: bool,
) -> Result<Value, Value> {
    let eid = equipment_id.trim();
    if eid.is_empty() {
        return Err(json!({
            "ok": false,
            "error": "equipment_id required",
            "building_id": building_id,
            "soft_open_neq_fq": true,
        }));
    }
    let store = load_overlay_store(building_root).map_err(|e| {
        json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        })
    })?;
    let mutate = (|| -> Result<(), String> {
        let mut equip = equip_uri(building_id, eid)?;
        let any = store
            .quads_for_pattern(
                Some(NamedOrBlankNode::from(equip.clone()).as_ref()),
                None,
                None,
                None,
            )
            .next()
            .is_some();
        if !any {
            if let Some(found) = find_subject_by_id_literal(&store, "equipmentId", eid)? {
                equip = found;
            }
        }
        let equip_ref = pinned("equipRef")?;
        let pred = nn(&equip_ref)?;
        let equip_term = Term::from(equip.clone());
        let children: Vec<NamedNode> = store
            .quads_for_pattern(None, Some((&pred).into()), Some((&equip_term).into()), None)
            .filter_map(|q| match q {
                Ok(quad) => match quad.subject {
                    NamedOrBlankNode::NamedNode(n) => Some(n),
                    _ => None,
                },
                Err(_) => None,
            })
            .collect();
        for pt in children {
            let mut pid: Option<String> = None;
            let p_id = nn(&ofdd("pointId"))?;
            let point_id_quads: Vec<Quad> = store
                .quads_for_pattern(
                    Some(NamedOrBlankNode::from(pt.clone()).as_ref()),
                    Some((&p_id).into()),
                    None,
                    None,
                )
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| format!("quads: {e}"))?;
            for quad in point_id_quads {
                if let Term::Literal(lit) = quad.object {
                    pid = Some(lit.value().to_string());
                    break;
                }
            }
            remove_subject(&store, &pt)?;
            if let Some(id) = pid {
                add_point_tombstone(&store, building_id, &id)?;
            }
        }
        remove_subject(&store, &equip)?;
        add_equip_tombstone(&store, building_id, eid)?;
        Ok(())
    })();
    if let Err(e) = mutate {
        return Err(json!({
            "ok": false,
            "error": e,
            "building_id": building_id,
            "soft_open_neq_fq": true,
        }));
    }
    commit_store(
        building_root,
        building_id,
        &store,
        expected_revision,
        dry_run,
        &format!("delete_equipment:{eid}"),
    )
}

/// One equipment in a portal inventory snapshot.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PortalEquip {
    pub equipment_id: String,
    pub dis: Option<String>,
    pub kind: Option<String>,
    pub markers: Vec<String>,
}

/// One point in a portal inventory snapshot.
///
/// `role` is empty when the portal point has no custom role. The point stays
/// in the overlay. Typed kind, unit, ref, enum, timezone, and history metadata
/// are stored beside that role and do not by themselves approve a rule input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PortalPoint {
    pub point_id: String,
    pub equipment_id: String,
    pub openfdd_key: String,
    pub role: String,
    pub dis: Option<String>,
    pub unit: Option<String>,
    pub markers: Vec<String>,
    pub kind: Option<String>,
    pub tz: Option<String>,
    pub his: Option<bool>,
    pub his_mode: Option<String>,
    pub enum_value: Option<String>,
    pub ref_rel: Option<String>,
    pub ref_id: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct PortalSyncReport {
    pub changed: bool,
    pub revision: u64,
    pub equipment_upserted: usize,
    pub points_upserted: usize,
    pub equipment_deleted: Vec<String>,
    pub points_deleted: Vec<String>,
    pub removals_skipped: bool,
    /// Symbols that were not emitted as pinned Haystack marker classes.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tag_diagnostics: Vec<PortalTagDiagnostic>,
}

/// One marker the shared resolver refused to mint as an official class.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PortalTagDiagnostic {
    pub entity_id: String,
    pub symbol: String,
    pub outcome: String,
}

/// Make the overlay match one portal inventory snapshot for `source`.
///
/// Listed equipment and points are upserted in place (one node per id; tags,
/// display name, unit, and equipment link replaced). Nodes stamped with this
/// `source` that the snapshot no longer lists are removed and tombstoned, so a
/// pack copy of the same id stays hidden from SPARQL. With `allow_removals`
/// false (a possibly truncated snapshot) nothing is removed. The file and its
/// revision change only when the graph changes.
pub fn sync_portal_inventory(
    building_root: &Path,
    building_id: &str,
    source: &str,
    equipment: &[PortalEquip],
    points: &[PortalPoint],
    allow_removals: bool,
) -> Result<PortalSyncReport, String> {
    let source = source.trim();
    if source.is_empty() {
        return Err("portal source required".into());
    }
    let store = load_overlay_store(building_root)?;
    let before = quad_set(&store)?;
    let site = ensure_site(&store, building_id)?;
    let source_pred = ofdd("portalSource");
    let mut report = PortalSyncReport {
        removals_skipped: !allow_removals,
        ..PortalSyncReport::default()
    };

    if allow_removals {
        let listed_equip: BTreeSet<&str> =
            equipment.iter().map(|e| e.equipment_id.as_str()).collect();
        let listed_points: BTreeSet<&str> = points.iter().map(|p| p.point_id.as_str()).collect();
        for (subject, id) in sourced_subjects(&store, source, "equipmentId")? {
            if listed_equip.contains(id.as_str()) {
                continue;
            }
            for (child, child_id) in child_points(&store, &subject)? {
                remove_subject(&store, &child)?;
                if let Some(pid) = child_id {
                    add_point_tombstone(&store, building_id, &pid)?;
                    report.points_deleted.push(pid);
                }
            }
            remove_subject(&store, &subject)?;
            add_equip_tombstone(&store, building_id, &id)?;
            report.equipment_deleted.push(id);
        }
        for (subject, id) in sourced_subjects(&store, source, "pointId")? {
            if listed_points.contains(id.as_str()) {
                continue;
            }
            remove_subject(&store, &subject)?;
            add_point_tombstone(&store, building_id, &id)?;
            report.points_deleted.push(id);
        }
    }

    for eq in equipment {
        let eid = eq.equipment_id.trim();
        if eid.is_empty() {
            continue;
        }
        let node = ensure_equip(&store, building_id, eid, &site)?;
        set_str(&store, &node, &source_pred, source)?;
        let dis_pred = pinned("dis")?;
        set_optional_str(&store, &node, &dis_pred, eq.dis.as_deref())?;
        let mut written = resolve_write_markers(&eq.markers);
        if let Some(kind) = eq.kind.as_deref() {
            let (iri, diag) = kind_class(kind);
            if let Some(iri) = iri {
                push_iri(&mut written.iris, iri);
            }
            if let Some(diag) = diag {
                written.diagnostics.push(diag);
            }
        }
        replace_tags(&store, &node, &written.iris)?;
        replace_native_tags(&store, &node, &written.native)?;
        report
            .tag_diagnostics
            .extend(to_portal_diags(eid, &written.diagnostics));
        remove_subject(&store, &tombstone_uri(building_id, "equip", eid)?)?;
        report.equipment_upserted += 1;
    }

    for pt in points {
        let pid = pt.point_id.trim();
        let eid = pt.equipment_id.trim();
        if pid.is_empty() || eid.is_empty() {
            continue;
        }
        let equip = ensure_equip(&store, building_id, eid, &site)?;
        let node = point_uri(building_id, pid)?;
        let point_class = pinned("point")?;
        if !has_type(&store, &node, &point_class)? {
            insert_type(&store, &node, &point_class)?;
            insert_str(&store, &node, &ofdd("pointId"), pid)?;
            insert_str(&store, &node, &ofdd("hasTimeseriesId"), pid)?;
            insert_str(&store, &node, &ofdd("siteId"), building_id)?;
            let site_ref = pinned("siteRef")?;
            insert_ref(&store, &node, &site_ref, &site)?;
            insert_bool_true(&store, &node, &ofdd("overlay"))?;
        }
        set_str(&store, &node, &source_pred, source)?;
        let equip_ref = pinned("equipRef")?;
        set_ref(&store, &node, &equip_ref, &equip)?;
        set_str(&store, &node, &ofdd("openfddKey"), pt.openfdd_key.trim())?;
        set_optional_str(
            &store,
            &node,
            &ofdd("role"),
            Some(pt.role.trim()).filter(|role| !role.is_empty()),
        )?;
        let dis_pred = pinned("dis")?;
        let unit_pred = pinned("unit")?;
        set_optional_str(&store, &node, &dis_pred, pt.dis.as_deref())?;
        set_optional_str(&store, &node, &unit_pred, pt.unit.as_deref())?;
        write_point_metadata(&store, building_id, &node, pt)?;
        let mut markers = pt.markers.clone();
        if pt.his == Some(true) && !markers.iter().any(|marker| marker == "his") {
            markers.push("his".to_string());
        }
        let written = resolve_write_markers(&markers);
        replace_tags(&store, &node, &written.iris)?;
        replace_native_tags(&store, &node, &written.native)?;
        report
            .tag_diagnostics
            .extend(to_portal_diags(pid, &written.diagnostics));
        remove_subject(&store, &tombstone_uri(building_id, "point", pid)?)?;
        report.points_upserted += 1;
    }

    if allow_removals && !report.points_deleted.is_empty() {
        for pid in &report.points_deleted {
            let _ = remove_engineer_point_overlay(building_root, pid, false);
        }
    }

    let after = quad_set(&store)?;
    if before == after {
        report.revision = load_revision(building_root)?;
        return Ok(report);
    }
    let committed = commit_store(
        building_root,
        building_id,
        &store,
        None,
        false,
        &format!("portal_inventory_sync:{source}"),
    )
    .map_err(|err| {
        err.get("error")
            .and_then(Value::as_str)
            .unwrap_or("overlay commit failed")
            .to_string()
    })?;
    report.changed = true;
    report.revision = committed
        .get("revision")
        .and_then(Value::as_u64)
        .unwrap_or_default();
    Ok(report)
}

fn quad_set(store: &Store) -> Result<BTreeSet<String>, String> {
    store
        .iter()
        .map(|q| q.map(|quad| quad.to_string()))
        .collect::<Result<BTreeSet<_>, _>>()
        .map_err(|e| format!("quads: {e}"))
}

fn set_optional_str(
    store: &Store,
    s: &NamedNode,
    pred: &str,
    value: Option<&str>,
) -> Result<(), String> {
    match value.map(str::trim).filter(|v| !v.is_empty()) {
        Some(v) => set_str(store, s, pred, v),
        None => {
            let pred_nn = nn(pred)?;
            let existing: Vec<Quad> = store
                .quads_for_pattern(
                    Some(NamedOrBlankNode::from(s.clone()).as_ref()),
                    Some((&pred_nn).into()),
                    None,
                    None,
                )
                .collect::<Result<Vec<_>, _>>()
                .map_err(|e| format!("quads: {e}"))?;
            for q in existing {
                store.remove(&q).map_err(|e| format!("remove quad: {e}"))?;
            }
            Ok(())
        }
    }
}

fn ensure_has_tag(store: &Store, s: &NamedNode, iri: &str) -> Result<(), String> {
    let tag_term = Term::from(nn(iri)?);
    if !has_quad(store, s, HAS_TAG_IRI, &tag_term)? {
        insert_quad(store, s, HAS_TAG_IRI, tag_term)?;
    }
    Ok(())
}

fn replace_native_tags(store: &Store, s: &NamedNode, symbols: &[String]) -> Result<(), String> {
    let pred = nn(NATIVE_TAG_IRI)?;
    let existing: Vec<Quad> = store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            Some((&pred).into()),
            None,
            None,
        )
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("quads: {e}"))?;
    for q in existing {
        store.remove(&q).map_err(|e| format!("remove quad: {e}"))?;
    }
    for symbol in symbols {
        insert_str(store, s, NATIVE_TAG_IRI, symbol)?;
    }
    Ok(())
}

fn replace_tags(store: &Store, s: &NamedNode, tags: &[String]) -> Result<(), String> {
    let pred = nn(HAS_TAG_IRI)?;
    let existing: Vec<Quad> = store
        .quads_for_pattern(
            Some(NamedOrBlankNode::from(s.clone()).as_ref()),
            Some((&pred).into()),
            None,
            None,
        )
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("quads: {e}"))?;
    for q in existing {
        store.remove(&q).map_err(|e| format!("remove quad: {e}"))?;
    }
    for tag in tags {
        insert_quad(store, s, HAS_TAG_IRI, Term::from(nn(tag)?))?;
    }
    Ok(())
}

/// Subjects stamped `ofdd:portalSource source`, with their `ofdd:<id_local>` value.
fn sourced_subjects(
    store: &Store,
    source: &str,
    id_local: &str,
) -> Result<Vec<(NamedNode, String)>, String> {
    let source_pred = nn(&ofdd("portalSource"))?;
    let source_lit = Term::from(Literal::new_simple_literal(source));
    let id_pred = nn(&ofdd(id_local))?;
    let mut out = Vec::new();
    for q in store.quads_for_pattern(
        None,
        Some((&source_pred).into()),
        Some((&source_lit).into()),
        None,
    ) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        let NamedOrBlankNode::NamedNode(subject) = q.subject else {
            continue;
        };
        for idq in store.quads_for_pattern(
            Some(NamedOrBlankNode::from(subject.clone()).as_ref()),
            Some((&id_pred).into()),
            None,
            None,
        ) {
            let idq = idq.map_err(|e| format!("quads: {e}"))?;
            if let Term::Literal(lit) = idq.object {
                out.push((subject.clone(), lit.value().to_string()));
            }
        }
    }
    Ok(out)
}

fn child_points(
    store: &Store,
    equip: &NamedNode,
) -> Result<Vec<(NamedNode, Option<String>)>, String> {
    let equip_ref_iri = pinned("equipRef")?;
    let equip_ref = nn(&equip_ref_iri)?;
    let equip_term = Term::from(equip.clone());
    let p_id = nn(&ofdd("pointId"))?;
    let mut out = Vec::new();
    for q in store.quads_for_pattern(
        None,
        Some((&equip_ref).into()),
        Some((&equip_term).into()),
        None,
    ) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        let NamedOrBlankNode::NamedNode(child) = q.subject else {
            continue;
        };
        let mut pid = None;
        for idq in store.quads_for_pattern(
            Some(NamedOrBlankNode::from(child.clone()).as_ref()),
            Some((&p_id).into()),
            None,
            None,
        ) {
            if let Term::Literal(lit) = idq.map_err(|e| format!("quads: {e}"))?.object {
                pid = Some(lit.value().to_string());
                break;
            }
        }
        out.push((child, pid));
    }
    Ok(out)
}

pub fn soft_open_gaps() -> Vec<&'static str> {
    // Soft-OPEN SPARQL pack ∪ overlay (+ tombstones) is shipped.
    // Remaining Soft-OPEN honesty: C2–C6 Haystack FQ (#997/#1123) is out of this layer.
    Vec::new()
}

/// Soft-OPEN SPARQL dataset: load pack Turtle ∪ overlay Turtle, then remove
/// subjects matching overlay tombstones (`excludesPointId` / `excludesEquipmentId`).
///
/// Pack RDF stays the immutable authority on disk; this only builds an ephemeral
/// query store. Empty overlay is a pack-only store (prior Soft-OPEN behavior).
pub fn union_pack_overlay_for_sparql(
    pack_turtle: &str,
    overlay_turtle: &str,
) -> Result<Store, String> {
    let store = Store::new().map_err(|e| format!("oxigraph store: {e}"))?;
    if !pack_turtle.trim().is_empty() {
        store
            .load_from_reader(RdfFormat::Turtle, Cursor::new(pack_turtle.as_bytes()))
            .map_err(|e| format!("load pack turtle: {e}"))?;
    }
    if !overlay_turtle.trim().is_empty() {
        store
            .load_from_reader(RdfFormat::Turtle, Cursor::new(overlay_turtle.as_bytes()))
            .map_err(|e| format!("load overlay turtle: {e}"))?;
    }
    apply_tombstone_exclusions(&store)?;
    Ok(store)
}

fn collect_tombstone_ids(store: &Store) -> Result<(BTreeSet<String>, BTreeSet<String>), String> {
    let mut points = BTreeSet::new();
    let mut equipment = BTreeSet::new();
    let p_point = nn(&ofdd("excludesPointId"))?;
    let p_equip = nn(&ofdd("excludesEquipmentId"))?;
    for q in store.quads_for_pattern(None, Some((&p_point).into()), None, None) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        if let Term::Literal(lit) = q.object {
            points.insert(lit.value().to_string());
        }
    }
    for q in store.quads_for_pattern(None, Some((&p_equip).into()), None, None) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        if let Term::Literal(lit) = q.object {
            equipment.insert(lit.value().to_string());
        }
    }
    Ok((points, equipment))
}

fn subjects_with_id_literal(
    store: &Store,
    pred_local: &str,
    id: &str,
) -> Result<Vec<NamedNode>, String> {
    let pred = nn(&ofdd(pred_local))?;
    let lit = Term::from(Literal::new_simple_literal(id));
    let mut out = Vec::new();
    for q in store.quads_for_pattern(None, Some((&pred).into()), Some((&lit).into()), None) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        if let NamedOrBlankNode::NamedNode(n) = q.subject {
            out.push(n);
        }
    }
    Ok(out)
}

fn apply_tombstone_exclusions(store: &Store) -> Result<(), String> {
    let (ex_points, ex_equips) = collect_tombstone_ids(store)?;
    if ex_points.is_empty() && ex_equips.is_empty() {
        return Ok(());
    }

    let mut doomed: BTreeSet<String> = BTreeSet::new();
    let mut doomed_nodes: Vec<NamedNode> = Vec::new();

    let push_node = |n: NamedNode, doomed: &mut BTreeSet<String>, nodes: &mut Vec<NamedNode>| {
        if doomed.insert(n.as_str().to_string()) {
            nodes.push(n);
        }
    };

    for eid in &ex_equips {
        for n in subjects_with_id_literal(store, "equipmentId", eid)? {
            push_node(n, &mut doomed, &mut doomed_nodes);
        }
    }

    // Hide points that reference a tombstoned equip (pack or overlay).
    let equip_ref_iri = pinned("equipRef")?;
    let equip_ref = nn(&equip_ref_iri)?;
    let equip_snapshot = doomed_nodes.clone();
    for eq in &equip_snapshot {
        let eq_term = Term::from(eq.clone());
        for q in store.quads_for_pattern(
            None,
            Some((&equip_ref).into()),
            Some((&eq_term).into()),
            None,
        ) {
            let q = q.map_err(|e| format!("quads: {e}"))?;
            if let NamedOrBlankNode::NamedNode(n) = q.subject {
                push_node(n, &mut doomed, &mut doomed_nodes);
            }
        }
    }

    for pid in &ex_points {
        for pred in ["pointId", "openfddKey"] {
            for n in subjects_with_id_literal(store, pred, pid)? {
                push_node(n, &mut doomed, &mut doomed_nodes);
            }
        }
    }

    // Drop tombstone marker nodes themselves from the query graph.
    let rdf_type = nn(RDF_TYPE)?;
    let tomb_class = nn(&ofdd("Tombstone"))?;
    let tomb_term = Term::from(tomb_class);
    for q in store.quads_for_pattern(
        None,
        Some((&rdf_type).into()),
        Some((&tomb_term).into()),
        None,
    ) {
        let q = q.map_err(|e| format!("quads: {e}"))?;
        if let NamedOrBlankNode::NamedNode(n) = q.subject {
            push_node(n, &mut doomed, &mut doomed_nodes);
        }
    }

    for n in doomed_nodes {
        remove_subject(store, &n)?;
    }
    Ok(())
}

pub fn get_overlay_payload(building_root: &Path, building_id: &str) -> Result<Value, String> {
    let revision = load_revision(building_root)?;
    let ttl = load_ttl(building_root)?;
    let present = ttl_path(building_root).is_file();
    let tombs =
        list_tombstones(building_root).unwrap_or_else(|_| json!({"points": [], "equipment": []}));
    Ok(json!({
        "ok": true,
        "building_id": building_id,
        "site_id": building_id,
        "revision": revision,
        "ttl": ttl,
        "overlay_present": present,
        "tombstones": tombs,
        "pack_immutable": true,
        "writable_layer": WRITABLE_LAYER,
        "sparql_union": "pack_cup_overlay_minus_tombstones",
        "soft_open_neq_fq": true,
        "gaps": soft_open_gaps(),
        "note": "Soft-OPEN overlay sidecar — SPARQL queries union pack ∪ overlay (− tombstones); ≠ C2–C6 FQ",
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    const SAMPLE_TTL: &str = r#"
@prefix ph: <https://project-haystack.org/def/ph#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<urn:openfdd:site/SYNTH_OVERLAY#equip-AHU_1> a ph:equip ;
  ph:dis "AHU 1" .
"#;

    #[test]
    fn validate_rejects_garbage() {
        let err = validate_turtle("this is not turtle {{{").unwrap_err();
        assert!(err.contains("invalid turtle"), "{err}");
    }

    #[test]
    fn put_dry_run_conflict_and_publish() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let bid = "SYNTH_OVERLAY";

        let dry = put_overlay_ttl(root, bid, SAMPLE_TTL, None, true).unwrap();
        assert_eq!(dry.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(dry.get("dry_run").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(dry.get("revision").and_then(|v| v.as_u64()), Some(0));
        assert_eq!(dry.get("would_revision").and_then(|v| v.as_u64()), Some(1));
        assert!(!ttl_path(root).is_file());

        let pub1 = put_overlay_ttl(root, bid, SAMPLE_TTL, Some(0), false).unwrap();
        assert_eq!(pub1.get("revision").and_then(|v| v.as_u64()), Some(1));
        assert!(ttl_path(root).is_file());
        assert_eq!(load_revision(root).unwrap(), 1);

        let conflict = put_overlay_ttl(root, bid, SAMPLE_TTL, Some(0), false).unwrap_err();
        assert_eq!(
            conflict.get("conflict").and_then(|v| v.as_bool()),
            Some(true)
        );

        let pub2 = put_overlay_ttl(root, bid, SAMPLE_TTL, Some(1), false).unwrap();
        assert_eq!(pub2.get("revision").and_then(|v| v.as_u64()), Some(2));

        let got = get_overlay_payload(root, bid).unwrap();
        assert_eq!(got.get("revision").and_then(|v| v.as_u64()), Some(2));
        assert!(got
            .get("ttl")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .contains("AHU_1"));
    }

    #[test]
    fn upsert_point_revision_and_conflict() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let bid = "lab-crud";

        let markers = ["sensor".into(), "temp".into()];
        let r0 = upsert_point(
            root,
            bid,
            "AHU-1",
            "SAT",
            PointUpsertFields {
                dis: None,
                openfdd_key: None,
                role: Some("discharge-air-temp"),
                markers: &markers,
                unit: None,
                quantity: None,
                primary_reference: None,
            },
            OverlayCasOpts::default(),
        )
        .unwrap();
        assert_eq!(r0.get("ok").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(r0.get("revision").and_then(|v| v.as_u64()), Some(1));

        let dry = upsert_point(
            root,
            bid,
            "AHU-1",
            "RAT",
            PointUpsertFields {
                dis: None,
                openfdd_key: None,
                role: None,
                markers: &[],
                unit: None,
                quantity: None,
                primary_reference: None,
            },
            OverlayCasOpts {
                expected_revision: Some(1),
                dry_run: true,
            },
        )
        .unwrap();
        assert_eq!(dry.get("dry_run").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(dry.get("revision").and_then(|v| v.as_u64()), Some(1));
        assert_eq!(load_revision(root).unwrap(), 1);

        let conflict = upsert_point(
            root,
            bid,
            "AHU-1",
            "MAT",
            PointUpsertFields {
                dis: None,
                openfdd_key: None,
                role: None,
                markers: &[],
                unit: None,
                quantity: None,
                primary_reference: None,
            },
            OverlayCasOpts {
                expected_revision: Some(0),
                dry_run: false,
            },
        )
        .unwrap_err();
        assert_eq!(
            conflict.get("conflict").and_then(|v| v.as_bool()),
            Some(true)
        );

        let ttl = load_ttl(root).unwrap();
        assert!(ttl.contains("SAT"), "{ttl}");
        assert!(
            ttl.contains("openfddKey") || ttl.contains("ofdd:openfddKey"),
            "{ttl}"
        );
    }

    #[test]
    fn delete_point_tombstones_and_clears_on_upsert() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let bid = "lab-tomb";

        upsert_point(
            root,
            bid,
            "AHU-1",
            "ZN_T",
            PointUpsertFields {
                dis: None,
                openfdd_key: Some("AHU-1.zone-air-temp"),
                role: None,
                markers: &[],
                unit: None,
                quantity: None,
                primary_reference: None,
            },
            OverlayCasOpts::default(),
        )
        .unwrap();

        let gone = delete_point(
            root,
            bid,
            "ZN_T",
            &["AHU-1.zone-air-temp".into()],
            Some(1),
            false,
        )
        .unwrap();
        assert_eq!(gone.get("ok").and_then(|v| v.as_bool()), Some(true));

        let tombs = list_tombstones(root).unwrap();
        let points = tombs
            .get("points")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(points.iter().any(|v| v.as_str() == Some("ZN_T")), "{tombs}");
        assert!(
            points
                .iter()
                .any(|v| v.as_str() == Some("AHU-1.zone-air-temp")),
            "{tombs}"
        );

        upsert_point(
            root,
            bid,
            "AHU-1",
            "ZN_T",
            PointUpsertFields {
                dis: None,
                openfdd_key: Some("AHU-1.zone-air-temp"),
                role: None,
                markers: &[],
                unit: None,
                quantity: None,
                primary_reference: None,
            },
            OverlayCasOpts {
                expected_revision: Some(2),
                dry_run: false,
            },
        )
        .unwrap();
        let tombs2 = list_tombstones(root).unwrap();
        let points2 = tombs2
            .get("points")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(
            !points2.iter().any(|v| v.as_str() == Some("ZN_T")),
            "{tombs2}"
        );
        assert!(
            !points2
                .iter()
                .any(|v| v.as_str() == Some("AHU-1.zone-air-temp")),
            "{tombs2}"
        );
    }

    #[test]
    fn delete_equipment_tombstone() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let bid = "lab-eq";

        upsert_equipment(
            root,
            bid,
            "AHU-X",
            EquipUpsertFields {
                dis: Some("AHU X"),
                kind: Some("ahu"),
                markers: &[],
            },
            OverlayCasOpts::default(),
        )
        .unwrap();
        upsert_point(
            root,
            bid,
            "AHU-X",
            "SAT",
            PointUpsertFields {
                dis: None,
                openfdd_key: None,
                role: None,
                markers: &[],
                unit: None,
                quantity: None,
                primary_reference: None,
            },
            OverlayCasOpts {
                expected_revision: Some(1),
                dry_run: false,
            },
        )
        .unwrap();

        let gone = delete_equipment(root, bid, "AHU-X", Some(2), false).unwrap();
        assert_eq!(gone.get("ok").and_then(|v| v.as_bool()), Some(true));

        let tombs = list_tombstones(root).unwrap();
        let equips = tombs
            .get("equipment")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let points = tombs
            .get("points")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        assert!(
            equips.iter().any(|v| v.as_str() == Some("AHU-X")),
            "{tombs}"
        );
        assert!(points.iter().any(|v| v.as_str() == Some("SAT")), "{tombs}");
    }

    #[test]
    fn sparql_union_adds_overlay_and_hides_tombstoned_pack() {
        let pack = r#"
@prefix ofdd: <urn:openfdd:ns#> .
@prefix phIoT: <https://project-haystack.org/def/phIoT/4.0.0#> .
<urn:openfdd:site/U1/equip/AHU_PACK> a phIoT:equip ;
  ofdd:equipmentId "AHU_PACK" .
<urn:openfdd:site/U1/equip/AHU_PACK/point/SAT> a phIoT:point ;
  ofdd:pointId "SAT" ;
  phIoT:equipRef <urn:openfdd:site/U1/equip/AHU_PACK> .
"#;
        let dir = tempdir().unwrap();
        let root = dir.path();
        let bid = "U1";

        upsert_equipment(
            root,
            bid,
            "AHU_OVERLAY",
            EquipUpsertFields {
                dis: Some("Overlay AHU"),
                kind: Some("ahu"),
                markers: &[],
            },
            OverlayCasOpts::default(),
        )
        .unwrap();
        delete_equipment(root, bid, "AHU_PACK", Some(1), false).unwrap();

        let overlay = load_ttl(root).unwrap();
        let store = union_pack_overlay_for_sparql(pack, &overlay).expect("union");

        let p_eid = nn(&ofdd("equipmentId")).unwrap();
        let lit_pack = Term::from(Literal::new_simple_literal("AHU_PACK"));
        let lit_ov = Term::from(Literal::new_simple_literal("AHU_OVERLAY"));
        assert!(
            store
                .quads_for_pattern(None, Some((&p_eid).into()), Some((&lit_pack).into()), None)
                .next()
                .is_none(),
            "tombstoned pack equip must be absent from SPARQL store"
        );
        assert!(
            store
                .quads_for_pattern(None, Some((&p_eid).into()), Some((&lit_ov).into()), None)
                .next()
                .is_some(),
            "overlay equip must appear in SPARQL store"
        );
        let p_pid = nn(&ofdd("pointId")).unwrap();
        let lit_sat = Term::from(Literal::new_simple_literal("SAT"));
        assert!(
            store
                .quads_for_pattern(None, Some((&p_pid).into()), Some((&lit_sat).into()), None)
                .next()
                .is_none(),
            "points under tombstoned equip must be stripped"
        );
    }

    /// Same published markers through NF inventory, agent CRUD, and the CSV
    /// package projector. Parsed SPARQL must return one shared point id.
    #[test]
    fn nf_csv_and_agent_share_one_resolved_point_id() {
        use crate::csv_ingest::haystack_projection::project_strict;
        use crate::csv_ingest::semantic_meta::SemanticMetaV1;

        const BID: &str = "SYNTH_TAG_RESOLVER";
        const EID: &str = "EQ_HP";
        const PID: &str = "pt-dat-1";
        const POINT_QUERY: &str = r#"
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX phScience: <https://project-haystack.org/def/phScience/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?id WHERE {
  ?point a phIoT:point ;
         ph:hasTag phIoT:discharge ;
         ph:hasTag phScience:air ;
         ph:hasTag phScience:temp ;
         ph:hasTag phIoT:sensor .
  ?point ofdd:pointId ?id .
}
"#;
        const EQUIP_QUERY: &str = r#"
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX phIoT: <https://project-haystack.org/def/phIoT/4.0.0#>
PREFIX phIct: <https://project-haystack.org/def/phIct/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?id WHERE {
  ?equip a phIoT:equip ;
         ph:hasTag phIoT:heatPump ;
         ph:hasTag phIct:protocol .
  ?equip ofdd:equipmentId ?id .
}
"#;
        const WRONG_DISCHARGE: &str = r#"
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?id WHERE {
  ?point ph:hasTag <https://project-haystack.org/def/ph/4.0.0#discharge> .
  ?point ofdd:pointId ?id .
}
"#;
        const WRONG_HEATPUMP: &str = r#"
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?id WHERE {
  ?equip ph:hasTag <https://project-haystack.org/def/phIoT/4.0.0#heatpump> .
  ?equip ofdd:equipmentId ?id .
}
"#;
        const UNIT_AS_MARKER: &str = r#"
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
ASK { ?point ph:hasTag ph:unit . }
"#;
        const UNKNOWN_OFFICIAL: &str = r#"
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
ASK {
  { ?s ph:hasTag <https://project-haystack.org/def/ph/4.0.0#vendorFooTag> }
  UNION { ?s ph:hasTag <https://project-haystack.org/def/phIoT/4.0.0#vendorFooTag> }
  UNION { ?s ph:hasTag <https://project-haystack.org/def/phScience/4.0.0#vendorFooTag> }
  UNION { ?s ph:hasTag <https://project-haystack.org/def/phIct/4.0.0#vendorFooTag> }
}
"#;
        const EXTENSION_QUERY: &str = r#"
PREFIX ph: <https://project-haystack.org/def/ph/4.0.0#>
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?id WHERE {
  ?point ph:hasTag <urn:openfdd:ext#sitePolicy> .
  ?point ofdd:pointId ?id .
}
"#;
        const NATIVE_QUERY: &str = r#"
PREFIX ofdd: <urn:openfdd:ns#>
SELECT ?sym WHERE {
  ?point ofdd:pointId "pt-dat-1" ;
         ofdd:nativeTag ?sym .
}
"#;

        let equip_markers = [
            "equip".to_string(),
            "protocol".to_string(),
            "ahu".to_string(),
        ];
        let point_markers = [
            "point",
            "discharge",
            "air",
            "temp",
            "sensor",
            "unit",
            "vendorFooTag",
            "ext:sitePolicy",
            "false",
            "heatpump",
        ]
        .map(str::to_string);

        let nf_dir = tempdir().unwrap();
        let nf_report = sync_portal_inventory(
            nf_dir.path(),
            BID,
            "nf:synth-resolver",
            &[PortalEquip {
                equipment_id: EID.to_string(),
                dis: Some("Heat pump".into()),
                kind: Some("heatPump".into()),
                markers: equip_markers.to_vec(),
            }],
            &[PortalPoint {
                point_id: PID.to_string(),
                equipment_id: EID.to_string(),
                openfdd_key: format!("{EID}.discharge-air-temp"),
                role: "discharge-air-temp".into(),
                dis: Some("Discharge air temp".into()),
                unit: Some("F".into()),
                markers: point_markers.to_vec(),
                kind: None,
                tz: None,
                his: None,
                his_mode: None,
                enum_value: None,
                ref_rel: None,
                ref_id: None,
            }],
            true,
        )
        .expect("nf sync");
        let nf_ttl = load_ttl(nf_dir.path()).expect("nf ttl");

        let agent_dir = tempdir().unwrap();
        upsert_equipment(
            agent_dir.path(),
            BID,
            EID,
            EquipUpsertFields {
                dis: Some("Heat pump"),
                kind: Some("heatPump"),
                markers: &equip_markers,
            },
            OverlayCasOpts::default(),
        )
        .expect("agent equip");
        upsert_point(
            agent_dir.path(),
            BID,
            EID,
            PID,
            PointUpsertFields {
                dis: Some("Discharge air temp"),
                openfdd_key: Some("EQ_HP.discharge-air-temp"),
                role: Some("discharge-air-temp"),
                markers: &point_markers,
                unit: None,
                quantity: None,
                primary_reference: None,
            },
            OverlayCasOpts {
                expected_revision: Some(1),
                dry_run: false,
            },
        )
        .expect("agent point");
        let agent_ttl = load_ttl(agent_dir.path()).expect("agent ttl");

        let meta: SemanticMetaV1 = serde_json::from_value(json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": BID,
            "points": [{
                "equipment_id": EID,
                "column": "dat",
                "point_id": PID,
                "haystack_tags": point_markers,
                "unit": "F"
            }],
            "equipment": [{
                "equipment_id": EID,
                "display_name": "Heat pump",
                "haystack_tags": ["equip", "heatPump", "protocol", "ahu"]
            }]
        }))
        .expect("semantic meta");
        let projected = project_strict(&meta, None);
        assert!(
            projected
                .report
                .omitted
                .iter()
                .all(|o| o.reason != "projection_error"),
            "{:?}",
            projected.report.omitted
        );
        let csv_ttl = projected.turtle;

        let graphs = [("nf", nf_ttl), ("agent", agent_ttl), ("csv", csv_ttl)];
        let mut point_ids = Vec::new();
        let mut equip_ids = Vec::new();
        for (label, ttl) in &graphs {
            let ids = select_values(ttl, POINT_QUERY, "id");
            assert_eq!(ids, vec![PID.to_string()], "{label} point id");
            point_ids.push(ids);
            let equips = select_values(ttl, EQUIP_QUERY, "id");
            assert_eq!(equips, vec![EID.to_string()], "{label} equip id");
            equip_ids.push(equips);
            assert!(
                select_values(ttl, WRONG_DISCHARGE, "id").is_empty(),
                "{label} matched discharge in the wrong library"
            );
            assert!(
                select_values(ttl, WRONG_HEATPUMP, "id").is_empty(),
                "{label} matched lowercased heatpump"
            );
            assert!(
                !ask_graph(ttl, UNIT_AS_MARKER),
                "{label} cast unit as a marker"
            );
            assert!(
                !ask_graph(ttl, UNKNOWN_OFFICIAL),
                "{label} minted vendorFooTag in a Haystack library"
            );
            assert_eq!(
                select_values(ttl, EXTENSION_QUERY, "id"),
                vec![PID.to_string()],
                "{label} extension tag"
            );
            let mut native = select_values(ttl, NATIVE_QUERY, "sym");
            native.sort();
            assert_eq!(
                native,
                vec!["heatpump".to_string(), "vendorFooTag".to_string()],
                "{label} native metadata"
            );
        }
        assert_eq!(point_ids[0], point_ids[1]);
        assert_eq!(point_ids[1], point_ids[2]);
        assert_eq!(equip_ids[0], equip_ids[1]);
        assert_eq!(equip_ids[1], equip_ids[2]);

        let outcomes = |entity: &str, symbol: &str| -> Vec<String> {
            nf_report
                .tag_diagnostics
                .iter()
                .filter(|d| d.entity_id == entity && d.symbol == symbol)
                .map(|d| d.outcome.clone())
                .collect()
        };
        assert_eq!(outcomes(PID, "unit"), vec!["value_not_marker".to_string()]);
        assert_eq!(outcomes(PID, "vendorFooTag"), vec!["unknown".to_string()]);
        assert_eq!(outcomes(PID, "heatpump"), vec!["unknown".to_string()]);
        assert_eq!(outcomes(PID, "false"), vec!["absent".to_string()]);
        assert_eq!(
            outcomes(PID, "ext:sitePolicy"),
            vec!["extension".to_string()]
        );
    }

    #[test]
    fn engineer_unit_overlay_survives_portal_resync() {
        let dir = tempdir().unwrap();
        let root = dir.path();
        let bid = "SITE_ENG_OVERLAY";
        let pid = "6a1f0c2a-0001-4000-8000-00000000a001";
        let portal = PortalPoint {
            point_id: pid.to_string(),
            equipment_id: "AHU_1".to_string(),
            openfdd_key: "AHU_1.sat".into(),
            role: "sat".into(),
            dis: Some("Supply".into()),
            unit: None,
            markers: vec!["sensor".into(), "temp".into()],
            kind: Some("Number".into()),
            tz: None,
            his: None,
            his_mode: None,
            enum_value: None,
            ref_rel: None,
            ref_id: None,
        };
        sync_portal_inventory(
            root,
            bid,
            "nf:test",
            &[PortalEquip {
                equipment_id: "AHU_1".into(),
                dis: Some("AHU".into()),
                kind: Some("ahu".into()),
                markers: vec![],
            }],
            &[portal],
            true,
        )
        .expect("sync");
        upsert_engineer_point_overlay(
            root,
            bid,
            pid,
            Some("degF"),
            Some("absolute_temperature"),
            Some(true),
            false,
        )
        .expect("engineer");
        let store = load_engineer_point_overlay(root).expect("load");
        assert_eq!(
            store.points.get(pid).and_then(|e| e.unit.as_deref()),
            Some("degF")
        );
        let portal2 = PortalPoint {
            point_id: pid.to_string(),
            equipment_id: "AHU_1".to_string(),
            openfdd_key: "AHU_1.sat".into(),
            role: "sat".into(),
            dis: Some("Supply renamed".into()),
            unit: None,
            markers: vec!["sensor".into(), "temp".into()],
            kind: Some("Number".into()),
            tz: None,
            his: None,
            his_mode: None,
            enum_value: None,
            ref_rel: None,
            ref_id: None,
        };
        sync_portal_inventory(
            root,
            bid,
            "nf:test",
            &[PortalEquip {
                equipment_id: "AHU_1".into(),
                dis: Some("AHU".into()),
                kind: Some("ahu".into()),
                markers: vec![],
            }],
            &[portal2],
            true,
        )
        .expect("resync");
        let store2 = load_engineer_point_overlay(root).expect("reload");
        let entry = store2.points.get(pid).expect("entry");
        assert_eq!(entry.unit.as_deref(), Some("degF"));
        assert_eq!(entry.quantity.as_deref(), Some("absolute_temperature"));
        assert!(entry.primary_reference);
        assert_eq!(
            effective_point_unit(None, Some(entry)),
            Some("degF".to_string())
        );
    }

    #[test]
    fn engineer_unit_validation_rejects_incompatible_pairs() {
        assert!(validate_engineer_unit_quantity("degF", "absolute_temperature").is_ok());
        assert!(validate_engineer_unit_quantity("%RH", "relative_humidity").is_ok());
        assert!(validate_engineer_unit_quantity("not_a_unit", "absolute_temperature").is_err());
        assert!(validate_engineer_unit_quantity("degF", "relative_humidity").is_err());
    }

    fn select_values(ttl: &str, query: &str, var: &str) -> Vec<String> {
        use crate::csv_ingest::haystack_sparql_bindings::execute_readonly_on_overlay;
        let out = execute_readonly_on_overlay("SYNTH_TAG_RESOLVER", query, ttl)
            .unwrap_or_else(|e| panic!("sparql: {e}\n{query}"));
        out["rows"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .filter_map(|row| {
                row.get(var)
                    .and_then(|b| b.get("value"))
                    .and_then(|v| v.as_str())
                    .map(str::to_string)
            })
            .collect()
    }

    fn ask_graph(ttl: &str, query: &str) -> bool {
        use crate::csv_ingest::haystack_sparql_bindings::execute_readonly_on_overlay;
        let out = execute_readonly_on_overlay("SYNTH_TAG_RESOLVER", query, ttl)
            .unwrap_or_else(|e| panic!("ask: {e}\n{query}"));
        out["boolean"].as_bool().expect("ask boolean")
    }
}
