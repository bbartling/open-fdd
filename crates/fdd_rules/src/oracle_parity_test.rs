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
        // zone_t left empty → pandas "no zone mapped" base (unoccupied + fan only).
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SCHED1");
        std::fs::create_dir_all(&building).unwrap();

        // occ unoccupied + fan on => raw 1. Sequence: 0,0,1,1,1,0,1,1
        let rows = "\
timestamp_utc,occ_col,fan_col,zone_col
2026-01-01T00:00:00Z,occupied,1,
2026-01-01T00:05:00Z,occupied,1,
2026-01-01T00:10:00Z,unoccupied,1,
2026-01-01T00:15:00Z,unoccupied,1,
2026-01-01T00:20:00Z,unoccupied,1,
2026-01-01T00:25:00Z,occupied,0,
2026-01-01T00:30:00Z,unoccupied,1,
2026-01-01T00:35:00Z,unoccupied,1,
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
                RoleCol {
                    csv_col: "zone_col",
                    role: "zone_t",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "sched1_unoccupied_runtime.sql",
            300.0,
            600,
            &[("ZONE_T_LO", "70"), ("ZONE_T_HI", "75")],
        )
        .await;

        let raw = [false, false, true, true, true, false, true, true];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        // indices 3,4,7 confirm => 3 * 300/3600 = 0.25h
        assert_hours_close(expected, 0.25, "pandas reference");
        assert_hours_close(got, expected, "SCHED-1 SQL");
    }

    #[tokio::test]
    async fn sched1_zone_comfort_gate_matches_pandas() {
        // When zone_t is mapped: fault only if unoccupied + fan + in comfort band.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SCHED1_ZONE");
        std::fs::create_dir_all(&building).unwrap();

        // Rows: occ/fan/zone — comfort band 70–75
        // 0 occupied+fan+72
        // 1 unoccupied+fan+80 (out of band → 0)
        // 2–4 unoccupied+fan+72 (in band → 1)
        // 5 unoccupied+fan+60 (out → 0)
        let rows = "\
timestamp_utc,occ_col,fan_col,zone_col
2026-01-01T00:00:00Z,occupied,1,72
2026-01-01T00:05:00Z,unoccupied,1,80
2026-01-01T00:10:00Z,unoccupied,1,72
2026-01-01T00:15:00Z,unoccupied,1,73
2026-01-01T00:20:00Z,unoccupied,1,74
2026-01-01T00:25:00Z,unoccupied,1,60
";
        write_equipment_fixture(
            &building,
            "VAV_1",
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
                RoleCol {
                    csv_col: "zone_col",
                    role: "zone_t",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "sched1_unoccupied_runtime.sql",
            300.0,
            600,
            &[("ZONE_T_LO", "70"), ("ZONE_T_HI", "75")],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "SCHED-1 zone-comfort SQL");
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
        // Keep parity_level sql_screening until SQL matches _sched247.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SCHED247");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,fan_col,fan_st,pump_st,ch_st
2026-01-01T00:00:00Z,0,,,
2026-01-01T00:05:00Z,0,,,
2026-01-01T00:10:00Z,50,,,
2026-01-01T00:15:00Z,50,,,
2026-01-01T00:20:00Z,50,,,
2026-01-01T00:25:00Z,0,,,
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "fan_col",
                    role: "fan_cmd",
                },
                RoleCol {
                    csv_col: "fan_st",
                    role: "fan_status",
                },
                RoleCol {
                    csv_col: "pump_st",
                    role: "pump_status",
                },
                RoleCol {
                    csv_col: "ch_st",
                    role: "chiller_status",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(&building, "sched247_always_on.sql", 300.0, 600, &[]).await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(got, expected, "SCHED-247 screening SQL");
    }

    #[tokio::test]
    async fn sv_range_screening_confirm_streak() {
        // Screening OAT hard limits (−60…130°F × scale). Keep ported until multi-sensor sweep.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVRANGE");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,oat_col
2026-01-01T00:00:00Z,70
2026-01-01T00:05:00Z,70
2026-01-01T00:10:00Z,140
2026-01-01T00:15:00Z,150
2026-01-01T00:20:00Z,160
2026-01-01T00:25:00Z,70
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
            "sv_range.sql",
            300.0,
            600,
            &[("RANGE_SCALE_TEMPERATURE", "1")],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(got, expected, "SV-RANGE screening SQL");
    }

    #[tokio::test]
    async fn sv_flatline_rolling_window_confirm_streak() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVFLAT");
        std::fs::create_dir_all(&building).unwrap();

        // FLATLINE_HOURS=0.25 at poll=300s → 3-sample rolling window.
        // Rolling span <= 0.1: rows 0/1 have a partial window, row 2 still spans
        // the 70→75 step, rows 3/4 are flat, row 5 spans the 75→80 step.
        let rows = "\
timestamp_utc,oat_col
2026-01-01T00:00:00Z,70
2026-01-01T00:05:00Z,75
2026-01-01T00:10:00Z,75.05
2026-01-01T00:15:00Z,75.08
2026-01-01T00:20:00Z,75.09
2026-01-01T00:25:00Z,80
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
            "sv_flatline.sql",
            300.0,
            600,
            &[("FLATLINE_TOL", "0.1"), ("FLATLINE_HOURS", "0.25")],
        )
        .await;

        let raw = [false, false, false, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.08333333333333333, "pandas reference");
        assert_hours_close(got, expected, "SV-FLATLINE rolling SQL");
    }

    #[tokio::test]
    async fn sv_flatline_ignores_deenergized_equipment() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVFLAT_OFF");
        std::fs::create_dir_all(&building).unwrap();

        // Perfectly flat sensor, but the fan is proven off the whole time.
        let rows = "\
timestamp_utc,oat_col,fan_st
2026-01-01T00:00:00Z,70,0
2026-01-01T00:05:00Z,70,0
2026-01-01T00:10:00Z,70,0
2026-01-01T00:15:00Z,70,0
2026-01-01T00:20:00Z,70,0
2026-01-01T00:25:00Z,70,0
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oat_col",
                    role: "oa_t",
                },
                RoleCol {
                    csv_col: "fan_st",
                    role: "fan_status",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "sv_flatline.sql",
            300.0,
            0,
            &[("FLATLINE_TOL", "0.1"), ("FLATLINE_HOURS", "0.25")],
        )
        .await;
        assert_hours_close(got, 0.0, "SV-FLATLINE energized gate");
    }

    #[tokio::test]
    async fn sv_spike_screening_confirm_streak() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVSPIKE");
        std::fs::create_dir_all(&building).unwrap();

        // |Δ| > 36 × SPIKE_SCALE (pandas SENSOR_LIMITS outside-air-temp spike).
        // Sequence: 0,0,1,1,1,0
        let rows = "\
timestamp_utc,oat_col
2026-01-01T00:00:00Z,70
2026-01-01T00:05:00Z,72
2026-01-01T00:10:00Z,120
2026-01-01T00:15:00Z,170
2026-01-01T00:20:00Z,220
2026-01-01T00:25:00Z,221
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
            "sv_spike.sql",
            300.0,
            600,
            &[("SPIKE_SCALE", "1")],
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(got, expected, "SV-SPIKE screening SQL");
    }

    #[tokio::test]
    async fn sv_stale_rolling_window_confirm_streak() {
        // Every mapped analog frozen across the trailing STALE_HOURS window.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVSTALE");
        std::fs::create_dir_all(&building).unwrap();

        // STALE_HOURS=0.25 at poll=300s → 3-sample window. Feed resumes at row 4.
        let rows = "\
timestamp_utc,oat_col,fan_col
2026-01-01T00:00:00Z,70,1
2026-01-01T00:05:00Z,70,1
2026-01-01T00:10:00Z,70,1
2026-01-01T00:15:00Z,70,1
2026-01-01T00:20:00Z,71,1
2026-01-01T00:25:00Z,72,1
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oat_col",
                    role: "oa_t",
                },
                RoleCol {
                    csv_col: "fan_col",
                    role: "fan_cmd",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "sv_stale.sql",
            300.0,
            600,
            &[("STALE_HOURS", "0.25"), ("STALE_TOL", "0.05")],
        )
        .await;

        let raw = [false, false, true, true, false, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.08333333333333333, "pandas reference");
        assert_hours_close(got, expected, "SV-STALE rolling SQL");
    }

    #[tokio::test]
    async fn sv_stale_requires_every_mapped_sensor_frozen() {
        // One live analog proves the feed is still updating → no stale fault.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVSTALE_PARTIAL");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,oat_col,zone_col
2026-01-01T00:00:00Z,70,72.0
2026-01-01T00:05:00Z,70,72.4
2026-01-01T00:10:00Z,70,72.8
2026-01-01T00:15:00Z,70,73.2
2026-01-01T00:20:00Z,70,73.6
2026-01-01T00:25:00Z,70,74.0
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oat_col",
                    role: "oa_t",
                },
                RoleCol {
                    csv_col: "zone_col",
                    role: "zone_t",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "sv_stale.sql",
            300.0,
            0,
            &[("STALE_HOURS", "0.25"), ("STALE_TOL", "0.05")],
        )
        .await;
        assert_hours_close(got, 0.0, "SV-STALE AND across mapped sensors");
    }

    #[tokio::test]
    async fn sv_stale_fan_off_rows_still_count() {
        // Pandas SV-STALE gate is `always` — fan-off samples still accumulate hours.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVSTALE_OFF");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,oat_col,fan_col
2026-01-01T00:00:00Z,70,0
2026-01-01T00:05:00Z,70,0
2026-01-01T00:10:00Z,70,0
2026-01-01T00:15:00Z,70,0
2026-01-01T00:20:00Z,70,0
2026-01-01T00:25:00Z,70,0
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oat_col",
                    role: "oa_t",
                },
                RoleCol {
                    csv_col: "fan_col",
                    role: "fan_cmd",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "sv_stale.sql",
            300.0,
            600,
            &[("STALE_HOURS", "0.25"), ("STALE_TOL", "0.05")],
        )
        .await;
        // Rows 2–5 have a full frozen window; confirm_rows=2 drops the first.
        assert_hours_close(
            got,
            0.25,
            "SV-STALE fan-off still counts (pandas always gate)",
        );
    }

    #[tokio::test]
    async fn fc4_flags_clock_hour_over_delta_os_max() {
        // GL36 fault 4: ΔOS entries per clock hour > ΔOSmax flags the whole hour.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_FC4");
        std::fs::create_dir_all(&building).unwrap();

        // Hour 00: 12 samples alternating econ (mode 2) / mech (mode 3) → 6 entries
        // per mode, above ΔOSmax=5. Hour 01: steady min-OA, 1 entry.
        let rows = "\
timestamp_utc,oa_d,clg_col,fan_col
2026-01-01T00:00:00Z,0.8,0,50
2026-01-01T00:05:00Z,0.2,50,50
2026-01-01T00:10:00Z,0.8,0,50
2026-01-01T00:15:00Z,0.2,50,50
2026-01-01T00:20:00Z,0.8,0,50
2026-01-01T00:25:00Z,0.2,50,50
2026-01-01T00:30:00Z,0.8,0,50
2026-01-01T00:35:00Z,0.2,50,50
2026-01-01T00:40:00Z,0.8,0,50
2026-01-01T00:45:00Z,0.2,50,50
2026-01-01T00:50:00Z,0.8,0,50
2026-01-01T00:55:00Z,0.2,50,50
2026-01-01T01:00:00Z,0.2,0,50
2026-01-01T01:05:00Z,0.2,0,50
2026-01-01T01:10:00Z,0.2,0,50
2026-01-01T01:15:00Z,0.2,0,50
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oa_d",
                    role: "oa_damper_pct",
                },
                RoleCol {
                    csv_col: "clg_col",
                    role: "clg_valve_pct",
                },
                RoleCol {
                    csv_col: "fan_col",
                    role: "fan_cmd",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "fc4_os_hunting.sql",
            300.0,
            0,
            &[("DELTA_OS_MAX", "5")],
        )
        .await;

        // Whole 00 hour flagged (12 samples), 01 hour clean.
        assert_hours_close(got, 1.0, "FC4 hourly ΔOS SQL");
    }

    #[tokio::test]
    async fn fc4_steady_operating_state_is_clean() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_FC4_STEADY");
        std::fs::create_dir_all(&building).unwrap();

        // Two mode changes in the hour — well under ΔOSmax.
        let rows = "\
timestamp_utc,oa_d,clg_col,fan_col
2026-01-01T00:00:00Z,0.2,0,50
2026-01-01T00:05:00Z,0.2,0,50
2026-01-01T00:10:00Z,0.8,0,50
2026-01-01T00:15:00Z,0.8,0,50
2026-01-01T00:20:00Z,0.2,50,50
2026-01-01T00:25:00Z,0.2,50,50
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oa_d",
                    role: "oa_damper_pct",
                },
                RoleCol {
                    csv_col: "clg_col",
                    role: "clg_valve_pct",
                },
                RoleCol {
                    csv_col: "fan_col",
                    role: "fan_cmd",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "fc4_os_hunting.sql",
            300.0,
            0,
            &[("DELTA_OS_MAX", "5")],
        )
        .await;
        assert_hours_close(got, 0.0, "FC4 steady operating state");
    }

    #[tokio::test]
    async fn pid_hunt1_output_step_screening_confirm_streak() {
        // Rolling TV/span/cycles/reversals (not s2s Δ). Short window + soft
        // thresholds so a 6-sample oscillation confirms under confirm_rows=2.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_PIDHUNT");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,clg_col
2026-01-01T00:00:00Z,10
2026-01-01T00:05:00Z,90
2026-01-01T00:10:00Z,10
2026-01-01T00:15:00Z,90
2026-01-01T00:20:00Z,10
2026-01-01T00:25:00Z,90
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[RoleCol {
                csv_col: "clg_col",
                role: "clg_valve_pct",
            }],
            rows,
        );

        let got = run_rule_fault_hours(
            &building,
            "pid_hunt_1.sql",
            300.0,
            600,
            &[
                ("WINDOW_HOURS", "0.25"),
                ("CHANGE_DEADBAND_PCT", "1"),
                ("MINIMUM_SPAN_PCT", "20"),
                ("TOTAL_VARIATION_FAULT_PCT", "50"),
                ("MINIMUM_EQUIVALENT_CYCLES", "1"),
                ("MINIMUM_REVERSALS", "1"),
                ("MINIMUM_COVERAGE_PCT", "50"),
            ],
        )
        .await;

        assert!(
            got > 0.0,
            "PID-HUNT-1 rolling hunting should confirm some fault hours, got {got}"
        );
    }

    #[tokio::test]
    async fn vav7_underflow_confirm_matches_pandas_reference() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_VAV7");
        std::fs::create_dir_all(&building).unwrap();

        // under min_flow_sp: flow 100 vs sp 200 => raw 1. Sequence length 6 with confirm_rows=2.
        // Final row is a closed box (0 CFM): below the SP but not delivering air,
        // so FLOW_ON_MIN must keep it out of the fault.
        let rows = "\
timestamp_utc,flow_col,min_col
2026-01-01T00:00:00Z,250,200
2026-01-01T00:05:00Z,250,200
2026-01-01T00:10:00Z,100,200
2026-01-01T00:15:00Z,100,200
2026-01-01T00:20:00Z,100,200
2026-01-01T00:25:00Z,0,200
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
            &[("HIGH_MIN_FLOW_SP", "2000"), ("FLOW_ON_MIN", "25")], // keep high-min branch inactive
        )
        .await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "VAV-7 under-flow SQL");
    }

    #[tokio::test]
    async fn sv_rate_sustained_slew_confirm_streak() {
        // Rate normalized to °F/h and required to persist for two samples so a
        // single step (SV-SPIKE territory) does not trip SV-RATE.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVRATE");
        std::fs::create_dir_all(&building).unwrap();

        // 10°F per 5 min = 120°F/h, far above the 6°F/h steady limit.
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
            &[("PERSISTENCE_MIN", "10"), ("STEADY_FAULT_PER_HOUR", "6")],
        )
        .await;

        // over_rate: 0,0,1,1,1,0 → sustained (needs the previous sample too): 0,0,0,1,1,0
        let raw = [false, false, false, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.08333333333333333, "pandas reference");
        assert_hours_close(got, expected, "SV-RATE sustained slew SQL");
    }

    #[tokio::test]
    async fn sv_rate_single_step_is_not_a_slew() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_SVRATE_STEP");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,oat_col
2026-01-01T00:00:00Z,70
2026-01-01T00:05:00Z,70
2026-01-01T00:10:00Z,80
2026-01-01T00:15:00Z,80
2026-01-01T00:20:00Z,80
2026-01-01T00:25:00Z,80
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
            0,
            &[("PERSISTENCE_MIN", "10"), ("STEADY_FAULT_PER_HOUR", "6")],
        )
        .await;
        assert_hours_close(got, 0.0, "SV-RATE single step");
    }

    #[tokio::test]
    async fn chw_noload_needs_running_plant_and_satisfied_load() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_CHW");
        std::fs::create_dir_all(&building).unwrap();

        // Load satisfied throughout; the plant only proves running from row 2,
        // and the chiller drops out on the last row.
        let rows = "\
timestamp_utc,ch_col,pump_col,load_col
2026-01-01T00:00:00Z,0,0,1
2026-01-01T00:05:00Z,0,0,1
2026-01-01T00:10:00Z,1,50,1
2026-01-01T00:15:00Z,1,50,1
2026-01-01T00:20:00Z,1,50,1
2026-01-01T00:25:00Z,0,0,1
";
        write_equipment_fixture(
            &building,
            "CHILLER_1",
            5,
            &[
                RoleCol {
                    csv_col: "ch_col",
                    role: "chiller_status",
                },
                RoleCol {
                    csv_col: "pump_col",
                    role: "chw_pump_cmd",
                },
                RoleCol {
                    csv_col: "load_col",
                    role: "building_zone_load_satisfied",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(&building, "chw_noload_1.sql", 300.0, 600, &[]).await;

        let raw = [false, false, true, true, true, false];
        let expected = pandas_confirm_fault_hours(&raw, 300.0, 2);
        assert_hours_close(expected, 0.16666666666666666, "pandas reference");
        assert_hours_close(got, expected, "CHW-NOLOAD-1 SQL");
    }

    #[tokio::test]
    async fn chw_noload_clean_when_building_still_calling() {
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_CHW_LOADED");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,ch_col,pump_col,load_col
2026-01-01T00:00:00Z,1,50,0
2026-01-01T00:05:00Z,1,50,0
2026-01-01T00:10:00Z,1,50,0
2026-01-01T00:15:00Z,1,50,0
";
        write_equipment_fixture(
            &building,
            "CHILLER_1",
            5,
            &[
                RoleCol {
                    csv_col: "ch_col",
                    role: "chiller_status",
                },
                RoleCol {
                    csv_col: "pump_col",
                    role: "chw_pump_cmd",
                },
                RoleCol {
                    csv_col: "load_col",
                    role: "building_zone_load_satisfied",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(&building, "chw_noload_1.sql", 300.0, 0, &[]).await;
        assert_hours_close(got, 0.0, "CHW-NOLOAD-1 loaded building");
    }

    #[tokio::test]
    async fn econ2_percent_min_oa_does_not_fault() {
        // B100-style 0–100 damper at min OA 20 with OAT 70 must not fire ECON-2
        // (0.20 < 0.42). Utf8/int 20 > 0.42 without CAST/percent gate would.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_ECON2_PCT");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,oa_t,oa_damper_pct
2026-01-01T00:00:00Z,70,20
2026-01-01T00:05:00Z,70,20
2026-01-01T00:10:00Z,70,20
2026-01-01T00:15:00Z,70,20
2026-01-01T00:20:00Z,70,20
2026-01-01T00:25:00Z,70,20
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oa_t",
                    role: "outside-air-temp",
                },
                RoleCol {
                    csv_col: "oa_damper_pct",
                    role: "outside-air-damper",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(&building, "economizer_fault.sql", 300.0, 0, &[]).await;
        assert_hours_close(got, 0.0, "ECON-2 percent min OA");
    }

    #[tokio::test]
    async fn econ2_fraction_damper_still_faults() {
        // Synthetic-59 style 0–1 damper 0.55 with OAT 70 must still fault.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_ECON2_FRAC");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,oa_t,oa_damper_pct
2026-01-01T00:00:00Z,70,0.55
2026-01-01T00:05:00Z,70,0.55
2026-01-01T00:10:00Z,70,0.55
2026-01-01T00:15:00Z,70,0.55
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oa_t",
                    role: "outside-air-temp",
                },
                RoleCol {
                    csv_col: "oa_damper_pct",
                    role: "outside-air-damper",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(&building, "economizer_fault.sql", 300.0, 0, &[]).await;
        assert!(got > 0.0, "ECON-2 fraction damper should fault, got {got}h");
    }

    #[tokio::test]
    async fn econ1_percent_stuck_closed_faults() {
        // Damper 0 (0–100 or fraction), fan-cmd 60 percent, OAT 70 → ECON-1 hours > 0.
        let tmp = tempfile::TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_ECON1_PCT");
        std::fs::create_dir_all(&building).unwrap();

        let rows = "\
timestamp_utc,oa_t,oa_damper_pct,fan_cmd,fan_status
2026-01-01T00:00:00Z,70,0,60,1
2026-01-01T00:05:00Z,70,0,60,1
2026-01-01T00:10:00Z,70,0,60,1
2026-01-01T00:15:00Z,70,0,60,1
2026-01-01T00:20:00Z,70,0,60,1
2026-01-01T00:25:00Z,70,0,60,1
";
        write_equipment_fixture(
            &building,
            "AHU_1",
            5,
            &[
                RoleCol {
                    csv_col: "oa_t",
                    role: "outside-air-temp",
                },
                RoleCol {
                    csv_col: "oa_damper_pct",
                    role: "outside-air-damper",
                },
                RoleCol {
                    csv_col: "fan_cmd",
                    role: "fan-cmd",
                },
                RoleCol {
                    csv_col: "fan_status",
                    role: "fan-status",
                },
            ],
            rows,
        );

        let got = run_rule_fault_hours(&building, "econ1_stuck_closed.sql", 300.0, 0, &[]).await;
        assert!(got > 0.0, "ECON-1 percent stuck closed should fault, got {got}h");
    }
}
