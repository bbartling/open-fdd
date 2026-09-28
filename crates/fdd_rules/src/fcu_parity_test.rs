//! Focused DataFusion predicates for the FCU family contributed in #1030.

#[cfg(test)]
mod tests {
    use crate::oracle_harness::{
        assert_hours_close, run_rule_fault_hours, write_equipment_fixture, RoleCol,
    };

    async fn run(file: &str, roles: &[RoleCol], header_rows: &str, params: &[(&str, &str)]) -> f64 {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("FCU_FIXTURE");
        std::fs::create_dir_all(&building).unwrap();
        write_equipment_fixture(&building, "FCU_1", 5, roles, header_rows);
        run_rule_fault_hours(&building, file, 300.0, 0, params).await
    }

    #[tokio::test]
    async fn sensor_null_and_crossed_cooling_fault() {
        let null_h = run(
            "fcu_sensor_null.sql",
            &[
                RoleCol {
                    csv_col: "zt",
                    role: "zone_t",
                },
                RoleCol {
                    csv_col: "zsp",
                    role: "zone_air_temp_sp",
                },
            ],
            "timestamp_utc,zt,zsp\n2026-01-01T00:00:00Z,,21\n2026-01-01T00:05:00Z,,21\n",
            &[("NULL_FRACTION", "0.9")],
        )
        .await;
        assert_hours_close(null_h, 2.0 * 300.0 / 3600.0, "FCU-SENSOR-NULL SQL");

        let crossed_h = run(
            "fcu_clg_coil.sql",
            &[
                RoleCol {
                    csv_col: "sat",
                    role: "sat",
                },
                RoleCol {
                    csv_col: "zt",
                    role: "zone_t",
                },
                RoleCol {
                    csv_col: "cv",
                    role: "clg_valve_pct",
                },
                RoleCol {
                    csv_col: "hv",
                    role: "htg_valve_pct",
                },
                RoleCol {
                    csv_col: "fan",
                    role: "fan_status",
                },
            ],
            "timestamp_utc,sat,zt,cv,hv,fan\n2026-01-01T00:00:00Z,90,72,100,0,1\n",
            &[("VALVE_OPEN", "0.8")],
        )
        .await;
        assert_hours_close(crossed_h, 300.0 / 3600.0, "FCU-CLG-COIL SQL");
    }

    #[tokio::test]
    async fn damper_deadband_and_mode_cycle_fault() {
        let damper_h = run(
            "fcu_damper_pos.sql",
            &[
                RoleCol {
                    csv_col: "cmd",
                    role: "damper_cmd",
                },
                RoleCol {
                    csv_col: "pos",
                    role: "damper_pct",
                },
                RoleCol {
                    csv_col: "fan",
                    role: "fan_status",
                },
            ],
            "timestamp_utc,cmd,pos,fan\n2026-01-01T00:00:00Z,25,7,1\n",
            &[("COMMAND_MIN", "0.15"), ("POSITION_ERROR", "0.15")],
        )
        .await;
        assert_hours_close(damper_h, 300.0 / 3600.0, "FCU-DAMPER-POS SQL");

        let deadband_h = run(
            "fcu_deadband.sql",
            &[
                RoleCol {
                    csv_col: "csp",
                    role: "cooling_sp",
                },
                RoleCol {
                    csv_col: "hsp",
                    role: "heating_sp",
                },
            ],
            "timestamp_utc,csp,hsp\n2026-01-01T00:00:00Z,21.5,21\n",
            &[("DEADBAND_C", "1.0")],
        )
        .await;
        assert_hours_close(deadband_h, 300.0 / 3600.0, "FCU-DEADBAND SQL");

        let cycle_h = run(
            "fcu_mode_cycle.sql",
            &[RoleCol { csv_col: "hv", role: "htg_valve_pct" }, RoleCol { csv_col: "cv", role: "clg_valve_pct" }],
            "timestamp_utc,hv,cv\n2026-01-01T00:00:00Z,100,0\n2026-01-01T00:05:00Z,0,100\n2026-01-01T00:10:00Z,100,0\n2026-01-01T00:15:00Z,0,100\n2026-01-01T00:20:00Z,100,0\n",
            &[("MODE_VALVE_MIN", "0.1"), ("MODE_CHANGES", "4")],
        ).await;
        assert_hours_close(cycle_h, 300.0 / 3600.0, "FCU-MODE-CYCLE SQL");
    }
}
