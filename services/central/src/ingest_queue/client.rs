//! Process-local handle. Postgres is required before replicas run workers.

use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tokio::sync::Mutex;
use uuid::Uuid;

use super::cursor::{self, CoverageCursor, CursorKey};
use super::memory::MemoryStore;
use super::model::*;
use super::postgres;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Coordination {
    Postgres,
    ExplicitMemory,
    Unavailable,
}

#[derive(Clone)]
pub struct QueueClient {
    memory: Arc<MemoryStore>,
    postgres: Arc<Mutex<Option<PgPool>>>,
    budget: BudgetDefaults,
    catchup: super::catchup_registry::SharedCatchupRegistry,
}

impl QueueClient {
    pub fn memory() -> Self {
        let budget = budget_from_env();
        Self {
            memory: Arc::new(MemoryStore::new(budget)),
            postgres: Arc::new(Mutex::new(None)),
            budget,
            catchup: super::catchup_registry::shared_registry(),
        }
    }

    pub fn catchup_registry(&self) -> super::catchup_registry::SharedCatchupRegistry {
        Arc::clone(&self.catchup)
    }

    pub fn coordination() -> Coordination {
        if database_url_present() {
            Coordination::Postgres
        } else if explicit_memory() {
            Coordination::ExplicitMemory
        } else {
            Coordination::Unavailable
        }
    }

    pub async fn enqueue(
        &self,
        job: NewJob,
        now: DateTime<Utc>,
    ) -> Result<EnqueueOutcome, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::enqueue(&pool, &job).await;
        }
        self.memory.enqueue(job, now)
    }

    pub async fn try_scheduler(
        &self,
        owner: &str,
        now: DateTime<Utc>,
        ttl: chrono::Duration,
    ) -> Result<Option<SchedulerGrant>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::try_scheduler(&pool, owner, now, ttl).await;
        }
        Ok(self.memory.try_scheduler(owner, now, ttl))
    }

    pub async fn renew_scheduler(
        &self,
        owner: &str,
        token: u64,
        now: DateTime<Utc>,
        ttl: chrono::Duration,
    ) -> Result<bool, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::renew_scheduler(&pool, owner, token, now, ttl).await;
        }
        Ok(self.memory.renew_scheduler(owner, token, now, ttl))
    }

    pub async fn portal_budget_status(
        &self,
        provider_instance_id: &str,
        now: DateTime<Utc>,
    ) -> Result<super::postgres::PortalBudgetStatus, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::portal_budget_status(&pool, provider_instance_id, now).await;
        }
        self.memory.portal_budget_status(provider_instance_id, now)
    }

    pub async fn note_throttle(
        &self,
        provider_instance_id: &str,
        now: DateTime<Utc>,
        retry_after: chrono::Duration,
    ) -> Result<(), QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::note_throttle(
                &pool,
                provider_instance_id,
                now,
                retry_after,
                self.budget,
            )
            .await;
        }
        self.memory
            .note_throttle(provider_instance_id, now, retry_after);
        Ok(())
    }

    pub async fn claim(&self, req: &ClaimRequest) -> Result<Vec<JobView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::claim(&pool, req, self.budget).await;
        }
        Ok(self.memory.claim(req))
    }

    pub async fn finish(&self, req: &FinishRequest) -> Result<Option<ReceiptView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::finish(&pool, req).await;
        }
        self.memory.finish(req)
    }

    pub async fn apply_samples(
        &self,
        job: &JobView,
        samples: &[AppliedSample],
    ) -> Result<ApplyStats, QueueError> {
        if samples.len() > super::coverage::MAX_TIMESTAMPS {
            return Err(QueueError::Invalid("payload_bound".into()));
        }
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::apply_samples(&pool, job, samples).await;
        }
        self.memory.apply_samples(job, samples)
    }

    /// Fenced canonical write for one claimed window. `None` when the queue is
    /// process memory: there is no shared database to fence against.
    pub async fn commit_window(
        &self,
        job: &JobView,
        now: DateTime<Utc>,
        window: &postgres::CanonicalWindow<'_>,
    ) -> Result<Option<postgres::WindowWrite>, QueueError> {
        if window.applied.len() > super::coverage::MAX_TIMESTAMPS {
            return Err(QueueError::Invalid("payload_bound".into()));
        }
        match self.pool_if_configured().await? {
            Some(pool) => postgres::commit_window(&pool, job, now, window)
                .await
                .map(Some),
            None => Ok(None),
        }
    }

    /// Recompute the verified-coverage cursor for one device revision.
    pub async fn advance_cursor(
        &self,
        key: &CursorKey,
        now: DateTime<Utc>,
    ) -> Result<Option<CoverageCursor>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return cursor::advance_postgres(&pool, key, now).await;
        }
        Ok(self.memory.advance_cursor(key, now))
    }

    /// Stored verified-coverage cursors for one tenant site.
    pub async fn list_cursors(
        &self,
        tenant_id: &str,
        canonical_site: &str,
    ) -> Result<Vec<CoverageCursor>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return cursor::list_postgres(&pool, tenant_id, canonical_site).await;
        }
        Ok(self.memory.list_cursors(tenant_id, canonical_site))
    }

    pub async fn list_jobs(&self, filter: &ListFilter) -> Result<Vec<JobView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::list_jobs(&pool, filter).await;
        }
        Ok(self.memory.list_jobs(filter))
    }

    pub async fn get_job(&self, job_id: Uuid) -> Result<Option<JobView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::get_job(&pool, job_id).await;
        }
        Ok(self.memory.get_job(job_id))
    }

    pub async fn list_receipts(&self, filter: &ListFilter) -> Result<Vec<ReceiptView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::list_receipts(&pool, filter).await;
        }
        Ok(self.memory.list_receipts(filter))
    }

    pub async fn get_receipt(&self, receipt_id: Uuid) -> Result<Option<ReceiptView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::get_receipt(&pool, receipt_id).await;
        }
        Ok(self.memory.get_receipt(receipt_id))
    }

    pub async fn list_gaps(&self, filter: &ListFilter) -> Result<Vec<JobView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::list_gaps(&pool, filter).await;
        }
        Ok(self.memory.list_gaps(filter))
    }

    pub fn budget_defaults(&self) -> BudgetDefaults {
        self.budget
    }

    pub async fn metrics(
        &self,
        now: DateTime<Utc>,
        scope: &MetricsScope,
    ) -> Result<QueueMetrics, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::metrics(&pool, now, scope).await;
        }
        Ok(self.memory.metrics(now, scope))
    }

    pub async fn retry_job(
        &self,
        job_id: Uuid,
        now: DateTime<Utc>,
        claim: &IdempotencyClaim,
    ) -> Result<JobView, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::retry_job(&pool, job_id, now, claim).await;
        }
        self.memory.retry_job(job_id, now, claim)
    }

    pub async fn cancel_jobs(
        &self,
        filter: CancelFilter,
        now: DateTime<Utc>,
        claim: &IdempotencyClaim,
    ) -> Result<CancelOutcome, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::cancel_jobs(&pool, &filter, now, claim).await;
        }
        self.memory.cancel_jobs(&filter, now, claim)
    }

    pub async fn backfill(
        &self,
        jobs: Vec<NewJob>,
        now: DateTime<Utc>,
        claim: &IdempotencyClaim,
    ) -> Result<Vec<JobView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::backfill(&pool, &jobs, now, claim).await;
        }
        self.memory.backfill(jobs, now, claim)
    }

    pub async fn site_backfill(
        &self,
        jobs: Vec<NewJob>,
        range_start: DateTime<Utc>,
        range_end: DateTime<Utc>,
        now: DateTime<Utc>,
        claim: &IdempotencyClaim,
    ) -> Result<Vec<JobView>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::site_backfill(&pool, &jobs, range_start, range_end, now, claim).await;
        }
        self.memory
            .site_backfill(jobs, range_start, range_end, now, claim)
    }

    pub async fn prune_applied_samples(
        &self,
        tenant_id: &str,
        canonical_site: &str,
        now: DateTime<Utc>,
        retention: chrono::Duration,
    ) -> Result<super::replay_horizon::PruneReport, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            return postgres::prune_applied_samples(
                &pool,
                tenant_id,
                canonical_site,
                now,
                retention,
            )
            .await;
        }
        Ok(self
            .memory
            .prune_applied_samples(tenant_id, canonical_site, now, retention))
    }

    pub async fn postgres_pool(&self) -> Result<Option<PgPool>, QueueError> {
        self.pool_if_configured().await
    }

    pub async fn provider_data_start_for_job(
        &self,
        job: &JobView,
    ) -> Result<Option<DateTime<Utc>>, QueueError> {
        if let Some(pool) = self.pool_if_configured().await? {
            let key = super::binding_state::DeviceBindingKey::from_job(job);
            return Ok(super::binding_state::load_binding_state(&pool, &key)
                .await?
                .and_then(|row| row.provider_data_start));
        }
        Ok(None)
    }

    pub async fn learn_provider_data_start_from_samples(
        &self,
        job: &JobView,
        samples: &[AppliedSample],
        now: DateTime<Utc>,
    ) -> Result<(), QueueError> {
        if samples.is_empty() {
            return Ok(());
        }
        let mut earliest = samples[0].ts;
        for sample in samples.iter().skip(1) {
            if sample.ts < earliest {
                earliest = sample.ts;
            }
        }
        let Some(pool) = self.pool_if_configured().await? else {
            return Err(QueueError::Db(
                "shared ingest queue database is unavailable".into(),
            ));
        };
        let key = super::binding_state::DeviceBindingKey::from_job(job);
        super::binding_state::learn_provider_data_start(
            &pool,
            super::binding_state::LearnProviderDataStartInput {
                key: &key,
                candidate: earliest,
                now,
            },
        )
        .await?;
        Ok(())
    }

    async fn pool_if_configured(&self) -> Result<Option<PgPool>, QueueError> {
        if !database_url_present() {
            return Ok(None);
        }
        let mut guard = self.postgres.lock().await;
        if let Some(pool) = guard.clone() {
            return Ok(Some(pool));
        }
        let url = std::env::var("OPENFDD_DATABASE_URL")
            .map_err(|_| QueueError::Db("database url missing".into()))?;
        let pool = PgPoolOptions::new()
            .max_connections(queue_max_connections())
            .acquire_timeout(Duration::from_secs(5))
            .connect(url.trim())
            .await
            .map_err(|err| postgres_connect_err(&err))?;
        postgres::apply_schema(&pool).await?;
        *guard = Some(pool.clone());
        Ok(Some(pool))
    }
}

pub fn database_url_present() -> bool {
    std::env::var("OPENFDD_DATABASE_URL")
        .ok()
        .is_some_and(|value| !value.trim().is_empty())
}

fn explicit_memory() -> bool {
    std::env::var("OPENFDD_INGEST_QUEUE")
        .ok()
        .is_some_and(|value| value.trim().eq_ignore_ascii_case("memory"))
}

fn budget_from_env() -> BudgetDefaults {
    BudgetDefaults {
        max_in_flight: env_u32("OPENFDD_INGEST_PORTAL_MAX_IN_FLIGHT", 2).max(1),
        max_per_minute: env_u32("OPENFDD_INGEST_PORTAL_MAX_PER_MINUTE", 30).max(1),
    }
}

fn queue_max_connections() -> u32 {
    env_u32("OPENFDD_INGEST_QUEUE_MAX_CONNECTIONS", 4).clamp(1, 8)
}

fn env_u32(name: &str, default: u32) -> u32 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

fn postgres_connect_err(err: &sqlx::Error) -> QueueError {
    let mut text = err.to_string();
    if let Some(idx) = text.find("postgres://") {
        text.truncate(idx);
        text.push_str("postgres://redacted");
    }
    QueueError::Db(truncate_chars(&text, 180))
}
