//! T1284-2 (CI, Postgres): single-writer SI ingest parity across declared-unit paths.

use chrono::{TimeZone, Utc};
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch, QUALITY_UNIT_UNDECLARED};
use sqlx::postgres::PgPoolOptions;

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

async fn schema(pool: &sqlx::PgPool) {
    crate::portal_inventory_fixtures::apply_schema(pool).await;
    for sql in include_str!("../../../sql/schema/11_point_map_binding_metadata.sql").split(';') {
        let stmt = sql.trim();
        if stmt.is_empty() {
            continue;
        }
        crate::test_ddl::execute_idempotent_ddl(pool, stmt).await;
    }
}

fn sample_row(
    site: &str,
    equip: &str,
    role: &str,
    ts: chrono::DateTime<Utc>,
    val: f64,
    unit: &str,
) -> SampleRow {
    let key = format!("{equip}.{role}");
    let mut row = SampleRow::new(ts, site, key, Some(val));
    row.equipment_id = Some(equip.into());
    row.role = Some(role.into());
    row.unit = Some(unit.into());
    row
}

#[tokio::test]
async fn t1284_2_same_physical_series_four_ingest_paths_match_si() {
    let Some(pool) = pool().await else {
        return;
    };
    schema(&pool).await;
    let site = format!("T1284_2_{}", uuid::Uuid::new_v4().simple());
    let ts = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap();
    let ts_later = ts + chrono::Duration::hours(1);
    let tsdb = Tsdb::from_pool(pool.clone());

    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&site)
        .execute(&pool)
        .await
        .expect("site");

    let nf_site = format!("{site}_nf");
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&nf_site)
        .execute(&pool)
        .await
        .expect("nf site");
    let mut nf = UpsertBatch::default();
    nf.push(sample_row(&nf_site, "AHU_A", "oa_t", ts, 50.0, "degF"));
    tsdb.upsert_samples(&nf).await.expect("nf upsert");

    let csv_site = format!("{site}_csv");
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&csv_site)
        .execute(&pool)
        .await
        .expect("csv site");
    let mut csv = UpsertBatch::default();
    csv.push(sample_row(&csv_site, "AHU_B", "oa_t", ts, 10.0, "degC"));
    tsdb.upsert_samples(&csv).await.expect("csv upsert");

    let mixed_site = format!("{site}_mix");
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&mixed_site)
        .execute(&pool)
        .await
        .expect("mix site");
    let mut mix = UpsertBatch::default();
    mix.push(sample_row(&mixed_site, "AHU_IP", "oa_t", ts, 68.0, "degF"));
    mix.push(sample_row(&mixed_site, "AHU_SI", "oa_t", ts, 20.0, "degC"));
    tsdb.upsert_samples(&mix).await.expect("mix upsert");

    let dated_site = format!("{site}_dated");
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&dated_site)
        .execute(&pool)
        .await
        .expect("dated site");
    let mut dated = UpsertBatch::default();
    dated.push(sample_row(&dated_site, "AHU_1", "oa_t", ts, 32.0, "degF"));
    dated.push(sample_row(
        &dated_site,
        "AHU_1",
        "oa_t",
        ts_later,
        100.0,
        "degC",
    ));
    tsdb.upsert_samples(&dated).await.expect("dated upsert");

    let rows: Vec<(String, f64, Option<String>, Option<String>)> = sqlx::query_as(
        "SELECT openfdd_key, val, unit, quality FROM sample \
         WHERE site_id = ANY($1) ORDER BY site_id, openfdd_key, ts",
    )
    .bind([
        nf_site.as_str(),
        csv_site.as_str(),
        mixed_site.as_str(),
        dated_site.as_str(),
    ])
    .fetch_all(&pool)
    .await
    .expect("read samples");

    let mut temps = Vec::new();
    for (_key, val, unit, quality) in &rows {
        assert!(quality.is_none(), "unexpected quality {quality:?}");
        assert_eq!(unit.as_deref(), Some("degC"));
        temps.push(*val);
    }
    assert_eq!(temps.len(), 6);
    for val in [10.0, 20.0] {
        assert!(
            temps.iter().any(|v| (*v - val).abs() < 1e-9),
            "missing {val}"
        );
    }
    assert!(temps.iter().any(|v| (*v - 0.0).abs() < 1e-9));
    assert!(temps.iter().any(|v| (*v - 100.0).abs() < 1e-9));

    let bad_site = format!("{site}_bad");
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&bad_site)
        .execute(&pool)
        .await
        .expect("bad site");
    let mut bad = UpsertBatch::default();
    bad.push({
        let key = "AHU_X.oa_t".to_string();
        let mut row = SampleRow::new(ts, &bad_site, key, Some(70.0));
        row.equipment_id = Some("AHU_X".into());
        row.role = Some("oa_t".into());
        row
    });
    bad.push(sample_row(
        &bad_site,
        "AHU_Y",
        "oa_t",
        ts,
        70.0,
        "bogus_unit",
    ));
    bad.push(sample_row(&bad_site, "AHU_Z", "oa_t", ts, 14.7, "psi"));
    tsdb.upsert_samples(&bad).await.expect("bad upsert");

    let bad_rows: Vec<(f64, Option<String>)> =
        sqlx::query_as("SELECT val, quality FROM sample WHERE site_id = $1 ORDER BY openfdd_key")
            .bind(&bad_site)
            .fetch_all(&pool)
            .await
            .expect("bad rows");
    assert_eq!(bad_rows.len(), 3);
    for (val, quality) in bad_rows {
        assert_eq!(val, 70.0);
        assert_eq!(quality.as_deref(), Some(QUALITY_UNIT_UNDECLARED));
    }

    for s in [nf_site, csv_site, mixed_site, dated_site, bad_site] {
        sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(&s)
            .execute(&pool)
            .await
            .ok();
        sqlx::query("DELETE FROM point_map WHERE site_id = $1")
            .bind(&s)
            .execute(&pool)
            .await
            .ok();
        sqlx::query("DELETE FROM role_map WHERE building_id = $1")
            .bind(&s)
            .execute(&pool)
            .await
            .ok();
        sqlx::query("DELETE FROM site WHERE site_id = $1")
            .bind(&s)
            .execute(&pool)
            .await
            .ok();
    }
}
