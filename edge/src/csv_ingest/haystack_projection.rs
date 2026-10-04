//! Strict Haystack RDF projection (`ofdd_haystack_projection_v1`) — C3 (#1001 / #1123).
//!
//! Authority is native `openfdd_semantic_meta_v1` only. SQL roles never invent
//! Haystack markers. Terms resolve from the pinned official defs bundle
//! (`haystack-defs-ttl-4.0.0`). Turtle is emitted via oxigraph's RDF serializer.

use std::collections::{BTreeMap, BTreeSet};
use std::io::Cursor;

use oxigraph::io::{RdfFormat, RdfSerializer};
use oxigraph::model::{GraphName, GraphNameRef, Literal, NamedNode, NamedOrBlankNode, Quad, Term};
use oxigraph::store::Store;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::haystack_defs::{self, DEFS_PIN, HAS_TAG_IRI, PHIOT_BASE, PHSCIENCE_BASE, PH_BASE};
use super::semantic_meta::{EquipmentMeta, PointMeta, SemanticMetaV1};

pub const PROFILE: &str = "ofdd_haystack_projection_v1";
pub const REPORT_SCHEMA: &str = "ofdd_haystack_projection_report_v1";
pub const OFDD_NS: &str = "urn:openfdd:ns#";
/// Re-export pin id for callers/routes.
pub use haystack_defs::DEFS_PIN as DEFS_PIN_REEXPORT;

const RDF_TYPE: &str = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type";
const ENTITY_MARKERS: &[&str] = &["site", "equip", "point"];

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProjectionOmission {
    pub reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub equipment_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub column: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub term: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProjectionReport {
    pub schema: String,
    pub profile: String,
    pub defs_pin: String,
    pub defs_sha256: String,
    pub building_id: String,
    pub emitted_sites: usize,
    pub emitted_equips: usize,
    pub emitted_points: usize,
    pub omitted: Vec<ProjectionOmission>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ProjectionResult {
    pub turtle: String,
    pub report: ProjectionReport,
}

fn nn(iri: &str) -> Result<NamedNode, String> {
    NamedNode::new(iri.to_string()).map_err(|e| format!("invalid IRI {iri:?}: {e}"))
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

/// Encode a path segment for urn:openfdd:… IRIs. Trailing `.` and reserved
/// punctuation are hex-escaped so identity never depends on Turtle local-name rules.
fn iri_segment(s: &str) -> String {
    let safe = s
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        && !s.is_empty()
        && !s.starts_with("enc_");
    if safe {
        return s.to_string();
    }
    format!("enc_{}", utf8_hex(s.as_bytes()))
}

fn site_iri(building_id: &str) -> String {
    format!("urn:openfdd:site/{}", iri_segment(building_id))
}

fn equip_iri(building_id: &str, equipment_id: &str) -> String {
    format!(
        "urn:openfdd:site/{}/equip/{}",
        iri_segment(building_id),
        iri_segment(equipment_id)
    )
}

fn point_iri(building_id: &str, equipment_id: &str, point_key: &str) -> String {
    format!(
        "urn:openfdd:site/{}/equip/{}/point/{}",
        iri_segment(building_id),
        iri_segment(equipment_id),
        iri_segment(point_key)
    )
}

fn is_false_marker(tag: &str) -> bool {
    let t = tag.trim();
    t.is_empty()
        || t.eq_ignore_ascii_case("false")
        || t.eq_ignore_ascii_case("null")
        || t.eq_ignore_ascii_case("none")
        || t == "0"
}

/// Case-sensitive resolution against pinned defs. No blanket lowercasing.
fn classify_tags(
    raw: &[String],
    omitted: &mut Vec<ProjectionOmission>,
    equipment_id: &str,
    column: Option<&str>,
) -> Vec<String> {
    let defs = haystack_defs::defs();
    let mut out = Vec::new();
    for tag in raw {
        if is_false_marker(tag) {
            omitted.push(ProjectionOmission {
                reason: "false_or_null_marker".into(),
                equipment_id: Some(equipment_id.to_string()),
                column: column.map(str::to_string),
                term: Some(tag.clone()),
                detail: Some("false/null/empty markers are never present tags".into()),
            });
            continue;
        }
        let sym = tag.trim();
        if defs.resolve(sym).is_some_and(|d| d.is_class) {
            if !out.iter().any(|t| t == sym) {
                out.push(sym.to_string());
            }
        } else if defs.contains(sym) {
            // Known non-class symbol used as a tag — still not invent under ph; omit as not a marker class.
            omitted.push(ProjectionOmission {
                reason: "non_marker_def".into(),
                equipment_id: Some(equipment_id.to_string()),
                column: column.map(str::to_string),
                term: Some(tag.clone()),
                detail: Some("def exists but is not an owl:Class marker/entity tag".into()),
            });
        } else {
            omitted.push(ProjectionOmission {
                reason: "unknown_tag".into(),
                equipment_id: Some(equipment_id.to_string()),
                column: column.map(str::to_string),
                term: Some(tag.clone()),
                detail: Some(format!("not in pinned defs {DEFS_PIN}")),
            });
        }
    }
    out
}

fn intentional_exclusion_columns(inventory: Option<&Value>) -> BTreeSet<(String, String)> {
    let mut out = BTreeSet::new();
    let Some(inv) = inventory else {
        return out;
    };
    let Some(equipment) = inv.get("equipment").and_then(|v| v.as_array()) else {
        return out;
    };
    for eq in equipment {
        let eid = eq
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .trim();
        let Some(cols) = eq.get("columns").and_then(|v| v.as_array()) else {
            continue;
        };
        for c in cols {
            let status = c
                .get("status")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_ascii_lowercase();
            if status != "excluded" {
                continue;
            }
            let col = c
                .get("column")
                .and_then(|v| v.as_str())
                .unwrap_or_default()
                .trim();
            if !eid.is_empty() && !col.is_empty() {
                out.insert((eid.to_string(), col.to_string()));
            }
        }
    }
    out
}

fn ambiguous_columns(inventory: Option<&Value>) -> BTreeSet<(String, String)> {
    let mut out = BTreeSet::new();
    let Some(inv) = inventory else {
        return out;
    };
    let Some(equipment) = inv.get("equipment").and_then(|v| v.as_array()) else {
        return out;
    };
    for eq in equipment {
        let eid = eq
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .trim();
        let Some(amb) = eq.get("ambiguous_roles").and_then(|v| v.as_object()) else {
            continue;
        };
        for (_role, cols) in amb {
            let Some(arr) = cols.as_array() else {
                continue;
            };
            for c in arr {
                if let Some(col) = c.as_str().map(str::trim).filter(|s| !s.is_empty()) {
                    out.insert((eid.to_string(), col.to_string()));
                }
            }
        }
    }
    out
}

fn missing_parent_equipment(inventory: Option<&Value>) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    let Some(inv) = inventory else {
        return out;
    };
    let Some(equipment) = inv.get("equipment").and_then(|v| v.as_array()) else {
        return out;
    };
    for eq in equipment {
        let eid = eq
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .trim();
        let et = eq
            .get("equipment_type")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        let parent = eq
            .get("parent_ahu")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty());
        if (et == "vav" || et.contains("vav")) && parent.is_none() {
            out.insert(eid.to_string());
        }
    }
    out
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

fn insert_tag(store: &Store, s: &NamedNode, tag_iri: &str) -> Result<(), String> {
    insert_quad(store, s, HAS_TAG_IRI, Term::from(nn(tag_iri)?))
}

fn insert_str(store: &Store, s: &NamedNode, pred_iri: &str, value: &str) -> Result<(), String> {
    insert_quad(
        store,
        s,
        pred_iri,
        Term::from(Literal::new_simple_literal(value)),
    )
}

fn insert_ref(
    store: &Store,
    s: &NamedNode,
    pred_iri: &str,
    target: &NamedNode,
) -> Result<(), String> {
    insert_quad(store, s, pred_iri, Term::from(target.clone()))
}

fn def_iri(symbol: &str) -> Result<String, String> {
    haystack_defs::defs()
        .resolve(symbol)
        .map(|d| d.iri.clone())
        .ok_or_else(|| format!("missing pinned def for {symbol}"))
}

fn emit_entity_tags(
    store: &Store,
    subject: &NamedNode,
    entity: &str,
    tags: &[String],
) -> Result<(), String> {
    insert_type(store, subject, &def_iri(entity)?)?;
    for tag in tags {
        let iri = def_iri(tag)?;
        insert_tag(store, subject, &iri)?;
    }
    Ok(())
}

fn validate_function_cardinality(
    tags: &[String],
    omitted: &mut Vec<ProjectionOmission>,
    equipment_id: &str,
    column: &str,
) {
    let funcs: Vec<&str> = ["sensor", "cmd", "sp"]
        .into_iter()
        .filter(|f| tags.iter().any(|t| t == *f))
        .collect();
    if funcs.len() > 1 {
        omitted.push(ProjectionOmission {
            reason: "point_function_cardinality".into(),
            equipment_id: Some(equipment_id.to_string()),
            column: Some(column.to_string()),
            term: Some(funcs.join("+")),
            detail: Some(
                "Haystack point modeling: sensor/cmd/sp are mutually exclusive functions; retained with diagnostic"
                    .into(),
            ),
        });
    }
}

fn project_equipment(
    store: &Store,
    building_id: &str,
    site: &NamedNode,
    eq: &EquipmentMeta,
    equip_iris: &BTreeMap<String, NamedNode>,
    omitted: &mut Vec<ProjectionOmission>,
    missing_parents: &BTreeSet<String>,
) -> Result<Option<NamedNode>, String> {
    let eid = eq.equipment_id.as_str();
    if eid.is_empty() {
        return Ok(None);
    }
    let tags = classify_tags(&eq.haystack_tags, omitted, eid, None);
    if tags.is_empty() {
        omitted.push(ProjectionOmission {
            reason: "equip_without_pinned_tags".into(),
            equipment_id: Some(eid.to_string()),
            column: None,
            term: None,
            detail: Some("equipment omitted from strict projection".into()),
        });
        return Ok(None);
    }
    if !tags.iter().any(|t| t == "equip") {
        omitted.push(ProjectionOmission {
            reason: "missing_equip_marker".into(),
            equipment_id: Some(eid.to_string()),
            column: None,
            term: None,
            detail: Some("pinned tags present but no equip marker — omitted".into()),
        });
        return Ok(None);
    }

    let subj = nn(&equip_iri(building_id, eid))?;
    emit_entity_tags(store, &subj, "equip", &tags)?;
    insert_ref(store, &subj, &def_iri("siteRef")?, site)?;
    insert_str(store, &subj, &format!("{OFDD_NS}equipmentId"), eid)?;

    if let Some(name) = eq
        .display_name
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        insert_str(store, &subj, &def_iri("dis")?, name)?;
    }

    if let Some(site_ref) = eq
        .site_ref
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        if site_ref != building_id {
            omitted.push(ProjectionOmission {
                reason: "site_ref_conflict".into(),
                equipment_id: Some(eid.to_string()),
                column: None,
                term: Some(site_ref.to_string()),
                detail: Some(format!(
                    "equipment site_ref {site_ref:?} disagrees with building_id {building_id:?}"
                )),
            });
        }
    }

    match (
        eq.parent_equip
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty()),
        eq.parent_relation
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty()),
    ) {
        (Some(parent), Some(rel)) => {
            if let Some(target) = equip_iris.get(parent) {
                let pred = match rel {
                    "equipRef" => def_iri("equipRef")?,
                    "airRef" => def_iri("airRef")?,
                    other => {
                        omitted.push(ProjectionOmission {
                            reason: "unsupported_parent_relation".into(),
                            equipment_id: Some(eid.to_string()),
                            column: None,
                            term: Some(other.to_string()),
                            detail: Some("expected equipRef or airRef".into()),
                        });
                        return Ok(Some(subj));
                    }
                };
                insert_ref(store, &subj, &pred, target)?;
            } else {
                omitted.push(ProjectionOmission {
                    reason: "dangling_parent_ref".into(),
                    equipment_id: Some(eid.to_string()),
                    column: None,
                    term: Some(parent.to_string()),
                    detail: Some("parent equipment not in scoped model".into()),
                });
            }
        }
        (Some(parent), None) => {
            omitted.push(ProjectionOmission {
                reason: "unconfirmed_parent_relation".into(),
                equipment_id: Some(eid.to_string()),
                column: None,
                term: Some(parent.to_string()),
                detail: Some(
                    "parent_equip present without parent_relation — not asserted as equipRef/airRef"
                        .into(),
                ),
            });
        }
        (None, _) => {
            if missing_parents.contains(eid) {
                omitted.push(ProjectionOmission {
                    reason: "missing_parent_ahu".into(),
                    equipment_id: Some(eid.to_string()),
                    column: None,
                    term: None,
                    detail: Some("stamped VAV without confirmed parent — no topology edge".into()),
                });
            }
        }
    }

    Ok(Some(subj))
}

struct PointProjectCtx<'a> {
    store: &'a Store,
    building_id: &'a str,
    site: &'a NamedNode,
    equip_iris: &'a BTreeMap<String, NamedNode>,
    omitted: &'a mut Vec<ProjectionOmission>,
    excluded: &'a BTreeSet<(String, String)>,
    ambiguous: &'a BTreeSet<(String, String)>,
}

fn project_point(ctx: &mut PointProjectCtx<'_>, pt: &PointMeta) -> Result<bool, String> {
    let eid = pt.equipment_id.as_str();
    let col = pt.column.as_str();
    if eid.is_empty() || col.is_empty() {
        return Ok(false);
    }

    let tags = classify_tags(&pt.haystack_tags, ctx.omitted, eid, Some(col));
    if !tags.iter().any(|t| t == "point") {
        ctx.omitted.push(ProjectionOmission {
            reason: "missing_point_marker".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some("points require pinned point marker".into()),
        });
        return Ok(false);
    }

    let Some(eq_subj) = ctx.equip_iris.get(eid).cloned() else {
        ctx.omitted.push(ProjectionOmission {
            reason: "point_equip_not_projected".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some("parent equipment absent from strict projection".into()),
        });
        return Ok(false);
    };

    validate_function_cardinality(&tags, ctx.omitted, eid, col);

    let point_key = pt.point_id.as_deref().unwrap_or(col);
    let subj = nn(&point_iri(ctx.building_id, eid, point_key))?;
    emit_entity_tags(ctx.store, &subj, "point", &tags)?;
    insert_ref(ctx.store, &subj, &def_iri("equipRef")?, &eq_subj)?;
    insert_ref(ctx.store, &subj, &def_iri("siteRef")?, ctx.site)?;
    insert_str(ctx.store, &subj, &format!("{OFDD_NS}column"), col)?;
    insert_str(ctx.store, &subj, &format!("{OFDD_NS}pointId"), point_key)?;

    // Ambiguous SQL roles stay as semantic points; selection is separate (HR-05 / #1123 F6).
    if ctx.ambiguous.contains(&(eid.to_string(), col.to_string())) {
        ctx.omitted.push(ProjectionOmission {
            reason: "ambiguous_role_unresolved_fdd".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some(
                "valid semantic point retained; FDD role selection unresolved without evidence"
                    .into(),
            ),
        });
        insert_str(
            ctx.store,
            &subj,
            &format!("{OFDD_NS}fddSelection"),
            "unresolved",
        )?;
    }

    if ctx.excluded.contains(&(eid.to_string(), col.to_string())) {
        ctx.omitted.push(ProjectionOmission {
            reason: "intentional_exclusion_fdd".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some(
                "operator FDD exclusion — semantic point retained with ofdd:fddExcluded".into(),
            ),
        });
        insert_str(ctx.store, &subj, &format!("{OFDD_NS}fddExcluded"), "true")?;
    }

    let unit_unknown = pt
        .unit_status
        .as_deref()
        .map(|s| s.eq_ignore_ascii_case("unknown"))
        .unwrap_or(false)
        || pt.unit.as_deref() == Some("???");
    if unit_unknown {
        ctx.omitted.push(ProjectionOmission {
            reason: "unknown_unit".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: pt.unit.clone(),
            detail: Some("retained in native metadata only — not strict literal".into()),
        });
    } else if let Some(unit) = pt.unit.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        insert_str(ctx.store, &subj, &def_iri("unit")?, unit)?;
    }

    if let Some(kind) = pt.kind.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        insert_str(ctx.store, &subj, &def_iri("kind")?, kind)?;
    }
    if let Some(tz) = pt.tz.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        insert_str(ctx.store, &subj, &def_iri("tz")?, tz)?;
    }
    if pt.his == Some(true) {
        insert_tag(ctx.store, &subj, &def_iri("his")?)?;
    }

    if let Some(site_ref) = pt
        .site_ref
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        if site_ref != ctx.building_id {
            ctx.omitted.push(ProjectionOmission {
                reason: "point_site_ref_conflict".into(),
                equipment_id: Some(eid.to_string()),
                column: Some(col.to_string()),
                term: Some(site_ref.to_string()),
                detail: Some("point site_ref disagrees with building scope".into()),
            });
        }
    }

    if let Some(ref_equip) = pt
        .ref_equip
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        if ref_equip != eid {
            if ctx.equip_iris.contains_key(ref_equip) {
                ctx.omitted.push(ProjectionOmission {
                    reason: "point_ref_equip_not_owner".into(),
                    equipment_id: Some(eid.to_string()),
                    column: Some(col.to_string()),
                    term: Some(ref_equip.to_string()),
                    detail: Some(format!(
                        "point ref_equip {ref_equip:?} differs from owner {eid:?}; owner equipRef kept"
                    )),
                });
            } else {
                ctx.omitted.push(ProjectionOmission {
                    reason: "dangling_point_ref_equip".into(),
                    equipment_id: Some(eid.to_string()),
                    column: Some(col.to_string()),
                    term: Some(ref_equip.to_string()),
                    detail: Some("ref_equip target not in scoped model".into()),
                });
            }
        }
    }

    if let Some(air) = pt
        .air_ref
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        if let Some(target) = ctx.equip_iris.get(air).cloned() {
            insert_ref(ctx.store, &subj, &def_iri("airRef")?, &target)?;
        } else {
            ctx.omitted.push(ProjectionOmission {
                reason: "dangling_air_ref".into(),
                equipment_id: Some(eid.to_string()),
                column: Some(col.to_string()),
                term: Some(air.to_string()),
                detail: Some("airRef target not in scoped model".into()),
            });
        }
    }

    if let Some(prov) = pt
        .provenance
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        insert_str(ctx.store, &subj, &format!("{OFDD_NS}provenance"), prov)?;
    }

    Ok(true)
}

fn serialize_store(store: &Store) -> Result<String, String> {
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
        .with_prefix("ofdd", OFDD_NS)
        .map_err(|e| format!("prefix ofdd: {e}"))?;
    store
        .dump_graph_to_writer(GraphNameRef::DefaultGraph, serializer, &mut buf)
        .map_err(|e| format!("turtle serialize: {e}"))?;
    let mut turtle = String::from_utf8(buf).map_err(|e| format!("turtle utf8: {e}"))?;
    let defs = haystack_defs::defs();
    let header = format!(
        "# profile={PROFILE} defs_pin={DEFS_PIN} defs_sha256={}\n# source={}\n",
        defs.sha256, defs.source_url
    );
    turtle.insert_str(0, &header);
    Ok(turtle)
}

/// Project native semantic metadata to strict Haystack Turtle + report.
///
/// Optional `inventory` supplies HR-05 diagnostics (ambiguity / exclusions /
/// missing parent). Roles never become Haystack tags. Ambiguous-role points are
/// retained as semantic entities; FDD selection stays unresolved.
pub fn project_strict(meta: &SemanticMetaV1, inventory: Option<&Value>) -> ProjectionResult {
    match project_strict_inner(meta, inventory) {
        Ok(r) => r,
        Err(e) => ProjectionResult {
            turtle: String::new(),
            report: ProjectionReport {
                schema: REPORT_SCHEMA.to_string(),
                profile: PROFILE.to_string(),
                defs_pin: DEFS_PIN.to_string(),
                defs_sha256: haystack_defs::defs().sha256.clone(),
                building_id: meta.building_id.clone(),
                emitted_sites: 0,
                emitted_equips: 0,
                emitted_points: 0,
                omitted: vec![ProjectionOmission {
                    reason: "projection_error".into(),
                    equipment_id: None,
                    column: None,
                    term: None,
                    detail: Some(e),
                }],
            },
        },
    }
}

fn project_strict_inner(
    meta: &SemanticMetaV1,
    inventory: Option<&Value>,
) -> Result<ProjectionResult, String> {
    let building_id = meta.building_id.trim();
    let building_id = if building_id.is_empty() {
        "unknown"
    } else {
        building_id
    };
    let mut omitted = Vec::new();
    let excluded = intentional_exclusion_columns(inventory);
    let ambiguous = ambiguous_columns(inventory);
    let missing_parents = missing_parent_equipment(inventory);

    if let Some(eqs) = meta.engineering_quantities.as_ref() {
        for q in eqs {
            omitted.push(ProjectionOmission {
                reason: "engineering_quantity_deferred".into(),
                equipment_id: Some(q.equipment_id.clone()),
                column: None,
                term: Some(q.kind.clone()),
                detail: Some(
                    "engineering quantities retained in native meta; strict numeric-value unit mapping deferred"
                        .into(),
                ),
            });
        }
    }

    let store = Store::new().map_err(|e| format!("rdf store: {e}"))?;
    let site = nn(&site_iri(building_id))?;
    emit_entity_tags(&store, &site, "site", &["site".to_string()])?;
    insert_str(&store, &site, &format!("{OFDD_NS}buildingId"), building_id)?;

    // Precompute equip IRIs (trimmed ids only — parse_semantic_meta rejects padded).
    let mut equip_iris = BTreeMap::new();
    for eq in &meta.equipment {
        equip_iris.insert(
            eq.equipment_id.clone(),
            nn(&equip_iri(building_id, &eq.equipment_id))?,
        );
    }

    let mut emitted_equips = 0usize;
    let mut projected_equip = BTreeMap::new();
    for eq in &meta.equipment {
        if let Some(subj) = project_equipment(
            &store,
            building_id,
            &site,
            eq,
            &equip_iris,
            &mut omitted,
            &missing_parents,
        )? {
            projected_equip.insert(eq.equipment_id.clone(), subj);
            emitted_equips += 1;
        }
    }

    let mut emitted_points = 0usize;
    let mut point_ctx = PointProjectCtx {
        store: &store,
        building_id,
        site: &site,
        equip_iris: &projected_equip,
        omitted: &mut omitted,
        excluded: &excluded,
        ambiguous: &ambiguous,
    };
    for pt in &meta.points {
        if project_point(&mut point_ctx, pt)? {
            emitted_points += 1;
        }
    }

    // Round-trip parse check: serializer output must reload.
    let turtle = serialize_store(&store)?;
    {
        let verify = Store::new().map_err(|e| format!("verify store: {e}"))?;
        verify
            .load_from_reader(RdfFormat::Turtle, Cursor::new(turtle.as_bytes()))
            .map_err(|e| format!("serialized turtle failed reload: {e}"))?;
    }

    let report = ProjectionReport {
        schema: REPORT_SCHEMA.to_string(),
        profile: PROFILE.to_string(),
        defs_pin: DEFS_PIN.to_string(),
        defs_sha256: haystack_defs::defs().sha256.clone(),
        building_id: building_id.to_string(),
        emitted_sites: 1,
        emitted_equips,
        emitted_points,
        omitted,
    };
    let _ = ENTITY_MARKERS;
    Ok(ProjectionResult { turtle, report })
}

/// JSON envelope for API / agents.
pub fn project_strict_json(meta: &SemanticMetaV1, inventory: Option<&Value>) -> Value {
    let result = project_strict(meta, inventory);
    let ok = result
        .report
        .omitted
        .iter()
        .all(|o| o.reason != "projection_error");
    json!({
        "ok": ok,
        "profile": PROFILE,
        "defs_pin": DEFS_PIN,
        "defs_sha256": haystack_defs::defs().sha256,
        "building_id": result.report.building_id,
        "turtle": result.turtle,
        "report": result.report,
    })
}

/// Write fixture projection bytes for independent RDFLib / SPARQL KATs.
pub fn export_fixture_projection(
    meta_path: &std::path::Path,
    inventory_path: Option<&std::path::Path>,
    out_ttl: &std::path::Path,
    out_report: &std::path::Path,
) -> Result<(), String> {
    let meta_raw: Value = serde_json::from_str(
        &std::fs::read_to_string(meta_path).map_err(|e| format!("read meta: {e}"))?,
    )
    .map_err(|e| format!("parse meta: {e}"))?;
    let meta = super::semantic_meta::parse_semantic_meta(&meta_raw)?;
    let inventory = match inventory_path {
        Some(p) => Some(
            serde_json::from_str::<Value>(
                &std::fs::read_to_string(p).map_err(|e| format!("read inventory: {e}"))?,
            )
            .map_err(|e| format!("parse inventory: {e}"))?,
        ),
        None => None,
    };
    let result = project_strict_inner(&meta, inventory.as_ref())?;
    if let Some(parent) = out_ttl.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("mkdir: {e}"))?;
    }
    std::fs::write(out_ttl, result.turtle.as_bytes()).map_err(|e| format!("write ttl: {e}"))?;
    let report = serde_json::to_string_pretty(&result.report).map_err(|e| e.to_string())?;
    std::fs::write(out_report, format!("{report}\n")).map_err(|e| format!("write report: {e}"))?;
    Ok(())
}

#[cfg(test)]
pub mod fixtures {
    use super::*;
    use serde_json::json;

    pub fn sample_meta() -> SemanticMetaV1 {
        serde_json::from_value(json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": "OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1",
            "points": [
                {
                    "equipment_id": "AHU_CASE_1",
                    "column": "SAT",
                    "point_id": "ahu1-sat",
                    "haystack_tags": ["sensor", "point", "air", "discharge", "temp", "false", ""],
                    "unit": "°F",
                    "unit_source": "package_map",
                    "kind": "Number",
                    "tz": "Chicago",
                    "his": true
                },
                {
                    "equipment_id": "AHU_CASE_1",
                    "column": "MYSTERY_FLOW",
                    "haystack_tags": ["sensor", "point", "vendorFooTag"],
                    "unit": "???",
                    "unit_status": "unknown"
                },
                {
                    "equipment_id": "VAV_CASE_1",
                    "column": "CLG_VLV_CMD",
                    "haystack_tags": ["sensor", "point", "sp"],
                    "unit": "°F"
                },
                {
                    "equipment_id": "VAV_EXCLUDED_1",
                    "column": "INTENTIONALLY_EXCLUDED_AUX",
                    "haystack_tags": ["sensor", "point"]
                }
            ],
            "equipment": [
                {
                    "equipment_id": "AHU_CASE_1",
                    "display_name": "AHU Case 1",
                    "haystack_tags": ["ahu", "equip"]
                },
                {
                    "equipment_id": "VAV_CASE_1",
                    "haystack_tags": ["vav", "equip"]
                },
                {
                    "equipment_id": "VAV_EXCLUDED_1",
                    "haystack_tags": ["vav", "equip"],
                    "parent_equip": "AHU_CASE_1"
                }
            ]
        }))
        .unwrap()
    }

    pub fn sample_inventory() -> Value {
        json!({
            "building_id": "OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1",
            "equipment": [
                {
                    "equipment_id": "AHU_CASE_1",
                    "equipment_type": "ahu",
                    "roles": {"SAT": "sat"},
                    "ambiguous_roles": {},
                    "columns": []
                },
                {
                    "equipment_id": "VAV_CASE_1",
                    "equipment_type": "vav",
                    "parent_ahu": null,
                    "ambiguous_roles": {
                        "sat_sp": ["CLG_VLV_CMD", "EFFECTIVE_SAT_SP"]
                    },
                    "columns": []
                },
                {
                    "equipment_id": "VAV_EXCLUDED_1",
                    "equipment_type": "vav",
                    "parent_ahu": "AHU_CASE_1",
                    "parent_ahu_source": "package",
                    "ambiguous_roles": {},
                    "columns": [
                        {
                            "column": "INTENTIONALLY_EXCLUDED_AUX",
                            "role": "",
                            "status": "excluded",
                            "exclusion_reason": "operator_policy_not_fdd_input"
                        }
                    ]
                }
            ]
        })
    }
}

#[cfg(test)]
mod tests {
    use super::fixtures::{sample_inventory, sample_meta};
    use super::*;

    #[test]
    fn strict_uses_versioned_multi_library_iris() {
        let result = project_strict(&sample_meta(), Some(&sample_inventory()));
        assert!(
            result
                .report
                .omitted
                .iter()
                .all(|o| o.reason != "projection_error"),
            "{:?}",
            result.report.omitted
        );
        assert!(result.turtle.contains(PHIOT_BASE));
        assert!(result.turtle.contains(PHSCIENCE_BASE));
        assert!(result.turtle.contains(PH_BASE));
        assert!(
            result.turtle.contains("phIoT:site")
                || result.turtle.contains(&format!("{PHIOT_BASE}site"))
        );
        assert!(
            result.turtle.contains("phScience:air")
                || result.turtle.contains(&format!("{PHSCIENCE_BASE}air"))
        );
        assert!(result.turtle.contains("ph:hasTag") || result.turtle.contains(HAS_TAG_IRI));
        assert!(
            result.turtle.contains("ph:unit") || result.turtle.contains(&format!("{PH_BASE}unit"))
        );
        assert!(
            result.turtle.contains("ph:dis") || result.turtle.contains(&format!("{PH_BASE}dis"))
        );
        assert!(result.turtle.contains("ahu1-sat") || result.turtle.contains("point/ahu1-sat"));
        assert!(!result
            .turtle
            .contains("https://project-haystack.org/def/ph#site"));
        assert_eq!(result.report.defs_pin, DEFS_PIN);
        assert_eq!(result.report.emitted_equips, 3);
        // SAT + MYSTERY_FLOW + CLG_VLV_CMD (ambiguity retained) + excluded aux retained
        assert_eq!(result.report.emitted_points, 4);
    }

    #[test]
    fn false_markers_and_unknown_tags_omitted() {
        let result = project_strict(&sample_meta(), Some(&sample_inventory()));
        assert!(!result.turtle.contains("vendorFooTag"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "false_or_null_marker"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "unknown_tag" && o.term.as_deref() == Some("vendorFooTag")));
    }

    #[test]
    fn ambiguity_and_exclusion_retain_semantic_points() {
        let result = project_strict(&sample_meta(), Some(&sample_inventory()));
        assert!(
            result.turtle.contains("CLG_VLV_CMD") || result.turtle.contains("point/CLG_VLV_CMD")
        );
        assert!(
            result.turtle.contains("INTENTIONALLY_EXCLUDED_AUX")
                || result.turtle.contains("fddExcluded")
        );
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "unknown_unit"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "ambiguous_role_unresolved_fdd"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "intentional_exclusion_fdd"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "unconfirmed_parent_relation"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "point_function_cardinality"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "missing_parent_ahu"));
    }

    #[test]
    fn parent_air_ref_requires_explicit_relation() {
        let mut meta = sample_meta();
        meta.equipment[2].parent_relation = Some("airRef".into());
        let result = project_strict(&meta, Some(&sample_inventory()));
        assert!(
            result.turtle.contains("airRef")
                || result.turtle.contains(&format!("{PHIOT_BASE}airRef"))
        );
        assert!(!result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "unconfirmed_parent_relation"
                && o.equipment_id.as_deref() == Some("VAV_EXCLUDED_1")));
    }

    #[test]
    fn trailing_dot_and_unicode_identity_roundtrip() {
        let meta: SemanticMetaV1 = serde_json::from_value(json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": "SITE.DOT",
            "equipment": [{
                "equipment_id": "AHU/1",
                "haystack_tags": ["ahu", "equip"],
                "display_name": "Quote \"and\" °F"
            }],
            "points": [{
                "equipment_id": "AHU/1",
                "column": "SAT.",
                "point_id": "pt:sat",
                "haystack_tags": ["point", "sensor", "temp"],
                "unit": "°F"
            }]
        }))
        .unwrap();
        let result = project_strict(&meta, None);
        assert!(
            result
                .report
                .omitted
                .iter()
                .all(|o| o.reason != "projection_error"),
            "{:?}",
            result.report.omitted
        );
        assert!(result.turtle.contains("enc_") || result.turtle.contains("AHU"));
        assert!(result.turtle.contains("°F") || result.turtle.contains("\\u"));
    }

    #[test]
    fn roles_alone_do_not_invent_points() {
        let meta: SemanticMetaV1 = serde_json::from_value(json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": "B1",
            "points": [],
            "equipment": [{"equipment_id": "AHU_1", "haystack_tags": ["ahu", "equip"]}]
        }))
        .unwrap();
        let inv = json!({
            "equipment": [{
                "equipment_id": "AHU_1",
                "equipment_type": "ahu",
                "roles": {"SAT": "sat", "RAT": "rat"},
                "ambiguous_roles": {},
                "columns": []
            }]
        });
        let result = project_strict(&meta, Some(&inv));
        assert_eq!(result.report.emitted_points, 0);
    }

    #[test]
    fn writes_independent_fixture_artifact() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
        let meta = root.join("scripts/fixtures/haystack_rdf/synthetic_point_metadata_v1.json");
        let inv = root.join("scripts/fixtures/haystack_rdf/synthetic_mapping_inventory.json");
        let out_dir = root.join("scripts/fixtures/haystack_rdf/generated");
        let ttl = out_dir.join("c3_projection.ttl");
        let report = out_dir.join("c3_projection_report.json");
        export_fixture_projection(&meta, Some(&inv), &ttl, &report).expect("export fixture");
        let body = std::fs::read_to_string(&ttl).unwrap();
        assert!(body.contains(PHIOT_BASE) || body.contains("phIoT:"));
        assert!(ttl.is_file());
    }
}
