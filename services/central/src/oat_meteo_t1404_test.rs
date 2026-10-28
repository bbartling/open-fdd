//! T1404-1 / T1404-2: OAT-METEO as-of join and primary local OAT reference.

use chrono::{Duration, TimeZone, Utc};
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
use serde_json::json;
use sqlx::postgres::PgPoolOptions;
use sqlx::Row;

use super::*;

const HELPERS: &str = include_str!("../../../sql/fdd/postgres/postgres_helpers.sql");

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
    let mut conn = pool.acquire().await.expect("conn");
    sqlx::query("SELECT pg_advisory_lock(70317)")
        .execute(&mut *conn)
        .await
        .expect("lock");
    let installed = sqlx::raw_sql(HELPERS).execute(&mut *conn).await;
    sqlx::query("SELECT pg_advisory_unlock(70317)")
        .execute(&mut *conn)
        .await
        .expect("unlock");
    installed.expect("helpers");
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

async fn seed_site(pool: &sqlx::PgPool, site: &str) {
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
    for (eq, kind) in [("WX", "weather"), ("AHU_1", "ahu")] {
        sqlx::query(
            "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        )
        .bind(site)
        .bind(eq)
        .bind(kind)
        .execute(pool)
        .await
        .expect("equip");
    }
}

async fn bind_point(
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
           SET role = EXCLUDED.role, equipment_id = EXCLUDED.equipment_id, portal_point_id = EXCLUDED.portal_point_id",
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
) -> SampleRow {
    let ts = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap() + Duration::minutes(minutes);
    let mut row = SampleRow::new(ts, site, key.to_string(), Some(val));
    row.equipment_id = Some(equipment_id.to_string());
    row.role = Some(role.to_string());
    row
}

async fn run_oat_meteo(pool: &sqlx::PgPool, site: &str, fill: Option<HistoryFillOptions>) -> f64 {
    let reg = load_reg().expect("registry");
    let rule = reg
        .rules
        .iter()
        .find(|r| r.rule_id == "OAT-METEO")
        .expect("rule");
    let sql = wrap_rule_sql(
        &render_rule_sql(&reg, rule, 300.0, 900, site, Some("AHU_1"), None).expect("render"),
        rule,
    );
    let roles = rule_history_roles(rule);
    let mut tx = pool.begin().await.expect("tx");
    ensure_history_table(&mut tx, &roles)
        .await
        .expect("history");
    let n = fill_history_for_equipment(&mut tx, site, "AHU_1", &roles, None, None, fill.as_ref())
        .await
        .expect("fill");
    assert!(n > 0, "history rows");
    crate::sql_pack::prepare_rule_inputs(&mut tx, site, None, None, &sql, true)
        .await
        .expect("inputs");
    let row = sqlx::query(&sql).fetch_one(&mut *tx).await.expect("rule");
    let _ = tx.rollback().await;
    row.try_get::<f64, _>("fault_hours").unwrap_or(0.0)
}

#[tokio::test]
async fn t1404_sql_asof_fixture_offsets_and_gap() {
    let Some(pool) = pool().await else {
        return;
    };
    apply_schema(&pool).await;
    let site = format!("t1404{}", uuid::Uuid::new_v4().simple());
    purge(&pool, &site).await;
    seed_site(&pool, &site).await;
    bind_point(&pool, &site, "WX", "web_oa_t", "WX.web_oa_t", "pt-web").await;
    bind_point(&pool, &site, "WX", "oa_t", "WX.oa_t_a", "pt-oa-a").await;
    bind_point(&pool, &site, "WX", "oa_t", "WX.oa_t_b", "pt-oa-b").await;

    let mut batch = UpsertBatch::default();
    for m in (0..=120).step_by(5) {
        batch.push(sample(&site, "WX", "oa_t", "WX.oa_t_a", m, 57.0));
    }
    for m in (0..=120).step_by(20) {
        batch.push(sample(&site, "WX", "web_oa_t", "WX.web_oa_t", m, 50.0));
    }
    upsert_samples(&pool, batch).await;

    let fill = HistoryFillOptions {
        site_oa_t: Some(SiteOatReference {
            openfdd_key: "WX.oa_t_a".into(),
            equipment_id: "WX".into(),
            selection: "default_lowest_binding".into(),
        }),
    };
    let fault_hours = run_oat_meteo(&pool, &site, Some(fill.clone())).await;
    assert!(
        (fault_hours - 1.75).abs() < 0.05,
        "fault_hours={fault_hours}"
    );

    let mut mild = UpsertBatch::default();
    for m in (0..=120).step_by(5) {
        mild.push(sample(&site, "WX", "oa_t", "WX.oa_t_a", m + 200, 53.0));
    }
    for m in (0..=120).step_by(20) {
        mild.push(sample(
            &site,
            "WX",
            "web_oa_t",
            "WX.web_oa_t",
            m + 200,
            50.0,
        ));
    }
    upsert_samples(&pool, mild).await;
    let mild_hours = run_oat_meteo(&pool, &site, Some(fill)).await;
    assert_eq!(mild_hours, 0.0);

    purge(&pool, &site).await;
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_WORKSPACE for engineer overlay file"
)]
async fn t1404_primary_reference_selection() {
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());

    let Some(pool) = pool().await else {
        return;
    };
    apply_schema(&pool).await;
    let site = format!("t1404b{}", uuid::Uuid::new_v4().simple());
    purge(&pool, &site).await;
    seed_site(&pool, &site).await;
    bind_point(&pool, &site, "WX", "oa_t", "WX.oa_t_a", "pt-oa-a").await;
    bind_point(&pool, &site, "WX", "oa_t", "WX.oa_t_b", "pt-oa-b").await;
    bind_point(&pool, &site, "WX", "web_oa_t", "WX.web_oa_t", "pt-web").await;

    let root = csv_building_root(&site);
    std::fs::create_dir_all(&root).expect("dir");
    let overlay = json!({
        "schema": "openfdd_model_point_engineer_overlay_v1",
        "building_id": site,
        "points": {
            "pt-oa-b": { "primary_reference": true }
        }
    });
    std::fs::write(
        root.join("model_point_engineer_overlay.json"),
        serde_json::to_string_pretty(&overlay).expect("json"),
    )
    .expect("overlay");

    let mut batch = UpsertBatch::default();
    for m in (0..=60).step_by(5) {
        batch.push(sample(&site, "WX", "oa_t", "WX.oa_t_a", m, 57.0));
        batch.push(sample(&site, "WX", "oa_t", "WX.oa_t_b", m, 50.0));
    }
    for m in (0..=60).step_by(20) {
        batch.push(sample(&site, "WX", "web_oa_t", "WX.web_oa_t", m, 50.0));
    }
    upsert_samples(&pool, batch).await;

    let picked = resolve_site_oa_t_reference(&pool, &site)
        .await
        .expect("resolve")
        .expect("reference");
    assert_eq!(picked.openfdd_key, "WX.oa_t_b");
    assert_eq!(picked.selection, "primary_reference");

    let fill = HistoryFillOptions {
        site_oa_t: Some(picked),
    };
    let fault_hours = run_oat_meteo(&pool, &site, Some(fill)).await;
    assert_eq!(fault_hours, 0.0);
    purge(&pool, &site).await;
}
