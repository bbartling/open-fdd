//! Building-scoped equipment type metadata persisted from package sidecars.
//!
//! Product cohorts use a recognized `equipType` / `equipment_type` stamp.
//! A missing or unrecognized stamp is unclassified. Equipment-id text is not a kind.

use std::collections::BTreeMap;
use std::path::Path;

use serde_json::{json, Value};

pub const EQUIPMENT_TYPES_FILE: &str = "equipment_types.json";
pub const EQUIPMENT_PARENTS_FILE: &str = "equipment_parents.json";

fn normalized_token(raw: &str) -> String {
    raw.chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

/// Canonical product equipment kind for a package stamp.
///
/// Keep this generic: BAS/vendor/site-specific aliases belong in preprocessors,
/// not in Open-FDD product code.
pub fn canonical_kind(raw: &str) -> Option<&'static str> {
    match normalized_token(raw).as_str() {
        // Unit ventilator = constant-volume AHU (same family as CV AHU).
        "ahu"
        | "airhandler"
        | "airhandlingunit"
        | "rtu"
        | "mau"
        | "doas"
        | "cvahu"
        | "vavahu"
        | "unitventilator"
        | "uv"
        | "erv"
        | "energyrecoveryventilator" => Some("ahu"),
        "vav" | "zoneterminal" => Some("vav"),
        // ZONE control: FCU (valve PID) + standalone DDC monitors — not AHU.
        "zoneother" | "zone" | "fcu" | "fancoil" | "fancoilunit" | "standaloneddc" | "ddczone"
        | "zoneddc" => Some("zone_other"),
        "vrf" => Some("vrf"),
        "chiller" | "chwplant" | "chilledwaterplant" => Some("chiller"),
        "coolingtower" | "tower" => Some("cooling_tower"),
        "boiler" | "hwplant" | "hotwaterplant" => Some("boiler"),
        "heatpump" | "hp" => Some("heatpump"),
        // Zone heat at the terminal (stamp), not an id-prefix guess.
        "baseboard" | "baseboardheat" => Some("baseboard"),
        "weather" => Some("weather"),
        // Electricity / utility meters (UTIL-* / SV-* / RCx metering).
        "meter" | "electricmeter" | "utilitymeter" | "powermeter" => Some("meter"),
        _ => None,
    }
}

/// Canonical kind from a package stamp.
///
/// `equipment_id` is unused. Missing and unrecognized stamps are `unknown`
/// and do not enter an AHU, VAV, plant, or weather cohort.
pub fn kind_for(_equipment_id: &str, stamped_type: Option<&str>) -> &'static str {
    stamped_type.and_then(canonical_kind).unwrap_or("unknown")
}

/// Zone-terminal kinds. Heat pumps are not in this set: plant and zone heat
/// pumps share `heatpump`, so a zone role is required (see `zone_comfort_member`).
pub fn is_zone_terminal_kind(kind: &str) -> bool {
    matches!(kind, "vav" | "zone_other" | "baseboard")
}

/// Zone-comfort membership from a package stamp plus a modeled zone role.
///
/// A recognized non-zone stamp excludes the equipment even when its id
/// contains `ZONE` or `VAV`. No recognized stamp includes the equipment only
/// when the caller has a modeled zone role (`has_zone_role`). A `heatpump`
/// stamp joins only with that role, so a plant heat pump is not a zone.
pub fn zone_comfort_member(stamped_type: Option<&str>, has_zone_role: bool) -> bool {
    match stamped_type.and_then(canonical_kind) {
        Some("heatpump") => has_zone_role,
        Some(kind) => is_zone_terminal_kind(kind),
        None => has_zone_role,
    }
}

/// Label for a Family Zones row. Uses the stamp. Role-only members are `Zone`
/// so equipment id text is not a type.
pub fn zone_comfort_type_label(stamped_type: Option<&str>) -> &'static str {
    if stamped_type.and_then(canonical_kind).is_some() {
        api_equipment_type_for("", stamped_type)
    } else {
        "Zone"
    }
}

/// `package` when the stamp is a recognized kind, otherwise `unclassified`.
pub fn equipment_type_source(stamped_type: Option<&str>) -> &'static str {
    if stamped_type.and_then(canonical_kind).is_some() {
        "package"
    } else {
        "unclassified"
    }
}

/// Display label for Overview inventory / devices-by-type tables.
pub fn api_equipment_type_for(equipment_id: &str, stamped_type: Option<&str>) -> &'static str {
    if let Some(raw) = stamped_type {
        match normalized_token(raw).as_str() {
            "zoneother" | "zone" => return "Zone Other",
            "fcu" | "fancoil" | "fancoilunit" => return "FCU",
            "standaloneddc" | "ddczone" | "zoneddc" => return "Zone DDC",
            "cvahu" | "unitventilator" | "uv" => return "CV AHU",
            "vavahu" => return "VAV AHU",
            "erv" | "energyrecoveryventilator" => return "ERV",
            "vrf" => return "VRF",
            _ => {}
        }
    }
    match kind_for(equipment_id, stamped_type) {
        "vav" => "VAV",
        "ahu" => "AHU",
        "chiller" | "boiler" | "cooling_tower" => "PLANT",
        "heatpump" => "HEAT_PUMP",
        "baseboard" => "Baseboard",
        "weather" => "WEATHER",
        "zone_other" => "Zone Other",
        "vrf" => "VRF",
        "meter" => "METER",
        _ => "GENERAL",
    }
}

/// Read a raw type stamp from any accepted package map shape.
pub fn stamped_type_from_map_json(map: &Value, equip_id: &str) -> Option<String> {
    fn from_block(block: &Value) -> Option<String> {
        for key in ["equipType", "equipment_type"] {
            if let Some(s) = block.get(key).and_then(Value::as_str).map(str::trim) {
                if !s.is_empty() {
                    return Some(s.to_string());
                }
            }
        }
        None
    }

    let obj = map.as_object()?;
    for key in ["equip", "equipment", "devices", "role_map"] {
        if let Some(blocks) = obj.get(key).and_then(Value::as_object) {
            if let Some(block) = blocks.get(equip_id) {
                if let Some(stamp) = from_block(block) {
                    return Some(stamp);
                }
            }
        }
    }
    from_block(map)
}

pub fn load_type_map(parquet_root: &Path, building_id: Option<&str>) -> BTreeMap<String, String> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return BTreeMap::new();
    };
    if bid.contains('/') || bid.contains('\\') || bid.contains("..") {
        return BTreeMap::new();
    }
    let path = parquet_root
        .join(format!("building={bid}"))
        .join(EQUIPMENT_TYPES_FILE);
    let Ok(text) = std::fs::read_to_string(path) else {
        return BTreeMap::new();
    };
    serde_json::from_str::<BTreeMap<String, String>>(&text).unwrap_or_default()
}

pub fn write_type_map(
    parquet_root: &Path,
    building_id: &str,
    types: &BTreeMap<String, String>,
) -> Result<(), String> {
    if types.is_empty() {
        return Ok(());
    }
    let dir = parquet_root.join(format!("building={building_id}"));
    std::fs::create_dir_all(&dir).map_err(|e| format!("mkdir {}: {e}", dir.display()))?;
    let body = serde_json::to_string_pretty(types).map_err(|e| e.to_string())?;
    std::fs::write(dir.join(EQUIPMENT_TYPES_FILE), body)
        .map_err(|e| format!("write equipment type registry: {e}"))
}

fn clean_equipment_id(raw: &str) -> Option<String> {
    let id = raw.trim();
    if id.is_empty()
        || id == "."
        || id == ".."
        || id.contains('/')
        || id.contains('\\')
        || id.contains(':')
    {
        return None;
    }
    if !id
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return None;
    }
    Some(id.to_string())
}

/// Parent AHU declared on a package map (`parentAhu` / `parent_ahu`).
///
/// Equipment-id text is not a parent. `VAV_2_AHU_1` has no parent unless the
/// map names one. A missing key returns `None`.
pub fn declared_parent_from_map_json(map: &Value, equip_id: &str) -> Option<String> {
    fn from_block(block: &Value) -> Option<String> {
        for key in ["parentAhu", "parent_ahu", "parentAHU"] {
            if let Some(s) = block.get(key).and_then(Value::as_str) {
                if let Some(id) = clean_equipment_id(s) {
                    return Some(id);
                }
            }
        }
        None
    }

    let obj = map.as_object()?;
    for key in ["equip", "equipment", "devices", "role_map"] {
        if let Some(blocks) = obj.get(key).and_then(Value::as_object) {
            if let Some(block) = blocks.get(equip_id) {
                if let Some(parent) = from_block(block) {
                    return Some(parent);
                }
            }
        }
    }
    from_block(map)
}

pub fn load_parent_map(parquet_root: &Path, building_id: Option<&str>) -> BTreeMap<String, String> {
    let Some(bid) = building_id.map(str::trim).filter(|s| !s.is_empty()) else {
        return BTreeMap::new();
    };
    if bid.contains('/') || bid.contains('\\') || bid.contains("..") {
        return BTreeMap::new();
    }
    let path = parquet_root
        .join(format!("building={bid}"))
        .join(EQUIPMENT_PARENTS_FILE);
    let Ok(text) = std::fs::read_to_string(path) else {
        return BTreeMap::new();
    };
    serde_json::from_str::<BTreeMap<String, String>>(&text)
        .unwrap_or_default()
        .into_iter()
        .filter_map(|(child, parent)| {
            let child = clean_equipment_id(&child)?;
            let parent = clean_equipment_id(&parent)?;
            if child == parent {
                return None;
            }
            Some((child, parent))
        })
        .collect()
}

pub fn write_parent_map(
    parquet_root: &Path,
    building_id: &str,
    parents: &BTreeMap<String, String>,
) -> Result<(), String> {
    let dir = parquet_root.join(format!("building={building_id}"));
    if parents.is_empty() {
        // A later package with no declared parents must not keep the previous
        // registry. `import_package_zip` rebuilds the package root and leaves
        // the parquet cache in place, and topology reads this file.
        return match std::fs::remove_file(dir.join(EQUIPMENT_PARENTS_FILE)) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => {
                Err(format!("remove stale equipment parent registry: {e}"))
            }
            _ => Ok(()),
        };
    }
    std::fs::create_dir_all(&dir).map_err(|e| format!("mkdir {}: {e}", dir.display()))?;
    let body = serde_json::to_string_pretty(parents).map_err(|e| e.to_string())?;
    std::fs::write(dir.join(EQUIPMENT_PARENTS_FILE), body)
        .map_err(|e| format!("write equipment parent registry: {e}"))
}

pub fn type_report(equipment_id: &str, stamped_type: Option<&str>) -> Value {
    json!({
        "equipment_id": equipment_id,
        "equipment_type": api_equipment_type_for(equipment_id, stamped_type),
        "equipment_type_raw": stamped_type,
        "equipment_type_source": equipment_type_source(stamped_type),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stamped_ahu_beats_unknown_folder_id() {
        assert_eq!(kind_for("AC_1", None), "unknown");
        assert_eq!(kind_for("jci_ahu_1", None), "unknown");
        assert_eq!(kind_for("jci_vav_1", None), "unknown");
        assert_eq!(kind_for("bldg2-zone-loopback", None), "unknown");
        assert_eq!(kind_for("AC_1", Some("ahu")), "ahu");
        assert_eq!(api_equipment_type_for("AC_1", Some("ahu")), "AHU");
        assert_eq!(kind_for("CHILLER_HEAT_PUMP", Some("chiller")), "chiller");
        assert_eq!(kind_for("AHU_1_VAV_12", Some("ahu")), "ahu");
        assert_eq!(equipment_type_source(None), "unclassified");
        assert_eq!(equipment_type_source(Some("not-a-kind")), "unclassified");
        assert_eq!(equipment_type_source(Some("vav")), "package");
    }

    #[test]
    fn zone_other_stamp_maps_to_display_label() {
        assert_eq!(canonical_kind("zone_other"), Some("zone_other"));
        assert_eq!(
            api_equipment_type_for("FEC_1", Some("zone_other")),
            "Zone Other"
        );
        assert_eq!(api_equipment_type_for("AC_1", Some("cv_ahu")), "CV AHU");
        assert_eq!(api_equipment_type_for("AC_2", Some("vrf")), "VRF");
    }

    #[test]
    fn zone_comfort_member_uses_stamp_or_role_not_id_text() {
        assert!(zone_comfort_member(Some("vav"), true));
        assert!(zone_comfort_member(Some("fcu"), true));
        assert!(zone_comfort_member(Some("fanCoil"), true));
        assert!(zone_comfort_member(Some("heatPump"), true));
        assert!(!zone_comfort_member(Some("heatPump"), false));
        assert!(zone_comfort_member(Some("baseboard"), true));
        assert!(zone_comfort_member(Some("zone_other"), true));
        assert!(zone_comfort_member(Some("standalone_ddc"), false));
        assert!(!zone_comfort_member(Some("ahu"), true));
        assert!(!zone_comfort_member(Some("ahu"), false));
        assert!(zone_comfort_member(None, true));
        assert!(!zone_comfort_member(None, false));
        assert_eq!(zone_comfort_type_label(Some("fcu")), "FCU");
        assert_eq!(zone_comfort_type_label(Some("heatPump")), "HEAT_PUMP");
        assert_eq!(zone_comfort_type_label(None), "Zone");
        assert_eq!(canonical_kind("baseboard"), Some("baseboard"));
        assert_eq!(
            api_equipment_type_for("BB_1", Some("baseboard")),
            "Baseboard"
        );
    }

    #[test]
    fn fcu_and_standalone_ddc_are_zone_not_ahu() {
        assert_eq!(canonical_kind("fcu"), Some("zone_other"));
        assert_eq!(canonical_kind("fanCoil"), Some("zone_other"));
        assert_eq!(canonical_kind("standalone_ddc"), Some("zone_other"));
        assert_eq!(api_equipment_type_for("FCU_1", Some("fcu")), "FCU");
        assert_eq!(
            api_equipment_type_for("ZONE_MON_1", Some("standalone_ddc")),
            "Zone DDC"
        );
        assert_ne!(kind_for("FCU_1", Some("fcu")), "ahu");
    }

    #[test]
    fn unit_ventilator_is_cv_ahu() {
        assert_eq!(canonical_kind("unitVentilator"), Some("ahu"));
        assert_eq!(canonical_kind("uv"), Some("ahu"));
        assert_eq!(
            api_equipment_type_for("UV_1", Some("unitVentilator")),
            "CV AHU"
        );
    }

    #[test]
    fn nested_map_reads_both_stamp_spellings() {
        let camel = json!({"equip": {"AC_1": {"equipType": "ahu", "points": {}}}});
        let snake = json!({"equipment": {"AC_2": {"equipment_type": "heatPump", "points": {}}}});
        assert_eq!(
            stamped_type_from_map_json(&camel, "AC_1").as_deref(),
            Some("ahu")
        );
        assert_eq!(
            stamped_type_from_map_json(&snake, "AC_2").as_deref(),
            Some("heatPump")
        );
    }

    #[test]
    fn declared_parent_is_map_metadata_not_id_text() {
        let bare = json!({"equipType": "vav", "points": {}});
        assert_eq!(declared_parent_from_map_json(&bare, "VAV_2_AHU_1"), None);
        assert_eq!(declared_parent_from_map_json(&bare, "VAV_9"), None);
        assert_eq!(
            declared_parent_from_map_json(&bare, "bldg2-zone-loopback"),
            None
        );
        let declared = json!({"equipType": "vav", "parentAhu": "AC_1", "points": {}});
        assert_eq!(
            declared_parent_from_map_json(&declared, "box_12").as_deref(),
            Some("AC_1")
        );
        let nested = json!({"equip": {"box_12": {"equipType": "vav", "parent_ahu": "AC_1"}}});
        assert_eq!(
            declared_parent_from_map_json(&nested, "box_12").as_deref(),
            Some("AC_1")
        );
        let junk = json!({"parentAhu": "AHU_1/../other"});
        assert_eq!(declared_parent_from_map_json(&junk, "box_12"), None);
        let prefix = json!({"parentAhu": "AHU_1"});
        assert_eq!(
            declared_parent_from_map_json(&prefix, "RTU_010").as_deref(),
            Some("AHU_1")
        );
    }

    #[test]
    fn write_parent_map_removes_stale_file_when_empty() {
        let root = std::env::temp_dir().join(format!("openfdd-parents-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let mut parents = BTreeMap::new();
        parents.insert("box_12".to_string(), "AC_1".to_string());
        write_parent_map(&root, "site_a", &parents).expect("write parents");
        let path = root.join("building=site_a").join(EQUIPMENT_PARENTS_FILE);
        assert!(path.is_file());
        assert_eq!(
            load_parent_map(&root, Some("site_a"))
                .get("box_12")
                .map(String::as_str),
            Some("AC_1")
        );
        write_parent_map(&root, "site_a", &BTreeMap::new()).expect("clear parents");
        assert!(!path.exists());
        assert!(load_parent_map(&root, Some("site_a")).is_empty());
        write_parent_map(&root, "site_a", &BTreeMap::new()).expect("missing file is success");
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn meter_stamp_is_required() {
        assert_eq!(canonical_kind("meter"), Some("meter"));
        assert_eq!(canonical_kind("electricMeter"), Some("meter"));
        assert_eq!(kind_for("CS_ELEC_METER", None), "unknown");
        assert_eq!(api_equipment_type_for("CS_ELEC_METER", None), "GENERAL");
        assert_eq!(api_equipment_type_for("MTR_1", Some("meter")), "METER");
        assert_eq!(kind_for("OA_REF", Some("weather")), "weather");
        assert_eq!(kind_for("jci_oat_sensor", None), "unknown");
    }
}
