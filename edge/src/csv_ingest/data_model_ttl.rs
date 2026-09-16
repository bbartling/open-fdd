//! Package mapping inventory → Turtle export (`openfdd_data_model_v1` sidecar).
//! Derived view only — never invents cookbook roles. Not on the FDD request path.

use serde_json::Value;

fn turtle_escape(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
}

fn iri_segment(s: &str) -> String {
    s.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

/// Build Turtle from the JSON returned by [`super::package::get_package_mapping_handler`].
pub fn package_mapping_to_turtle(inventory: &Value) -> String {
    let building_id = inventory
        .get("building_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .unwrap_or("unknown");
    let bid = iri_segment(building_id);
    let mut out = String::new();
    out.push_str("@prefix ofdd: <urn:openfdd:ns#> .\n");
    out.push_str("@prefix hs: <https://project-haystack.org/def/ph#> .\n");
    out.push_str("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n");
    out.push_str(&format!("ofdd:building_{bid} a ofdd:Building ;\n"));
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
        let eid = iri_segment(eid_raw);
        let subj = format!("ofdd:building_{bid}_equip_{eid}");
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
        out.push_str(&format!("  ofdd:inBuilding ofdd:building_{bid}"));

        if let Some(parent) = eq
            .get("parent_ahu")
            .and_then(|v| v.as_str())
            .map(str::trim)
            .filter(|s| !s.is_empty())
        {
            out.push_str(&format!(
                " ;\n  ofdd:parentAhu ofdd:building_{bid}_equip_{}",
                iri_segment(parent)
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
        assert!(ttl.contains("ofdd:building_B1_equip_AHU_1"));
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
        assert!(ttl.contains("ofdd:building_X_equip_E1"));
        assert!(ttl.contains("ofdd:Equipment"));
    }
}
