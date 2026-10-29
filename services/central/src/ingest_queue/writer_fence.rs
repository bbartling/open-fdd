//! A stale ingest worker must not change canonical Timescale history.
//!
//! Two pools are two replicas. Worker A claims a window, fetches, and pauses
//! before its canonical write. Its lease expires, worker B reclaims, writes a
//! different value, and commits. A then resumes. The assertions read the
//! `sample` table, not only the queue ledger. Runs when
//! `OPENFDD_TEST_DATABASE_URL` is set; required when
//! `OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED=1`.

use chrono::{DateTime, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};
use tokio::sync::oneshot;
use uuid::Uuid;

use super::model::*;
use super::postgres::{self, CanonicalWindow, WindowWrite};
use crate::providers::types::NormalizedSample;

const REVISION: &str = "rev-fence";
const PORTAL: &str = "portal-fence";
const DEVICE: &str = "AHU_FENCE";
const POINT: &str = "nf-point-fence-sat";
const LEASE_SECS: i64 = 180;

fn origin() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-07-01T00:00:00Z")
        .expect("fence origin")
        .with_timezone(&Utc)
}

fn window(offset: i64) -> (DateTime<Utc>, DateTime<Utc>) {
    let start = origin() + chrono::Duration::hours(offset);
    (start, start + chrono::Duration::hours(1))
}

fn sample_ts(offset: i64) -> DateTime<Utc> {
    window(offset).0 + chrono::Duration::minutes(1)
}

struct Scope {
    tenant: String,
    site: String,
}

/// What a worker fetched from the portal: canonical rows plus ledger rows.
struct Fetched {
    rows: fdd_tsdb::UpsertBatch,
    applied: Vec<AppliedSample>,
}

fn fetch(scope: &Scope, offset: i64, val: f64) -> Fetched {
    let ts = sample_ts(offset);
    let sample = NormalizedSample {
        building_id: scope.site.clone(),
        provider_instance_id: PORTAL.into(),
        equipment_id: DEVICE.into(),
        provider_point_id: POINT.into(),
        role: "sat".into(),
        equip_type: Some("ahu".into()),
        ts,
        val,
        unit: Some("degF".into()),
        source_quality: None,
        attrs: serde_json::Map::new(),
    };
    let rows = crate::providers::writer::project_historian_rows(&scope.site, &[sample])
        .expect("project canonical rows");
    assert_eq!(rows.len(), 1);
    Fetched {
        rows: fdd_tsdb::UpsertBatch { rows },
        applied: vec![AppliedSample {
            point_id: POINT.into(),
            ts,
            value_bits: val.to_bits(),
        }],
    }
}

async fn write(
    pool: &PgPool,
    job: &JobView,
    now: DateTime<Utc>,
    fetched: &Fetched,
) -> Result<WindowWrite, QueueError> {
    postgres::commit_window(
        pool,
        job,
        now,
        &CanonicalWindow {
            equip_type: Some("ahu"),
            rows: &fetched.rows,
            applied: &fetched.applied,
        },
    )
    .await
}

fn finish_req(owner: &str, job: &JobView, now: DateTime<Utc>) -> FinishRequest {
    FinishRequest::new(
        owner,
        job.job_id,
        job.fencing_token,
        now,
        FinishOutcome::committed_accounted(JobCounts {
            fetched: 1,
            accepted: 1,
            inserted: 1,
            ..JobCounts::default()
        }),
    )
}

struct WorkerResult {
    wrote: Result<WindowWrite, QueueError>,
    finished: Result<Option<ReceiptView>, QueueError>,
}

/// Worker A after claim: fetch, report the fetch, wait at the barrier, then
/// write and finish with the wall time it resumes at.
struct PausedWorker {
    fetched: oneshot::Receiver<()>,
    release: oneshot::Sender<DateTime<Utc>>,
    done: tokio::task::JoinHandle<WorkerResult>,
}

fn spawn_paused_worker(pool: PgPool, job: JobView, fetched: Fetched) -> PausedWorker {
    let (fetched_tx, fetched_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel::<DateTime<Utc>>();
    let done = tokio::spawn(async move {
        fetched_tx.send(()).expect("report fetch");
        let resumed_at = release_rx.await.expect("barrier release");
        let wrote = write(&pool, &job, resumed_at, &fetched).await;
        let finished = postgres::finish(&pool, &finish_req("replica-a", &job, resumed_at)).await;
        WorkerResult { wrote, finished }
    });
    PausedWorker {
        fetched: fetched_rx,
        release: release_tx,
        done,
    }
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize ingest schema DDL with the other queue fixtures"
)]
async fn stale_worker_cannot_overwrite_canonical_history() {
    let required = std::env::var("OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
    let Some(url) = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    else {
        if required {
            panic!("OPENFDD_TEST_DATABASE_URL is required for the writer fence fixture");
        }
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let replica_a = connect(&url, "replica a").await;
    let replica_b = connect(&url, "replica b").await;
    postgres::apply_schema(&replica_a)
        .await
        .expect("ingest schema");
    apply_historian_schema(&replica_a).await;
    let id = Uuid::new_v4().simple().to_string();
    let scope = Scope {
        tenant: format!("wfence-{}", &id[..12]),
        site: format!("WFENCE_{}", &id[..12]),
    };
    stale_owner_is_fenced(&replica_a, &replica_b, &scope).await;
    live_owner_commits(&replica_a, &replica_b, &scope).await;
    purge(&replica_a, &scope).await;
}

async fn stale_owner_is_fenced(replica_a: &PgPool, replica_b: &PgPool, scope: &Scope) {
    let t0 = origin();
    let job = enqueue(replica_a, scope, 0).await;
    let leased_a = claim_one(replica_a, &scope.tenant, "replica-a", t0).await;
    assert_eq!(leased_a.job_id, job.job_id);
    let mut worker_a =
        spawn_paused_worker(replica_a.clone(), leased_a.clone(), fetch(scope, 0, 1.0));
    (&mut worker_a.fetched).await.expect("worker a fetched");

    let reclaim_at = t0 + chrono::Duration::seconds(LEASE_SECS + 1);
    let leased_b = claim_one(replica_b, &scope.tenant, "replica-b", reclaim_at).await;
    assert_eq!(leased_b.job_id, job.job_id);
    assert_eq!(leased_b.fencing_token, leased_a.fencing_token + 1);
    let wrote_b = write(replica_b, &leased_b, reclaim_at, &fetch(scope, 0, 2.0))
        .await
        .expect("owner b canonical write");
    assert_eq!(wrote_b.samples.inserted, 1);
    postgres::finish(replica_b, &finish_req("replica-b", &leased_b, reclaim_at))
        .await
        .expect("owner b finish")
        .expect("owner b receipt");

    let resumed_at = reclaim_at + chrono::Duration::seconds(1);
    worker_a.release.send(resumed_at).expect("release a");
    let WorkerResult {
        wrote: wrote_a,
        finished: finished_a,
    } = worker_a.done.await.expect("worker a task");

    assert!(
        matches!(finished_a, Err(QueueError::StaleFence)),
        "stale owner finish must be rejected, got {finished_a:?}"
    );
    assert_eq!(
        canonical_values(replica_b, &scope.site, sample_ts(0)).await,
        vec![fdd_core::fahrenheit_to_celsius(2.0)],
        "canonical history must keep the reclaiming owner's value"
    );
    assert!(
        matches!(wrote_a, Err(QueueError::StaleFence)),
        "stale owner canonical write must be rejected, got {wrote_a:?}"
    );
    assert_eq!(
        ledger_bits(replica_b, scope, sample_ts(0)).await,
        vec![format!("{:016x}", 2.0f64.to_bits())]
    );
    assert_eq!(receipt_count(replica_b, job.job_id).await, 1);
    assert_eq!(job_state(replica_b, job.job_id).await, "committed");
}

async fn live_owner_commits(replica_a: &PgPool, replica_b: &PgPool, scope: &Scope) {
    let t0 = origin();
    let job = enqueue(replica_a, scope, 1).await;
    let leased_a = claim_one(replica_a, &scope.tenant, "replica-a", t0).await;
    assert_eq!(leased_a.job_id, job.job_id);
    let mut worker_a =
        spawn_paused_worker(replica_a.clone(), leased_a.clone(), fetch(scope, 1, 1.0));
    (&mut worker_a.fetched).await.expect("worker a fetched");

    let just_under = t0 + chrono::Duration::seconds(LEASE_SECS - 1);
    let stolen = claim_for(replica_b, &scope.tenant, "replica-b", just_under).await;
    assert!(stolen.is_empty(), "an unexpired lease is not reclaimed");

    worker_a.release.send(just_under).expect("release a");
    let WorkerResult {
        wrote: wrote_a,
        finished: finished_a,
    } = worker_a.done.await.expect("worker a task");
    let wrote_a = wrote_a.expect("owner a canonical write");
    assert_eq!(wrote_a.samples.inserted, 1);
    assert_eq!(wrote_a.ledger.inserted, 1);
    finished_a
        .expect("owner a finish")
        .expect("owner a receipt");
    assert_eq!(
        canonical_values(replica_b, &scope.site, sample_ts(1)).await,
        vec![fdd_core::fahrenheit_to_celsius(1.0)]
    );
    assert_eq!(receipt_count(replica_b, job.job_id).await, 1);
    assert_eq!(job_state(replica_b, job.job_id).await, "committed");
}

async fn connect(url: &str, label: &str) -> PgPool {
    PgPoolOptions::new()
        .max_connections(2)
        .connect(url)
        .await
        .unwrap_or_else(|err| {
            panic!(
                "writer fence {label} connect failed: {}",
                redact_db_text(&err.to_string())
            )
        })
}

async fn enqueue(pool: &PgPool, scope: &Scope, offset: i64) -> JobView {
    let (start, end) = window(offset);
    let job = NewJob {
        tenant_id: scope.tenant.clone(),
        canonical_site: scope.site.clone(),
        provider_instance_id: PORTAL.into(),
        device_id: DEVICE.into(),
        model_revision: REVISION.into(),
        logical_window_start: start,
        logical_window_end: end,
        shard: String::new(),
        not_before: origin(),
        estimated_cost: 1,
        requested_points_digest: None,
    };
    match postgres::enqueue(pool, &job).await.expect("enqueue") {
        EnqueueOutcome::Created(view) => view,
        EnqueueOutcome::Existing(view) => panic!("expected a new job, found {}", view.job_id),
    }
}

async fn claim_one(pool: &PgPool, tenant: &str, owner: &str, now: DateTime<Utc>) -> JobView {
    let mut rows = claim_for(pool, tenant, owner, now).await;
    assert_eq!(rows.len(), 1, "expected one leased job for {owner}");
    rows.pop().expect("leased job")
}

/// The product claim with a tenant filter and the worker's lease length. A
/// shared test database can hold other suites' rows.
async fn claim_for(pool: &PgPool, tenant: &str, owner: &str, now: DateTime<Utc>) -> Vec<JobView> {
    let sql = postgres::CLAIM_SELECT_SQL.replacen("WHERE (", "WHERE j.tenant_id = $3 AND (", 1);
    let mut tx = pool.begin().await.expect("begin claim");
    let row = sqlx::query(&sql)
        .bind(now)
        .bind(4i32)
        .bind(tenant)
        .fetch_optional(&mut *tx)
        .await
        .expect("select claim");
    let mut ids = Vec::new();
    if let Some(row) = row {
        let job_id: String = row.try_get("job_id").expect("job id");
        sqlx::query(
            "UPDATE ingest_job SET
                state = 'leased', lease_owner = $2, lease_expiry = $3,
                fencing_token = fencing_token + 1, attempt = attempt + 1,
                safe_error_code = NULL, updated_at = $4
             WHERE job_id = $1",
        )
        .bind(&job_id)
        .bind(owner)
        .bind(now + chrono::Duration::seconds(LEASE_SECS))
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

async fn canonical_values(pool: &PgPool, site: &str, ts: DateTime<Utc>) -> Vec<f64> {
    sqlx::query_scalar(
        "SELECT s.val FROM sample s
         JOIN point_map p ON p.site_id = s.site_id AND p.openfdd_key = s.openfdd_key
         WHERE s.site_id = $1 AND p.portal_point_id = $2 AND s.ts = $3
         ORDER BY s.openfdd_key",
    )
    .bind(site)
    .bind(POINT)
    .bind(ts)
    .fetch_all(pool)
    .await
    .expect("canonical samples")
}

async fn ledger_bits(pool: &PgPool, scope: &Scope, ts: DateTime<Utc>) -> Vec<String> {
    sqlx::query_scalar(
        "SELECT value_bits FROM ingest_applied_sample
         WHERE tenant_id = $1 AND canonical_site = $2 AND point_id = $3 AND ts = $4",
    )
    .bind(&scope.tenant)
    .bind(&scope.site)
    .bind(POINT)
    .bind(ts)
    .fetch_all(pool)
    .await
    .expect("ledger bits")
}

async fn receipt_count(pool: &PgPool, job_id: Uuid) -> i64 {
    sqlx::query_scalar("SELECT COUNT(*) FROM ingest_receipt WHERE job_id = $1")
        .bind(job_id.to_string())
        .fetch_one(pool)
        .await
        .expect("receipt count")
}

async fn job_state(pool: &PgPool, job_id: Uuid) -> String {
    sqlx::query_scalar("SELECT state FROM ingest_job WHERE job_id = $1")
        .bind(job_id.to_string())
        .fetch_one(pool)
        .await
        .expect("job state")
}

/// Plain-Postgres copy of the historian tables the provider write touches.
/// CI's default database has no Timescale extension.
async fn apply_historian_schema(pool: &PgPool) {
    for statement in [
        "CREATE TABLE IF NOT EXISTS site (
            site_id text PRIMARY KEY,
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS building (
            building_id text PRIMARY KEY,
            site_id text REFERENCES site(site_id),
            dis text,
            timezone text NOT NULL DEFAULT 'UTC',
            created_at timestamptz NOT NULL DEFAULT now()
        )",
        "CREATE TABLE IF NOT EXISTS equipment (
            building_id text NOT NULL REFERENCES building(building_id),
            equipment_id text NOT NULL,
            equip_type text,
            parent_equipment_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (building_id, equipment_id)
        )",
        "CREATE TABLE IF NOT EXISTS sample (
            ts timestamptz NOT NULL,
            site_id text NOT NULL,
            openfdd_key text NOT NULL,
            haystack_id text,
            val double precision,
            unit text,
            quality text,
            PRIMARY KEY (site_id, openfdd_key, ts)
        )",
        "CREATE TABLE IF NOT EXISTS role_map (
            building_id text NOT NULL,
            equipment_id text NOT NULL,
            openfdd_key text NOT NULL,
            role text NOT NULL,
            unit text,
            PRIMARY KEY (building_id, equipment_id, openfdd_key)
        )",
        "CREATE TABLE IF NOT EXISTS point_map (
            site_id text NOT NULL REFERENCES site(site_id),
            openfdd_key text NOT NULL,
            haystack_id text NOT NULL,
            role text,
            unit text,
            equipment_id text,
            PRIMARY KEY (site_id, openfdd_key)
        )",
        "ALTER TABLE sample ADD COLUMN IF NOT EXISTS haystack_id text",
        "ALTER TABLE sample ADD COLUMN IF NOT EXISTS unit text",
        "ALTER TABLE sample ADD COLUMN IF NOT EXISTS quality text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS portal_point_id text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS referenced boolean NOT NULL DEFAULT true",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS provider_instance_id text",
        "CREATE UNIQUE INDEX IF NOT EXISTS point_map_site_portal_point_uidx
            ON point_map (site_id, portal_point_id)
            WHERE portal_point_id IS NOT NULL",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS source_unit text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS source_history_mode text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS quantity text",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS cadence_secs bigint",
        "ALTER TABLE point_map ADD COLUMN IF NOT EXISTS history_mode text",
    ] {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
}

async fn purge(pool: &PgPool, scope: &Scope) {
    for (stmt, key) in [
        (
            "DELETE FROM ingest_point_coverage WHERE job_id IN (SELECT job_id FROM ingest_job WHERE tenant_id = $1)",
            &scope.tenant,
        ),
        ("DELETE FROM ingest_applied_sample WHERE tenant_id = $1", &scope.tenant),
        ("DELETE FROM ingest_receipt WHERE tenant_id = $1", &scope.tenant),
        ("DELETE FROM ingest_job WHERE tenant_id = $1", &scope.tenant),
        ("DELETE FROM sample WHERE site_id = $1", &scope.site),
        ("DELETE FROM role_map WHERE building_id = $1", &scope.site),
        ("DELETE FROM point_map WHERE site_id = $1", &scope.site),
        ("DELETE FROM equipment WHERE building_id = $1", &scope.site),
        ("DELETE FROM building WHERE building_id = $1", &scope.site),
        ("DELETE FROM site WHERE site_id = $1", &scope.site),
    ] {
        sqlx::query(stmt)
            .bind(key)
            .execute(pool)
            .await
            .expect("purge writer fence fixture");
    }
}
