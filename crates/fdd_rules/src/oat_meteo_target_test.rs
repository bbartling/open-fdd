//! OAT-METEO targets stamped AHU equipment, not an `equipment_id` prefix (#1040).

use std::io::Write;
use std::path::Path;

use fdd_sql::{register_parquet_tree, run_sql};
use fdd_store::ingest_building;

use crate::params::{rule_params, substitute_sql};

fn write_oat_equipment(building: &Path, equipment_id: &str) {
    let eq = building.join(equipment_id);
    std::fs::create_dir_all(&eq).unwrap();
    std::fs::write(
        eq.join("columns.csv"),
        "col,point_role\noat_col,oa_t\nweb_col,web_oa_t\n",
    )
    .unwrap();
    let mut f = std::fs::File::create(eq.join("history_wide.csv")).unwrap();
    writeln!(f, "timestamp_utc,oat_col,web_col").unwrap();
    writeln!(f, "2026-06-01T00:00:00Z,80.0,60.0").unwrap();
}

#[tokio::test]
async fn oat_meteo_includes_opaque_ids_and_does_not_like_filter() {
    let tmp = tempfile::TempDir::new().unwrap();
    let data_root = tmp.path().join("data");
    let building = data_root.join("SITE_OAT");
    std::fs::create_dir_all(&building).unwrap();
    std::fs::write(building.join("manifest.json"), r#"{"grid_minutes":5}"#).unwrap();
    write_oat_equipment(&building, "AC_1");
    write_oat_equipment(&building, "AHU_BOX");

    let parquet_root = tmp.path().join("parquet");
    ingest_building(&data_root, "SITE_OAT", &parquet_root).unwrap();

    let ctx = datafusion::prelude::SessionContext::new();
    register_parquet_tree(&ctx, &parquet_root).await.unwrap();
    ctx.sql(
        "CREATE OR REPLACE VIEW weather AS \
         SELECT CAST(NULL AS TIMESTAMP) AS timestamp_utc, \
                CAST(NULL AS DOUBLE) AS oa_t \
         WHERE 1=0",
    )
    .await
    .unwrap()
    .collect()
    .await
    .unwrap();

    let sql_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("sql_rules")
        .join("oat_meteo_fault.sql");
    let raw_sql = std::fs::read_to_string(&sql_path).expect("oat_meteo_fault.sql");
    assert!(
        !raw_sql.to_ascii_uppercase().contains("EQUIPMENT_ID LIKE"),
        "{raw_sql}"
    );
    let mut params = rule_params(300.0, 300);
    params.insert("OAT_ERR".into(), "5.0".into());
    let sql = substitute_sql(&raw_sql, &params);
    let result = run_sql(&ctx, &sql).await.unwrap();
    let ids: Vec<String> = result
        .rows
        .iter()
        .filter_map(|row| {
            row.get("equipment_id")
                .and_then(|v| v.as_str())
                .map(str::to_string)
        })
        .collect();
    assert!(
        ids.iter().any(|id| id == "AC_1"),
        "opaque id must remain a SQL row; applicability is the stamp: {ids:?}"
    );
    assert!(
        ids.iter().any(|id| id == "AHU_BOX"),
        "an AHU prefix is not how the SQL chooses rows: {ids:?}"
    );
}
