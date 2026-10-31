//! Per-point stored-hour coverage for gap/catch-up planning (#1423).

use chrono::{DateTime, Duration, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

use super::binding_state::{stored_hour_starts_for_device, DeviceBindingKey, DevicePointCoverage};
use super::gap_backfill::{plan_device_gap_backfill, DeviceGapBackfillRequest};
use crate::providers::committed_model::{IngestDeviceGroup, PlannedPoint};

const TENANT: &str = "t1423-ppc-tenant";
const SITE: &str = "t1423-ppc-site";
const PROVIDER: &str = "nf:t1423-ppc";
const DEVICE: &str = "dev-ppc";
const REV: &str = "rev-t1423-ppc";

fn h(n: i64) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
        + Duration::hours(n)
}

async fn test_pool() -> Option<PgPool> {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .filter(|value| !value.trim().is_empty())?;
    let pool = PgPoolOptions::new()
        .max_connections(3)
        .connect(url.trim())
        .await
        .expect("test database");
    crate::ingest_queue::test_schema::apply_ingest_queue_schema(&pool)
        .await
        .expect("schema");
    sqlx::query("INSERT INTO site (site_id) VALUES ($1) ON CONFLICT DO NOTHING")
        .bind(SITE)
        .execute(&pool)
        .await
        .expect("site row");
    Some(pool)
}

async fn cleanup(pool: &PgPool) {
    let _ = sqlx::query("DELETE FROM sample WHERE site_id = $1")
        .bind(SITE)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM ingest_point_coverage WHERE job_id IN (SELECT job_id FROM ingest_job WHERE tenant_id = $1)")
        .bind(TENANT)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM ingest_job WHERE tenant_id = $1")
        .bind(TENANT)
        .execute(pool)
        .await;
    let _ = sqlx::query("DELETE FROM ingest_device_binding WHERE tenant_id = $1")
        .bind(TENANT)
        .execute(pool)
        .await;
}

async fn insert_sample(pool: &PgPool, key: &str, at: DateTime<Utc>) {
    sqlx::query(
        "INSERT INTO sample (ts, site_id, openfdd_key, val, unit, quality)
         VALUES ($1, $2, $3, 1.0, 'degF', 'good')",
    )
    .bind(at)
    .bind(SITE)
    .bind(key)
    .execute(pool)
    .await
    .expect("sample");
}

fn binding_key() -> DeviceBindingKey {
    DeviceBindingKey {
        tenant_id: TENANT.into(),
        canonical_site: SITE.into(),
        provider_instance_id: PROVIDER.into(),
        device_id: DEVICE.into(),
        model_revision: REV.into(),
    }
}

fn two_point_group() -> IngestDeviceGroup {
    IngestDeviceGroup {
        provider_instance_id: PROVIDER.into(),
        equipment_id: DEVICE.into(),
        equip_type: "ahu".into(),
        points: vec![
            PlannedPoint {
                semantic_point_id: "urn:openfdd:point:ppc:p1".into(),
                source_point_id: "src-p1".into(),
                canonical_role: "sat".into(),
                kind: None,
                source_unit: Some("degF".into()),
                canonical_unit: None,
                quantity: None,
                history_mode: None,
                cadence_secs: None,
                heartbeat_secs: None,
            },
            PlannedPoint {
                semantic_point_id: "urn:openfdd:point:ppc:p2".into(),
                source_point_id: "src-p2".into(),
                canonical_role: "rat".into(),
                kind: None,
                source_unit: Some("degF".into()),
                canonical_unit: None,
                quantity: None,
                history_mode: None,
                cadence_secs: None,
                heartbeat_secs: None,
            },
        ],
        withheld: Vec::new(),
    }
}

fn coverage_points(group: &IngestDeviceGroup) -> Vec<DevicePointCoverage> {
    group
        .points
        .iter()
        .map(|point| DevicePointCoverage {
            openfdd_key: point.semantic_point_id.clone(),
            coverage_point_id: point.source_point_id.clone(),
            history_mode: point.history_mode.clone(),
            cadence_secs: point.cadence_secs,
            heartbeat_secs: point.heartbeat_secs,
        })
        .collect()
}

#[tokio::test]
async fn t1423_6_one_point_present_one_missing_does_not_mark_hour_stored() {
    let Some(pool) = test_pool().await else {
        panic!("OPENFDD_TEST_DATABASE_URL is required for T1423-6 per-point coverage tests");
    };
    cleanup(&pool).await;
    insert_sample(
        &pool,
        "urn:openfdd:point:ppc:p1",
        h(2) + Duration::minutes(5),
    )
    .await;
    let group = two_point_group();
    let coverage = coverage_points(&group);
    let stored = stored_hour_starts_for_device(&pool, &binding_key(), SITE, &coverage, h(0), h(4))
        .await
        .expect("stored hours");
    assert!(
        stored.is_empty(),
        "hour 2 must not be stored when P2 is missing: {stored:?}"
    );
    let (plan, jobs) = plan_device_gap_backfill(
        &pool,
        DeviceGapBackfillRequest {
            key: binding_key(),
            group: &group,
            range_start: h(0),
            range_end: h(4),
            force: false,
            now: Utc::now(),
        },
    )
    .await
    .expect("plan");
    assert!(
        plan.counts.planned > 0,
        "missing P2 should plan backfill: {plan:?}"
    );
    assert!(
        jobs.iter()
            .any(|job| job.logical_window_start <= h(2) && job.logical_window_end > h(2)),
        "expected a job covering hour 2: {jobs:?}"
    );
    cleanup(&pool).await;
}

#[tokio::test]
async fn t1423_6_internal_gap_with_current_last_sample_plans_middle_hours() {
    let Some(pool) = test_pool().await else {
        panic!("OPENFDD_TEST_DATABASE_URL is required for T1423-6 per-point coverage tests");
    };
    cleanup(&pool).await;
    let key = "urn:openfdd:point:ppc:interval";
    insert_sample(&pool, key, h(3) + Duration::minutes(5)).await;
    insert_sample(&pool, key, h(6) + Duration::minutes(5)).await;
    let group = IngestDeviceGroup {
        provider_instance_id: PROVIDER.into(),
        equipment_id: DEVICE.into(),
        equip_type: "ahu".into(),
        points: vec![PlannedPoint {
            semantic_point_id: key.into(),
            source_point_id: "src-interval".into(),
            canonical_role: "sat".into(),
            kind: None,
            source_unit: Some("degF".into()),
            canonical_unit: None,
            quantity: None,
            history_mode: Some("interval".into()),
            cadence_secs: Some(3600),
            heartbeat_secs: None,
        }],
        withheld: Vec::new(),
    };
    let coverage = coverage_points(&group);
    let stored = stored_hour_starts_for_device(&pool, &binding_key(), SITE, &coverage, h(0), h(8))
        .await
        .expect("stored");
    assert_eq!(stored, vec![h(3), h(6)]);
    let (plan, jobs) = plan_device_gap_backfill(
        &pool,
        DeviceGapBackfillRequest {
            key: binding_key(),
            group: &group,
            range_start: h(0),
            range_end: h(8),
            force: false,
            now: Utc::now(),
        },
    )
    .await
    .expect("plan");
    assert!(
        jobs.iter()
            .any(|job| job.logical_window_start <= h(4) && job.logical_window_end > h(4)),
        "hour 4 must remain a gap: plan={plan:?} jobs={jobs:?}"
    );
    cleanup(&pool).await;
}

#[tokio::test]
async fn t1423_6_cov_sparse_window_is_stored_without_samples() {
    let Some(pool) = test_pool().await else {
        panic!("OPENFDD_TEST_DATABASE_URL is required for T1423-6 per-point coverage tests");
    };
    cleanup(&pool).await;
    let group = IngestDeviceGroup {
        provider_instance_id: PROVIDER.into(),
        equipment_id: DEVICE.into(),
        equip_type: "ahu".into(),
        points: vec![PlannedPoint {
            semantic_point_id: "urn:openfdd:point:ppc:cov".into(),
            source_point_id: "src-cov".into(),
            canonical_role: "fan_status".into(),
            kind: None,
            source_unit: None,
            canonical_unit: None,
            quantity: None,
            history_mode: Some("cov".into()),
            cadence_secs: None,
            heartbeat_secs: None,
        }],
        withheld: Vec::new(),
    };
    let coverage = coverage_points(&group);
    let stored = stored_hour_starts_for_device(&pool, &binding_key(), SITE, &coverage, h(0), h(2))
        .await
        .expect("stored");
    assert_eq!(stored, vec![h(0), h(1)]);
    cleanup(&pool).await;
}

#[tokio::test]
async fn t1423_6_fully_covered_device_queues_nothing() {
    let Some(pool) = test_pool().await else {
        panic!("OPENFDD_TEST_DATABASE_URL is required for T1423-6 per-point coverage tests");
    };
    cleanup(&pool).await;
    let group = two_point_group();
    for hour in 0..4 {
        insert_sample(
            &pool,
            "urn:openfdd:point:ppc:p1",
            h(hour) + Duration::minutes(10),
        )
        .await;
        insert_sample(
            &pool,
            "urn:openfdd:point:ppc:p2",
            h(hour) + Duration::minutes(20),
        )
        .await;
    }
    let (plan, jobs) = plan_device_gap_backfill(
        &pool,
        DeviceGapBackfillRequest {
            key: binding_key(),
            group: &group,
            range_start: h(0),
            range_end: h(4),
            force: false,
            now: Utc::now(),
        },
    )
    .await
    .expect("plan");
    assert_eq!(plan.counts.planned, 0, "{plan:?}");
    assert!(jobs.is_empty(), "{jobs:?}");
    cleanup(&pool).await;
}

#[tokio::test]
async fn t1423_6_sample_query_uses_openfdd_key_filter() {
    let Some(pool) = test_pool().await else {
        panic!("OPENFDD_TEST_DATABASE_URL is required for T1423-6 per-point coverage tests");
    };
    cleanup(&pool).await;
    let explain: (String,) = sqlx::query_as(
        "EXPLAIN (FORMAT TEXT)
         SELECT openfdd_key, ts
         FROM sample
         WHERE site_id = $1 AND openfdd_key = ANY($2)
           AND ts >= $3 AND ts < $4
         ORDER BY openfdd_key, ts",
    )
    .bind(SITE)
    .bind(&["urn:openfdd:point:ppc:p1".to_string()])
    .bind(h(0))
    .bind(h(1))
    .fetch_one(&pool)
    .await
    .expect("explain");
    assert!(
        explain.0.to_lowercase().contains("sample"),
        "expected sample scan in plan: {}",
        explain.0
    );
    cleanup(&pool).await;
}
