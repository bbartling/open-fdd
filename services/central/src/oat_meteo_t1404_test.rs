//! T1404-1 / T1404-2 / T1404-3: OAT-METEO as-of join, primary local OAT, bas-vs-web parity.

use chrono::{Duration, TimeZone, Utc};
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::Row;

use super::*;

const HELPERS: &str = include_str!("../../../sql/fdd/postgres/postgres_helpers.sql");
const PACK_RUNTIME: &str = include_str!("../../../sql/schema/06_fdd_pack_runtime.sql");

pub(super) async fn pool() -> Option<sqlx::PgPool> {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .filter(|v| !v.trim().is_empty())?;
    PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .ok()
}

pub(super) async fn apply_schema(pool: &sqlx::PgPool) {
    crate::portal_inventory_fixtures::apply_schema(pool).await;
    crate::series_binding::ensure_authorized_series(pool).await;
    let mut conn = pool.acquire().await.expect("conn");
    sqlx::query("SELECT pg_advisory_lock(70317)")
        .execute(&mut *conn)
        .await
        .expect("lock");
    let installed = sqlx::raw_sql(HELPERS).execute(&mut *conn).await;
    installed.expect("helpers");
    for statement in crate::db_lifecycle::statements(PACK_RUNTIME) {
        sqlx::raw_sql(&statement)
            .execute(&mut *conn)
            .await
            .expect("pack runtime");
    }
    sqlx::query("SELECT pg_advisory_unlock(70317)")
        .execute(&mut *conn)
        .await
        .expect("unlock");
}

pub(super) async fn purge(pool: &sqlx::PgPool, site: &str) {
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

pub(super) async fn seed_site(pool: &sqlx::PgPool, site: &str) {
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

pub(super) async fn bind_point(
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

pub(super) async fn upsert_samples(pool: &sqlx::PgPool, batch: UpsertBatch) {
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

/// Sample declared in °F the way a BACnet/NF source reports it; the single SI
/// writer (`prepare_numeric_sample`) converts it to metric-c-v2 °C storage.
fn sample_degf(
    site: &str,
    equipment_id: &str,
    role: &str,
    key: &str,
    minutes: i64,
    val_degf: f64,
) -> SampleRow {
    let mut row = sample(site, equipment_id, role, key, minutes, val_degf);
    row.source_unit = Some("degF".to_string());
    row.quantity = Some("absolute_temperature".to_string());
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
    match crate::sql_pack::prepare_rule_inputs(&mut tx, site, None, None, &sql, true).await {
        Ok(crate::sql_pack::InputGate::Ready(_)) => {}
        Ok(crate::sql_pack::InputGate::Stop(stop)) => {
            let _ = tx.rollback().await;
            panic!("prepare_rule_inputs stopped: {stop:?}");
        }
        Err(err) => {
            let _ = tx.rollback().await;
            panic!("prepare_rule_inputs: {err:?}");
        }
    }
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
        batch.push(sample_degf(&site, "WX", "oa_t", "WX.oa_t_a", m, 57.0));
    }
    for m in (0..=120).step_by(20) {
        batch.push(sample_degf(&site, "WX", "web_oa_t", "WX.web_oa_t", m, 50.0));
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
        (fault_hours - 1.75).abs() < 0.1,
        "fault_hours={fault_hours}"
    );

    sqlx::query("DELETE FROM sample WHERE site_id = $1")
        .bind(&site)
        .execute(&pool)
        .await
        .expect("clear samples");
    let mut mild = UpsertBatch::default();
    for m in (0..=120).step_by(5) {
        mild.push(sample_degf(&site, "WX", "oa_t", "WX.oa_t_a", m, 53.0));
    }
    for m in (0..=120).step_by(20) {
        mild.push(sample_degf(&site, "WX", "web_oa_t", "WX.web_oa_t", m, 50.0));
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

async fn run_bas_vs_web(
    pool: &sqlx::PgPool,
    site: &str,
    scope: &crate::timescale_analytics::AnalyticsSqlScope,
) -> Value {
    let tsdb = Tsdb::from_pool(pool.clone());
    crate::timescale_analytics::bas_vs_web_oat(&tsdb, site, scope, 2000)
        .await
        .expect("bas_vs_web_oat")
}

async fn run_bas_vs_web_open(pool: &sqlx::PgPool, site: &str) -> Value {
    let scope = crate::timescale_analytics::AnalyticsSqlScope {
        start: None,
        end: None,
        equipment_ids: Vec::new(),
    };
    run_bas_vs_web(pool, site, &scope).await
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_WORKSPACE for engineer overlay file"
)]
async fn t1404_3_bas_vs_web_primary_and_default_reference() {
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());

    let Some(pool) = pool().await else {
        return;
    };
    apply_schema(&pool).await;
    let site = format!("t1404c{}", uuid::Uuid::new_v4().simple());
    purge(&pool, &site).await;
    seed_site(&pool, &site).await;
    bind_point(&pool, &site, "WX", "oa_t", "WX.oa_t_a", "pt-oa-a").await;
    bind_point(&pool, &site, "WX", "oa_t", "WX.oa_t_b", "pt-oa-b").await;
    bind_point(&pool, &site, "WX", "web_oa_t", "WX.web_oa_t", "pt-web").await;

    let mut batch = UpsertBatch::default();
    for m in (0..=60).step_by(5) {
        batch.push(sample(&site, "WX", "oa_t", "WX.oa_t_a", m, 57.0));
        batch.push(sample(&site, "WX", "oa_t", "WX.oa_t_b", m, 50.0));
    }
    for m in (0..=60).step_by(20) {
        batch.push(sample(&site, "WX", "web_oa_t", "WX.web_oa_t", m, 50.0));
    }
    upsert_samples(&pool, batch).await;

    let default_body = run_bas_vs_web_open(&pool, &site).await;
    let default_ref = default_body
        .get("oa_t_reference")
        .expect("oa_t_reference metadata");
    assert_eq!(
        default_ref.get("selection").and_then(|v| v.as_str()),
        Some("default_lowest_binding")
    );
    assert_eq!(
        default_ref.get("openfdd_key").and_then(|v| v.as_str()),
        Some("WX.oa_t_a")
    );
    let default_rows = default_body
        .get("rows")
        .and_then(|v| v.as_array())
        .expect("rows");
    assert!(
        !default_rows.is_empty(),
        "expected assessable bas-vs-web rows"
    );
    for row in default_rows {
        assert_eq!(row.get("bas_oa_t").and_then(|v| v.as_f64()), Some(57.0));
    }
    let mut per_ts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    for row in default_rows {
        if let Some(ts) = row.get("ts").and_then(|v| v.as_str()) {
            *per_ts.entry(ts.to_string()).or_insert(0) += 1;
        }
    }
    assert!(
        per_ts.values().all(|&n| n == 1),
        "each timestamp must return one row: {per_ts:?}"
    );

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

    let primary_body = run_bas_vs_web_open(&pool, &site).await;
    let primary_ref = primary_body
        .get("oa_t_reference")
        .expect("oa_t_reference metadata");
    assert_eq!(
        primary_ref.get("selection").and_then(|v| v.as_str()),
        Some("primary_reference")
    );
    assert_eq!(
        primary_ref.get("openfdd_key").and_then(|v| v.as_str()),
        Some("WX.oa_t_b")
    );
    let primary_rows = primary_body
        .get("rows")
        .and_then(|v| v.as_array())
        .expect("rows");
    assert!(!primary_rows.is_empty());
    for row in primary_rows {
        assert_eq!(row.get("bas_oa_t").and_then(|v| v.as_f64()), Some(50.0));
    }
    purge(&pool, &site).await;
}

#[tokio::test]
async fn t1404_4_bas_vs_web_web_prefetch_before_window_start() {
    let Some(pool) = pool().await else {
        return;
    };
    apply_schema(&pool).await;
    let site = format!("t1404d{}", uuid::Uuid::new_v4().simple());
    purge(&pool, &site).await;
    seed_site(&pool, &site).await;
    bind_point(&pool, &site, "WX", "oa_t", "WX.oa_t_a", "pt-oa-a").await;
    bind_point(&pool, &site, "WX", "web_oa_t", "WX.web_oa_t", "pt-web").await;

    let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap();
    let mut batch = UpsertBatch::default();
    batch.push(sample(&site, "WX", "web_oa_t", "WX.web_oa_t", -10, 48.0));
    batch.push(sample(&site, "WX", "oa_t", "WX.oa_t_a", 5, 50.0));
    upsert_samples(&pool, batch).await;

    let scope = crate::timescale_analytics::AnalyticsSqlScope {
        start: Some(t0),
        end: Some(t0 + Duration::hours(2)),
        equipment_ids: Vec::new(),
    };
    let body = run_bas_vs_web(&pool, &site, &scope).await;
    let rows = body.get("rows").and_then(|v| v.as_array()).expect("rows");
    assert_eq!(
        rows.len(),
        1,
        "web sample before window start must as-of join: {body}"
    );
    assert_eq!(rows[0].get("bas_oa_t").and_then(|v| v.as_f64()), Some(50.0));
    assert_eq!(rows[0].get("web_oa_t").and_then(|v| v.as_f64()), Some(48.0));
    purge(&pool, &site).await;
}

#[test]
fn bas_vs_web_cache_config_line_changes_with_primary_overlay() {
    use crate::timescale_product::{bas_vs_web_oa_t_config_line, SiteOatReference};

    let default = bas_vs_web_oa_t_config_line(Some(&SiteOatReference {
        openfdd_key: "WX.oa_t_a".into(),
        equipment_id: "WX".into(),
        selection: "default_lowest_binding".into(),
    }));
    let primary = bas_vs_web_oa_t_config_line(Some(&SiteOatReference {
        openfdd_key: "WX.oa_t_b".into(),
        equipment_id: "WX".into(),
        selection: "primary_reference".into(),
    }));
    assert_ne!(default, primary);
}
