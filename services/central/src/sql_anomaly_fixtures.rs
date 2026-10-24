//! Timescale anomaly event-table fixtures.
//!
//! PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is set. The route output
//! is the shared fixture the React table renders
//! (`frontend/web/src/fixtures/sqlAnomalyEventV1.json`).
//! Set `OPENFDD_WRITE_SQL_ANOMALY_FIXTURE=1` to rewrite that file from the route.

use std::collections::BTreeSet;

use chrono::{DateTime, Duration, TimeZone, Utc};
use serde_json::{json, Map, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

use crate::analytics::{AnalyticsQuery, AnalyticsRequest, QV_SQL_ANOMALY};
use crate::timescale_analytics::AnalyticsSqlScope;

const MULTI: &str = "w1c-anom-multi";
const NONE: &str = "w1c-anom-none";
const CONST: &str = "w1c-anom-const";
const SHORT: &str = "w1c-anom-short";
const MISS: &str = "w1c-anom-miss";
const EMPTY: &str = "w1c-anom-empty";
const TZ: &str = "w1c-anom-tz";
const UNIT_A: &str = "UNIT_A";
const UNIT_A2: &str = "UNIT_A2";
const MULTI_VALS: [f64; 16] = [
    10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 40.0, 80.0, 10.0, 12.0, 10.0, 12.0, 40.0, 11.0,
];
const ROW_KEYS: &[&str] = &[
    "anomaly_flag",
    "avg_val",
    "equipment_id",
    "method",
    "role",
    "stddev_val",
    "threshold",
    "transition",
    "ts",
    "val",
    "z_abs",
];
const COVERAGE_KEYS: &[&str] = &[
    "contract",
    "method",
    "n_flagged",
    "n_ok",
    "n_returned",
    "n_samples",
    "n_scored",
    "semantics",
    "series",
    "transition_events",
    "truncated",
    "window_end",
    "window_rows",
    "window_start",
    "z_threshold",
];

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

fn test_database_url() -> Option<String> {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn fixture_path() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../frontend/web/src/fixtures/sqlAnomalyEventV1.json")
}

fn base() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 6, 1, 0, 0, 0).unwrap()
}

fn stamp_micros(ts: DateTime<Utc>) -> String {
    ts.to_rfc3339_opts(chrono::SecondsFormat::Micros, true)
}

fn role_list(sql: &str) -> String {
    let marker = "a.role IN (";
    let start = sql
        .find(marker)
        .unwrap_or_else(|| panic!("role list missing"));
    let rest = &sql[start + marker.len()..];
    let end = rest.find(')').unwrap_or_else(|| panic!("role list end"));
    rest[..end].split_whitespace().collect()
}

#[test]
fn anomaly_sql_shares_one_role_list_and_binds_the_controls() {
    let events = include_str!("../../../sql/analytics/postgres/queries/sql_anomaly_zscore.sql");
    let series = include_str!("../../../sql/analytics/postgres/queries/sql_anomaly_series.sql");
    assert_eq!(role_list(events), role_list(series));
    assert!(events.contains("$5::int"));
    assert!(events.contains("$6::double precision"));
    assert!(events.contains("$7::boolean"));
    assert!(events.contains("LIMIT 2000"));
    assert!(
        !events.contains(">= 3.0"),
        "the cutoff is the bound threshold, not a fixed 3.0"
    );
    assert!(
        !events.contains("LIKE") && !series.contains("LIKE"),
        "equipment selection stays an exact id match"
    );
    assert!(events.contains("= ANY ($4)") && series.contains("= ANY ($4)"));
}

struct Probe<'a> {
    site: &'a str,
    window: u32,
    threshold: f64,
    transition: bool,
    method: &'a str,
    query_version: &'a str,
    equipment: &'a [&'a str],
    start: Option<DateTime<Utc>>,
    end: Option<DateTime<Utc>>,
}

fn probe<'a>(site: &'a str, equipment: &'a [&'a str]) -> Probe<'a> {
    Probe {
        site,
        window: 4,
        threshold: 3.0,
        transition: false,
        method: "zscore",
        query_version: QV_SQL_ANOMALY,
        equipment,
        start: None,
        end: None,
    }
}

fn request_for(probe: &Probe<'_>) -> AnalyticsRequest {
    AnalyticsRequest {
        query: AnalyticsQuery {
            building_id: Some(probe.site.to_string()),
            start: probe.start,
            end: probe.end,
            equipment_ids: if probe.equipment.is_empty() {
                None
            } else {
                Some(probe.equipment.iter().map(|id| (*id).to_string()).collect())
            },
            query_version: Some(probe.query_version.to_string()),
            ..Default::default()
        },
        series: Some(json!({
            "window_rows": probe.window,
            "z_threshold": probe.threshold,
            "method": probe.method,
            "transition_events": probe.transition,
        })),
        ..Default::default()
    }
}

async fn apply_schema(pool: &PgPool) {
    crate::test_ddl::execute_idempotent_ddl(
        pool,
        "CREATE TABLE IF NOT EXISTS sample (
            ts timestamptz NOT NULL,
            site_id text NOT NULL,
            openfdd_key text NOT NULL,
            val double precision,
            PRIMARY KEY (site_id, openfdd_key, ts)
        )",
    )
    .await;
}

async fn purge(pool: &PgPool, site: &str) {
    sqlx::query("DELETE FROM sample WHERE site_id = $1")
        .bind(site)
        .execute(pool)
        .await
        .unwrap_or_else(|err| panic!("purge {site}: {err}"));
}

async fn insert_series(
    pool: &PgPool,
    site: &str,
    equipment: &str,
    role: &str,
    start: DateTime<Utc>,
    values: &[f64],
) {
    for (index, value) in values.iter().enumerate() {
        let at = start + Duration::hours(i64::try_from(index).unwrap_or(0));
        sqlx::query("INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, $4)")
            .bind(at)
            .bind(site)
            .bind(format!("{equipment}.{role}"))
            .bind(value)
            .execute(pool)
            .await
            .unwrap_or_else(|err| panic!("insert {site}: {err}"));
    }
    crate::series_binding::bind_conventional_key(pool, site, &format!("{equipment}.{role}")).await;
}

async fn run(tsdb: &fdd_tsdb::Tsdb, probe: &Probe<'_>) -> Value {
    let req = request_for(probe);
    let scope = AnalyticsSqlScope::from_request(&req);
    crate::timescale_analytics::sql_anomaly_zscore(tsdb, probe.site, &scope, &req, QV_SQL_ANOMALY)
        .await
        .unwrap_or_else(|err| panic!("sql_anomaly_zscore {}: {err}", probe.site))
}

fn prior_z(values: &[f64], index: usize, window: usize) -> Option<(f64, f64, f64)> {
    if index < window {
        return None;
    }
    let prior = &values[index - window..index];
    let n = prior.len() as f64;
    let mean = prior.iter().copied().sum::<f64>() / n;
    let var = prior
        .iter()
        .map(|value| {
            let delta = value - mean;
            delta * delta
        })
        .sum::<f64>()
        / (n - 1.0);
    if !var.is_finite() || var <= 0.0 {
        return None;
    }
    let scale = var.sqrt();
    Some((mean, scale, (values[index] - mean).abs() / scale))
}

fn expected_events(values: &[f64], window: usize, threshold: f64, edges_only: bool) -> Vec<usize> {
    let mut previous_flag = None;
    let mut events = Vec::new();
    for index in 0..values.len() {
        let Some((_, _, z)) = prior_z(values, index, window) else {
            continue;
        };
        let flag = z >= threshold;
        let rising = previous_flag != Some(true);
        if flag && (!edges_only || rising) {
            events.push(index);
        }
        previous_flag = Some(flag);
    }
    events
}

fn object_keys(value: &Value) -> Vec<String> {
    value
        .as_object()
        .map(|obj| {
            let mut keys: Vec<String> = obj.keys().cloned().collect();
            keys.sort();
            keys
        })
        .unwrap_or_default()
}

fn assert_json_near(actual: &Value, expected: &Value, path: &str) {
    match (actual, expected) {
        (Value::Number(left), Value::Number(right)) => {
            let a = left.as_f64().unwrap_or(f64::NAN);
            let b = right.as_f64().unwrap_or(f64::NAN);
            let scale = a.abs().max(b.abs()).max(1.0);
            assert!((a - b).abs() <= 1e-8 * scale, "{path}: {a} != {b}");
        }
        (Value::Array(left), Value::Array(right)) => {
            assert_eq!(left.len(), right.len(), "{path} length");
            for (index, (item, want)) in left.iter().zip(right).enumerate() {
                assert_json_near(item, want, &format!("{path}[{index}]"));
            }
        }
        (Value::Object(left), Value::Object(right)) => {
            assert_eq!(object_keys(actual), object_keys(expected), "{path} keys");
            for key in object_keys(actual) {
                assert_json_near(&left[&key], &right[&key], &format!("{path}.{key}"));
            }
        }
        _ => assert_eq!(actual, expected, "{path}"),
    }
}

fn assert_events_match_oracle(
    response: &Value,
    values: &[f64],
    window: usize,
    threshold: f64,
    edges_only: bool,
    equipment: &[&str],
    origin: DateTime<Utc>,
) {
    let rows = response["rows"].as_array().expect("rows");
    let mut seen = BTreeSet::new();
    let mut expected = BTreeSet::new();
    for id in equipment {
        for index in expected_events(values, window, threshold, edges_only) {
            expected.insert(format!(
                "{id}|sat|{}",
                stamp_micros(origin + Duration::hours(i64::try_from(index).unwrap_or(0)))
            ));
        }
    }
    for row in rows {
        assert_eq!(
            object_keys(row),
            ROW_KEYS
                .iter()
                .map(|s| (*s).to_string())
                .collect::<Vec<_>>()
        );
        assert_eq!(row["anomaly_flag"], "ANOMALY");
        assert_eq!(row["method"], "zscore");
        assert_eq!(row["role"], "sat");
        let id = row["equipment_id"].as_str().unwrap_or("");
        let ts = row["ts"].as_str().unwrap_or("");
        assert!(ts.ends_with('Z'), "{ts}");
        assert!(!ts.contains("+00"), "{ts}");
        let identity = format!("{id}|sat|{ts}");
        assert!(seen.insert(identity.clone()), "duplicate event {identity}");
        let parsed = DateTime::parse_from_rfc3339(ts)
            .expect("ts")
            .with_timezone(&Utc);
        let index = usize::try_from((parsed - origin).num_hours()).expect("hour index");
        let (mean, scale, z) = prior_z(values, index, window).expect("scored sample");
        let val = row["val"].as_f64().expect("val");
        assert!((val - values[index]).abs() <= 1e-12, "val {val}");
        assert!((row["avg_val"].as_f64().unwrap_or(0.0) - mean).abs() <= 1e-8);
        assert!((row["stddev_val"].as_f64().unwrap_or(0.0) - scale).abs() <= 1e-8);
        assert!((row["z_abs"].as_f64().unwrap_or(0.0) - z).abs() <= 1e-8);
        assert!((row["threshold"].as_f64().unwrap_or(0.0) - threshold).abs() <= 1e-12);
        let rising = {
            let mut previous = None;
            let mut edge = false;
            for at in 0..=index {
                if let Some((_, _, score)) = prior_z(values, at, window) {
                    let flag = score >= threshold;
                    if at == index {
                        edge = previous != Some(true);
                    }
                    previous = Some(flag);
                }
            }
            edge
        };
        assert_eq!(row["transition"], json!(rising));
    }
    assert_eq!(seen, expected, "{response}");
    let coverage = &response["coverage"];
    assert_eq!(
        object_keys(coverage),
        COVERAGE_KEYS
            .iter()
            .map(|s| (*s).to_string())
            .collect::<Vec<_>>()
    );
    assert_eq!(coverage["contract"], "event-table");
    assert_eq!(coverage["semantics"], "rolling-prior-window-zscore");
    assert_eq!(coverage["n_returned"], json!(rows.len()));
    assert_eq!(response["query_version"], QV_SQL_ANOMALY);
    assert_eq!(response["truncated"], false);
}

fn stable_case(response: &Value) -> Value {
    json!({
        "building_id": response["building_id"],
        "query_id": response["query_id"],
        "query_version": response["query_version"],
        "contract": response["contract"],
        "semantics": response["semantics"],
        "method": response["method"],
        "window_rows": response["window_rows"],
        "z_threshold": response["z_threshold"],
        "transition_events": response["transition_events"],
        "truncated": response["truncated"],
        "window_start": response["window_start"],
        "window_end": response["window_end"],
        "equipment_ids": response["equipment_ids"],
        "warnings": response["warnings"],
        "rows": response["rows"],
        "coverage": response["coverage"],
    })
}

fn assert_reason(response: &Value, reason: &str) {
    let series = response["coverage"]["series"].as_array().expect("series");
    assert!(!series.is_empty(), "{response}");
    assert!(
        series.iter().all(|row| row["reason"] == reason),
        "{response}"
    );
    assert!(response["rows"].as_array().expect("rows").is_empty());
    assert_eq!(response["coverage"]["n_flagged"], 0);
    assert!(
        response["rows"]
            .as_array()
            .expect("rows")
            .iter()
            .all(|row| row.get("score").is_none() && row.get("anomaly_hours").is_none()),
        "empty history must not become a zero aggregate"
    );
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize anomaly screening and database env for the shared fixture"
)]
async fn timescale_route_matches_the_shared_event_fixture() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let _screening = EnvGuard::set("OPENFDD_SQL_ANOMALY_SCREENING", "1");
    let _database = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
    let _pool_reset = SharedPoolReset::arm();

    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("anomaly postgres");
    apply_schema(&pool).await;
    for site in [MULTI, NONE, CONST, SHORT, MISS, EMPTY, TZ] {
        purge(&pool, site).await;
    }
    let origin = base();
    insert_series(&pool, MULTI, UNIT_A, "sat", origin, &MULTI_VALS).await;
    insert_series(&pool, MULTI, UNIT_A2, "sat", origin, &MULTI_VALS).await;
    sqlx::query("INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, $4)")
        .bind(origin)
        .bind(MULTI)
        .bind(format!("{UNIT_A}.zone_rh"))
        .bind(999.0_f64)
        .execute(&pool)
        .await
        .expect("unscreened role");
    crate::series_binding::bind_conventional_key(&pool, MULTI, &format!("{UNIT_A}.zone_rh")).await;
    insert_series(
        &pool,
        NONE,
        UNIT_A,
        "sat",
        origin,
        &[
            10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0,
        ],
    )
    .await;
    insert_series(&pool, CONST, UNIT_A, "sat", origin, &[70.0; 12]).await;
    insert_series(&pool, SHORT, UNIT_A, "sat", origin, &[10.0, 20.0, 30.0]).await;
    for index in 0..4 {
        sqlx::query("INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES ($1, $2, $3, NULL)")
            .bind(origin + Duration::hours(index))
            .bind(MISS)
            .bind(format!("{UNIT_A}.sat"))
            .execute(&pool)
            .await
            .expect("null history");
    }
    crate::series_binding::bind_conventional_key(&pool, MISS, &format!("{UNIT_A}.sat")).await;
    sqlx::query(
        "INSERT INTO sample (ts, site_id, openfdd_key, val) VALUES
         (timestamptz '2026-06-15 15:15:00-04', $1, $2, 7),
         (timestamptz '2026-06-15 16:15:00-04', $1, $2, 10),
         (timestamptz '2026-06-15 17:15:00-04', $1, $2, 12),
         (timestamptz '2026-06-15 18:15:00-04', $1, $2, 10),
         (timestamptz '2026-06-15 19:15:00-04', $1, $2, 12),
         (timestamptz '2026-06-15 20:15:00-04', $1, $2, 80.125),
         (timestamptz '2026-06-16 00:15:01+00', $1, $2, 500)",
    )
    .bind(TZ)
    .bind(format!("{UNIT_A}.sat"))
    .execute(&pool)
    .await
    .expect("timezone samples");
    crate::series_binding::bind_conventional_key(&pool, TZ, &format!("{UNIT_A}.sat")).await;

    let tsdb = fdd_tsdb::Tsdb::from_pool(pool);
    let both = [UNIT_A, UNIT_A2];
    let only_a = [UNIT_A];
    let multi = run(&tsdb, &probe(MULTI, &both)).await;
    assert_events_match_oracle(&multi, &MULTI_VALS, 4, 3.0, false, &both, origin);
    assert!(multi["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .any(|row| row["transition"] == false && row["val"] == 80.0));
    assert!(multi["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .all(|row| row["val"] != 999.0 && row["role"] != "zone_rh"));
    assert_eq!(multi["coverage"]["n_flagged"], 6);
    assert_eq!(
        multi["coverage"]["series"]
            .as_array()
            .expect("series")
            .len(),
        2
    );

    let mut edges_probe = probe(MULTI, &both);
    edges_probe.transition = true;
    let edges = run(&tsdb, &edges_probe).await;
    assert_events_match_oracle(&edges, &MULTI_VALS, 4, 3.0, true, &both, origin);
    assert!(edges["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .all(|row| row["transition"] == true && row["val"] != 80.0));
    assert_eq!(
        edges["coverage"]["n_flagged"],
        multi["coverage"]["n_flagged"]
    );
    assert!(
        edges["coverage"]["n_returned"].as_i64().unwrap_or(0)
            < multi["coverage"]["n_returned"].as_i64().unwrap_or(0)
    );

    let mut threshold_probe = probe(MULTI, &only_a);
    threshold_probe.threshold = 10.0;
    let threshold = run(&tsdb, &threshold_probe).await;
    assert_events_match_oracle(&threshold, &MULTI_VALS, 4, 10.0, false, &only_a, origin);
    assert!(threshold["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .all(|row| row["val"] == 40.0));

    let mut cleared_probe = probe(MULTI, &only_a);
    cleared_probe.threshold = 30.0;
    let cleared = run(&tsdb, &cleared_probe).await;
    assert!(cleared["rows"].as_array().expect("rows").is_empty());
    assert_eq!(cleared["coverage"]["n_flagged"], 0);
    assert!(cleared["coverage"]["n_scored"].as_i64().unwrap_or(0) > 0);
    assert_eq!(cleared["coverage"]["series"][0]["reason"], "scored");

    let mut long_probe = probe(MULTI, &only_a);
    long_probe.window = 100;
    let long_window = run(&tsdb, &long_probe).await;
    assert_reason(&long_window, "short_history");
    assert_eq!(long_window["coverage"]["n_scored"], 0);
    assert_eq!(long_window["window_rows"], 100);

    let exact = run(&tsdb, &probe(MULTI, &only_a)).await;
    assert_events_match_oracle(&exact, &MULTI_VALS, 4, 3.0, false, &only_a, origin);
    assert!(exact["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .all(|row| row["equipment_id"] == UNIT_A));

    let quiet = [
        10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0, 10.0, 12.0,
    ];
    let no_event = run(&tsdb, &probe(NONE, &[])).await;
    assert_events_match_oracle(&no_event, &quiet, 4, 3.0, false, &only_a, origin);
    assert!(no_event["rows"].as_array().expect("rows").is_empty());
    assert_eq!(no_event["coverage"]["series"][0]["reason"], "scored");
    assert!(no_event["warnings"]
        .as_array()
        .expect("warnings")
        .is_empty());

    let constant = run(&tsdb, &probe(CONST, &[])).await;
    assert_reason(&constant, "constant_history");

    let short = run(&tsdb, &probe(SHORT, &[])).await;
    assert_reason(&short, "short_history");

    let missing = run(&tsdb, &probe(MISS, &[])).await;
    assert_reason(&missing, "missing_values");
    assert_eq!(missing["coverage"]["n_samples"], 0);
    assert_eq!(missing["coverage"]["series"][0]["n"], 0);
    assert!(
        missing["coverage"]["series"][0]["n_null"]
            .as_i64()
            .unwrap_or(0)
            > 0
    );
    assert!(missing["warnings"]
        .as_array()
        .expect("warnings")
        .iter()
        .any(|warning| warning
            .as_str()
            .unwrap_or("")
            .contains("no screened samples")));

    let absent = run(&tsdb, &probe(EMPTY, &[])).await;
    assert!(absent["rows"].as_array().expect("rows").is_empty());
    assert!(absent["coverage"]["series"]
        .as_array()
        .expect("series")
        .is_empty());
    assert_eq!(absent["coverage"]["n_samples"], 0);
    assert!(absent["warnings"]
        .as_array()
        .expect("warnings")
        .iter()
        .any(|warning| warning
            .as_str()
            .unwrap_or("")
            .contains("no screened samples")));

    let start = Utc.with_ymd_and_hms(2026, 6, 15, 20, 15, 0).unwrap();
    let end = Utc.with_ymd_and_hms(2026, 6, 16, 0, 15, 1).unwrap();
    let mut zone_probe = probe(TZ, &only_a);
    zone_probe.start = Some(start);
    zone_probe.end = Some(end);
    let zone = run(&tsdb, &zone_probe).await;
    let zone_vals = [10.0, 12.0, 10.0, 12.0, 80.125];
    assert_eq!(zone["rows"].as_array().expect("rows").len(), 1);
    let event = &zone["rows"][0];
    assert_eq!(event["ts"], "2026-06-16T00:15:00.000000Z");
    assert_eq!(
        event["val"].as_f64().expect("val").to_bits(),
        80.125_f64.to_bits()
    );
    assert!(zone["rows"]
        .as_array()
        .expect("rows")
        .iter()
        .all(|row| row["val"] != 500.0 && row["val"] != 7.0));
    let (_, _, z) = prior_z(&zone_vals, 4, 4).expect("timezone z");
    assert!((event["z_abs"].as_f64().unwrap_or(0.0) - z).abs() <= 1e-8);
    assert_eq!(zone["coverage"]["window_start"], "2026-06-15T20:15:00Z");
    assert_eq!(zone["window_start"], zone["coverage"]["window_start"]);
    assert_eq!(zone["coverage"]["window_end"], "2026-06-16T00:15:01Z");

    let mut legacy_probe = probe(MULTI, &both);
    legacy_probe.query_version = "sql-anomaly-v1";
    let legacy = run(&tsdb, &legacy_probe).await;
    assert_eq!(legacy["query_version"], QV_SQL_ANOMALY);
    assert_eq!(legacy["rows"], multi["rows"]);
    assert!(legacy["warnings"]
        .as_array()
        .expect("warnings")
        .iter()
        .any(|warning| warning.as_str().unwrap_or("").contains("sql-anomaly-v1")));

    let mut robust_probe = probe(MULTI, &only_a);
    robust_probe.method = "robust";
    let unsupported = run(&tsdb, &robust_probe).await;
    assert!(unsupported["rows"].as_array().expect("rows").is_empty());
    assert!(unsupported["warnings"]
        .as_array()
        .expect("warnings")
        .iter()
        .any(|warning| warning.as_str().unwrap_or("").contains("not supported")));

    let dispatch_req = request_for(&probe(MULTI, &both));
    let dispatched =
        crate::timescale_analytics::respond_query("sql-anomaly", QV_SQL_ANOMALY, &dispatch_req)
            .await
            .unwrap_or_else(|err| panic!("dispatch: {err:?}"));
    assert_eq!(dispatched["rows"], multi["rows"]);

    let disabled = {
        let _off = EnvGuard::set("OPENFDD_SQL_ANOMALY_SCREENING", "0");
        run(&tsdb, &probe(MULTI, &both)).await
    };
    assert!(disabled["rows"].as_array().expect("rows").is_empty());
    assert!(disabled["warnings"]
        .as_array()
        .expect("warnings")
        .iter()
        .any(|warning| warning.as_str().unwrap_or("").contains("disabled")));
    assert_eq!(disabled["coverage"]["n_flagged"], 0);

    let mut cases = Map::new();
    let mut insert = |name: &str, response: &Value| {
        cases.insert(name.to_string(), stable_case(response));
    };
    insert("multi_event", &multi);
    insert("transition_edges", &edges);
    insert("custom_threshold", &threshold);
    insert("high_threshold", &cleared);
    insert("long_window", &long_window);
    insert("exact_equipment", &exact);
    insert("no_event", &no_event);
    insert("constant_history", &constant);
    insert("short_history", &short);
    insert("missing_values", &missing);
    insert("no_history", &absent);
    insert("timezone_precision", &zone);
    insert("legacy_version", &legacy);
    insert("unsupported_method", &unsupported);
    insert("disabled", &disabled);
    let document = json!({
        "contract": QV_SQL_ANOMALY,
        "semantics": "rolling-prior-window-zscore",
        "query_version": QV_SQL_ANOMALY,
        "row_keys": ROW_KEYS,
        "coverage_keys": COVERAGE_KEYS,
        "cases": cases,
    });
    let path = fixture_path();
    if std::env::var("OPENFDD_WRITE_SQL_ANOMALY_FIXTURE")
        .ok()
        .is_some_and(|value| value == "1")
    {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).expect("fixture dir");
        }
        let text = serde_json::to_string_pretty(&document).expect("fixture json");
        std::fs::write(&path, format!("{text}\n")).expect("write fixture");
    }
    let saved: Value = serde_json::from_str(
        &std::fs::read_to_string(&path).unwrap_or_else(|err| panic!("read fixture: {err}")),
    )
    .expect("parse fixture");
    assert_json_near(&saved, &document, "fixture");
}
