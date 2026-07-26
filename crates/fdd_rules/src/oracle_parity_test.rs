//! Mask-level SQL oracle fixtures for #550 phase 1.
//!
//! These compare shipped SQL `fault_hours` against a pandas-equivalent
//! `confirm_fault` reference on synthetic role-mapped history.

#[cfg(test)]
mod tests {
    use crate::oracle_harness::{
        assert_hours_close, pandas_confirm_fault_hours, run_rule_fault_hours,
        write_equipment_fixture, RoleCol,
    };

    #[tokio::test]
    async fn sched1_confirm_matches_pandas_reference() {
        // poll=300s, confirm=600s -> CONFIRM_ROWS=2 (narrower than registry default so the
        // synthetic series stays short; still exercises the same streak math).
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SCHED1");
        std::fs::create_dir_all(&building).unwrap();

        // occ unoccupied + fan on => raw 1. Sequence: 0,0,1,1,1,0,1,1
        let rows = "\
timestamp_utc,occ_col,fan_col
2026-01-01T00:00:00Z,occupied,1
2026-01-01T00:05:00Z,occupied,1
2026-01-01T00:10:00Z,unoccupied,1
2026-01-01T00:15:00Z,unoccupied,1
2026-01-01T00:20:00Z,unoccupied,1
2026-01-01T00:25:00Z,occupied,0
2026-01-01T00:30:00Z,unoccupied,1
2026-01-01T00:35:00Z,unoccupied,1
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "occ_col",
                    role: "occ_mode",
                },
                RoleCol {
                    csv_col: "fan_col",
                    role: "fan_status",
                },
            ],
            rows,
        );

        let got =
            run_rule_fault_hours(&building, "sched1_unoccupied_runtime.sql", 300.0, 600, &[]).await;

        let raw = [false, false, true, true, true, false, true, true];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        // indices 3,4,7 confirm => 3 * 300/3600 = 0.25h
        assert_hours_close(expected, 0.25, "pandas reference");
        assert_hours_close(got, expected, "SCHED-1 SQL");
    }

    #[tokio::test]
    async fn mech_oat1_web_oat_clg_proxy_matches_pandas_reference() {
        // SQL uses web_oa_t + clg_valve_pct proxy (registry roles). Matches vibe19
        // mech_oat1 when mechanical proof is cooling-valve.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_MECHOAT");
        std::fs::create_dir_all(&building).unwrap();

        // Fault when web_oa_t < 60 and clg > 0.05. Sequence: 0,0,1,1,1,0
        let rows = "\
timestamp_utc,web_oat,clg_col
2026-01-01T00:00:00Z,65,50
2026-01-01T00:05:00Z,55,0
2026-01-01T00:10:00Z,55,50
2026-01-01T00:15:00Z,50,50
2026-01-01T00:20:00Z,45,50
2026-01-01T00:25:00Z,70,50
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "web_oat",
                    role: "web_oa_t",
                },
                RoleCol {
                    csv_col: "clg_col",
                    role: "clg_valve_pct",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "mech_oat_1.sql",
            300.0,
            600,
            &[("MECH_OAT_MAX_F", "60")],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "MECH-OAT-1 SQL");
    }

    #[tokio::test]
    async fn econ3_web_free_cool_not_integrated_matches_pandas_reference() {
        // Strict web DB+DP; free-cool band + mech cooling + damper not integrated.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_ECON3");
        std::fs::create_dir_all(&building).unwrap();

        // Defaults: 60<=DB<72, DP<60, clg>0.01, oa_d<0.9
        // Rows: no, no, fault, fault, fault, no (damper integrated)
        let rows = "\
timestamp_utc,web_oat,web_dp,oa_d,clg_col
2026-01-01T00:00:00Z,50,50,0.2,50
2026-01-01T00:05:00Z,65,50,0.2,0
2026-01-01T00:10:00Z,65,50,0.2,50
2026-01-01T00:15:00Z,68,55,0.3,50
2026-01-01T00:20:00Z,70,58,0.4,50
2026-01-01T00:25:00Z,65,50,0.95,50
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "web_oat",
                    role: "web_oa_t",
                },
                RoleCol {
                    csv_col: "web_dp",
                    role: "web_oa_dp",
                },
                RoleCol {
                    csv_col: "oa_d",
                    role: "oa_damper_pct",
                },
                RoleCol {
                    csv_col: "clg_col",
                    role: "clg_valve_pct",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "econ3_mech_without_econ.sql",
            300.0,
            600,
            &[
                ("ECON3_DB_MIN", "60"),
                ("ECON3_DB_MAX", "72"),
                ("ECON3_DP_MAX", "60"),
                ("ECON3_DAMPER_HI", "0.9"),
            ],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "ECON-3 SQL");
    }

    #[tokio::test]
    async fn econ5_preheat_over_matches_pandas_reference() {
        // Matches vibe19 econ5: htg open + (OAT>SAT⇒preheat−OAT>ΔT | OAT<SAT⇒preheat−SAT>ΔT).
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_ECON5");
        std::fs::create_dir_all(&building).unwrap();

        // over=2.2; OAT < SAT branch: preheat - sat_sp > 2.2 while htg open.
        // Sequence: 0,0,1,1,1,0
        let rows = "\
timestamp_utc,preheat,sat,oat,htg
2026-01-01T00:00:00Z,58,55,40,0
2026-01-01T00:05:00Z,56,55,40,50
2026-01-01T00:10:00Z,58,55,40,50
2026-01-01T00:15:00Z,59,55,40,50
2026-01-01T00:20:00Z,60,55,40,50
2026-01-01T00:25:00Z,60,55,40,0
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "preheat",
                    role: "preheat_leave_t",
                },
                RoleCol {
                    csv_col: "sat",
                    role: "sat_sp",
                },
                RoleCol {
                    csv_col: "oat",
                    role: "oa_t",
                },
                RoleCol {
                    csv_col: "htg",
                    role: "htg_valve_pct",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "econ5_preheat_over.sql",
            300.0,
            600,
            &[("PREHEAT_OVER_F", "2.2")],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "ECON-5 SQL");
    }

    #[tokio::test]
    async fn econ6_freezing_economizer_matches_pandas_reference() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_ECON6");
        std::fs::create_dir_all(&building).unwrap();

        // web_oa_t < 25 and oa_d > 0.25. Sequence: 0,0,1,1,1,0
        let rows = "\
timestamp_utc,web_oat,oa_d
2026-01-01T00:00:00Z,30,0.5
2026-01-01T00:05:00Z,20,0.1
2026-01-01T00:10:00Z,20,0.5
2026-01-01T00:15:00Z,15,0.4
2026-01-01T00:20:00Z,10,0.6
2026-01-01T00:25:00Z,20,0.1
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "web_oat",
                    role: "web_oa_t",
                },
                RoleCol {
                    csv_col: "oa_d",
                    role: "oa_damper_pct",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "econ6_econ_freezing.sql",
            300.0,
            600,
            &[("ECON6_OAT_MAX_F", "25"), ("ECON6_DAMPER_MAX", "0.25")],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "ECON-6 SQL");
    }

    #[tokio::test]
    async fn econ7_ok_not_economizing_matches_pandas_reference() {
        // Matches vibe19 econ7 with cooling-valve demand proxy (clg > 0.05).
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_ECON7");
        std::fs::create_dir_all(&building).unwrap();

        // 35<=DB<72, DP<60, clg>0.05, oa_d < 0.5. Sequence: 0,0,1,1,1,0
        let rows = "\
timestamp_utc,web_oat,web_dp,oa_d,clg_col
2026-01-01T00:00:00Z,30,50,0.2,50
2026-01-01T00:05:00Z,50,50,0.2,0
2026-01-01T00:10:00Z,50,50,0.2,50
2026-01-01T00:15:00Z,55,55,0.3,50
2026-01-01T00:20:00Z,60,58,0.4,50
2026-01-01T00:25:00Z,50,50,0.8,50
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "web_oat",
                    role: "web_oa_t",
                },
                RoleCol {
                    csv_col: "web_dp",
                    role: "web_oa_dp",
                },
                RoleCol {
                    csv_col: "oa_d",
                    role: "oa_damper_pct",
                },
                RoleCol {
                    csv_col: "clg_col",
                    role: "clg_valve_pct",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "econ7_ok_not_economizing.sql",
            300.0,
            600,
            &[
                ("ECON7_DB_MIN", "35"),
                ("ECON7_DB_MAX", "72"),
                ("ECON7_DP_MAX", "60"),
                ("ECON7_DAMPER_MIN", "0.5"),
            ],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "ECON-7 SQL");
    }

    #[tokio::test]
    async fn sched247_fan_cmd_screening_confirm_streak() {
        // Screening: SQL confirms fan_cmd>=0.05 streaks — not vibe19 window always_on_pct.
        // Keep parity_status ported_from_cookbook until SQL matches _sched247.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SCHED247");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,fan_col
2026-01-01T00:00:00Z,0
2026-01-01T00:05:00Z,0
2026-01-01T00:10:00Z,50
2026-01-01T00:15:00Z,50
2026-01-01T00:20:00Z,50
2026-01-01T00:25:00Z,0
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[RoleCol {
                csv_col: "fan_col",
                role: "fan_cmd",
            }],
            rows,
        );

        let got = run_rule_fault_hours(&building, "sched247_always_on.sql", 300.0, 600, &[]).await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(got, expected, "SCHED-247 screening SQL");
    }

    #[tokio::test]
    async fn vav7_underflow_confirm_matches_pandas_reference() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_VAV7");
        std::fs::create_dir_all(&building).unwrap();

        // under min_flow_sp: flow 100 vs sp 200 => raw 1. Sequence length 6 with confirm_rows=2.
        let rows = "\
timestamp_utc,flow_col,min_col
2026-01-01T00:00:00Z,250,200
2026-01-01T00:05:00Z,250,200
2026-01-01T00:10:00Z,100,200
2026-01-01T00:15:00Z,100,200
2026-01-01T00:20:00Z,100,200
2026-01-01T00:25:00Z,250,200
";
        write_equipment_fixture(
            &building,
            "VAV_1",
            5,
            &[
                RoleCol {
                    csv_col: "flow_col",
                    role: "zone_flow",
                },
                RoleCol {
                    csv_col: "min_col",
                    role: "min_flow_sp",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "vav7_min_airflow.sql",
            300.0,
            600,
            &[("HIGH_MIN_FLOW_SP", "2000")], // keep high-min branch inactive
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "VAV-7 under-flow SQL");
    }

    #[tokio::test]
    async fn sv_rate_screening_confirm_streak() {
        // Documents SV-RATE as a screening SQL (hard-coded 5°F Δ), not full pandas context.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVRATE");
        std::fs::create_dir_all(&building).unwrap();

        // Jump >5°F within persistence window on consecutive samples.
        let rows = "\
timestamp_utc,oat_col
2026-01-01T00:00:00Z,70
2026-01-01T00:05:00Z,70
2026-01-01T00:10:00Z,80
2026-01-01T00:15:00Z,90
2026-01-01T00:20:00Z,100
2026-01-01T00:25:00Z,100
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[RoleCol {
                csv_col: "oat_col",
                role: "oa_t",
            }],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "sv_rate.sql",
            300.0,
            600,
            &[("PERSISTENCE_MIN", "10")],
        )
        .await;

        // raw: row0 no prev=0; 70->70=0; 70->80=1; 80->90=1; 90->100=1; 100->100=0
        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(got, expected, "SV-RATE screening SQL");
    }

    #[tokio::test]
    async fn chw_noload_confirm_matches_screening_reference() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_CHW");
        std::fs::create_dir_all(&building).unwrap();

        // pump on + supply within band of SP => fault. sat_band default-like 1.5°F
        let rows = "\
timestamp_utc,t_col,sp_col,pump_col
2026-01-01T00:00:00Z,44,44,0
2026-01-01T00:05:00Z,44,44,0
2026-01-01T00:10:00Z,44,44,50
2026-01-01T00:15:00Z,44,44,50
2026-01-01T00:20:00Z,44,44,50
2026-01-01T00:25:00Z,50,44,50
";
        write_equipment_fixture(
            &building,
            "CHILLER_1",
            5,
            &[
                RoleCol {
                    csv_col: "t_col",
                    role: "chw_supply_t",
                },
                RoleCol {
                    csv_col: "sp_col",
                    role: "chw_supply_sp",
                },
                RoleCol {
                    csv_col: "pump_col",
                    role: "chw_pump_cmd",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "chw_noload_1.sql",
            300.0,
            600,
            &[("SAT_BAND_F", "1.5")],
        )
        .await;

        // pump>0.05 and |t-sp|<=1.5: rows 2,3,4 fault; 5 has |50-44|=6 => 0
        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(got, expected, "CHW-NOLOAD-1 screening SQL");
    }
}
