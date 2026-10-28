//! T1407-1: VAV-1 occupancy gate and declared-unit comfort rank.

use chrono::{Duration, TimeZone, Utc};
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
use serde_json::json;
use sqlx::postgres::PgPoolOptions;

use super::*;

const HELPERS: &str = include_str!("../../../sql/fdd/postgres/postgres_helpers.sql");
const PACK_RUNTIME: &str = include_str!("../../../sql/schema/06_fdd_pack_runtime.sql");

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
    crate::series_binding::ensure_authorized_series(pool).await;
    let mut conn = pool.acquire().await.expect("conn");
    sqlx::query("SELECT pg_advisory_lock(70318)")
        .execute(&mut *conn)
        .await
        .expect("lock");
    sqlx::raw_sql(HELPERS)
        .execute(&mut *conn)
        .await
        .expect("helpers");
    for statement in crate::db_lifecycle::statements(PACK_RUNTIME) {
        sqlx::raw_sql(&statement)
            .execute(&mut *conn)
            .await
            .expect("pack runtime");
    }
    sqlx::query("SELECT pg_advisory_unlock(70318)")
        .execute(&mut *conn)
        .await
        .expect("unlock");
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

async fn seed_vav_site(pool: &sqlx::PgPool, site: &str, equipment_id: &str) {
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
        "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'vav') ON CONFLICT DO NOTHING",
    )
    .bind(site)
    .bind(equipment_id)
    .execute(pool)
    .await
    .expect("equip");
}

async fn bind_role(
    pool: &sqlx::PgPool,
    site: &str,
    equipment_id: &str,
    role: &str,
    key: &str,
    portal_point_id: &str,
) {
    sqlx::query(
        "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id, portal_point_id, referenced)
         VALUES ($1, $2, $2, $3, $4, $5, true)
         ON CONFLICT (site_id, openfdd_key) DO UPDATE
           SET role = EXCLUDED.role, equipment_id = EXCLUDED.equipment_id",
    )
    .bind(site)
    .bind(key)
    .bind(role)
    .bind(equipment_id)
    .bind(portal_point_id)
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

async fn upsert_samples(pool: &sqlx::PgPool, batch: UpsertBatch) {
    let tsdb = Tsdb::from_pool(pool.clone());
    tsdb.upsert_samples_stats(&batch).await.expect("upsert");
}

fn sample(
    site: &str,
    equipment_id: &str,
    role: &str,
    key: &str,
    minutes: i64,
    val: f64,
    unit: Option<&str>,
) -> SampleRow {
    let ts = Utc.with_ymd_and_hms(2026, 6, 2, 12, 0, 0).unwrap() + Duration::minutes(minutes);
    let mut row = SampleRow::new(ts, site, key.to_string(), Some(val));
    row.equipment_id = Some(equipment_id.to_string());
    row.role = Some(role.to_string());
    row.unit = unit.map(str::to_string);
    row
}

fn result_row<'a>(
    body: &'a serde_json::Value,
    rule_id: &str,
    equipment_id: &str,
) -> &'a serde_json::Value {
    body.get("results")
        .and_then(|v| v.as_array())
        .and_then(|rows| {
            rows.iter().find(|row| {
                row.get("rule_id").and_then(|v| v.as_str()) == Some(rule_id)
                    && row.get("equipment_id").and_then(|v| v.as_str()) == Some(equipment_id)
            })
        })
        .unwrap_or_else(|| panic!("missing {rule_id}/{equipment_id} in {body}"))
}

async fn run_vav1(pool: &sqlx::PgPool, site: &str, extra: serde_json::Value) -> serde_json::Value {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL").expect("db url");
    std::env::set_var("OPENFDD_DATABASE_URL", &url);
    std::env::set_var("OPENFDD_HISTORIAN", "timescale");
    fdd_tsdb::clear_shared_pool();
    let mut payload = json!({
        "building_id": site,
        "confirmation_seconds": 0,
    });
    if let Some(obj) = extra.as_object() {
        for (k, v) in obj {
            payload[k] = v.clone();
        }
    }
    crate::timescale_product::run_fdd_registry(&payload)
        .await
        .expect("run")
}

#[tokio::test]
async fn t1407_vav1_occupancy_and_comfort_units() {
    let Some(pool) = pool().await else {
        eprintln!("SKIP t1407_vav1_occupancy_and_comfort_units: OPENFDD_TEST_DATABASE_URL unset");
        return;
    };
    apply_schema(&pool).await;
    let token = uuid::Uuid::new_v4().simple().to_string();
    let site_no_occ = format!("t1407a{}", &token[..6]);
    let site_sched = format!("t1407b{}", &token[..6]);
    let site_c = format!("t1407c{}", &token[..6]);

    for site in [&site_no_occ, &site_sched, &site_c] {
        purge(&pool, site).await;
    }

    seed_vav_site(&pool, &site_no_occ, "VAV_A").await;
    bind_role(&pool, &site_no_occ, "VAV_A", "zone_t", "VAV_A.zt", "pt-a").await;
    upsert_samples(
        &pool,
        UpsertBatch {
            rows: vec![
                sample(
                    &site_no_occ,
                    "VAV_A",
                    "zone_t",
                    "VAV_A.zt",
                    0,
                    80.0,
                    Some("degF"),
                ),
                sample(
                    &site_no_occ,
                    "VAV_A",
                    "zone_t",
                    "VAV_A.zt",
                    5,
                    80.0,
                    Some("degF"),
                ),
            ],
        },
    )
    .await;

    seed_vav_site(&pool, &site_sched, "VAV_B").await;
    bind_role(&pool, &site_sched, "VAV_B", "zone_t", "VAV_B.zt", "pt-b").await;
    upsert_samples(
        &pool,
        UpsertBatch {
            rows: vec![
                sample(
                    &site_sched,
                    "VAV_B",
                    "zone_t",
                    "VAV_B.zt",
                    0,
                    80.0,
                    Some("degF"),
                ),
                sample(
                    &site_sched,
                    "VAV_B",
                    "zone_t",
                    "VAV_B.zt",
                    5,
                    72.0,
                    Some("degF"),
                ),
            ],
        },
    )
    .await;

    seed_vav_site(&pool, &site_c, "VAV_C").await;
    bind_role(&pool, &site_c, "VAV_C", "zone_t", "VAV_C.zt", "pt-c").await;
    upsert_samples(
        &pool,
        UpsertBatch {
            rows: vec![
                sample(
                    &site_c,
                    "VAV_C",
                    "zone_t",
                    "VAV_C.zt",
                    0,
                    22.0,
                    Some("degC"),
                ),
                sample(
                    &site_c,
                    "VAV_C",
                    "zone_t",
                    "VAV_C.zt",
                    5,
                    28.0,
                    Some("degC"),
                ),
            ],
        },
    )
    .await;

    let no_occ = run_vav1(&pool, &site_no_occ, json!({})).await;
    let skip = result_row(&no_occ, "VAV-1", "VAV_A");
    assert_eq!(
        skip.get("status").and_then(|v| v.as_str()),
        Some("NOT_ASSESSED_NO_OCCUPANCY")
    );
    assert_eq!(skip.get("fault_hours").and_then(|v| v.as_f64()), Some(0.0));

    let with_sched = run_vav1(
        &pool,
        &site_sched,
        json!({
            "occupancy_schedule": {
                "timezone": "UTC",
                "days": {
                    "tue": { "occupied": true, "start": "00:00", "end": "23:59" }
                }
            }
        }),
    )
    .await;
    let evaluated = result_row(&with_sched, "VAV-1", "VAV_B");
    assert!(
        matches!(
            evaluated.get("status").and_then(|v| v.as_str()),
            Some("FAULT") | Some("PASS")
        ),
        "{evaluated}"
    );

    std::env::set_var(
        "OPENFDD_DATABASE_URL",
        std::env::var("OPENFDD_TEST_DATABASE_URL").expect("db url"),
    );
    fdd_tsdb::clear_shared_pool();
    let rank = rcx_zone_comfort_rank(
        &site_c,
        &["vav"],
        70.0,
        75.0,
        &crate::timescale_analytics::AnalyticsSqlScope {
            start: None,
            end: None,
            equipment_ids: vec!["VAV_C".into()],
        },
    )
    .await
    .expect("rank")
    .expect("rank env");
    let pct = rank.points[0]["comfort_pct"].as_f64().expect("pct");
    assert!(
        (pct - 50.0).abs() < 1e-6,
        "expected 50% in-band for °C fixture, got {pct}"
    );

    for site in [&site_no_occ, &site_sched, &site_c] {
        purge(&pool, site).await;
    }
}
