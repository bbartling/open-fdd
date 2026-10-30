//! Crash, fencing, retry, and coverage behavior of the device/hour queue.
//!
//! Memory covers the same fences in one process. PostgreSQL runs when
//! `OPENFDD_TEST_DATABASE_URL` is set, and is required when
//! `OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED=1`. Two pools are two replicas.

use chrono::{DateTime, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};
use uuid::Uuid;

use super::coverage::{
    reconcile, CoverageReport, Expectation, PointExpectation, PointObservation, ReconcileInput,
    COMPLETE, GENUINE_GAP, NO_SAMPLE_EXPECTED, NO_SAMPLE_RECEIVED, PRESENT,
};
use super::memory::MemoryStore;
use super::model::*;
use super::postgres;

const SITE: &str = "w3b-site";
const REVISION: &str = "rev-w3b";

fn origin() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-15T00:00:00Z")
        .expect("durability origin")
        .with_timezone(&Utc)
}

fn hour(offset: i64) -> (DateTime<Utc>, DateTime<Utc>) {
    let start = origin() + chrono::Duration::hours(offset);
    (start, start + chrono::Duration::hours(1))
}

fn new_job(tenant: &str, portal: &str, device: &str, offset: i64) -> NewJob {
    let (start, end) = hour(offset);
    NewJob {
        tenant_id: tenant.to_string(),
        canonical_site: SITE.into(),
        provider_instance_id: portal.to_string(),
        device_id: device.to_string(),
        model_revision: REVISION.into(),
        logical_window_start: start,
        logical_window_end: end,
        shard: String::new(),
        not_before: origin(),
        estimated_cost: 1,
        requested_points_digest: None,
    }
}

fn budget() -> BudgetDefaults {
    BudgetDefaults {
        max_in_flight: 4,
        max_per_minute: 1000,
    }
}

fn claim_req(owner: &str, now: DateTime<Utc>) -> ClaimRequest {
    ClaimRequest {
        owner: owner.to_string(),
        limit: 1,
        now,
        lease_for: chrono::Duration::seconds(30),
    }
}

fn accounted() -> FinishOutcome {
    FinishOutcome::committed_accounted(JobCounts {
        fetched: 1,
        accepted: 1,
        rejected: 0,
        inserted: 1,
        ..JobCounts::default()
    })
}

fn gap_report() -> CoverageReport {
    CoverageReport {
        summary: "incomplete".into(),
        points: vec![super::coverage::PointCoverage {
            point_id: "sat".into(),
            disposition: GENUINE_GAP.into(),
            expected_slots: 1,
            observed_slots: 0,
            late_slots: 0,
        }],
        duplicate_timestamps: 0,
        out_of_window: 0,
    }
}

fn sample(point: &str, ts: DateTime<Utc>, bits: u64) -> AppliedSample {
    AppliedSample {
        point_id: point.to_string(),
        ts,
        value_bits: bits,
    }
}

fn created(outcome: EnqueueOutcome) -> JobView {
    match outcome {
        EnqueueOutcome::Created(view) => view,
        EnqueueOutcome::Existing(view) => panic!("expected a new job, found {}", view.job_id),
    }
}

#[test]
fn memory_crash_lease_retry_and_model_change() {
    let tenant = "w3b-memory";
    crash_before_fetch_memory(tenant);
    crash_during_write_memory(tenant);
    crash_after_commit_memory(tenant);
    expired_lease_two_owners_memory(tenant);
    throttle_and_timeout_do_not_commit_memory(tenant);
    model_change_and_gap_do_not_commit_memory(tenant);
    replay_keeps_first_value_memory(tenant);
    misaligned_window_is_rejected_memory(tenant);
}

fn crash_before_fetch_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let now = origin();
    let job = created(
        store
            .enqueue(new_job(tenant, "portal-before", "before", 0), now)
            .expect("enqueue"),
    );
    let leased = one(store.claim(&claim_req("replica-a", now)));
    assert_eq!(leased.job_id, job.job_id);
    assert_eq!(leased.fencing_token, 1);
    assert!(store.list_receipts(&filter(tenant)).is_empty());
    let later = now + chrono::Duration::seconds(31);
    let stale = store.finish(&FinishRequest::new(
        "replica-a",
        leased.job_id,
        leased.fencing_token,
        later,
        accounted(),
    ));
    assert!(matches!(stale, Err(QueueError::StaleFence)));
    let next = one(store.claim(&claim_req("replica-b", later)));
    assert_eq!(next.lease_owner.as_deref(), Some("replica-b"));
    assert_eq!(next.fencing_token, 2);
    assert!(store.list_receipts(&filter(tenant)).is_empty());
    let view = store.get_job(job.job_id).expect("job");
    assert_eq!(view.state, "leased");
    assert_ne!(view.state, "committed");
}

fn crash_during_write_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let now = origin();
    let job = created(
        store
            .enqueue(new_job(tenant, "portal-write", "write", 1), now)
            .expect("enqueue"),
    );
    let first = one(store.claim(&claim_req("replica-a", now)));
    let start = job.logical_window_start;
    let original = sample("sat", start, 7);
    let stats = store
        .apply_samples(&first, std::slice::from_ref(&original))
        .expect("prefix write");
    assert_eq!(stats.inserted, 1);
    let later = now + chrono::Duration::seconds(31);
    let second = one(store.claim(&claim_req("replica-b", later)));
    let mut conflict = original.clone();
    conflict.value_bits = 9;
    let extra = sample("sat", start + chrono::Duration::minutes(5), 3);
    let stats = store
        .apply_samples(&second, &[original.clone(), conflict, extra])
        .expect("replay write");
    assert_eq!(stats.unchanged, 1);
    assert_eq!(stats.conflict, 1);
    assert_eq!(stats.inserted, 1);
    let again = store
        .apply_samples(&second, &[original])
        .expect("second replay");
    assert_eq!(again.unchanged, 1);
    assert_eq!(again.conflict, 0);
    let stale = store.finish(&FinishRequest::new(
        "replica-a",
        first.job_id,
        first.fencing_token,
        later,
        accounted(),
    ));
    assert!(matches!(stale, Err(QueueError::StaleFence)));
    let receipt = store
        .finish(&FinishRequest::new(
            "replica-b",
            second.job_id,
            second.fencing_token,
            later,
            accounted(),
        ))
        .expect("owner finish")
        .expect("receipt");
    assert_eq!(receipt.job_id, job.job_id);
    let replay = store.finish(&FinishRequest::new(
        "replica-b",
        second.job_id,
        second.fencing_token,
        later,
        accounted(),
    ));
    assert!(matches!(replay, Err(QueueError::StaleFence)));
    assert_eq!(store.list_receipts(&filter(tenant)).len(), 1);
    assert_eq!(store.get_job(job.job_id).expect("job").state, "committed");
}

fn crash_after_commit_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let now = origin();
    let job = created(
        store
            .enqueue(new_job(tenant, "portal-ack", "ack", 2), now)
            .expect("enqueue"),
    );
    let leased = one(store.claim(&claim_req("replica-a", now)));
    let receipt = store
        .finish(&FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            accounted(),
        ))
        .expect("commit")
        .expect("receipt");
    let lost_ack = store.finish(&FinishRequest::new(
        "replica-a",
        leased.job_id,
        leased.fencing_token,
        now,
        accounted(),
    ));
    assert!(matches!(lost_ack, Err(QueueError::StaleFence)));
    let rows = store.list_receipts(&filter(tenant));
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].receipt_id, receipt.receipt_id);
    assert_eq!(store.get_job(job.job_id).expect("job").state, "committed");
}

fn expired_lease_two_owners_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let now = origin();
    created(
        store
            .enqueue(new_job(tenant, "portal-lease", "lease", 3), now)
            .expect("enqueue"),
    );
    let first = one(store.claim(&claim_req("replica-a", now)));
    let early = store.claim(&claim_req("replica-b", now + chrono::Duration::seconds(5)));
    assert!(early.is_empty(), "live lease stays with replica-a");
    let later = now + chrono::Duration::seconds(31);
    let second = one(store.claim(&claim_req("replica-b", later)));
    assert_eq!(second.fencing_token, first.fencing_token + 1);
    assert_ne!(second.lease_owner, first.lease_owner);
    let stale = store.finish(&FinishRequest::new(
        "replica-a",
        first.job_id,
        first.fencing_token,
        later,
        accounted(),
    ));
    assert!(matches!(stale, Err(QueueError::StaleFence)));
}

fn throttle_and_timeout_do_not_commit_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let now = origin();
    let job = created(
        store
            .enqueue(new_job(tenant, "portal-throttle", "throttle", 4), now)
            .expect("enqueue"),
    );
    let leased = one(store.claim(&claim_req("replica-a", now)));
    let retry_at = now + chrono::Duration::seconds(60);
    let receipt = store
        .finish(&FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Retry {
                code: "throttled".into(),
                not_before: retry_at,
            },
        ))
        .expect("throttle finish");
    assert!(receipt.is_none());
    assert!(store
        .claim(&claim_req("replica-a", now + chrono::Duration::seconds(1)))
        .is_empty());
    assert!(store.list_receipts(&filter(tenant)).is_empty());
    let again = one(store.claim(&claim_req("replica-b", retry_at)));
    let timeout = store
        .finish(&FinishRequest::new(
            "replica-b",
            again.job_id,
            again.fencing_token,
            retry_at,
            FinishOutcome::Retry {
                code: "timeout".into(),
                not_before: retry_at + chrono::Duration::seconds(60),
            },
        ))
        .expect("timeout finish");
    assert!(timeout.is_none());
    let view = store.get_job(job.job_id).expect("job");
    assert_eq!(view.state, "retry_wait");
    assert_eq!(view.safe_error_code.as_deref(), Some("timeout"));
    assert_ne!(view.state, "committed");
}

fn model_change_and_gap_do_not_commit_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let now = origin();
    let job = created(
        store
            .enqueue(new_job(tenant, "portal-model", "model", 5), now)
            .expect("enqueue"),
    );
    let leased = one(store.claim(&claim_req("replica-a", now)));
    let mut changed = FinishRequest::new(
        "replica-a",
        leased.job_id,
        leased.fencing_token,
        now,
        accounted(),
    );
    changed.active_model_revision = Some("rev-next".into());
    let receipt = store.finish(&changed).expect("model fence");
    assert!(receipt.is_none());
    let view = store.get_job(job.job_id).expect("job");
    assert_eq!(view.state, "permanent_failure");
    assert_eq!(
        view.safe_error_code.as_deref(),
        Some("model_revision_changed")
    );
    assert!(store.list_receipts(&filter(tenant)).is_empty());
    assert!(store.claim(&claim_req("replica-b", now)).is_empty());

    let gap_job = created(
        store
            .enqueue(new_job(tenant, "portal-gap", "gap", 6), now)
            .expect("enqueue gap"),
    );
    let gap_lease = one(store.claim(&claim_req("replica-a", now)));
    let refused = store.finish(&FinishRequest::new(
        "replica-a",
        gap_lease.job_id,
        gap_lease.fencing_token,
        now,
        FinishOutcome::Committed {
            counts: JobCounts::default(),
            coverage: gap_report(),
        },
    ));
    assert!(matches!(refused, Err(QueueError::Invalid(_))));
    assert_eq!(store.get_job(gap_job.job_id).expect("gap").state, "leased");
    store
        .finish(&FinishRequest::new(
            "replica-a",
            gap_lease.job_id,
            gap_lease.fencing_token,
            now,
            FinishOutcome::Partial {
                counts: JobCounts::default(),
                code: GENUINE_GAP.into(),
                coverage: gap_report(),
            },
        ))
        .expect("partial");
    let partial = store.get_job(gap_job.job_id).expect("partial");
    assert_eq!(partial.state, "partial");
    assert_eq!(partial.coverage, "incomplete");
    assert_eq!(partial.point_coverage[0].disposition, GENUINE_GAP);
    assert_ne!(partial.point_coverage[0].disposition, NO_SAMPLE_EXPECTED);
    assert!(store.claim(&claim_req("replica-b", now)).is_empty());
}

fn replay_keeps_first_value_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let now = origin();
    let job = created(
        store
            .enqueue(new_job(tenant, "portal-replay", "replay", 7), now)
            .expect("enqueue"),
    );
    let again = store
        .enqueue(new_job(tenant, "portal-replay", "replay", 7), now)
        .expect("duplicate enqueue");
    match again {
        EnqueueOutcome::Existing(view) => assert_eq!(view.job_id, job.job_id),
        EnqueueOutcome::Created(_) => panic!("duplicate key created a second job"),
    }
    let leased = one(store.claim(&claim_req("replica-a", now)));
    let start = job.logical_window_start;
    let original = sample("sat", start, 11);
    store
        .apply_samples(&leased, &[original.clone(), original.clone()])
        .expect("duplicate timestamp");
    let mut other = original.clone();
    other.value_bits = 12;
    let stats = store.apply_samples(&leased, &[other]).expect("conflict");
    assert_eq!(stats.inserted, 0);
    assert_eq!(stats.unchanged, 0);
    assert_eq!(stats.conflict, 1);
    let kept = store
        .apply_samples(&leased, &[original])
        .expect("same bits");
    assert_eq!(kept.unchanged, 1);
}

fn misaligned_window_is_rejected_memory(tenant: &str) {
    let store = MemoryStore::new(budget());
    let start = origin() + chrono::Duration::seconds(30);
    let mut job = new_job(tenant, "portal-window", "window", 8);
    job.logical_window_start = start;
    job.logical_window_end = start + chrono::Duration::seconds(60);
    let err = store.enqueue(job, origin()).expect_err("misaligned");
    assert!(matches!(err, QueueError::Invalid(_)));
}

fn one(mut jobs: Vec<JobView>) -> JobView {
    assert_eq!(jobs.len(), 1, "expected one leased job");
    jobs.pop().expect("leased job")
}

fn filter(tenant: &str) -> ListFilter {
    ListFilter {
        sites: None,
        tenant_id: Some(tenant.to_string()),
        state: None,
        limit: 50,
    }
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize ingest durability DDL with other queue fixtures"
)]
async fn postgres_crash_lease_coverage_and_replay() {
    let required = std::env::var("OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    let Some(url) = url else {
        if required {
            panic!("OPENFDD_TEST_DATABASE_URL is required for the ingest durability fixture");
        }
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let left = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .unwrap_or_else(|err| {
            panic!(
                "ingest durability postgres connect failed: {}",
                redact_db_text(&err.to_string())
            )
        });
    let right = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .unwrap_or_else(|err| {
            panic!(
                "ingest durability second replica connect failed: {}",
                redact_db_text(&err.to_string())
            )
        });
    crate::ingest_queue::test_schema::apply_ingest_queue_schema(&left)
        .await
        .expect("ingest schema");
    let tenant = format!("w3b-{}", &Uuid::new_v4().simple().to_string()[..12]);
    postgres_suite(&left, &right, &tenant).await;
    purge(&left, &tenant).await;
}

async fn postgres_suite(left: &PgPool, right: &PgPool, tenant: &str) {
    crash_before_fetch(left, right, tenant).await;
    crash_during_write(left, right, tenant).await;
    crash_after_commit(left, tenant).await;
    two_replicas_one_claim(left, right, tenant).await;
    expired_lease(left, right, tenant).await;
    throttle_does_not_commit(left, tenant).await;
    model_change_does_not_commit(left, tenant).await;
    coverage_round_trip(left, tenant).await;
    duplicate_enqueue_and_value(left, tenant).await;
}

/// Drop leftover queued, leased, and retrying rows so a later claim time
/// cannot steal an expired lease from an earlier scenario.
async fn retire_ready(pool: &PgPool, tenant: &str) {
    sqlx::query(
        "UPDATE ingest_job
         SET state = 'cancelled', lease_owner = NULL, lease_expiry = NULL
         WHERE tenant_id = $1 AND state IN ('queued', 'leased', 'retry_wait')",
    )
    .bind(tenant)
    .execute(pool)
    .await
    .expect("retire ready jobs");
}

async fn crash_before_fetch(left: &PgPool, right: &PgPool, tenant: &str) {
    retire_ready(left, tenant).await;
    let now = origin();
    let job = enqueue(left, new_job(tenant, "pg-before", "before", 0)).await;
    let leased = claim(left, tenant, "replica-a", now).await;
    assert_eq!(leased.job_id, job.job_id);
    assert_eq!(applied_count(left, tenant, "before").await, 0);
    assert_eq!(receipt_count(left, job.job_id).await, 0);
    let later = now + chrono::Duration::seconds(31);
    let stale = postgres::finish(
        left,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            later,
            accounted(),
        ),
    )
    .await;
    assert!(matches!(stale, Err(QueueError::StaleFence)));
    let next = claim(right, tenant, "replica-b", later).await;
    assert_eq!(next.fencing_token, 2);
    assert_eq!(next.lease_owner.as_deref(), Some("replica-b"));
    assert_eq!(receipt_count(left, job.job_id).await, 0);
    let view = postgres::get_job(left, job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "leased");
}

async fn crash_during_write(left: &PgPool, right: &PgPool, tenant: &str) {
    retire_ready(left, tenant).await;
    let now = origin();
    let job = enqueue(left, new_job(tenant, "pg-write", "write", 1)).await;
    let first = claim(left, tenant, "replica-a", now).await;
    let original = sample("sat", job.logical_window_start, 7);
    let stats = postgres::apply_samples(left, &first, std::slice::from_ref(&original))
        .await
        .expect("prefix");
    assert_eq!(stats.inserted, 1);
    let later = now + chrono::Duration::seconds(31);
    let second = claim(right, tenant, "replica-b", later).await;
    let mut conflict = original.clone();
    conflict.value_bits = 9;
    let extra = sample(
        "sat",
        job.logical_window_start + chrono::Duration::minutes(5),
        3,
    );
    let stats = postgres::apply_samples(right, &second, &[original.clone(), conflict, extra])
        .await
        .expect("replay");
    assert_eq!(stats.unchanged, 1);
    assert_eq!(stats.conflict, 1);
    assert_eq!(stats.inserted, 1);
    assert_eq!(applied_count(left, tenant, "write").await, 2);
    let bits = stored_bits(left, tenant, "write", "sat", job.logical_window_start).await;
    assert_eq!(bits, format!("{:016x}", 7u64));
    let stale = postgres::finish(
        left,
        &FinishRequest::new(
            "replica-a",
            first.job_id,
            first.fencing_token,
            later,
            accounted(),
        ),
    )
    .await;
    assert!(matches!(stale, Err(QueueError::StaleFence)));
    postgres::finish(
        right,
        &FinishRequest::new(
            "replica-b",
            second.job_id,
            second.fencing_token,
            later,
            accounted(),
        ),
    )
    .await
    .expect("commit")
    .expect("receipt");
    let replay = postgres::finish(
        right,
        &FinishRequest::new(
            "replica-b",
            second.job_id,
            second.fencing_token,
            later,
            accounted(),
        ),
    )
    .await;
    assert!(matches!(replay, Err(QueueError::StaleFence)));
    assert_eq!(receipt_count(left, job.job_id).await, 1);
    let view = postgres::get_job(right, job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "committed");
    assert_eq!(view.coverage, COMPLETE);
}

async fn crash_after_commit(pool: &PgPool, tenant: &str) {
    retire_ready(pool, tenant).await;
    let now = origin();
    let job = enqueue(pool, new_job(tenant, "pg-ack", "ack", 2)).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    let receipt = postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            accounted(),
        ),
    )
    .await
    .expect("commit")
    .expect("receipt");
    let lost = postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            accounted(),
        ),
    )
    .await;
    assert!(matches!(lost, Err(QueueError::StaleFence)));
    assert_eq!(receipt_count(pool, job.job_id).await, 1);
    let stored: String = sqlx::query_scalar(
        "SELECT receipt_id FROM ingest_receipt WHERE job_id = $1 AND tenant_id = $2",
    )
    .bind(job.job_id.to_string())
    .bind(tenant)
    .fetch_one(pool)
    .await
    .expect("receipt id");
    assert_eq!(stored, receipt.receipt_id.to_string());
    let view = postgres::get_job(pool, job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "committed");
}

async fn two_replicas_one_claim(left: &PgPool, right: &PgPool, tenant: &str) {
    retire_ready(left, tenant).await;
    let now = origin();
    let job = enqueue(left, new_job(tenant, "pg-race", "race", 3)).await;
    let (a, b) = tokio::join!(
        claim_for(left, tenant, "replica-a", now),
        claim_for(right, tenant, "replica-b", now),
    );
    assert_eq!(a.len() + b.len(), 1, "one replica owns the job");
    let winner = a.into_iter().chain(b).next().expect("winner");
    assert_eq!(winner.job_id, job.job_id);
    assert_eq!(winner.fencing_token, 1);
}

async fn expired_lease(left: &PgPool, right: &PgPool, tenant: &str) {
    retire_ready(left, tenant).await;
    let now = origin();
    enqueue(left, new_job(tenant, "pg-lease", "lease", 4)).await;
    let first = claim(left, tenant, "replica-a", now).await;
    let early = claim_for(
        right,
        tenant,
        "replica-b",
        now + chrono::Duration::seconds(5),
    )
    .await;
    assert!(early.is_empty(), "unexpired lease is not stolen");
    let later = now + chrono::Duration::seconds(31);
    let second = claim(right, tenant, "replica-b", later).await;
    assert_eq!(second.job_id, first.job_id);
    assert_eq!(second.fencing_token, 2);
    let stale = postgres::finish(
        left,
        &FinishRequest::new(
            "replica-a",
            first.job_id,
            first.fencing_token,
            later,
            accounted(),
        ),
    )
    .await;
    assert!(matches!(stale, Err(QueueError::StaleFence)));
}

async fn throttle_does_not_commit(pool: &PgPool, tenant: &str) {
    retire_ready(pool, tenant).await;
    let now = origin();
    let job = enqueue(pool, new_job(tenant, "pg-throttle", "throttle", 5)).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    let retry_at = now + chrono::Duration::seconds(60);
    let receipt = postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Retry {
                code: "throttled".into(),
                not_before: retry_at,
            },
        ),
    )
    .await
    .expect("throttle");
    assert!(receipt.is_none());
    assert_eq!(receipt_count(pool, job.job_id).await, 0);
    let early = claim_for(
        pool,
        tenant,
        "replica-b",
        now + chrono::Duration::seconds(1),
    )
    .await;
    assert!(early.iter().all(|row| row.job_id != job.job_id));
    let again = claim(pool, tenant, "replica-b", retry_at).await;
    assert_eq!(again.job_id, job.job_id);
    postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-b",
            again.job_id,
            again.fencing_token,
            retry_at,
            FinishOutcome::Retry {
                code: "timeout".into(),
                not_before: retry_at + chrono::Duration::seconds(30),
            },
        ),
    )
    .await
    .expect("timeout");
    let view = postgres::get_job(pool, job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "retry_wait");
    assert_eq!(view.safe_error_code.as_deref(), Some("timeout"));
    assert_eq!(receipt_count(pool, job.job_id).await, 0);
}

async fn model_change_does_not_commit(pool: &PgPool, tenant: &str) {
    retire_ready(pool, tenant).await;
    let now = origin();
    let mut spec = new_job(tenant, "pg-model", "model", 6);
    spec.requested_points_digest = Some("stored-digest".into());
    let job = enqueue(pool, spec).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    let mut changed = FinishRequest::new(
        "replica-a",
        leased.job_id,
        leased.fencing_token,
        now,
        accounted(),
    );
    changed.active_model_revision = Some("rev-next".into());
    let receipt = postgres::finish(pool, &changed).await.expect("model fence");
    assert!(receipt.is_none());
    assert_eq!(receipt_count(pool, job.job_id).await, 0);
    let view = postgres::get_job(pool, job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "permanent_failure");
    assert_eq!(
        view.safe_error_code.as_deref(),
        Some("model_revision_changed")
    );

    let mut digest_job = new_job(tenant, "pg-digest", "digest", 7);
    digest_job.requested_points_digest = Some("stored-digest".into());
    let digest = enqueue(pool, digest_job).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    let mut mismatch = FinishRequest::new(
        "replica-a",
        leased.job_id,
        leased.fencing_token,
        now,
        accounted(),
    );
    mismatch.active_model_revision = Some(REVISION.into());
    mismatch.active_points_digest = Some("other-digest".into());
    postgres::finish(pool, &mismatch)
        .await
        .expect("digest fence");
    let view = postgres::get_job(pool, digest.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "permanent_failure");
    assert_eq!(receipt_count(pool, digest.job_id).await, 0);

    let mut bootstrap = new_job(tenant, "pg-boot", "boot", 8);
    bootstrap.model_revision = MODEL_REVISION_BOOTSTRAP.into();
    let boot = enqueue(pool, bootstrap).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    let mut finish = FinishRequest::new(
        "replica-a",
        leased.job_id,
        leased.fencing_token,
        now,
        accounted(),
    );
    finish.active_model_revision = Some("live-plan".into());
    postgres::finish(pool, &finish)
        .await
        .expect("bootstrap still owns the window")
        .expect("receipt");
    let view = postgres::get_job(pool, boot.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "committed");
}

async fn coverage_round_trip(pool: &PgPool, tenant: &str) {
    retire_ready(pool, tenant).await;
    let now = origin();
    let (start, end) = hour(9);
    let gap = reconcile(&ReconcileInput {
        start,
        end,
        expectations: &[interval("sat", 3600)],
        observations: &[answered("sat", &[end])],
        prior: &[],
        response_complete: true,
    })
    .expect("half-open reconcile");
    assert_eq!(gap.points[0].disposition, GENUINE_GAP);
    assert!(gap.out_of_window >= 1);
    let job = enqueue(pool, new_job(tenant, "pg-cov", "half-open", 9)).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    let refused = postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Committed {
                counts: JobCounts::default(),
                coverage: gap.clone(),
            },
        ),
    )
    .await;
    assert!(matches!(refused, Err(QueueError::Invalid(_))));
    postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Partial {
                counts: JobCounts {
                    fetched: 1,
                    ..JobCounts::default()
                },
                code: gap.block_code(),
                coverage: gap,
            },
        ),
    )
    .await
    .expect("partial");
    let view = postgres::get_job(pool, job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "partial");
    assert_eq!(view.coverage, "incomplete");
    assert_eq!(view.point_coverage[0].disposition, GENUINE_GAP);
    assert_ne!(view.point_coverage[0].disposition, NO_SAMPLE_RECEIVED);

    let quiet = reconcile(&ReconcileInput {
        start,
        end,
        expectations: &[cov("damper")],
        observations: &[answered("damper", &[])],
        prior: &[],
        response_complete: true,
    })
    .expect("cov");
    assert_eq!(quiet.points[0].disposition, NO_SAMPLE_EXPECTED);
    assert!(quiet.allows_commit());
    let cov_job = enqueue(pool, new_job(tenant, "pg-cov2", "cov", 10)).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Committed {
                counts: JobCounts::default(),
                coverage: quiet,
            },
        ),
    )
    .await
    .expect("cov commit")
    .expect("receipt");
    let view = postgres::get_job(pool, cov_job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "committed");
    assert_eq!(view.point_coverage[0].disposition, NO_SAMPLE_EXPECTED);

    let mut fast = Vec::new();
    for step in 0..12 {
        fast.push(start + chrono::Duration::seconds(step * 300));
    }
    fast.remove(3);
    let mixed = reconcile(&ReconcileInput {
        start,
        end,
        expectations: &[
            interval("fast", 300),
            interval("hourly", 3600),
            cov("damper"),
        ],
        observations: &[
            answered("fast", &fast),
            answered("hourly", &[start]),
            answered("damper", &[]),
        ],
        prior: &[],
        response_complete: true,
    })
    .expect("mixed");
    assert!(!mixed.allows_commit());
    let mixed_job = enqueue(pool, new_job(tenant, "pg-mixed", "mixed", 11)).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Partial {
                counts: JobCounts::default(),
                code: mixed.block_code(),
                coverage: mixed,
            },
        ),
    )
    .await
    .expect("mixed partial");
    let view = postgres::get_job(pool, mixed_job.job_id)
        .await
        .expect("read")
        .expect("job");
    let fast = point_row(&view, "fast");
    let hourly = point_row(&view, "hourly");
    let damper = point_row(&view, "damper");
    assert_eq!(fast.disposition, GENUINE_GAP);
    assert_eq!(fast.observed_slots, 11);
    assert_eq!(hourly.disposition, PRESENT);
    assert_eq!(damper.disposition, NO_SAMPLE_EXPECTED);
    assert_eq!(view.state, "partial");

    let spring = DateTime::parse_from_rfc3339("2026-03-08T06:00:00Z")
        .expect("spring")
        .with_timezone(&Utc);
    let spring_end = spring + chrono::Duration::hours(1);
    let mut spring_samples = Vec::new();
    for step in 0..4 {
        spring_samples.push(spring + chrono::Duration::seconds(step * 900));
    }
    let dst = reconcile(&ReconcileInput {
        start: spring,
        end: spring_end,
        expectations: &[interval("zone", 900)],
        observations: &[answered("zone", &spring_samples)],
        prior: &[],
        response_complete: true,
    })
    .expect("dst");
    assert_eq!(dst.points[0].expected_slots, 4);
    assert!(dst.allows_commit());
    let mut dst_job = new_job(tenant, "pg-dst", "dst", 0);
    dst_job.logical_window_start = spring;
    dst_job.logical_window_end = spring_end;
    let stored = enqueue(pool, dst_job).await;
    let leased = claim(pool, tenant, "replica-a", now).await;
    postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Committed {
                counts: JobCounts {
                    fetched: 4,
                    accepted: 4,
                    inserted: 4,
                    ..JobCounts::default()
                },
                coverage: dst,
            },
        ),
    )
    .await
    .expect("dst commit")
    .expect("receipt");
    let view = postgres::get_job(pool, stored.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.point_coverage[0].expected_slots, 4);
    assert_eq!(view.point_coverage[0].disposition, PRESENT);
    assert_eq!(
        (view.logical_window_end - view.logical_window_start).num_seconds(),
        3600
    );

    let prior = super::coverage::PointCoverage {
        point_id: "sat".into(),
        disposition: GENUINE_GAP.into(),
        expected_slots: 1,
        observed_slots: 0,
        late_slots: 0,
    };
    let late = reconcile(&ReconcileInput {
        start,
        end,
        expectations: &[interval("sat", 3600)],
        observations: &[answered("sat", &[start + chrono::Duration::minutes(10)])],
        prior: &[prior],
        response_complete: true,
    })
    .expect("late");
    assert!(late.allows_commit());
    assert_eq!(late.points[0].disposition, "late_arrival");
    let retry_claim = IdempotencyClaim {
        actor: "w3b-operator".into(),
        tenant_id: tenant.to_string(),
        client_key: format!("retry-{tenant}-half-open"),
        object_id: retry_object_id(job.job_id),
        payload_hash: retry_payload_hash(tenant, job.job_id),
    };
    postgres::retry_job(pool, job.job_id, now, &retry_claim)
        .await
        .expect("retry partial");
    let leased = claim(pool, tenant, "replica-a", now).await;
    assert_eq!(leased.job_id, job.job_id);
    postgres::finish(
        pool,
        &FinishRequest::new(
            "replica-a",
            leased.job_id,
            leased.fencing_token,
            now,
            FinishOutcome::Committed {
                counts: JobCounts {
                    fetched: 1,
                    accepted: 1,
                    inserted: 1,
                    ..JobCounts::default()
                },
                coverage: late,
            },
        ),
    )
    .await
    .expect("late commit")
    .expect("receipt");
    let view = postgres::get_job(pool, job.job_id)
        .await
        .expect("read")
        .expect("job");
    assert_eq!(view.state, "committed");
    assert_eq!(view.point_coverage[0].disposition, "late_arrival");
    assert_eq!(view.point_coverage[0].late_slots, 1);
}

async fn duplicate_enqueue_and_value(pool: &PgPool, tenant: &str) {
    retire_ready(pool, tenant).await;
    let now = origin();
    let spec = new_job(tenant, "pg-dup", "dup", 12);
    let job = enqueue(pool, spec.clone()).await;
    let again = postgres::enqueue(pool, &spec)
        .await
        .expect("second enqueue");
    match again {
        EnqueueOutcome::Existing(view) => assert_eq!(view.job_id, job.job_id),
        EnqueueOutcome::Created(_) => panic!("duplicate identity inserted a second job"),
    }
    let leased = claim(pool, tenant, "replica-a", now).await;
    let original = sample("sat", job.logical_window_start, 11);
    postgres::apply_samples(pool, &leased, std::slice::from_ref(&original))
        .await
        .expect("insert");
    let mut other = original.clone();
    other.value_bits = 99;
    let stats = postgres::apply_samples(pool, &leased, &[original.clone(), other])
        .await
        .expect("conflict");
    assert_eq!(stats.unchanged, 1);
    assert_eq!(stats.conflict, 1);
    assert_eq!(stats.inserted, 0);
    assert_eq!(applied_count(pool, tenant, "dup").await, 1);
    let bits = stored_bits(pool, tenant, "dup", "sat", job.logical_window_start).await;
    assert_eq!(bits, format!("{:016x}", 11u64));
    let mut skewed = spec;
    skewed.logical_window_start = origin() + chrono::Duration::seconds(30);
    skewed.logical_window_end = skewed.logical_window_start + chrono::Duration::seconds(60);
    let err = postgres::enqueue(pool, &skewed).await.expect_err("skew");
    assert!(matches!(err, QueueError::Invalid(_)));
}

fn point_row<'a>(view: &'a JobView, point_id: &str) -> &'a super::coverage::PointCoverage {
    view.point_coverage
        .iter()
        .find(|point| point.point_id == point_id)
        .unwrap_or_else(|| panic!("missing point {point_id}"))
}

fn interval(point: &str, cadence: i64) -> PointExpectation {
    PointExpectation {
        point_id: point.to_string(),
        expectation: Expectation::Interval {
            cadence_secs: cadence,
        },
    }
}

fn cov(point: &str) -> PointExpectation {
    PointExpectation {
        point_id: point.to_string(),
        expectation: Expectation::Cov {
            heartbeat_secs: None,
            last_sample_at: None,
        },
    }
}

fn answered(point: &str, timestamps: &[DateTime<Utc>]) -> PointObservation {
    PointObservation {
        point_id: point.to_string(),
        returned: true,
        timestamps: timestamps.to_vec(),
    }
}

async fn enqueue(pool: &PgPool, job: NewJob) -> JobView {
    created(postgres::enqueue(pool, &job).await.expect("enqueue"))
}

async fn claim(pool: &PgPool, tenant: &str, owner: &str, now: DateTime<Utc>) -> JobView {
    let mut rows = claim_for(pool, tenant, owner, now).await;
    assert_eq!(rows.len(), 1, "expected one leased job for {owner}");
    rows.pop().expect("leased job")
}

/// Claim only this fixture's tenant. The product claim is hub-wide; a shared
/// test database can hold other suites' rows.
async fn claim_for(pool: &PgPool, tenant: &str, owner: &str, now: DateTime<Utc>) -> Vec<JobView> {
    let sql = postgres::CLAIM_SELECT_SQL.replacen("WHERE (", "WHERE j.tenant_id = $3 AND (", 1);
    let mut tx = pool.begin().await.expect("begin claim");
    let mut ids = Vec::new();
    let row = sqlx::query(&sql)
        .bind(now)
        .bind(i32::try_from(budget().max_in_flight).unwrap_or(4))
        .bind(tenant)
        .fetch_optional(&mut *tx)
        .await
        .expect("select claim");
    if let Some(row) = row {
        let job_id: String = row.try_get("job_id").expect("job id");
        let expiry = now + chrono::Duration::seconds(30);
        sqlx::query(
            "UPDATE ingest_job SET
                state = 'leased', lease_owner = $2, lease_expiry = $3,
                fencing_token = fencing_token + 1, attempt = attempt + 1,
                safe_error_code = NULL, updated_at = $4
             WHERE job_id = $1",
        )
        .bind(&job_id)
        .bind(owner)
        .bind(expiry)
        .bind(now)
        .execute(&mut *tx)
        .await
        .expect("lease");
        ids.push(job_id);
    }
    tx.commit().await.expect("commit claim");
    let mut views = Vec::new();
    for id in ids {
        let id = Uuid::parse_str(&id).expect("job uuid");
        views.push(
            postgres::get_job(pool, id)
                .await
                .expect("read claimed job")
                .expect("claimed job"),
        );
    }
    views
}

async fn receipt_count(pool: &PgPool, job_id: Uuid) -> i64 {
    sqlx::query_scalar("SELECT COUNT(*) FROM ingest_receipt WHERE job_id = $1")
        .bind(job_id.to_string())
        .fetch_one(pool)
        .await
        .expect("receipt count")
}

async fn applied_count(pool: &PgPool, tenant: &str, device: &str) -> i64 {
    sqlx::query_scalar(
        "SELECT COUNT(*) FROM ingest_applied_sample WHERE tenant_id = $1 AND device_id = $2",
    )
    .bind(tenant)
    .bind(device)
    .fetch_one(pool)
    .await
    .expect("applied count")
}

async fn stored_bits(
    pool: &PgPool,
    tenant: &str,
    device: &str,
    point: &str,
    ts: DateTime<Utc>,
) -> String {
    sqlx::query_scalar(
        "SELECT value_bits FROM ingest_applied_sample
         WHERE tenant_id = $1 AND device_id = $2 AND point_id = $3 AND ts = $4",
    )
    .bind(tenant)
    .bind(device)
    .bind(point)
    .bind(ts)
    .fetch_one(pool)
    .await
    .expect("stored bits")
}

async fn purge(pool: &PgPool, tenant: &str) {
    for stmt in [
        "DELETE FROM ingest_point_coverage WHERE job_id IN (SELECT job_id FROM ingest_job WHERE tenant_id = $1)",
        "DELETE FROM ingest_applied_sample WHERE tenant_id = $1",
        "DELETE FROM ingest_receipt WHERE tenant_id = $1",
        "DELETE FROM ingest_job WHERE tenant_id = $1",
        "DELETE FROM ingest_idempotency WHERE tenant_id = $1",
    ] {
        sqlx::query(stmt)
            .bind(tenant)
            .execute(pool)
            .await
            .expect("purge durability fixture");
    }
}
