//! PID and sensor diagnostic matrix against a real PostgreSQL sample table.
//! The product handlers are the analytics routes. Fixture sites are disposable
//! and are removed when the test ends.

use std::collections::HashMap;
use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::Router;
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Value};
use tower::ServiceExt;

use crate::state::AppState;
use crate::test_env_lock::{lock_env, WorkspaceEnv};

struct EnvSet {
    prev: Vec<(&'static str, Option<String>)>,
}

impl EnvSet {
    fn set(pairs: &[(&'static str, Option<&str>)]) -> Self {
        let prev = pairs
            .iter()
            .map(|(key, value)| {
                let old = std::env::var(key).ok();
                match value {
                    Some(next) => std::env::set_var(key, next),
                    None => std::env::remove_var(key),
                }
                (*key, old)
            })
            .collect();
        Self { prev }
    }
}

impl Drop for EnvSet {
    fn drop(&mut self) {
        for (key, old) in self.prev.drain(..) {
            match old {
                Some(value) => std::env::set_var(key, value),
                None => std::env::remove_var(key),
            }
        }
    }
}

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

struct SampleCleanup {
    url: String,
    sites: Vec<String>,
}

impl Drop for SampleCleanup {
    fn drop(&mut self) {
        let url = std::mem::take(&mut self.url);
        let sites = std::mem::take(&mut self.sites);
        if url.is_empty() || sites.is_empty() {
            return;
        }
        let joined = std::thread::spawn(move || {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("cleanup runtime");
            runtime.block_on(delete_sites(&url, &sites));
        })
        .join();
        let _ = joined;
    }
}

fn postgres_url() -> Option<String> {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

async fn delete_sites(url: &str, sites: &[String]) {
    let Ok(pool) = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(url)
        .await
    else {
        return;
    };
    for site in sites {
        let _ = sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(site)
            .execute(&pool)
            .await;
    }
}

async fn insert_series(
    pool: &sqlx::PgPool,
    site: &str,
    equipment: &str,
    role: &str,
    start: DateTime<Utc>,
    values: &[f64],
) {
    let key = format!("{equipment}.{role}");
    let step = Duration::minutes(1);
    for (index, value) in values.iter().enumerate() {
        let offset = i32::try_from(index).unwrap_or(0);
        let ts = start + step * offset;
        sqlx::query("INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, $4)")
            .bind(ts)
            .bind(site)
            .bind(&key)
            .bind(value)
            .execute(pool)
            .await
            .expect("insert sample");
    }
    crate::series_binding::bind_conventional_key(pool, site, &key).await;
}

fn repeat(value: f64, count: usize) -> Vec<f64> {
    vec![value; count]
}

fn alternate(low: f64, high: f64, count: usize) -> Vec<f64> {
    (0..count)
        .map(|index| if index % 2 == 0 { low } else { high })
        .collect()
}

async fn post_matrix(app: &Router, path: &str, building_id: &str) -> (StatusCode, Value) {
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri(path)
                .header("content-type", "application/json")
                .body(Body::from(
                    json!({ "building_id": building_id }).to_string(),
                ))
                .expect("request"),
        )
        .await
        .expect("response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let body = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    (status, body)
}

fn index_rows(body: &Value) -> HashMap<(String, String), Value> {
    let mut map = HashMap::new();
    let rows = body
        .get("rows")
        .and_then(Value::as_array)
        .expect("rows array");
    for row in rows {
        let equipment = row["equipment_id"]
            .as_str()
            .expect("equipment_id")
            .to_string();
        let role = row["role"].as_str().expect("role").to_string();
        let key = (equipment, role);
        assert!(
            map.insert(key.clone(), row.clone()).is_none(),
            "duplicate diagnostic identity {key:?} in {body}"
        );
        let site = row["site_id"].as_str().unwrap_or_default();
        let expected = format!("{site}\u{1f}{}\u{1f}{}", key.0, key.1);
        assert_eq!(
            row["row_key"].as_str(),
            Some(expected.as_str()),
            "row_key {row}"
        );
    }
    map
}

/// Two disposable sites. Handlers return one typed row per equipment role,
/// with the proxy flag, and never the other site's rows.
#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "OPENFDD_HISTORIAN and OPENFDD_DATABASE_URL are process-global while the handlers run"
)]
async fn diagnostic_matrix_handlers_keep_site_equipment_role_flags() {
    let Some(url) = postgres_url() else {
        eprintln!("skip: OPENFDD_TEST_DATABASE_URL unset");
        return;
    };
    let _lock = lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _workspace = WorkspaceEnv::set(workspace.path());
    let suffix = uuid::Uuid::new_v4().simple().to_string();
    let site_a = format!("w3c_diag_a_{suffix}");
    let site_b = format!("w3c_diag_b_{suffix}");
    let _cleanup = SampleCleanup {
        url: url.clone(),
        sites: vec![site_a.clone(), site_b.clone()],
    };
    let _env = EnvSet::set(&[
        ("OPENFDD_MULTI_TENANT", None),
        ("OPENFDD_JWT_SECRET", None),
        ("OPENFDD_HISTORIAN", Some("timescale")),
        ("OPENFDD_DATABASE_URL", Some(&url)),
    ]);
    let _shared = SharedPoolReset::arm();

    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("connect postgres fixture");
    crate::test_ddl::execute_idempotent_ddl(
        &pool,
        "CREATE TABLE IF NOT EXISTS sample (
            ts timestamptz NOT NULL,
            site_id text NOT NULL,
            openfdd_key text NOT NULL,
            val double precision,
            PRIMARY KEY (site_id, openfdd_key, ts)
        )",
    )
    .await;
    for site in [&site_a, &site_b] {
        sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(site)
            .execute(&pool)
            .await
            .expect("clear fixture site");
    }

    let recent = Utc::now() - Duration::hours(3);
    let stale_at = Utc::now() - Duration::hours(96);
    insert_series(
        &pool,
        &site_a,
        "flat_unit",
        "sat",
        recent,
        &repeat(72.0, 24),
    )
    .await;
    insert_series(
        &pool,
        &site_a,
        "flat_unit",
        "zone_t",
        recent,
        &alternate(60.0, 62.0, 24),
    )
    .await;
    insert_series(
        &pool,
        &site_a,
        "hunt_unit",
        "zone_t",
        recent,
        &alternate(40.0, 90.0, 24),
    )
    .await;
    insert_series(
        &pool,
        &site_a,
        "range_unit",
        "supply_t",
        recent,
        &alternate(70.0, 280.0, 12),
    )
    .await;
    insert_series(
        &pool,
        &site_a,
        "stale_unit",
        "oa_t",
        stale_at,
        &repeat(55.0, 12),
    )
    .await;
    insert_series(
        &pool,
        &site_b,
        "foreign_unit",
        "sat",
        recent,
        &repeat(72.0, 16),
    )
    .await;

    let app = crate::routes::router(Arc::new(AppState::new()));
    let (status, body) = post_matrix(&app, "/api/analytics/sensor-faults", &site_a).await;
    assert_eq!(status, StatusCode::OK, "sensor-faults {body}");
    assert_eq!(body["schema_version"], json!("diagnostic_matrix_v1"));
    assert_eq!(body["query_version"], json!("diagnostic-matrix-v1"));
    assert_eq!(body["query_id"], json!("sensor-faults"));
    assert_eq!(body["site_id"], json!(site_a));
    assert_eq!(body["building_id"], json!(site_a));
    let sensor = index_rows(&body);
    assert_eq!(sensor.len(), 5, "sensor rows {body}");
    assert_eq!(
        sensor[&("flat_unit".into(), "sat".into())]["fault_flag"],
        json!("FLATLINE")
    );
    assert_eq!(
        sensor[&("flat_unit".into(), "sat".into())]["flag"],
        json!("FLATLINE")
    );
    assert_eq!(sensor[&("flat_unit".into(), "sat".into())]["n"], json!(24));
    assert_eq!(
        sensor[&("flat_unit".into(), "zone_t".into())]["fault_flag"],
        json!("OK")
    );
    assert_eq!(
        sensor[&("hunt_unit".into(), "zone_t".into())]["fault_flag"],
        json!("OK")
    );
    assert_eq!(
        sensor[&("range_unit".into(), "supply_t".into())]["fault_flag"],
        json!("RANGE")
    );
    assert_eq!(
        sensor[&("stale_unit".into(), "oa_t".into())]["fault_flag"],
        json!("STALE")
    );
    assert!(sensor
        .keys()
        .all(|(equipment, _)| equipment != "foreign_unit"));
    assert!(body["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .all(|row| row["site_id"] == json!(site_a) && row.get("hunt_flag").is_none()));

    let (status, body) = post_matrix(&app, "/api/analytics/pid-hunting", &site_a).await;
    assert_eq!(status, StatusCode::OK, "pid-hunting {body}");
    assert_eq!(body["schema_version"], json!("diagnostic_matrix_v1"));
    assert_eq!(body["query_id"], json!("pid-hunting"));
    assert_eq!(body["site_id"], json!(site_a));
    let hunt = index_rows(&body);
    assert_eq!(hunt.len(), 3, "pid rows {body}");
    assert_eq!(
        hunt[&("flat_unit".into(), "sat".into())]["hunt_flag"],
        json!("OK")
    );
    assert_eq!(
        hunt[&("flat_unit".into(), "zone_t".into())]["hunt_flag"],
        json!("OK")
    );
    assert_eq!(
        hunt[&("hunt_unit".into(), "zone_t".into())]["hunt_flag"],
        json!("HUNT_PROXY")
    );
    assert_eq!(
        hunt[&("hunt_unit".into(), "zone_t".into())]["flag"],
        json!("HUNT_PROXY")
    );
    assert!(hunt
        .keys()
        .all(|(equipment, _)| equipment != "foreign_unit"));
    assert!(body["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .all(|row| row["site_id"] == json!(site_a) && row.get("fault_flag").is_none()));

    let (status, body) = post_matrix(&app, "/api/analytics/sensor-faults", &site_b).await;
    assert_eq!(status, StatusCode::OK, "site b sensor {body}");
    let foreign = index_rows(&body);
    assert_eq!(foreign.len(), 1, "site b rows {body}");
    assert_eq!(
        foreign[&("foreign_unit".into(), "sat".into())]["fault_flag"],
        json!("FLATLINE")
    );
    assert_eq!(body["site_id"], json!(site_b));
    assert!(foreign
        .keys()
        .all(|(equipment, _)| equipment != "flat_unit"));
}
