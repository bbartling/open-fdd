//! Duplicate-timestamp oracle fixtures through the product historian and SQL rules.
//!
//! Each `crates/fdd_rules/fixtures/oracle/<RULE>/duplicate_timestamp` fixture
//! repeats one timestamp. The rows go through `Tsdb::upsert_samples_stats`
//! (the ingest path) twice, then the product pivot and rule SQL run. The
//! repeated row and the retried batch must not add samples, and SQL fault
//! hours must match the pandas oracle hours pinned in `expected.json`
//! (`scripts/golden_dual_compare.py` checks the pandas side).
//!
//! Runs when `OPENFDD_TEST_DATABASE_URL` is set.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;

use super::*;

const RULES: [&str; 6] = ["FC7", "RESET-1", "VAV-2", "VAV-4", "VAV-6", "VAV-7"];

const TOLERANCE_HOURS: f64 = 1.0 / 3600.0;

const HELPERS: &str = include_str!("../../../sql/fdd/postgres/postgres_helpers.sql");

fn fixture_dir(rule: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../crates/fdd_rules/fixtures/oracle")
        .join(rule)
        .join("duplicate_timestamp")
}

/// Product history is numeric. Occupancy strings land as 0/1 like a package seed.
fn cell_value(raw: &str) -> Option<f64> {
    let t = raw.trim();
    if t.is_empty() {
        return None;
    }
    match t.to_ascii_lowercase().as_str() {
        "unoccupied" => Some(0.0),
        "occupied" => Some(1.0),
        other => other.parse().ok(),
    }
}

struct Fixture {
    equipment_id: String,
    columns: Vec<String>,
    rows: Vec<(DateTime<Utc>, Vec<Option<f64>>)>,
    pandas_hours: f64,
}

fn load_fixture(rule: &str) -> Fixture {
    let dir = fixture_dir(rule);
    let meta: Value = serde_json::from_str(
        &std::fs::read_to_string(dir.join("expected.json")).expect("expected.json"),
    )
    .expect("expected json");
    let pandas_hours = meta["fault_hours"]
        .as_f64()
        .unwrap_or_else(|| panic!("{rule}: expected.json must pin pandas fault_hours"));
    let equipment_id = meta["equipment_id"]
        .as_str()
        .expect("equipment_id")
        .to_string();
    let text = std::fs::read_to_string(dir.join("history_wide.csv")).expect("history");
    let mut lines = text.lines();
    let header: Vec<String> = lines
        .next()
        .expect("header")
        .split(',')
        .map(|s| s.trim().to_string())
        .collect();
    assert_eq!(header[0], "timestamp_utc");
    let columns = header[1..].to_vec();
    let rows = lines
        .filter(|l| !l.trim().is_empty())
        .map(|line| {
            let cells: Vec<&str> = line.split(',').collect();
            let ts = DateTime::parse_from_rfc3339(cells[0].trim())
                .expect("timestamp")
                .with_timezone(&Utc);
            (ts, cells[1..].iter().map(|c| cell_value(c)).collect())
        })
        .collect();
    Fixture {
        equipment_id,
        columns,
        rows,
        pandas_hours,
    }
}

fn batch(site: &str, fx: &Fixture) -> UpsertBatch {
    let mut batch = UpsertBatch::default();
    for (ts, values) in &fx.rows {
        for (col, val) in fx.columns.iter().zip(values) {
            let Some(val) = val else { continue };
            let mut row =
                SampleRow::new(*ts, site, format!("{}.{col}", fx.equipment_id), Some(*val));
            row.equipment_id = Some(fx.equipment_id.clone());
            row.role = Some(col.clone());
            batch.push(row);
        }
    }
    batch
}

async fn purge(pool: &sqlx::PgPool, site: &str) {
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

async fn sql_fault_hours(tsdb: &Tsdb, site: &str, rule_id: &str, equipment_id: &str) -> f64 {
    let reg = load_reg().expect("registry");
    let rule = reg
        .rules
        .iter()
        .find(|r| r.rule_id == rule_id)
        .unwrap_or_else(|| panic!("{rule_id} in registry"));
    let confirm = confirm_seconds_from_payload(&json!({}), rule);
    let sql = wrap_rule_sql(
        &render_rule_sql(&reg, rule, 300.0, confirm, site, Some(equipment_id), None)
            .expect("render"),
        rule,
    );
    let roles = rule_history_roles(rule);
    let mut tx = tsdb.pool().begin().await.expect("begin");
    ensure_history_table(&mut tx, &roles)
        .await
        .expect("history");
    let n = fill_history_for_equipment(&mut tx, site, equipment_id, &roles, None, None)
        .await
        .expect("fill");
    assert!(n > 0, "{rule_id}: pivot produced no rows");
    let distinct: i64 =
        sqlx::query_scalar("SELECT count(*) - count(DISTINCT timestamp_utc) FROM history")
            .fetch_one(&mut *tx)
            .await
            .expect("pivot duplicates");
    assert_eq!(distinct, 0, "{rule_id}: pivot repeats a timestamp");
    let rows = sqlx::query(&sql)
        .fetch_all(&mut *tx)
        .await
        .expect("rule sql");
    let _ = tx.rollback().await;
    rows.first()
        .and_then(|row| row_optional_f64(row, "fault_hours"))
        .unwrap_or(0.0)
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "other fixtures point OPENFDD_SQL_ROOT at a temp registry while holding this lock"
)]
async fn duplicate_timestamp_fixtures_match_pandas_and_never_double_count() {
    let Some(url) = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
    else {
        return;
    };
    let _env_lock = crate::test_env_lock::lock_env();
    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("duplicate parity postgres");
    crate::portal_inventory_fixtures::apply_schema(&pool).await;
    // Serialize helper installation against other fixtures in the same database.
    let mut conn = pool.acquire().await.expect("conn");
    sqlx::query("SELECT pg_advisory_lock(70317)")
        .execute(&mut *conn)
        .await
        .expect("lock");
    let installed = sqlx::raw_sql(HELPERS).execute(&mut *conn).await;
    sqlx::query("SELECT pg_advisory_unlock(70317)")
        .execute(&mut *conn)
        .await
        .expect("unlock");
    drop(conn);
    installed.expect("fdd helpers");
    let tsdb = Tsdb::from_pool(pool.clone());

    let mut report = Vec::new();
    for rule in RULES {
        let fx = load_fixture(rule);
        let site = format!("w7n-dup-{}", rule.to_ascii_lowercase());
        purge(&pool, &site).await;
        tsdb.ensure_site_building(&site).await.expect("site");

        let distinct: BTreeSet<(DateTime<Utc>, &str)> = fx
            .rows
            .iter()
            .flat_map(|(ts, values)| {
                fx.columns
                    .iter()
                    .zip(values)
                    .filter(|(_, v)| v.is_some())
                    .map(move |(c, _)| (*ts, c.as_str()))
            })
            .collect();
        let rows = batch(&site, &fx);
        assert!(
            rows.len() > distinct.len(),
            "{rule}: fixture has no duplicate timestamp"
        );

        let first = tsdb
            .upsert_samples_stats(&rows)
            .await
            .expect("first upsert");
        assert_eq!(first.inserted as usize, distinct.len(), "{rule}: {first:?}");
        assert_eq!(
            first.updated, 0,
            "{rule}: identical repeat rewrote a sample"
        );
        assert_eq!(
            first.unchanged as usize,
            rows.len() - distinct.len(),
            "{rule}: {first:?}"
        );
        let retry = tsdb
            .upsert_samples_stats(&rows)
            .await
            .expect("retry upsert");
        assert_eq!(
            (retry.inserted, retry.updated, retry.unchanged as usize),
            (0, 0, rows.len()),
            "{rule}: a retried batch is a duplicate, not new data"
        );
        assert_eq!(
            tsdb.sample_count(&site).await.expect("count") as usize,
            distinct.len(),
            "{rule}: duplicate timestamp stored twice"
        );

        let sql_hours = sql_fault_hours(&tsdb, &site, rule, &fx.equipment_id).await;
        report.push(format!(
            "{rule}: sql {sql_hours:.4} h, pandas {:.4} h",
            fx.pandas_hours
        ));
        assert!(
            (sql_hours - fx.pandas_hours).abs() <= TOLERANCE_HOURS,
            "{rule}: SQL {sql_hours} h vs pandas {} h",
            fx.pandas_hours
        );
        purge(&pool, &site).await;
    }
    eprintln!("{}", report.join("\n"));
}
