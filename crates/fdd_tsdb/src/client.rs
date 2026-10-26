use std::collections::HashMap;
use std::env;
use std::sync::{Arc, Mutex};

use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Postgres, Row, Transaction};
use thiserror::Error;

use crate::portal::{upsert_portal_point, PortalPointUpsert};
use crate::sample::{SampleRow, UpsertBatch};
use crate::writer::{write_samples, SampleWrite};

#[derive(Debug, Error)]
pub enum TsdbError {
    #[error("OPENFDD_DATABASE_URL is required for Timescale historian")]
    MissingDatabaseUrl,
    #[error("invalid building id")]
    InvalidBuildingId,
    #[error(transparent)]
    Sqlx(#[from] sqlx::Error),
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct SampleUpsertStats {
    pub inserted: u64,
    pub updated: u64,
    /// Already stored with identical value, unit, quality, and haystack id.
    /// A retried window lands here: it is a duplicate, not new data.
    pub unchanged: u64,
}

impl SampleUpsertStats {
    /// Rows the historian holds after the batch, including unchanged duplicates.
    pub fn persisted(self) -> u64 {
        self.inserted
            .saturating_add(self.updated)
            .saturating_add(self.unchanged)
    }
}

#[derive(Clone)]
pub struct Tsdb {
    pool: PgPool,
}

pub fn database_url_from_env() -> Result<String, TsdbError> {
    env::var("OPENFDD_DATABASE_URL").map_err(|_| TsdbError::MissingDatabaseUrl)
}

fn pool_max_connections() -> u32 {
    env::var("OPENFDD_TIMESCALE_POOL")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8)
        .clamp(1, 64)
}

/// Process-wide shared pool (Wave-X C3). Do not open a new pool per HTTP request.
/// A test can clear it: each `tokio::test` has its own runtime, and a pool
/// created on a finished runtime never yields a connection.
static SHARED: Mutex<Option<Arc<Tsdb>>> = Mutex::new(None);

fn shared_slot() -> std::sync::MutexGuard<'static, Option<Arc<Tsdb>>> {
    SHARED.lock().unwrap_or_else(|err| err.into_inner())
}

/// Drop the cached pool so the next caller connects on the current runtime.
pub fn clear_shared_pool() {
    *shared_slot() = None;
}

impl Tsdb {
    pub async fn shared() -> Result<Arc<Self>, TsdbError> {
        if let Some(existing) = shared_slot().clone() {
            return Ok(existing);
        }
        let created = Arc::new(Self::connect(&database_url_from_env()?).await?);
        let mut slot = shared_slot();
        if let Some(existing) = slot.clone() {
            return Ok(existing);
        }
        *slot = Some(Arc::clone(&created));
        Ok(created)
    }

    pub async fn connect_from_env() -> Result<Self, TsdbError> {
        Ok(Self::shared().await?.as_ref().clone())
    }

    pub async fn connect(url: &str) -> Result<Self, TsdbError> {
        let pool = PgPoolOptions::new()
            .max_connections(pool_max_connections())
            .acquire_timeout(std::time::Duration::from_secs(
                env::var("OPENFDD_TIMESCALE_ACQUIRE_SECS")
                    .ok()
                    .and_then(|s| s.parse().ok())
                    .unwrap_or(30),
            ))
            .idle_timeout(Some(std::time::Duration::from_secs(60)))
            .connect(url)
            .await?;
        Ok(Self { pool })
    }

    pub fn from_pool(pool: PgPool) -> Self {
        Self { pool }
    }

    pub fn pool(&self) -> &PgPool {
        &self.pool
    }

    pub async fn ensure_site_building(&self, building_id: &str) -> Result<(), TsdbError> {
        let mut tx = self.pool.begin().await?;
        Self::ensure_site_building_tx(&mut tx, building_id).await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn ensure_site_building_tx(
        tx: &mut Transaction<'_, Postgres>,
        building_id: &str,
    ) -> Result<(), TsdbError> {
        sqlx::query(
            r#"
            INSERT INTO site(site_id, dis, timezone, enabled)
            VALUES ($1, $1, 'UTC', true)
            ON CONFLICT (site_id) DO NOTHING
            "#,
        )
        .bind(building_id)
        .execute(&mut **tx)
        .await?;
        sqlx::query(
            r#"
            INSERT INTO building(building_id, site_id, dis, timezone)
            VALUES ($1, $1, $1, 'UTC')
            ON CONFLICT (building_id) DO NOTHING
            "#,
        )
        .bind(building_id)
        .execute(&mut **tx)
        .await?;
        Ok(())
    }

    pub async fn upsert_equipment(
        &self,
        building_id: &str,
        equipment_id: &str,
        equip_type: Option<&str>,
    ) -> Result<(), TsdbError> {
        let mut tx = self.pool.begin().await?;
        Self::upsert_equipment_tx(&mut tx, building_id, equipment_id, equip_type).await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn upsert_equipment_tx(
        tx: &mut Transaction<'_, Postgres>,
        building_id: &str,
        equipment_id: &str,
        equip_type: Option<&str>,
    ) -> Result<(), TsdbError> {
        sqlx::query(
            r#"
            INSERT INTO equipment(building_id, equipment_id, equip_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (building_id, equipment_id) DO UPDATE
              SET equip_type = COALESCE(EXCLUDED.equip_type, equipment.equip_type)
            "#,
        )
        .bind(building_id)
        .bind(equipment_id)
        .bind(equip_type)
        .execute(&mut **tx)
        .await?;
        Ok(())
    }

    pub async fn upsert_samples(&self, batch: &UpsertBatch) -> Result<u64, TsdbError> {
        let stats = self.upsert_samples_stats(batch).await?;
        Ok(stats.persisted())
    }

    /// Inserted rows are new observations. Updated rows already existed at the
    /// same `(site_id, openfdd_key, ts)` with a different value and were
    /// overwritten in place. Unchanged rows were identical and left alone.
    ///
    /// Rows with a `portal_point_id` resolve their key through `point_map`, so
    /// a re-poll lands on the series the first poll created. Samples are
    /// written by [`crate::writer::write_samples`], the single sample writer.
    pub async fn upsert_samples_stats(
        &self,
        batch: &UpsertBatch,
    ) -> Result<SampleUpsertStats, TsdbError> {
        if batch.rows.is_empty() {
            return Ok(SampleUpsertStats::default());
        }
        let mut tx = self.pool.begin().await?;
        let stats = Self::upsert_samples_tx(&mut tx, batch).await?;
        tx.commit().await?;
        Ok(stats)
    }

    /// [`Self::upsert_samples_stats`] inside a caller-owned transaction, so a
    /// caller can check its own write fence and publish samples atomically.
    pub async fn upsert_samples_tx(
        tx: &mut Transaction<'_, Postgres>,
        batch: &UpsertBatch,
    ) -> Result<SampleUpsertStats, TsdbError> {
        let mut portal_keys: HashMap<(String, String), String> = HashMap::new();
        let mut keys: Vec<String> = Vec::with_capacity(batch.rows.len());
        for row in &batch.rows {
            let portal = match (&row.portal_point_id, &row.equipment_id, &row.role) {
                (Some(pid), Some(equip), Some(role)) if !pid.trim().is_empty() => {
                    Some((pid.trim(), equip, role))
                }
                _ => None,
            };
            let key = match portal {
                Some((pid, equip, role)) => {
                    let cache = (row.site_id.clone(), pid.to_string());
                    match portal_keys.get(&cache) {
                        Some(key) => key.clone(),
                        None => {
                            let key = upsert_portal_point(
                                tx,
                                &PortalPointUpsert {
                                    site_id: &row.site_id,
                                    portal_point_id: pid,
                                    provider_instance_id: row.provider_instance_id.as_deref(),
                                    equipment_id: equip,
                                    role,
                                    unit: row.unit.as_deref(),
                                    candidate_key: &row.openfdd_key,
                                    mark_referenced: false,
                                },
                            )
                            .await?;
                            portal_keys.insert(cache, key.clone());
                            key
                        }
                    }
                }
                None => row.openfdd_key.clone(),
            };
            keys.push(key);
            if portal.is_some() {
                continue;
            }
            if let (Some(equip), Some(role)) = (&row.equipment_id, &row.role) {
                sqlx::query(
                    r#"
                    INSERT INTO role_map(building_id, equipment_id, openfdd_key, role, unit)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (building_id, equipment_id, openfdd_key) DO UPDATE
                      SET role = EXCLUDED.role,
                          unit = COALESCE(EXCLUDED.unit, role_map.unit)
                    "#,
                )
                .bind(&row.site_id)
                .bind(equip)
                .bind(&row.openfdd_key)
                .bind(role)
                .bind(&row.unit)
                .execute(&mut **tx)
                .await?;
                sqlx::query(
                    r#"
                    INSERT INTO point_map(site_id, openfdd_key, haystack_id, role, unit, equipment_id)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (site_id, openfdd_key) DO UPDATE
                      SET haystack_id = EXCLUDED.haystack_id,
                          role = EXCLUDED.role,
                          unit = COALESCE(EXCLUDED.unit, point_map.unit),
                          equipment_id = EXCLUDED.equipment_id
                    "#,
                )
                .bind(&row.site_id)
                .bind(&row.openfdd_key)
                .bind(row.haystack_id.as_deref().unwrap_or(&row.openfdd_key))
                .bind(role)
                .bind(&row.unit)
                .bind(equip)
                .execute(&mut **tx)
                .await?;
            }
        }
        let writes: Vec<SampleWrite<'_>> = batch
            .rows
            .iter()
            .zip(&keys)
            .map(|(row, key)| SampleWrite {
                ts: row.ts,
                site_id: &row.site_id,
                openfdd_key: key,
                haystack_id: row.haystack_id.as_deref(),
                val: row.val,
                unit: row.unit.as_deref(),
                quality: row.quality.as_deref(),
            })
            .collect();
        let stats = write_samples(tx, &writes).await?;
        Ok(stats)
    }

    pub async fn sample_count(&self, site_id: &str) -> Result<i64, TsdbError> {
        let row = sqlx::query("SELECT count(*)::bigint AS n FROM sample WHERE site_id = $1")
            .bind(site_id)
            .fetch_one(&self.pool)
            .await?;
        Ok(row.get::<i64, _>("n"))
    }

    pub async fn max_sample_ts(
        &self,
        site_id: &str,
    ) -> Result<Option<chrono::DateTime<chrono::Utc>>, TsdbError> {
        let row = sqlx::query("SELECT max(ts) AS ts FROM sample WHERE site_id = $1")
            .bind(site_id)
            .fetch_one(&self.pool)
            .await?;
        Ok(row.try_get::<Option<chrono::DateTime<chrono::Utc>>, _>("ts")?)
    }

    /// Global AFDD Soft-OPEN: newest sample across all Timescale sites.
    pub async fn max_sample_ts_global(
        &self,
    ) -> Result<Option<chrono::DateTime<chrono::Utc>>, TsdbError> {
        let row = sqlx::query("SELECT max(ts) AS ts FROM sample")
            .fetch_one(&self.pool)
            .await?;
        Ok(row.try_get::<Option<chrono::DateTime<chrono::Utc>>, _>("ts")?)
    }

    pub async fn rule_registry_count(&self) -> Result<i64, TsdbError> {
        let row = sqlx::query("SELECT count(*)::bigint AS n FROM fdd_rule_registry")
            .fetch_one(&self.pool)
            .await?;
        Ok(row.get::<i64, _>("n"))
    }

    pub async fn health_ping(&self) -> Result<(), TsdbError> {
        sqlx::query("SELECT 1").execute(&self.pool).await?;
        Ok(())
    }

    /// Row count for the whole historian. Used to decide an empty-database seed.
    pub async fn sample_row_count(&self) -> Result<i64, TsdbError> {
        let n: i64 = sqlx::query_scalar("SELECT COUNT(*)::bigint FROM sample")
            .fetch_one(&self.pool)
            .await?;
        Ok(n)
    }

    /// Delete one building's historian rows in FK-safe order. Other buildings stay.
    pub async fn purge_building(&self, building_id: &str) -> Result<u64, TsdbError> {
        let id = building_id.trim();
        if id.is_empty()
            || !id
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
        {
            return Err(TsdbError::InvalidBuildingId);
        }
        let mut tx = self.pool.begin().await?;
        let mut removed = 0u64;
        removed += delete_by_job_site(&mut tx, id).await?;
        // Building-scoped subset of db_lifecycle::RESET_TABLES / purge_historian.RESET_TABLES.
        // The full historian wipe stays on that one-shot token. This deletes one site.
        for (table, column) in [
            ("provider_hourly_gap", "canonical_site"),
            ("provider_hourly_job", "canonical_site"),
            ("provider_hourly_checkpoint", "canonical_site"),
            ("ingest_receipt", "canonical_site"),
            ("ingest_job", "canonical_site"),
            ("sample", "site_id"),
            ("fdd_run", "site_id"),
            ("analytics_result", "building_id"),
            ("point_map", "site_id"),
            ("role_map", "building_id"),
            ("batch_job", "site_id"),
            ("equipment", "building_id"),
            ("building", "building_id"),
            ("site", "site_id"),
        ] {
            removed += delete_where(&mut tx, table, column, id).await?;
        }
        if id == "BUILDING_50" && relation_exists(&mut tx, "seed_meta").await? {
            let res = sqlx::query("DELETE FROM seed_meta WHERE key LIKE 'building50%'")
                .execute(&mut *tx)
                .await?;
            removed += res.rows_affected();
        }
        tx.commit().await?;
        Ok(removed)
    }

    /// Site ids that have equipment or samples. Empty tenant/building rows
    /// stay out of the sidebar picker.
    pub async fn list_site_ids(&self) -> Result<Vec<String>, TsdbError> {
        let rows = sqlx::query(
            "SELECT id FROM (
                SELECT building_id AS id FROM equipment
                UNION
                SELECT DISTINCT site_id AS id FROM sample
             ) sites
             WHERE id IS NOT NULL AND btrim(id) <> ''
             ORDER BY 1",
        )
        .fetch_all(&self.pool)
        .await?;
        Ok(rows
            .into_iter()
            .filter_map(|row| row.try_get::<String, _>("id").ok())
            .collect())
    }

    /// Apply transaction-local statement/lock deadlines for a request-scoped txn.
    pub async fn apply_request_timeouts(
        tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
        statement_ms: i64,
        lock_ms: i64,
    ) -> Result<(), TsdbError> {
        sqlx::query(&format!("SET LOCAL statement_timeout = '{statement_ms}'"))
            .execute(&mut **tx)
            .await?;
        sqlx::query(&format!("SET LOCAL lock_timeout = '{lock_ms}'"))
            .execute(&mut **tx)
            .await?;
        Ok(())
    }
}

impl SampleRow {
    pub fn new(
        ts: chrono::DateTime<chrono::Utc>,
        site_id: impl Into<String>,
        openfdd_key: impl Into<String>,
        val: Option<f64>,
    ) -> Self {
        Self {
            ts,
            site_id: site_id.into(),
            openfdd_key: openfdd_key.into(),
            haystack_id: None,
            val,
            unit: None,
            quality: None,
            equipment_id: None,
            role: None,
            portal_point_id: None,
            provider_instance_id: None,
        }
    }
}

fn ident_ok(name: &str) -> bool {
    let mut chars = name.chars();
    match chars.next() {
        Some(first) if first.is_ascii_alphabetic() || first == '_' => {}
        _ => return false,
    }
    chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '_')
}

async fn relation_exists(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    table: &str,
) -> Result<bool, TsdbError> {
    let reg: Option<String> = sqlx::query_scalar("SELECT to_regclass($1)::text")
        .bind(format!("public.{table}"))
        .fetch_one(&mut **tx)
        .await?;
    Ok(reg.is_some())
}

async fn delete_where(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    table: &str,
    column: &str,
    id: &str,
) -> Result<u64, TsdbError> {
    if !ident_ok(table) || !ident_ok(column) || !relation_exists(tx, table).await? {
        return Ok(0);
    }
    let sql = format!("DELETE FROM {table} WHERE {column} = $1");
    let res = sqlx::query(&sql).bind(id).execute(&mut **tx).await?;
    Ok(res.rows_affected())
}

async fn delete_by_job_site(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    id: &str,
) -> Result<u64, TsdbError> {
    if !relation_exists(tx, "provider_hourly_receipt").await?
        || !relation_exists(tx, "provider_hourly_job").await?
    {
        return Ok(0);
    }
    let res = sqlx::query(
        "DELETE FROM provider_hourly_receipt WHERE job_id IN (\
         SELECT job_id FROM provider_hourly_job WHERE canonical_site = $1)",
    )
    .bind(id)
    .execute(&mut **tx)
    .await?;
    Ok(res.rows_affected())
}
