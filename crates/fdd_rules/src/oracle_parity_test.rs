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
