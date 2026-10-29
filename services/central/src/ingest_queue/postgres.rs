//! Postgres queue. Statements use bound parameters and `SKIP LOCKED` claims.
//!
//! Fencing rules match [`super::memory`]: a finish must present the current
//! owner, token, and an unexpired lease. Schema DDL is applied on connect.

use chrono::{DateTime, Utc};
use sqlx::postgres::PgRow;
use sqlx::{PgPool, Row};
use uuid::Uuid;

use super::model::*;
use super::replay_horizon;

pub const SCHEMA_SQL: &str = include_str!("../../../../sql/schema/04_ingest_queue.sql");

/// Serializes ingest-queue DDL. Concurrent `CREATE TABLE IF NOT EXISTS`
/// races on `pg_type_typname_nsp_index` when several tests share one database.
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
    CASE WHEN j.shard = 'asap' THEN 1 ELSE 0 END
), (
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
    // Ingest tables, the applied-sample ledger, the audit table, and the
    // scheduler fence are one batch. The transaction lock serializes this
    // with hourly-job schema init and the startup migration.
    let mut tx = crate::db_lifecycle::begin_schema_ddl(pool)
        .await
        .map_err(db_err)?;
    for stmt in statements(SCHEMA_SQL) {
        sqlx::query(&stmt).execute(&mut *tx).await.map_err(db_err)?;
    }
    migrate_idempotency_scope(&mut tx).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(())
}

pub async fn enqueue(pool: &PgPool, job: &NewJob) -> Result<EnqueueOutcome, QueueError> {
    validate_new_job(job)?;
    let job_id = Uuid::new_v4().to_string();
    let inserted: Option<String> = sqlx::query_scalar(
        "INSERT INTO ingest_job (
            job_id, tenant_id, canonical_site, provider_instance_id, device_id,
            model_revision, logical_window_start, logical_window_end, shard,
            state, attempt, not_before, fencing_token, estimated_cost, requested_points_digest,
            server_request_id
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,'queued',0,$10,0,$11,$12,$13
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
    .bind(crate::audit::current_server_request_id())
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
    crate::audit::correlate_job(&id);
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PortalBudgetStatus {
    pub paused_until: Option<DateTime<Utc>>,
    pub tokens_remaining: Option<i32>,
}

pub async fn portal_budget_status(
    pool: &PgPool,
    provider_instance_id: &str,
    _now: DateTime<Utc>,
) -> Result<PortalBudgetStatus, QueueError> {
    let row = sqlx::query_as::<_, (Option<DateTime<Utc>>, Option<i32>)>(
        "SELECT paused_until, tokens_remaining
         FROM ingest_portal_budget
         WHERE provider_instance_id = $1",
    )
    .bind(provider_instance_id)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    Ok(match row {
        Some((paused, tokens)) => PortalBudgetStatus {
            paused_until: paused,
            tokens_remaining: tokens,
        },
        None => PortalBudgetStatus {
            paused_until: None,
            tokens_remaining: None,
        },
    })
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

pub async fn apply_samples(
    pool: &PgPool,
    job: &JobView,
    samples: &[AppliedSample],
) -> Result<ApplyStats, QueueError> {
    let mut tx = pool.begin().await.map_err(db_err)?;
    let stats = apply_samples_tx(&mut tx, job, samples).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(stats)
}

/// Canonical rows for one claimed device window and the ledger rows that
/// record them. Rows belong to `job.canonical_site` / `job.device_id`.
pub struct CanonicalWindow<'a> {
    pub equip_type: Option<&'a str>,
    pub rows: &'a fdd_tsdb::UpsertBatch,
    pub applied: &'a [AppliedSample],
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WindowWrite {
    pub samples: fdd_tsdb::SampleUpsertStats,
    pub ledger: ApplyStats,
}

/// Write one window to canonical history and the applied-sample ledger in one
/// transaction. The job row is locked first and must still name this lease
/// owner, fencing token, and an unexpired lease at `now`; otherwise nothing is
/// written and the caller gets [`QueueError::StaleFence`]. While the lock is
/// held a reclaiming claim skips the row, so a write that passed the check
/// commits before any later owner can start.
pub async fn commit_window(
    pool: &PgPool,
    job: &JobView,
    now: DateTime<Utc>,
    window: &CanonicalWindow<'_>,
) -> Result<WindowWrite, QueueError> {
    if window.rows.rows.iter().any(|row| {
        row.site_id != job.canonical_site
            || row.equipment_id.as_deref() != Some(job.device_id.as_str())
    }) {
        return Err(QueueError::Invalid(
            "canonical rows are outside the claimed window".into(),
        ));
    }
    let Some(owner) = job.lease_owner.as_deref() else {
        return Err(QueueError::StaleFence);
    };
    let mut tx = pool.begin().await.map_err(db_err)?;
    let owned: Option<String> = sqlx::query_scalar(
        "SELECT job_id FROM ingest_job
         WHERE job_id = $1 AND lease_owner = $2 AND fencing_token = $3
           AND state = 'leased' AND lease_expiry > $4
         FOR UPDATE",
    )
    .bind(job.job_id.to_string())
    .bind(owner)
    .bind(i64::try_from(job.fencing_token).unwrap_or(i64::MAX))
    .bind(now)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db_err)?;
    if owned.is_none() {
        tx.rollback().await.map_err(db_err)?;
        return Err(QueueError::StaleFence);
    }
    if !window.rows.is_empty() {
        fdd_tsdb::Tsdb::ensure_site_building_tx(&mut tx, &job.canonical_site)
            .await
            .map_err(tsdb_err)?;
        fdd_tsdb::Tsdb::upsert_equipment_tx(
            &mut tx,
            &job.canonical_site,
            &job.device_id,
            window.equip_type,
        )
        .await
        .map_err(tsdb_err)?;
    }
    let samples = fdd_tsdb::Tsdb::upsert_samples_tx(&mut tx, window.rows)
        .await
        .map_err(tsdb_err)?;
    let ledger = apply_samples_tx(&mut tx, job, window.applied).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(WindowWrite { samples, ledger })
}

fn tsdb_err(err: fdd_tsdb::TsdbError) -> QueueError {
    match err {
        fdd_tsdb::TsdbError::Sqlx(inner) => db_err(inner),
        other => QueueError::Db(other.to_string()),
    }
}

pub async fn finish(pool: &PgPool, req: &FinishRequest) -> Result<Option<ReceiptView>, QueueError> {
    let job_id = req.job_id.to_string();
    let exists: Option<(String, Option<String>)> = sqlx::query_as(
        "SELECT model_revision, requested_points_digest FROM ingest_job WHERE job_id = $1",
    )
    .bind(&job_id)
    .fetch_optional(pool)
    .await
    .map_err(db_err)?;
    let Some((model_revision, stored_digest)) = exists else {
        return Err(QueueError::NotFound);
    };
    if model_identity_changed(&model_revision, stored_digest.as_deref(), req) {
        let updated = sqlx::query(
            "UPDATE ingest_job SET state = 'permanent_failure', safe_error_code = 'model_revision_changed',
                lease_owner = NULL, lease_expiry = NULL, updated_at = $4
             WHERE job_id = $1 AND lease_owner = $2 AND fencing_token = $3
               AND state = 'leased' AND lease_expiry > $4",
        )
        .bind(&job_id)
        .bind(&req.owner)
        .bind(i64::try_from(req.fencing_token).unwrap_or(i64::MAX))
        .bind(req.now)
        .execute(pool)
        .await
        .map_err(db_err)?;
        if updated.rows_affected() == 0 {
            return Err(QueueError::StaleFence);
        }
        return Ok(None);
    }
    let (state, code, counts, coverage) = match &req.outcome {
        FinishOutcome::Committed { counts, coverage } => {
            if !coverage.allows_commit() {
                return Err(QueueError::Invalid("coverage does not allow commit".into()));
            }
            ("committed", None, *counts, Some(coverage))
        }
        FinishOutcome::Partial {
            counts,
            code,
            coverage,
        } => {
            if coverage.allows_commit() {
                return Err(QueueError::Invalid(
                    "partial finish requires an incomplete coverage report".into(),
                ));
            }
            if coverage.points.is_empty() && code != "payload_bound" {
                return Err(QueueError::Invalid(
                    "partial finish requires point coverage".into(),
                ));
            }
            ("partial", Some(code.clone()), *counts, Some(coverage))
        }
        FinishOutcome::Retry { code, not_before } => {
            let updated = sqlx::query(
                "UPDATE ingest_job SET state = 'retry_wait', safe_error_code = $5,
                    not_before = $6, lease_owner = NULL, lease_expiry = NULL, updated_at = $4,
                    attempt = CASE
                      WHEN $5 = 'throttled' THEN GREATEST(attempt - 1, 0)
                      ELSE attempt
                    END
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
    let coverage_summary = coverage
        .map(|report| report.summary.clone())
        .unwrap_or_else(|| COVERAGE_NOT_ASSESSED.to_string());
    let mut tx = pool.begin().await.map_err(db_err)?;
    let updated = sqlx::query(
        "UPDATE ingest_job SET state = $5, safe_error_code = $6, receipt_id = $7,
            fetched_count = $8, accepted_count = $9, rejected_count = $10,
            inserted_count = $11, updated_count = $12, unchanged_count = $13,
            coverage = $14,
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
    .bind(&coverage_summary)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    if updated.rows_affected() == 0 {
        return Err(QueueError::StaleFence);
    }
    let job = load_job_tx(&mut tx, &job_id).await?;
    if let Some(report) = coverage {
        replace_point_coverage(&mut tx, &job_id, report).await?;
    }
    apply_samples_tx(&mut tx, &job, &req.applied_samples).await?;
    let inserted = sqlx::query(
        "INSERT INTO ingest_receipt (
            receipt_id, job_id, tenant_id, canonical_site, provider_instance_id, device_id,
            model_revision, fencing_token, committed_at, counts, safe_error_code, coverage,
            server_request_id
         )
         SELECT $1, job_id, tenant_id, canonical_site, provider_instance_id, device_id,
                model_revision, $2, $3, $4, $5, $7, server_request_id
         FROM ingest_job
         WHERE job_id = $6",
    )
    .bind(&receipt_id)
    .bind(i64::try_from(req.fencing_token).unwrap_or(i64::MAX))
    .bind(req.now)
    .bind(serde_json::json!(counts))
    .bind(&code)
    .bind(&job_id)
    .bind(&coverage_summary)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    if inserted.rows_affected() != 1 {
        return Err(QueueError::Invalid(
            "receipt identity could not be copied from the job".into(),
        ));
    }
    tx.commit().await.map_err(db_err)?;
    crate::audit::correlate_receipt(&receipt_id);
    Ok(Some(ReceiptView {
        receipt_id: parse_uuid(&receipt_id)?,
        job_id: req.job_id,
        tenant_id: job.tenant_id,
        canonical_site: job.canonical_site,
        provider_instance_id: job.provider_instance_id,
        device_id: job.device_id,
        model_revision: job.model_revision,
        fencing_token: req.fencing_token,
        committed_at: req.now,
        counts,
        safe_error_code: code,
        server_request_id: job.server_request_id.clone(),
    }))
}

pub async fn list_jobs(pool: &PgPool, filter: &ListFilter) -> Result<Vec<JobView>, QueueError> {
    let rows = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job
         WHERE ($1::text[] IS NULL OR canonical_site = ANY($1))
           AND ($2::text IS NULL OR state = $2)
           AND ($3::text IS NULL OR tenant_id = $3)
         ORDER BY logical_window_start DESC
         LIMIT $4"
    ))
    .bind(filter.sites.clone())
    .bind(filter.state.clone())
    .bind(filter.tenant_id.clone())
    .bind(i64::from(filter.limit.min(MAX_LIST)))
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    let mut jobs = rows
        .iter()
        .map(job_from_row)
        .collect::<Result<Vec<_>, _>>()?;
    attach_point_coverage(pool, &mut jobs).await?;
    Ok(jobs)
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
        Some(row) => {
            let mut job = job_from_row(&row)?;
            attach_point_coverage(pool, std::slice::from_mut(&mut job)).await?;
            Ok(Some(job))
        }
        None => Ok(None),
    }
}

pub async fn retry_job(
    pool: &PgPool,
    job_id: Uuid,
    now: DateTime<Utc>,
    claim: &IdempotencyClaim,
) -> Result<JobView, QueueError> {
    if claim.object_id != retry_object_id(job_id)
        || claim.payload_hash != retry_payload_hash(&claim.tenant_id, job_id)
    {
        return Err(QueueError::Conflict(
            "idempotency key does not match the original request".into(),
        ));
    }
    let mut tx = pool.begin().await.map_err(db_err)?;
    let reserved = lock_idempotency(&mut tx, "retry", claim).await?;
    if !reserved.inserted {
        if !binding_matches(&reserved, claim) {
            return Err(QueueError::Conflict(
                "idempotency key does not match the original request".into(),
            ));
        }
        let views = load_jobs_for_replay(&mut tx, &reserved.job_ids, &claim.tenant_id).await?;
        let Some(job) = views.into_iter().next() else {
            return Err(QueueError::NotFound);
        };
        tx.commit().await.map_err(db_err)?;
        return Ok(job);
    }
    let Some(job) = load_job_for_update(&mut tx, &job_id.to_string()).await? else {
        return Err(QueueError::NotFound);
    };
    if job.tenant_id != claim.tenant_id {
        return Err(QueueError::NotFound);
    }
    if !operator_retry_allowed(&job.state, job.safe_error_code.as_deref()) {
        return Err(QueueError::Invalid(
            "job is not eligible for operator retry".into(),
        ));
    }
    refuse_before_replay_horizon(
        &mut tx,
        &job.tenant_id,
        &job.canonical_site,
        job.logical_window_start,
        now,
    )
    .await?;
    let updated = sqlx::query(&format!(
        "UPDATE ingest_job SET state = 'queued', not_before = $2, lease_owner = NULL,
            lease_expiry = NULL, safe_error_code = NULL, updated_at = $2
         WHERE job_id = $1 AND state IN ('partial', 'permanent_failure', 'retry_wait', 'cancelled')
         RETURNING {JOB_COLUMNS}"
    ))
    .bind(job_id.to_string())
    .bind(now)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db_err)?;
    let Some(row) = updated else {
        return Err(QueueError::Invalid(
            "job is not eligible for operator retry".into(),
        ));
    };
    let view = job_from_row(&row)?;
    store_idempotency_result(&mut tx, "retry", claim, &[job_id], Some(job_id)).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(view)
}

pub async fn backfill(
    pool: &PgPool,
    jobs: &[NewJob],
    now: DateTime<Utc>,
    claim: &IdempotencyClaim,
) -> Result<Vec<JobView>, QueueError> {
    if jobs.is_empty() || jobs.len() > MAX_CATCHUP_HOURS as usize {
        return Err(QueueError::Invalid(
            "backfill requires 1 to 48 hourly windows".into(),
        ));
    }
    let object_id = backfill_object_id(&jobs[0]);
    let payload_hash = backfill_payload_hash(jobs)?;
    if claim.object_id != object_id
        || claim.payload_hash != payload_hash
        || jobs.iter().any(|job| job.tenant_id != claim.tenant_id)
    {
        return Err(QueueError::Conflict(
            "idempotency key does not match the original request".into(),
        ));
    }
    let mut tx = pool.begin().await.map_err(db_err)?;
    let reserved = lock_idempotency(&mut tx, "backfill", claim).await?;
    if !reserved.inserted {
        if !binding_matches(&reserved, claim) {
            return Err(QueueError::Conflict(
                "idempotency key does not match the original request".into(),
            ));
        }
        let views = load_jobs_for_replay(&mut tx, &reserved.job_ids, &claim.tenant_id).await?;
        tx.commit().await.map_err(db_err)?;
        return Ok(views);
    }
    for job in jobs {
        refuse_before_replay_horizon(
            &mut tx,
            &job.tenant_id,
            &job.canonical_site,
            job.logical_window_start,
            now,
        )
        .await?;
    }
    let mut views = Vec::new();
    for job in jobs {
        views.push(enqueue_tx(&mut tx, job).await?);
    }
    let ids: Vec<Uuid> = views.iter().map(|job| job.job_id).collect();
    store_idempotency_result(&mut tx, "backfill", claim, &ids, None).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(views)
}

pub async fn site_backfill(
    pool: &PgPool,
    jobs: &[NewJob],
    range_start: DateTime<Utc>,
    range_end: DateTime<Utc>,
    now: DateTime<Utc>,
    claim: &IdempotencyClaim,
) -> Result<Vec<JobView>, QueueError> {
    if jobs.is_empty() || jobs.len() > MAX_SITE_BACKFILL_JOBS as usize {
        return Err(QueueError::Invalid(format!(
            "site backfill requires 1 to {} jobs",
            MAX_SITE_BACKFILL_JOBS
        )));
    }
    let object_id = site_backfill_object_id(&jobs[0]);
    let payload_hash = site_backfill_payload_hash(
        &jobs[0].tenant_id,
        &jobs[0].canonical_site,
        &jobs[0].provider_instance_id,
        &jobs[0].model_revision,
        range_start,
        range_end,
    );
    if claim.object_id != object_id
        || claim.payload_hash != payload_hash
        || jobs.iter().any(|job| job.tenant_id != claim.tenant_id)
    {
        return Err(QueueError::Conflict(
            "idempotency key does not match the original request".into(),
        ));
    }
    let mut tx = pool.begin().await.map_err(db_err)?;
    let reserved = lock_idempotency(&mut tx, "site_backfill", claim).await?;
    if !reserved.inserted {
        if !binding_matches(&reserved, claim) {
            return Err(QueueError::Conflict(
                "idempotency key does not match the original request".into(),
            ));
        }
        let views = load_jobs_for_replay(&mut tx, &reserved.job_ids, &claim.tenant_id).await?;
        tx.commit().await.map_err(db_err)?;
        return Ok(views);
    }
    for job in jobs {
        refuse_before_replay_horizon(
            &mut tx,
            &job.tenant_id,
            &job.canonical_site,
            job.logical_window_start,
            now,
        )
        .await?;
    }
    let mut views = Vec::with_capacity(jobs.len());
    for job in jobs {
        views.push(enqueue_tx(&mut tx, job).await?);
    }
    let ids: Vec<Uuid> = views.iter().map(|job| job.job_id).collect();
    store_idempotency_result(&mut tx, "site_backfill", claim, &ids, None).await?;
    tx.commit().await.map_err(db_err)?;
    Ok(views)
}

pub async fn cancel_jobs(
    pool: &PgPool,
    filter: &CancelFilter,
    now: DateTime<Utc>,
    claim: &IdempotencyClaim,
) -> Result<CancelOutcome, QueueError> {
    if claim.object_id != cancel_object_id(filter)
        || claim.payload_hash != cancel_payload_hash(filter)
    {
        return Err(QueueError::Conflict(
            "idempotency key does not match the original request".into(),
        ));
    }
    let mut tx = pool.begin().await.map_err(db_err)?;
    let reserved = lock_idempotency(&mut tx, "cancel", claim).await?;
    if !reserved.inserted {
        if !binding_matches(&reserved, claim) {
            return Err(QueueError::Conflict(
                "idempotency key does not match the original request".into(),
            ));
        }
        let views = load_jobs_for_replay(&mut tx, &reserved.job_ids, &claim.tenant_id).await?;
        let job_ids: Vec<Uuid> = views.iter().map(|job| job.job_id).collect();
        let cancelled = u32::try_from(job_ids.len())
            .map_err(|_| QueueError::Invalid("cancelled job count overflow".into()))?;
        tx.commit().await.map_err(db_err)?;
        return Ok(CancelOutcome { cancelled, job_ids });
    }
    let rows = sqlx::query_scalar::<_, String>(
        "UPDATE ingest_job SET state = 'cancelled', lease_owner = NULL, lease_expiry = NULL,
            safe_error_code = 'cancelled', updated_at = $1
         WHERE tenant_id = $2
           AND state IN ('queued', 'retry_wait')
           AND ($3::text IS NULL OR canonical_site = $3)
           AND ($4::text IS NULL OR provider_instance_id = $4)
           AND ($5::text IS NULL OR device_id = $5)
           AND ($6::timestamptz IS NULL OR logical_window_start >= $6)
           AND ($7::timestamptz IS NULL OR logical_window_end <= $7)
         RETURNING job_id",
    )
    .bind(now)
    .bind(&filter.tenant_id)
    .bind(filter.canonical_site.as_deref())
    .bind(filter.provider_instance_id.as_deref())
    .bind(filter.device_id.as_deref())
    .bind(filter.window_start)
    .bind(filter.window_end)
    .fetch_all(&mut *tx)
    .await
    .map_err(db_err)?;
    let job_ids: Result<Vec<Uuid>, QueueError> = rows
        .iter()
        .map(|raw| {
            Uuid::parse_str(raw)
                .map_err(|_| QueueError::Db("cancel returned an invalid job id".into()))
        })
        .collect();
    let job_ids = job_ids?;
    store_idempotency_result(&mut tx, "cancel", claim, &job_ids, None).await?;
    let cancelled = u32::try_from(job_ids.len())
        .map_err(|_| QueueError::Invalid("cancelled job count overflow".into()))?;
    tx.commit().await.map_err(db_err)?;
    Ok(CancelOutcome { cancelled, job_ids })
}

pub async fn list_gaps(pool: &PgPool, filter: &ListFilter) -> Result<Vec<JobView>, QueueError> {
    let rows = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job
         WHERE state IN ('partial', 'permanent_failure', 'retry_wait')
           AND ($1::text[] IS NULL OR canonical_site = ANY($1))
           AND ($3::text IS NULL OR tenant_id = $3)
         ORDER BY logical_window_start ASC
         LIMIT $2"
    ))
    .bind(filter.sites.clone())
    .bind(i64::from(filter.limit.min(MAX_LIST)))
    .bind(filter.tenant_id.clone())
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    let mut jobs = rows
        .iter()
        .map(job_from_row)
        .collect::<Result<Vec<_>, _>>()?;
    attach_point_coverage(pool, &mut jobs).await?;
    Ok(jobs)
}

pub async fn list_receipts(
    pool: &PgPool,
    filter: &ListFilter,
) -> Result<Vec<ReceiptView>, QueueError> {
    let rows = sqlx::query(
        "SELECT receipt_id, job_id, tenant_id, canonical_site, provider_instance_id, device_id,
                model_revision, fencing_token, committed_at, counts, safe_error_code,
                server_request_id
         FROM ingest_receipt
         WHERE ($1::text[] IS NULL OR canonical_site = ANY($1))
           AND ($3::text IS NULL OR tenant_id = $3)
         ORDER BY committed_at DESC
         LIMIT $2",
    )
    .bind(filter.sites.clone())
    .bind(i64::from(filter.limit.min(MAX_LIST)))
    .bind(filter.tenant_id.clone())
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
        "SELECT receipt_id, job_id, tenant_id, canonical_site, provider_instance_id, device_id,
                model_revision, fencing_token, committed_at, counts, safe_error_code,
                server_request_id
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

pub async fn metrics(
    pool: &PgPool,
    now: DateTime<Utc>,
    scope: &MetricsScope,
) -> Result<QueueMetrics, QueueError> {
    let counts = sqlx::query(
        "SELECT
            COUNT(*) FILTER (
                WHERE state IN ('queued', 'retry_wait') AND not_before <= $1
            ) AS ready,
            MIN(not_before) FILTER (
                WHERE state IN ('queued', 'retry_wait') AND not_before <= $1
            ) AS oldest,
            COUNT(*) FILTER (WHERE state = 'leased') AS leased,
            COUNT(*) FILTER (WHERE state = 'retry_wait') AS retry_wait,
            COUNT(*) FILTER (WHERE state = 'partial') AS partial,
            COUNT(*) FILTER (WHERE state = 'permanent_failure') AS permanent_failure,
            COUNT(*) FILTER (WHERE state = 'committed') AS committed
         FROM ingest_job
         WHERE ($2::text IS NULL OR tenant_id = $2)
           AND ($3::text[] IS NULL OR canonical_site = ANY($3))",
    )
    .bind(now)
    .bind(scope.tenant_id.clone())
    .bind(scope.sites.clone())
    .fetch_one(pool)
    .await
    .map_err(db_err)?;
    let ready: i64 = counts.try_get("ready").map_err(db_err)?;
    let oldest: Option<DateTime<Utc>> = counts.try_get("oldest").map_err(db_err)?;
    let leased: i64 = counts.try_get("leased").map_err(db_err)?;
    let retry_wait: i64 = counts.try_get("retry_wait").map_err(db_err)?;
    let partial: i64 = counts.try_get("partial").map_err(db_err)?;
    let permanent: i64 = counts.try_get("permanent_failure").map_err(db_err)?;
    let committed: i64 = counts.try_get("committed").map_err(db_err)?;
    let owner = if scope.include_scheduler {
        sqlx::query_scalar(
            "SELECT owner FROM ingest_scheduler_lease WHERE lease_name = 'scheduler' AND expires_at > $1",
        )
        .bind(now)
        .fetch_optional(pool)
        .await
        .map_err(db_err)?
    } else {
        None
    };
    let portals = sqlx::query(
        "SELECT provider_instance_id, COUNT(*)::int AS in_flight
         FROM ingest_job
         WHERE state = 'leased' AND lease_expiry > $1
           AND ($2::text IS NULL OR tenant_id = $2)
           AND ($3::text[] IS NULL OR canonical_site = ANY($3))
         GROUP BY provider_instance_id
         ORDER BY provider_instance_id",
    )
    .bind(now)
    .bind(scope.tenant_id.clone())
    .bind(scope.sites.clone())
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
fetched_count, accepted_count, rejected_count, inserted_count, updated_count, unchanged_count, \
coverage, server_request_id";

async fn load_job(pool: &PgPool, job_id: &str) -> Result<JobView, QueueError> {
    let row = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job WHERE job_id = $1"
    ))
    .bind(job_id)
    .fetch_one(pool)
    .await
    .map_err(db_err)?;
    let mut job = job_from_row(&row)?;
    attach_point_coverage(pool, std::slice::from_mut(&mut job)).await?;
    Ok(job)
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

async fn attach_point_coverage(pool: &PgPool, jobs: &mut [JobView]) -> Result<(), QueueError> {
    if jobs.is_empty() {
        return Ok(());
    }
    let ids: Vec<String> = jobs.iter().map(|job| job.job_id.to_string()).collect();
    let rows = sqlx::query(
        "SELECT job_id, point_id, disposition, expected_slots, observed_slots, late_slots
         FROM ingest_point_coverage
         WHERE job_id = ANY($1)
         ORDER BY point_id",
    )
    .bind(&ids)
    .fetch_all(pool)
    .await
    .map_err(db_err)?;
    for job in jobs.iter_mut() {
        job.point_coverage.clear();
    }
    for row in rows {
        let job_id: String = row.try_get("job_id").map_err(db_err)?;
        let point = super::coverage::PointCoverage {
            point_id: row.try_get("point_id").map_err(db_err)?,
            disposition: row.try_get("disposition").map_err(db_err)?,
            expected_slots: i32_to_u32(row.try_get("expected_slots").map_err(db_err)?),
            observed_slots: i32_to_u32(row.try_get("observed_slots").map_err(db_err)?),
            late_slots: i32_to_u32(row.try_get("late_slots").map_err(db_err)?),
        };
        if let Some(job) = jobs.iter_mut().find(|job| job.job_id.to_string() == job_id) {
            job.point_coverage.push(point);
        }
    }
    Ok(())
}

async fn replace_point_coverage(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    job_id: &str,
    report: &super::coverage::CoverageReport,
) -> Result<(), QueueError> {
    sqlx::query("DELETE FROM ingest_point_coverage WHERE job_id = $1")
        .bind(job_id)
        .execute(&mut **tx)
        .await
        .map_err(db_err)?;
    for point in &report.points {
        if !bounded_point_id(&point.point_id) {
            return Err(QueueError::Invalid("point id is empty or too long".into()));
        }
        sqlx::query(
            "INSERT INTO ingest_point_coverage (
                job_id, point_id, disposition, expected_slots, observed_slots, late_slots
             ) VALUES ($1, $2, $3, $4, $5, $6)",
        )
        .bind(job_id)
        .bind(&point.point_id)
        .bind(&point.disposition)
        .bind(i32_count(point.expected_slots))
        .bind(i32_count(point.observed_slots))
        .bind(i32_count(point.late_slots))
        .execute(&mut **tx)
        .await
        .map_err(db_err)?;
    }
    Ok(())
}

async fn apply_samples_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    job: &JobView,
    samples: &[AppliedSample],
) -> Result<ApplyStats, QueueError> {
    if samples.len() > super::coverage::MAX_TIMESTAMPS {
        return Err(QueueError::Invalid("payload_bound".into()));
    }
    let mut stats = ApplyStats::default();
    for sample in samples {
        if !bounded_point_id(&sample.point_id) {
            return Err(QueueError::Invalid("point id is empty or too long".into()));
        }
        let bits = format!("{:016x}", sample.value_bits);
        let inserted: Option<String> = sqlx::query_scalar(
            "INSERT INTO ingest_applied_sample (
                tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
                point_id, ts, value_bits, first_job_id
             ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
             ON CONFLICT (
                tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
                point_id, ts
             ) DO NOTHING
             RETURNING value_bits",
        )
        .bind(&job.tenant_id)
        .bind(&job.canonical_site)
        .bind(&job.provider_instance_id)
        .bind(&job.device_id)
        .bind(&job.model_revision)
        .bind(&sample.point_id)
        .bind(sample.ts)
        .bind(&bits)
        .bind(job.job_id.to_string())
        .fetch_optional(&mut **tx)
        .await
        .map_err(db_err)?;
        if inserted.is_some() {
            stats.inserted = stats.inserted.saturating_add(1);
            continue;
        }
        let stored: String = sqlx::query_scalar(
            "SELECT value_bits FROM ingest_applied_sample
             WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
               AND device_id = $4 AND model_revision = $5 AND point_id = $6 AND ts = $7",
        )
        .bind(&job.tenant_id)
        .bind(&job.canonical_site)
        .bind(&job.provider_instance_id)
        .bind(&job.device_id)
        .bind(&job.model_revision)
        .bind(&sample.point_id)
        .bind(sample.ts)
        .fetch_one(&mut **tx)
        .await
        .map_err(db_err)?;
        if stored == bits {
            stats.unchanged = stats.unchanged.saturating_add(1);
        } else {
            stats.conflict = stats.conflict.saturating_add(1);
        }
    }
    Ok(stats)
}

fn model_identity_changed(
    model_revision: &str,
    stored_digest: Option<&str>,
    req: &FinishRequest,
) -> bool {
    if !matches!(
        req.outcome,
        FinishOutcome::Committed { .. } | FinishOutcome::Partial { .. }
    ) {
        return false;
    }
    if let Some(active) = req.active_model_revision.as_deref() {
        if !revision_still_owns(model_revision, active) {
            return true;
        }
    }
    if let (Some(active_digest), Some(stored)) =
        (req.active_points_digest.as_deref(), stored_digest)
    {
        if stored != active_digest {
            return true;
        }
    }
    false
}

fn bounded_point_id(value: &str) -> bool {
    let n = value.chars().count();
    (1..=512).contains(&n) && value.chars().all(|ch| !ch.is_control())
}

fn i32_to_u32(value: i32) -> u32 {
    u32::try_from(value).unwrap_or(0)
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
        coverage: row.try_get("coverage").map_err(db_err)?,
        point_coverage: Vec::new(),
        server_request_id: row.try_get("server_request_id").map_err(db_err)?,
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
        provider_instance_id: row.try_get("provider_instance_id").map_err(db_err)?,
        device_id: row.try_get("device_id").map_err(db_err)?,
        model_revision: row.try_get("model_revision").map_err(db_err)?,
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
        server_request_id: row.try_get("server_request_id").map_err(db_err)?,
    })
}

struct IdempotencyRow {
    object_id: String,
    payload_hash: String,
    job_ids: Vec<Uuid>,
    inserted: bool,
}

fn binding_matches(row: &IdempotencyRow, claim: &IdempotencyClaim) -> bool {
    row.object_id == claim.object_id && row.payload_hash == claim.payload_hash
}

async fn lock_idempotency(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    action: &str,
    claim: &IdempotencyClaim,
) -> Result<IdempotencyRow, QueueError> {
    let inserted = sqlx::query(
        "INSERT INTO ingest_idempotency (
            idempotency_key, actor, tenant_id, action, object_id, payload_hash, job_ids
         ) VALUES ($1, $2, $3, $4, $5, $6, '[]'::jsonb)
         ON CONFLICT (actor, tenant_id, action, idempotency_key) DO NOTHING
         RETURNING object_id, payload_hash, job_ids",
    )
    .bind(&claim.client_key)
    .bind(&claim.actor)
    .bind(&claim.tenant_id)
    .bind(action)
    .bind(&claim.object_id)
    .bind(&claim.payload_hash)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db_err)?;
    if let Some(row) = inserted {
        return Ok(IdempotencyRow {
            object_id: row.try_get("object_id").map_err(db_err)?,
            payload_hash: row.try_get("payload_hash").map_err(db_err)?,
            job_ids: Vec::new(),
            inserted: true,
        });
    }
    let row = sqlx::query(
        "SELECT object_id, payload_hash, job_ids FROM ingest_idempotency
         WHERE actor = $1 AND tenant_id = $2 AND action = $3 AND idempotency_key = $4
         FOR UPDATE",
    )
    .bind(&claim.actor)
    .bind(&claim.tenant_id)
    .bind(action)
    .bind(&claim.client_key)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db_err)?;
    let Some(row) = row else {
        return Err(QueueError::Db("idempotency reservation missing".into()));
    };
    Ok(IdempotencyRow {
        object_id: row.try_get("object_id").map_err(db_err)?,
        payload_hash: row.try_get("payload_hash").map_err(db_err)?,
        job_ids: parse_job_ids(row.try_get("job_ids").map_err(db_err)?)?,
        inserted: false,
    })
}

async fn store_idempotency_result(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    action: &str,
    claim: &IdempotencyClaim,
    job_ids: &[Uuid],
    job_id: Option<Uuid>,
) -> Result<(), QueueError> {
    let ids: Vec<String> = job_ids.iter().map(ToString::to_string).collect();
    sqlx::query(
        "UPDATE ingest_idempotency SET job_ids = $5
         WHERE actor = $1 AND tenant_id = $2 AND action = $3 AND idempotency_key = $4",
    )
    .bind(&claim.actor)
    .bind(&claim.tenant_id)
    .bind(action)
    .bind(&claim.client_key)
    .bind(serde_json::json!(ids))
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    sqlx::query(
        "INSERT INTO ingest_audit (actor, action, job_id, idempotency_key, detail)
         VALUES ($1, $2, $3, $4, $5)",
    )
    .bind(&claim.actor)
    .bind(action)
    .bind(job_id.map(|id| id.to_string()))
    .bind(&claim.client_key)
    .bind(serde_json::json!({
        "server_request_id": crate::audit::current_server_request_id()
    }))
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    Ok(())
}

async fn load_jobs_for_replay(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    ids: &[Uuid],
    tenant_id: &str,
) -> Result<Vec<JobView>, QueueError> {
    let mut views = Vec::new();
    for id in ids {
        match load_job_for_update(tx, &id.to_string()).await? {
            Some(job) if job.tenant_id == tenant_id => views.push(job),
            Some(_) => return Err(QueueError::NotFound),
            None => {}
        }
    }
    if views.is_empty() {
        return Err(QueueError::NotFound);
    }
    Ok(views)
}

async fn load_job_for_update(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    job_id: &str,
) -> Result<Option<JobView>, QueueError> {
    let row = sqlx::query(&format!(
        "SELECT {JOB_COLUMNS} FROM ingest_job WHERE job_id = $1 FOR UPDATE"
    ))
    .bind(job_id)
    .fetch_optional(&mut **tx)
    .await
    .map_err(db_err)?;
    row.as_ref().map(job_from_row).transpose()
}

async fn enqueue_tx(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    job: &NewJob,
) -> Result<JobView, QueueError> {
    validate_new_job(job)?;
    let job_id = Uuid::new_v4().to_string();
    let inserted: Option<String> = sqlx::query_scalar(
        "INSERT INTO ingest_job (
            job_id, tenant_id, canonical_site, provider_instance_id, device_id,
            model_revision, logical_window_start, logical_window_end, shard,
            state, attempt, not_before, fencing_token, estimated_cost, requested_points_digest,
            server_request_id
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,'queued',0,$10,0,$11,$12,$13
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
    .bind(crate::audit::current_server_request_id())
    .fetch_optional(&mut **tx)
    .await
    .map_err(db_err)?;
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
        .fetch_one(&mut **tx)
        .await
        .map_err(db_err)?,
    };
    crate::audit::correlate_job(&id);
    load_job_tx(tx, &id).await
}

async fn migrate_idempotency_scope(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
) -> Result<(), QueueError> {
    sqlx::query(
        "DELETE FROM ingest_idempotency
         WHERE tenant_id IS NULL OR object_id IS NULL OR payload_hash IS NULL
            OR tenant_id = '' OR object_id = '' OR payload_hash = ''",
    )
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    for column in ["tenant_id", "object_id", "payload_hash"] {
        let stmt = format!("ALTER TABLE ingest_idempotency ALTER COLUMN {column} SET NOT NULL");
        sqlx::query(&stmt)
            .execute(&mut **tx)
            .await
            .map_err(db_err)?;
    }
    let current: Option<String> = sqlx::query_scalar(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint
         WHERE conrelid = 'ingest_idempotency'::regclass AND contype = 'p'",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db_err)?;
    let definition = current.unwrap_or_default();
    if ["actor", "tenant_id", "action", "idempotency_key"]
        .iter()
        .all(|column| definition.contains(column))
    {
        return Ok(());
    }
    let name: Option<String> = sqlx::query_scalar(
        "SELECT conname FROM pg_constraint
         WHERE conrelid = 'ingest_idempotency'::regclass AND contype = 'p'",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(db_err)?;
    if let Some(name) = name {
        let Some(ident) = safe_pg_ident(&name) else {
            return Err(QueueError::Db(
                "unexpected idempotency primary key name".into(),
            ));
        };
        let drop_sql = format!("ALTER TABLE ingest_idempotency DROP CONSTRAINT {ident}");
        sqlx::query(&drop_sql)
            .execute(&mut **tx)
            .await
            .map_err(db_err)?;
    }
    sqlx::query(
        "ALTER TABLE ingest_idempotency
         ADD CONSTRAINT ingest_idempotency_pkey
         PRIMARY KEY (actor, tenant_id, action, idempotency_key)",
    )
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    Ok(())
}

fn safe_pg_ident(name: &str) -> Option<&str> {
    if (1..=63).contains(&name.len())
        && name
            .chars()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '_')
    {
        Some(name)
    } else {
        None
    }
}

fn parse_job_ids(raw: serde_json::Value) -> Result<Vec<Uuid>, QueueError> {
    let items = raw
        .as_array()
        .ok_or_else(|| QueueError::Invalid("invalid idempotency record".into()))?;
    items
        .iter()
        .map(|value| {
            value
                .as_str()
                .ok_or_else(|| QueueError::Invalid("invalid idempotency record".into()))
                .and_then(parse_uuid)
        })
        .collect()
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

/// Refuses a replay of a window that starts before the site's replay
/// horizon. The horizon row is created if missing and read under a share lock,
/// so a concurrent prune waits for this transaction.
async fn refuse_before_replay_horizon(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    tenant_id: &str,
    canonical_site: &str,
    window_start: DateTime<Utc>,
    now: DateTime<Utc>,
) -> Result<(), QueueError> {
    sqlx::query(
        "INSERT INTO ingest_applied_sample_horizon (tenant_id, canonical_site, pruned_before, updated_at)
         VALUES ($1, $2, NULL, $3)
         ON CONFLICT (tenant_id, canonical_site) DO NOTHING",
    )
    .bind(tenant_id)
    .bind(canonical_site)
    .bind(now)
    .execute(&mut **tx)
    .await
    .map_err(db_err)?;
    let pruned_before: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT pruned_before FROM ingest_applied_sample_horizon
         WHERE tenant_id = $1 AND canonical_site = $2
         FOR SHARE",
    )
    .bind(tenant_id)
    .bind(canonical_site)
    .fetch_one(&mut **tx)
    .await
    .map_err(db_err)?;
    match pruned_before {
        Some(cut) if replay_horizon::replay_refused(window_start, Some(cut)) => Err(
            QueueError::ReplayHorizon(replay_horizon::refusal_message(window_start, cut)),
        ),
        _ => Ok(()),
    }
}

/// Deletes one batch of ledger rows older than the retention for one site and
/// moves the site's replay horizon forward. Rows at or after the start of a
/// queued, leased, or retry-wait job are kept.
pub async fn prune_applied_samples(
    pool: &PgPool,
    tenant_id: &str,
    canonical_site: &str,
    now: DateTime<Utc>,
    retention: chrono::Duration,
) -> Result<replay_horizon::PruneReport, QueueError> {
    sqlx::query(
        "INSERT INTO ingest_applied_sample_horizon (tenant_id, canonical_site, pruned_before, updated_at)
         VALUES ($1, $2, NULL, $3)
         ON CONFLICT (tenant_id, canonical_site) DO NOTHING",
    )
    .bind(tenant_id)
    .bind(canonical_site)
    .bind(now)
    .execute(pool)
    .await
    .map_err(db_err)?;
    let mut tx = pool.begin().await.map_err(db_err)?;
    let stored: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT pruned_before FROM ingest_applied_sample_horizon
         WHERE tenant_id = $1 AND canonical_site = $2
         FOR UPDATE",
    )
    .bind(tenant_id)
    .bind(canonical_site)
    .fetch_one(&mut *tx)
    .await
    .map_err(db_err)?;
    let oldest_live: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT min(logical_window_start) FROM ingest_job
         WHERE tenant_id = $1 AND canonical_site = $2
           AND state IN ('queued', 'leased', 'retry_wait')",
    )
    .bind(tenant_id)
    .bind(canonical_site)
    .fetch_one(&mut *tx)
    .await
    .map_err(db_err)?;
    let delete_below = replay_horizon::prune_cutoff(now, retention, oldest_live);
    let pruned_before = stored.map_or(delete_below, |cut| cut.max(delete_below));
    let deleted = sqlx::query(
        "DELETE FROM ingest_applied_sample WHERE ctid IN (
            SELECT ctid FROM ingest_applied_sample
            WHERE tenant_id = $1 AND canonical_site = $2 AND ts < $3
            LIMIT $4
         )",
    )
    .bind(tenant_id)
    .bind(canonical_site)
    .bind(delete_below)
    .bind(replay_horizon::PRUNE_BATCH)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?
    .rows_affected();
    sqlx::query(
        "UPDATE ingest_applied_sample_horizon SET pruned_before = $3, updated_at = $4
         WHERE tenant_id = $1 AND canonical_site = $2",
    )
    .bind(tenant_id)
    .bind(canonical_site)
    .bind(pruned_before)
    .bind(now)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    tx.commit().await.map_err(db_err)?;
    Ok(replay_horizon::PruneReport {
        deleted,
        pruned_before,
    })
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
        assert!(SCHEMA_SQL
            .contains("ALTER TABLE ingest_job ADD COLUMN IF NOT EXISTS server_request_id text"));
        assert!(SCHEMA_SQL.contains(
            "ALTER TABLE ingest_receipt ADD COLUMN IF NOT EXISTS server_request_id text"
        ));
        let stmts = statements(SCHEMA_SQL);
        assert!(stmts.len() >= 6);
        assert!(stmts.iter().all(|stmt| !stmt.contains("postgres://")));
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize ingest schema DDL with the other queue fixtures"
    )]
    async fn server_request_id_round_trips_through_postgres_and_stays_on_conflict() {
        let required = std::env::var("OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED")
            .ok()
            .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
        let Some(url) = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
        else {
            if required {
                panic!("OPENFDD_TEST_DATABASE_URL is required for the server request id fixture");
            }
            return;
        };
        let _env = crate::test_env_lock::lock_env();
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect(&url)
            .await
            .expect("server request id postgres");
        apply_schema(&pool).await.expect("ingest schema");

        let device = format!("device-{}", Uuid::new_v4());
        let tenant = "tenant-audit";
        let at = DateTime::parse_from_rfc3339("2026-10-19T12:00:00Z")
            .expect("window")
            .with_timezone(&Utc);
        let finish_at = at + chrono::Duration::minutes(65);
        let job = NewJob {
            tenant_id: tenant.into(),
            canonical_site: "site-audit".into(),
            provider_instance_id: "portal-audit".into(),
            device_id: device.clone(),
            model_revision: "rev-audit".into(),
            logical_window_start: at,
            logical_window_end: at + chrono::Duration::hours(1),
            shard: String::new(),
            not_before: at,
            estimated_cost: 1,
            requested_points_digest: None,
        };
        let ctx_a = crate::audit::RequestContext::new(Some("label-a"), "POST", "/api/ingest");
        let id_a = ctx_a.server_id.clone();
        let ctx_b = crate::audit::RequestContext::new(Some("label-b"), "POST", "/api/ingest");
        let id_b = ctx_b.server_id.clone();
        let created = crate::audit::with_request_context(ctx_a, async {
            match enqueue(&pool, &job).await.expect("enqueue") {
                EnqueueOutcome::Created(view) => view,
                EnqueueOutcome::Existing(_) => panic!("new job"),
            }
        })
        .await;
        assert_eq!(created.server_request_id.as_deref(), Some(id_a.as_str()));

        let existing = crate::audit::with_request_context(ctx_b.clone(), async {
            match enqueue(&pool, &job).await.expect("conflict enqueue") {
                EnqueueOutcome::Existing(view) => view,
                EnqueueOutcome::Created(_) => panic!("duplicate job"),
            }
        })
        .await;
        assert_eq!(existing.job_id, created.job_id);
        assert_eq!(existing.server_request_id.as_deref(), Some(id_a.as_str()));

        let bare = enqueue(
            &pool,
            &NewJob {
                device_id: format!("sched-{device}"),
                ..job.clone()
            },
        )
        .await
        .expect("scheduler enqueue");
        match bare {
            EnqueueOutcome::Created(view) => assert!(view.server_request_id.is_none()),
            EnqueueOutcome::Existing(_) => panic!("scheduler job"),
        }

        sqlx::query(
            "UPDATE ingest_job SET state = 'permanent_failure', safe_error_code = 'io'
             WHERE job_id = $1",
        )
        .bind(created.job_id.to_string())
        .execute(&pool)
        .await
        .expect("mark retryable");
        let actor = format!("actor-{}", Uuid::new_v4());
        let claim = IdempotencyClaim {
            actor: actor.clone(),
            tenant_id: tenant.into(),
            client_key: format!("key-{}", Uuid::new_v4()),
            object_id: retry_object_id(created.job_id),
            payload_hash: retry_payload_hash(tenant, created.job_id),
        };
        let retried = crate::audit::with_request_context(ctx_b, async {
            retry_job(&pool, created.job_id, finish_at, &claim)
                .await
                .expect("retry")
        })
        .await;
        assert_eq!(retried.server_request_id.as_deref(), Some(id_a.as_str()));
        let detail: serde_json::Value = sqlx::query_scalar(
            "SELECT detail FROM ingest_audit WHERE job_id = $1 AND action = 'retry'",
        )
        .bind(created.job_id.to_string())
        .fetch_one(&pool)
        .await
        .expect("audit row");
        assert_eq!(detail["server_request_id"], id_b);

        sqlx::query(
            "UPDATE ingest_job SET state = 'leased', lease_owner = 'worker',
                lease_expiry = $2, fencing_token = 1
             WHERE job_id = $1",
        )
        .bind(created.job_id.to_string())
        .bind(finish_at + chrono::Duration::minutes(5))
        .execute(&pool)
        .await
        .expect("lease");
        let receipt = finish(
            &pool,
            &FinishRequest::new(
                "worker",
                created.job_id,
                1,
                finish_at,
                FinishOutcome::committed_accounted(JobCounts::default()),
            ),
        )
        .await
        .expect("finish")
        .expect("receipt");
        assert_eq!(receipt.server_request_id.as_deref(), Some(id_a.as_str()));
        let loaded = get_receipt(&pool, receipt.receipt_id)
            .await
            .expect("load receipt")
            .expect("stored receipt");
        assert_eq!(loaded.server_request_id.as_deref(), Some(id_a.as_str()));

        sqlx::query("DELETE FROM ingest_receipt WHERE device_id = $1 OR device_id = $2")
            .bind(&device)
            .bind(format!("sched-{device}"))
            .execute(&pool)
            .await
            .expect("delete receipts");
        sqlx::query("DELETE FROM ingest_audit WHERE job_id = $1")
            .bind(created.job_id.to_string())
            .execute(&pool)
            .await
            .expect("delete audit");
        sqlx::query("DELETE FROM ingest_idempotency WHERE actor = $1")
            .bind(&actor)
            .execute(&pool)
            .await
            .expect("delete idempotency");
        sqlx::query("DELETE FROM ingest_job WHERE device_id = $1 OR device_id = $2")
            .bind(&device)
            .bind(format!("sched-{device}"))
            .execute(&pool)
            .await
            .expect("delete jobs");
    }

    /// Eight fresh connections apply ingest schema at once, then eight more
    /// apply the hourly-job schema. A second pass checks the lock still allows
    /// a later init. Each pass uses an empty database so `CREATE TABLE IF NOT
    /// EXISTS` takes the catalog path that races on `pg_type`.
    #[tokio::test(flavor = "multi_thread", worker_threads = 8)]
    async fn concurrent_schema_init_on_fresh_connections() {
        let Some(url) = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
        else {
            return;
        };
        let admin = maintenance_database_url(&url).expect("maintenance database url");
        for _ in 0..3 {
            let name = disposable_database_name();
            let _drop = DropDisposableDb {
                admin: admin.clone(),
                name: name.clone(),
            };
            create_disposable_database(&admin, &name).await;
            let fresh = database_url_for(&url, &name).expect("fresh database url");
            join_schema_inits(&fresh, 8, SchemaInit::Ingest).await;
            join_schema_inits(&fresh, 8, SchemaInit::Hourly).await;
            assert_schema_objects(&fresh).await;
            join_schema_inits(&fresh, 8, SchemaInit::Ingest).await;
            join_schema_inits(&fresh, 8, SchemaInit::Hourly).await;
        }
    }

    #[derive(Clone, Copy)]
    enum SchemaInit {
        Ingest,
        Hourly,
    }

    fn disposable_database_name() -> String {
        format!("schemarace{}", Uuid::new_v4().simple())
    }

    fn is_disposable_database_name(name: &str) -> bool {
        let Some(rest) = name.strip_prefix("schemarace") else {
            return false;
        };
        !rest.is_empty()
            && rest
                .chars()
                .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit())
    }

    fn maintenance_database_url(database_url: &str) -> Option<String> {
        let mut url = url::Url::parse(database_url).ok()?;
        url.set_path("/postgres");
        Some(url.to_string())
    }

    fn database_url_for(database_url: &str, name: &str) -> Option<String> {
        if !is_disposable_database_name(name) {
            return None;
        }
        let mut url = url::Url::parse(database_url).ok()?;
        url.set_path(&format!("/{name}"));
        Some(url.to_string())
    }

    async fn create_disposable_database(admin: &str, name: &str) {
        assert!(
            is_disposable_database_name(name),
            "refusing to create a database whose name is not a generated schema-race id"
        );
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect(admin)
            .await
            .expect("admin connection");
        let sql = format!("CREATE DATABASE {name}");
        sqlx::query(&sql)
            .execute(&pool)
            .await
            .expect("create disposable database");
    }

    async fn join_schema_inits(url: &str, workers: usize, kind: SchemaInit) {
        let mut pools = Vec::with_capacity(workers);
        for _ in 0..workers {
            pools.push(
                sqlx::postgres::PgPoolOptions::new()
                    .max_connections(1)
                    .connect(url)
                    .await
                    .expect("fresh schema connection"),
            );
        }
        let barrier = std::sync::Arc::new(tokio::sync::Barrier::new(workers));
        let mut tasks = Vec::with_capacity(workers);
        for pool in pools {
            let barrier = std::sync::Arc::clone(&barrier);
            tasks.push(tokio::spawn(async move {
                barrier.wait().await;
                match kind {
                    SchemaInit::Ingest => {
                        apply_schema(&pool).await.map_err(|err| format!("{err:?}"))
                    }
                    SchemaInit::Hourly => crate::providers::pg_store::ensure_schema(&pool).await,
                }
            }));
        }
        for task in tasks {
            let result = task.await.expect("schema init task");
            result.unwrap_or_else(|err| panic!("concurrent schema init failed: {err}"));
        }
    }

    async fn assert_schema_objects(url: &str) {
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(1)
            .connect(url)
            .await
            .expect("assert connection");
        for relation in [
            "public.ingest_applied_sample",
            "public.ingest_applied_sample_horizon",
            "public.ingest_audit",
            "public.ingest_coverage_cursor",
            "public.ingest_scheduler_lease",
            "public.provider_hourly_job",
        ] {
            let reg: Option<String> = sqlx::query_scalar("SELECT to_regclass($1)::text")
                .bind(relation)
                .fetch_one(&pool)
                .await
                .expect("relation lookup");
            assert!(
                reg.is_some(),
                "{relation} missing after concurrent schema init"
            );
        }
    }

    struct DropDisposableDb {
        admin: String,
        name: String,
    }

    impl Drop for DropDisposableDb {
        fn drop(&mut self) {
            let admin = self.admin.clone();
            let name = self.name.clone();
            if !is_disposable_database_name(&name) {
                return;
            }
            let _ = std::thread::spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("drop runtime");
                runtime.block_on(async move {
                    let Ok(pool) = sqlx::postgres::PgPoolOptions::new()
                        .max_connections(1)
                        .connect(&admin)
                        .await
                    else {
                        return;
                    };
                    let sql = format!("DROP DATABASE IF EXISTS {name} WITH (FORCE)");
                    let _ = sqlx::query(&sql).execute(&pool).await;
                });
            })
            .join();
        }
    }
}
