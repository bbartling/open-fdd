//! Postgres queue. Statements use bound parameters and `SKIP LOCKED` claims.
//!
//! Fencing rules match [`super::memory`]: a finish must present the current
//! owner, token, and an unexpired lease. Schema DDL is applied on connect.

use chrono::{DateTime, Utc};
use sqlx::postgres::PgRow;
use sqlx::{PgPool, Row};
use uuid::Uuid;

use super::model::*;

pub const SCHEMA_SQL: &str = include_str!("../../../../sql/schema/04_ingest_queue.sql");

pub const CLAIM_SELECT_SQL: &str = "\
SELECT j.job_id
FROM ingest_job j
WHERE (
    (j.state IN ('queued', 'retry_wait') AND j.not_before <= $1)
    OR (j.state = 'leased' AND j.lease_expiry IS NOT NULL AND j.lease_expiry <= $1)
)
AND (
    SELECT COUNT(*)::int FROM ingest_job l
    WHERE l.provider_instance_id = j.provider_instance_id
      AND l.state = 'leased'
      AND l.lease_expiry > $1
) < COALESCE(
    (
        SELECT b.cap_override
        FROM ingest_portal_budget b
        WHERE b.provider_instance_id = j.provider_instance_id
          AND b.cap_override IS NOT NULL
          AND (b.paused_until IS NULL OR b.paused_until <= $1)
    ),
    $2
)
AND NOT EXISTS (
    SELECT 1 FROM ingest_portal_budget b
    WHERE b.provider_instance_id = j.provider_instance_id
      AND (
        (b.paused_until IS NOT NULL AND b.paused_until > $1)
        OR (b.tokens_remaining <= 0 AND b.window_start + interval '60 seconds' > $1)
      )
)
ORDER BY (
    SELECT COUNT(*) FROM ingest_job l2
    WHERE l2.provider_instance_id = j.provider_instance_id
      AND l2.state = 'leased'
      AND l2.lease_expiry > $1
), j.not_before, j.logical_window_start, j.job_id
FOR UPDATE OF j SKIP LOCKED
LIMIT 1";

pub fn statements(ddl: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for line in ddl.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("--") {
            continue;
        }
        current.push_str(line);
        current.push('\n');
        if trimmed.ends_with(';') {
            let stmt = current.trim().trim_end_matches(';').trim().to_string();
            if !stmt.is_empty() {
                out.push(stmt);
            }
            current.clear();
        }
    }
    out
}

pub async fn apply_schema(pool: &PgPool) -> Result<(), QueueError> {
    for stmt in statements(SCHEMA_SQL) {
        sqlx::query(&stmt).execute(pool).await.map_err(db_err)?;
    }
    Ok(())
}

pub async fn enqueue(pool: &PgPool, job: &NewJob) -> Result<EnqueueOutcome, QueueError> {
    let job_id = Uuid::new_v4().to_string();
    let inserted: Option<String> = sqlx::query_scalar(
        "INSERT INTO ingest_job (
            job_id, tenant_id, canonical_site, provider_instance_id, device_id,
            model_revision, logical_window_start, logical_window_end, shard,
            state, attempt, not_before, fencing_token, estimated_cost, requested_points_digest
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,'queued',0,$10,0,$11,$12
        )
        ON CONFLICT ON CONSTRAINT ingest_job_logical_key DO NOTHING
        RETURNING job_id",
    )
    .bind(&job_id)
    .bind(&job.tenant_id)
    .bind(&job.canonical_site)
    .bind(&job.provider_instance_id)
    .bind(&job.device_id)
    .bind(&job.model_revision)
    .bind(job.logical_window_start)
    .bind(job.logical_window_end)
    .bind(&job.shard)
    .bind(job.not_before)
    .bind(i32::try_from(job.estimated_cost.max(1)).unwrap_or(1))
    .bind(&job.requested_points_digest)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    let created = inserted.is_some();
    let id = match inserted {
        Some(id) => id,
        None => sqlx::query_scalar(
            "SELECT job_id FROM ingest_job
             WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
               AND device_id = $4 AND model_revision = $5
               AND logical_window_start = $6 AND logical_window_end = $7 AND shard = $8",
        )
        .bind(&job.tenant_id)
        .bind(&job.canonical_site)
        .bind(&job.provider_instance_id)
        .bind(&job.device_id)
        .bind(&job.model_revision)
        .bind(job.logical_window_start)
        .bind(job.logical_window_end)
        .bind(&job.shard)
        .fetch_one(pool)
        .await
        .map_err(db_err)?,
    };
    let view = load_job(pool, &id).await?;
    if created {
        Ok(EnqueueOutcome::Created(view))
    } else {
        Ok(EnqueueOutcome::Existing(view))
    }
}

pub async fn try_scheduler(
    pool: &PgPool,
    owner: &str,
    now: DateTime<Utc>,
    ttl: chrono::Duration,
) -> Result<Option<SchedulerGrant>, QueueError> {
    let expires = now + ttl;
    let row = sqlx::query(
        "INSERT INTO ingest_scheduler_lease (lease_name, owner, fencing_token, expires_at)
         VALUES ('scheduler', $1, 1, $2)
         ON CONFLICT (lease_name) DO UPDATE SET
           owner = EXCLUDED.owner,
           fencing_token = CASE
             WHEN ingest_scheduler_lease.owner = EXCLUDED.owner
              AND ingest_scheduler_lease.expires_at > $3
             THEN ingest_scheduler_lease.fencing_token
             ELSE ingest_scheduler_lease.fencing_token + 1
           END,
           expires_at = EXCLUDED.expires_at
         WHERE ingest_scheduler_lease.owner = EXCLUDED.owner
            OR ingest_scheduler_lease.expires_at <= $3
         RETURNING owner, fencing_token, expires_at",
    )
    .bind(owner)
    .bind(expires)
    .bind(now)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    match row {
        Some(row) => Ok(Some(SchedulerGrant {
            owner: row.try_get("owner").map_err(db_err)?,
            fencing_token: i64_to_u64(row.try_get("fencing_token").map_err(db_err)?),
            expires_at: row.try_get("expires_at").map_err(db_err)?,
        })),
        None => Ok(None),
    }
}

pub async fn renew_scheduler(
    pool: &PgPool,
    owner: &str,
    token: u64,
    now: DateTime<Utc>,
    ttl: chrono::Duration,
) -> Result<bool, QueueError> {
    let expires = now + ttl;
    let updated = sqlx::query(
        "UPDATE ingest_scheduler_lease
         SET expires_at = $4
         WHERE lease_name = 'scheduler'
           AND owner = $1
           AND fencing_token = $2
           AND expires_at > $3",
    )
    .bind(owner)
    .bind(i64::try_from(token).unwrap_or(i64::MAX))
    .bind(now)
    .bind(expires)
    .execute(pool)
    .await
    .map_err(db_err)?;
    Ok(updated.rows_affected() > 0)
}

pub async fn note_throttle(
    pool: &PgPool,
    provider_instance_id: &str,
    now: DateTime<Utc>,
    retry_after: chrono::Duration,
    budget: BudgetDefaults,
) -> Result<(), QueueError> {
    let paused_until = now + retry_after;
    let max_in_flight = i32::try_from(budget.max_in_flight.max(1)).unwrap_or(1);
    let max_per_minute = i32::try_from(budget.max_per_minute.max(1)).unwrap_or(1);
    sqlx::query(
        "INSERT INTO ingest_portal_budget (
            provider_instance_id, max_in_flight, max_per_minute, tokens_remaining,
            window_start, paused_until, cap_override
        ) VALUES ($1, $2, $3, $3, $4, $5, GREATEST($2 / 2, 1))
        ON CONFLICT (provider_instance_id) DO UPDATE SET
          paused_until = EXCLUDED.paused_until,
          cap_override = GREATEST(
            COALESCE(ingest_portal_budget.cap_override, ingest_portal_budget.max_in_flight) / 2,
            1
          )",
    )
    .bind(provider_instance_id)
    .bind(max_in_flight)
    .bind(max_per_minute)
    .bind(now)
    .bind(paused_until)
    .execute(pool)
    .await
    .map_err(db_err)?;
    Ok(())
}

pub async fn claim(
    pool: &PgPool,
    req: &ClaimRequest,
    budget: BudgetDefaults,
) -> Result<Vec<JobView>, QueueError> {
    let mut tx = pool.begin().await.map_err(db_err)?;
    let mut out = Vec::new();
    for _ in 0..req.limit.min(32) {
        let row = sqlx::query(CLAIM_SELECT_SQL)
            .bind(req.now)
            .bind(i32::try_from(budget.max_in_flight.max(1)).unwrap_or(1))
            .fetch_optional(&mut *tx)
            .await
            .map_err(db_err)?;
        let Some(row) = row else { break };
        let job_id: String = row.try_get("job_id").map_err(db_err)?;
        let portal: String =
            sqlx::query_scalar("SELECT provider_instance_id FROM ingest_job WHERE job_id = $1")
                .bind(&job_id)
                .fetch_one(&mut *tx)
                .await
                .map_err(db_err)?;
        let expiry = req.now + req.lease_for;
        let updated = sqlx::query(&format!(
            "UPDATE ingest_job SET
                state = 'leased', lease_owner = $2, lease_expiry = $3,
                fencing_token = fencing_token + 1, attempt = attempt + 1,
                safe_error_code = NULL, updated_at = $4
             WHERE job_id = $1
             RETURNING {JOB_COLUMNS}"
        ))
        .bind(&job_id)
        .bind(&req.owner)
        .bind(expiry)
        .bind(req.now)
        .fetch_one(&mut *tx)
        .await
        .map_err(db_err)?;
        touch_budget(&mut tx, &portal, req.now, budget).await?;
        out.push(job_from_row(&updated)?);
    }
    tx.commit().await.map_err(db_err)?;
    Ok(out)
}

pub async fn finish(pool: &PgPool, req: &FinishRequest) -> Result<Option<ReceiptView>, QueueError> {
    let job_id = req.job_id.to_string();
    let exists: Option<String> =
        sqlx::query_scalar("SELECT job_id FROM ingest_job WHERE job_id = $1")
            .bind(&job_id)
            .fetch_optional(pool)
            .await
            .map_err(db_err)?;
    if exists.is_none() {
        return Err(QueueError::NotFound);
    }
    let (state, code, counts) = match &req.outcome {
        FinishOutcome::Committed { counts } => ("committed", None, *counts),
        FinishOutcome::Partial { counts, code } => ("partial", Some(code.clone()), *counts),
        FinishOutcome::Retry { code, not_before } => {
            let updated = sqlx::query(
                "UPDATE ingest_job SET state = 'retry_wait', safe_error_code = $5,
                    not_before = $6, lease_owner = NULL, lease_expiry = NULL, updated_at = $4
                 WHERE job_id = $1 AND lease_owner = $2 AND fencing_token = $3
                   AND state = 'leased' AND lease_expiry > $4",
            )
            .bind(&job_id)
            .bind(&req.owner)
            .bind(i64::try_from(req.fencing_token).unwrap_or(i64::MAX))
            .bind(req.now)
            .bind(code)
            .bind(not_before)
            .execute(pool)
            .await
            .map_err(db_err)?;
            if updated.rows_affected() == 0 {
                return Err(QueueError::StaleFence);
            }
            return Ok(None);
        }
        FinishOutcome::Permanent { code } => {
            let updated = sqlx::query(
                "UPDATE ingest_job SET state = 'permanent_failure', safe_error_code = $5,
                    lease_owner = NULL, lease_expiry = NULL, updated_at = $4
                 WHERE job_id = $1 AND lease_owner = $2 AND fencing_token = $3
                   AND state = 'leased' AND lease_expiry > $4",
            )
            .bind(&job_id)
            .bind(&req.owner)
            .bind(i64::try_from(req.fencing_token).unwrap_or(i64::MAX))
            .bind(req.now)
            .bind(code)
            .execute(pool)
            .await
            .map_err(db_err)?;
            if updated.rows_affected() == 0 {
                return Err(QueueError::StaleFence);
            }
            return Ok(None);
        }
    };
    let receipt_id = Uuid::new_v4().to_string();
    let mut tx = pool.begin().await.map_err(db_err)?;
    let updated = sqlx::query(
        "UPDATE ingest_job SET state = $5, safe_error_code = $6, receipt_id = $7,
            fetched_count = $8, accepted_count = $9, rejected_count = $10,
            inserted_count = $11, updated_count = $12, unchanged_count = $13,
            lease_owner = NULL, lease_expiry = NULL, updated_at = $4
         WHERE job_id = $1 AND lease_owner = $2 AND fencing_token = $3
           AND state = 'leased' AND lease_expiry > $4",
    )
    .bind(&job_id)
    .bind(&req.owner)
    .bind(i64::try_from(req.fencing_token).unwrap_or(i64::MAX))
    .bind(req.now)
    .bind(state)
    .bind(&code)
    .bind(&receipt_id)
    .bind(i32_count(counts.fetched))
    .bind(i32_count(counts.accepted))
    .bind(i32_count(counts.rejected))
    .bind(i32_count(counts.inserted))
    .bind(i32_count(counts.updated))
    .bind(i32_count(counts.unchanged))
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    if updated.rows_affected() == 0 {
        return Err(QueueError::StaleFence);
    }
    let job = load_job_tx(&mut tx, &job_id).await?;
    sqlx::query(
        "INSERT INTO ingest_receipt (
            receipt_id, job_id, tenant_id, canonical_site, fencing_token, committed_at, counts, safe_error_code
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
    )
    .bind(&receipt_id)
    .bind(&job_id)
    .bind(&job.tenant_id)
    .bind(&job.canonical_site)
    .bind(i64::try_from(req.fencing_token).unwrap_or(i64::MAX))
    .bind(req.now)
    .bind(serde_json::json!(counts))
    .bind(&code)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    tx.commit().await.map_err(db_err)?;
    Ok(Some(ReceiptView {
        receipt_id: parse_uuid(&receipt_id)?,
        job_id: req.job_id,
        tenant_id: job.tenant_id,
        canonical_site: job.canonical_site,
        fencing_token: req.fencing_token,
        committed_at: req.now,
        counts,
        safe_error_code: code,
    }))
}

pub async fn list_jobs(pool: &PgPool, filter: &ListFilter) -> Result<Vec<JobView>, QueueError> {
    let rows = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job
         WHERE ($1::text[] IS NULL OR canonical_site = ANY($1))
           AND ($2::text IS NULL OR state = $2)
         ORDER BY logical_window_start DESC
         LIMIT $3"
    ))
    .bind(filter.sites.clone())
    .bind(filter.state.clone())
    .bind(i64::from(filter.limit.min(MAX_LIST)))
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    rows.iter().map(job_from_row).collect()
}

pub async fn get_job(pool: &PgPool, job_id: Uuid) -> Result<Option<JobView>, QueueError> {
    match sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job WHERE job_id = $1"
    ))
    .bind(job_id.to_string())
    .fetch_optional(pool)
    .await
    .map_err(db_err)?
    {
        Some(row) => Ok(Some(job_from_row(&row)?)),
        None => Ok(None),
    }
}

pub async fn retry_job(
    pool: &PgPool,
    job_id: Uuid,
    now: DateTime<Utc>,
    actor: &str,
    idempotency_key: &str,
) -> Result<JobView, QueueError> {
    if let Some(existing) = idempotent_jobs(pool, idempotency_key, "retry").await? {
        if let Some(id) = existing.first() {
            if let Some(job) = get_job(pool, *id).await? {
                return Ok(job);
            }
        }
    }
    let Some(job) = get_job(pool, job_id).await? else {
        return Err(QueueError::NotFound);
    };
    if !operator_retry_allowed(&job.state, job.safe_error_code.as_deref()) {
        return Err(QueueError::Invalid(
            "job is not eligible for operator retry".into(),
        ));
    }
    let updated = sqlx::query(
        "UPDATE ingest_job SET state = 'queued', not_before = $2, lease_owner = NULL,
            lease_expiry = NULL, safe_error_code = NULL, updated_at = $2
         WHERE job_id = $1 AND state IN ('partial', 'permanent_failure', 'retry_wait', 'cancelled')",
    )
    .bind(job_id.to_string())
    .bind(now)
    .execute(pool)
    .await
    .map_err(db_err)?;
    if updated.rows_affected() == 0 {
        return Err(QueueError::Invalid(
            "job is not eligible for operator retry".into(),
        ));
    }
    save_idempotency(
        pool,
        idempotency_key,
        actor,
        "retry",
        &[job_id],
        Some(job_id),
    )
    .await?;
    get_job(pool, job_id).await?.ok_or(QueueError::NotFound)
}

pub async fn remember_backfill(
    pool: &PgPool,
    actor: &str,
    idempotency_key: &str,
    job_ids: &[Uuid],
) -> Result<(), QueueError> {
    save_idempotency(pool, idempotency_key, actor, "backfill", job_ids, None).await
}

pub async fn idempotent_jobs(
    pool: &PgPool,
    key: &str,
    action: &str,
) -> Result<Option<Vec<Uuid>>, QueueError> {
    let raw: Option<serde_json::Value> = sqlx::query_scalar(
        "SELECT job_ids FROM ingest_idempotency WHERE idempotency_key = $1 AND action = $2",
    )
    .bind(key)
    .bind(action)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    let Some(raw) = raw else {
        return Ok(None);
    };
    let ids = raw
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|value| value.as_str())
        .map(parse_uuid)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Some(ids))
}

async fn save_idempotency(
    pool: &PgPool,
    key: &str,
    actor: &str,
    action: &str,
    job_ids: &[Uuid],
    job_id: Option<Uuid>,
) -> Result<(), QueueError> {
    let ids: Vec<String> = job_ids.iter().map(ToString::to_string).collect();
    sqlx::query(
        "INSERT INTO ingest_idempotency (idempotency_key, actor, action, job_ids)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (idempotency_key) DO NOTHING",
    )
    .bind(key)
    .bind(actor)
    .bind(action)
    .bind(serde_json::json!(ids))
    .execute(pool)
    .await
    .map_err(db_err)?;
    sqlx::query(
        "INSERT INTO ingest_audit (actor, action, job_id, idempotency_key, detail)
         VALUES ($1, $2, $3, $4, '{}'::jsonb)",
    )
    .bind(actor)
    .bind(action)
    .bind(job_id.map(|id| id.to_string()))
    .bind(key)
    .execute(pool)
    .await
    .map_err(db_err)?;
    Ok(())
}

pub async fn list_gaps(pool: &PgPool, filter: &ListFilter) -> Result<Vec<JobView>, QueueError> {
    let rows = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job
         WHERE state IN ('partial', 'permanent_failure', 'retry_wait')
           AND ($1::text[] IS NULL OR canonical_site = ANY($1))
         ORDER BY logical_window_start ASC
         LIMIT $2"
    ))
    .bind(filter.sites.clone())
    .bind(i64::from(filter.limit.min(MAX_LIST)))
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    rows.iter().map(job_from_row).collect()
}

pub async fn list_receipts(
    pool: &PgPool,
    filter: &ListFilter,
) -> Result<Vec<ReceiptView>, QueueError> {
    let rows = sqlx::query(
        "SELECT receipt_id, job_id, tenant_id, canonical_site, fencing_token, committed_at, counts, safe_error_code
         FROM ingest_receipt
         WHERE ($1::text[] IS NULL OR canonical_site = ANY($1))
         ORDER BY committed_at DESC
         LIMIT $2",
    )
    .bind(filter.sites.clone())
    .bind(i64::from(filter.limit.min(MAX_LIST)))
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    rows.iter().map(receipt_from_row).collect()
}

pub async fn get_receipt(
    pool: &PgPool,
    receipt_id: Uuid,
) -> Result<Option<ReceiptView>, QueueError> {
    let row = sqlx::query(
        "SELECT receipt_id, job_id, tenant_id, canonical_site, fencing_token, committed_at, counts, safe_error_code
         FROM ingest_receipt WHERE receipt_id = $1",
    )
    .bind(receipt_id.to_string())
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    match row {
        Some(row) => Ok(Some(receipt_from_row(&row)?)),
        None => Ok(None),
    }
}

pub async fn metrics(pool: &PgPool, now: DateTime<Utc>) -> Result<QueueMetrics, QueueError> {
    let ready: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM ingest_job
         WHERE state IN ('queued', 'retry_wait') AND not_before <= $1",
    )
    .bind(now)
    .fetch_one(pool)
    .await
    .map_err(db_err)?;
    let oldest: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT MIN(not_before) FROM ingest_job
         WHERE state IN ('queued', 'retry_wait') AND not_before <= $1",
    )
    .bind(now)
    .fetch_one(pool)
    .await
    .map_err(db_err)?;
    let leased: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM ingest_job WHERE state = 'leased'")
        .fetch_one(pool)
        .await
        .map_err(db_err)?;
    let retry_wait: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM ingest_job WHERE state = 'retry_wait'")
            .fetch_one(pool)
            .await
            .map_err(db_err)?;
    let partial: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM ingest_job WHERE state = 'partial'")
            .fetch_one(pool)
            .await
            .map_err(db_err)?;
    let permanent: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM ingest_job WHERE state = 'permanent_failure'")
            .fetch_one(pool)
            .await
            .map_err(db_err)?;
    let committed: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM ingest_job WHERE state = 'committed'")
            .fetch_one(pool)
            .await
            .map_err(db_err)?;
    let owner: Option<String> = sqlx::query_scalar(
        "SELECT owner FROM ingest_scheduler_lease WHERE lease_name = 'scheduler' AND expires_at > $1",
    )
    .bind(now)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    let portals = sqlx::query(
        "SELECT provider_instance_id, COUNT(*)::int AS in_flight
         FROM ingest_job
         WHERE state = 'leased' AND lease_expiry > $1
         GROUP BY provider_instance_id
         ORDER BY provider_instance_id",
    )
    .bind(now)
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    let portal_in_flight = portals
        .iter()
        .map(|row| {
            Ok(PortalInFlight {
                provider_instance_id: row.try_get("provider_instance_id").map_err(db_err)?,
                in_flight: u32::try_from(row.try_get::<i32, _>("in_flight").map_err(db_err)?)
                    .unwrap_or(0),
            })
        })
        .collect::<Result<Vec<_>, QueueError>>()?;
    Ok(QueueMetrics {
        ready_backlog: u64::try_from(ready).unwrap_or(0),
        oldest_ready_age_secs: oldest
            .map(|ts| now.signed_duration_since(ts).num_seconds().max(0) as u64),
        leased: u64::try_from(leased).unwrap_or(0),
        retry_wait: u64::try_from(retry_wait).unwrap_or(0),
        partial: u64::try_from(partial).unwrap_or(0),
        permanent_failure: u64::try_from(permanent).unwrap_or(0),
        committed: u64::try_from(committed).unwrap_or(0),
        scheduler_owner: owner,
        portal_in_flight,
    })
}

const JOB_COLUMNS: &str = "job_id, tenant_id, canonical_site, provider_instance_id, device_id, \
model_revision, logical_window_start, logical_window_end, shard, state, attempt, not_before, \
lease_owner, lease_expiry, fencing_token, estimated_cost, safe_error_code, receipt_id, \
fetched_count, accepted_count, rejected_count, inserted_count, updated_count, unchanged_count";

async fn load_job(pool: &PgPool, job_id: &str) -> Result<JobView, QueueError> {
    let row = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job WHERE job_id = $1"
    ))
    .bind(job_id)
    .fetch_one(pool)
    .await
    .map_err(db_err)?;
    job_from_row(&row)
}

async fn load_job_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    job_id: &str,
) -> Result<JobView, QueueError> {
    let row = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job WHERE job_id = $1"
    ))
    .bind(job_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(db_err)?;
    job_from_row(&row)
}

async fn touch_budget(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    portal: &str,
    now: DateTime<Utc>,
    budget: BudgetDefaults,
) -> Result<(), QueueError> {
    let max_in_flight = i32::try_from(budget.max_in_flight.max(1)).unwrap_or(1);
    let max_per_minute = i32::try_from(budget.max_per_minute.max(1)).unwrap_or(1);
    sqlx::query(
        "INSERT INTO ingest_portal_budget (
            provider_instance_id, max_in_flight, max_per_minute, tokens_remaining, window_start
        ) VALUES ($1, $2, $3, GREATEST($3 - 1, 0), $4)
        ON CONFLICT (provider_instance_id) DO UPDATE SET
          tokens_remaining = CASE
            WHEN ingest_portal_budget.window_start + interval '60 seconds' <= $4
            THEN GREATEST($3 - 1, 0)
            ELSE GREATEST(ingest_portal_budget.tokens_remaining - 1, 0)
          END,
          window_start = CASE
            WHEN ingest_portal_budget.window_start + interval '60 seconds' <= $4 THEN $4
            ELSE ingest_portal_budget.window_start
          END,
          max_in_flight = $2,
          max_per_minute = $3",
    )
    .bind(portal)
    .bind(max_in_flight)
    .bind(max_per_minute)
    .bind(now)
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    Ok(())
}

fn job_from_row(row: &PgRow) -> Result<JobView, QueueError> {
    let receipt: Option<String> = row.try_get("receipt_id").map_err(db_err)?;
    Ok(JobView {
        job_id: parse_uuid(&row.try_get::<String, _>("job_id").map_err(db_err)?)?,
        tenant_id: row.try_get("tenant_id").map_err(db_err)?,
        canonical_site: row.try_get("canonical_site").map_err(db_err)?,
        provider_instance_id: row.try_get("provider_instance_id").map_err(db_err)?,
        device_id: row.try_get("device_id").map_err(db_err)?,
        model_revision: row.try_get("model_revision").map_err(db_err)?,
        logical_window_start: row.try_get("logical_window_start").map_err(db_err)?,
        logical_window_end: row.try_get("logical_window_end").map_err(db_err)?,
        shard: row.try_get("shard").map_err(db_err)?,
        state: row.try_get("state").map_err(db_err)?,
        attempt: u32::try_from(row.try_get::<i32, _>("attempt").map_err(db_err)?).unwrap_or(0),
        not_before: row.try_get("not_before").map_err(db_err)?,
        lease_owner: row.try_get("lease_owner").map_err(db_err)?,
        lease_expiry: row.try_get("lease_expiry").map_err(db_err)?,
        fencing_token: i64_to_u64(row.try_get("fencing_token").map_err(db_err)?),
        estimated_cost: u32::try_from(row.try_get::<i32, _>("estimated_cost").map_err(db_err)?)
            .unwrap_or(1),
        safe_error_code: row.try_get("safe_error_code").map_err(db_err)?,
        receipt_id: receipt.as_deref().map(parse_uuid).transpose()?,
        coverage: COVERAGE_NOT_ASSESSED.to_string(),
        counts: JobCounts {
            fetched: u32::try_from(row.try_get::<i32, _>("fetched_count").map_err(db_err)?)
                .unwrap_or(0),
            accepted: u32::try_from(row.try_get::<i32, _>("accepted_count").map_err(db_err)?)
                .unwrap_or(0),
            rejected: u32::try_from(row.try_get::<i32, _>("rejected_count").map_err(db_err)?)
                .unwrap_or(0),
            inserted: u32::try_from(row.try_get::<i32, _>("inserted_count").map_err(db_err)?)
                .unwrap_or(0),
            updated: u32::try_from(row.try_get::<i32, _>("updated_count").map_err(db_err)?)
                .unwrap_or(0),
            unchanged: u32::try_from(row.try_get::<i32, _>("unchanged_count").map_err(db_err)?)
                .unwrap_or(0),
        },
    })
}

fn receipt_from_row(row: &PgRow) -> Result<ReceiptView, QueueError> {
    let counts: serde_json::Value = row.try_get("counts").map_err(db_err)?;
    Ok(ReceiptView {
        receipt_id: parse_uuid(&row.try_get::<String, _>("receipt_id").map_err(db_err)?)?,
        job_id: parse_uuid(&row.try_get::<String, _>("job_id").map_err(db_err)?)?,
        tenant_id: row.try_get("tenant_id").map_err(db_err)?,
        canonical_site: row.try_get("canonical_site").map_err(db_err)?,
        fencing_token: i64_to_u64(row.try_get("fencing_token").map_err(db_err)?),
        committed_at: row.try_get("committed_at").map_err(db_err)?,
        counts: JobCounts {
            fetched: counts.get("fetched").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
            accepted: counts.get("accepted").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
            rejected: counts.get("rejected").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
            inserted: counts.get("inserted").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
            updated: counts.get("updated").and_then(|v| v.as_u64()).unwrap_or(0) as u32,
            unchanged: counts
                .get("unchanged")
                .and_then(|v| v.as_u64())
                .unwrap_or(0) as u32,
        },
        safe_error_code: row.try_get("safe_error_code").map_err(db_err)?,
    })
}

fn parse_uuid(raw: &str) -> Result<Uuid, QueueError> {
    Uuid::parse_str(raw).map_err(|_| QueueError::Invalid("invalid queue identifier".into()))
}

fn i64_to_u64(value: i64) -> u64 {
    u64::try_from(value).unwrap_or(0)
}

fn i32_count(value: u32) -> i32 {
    i32::try_from(value).unwrap_or(i32::MAX)
}

fn db_err(err: sqlx::Error) -> QueueError {
    let mut text = err.to_string();
    if let Some(idx) = text.find("postgres://") {
        text.truncate(idx);
        text.push_str("postgres://redacted");
    }
    QueueError::Db(super::model::truncate_chars(&text, 180))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claim_sql_locks_one_row_and_bumps_the_fence_on_update() {
        assert!(CLAIM_SELECT_SQL.contains("FOR UPDATE OF j SKIP LOCKED"));
        assert!(SCHEMA_SQL.contains("fencing_token"));
        assert!(SCHEMA_SQL.contains("ingest_job_logical_key"));
        let stmts = statements(SCHEMA_SQL);
        assert!(stmts.len() >= 6);
        assert!(stmts.iter().all(|stmt| !stmt.contains("postgres://")));
    }
}
