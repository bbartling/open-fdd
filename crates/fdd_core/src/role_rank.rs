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
            if c.contains("ex_dmpr") || c.contains("oa_damper") {
                90
            } else if c.contains("damper") || c.contains("dmpr") {
                70
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
            if c.contains("mixed_air") {
                100
            } else if c == "mad_c" {
                80
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
}
