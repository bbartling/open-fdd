//! Derived analytics / RCx / sensor-fault results in PostgreSQL (`analytics_result`).
//!
//! These rows are recomputable output, not telemetry. The primary key is
//! building, query id, query version, window, and config hash. The config hash
//! already folds in the result contract, SQL pack, and model revision; those
//! three are also stored as columns so freshness can reject an unstamped row.
//! Each building keeps at most `OPENFDD_ANALYTICS_CACHE_MAX_ROWS` rows (newest
//! `updated_at` first).

use std::sync::Arc;

use fdd_store::{AnalyticsCacheKey, AnalyticsResultTable, CacheProvenance};
use serde_json::{json, Value};
use sqlx::Row;

/// Storage layout reported on `cache.schema`. Distinct from the result contract.
pub const STORE_SCHEMA: &str = "analytics-result-postgres-v1";

const DEFAULT_MAX_ROWS_PER_BUILDING: i64 = 2_000;
const MAX_ROWS_CEILING: i64 = 100_000;

pub enum ResultStore {
    Postgres(Arc<fdd_tsdb::Tsdb>),
    #[cfg(test)]
    Memory(Arc<memory::MemoryStore>),
}

/// The Timescale pool when that historian is configured. Without it the cache
/// is skipped; there is no file fallback.
pub async fn store_from_env() -> Result<ResultStore, String> {
    if !crate::timescale_historian::historian_is_timescale() {
        return Err("Timescale historian is not configured".into());
    }
    fdd_tsdb::Tsdb::shared()
        .await
        .map(ResultStore::Postgres)
        .map_err(|err| format!("Timescale connect failed: {err}"))
}

fn window_key(key: &AnalyticsCacheKey) -> String {
    format!("{}__{}", key.window_start, key.window_end)
}

fn max_rows_per_building() -> i64 {
    std::env::var("OPENFDD_ANALYTICS_CACHE_MAX_ROWS")
        .ok()
        .and_then(|raw| raw.trim().parse::<i64>().ok())
        .filter(|n| *n > 0)
        .map(|n| n.min(MAX_ROWS_CEILING))
        .unwrap_or(DEFAULT_MAX_ROWS_PER_BUILDING)
}

fn payload(table: &AnalyticsResultTable) -> Value {
    json!({
        "rows": table.rows,
        "equipment": table.equipment,
        "points": table.points,
        "skipped": table.skipped,
        "warnings": table.warnings,
        "coverage": table.coverage,
    })
}

fn values(payload: &Value, field: &str) -> Vec<Value> {
    payload
        .get(field)
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn table_from_payload(
    payload: &Value,
    engine: String,
    result_query_version: String,
) -> AnalyticsResultTable {
    AnalyticsResultTable {
        rows: values(payload, "rows"),
        equipment: values(payload, "equipment"),
        points: values(payload, "points"),
        skipped: values(payload, "skipped"),
        warnings: values(payload, "warnings")
            .into_iter()
            .filter_map(|v| v.as_str().map(str::to_string))
            .collect(),
        coverage: payload.get("coverage").filter(|v| !v.is_null()).cloned(),
        engine,
        result_query_version,
    }
}

const PROVENANCE_COLUMNS: &str = "building_id, query_id, query_version, window_start, window_end, \
     config_hash, watermark_order, watermark_utc, generated_at, engine, result_query_version, \
     result_contract, sql_pack, model_revision, watermark_source, watermark_status, coverage";

fn provenance_from_row(row: &sqlx::postgres::PgRow) -> Result<CacheProvenance, sqlx::Error> {
    let order: i64 = row.try_get("watermark_order")?;
    Ok(CacheProvenance {
        building_id: row.try_get("building_id")?,
        query_id: row.try_get("query_id")?,
        query_version: row.try_get("query_version")?,
        window_start: row.try_get("window_start")?,
        window_end: row.try_get("window_end")?,
        config_hash: row.try_get("config_hash")?,
        // A negative order was never written by this module; treat it as unknown.
        watermark_order: u64::try_from(order).unwrap_or(0),
        watermark_utc: row.try_get("watermark_utc")?,
        generated_at: row.try_get("generated_at")?,
        engine: row.try_get("engine")?,
        result_query_version: row.try_get("result_query_version")?,
        result_contract: row.try_get("result_contract")?,
        sql_pack: row.try_get("sql_pack")?,
        model_revision: row.try_get("model_revision")?,
        watermark_source: row.try_get("watermark_source")?,
        watermark_status: row.try_get("watermark_status")?,
        coverage: row.try_get("coverage")?,
    })
}

fn db_error(op: &str, err: &sqlx::Error) -> String {
    match err {
        sqlx::Error::Database(db) => format!("{op}: {}", db.message()),
        _ => format!("{op} failed"),
    }
}

impl ResultStore {
    /// Provenance only. Callers take compute admission before [`Self::read`].
    pub async fn peek(&self, key: &AnalyticsCacheKey) -> Result<Option<CacheProvenance>, String> {
        match self {
            Self::Postgres(tsdb) => {
                let sql = format!(
                    "SELECT {PROVENANCE_COLUMNS} FROM analytics_result \
                     WHERE building_id = $1 AND query_id = $2 AND query_version = $3 \
                       AND window_key = $4 AND config_hash = $5"
                );
                let row = sqlx::query(&sql)
                    .bind(&key.building_id)
                    .bind(&key.query_id)
                    .bind(&key.query_version)
                    .bind(window_key(key))
                    .bind(&key.config_hash)
                    .fetch_optional(tsdb.pool())
                    .await
                    .map_err(|err| db_error("analytics_result peek", &err))?;
                row.as_ref()
                    .map(provenance_from_row)
                    .transpose()
                    .map_err(|err| db_error("analytics_result decode", &err))
            }
            #[cfg(test)]
            Self::Memory(mem) => Ok(mem.get(key).map(|(_, prov)| prov)),
        }
    }

    pub async fn read(
        &self,
        key: &AnalyticsCacheKey,
    ) -> Result<Option<(AnalyticsResultTable, CacheProvenance)>, String> {
        match self {
            Self::Postgres(tsdb) => {
                let sql = format!(
                    "SELECT {PROVENANCE_COLUMNS}, payload FROM analytics_result \
                     WHERE building_id = $1 AND query_id = $2 AND query_version = $3 \
                       AND window_key = $4 AND config_hash = $5"
                );
                let Some(row) = sqlx::query(&sql)
                    .bind(&key.building_id)
                    .bind(&key.query_id)
                    .bind(&key.query_version)
                    .bind(window_key(key))
                    .bind(&key.config_hash)
                    .fetch_optional(tsdb.pool())
                    .await
                    .map_err(|err| db_error("analytics_result read", &err))?
                else {
                    return Ok(None);
                };
                let prov = provenance_from_row(&row)
                    .map_err(|err| db_error("analytics_result decode", &err))?;
                let payload: Value = row
                    .try_get("payload")
                    .map_err(|err| db_error("analytics_result payload", &err))?;
                let table = table_from_payload(
                    &payload,
                    prov.engine.clone(),
                    prov.result_query_version.clone(),
                );
                Ok(Some((table, prov)))
            }
            #[cfg(test)]
            Self::Memory(mem) => Ok(mem.get(key)),
        }
    }

    /// Upsert one envelope, then trim the building to the row cap.
    pub async fn write(
        &self,
        key: &AnalyticsCacheKey,
        table: &AnalyticsResultTable,
        prov: &CacheProvenance,
    ) -> Result<(), String> {
        self.write_capped(key, table, prov, max_rows_per_building())
            .await
    }

    async fn write_capped(
        &self,
        key: &AnalyticsCacheKey,
        table: &AnalyticsResultTable,
        prov: &CacheProvenance,
        max_rows: i64,
    ) -> Result<(), String> {
        match self {
            Self::Postgres(tsdb) => {
                let order = i64::try_from(prov.watermark_order)
                    .map_err(|_| "watermark order out of range".to_string())?;
                let mut tx = tsdb
                    .pool()
                    .begin()
                    .await
                    .map_err(|err| db_error("analytics_result begin", &err))?;
                sqlx::query(
                    r#"
                    INSERT INTO analytics_result (
                      building_id, query_id, query_version, window_key, config_hash, stale,
                      payload, window_start, window_end, result_contract, sql_pack,
                      model_revision, watermark_source, watermark_status, watermark_order,
                      watermark_utc, coverage, generated_at, engine, result_query_version,
                      updated_at
                    ) VALUES (
                      $1, $2, $3, $4, $5, false, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                      $15, $16, $17, $18, $19, now()
                    )
                    ON CONFLICT (building_id, query_id, query_version, window_key, config_hash)
                    DO UPDATE SET
                      stale = false,
                      payload = EXCLUDED.payload,
                      window_start = EXCLUDED.window_start,
                      window_end = EXCLUDED.window_end,
                      result_contract = EXCLUDED.result_contract,
                      sql_pack = EXCLUDED.sql_pack,
                      model_revision = EXCLUDED.model_revision,
                      watermark_source = EXCLUDED.watermark_source,
                      watermark_status = EXCLUDED.watermark_status,
                      watermark_order = EXCLUDED.watermark_order,
                      watermark_utc = EXCLUDED.watermark_utc,
                      coverage = EXCLUDED.coverage,
                      generated_at = EXCLUDED.generated_at,
                      engine = EXCLUDED.engine,
                      result_query_version = EXCLUDED.result_query_version,
                      updated_at = now()
                    "#,
                )
                .bind(&key.building_id)
                .bind(&key.query_id)
                .bind(&key.query_version)
                .bind(window_key(key))
                .bind(&key.config_hash)
                .bind(payload(table))
                .bind(&key.window_start)
                .bind(&key.window_end)
                .bind(&prov.result_contract)
                .bind(&prov.sql_pack)
                .bind(&prov.model_revision)
                .bind(&prov.watermark_source)
                .bind(&prov.watermark_status)
                .bind(order)
                .bind(&prov.watermark_utc)
                .bind(&prov.coverage)
                .bind(&prov.generated_at)
                .bind(&prov.engine)
                .bind(&prov.result_query_version)
                .execute(&mut *tx)
                .await
                .map_err(|err| db_error("analytics_result upsert", &err))?;
                sqlx::query(
                    r#"
                    DELETE FROM analytics_result
                    WHERE building_id = $1
                      AND (query_id, query_version, window_key, config_hash) IN (
                        SELECT query_id, query_version, window_key, config_hash
                        FROM analytics_result
                        WHERE building_id = $1
                        ORDER BY updated_at DESC
                        OFFSET $2
                      )
                    "#,
                )
                .bind(&key.building_id)
                .bind(max_rows)
                .execute(&mut *tx)
                .await
                .map_err(|err| db_error("analytics_result trim", &err))?;
                tx.commit()
                    .await
                    .map_err(|err| db_error("analytics_result commit", &err))
            }
            #[cfg(test)]
            Self::Memory(mem) => {
                mem.put(key, table, prov);
                Ok(())
            }
        }
    }
}

#[cfg(test)]
pub mod memory {
    //! Bounded in-process store for unit tests without a database.

    use std::collections::VecDeque;
    use std::sync::Mutex;

    use super::*;

    type Entry = (AnalyticsCacheKey, AnalyticsResultTable, CacheProvenance);

    pub struct MemoryStore {
        cap: usize,
        entries: Mutex<VecDeque<Entry>>,
    }

    impl MemoryStore {
        pub fn new(cap: usize) -> Self {
            Self {
                cap,
                entries: Mutex::new(VecDeque::new()),
            }
        }

        pub fn get(
            &self,
            key: &AnalyticsCacheKey,
        ) -> Option<(AnalyticsResultTable, CacheProvenance)> {
            let guard = self.entries.lock().unwrap_or_else(|p| p.into_inner());
            guard
                .iter()
                .find(|(k, _, _)| k == key)
                .map(|(_, table, prov)| (table.clone(), prov.clone()))
        }

        pub fn put(
            &self,
            key: &AnalyticsCacheKey,
            table: &AnalyticsResultTable,
            prov: &CacheProvenance,
        ) {
            let mut guard = self.entries.lock().unwrap_or_else(|p| p.into_inner());
            guard.retain(|(k, _, _)| k != key);
            guard.push_front((key.clone(), table.clone(), prov.clone()));
            guard.truncate(self.cap);
        }

        pub fn len(&self) -> usize {
            self.entries.lock().unwrap_or_else(|p| p.into_inner()).len()
        }
    }

    #[test]
    fn memory_store_is_bounded_and_replaces_by_key() {
        let store = MemoryStore::new(2);
        let table = AnalyticsResultTable {
            rows: vec![json!({"a": 1})],
            equipment: Vec::new(),
            points: Vec::new(),
            skipped: Vec::new(),
            warnings: Vec::new(),
            coverage: None,
            engine: "timescale-sql".into(),
            result_query_version: "v1".into(),
        };
        let prov = CacheProvenance {
            building_id: "site-a".into(),
            query_id: "q".into(),
            query_version: "v1".into(),
            window_start: "open".into(),
            window_end: "open".into(),
            config_hash: "h".into(),
            watermark_order: 1,
            watermark_utc: String::new(),
            generated_at: String::new(),
            engine: "timescale-sql".into(),
            result_query_version: "v1".into(),
            result_contract: "c".into(),
            sql_pack: "p".into(),
            model_revision: "m".into(),
            watermark_source: "timescale".into(),
            watermark_status: "known".into(),
            coverage: String::new(),
        };
        for hash in ["h1", "h2", "h3", "h3"] {
            let key = AnalyticsCacheKey {
                building_id: "site-a".into(),
                query_id: "q".into(),
                query_version: "v1".into(),
                window_start: "open".into(),
                window_end: "open".into(),
                config_hash: hash.into(),
            };
            store.put(&key, &table, &prov);
        }
        assert_eq!(store.len(), 2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn payload_round_trip_keeps_explicit_nulls() {
        let table = AnalyticsResultTable {
            rows: vec![json!({"equipment_id": "AHU_1", "fc1_fault_h": null, "run_hours": 3.5})],
            equipment: vec![json!({"equipment_id": "AHU_1"})],
            points: Vec::new(),
            skipped: vec![json!({"equipment_id": "VAV_1", "reason": "missing roles"})],
            warnings: vec!["thin data".into()],
            coverage: Some(json!({"samples": 4})),
            engine: "timescale-sql".into(),
            result_query_version: "runtime-v1".into(),
        };
        let back = table_from_payload(
            &payload(&table),
            table.engine.clone(),
            table.result_query_version.clone(),
        );
        assert_eq!(back, table);
        assert!(back.rows[0]
            .as_object()
            .is_some_and(|o| o.contains_key("fc1_fault_h")));
    }

    fn test_database_url() -> Option<String> {
        std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    }

    fn key(building: &str, hash: &str) -> AnalyticsCacheKey {
        AnalyticsCacheKey {
            building_id: building.into(),
            query_id: "rcx-preset".into(),
            query_version: "rcx-preset-v1".into(),
            window_start: "open".into(),
            window_end: "open".into(),
            config_hash: hash.into(),
        }
    }

    fn prov(key: &AnalyticsCacheKey, order: u64) -> CacheProvenance {
        CacheProvenance {
            building_id: key.building_id.clone(),
            query_id: key.query_id.clone(),
            query_version: key.query_version.clone(),
            window_start: key.window_start.clone(),
            window_end: key.window_end.clone(),
            config_hash: key.config_hash.clone(),
            watermark_order: order,
            watermark_utc: "2026-06-01T00:00:00Z".into(),
            generated_at: "2026-06-01T00:00:00Z".into(),
            engine: "timescale-sql".into(),
            result_query_version: "rcx-preset-v1".into(),
            result_contract: "analytics-result-contract-v2".into(),
            sql_pack: "analytics=p;fdd=p".into(),
            model_revision: "model-a".into(),
            watermark_source: "timescale".into(),
            watermark_status: "known".into(),
            coverage: "samples=1;series=1".into(),
        }
    }

    /// Runs when `OPENFDD_TEST_DATABASE_URL` is set; otherwise returns early.
    #[tokio::test]
    async fn postgres_store_round_trips_isolates_buildings_and_trims() {
        let Some(url) = test_database_url() else {
            return;
        };
        let tsdb = Arc::new(fdd_tsdb::Tsdb::connect(&url).await.expect("connect"));
        crate::test_ddl::execute_idempotent_ddl(
            tsdb.pool(),
            "CREATE TABLE IF NOT EXISTS analytics_result (
                building_id text NOT NULL,
                query_id text NOT NULL,
                query_version text NOT NULL,
                window_key text NOT NULL,
                config_hash text NOT NULL,
                stale boolean NOT NULL DEFAULT false,
                payload jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (building_id, query_id, query_version, window_key, config_hash)
            )",
        )
        .await;
        for stmt in crate::db_lifecycle::statements(include_str!(
            "../../../../sql/schema/08_analytics_result_cache.sql"
        )) {
            crate::test_ddl::execute_idempotent_ddl(tsdb.pool(), &stmt).await;
        }
        let suffix = uuid::Uuid::new_v4().simple().to_string();
        let site_a = format!("wp2a-a-{suffix}");
        let site_b = format!("wp2a-b-{suffix}");
        let store = ResultStore::Postgres(Arc::clone(&tsdb));
        let table = AnalyticsResultTable {
            rows: vec![json!({"equipment_id": "AHU_1", "fc1_fault_h": null})],
            equipment: Vec::new(),
            points: vec![json!({"x_role": "web_oa_t"})],
            skipped: Vec::new(),
            warnings: vec!["w".into()],
            coverage: Some(json!({"samples": 1})),
            engine: "timescale-sql".into(),
            result_query_version: "rcx-preset-v1".into(),
        };

        let ka = key(&site_a, "h1");
        assert!(store.peek(&ka).await.unwrap().is_none());
        store.write(&ka, &table, &prov(&ka, 1)).await.unwrap();
        let (back, p) = store.read(&ka).await.unwrap().expect("row");
        assert_eq!(back, table);
        assert_eq!(p, prov(&ka, 1));
        assert_eq!(store.peek(&ka).await.unwrap(), Some(prov(&ka, 1)));

        // Same key replaces in place; the other building sees nothing.
        store.write(&ka, &table, &prov(&ka, 2)).await.unwrap();
        assert_eq!(
            store.peek(&ka).await.unwrap().map(|p| p.watermark_order),
            Some(2)
        );
        assert!(store.peek(&key(&site_b, "h1")).await.unwrap().is_none());

        for hash in ["h2", "h3"] {
            let k = key(&site_a, hash);
            store
                .write_capped(&k, &table, &prov(&k, 1), 2)
                .await
                .unwrap();
        }
        let kb = key(&site_b, "h1");
        store
            .write_capped(&kb, &table, &prov(&kb, 1), 2)
            .await
            .unwrap();
        let count = |site: String| {
            let pool = tsdb.pool().clone();
            async move {
                sqlx::query_scalar::<_, i64>(
                    "SELECT count(*) FROM analytics_result WHERE building_id = $1",
                )
                .bind(site)
                .fetch_one(&pool)
                .await
                .unwrap()
            }
        };
        assert_eq!(count(site_a.clone()).await, 2);
        assert_eq!(count(site_b.clone()).await, 1);
        assert!(
            store.peek(&ka).await.unwrap().is_none(),
            "oldest row trimmed"
        );

        sqlx::query("DELETE FROM analytics_result WHERE building_id = ANY($1)")
            .bind(vec![site_a, site_b])
            .execute(tsdb.pool())
            .await
            .unwrap();
    }

    #[test]
    fn row_cap_is_clamped() {
        let _env = crate::test_env_lock::lock_env();
        let prev = std::env::var("OPENFDD_ANALYTICS_CACHE_MAX_ROWS").ok();
        std::env::set_var("OPENFDD_ANALYTICS_CACHE_MAX_ROWS", "999999999");
        assert_eq!(max_rows_per_building(), MAX_ROWS_CEILING);
        std::env::set_var("OPENFDD_ANALYTICS_CACHE_MAX_ROWS", "0");
        assert_eq!(max_rows_per_building(), DEFAULT_MAX_ROWS_PER_BUILDING);
        match prev {
            Some(v) => std::env::set_var("OPENFDD_ANALYTICS_CACHE_MAX_ROWS", v),
            None => std::env::remove_var("OPENFDD_ANALYTICS_CACHE_MAX_ROWS"),
        }
    }
}
