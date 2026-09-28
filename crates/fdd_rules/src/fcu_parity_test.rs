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

    #[tokio::test]
    async fn fan_fallback_missing_valve_and_idle_mode_match_pandas() {
        let fan_h = run(
            "fcu_htg_coil.sql",
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
                    csv_col: "hv",
                    role: "htg_valve_pct",
                },
                RoleCol {
                    csv_col: "fs",
                    role: "fan_status",
                },
                RoleCol {
                    csv_col: "fc",
                    role: "fan_cmd",
                },
            ],
            "timestamp_utc,sat,zt,hv,fs,fc\n\
             2026-01-01T00:00:00Z,75,72,100,,100\n\
             2026-01-01T00:05:00Z,75,72,100,0,100\n",
            &[("VALVE_OPEN", "0.8"), ("COIL_DELTA_F", "5.4")],
        )
        .await;
        // Row 1 falls back to fan command. Row 2 has explicit fan-off status.
        assert_hours_close(fan_h, 300.0 / 3600.0, "FCU fan fallback SQL");

        let missing_valve = run(
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
            "timestamp_utc,sat,zt,cv,hv,fan\n2026-01-01T00:00:00Z,90,72,100,,1\n",
            &[("VALVE_OPEN", "0.8")],
        )
        .await;
        assert_hours_close(missing_valve, 0.0, "FCU missing heating valve SQL");

        let idle_h = run(
            "fcu_mode_cycle.sql",
            &[
                RoleCol {
                    csv_col: "hv",
                    role: "htg_valve_pct",
                },
                RoleCol {
                    csv_col: "cv",
                    role: "clg_valve_pct",
                },
            ],
            "timestamp_utc,hv,cv\n\
             2026-01-01T00:00:00Z,100,0\n\
             2026-01-01T00:05:00Z,0,100\n\
             2026-01-01T00:10:00Z,100,0\n\
             2026-01-01T00:15:00Z,0,100\n\
             2026-01-01T00:20:00Z,100,0\n\
             2026-01-01T00:25:00Z,0,0\n",
            &[("MODE_VALVE_MIN", "0.1"), ("MODE_CHANGES", "4")],
        )
        .await;
        assert_hours_close(idle_h, 300.0 / 3600.0, "FCU idle mode row SQL");
    }

    #[tokio::test]
    async fn valve_pass_and_co2_damper_fault() {
        let heat_pass = run(
            "fcu_valve_pass_htg.sql",
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
                    csv_col: "hv",
                    role: "htg_valve_pct",
                },
                RoleCol {
                    csv_col: "cv",
                    role: "clg_valve_pct",
                },
                RoleCol {
                    csv_col: "fan",
                    role: "fan_status",
                },
            ],
            "timestamp_utc,sat,zt,hv,cv,fan\n2026-01-01T00:00:00Z,80,72,0,0,1\n",
            &[("PASS_DELTA_F", "5.4")],
        )
        .await;
        assert_hours_close(heat_pass, 300.0 / 3600.0, "FCU-VALVE-PASS-HTG SQL");

        let cool_pass = run(
            "fcu_valve_pass_clg.sql",
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
                    csv_col: "hv",
                    role: "htg_valve_pct",
                },
                RoleCol {
                    csv_col: "cv",
                    role: "clg_valve_pct",
                },
                RoleCol {
                    csv_col: "fan",
                    role: "fan_status",
                },
            ],
            "timestamp_utc,sat,zt,hv,cv,fan\n2026-01-01T00:00:00Z,60,72,0,0,1\n",
            &[("PASS_DELTA_F", "5.4")],
        )
        .await;
        assert_hours_close(cool_pass, 300.0 / 3600.0, "FCU-VALVE-PASS-CLG SQL");

        let co2 = run(
            "fcu_co2_damper.sql",
            &[
                RoleCol {
                    csv_col: "co2",
                    role: "zone_co2",
                },
                RoleCol {
                    csv_col: "cmd",
                    role: "damper_cmd",
                },
                RoleCol {
                    csv_col: "fan",
                    role: "fan_status",
                },
            ],
            "timestamp_utc,co2,cmd,fan\n2026-01-01T00:00:00Z,1200,5,1\n",
            &[("CO2_HIGH_PPM", "1000"), ("DAMPER_LOW", "0.10")],
        )
        .await;
        assert_hours_close(co2, 300.0 / 3600.0, "FCU-CO2-DAMPER SQL");
    }
}
