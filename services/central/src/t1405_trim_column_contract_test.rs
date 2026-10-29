//! T1405-3: TRIM optional reset-request roles pivot as NULL without SQL failure.

use chrono::{Duration, TimeZone, Utc};
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
use serde_json::{json, Value};
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
    for statement in crate::db_lifecycle::statements(HELPERS) {
        sqlx::raw_sql(&statement)
            .execute(&mut *conn)
            .await
            .expect("helpers");
    }
    for statement in crate::db_lifecycle::statements(PACK_RUNTIME) {
        sqlx::raw_sql(&statement)
            .execute(&mut *conn)
            .await
            .expect("pack runtime");
    }
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

async fn seed_site(pool: &sqlx::PgPool, site: &str, equip_type: &str, equipment_id: &str) {
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
        "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
    )
    .bind(site)
    .bind(equipment_id)
    .bind(equip_type)
    .execute(pool)
    .await
    .expect("equip");
}

async fn bind_point(pool: &sqlx::PgPool, site: &str, equipment_id: &str, role: &str, key: &str) {
    sqlx::query(
        "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id, referenced)
         VALUES ($1, $2, $2, $3, $4, true)
         ON CONFLICT (site_id, openfdd_key) DO UPDATE
           SET role = EXCLUDED.role, equipment_id = EXCLUDED.equipment_id",
    )
    .bind(site)
    .bind(key)
    .bind(role)
    .bind(equipment_id)
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

fn result_row<'a>(meta: &'a Value, rule_id: &str, equipment_id: &str) -> &'a Value {
    meta.get("results")
        .and_then(Value::as_array)
        .and_then(|rows| {
            rows.iter().find(|row| {
                row.get("rule_id").and_then(Value::as_str) == Some(rule_id)
                    && row.get("equipment_id").and_then(Value::as_str) == Some(equipment_id)
            })
        })
        .unwrap_or_else(|| panic!("missing {rule_id}/{equipment_id} in {meta}"))
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL with other Timescale registry tests"
)]
async fn t1405_3_trim_rules_without_reset_request_binding_not_sql_error() {
    let _lock = crate::test_env_lock::lock_env();
    let Some(pool) = pool().await else {
        eprintln!("skip: OPENFDD_TEST_DATABASE_URL unset");
        return;
    };
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL").expect("db url");
    let site = format!("t1405{}", uuid::Uuid::new_v4().simple());
    apply_schema(&pool).await;
    purge(&pool, &site).await;

    seed_site(&pool, &site, "boiler", "BLR_1").await;
    bind_point(&pool, &site, "BLR_1", "hw_supply_t", "BLR_1.hw_supply_t").await;
    bind_point(&pool, &site, "BLR_1", "chw_flow", "BLR_1.chw_flow").await;

    seed_site(&pool, &site, "chiller", "CHW_1").await;
    bind_point(&pool, &site, "CHW_1", "chw_supply_t", "CHW_1.chw_supply_t").await;
    bind_point(&pool, &site, "CHW_1", "chw_flow", "CHW_1.chw_flow").await;

    let mut batch = UpsertBatch::default();
    for minute in (0..12).step_by(3) {
        batch.push(sample(
            &site,
            "BLR_1",
            "hw_supply_t",
            "BLR_1.hw_supply_t",
            minute,
            165.0,
        ));
        batch.push(sample(
            &site,
            "BLR_1",
            "chw_flow",
            "BLR_1.chw_flow",
            minute,
            50.0,
        ));
        batch.push(sample(
            &site,
            "CHW_1",
            "chw_supply_t",
            "CHW_1.chw_supply_t",
            minute,
            44.0,
        ));
        batch.push(sample(
            &site,
            "CHW_1",
            "chw_flow",
            "CHW_1.chw_flow",
            minute,
            50.0,
        ));
    }
    let tsdb = Tsdb::from_pool(pool.clone());
    tsdb.upsert_samples_stats(&batch).await.expect("upsert");

    let reg = load_reg().expect("registry");
    let trim3 = reg
        .rules
        .iter()
        .find(|r| r.rule_id == "TRIM-3")
        .expect("TRIM-3");
    let roles = rule_history_roles(trim3);
    assert!(
        roles.iter().any(|r| r == "hw_reset_request_sum"),
        "registry optional role must pivot hw_reset_request_sum"
    );
    let mut tx = pool.begin().await.expect("tx");
    ensure_history_table(&mut tx, &roles)
        .await
        .expect("history table");
    let n = fill_history_for_equipment(&mut tx, &site, "BLR_1", &roles, None, None, None)
        .await
        .expect("fill history");
    assert!(n > 0, "history rows");
    let nulls: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)::bigint FROM history WHERE hw_reset_request_sum IS NULL",
    )
    .fetch_one(&mut *tx)
    .await
    .expect("null count");
    assert_eq!(
        nulls, n,
        "unbound optional role projects NULL, not missing column"
    );
    let _ = tx.rollback().await;

    let results_dir = tempfile::tempdir().expect("results dir");
    struct EnvRestore {
        saved: Vec<(String, Option<String>)>,
    }
    impl EnvRestore {
        fn capture(keys: &[&str]) -> Self {
            Self {
                saved: keys
                    .iter()
                    .map(|k| (k.to_string(), std::env::var(k).ok()))
                    .collect(),
            }
        }
    }
    impl Drop for EnvRestore {
        fn drop(&mut self) {
            for (key, val) in &self.saved {
                match val {
                    Some(v) => std::env::set_var(key, v),
                    None => std::env::remove_var(key),
                }
            }
        }
    }
    let _env = EnvRestore::capture(&[
        "OPENFDD_DATABASE_URL",
        "OPENFDD_HISTORIAN",
        "OPENFDD_RULE_RESULTS_DIR",
    ]);
    std::env::set_var("OPENFDD_DATABASE_URL", &url);
    std::env::set_var("OPENFDD_HISTORIAN", "timescale");
    std::env::set_var("OPENFDD_RULE_RESULTS_DIR", results_dir.path());
    fdd_tsdb::clear_shared_pool();

    let payload = json!({
        "building_id": site,
        "rule_ids": ["TRIM-3", "TRIM-4"],
        "confirmation_seconds": 0,
    });
    let out = run_fdd_registry(&payload)
        .await
        .unwrap_or_else(|err| panic!("run_fdd_registry: {err}"));
    assert_eq!(out["rules_failed"], json!(0), "{out}");

    for (rule_id, equipment_id) in [("TRIM-3", "BLR_1"), ("TRIM-4", "CHW_1")] {
        let row = result_row(&out, rule_id, equipment_id);
        let status = row.get("status").and_then(Value::as_str).unwrap_or("");
        assert!(
            status != "ERROR" && status != "SKIP_MISSING_ROLES",
            "{rule_id} unexpected status {status}: {row}"
        );
        assert!(
            row.get("notes")
                .and_then(Value::as_str)
                .is_none_or(|notes| !notes.to_ascii_lowercase().contains("column")),
            "{rule_id} notes suggest SQL column failure: {row}"
        );
    }

    purge(&pool, &site).await;
}
