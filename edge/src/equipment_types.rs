//! Building-scoped equipment type metadata persisted from package sidecars.
//!
//! Product code prefers an explicit `equipType` / `equipment_type` stamp when
//! present and falls back to vendor-neutral equipment-id heuristics otherwise.

use std::collections::BTreeMap;
use std::path::Path;

use serde_json::{json, Value};

pub const EQUIPMENT_TYPES_FILE: &str = "equipment_types.json";

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
        "ahu" | "airhandler" | "airhandlingunit" | "rtu" | "mau" | "doas" | "fcu" => Some("ahu"),
        "vav" | "zoneterminal" => Some("vav"),
        "chiller" | "chwplant" | "chilledwaterplant" => Some("chiller"),
        "coolingtower" | "tower" => Some("cooling_tower"),
        "boiler" | "hwplant" | "hotwaterplant" => Some("boiler"),
        "heatpump" | "hp" => Some("heatpump"),
        "weather" => Some("weather"),
        _ => None,
    }
}

pub fn infer_kind_from_id(equipment_id: &str) -> &'static str {
    let id = equipment_id.to_ascii_uppercase().replace('\\', "/");
    if id.contains("WEATHER") {
        "weather"
    } else if id.contains("VAV") || id.contains("ZONE") {
        "vav"
    } else if id.contains("AHU") || id.contains("RTU") || id.contains("MAU") || id.contains("DOAS")
    {
        "ahu"
    } else if id.contains("CHILL") || id.contains("CHLR") || id.starts_with("CHW") {
        "chiller"
    } else if id.contains("TOWER") || id.starts_with("CT_") || id.contains("/CT_") {
        "cooling_tower"
    } else if id.contains("BOILER") {
        "boiler"
    } else if id.starts_with("HP_") || id.contains("HEAT_PUMP") || id.contains("HEATPUMP") {
        "heatpump"
    } else {
        "unknown"
    }
}

/// Prefer stamped package type; fall back to generic id inference.
pub fn kind_for(equipment_id: &str, stamped_type: Option<&str>) -> &'static str {
    stamped_type
        .and_then(canonical_kind)
        .unwrap_or_else(|| infer_kind_from_id(equipment_id))
}

pub fn api_equipment_type_for(equipment_id: &str, stamped_type: Option<&str>) -> &'static str {
    match kind_for(equipment_id, stamped_type) {
        "vav" => "VAV",
        "ahu" => "AHU",
        "chiller" | "boiler" | "cooling_tower" => "PLANT",
        "heatpump" => "HEAT_PUMP",
        "weather" => "WEATHER",
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

pub fn type_report(equipment_id: &str, stamped_type: Option<&str>) -> Value {
    json!({
        "equipment_id": equipment_id,
        "equipment_type": api_equipment_type_for(equipment_id, stamped_type),
        "equipment_type_raw": stamped_type,
        "equipment_type_source": if stamped_type.and_then(canonical_kind).is_some() { "package" } else { "id" },
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stamped_ahu_beats_unknown_folder_id() {
        assert_eq!(infer_kind_from_id("AC_1"), "unknown");
        assert_eq!(kind_for("AC_1", Some("ahu")), "ahu");
        assert_eq!(api_equipment_type_for("AC_1", Some("ahu")), "AHU");
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
}
