#[cfg(test)]
mod tests {
    //! FC8 must not count SAT/MAT economizer faults while the fan is off.
    //!
    //! Vibe19 ANDs `raw_fault` with the fan_running active mask before confirmation.
    //! Open-FDD previously evaluated FC8 SQL without that gate, inflating Building 100
    //! fault hours (e.g. AHU_1 ~1463h vs oracle ~382h).

    use std::collections::HashSet;
    use std::io::Write;
    use std::path::Path;

    use fdd_sql::{register_parquet_tree, run_sql};
    use fdd_store::ingest_building;

    use crate::gate_sql::{
        inject_raw_fault_operational_gate, operational_proof_expr, startup_delay_rows,
    };
    use crate::params::{rule_params, substitute_sql};
    use crate::registry::OperationalGate;
    use crate::registry::RuleSpec;

    fn write_fc8_fixture(building_root: &Path) {
        std::fs::write(
            building_root.join("manifest.json"),
            r#"{"grid_minutes": 5}"#,
        )
        .unwrap();
        let ahu = building_root.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nsat_col,sat\nmat_col,mat\noa_dpr,oa_damper_pct\nclg,clg_valve_pct\nfan_col,fan_cmd\n",
        )
        .unwrap();

        // SAT-MAT mismatch while economizing (oa damper open, clg closed).
        // Indices 0-4: fan OFF → must not confirm.
        // Indices 5-9: fan ON  → confirm after CONFIRM_ROWS=2.
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,sat_col,mat_col,oa_dpr,clg,fan_col").unwrap();
        for i in 0..10 {
            let minute = i * 5;
            let fan = if i < 5 { 0.0 } else { 50.0 };
            // sat=60, mat=50, delta_sf=0.55 → |60-0.55-50|=9.45 > 1.626 → raw fault
            writeln!(f, "2026-01-01T00:{minute:02}:00Z,60.0,50.0,50.0,0.0,{fan}").unwrap();
        }
    }

    #[tokio::test]
    async fn fc8_ignores_faults_while_fan_off() {
        let tmp = tempfile::TempDir::new().unwrap();
        let data_root = tmp.path().join("data");
        let building = data_root.join("BUILDING_100");
        std::fs::create_dir_all(&building).unwrap();
        write_fc8_fixture(&building);

        let parquet_root = tmp.path().join("parquet");
        ingest_building(&data_root, "BUILDING_100", &parquet_root).unwrap();

        let ctx = datafusion::prelude::SessionContext::new();
        register_parquet_tree(&ctx, &parquet_root).await.unwrap();

        let sql_path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("sql_rules")
            .join("fc8_sat_mat_econ.sql");
        let raw_sql = std::fs::read_to_string(&sql_path).unwrap();
        let params = rule_params(300.0, 600); // CONFIRM_ROWS = 2
        let substituted = substitute_sql(&raw_sql, &params);

        let mut cols = HashSet::new();
        cols.insert("fan_cmd".into());
        let proof = operational_proof_expr(&cols, "fan_running").unwrap();
        let rule = RuleSpec {
            rule_id: "FC8".into(),
            sql_file: "fc8_sat_mat_econ.sql".into(),
            description: "t".into(),
            required_roles: vec![],
            optional_roles: vec![],
            equipment_types: vec![],
            output_columns: vec![],
            confirm_seconds: 600,
            parameters: Default::default(),
            parity_status: String::new(),
            dashboard_wired: false,
            operational_gate: Some(OperationalGate {
                mode: "RUN".into(),
                predicate: "fan_running".into(),
                required: true,
                preferred_roles: vec![],
                command_fallback_allowed: true,
                startup_delay_seconds: 600,
                minimum_active_coverage_pct: 0.0,
            }),
        };
        let startup = startup_delay_rows(&rule, 300.0);
        assert_eq!(startup, 2);
        let sql = inject_raw_fault_operational_gate(&substituted, &proof, startup, true).unwrap();

        let ungated = run_sql(&ctx, &substituted).await.unwrap();
        let gated = run_sql(&ctx, &sql).await.unwrap();

        let ungated_h = ungated.rows[0]
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap();
        let gated_h = gated.rows[0]
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap();

        // Ungated: 10 raw faults, confirm from sample index 1 → 9 * 300/3600 = 0.75h
        assert!(
            (ungated_h - 0.75).abs() < 1e-6,
            "ungated expected 0.75h, got {ungated_h}"
        );
        // Gated: fan off 0-4; fan on 5-9 with startup=2 → proof active at 6,7,8,9;
        // confirm needs 2 consecutive raw under gate → indices 7,8,9 = 0.25h
        assert!(
            (gated_h - 0.25).abs() < 1e-6,
            "gated expected 0.25h (fan-off excluded + startup), got {gated_h}"
        );
        assert!(
            gated_h < ungated_h,
            "gated hours must be strictly less than ungated"
        );
    }
}
