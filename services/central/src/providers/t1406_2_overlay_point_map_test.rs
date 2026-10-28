//! T1406-2 (CI, Postgres): engineer overlay unit/quantity/cadence_secs on point_map
//! and authorized_series survive inventory resync when NF tags drop unit.

use fdd_tsdb::Tsdb;
use open_fdd_edge_prototype::csv_ingest::model_overlay;
use sqlx::postgres::PgPoolOptions;
use sqlx::Row;

use super::{apply_to_stores, InventoryDiagnostics, InventoryPoint, InventorySnapshot};
use super::committed_model::refresh_point_map_overlay;

const SOURCE: &str = "nf:t1406-2";

async fn pool() -> Option<sqlx::PgPool> {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .filter(|v| !v.trim().is_empty())?;
    PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .ok()
}

async fn apply_schema(pool: &sqlx::PgPool) {
    crate::portal_inventory_fixtures::apply_schema(pool).await;
}

fn sat_point(unit: Option<&str>) -> InventoryPoint {
    InventoryPoint {
        portal_point_id: "pt-sat-t1406".into(),
        display_name: None,
        unit: unit.map(str::to_string),
        equipment_id: "AHU_1".into(),
        equip_type: Some("ahu".into()),
        equip_dis: None,
        equip_markers: vec!["ahu".into()],
        role: "sat".into(),
        markers: vec!["sensor".into(), "temp".into()],
        kind: Some("Number".into()),
        tz: None,
        his: Some(true),
        his_mode: Some("interval".into()),
        enum_value: None,
        ref_rel: None,
        ref_id: None,
    }
}

fn snapshot(unit: Option<&str>) -> InventorySnapshot {
    InventorySnapshot {
        points: vec![sat_point(unit)],
        source_points: 1,
        complete: true,
        diagnostics: InventoryDiagnostics::default(),
    }
}

#[tokio::test]
async fn t1406_2_overlay_metadata_survives_inventory_resync() {
    let Some(pool) = pool().await else {
        return;
    };
    let site = "T1406_POINT_MAP";
    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
    apply_schema(&pool).await;
    let tsdb = Tsdb::from_pool(pool.clone());
    let dir = tempfile::tempdir().expect("tempdir");
    let root = dir.path().join(site);

    model_overlay::upsert_engineer_point_overlay(
        &root,
        site,
        "pt-sat-t1406",
        Some("degF"),
        Some("absolute_temperature"),
        Some(900),
        false,
        false,
    )
    .expect("overlay");

    let first = apply_to_stores(Some(&tsdb), &root, site, SOURCE, &snapshot(Some("degC"))).await;
    assert!(first.errors.is_empty(), "{:?}", first.errors);

    let row = sqlx::query(
        "SELECT unit, quantity, cadence_secs, source_unit FROM point_map \
         WHERE site_id = $1 AND portal_point_id = 'pt-sat-t1406'",
    )
    .bind(site)
    .fetch_one(&pool)
    .await
    .expect("point_map");
    assert_eq!(row.get::<Option<String>, _>("unit").as_deref(), Some("degF"));
    assert_eq!(
        row.get::<Option<String>, _>("quantity").as_deref(),
        Some("absolute_temperature")
    );
    assert_eq!(row.get::<Option<i64>, _>("cadence_secs"), Some(900));
    assert_eq!(row.get::<Option<String>, _>("source_unit").as_deref(), Some("degC"));

    let auth_unit: Option<String> = sqlx::query_scalar(
        "SELECT unit FROM authorized_series WHERE site_id = $1 AND role = 'sat'",
    )
    .bind(site)
    .fetch_one(&pool)
    .await
    .expect("authorized_series");
    assert_eq!(auth_unit.as_deref(), Some("degF"));

    let resync = apply_to_stores(
        Some(&tsdb),
        &root,
        site,
        SOURCE,
        &snapshot(None),
    )
    .await;
    assert!(resync.errors.is_empty(), "{:?}", resync.errors);

    let row = sqlx::query(
        "SELECT unit, quantity, cadence_secs, source_unit FROM point_map \
         WHERE site_id = $1 AND portal_point_id = 'pt-sat-t1406'",
    )
    .bind(site)
    .fetch_one(&pool)
    .await
    .expect("point_map after resync");
    assert_eq!(row.get::<Option<String>, _>("unit").as_deref(), Some("degF"));
    assert_eq!(
        row.get::<Option<String>, _>("quantity").as_deref(),
        Some("absolute_temperature")
    );
    assert_eq!(row.get::<Option<i64>, _>("cadence_secs"), Some(900));
    assert!(row.get::<Option<String>, _>("source_unit").is_none());

    let auth_unit: Option<String> = sqlx::query_scalar(
        "SELECT unit FROM authorized_series WHERE site_id = $1 AND role = 'sat'",
    )
    .bind(site)
    .fetch_one(&pool)
    .await
    .expect("authorized_series after resync");
    assert_eq!(auth_unit.as_deref(), Some("degF"));

    refresh_point_map_overlay(
        &tsdb,
        &root,
        site,
        &["pt-sat-t1406".to_string()],
    )
    .await
    .expect("overlay refresh");

    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
}
