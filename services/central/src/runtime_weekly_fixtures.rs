//! Weekly runtime observation counts from the real analytics handler.
//!
//! PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is set. The fixture inserts
//! sample rows and reads `/api/analytics/runtime`. The occupied-hours reference
//! is the site session calendar, asserted by the web runtime fixture.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::state::AppState;

const SITE: &str = "w5e-runtime-obs";
const FULL: &str = "W5E_FULL";
const PART: &str = "W5E_PART";

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

/// Week buckets follow the session TimeZone. Pin UTC so Monday 00:00 is one week.
fn force_utc(url: &str) -> String {
    if url.to_ascii_lowercase().contains("timezone") {
        return url.to_string();
    }
    let joiner = if url.contains('?') { '&' } else { '?' };
    format!("{url}{joiner}options=-c%20TimeZone%3DUTC")
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL for the weekly runtime fixture"
)]
async fn runtime_handler_reports_observation_counts_and_partial_weeks() {
    let Some(url) = test_database_url() else {
        return;
    };
    let url = force_utc(&url);
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
        .max_connections(2)
        .connect(&url)
        .await
        .expect("runtime weekly postgres fixture");
    apply_schema(&pool).await;
    purge_site(&pool, SITE).await;
    seed(&pool).await;

    let state = Arc::new(AppState::new());
    let app = crate::routes::router(state);
    let body = post_runtime(&app).await;
    assert!(
        body.get("points").is_none(),
        "runtime stays row-only: {body}"
    );
    let rows = body["rows"].as_array().expect("runtime rows");
    assert!(!rows.is_empty(), "{body}");

    let full = rows_for(rows, FULL);
    let part = rows_for(rows, PART);
    assert!(!full.is_empty(), "full-week motor missing: {body}");
    assert!(!part.is_empty(), "partial-week motor missing: {body}");
    assert!(
        rows.iter().all(|row| row["signal"] == "fan_status"),
        "command samples must not become a second trace: {body}"
    );
    assert_eq!(
        observation_sum(&full),
        168,
        "status samples only, not status plus command: {full:?}"
    );
    assert_eq!(observation_sum(&part), 6, "{part:?}");
    let hours: f64 = full
        .iter()
        .map(|row| row["run_hours"].as_f64().unwrap_or(0.0))
        .sum();
    assert!(
        (hours - 167.0).abs() < 1e-6,
        "on-time is the forward delta, last sample has no interval: {hours} {full:?}"
    );
    assert!(
        full.iter().any(|row| row["partial_week"] == false),
        "a Monday–Sunday sample span is a full week: {full:?}"
    );
    assert!(
        part.iter().all(|row| row["partial_week"] == true),
        "a six-hour bucket is partial: {part:?}"
    );

    purge_site(&pool, SITE).await;
}

fn rows_for<'a>(rows: &'a [Value], equipment_id: &str) -> Vec<&'a Value> {
    rows.iter()
        .filter(|row| row["equipment_id"] == equipment_id)
        .collect()
}

fn observation_sum(rows: &[&Value]) -> i64 {
    rows.iter()
        .map(|row| row["n_observations"].as_i64().unwrap_or(0))
        .sum()
}

async fn post_runtime(app: &axum::Router) -> Value {
    let payload = json!({
        "building_id": SITE,
        "max_points": 500,
    });
    let response = app
        .clone()
        .oneshot(
            Request::post("/api/analytics/runtime")
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
    assert_eq!(status, StatusCode::OK, "{body}");
    body
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
}

async fn purge_site(pool: &PgPool, site: &str) {
    sqlx::query("DELETE FROM sample WHERE site_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .expect("purge sample");
    let _ = sqlx::query("DELETE FROM equipment WHERE building_id = $1")
        .bind(site)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM building WHERE building_id = $1")
        .bind(site)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM site WHERE site_id = $1")
        .bind(site)
        .execute(pool)
        .await;
}

async fn seed(pool: &PgPool) {
    sqlx::query("INSERT INTO site (site_id, dis, timezone) VALUES ($1, $1, 'UTC')")
        .bind(SITE)
        .execute(pool)
        .await
        .expect("site");
    sqlx::query(
        "INSERT INTO building (building_id, site_id, dis, timezone) VALUES ($1, $1, $1, 'UTC')",
    )
    .bind(SITE)
    .execute(pool)
    .await
    .expect("building");
    for equipment_id in [FULL, PART] {
        sqlx::query(
            "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'ahu')",
        )
        .bind(SITE)
        .bind(equipment_id)
        .execute(pool)
        .await
        .expect("equipment");
    }
    let monday = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    insert_hourly(pool, FULL, "fan_status", monday, 168, 1.0).await;
    insert_hourly(pool, FULL, "fan_cmd", monday, 168, 0.0).await;
    let next_monday = Utc.with_ymd_and_hms(2026, 6, 8, 0, 0, 0).unwrap();
    insert_hourly(pool, PART, "fan_status", next_monday, 6, 1.0).await;
}

async fn insert_hourly(
    pool: &PgPool,
    equipment_id: &str,
    role: &str,
    start: chrono::DateTime<Utc>,
    hours: i64,
    val: f64,
) {
    let key = format!("{equipment_id}.{role}");
    for hour in 0..hours {
        let ts = start + Duration::hours(hour);
        sqlx::query("INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, $4)")
            .bind(ts)
            .bind(SITE)
            .bind(&key)
            .bind(val)
            .execute(pool)
            .await
            .expect("sample");
    }
}
