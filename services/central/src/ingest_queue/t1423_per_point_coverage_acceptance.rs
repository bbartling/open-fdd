//! Per-point stored-hour coverage for gap/catch-up planning (#1423).

use chrono::{DateTime, Duration, Utc};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use uuid::Uuid;

use super::binding_state::{stored_hour_starts_for_device, DeviceBindingKey, DevicePointCoverage};
use super::gap_backfill::{plan_device_gap_backfill, DeviceGapBackfillRequest};
use crate::providers::committed_model::{IngestDeviceGroup, PlannedPoint};

fn h(n: i64) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
        + Duration::hours(n)
}

/// One isolated Postgres fixture per test invocation (parallel-safe).
struct PpcCase {
    tenant: String,
    site: String,
    provider: String,
    device: String,
    rev: String,
    pool: PgPool,
}

impl PpcCase {
    async fn open(case_id: &str) -> Option<Self> {
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
        let suffix = &Uuid::new_v4().simple().to_string()[..10];
        let tenant = format!("t1423-ppc-{case_id}-{suffix}");
        let site = format!("{tenant}-site");
        let provider = format!("nf:{tenant}");
        let device = format!("dev-{suffix}");
        let rev = format!("rev-{suffix}");
        sqlx::query("INSERT INTO site (site_id) VALUES ($1) ON CONFLICT DO NOTHING")
            .bind(&site)
            .execute(&pool)
            .await
            .expect("site row");
        Some(Self {
            tenant,
            site,
            provider,
            device,
            rev,
            pool,
        })
    }

    fn binding_key(&self) -> DeviceBindingKey {
        DeviceBindingKey {
            tenant_id: self.tenant.clone(),
            canonical_site: self.site.clone(),
            provider_instance_id: self.provider.clone(),
            device_id: self.device.clone(),
            model_revision: self.rev.clone(),
        }
    }

    async fn cleanup(&self) {
        let _ = sqlx::query("DELETE FROM sample WHERE site_id = $1")
            .bind(&self.site)
            .execute(&self.pool)
            .await;
        let _ = sqlx::query(
            "DELETE FROM ingest_point_coverage WHERE job_id IN (SELECT job_id FROM ingest_job WHERE tenant_id = $1)",
        )
        .bind(&self.tenant)
        .execute(&self.pool)
        .await;
        let _ = sqlx::query("DELETE FROM ingest_job WHERE tenant_id = $1")
            .bind(&self.tenant)
            .execute(&self.pool)
            .await;
        let _ = sqlx::query("DELETE FROM ingest_device_binding WHERE tenant_id = $1")
            .bind(&self.tenant)
            .execute(&self.pool)
            .await;
    }

    async fn seed_provider_start(&self, provider_start: DateTime<Utc>) {
        sqlx::query(
            "INSERT INTO ingest_device_binding (
            tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
            binding_created_at, provider_data_start, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $6)
         ON CONFLICT (tenant_id, canonical_site, provider_instance_id, device_id, model_revision)
         DO UPDATE SET provider_data_start = EXCLUDED.provider_data_start",
        )
        .bind(&self.tenant)
        .bind(&self.site)
        .bind(&self.provider)
        .bind(&self.device)
        .bind(&self.rev)
        .bind(h(0))
        .bind(provider_start)
        .execute(&self.pool)
        .await
        .expect("binding row");
    }

    async fn insert_sample(&self, key: &str, at: DateTime<Utc>) {
        sqlx::query(
            "INSERT INTO sample (ts, site_id, openfdd_key, val, unit, quality)
         VALUES ($1, $2, $3, 1.0, 'degF', 'good')",
        )
        .bind(at)
        .bind(&self.site)
        .bind(key)
        .execute(&self.pool)
        .await
        .expect("sample");
    }

    async fn seed_point_map(&self, portal_point_id: &str, openfdd_key: &str, role: &str) {
        sqlx::query(
            "INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, equipment_id, portal_point_id, referenced)
         VALUES ($1, $2, $3, $4, $5, $3, true)
         ON CONFLICT (site_id, openfdd_key) DO UPDATE
           SET portal_point_id = EXCLUDED.portal_point_id,
               role = EXCLUDED.role,
               equipment_id = EXCLUDED.equipment_id",
        )
        .bind(&self.site)
        .bind(openfdd_key)
        .bind(portal_point_id)
        .bind(role)
        .bind(&self.device)
        .execute(&self.pool)
        .await
        .expect("point_map");
    }

    fn point_key(&self, stem: &str) -> String {
        format!("urn:openfdd:point:{}:{stem}", self.site)
    }

    fn two_point_group(&self) -> IngestDeviceGroup {
        IngestDeviceGroup {
            provider_instance_id: self.provider.clone(),
            equipment_id: self.device.clone(),
            equip_type: "ahu".into(),
            points: vec![
                PlannedPoint {
                    semantic_point_id: self.point_key("p1"),
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
                    semantic_point_id: self.point_key("p2"),
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
        }
    }
}

fn coverage_points(group: &IngestDeviceGroup) -> Vec<DevicePointCoverage> {
    group
        .points
        .iter()
        .map(|point| DevicePointCoverage {
            openfdd_key: format!("opaque-{}", point.source_point_id),
            coverage_point_id: point.source_point_id.clone(),
            history_mode: point.history_mode.clone(),
            cadence_secs: point.cadence_secs,
            heartbeat_secs: point.heartbeat_secs,
        })
        .collect()
}

#[tokio::test]
async fn t1423_6_one_point_present_one_missing_does_not_mark_hour_stored() {
    let Some(case) = PpcCase::open("one-missing").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-6");
        return;
    };
    case.cleanup().await;
    case.seed_point_map("src-p1", "opaque-p1", "sat").await;
    case.insert_sample("opaque-p1", h(2) + Duration::minutes(5))
        .await;
    let group = case.two_point_group();
    let coverage =
        super::binding_state::device_point_coverage_for_group(&case.pool, &case.site, &group)
            .await
            .expect("coverage");
    let stored = stored_hour_starts_for_device(
        &case.pool,
        &case.binding_key(),
        &case.site,
        &coverage,
        h(0),
        h(4),
    )
    .await
    .expect("stored hours");
    assert!(
        stored.is_empty(),
        "hour 2 must not be stored when P2 is missing: {stored:?}"
    );
    let (plan, jobs) = plan_device_gap_backfill(
        &case.pool,
        DeviceGapBackfillRequest {
            key: case.binding_key(),
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
    case.cleanup().await;
}

#[tokio::test]
async fn t1423_6_internal_gap_with_current_last_sample_plans_middle_hours() {
    let Some(case) = PpcCase::open("internal-gap").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-6");
        return;
    };
    case.cleanup().await;
    case.seed_point_map("src-interval", "opaque-interval", "sat").await;
    case.insert_sample("opaque-interval", h(3) + Duration::minutes(5))
        .await;
    case.insert_sample("opaque-interval", h(6) + Duration::minutes(5))
        .await;
    let group = IngestDeviceGroup {
        provider_instance_id: case.provider.clone(),
        equipment_id: case.device.clone(),
        equip_type: "ahu".into(),
        points: vec![PlannedPoint {
            semantic_point_id: case.point_key("interval"),
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
    };
    let coverage =
        super::binding_state::device_point_coverage_for_group(&case.pool, &case.site, &group)
            .await
            .expect("coverage");
    let stored = stored_hour_starts_for_device(
        &case.pool,
        &case.binding_key(),
        &case.site,
        &coverage,
        h(0),
        h(8),
    )
    .await
    .expect("stored");
    assert_eq!(stored, vec![h(3), h(6)]);
    let (plan, jobs) = plan_device_gap_backfill(
        &case.pool,
        DeviceGapBackfillRequest {
            key: case.binding_key(),
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
    case.cleanup().await;
}

#[tokio::test]
async fn t1423_6_cov_sparse_window_is_stored_without_samples() {
    let Some(case) = PpcCase::open("cov-sparse").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-6");
        return;
    };
    case.cleanup().await;
    let group = IngestDeviceGroup {
        provider_instance_id: case.provider.clone(),
        equipment_id: case.device.clone(),
        equip_type: "ahu".into(),
        points: vec![PlannedPoint {
            semantic_point_id: case.point_key("cov"),
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
    };
    let coverage = coverage_points(&group);
    let stored = stored_hour_starts_for_device(
        &case.pool,
        &case.binding_key(),
        &case.site,
        &coverage,
        h(0),
        h(2),
    )
    .await
    .expect("stored");
    assert_eq!(stored, vec![h(0), h(1)]);
    case.cleanup().await;
}

#[tokio::test]
async fn t1423_6_fully_covered_device_queues_nothing() {
    let Some(case) = PpcCase::open("fully-covered").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-6");
        return;
    };
    case.cleanup().await;
    case.seed_point_map("src-p1", "opaque-p1", "sat").await;
    case.seed_point_map("src-p2", "opaque-p2", "rat").await;
    let group = case.two_point_group();
    for hour in 0..4 {
        case.insert_sample("opaque-p1", h(hour) + Duration::minutes(10))
            .await;
        case.insert_sample("opaque-p2", h(hour) + Duration::minutes(20))
            .await;
    }
    let (plan, jobs) = plan_device_gap_backfill(
        &case.pool,
        DeviceGapBackfillRequest {
            key: case.binding_key(),
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
    case.cleanup().await;
}

#[tokio::test]
async fn t1423_6_pre_provider_start_horizon_not_gap() {
    let Some(case) = PpcCase::open("provider-start").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-6");
        return;
    };
    case.cleanup().await;
    case.seed_provider_start(h(2)).await;
    let group = case.two_point_group();
    let (plan, jobs) = plan_device_gap_backfill(
        &case.pool,
        DeviceGapBackfillRequest {
            key: case.binding_key(),
            group: &group,
            range_start: h(0),
            range_end: h(5),
            force: false,
            now: Utc::now(),
        },
    )
    .await
    .expect("plan");
    assert_eq!(
        plan.counts.not_expected, 2,
        "hours 0-1 are before provider_data_start: {plan:?}"
    );
    assert!(
        plan.not_expected.iter().any(|w| w.start == h(0)),
        "{plan:?}"
    );
    assert!(
        plan.not_expected.iter().any(|w| w.start == h(1)),
        "{plan:?}"
    );
    assert!(
        plan.counts.planned > 0,
        "hours from provider start onward should plan: {plan:?}"
    );
    assert!(
        !jobs.iter().any(|job| job.logical_window_end <= h(2)),
        "must not enqueue backfill before provider_data_start: {jobs:?}"
    );
    case.cleanup().await;
}

#[tokio::test]
async fn t1423_6_sample_query_uses_openfdd_key_filter() {
    let Some(case) = PpcCase::open("explain-filter").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-6");
        return;
    };
    case.cleanup().await;
    let key = case.point_key("p1");
    let explain: Vec<(String,)> = sqlx::query_as(
        "EXPLAIN (FORMAT TEXT)
         SELECT openfdd_key, ts
         FROM sample
         WHERE site_id = $1 AND openfdd_key = ANY($2)
           AND ts >= $3 AND ts < $4
         ORDER BY openfdd_key, ts",
    )
    .bind(&case.site)
    .bind(std::slice::from_ref(&key))
    .bind(h(0))
    .bind(h(1))
    .fetch_all(&case.pool)
    .await
    .expect("explain");
    let plan = explain
        .iter()
        .map(|(line,)| line.as_str())
        .collect::<Vec<_>>()
        .join("\n");
    let plan_lower = plan.to_lowercase();
    assert!(
        plan_lower.contains("sample") && plan_lower.contains("openfdd_key"),
        "expected the sample scan to filter openfdd_key: {plan}"
    );
    case.cleanup().await;
}
