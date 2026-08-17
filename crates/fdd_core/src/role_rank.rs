//! Column ranking when multiple physical columns map to the same logical role.
//! Mirrors Python ``cookbook_engine.ROLE_CANDIDATES`` + physical heuristics.

/// Higher score wins when selecting one column per role during CSV ingest.
pub fn score_column_for_role(role: &str, column: &str) -> i32 {
    let c = column.to_lowercase();
    match role {
        "zone_t" => score_zone_t(&c),
        "sat" => {
            if c == "discharge_air_temp_f" {
                100
            } else if c.contains("discharge_air") {
                80
            } else if c.contains("dat_y") {
                60
            } else if c.contains("dat_x") {
                10
            } else if c.starts_with("dat_") {
                5
            } else {
                0
            }
        }
        "sat_sp" => {
            if c.contains("dat_reset") {
                100
            } else if c.contains("sat_sp") || c.contains("sat_setpoint") {
                90
            } else {
                0
            }
        }
        "oa_damper_pct" => {
            if c.contains("enable")
                || c.contains("minimum")
                || c.contains("min_pos")
                || c.contains("minpos")
            {
                -100
            } else if c == "mad_c"
                || c == "mad-c"
                || c.contains("mad_c")
                || c.contains("mixed_air_damper")
            {
                100
            } else if (c.contains("ex_dmpr") || c.contains("oa_damper")) && !c.contains("enable") {
                90
            } else if c.contains("damper") || c.contains("dmpr") {
                70
            } else {
                0
            }
        }
        "damper_pct" => {
            // Pandas ROLE_COLUMN_RANK: vavactuatorcommand > actuatorcommand > damper_pct > dpr_pos.
            // Do not let OA / heating-damper analogs steal the VAV damper.
            if c.contains("ex_dmpr")
                || c.contains("oa_damper")
                || c.contains("outdoor_air")
                || c.contains("mad_c")
                || c.contains("oad_")
                || c.contains("heatingdamper")
                || c.contains("heating_damper")
            {
                -100
            } else if c.contains("vavactuatorcommand") || c.contains("actuatorcommand") {
                100
            } else if c.contains("damper_pct") || c.contains("damper_pos") {
                80
            } else if c.contains("dpr_pos") || c.contains("vavactuator") {
                70
            } else {
                0
            }
        }
        "zone_flow" => {
            if c.contains("setpoint")
                || c.contains("minflow")
                || c.contains("maxflow")
                || c.contains("min_flow")
                || c.contains("max_flow")
                || c.contains("_sp")
                || c.contains("stby")
                || c.contains("unocc")
            {
                -100
            } else if c.contains("actflow") {
                100
            } else if c.contains("flow_input") {
                90
            } else if c.contains("airflow") {
                50
            } else {
                0
            }
        }
        "fan_cmd" => {
            if c.contains("supply_fan") && !c.contains("status") {
                100
            } else if c.contains("fan_cmd") || c.contains("fan_speed") {
                90
            } else {
                0
            }
        }
        "mat" => {
            if c.contains("mixed_air") && !c.contains("damper") {
                100
            } else if c == "mad_c" || c == "mad-c" || c.contains("mad_c") {
                // mad_c is damper command; never prefer it as mixed-air temp.
                -100
            } else {
                0
            }
        }
        _ => 0,
    }
}

pub fn is_zone_t_limit_or_alarm_column(column: &str) -> bool {
    score_zone_t(&column.to_lowercase()) < 0
}

fn score_zone_t(c: &str) -> i32 {
    if c.contains("alarm")
        || c.contains("limit")
        || c.contains("highlimit")
        || c.contains("lowlimit")
        || c.contains("setpoint")
        || c.contains("deadband")
        || c.contains("sa_temp")
        || c.contains("duct")
        || c.contains("inlet")
        || c.ends_with("_58")
        || c.ends_with("_59")
    {
        return -100;
    }
    if c.contains("vav_") && c.contains("space_temp") {
        return 100;
    }
    if c.contains("space_temp") || c.contains("spacetemp") || c.contains("zone_temp") {
        return 70;
    }
    if c.contains("zone_t") || c.contains("room_temp") || c.contains("roomtemp") {
        return 60;
    }
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vav7_prefers_vav_space_temp_f() {
        let candidates = [
            "space_temp_f_58",
            "space_temp_f_77",
            "vav_7_space_temp_f",
            "space_temp_f_59",
        ];
        let best = candidates
            .iter()
            .max_by_key(|c| score_column_for_role("zone_t", c))
            .unwrap();
        assert_eq!(*best, "vav_7_space_temp_f");
    }

    #[test]
    fn alarm_columns_rejected() {
        assert!(is_zone_t_limit_or_alarm_column("space_temp_f_58"));
        assert!(!is_zone_t_limit_or_alarm_column("vav_7_space_temp_f"));
    }

    #[test]
    fn oa_damper_prefers_mad_c_over_fan_enable() {
        let mad = score_column_for_role("oa_damper_pct", "mad_c");
        let enable = score_column_for_role("oa_damper_pct", "ex_dmpr_pos_fan_enable_pct");
        let min_oa = score_column_for_role("oa_damper_pct", "oa_minimum_position_pct");
        assert!(mad > enable, "mad_c={mad} enable={enable}");
        assert!(mad > min_oa, "mad_c={mad} min_oa={min_oa}");
        assert!(enable < 0);
        assert_eq!(score_column_for_role("mat", "mad_c"), -100);
        assert_eq!(score_column_for_role("mat", "mixed_air_temp_f"), 100);
    }

    #[test]
    fn vav_damper_prefers_actuator_command_over_heating_damper() {
        let cmd = score_column_for_role("damper_pct", "vav_1_vavactuatorcommand_pct");
        let heat = score_column_for_role("damper_pct", "damper_pct_40");
        let dpr = score_column_for_role("damper_pct", "vav_1_dpr_pos_pct");
        assert!(cmd > heat, "actuator={cmd} heating_damper={heat}");
        assert!(cmd > dpr, "actuator={cmd} dpr_pos={dpr}");
        assert_eq!(
            score_column_for_role("damper_pct", "ex_dmpr_pos_fan_enable_pct"),
            -100
        );
    }

    #[test]
    fn zone_flow_prefers_actflow_over_minflow_sp() {
        let act = score_column_for_role("zone_flow", "actflow");
        let input = score_column_for_role("zone_flow", "flow_input");
        let min_sp = score_column_for_role("zone_flow", "minflowsp");
        assert!(act > input, "actflow={act} flow_input={input}");
        assert!(act > min_sp, "actflow={act} minflowsp={min_sp}");
        assert!(min_sp < 0);
    }
}
