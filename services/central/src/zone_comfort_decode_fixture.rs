//! Zone comfort ranking against real PostgreSQL result types.
//!
//! `AVG(CASE ... 1.0 ELSE 0.0 END)` is PostgreSQL `numeric`, which sqlx does
//! not decode as `f64`. The ranking used to swallow that decode error, so every
//! row came back with a null `comfort_pct`. These fixtures seed `sample` rows,
//! run the `zone_comfort_rank` preset dispatch, and pin the decoded values.
//!
//! Runs when `OPENFDD_TEST_DATABASE_URL` is set.

use chrono::{DateTime, TimeZone, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;

use super::*;

const LOW_F: f64 = 70.0;
const HIGH_F: f64 = 75.0;
const PRESET: &str = "zone_comfort_rank";

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
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        match self.prev.take() {
            Some(value) => std::env::set_var(self.key, value),
            None => std::env::remove_var(self.key),
        }
        fdd_tsdb::clear_shared_pool();
    }
}

fn test_database_url() -> Option<String> {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn at(minute: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 6, 1, 12, minute, 0).unwrap()
}

fn scope() -> crate::timescale_analytics::AnalyticsSqlScope {
    crate::timescale_analytics::AnalyticsSqlScope {
        start: None,
        end: None,
        equipment_ids: Vec::new(),
    }
}

async fn ensure_schema(pool: &sqlx::PgPool) {
    crate::series_binding::ensure_authorized_series(pool).await;
    for statement in [
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
            haystack_id text,
            val double precision,
            unit text,
            quality text,
            PRIMARY KEY (site_id, openfdd_key, ts)
        )",
    ] {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
}

async fn seed_vav(pool: &sqlx::PgPool, site: &str, equipment_id: &str, values: &[Option<f64>]) {
    for (sql, what) in [
        (
            "INSERT INTO site(site_id, dis) VALUES ($1, $1) ON CONFLICT (site_id) DO NOTHING",
            "site",
        ),
        (
            "INSERT INTO building(building_id, site_id, dis) VALUES ($1, $1, $1)
             ON CONFLICT (building_id) DO NOTHING",
            "building",
        ),
    ] {
        sqlx::query(sql).bind(site).execute(pool).await.expect(what);
    }
    sqlx::query(
        "INSERT INTO equipment(building_id, equipment_id, equip_type) VALUES ($1, $2, 'vav')
         ON CONFLICT (building_id, equipment_id) DO UPDATE SET equip_type = EXCLUDED.equip_type",
    )
    .bind(site)
    .bind(equipment_id)
    .execute(pool)
    .await
    .expect("equipment");
    let key = format!("{equipment_id}.zone_t");
    for (minute, val) in values.iter().enumerate() {
        sqlx::query(
            "INSERT INTO sample(ts, site_id, openfdd_key, val, unit) VALUES ($1, $2, $3, $4, $5)",
        )
        .bind(at(u32::try_from(minute).expect("minute")))
        .bind(site)
        .bind(&key)
        .bind(*val)
        .bind("degF")
        .execute(pool)
        .await
        .expect("sample");
    }
    crate::series_binding::bind_series(pool, site, equipment_id, "zone_t", &key).await;
}

async fn cleanup(pool: &sqlx::PgPool, site: &str) {
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

async fn preset_json(site: &str, scope: &crate::timescale_analytics::AnalyticsSqlScope) -> Value {
    crate::analytics::rcx_presets::run_preset(Some(site), PRESET, 8000, scope)
        .await
        .expect("preset runs")
        .expect("preset is registered")
        .to_json()
}

fn object_keys(value: &Value) -> Vec<&str> {
    let mut keys: Vec<&str> = value
        .as_object()
        .expect("object")
        .keys()
        .map(String::as_str)
        .collect();
    keys.sort_unstable();
    keys
}

#[tokio::test]
async fn invalid_band_is_a_typed_error() {
    for (low, high) in [(HIGH_F, LOW_F), (f64::NAN, HIGH_F), (LOW_F, f64::INFINITY)] {
        let err = rcx_zone_comfort_rank("any-site", &["ZONE_FAMILY"], low, high, &scope())
            .await
            .expect_err("invalid band must not run");
        assert!(
            matches!(
                err.downcast_ref::<ComfortRankError>(),
                Some(ComfortRankError::InvalidBand { .. })
            ),
            "unexpected error for ({low}, {high}): {err:#}"
        );
    }
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize the database env for the shared fixture"
)]
async fn zone_comfort_rank_decodes_postgres_aggregate() {
    let _lock = crate::test_env_lock::lock_env();
    let Some(url) = test_database_url() else {
        eprintln!("skip: OPENFDD_TEST_DATABASE_URL is not set");
        return;
    };
    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("OPENFDD_TEST_DATABASE_URL connect");
    let _db = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
    let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
    fdd_tsdb::clear_shared_pool();
    ensure_schema(&pool).await;

    // The unfixed expression is numeric, and sqlx refuses it as f64.
    let numeric = sqlx::query(
        "SELECT 'probe'::text AS equipment_id,
                100.0 * AVG(CASE WHEN v BETWEEN 70 AND 75 THEN 1.0 ELSE 0.0 END) AS comfort_pct,
                COUNT(*)::bigint AS n
         FROM (VALUES (72.0::float8), (80.0::float8)) t(v)",
    )
    .fetch_one(&pool)
    .await
    .expect("numeric probe");
    let type_name = numeric.columns()[1].type_info().to_string();
    assert_eq!(type_name, "NUMERIC");
    assert!(numeric.try_get::<Option<f64>, _>("comfort_pct").is_err());
    assert!(matches!(
        comfort_rank_point(&numeric),
        Err(ComfortRankError::Decode {
            column: "comfort_pct",
            ..
        })
    ));
    let null_row = sqlx::query(
        "SELECT 'probe'::text AS equipment_id, NULL::float8 AS comfort_pct, 1::bigint AS n",
    )
    .fetch_one(&pool)
    .await
    .expect("null probe");
    assert!(matches!(
        comfort_rank_point(&null_row),
        Err(ComfortRankError::Decode {
            column: "comfort_pct",
            ..
        })
    ));
    let nan_row = sqlx::query(
        "SELECT 'probe'::text AS equipment_id, 'NaN'::float8 AS comfort_pct, 1::bigint AS n",
    )
    .fetch_one(&pool)
    .await
    .expect("nan probe");
    assert!(matches!(
        comfort_rank_point(&nan_row),
        Err(ComfortRankError::NonFinite { .. })
    ));

    let token = uuid::Uuid::new_v4().simple().to_string();
    let site = format!("w1b{}", &token[..8]);
    let empty_site = format!("w1e{}", &token[..8]);
    // 1 of 3 in band; 2 of 4 in band plus a null that is not a sample; band
    // edges are inclusive.
    seed_vav(
        &pool,
        &site,
        "vav_low",
        &[Some(72.0), Some(80.0), Some(65.0)],
    )
    .await;
    seed_vav(
        &pool,
        &site,
        "vav_mid",
        &[Some(70.0), Some(76.0), Some(75.0), Some(69.9), None],
    )
    .await;
    seed_vav(
        &pool,
        &site,
        "vav_high",
        &[Some(70.0), Some(72.5), Some(75.0), Some(74.0)],
    )
    .await;
    seed_vav(&pool, &site, "vav_quiet", &[]).await;
    seed_vav(&pool, &empty_site, "vav_quiet", &[]).await;

    let body = preset_json(&site, &scope()).await;
    assert_eq!(
        body["query_version"],
        json!("rcx-preset-zone_comfort_rank-v1")
    );
    assert_eq!(body["engine"], json!(TS_ENGINE));
    assert_eq!(body["coverage"]["chart_kind"], json!("ranking"));
    assert_eq!(body["coverage"]["point_count"], json!(3));
    assert_eq!(body["points"], body["rows"]);
    let points = body["points"].as_array().expect("points");
    let expected = [
        ("vav_low", 100.0 / 3.0, 3),
        ("vav_mid", 50.0, 4),
        ("vav_high", 100.0, 4),
    ];
    assert_eq!(points.len(), expected.len(), "{body}");
    for (point, (id, pct, n)) in points.iter().zip(expected) {
        assert_eq!(
            object_keys(point),
            ["comfort_pct", "equipment_id", "n", "value_f"]
        );
        assert_eq!(point["equipment_id"], json!(id));
        assert_eq!(point["n"], json!(n), "{point}");
        let comfort = point["comfort_pct"]
            .as_f64()
            .unwrap_or_else(|| panic!("comfort_pct must be a JSON number: {point}"));
        assert!(comfort > 0.0, "{point}");
        assert!((comfort - pct).abs() < 1e-9, "{point}");
        assert_eq!(point["value_f"], point["comfort_pct"]);
    }

    // No samples: an equipment with a bound key but no rows is absent, and a
    // building or window with no samples has no ranking.
    assert!(
        rcx_zone_comfort_rank(&empty_site, &["ZONE_FAMILY"], LOW_F, HIGH_F, &scope())
            .await
            .expect("empty building")
            .is_none()
    );
    let empty = preset_json(&empty_site, &scope()).await;
    assert_eq!(empty["coverage"]["empty"], json!(true));
    assert_eq!(empty["points"], json!([]));
    assert_eq!(empty["rows"], json!([]));
    let late = crate::timescale_analytics::AnalyticsSqlScope {
        start: Some(at(30)),
        end: None,
        equipment_ids: Vec::new(),
    };
    assert!(
        rcx_zone_comfort_rank(&site, &["ZONE_FAMILY"], LOW_F, HIGH_F, &late)
            .await
            .expect("empty window")
            .is_none()
    );

    cleanup(&pool, &site).await;
    cleanup(&pool, &empty_site).await;
}
