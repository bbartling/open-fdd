//! T1406: upgrade from 4.0.6 authorized_series view to W1a binding metadata.

use sqlx::postgres::PgPoolOptions;
use sqlx::Row;

const OLD_VIEW: &str = include_str!("../../../../sql/schema/fixtures/authorized_series_v4_0_6.sql");
const BINDING_DDL: &str = include_str!("../../../../sql/schema/11_point_map_binding_metadata.sql");
const NEW_VIEW: &str = include_str!("../../../../sql/schema/07_opaque_series_binding.sql");
const UPGRADE_TEST_LOCK: i64 = 14_061_406;

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

async fn baseline_tables(pool: &sqlx::PgPool) {
    crate::test_ddl::execute_idempotent_ddl(pool, "DROP VIEW IF EXISTS authorized_series CASCADE")
        .await;
    for statement in [
        "CREATE TABLE IF NOT EXISTS site (
            site_id text PRIMARY KEY,
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS point_map (
            site_id text NOT NULL,
            openfdd_key text NOT NULL,
            haystack_id text NOT NULL,
            role text,
            unit text,
            equipment_id text,
            portal_point_id text,
            referenced boolean NOT NULL DEFAULT true,
            provider_instance_id text,
            PRIMARY KEY (site_id, openfdd_key)
        )",
        "CREATE TABLE IF NOT EXISTS role_map (
            building_id text NOT NULL,
            equipment_id text NOT NULL,
            openfdd_key text NOT NULL,
            role text NOT NULL,
            unit text,
            PRIMARY KEY (building_id, equipment_id, openfdd_key)
        )",
    ] {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
    for statement in crate::db_lifecycle::statements(OLD_VIEW) {
        crate::test_ddl::execute_idempotent_ddl(pool, &statement).await;
    }
}

#[tokio::test]
async fn t1406_authorized_series_view_upgrades_from_v406_column_order() {
    let Some(pool) = pool().await else {
        return;
    };
    let site = "T1406_SCHEMA_UPGRADE";
    sqlx::query("SELECT pg_advisory_lock($1)")
        .bind(UPGRADE_TEST_LOCK)
        .execute(&pool)
        .await
        .expect("upgrade test lock");
    baseline_tables(&pool).await;

    sqlx::query("INSERT INTO site (site_id) VALUES ($1) ON CONFLICT DO NOTHING")
        .bind(site)
        .execute(&pool)
        .await
        .expect("site");
    sqlx::query(
        "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, unit, equipment_id, \
         portal_point_id, referenced, provider_instance_id) \
         VALUES ($1, 'AHU_1.sat', 'pt-upg', 'sat', 'degC', 'AHU_1', 'pt-upg', true, 'nf:upg') \
         ON CONFLICT DO NOTHING",
    )
    .bind(site)
    .execute(&pool)
    .await
    .expect("point_map");
    sqlx::query(
        "INSERT INTO role_map (building_id, equipment_id, openfdd_key, role, unit) \
         VALUES ($1, 'AHU_1', 'AHU_1.sat', 'sat', 'degC') ON CONFLICT DO NOTHING",
    )
    .bind(site)
    .execute(&pool)
    .await
    .expect("role_map");

    for statement in crate::db_lifecycle::statements(BINDING_DDL) {
        crate::test_ddl::execute_idempotent_ddl(&pool, &statement).await;
    }
    crate::test_ddl::execute_idempotent_ddl(&pool, "DROP VIEW IF EXISTS authorized_series CASCADE")
        .await;
    for statement in crate::db_lifecycle::statements(NEW_VIEW) {
        crate::test_ddl::execute_idempotent_ddl(&pool, &statement).await;
    }

    let cols: Vec<String> = sqlx::query_scalar(
        "SELECT column_name FROM information_schema.columns \
         WHERE table_schema = 'public' AND table_name = 'authorized_series' \
         ORDER BY ordinal_position",
    )
    .fetch_all(&pool)
    .await
    .expect("columns");
    assert_eq!(
        cols,
        vec![
            "site_id",
            "openfdd_key",
            "equipment_id",
            "role",
            "unit",
            "referenced",
            "portal_point_id",
            "provider_instance_id",
            "haystack_id",
            "quantity",
            "cadence_secs",
            "history_mode",
        ]
    );

    sqlx::query(
        "UPDATE point_map SET unit = 'degF', quantity = 'absolute_temperature', \
         cadence_secs = 900, history_mode = 'interval' WHERE site_id = $1",
    )
    .bind(site)
    .execute(&pool)
    .await
    .expect("bind metadata");

    let row = sqlx::query(
        "SELECT unit, quantity, cadence_secs, history_mode FROM authorized_series \
         WHERE site_id = $1 AND role = 'sat'",
    )
    .bind(site)
    .fetch_one(&pool)
    .await
    .expect("authorized_series row");
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
        row.get::<Option<String>, _>("history_mode").as_deref(),
        Some("interval")
    );

    for sql in [
        "DELETE FROM role_map WHERE building_id = $1",
        "DELETE FROM point_map WHERE site_id = $1",
        "DELETE FROM site WHERE site_id = $1",
    ] {
        sqlx::query(sql).bind(site).execute(&pool).await.expect(sql);
    }
    sqlx::query("SELECT pg_advisory_unlock($1)")
        .bind(UPGRADE_TEST_LOCK)
        .execute(&pool)
        .await
        .expect("upgrade test unlock");
}
