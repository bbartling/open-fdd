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
            let normalized = haystack_point_to_role(raw_role);
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
                (Some(inferred_role), "vav_point") => Some(inferred_role.to_string()),
                (Some("min_flow_sp"), "zone_flow") => Some("min_flow_sp".into()),
                // Historian `other` (CHILLER_2 command/amps) — pandas COL_PATTERN_ROLES
                // still maps physical names; do not keep a useless `other` parquet col.
                (Some(inferred_role), "other") => Some(inferred_role.to_string()),
                (None, "other") => None,
                _ => Some(normalized),
            }
        };
        let Some(role) = role else { continue };
        if role == "zone_t" && is_zone_t_limit_or_alarm_column(&column) {
            continue;
        }
        if role == "ahu_point" || role == "ignore" || role == "vav_point" {
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

/// Project-Haystack-style point tags (kebab or snake) → SQL cookbook roles.
/// Same mapping as package ZIP ingest so `fdd_cli ingest` of synthetic fixtures
/// produces `fan_status` / `zone_t` / `duct_static` columns, not `fan-status`.
pub fn haystack_point_to_role(point: &str) -> String {
    let slug = point.trim().to_lowercase().replace([' ', '_'], "-");
    match slug.as_str() {
        "discharge-air-temp" => "sat".into(),
        "discharge-air-temp-sp" => "sat_sp".into(),
        "mixed-air-temp" => "mat".into(),
        "return-air-temp" => "rat".into(),
        "outside-air-temp" | "bas-outside-air-temp" => "oa_t".into(),
        "outside-air-humidity" => "oa_h".into(),
        "outside-air-damper" => "oa_damper_pct".into(),
        "cooling-valve" => "clg_valve_pct".into(),
        "heating-valve" => "htg_valve_pct".into(),
        "fan-cmd" => "fan_cmd".into(),
        "return-fan-cmd" => "return_fan".into(),
        "fan-status" => "fan_status".into(),
        "duct-static-pressure" => "duct_static".into(),
        "duct-static-pressure-sp" => "duct_static_sp".into(),
        "vav-pressure-request-sum" | "static-reset-request" => "static_reset_request".into(),
        "cooling-coil-entering-temp" => "cooling_coil_entering_temp".into(),
        "cooling-coil-leaving-temp" => "cooling_coil_leaving_temp".into(),
        "heating-coil-entering-temp" => "heating_coil_entering_temp".into(),
        "heating-coil-leaving-temp" => "heating_coil_leaving_temp".into(),
        "chiller-status" => "chiller_status".into(),
        "loop-enabled" => "loop_enabled".into(),
        "zone-air-temp" => "zone_t".into(),
        "zone-airflow" | "airflow" => "zone_flow".into(),
        "vav-total-airflow" => "vav_total_flow".into(),
        "min-flow-sp" => "min_flow_sp".into(),
        "chw-pump-status" => "chw_pump_status".into(),
        "compressor-status" => "compressor_status".into(),
        "building-zone-load-satisfied" => "building_zone_load_satisfied".into(),
        "building-ahu-load-satisfied" => "building_ahu_load_satisfied".into(),
        "damper" => "damper_pct".into(),
        "reheat-valve" => "reheat_valve_pct".into(),
        "vav-discharge-air-temp" => "vav_discharge_t".into(),
        "vav-inlet-air-temp" => "vav_inlet_t".into(),
        "ahu-discharge-air-temp" => "ahu_sat".into(),
        "chilled-water-supply-temp" => "chw_supply_t".into(),
        "chilled-water-return-temp" => "chw_return_t".into(),
        "chilled-water-supply-temp-sp" => "chw_supply_sp".into(),
        "hot-water-supply-temp" => "hw_supply_t".into(),
        "hot-water-return-temp" => "hw_return_t".into(),
        "occupied" => "occ_mode".into(),
        "chw-diff-pressure" => "chw_dp".into(),
        "chw-diff-pressure-sp" => "chw_dp_sp".into(),
        "chw-flow" => "chw_flow".into(),
        "chw-pump-cmd" => "chw_pump_cmd".into(),
        "cw-pump-cmd" => "cw_pump_cmd".into(),
        "tower-fan-cmd" | "cw-fan-cmd" => "tower_fan_cmd".into(),
        "condenser-water-supply-temp" => "cw_supply_t".into(),
        "condenser-water-return-temp" => "cw_return_t".into(),
        "preheat-leaving-temp" => "preheat_leave_t".into(),
        "web-outside-air-temp" => "web_oa_t".into(),
        "web-outside-air-dewpoint" => "web_oa_dp".into(),
        "web-outside-air-wetbulb" => "web_wb_t".into(),
        "web-outside-air-humidity" => "web_oa_h".into(),
        "chiller-power" | "power" => "chiller_power".into(),
        "chiller-amps" => "chiller_amps".into(),
        "chiller-current" => "chiller_current".into(),
        "pump-status" => "pump_status".into(),
        other => normalize_role(&other.replace('-', "_")),
    }
}

/// Align columns.csv / Haystack role strings with SQL rule column names.
/// Mirrors Python ``cookbook_engine.ROLE_CANDIDATES`` RDF role aliases.
pub fn normalize_role(role: &str) -> String {
    match role.trim().to_lowercase().as_str() {
        "oat" | "outside_air_temp" | "outside_air_temp_f" | "weather_oat" | "oa_temp" => {
            "oa_t".into()
        }
        "zone_temp" | "zone_temperature" | "space_temp" | "zn_t" | "zone_t" => "zone_t".into(),
        "supply_air_temp"
        | "supply_air_temperature"
        | "discharge_air_temp"
        | "discharge_air_temp_f"
        | "sat" => "sat".into(),
        // Keep web_oa_t as identity (mech_oat / econ3/6/7 SQL require that column name).
        // Liberty economizer historian accepts web_oa_t as an oa_t alias in historian.rs.
        "return_air_temp" | "return_air_temp_f" | "rat" | "ra_t" | "web_ra_t" | "web_rat"
        | "return_air_t" => "rat".into(),
        "mixed_air_temp" | "mixed_air_temp_f" | "mat" | "ma_t" | "web_mat" | "web_ma_t"
        | "mixed_air_t" => "mat".into(),
        "fan_speed"
        | "fan_pct"
        | "fan_percent"
        | "fan_cmd"
        | "supply_fan"
        | "supply_fan_speed"
        | "supply_fan_speed_pct" => "fan_cmd".into(),
        "fan_status" | "fan_proof" | "supply_fan_status" | "supply_fan_stat" => "fan_status".into(),
        "oa_damper" | "outside_air_damper" | "oa_damper_pct" | "oa_damper_cmd"
        | "oa_damper_pos" => "oa_damper_pct".into(),
        "damper" | "zone_damper" | "vav_damper" | "damper_pct" | "damper_pos" => {
            "damper_pct".into()
        }
        "cooling_valve" | "cooling_cmd" | "clg_valve" | "chw_valve" | "clg_valve_pct"
        | "chw_valve_pct" | "cooling_valve_pct" => "clg_valve_pct".into(),
        "heating_valve" | "heating_cmd" | "htg_valve" | "htg_valve_pct" | "heating_valve_pct"
        | "hw_valve_pct" => "htg_valve_pct".into(),
        "reheat_valve" | "reheat_valve_pct" | "rht_valve" => "reheat_valve_pct".into(),
        "sat_setpoint" | "sat_sp" | "dat_reset" | "dat_reset_f" | "sat_sp_f" | "sat_setpoint_f" => {
            "sat_sp".into()
        }
        "duct_static" | "da_p_inwc" | "duct_static_inwc" => "duct_static".into(),
        "duct_static_sp" | "da_p_setpoint_inwc" | "duct_press_sp" => "duct_static_sp".into(),
        "vav_pressure_request_sum" | "static_reset_request" => "static_reset_request".into(),
        "cooling_coil_entering_temp" | "ccet" => "cooling_coil_entering_temp".into(),
        "cooling_coil_leaving_temp" | "cclt" => "cooling_coil_leaving_temp".into(),
        "heating_coil_entering_temp" | "hcet" => "heating_coil_entering_temp".into(),
        "heating_coil_leaving_temp" | "hclt" => "heating_coil_leaving_temp".into(),
        "chiller_status" | "chiller_proof" => "chiller_status".into(),
        "vav_total_airflow" | "vav_total_flow" | "total_airflow" | "ahu_total_airflow" => {
            "vav_total_flow".into()
        }
        "airflow" | "actflow" | "flow_input" | "zone_flow" | "zone_airflow" => "zone_flow".into(),
        "min_flow_sp" | "minflowsp" | "min_airflow" => "min_flow_sp".into(),
        "loop_enabled" | "pid_enable" => "loop_enabled".into(),
        "chws_t" | "chw_supply" | "chwst" | "chws_t_f" | "chw_supply_t" => "chw_supply_t".into(),
        "chwr_t" | "chw_return" | "chwrt" | "chwr_t_f" | "chw_return_t" => "chw_return_t".into(),
        "power" | "chiller_power" => "chiller_power".into(),
        "chiller_amps" | "chiller_amp" => "chiller_amps".into(),
        "chiller_current" => "chiller_current".into(),
        "pump_status" => "pump_status".into(),
        "hws_t" | "hw_supply" | "hwst" | "hws_t_f" | "hw_supply_t" => "hw_supply_t".into(),
        "hwr_t" | "hw_return" | "hwrt" | "hwr_t_f" | "hw_return_t" => "hw_return_t".into(),
        "oa_humidity" | "oa_h" | "relative_humidity_pct" | "oa_rh_pct" => "oa_h".into(),
        "cooling_setpoint" | "effective_setpoint" | "clg_stpt" => "sat_sp".into(),
        "occ_mode" | "occupancy" | "occupied" | "schedule" => "occ_mode".into(),
        "return_fan" => "return_fan".into(),
        other => other.to_string(),
    }
}

/// Canonical SQL cookbook roles (identity mapping + Data Model Select catalog).
pub const COOKBOOK_ROLES: &[&str] = &[
    "fan_cmd",
    "fan_status",
    "sat",
    "sat_sp",
    "oa_t",
    "rat",
    "mat",
    "web_oa_t",
    "web_oa_dp",
    "duct_static",
    "duct_static_sp",
    "oa_damper_pct",
    "damper_pct",
    "clg_valve_pct",
    "htg_valve_pct",
    "reheat_valve_pct",
    "zone_t",
    "zone_flow",
    "vav_total_flow",
    "min_flow_sp",
    "chiller_status",
    "chw_pump_status",
    "chw_pump_cmd",
    "building_zone_load_satisfied",
    "building_ahu_load_satisfied",
    "chw_supply_t",
    "chw_return_t",
    "chiller_power",
    "chiller_amps",
    "chiller_current",
    "pump_status",
    "hw_supply_t",
    "hw_return_t",
    "oa_h",
    "occ_mode",
    "return_fan",
];

/// Cookbook roles that may appear as literal CSV column names (identity mapping).
pub fn is_known_cookbook_role(role: &str) -> bool {
    matches!(
        role,
        "fan_cmd"
            | "fan_status"
            | "sat"
            | "sat_sp"
            | "oa_t"
            | "rat"
            | "mat"
            | "web_oa_t"
            | "web_oa_dp"
            | "duct_static"
            | "duct_static_sp"
            | "oa_damper_pct"
            | "damper_pct"
            | "clg_valve_pct"
            | "htg_valve_pct"
            | "reheat_valve_pct"
            | "zone_t"
            | "zone_flow"
            | "min_flow_sp"
            | "chw_supply_t"
            | "chw_return_t"
            | "chiller_power"
            | "chiller_amps"
            | "chiller_current"
            | "pump_status"
            | "hw_supply_t"
            | "hw_return_t"
            | "oa_h"
            | "occ_mode"
            | "return_fan"
    )
}

/// Full catalog for Data Model role Select (known roles + common extras).
pub fn cookbook_role_catalog() -> Vec<&'static str> {
    let mut out: Vec<&'static str> = COOKBOOK_ROLES.to_vec();
    out.sort_unstable();
    out.dedup();
    out
}

fn infer_role_from_column_name(column: &str) -> Option<String> {
    let c = column.to_lowercase();
    // Identity: column already named a canonical cookbook role (e.g. fan_cmd).
    // Without this, blank columns.csv roles silently drop the column at parquet ingest.
    let as_role = normalize_role(&c);
    if is_known_cookbook_role(&as_role) {
        return Some(as_role);
    }
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
        // Preserve first-class web_oa_t role for mech_oat / econ SQL (do not collapse to oa_t).
        if c == "web_oa_t" || c == "web_oat" || c.starts_with("web_oa_t") {
            return Some("web_oa_t".into());
        }
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
    if c.contains("return_air")
        || c.contains("ra_t")
        || c.contains("ra-t")
        || c.starts_with("web_ra")
        || c.starts_with("web_rat")
    {
        return Some("rat".into());
    }
    // Mixed-air *damper command* (mad_c) is OA damper, not mixed-air temperature.
    // Mapping mad_c → mat made ingest drop the explicit oa_damper_pct role or
    // lose the race to ex_dmpr_pos_fan_enable_pct (B100 ECON hours).
    if c == "mad_c" || c == "mad-c" || c == "mad_c_pct" || c.contains("mixed_air_damper") {
        return Some("oa_damper_pct".into());
    }
    if c.contains("mixed_air")
        || c.contains("ma_t")
        || c.contains("ma-t")
        || c.starts_with("web_ma")
        || c == "web_mat"
    {
        return Some("mat".into());
    }
    if c.contains("chw_valve") || c.contains("clg_valve") || c.contains("cooling_valve") {
        return Some("clg_valve_pct".into());
    }
    if c.contains("htg_valve") || c.contains("heating_valve") || c.contains("hhw_valve") {
        return Some("htg_valve_pct".into());
    }
    if c.contains("damper")
        || c.contains("dmpr")
        || c.contains("dpr_pos")
        || c.contains("vavactuator")
    {
        // Fan-enable / min-OA setpoints are not a damper command.
        if c.contains("enable")
            || c.contains("minimum")
            || c.contains("min_pos")
            || c.contains("minpos")
        {
            return None;
        }
        // OA / mixed-air damper stays oa_damper_pct (mad_c handled above).
        if c.contains("ex_dmpr")
            || c.contains("oa_damper")
            || c.contains("outdoor_air")
            || c.contains("mixed_air_damper")
            || c.contains("oad_")
        {
            return Some("oa_damper_pct".into());
        }
        // Zone / VAV damper — never treat generic damper as OA (pandas role_map).
        return Some("damper_pct".into());
    }
    if c.contains("actflow")
        || c.contains("flow_input")
        || (c.contains("airflow") && !c.contains("min") && !c.contains("max") && !c.contains("sp"))
    {
        return Some("zone_flow".into());
    }
    if c.contains("minflowsp") || (c.contains("min") && c.contains("airflow")) {
        return Some("min_flow_sp".into());
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
    if c.contains("dew_point") || c.contains("dewpoint") {
        return Some("web_oa_dp".into());
    }
    // Pandas COL_PATTERN_ROLES: chiller_N_command → status, chiller_N_amps → amps.
    if c.contains("chiller") && c.contains("command") {
        return Some("chiller_status".into());
    }
    if (c.contains("chiller") && c.contains("amps")) || c.ends_with("amps_a") {
        return Some("chiller_amps".into());
    }
    if c.contains("power_demand_this_interval") || c.contains("meter_power_sum") {
        return Some("chiller_power".into());
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
        assert_eq!(haystack_point_to_role("fan-status"), "fan_status");
        assert_eq!(haystack_point_to_role("zone-air-temp"), "zone_t");
        assert_eq!(
            haystack_point_to_role("duct-static-pressure"),
            "duct_static"
        );
        assert_eq!(haystack_point_to_role("web-outside-air-temp"), "web_oa_t");
        assert_eq!(haystack_point_to_role("fan_cmd"), "fan_cmd");
    }

    #[test]
    fn liberty_web_prefixed_econ_roles_normalize() {
        // OFDD-070: web_oa_t stays first-class (mech_oat/econ SQL); rat/mat aliases map.
        assert_eq!(normalize_role("duct_static"), "duct_static");
        assert_eq!(
            normalize_role("vav_pressure_request_sum"),
            "static_reset_request"
        );
        assert_eq!(normalize_role("web_oa_t"), "web_oa_t");
        assert_eq!(normalize_role("oa_temp"), "oa_t");
        assert_eq!(normalize_role("web_ra_t"), "rat");
        assert_eq!(normalize_role("web_rat"), "rat");
        assert_eq!(normalize_role("return_air_t"), "rat");
        assert_eq!(normalize_role("web_mat"), "mat");
        assert_eq!(normalize_role("web_ma_t"), "mat");
        assert_eq!(normalize_role("mixed_air_t"), "mat");
        assert_eq!(
            infer_role_from_column_name("web_oa_t").as_deref(),
            Some("web_oa_t")
        );
        assert_eq!(
            infer_role_from_column_name("web_ra_t").as_deref(),
            Some("rat")
        );
        assert_eq!(
            infer_role_from_column_name("web_mat").as_deref(),
            Some("mat")
        );
    }

    #[test]
    fn literal_fan_cmd_column_maps_identity() {
        assert_eq!(
            infer_role_from_column_name("fan_cmd").as_deref(),
            Some("fan_cmd")
        );
        assert_eq!(
            infer_role_from_column_name("duct_static_sp").as_deref(),
            Some("duct_static_sp")
        );
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("columns.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(
            f,
            "column,role\n\
             timestamp_utc,\n\
             duct_static,\n\
             duct_static_sp,\n\
             fan_cmd,"
        )
        .unwrap();
        let map = load_column_role_map(&path).unwrap();
        assert_eq!(map.get("fan_cmd"), Some(&"fan_cmd".to_string()));
        assert_eq!(map.get("duct_static"), Some(&"duct_static".to_string()));
        assert_eq!(
            map.get("duct_static_sp"),
            Some(&"duct_static_sp".to_string())
        );
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

    #[test]
    fn b100_mad_c_is_oa_damper_not_mat_or_enable() {
        assert_eq!(
            infer_role_from_column_name("mad_c").as_deref(),
            Some("oa_damper_pct")
        );
        assert_eq!(
            infer_role_from_column_name("mad_c_pct").as_deref(),
            Some("oa_damper_pct")
        );
        assert_eq!(
            infer_role_from_column_name("mixed_air_temp_f").as_deref(),
            Some("mat")
        );
        assert_eq!(
            infer_role_from_column_name("ex_dmpr_pos_fan_enable_pct"),
            None
        );
        assert_eq!(infer_role_from_column_name("oa_minimum_position_pct"), None);

        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("columns.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(
            f,
            "column,role\n\
             mad_c,oa_damper_pct\n\
             mixed_air_temp_f,mat\n\
             ex_dmpr_pos_fan_enable_pct,\n\
             oa_minimum_position_pct,"
        )
        .unwrap();
        let map = load_column_role_map(&path).unwrap();
        assert_eq!(map.get("mad_c"), Some(&"oa_damper_pct".to_string()));
        assert_eq!(map.get("mixed_air_temp_f"), Some(&"mat".to_string()));
        assert!(!map.contains_key("ex_dmpr_pos_fan_enable_pct"));
        assert!(!map.contains_key("oa_minimum_position_pct"));
    }

    #[test]
    fn b100_vav_damper_and_airflow_roles() {
        assert_eq!(haystack_point_to_role("damper"), "damper_pct");
        assert_eq!(haystack_point_to_role("airflow"), "zone_flow");
        assert_eq!(normalize_role("damper"), "damper_pct");
        assert_eq!(normalize_role("reheat_valve"), "reheat_valve_pct");
        assert_eq!(
            infer_role_from_column_name("vav_1_vavactuatorcommand_pct").as_deref(),
            Some("damper_pct")
        );
        assert_eq!(
            infer_role_from_column_name("vav_1_dpr_pos_pct").as_deref(),
            Some("damper_pct")
        );
        assert_eq!(
            infer_role_from_column_name("damper_pct_40").as_deref(),
            Some("damper_pct")
        );
        assert_eq!(
            infer_role_from_column_name("actflow").as_deref(),
            Some("zone_flow")
        );
        assert_eq!(
            infer_role_from_column_name("minflowsp").as_deref(),
            Some("min_flow_sp")
        );

        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("columns.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(
            f,
            "column,role\n\
             damper_pct_40,damper\n\
             vav_1_vavactuatorcommand_pct,vav_point\n\
             actflow,airflow\n\
             minflowsp,airflow"
        )
        .unwrap();
        let map = load_column_role_map(&path).unwrap();
        assert_eq!(map.get("damper_pct_40"), Some(&"damper_pct".to_string()));
        assert_eq!(
            map.get("vav_1_vavactuatorcommand_pct"),
            Some(&"damper_pct".to_string())
        );
        assert_eq!(map.get("actflow"), Some(&"zone_flow".to_string()));
        assert_eq!(map.get("minflowsp"), Some(&"min_flow_sp".to_string()));
    }

    #[test]
    fn chiller_other_and_power_roles_match_pandas() {
        assert_eq!(haystack_point_to_role("power"), "chiller_power");
        assert_eq!(
            infer_role_from_column_name("chiller_2_command").as_deref(),
            Some("chiller_status")
        );
        assert_eq!(
            infer_role_from_column_name("chiller_2_amps_a").as_deref(),
            Some("chiller_amps")
        );
        assert_eq!(
            infer_role_from_column_name(
                "meter_chiller2_chiller2_power_demand_this_interval_element_h_kw"
            )
            .as_deref(),
            Some("chiller_power")
        );
        let tmp = TempDir::new().unwrap();
        let path = tmp.path().join("columns.csv");
        let mut f = std::fs::File::create(&path).unwrap();
        writeln!(
            f,
            "col,point_role\n\
             chiller_2_command,other\n\
             chiller_2_amps_a,other\n\
             meter_chiller2_chiller2_power_demand_this_interval_element_h_kw,power\n\
             meter_chiller2_chiller2_power_demand_peak_element_h_kw,power\n\
             chwr_t_f,other\n\
             chws_t_f,other"
        )
        .unwrap();
        let map = load_column_role_map(&path).unwrap();
        assert_eq!(
            map.get("chiller_2_command"),
            Some(&"chiller_status".to_string())
        );
        assert_eq!(
            map.get("chiller_2_amps_a"),
            Some(&"chiller_amps".to_string())
        );
        assert_eq!(
            map.get("meter_chiller2_chiller2_power_demand_this_interval_element_h_kw"),
            Some(&"chiller_power".to_string())
        );
        assert_eq!(
            map.get("meter_chiller2_chiller2_power_demand_peak_element_h_kw"),
            Some(&"chiller_power".to_string())
        );
        assert_eq!(map.get("chws_t_f"), Some(&"chw_supply_t".to_string()));
        assert_eq!(map.get("chwr_t_f"), Some(&"chw_return_t".to_string()));
    }
}
