//! Per-device ingest binding metadata (#1423): provider data start and creation time.

use chrono::{DateTime, Utc};
use sqlx::PgPool;

use super::model::QueueError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeviceBindingState {
    pub binding_created_at: DateTime<Utc>,
    pub provider_data_start: Option<DateTime<Utc>>,
}

pub async fn ensure_binding_row(
    pool: &PgPool,
    tenant_id: &str,
    site_id: &str,
    provider_id: &str,
    device_id: &str,
    model_revision: &str,
    now: DateTime<Utc>,
) -> Result<DeviceBindingState, QueueError> {
    let row = sqlx::query_as::<_, (DateTime<Utc>, Option<DateTime<Utc>>)>(
        "INSERT INTO ingest_device_binding (
            tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
            binding_created_at, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $6)
         ON CONFLICT (tenant_id, canonical_site, provider_instance_id, device_id, model_revision)
         DO UPDATE SET updated_at = ingest_device_binding.updated_at
         RETURNING binding_created_at, provider_data_start",
    )
    .bind(tenant_id)
    .bind(site_id)
    .bind(provider_id)
    .bind(device_id)
    .bind(model_revision)
    .bind(now)
    .fetch_one(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(DeviceBindingState {
        binding_created_at: row.0,
        provider_data_start: row.1,
    })
}

#[expect(
    clippy::too_many_arguments,
    reason = "binding update keys match the ingest_device_binding primary key columns"
)]
pub async fn learn_provider_data_start(
    pool: &PgPool,
    tenant_id: &str,
    site_id: &str,
    provider_id: &str,
    device_id: &str,
    model_revision: &str,
    candidate: DateTime<Utc>,
    now: DateTime<Utc>,
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
    .bind(tenant_id)
    .bind(site_id)
    .bind(provider_id)
    .bind(device_id)
    .bind(model_revision)
    .bind(candidate)
    .bind(now)
    .fetch_optional(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(row.flatten())
}

pub async fn load_binding_state(
    pool: &PgPool,
    tenant_id: &str,
    site_id: &str,
    provider_id: &str,
    device_id: &str,
    model_revision: &str,
) -> Result<Option<DeviceBindingState>, QueueError> {
    let row = sqlx::query_as::<_, (DateTime<Utc>, Option<DateTime<Utc>>)>(
        "SELECT binding_created_at, provider_data_start
         FROM ingest_device_binding
         WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
           AND device_id = $4 AND model_revision = $5",
    )
    .bind(tenant_id)
    .bind(site_id)
    .bind(provider_id)
    .bind(device_id)
    .bind(model_revision)
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
    let rows = sqlx::query_scalar::<_, DateTime<Utc>>(
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
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
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
    let row = sqlx::query_scalar::<_, Option<DateTime<Utc>>>(
        "SELECT max(ts) FROM sample WHERE site_id = $1 AND openfdd_key = ANY($2)",
    )
    .bind(site_id)
    .bind(openfdd_keys)
    .fetch_one(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(row)
}
