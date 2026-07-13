#[cfg(test)]
mod tests {
    //! SV-STALE must not treat projected NULL optional roles as "unchanged".

    use std::collections::HashSet;
    use std::io::Write;
    use std::path::Path;

    use fdd_sql::{register_parquet_tree, run_sql};
    use fdd_store::ingest_building;

    use crate::params::{rule_params, substitute_sql};
    use crate::registry::RuleSpec;
    use crate::runner::{derive_window_rows, project_optional_roles};

    fn write_fixture(building_root: &Path) {
        std::fs::write(
            building_root.join("manifest.json"),
            r#"{"grid_minutes": 5}"#,
        )
        .unwrap();
        let eq = building_root.join("CHILLER_1");
        std::fs::create_dir_all(&eq).unwrap();
        std::fs::write(
            eq.join("columns.csv"),
            "col,point_role\nchw_s,chw_supply_t\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(eq.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,chw_s").unwrap();
        for i in 0..30 {
            let minute = (i * 5) % 60;
            let hour = (i * 5) / 60;
            let t = 42.0 + (i as f64) * 0.1;
            writeln!(f, "2026-01-01T{hour:02}:{minute:02}:00Z,{t}").unwrap();
        }
    }

    #[tokio::test]
    async fn sv_stale_ignores_missing_optional_roles() {
        let tmp = tempfile::TempDir::new().unwrap();
        let data_root = tmp.path().join("data");
        let building = data_root.join("BUILDING_100");
        std::fs::create_dir_all(&building).unwrap();
        write_fixture(&building);

        let parquet_root = tmp.path().join("parquet");
        ingest_building(&data_root, "BUILDING_100", &parquet_root).unwrap();

        let ctx = datafusion::prelude::SessionContext::new();
        register_parquet_tree(&ctx, &parquet_root).await.unwrap();

        let sql_path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .join("sql_rules/sv_stale.sql");
        let raw = std::fs::read_to_string(&sql_path).unwrap();

        let rule = RuleSpec {
            rule_id: "SV-STALE".into(),
            sql_file: "sv_stale.sql".into(),
            description: "t".into(),
            required_roles: vec![],
            optional_roles: vec![
                "oa_t".into(),
                "rat".into(),
                "mat".into(),
                "sat".into(),
                "zone_t".into(),
                "chw_supply_t".into(),
                "chw_return_t".into(),
                "hw_supply_t".into(),
                "hw_return_t".into(),
                "oa_h".into(),
            ],
            equipment_types: vec![],
            output_columns: vec![],
            confirm_seconds: 300,
            parameters: Default::default(),
            parity_status: String::new(),
            dashboard_wired: false,
            operational_gate: None,
        };
        let mut available = HashSet::new();
        available.insert("chw_supply_t".into());
        available.insert("equipment_id".into());
        available.insert("timestamp_utc".into());

        let mut params = rule_params(300.0, 300);
        let (wr, wr1) = derive_window_rows(120.0, 300.0);
        params.insert("WINDOW_ROWS".into(), wr.to_string());
        params.insert("WINDOW_ROWS_MINUS_ONE".into(), wr1.to_string());

        let sql = substitute_sql(&project_optional_roles(&raw, &rule, &available), &params);
        let result = run_sql(&ctx, &sql).await.unwrap();
        let hours = result.rows[0]
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap_or(-1.0);
        assert!(
            hours < 1e-6,
            "varying chw_supply_t must not be STALE when other roles are missing; got {hours}"
        );
    }
}
