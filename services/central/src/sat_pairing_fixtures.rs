//! Handler fixtures for one weather-bound outdoor series, alignment age, and scope.
//!
//! PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is set (the Rust CI job).
//! Rows are inserted into `sample`. The assertions read the HTTP handlers.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use chrono::{Duration, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::state::AppState;

const PAIR: &str = "w4d-sat-pair";
const WB: &str = "w4d-sat-wb";
const AHU_A: &str = "W4D_AHU_A";
const AHU_B: &str = "W4D_AHU_B";
const WX_A: &str = "W4D_WX_A";
const WX_B: &str = "W4D_WX_B";
const CHILLER: &str = "W4D_CH";
const VAV_1: &str = "W4D_VAV_1";
const VAV_2: &str = "W4D_VAV_2";

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
    reason = "serialize OPENFDD_DATABASE_URL for the SAT pairing fixture"
)]
async fn sat_scatter_binds_one_weather_series_and_scopes_the_window() {
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
    let _shed = EnvGuard::set("OPENFDD_MEMORY_SHED_FRACTION", "0.99");
    let _abort = EnvGuard::set("OPENFDD_MEMORY_ABORT_FRACTION", "1.0");
    let _shared_pool = SharedPoolReset::arm();

    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("sat pairing postgres fixture");
    apply_schema(&pool).await;
    for site in [PAIR, WB] {
        purge_site(&pool, site).await;
    }
    seed(&pool).await;

    let state = Arc::new(AppState::new());
    let app = crate::routes::router(state);

    let open = post_preset(&app, PAIR, "ahu_sat_reset_scatter", None, None, None).await;
    let points = points_of(&open);
    assert_eq!(
        points.len(),
        5,
        "one X series, not every OAT identity: {open}"
    );
    assert_eq!(
        points
            .iter()
            .filter(|p| ts_of(p).contains("2026-06-01T12:00:00"))
            .count(),
        2,
        "two SAT rows at the same time stay two pairs: {open}"
    );
    assert_pair(&open, 48.0, 60.0, 0.0, "good");
    assert_pair(&open, 77.0, 60.0, 0.0, "good");
    assert_pair(&open, 50.0, 61.0, 600.0, "uncertain");
    assert_pair(&open, 53.0, 62.0, 900.0, "good");
    assert_pair(&open, 52.0, 70.0, 0.0, "good");
    assert!(points.iter().all(|p| p["x_equipment_id"] == WX_A), "{open}");
    assert!(
        points
            .iter()
            .all(|p| p["x_role"] == "web_oa_t" && p["x_quantity"] == "dry_bulb_temperature"),
        "{open}"
    );
    assert!(
        points
            .iter()
            .all(|p| p["x_openfdd_key"] == format!("{WX_A}.web_oa_t")),
        "{open}"
    );
    assert!(
        points.iter().all(|p| p.get("dry_bulb_f").is_none()),
        "dry-bulb preset does not copy X into a second dry-bulb trace: {open}"
    );
    for forbidden in [67.0, 66.0, 64.0, 63.0, 99.0, 55.0] {
        assert!(
            points.iter().all(|p| !near(p["x_f"].as_f64(), forbidden)
                && !near(p["oat_f"].as_f64(), forbidden)
                && !near(p["y_f"].as_f64(), forbidden)),
            "substituted or unpaired value {forbidden} leaked: {open}"
        );
    }
    let cov = &open["coverage"];
    assert_eq!(cov["x_available"], true);
    assert_eq!(cov["x_point"]["equipment_id"], WX_A);
    assert_eq!(cov["x_point"]["role"], "web_oa_t");
    assert_eq!(cov["x_point"]["quantity"], "dry_bulb_temperature");
    assert_eq!(cov["x_point"]["unit"], "°F");
    assert_eq!(cov["alignment"]["method"], "nearest_sample");
    assert_eq!(cov["alignment"]["max_age_seconds"], 900);
    assert_eq!(cov["alignment"]["interpolation"], false);
    assert_eq!(cov["alignment"]["tie_break"], "earlier_timestamp");
    assert_eq!(cov["prefer_wetbulb"], false);
    assert_eq!(
        cov["effective_equipment_ids"],
        json!([AHU_A, AHU_B]),
        "{cov}"
    );

    let scoped = post_preset(
        &app,
        PAIR,
        "ahu_sat_reset_scatter",
        Some("2026-06-01T12:00:00Z"),
        Some("2026-06-01T15:00:00Z"),
        Some(vec![AHU_A]),
    )
    .await;
    let scoped_points = points_of(&scoped);
    assert_eq!(scoped_points.len(), 3, "{scoped}");
    assert_pair(&scoped, 48.0, 60.0, 0.0, "good");
    assert_pair(&scoped, 50.0, 61.0, 600.0, "uncertain");
    assert_pair(&scoped, 53.0, 62.0, 900.0, "good");
    let scoped_body = scoped.to_string();
    for absent in ["77", "52.0", "70", "54", "63", "99", AHU_B] {
        assert!(
            !scoped_points.iter().any(|p| {
                near(p["y_f"].as_f64(), absent.parse().unwrap_or(f64::NAN))
                    || near(p["x_f"].as_f64(), absent.parse().unwrap_or(f64::NAN))
                    || p["equipment_id"] == absent
            }),
            "{absent} is outside the requested scope: {scoped_body}"
        );
    }
    let scov = &scoped["coverage"];
    assert_eq!(scov["window_start"], "2026-06-01T12:00:00Z");
    assert_eq!(scov["window_end"], "2026-06-01T15:00:00Z");
    assert_eq!(scov["equipment_ids"], json!([AHU_A]));
    assert_eq!(scov["effective_equipment_ids"], json!([AHU_A]));

    let missing_wb = post_preset(&app, PAIR, "cw_reset_scatter", None, None, None).await;
    assert!(
        points_of(&missing_wb).is_empty(),
        "missing wet-bulb returns no pairs: {missing_wb}"
    );
    let missing_text = warning_text(&missing_wb);
    assert!(
        missing_text.contains("wet-bulb") && missing_text.contains("unavailable"),
        "{missing_wb}"
    );
    assert_eq!(missing_wb["coverage"]["x_available"], false);
    assert_eq!(
        missing_wb["coverage"]["x_point"]["quantity"],
        "wet_bulb_temperature"
    );
    assert_eq!(missing_wb["coverage"]["prefer_wetbulb"], true);
    assert!(
        !missing_wb.to_string().contains("\"x_f\""),
        "dry-bulb was not plotted under a wet-bulb request: {missing_wb}"
    );

    let chw = post_preset(&app, PAIR, "chw_reset_scatter", None, None, None).await;
    let chw_points = points_of(&chw);
    assert_eq!(chw_points.len(), 1, "{chw}");
    assert_pair(&chw, 44.0, 60.0, 0.0, "good");
    assert_eq!(
        chw["coverage"]["x_point"]["quantity"],
        "dry_bulb_temperature"
    );
    assert_eq!(chw["coverage"]["prefer_wetbulb"], false);
    assert!(chw_points.iter().all(|p| p.get("dry_bulb_f").is_none()));

    let cw = post_preset(&app, WB, "cw_reset_scatter", None, None, None).await;
    let cw_points = points_of(&cw);
    assert_eq!(cw_points.len(), 1, "{cw}");
    assert_pair(&cw, 82.0, 70.0, 0.0, "good");
    assert!(near(cw_points[0]["dry_bulb_f"].as_f64(), 88.0), "{cw}");
    assert_eq!(cw_points[0]["x_quantity"], "wet_bulb_temperature");
    assert!(
        (cw_points[0]["dry_bulb_f"].as_f64().unwrap_or(0.0) - 70.0).abs() > 1.0,
        "dry-bulb reference is not a copy of wet-bulb: {cw}"
    );

    let chw_wb = post_preset(&app, WB, "chw_reset_scatter", None, None, None).await;
    let chw_wb_points = points_of(&chw_wb);
    assert_eq!(chw_wb_points.len(), 1, "{chw_wb}");
    assert_pair(&chw_wb, 45.0, 88.0, 0.0, "good");
    assert_eq!(
        chw_wb_points[0]["x_quantity"], "dry_bulb_temperature",
        "{chw_wb}"
    );
    assert!(chw_wb_points.iter().all(|p| p.get("dry_bulb_f").is_none()));
    assert!(
        chw_wb_points.iter().all(|p| !near(p["x_f"].as_f64(), 70.0)),
        "wet-bulb was not used for a dry-bulb request: {chw_wb}"
    );

    let dats = post_preset(
        &app,
        PAIR,
        "ahu_dats",
        Some("2026-06-01T12:00:00Z"),
        Some("2026-06-01T15:00:00Z"),
        Some(vec![AHU_A]),
    )
    .await;
    let primary: Vec<&Value> = points_of(&dats)
        .iter()
        .filter(|p| p["series"] == "primary")
        .collect();
    assert_eq!(primary.len(), 3, "{dats}");
    for want in [48.0, 50.0, 53.0] {
        assert!(
            primary.iter().any(|p| near(p["value_f"].as_f64(), want)),
            "missing {want}: {dats}"
        );
    }
    for absent in [77.0, 52.0, 54.0, 51.0] {
        assert!(
            primary
                .iter()
                .all(|p| !near(p["value_f"].as_f64(), absent) && p["equipment_id"] == AHU_A),
            "{absent} leaked into the scoped timeseries: {dats}"
        );
    }
    assert_eq!(dats["coverage"]["window_start"], "2026-06-01T12:00:00Z");
    assert_eq!(dats["coverage"]["window_end"], "2026-06-01T15:00:00Z");
    assert_eq!(dats["coverage"]["equipment_ids"], json!([AHU_A]));
    assert_eq!(dats["coverage"]["effective_equipment_ids"], json!([AHU_A]));
    assert_eq!(primary[0]["quantity"], "absolute_temperature");
    assert_eq!(primary[0]["unit"], "°F");

    let vav = post_json(
        &app,
        "/api/analytics/rcx/vav",
        json!({
            "building_id": PAIR,
            "max_points": 2000,
            "refresh": true,
            "start": "2026-06-01T12:00:00Z",
            "end": "2026-06-01T13:00:00Z",
            "equipment_ids": [VAV_1],
        }),
    )
    .await;
    let rows = vav["rows"].as_array().expect("vav rows");
    assert_eq!(rows.len(), 1, "{vav}");
    assert_eq!(rows[0]["equipment_id"], VAV_1);
    assert!(near(rows[0]["val"].as_f64(), 72.0), "{vav}");
    assert_eq!(vav["window_start"], "2026-06-01T12:00:00Z");
    assert_eq!(vav["window_end"], "2026-06-01T13:00:00Z");
    assert_eq!(vav["equipment_ids"], json!([VAV_1]));
    let vav_body = vav.to_string();
    assert!(!vav_body.contains(VAV_2), "{vav}");
    assert!(!vav_body.contains("73"), "{vav}");

    let inspect = post_json(
        &app,
        "/api/analytics/inspect",
        json!({
            "building_id": PAIR,
            "max_points": 2000,
            "refresh": true,
            "start": "2026-06-01T12:00:00Z",
            "end": "2026-06-01T13:00:00Z",
            "equipment_ids": [AHU_A],
            "series": { "columns": ["sat"] },
        }),
    )
    .await;
    let inspect_points = points_of(&inspect);
    assert_eq!(inspect_points.len(), 1, "{inspect}");
    assert!(near(inspect_points[0]["sat"].as_f64(), 48.0), "{inspect}");
    assert!(
        inspect_points
            .iter()
            .all(|p| !ts_of(p).contains("2026-06-01T13:00:00")),
        "inspect sampled past the window: {inspect}"
    );
    assert_eq!(inspect["coverage"]["window_start"], "2026-06-01T12:00:00Z");
    assert_eq!(inspect["coverage"]["window_end"], "2026-06-01T13:00:00Z");
    assert_eq!(inspect["coverage"]["equipment_ids"], json!([AHU_A]));
    assert_eq!(
        inspect["coverage"]["effective_equipment_ids"],
        json!([AHU_A])
    );

    for site in [PAIR, WB] {
        purge_site(&pool, site).await;
    }
}

fn points_of(body: &Value) -> &Vec<Value> {
    body["points"]
        .as_array()
        .unwrap_or_else(|| panic!("points: {body}"))
}

fn ts_of(point: &Value) -> String {
    point["timestamp_utc"].as_str().unwrap_or("").to_string()
}

fn near(value: Option<f64>, want: f64) -> bool {
    value.is_some_and(|got| (got - want).abs() < 0.51)
}

fn assert_pair(body: &Value, y: f64, x: f64, age: f64, quality: &str) {
    let found = points_of(body).iter().any(|p| {
        near(p["y_f"].as_f64(), y)
            && near(p["x_f"].as_f64(), x)
            && near(p["oat_f"].as_f64(), x)
            && near(p["x_age_seconds"].as_f64(), age)
            && p["x_quality"] == quality
            && p["x_unit"] == "°F"
    });
    assert!(
        found,
        "missing y={y} x={x} age={age} quality={quality}: {body}"
    );
}

fn warning_text(body: &Value) -> String {
    body.get("warnings")
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

async fn post_preset(
    app: &axum::Router,
    building_id: &str,
    preset_id: &str,
    start: Option<&str>,
    end: Option<&str>,
    equipment_ids: Option<Vec<&str>>,
) -> Value {
    let mut payload = json!({
        "building_id": building_id,
        "max_points": 2000,
        "refresh": true,
        "series": { "preset_id": preset_id },
    });
    if let Some(start) = start {
        payload["start"] = json!(start);
    }
    if let Some(end) = end {
        payload["end"] = json!(end);
    }
    if let Some(ids) = equipment_ids {
        payload["equipment_ids"] = json!(ids);
    }
    let body = post_json(app, "/api/analytics/rcx/preset", payload).await;
    // Preset responses are the result-cache wrapper. The computed envelope is `analytics`.
    body.get("analytics").cloned().unwrap_or(body)
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
    crate::analytics_response_fixtures::analytics_envelope(&body)
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
        "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
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
    for site in [PAIR, WB] {
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
    insert_equip(pool, PAIR, AHU_A, "ahu").await;
    insert_equip(pool, PAIR, AHU_B, "ahu").await;
    insert_equip(pool, PAIR, WX_A, "weather").await;
    insert_equip(pool, PAIR, WX_B, "weather").await;
    insert_equip(pool, PAIR, CHILLER, "chiller").await;
    insert_equip(pool, PAIR, VAV_1, "vav").await;
    insert_equip(pool, PAIR, VAV_2, "vav").await;
    insert_equip(pool, WB, WX_A, "weather").await;
    insert_equip(pool, WB, CHILLER, "chiller").await;

    let t0 = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap();
    let t1 = t0 + Duration::hours(1);
    let t2 = t0 + Duration::hours(2);
    let t3 = t0 + Duration::hours(4);
    let t4 = t0 + Duration::hours(6);
    let t5 = t0 + Duration::hours(8);

    insert_sample(pool, PAIR, t0, &format!("{AHU_A}.sat"), 48.0, None).await;
    insert_sample(pool, PAIR, t0, &format!("{AHU_A}.oa_t"), 67.0, Some("good")).await;
    insert_sample(
        pool,
        PAIR,
        t0,
        &format!("{AHU_A}.web_oa_t"),
        66.0,
        Some("good"),
    )
    .await;
    insert_sample(
        pool,
        PAIR,
        t0,
        &format!("{AHU_A}.web_wb_t"),
        55.0,
        Some("good"),
    )
    .await;
    insert_sample(
        pool,
        PAIR,
        t0,
        &format!("{WX_B}.web_oa_t"),
        64.0,
        Some("good"),
    )
    .await;
    insert_sample(
        pool,
        PAIR,
        t0,
        &format!("{WX_A}.web_oa_t"),
        60.0,
        Some("good"),
    )
    .await;
    insert_sample(pool, PAIR, t0, &format!("{AHU_B}.sat"), 77.0, None).await;
    insert_sample(
        pool,
        PAIR,
        t0,
        &format!("{CHILLER}.chw_supply_t"),
        44.0,
        None,
    )
    .await;
    insert_sample(
        pool,
        PAIR,
        t0,
        &format!("{CHILLER}.cw_supply_t"),
        80.0,
        None,
    )
    .await;

    insert_sample(pool, PAIR, t1, &format!("{AHU_A}.sat"), 50.0, None).await;
    insert_sample(
        pool,
        PAIR,
        t1 + Duration::minutes(10),
        &format!("{WX_A}.web_oa_t"),
        61.0,
        Some("uncertain"),
    )
    .await;

    insert_sample(pool, PAIR, t2, &format!("{AHU_A}.sat"), 53.0, None).await;
    insert_sample(
        pool,
        PAIR,
        t2 + Duration::seconds(900),
        &format!("{WX_A}.web_oa_t"),
        62.0,
        Some("good"),
    )
    .await;

    insert_sample(pool, PAIR, t3, &format!("{AHU_A}.sat"), 54.0, None).await;
    insert_sample(
        pool,
        PAIR,
        t3 + Duration::seconds(901),
        &format!("{WX_A}.web_oa_t"),
        63.0,
        Some("good"),
    )
    .await;

    insert_sample(pool, PAIR, t4, &format!("{AHU_A}.sat"), 52.0, None).await;
    insert_sample(
        pool,
        PAIR,
        t4,
        &format!("{WX_A}.web_oa_t"),
        70.0,
        Some("good"),
    )
    .await;

    insert_sample(pool, PAIR, t5, &format!("{AHU_A}.sat"), 51.0, None).await;
    insert_sample(
        pool,
        PAIR,
        t5 + Duration::minutes(20),
        &format!("{WX_A}.web_oa_t"),
        99.0,
        Some("good"),
    )
    .await;

    insert_sample(pool, PAIR, t0, &format!("{VAV_1}.zone_t"), 72.0, None).await;
    insert_sample(
        pool,
        PAIR,
        t0 + Duration::hours(6),
        &format!("{VAV_1}.zone_t"),
        73.0,
        None,
    )
    .await;
    insert_sample(pool, PAIR, t0, &format!("{VAV_2}.zone_t"), 80.0, None).await;

    insert_sample(
        pool,
        WB,
        t0,
        &format!("{WX_A}.web_wb_t"),
        70.0,
        Some("good"),
    )
    .await;
    insert_sample(
        pool,
        WB,
        t0,
        &format!("{WX_A}.web_oa_t"),
        88.0,
        Some("good"),
    )
    .await;
    insert_sample(pool, WB, t0, &format!("{CHILLER}.cw_supply_t"), 82.0, None).await;
    insert_sample(pool, WB, t0, &format!("{CHILLER}.chw_supply_t"), 45.0, None).await;
}

async fn insert_equip(pool: &PgPool, site: &str, equipment_id: &str, equip_type: &str) {
    sqlx::query(
        "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, $3)",
    )
    .bind(site)
    .bind(equipment_id)
    .bind(equip_type)
    .execute(pool)
    .await
    .unwrap_or_else(|err| panic!("equip {equipment_id}: {err}"));
}

async fn insert_sample(
    pool: &PgPool,
    site: &str,
    ts: chrono::DateTime<Utc>,
    key: &str,
    val: f64,
    quality: Option<&str>,
) {
    sqlx::query(
        "INSERT INTO sample (ts, site_id, openfdd_key, val, quality) VALUES ($1, $2, $3, $4, $5)
         ON CONFLICT (site_id, openfdd_key, ts) DO UPDATE SET val = EXCLUDED.val, quality = EXCLUDED.quality",
    )
    .bind(ts)
    .bind(site)
    .bind(key)
    .bind(val)
    .bind(quality)
    .execute(pool)
    .await
    .unwrap_or_else(|err| panic!("insert {key}: {err}"));
    crate::series_binding::bind_conventional_key(pool, site, key).await;
}
