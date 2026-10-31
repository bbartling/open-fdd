//! T1402-2: computing `/api/analytics/*` POST handlers use `analytics_result`.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::analytics::{
    plant, plant_health, vav_health, QV_DIURNAL, QV_ECONOMIZER, QV_MECHANICAL_COOLING, QV_METERING,
    QV_MV_CHANGE_POINT, QV_RCX_AHU, QV_RCX_VAV, QV_RUNTIME, QV_SCHEDULE, QV_SENSOR_HEALTH,
    QV_SENSOR_STATS, QV_SETPOINTS, QV_SQL_ANOMALY, QV_TOPOLOGY,
};
use crate::state::AppState;

const SITE: &str = "t1402-cache";

/// Every computing analytics POST (path, cache `query_id`, contract `query_version`).
/// Static catalogs and inline demo twins are intentionally absent.
pub const COMPUTING_ANALYTICS_POST_ROUTES: &[(&str, &str, &str)] = &[
    ("/api/analytics/runtime", "runtime", QV_RUNTIME),
    (
        "/api/analytics/vav-health",
        "vav-health",
        vav_health::QV_VAV_HEALTH,
    ),
    (
        "/api/analytics/ahu-health",
        "ahu-health",
        plant_health::QV_AHU_HEALTH,
    ),
    (
        "/api/analytics/ahu-temperature-health",
        "ahu-temperature-health",
        plant_health::QV_AHU_TEMPERATURE_HEALTH,
    ),
    (
        "/api/analytics/ahu-pressure-health",
        "ahu-pressure-health",
        plant_health::QV_AHU_PRESSURE_HEALTH,
    ),
    (
        "/api/analytics/ahu-economizer-health",
        "ahu-economizer-health",
        plant_health::QV_AHU_ECONOMIZER_HEALTH,
    ),
    (
        "/api/analytics/chiller-health",
        "chiller-health",
        plant_health::QV_CHILLER_HEALTH,
    ),
    (
        "/api/analytics/cooling-tower-health",
        "cooling-tower-health",
        plant_health::QV_COOLING_TOWER_HEALTH,
    ),
    (
        "/api/analytics/sensor-faults",
        "sensor-faults",
        plant_health::QV_SENSOR_FAULTS,
    ),
    (
        "/api/analytics/pid-hunting",
        "pid-hunting",
        plant_health::QV_PID_HUNTING,
    ),
    (
        "/api/analytics/boiler-health",
        "boiler-health",
        plant_health::QV_BOILER_HEALTH,
    ),
    (
        "/api/analytics/hp-health",
        "hp-health",
        plant_health::QV_HP_HEALTH,
    ),
    (
        "/api/analytics/zone-other-health",
        "zone-other-health",
        plant_health::QV_ZONE_OTHER_HEALTH,
    ),
    (
        "/api/analytics/sensor-health",
        "sensor-health",
        QV_SENSOR_HEALTH,
    ),
    ("/api/analytics/schedule", "schedule", QV_SCHEDULE),
    (
        "/api/analytics/mechanical-cooling",
        "mechanical-cooling",
        QV_MECHANICAL_COOLING,
    ),
    (
        "/api/analytics/bas-vs-web-oat",
        "bas-vs-web-oat",
        "bas-vs-web-oat-v4",
    ),
    (
        "/api/analytics/inspect",
        "equipment-inspect",
        "equipment-inspect-v1",
    ),
    ("/api/analytics/economizer", "economizer", QV_ECONOMIZER),
    ("/api/analytics/rcx/ahu", "rcx-ahu", QV_RCX_AHU),
    ("/api/analytics/rcx/vav", "rcx-vav", QV_RCX_VAV),
    (
        "/api/analytics/rcx/chiller",
        "rcx-chiller",
        plant::QV_RCX_CHILLER,
    ),
    (
        "/api/analytics/rcx/boiler",
        "rcx-boiler",
        plant::QV_RCX_BOILER,
    ),
    ("/api/analytics/rcx/preset", "rcx-preset", "rcx-preset-v1"),
    ("/api/analytics/metering", "metering", QV_METERING),
    ("/api/analytics/mv", "mv-change-point", QV_MV_CHANGE_POINT),
    ("/api/analytics/fuel", "fuel", "fuel"),
    ("/api/analytics/setpoints", "setpoints", QV_SETPOINTS),
    ("/api/analytics/diurnal", "diurnal", QV_DIURNAL),
    ("/api/analytics/topology", "topology", QV_TOPOLOGY),
    (
        "/api/analytics/sensor-stats",
        "sensor-stats",
        QV_SENSOR_STATS,
    ),
    ("/api/analytics/sql-anomaly", "sql-anomaly", QV_SQL_ANOMALY),
];

struct SharedPoolReset;

impl SharedPoolReset {
    fn arm() -> Self {
        fdd_tsdb::clear_shared_pool();
        Self
    }
}

impl Drop for SharedPoolReset {
    fn drop(&mut self) {
        fdd_tsdb::clear_shared_pool();
    }
}

struct EnvGuard {
    key: &'static str,
    prev: Option<String>,
}

impl EnvGuard {
    fn set(key: &'static str, value: &str) -> Self {
        let prev = std::env::var(key).ok();
        std::env::set_var(key, value);
        Self { key, prev }
    }

    fn unset(key: &'static str) -> Self {
        let prev = std::env::var(key).ok();
        std::env::remove_var(key);
        Self { key, prev }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        match self.prev.take() {
            Some(value) => std::env::set_var(self.key, value),
            None => std::env::remove_var(self.key),
        }
    }
}

fn test_database_url() -> Option<String> {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

#[test]
fn every_computing_analytics_post_route_is_documented() {
    let routes = include_str!("routes.rs");
    for (path, query_id, _qv) in COMPUTING_ANALYTICS_POST_ROUTES {
        assert!(routes.contains(path), "routes.rs must register POST {path}");
        assert!(
            routes.contains(query_id),
            "routes.rs must dispatch cache query_id {query_id} for {path}"
        );
    }
    assert!(
        routes.contains(
            "Static RCx preset catalog — not a historian compute; intentionally uncached"
        ),
        "rcx presets list must document uncached static catalog"
    );
    assert!(
        routes.contains("Inline M&V demo twin — not backed by Timescale; intentionally uncached"),
        "mv handler must document uncached inline demo"
    );
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL for analytics result cache fixture"
)]
async fn every_analytics_endpoint_uses_result_store() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
    let _database = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
    let _jwt = EnvGuard::unset("OPENFDD_JWT_SECRET");
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    let _shed = EnvGuard::set("OPENFDD_MEMORY_SHED_FRACTION", "0.99");
    let _abort = EnvGuard::set("OPENFDD_MEMORY_ABORT_FRACTION", "1.0");
    let _shared_pool = SharedPoolReset::arm();

    let pool = PgPoolOptions::new()
        .max_connections(3)
        .connect(&url)
        .await
        .expect("analytics cache postgres");
    apply_schema(&pool).await;
    purge_site(&pool, SITE).await;
    seed_runtime_site(&pool).await;

    let app = crate::routes::router(Arc::new(AppState::new()));
    let path = "/api/analytics/runtime";
    assert!(
        COMPUTING_ANALYTICS_POST_ROUTES
            .iter()
            .any(|(p, _, _)| *p == path),
        "fixture exercises a listed computing route"
    );

    let before_rows = cache_rows(&pool, SITE).await;
    let first = post_json(
        &app,
        path,
        json!({ "building_id": SITE, "max_points": 500 }),
    )
    .await;
    assert_eq!(first["cache"]["hit"], false, "{first}");
    let after_miss = cache_rows(&pool, SITE).await;
    assert!(
        after_miss > before_rows,
        "miss must persist analytics_result row"
    );

    let second = post_json(
        &app,
        path,
        json!({ "building_id": SITE, "max_points": 500 }),
    )
    .await;
    assert_eq!(second["cache"]["hit"], true, "{second}");
    assert_eq!(cache_rows(&pool, SITE).await, after_miss);

    let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap();
    let key = "AHU_T1402.fan_status";
    sqlx::query("INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, 1.0)")
        .bind(t0 + Duration::hours(2))
        .bind(SITE)
        .bind(key)
        .execute(&pool)
        .await
        .expect("append sample");
    crate::series_binding::bind_conventional_key(&pool, SITE, key).await;
    fdd_tsdb::clear_shared_pool();

    let stale = post_json(
        &app,
        path,
        json!({ "building_id": SITE, "max_points": 500 }),
    )
    .await;
    assert_eq!(stale["cache"]["hit"], true, "{stale}");
    assert_eq!(stale["cache"]["stale"], true, "{stale}");

    let refreshed = post_json(
        &app,
        path,
        json!({
            "building_id": SITE,
            "max_points": 500,
            "refresh": true,
        }),
    )
    .await;
    assert_eq!(refreshed["cache"]["hit"], false, "{refreshed}");
    assert_eq!(refreshed["cache"]["stale"], false, "{refreshed}");

    purge_site(&pool, SITE).await;
}

async fn post_json(app: &axum::Router, path: &str, payload: Value) -> Value {
    let response = app
        .clone()
        .oneshot(
            Request::post(path)
                .header("content-type", "application/json")
                .body(Body::from(payload.to_string()))
                .expect("request"),
        )
        .await
        .expect("response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let body: Value = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    assert_eq!(status, StatusCode::OK, "{path} {body}");
    body
}

async fn cache_rows(pool: &PgPool, building_id: &str) -> i64 {
    sqlx::query_scalar("SELECT COUNT(*)::bigint FROM analytics_result WHERE building_id = $1")
        .bind(building_id)
        .fetch_one(pool)
        .await
        .expect("count cache rows")
}

async fn apply_schema(pool: &PgPool) {
    for statement in [
        "CREATE TABLE IF NOT EXISTS site (
            site_id text PRIMARY KEY,
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS building (
            building_id text PRIMARY KEY,
            site_id text REFERENCES site(site_id),
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS equipment (
            building_id text NOT NULL REFERENCES building(building_id),
            equipment_id text NOT NULL,
            equip_type text,
            parent_equipment_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (building_id, equipment_id)
        )",
        "CREATE TABLE IF NOT EXISTS sample (
            ts timestamptz NOT NULL,
            site_id text NOT NULL,
            openfdd_key text NOT NULL,
            val double precision,
            PRIMARY KEY (site_id, openfdd_key, ts)
        )",
    ] {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
    for statement in crate::db_lifecycle::statements(include_str!(
        "../../../sql/schema/08_analytics_result_cache.sql"
    )) {
        crate::test_ddl::execute_idempotent_ddl(pool, &statement).await;
    }
}

async fn purge_site(pool: &PgPool, site: &str) {
    sqlx::query("DELETE FROM sample WHERE site_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge samples");
    sqlx::query("DELETE FROM role_map WHERE building_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge role_map");
    sqlx::query("DELETE FROM point_map WHERE site_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge point_map");
    sqlx::query("DELETE FROM equipment WHERE building_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge equipment");
    sqlx::query("DELETE FROM building WHERE building_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge building");
    sqlx::query("DELETE FROM site WHERE site_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge site");
    sqlx::query("DELETE FROM analytics_result WHERE building_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge analytics_result");
}

async fn seed_runtime_site(pool: &PgPool) {
    sqlx::query("INSERT INTO site (site_id) VALUES ($1) ON CONFLICT DO NOTHING")
        .bind(SITE)
        .execute(pool)
        .await
        .expect("site");
    sqlx::query(
        "INSERT INTO building (building_id, site_id) VALUES ($1, $1) ON CONFLICT DO NOTHING",
    )
    .bind(SITE)
    .execute(pool)
    .await
    .expect("building");
    sqlx::query(
        "INSERT INTO equipment (building_id, equipment_id, equip_type)
         VALUES ($1, $2, 'ahu') ON CONFLICT DO NOTHING",
    )
    .bind(SITE)
    .bind("AHU_T1402")
    .execute(pool)
    .await
    .expect("equipment");
    let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 10, 0, 0).unwrap();
    let key = "AHU_T1402.fan_status";
    for (offset_mins, value) in [(0, 1.0), (30, 1.0), (60, 0.0)] {
        sqlx::query("INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, $4)")
            .bind(t0 + Duration::minutes(offset_mins))
            .bind(SITE)
            .bind(key)
            .bind(value)
            .execute(pool)
            .await
            .expect("sample");
    }
    crate::series_binding::bind_conventional_key(pool, SITE, key).await;
}
