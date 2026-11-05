//! T1406: upgrade from 4.0.6 authorized_series view to W1a binding metadata.
//!
//! Uses a disposable database so `DROP VIEW authorized_series` never races shared
//! CI Postgres used by inventory overlay tests.

use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};

const OLD_VIEW: &str = include_str!("../../../../sql/schema/fixtures/authorized_series_v4_0_6.sql");
const BINDING_DDL: &str = include_str!("../../../../sql/schema/11_point_map_binding_metadata.sql");
const NEW_VIEW: &str = include_str!("../../../../sql/schema/07_opaque_series_binding.sql");

fn admin_postgres_url(database_url: &str) -> String {
    let mut url = url::Url::parse(database_url).expect("database url");
    url.set_path("/postgres");
    url.to_string()
}

struct IsolatedDb {
    admin: String,
    name: String,
}

impl Drop for IsolatedDb {
    fn drop(&mut self) {
        let admin = self.admin.clone();
        let name = self.name.clone();
        if !name
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
        {
            return;
        }
        let _ = std::thread::spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("drop runtime");
            runtime.block_on(async move {
                let Ok(pool) = PgPoolOptions::new()
                    .max_connections(1)
                    .connect(&admin)
                    .await
                else {
                    return;
                };
                let sql = format!("DROP DATABASE IF EXISTS {name} WITH (FORCE)");
                let _ = sqlx::query(&sql).execute(&pool).await;
            });
        })
        .join();
    }
}

async fn create_isolated_pool(admin_url: &str, name: &str) -> PgPool {
    let admin = PgPoolOptions::new()
        .max_connections(1)
        .connect(admin_url)
        .await
        .expect("admin connect");
    let sql = format!("CREATE DATABASE {name}");
    sqlx::query(&sql)
        .execute(&admin)
        .await
        .expect("create database");
    let mut url = url::Url::parse(admin_url).expect("admin url");
    url.set_path(&format!("/{name}"));
    PgPoolOptions::new()
        .max_connections(2)
        .connect(url.as_str())
        .await
        .expect("isolated connect")
}

async fn isolated_pool() -> Option<(PgPool, IsolatedDb)> {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .filter(|v| !v.trim().is_empty())?;
    let admin = admin_postgres_url(&url);
    let name = format!("t1406upg{}", uuid::Uuid::new_v4().simple());
    assert!(
        name.chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '_'),
        "invalid database name"
    );
    let pool = create_isolated_pool(&admin, &name).await;
    Some((pool, IsolatedDb { admin, name }))
}

async fn baseline_tables(pool: &PgPool) {
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
    let Some((pool, _drop)) = isolated_pool().await else {
        return;
    };
    let site = "T1406_SCHEMA_UPGRADE";
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
}
