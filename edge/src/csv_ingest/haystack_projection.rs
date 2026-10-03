//! Strict Haystack RDF projection (`ofdd_haystack_projection_v1`) — C3 (#1001).
//!
//! Authority is native `openfdd_semantic_meta_v1` only. SQL roles never invent
//! Haystack markers. Unknown tags/units and ambiguous/excluded columns are omitted
//! with a projection report (HR-03/04/05).

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use super::semantic_meta::{EquipmentMeta, PointMeta, SemanticMetaV1};

pub const PROFILE: &str = "ofdd_haystack_projection_v1";
pub const REPORT_SCHEMA: &str = "ofdd_haystack_projection_report_v1";
/// CI pin for the marker allowlist (not a full Project Haystack defs download).
pub const DEFS_PIN: &str = "ph-markers-allowlist-v1";

/// Marker tags accepted in strict projection (Project Haystack 4.x common markers).
const PINNED_MARKERS: &[&str] = &[
    "site", "equip", "point", "sensor", "cmd", "sp", "air", "water", "steam", "elec",
    "temp", "pressure", "flow", "humidity", "co2", "speed", "damper", "valve", "fan",
    "pump", "ahu", "vav", "chiller", "boiler", "supply", "return", "discharge",
    "outside", "zone", "leaving", "entering", "mixed",
];

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

fn turtle_escape(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
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

fn iri_segment(s: &str) -> String {
    let safe = s
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b'_' || b == b'-')
        && !s.starts_with("enc_")
        && !s.contains("__");
    if safe {
        return s.to_string();
    }
    format!("enc_{}", utf8_hex(s.as_bytes()))
}

fn site_subject(building_id: &str) -> String {
    format!("ofdd:site_{}", iri_segment(building_id))
}

fn equip_subject(building_id: &str, equipment_id: &str) -> String {
    format!(
        "ofdd:eq_{}__{}",
        iri_segment(building_id),
        iri_segment(equipment_id)
    )
}

fn point_subject(building_id: &str, equipment_id: &str, column: &str) -> String {
    format!(
        "ofdd:pt_{}__{}__{}",
        iri_segment(building_id),
        iri_segment(equipment_id),
        iri_segment(column)
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

fn is_pinned_marker(tag: &str) -> bool {
    PINNED_MARKERS
        .iter()
        .any(|p| p.eq_ignore_ascii_case(tag.trim()))
}

fn normalize_marker(tag: &str) -> String {
    tag.trim().to_ascii_lowercase()
}

/// Filter tags: drop false/null/empty; split pinned vs unknown.
fn classify_tags(raw: &[String], omitted: &mut Vec<ProjectionOmission>, equipment_id: &str, column: Option<&str>) -> Vec<String> {
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
        let norm = normalize_marker(tag);
        if is_pinned_marker(&norm) {
            if !out.iter().any(|t| t == &norm) {
                out.push(norm);
            }
        } else {
            omitted.push(ProjectionOmission {
                reason: "unknown_tag".into(),
                equipment_id: Some(equipment_id.to_string()),
                column: column.map(str::to_string),
                term: Some(tag.clone()),
                detail: Some(format!("not in {DEFS_PIN}")),
            });
        }
    }
    out
}

fn intentional_exclusion_columns(inventory: Option<&Value>) -> Vec<(String, String)> {
    let mut out = Vec::new();
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
            .unwrap_or_default();
        if let Some(cols) = eq.get("columns").and_then(|v| v.as_array()) {
            for col in cols {
                let status = col.get("status").and_then(|v| v.as_str()).unwrap_or("");
                let reason = col.get("exclusion_reason").and_then(|v| v.as_str());
                let name = col.get("column").and_then(|v| v.as_str()).unwrap_or("");
                if status == "excluded"
                    || reason.is_some()
                    || (name.contains("INTENTIONALLY_EXCLUDED") && status != "mapped")
                {
                    if !name.is_empty() {
                        out.push((eid.to_string(), name.to_string()));
                    }
                }
            }
        }
    }
    out
}

fn ambiguous_columns(inventory: Option<&Value>) -> Vec<(String, String)> {
    let mut out = Vec::new();
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
            .unwrap_or_default();
        if let Some(amb) = eq.get("ambiguous_roles").and_then(|v| v.as_object()) {
            for (_role, cols) in amb {
                if let Some(arr) = cols.as_array() {
                    for c in arr {
                        if let Some(col) = c.as_str() {
                            out.push((eid.to_string(), col.to_string()));
                        }
                    }
                }
            }
        }
    }
    out
}

fn missing_parent_equipment(inventory: Option<&Value>) -> Vec<String> {
    let mut out = Vec::new();
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
            .unwrap_or_default();
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
            out.push(eid.to_string());
        }
    }
    out
}

fn emit_resource(
    out: &mut String,
    subject: &str,
    class_marker: &str,
    tags: &[String],
    extra_lines: &[String],
) {
    out.push_str(&format!("{subject} a ph:{class_marker}"));
    let mut preds: Vec<String> = Vec::new();
    for tag in tags {
        preds.push(format!("  ph:hasTag ph:{tag}"));
    }
    for line in extra_lines {
        preds.push(format!("  {line}"));
    }
    if preds.is_empty() {
        out.push_str(" .\n\n");
        return;
    }
    out.push_str(" ;\n");
    for (i, p) in preds.iter().enumerate() {
        if i + 1 == preds.len() {
            out.push_str(&format!("{p} .\n\n"));
        } else {
            out.push_str(&format!("{p} ;\n"));
        }
    }
}

fn project_equipment(
    building_id: &str,
    site: &str,
    eq: &EquipmentMeta,
    omitted: &mut Vec<ProjectionOmission>,
    missing_parents: &[String],
) -> Option<(String, String)> {
    let eid = eq.equipment_id.trim();
    if eid.is_empty() {
        return None;
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
        return None;
    }
    if !tags.iter().any(|t| t == "equip") {
        // Require equip marker for equip resources when other tags present.
        omitted.push(ProjectionOmission {
            reason: "missing_equip_marker".into(),
            equipment_id: Some(eid.to_string()),
            column: None,
            term: None,
            detail: Some("pinned tags present but no equip marker — omitted".into()),
        });
        return None;
    }

    let subj = equip_subject(building_id, eid);
    let mut extras = vec![
        format!("ph:siteRef {site}"),
        format!("ofdd:equipmentId \"{}\"", turtle_escape(eid)),
    ];
    if let Some(name) = eq.display_name.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        extras.push(format!("ofdd:displayName \"{}\"", turtle_escape(name)));
    }
    if let Some(parent) = eq
        .parent_equip
        .as_deref()
        .map(str::trim)
        .filter(|s| !s.is_empty())
    {
        extras.push(format!(
            "ph:equipRef {}",
            equip_subject(building_id, parent)
        ));
    } else if missing_parents.iter().any(|m| m == eid) {
        omitted.push(ProjectionOmission {
            reason: "missing_parent_ahu".into(),
            equipment_id: Some(eid.to_string()),
            column: None,
            term: None,
            detail: Some("stamped VAV without confirmed parent — no containment edge".into()),
        });
    }

    let mut ttl = String::new();
    emit_resource(&mut ttl, &subj, "equip", &tags, &extras);
    Some((subj, ttl))
}

fn project_point(
    building_id: &str,
    pt: &PointMeta,
    equip_subjects: &std::collections::BTreeMap<String, String>,
    omitted: &mut Vec<ProjectionOmission>,
    excluded: &[(String, String)],
    ambiguous: &[(String, String)],
) -> Option<String> {
    let eid = pt.equipment_id.trim();
    let col = pt.column.trim();
    if eid.is_empty() || col.is_empty() {
        return None;
    }

    if excluded.iter().any(|(e, c)| e == eid && c == col) {
        omitted.push(ProjectionOmission {
            reason: "intentional_exclusion".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some("operator policy — not promoted to Haystack point".into()),
        });
        return None;
    }
    if ambiguous.iter().any(|(e, c)| e == eid && c == col) {
        omitted.push(ProjectionOmission {
            reason: "ambiguous_role".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some("no single-column promotion without selection evidence".into()),
        });
        return None;
    }

    let tags = classify_tags(&pt.haystack_tags, omitted, eid, Some(col));
    if !tags.iter().any(|t| t == "point") {
        omitted.push(ProjectionOmission {
            reason: "missing_point_marker".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some("points require pinned point marker".into()),
        });
        return None;
    }

    let Some(eq_subj) = equip_subjects.get(eid) else {
        omitted.push(ProjectionOmission {
            reason: "point_equip_not_projected".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: None,
            detail: Some("parent equipment absent from strict projection".into()),
        });
        return None;
    };

    let mut extras = vec![
        format!("ph:equipRef {eq_subj}"),
        format!("ofdd:column \"{}\"", turtle_escape(col)),
    ];

    let unit_unknown = pt
        .unit_status
        .as_deref()
        .map(|s| s.eq_ignore_ascii_case("unknown"))
        .unwrap_or(false)
        || pt.unit.as_deref() == Some("???");
    if unit_unknown {
        omitted.push(ProjectionOmission {
            reason: "unknown_unit".into(),
            equipment_id: Some(eid.to_string()),
            column: Some(col.to_string()),
            term: pt.unit.clone(),
            detail: Some("retained in native metadata only — not strict literal".into()),
        });
    } else if let Some(unit) = pt.unit.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        // Known units stay as ofdd annotation until full ph unit defs are pinned.
        extras.push(format!("ofdd:unit \"{}\"", turtle_escape(unit)));
    }

    let subj = point_subject(building_id, eid, col);
    let mut ttl = String::new();
    emit_resource(&mut ttl, &subj, "point", &tags, &extras);
    Some(ttl)
}

/// Project native semantic metadata to strict Haystack Turtle + report.
///
/// Optional `inventory` supplies HR-05 diagnostics (ambiguity / exclusions /
/// missing parent). Roles never become Haystack tags.
pub fn project_strict(meta: &SemanticMetaV1, inventory: Option<&Value>) -> ProjectionResult {
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

    // Never invent tags from inventory SQL roles.
    if let Some(inv) = inventory {
        if let Some(equipment) = inv.get("equipment").and_then(|v| v.as_array()) {
            for eq in equipment {
                let eid = eq
                    .get("equipment_id")
                    .and_then(|v| v.as_str())
                    .unwrap_or_default();
                if let Some(roles) = eq.get("roles").and_then(|v| v.as_object()) {
                    for (column, _role) in roles {
                        let in_meta = meta.points.iter().any(|p| {
                            p.equipment_id == eid && p.column == *column
                        });
                        if !in_meta {
                            // Silent: roles without native tags are not Haystack points.
                            let _ = column;
                        }
                    }
                }
            }
        }
    }

    let site = site_subject(building_id);
    let mut turtle = String::new();
    turtle.push_str("@prefix ph: <https://project-haystack.org/def/ph#> .\n");
    turtle.push_str("@prefix ofdd: <urn:openfdd:ns#> .\n");
    turtle.push_str("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n");
    turtle.push_str(&format!(
        "# profile={PROFILE} defs_pin={DEFS_PIN}\n\n"
    ));

    let site_tags = vec!["site".to_string()];
    emit_resource(
        &mut turtle,
        &site,
        "site",
        &site_tags,
        &[format!(
            "ofdd:buildingId \"{}\"",
            turtle_escape(building_id)
        )],
    );

    let mut equip_subjects = std::collections::BTreeMap::new();
    let mut emitted_equips = 0usize;
    for eq in &meta.equipment {
        if let Some((subj, chunk)) =
            project_equipment(building_id, &site, eq, &mut omitted, &missing_parents)
        {
            equip_subjects.insert(eq.equipment_id.clone(), subj);
            turtle.push_str(&chunk);
            emitted_equips += 1;
        }
    }

    let mut emitted_points = 0usize;
    for pt in &meta.points {
        if let Some(chunk) = project_point(
            building_id,
            pt,
            &equip_subjects,
            &mut omitted,
            &excluded,
            &ambiguous,
        ) {
            turtle.push_str(&chunk);
            emitted_points += 1;
        }
    }

    let report = ProjectionReport {
        schema: REPORT_SCHEMA.to_string(),
        profile: PROFILE.to_string(),
        defs_pin: DEFS_PIN.to_string(),
        building_id: building_id.to_string(),
        emitted_sites: 1,
        emitted_equips,
        emitted_points,
        omitted,
    };

    ProjectionResult { turtle, report }
}

/// JSON envelope for API / agents.
pub fn project_strict_json(meta: &SemanticMetaV1, inventory: Option<&Value>) -> Value {
    let result = project_strict(meta, inventory);
    json!({
        "ok": true,
        "profile": PROFILE,
        "defs_pin": DEFS_PIN,
        "building_id": result.report.building_id,
        "turtle": result.turtle,
        "report": result.report,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn sample_meta() -> SemanticMetaV1 {
        serde_json::from_value(json!({
            "schema": "openfdd_semantic_meta_v1",
            "building_id": "OPENFDD_SYNTHETIC_HAYSTACK_RDF_C1_V1",
            "points": [
                {
                    "equipment_id": "AHU_CASE_1",
                    "column": "SAT",
                    "haystack_tags": ["sensor", "point", "air", "supply", "temp", "false", ""],
                    "unit": "°F",
                    "unit_source": "package_map"
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

    fn sample_inventory() -> Value {
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

    #[test]
    fn strict_emits_site_equip_and_known_point() {
        let result = project_strict(&sample_meta(), Some(&sample_inventory()));
        assert!(result.turtle.contains("a ph:site"));
        assert!(result.turtle.contains("a ph:equip"));
        assert!(result.turtle.contains("a ph:point"));
        assert!(result.turtle.contains("ph:hasTag ph:sensor"));
        assert!(result.turtle.contains("ofdd:column \"SAT\""));
        assert!(result.turtle.contains("ofdd:unit \"°F\""));
        assert_eq!(result.report.emitted_points, 2); // SAT + MYSTERY_FLOW (no unit)
        assert_eq!(result.report.emitted_equips, 3);
    }

    #[test]
    fn false_markers_and_unknown_tags_omitted() {
        let result = project_strict(&sample_meta(), Some(&sample_inventory()));
        assert!(!result.turtle.contains("ph:hasTag ph:false"));
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
    fn unknown_unit_and_ambiguous_and_exclusion() {
        let result = project_strict(&sample_meta(), Some(&sample_inventory()));
        // Unknown unit → point may emit without typed unit literal.
        assert!(result.turtle.contains("MYSTERY_FLOW"));
        assert!(!result.turtle.contains("ofdd:unit \"???\""));
        assert!(!result.turtle.contains("CLG_VLV_CMD"));
        assert!(!result.turtle.contains("INTENTIONALLY_EXCLUDED_AUX"));
        assert_eq!(result.report.emitted_points, 2); // SAT + MYSTERY_FLOW
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "unknown_unit"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "ambiguous_role"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "intentional_exclusion"));
        assert!(result
            .report
            .omitted
            .iter()
            .any(|o| o.reason == "missing_parent_ahu"));
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
        assert!(!result.turtle.contains("ofdd:column \"SAT\""));
    }
}
