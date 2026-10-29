//! Row-only Timescale fixtures for the RCx overview presets and duct-static setpoint.
//!
//! PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is set (the Rust CI job).
//! The fixture inserts sample rows only — it does not seed a pre-shaped points payload.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::state::AppState;

const SITE: &str = "w4c-rcx-rows";
const REJECT: &str = "w4c-rcx-reject";
const EMPTY: &str = "w4c-rcx-empty";
const AHU: &str = "W4C_AHU";
const EXTRA: &str = "W4C_AHU_EXTRA";
const CHILLER: &str = "W4C_CH";
const WEATHER: &str = "W4C_WX";

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

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL for the RCx row fixture"
)]
async fn rcx_row_endpoints_gate_economizer_and_return_duct_setpoint() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let cache = workspace.path().join("analytics-cache");
    let _cache = EnvGuard::set(
        "OPENFDD_ANALYTICS_CACHE_ROOT",
        cache.to_str().unwrap_or("analytics-cache"),
    );
    let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
    let _database = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
    let _jwt = EnvGuard::unset("OPENFDD_JWT_SECRET");
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    // The duct-static preset recomputes through analytics admission. A busy
    // CI host above the default 0.75 shed line must not turn a row fixture
    // into a memory deferral.
    let _shed = EnvGuard::set("OPENFDD_MEMORY_SHED_FRACTION", "0.99");
    let _abort = EnvGuard::set("OPENFDD_MEMORY_ABORT_FRACTION", "1.0");
    // Each tokio test has its own runtime. A shared Timescale pool left behind
    // never yields a connection to the next test.
    let _shared_pool = SharedPoolReset::arm();

    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("rcx row postgres fixture");
    apply_schema(&pool).await;
    for site in [SITE, REJECT, EMPTY] {
        purge_site(&pool, site).await;
    }
    seed(&pool).await;

    let state = Arc::new(AppState::new());
    let app = crate::routes::router(state);

    let qualified = post_analytics(&app, "/api/analytics/economizer", SITE, Some(10.0)).await;
    let rows = qualified["rows"].as_array().expect("economizer rows");
    assert!(
        crate::analytics_response_fixtures::points_absent_or_empty(&qualified),
        "economizer endpoint stays row-only: {qualified}"
    );
    assert_eq!(
        rows.len(),
        1,
        "only the fan-on measurable row qualifies: {qualified}"
    );
    let row = &rows[0];
    assert_eq!(row["equipment_id"], AHU);
    assert_eq!(row["fan_on"], true);
    assert_eq!(row["identifiable"], true);
    assert!(
        row["mat"].as_f64().is_some(),
        "qualified row keeps measured MAT"
    );
    let delta = row["delta_or_f"].as_f64().expect("delta");
    assert!(delta.abs() >= 10.0, "qualified |OAT−RAT|={delta}");
    let resid = row["mat_resid_f"].as_f64().expect("residual");
    assert!(
        (resid - (-3.2)).abs() < 1e-6,
        "MAT residual {resid} is the damper mixing difference"
    );
    let body = qualified.to_string();
    assert!(body.contains("2026-06-01T12:00:00"), "{body}");
    assert!(
        !body.contains("2026-06-01T13:00:00"),
        "off-fan row qualified: {body}"
    );
    assert!(
        !body.contains("2026-06-01T14:00:00"),
        "low-delta row qualified: {body}"
    );
    assert!(
        !body.contains("2026-06-01T15:00:00"),
        "missing-MAT row qualified: {body}"
    );
    assert!(
        !body.contains("2026-06-01T16:00:00"),
        "missing fan-status row qualified: {body}"
    );

    let tight = post_analytics(&app, "/api/analytics/economizer", SITE, Some(30.0)).await;
    assert!(
        tight["rows"].as_array().expect("rows").is_empty(),
        "22°F delta is below a 30°F gate: {tight}"
    );
    assert!(
        warning_text(&tight).contains("not qualified"),
        "tight gate explains the empty result: {tight}"
    );

    let rejected = post_analytics(&app, "/api/analytics/economizer", REJECT, Some(10.0)).await;
    assert!(
        rejected["rows"].as_array().expect("rows").is_empty(),
        "{rejected}"
    );
    assert!(
        warning_text(&rejected).contains("not qualified"),
        "all-missing economizer explains why: {rejected}"
    );

    let runtime = post_analytics(&app, "/api/analytics/runtime", SITE, None).await;
    assert!(
        crate::analytics_response_fixtures::points_absent_or_empty(&runtime),
        "runtime stays row-only: {runtime}"
    );
    let runtime_rows = runtime["rows"].as_array().expect("runtime rows");
    assert!(!runtime_rows.is_empty(), "{runtime}");
    // t0 stays on for one hour, and the later fan-on samples (low-delta, missing MAT)
    // add a second hour. Off-fan time is not counted.
    let hours: f64 = runtime_rows
        .iter()
        .map(|row| row["run_hours"].as_f64().unwrap_or(0.0))
        .sum();
    assert!(
        (hours - 2.0).abs() < 1e-6,
        "fan-on hours integrated to {hours}: {runtime}"
    );
    assert!(runtime_rows.iter().all(|row| row["plant_group"] == "air"));

    let mech = post_analytics(&app, "/api/analytics/mechanical-cooling", SITE, None).await;
    assert!(
        crate::analytics_response_fixtures::points_absent_or_empty(&mech),
        "mechanical cooling stays row-only: {mech}"
    );
    let mech_rows = mech["rows"].as_array().expect("mech rows");
    assert_eq!(mech_rows.len(), 1, "{mech}");
    assert_eq!(mech_rows[0]["oat_bin"], "60-70");
    assert!((mech_rows[0]["run_hours"].as_f64().unwrap_or(0.0) - 1.0).abs() < 1e-6);

    let bas = post_analytics(&app, "/api/analytics/bas-vs-web-oat", SITE, None).await;
    assert!(
        crate::analytics_response_fixtures::points_absent_or_empty(&bas),
        "BAS stays row-only: {bas}"
    );
    let bas_rows = bas["rows"].as_array().expect("bas rows");
    assert!(!bas_rows.is_empty(), "{bas}");
    let t0_pairs: Vec<_> = bas_rows
        .iter()
        .filter(|row| {
            row.get("bas_oa_t") == Some(&json!(50.0)) && row.get("web_oa_t") == Some(&json!(48.0))
        })
        .collect();
    assert_eq!(t0_pairs.len(), 1, "expected one assessable t0 pair: {bas}");
    assert_eq!(
        bas.get("oa_t_reference")
            .or_else(|| bas.get("coverage").and_then(|c| c.get("oa_t_reference")))
            .and_then(|v| v.get("selection"))
            .and_then(|v| v.as_str()),
        Some("default_lowest_binding")
    );
    assert!(
        bas.get("oa_t_reference").is_some(),
        "HTTP envelope must expose oa_t_reference at top level: {bas}"
    );
    assert!(
        bas.get("web_asof_bound_seconds")
            .and_then(|v| v.as_f64())
            .is_some(),
        "HTTP envelope must expose web_asof_bound_seconds: {bas}"
    );

    let empty_runtime = post_analytics(&app, "/api/analytics/runtime", EMPTY, None).await;
    assert!(empty_runtime["rows"].as_array().expect("rows").is_empty());
    assert!(
        warning_text(&empty_runtime).contains("motor weekly"),
        "{empty_runtime}"
    );
    let empty_mech = post_analytics(&app, "/api/analytics/mechanical-cooling", EMPTY, None).await;
    assert!(
        warning_text(&empty_mech).contains("outdoor-air"),
        "{empty_mech}"
    );
    let empty_bas = post_analytics(&app, "/api/analytics/bas-vs-web-oat", EMPTY, None).await;
    assert!(
        warning_text(&empty_bas).contains("BAS vs web"),
        "{empty_bas}"
    );

    let preset = post_json(
        &app,
        "/api/analytics/rcx/preset",
        json!({
            "building_id": SITE,
            "max_points": 500,
            "series": { "preset_id": "duct_static_ts" }
        }),
    )
    .await;
    let analytics = preset.get("analytics").unwrap_or(&preset);
    let points = analytics["points"]
        .as_array()
        .expect("duct points: {preset}");
    let primary: Vec<&Value> = points
        .iter()
        .filter(|p| p["series"] == "primary" && p["role"] == "duct_static")
        .collect();
    let setpoint: Vec<&Value> = points
        .iter()
        .filter(|p| p["series"] == "overlay" && p["role"] == "duct_static_sp")
        .collect();
    assert_eq!(primary.len(), 2, "primary duct static traces: {preset}");
    assert_eq!(setpoint.len(), 2, "setpoint companion traces: {preset}");
    assert!(
        primary.iter().any(|p| p["value_f"] == 1.25) && primary.iter().any(|p| p["value_f"] == 1.4),
        "{primary:?}"
    );
    assert!(
        setpoint.iter().any(|p| p["value_f"] == 1.5)
            && setpoint.iter().any(|p| p["value_f"] == 1.55),
        "{setpoint:?}"
    );
    for point in primary.iter().chain(setpoint.iter()) {
        assert_eq!(point["quantity"], "air_pressure", "{point}");
        assert_eq!(point["unit"], "in. w.c.", "{point}");
        assert_eq!(point["equipment_id"], AHU, "{point}");
    }
    assert!(
        points
            .iter()
            .all(|p| p["equipment_id"] != EXTRA && p["value_f"] != 9.9),
        "untyped prefix id must not join the AHU preset: {preset}"
    );
    let traces = analytics["coverage"]["traces"].as_array().expect("traces");
    assert!(
        traces
            .iter()
            .any(|t| t["series"] == "overlay" && t["role"] == "duct_static_sp"),
        "coverage names the setpoint trace: {traces:?}"
    );

    for site in [SITE, REJECT, EMPTY] {
        purge_site(&pool, site).await;
    }
}

fn analytics_payload(body: &Value) -> Value {
    crate::analytics_response_fixtures::analytics_envelope(body)
}

fn warning_text(body: &Value) -> String {
    let payload = analytics_payload(body);
    payload
        .get("warnings")
        .and_then(|v| v.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|v| v.as_str())
                .collect::<Vec<_>>()
                .join(" ")
        })
        .unwrap_or_default()
}

async fn post_analytics(
    app: &axum::Router,
    path: &str,
    building_id: &str,
    dt_min_f: Option<f64>,
) -> Value {
    let mut payload = json!({
        "building_id": building_id,
        "max_points": 500,
    });
    if let Some(dt) = dt_min_f {
        payload["dt_min_f"] = json!(dt);
    }
    post_json(app, path, payload).await
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
    analytics_payload(&body)
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
    for site in [SITE, REJECT, EMPTY] {
        sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1)")
            .bind(site)
            .execute(pool)
            .await
            .expect("site");
        sqlx::query("INSERT INTO building (building_id, site_id, dis) VALUES ($1, $1, $1)")
            .bind(site)
            .execute(pool)
            .await
            .expect("building");
    }
    sqlx::query(
        "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'ahu')",
    )
    .bind(SITE)
    .bind(AHU)
    .execute(pool)
    .await
    .expect("ahu");
    sqlx::query(
        "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'chiller')",
    )
    .bind(SITE)
    .bind(CHILLER)
    .execute(pool)
    .await
    .expect("chiller");
    sqlx::query(
        "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'ahu')",
    )
    .bind(EMPTY)
    .bind(AHU)
    .execute(pool)
    .await
    .expect("empty ahu");

    let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap();
    // Qualified: fan on, |OAT−RAT| = 22, MAT present, damper 40 → residual -3.2.
    insert_econ(
        pool,
        SITE,
        t0,
        EconSample {
            fan: Some(1.0),
            oa: 50.0,
            rat: 72.0,
            mat: Some(60.0),
            damper: Some(40.0),
        },
    )
    .await;
    // Off fan.
    insert_econ(
        pool,
        SITE,
        t0 + Duration::hours(1),
        EconSample {
            fan: Some(0.0),
            oa: 50.0,
            rat: 72.0,
            mat: Some(60.0),
            damper: Some(40.0),
        },
    )
    .await;
    // |OAT−RAT| = 2.
    insert_econ(
        pool,
        SITE,
        t0 + Duration::hours(2),
        EconSample {
            fan: Some(1.0),
            oa: 70.0,
            rat: 72.0,
            mat: Some(71.0),
            damper: Some(40.0),
        },
    )
    .await;
    // Missing MAT.
    insert_econ(
        pool,
        SITE,
        t0 + Duration::hours(3),
        EconSample {
            fan: Some(1.0),
            oa: 50.0,
            rat: 72.0,
            mat: None,
            damper: Some(40.0),
        },
    )
    .await;
    // Temps without fan status.
    insert_econ(
        pool,
        SITE,
        t0 + Duration::hours(4),
        EconSample {
            fan: None,
            oa: 50.0,
            rat: 72.0,
            mat: Some(60.0),
            damper: Some(40.0),
        },
    )
    .await;

    insert_sample(pool, SITE, t0, &format!("{AHU}.duct_static"), 1.25).await;
    insert_sample(pool, SITE, t0, &format!("{AHU}.duct_static_sp"), 1.50).await;
    insert_sample(
        pool,
        SITE,
        t0 + Duration::hours(1),
        &format!("{AHU}.duct_static"),
        1.40,
    )
    .await;
    insert_sample(
        pool,
        SITE,
        t0 + Duration::hours(1),
        &format!("{AHU}.duct_static_sp"),
        1.55,
    )
    .await;
    insert_sample(pool, SITE, t0, &format!("{EXTRA}.duct_static"), 9.9).await;
    insert_sample(pool, SITE, t0, &format!("{EXTRA}.duct_static_sp"), 9.9).await;

    insert_sample(pool, SITE, t0, &format!("{WEATHER}.web_oa_t"), 48.0).await;

    let cool = t0 + Duration::hours(10);
    insert_sample(pool, SITE, cool, &format!("{CHILLER}.chiller_status"), 1.0).await;
    insert_sample(pool, SITE, cool, &format!("{WEATHER}.web_oa_t"), 65.0).await;
    insert_sample(
        pool,
        SITE,
        cool + Duration::hours(1),
        &format!("{CHILLER}.chiller_status"),
        1.0,
    )
    .await;
    insert_sample(
        pool,
        SITE,
        cool + Duration::hours(1),
        &format!("{WEATHER}.web_oa_t"),
        65.0,
    )
    .await;

    // Rejected site: the three unqualified shapes, and nothing that can pass.
    insert_econ(
        pool,
        REJECT,
        t0,
        EconSample {
            fan: Some(0.0),
            oa: 50.0,
            rat: 72.0,
            mat: Some(60.0),
            damper: Some(40.0),
        },
    )
    .await;
    insert_econ(
        pool,
        REJECT,
        t0 + Duration::hours(1),
        EconSample {
            fan: Some(1.0),
            oa: 71.0,
            rat: 72.0,
            mat: Some(71.5),
            damper: Some(20.0),
        },
    )
    .await;
    insert_econ(
        pool,
        REJECT,
        t0 + Duration::hours(2),
        EconSample {
            fan: Some(1.0),
            oa: 40.0,
            rat: 72.0,
            mat: None,
            damper: Some(80.0),
        },
    )
    .await;
}

struct EconSample {
    fan: Option<f64>,
    oa: f64,
    rat: f64,
    mat: Option<f64>,
    damper: Option<f64>,
}

async fn insert_econ(pool: &PgPool, site: &str, ts: chrono::DateTime<Utc>, sample: EconSample) {
    insert_sample(pool, site, ts, &format!("{AHU}.oa_t"), sample.oa).await;
    insert_sample(pool, site, ts, &format!("{AHU}.rat"), sample.rat).await;
    insert_sample(pool, site, ts, &format!("{AHU}.sat"), 55.0).await;
    if let Some(value) = sample.mat {
        insert_sample(pool, site, ts, &format!("{AHU}.mat"), value).await;
    }
    if let Some(value) = sample.damper {
        insert_sample(pool, site, ts, &format!("{AHU}.oa_damper_pct"), value).await;
    }
    if let Some(value) = sample.fan {
        insert_sample(pool, site, ts, &format!("{AHU}.fan_status"), value).await;
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
