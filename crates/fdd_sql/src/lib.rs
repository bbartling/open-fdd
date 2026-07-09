//! DataFusion SQL execution over Parquet sidecars.

pub mod session;

pub use session::{
    register_parquet_tree, register_weather_if_present, run_sql, run_sql_file, QueryResult,
};

#[cfg(test)]
mod smoke {
    use std::io::Write;

    use datafusion::prelude::SessionContext;
    use tempfile::TempDir;

    use crate::{register_parquet_tree, run_sql};
    use fdd_store::ingest_building;

    #[tokio::test]
    async fn datafusion_query_on_ingested_fixture() {
        let tmp = TempDir::new().unwrap();
        let building = tmp.path().join("BUILDING_100");
        std::fs::create_dir_all(&building).unwrap();
        std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
        let ahu = building.join("AHU_1");
        std::fs::create_dir_all(&ahu).unwrap();
        std::fs::write(
            ahu.join("columns.csv"),
            "col,point_role\nfan_speed_pct,fan_cmd\n",
        )
        .unwrap();
        let mut f = std::fs::File::create(ahu.join("history_wide.csv")).unwrap();
        writeln!(f, "timestamp_utc,fan_speed_pct").unwrap();
        writeln!(f, "2026-01-01T00:00:00Z,100").unwrap();
        writeln!(f, "2026-01-01T00:05:00Z,0").unwrap();

        let parquet = tmp.path().join("parquet");
        ingest_building(tmp.path(), "BUILDING_100", &parquet).unwrap();

        let ctx = SessionContext::new();
        register_parquet_tree(&ctx, &parquet).await.unwrap();
        let sql = r#"
            SELECT equipment_id,
                   SUM(CASE WHEN fan_cmd > 0.05 THEN 1 ELSE 0 END) * 300.0 / 3600.0 AS fan_runtime_hours
            FROM history
            GROUP BY equipment_id
        "#;
        let result = run_sql(&ctx, sql).await.unwrap();
        assert_eq!(result.row_count, 1);
        let hours = result.rows[0]
            .get("fan_runtime_hours")
            .and_then(|v| v.as_f64())
            .unwrap();
        assert!((hours - 0.083333).abs() < 0.01);
    }
}
