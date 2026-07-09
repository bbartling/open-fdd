use std::collections::HashMap;
use std::path::Path;

use crate::error::Result;
use crate::role_rank::is_zone_t_limit_or_alarm_column;

/// Map physical CSV column name → cookbook logical role used by SQL rules.
pub fn load_column_role_map(path: &Path) -> Result<HashMap<String, String>> {
    let mut out = HashMap::new();
    let mut rdr = csv::Reader::from_path(path)?;
    let headers = rdr.headers()?.clone();
    let col_idx = header_index(&headers, &["col", "column"]);
    let role_idx = header_index(&headers, &["point_role", "role"]);
    if col_idx.is_none() {
        return Ok(out);
    }
    let col_idx = col_idx.unwrap();

    for rec in rdr.records() {
        let rec = rec?;
        let column = rec.get(col_idx).unwrap_or("").trim().to_string();
        if column.is_empty() || column == "col" || column == "column" {
            continue;
        }
        let raw_role = role_idx.and_then(|i| rec.get(i)).unwrap_or("").trim();
        let inferred = infer_role_from_column_name(&column);
        let role = if raw_role.is_empty() || raw_role == "ahu_point" {
            inferred
        } else {
            let normalized = normalize_role(raw_role);
            // Mis-tagged historian roles: prefer physical-name inference (Python ROLE_CANDIDATES).
            match (inferred.as_deref(), normalized.as_str()) {
                (Some("sat_sp"), "sat") => Some("sat_sp".into()),
                (Some("mat"), "ahu_point") | (Some("mat"), "ignore") => Some("mat".into()),
                (Some("oa_damper_pct"), _) if normalized == "ahu_point" => {
                    Some("oa_damper_pct".into())
                }
                (Some("clg_valve_pct"), _)
                    if normalized == "ahu_point" || normalized == "chw_valve" =>
                {
                    Some("clg_valve_pct".into())
                }
                (Some("zone_t"), "vav_point") => Some("zone_t".into()),
                _ => Some(normalized),
            }
        };
        let Some(role) = role else { continue };
        if role == "zone_t" && is_zone_t_limit_or_alarm_column(&column) {
            continue;
        }
        if role == "ahu_point" || role == "ignore" {
            continue;
        }
        // Prefer first mapping per role (supply fan before return fan, etc.)
        out.entry(column).or_insert(role);
    }
    Ok(out)
}

fn header_index(headers: &csv::StringRecord, names: &[&str]) -> Option<usize> {
    for (i, h) in headers.iter().enumerate() {
        let hl = h.trim().to_lowercase();
        if names.iter().any(|n| hl == *n) {
            return Some(i);
        }
    }
    None
}

/// Align columns.csv / Haystack role strings with SQL rule column names.
/// Mirrors Python ``cookbook_engine.ROLE_CANDIDATES`` RDF role aliases.
pub fn normalize_role(role: &str) -> String {
    match role.trim().to_lowercase().as_str() {
        "oat" | "outside_air_temp" | "outside_air_temp_f" | "weather_oat" => "oa_t".into(),
        "zone_temp" | "zone_temperature" | "space_temp" | "zn_t" | "zone_t" => "zone_t".into(),
        "supply_air_temp"
        | "supply_air_temperature"
        | "discharge_air_temp"
        | "discharge_air_temp_f"
        | "sat" => "sat".into(),
        "return_air_temp" | "return_air_temp_f" | "rat" | "ra_t" => "rat".into(),
        "mixed_air_temp" | "mixed_air_temp_f" | "mat" | "ma_t" => "mat".into(),
        "fan_speed"
        | "fan_pct"
        | "fan_percent"
        | "fan_cmd"
        | "supply_fan"
        | "supply_fan_speed"
        | "supply_fan_speed_pct" => "fan_cmd".into(),
        "fan_status" | "fan_proof" | "supply_fan_status" | "supply_fan_stat" => "fan_status".into(),
        "oa_damper" | "outside_air_damper" | "damper" | "oa_damper_pct" | "oa_damper_cmd"
        | "oa_damper_pos" => "oa_damper_pct".into(),
        "cooling_valve" | "cooling_cmd" | "clg_valve" | "chw_valve" | "clg_valve_pct"
        | "chw_valve_pct" | "cooling_valve_pct" => "clg_valve_pct".into(),
        "heating_valve" | "heating_cmd" | "htg_valve" | "htg_valve_pct" | "heating_valve_pct"
        | "hw_valve_pct" | "reheat_valve" => "htg_valve_pct".into(),
        "sat_setpoint" | "sat_sp" | "dat_reset" | "dat_reset_f" | "sat_sp_f" | "sat_setpoint_f" => {
            "sat_sp".into()
        }
        "duct_static" | "da_p_inwc" | "duct_static_inwc" => "duct_static".into(),
        "duct_static_sp" | "da_p_setpoint_inwc" | "duct_press_sp" => "duct_static_sp".into(),
        "chws_t" | "chw_supply" | "chwst" | "chws_t_f" | "chw_supply_t" => "chw_supply_t".into(),
        "chwr_t" | "chw_return" | "chwrt" | "chwr_t_f" | "chw_return_t" => "chw_return_t".into(),
        "hws_t" | "hw_supply" | "hwst" | "hws_t_f" | "hw_supply_t" => "hw_supply_t".into(),
        "hwr_t" | "hw_return" | "hwrt" | "hwr_t_f" | "hw_return_t" => "hw_return_t".into(),
        "oa_humidity" | "oa_h" | "relative_humidity_pct" | "oa_rh_pct" => "oa_h".into(),
        "cooling_setpoint" | "effective_setpoint" | "clg_stpt" => "sat_sp".into(),
        "occ_mode" | "occupancy" | "occupied" | "schedule" => "occ_mode".into(),
        "return_fan" => "return_fan".into(),
        other => other.to_string(),
    }
}

fn infer_role_from_column_name(column: &str) -> Option<String> {
    let c = column.to_lowercase();
    if c.contains("supply_fan_speed")
        || c.contains("supply_fan_status")
        || c == "supplyfan"
        || c.ends_with("sf-c")
        || c.contains("sf_s")
    {
        return Some(
            if c.contains("status") || c.contains("proof") || c.contains("stat") {
                "fan_status".into()
            } else {
                "fan_cmd".into()
            },
        );
    }
    if c.contains("outside_air_temp") || c.contains("oa_t") || c.ends_with("oa-t") {
        return Some("oa_t".into());
    }
    if c.contains("dry_bulb") || c.contains("drybulb") {
        return Some("oa_t".into());
    }
    if c.contains("sat_sp")
        || c.contains("sat_setpoint")
        || c.contains("dat_reset")
        || c.contains("cooling_setpoint")
        || c.contains("effective_setpoint")
    {
        return Some("sat_sp".into());
    }
    if c.contains("discharge_air") || c.starts_with("dat_") || c.contains(" da-t") {
        return Some("sat".into());
    }
    if c.contains("return_air") || c.contains("ra_t") || c.contains("ra-t") {
        return Some("rat".into());
    }
    if c.contains("mixed_air")
        || c.contains("ma_t")
        || c.contains("ma-t")
        || c == "mad_c"
        || c == "mad-c"
    {
        return Some("mat".into());
    }
    if c.contains("chw_valve") || c.contains("clg_valve") || c.contains("cooling_valve") {
        return Some("clg_valve_pct".into());
    }
    if c.contains("htg_valve") || c.contains("heating_valve") || c.contains("hhw_valve") {
        return Some("htg_valve_pct".into());
    }
    if c.contains("damper") || c.contains("dmpr") {
        return Some("oa_damper_pct".into());
    }
    if c.contains("zone_t") || c.contains("spacetemp") {
        if is_zone_t_limit_or_alarm_column(column) {
            return None;
        }
        return Some("zone_t".into());
    }
    if (c.contains("space_temp") || c.contains("room_temp") || c.contains("roomtemp"))
        && !is_zone_t_limit_or_alarm_column(column)
    {
        return Some("zone_t".into());
    }
    if c.contains("da_p") || c.contains("duct_static") {
        return Some(
            if c.contains("setpoint") || c.ends_with("_sp") || c.contains("_sp_") {
                "duct_static_sp".into()
            } else {
                "duct_static".into()
            },
        );
    }
    if c.contains("chws") || c.contains("chw_supply") {
        return Some("chw_supply_t".into());
    }
    if c.contains("chwr") || c.contains("chw_return") {
        return Some("chw_return_t".into());
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    #[test]
    fn normalize_oat_alias() {
        assert_eq!(normalize_role("outside_air_temp"), "oa_t");
        assert_eq!(normalize_role("supply_fan"), "fan_cmd");
        assert_eq!(normalize_role("fan_status"), "fan_status");
        assert_eq!(normalize_role("ra_t"), "rat");
    }

    #[test]
    fn load_building_style_columns_csv() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("columns.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(
            f,
            "col,point_name,unit,point_role,vav_id\n\
             supply_fan_speed_pct,SF-VFD,%,supply_fan,\n\
             outside_air_temp_f,OA-T,°F,outside_air_temp,\n\
             zone_t100_x,bld SpaceTemp,°F,zone_temp,VAV_1"
        )
        .unwrap();
        let map = load_column_role_map(&path).unwrap();
        assert_eq!(
            map.get("supply_fan_speed_pct"),
            Some(&"fan_cmd".to_string())
        );
        assert_eq!(map.get("outside_air_temp_f"), Some(&"oa_t".to_string()));
        assert_eq!(map.get("zone_t100_x"), Some(&"zone_t".to_string()));
    }

    #[test]
    fn dat_reset_maps_to_sat_sp_not_sat() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("columns.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(
            f,
            "col,point_name,unit,point_role\n\
             dat_reset_f,DAT Reset,°F,discharge_air_temp\n\
             discharge_air_temp_f,DA-T,°F,discharge_air_temp\n\
             chw_valve_pct,CHW Valve,%,chw_valve"
        )
        .unwrap();
        let map = load_column_role_map(&path).unwrap();
        assert_eq!(map.get("dat_reset_f"), Some(&"sat_sp".to_string()));
        assert_eq!(map.get("discharge_air_temp_f"), Some(&"sat".to_string()));
        assert_eq!(map.get("chw_valve_pct"), Some(&"clg_valve_pct".to_string()));
    }

    #[test]
    fn vav_space_temp_f_maps_zone_t_from_vav_point() {
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("columns.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(
            f,
            "col,point_name,unit,point_role,vav_id\n\
             space_temp_f_58,Alarm High,78,zone_temp,VAV_7\n\
             space_temp_f_77,SpaceTemp,°F,zone_temp,VAV_7\n\
             vav_7_space_temp_f,space temp,°F,vav_point,VAV_7"
        )
        .unwrap();
        let map = load_column_role_map(&path).unwrap();
        assert_eq!(map.get("vav_7_space_temp_f"), Some(&"zone_t".to_string()));
        assert!(!map.contains_key("space_temp_f_58"));
        assert_eq!(map.get("space_temp_f_77"), Some(&"zone_t".to_string()));
    }
}
