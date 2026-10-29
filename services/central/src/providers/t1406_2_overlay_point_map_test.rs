//! T1406-2 (CI, Postgres): engineer overlay unit/quantity/cadence_secs on point_map
//! and authorized_series survive inventory resync when NF tags drop unit.

use fdd_tsdb::Tsdb;
use open_fdd_edge_prototype::csv_ingest::model_overlay;
use sqlx::postgres::PgPoolOptions;
use sqlx::Row;

use super::{apply_to_stores, InventoryDiagnostics, InventoryPoint, InventorySnapshot};
use crate::providers::committed_model::refresh_point_map_overlay;

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

fn snapshot_with_id(
    portal_point_id: &str,
    unit: Option<&str>,
    his_mode: Option<&str>,
) -> InventorySnapshot {
    InventorySnapshot {
        points: vec![InventoryPoint {
            portal_point_id: portal_point_id.into(),
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
            his_mode: his_mode.map(str::to_string),
            enum_value: None,
            ref_rel: None,
            ref_id: None,
        }],
        source_points: 1,
        complete: true,
        diagnostics: InventoryDiagnostics::default(),
    }
}

fn snapshot(unit: Option<&str>, his_mode: Option<&str>) -> InventorySnapshot {
    snapshot_with_id("pt-sat-t1406", unit, his_mode)
}

#[tokio::test]
async fn t1406_2_overlay_metadata_survives_inventory_resync() {
    let Some(pool) = pool().await else {
        return;
    };
    let site = "T1406_POINT_MAP";
    apply_schema(&pool).await;
    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
    let tsdb = Tsdb::from_pool(pool.clone());
    let dir = tempfile::tempdir().expect("tempdir");
    let root = dir.path().join(site);

    model_overlay::upsert_engineer_point_overlay(
        &root,
        site,
        "pt-sat-t1406",
        model_overlay::EngineerPointOverlayPatch {
            unit: Some("degF"),
            quantity: Some("absolute_temperature"),
            cadence_secs: Some(900),
            primary_reference: None,
        },
        false,
    )
    .expect("overlay");

    let first = apply_to_stores(
        Some(&tsdb),
        &root,
        site,
        SOURCE,
        &snapshot(Some("degC"), Some("interval")),
    )
    .await;
    assert!(first.errors.is_empty(), "{:?}", first.errors);

    let row = sqlx::query(
        "SELECT unit, quantity, cadence_secs, source_unit FROM point_map \
         WHERE site_id = $1 AND portal_point_id = 'pt-sat-t1406'",
    )
    .bind(site)
    .fetch_one(&pool)
    .await
    .expect("point_map");
    assert_eq!(
        row.get::<Option<String>, _>("unit").as_deref(),
        Some("degF")
    );
    assert_eq!(
        row.get::<Option<String>, _>("quantity").as_deref(),
        Some("absolute_temperature")
    );
    assert_eq!(row.get::<Option<i64>, _>("cadence_secs"), Some(900));
    assert_eq!(
        row.get::<Option<String>, _>("source_unit").as_deref(),
        Some("degC")
    );

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
        &snapshot(None, Some("interval")),
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
    assert_eq!(
        row.get::<Option<String>, _>("unit").as_deref(),
        Some("degF")
    );
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

    refresh_point_map_overlay(&tsdb, &root, site, &["pt-sat-t1406".to_string()])
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

#[tokio::test]
async fn t1406_2_overlay_refresh_without_cadence_preserves_cov_history_mode() {
    let Some(pool) = pool().await else {
        return;
    };
    let site = "T1406_COV_REFRESH";
    apply_schema(&pool).await;
    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
    let tsdb = Tsdb::from_pool(pool.clone());
    let dir = tempfile::tempdir().expect("tempdir");
    let root = dir.path().join(site);
    let pid = "pt-cov-t1406";

    let sync = apply_to_stores(
        Some(&tsdb),
        &root,
        site,
        SOURCE,
        &snapshot_with_id(pid, Some("degC"), Some("cov")),
    )
    .await;
    assert!(sync.errors.is_empty(), "{:?}", sync.errors);

    model_overlay::upsert_engineer_point_overlay(
        &root,
        site,
        pid,
        model_overlay::EngineerPointOverlayPatch {
            unit: Some("degF"),
            quantity: Some("absolute_temperature"),
            cadence_secs: None,
            primary_reference: None,
        },
        false,
    )
    .expect("overlay unit only");

    refresh_point_map_overlay(&tsdb, &root, site, &[pid.to_string()])
        .await
        .expect("overlay refresh");

    let history_mode: Option<String> = sqlx::query_scalar(
        "SELECT history_mode FROM point_map WHERE site_id = $1 AND portal_point_id = $2",
    )
    .bind(site)
    .bind(pid)
    .fetch_one(&pool)
    .await
    .expect("point_map history_mode");
    assert_eq!(history_mode.as_deref(), Some("cov"));

    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
}

#[tokio::test]
async fn t1406_2_patch_binding_clears_role_map_unit() {
    let Some(pool) = pool().await else {
        return;
    };
    let site = "T1406_UNIT_CLEAR";
    apply_schema(&pool).await;
    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
    let tsdb = Tsdb::from_pool(pool.clone());
    let dir = tempfile::tempdir().expect("tempdir");
    let root = dir.path().join(site);
    let pid = "pt-unit-clear";

    let sync = apply_to_stores(
        Some(&tsdb),
        &root,
        site,
        SOURCE,
        &snapshot_with_id(pid, None, Some("cov")),
    )
    .await;
    assert!(sync.errors.is_empty(), "{:?}", sync.errors);

    model_overlay::upsert_engineer_point_overlay(
        &root,
        site,
        pid,
        model_overlay::EngineerPointOverlayPatch {
            unit: Some("degF"),
            quantity: Some("absolute_temperature"),
            cadence_secs: None,
            primary_reference: None,
        },
        false,
    )
    .expect("overlay set unit");

    refresh_point_map_overlay(&tsdb, &root, site, &[pid.to_string()])
        .await
        .expect("overlay refresh set");

    let role_unit: Option<String> = sqlx::query_scalar(
        "SELECT unit FROM role_map WHERE building_id = $1 \
         AND openfdd_key IN (SELECT openfdd_key FROM point_map WHERE site_id = $1 AND portal_point_id = $2)",
    )
    .bind(site)
    .bind(pid)
    .fetch_one(&pool)
    .await
    .expect("role_map unit before clear");
    assert_eq!(role_unit.as_deref(), Some("degF"));

    model_overlay::upsert_engineer_point_overlay(
        &root,
        site,
        pid,
        model_overlay::EngineerPointOverlayPatch {
            unit: Some(""),
            quantity: None,
            cadence_secs: None,
            primary_reference: None,
        },
        false,
    )
    .expect("overlay clear unit");

    refresh_point_map_overlay(&tsdb, &root, site, &[pid.to_string()])
        .await
        .expect("overlay refresh");

    let pm_unit: Option<String> = sqlx::query_scalar(
        "SELECT unit FROM point_map WHERE site_id = $1 AND portal_point_id = $2",
    )
    .bind(site)
    .bind(pid)
    .fetch_one(&pool)
    .await
    .expect("point_map unit");
    assert!(pm_unit.is_none(), "engineer cleared unit should be NULL");

    let role_unit: Option<String> = sqlx::query_scalar(
        "SELECT unit FROM role_map WHERE building_id = $1 \
         AND openfdd_key IN (SELECT openfdd_key FROM point_map WHERE site_id = $1 AND portal_point_id = $2)",
    )
    .bind(site)
    .bind(pid)
    .fetch_one(&pool)
    .await
    .expect("role_map unit after clear");
    assert!(
        role_unit.is_none(),
        "role_map.unit must follow cleared engineer unit"
    );

    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
}
