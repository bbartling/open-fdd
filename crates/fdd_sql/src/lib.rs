//! DataFusion SQL execution over Parquet historian datasets.

use std::path::Path;

use anyhow::{anyhow, Result};
use datafusion::prelude::SessionContext;
use fdd_store::{HistorianConfig, StorageUrl};

pub mod historian;
pub mod object_store;
pub mod query;
pub mod session;
pub mod tuning;

pub use historian::{
    new_historian_session, register_historian_building, register_historian_dataset,
    HistorianDatasetKind, HistorianRegistration,
};
pub use object_store::{
    refresh_s3_scope_index_from_env, register_configured_historian,
    register_configured_historian_scoped, s3_scope_index_root, S3ObjectStoreConfig, S3UrlStyle,
};
pub use query::{collect_sql_bounded, stream_sql, DEFAULT_INTERACTIVE_MAX_ROWS};
pub use session::{
    register_utility_if_present, register_weather_if_present, run_sql, run_sql_bounded,
    run_sql_file, run_sql_file_bounded, QueryResult,
};
pub use tuning::{historian_session_config_from_env, DataFusionTuning};

/// Compatibility registration entry point used by central/edge callers.
///
/// Existing local callers remain path-driven. When `OPENFDD_STORAGE_URL`
/// explicitly selects S3, an existing `building=<id>` compatibility marker is
/// translated into a canonical object-store prefix before DataFusion discovers
/// files, avoiding unrelated-building object listings. Compatibility callers may
/// not fall back to unscoped whole-bucket history; explicit global/operator S3
/// queries must use `register_configured_historian` directly.
pub async fn register_parquet_tree(ctx: &SessionContext, parquet_root: &Path) -> Result<usize> {
    if let Ok(raw) = std::env::var("OPENFDD_STORAGE_URL") {
        if matches!(StorageUrl::parse(&raw)?, StorageUrl::S3 { .. }) {
            let config = HistorianConfig::from_env()?;
            let building_id = object_store::building_scope_from_compat_path(parquet_root)
                .ok_or_else(|| {
                    anyhow!("S3 historian compatibility registration requires a building scope")
                })?;
            object_store::register_configured_historian_scoped(ctx, &config, Some(building_id))
                .await?;
            return Ok(1);
        }
    }
    historian::register_parquet_tree(ctx, parquet_root).await
}

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

    #[tokio::test]
    async fn weather_view_falls_back_to_history() {
        use std::sync::Arc;

        use datafusion::arrow::array::{Float64Array, StringArray};
        use datafusion::arrow::datatypes::{DataType, Field, Schema};
        use datafusion::arrow::record_batch::RecordBatch;
        use datafusion::datasource::MemTable;

        use crate::register_weather_if_present;

        let ctx = SessionContext::new();
        let schema = Arc::new(Schema::new(vec![
            Field::new("equipment_id", DataType::Utf8, false),
            Field::new("oa_t", DataType::Float64, false),
        ]));
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(StringArray::from(vec!["AHU_1", "weather_station"])) as _,
                Arc::new(Float64Array::from(vec![70.0, 55.0])) as _,
            ],
        )
        .unwrap();
        let mem = MemTable::try_new(schema, vec![vec![batch]]).unwrap();
        ctx.register_table("history", Arc::new(mem)).unwrap();

        // No sidecar dir → register a `weather` view from weather-like history.
        let registered =
            register_weather_if_present(&ctx, std::path::Path::new("/nonexistent/xyz"))
                .await
                .unwrap();
        assert!(registered, "expected weather view to register from history");
        let res = run_sql(&ctx, "SELECT oa_t FROM weather").await.unwrap();
        assert_eq!(res.row_count, 1, "only the weather-station row: {res:?}");
        assert!((res.rows[0]["oa_t"].as_f64().unwrap() - 55.0).abs() < 1e-6);
    }
}
