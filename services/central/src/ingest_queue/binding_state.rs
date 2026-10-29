//! Per-device ingest binding metadata (#1423): provider data start and creation time.

use chrono::{DateTime, Utc};
use sqlx::PgPool;

use super::model::{JobView, QueueError};

fn sample_table_missing(err: &sqlx::Error) -> bool {
    matches!(
        err,
        sqlx::Error::Database(db) if db.code().as_deref() == Some("42P01")
    )
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct DeviceBindingKey {
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
}

impl DeviceBindingKey {
    pub fn from_job(job: &JobView) -> Self {
        Self {
            tenant_id: job.tenant_id.clone(),
            canonical_site: job.canonical_site.clone(),
            provider_instance_id: job.provider_instance_id.clone(),
            device_id: job.device_id.clone(),
            model_revision: job.model_revision.clone(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeviceBindingState {
    pub binding_created_at: DateTime<Utc>,
    pub provider_data_start: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy)]
pub struct EnsureBindingInput<'a> {
    pub key: &'a DeviceBindingKey,
    pub planning_range_start: DateTime<Utc>,
    pub now: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy)]
pub struct LearnProviderDataStartInput<'a> {
    pub key: &'a DeviceBindingKey,
    pub candidate: DateTime<Utc>,
    pub now: DateTime<Utc>,
}

pub async fn ensure_binding_row(
    pool: &PgPool,
    input: EnsureBindingInput<'_>,
) -> Result<DeviceBindingState, QueueError> {
    let binding_created_at = if input.planning_range_start < input.now {
        input.planning_range_start
    } else {
        input.now
    };
    let row = sqlx::query_as::<_, (DateTime<Utc>, Option<DateTime<Utc>>)>(
        "INSERT INTO ingest_device_binding (
            tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
            binding_created_at, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $6)
         ON CONFLICT (tenant_id, canonical_site, provider_instance_id, device_id, model_revision)
         DO UPDATE SET updated_at = ingest_device_binding.updated_at
         RETURNING binding_created_at, provider_data_start",
    )
    .bind(&input.key.tenant_id)
    .bind(&input.key.canonical_site)
    .bind(&input.key.provider_instance_id)
    .bind(&input.key.device_id)
    .bind(&input.key.model_revision)
    .bind(binding_created_at)
    .fetch_one(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(DeviceBindingState {
        binding_created_at: row.0,
        provider_data_start: row.1,
    })
}

pub async fn learn_provider_data_start(
    pool: &PgPool,
    input: LearnProviderDataStartInput<'_>,
) -> Result<Option<DateTime<Utc>>, QueueError> {
    let row = sqlx::query_scalar::<_, Option<DateTime<Utc>>>(
        "UPDATE ingest_device_binding
         SET provider_data_start = CASE
             WHEN provider_data_start IS NULL OR $6 < provider_data_start THEN $6
             ELSE provider_data_start
           END,
           updated_at = $7
         WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
           AND device_id = $4 AND model_revision = $5
         RETURNING provider_data_start",
    )
    .bind(&input.key.tenant_id)
    .bind(&input.key.canonical_site)
    .bind(&input.key.provider_instance_id)
    .bind(&input.key.device_id)
    .bind(&input.key.model_revision)
    .bind(input.candidate)
    .bind(input.now)
    .fetch_optional(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(row.flatten())
}

pub async fn load_binding_state(
    pool: &PgPool,
    key: &DeviceBindingKey,
) -> Result<Option<DeviceBindingState>, QueueError> {
    let row = sqlx::query_as::<_, (DateTime<Utc>, Option<DateTime<Utc>>)>(
        "SELECT binding_created_at, provider_data_start
         FROM ingest_device_binding
         WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
           AND device_id = $4 AND model_revision = $5",
    )
    .bind(&key.tenant_id)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance_id)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .fetch_optional(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(row.map(|(created, start)| DeviceBindingState {
        binding_created_at: created,
        provider_data_start: start,
    }))
}

pub async fn stored_hour_starts_for_device(
    pool: &PgPool,
    site_id: &str,
    openfdd_keys: &[String],
    range_start: DateTime<Utc>,
    range_end: DateTime<Utc>,
) -> Result<Vec<DateTime<Utc>>, QueueError> {
    if openfdd_keys.is_empty() {
        return Ok(Vec::new());
    }
    let rows = match sqlx::query_scalar::<_, DateTime<Utc>>(
        "SELECT DISTINCT date_trunc('hour', ts) AS hour_start
         FROM sample
         WHERE site_id = $1 AND openfdd_key = ANY($2)
           AND ts >= $3 AND ts < $4
         ORDER BY hour_start",
    )
    .bind(site_id)
    .bind(openfdd_keys)
    .bind(range_start)
    .bind(range_end)
    .fetch_all(pool)
    .await
    {
        Ok(rows) => rows,
        Err(err) if sample_table_missing(&err) => Vec::new(),
        Err(err) => {
            return Err(QueueError::Db(super::model::redact_db_text(
                &err.to_string(),
            )));
        }
    };
    Ok(rows)
}

pub async fn last_stored_ts_for_device(
    pool: &PgPool,
    site_id: &str,
    openfdd_keys: &[String],
) -> Result<Option<DateTime<Utc>>, QueueError> {
    if openfdd_keys.is_empty() {
        return Ok(None);
    }
    let row = match sqlx::query_scalar::<_, Option<DateTime<Utc>>>(
        "SELECT max(ts) FROM sample WHERE site_id = $1 AND openfdd_key = ANY($2)",
    )
    .bind(site_id)
    .bind(openfdd_keys)
    .fetch_one(pool)
    .await
    {
        Ok(row) => row,
        Err(err) if sample_table_missing(&err) => None,
        Err(err) => {
            return Err(QueueError::Db(super::model::redact_db_text(
                &err.to_string(),
            )));
        }
    };
    Ok(row)
}
