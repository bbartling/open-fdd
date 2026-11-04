//! T1513: declared source unit → canonical storage → historian API trace (#1513).

use chrono::{TimeZone, Utc};
use fdd_core::units_contract::MetricUnitsContract;
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch, UNIT_ASSESSED, UNIT_NOT_ASSESSED};
use sqlx::postgres::PgPoolOptions;

const T1513_LOCK: i64 = 151_301_513;

async fn connect_test_pool() -> Option<sqlx::PgPool> {
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
    crate::series_binding::ensure_authorized_series(pool).await;
}

async fn purge(pool: &sqlx::PgPool, site: &str) {
    for sql in [
        "DELETE FROM sample WHERE site_id = $1",
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM equipment WHERE building_id = $1",
        "DELETE FROM building WHERE building_id = $1",
        "DELETE FROM site WHERE site_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(pool).await.expect(sql);
    }
}

async fn bind_pressure(
    pool: &sqlx::PgPool,
    site: &str,
    equipment_id: &str,
    role: &str,
    key: &str,
    overlay_unit: Option<&str>,
    quantity: Option<&str>,
) {
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(site)
        .execute(pool)
        .await
        .expect("site");
    sqlx::query(
        "INSERT INTO building (building_id, site_id, dis) VALUES ($1, $1, $1) ON CONFLICT DO NOTHING",
    )
    .bind(site)
    .execute(pool)
    .await
    .expect("building");
    sqlx::query(
        "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'ahu') ON CONFLICT DO NOTHING",
    )
    .bind(site)
    .bind(equipment_id)
    .execute(pool)
    .await
    .expect("equip");
    sqlx::query(
        "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id, unit, quantity, referenced)
         VALUES ($1, $2, $2, $3, $4, $5, $6, true)
         ON CONFLICT (site_id, openfdd_key) DO UPDATE
           SET role = EXCLUDED.role, unit = EXCLUDED.unit, quantity = EXCLUDED.quantity",
    )
    .bind(site)
    .bind(key)
    .bind(role)
    .bind(equipment_id)
    .bind(overlay_unit)
    .bind(quantity)
    .execute(pool)
    .await
    .expect("point_map");
    sqlx::query(
        "INSERT INTO role_map (building_id, equipment_id, openfdd_key, role)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(site)
    .bind(equipment_id)
    .bind(key)
    .bind(role)
    .execute(pool)
    .await
    .expect("role_map");
}

#[tokio::test]
async fn t1513_historian_points_trace_inwc_to_pa_and_legacy_not_assessed() {
    let Some(pool) = connect_test_pool().await else {
        eprintln!("SKIP t1513: OPENFDD_TEST_DATABASE_URL unset");
        return;
    };
    apply_schema(&pool).await;
    sqlx::query("SELECT pg_advisory_lock($1)")
        .bind(T1513_LOCK)
        .execute(&pool)
        .await
        .expect("lock");

    let token = uuid::Uuid::new_v4().simple().to_string();
    let site = format!("t1513{}", &token[..8]);
    purge(&pool, &site).await;

    let contract = MetricUnitsContract::load_embedded().expect("contract");
    let pa = contract
        .convert_to_canonical("air_pressure", 1.214, "inH2O")
        .expect("convert");
    assert!((pa - 302.09256).abs() < 1e-3);

    bind_pressure(
        &pool,
        &site,
        "AHU_1",
        "duct_static",
        "AHU_1.duct_static",
        Some("inH2O"),
        Some("air_pressure"),
    )
    .await;
    bind_pressure(
        &pool,
        &site,
        "AHU_1",
        "duct_static_sp",
        "AHU_1.duct_static_sp",
        Some("inH2O"),
        Some("air_pressure"),
    )
    .await;
    bind_pressure(
        &pool,
        &site,
        "AHU_1",
        "duct_static_legacy",
        "AHU_1.duct_static_legacy",
        Some("inH2O"),
        Some("air_pressure"),
    )
    .await;

    let ts = Utc.with_ymd_and_hms(2026, 3, 1, 0, 0, 0).unwrap();
    let tsdb = Tsdb::from_pool(pool.clone());
    let mut batch = UpsertBatch::default();
    batch.push(SampleRow {
        ts,
        site_id: site.clone(),
        openfdd_key: "AHU_1.duct_static".into(),
        val: Some(pa),
        unit: Some("Pa".into()),
        equipment_id: Some("AHU_1".into()),
        role: Some("duct_static".into()),
        source_unit: Some("inH2O".into()),
        quantity: Some("air_pressure".into()),
        ..SampleRow::default_row(ts, &site, "AHU_1.duct_static")
    });
    batch.push(SampleRow {
        ts,
        site_id: site.clone(),
        openfdd_key: "AHU_1.duct_static_sp".into(),
        val: Some(
            contract
                .convert_to_canonical("air_pressure", 1.5, "inH2O")
                .expect("sp"),
        ),
        unit: Some("Pa".into()),
        equipment_id: Some("AHU_1".into()),
        role: Some("duct_static_sp".into()),
        source_unit: Some("inH2O".into()),
        quantity: Some("air_pressure".into()),
        ..SampleRow::default_row(ts, &site, "AHU_1.duct_static_sp")
    });
    tsdb.upsert_samples_stats(&batch).await.expect("upsert");

    // Pre-cutover row: declared inH₂O in point_map but sample never got canonical unit at write time.
    sqlx::query(
        "INSERT INTO sample (ts, site_id, openfdd_key, val, unit) VALUES ($1, $2, $3, $4, NULL)",
    )
    .bind(ts)
    .bind(&site)
    .bind("AHU_1.duct_static_legacy")
    .bind(1.214_f64)
    .execute(&pool)
    .await
    .expect("legacy sample insert");

    let points = tsdb.historian_points(&site).await.expect("historian");
    let assessed = points
        .iter()
        .find(|p| p.role.as_deref() == Some("duct_static"))
        .expect("duct_static");
    assert_eq!(assessed.unit_assessment, UNIT_ASSESSED);
    assert_eq!(assessed.declared_unit.as_deref(), Some("inH2O"));
    assert_eq!(assessed.canonical_unit.as_deref(), Some("Pa"));
    assert_eq!(assessed.storage_unit.as_deref(), Some("Pa"));

    let sp = points
        .iter()
        .find(|p| p.role.as_deref() == Some("duct_static_sp"))
        .expect("setpoint");
    assert_eq!(sp.unit_assessment, UNIT_ASSESSED);
    assert_eq!(sp.declared_unit.as_deref(), Some("inH2O"));

    let legacy = points
        .iter()
        .find(|p| p.role.as_deref() == Some("duct_static_legacy"))
        .expect("legacy");
    assert_eq!(legacy.unit_assessment, UNIT_NOT_ASSESSED);
    assert_eq!(
        legacy.unit_assessment_reason.as_deref(),
        Some("legacy_unconverted")
    );

    purge(&pool, &site).await;
    sqlx::query("SELECT pg_advisory_unlock($1)")
        .bind(T1513_LOCK)
        .execute(&pool)
        .await
        .expect("unlock");
    fdd_tsdb::clear_shared_pool();
}

trait DefaultSampleRow {
    fn default_row(ts: chrono::DateTime<Utc>, site: &str, key: &str) -> SampleRow;
}

impl DefaultSampleRow for SampleRow {
    fn default_row(ts: chrono::DateTime<Utc>, site: &str, key: &str) -> SampleRow {
        SampleRow {
            ts,
            site_id: site.to_string(),
            openfdd_key: key.to_string(),
            haystack_id: None,
            val: None,
            unit: None,
            quality: None,
            equipment_id: None,
            role: None,
            source_unit: None,
            quantity: None,
            unit_system: None,
            portal_point_id: None,
            provider_instance_id: None,
        }
    }
}
