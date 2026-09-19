//! Package mapping inventory → Turtle export (`openfdd_data_model_v2` sidecar).
//! Derived view only — never invents cookbook roles. Not on the FDD request path.

use serde_json::Value;

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

/// Stable ofdd IRI local-name segment (parity with SPA `turtleIriSegment`).
/// Safe ASCII that does not start with reserved `enc_` and does not contain `__`
/// passes through; otherwise reversible `enc_<utf8-hex>` (DM-01).
fn iri_segment(s: &str) -> String {
    let safe = s.bytes().all(|b| {
        b.is_ascii_alphanumeric() || b == b'.' || b == b'_' || b == b'-'
    }) && !s.starts_with("enc_")
        && !s.contains("__");
    if safe {
        return s.to_string();
    }
    format!("enc_{}", utf8_hex(s.as_bytes()))
}

fn building_subject(building_id: &str) -> String {
    format!("ofdd:b_{}", iri_segment(building_id))
}

fn equipment_subject(building_id: &str, equipment_id: &str) -> String {
    format!(
        "ofdd:eq_{}__{}",
        iri_segment(building_id),
        iri_segment(equipment_id)
    )
}

/// Build Turtle from the JSON returned by [`super::package::get_package_mapping_handler`].
pub fn package_mapping_to_turtle(inventory: &Value) -> String {
    let building_id = inventory
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("unknown");
    let b_subj = building_subject(building_id);
    let mut out = String::new();
    out.push_str("@prefix ofdd: <urn:openfdd:ns#> .\n");
    out.push_str("@prefix hs: <https://project-haystack.org/def/ph#> .\n");
    out.push_str("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n");
    out.push_str(&format!("{b_subj} a ofdd:Building ;\n"));
    out.push_str(&format!(
        "  ofdd:buildingId \"{}\" .\n\n",
        turtle_escape(building_id)
    ));

    let Some(equipment) = inventory.get("equipment").and_then(|v| v.as_array()) else {
        return out;
    };

    for eq in equipment {
        let eid_raw = eq
            .get("equipment_id")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty());
        let Some(eid_raw) = eid_raw else {
            continue;
        };
        let subj = equipment_subject(building_id, eid_raw);
        let eq_type = eq
            .get("equipment_type")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");

        out.push_str(&format!("{subj} a ofdd:Equipment ;\n"));
        out.push_str(&format!(
            "  ofdd:equipmentId \"{}\" ;\n",
            turtle_escape(eid_raw)
        ));
        out.push_str(&format!(
            "  ofdd:equipmentType \"{}\" ;\n",
            turtle_escape(eq_type)
        ));
        out.push_str(&format!("  ofdd:inBuilding {b_subj}"));

        if let Some(parent) = eq
            .get("parent_ahu")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            out.push_str(&format!(
                " ;\n  ofdd:parentAhu {}",
                equipment_subject(building_id, parent)
            ));
        }

        let mut bindings: Vec<(String, String)> = Vec::new();
        if let Some(roles) = eq.get("roles").and_then(|v| v.as_object()) {
            for (column, role_v) in roles {
                let role = role_v.as_str().map(str::trim).unwrap_or("");
                if role.is_empty() {
                    continue;
                }
                bindings.push((column.clone(), role.to_string()));
            }
        }
        bindings.sort_by(|a, b| a.0.cmp(&b.0));

        if bindings.is_empty() {
            out.push_str(" .\n\n");
        } else {
            for (i, (column, role)) in bindings.iter().enumerate() {
                let term = if i + 1 == bindings.len() { " ." } else { " ;" };
                out.push_str(&format!(
                    " ;\n  ofdd:roleBinding [ ofdd:role \"{}\" ; ofdd:column \"{}\" ]{term}",
                    turtle_escape(role),
                    turtle_escape(column)
                ));
            }
            out.push_str("\n\n");
        }

        if let Some(unmapped) = eq.get("unmapped_columns").and_then(|v| v.as_array()) {
            for col in unmapped {
                let Some(c) = col.as_str().map(str::trim).filter(|s| !s.is_empty()) else {
                    continue;
                };
                out.push_str(&format!(
                    "{subj} ofdd:unmappedColumn \"{}\" .\n",
                    turtle_escape(c)
                ));
            }
            if unmapped.iter().any(|c| {
                c.as_str()
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .is_some()
            }) {
                out.push('\n');
            }
        }
    }

    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn turtle_includes_prefix_and_ahu_role_not_phantom() {
        let inv = json!({
            "ok": true,
            "building_id": "B1",
            "equipment": [{
                "equipment_id": "AHU_1",
                "equipment_type": "AHU",
                "roles": { "SF_SPD": "fan_cmd" },
                "unmapped_columns": ["NOISE"]
            }]
        });
        let ttl = package_mapping_to_turtle(&inv);
        assert!(ttl.contains("@prefix ofdd:"));
        assert!(ttl.contains("ofdd:eq_B1__AHU_1"));
        assert!(ttl.contains("fan_cmd"));
        assert!(ttl.contains("SF_SPD"));
        assert!(ttl.contains("unmappedColumn"));
        assert!(!ttl.contains("duct_static"));
    }

    #[test]
    fn empty_roles_still_emit_equipment() {
        let inv = json!({
            "building_id": "X",
            "equipment": [{
                "equipment_id": "E1",
                "equipment_type": "AHU",
                "roles": {}
            }]
        });
        let ttl = package_mapping_to_turtle(&inv);
        assert!(ttl.contains("ofdd:eq_X__E1"));
        assert!(ttl.contains("ofdd:Equipment"));
    }

    #[test]
    fn dm01_enc_prefix_reserved() {
        assert_eq!(iri_segment("AHU 1"), "enc_4148552031");
        assert_ne!(iri_segment("enc_4148552031"), iri_segment("AHU 1"));
        assert!(iri_segment("enc_4148552031").starts_with("enc_"));
    }

    #[test]
    fn dm02_building_equip_tuple_unambiguous() {
        assert_ne!(
            equipment_subject("X_equip_Y", "Z"),
            equipment_subject("X", "Y_equip_Z")
        );
        assert_eq!(equipment_subject("X_equip_Y", "Z"), "ofdd:eq_X_equip_Y__Z");
        assert_eq!(equipment_subject("X", "Y_equip_Z"), "ofdd:eq_X__Y_equip_Z");
    }

    #[test]
    fn dm03_unmapped_only_equipment() {
        let inv = json!({
            "building_id": "B1",
            "equipment": [{
                "equipment_id": "ORPHAN",
                "equipment_type": "unknown",
                "roles": {},
                "unmapped_columns": ["RAW_X"]
            }]
        });
        let ttl = package_mapping_to_turtle(&inv);
        assert!(ttl.contains("ofdd:eq_B1__ORPHAN"));
        assert!(ttl.contains("unmappedColumn"));
        assert!(ttl.contains("RAW_X"));
    }

    #[test]
    fn historian_id_collision_keeps_distinct_subjects() {
        assert_ne!(iri_segment("AHU 1"), iri_segment("AHU_1"));
        assert_ne!(iri_segment("AHU:1"), iri_segment("AHU 1"));
        assert_eq!(iri_segment("AHU_1"), "AHU_1");
        assert_eq!(iri_segment("AHU 1"), "enc_4148552031");
        let inv = json!({
            "building_id": "B1",
            "equipment": [
                {"equipment_id": "AHU 1", "equipment_type": "AHU", "roles": {"A": "sat"}},
                {"equipment_id": "AHU_1", "equipment_type": "AHU", "roles": {"B": "fan_cmd"}},
            ]
        });
        let ttl = package_mapping_to_turtle(&inv);
        assert!(ttl.contains("ofdd:eq_B1__enc_4148552031"));
        assert!(ttl.contains("ofdd:eq_B1__AHU_1"));
    }

    #[test]
    fn non_ascii_iri_matches_spa_utf8_hex_contract() {
        assert_eq!(iri_segment("AHUé"), "enc_414855c3a9");
        let inv = json!({
            "building_id": "Café",
            "equipment": [{
                "equipment_id": "AHUé",
                "equipment_type": "AHU",
                "roles": { "SF_SPD": "fan_cmd" }
            }]
        });
        let ttl = package_mapping_to_turtle(&inv);
        assert!(ttl.contains(&format!(
            "ofdd:eq_{}__{}",
            iri_segment("Café"),
            iri_segment("AHUé")
        )));
    }
}
