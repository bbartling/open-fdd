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

use std::collections::BTreeSet;
use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};

use chrono::Utc;
use oxigraph::io::{RdfFormat, RdfSerializer};
use oxigraph::model::{GraphName, GraphNameRef, Literal, NamedNode, NamedOrBlankNode, Quad, Term};
use oxigraph::store::Store;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use super::haystack_defs::{HAS_TAG_IRI, PHIOT_BASE, PH_BASE};
use super::haystack_projection::OFDD_NS;

pub const OVERLAY_TTL_FILE: &str = "model_overlay.ttl";
pub const OVERLAY_META_FILE: &str = "model_overlay.meta.json";
pub const OVERLAY_TMP_SUFFIX: &str = ".tmp";
/// BPS-compatible body size cap (chars).
pub const MAX_TTL_CHARS: usize = 2_000_000;
pub const WRITABLE_LAYER: &str = "model_overlay_ttl";

const RDF_TYPE: &str = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type";
const XSD_BOOLEAN: &str = "http://www.w3.org/2001/XMLSchema#boolean";

const KIND_TAGS: &[(&str, &str)] = &[
    ("ahu", "ahu"),
    ("vav", "vav"),
    ("chiller", "chiller"),
    ("boiler", "boiler"),
    ("fan", "fan"),
    ("pump", "pump"),
];

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

fn phiot(local: &str) -> String {
    format!("{PHIOT_BASE}{local}")
}

fn ph(local: &str) -> String {
    format!("{PH_BASE}{local}")
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
    if !has_type(store, &site, &phiot("site"))? {
        insert_type(store, &site, &phiot("site"))?;
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
    if !has_type(store, &equip, &phiot("equip"))? {
        insert_type(store, &equip, &phiot("equip"))?;
        insert_str(store, &equip, &ofdd("equipmentId"), equipment_id)?;
        insert_ref(store, &equip, &phiot("siteRef"), site)?;
        insert_bool_true(store, &equip, &ofdd("overlay"))?;
    }
    Ok(equip)
}

fn kind_tag_iri(kind: &str) -> Option<String> {
    let key = kind.trim().to_ascii_lowercase();
    KIND_TAGS
        .iter()
        .find(|(k, _)| *k == key)
        .map(|(_, local)| phiot(local))
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
    let mutate = (|| -> Result<(), String> {
        let site = ensure_site(&store, building_id)?;
        let equip = ensure_equip(&store, building_id, eid, &site)?;
        if let Some(d) = fields.dis.map(str::trim).filter(|s| !s.is_empty()) {
            set_str(&store, &equip, &ph("dis"), d)?;
        }
        if let Some(k) = fields.kind.map(str::trim).filter(|s| !s.is_empty()) {
            if let Some(tag) = kind_tag_iri(k) {
                let tag_term = Term::from(nn(&tag)?);
                if !has_quad(&store, &equip, HAS_TAG_IRI, &tag_term)? {
                    insert_quad(&store, &equip, HAS_TAG_IRI, tag_term)?;
                }
            }
        }
        for m in fields.markers {
            let local = m.trim().to_ascii_lowercase();
            if local.is_empty() {
                continue;
            }
            let tag = kind_tag_iri(&local).unwrap_or_else(|| phiot(&local));
            let tag_term = Term::from(nn(&tag)?);
            if !has_quad(&store, &equip, HAS_TAG_IRI, &tag_term)? {
                insert_quad(&store, &equip, HAS_TAG_IRI, tag_term)?;
            }
        }
        let tomb = tombstone_uri(building_id, "equip", eid)?;
        remove_subject(&store, &tomb)?;
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
        opts.expected_revision,
        opts.dry_run,
        &format!("upsert_equipment:{eid}"),
    )
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
    let mutate = (|| -> Result<(), String> {
        let site = ensure_site(&store, building_id)?;
        let equip = ensure_equip(&store, building_id, eid, &site)?;
        let point = point_uri(building_id, pid)?;
        if !has_type(&store, &point, &phiot("point"))? {
            insert_type(&store, &point, &phiot("point"))?;
            insert_str(&store, &point, &ofdd("pointId"), pid)?;
            insert_str(&store, &point, &ofdd("hasTimeseriesId"), pid)?;
            insert_str(&store, &point, &ofdd("siteId"), building_id)?;
            insert_ref(&store, &point, &phiot("siteRef"), &site)?;
            insert_bool_true(&store, &point, &ofdd("overlay"))?;
        }
        set_ref(&store, &point, &phiot("equipRef"), &equip)?;
        set_str(&store, &point, &ofdd("openfddKey"), &ofk)?;
        if let Some(d) = fields.dis.map(str::trim).filter(|s| !s.is_empty()) {
            set_str(&store, &point, &ph("dis"), d)?;
        }
        if let Some(r) = fields.role.map(str::trim).filter(|s| !s.is_empty()) {
            set_str(&store, &point, &ofdd("role"), r)?;
        }
        for m in fields.markers {
            let local = m.trim().to_ascii_lowercase();
            if local.is_empty() {
                continue;
            }
            let tag = ph(&local);
            let tag_term = Term::from(nn(&tag)?);
            if !has_quad(&store, &point, HAS_TAG_IRI, &tag_term)? {
                insert_quad(&store, &point, HAS_TAG_IRI, tag_term)?;
            }
        }
        let tomb = tombstone_uri(building_id, "point", pid)?;
        remove_subject(&store, &tomb)?;
        if ofk != pid {
            let tomb_ofk = tombstone_uri(building_id, "point", &ofk)?;
            remove_subject(&store, &tomb_ofk)?;
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
    commit_store(
        building_root,
        building_id,
        &store,
        opts.expected_revision,
        opts.dry_run,
        &format!("upsert_point:{pid}"),
    )
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
        let equip_ref = phiot("equipRef");
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
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PortalPoint {
    pub point_id: String,
    pub equipment_id: String,
    pub openfdd_key: String,
    pub role: String,
    pub dis: Option<String>,
    pub unit: Option<String>,
    pub markers: Vec<String>,
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
        set_optional_str(&store, &node, &ph("dis"), eq.dis.as_deref())?;
        let mut tags: Vec<String> = Vec::new();
        if let Some(tag) = eq.kind.as_deref().and_then(kind_tag_iri) {
            tags.push(tag);
        }
        for m in &eq.markers {
            let local = m.trim().to_ascii_lowercase();
            if !local.is_empty() {
                tags.push(kind_tag_iri(&local).unwrap_or_else(|| phiot(&local)));
            }
        }
        replace_tags(&store, &node, &tags)?;
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
        if !has_type(&store, &node, &phiot("point"))? {
            insert_type(&store, &node, &phiot("point"))?;
            insert_str(&store, &node, &ofdd("pointId"), pid)?;
            insert_str(&store, &node, &ofdd("hasTimeseriesId"), pid)?;
            insert_str(&store, &node, &ofdd("siteId"), building_id)?;
            insert_ref(&store, &node, &phiot("siteRef"), &site)?;
            insert_bool_true(&store, &node, &ofdd("overlay"))?;
        }
        set_str(&store, &node, &source_pred, source)?;
        set_ref(&store, &node, &phiot("equipRef"), &equip)?;
        set_str(&store, &node, &ofdd("openfddKey"), pt.openfdd_key.trim())?;
        set_str(&store, &node, &ofdd("role"), pt.role.trim())?;
        set_optional_str(&store, &node, &ph("dis"), pt.dis.as_deref())?;
        set_optional_str(&store, &node, &ph("unit"), pt.unit.as_deref())?;
        let tags: Vec<String> = pt
            .markers
            .iter()
            .map(|m| m.trim().to_ascii_lowercase())
            .filter(|m| !m.is_empty())
            .map(|m| ph(&m))
            .collect();
        replace_tags(&store, &node, &tags)?;
        remove_subject(&store, &tombstone_uri(building_id, "point", pid)?)?;
        report.points_upserted += 1;
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
    let equip_ref = nn(&phiot("equipRef"))?;
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
    let equip_ref = nn(&phiot("equipRef"))?;
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
}
