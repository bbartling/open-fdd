//! Site-level backfill enqueue caps and idempotency (T1401-4).

use chrono::{DateTime, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

use super::memory::MemoryStore;
use super::model::*;
use super::postgres;

const TENANT: &str = "t1401-tenant";
const SITE: &str = "t1401-site";
const PROVIDER: &str = "nf:t1401";
const REV: &str = "rev-t1401";

fn origin() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-15T00:00:00Z")
        .expect("origin")
        .with_timezone(&Utc)
}

fn hour(offset: i64) -> (DateTime<Utc>, DateTime<Utc>) {
    let start = origin() + chrono::Duration::hours(offset);
    (start, start + chrono::Duration::hours(1))
}

fn device_job(device: &str, offset: i64) -> NewJob {
    let (start, end) = hour(offset);
    NewJob {
        tenant_id: TENANT.into(),
        canonical_site: SITE.into(),
        provider_instance_id: PROVIDER.into(),
        device_id: device.into(),
        model_revision: REV.into(),
        logical_window_start: start,
        logical_window_end: end,
        shard: String::new(),
        not_before: origin(),
        estimated_cost: 1,
        requested_points_digest: None,
    }
}

fn site_jobs(devices: &[&str], window_offsets: &[i64]) -> Vec<NewJob> {
    let mut jobs = Vec::new();
    for device in devices {
        for offset in window_offsets {
            jobs.push(device_job(device, *offset));
        }
    }
    jobs
}

fn site_claim(
    key: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    jobs: &[NewJob],
) -> IdempotencyClaim {
    IdempotencyClaim {
        actor: "operator".into(),
        tenant_id: TENANT.into(),
        client_key: key.into(),
        object_id: site_backfill_object_id(&jobs[0]),
        payload_hash: site_backfill_payload_hash(TENANT, SITE, PROVIDER, REV, start, end),
    }
}

async fn test_pool() -> Option<PgPool> {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .filter(|value| !value.trim().is_empty())?;
    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("test database");
    crate::ingest_queue::test_schema::apply_ingest_queue_schema(&pool)
        .await
        .expect("schema");
    Some(pool)
}

async fn cleanup(pool: &PgPool) {
    let _ = sqlx::query("DELETE FROM ingest_idempotency WHERE tenant_id = $1")
        .bind(TENANT)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM ingest_job WHERE tenant_id = $1")
        .bind(TENANT)
        .execute(pool)
        .await;
}

#[tokio::test]
async fn site_backfill_enqueues_groups_times_windows_and_replays_idempotently() {
    let devices = ["dev-a", "dev-b", "dev-c"];
    let windows = [0_i64, 1, 2];
    let jobs = site_jobs(&devices, &windows);
    let range_start = hour(0).0;
    let range_end = hour(2).1;
    let claim = site_claim("site-backfill-key", range_start, range_end, &jobs);
    let now = origin();

    if let Some(pool) = test_pool().await {
        cleanup(&pool).await;
        let first = postgres::site_backfill(&pool, &jobs, range_start, range_end, now, &claim)
            .await
            .expect("first site backfill");
        assert_eq!(first.len(), devices.len() * windows.len());
        let count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM ingest_job WHERE tenant_id = $1 AND canonical_site = $2",
        )
        .bind(TENANT)
        .bind(SITE)
        .fetch_one(&pool)
        .await
        .expect("count");
        assert_eq!(count as usize, first.len());
        let second = postgres::site_backfill(&pool, &jobs, range_start, range_end, now, &claim)
            .await
            .expect("replay");
        assert_eq!(second.len(), first.len());
        let count_after: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM ingest_job WHERE tenant_id = $1 AND canonical_site = $2",
        )
        .bind(TENANT)
        .bind(SITE)
        .fetch_one(&pool)
        .await
        .expect("count after");
        assert_eq!(count_after, count);
        cleanup(&pool).await;
        return;
    }

    let store = MemoryStore::new(BudgetDefaults::default());
    let first = store
        .site_backfill(jobs.clone(), range_start, range_end, now, &claim)
        .expect("memory first");
    assert_eq!(first.len(), devices.len() * windows.len());
    let second = store
        .site_backfill(jobs, range_start, range_end, now, &claim)
        .expect("memory replay");
    assert_eq!(second.len(), first.len());
}

#[test]
fn site_backfill_job_cap_is_enforced() {
    let devices: Vec<String> = (0..50).map(|n| format!("dev-{n}")).collect();
    let device_refs: Vec<&str> = devices.iter().map(String::as_str).collect();
    let windows: Vec<i64> = (0..50).collect();
    let jobs = site_jobs(&device_refs, &windows);
    assert!(jobs.len() > MAX_SITE_BACKFILL_JOBS as usize);
    let range_start = hour(0).0;
    let range_end = hour(49).1;
    let claim = site_claim("cap-key", range_start, range_end, &jobs);
    let store = MemoryStore::new(BudgetDefaults::default());
    let err = store
        .site_backfill(jobs, range_start, range_end, origin(), &claim)
        .expect_err("cap");
    assert!(matches!(err, QueueError::Invalid(_)));
}

#[test]
fn hourly_windows_between_rejects_unaligned_bounds() {
    let start = origin() + chrono::Duration::minutes(5);
    let end = origin() + chrono::Duration::hours(2);
    let err = hourly_windows_between(start, end, MAX_SITE_BACKFILL_WINDOWS).unwrap_err();
    assert!(matches!(err, QueueError::Invalid(_)));
}
