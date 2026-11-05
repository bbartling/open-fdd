//! Retention of the applied-sample ledger and the replay horizon it leaves.
//!
//! Memory always runs. PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is
//! set, and is required when `OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED=1`.

use chrono::{DateTime, Duration, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use uuid::Uuid;

use super::memory::MemoryStore;
use super::model::*;
use super::postgres;
use super::replay_horizon::REPLAY_HORIZON_EXCEEDED;

const SITE: &str = "w7a-site";
const PORTAL: &str = "w7a-portal";
const REVISION: &str = "rev-w7a";

fn origin() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-15T00:00:00Z")
        .expect("replay horizon origin")
        .with_timezone(&Utc)
}

fn at(hours: i64) -> DateTime<Utc> {
    origin() + Duration::hours(hours)
}

/// Every window is older than the retention below, except hour 90.
fn now() -> DateTime<Utc> {
    at(300)
}

fn retention() -> Duration {
    Duration::hours(216)
}

fn new_job(tenant: &str, device: &str, hour: i64) -> NewJob {
    NewJob {
        tenant_id: tenant.to_string(),
        canonical_site: SITE.into(),
        provider_instance_id: PORTAL.into(),
        device_id: device.to_string(),
        model_revision: REVISION.into(),
        logical_window_start: at(hour),
        logical_window_end: at(hour + 1),
        shard: String::new(),
        not_before: origin(),
        estimated_cost: 1,
        requested_points_digest: None,
    }
}

fn retry_claim(tenant: &str, job_id: Uuid) -> IdempotencyClaim {
    IdempotencyClaim {
        actor: "w7a-operator".into(),
        tenant_id: tenant.to_string(),
        client_key: format!("retry-{job_id}"),
        object_id: retry_object_id(job_id),
        payload_hash: retry_payload_hash(tenant, job_id),
    }
}

fn backfill_claim(tenant: &str, jobs: &[NewJob]) -> IdempotencyClaim {
    IdempotencyClaim {
        actor: "w7a-operator".into(),
        tenant_id: tenant.to_string(),
        client_key: format!("backfill-{}", Uuid::new_v4().simple()),
        object_id: backfill_object_id(&jobs[0]),
        payload_hash: backfill_payload_hash(jobs).expect("backfill hash"),
    }
}

fn created(outcome: EnqueueOutcome) -> JobView {
    match outcome {
        EnqueueOutcome::Created(view) => view,
        EnqueueOutcome::Existing(view) => panic!("expected a new job, found {}", view.job_id),
    }
}

fn is_horizon_refusal(err: &QueueError) -> bool {
    matches!(err, QueueError::ReplayHorizon(msg) if msg.starts_with(REPLAY_HORIZON_EXCEEDED))
}

fn memory_store() -> MemoryStore {
    MemoryStore::new(BudgetDefaults {
        max_in_flight: 4,
        max_per_minute: 1000,
    })
}

/// Enqueues, claims, and finishes one memory job, recording one ledger sample
/// at the window start when `sample` is set.
fn memory_finished(
    store: &MemoryStore,
    tenant: &str,
    device: &str,
    hour: i64,
    outcome: FinishOutcome,
    sample: bool,
) -> JobView {
    let job = created(
        store
            .enqueue(new_job(tenant, device, hour), now())
            .expect("enqueue"),
    );
    let mut leased = store.claim(&ClaimRequest {
        owner: "w7a-replica".into(),
        limit: 1,
        now: now(),
        lease_for: Duration::seconds(30),
    });
    assert_eq!(leased.len(), 1, "one leased job");
    let leased = leased.pop().expect("leased job");
    assert_eq!(leased.job_id, job.job_id);
    if sample {
        store
            .apply_samples(
                &leased,
                &[AppliedSample {
                    point_id: "sat".into(),
                    ts: at(hour),
                    value_bits: 7,
                }],
            )
            .expect("apply sample");
    }
    store
        .finish(&FinishRequest::new(
            "w7a-replica",
            leased.job_id,
            leased.fencing_token,
            now(),
            outcome,
        ))
        .expect("finish");
    job
}

fn permanent() -> FinishOutcome {
    FinishOutcome::Permanent {
        code: "w7a_failure".into(),
    }
}

fn committed() -> FinishOutcome {
    FinishOutcome::committed_accounted(JobCounts {
        fetched: 1,
        accepted: 1,
        rejected: 0,
        inserted: 1,
        ..JobCounts::default()
    })
}

#[test]
fn memory_prune_keeps_live_jobs_and_refuses_replay_before_the_horizon() {
    let tenant = "w7a-memory";
    let store = memory_store();
    memory_finished(&store, tenant, "old", 0, committed(), true);
    memory_finished(&store, tenant, "kept", 60, committed(), true);
    let early = memory_finished(&store, tenant, "early", 10, permanent(), false);
    let edge = memory_finished(&store, tenant, "edge", 50, permanent(), false);
    created(
        store
            .enqueue(new_job(tenant, "live", 50), now())
            .expect("live job"),
    );

    let report = store.prune_applied_samples(tenant, SITE, now(), retention());
    assert_eq!(report.deleted, 1, "only the row before the live job goes");
    assert_eq!(
        report.pruned_before,
        at(50),
        "the cut stops at the live job"
    );
    let other = store.prune_applied_samples("w7a-other", SITE, now(), retention());
    assert_eq!(other.deleted, 0);

    let refused = store
        .retry_job(early.job_id, now(), &retry_claim(tenant, early.job_id))
        .expect_err("retry before the horizon");
    assert!(is_horizon_refusal(&refused), "{refused}");
    store
        .retry_job(edge.job_id, now(), &retry_claim(tenant, edge.job_id))
        .expect("retry at the horizon");

    let before = vec![new_job(tenant, "backfill", 49)];
    let refused = store
        .backfill(before.clone(), now(), &backfill_claim(tenant, &before))
        .expect_err("backfill before the horizon");
    assert!(is_horizon_refusal(&refused), "{refused}");
    let after = vec![new_job(tenant, "backfill", 51)];
    let made = store
        .backfill(after.clone(), now(), &backfill_claim(tenant, &after))
        .expect("backfill after the horizon");
    assert_eq!(made.len(), 1);

    let earlier =
        store.prune_applied_samples(tenant, SITE, now() - Duration::hours(100), retention());
    assert_eq!(
        earlier.pruned_before,
        at(50),
        "the horizon never moves back"
    );
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize ingest DDL with other queue fixtures"
)]
async fn postgres_prune_keeps_live_jobs_and_refuses_replay_before_the_horizon() {
    let required = std::env::var("OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    let Some(url) = url else {
        if required {
            panic!("OPENFDD_TEST_DATABASE_URL is required for the replay horizon fixture");
        }
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .unwrap_or_else(|err| {
            panic!(
                "replay horizon postgres connect failed: {}",
                redact_db_text(&err.to_string())
            )
        });
    crate::ingest_queue::test_schema::apply_ingest_queue_schema(&pool)
        .await
        .expect("ingest schema");
    let tenant = format!("w7a-{}", &Uuid::new_v4().simple().to_string()[..12]);
    postgres_suite(&pool, &tenant).await;
    purge(&pool, &tenant).await;
}

async fn pg_job(pool: &PgPool, tenant: &str, device: &str, hour: i64, state: &str) -> JobView {
    let job = created(
        postgres::enqueue(pool, &new_job(tenant, device, hour))
            .await
            .expect("enqueue"),
    );
    if state != JobState::Queued.as_str() {
        sqlx::query("UPDATE ingest_job SET state = $2, safe_error_code = $3 WHERE job_id = $1")
            .bind(job.job_id.to_string())
            .bind(state)
            .bind((state == JobState::PermanentFailure.as_str()).then_some("w7a_failure"))
            .execute(pool)
            .await
            .expect("set job state");
    }
    job
}

async fn pg_sample(pool: &PgPool, tenant: &str, job: &JobView) {
    sqlx::query(
        "INSERT INTO ingest_applied_sample (
            tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
            point_id, ts, value_bits, first_job_id
         ) VALUES ($1, $2, $3, $4, $5, 'sat', $6, '7', $7)",
    )
    .bind(tenant)
    .bind(SITE)
    .bind(PORTAL)
    .bind(&job.device_id)
    .bind(REVISION)
    .bind(job.logical_window_start)
    .bind(job.job_id.to_string())
    .execute(pool)
    .await
    .expect("ledger row");
}

async fn ledger_rows(pool: &PgPool, tenant: &str) -> Vec<String> {
    sqlx::query_scalar(
        "SELECT device_id FROM ingest_applied_sample WHERE tenant_id = $1 ORDER BY device_id",
    )
    .bind(tenant)
    .fetch_all(pool)
    .await
    .expect("ledger rows")
}

async fn device_jobs(pool: &PgPool, tenant: &str, device: &str) -> i64 {
    sqlx::query_scalar("SELECT COUNT(*) FROM ingest_job WHERE tenant_id = $1 AND device_id = $2")
        .bind(tenant)
        .bind(device)
        .fetch_one(pool)
        .await
        .expect("job count")
}

async fn postgres_suite(pool: &PgPool, tenant: &str) {
    let old = pg_job(pool, tenant, "old", 0, JobState::Committed.as_str()).await;
    let kept = pg_job(pool, tenant, "kept", 60, JobState::Committed.as_str()).await;
    let live_old = pg_job(pool, tenant, "live", 50, JobState::Queued.as_str()).await;
    pg_sample(pool, tenant, &old).await;
    pg_sample(pool, tenant, &kept).await;
    pg_sample(pool, tenant, &live_old).await;
    let early = pg_job(
        pool,
        tenant,
        "early",
        10,
        JobState::PermanentFailure.as_str(),
    )
    .await;
    let edge = pg_job(
        pool,
        tenant,
        "edge",
        50,
        JobState::PermanentFailure.as_str(),
    )
    .await;

    let report = postgres::prune_applied_samples(pool, tenant, SITE, now(), retention())
        .await
        .expect("prune");
    assert_eq!(report.deleted, 1, "only the row before the live job goes");
    assert_eq!(
        report.pruned_before,
        at(50),
        "the cut stops at the live job"
    );
    assert_eq!(ledger_rows(pool, tenant).await, vec!["kept", "live"]);
    let other =
        postgres::prune_applied_samples(pool, &format!("{tenant}-x"), SITE, now(), retention())
            .await
            .expect("prune other tenant");
    assert_eq!(other.deleted, 0);
    assert_eq!(ledger_rows(pool, tenant).await, vec!["kept", "live"]);

    let refused = postgres::retry_job(
        pool,
        early.job_id,
        now(),
        &retry_claim(tenant, early.job_id),
    )
    .await
    .expect_err("retry before the horizon");
    assert!(is_horizon_refusal(&refused), "{refused}");
    let state: String = sqlx::query_scalar("SELECT state FROM ingest_job WHERE job_id = $1")
        .bind(early.job_id.to_string())
        .fetch_one(pool)
        .await
        .expect("early state");
    assert_eq!(
        state,
        JobState::PermanentFailure.as_str(),
        "refusal changes nothing"
    );
    postgres::retry_job(pool, edge.job_id, now(), &retry_claim(tenant, edge.job_id))
        .await
        .expect("retry at the horizon");

    let before = vec![new_job(tenant, "backfill", 49)];
    let refused = postgres::backfill(pool, &before, now(), &backfill_claim(tenant, &before))
        .await
        .expect_err("backfill before the horizon");
    assert!(is_horizon_refusal(&refused), "{refused}");
    assert_eq!(
        device_jobs(pool, tenant, "backfill").await,
        0,
        "refusal enqueues nothing"
    );
    let after = vec![new_job(tenant, "backfill", 51)];
    let made = postgres::backfill(pool, &after, now(), &backfill_claim(tenant, &after))
        .await
        .expect("backfill after the horizon");
    assert_eq!(made.len(), 1);

    // Once the live job and the retried job finish, the cut moves to the
    // retention edge; an earlier clock never moves it back.
    sqlx::query("UPDATE ingest_job SET state = 'committed' WHERE tenant_id = $1 AND state IN ('queued', 'leased', 'retry_wait')")
        .bind(tenant)
        .execute(pool)
        .await
        .expect("finish live jobs");
    let moved = postgres::prune_applied_samples(pool, tenant, SITE, now(), retention())
        .await
        .expect("second prune");
    assert_eq!(moved.pruned_before, now() - retention());
    assert_eq!(moved.deleted, 2);
    assert!(ledger_rows(pool, tenant).await.is_empty());
    let earlier = postgres::prune_applied_samples(
        pool,
        tenant,
        SITE,
        now() - Duration::hours(100),
        retention(),
    )
    .await
    .expect("earlier prune");
    assert_eq!(
        earlier.pruned_before,
        now() - retention(),
        "the horizon never moves back"
    );
}

async fn purge(pool: &PgPool, tenant: &str) {
    for stmt in [
        "DELETE FROM ingest_applied_sample WHERE tenant_id LIKE $1 || '%'",
        "DELETE FROM ingest_applied_sample_horizon WHERE tenant_id LIKE $1 || '%'",
        "DELETE FROM ingest_job WHERE tenant_id = $1",
        "DELETE FROM ingest_idempotency WHERE tenant_id = $1",
    ] {
        sqlx::query(stmt)
            .bind(tenant)
            .execute(pool)
            .await
            .expect("purge replay horizon fixture");
    }
}
