//! Selected-site meters do not fall back to another campus, and the
//! M&V demo caller reaches the inline twin while Timescale is the historian.
//!
//! PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is set (the Rust CI job).

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::state::AppState;

const METERED: &str = "w5f-metered";
const EMPTY: &str = "w5f-empty";
const OTHER: &str = "w5f-other";
const OTHER_METER: &str = "OTHER_METER";
const SITE_METER: &str = "SITE_METER";
const INTERVAL_METER: &str = "W5F_METER";

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

fn demo_request() -> Value {
    let baseline = [
        ("2023-01", 800.0),
        ("2023-02", 700.0),
        ("2023-03", 500.0),
        ("2023-04", 300.0),
        ("2023-05", 100.0),
        ("2023-06", 50.0),
        ("2023-07", 20.0),
        ("2023-08", 30.0),
        ("2023-09", 80.0),
        ("2023-10", 250.0),
        ("2023-11", 450.0),
        ("2023-12", 750.0),
    ];
    let reporting = [("2024-01", 780.0), ("2024-02", 690.0), ("2024-03", 480.0)];
    let mut rows = Vec::new();
    for (period, degree_days) in baseline {
        rows.push(json!({
            "period": period,
            "energy": 500.0 + 2.0 * degree_days,
            "degree_days": degree_days,
        }));
    }
    for (period, degree_days) in reporting {
        rows.push(json!({
            "period": period,
            "energy": 500.0 + 2.0 * degree_days - 100.0,
            "degree_days": degree_days,
        }));
    }
    json!({
        "query_version": "mv-change-point-v1",
        "series": {
            "baseline_end": "2023-12",
            "dd_kind": "hdd",
            "rows": rows,
        }
    })
}

fn write_campus(root: &std::path::Path, id: &str, meter_id: &str, kwh: i64) {
    let dir = root.join("data").join("fuel").join(id);
    std::fs::create_dir_all(&dir).expect("campus dir");
    std::fs::write(
        dir.join("bills.csv"),
        format!("month,kwh,cost\n2024-01,{kwh},12\n"),
    )
    .expect("bills");
    let doc = json!({
        "campus_id": id,
        "label": id,
        "buildings": [{
            "building_id": id,
            "label": id,
            "floor_area_ft2": 1000.0,
            "property_type": "office"
        }],
        "meters": [{
            "meter_id": meter_id,
            "fuel": "electricity",
            "unit": "kwh",
            "file": "bills.csv",
            "serves": [id]
        }]
    });
    std::fs::write(
        dir.join("campus.json"),
        serde_json::to_string_pretty(&doc).expect("campus json"),
    )
    .expect("write campus");
}

async fn send(
    app: &axum::Router,
    method: &str,
    path: &str,
    payload: Option<Value>,
) -> (StatusCode, Value) {
    let request = match method {
        "GET" => Request::get(path).body(Body::empty()).expect("get"),
        "POST" => Request::post(path)
            .header("content-type", "application/json")
            .body(Body::from(payload.unwrap_or(json!({})).to_string()))
            .expect("post"),
        other => panic!("unsupported method {other}"),
    };
    let response = app.clone().oneshot(request).await.expect("response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let body: Value = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    (status, body)
}

fn assert_demo(status: StatusCode, body: &Value) {
    let text = body.to_string();
    assert_eq!(status, StatusCode::OK, "{text}");
    assert_eq!(body["ok"], true, "{text}");
    assert_eq!(body["scope"], "inline_series", "{text}");
    assert_eq!(
        body["analytics"]["engine"], "central-analytics-v1",
        "{text}"
    );
    assert_eq!(
        body["analytics"]["coverage"]["provenance"], "inline_series",
        "{text}"
    );
    assert_eq!(
        body["analytics"]["coverage"]["site_performance_claim"], false,
        "{text}"
    );
    let savings = body["analytics"]["coverage"]["savings_reporting_total"]
        .as_f64()
        .expect("savings");
    assert!(
        (savings - 300.0).abs() < 1.0,
        "expected about 300 savings, got {savings}: {text}"
    );
    assert!(
        !text.contains("building_id is required"),
        "demo dispatch still requires a building: {text}"
    );
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL while the demo request is served"
)]
async fn mv_inline_series_is_served_when_timescale_dispatch_would_reject_it() {
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
    let _database = EnvGuard::set(
        "OPENFDD_DATABASE_URL",
        "postgres://127.0.0.1:9/openfdd_mv_demo_unused",
    );
    let _jwt = EnvGuard::unset("OPENFDD_JWT_SECRET");
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    let _shared_pool = SharedPoolReset::arm();

    let app = crate::routes::router(Arc::new(AppState::new()));
    let (status, body) = send(&app, "POST", "/api/analytics/mv", Some(demo_request())).await;
    assert_demo(status, &body);

    let (missing_status, missing) = send(&app, "POST", "/api/analytics/mv", Some(json!({}))).await;
    assert_eq!(missing_status, StatusCode::BAD_REQUEST, "{missing}");
    assert_eq!(missing["ok"], false, "{missing}");
    assert_eq!(missing["code"], "mv.scope_required", "{missing}");
    assert_eq!(missing["engine"], "mv-change-point", "{missing}");
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL for the metering scope fixture"
)]
async fn selected_site_without_meters_does_not_show_another_campus() {
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

    write_campus(workspace.path(), OTHER, OTHER_METER, 9999);
    write_campus(workspace.path(), METERED, SITE_METER, 111);

    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("metering scope postgres");
    apply_schema(&pool).await;
    purge_site(&pool, METERED).await;
    purge_site(&pool, EMPTY).await;
    seed_interval(&pool).await;

    let app = crate::routes::router(Arc::new(AppState::new()));

    let (catalog_status, catalog) = send(&app, "GET", "/api/fuel/campus", None).await;
    assert_eq!(catalog_status, StatusCode::OK, "{catalog}");
    assert!(
        catalog.to_string().contains(OTHER_METER),
        "residual campus missing from the unscoped control: {catalog}"
    );

    let (empty_status, empty) = send(
        &app,
        "GET",
        &format!("/api/fuel/campus?building_id={EMPTY}"),
        None,
    )
    .await;
    let empty_body = empty.to_string();
    assert_eq!(empty_status, StatusCode::OK, "{empty_body}");
    assert_eq!(empty["status"], "no_meters", "{empty_body}");
    assert_eq!(empty["campuses"].as_array().expect("campuses").len(), 0);
    assert!(!empty_body.contains(OTHER_METER), "{empty_body}");
    assert!(!empty_body.contains(SITE_METER), "{empty_body}");
    assert!(!empty_body.contains(OTHER), "{empty_body}");

    let (monthly_status, monthly) = send(
        &app,
        "POST",
        "/api/analytics/fuel",
        Some(json!({
            "query_version": "fuel-monthly-v1",
            "building_id": EMPTY,
            "campus_id": EMPTY,
        })),
    )
    .await;
    let monthly_body = monthly.to_string();
    assert_eq!(monthly_status, StatusCode::OK, "{monthly_body}");
    assert_eq!(monthly["status"], "no_meters", "{monthly_body}");
    assert_eq!(
        monthly["analytics"]["rows"].as_array().expect("rows").len(),
        0
    );
    assert!(!monthly_body.contains(OTHER_METER), "{monthly_body}");
    assert!(!monthly_body.contains("9999"), "{monthly_body}");

    let (mismatch_status, mismatch) = send(
        &app,
        "POST",
        "/api/analytics/fuel",
        Some(json!({
            "query_version": "fuel-monthly-v1",
            "building_id": EMPTY,
            "campus_id": OTHER,
        })),
    )
    .await;
    let mismatch_body = mismatch.to_string();
    assert_eq!(mismatch_status, StatusCode::OK, "{mismatch_body}");
    assert_eq!(
        mismatch["analytics"]["status"], "scope_mismatch",
        "{mismatch_body}"
    );
    assert_eq!(mismatch["ok"], false, "{mismatch_body}");
    assert!(!mismatch_body.contains(OTHER_METER), "{mismatch_body}");
    assert!(!mismatch_body.contains("9999"), "{mismatch_body}");

    let (own_status, own) = send(
        &app,
        "POST",
        "/api/analytics/fuel",
        Some(json!({
            "query_version": "fuel-monthly-v1",
            "building_id": METERED,
            "campus_id": METERED,
        })),
    )
    .await;
    let own_body = own.to_string();
    assert_eq!(own_status, StatusCode::OK, "{own_body}");
    assert_eq!(own["ok"], true, "{own_body}");
    assert!(own_body.contains(SITE_METER), "{own_body}");
    assert!(!own_body.contains(OTHER_METER), "{own_body}");

    let (interval_empty_status, interval_empty) = send(
        &app,
        "POST",
        "/api/analytics/fuel",
        Some(json!({
            "query_version": "fuel",
            "building_id": EMPTY,
        })),
    )
    .await;
    let interval_empty_body = interval_empty.to_string();
    assert_eq!(
        interval_empty_status,
        StatusCode::OK,
        "{interval_empty_body}"
    );
    assert_eq!(
        interval_empty["status"], "no_meters",
        "{interval_empty_body}"
    );
    assert_eq!(
        interval_empty["analytics"]["rows"]
            .as_array()
            .expect("rows")
            .len(),
        0
    );
    assert!(
        !interval_empty_body.contains(INTERVAL_METER),
        "{interval_empty_body}"
    );
    assert!(
        !interval_empty_body.contains(OTHER_METER),
        "{interval_empty_body}"
    );

    let (interval_own_status, interval_own) = send(
        &app,
        "POST",
        "/api/analytics/fuel",
        Some(json!({
            "query_version": "fuel",
            "building_id": METERED,
        })),
    )
    .await;
    let interval_own_body = interval_own.to_string();
    assert_eq!(interval_own_status, StatusCode::OK, "{interval_own_body}");
    assert!(
        interval_own_body.contains(INTERVAL_METER),
        "metered site interval rows missing: {interval_own_body}"
    );
    assert!(!interval_own_body.contains(EMPTY), "{interval_own_body}");

    let (demo_status, demo) = send(&app, "POST", "/api/analytics/mv", Some(demo_request())).await;
    assert_demo(demo_status, &demo);

    let (mv_empty_status, mv_empty) = send(
        &app,
        "POST",
        "/api/analytics/mv",
        Some(json!({
            "query_version": "mv-change-point-v1",
            "building_id": EMPTY,
        })),
    )
    .await;
    let mv_empty_body = mv_empty.to_string();
    assert_eq!(mv_empty_status, StatusCode::OK, "{mv_empty_body}");
    let mv_env = crate::analytics_response_fixtures::analytics_envelope(&mv_empty);
    assert_eq!(
        mv_env
            .pointer("/coverage/building_id")
            .and_then(|v| v.as_str()),
        Some(EMPTY),
        "{mv_empty_body}"
    );
    assert_eq!(mv_env["rows"].as_array().expect("rows").len(), 0);
    assert!(!mv_empty_body.contains(INTERVAL_METER), "{mv_empty_body}");

    let (mv_own_status, mv_own) = send(
        &app,
        "POST",
        "/api/analytics/mv",
        Some(json!({
            "query_version": "mv-change-point-v1",
            "building_id": METERED,
        })),
    )
    .await;
    let mv_own_body = mv_own.to_string();
    assert_eq!(mv_own_status, StatusCode::OK, "{mv_own_body}");
    let mv_own_env = crate::analytics_response_fixtures::analytics_envelope(&mv_own);
    assert_eq!(
        mv_own_env
            .pointer("/coverage/building_id")
            .and_then(|v| v.as_str()),
        Some(METERED),
        "{mv_own_body}"
    );
    assert!(
        mv_own_body.contains(INTERVAL_METER),
        "metered site M&V rows missing: {mv_own_body}"
    );
    assert!(!mv_own_body.contains(OTHER_METER), "{mv_own_body}");

    purge_site(&pool, METERED).await;
    purge_site(&pool, EMPTY).await;
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
    let _ = sqlx::query("DELETE FROM building WHERE building_id = $1")
        .bind(site)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM site WHERE site_id = $1")
        .bind(site)
        .execute(pool)
        .await;
}

async fn seed_interval(pool: &PgPool) {
    for site in [METERED, EMPTY] {
        sqlx::query(
            "INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("site");
        sqlx::query(
            "INSERT INTO building (building_id, site_id, dis) VALUES ($1, $1, $1)
             ON CONFLICT (building_id) DO NOTHING",
        )
        .bind(site)
        .execute(pool)
        .await
        .expect("building");
    }
    let day_one = Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap();
    let day_two = Utc.with_ymd_and_hms(2026, 6, 2, 0, 0, 0).unwrap();
    let key = format!("{INTERVAL_METER}.electric_kwh");
    for hour in 0..6 {
        insert_sample(pool, METERED, day_one + Duration::hours(hour), &key, 100.0).await;
        insert_sample(pool, METERED, day_two + Duration::hours(hour), &key, 250.0).await;
    }
}

async fn insert_sample(pool: &PgPool, site: &str, ts: chrono::DateTime<Utc>, key: &str, val: f64) {
    sqlx::query(
        "INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, $4)
         ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET val = EXCLUDED.val",
    )
    .bind(ts)
    .bind(site)
    .bind(key)
    .bind(val)
    .execute(pool)
    .await
    .unwrap_or_else(|err| panic!("insert {key}: {err}"));
    crate::series_binding::bind_conventional_key(pool, site, key).await;
}
