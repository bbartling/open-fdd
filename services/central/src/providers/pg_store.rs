//! Postgres backing store for hourly jobs. Queries use `SKIP LOCKED` claims.
//! Replica control stays out of this file.

use chrono::{DateTime, Duration, Utc};
use sqlx::Row;

use super::hourly::LogicalWindow;
use super::store::{
    claim_ready_sql, plan_claim_ids, CheckpointKey, CommitPatch, FailPatch, GapDraft, JobRecord,
    JobState, NewJob, ReceiptDraft,
};

pub async fn ensure_schema(pool: &sqlx::PgPool) -> Result<(), String> {
    let sql = include_str!("../../../../sql/schema/04_provider_hourly_jobs.sql");
    for stmt in statements(sql) {
        sqlx::query(&stmt).execute(pool).await.map_err(db_err)?;
    }
    Ok(())
}

fn statements(sql: &str) -> Vec<String> {
    sql.split(';')
        .map(|part| {
            part.lines()
                .filter(|line| !line.trim_start().starts_with("--"))
                .collect::<Vec<_>>()
                .join("\n")
        })
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn db_err(err: sqlx::Error) -> String {
    let code = err
        .as_database_error()
        .and_then(|d| d.code())
        .map(|c| c.to_string())
        .unwrap_or_default();
    tracing::warn!(pg_code = %code, "hourly job store query failed");
    "job_store_error".into()
}

pub async fn checkpoint(
    pool: &sqlx::PgPool,
    key: &CheckpointKey,
) -> Result<Option<DateTime<Utc>>, String> {
    let row = sqlx::query(
        r#"
        SELECT contiguous_end FROM provider_hourly_checkpoint
        WHERE tenant = $1 AND canonical_site = $2 AND provider_instance = $3
          AND device_id = $4 AND model_revision = $5
        "#,
    )
    .bind(&key.tenant)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    Ok(row.and_then(|row| row.try_get("contiguous_end").ok()))
}

pub async fn put_checkpoint(
    pool: &sqlx::PgPool,
    key: &CheckpointKey,
    contiguous_end: DateTime<Utc>,
) -> Result<(), String> {
    sqlx::query(
        r#"
        INSERT INTO provider_hourly_checkpoint (
            tenant, canonical_site, provider_instance, device_id, model_revision, contiguous_end
        ) VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (tenant, canonical_site, provider_instance, device_id, model_revision)
        DO UPDATE SET contiguous_end = EXCLUDED.contiguous_end, updated_at = now()
        "#,
    )
    .bind(&key.tenant)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .bind(contiguous_end)
    .execute(pool)
    .await
    .map_err(db_err)?;
    Ok(())
}

pub async fn insert_job_if_absent(pool: &sqlx::PgPool, job: &NewJob) -> Result<bool, String> {
    let result = sqlx::query(
        r#"
        INSERT INTO provider_hourly_job (
            job_id, tenant, canonical_site, provider_instance, device_id, model_revision,
            window_start, window_end, shard, shard_count, purpose, generation, state,
            not_before, point_ids
        ) VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10, $11, $12, 'queued',
            $13, $14
        )
        ON CONFLICT (job_id) DO NOTHING
        "#,
    )
    .bind(job.job_id())
    .bind(&job.tenant)
    .bind(&job.canonical_site)
    .bind(&job.provider_instance)
    .bind(&job.device_id)
    .bind(&job.model_revision)
    .bind(job.window_start)
    .bind(job.window_end)
    .bind(job.shard)
    .bind(job.shard_count)
    .bind(&job.purpose)
    .bind(job.generation)
    .bind(job.not_before)
    .bind(serde_json::json!(job.point_ids))
    .execute(pool)
    .await
    .map_err(db_err)?;
    Ok(result.rows_affected() == 1)
}

pub async fn hourly_committed(
    pool: &sqlx::PgPool,
    key: &CheckpointKey,
    window: LogicalWindow,
    shard_count: i32,
) -> Result<bool, String> {
    if shard_count <= 0 {
        return Ok(false);
    }
    let row = sqlx::query(
        r#"
        SELECT COUNT(*)::int AS n FROM provider_hourly_job
        WHERE tenant = $1 AND canonical_site = $2 AND provider_instance = $3
          AND device_id = $4 AND model_revision = $5
          AND purpose = 'hourly' AND generation = 0
          AND window_start = $6 AND window_end = $7
          AND state = 'committed' AND shard >= 0 AND shard < $8
        "#,
    )
    .bind(&key.tenant)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .bind(window.start)
    .bind(window.end)
    .bind(shard_count)
    .fetch_one(pool)
    .await
    .map_err(db_err)?;
    let n: i32 = row.try_get("n").map_err(db_err)?;
    Ok(n == shard_count)
}

pub async fn shard_count_for(
    pool: &sqlx::PgPool,
    key: &CheckpointKey,
    window: LogicalWindow,
) -> Result<i32, String> {
    let row = sqlx::query(
        r#"
        SELECT shard_count FROM provider_hourly_job
        WHERE tenant = $1 AND canonical_site = $2 AND provider_instance = $3
          AND device_id = $4 AND model_revision = $5
          AND purpose = 'hourly' AND generation = 0
          AND window_start = $6 AND window_end = $7
        LIMIT 1
        "#,
    )
    .bind(&key.tenant)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .bind(window.start)
    .bind(window.end)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    Ok(row
        .and_then(|row| row.try_get("shard_count").ok())
        .unwrap_or(0))
}

pub async fn claim(
    pool: &sqlx::PgPool,
    canonical_site: &str,
    now: DateTime<Utc>,
    limit: usize,
    owner: &str,
    lease: Duration,
) -> Result<Vec<JobRecord>, String> {
    let mut tx = pool.begin().await.map_err(db_err)?;
    let oldest = sqlx::query(&claim_ready_sql(64, false))
        .bind(canonical_site)
        .bind(now)
        .fetch_all(&mut *tx)
        .await
        .map_err(db_err)?;
    let newest = sqlx::query(&claim_ready_sql(1, true))
        .bind(canonical_site)
        .bind(now)
        .fetch_all(&mut *tx)
        .await
        .map_err(db_err)?;
    let mut ready = Vec::new();
    for row in oldest.into_iter().chain(newest) {
        let id: String = row.try_get("job_id").map_err(db_err)?;
        if ready.iter().any(|job: &JobRecord| job.job_id == id) {
            continue;
        }
        if let Some(job) = load_job(&mut tx, &id).await? {
            ready.push(job);
        }
    }
    ready.sort_by_key(|job| (job.window_start, job.shard, job.purpose.clone()));
    let ids = plan_claim_ids(&ready, limit);
    let expiry = now + lease;
    let mut claimed = Vec::new();
    for id in ids {
        let row = sqlx::query(
            r#"
            UPDATE provider_hourly_job
            SET state = 'leased',
                attempt = attempt + 1,
                lease_owner = $2,
                lease_expiry = $3,
                fencing_token = fencing_token + 1,
                updated_at = $4
            WHERE job_id = $1
            RETURNING job_id
            "#,
        )
        .bind(&id)
        .bind(owner)
        .bind(expiry)
        .bind(now)
        .fetch_optional(&mut *tx)
        .await
        .map_err(db_err)?;
        if row.is_some() {
            if let Some(job) = load_job(&mut tx, &id).await? {
                claimed.push(job);
            }
        }
    }
    tx.commit().await.map_err(db_err)?;
    Ok(claimed)
}

pub async fn commit(
    pool: &sqlx::PgPool,
    job_id: &str,
    token: i64,
    owner: &str,
    patch: &CommitPatch,
) -> Result<bool, String> {
    let mut tx = pool.begin().await.map_err(db_err)?;
    let updated = sqlx::query(
        r#"
        UPDATE provider_hourly_job
        SET state = 'committed',
            fetched_count = $5,
            accepted_count = $6,
            rejected_count = $7,
            overlap_count = $8,
            writer_acknowledged = $9,
            received_at = $4,
            committed_at = $4,
            safe_error_code = NULL,
            receipt_id = $10,
            lease_owner = NULL,
            lease_expiry = NULL,
            updated_at = $4
        WHERE job_id = $1 AND fencing_token = $2 AND lease_owner = $3
          AND state = 'leased' AND lease_expiry > $4
        "#,
    )
    .bind(job_id)
    .bind(token)
    .bind(owner)
    .bind(patch.now)
    .bind(patch.receipt.fetched_count)
    .bind(patch.receipt.accepted_count)
    .bind(patch.receipt.rejected_count)
    .bind(patch.receipt.overlap_count)
    .bind(patch.receipt.writer_acknowledged)
    .bind(&patch.receipt.receipt_id)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    if updated.rows_affected() != 1 {
        tx.rollback().await.map_err(db_err)?;
        return Ok(false);
    }
    insert_receipt(&mut tx, &patch.receipt).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(true)
}

pub async fn fail(
    pool: &sqlx::PgPool,
    job_id: &str,
    token: i64,
    owner: &str,
    patch: &FailPatch,
) -> Result<bool, String> {
    let mut tx = pool.begin().await.map_err(db_err)?;
    let updated = sqlx::query(
        r#"
        UPDATE provider_hourly_job
        SET state = $5,
            not_before = $6,
            safe_error_code = $7,
            received_at = $4,
            lease_owner = NULL,
            lease_expiry = NULL,
            updated_at = $4
        WHERE job_id = $1 AND fencing_token = $2 AND lease_owner = $3
          AND state = 'leased' AND lease_expiry > $4
        "#,
    )
    .bind(job_id)
    .bind(token)
    .bind(owner)
    .bind(patch.now)
    .bind(patch.state.as_str())
    .bind(patch.not_before)
    .bind(&patch.safe_error_code)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    if updated.rows_affected() != 1 {
        tx.rollback().await.map_err(db_err)?;
        return Ok(false);
    }
    if let Some(gap) = &patch.gap {
        insert_gap_tx(&mut tx, gap).await?;
    }
    tx.commit().await.map_err(db_err)?;
    Ok(true)
}

pub async fn insert_gap(pool: &sqlx::PgPool, gap: &GapDraft) -> Result<(), String> {
    let mut tx = pool.begin().await.map_err(db_err)?;
    insert_gap_tx(&mut tx, gap).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(())
}

pub async fn gap_count(pool: &sqlx::PgPool, canonical_site: &str) -> Result<u32, String> {
    let row = sqlx::query(
        r#"SELECT COUNT(*)::int AS n FROM provider_hourly_gap WHERE canonical_site = $1"#,
    )
    .bind(canonical_site)
    .fetch_one(pool)
    .await
    .map_err(db_err)?;
    let n: i32 = row.try_get("n").map_err(db_err)?;
    Ok(u32::try_from(n.max(0)).unwrap_or(0))
}

pub async fn cancel_stale(
    pool: &sqlx::PgPool,
    canonical_site: &str,
    provider_instance: &str,
    active: &[(String, String)],
) -> Result<u32, String> {
    let rows = sqlx::query(
        r#"
        SELECT job_id, device_id, model_revision FROM provider_hourly_job
        WHERE canonical_site = $1 AND provider_instance = $2
          AND state IN ('queued', 'retry_wait', 'partial', 'leased')
        "#,
    )
    .bind(canonical_site)
    .bind(provider_instance)
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    let mut n = 0u32;
    for row in rows {
        let device: String = row.try_get("device_id").map_err(db_err)?;
        let revision: String = row.try_get("model_revision").map_err(db_err)?;
        if active.iter().any(|(d, r)| d == &device && r == &revision) {
            continue;
        }
        let job_id: String = row.try_get("job_id").map_err(db_err)?;
        sqlx::query(
            r#"
            UPDATE provider_hourly_job
            SET state = 'cancelled', lease_owner = NULL, lease_expiry = NULL,
                safe_error_code = 'model_revision_changed', updated_at = now()
            WHERE job_id = $1 AND state IN ('queued', 'retry_wait', 'partial', 'leased')
            "#,
        )
        .bind(&job_id)
        .execute(pool)
        .await
        .map_err(db_err)?;
        n = n.saturating_add(1);
    }
    Ok(n)
}

#[cfg(test)]
pub async fn list_jobs(
    pool: &sqlx::PgPool,
    canonical_site: &str,
) -> Result<Vec<JobRecord>, String> {
    let rows = sqlx::query(
        r#"
        SELECT job_id FROM provider_hourly_job
        WHERE canonical_site = $1
        ORDER BY window_start, shard, purpose, generation
        "#,
    )
    .bind(canonical_site)
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    let mut jobs = Vec::new();
    for row in rows {
        let id: String = row.try_get("job_id").map_err(db_err)?;
        if let Some(job) = load_job_pool(pool, &id).await? {
            jobs.push(job);
        }
    }
    Ok(jobs)
}

async fn insert_receipt(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    receipt: &ReceiptDraft,
) -> Result<(), String> {
    sqlx::query(
        r#"
        INSERT INTO provider_hourly_receipt (
            receipt_id, job_id, outcome, fetched_count, accepted_count, rejected_count,
            overlap_count, writer_acknowledged, safe_code
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (receipt_id) DO NOTHING
        "#,
    )
    .bind(&receipt.receipt_id)
    .bind(&receipt.job_id)
    .bind(&receipt.outcome)
    .bind(receipt.fetched_count)
    .bind(receipt.accepted_count)
    .bind(receipt.rejected_count)
    .bind(receipt.overlap_count)
    .bind(receipt.writer_acknowledged)
    .bind(&receipt.safe_code)
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    Ok(())
}

async fn insert_gap_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    gap: &GapDraft,
) -> Result<(), String> {
    let gap_id = {
        use sha2::{Digest, Sha256};
        let raw = format!(
            "{}|{}|{}|{}|{}|{}|{}",
            gap.tenant,
            gap.canonical_site,
            gap.provider_instance,
            gap.device_id,
            gap.model_revision,
            gap.window_start.timestamp(),
            gap.reason
        );
        let mut hasher = Sha256::new();
        hasher.update(raw.as_bytes());
        hex::encode(hasher.finalize())
    };
    sqlx::query(
        r#"
        INSERT INTO provider_hourly_gap (
            gap_id, tenant, canonical_site, provider_instance, device_id, model_revision,
            window_start, window_end, reason, recoverability
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (gap_id) DO NOTHING
        "#,
    )
    .bind(gap_id)
    .bind(&gap.tenant)
    .bind(&gap.canonical_site)
    .bind(&gap.provider_instance)
    .bind(&gap.device_id)
    .bind(&gap.model_revision)
    .bind(gap.window_start)
    .bind(gap.window_end)
    .bind(&gap.reason)
    .bind(&gap.recoverability)
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    Ok(())
}

async fn load_job(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    job_id: &str,
) -> Result<Option<JobRecord>, String> {
    let row = sqlx::query(JOB_SQL)
        .bind(job_id)
        .fetch_optional(&mut **tx)
        .await
        .map_err(db_err)?;
    row.map(|row| row_to_job(&row)).transpose()
}

#[cfg(test)]
async fn load_job_pool(pool: &sqlx::PgPool, job_id: &str) -> Result<Option<JobRecord>, String> {
    let row = sqlx::query(JOB_SQL)
        .bind(job_id)
        .fetch_optional(pool)
        .await
        .map_err(db_err)?;
    row.map(|row| row_to_job(&row)).transpose()
}

const JOB_SQL: &str = r#"
SELECT job_id, tenant, canonical_site, provider_instance, device_id, model_revision,
       window_start, window_end, shard, shard_count, purpose, generation, state, attempt,
       not_before, lease_owner, lease_expiry, fencing_token, point_ids,
       fetched_count, accepted_count, rejected_count, overlap_count, writer_acknowledged,
       received_at, committed_at, safe_error_code, receipt_id
FROM provider_hourly_job WHERE job_id = $1
"#;

fn row_to_job(row: &sqlx::postgres::PgRow) -> Result<JobRecord, String> {
    let state_raw: String = row.try_get("state").map_err(db_err)?;
    let state = JobState::parse(&state_raw).ok_or_else(|| "job_store_error".to_string())?;
    let points: serde_json::Value = row.try_get("point_ids").map_err(db_err)?;
    let point_ids = points
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    Ok(JobRecord {
        job_id: row.try_get("job_id").map_err(db_err)?,
        tenant: row.try_get("tenant").map_err(db_err)?,
        canonical_site: row.try_get("canonical_site").map_err(db_err)?,
        provider_instance: row.try_get("provider_instance").map_err(db_err)?,
        device_id: row.try_get("device_id").map_err(db_err)?,
        model_revision: row.try_get("model_revision").map_err(db_err)?,
        window_start: row.try_get("window_start").map_err(db_err)?,
        window_end: row.try_get("window_end").map_err(db_err)?,
        shard: row.try_get("shard").map_err(db_err)?,
        shard_count: row.try_get("shard_count").map_err(db_err)?,
        purpose: row.try_get("purpose").map_err(db_err)?,
        generation: row.try_get("generation").map_err(db_err)?,
        state,
        attempt: row.try_get("attempt").map_err(db_err)?,
        not_before: row.try_get("not_before").map_err(db_err)?,
        lease_owner: row.try_get("lease_owner").map_err(db_err)?,
        lease_expiry: row.try_get("lease_expiry").map_err(db_err)?,
        fencing_token: row.try_get("fencing_token").map_err(db_err)?,
        point_ids,
        fetched_count: row.try_get("fetched_count").map_err(db_err)?,
        accepted_count: row.try_get("accepted_count").map_err(db_err)?,
        rejected_count: row.try_get("rejected_count").map_err(db_err)?,
        overlap_count: row.try_get("overlap_count").map_err(db_err)?,
        writer_acknowledged: row.try_get("writer_acknowledged").map_err(db_err)?,
        received_at: row.try_get("received_at").map_err(db_err)?,
        committed_at: row.try_get("committed_at").map_err(db_err)?,
        safe_error_code: row.try_get("safe_error_code").map_err(db_err)?,
        receipt_id: row.try_get("receipt_id").map_err(db_err)?,
    })
}
