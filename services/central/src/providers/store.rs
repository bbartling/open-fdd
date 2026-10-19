//! Durable hourly job queue.
//!
//! Postgres is the product store. Process memory is the fixture store and the
//! explicit non-durable fallback when `OPENFDD_DATABASE_URL` is unset.
//! Claim uses a fencing token. A worker whose lease expired cannot commit.
//! Multi-replica autoscaling is not this module (N8).

use std::collections::HashMap;
use std::sync::Arc;

use chrono::{DateTime, Duration, Utc};
use sha2::{Digest, Sha256};
use tokio::sync::Mutex;

use super::hourly::{fair_windows, LogicalWindow};

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct CheckpointKey {
    pub tenant: String,
    pub canonical_site: String,
    pub provider_instance: String,
    pub device_id: String,
    pub model_revision: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JobState {
    Queued,
    Leased,
    RetryWait,
    Committed,
    Partial,
    PermanentFailure,
    Cancelled,
}

impl JobState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Leased => "leased",
            Self::RetryWait => "retry_wait",
            Self::Committed => "committed",
            Self::Partial => "partial",
            Self::PermanentFailure => "permanent_failure",
            Self::Cancelled => "cancelled",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        Some(match raw {
            "queued" => Self::Queued,
            "leased" => Self::Leased,
            "retry_wait" => Self::RetryWait,
            "committed" => Self::Committed,
            "partial" => Self::Partial,
            "permanent_failure" => Self::PermanentFailure,
            "cancelled" => Self::Cancelled,
            _ => return None,
        })
    }

    pub fn claimable(self) -> bool {
        matches!(self, Self::Queued | Self::RetryWait | Self::Partial)
    }
}

#[derive(Debug, Clone)]
pub struct NewJob {
    pub tenant: String,
    pub canonical_site: String,
    pub provider_instance: String,
    pub device_id: String,
    pub model_revision: String,
    pub window_start: DateTime<Utc>,
    pub window_end: DateTime<Utc>,
    pub shard: i32,
    pub shard_count: i32,
    pub purpose: String,
    pub generation: i64,
    pub not_before: DateTime<Utc>,
    pub point_ids: Vec<String>,
}

impl NewJob {
    pub fn job_id(&self) -> String {
        let raw = format!(
            "{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}\u{1f}{}",
            self.tenant,
            self.canonical_site,
            self.provider_instance,
            self.device_id,
            self.model_revision,
            self.window_start.timestamp(),
            self.window_end.timestamp(),
            self.shard,
            self.purpose,
            self.generation
        );
        let mut hasher = Sha256::new();
        hasher.update(raw.as_bytes());
        hex::encode(hasher.finalize())
    }
}

#[derive(Debug, Clone)]
pub struct JobRecord {
    pub job_id: String,
    pub tenant: String,
    pub canonical_site: String,
    pub provider_instance: String,
    pub device_id: String,
    pub model_revision: String,
    pub window_start: DateTime<Utc>,
    pub window_end: DateTime<Utc>,
    pub shard: i32,
    pub shard_count: i32,
    pub purpose: String,
    pub generation: i64,
    pub state: JobState,
    pub attempt: i32,
    pub not_before: Option<DateTime<Utc>>,
    pub lease_owner: Option<String>,
    pub lease_expiry: Option<DateTime<Utc>>,
    pub fencing_token: i64,
    pub point_ids: Vec<String>,
    pub fetched_count: i32,
    pub accepted_count: i32,
    pub rejected_count: i32,
    pub overlap_count: i32,
    pub writer_acknowledged: i32,
    pub received_at: Option<DateTime<Utc>>,
    pub committed_at: Option<DateTime<Utc>>,
    pub safe_error_code: Option<String>,
    pub receipt_id: Option<String>,
}

impl JobRecord {
    fn window(&self) -> LogicalWindow {
        LogicalWindow {
            start: self.window_start,
            end: self.window_end,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ReceiptDraft {
    pub receipt_id: String,
    pub job_id: String,
    pub outcome: String,
    pub fetched_count: i32,
    pub accepted_count: i32,
    pub rejected_count: i32,
    pub overlap_count: i32,
    pub writer_acknowledged: i32,
    pub safe_code: String,
}

#[derive(Debug, Clone)]
pub struct GapDraft {
    pub tenant: String,
    pub canonical_site: String,
    pub provider_instance: String,
    pub device_id: String,
    pub model_revision: String,
    pub window_start: DateTime<Utc>,
    pub window_end: DateTime<Utc>,
    pub reason: String,
    pub recoverability: String,
}

impl GapDraft {
    fn gap_id(&self) -> String {
        let raw = format!(
            "{}|{}|{}|{}|{}|{}|{}",
            self.tenant,
            self.canonical_site,
            self.provider_instance,
            self.device_id,
            self.model_revision,
            self.window_start.timestamp(),
            self.reason
        );
        let mut hasher = Sha256::new();
        hasher.update(raw.as_bytes());
        hex::encode(hasher.finalize())
    }
}

#[derive(Debug, Clone)]
pub struct CommitPatch {
    pub receipt: ReceiptDraft,
    pub now: DateTime<Utc>,
}

#[derive(Debug, Clone)]
pub struct FailPatch {
    pub now: DateTime<Utc>,
    pub state: JobState,
    pub not_before: Option<DateTime<Utc>>,
    pub safe_error_code: String,
    pub gap: Option<GapDraft>,
}

#[derive(Clone)]
pub enum HourlyStore {
    Memory(Arc<Mutex<MemoryInner>>),
    Postgres(sqlx::PgPool),
}

pub enum StoreOpen {
    Durable(HourlyStore),
    MemoryOnly(HourlyStore),
    Unavailable,
}

impl HourlyStore {
    pub fn memory() -> Self {
        Self::Memory(Arc::new(Mutex::new(MemoryInner::default())))
    }

    pub fn is_durable(&self) -> bool {
        matches!(self, Self::Postgres(_))
    }

    pub async fn open_from_env() -> StoreOpen {
        let url = std::env::var("OPENFDD_DATABASE_URL")
            .ok()
            .filter(|s| !s.trim().is_empty());
        let Some(url) = url else {
            return StoreOpen::MemoryOnly(Self::memory());
        };
        let pool = match sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .acquire_timeout(std::time::Duration::from_secs(10))
            .connect(&url)
            .await
        {
            Ok(pool) => pool,
            Err(_) => return StoreOpen::Unavailable,
        };
        if super::pg_store::ensure_schema(&pool).await.is_err() {
            return StoreOpen::Unavailable;
        }
        StoreOpen::Durable(Self::Postgres(pool))
    }

    pub async fn checkpoint(&self, key: &CheckpointKey) -> Result<Option<DateTime<Utc>>, String> {
        match self {
            Self::Memory(inner) => Ok(inner.lock().await.checkpoint(key)),
            Self::Postgres(pool) => super::pg_store::checkpoint(pool, key).await,
        }
    }

    pub async fn put_checkpoint(
        &self,
        key: &CheckpointKey,
        contiguous_end: DateTime<Utc>,
    ) -> Result<(), String> {
        match self {
            Self::Memory(inner) => {
                inner.lock().await.put_checkpoint(key, contiguous_end);
                Ok(())
            }
            Self::Postgres(pool) => {
                super::pg_store::put_checkpoint(pool, key, contiguous_end).await
            }
        }
    }

    pub async fn insert_job_if_absent(&self, job: &NewJob) -> Result<bool, String> {
        match self {
            Self::Memory(inner) => Ok(inner.lock().await.insert_job_if_absent(job)),
            Self::Postgres(pool) => super::pg_store::insert_job_if_absent(pool, job).await,
        }
    }

    pub async fn hourly_committed(
        &self,
        key: &CheckpointKey,
        window: LogicalWindow,
        shard_count: i32,
    ) -> Result<bool, String> {
        match self {
            Self::Memory(inner) => {
                Ok(inner
                    .lock()
                    .await
                    .hourly_committed(key, window, shard_count))
            }
            Self::Postgres(pool) => {
                super::pg_store::hourly_committed(pool, key, window, shard_count).await
            }
        }
    }

    pub async fn shard_count_for(
        &self,
        key: &CheckpointKey,
        window: LogicalWindow,
    ) -> Result<i32, String> {
        match self {
            Self::Memory(inner) => Ok(inner.lock().await.shard_count_for(key, window)),
            Self::Postgres(pool) => super::pg_store::shard_count_for(pool, key, window).await,
        }
    }

    pub async fn claim(
        &self,
        canonical_site: &str,
        now: DateTime<Utc>,
        limit: usize,
        owner: &str,
        lease: Duration,
    ) -> Result<Vec<JobRecord>, String> {
        match self {
            Self::Memory(inner) => {
                Ok(inner
                    .lock()
                    .await
                    .claim(canonical_site, now, limit, owner, lease))
            }
            Self::Postgres(pool) => {
                super::pg_store::claim(pool, canonical_site, now, limit, owner, lease).await
            }
        }
    }

    pub async fn commit(
        &self,
        job_id: &str,
        token: i64,
        owner: &str,
        patch: &CommitPatch,
    ) -> Result<bool, String> {
        match self {
            Self::Memory(inner) => Ok(inner.lock().await.commit(job_id, token, owner, patch)),
            Self::Postgres(pool) => {
                super::pg_store::commit(pool, job_id, token, owner, patch).await
            }
        }
    }

    pub async fn fail(
        &self,
        job_id: &str,
        token: i64,
        owner: &str,
        patch: &FailPatch,
    ) -> Result<bool, String> {
        match self {
            Self::Memory(inner) => Ok(inner.lock().await.fail(job_id, token, owner, patch)),
            Self::Postgres(pool) => super::pg_store::fail(pool, job_id, token, owner, patch).await,
        }
    }

    pub async fn insert_gap(&self, gap: &GapDraft) -> Result<(), String> {
        match self {
            Self::Memory(inner) => {
                inner.lock().await.insert_gap(gap);
                Ok(())
            }
            Self::Postgres(pool) => super::pg_store::insert_gap(pool, gap).await,
        }
    }

    pub async fn ledger_snapshot(
        &self,
        canonical_site: &str,
        since: DateTime<Utc>,
        limit: i64,
    ) -> Result<LedgerSnapshot, String> {
        let limit = limit.clamp(1, 2_000);
        match self {
            Self::Memory(inner) => {
                Ok(inner
                    .lock()
                    .await
                    .ledger_snapshot(canonical_site, since, limit))
            }
            Self::Postgres(pool) => {
                super::pg_store::ledger_snapshot(pool, canonical_site, since, limit).await
            }
        }
    }

    pub async fn gap_count(&self, canonical_site: &str) -> Result<u32, String> {
        match self {
            Self::Memory(inner) => Ok(inner.lock().await.gap_count(canonical_site)),
            Self::Postgres(pool) => super::pg_store::gap_count(pool, canonical_site).await,
        }
    }

    pub async fn cancel_stale(
        &self,
        canonical_site: &str,
        provider_instance: &str,
        active: &[(String, String)],
    ) -> Result<u32, String> {
        match self {
            Self::Memory(inner) => {
                Ok(inner
                    .lock()
                    .await
                    .cancel_stale(canonical_site, provider_instance, active))
            }
            Self::Postgres(pool) => {
                super::pg_store::cancel_stale(pool, canonical_site, provider_instance, active).await
            }
        }
    }

    #[cfg(test)]
    pub async fn list_jobs(&self, canonical_site: &str) -> Result<Vec<JobRecord>, String> {
        match self {
            Self::Memory(inner) => Ok(inner.lock().await.list_jobs(canonical_site)),
            Self::Postgres(pool) => super::pg_store::list_jobs(pool, canonical_site).await,
        }
    }
}

#[derive(Debug, Clone)]
pub struct LedgerSnapshot {
    pub jobs: Vec<JobRecord>,
    pub gaps: Vec<GapDraft>,
    pub receipts: Vec<ReceiptDraft>,
    pub truncated: bool,
}

#[derive(Debug, Default)]
pub struct MemoryInner {
    jobs: HashMap<String, JobRecord>,
    checkpoints: HashMap<CheckpointKey, DateTime<Utc>>,
    receipts: HashMap<String, ReceiptDraft>,
    gaps: HashMap<String, GapDraft>,
}

impl MemoryInner {
    fn checkpoint(&self, key: &CheckpointKey) -> Option<DateTime<Utc>> {
        self.checkpoints.get(key).copied()
    }

    fn put_checkpoint(&mut self, key: &CheckpointKey, contiguous_end: DateTime<Utc>) {
        self.checkpoints.insert(key.clone(), contiguous_end);
    }

    fn insert_job_if_absent(&mut self, job: &NewJob) -> bool {
        let job_id = job.job_id();
        if self.jobs.contains_key(&job_id) {
            return false;
        }
        self.jobs.insert(
            job_id.clone(),
            JobRecord {
                job_id,
                tenant: job.tenant.clone(),
                canonical_site: job.canonical_site.clone(),
                provider_instance: job.provider_instance.clone(),
                device_id: job.device_id.clone(),
                model_revision: job.model_revision.clone(),
                window_start: job.window_start,
                window_end: job.window_end,
                shard: job.shard,
                shard_count: job.shard_count,
                purpose: job.purpose.clone(),
                generation: job.generation,
                state: JobState::Queued,
                attempt: 0,
                not_before: Some(job.not_before),
                lease_owner: None,
                lease_expiry: None,
                fencing_token: 0,
                point_ids: job.point_ids.clone(),
                fetched_count: 0,
                accepted_count: 0,
                rejected_count: 0,
                overlap_count: 0,
                writer_acknowledged: 0,
                received_at: None,
                committed_at: None,
                safe_error_code: None,
                receipt_id: None,
            },
        );
        true
    }

    fn hourly_committed(
        &self,
        key: &CheckpointKey,
        window: LogicalWindow,
        shard_count: i32,
    ) -> bool {
        if shard_count <= 0 {
            return false;
        }
        (0..shard_count).all(|shard| {
            self.jobs.values().any(|job| {
                same_scope(job, key)
                    && job.purpose == "hourly"
                    && job.generation == 0
                    && job.shard == shard
                    && job.window_start == window.start
                    && job.window_end == window.end
                    && job.state == JobState::Committed
            })
        })
    }

    fn shard_count_for(&self, key: &CheckpointKey, window: LogicalWindow) -> i32 {
        self.jobs
            .values()
            .find(|job| {
                same_scope(job, key)
                    && job.purpose == "hourly"
                    && job.generation == 0
                    && job.window_start == window.start
                    && job.window_end == window.end
            })
            .map(|job| job.shard_count)
            .unwrap_or(0)
    }

    fn claim(
        &mut self,
        canonical_site: &str,
        now: DateTime<Utc>,
        limit: usize,
        owner: &str,
        lease: Duration,
    ) -> Vec<JobRecord> {
        let mut ready: Vec<JobRecord> = self
            .jobs
            .values()
            .filter(|job| job.canonical_site == canonical_site && ready_at(job, now))
            .cloned()
            .collect();
        ready.sort_by_key(|job| (job.window_start, job.shard, job.purpose.clone()));
        let chosen_ids = plan_claim_ids(&ready, limit);
        let expiry = now + lease;
        for job_id in &chosen_ids {
            if let Some(stored) = self.jobs.get_mut(job_id) {
                stored.state = JobState::Leased;
                stored.attempt = stored.attempt.saturating_add(1);
                stored.lease_owner = Some(owner.to_string());
                stored.lease_expiry = Some(expiry);
                stored.fencing_token = stored.fencing_token.saturating_add(1);
            }
        }
        chosen_ids
            .iter()
            .filter_map(|job_id| self.jobs.get(job_id).cloned())
            .collect()
    }

    fn commit(&mut self, job_id: &str, token: i64, owner: &str, patch: &CommitPatch) -> bool {
        let Some(job) = self.jobs.get(job_id) else {
            return false;
        };
        if !fence_holds(job, token, owner, patch.now) {
            return false;
        }
        let job = self.jobs.get_mut(job_id).expect("job present");
        job.state = JobState::Committed;
        job.fetched_count = patch.receipt.fetched_count;
        job.accepted_count = patch.receipt.accepted_count;
        job.rejected_count = patch.receipt.rejected_count;
        job.overlap_count = patch.receipt.overlap_count;
        job.writer_acknowledged = patch.receipt.writer_acknowledged;
        job.received_at = Some(patch.now);
        job.committed_at = Some(patch.now);
        job.safe_error_code = None;
        job.receipt_id = Some(patch.receipt.receipt_id.clone());
        job.lease_owner = None;
        job.lease_expiry = None;
        self.receipts
            .insert(patch.receipt.receipt_id.clone(), patch.receipt.clone());
        true
    }

    fn fail(&mut self, job_id: &str, token: i64, owner: &str, patch: &FailPatch) -> bool {
        let Some(job) = self.jobs.get(job_id) else {
            return false;
        };
        if !fence_holds(job, token, owner, patch.now) {
            return false;
        }
        let job = self.jobs.get_mut(job_id).expect("job present");
        job.state = patch.state;
        job.not_before = patch.not_before;
        job.safe_error_code = Some(patch.safe_error_code.clone());
        job.received_at = Some(patch.now);
        job.lease_owner = None;
        job.lease_expiry = None;
        if let Some(gap) = &patch.gap {
            let id = gap.gap_id();
            self.gaps.entry(id).or_insert_with(|| gap.clone());
        }
        true
    }

    fn insert_gap(&mut self, gap: &GapDraft) {
        self.gaps.entry(gap.gap_id()).or_insert_with(|| gap.clone());
    }

    fn ledger_snapshot(
        &self,
        canonical_site: &str,
        since: DateTime<Utc>,
        limit: i64,
    ) -> LedgerSnapshot {
        let limit = usize::try_from(limit).unwrap_or(2_000);
        let mut jobs: Vec<JobRecord> = self
            .jobs
            .values()
            .filter(|job| job.canonical_site == canonical_site && job.window_start >= since)
            .cloned()
            .collect();
        jobs.sort_by(|a, b| {
            b.window_start
                .cmp(&a.window_start)
                .then(a.job_id.cmp(&b.job_id))
        });
        let jobs_truncated = jobs.len() > limit;
        jobs.truncate(limit);
        let ids: std::collections::HashSet<&str> =
            jobs.iter().map(|job| job.job_id.as_str()).collect();
        let receipts = self
            .receipts
            .values()
            .filter(|receipt| ids.contains(receipt.job_id.as_str()))
            .cloned()
            .collect();
        let mut gaps: Vec<GapDraft> = self
            .gaps
            .values()
            .filter(|gap| gap.canonical_site == canonical_site && gap.window_start >= since)
            .cloned()
            .collect();
        gaps.sort_by_key(|gap| std::cmp::Reverse(gap.window_start));
        let gaps_truncated = gaps.len() > limit;
        gaps.truncate(limit);
        LedgerSnapshot {
            jobs,
            gaps,
            receipts,
            truncated: jobs_truncated || gaps_truncated,
        }
    }

    fn gap_count(&self, canonical_site: &str) -> u32 {
        u32::try_from(
            self.gaps
                .values()
                .filter(|gap| gap.canonical_site == canonical_site)
                .count(),
        )
        .unwrap_or(u32::MAX)
    }

    fn cancel_stale(
        &mut self,
        canonical_site: &str,
        provider_instance: &str,
        active: &[(String, String)],
    ) -> u32 {
        let mut n = 0u32;
        for job in self.jobs.values_mut() {
            if job.canonical_site != canonical_site || job.provider_instance != provider_instance {
                continue;
            }
            if !job.state.claimable() && job.state != JobState::Leased {
                continue;
            }
            let live = active
                .iter()
                .any(|(device, rev)| device == &job.device_id && rev == &job.model_revision);
            if live {
                continue;
            }
            job.state = JobState::Cancelled;
            job.lease_owner = None;
            job.lease_expiry = None;
            job.safe_error_code = Some("model_revision_changed".into());
            n = n.saturating_add(1);
        }
        n
    }

    #[cfg(test)]
    fn list_jobs(&self, canonical_site: &str) -> Vec<JobRecord> {
        let mut jobs: Vec<_> = self
            .jobs
            .values()
            .filter(|job| job.canonical_site == canonical_site)
            .cloned()
            .collect();
        jobs.sort_by_key(|job| {
            (
                job.window_start,
                job.shard,
                job.purpose.clone(),
                job.generation,
            )
        });
        jobs
    }
}

fn same_scope(job: &JobRecord, key: &CheckpointKey) -> bool {
    job.tenant == key.tenant
        && job.canonical_site == key.canonical_site
        && job.provider_instance == key.provider_instance
        && job.device_id == key.device_id
        && job.model_revision == key.model_revision
}

fn ready_at(job: &JobRecord, now: DateTime<Utc>) -> bool {
    if job.state.claimable() {
        return job.not_before.map(|t| t <= now).unwrap_or(true);
    }
    job.state == JobState::Leased && job.lease_expiry.map(|t| t <= now).unwrap_or(false)
}

pub fn plan_claim_ids(ready: &[JobRecord], limit: usize) -> Vec<String> {
    if limit == 0 || ready.is_empty() {
        return Vec::new();
    }
    let windows: Vec<LogicalWindow> = ready.iter().map(JobRecord::window).collect();
    let picked_windows = fair_windows(&windows, limit);
    let mut chosen = Vec::new();
    for window in picked_windows {
        if let Some(job) = ready.iter().find(|job| {
            job.window() == window && !chosen.iter().any(|id: &String| id == &job.job_id)
        }) {
            chosen.push(job.job_id.clone());
        }
    }
    if chosen.len() < limit {
        for job in ready {
            if chosen.len() >= limit {
                break;
            }
            if !chosen.iter().any(|id| id == &job.job_id) {
                chosen.push(job.job_id.clone());
            }
        }
    }
    chosen
}

fn fence_holds(job: &JobRecord, token: i64, owner: &str, now: DateTime<Utc>) -> bool {
    job.state == JobState::Leased
        && job.fencing_token == token
        && job.lease_owner.as_deref() == Some(owner)
        && job.lease_expiry.map(|t| t > now).unwrap_or(false)
}

/// Ready-job selection shared with the Postgres claim. `LIMIT` is before
/// `FOR UPDATE SKIP LOCKED`. The statement does not call the portal.
pub fn claim_ready_sql(limit: usize, newest: bool) -> String {
    let order = if newest { "DESC" } else { "ASC" };
    let limit = limit.clamp(1, 64);
    format!(
        "SELECT job_id FROM provider_hourly_job \
         WHERE canonical_site = $1 AND ( \
           (state IN ('queued','retry_wait','partial') AND (not_before IS NULL OR not_before <= $2)) \
           OR (state = 'leased' AND lease_expiry IS NOT NULL AND lease_expiry <= $2) \
         ) ORDER BY window_start {order} LIMIT {limit} FOR UPDATE SKIP LOCKED"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn new_job(start: DateTime<Utc>, device: &str) -> NewJob {
        NewJob {
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: device.into(),
            model_revision: "rev-1".into(),
            window_start: start,
            window_end: start + Duration::seconds(3600),
            shard: 0,
            shard_count: 1,
            purpose: "hourly".into(),
            generation: 0,
            not_before: start,
            point_ids: vec!["p1".into()],
        }
    }

    fn ts(hour: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 19, hour, 0, 0).unwrap()
    }

    #[test]
    fn claim_sql_locks_rows_without_a_portal_call() {
        let sql = claim_ready_sql(64, false);
        assert!(sql.contains("LIMIT 64 FOR UPDATE SKIP LOCKED"));
        assert!(claim_ready_sql(1, true).contains("ORDER BY window_start DESC"));
        assert!(!sql.to_ascii_lowercase().contains("point/data"));
    }

    #[tokio::test]
    async fn duplicate_enqueue_is_unique_and_stale_fence_cannot_commit() {
        let store = HourlyStore::memory();
        let job = new_job(ts(9), "dev-1");
        assert!(store.insert_job_if_absent(&job).await.unwrap());
        assert!(!store.insert_job_if_absent(&job).await.unwrap());
        let now = ts(12);
        let claimed = store
            .claim("site-a", now, 4, "worker-a", Duration::seconds(120))
            .await
            .unwrap();
        assert_eq!(claimed.len(), 1);
        let token = claimed[0].fencing_token;
        let later = now + Duration::seconds(121);
        let reclaimed = store
            .claim("site-a", later, 4, "worker-b", Duration::seconds(120))
            .await
            .unwrap();
        assert_eq!(reclaimed.len(), 1);
        assert_ne!(reclaimed[0].fencing_token, token);
        let stale = CommitPatch {
            now: later,
            receipt: ReceiptDraft {
                receipt_id: "r-stale".into(),
                job_id: claimed[0].job_id.clone(),
                outcome: "samples".into(),
                fetched_count: 1,
                accepted_count: 1,
                rejected_count: 0,
                overlap_count: 0,
                writer_acknowledged: 1,
                safe_code: "samples".into(),
            },
        };
        assert!(!store
            .commit(&claimed[0].job_id, token, "worker-a", &stale)
            .await
            .unwrap());
        let fresh = CommitPatch {
            receipt: ReceiptDraft {
                receipt_id: "r-ok".into(),
                ..stale.receipt.clone()
            },
            ..stale
        };
        assert!(store
            .commit(
                &reclaimed[0].job_id,
                reclaimed[0].fencing_token,
                "worker-b",
                &fresh
            )
            .await
            .unwrap());
        let jobs = store.list_jobs("site-a").await.unwrap();
        assert_eq!(jobs[0].state, JobState::Committed);
        assert_eq!(jobs[0].receipt_id.as_deref(), Some("r-ok"));
    }

    #[tokio::test]
    async fn expired_lease_cannot_commit_before_reclaim() {
        let store = HourlyStore::memory();
        let job = new_job(ts(9), "dev-1");
        store.insert_job_if_absent(&job).await.unwrap();
        let now = ts(12);
        let claimed = store
            .claim("site-a", now, 1, "worker-a", Duration::seconds(30))
            .await
            .unwrap();
        let patch = CommitPatch {
            now: now + Duration::seconds(31),
            receipt: ReceiptDraft {
                receipt_id: "r".into(),
                job_id: claimed[0].job_id.clone(),
                outcome: "samples".into(),
                fetched_count: 1,
                accepted_count: 1,
                rejected_count: 0,
                overlap_count: 0,
                writer_acknowledged: 1,
                safe_code: "samples".into(),
            },
        };
        assert!(!store
            .commit(
                &claimed[0].job_id,
                claimed[0].fencing_token,
                "worker-a",
                &patch
            )
            .await
            .unwrap());
        let jobs = store.list_jobs("site-a").await.unwrap();
        assert_eq!(jobs[0].state, JobState::Leased);
    }

    #[tokio::test]
    async fn ledger_snapshot_is_bounded_to_the_site_window() {
        let store = HourlyStore::memory();
        store
            .insert_job_if_absent(&new_job(ts(8), "dev-1"))
            .await
            .unwrap();
        store
            .insert_job_if_absent(&new_job(ts(12), "dev-1"))
            .await
            .unwrap();
        let other = NewJob {
            canonical_site: "site-b".into(),
            ..new_job(ts(12), "dev-1")
        };
        store.insert_job_if_absent(&other).await.unwrap();
        let snap = store.ledger_snapshot("site-a", ts(10), 10).await.unwrap();
        assert!(!snap.truncated);
        assert_eq!(snap.jobs.len(), 1);
        assert_eq!(snap.jobs[0].window_start, ts(12));
        let tight = store.ledger_snapshot("site-a", ts(1), 1).await.unwrap();
        assert!(tight.truncated);
        assert_eq!(tight.jobs.len(), 1);
    }
}
