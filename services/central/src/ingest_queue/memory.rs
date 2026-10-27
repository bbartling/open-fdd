//! In-process queue with the same lease, fence, and portal-budget rules as Postgres.
//!
//! Replica safety requires the Postgres backend. This store is the fixture for
//! multi-worker tests and the single-process `OPENFDD_INGEST_QUEUE=memory` mode.

use std::cmp::Reverse;
use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

use chrono::{DateTime, Utc};
use tracing::debug;
use uuid::Uuid;

use super::cursor::{walk, CoverageCursor, CursorKey, WindowState};
use super::model::*;

struct PortalBudget {
    max_in_flight: u32,
    max_per_minute: u32,
    tokens: u32,
    window_start: DateTime<Utc>,
    paused_until: Option<DateTime<Utc>>,
    cap_override: Option<u32>,
}

struct StoredJob {
    view: JobView,
    points_digest: Option<String>,
}

#[derive(Clone, PartialEq, Eq, Hash)]
struct AppliedKey {
    tenant_id: String,
    canonical_site: String,
    provider_instance_id: String,
    device_id: String,
    model_revision: String,
    point_id: String,
    ts: DateTime<Utc>,
}

#[derive(Clone, PartialEq, Eq, Hash)]
struct IdempotencyKey {
    actor: String,
    tenant_id: String,
    action: String,
    client_key: String,
}

struct IdempotencyRecord {
    object_id: String,
    payload_hash: String,
    job_ids: Vec<Uuid>,
}

struct Inner {
    jobs: Vec<StoredJob>,
    by_key: HashMap<JobKey, usize>,
    receipts: Vec<ReceiptView>,
    scheduler: Option<SchedulerGrant>,
    budgets: HashMap<String, PortalBudget>,
    defaults: BudgetDefaults,
    idempotency: HashMap<IdempotencyKey, IdempotencyRecord>,
    audit: VecDeque<AuditEvent>,
    applied: HashMap<AppliedKey, u64>,
    cursors: HashMap<CursorKey, CoverageCursor>,
}

#[derive(Clone)]
pub struct AuditEvent {
    pub actor: String,
    pub action: String,
    pub job_id: Option<Uuid>,
    pub idempotency_key: Option<String>,
}

pub struct MemoryStore {
    inner: Mutex<Inner>,
}

impl MemoryStore {
    pub fn new(defaults: BudgetDefaults) -> Self {
        Self {
            inner: Mutex::new(Inner {
                jobs: Vec::new(),
                by_key: HashMap::new(),
                receipts: Vec::new(),
                scheduler: None,
                budgets: HashMap::new(),
                defaults,
                idempotency: HashMap::new(),
                audit: VecDeque::new(),
                applied: HashMap::new(),
                cursors: HashMap::new(),
            }),
        }
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|err| err.into_inner())
    }

    pub fn enqueue(&self, job: NewJob, now: DateTime<Utc>) -> Result<EnqueueOutcome, QueueError> {
        let mut inner = self.lock();
        enqueue_locked(&mut inner, job, now)
    }

    pub fn try_scheduler(
        &self,
        owner: &str,
        now: DateTime<Utc>,
        ttl: chrono::Duration,
    ) -> Option<SchedulerGrant> {
        let mut inner = self.lock();
        let blocked = inner
            .scheduler
            .as_ref()
            .is_some_and(|lease| lease.expires_at > now && lease.owner != owner);
        if blocked {
            return None;
        }
        let token = match &inner.scheduler {
            Some(lease) if lease.owner == owner && lease.expires_at > now => lease.fencing_token,
            Some(lease) => lease.fencing_token.saturating_add(1),
            None => 1,
        };
        let grant = SchedulerGrant {
            owner: owner.to_string(),
            fencing_token: token,
            expires_at: now + ttl,
        };
        inner.scheduler = Some(grant.clone());
        Some(grant)
    }

    pub fn renew_scheduler(
        &self,
        owner: &str,
        token: u64,
        now: DateTime<Utc>,
        ttl: chrono::Duration,
    ) -> bool {
        let mut inner = self.lock();
        match inner.scheduler.as_mut() {
            Some(lease)
                if lease.owner == owner
                    && lease.fencing_token == token
                    && lease.expires_at > now =>
            {
                lease.expires_at = now + ttl;
                true
            }
            _ => false,
        }
    }

    pub fn claim(&self, req: &ClaimRequest) -> Vec<JobView> {
        let mut inner = self.lock();
        let mut claimed = Vec::new();
        let limit = req.limit.min(32);
        for _ in 0..limit {
            let Some(idx) = pick_candidate(&inner, req.now) else {
                break;
            };
            let portal = inner.jobs[idx].view.provider_instance_id.clone();
            if !budget_allows(&mut inner, &portal, req.now) {
                break;
            }
            consume_token(&mut inner, &portal, req.now);
            let job = &mut inner.jobs[idx].view;
            job.fencing_token = job.fencing_token.saturating_add(1);
            job.attempt = job.attempt.saturating_add(1);
            job.state = JobState::Leased.as_str().to_string();
            job.lease_owner = Some(req.owner.clone());
            job.lease_expiry = Some(req.now + req.lease_for);
            job.safe_error_code = None;
            claimed.push(job.clone());
        }
        claimed
    }

    pub fn apply_samples(
        &self,
        job: &JobView,
        samples: &[AppliedSample],
    ) -> Result<ApplyStats, QueueError> {
        let mut inner = self.lock();
        apply_locked(&mut inner, job, samples)
    }

    pub fn finish(&self, req: &FinishRequest) -> Result<Option<ReceiptView>, QueueError> {
        let mut inner = self.lock();
        let Some(idx) = inner
            .jobs
            .iter()
            .position(|job| job.view.job_id == req.job_id)
        else {
            return Err(QueueError::NotFound);
        };
        if !fence_holds(
            &inner.jobs[idx].view,
            &req.owner,
            req.fencing_token,
            req.now,
        ) {
            return Err(QueueError::StaleFence);
        }
        if model_changed(&inner.jobs[idx], req) {
            let job = &mut inner.jobs[idx].view;
            job.lease_owner = None;
            job.lease_expiry = None;
            job.state = JobState::PermanentFailure.as_str().to_string();
            job.safe_error_code = Some("model_revision_changed".into());
            return Ok(None);
        }
        guard_finish(req)?;
        let snapshot = inner.jobs[idx].view.clone();
        apply_locked(&mut inner, &snapshot, &req.applied_samples)?;
        let receipt_code = {
            let job = &mut inner.jobs[idx].view;
            job.lease_owner = None;
            job.lease_expiry = None;
            match &req.outcome {
                FinishOutcome::Committed { counts, coverage } => {
                    job.state = JobState::Committed.as_str().to_string();
                    job.counts = *counts;
                    job.coverage = coverage.summary.clone();
                    job.point_coverage = coverage.points.clone();
                    job.safe_error_code = None;
                    Some(None)
                }
                FinishOutcome::Partial {
                    counts,
                    code,
                    coverage,
                } => {
                    job.state = JobState::Partial.as_str().to_string();
                    job.counts = *counts;
                    job.coverage = coverage.summary.clone();
                    job.point_coverage = coverage.points.clone();
                    job.safe_error_code = Some(code.clone());
                    Some(Some(code.clone()))
                }
                FinishOutcome::Retry { code, not_before } => {
                    job.state = JobState::RetryWait.as_str().to_string();
                    job.safe_error_code = Some(code.clone());
                    job.not_before = *not_before;
                    None
                }
                FinishOutcome::Permanent { code } => {
                    job.state = JobState::PermanentFailure.as_str().to_string();
                    job.safe_error_code = Some(code.clone());
                    None
                }
            }
        };
        let Some(code) = receipt_code else {
            return Ok(None);
        };
        let snapshot = inner.jobs[idx].view.clone();
        let receipt = push_receipt(&mut inner, &snapshot, req.now, code);
        inner.jobs[idx].view.receipt_id = Some(receipt.receipt_id);
        Ok(Some(receipt))
    }

    pub fn note_throttle(
        &self,
        provider_instance_id: &str,
        now: DateTime<Utc>,
        retry_after: chrono::Duration,
    ) {
        let mut inner = self.lock();
        let budget = budget_mut(&mut inner, provider_instance_id, now);
        budget.paused_until = Some(now + retry_after);
        let current = budget.cap_override.unwrap_or(budget.max_in_flight);
        budget.cap_override = Some((current / 2).max(1));
    }

    pub fn retry_job(
        &self,
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
        let mut inner = self.lock();
        let key = idempotency_key(claim, "retry");
        if let Some(record) = inner.idempotency.get(&key) {
            if record.object_id != claim.object_id || record.payload_hash != claim.payload_hash {
                return Err(QueueError::Conflict(
                    "idempotency key does not match the original request".into(),
                ));
            }
            return replay_jobs(&inner, &record.job_ids, &claim.tenant_id);
        }
        let Some(job) = inner.jobs.iter_mut().find(|job| job.view.job_id == job_id) else {
            return Err(QueueError::NotFound);
        };
        if job.view.tenant_id != claim.tenant_id {
            return Err(QueueError::NotFound);
        }
        if !operator_retry_allowed(&job.view.state, job.view.safe_error_code.as_deref()) {
            return Err(QueueError::Invalid(
                "job is not eligible for operator retry".into(),
            ));
        }
        if job.view.state == JobState::Leased.as_str()
            && job.view.lease_expiry.is_some_and(|exp| exp > now)
        {
            return Err(QueueError::Invalid("leased job cannot be retried".into()));
        }
        job.view.state = JobState::Queued.as_str().to_string();
        job.view.not_before = now;
        job.view.lease_owner = None;
        job.view.lease_expiry = None;
        job.view.safe_error_code = None;
        let view = job.view.clone();
        remember_idempotency(
            &mut inner,
            claim,
            "retry",
            vec![view.job_id],
            Some(view.job_id),
        );
        Ok(view)
    }

    pub fn backfill(
        &self,
        jobs: Vec<NewJob>,
        now: DateTime<Utc>,
        claim: &IdempotencyClaim,
    ) -> Result<Vec<JobView>, QueueError> {
        if jobs.is_empty() || jobs.len() > MAX_CATCHUP_HOURS as usize {
            return Err(QueueError::Invalid(
                "backfill requires 1 to 48 hourly windows".into(),
            ));
        }
        let object_id = backfill_object_id(&jobs[0]);
        let payload_hash = backfill_payload_hash(&jobs)?;
        if claim.object_id != object_id
            || claim.payload_hash != payload_hash
            || jobs.iter().any(|job| job.tenant_id != claim.tenant_id)
        {
            return Err(QueueError::Conflict(
                "idempotency key does not match the original request".into(),
            ));
        }
        let mut inner = self.lock();
        let key = idempotency_key(claim, "backfill");
        if let Some(record) = inner.idempotency.get(&key) {
            if record.object_id != claim.object_id || record.payload_hash != claim.payload_hash {
                return Err(QueueError::Conflict(
                    "idempotency key does not match the original request".into(),
                ));
            }
            return replay_job_list(&inner, &record.job_ids, &claim.tenant_id);
        }
        let mut created = Vec::new();
        for job in jobs {
            match enqueue_locked(&mut inner, job, now)? {
                EnqueueOutcome::Created(view) | EnqueueOutcome::Existing(view) => {
                    created.push(view)
                }
            }
        }
        let ids: Vec<Uuid> = created.iter().map(|job| job.job_id).collect();
        remember_idempotency(&mut inner, claim, "backfill", ids, None);
        Ok(created)
    }

    pub fn advance_cursor(&self, key: &CursorKey, now: DateTime<Utc>) -> Option<CoverageCursor> {
        let mut inner = self.lock();
        let current = inner.cursors.get(key).map(|row| row.verified_through);
        let windows: Vec<WindowState> = inner
            .jobs
            .iter()
            .map(|job| &job.view)
            .filter(|job| {
                job.tenant_id == key.tenant_id
                    && job.canonical_site == key.canonical_site
                    && job.provider_instance_id == key.provider_instance_id
                    && job.device_id == key.device_id
                    && job.model_revision == key.model_revision
                    && current.is_none_or(|at| job.logical_window_end > at)
            })
            .map(|job| WindowState {
                start: job.logical_window_start,
                end: job.logical_window_end,
                state: job.state.clone(),
                code: job.safe_error_code.clone(),
            })
            .collect();
        let (verified_through, hole) = walk(current, &windows)?;
        let row = CoverageCursor {
            key: key.clone(),
            verified_through: current.map_or(verified_through, |at| at.max(verified_through)),
            hole,
            updated_at: now,
        };
        inner.cursors.insert(key.clone(), row.clone());
        Some(row)
    }

    pub fn list_jobs(&self, filter: &ListFilter) -> Vec<JobView> {
        let inner = self.lock();
        filtered_jobs(&inner.jobs, filter)
    }

    pub fn get_job(&self, job_id: Uuid) -> Option<JobView> {
        self.lock()
            .jobs
            .iter()
            .find(|job| job.view.job_id == job_id)
            .map(|job| job.view.clone())
    }

    pub fn list_receipts(&self, filter: &ListFilter) -> Vec<ReceiptView> {
        let inner = self.lock();
        let mut rows: Vec<ReceiptView> = inner
            .receipts
            .iter()
            .filter(|row| {
                site_allowed(filter.sites.as_ref(), &row.canonical_site)
                    && tenant_allowed(filter.tenant_id.as_ref(), &row.tenant_id)
            })
            .cloned()
            .collect();
        rows.sort_by_key(|row| Reverse(row.committed_at));
        rows.truncate(filter.limit as usize);
        rows
    }

    pub fn get_receipt(&self, receipt_id: Uuid) -> Option<ReceiptView> {
        self.lock()
            .receipts
            .iter()
            .find(|row| row.receipt_id == receipt_id)
            .cloned()
    }

    pub fn list_gaps(&self, filter: &ListFilter) -> Vec<JobView> {
        let inner = self.lock();
        let mut rows: Vec<JobView> = inner
            .jobs
            .iter()
            .filter(|job| {
                site_allowed(filter.sites.as_ref(), &job.view.canonical_site)
                    && tenant_allowed(filter.tenant_id.as_ref(), &job.view.tenant_id)
                    && matches!(
                        job.view.state.as_str(),
                        "partial" | "permanent_failure" | "retry_wait"
                    )
            })
            .map(|job| job.view.clone())
            .collect();
        rows.sort_by_key(|row| row.logical_window_start);
        rows.truncate(filter.limit as usize);
        rows
    }

    pub fn metrics(&self, now: DateTime<Utc>, scope: &MetricsScope) -> QueueMetrics {
        let inner = self.lock();
        let mut ready_times = Vec::new();
        let mut leased = 0u64;
        let mut retry_wait = 0u64;
        let mut partial = 0u64;
        let mut permanent_failure = 0u64;
        let mut committed = 0u64;
        let mut portals: HashMap<String, u32> = HashMap::new();
        for job in &inner.jobs {
            if !metrics_job_in_scope(&job.view, scope) {
                continue;
            }
            match job.view.state.as_str() {
                "queued" | "retry_wait" if job.view.not_before <= now => {
                    ready_times.push(job.view.not_before);
                }
                "leased" => {
                    leased += 1;
                    if job.view.lease_expiry.is_some_and(|exp| exp > now) {
                        *portals
                            .entry(job.view.provider_instance_id.clone())
                            .or_default() += 1;
                    }
                }
                "retry_wait" => retry_wait += 1,
                "partial" => partial += 1,
                "permanent_failure" => permanent_failure += 1,
                "committed" => committed += 1,
                _ => {}
            }
            if job.view.state == "retry_wait" && job.view.not_before <= now {
                // Counted as ready above; also keep the state total.
                retry_wait += 1;
            }
        }
        ready_times.sort();
        let oldest_ready_age_secs = ready_times
            .first()
            .map(|ts| now.signed_duration_since(*ts).num_seconds().max(0) as u64);
        let mut portal_in_flight: Vec<PortalInFlight> = portals
            .into_iter()
            .map(|(provider_instance_id, in_flight)| PortalInFlight {
                provider_instance_id,
                in_flight,
            })
            .collect();
        portal_in_flight.sort_by(|a, b| a.provider_instance_id.cmp(&b.provider_instance_id));
        QueueMetrics {
            ready_backlog: ready_times.len() as u64,
            oldest_ready_age_secs,
            leased,
            retry_wait,
            partial,
            permanent_failure,
            committed,
            scheduler_owner: scope
                .include_scheduler
                .then(|| {
                    inner
                        .scheduler
                        .as_ref()
                        .and_then(|lease| (lease.expires_at > now).then(|| lease.owner.clone()))
                })
                .flatten(),
            portal_in_flight,
        }
    }
}

fn enqueue_locked(
    inner: &mut Inner,
    job: NewJob,
    now: DateTime<Utc>,
) -> Result<EnqueueOutcome, QueueError> {
    validate_new(&job)?;
    let key = job.key();
    if let Some(idx) = inner.by_key.get(&key).copied() {
        let id = inner.jobs[idx].view.job_id.to_string();
        crate::audit::correlate_job(&id);
        return Ok(EnqueueOutcome::Existing(inner.jobs[idx].view.clone()));
    }
    let server_request_id = crate::audit::current_server_request_id();
    let view = JobView {
        job_id: Uuid::new_v4(),
        tenant_id: job.tenant_id,
        canonical_site: job.canonical_site,
        provider_instance_id: job.provider_instance_id,
        device_id: job.device_id,
        model_revision: job.model_revision,
        logical_window_start: job.logical_window_start,
        logical_window_end: job.logical_window_end,
        shard: job.shard,
        state: JobState::Queued.as_str().to_string(),
        attempt: 0,
        not_before: job.not_before,
        lease_owner: None,
        lease_expiry: None,
        fencing_token: 0,
        estimated_cost: job.estimated_cost.max(1),
        safe_error_code: None,
        receipt_id: None,
        coverage: COVERAGE_NOT_ASSESSED.to_string(),
        point_coverage: Vec::new(),
        counts: JobCounts::default(),
        server_request_id,
    };
    crate::audit::correlate_job(&view.job_id.to_string());
    let idx = inner.jobs.len();
    inner.by_key.insert(key, idx);
    inner.jobs.push(StoredJob {
        view: view.clone(),
        points_digest: job.requested_points_digest,
    });
    let _ = now;
    Ok(EnqueueOutcome::Created(view))
}

fn metrics_job_in_scope(job: &JobView, scope: &MetricsScope) -> bool {
    if let Some(tenant) = scope.tenant_id.as_deref() {
        if job.tenant_id != tenant {
            return false;
        }
    }
    if let Some(sites) = scope.sites.as_ref() {
        if !sites.iter().any(|site| site == &job.canonical_site) {
            return false;
        }
    }
    true
}

fn idempotency_key(claim: &IdempotencyClaim, action: &str) -> IdempotencyKey {
    IdempotencyKey {
        actor: claim.actor.clone(),
        tenant_id: claim.tenant_id.clone(),
        action: action.to_string(),
        client_key: claim.client_key.clone(),
    }
}

fn replay_jobs(inner: &Inner, ids: &[Uuid], tenant_id: &str) -> Result<JobView, QueueError> {
    let mut matched = None;
    for id in ids {
        if let Some(job) = inner.jobs.iter().find(|job| job.view.job_id == *id) {
            if job.view.tenant_id != tenant_id {
                return Err(QueueError::NotFound);
            }
            if matched.is_none() {
                matched = Some(job.view.clone());
            }
        }
    }
    matched.ok_or(QueueError::NotFound)
}

fn replay_job_list(
    inner: &Inner,
    ids: &[Uuid],
    tenant_id: &str,
) -> Result<Vec<JobView>, QueueError> {
    let mut views = Vec::new();
    for id in ids {
        if let Some(job) = inner.jobs.iter().find(|job| job.view.job_id == *id) {
            if job.view.tenant_id != tenant_id {
                return Err(QueueError::NotFound);
            }
            views.push(job.view.clone());
        }
    }
    if views.is_empty() {
        return Err(QueueError::NotFound);
    }
    Ok(views)
}

fn remember_idempotency(
    inner: &mut Inner,
    claim: &IdempotencyClaim,
    action: &str,
    job_ids: Vec<Uuid>,
    job_id: Option<Uuid>,
) {
    inner.idempotency.insert(
        idempotency_key(claim, action),
        IdempotencyRecord {
            object_id: claim.object_id.clone(),
            payload_hash: claim.payload_hash.clone(),
            job_ids,
        },
    );
    let event = AuditEvent {
        actor: claim.actor.clone(),
        action: action.to_string(),
        job_id,
        idempotency_key: Some(claim.client_key.clone()),
    };
    debug!(
        actor = %event.actor,
        action = %event.action,
        job_id = ?event.job_id,
        idempotency_key_len = event.idempotency_key.as_ref().map(String::len),
        "ingest audit recorded"
    );
    inner.audit.push_back(event);
    while inner.audit.len() > 500 {
        inner.audit.pop_front();
    }
}

fn validate_new(job: &NewJob) -> Result<(), QueueError> {
    validate_new_job(job)
}

fn model_changed(job: &StoredJob, req: &FinishRequest) -> bool {
    if !matches!(
        req.outcome,
        FinishOutcome::Committed { .. } | FinishOutcome::Partial { .. }
    ) {
        return false;
    }
    if let Some(active) = req.active_model_revision.as_deref() {
        if !revision_still_owns(&job.view.model_revision, active) {
            return true;
        }
    }
    if let (Some(active_digest), Some(stored)) = (
        req.active_points_digest.as_deref(),
        job.points_digest.as_deref(),
    ) {
        return stored != active_digest;
    }
    false
}

fn guard_finish(req: &FinishRequest) -> Result<(), QueueError> {
    match &req.outcome {
        FinishOutcome::Committed { coverage, .. } => {
            if !coverage.allows_commit() {
                return Err(QueueError::Invalid("coverage does not allow commit".into()));
            }
        }
        FinishOutcome::Partial { coverage, code, .. } => {
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
        }
        FinishOutcome::Retry { .. } | FinishOutcome::Permanent { .. } => {}
    }
    Ok(())
}

fn apply_locked(
    inner: &mut Inner,
    job: &JobView,
    samples: &[AppliedSample],
) -> Result<ApplyStats, QueueError> {
    if samples.len() > super::coverage::MAX_TIMESTAMPS {
        return Err(QueueError::Invalid("payload_bound".into()));
    }
    let mut stats = ApplyStats::default();
    for sample in samples {
        let key = AppliedKey {
            tenant_id: job.tenant_id.clone(),
            canonical_site: job.canonical_site.clone(),
            provider_instance_id: job.provider_instance_id.clone(),
            device_id: job.device_id.clone(),
            model_revision: job.model_revision.clone(),
            point_id: sample.point_id.clone(),
            ts: sample.ts,
        };
        match super::coverage::classify_replay(inner.applied.get(&key).copied(), sample.value_bits)
        {
            super::coverage::Replay::Insert => {
                inner.applied.insert(key, sample.value_bits);
                stats.inserted = stats.inserted.saturating_add(1);
            }
            super::coverage::Replay::Unchanged => {
                stats.unchanged = stats.unchanged.saturating_add(1);
            }
            super::coverage::Replay::Conflict => {
                stats.conflict = stats.conflict.saturating_add(1);
            }
        }
    }
    Ok(stats)
}

fn fence_holds(job: &JobView, owner: &str, token: u64, now: DateTime<Utc>) -> bool {
    job.state == JobState::Leased.as_str()
        && job.lease_owner.as_deref() == Some(owner)
        && job.fencing_token == token
        && job.lease_expiry.is_some_and(|exp| exp > now)
}

#[derive(PartialEq, Eq, PartialOrd, Ord)]
struct ClaimRank {
    in_flight: u32,
    not_before: DateTime<Utc>,
    window_start: DateTime<Utc>,
    job_id: Uuid,
    idx: usize,
}

fn pick_candidate(inner: &Inner, now: DateTime<Utc>) -> Option<usize> {
    let mut best: Option<ClaimRank> = None;
    for (idx, job) in inner.jobs.iter().enumerate() {
        if !eligible(&job.view, now) {
            continue;
        }
        if !portal_claimable(inner, &job.view.provider_instance_id, now) {
            continue;
        }
        let rank = ClaimRank {
            in_flight: in_flight_count(inner, &job.view.provider_instance_id, now),
            not_before: job.view.not_before,
            window_start: job.view.logical_window_start,
            job_id: job.view.job_id,
            idx,
        };
        if best.as_ref().is_none_or(|current| rank < *current) {
            best = Some(rank);
        }
    }
    best.map(|rank| rank.idx)
}

fn eligible(job: &JobView, now: DateTime<Utc>) -> bool {
    match job.state.as_str() {
        "queued" | "retry_wait" => job.not_before <= now,
        "leased" => job.lease_expiry.is_some_and(|exp| exp <= now),
        _ => false,
    }
}

fn portal_claimable(inner: &Inner, portal: &str, now: DateTime<Utc>) -> bool {
    let Some(budget) = inner.budgets.get(portal) else {
        return true;
    };
    if budget.paused_until.is_some_and(|until| until > now) {
        return false;
    }
    let cap = budget.cap_override.unwrap_or(budget.max_in_flight);
    if in_flight_count(inner, portal, now) >= cap {
        return false;
    }
    let window_fresh =
        now.signed_duration_since(budget.window_start) < chrono::Duration::seconds(60);
    if window_fresh && budget.tokens == 0 {
        return false;
    }
    true
}

fn budget_allows(inner: &mut Inner, portal: &str, now: DateTime<Utc>) -> bool {
    refresh_budget(inner, portal, now);
    portal_claimable(inner, portal, now)
}

fn refresh_budget<'a>(
    inner: &'a mut Inner,
    portal: &str,
    now: DateTime<Utc>,
) -> &'a mut PortalBudget {
    let defaults = inner.defaults;
    let budget = inner
        .budgets
        .entry(portal.to_string())
        .or_insert(PortalBudget {
            max_in_flight: defaults.max_in_flight.max(1),
            max_per_minute: defaults.max_per_minute.max(1),
            tokens: defaults.max_per_minute.max(1),
            window_start: now,
            paused_until: None,
            cap_override: None,
        });
    if budget.paused_until.is_some_and(|until| until <= now) {
        budget.paused_until = None;
        budget.cap_override = None;
    }
    if now.signed_duration_since(budget.window_start) >= chrono::Duration::seconds(60) {
        budget.tokens = budget.max_per_minute;
        budget.window_start = now;
    }
    budget
}

fn consume_token(inner: &mut Inner, portal: &str, now: DateTime<Utc>) {
    refresh_budget(inner, portal, now);
    if let Some(budget) = inner.budgets.get_mut(portal) {
        budget.tokens = budget.tokens.saturating_sub(1);
    }
    let _ = now;
}

fn budget_mut<'a>(inner: &'a mut Inner, portal: &str, now: DateTime<Utc>) -> &'a mut PortalBudget {
    refresh_budget(inner, portal, now)
}

fn in_flight_count(inner: &Inner, portal: &str, now: DateTime<Utc>) -> u32 {
    inner
        .jobs
        .iter()
        .filter(|job| {
            job.view.provider_instance_id == portal
                && job.view.state == JobState::Leased.as_str()
                && job.view.lease_expiry.is_some_and(|exp| exp > now)
        })
        .count() as u32
}

fn push_receipt(
    inner: &mut Inner,
    job: &JobView,
    now: DateTime<Utc>,
    code: Option<String>,
) -> ReceiptView {
    let receipt = ReceiptView {
        receipt_id: Uuid::new_v4(),
        job_id: job.job_id,
        tenant_id: job.tenant_id.clone(),
        canonical_site: job.canonical_site.clone(),
        provider_instance_id: job.provider_instance_id.clone(),
        device_id: job.device_id.clone(),
        model_revision: job.model_revision.clone(),
        fencing_token: job.fencing_token,
        committed_at: now,
        counts: job.counts,
        safe_error_code: code,
        server_request_id: job.server_request_id.clone(),
    };
    crate::audit::correlate_receipt(&receipt.receipt_id.to_string());
    inner.receipts.push(receipt.clone());
    receipt
}

fn site_allowed(sites: Option<&Vec<String>>, site: &str) -> bool {
    match sites {
        None => true,
        Some(allowed) => allowed.iter().any(|candidate| candidate == site),
    }
}

fn tenant_allowed(tenant: Option<&String>, job_tenant: &str) -> bool {
    tenant.is_none_or(|expected| expected == job_tenant)
}

fn filtered_jobs(jobs: &[StoredJob], filter: &ListFilter) -> Vec<JobView> {
    let mut rows: Vec<JobView> = jobs
        .iter()
        .filter(|job| {
            site_allowed(filter.sites.as_ref(), &job.view.canonical_site)
                && tenant_allowed(filter.tenant_id.as_ref(), &job.view.tenant_id)
        })
        .filter(|job| {
            filter
                .state
                .as_deref()
                .is_none_or(|state| job.view.state == state)
        })
        .map(|job| job.view.clone())
        .collect();
    rows.sort_by_key(|row| Reverse(row.logical_window_start));
    rows.truncate(filter.limit as usize);
    rows
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Barrier};
    use std::thread;

    fn hour(start: &str) -> (DateTime<Utc>, DateTime<Utc>) {
        let start = DateTime::parse_from_rfc3339(start)
            .unwrap()
            .with_timezone(&Utc);
        (start, start + chrono::Duration::hours(1))
    }

    fn sample(site: &str, portal: &str, device: &str, start: &str) -> NewJob {
        let (logical_window_start, logical_window_end) = hour(start);
        NewJob {
            tenant_id: "tenant-a".into(),
            canonical_site: site.into(),
            provider_instance_id: portal.into(),
            device_id: device.into(),
            model_revision: "rev-1".into(),
            logical_window_start,
            logical_window_end,
            shard: String::new(),
            not_before: logical_window_end,
            estimated_cost: 1,
            requested_points_digest: None,
        }
    }

    fn now() -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-10-19T13:05:00Z")
            .unwrap()
            .with_timezone(&Utc)
    }

    fn claim_req(owner: &str, limit: usize, at: DateTime<Utc>) -> ClaimRequest {
        ClaimRequest {
            owner: owner.into(),
            limit,
            now: at,
            lease_for: chrono::Duration::seconds(30),
        }
    }

    #[test]
    fn duplicate_logical_key_does_not_create_a_second_job() {
        let store = MemoryStore::new(BudgetDefaults::default());
        let job = sample("site-a", "nf:site-a", "ahu-1", "2026-10-19T12:00:00Z");
        let created = store.enqueue(job.clone(), now()).unwrap();
        let again = store.enqueue(job, now()).unwrap();
        match (created, again) {
            (EnqueueOutcome::Created(first), EnqueueOutcome::Existing(second)) => {
                assert_eq!(first.job_id, second.job_id);
            }
            other => panic!("unexpected enqueue pair {other:?}"),
        }
    }

    #[test]
    fn two_and_four_workers_have_one_lease_owner() {
        for workers in [2usize, 4] {
            let store = Arc::new(MemoryStore::new(BudgetDefaults {
                max_in_flight: 4,
                max_per_minute: 100,
            }));
            store
                .enqueue(
                    sample("site-a", "nf:site-a", "ahu-1", "2026-10-19T12:00:00Z"),
                    now(),
                )
                .unwrap();
            let barrier = Arc::new(Barrier::new(workers));
            let mut handles = Vec::new();
            for idx in 0..workers {
                let store = Arc::clone(&store);
                let barrier = Arc::clone(&barrier);
                handles.push(thread::spawn(move || {
                    barrier.wait();
                    store.claim(&claim_req(&format!("worker-{idx}"), 1, now()))
                }));
            }
            let claimed: Vec<_> = handles
                .into_iter()
                .map(|handle| handle.join().expect("worker"))
                .collect();
            let winners: Vec<_> = claimed.iter().filter(|rows| !rows.is_empty()).collect();
            assert_eq!(winners.len(), 1, "{workers} workers");
            assert_eq!(winners[0][0].fencing_token, 1);
        }
    }

    #[test]
    fn expired_lease_can_be_reclaimed_and_stale_fence_cannot_finish() {
        let store = MemoryStore::new(BudgetDefaults::default());
        let created = match store
            .enqueue(
                sample("site-a", "nf:site-a", "ahu-1", "2026-10-19T12:00:00Z"),
                now(),
            )
            .unwrap()
        {
            EnqueueOutcome::Created(view) => view,
            EnqueueOutcome::Existing(_) => panic!("new job"),
        };
        let at = now();
        let first = store.claim(&claim_req("worker-a", 1, at));
        assert_eq!(first.len(), 1);
        let later = at + chrono::Duration::seconds(31);
        let second = store.claim(&claim_req("worker-b", 1, later));
        assert_eq!(second.len(), 1);
        assert_eq!(second[0].job_id, created.job_id);
        assert_eq!(second[0].fencing_token, 2);
        let stale = store.finish(&FinishRequest::new(
            "worker-a",
            created.job_id,
            1,
            later,
            FinishOutcome::committed_accounted(JobCounts {
                inserted: 60,
                ..JobCounts::default()
            }),
        ));
        assert!(matches!(stale, Err(QueueError::StaleFence)));
        let fresh = store
            .finish(&FinishRequest::new(
                "worker-b",
                created.job_id,
                2,
                later,
                FinishOutcome::committed_accounted(JobCounts {
                    inserted: 60,
                    ..JobCounts::default()
                }),
            ))
            .unwrap();
        assert!(fresh.is_some());
        assert!(store.claim(&claim_req("worker-c", 1, later)).is_empty());
    }

    #[test]
    fn portal_budget_and_throttle_do_not_stop_other_portals() {
        let store = MemoryStore::new(BudgetDefaults {
            max_in_flight: 1,
            max_per_minute: 10,
        });
        let at = now();
        for (portal, device, start) in [
            ("nf:big", "d1", "2026-10-19T08:00:00Z"),
            ("nf:big", "d2", "2026-10-19T09:00:00Z"),
            ("nf:other", "d3", "2026-10-19T08:00:00Z"),
            ("nf:other", "d4", "2026-10-19T09:00:00Z"),
        ] {
            store
                .enqueue(sample("site", portal, device, start), at)
                .unwrap();
        }
        let first = store.claim(&claim_req("w", 2, at));
        assert_eq!(first.len(), 2, "one slot per portal");
        let portals: Vec<_> = first
            .iter()
            .map(|job| job.provider_instance_id.as_str())
            .collect();
        assert!(portals.contains(&"nf:big"));
        assert!(portals.contains(&"nf:other"));
        assert!(store.claim(&claim_req("w2", 2, at)).is_empty());
        store.note_throttle("nf:other", at, chrono::Duration::seconds(60));
        store
            .finish(&FinishRequest::new(
                "w",
                first[0].job_id,
                first[0].fencing_token,
                at,
                FinishOutcome::committed_accounted(JobCounts::default()),
            ))
            .unwrap();
        store
            .finish(&FinishRequest::new(
                "w",
                first[1].job_id,
                first[1].fencing_token,
                at,
                FinishOutcome::committed_accounted(JobCounts::default()),
            ))
            .unwrap();
        let after = store.claim(&claim_req("w3", 2, at + chrono::Duration::seconds(1)));
        assert!(after
            .iter()
            .all(|job| job.provider_instance_id != "nf:other"));
        assert_eq!(after.len(), 1);
        assert_eq!(after[0].provider_instance_id, "nf:big");
    }

    #[test]
    fn only_one_scheduler_owner_and_old_token_cannot_renew() {
        let store = MemoryStore::new(BudgetDefaults::default());
        let at = now();
        let ttl = chrono::Duration::seconds(20);
        let first = store.try_scheduler("leader-a", at, ttl).unwrap();
        assert!(store.try_scheduler("leader-b", at, ttl).is_none());
        assert!(store.renew_scheduler("leader-a", first.fencing_token, at, ttl));
        let later = at + chrono::Duration::seconds(21);
        let second = store.try_scheduler("leader-b", later, ttl).unwrap();
        assert!(second.fencing_token > first.fencing_token);
        assert!(!store.renew_scheduler("leader-a", first.fencing_token, later, ttl));
    }

    #[test]
    fn retry_idempotency_replays_without_a_second_transition() {
        let store = MemoryStore::new(BudgetDefaults::default());
        let created = match store
            .enqueue(
                sample("site-a", "nf:site-a", "ahu-1", "2026-10-19T12:00:00Z"),
                now(),
            )
            .unwrap()
        {
            EnqueueOutcome::Created(view) => view,
            EnqueueOutcome::Existing(_) => panic!("new"),
        };
        let at = now();
        let leased = store.claim(&claim_req("w", 1, at));
        store
            .finish(&FinishRequest::new(
                "w",
                leased[0].job_id,
                leased[0].fencing_token,
                at,
                FinishOutcome::Permanent {
                    code: "provider_poll_failed".into(),
                },
            ))
            .unwrap();
        let claim = IdempotencyClaim {
            actor: "operator".into(),
            tenant_id: "tenant-a".into(),
            client_key: "idem-1".into(),
            object_id: retry_object_id(created.job_id),
            payload_hash: retry_payload_hash("tenant-a", created.job_id),
        };
        let retried = store.retry_job(created.job_id, at, &claim).unwrap();
        assert_eq!(retried.state, "queued");
        let again = store.retry_job(created.job_id, at, &claim).unwrap();
        assert_eq!(again.job_id, retried.job_id);
        assert_eq!(again.state, "queued");
        let other = IdempotencyClaim {
            actor: "other-operator".into(),
            tenant_id: "tenant-b".into(),
            client_key: "idem-1".into(),
            object_id: retry_object_id(created.job_id),
            payload_hash: retry_payload_hash("tenant-b", created.job_id),
        };
        let foreign = store.retry_job(created.job_id, at, &other);
        assert!(matches!(foreign, Err(QueueError::NotFound)));
        let mismatch = IdempotencyClaim {
            client_key: "idem-1".into(),
            object_id: retry_object_id(Uuid::new_v4()),
            payload_hash: retry_payload_hash("tenant-a", Uuid::new_v4()),
            ..claim
        };
        assert!(matches!(
            store.retry_job(created.job_id, at, &mismatch),
            Err(QueueError::Conflict(_))
        ));
    }

    #[test]
    fn metrics_ignore_another_tenants_jobs() {
        let store = MemoryStore::new(BudgetDefaults::default());
        let at = now();
        let mut foreign = sample("site-b", "nf:site-b", "ahu-b", "2026-10-19T12:00:00Z");
        foreign.tenant_id = "tenant-b".into();
        store.enqueue(foreign, at).unwrap();
        let scope = MetricsScope {
            tenant_id: Some("tenant-a".into()),
            sites: Some(vec!["site-a".into()]),
            include_scheduler: false,
        };
        let metrics = store.metrics(at, &scope);
        assert_eq!(metrics.ready_backlog, 0);
        assert!(metrics.scheduler_owner.is_none());
        let global = store.metrics(at, &MetricsScope::global());
        assert_eq!(global.ready_backlog, 1);
    }

    #[tokio::test]
    async fn server_request_id_is_copied_onto_the_job_and_the_receipt() {
        let ctx = crate::audit::RequestContext::new(Some("caller-label"), "POST", "/api/ingest");
        let server_id = ctx.server_id.clone();
        let store = MemoryStore::new(BudgetDefaults::default());
        let at = now();
        crate::audit::with_request_context(ctx, async {
            let created = match store
                .enqueue(
                    sample("site-a", "nf:site-a", "ahu-srv", "2026-10-19T12:00:00Z"),
                    at,
                )
                .unwrap()
            {
                EnqueueOutcome::Created(view) => view,
                EnqueueOutcome::Existing(_) => panic!("new job"),
            };
            assert_eq!(
                created.server_request_id.as_deref(),
                Some(server_id.as_str())
            );
            let again = match store
                .enqueue(
                    sample("site-a", "nf:site-a", "ahu-srv", "2026-10-19T12:00:00Z"),
                    at,
                )
                .unwrap()
            {
                EnqueueOutcome::Existing(view) => view,
                EnqueueOutcome::Created(_) => panic!("duplicate job"),
            };
            assert_eq!(again.server_request_id.as_deref(), Some(server_id.as_str()));
            assert_eq!(again.job_id, created.job_id);
            let leased = store.claim(&claim_req("worker", 1, at));
            assert_eq!(leased.len(), 1);
            let receipt = store
                .finish(&FinishRequest::new(
                    "worker",
                    leased[0].job_id,
                    leased[0].fencing_token,
                    at,
                    FinishOutcome::committed_accounted(JobCounts::default()),
                ))
                .unwrap()
                .expect("receipt");
            assert_eq!(
                receipt.server_request_id.as_deref(),
                Some(server_id.as_str())
            );
            let event = crate::audit::AuditEvent::new(crate::audit::AuditAction::PackageImport);
            let value = event.to_value();
            assert_eq!(value["correlation"]["server_request_id"], server_id);
            assert_eq!(
                value["correlation"]["job_ids"]["items"][0],
                created.job_id.to_string()
            );
            assert_eq!(
                value["correlation"]["receipt_ids"]["items"][0],
                receipt.receipt_id.to_string()
            );
        })
        .await;

        let bare = match store
            .enqueue(
                sample("site-a", "nf:site-a", "ahu-sched", "2026-10-19T12:00:00Z"),
                at,
            )
            .unwrap()
        {
            EnqueueOutcome::Created(view) => view,
            EnqueueOutcome::Existing(_) => panic!("scheduler job"),
        };
        assert!(bare.server_request_id.is_none());
    }
}
