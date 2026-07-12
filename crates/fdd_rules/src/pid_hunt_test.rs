#[cfg(test)]
mod tests {
    //! PID-HUNT-1 micro-fixtures: normalization, reversal ffill, clipping.

    use std::io::Write;
    use std::path::Path;

    use fdd_sql::{register_parquet_tree, run_sql};
    use fdd_store::ingest_building;

    use crate::params::{rule_params, substitute_sql};

    fn write_pid_fixture(building_root: &Path, outputs: &[f64]) {
        std::fs::write(
            building_root.join("manifest.json"),
            r#"{"grid_minutes": 1}"#,
        )
        .unwrap();
        let ahu = building_root.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nao_col,control_output_pct\nenable_col,loop_enabled\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,ao_col,enable_col").unwrap();
        for (i, out) in outputs.iter().enumerate() {
            let hour = i / 60;
            let minute = i % 60;
            writeln!(f, "2026-01-01T{hour:02}:{minute:02}:00Z,{out},1").unwrap();
        }
    }

    async fn run_pid(outputs: &[f64]) -> f64 {
        let tmp = tempfile::TempDir::new().unwrap();
        let data_root = tmp.path().join("data");
        let building = data_root.join("BUILDING_PID");
        std::fs::create_dir_all(&building).unwrap();
        write_pid_fixture(&building, outputs);

        let parquet_root = tmp.path().join("parquet");
        ingest_building(&data_root, "BUILDING_PID", &parquet_root).unwrap();

        let ctx = datafusion::prelude::SessionContext::new();
        register_parquet_tree(&ctx, &parquet_root).await.unwrap();

        let sql_path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("sql_rules")
            .join("pid_hunt_1.sql");
        let raw_sql = std::fs::read_to_string(&sql_path).unwrap();
        let mut params = rule_params(60.0, 0);
        params.insert("CHANGE_DEADBAND_PCT".into(), "1".into());
        params.insert("MINIMUM_SPAN_PCT".into(), "20".into());
        params.insert("TOTAL_VARIATION_FAULT_PCT".into(), "500".into());
        params.insert("MINIMUM_EQUIVALENT_CYCLES".into(), "2.5".into());
        params.insert("MINIMUM_REVERSALS".into(), "4".into());
        params.insert("MINIMUM_COVERAGE_PCT".into(), "80".into());
        params.insert("MINIMUM_SAMPLES".into(), "48".into());
        params.insert("WINDOW_ROWS".into(), "60".into());
        params.insert("WINDOW_ROWS_MINUS_ONE".into(), "59".into());
        let sql = substitute_sql(&raw_sql, &params);
        let result = run_sql(&ctx, &sql).await.expect("pid sql");
        assert_eq!(result.row_count, 1);
        result.rows[0]
            .get("fault_hours")
            .and_then(|v| v.as_f64())
            .unwrap()
    }

    #[tokio::test]
    async fn monotonic_rise_is_not_fault() {
        // Steady climb — high TV possible but few reversals.
        let mut outs = Vec::new();
        for i in 0..60 {
            outs.push(i as f64 * (100.0 / 59.0));
        }
        let hours = run_pid(&outs).await;
        assert!(hours < 1e-9, "monotonic rise should not hunt, got {hours}");
    }

    #[tokio::test]
    async fn oscillation_above_deadband_faults() {
        // Severe hunting: 0↔100 every sample for a full hour.
        let mut outs = Vec::new();
        for i in 0..60 {
            outs.push(if i % 2 == 0 { 0.0 } else { 100.0 });
        }
        let hours = run_pid(&outs).await;
        assert!(
            hours > 0.0,
            "severe oscillation should accumulate fault hours, got {hours}"
        );
    }

    #[tokio::test]
    async fn fraction_commands_scale_like_percent() {
        // 0.0↔1.0 fractions should scale to 0↔100 and fault similarly.
        let mut outs = Vec::new();
        for i in 0..60 {
            outs.push(if i % 2 == 0 { 0.0 } else { 1.0 });
        }
        let hours = run_pid(&outs).await;
        assert!(
            hours > 0.0,
            "0–1 fraction oscillation should scale and fault, got {hours}"
        );
    }
}
