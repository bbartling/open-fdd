//! W2e / #1423 gap planner and cancel acceptance (T1423-3, T1423-4).

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::Router;
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;
use uuid::Uuid;

use super::binding_state::DeviceBindingKey;
use super::gap_backfill::{plan_device_gap_backfill, DeviceGapBackfillRequest};
use super::model::{EnqueueOutcome, JobState, NewJob};
use super::postgres;
use crate::auth::{AuthConfig, Role};
use crate::providers::committed_model::{IngestDeviceGroup, PlannedPoint};
use crate::state::AppState;
use crate::tenant::{ControlPlane, TenantRecord};

struct EnvGuard {
    key: &'static str,
    prev: Option<String>,
}

impl EnvGuard {
    fn set(key: &'static str, value: &str) -> Self {
        let prev = std::env::var(key).ok();
        std::env::set_var(key, value);
        Self { key, prev }
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        match self.prev.take() {
            Some(value) => std::env::set_var(self.key, value),
            None => std::env::remove_var(self.key),
        }
    }
}

fn h(n: i64) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
        + Duration::hours(n)
}

/// Parallel-safe Postgres fixture (unique tenant/site/binding per test).
struct GapCase {
    tenant: String,
    site: String,
    provider: String,
    device: String,
    rev: String,
    point: String,
    pool: PgPool,
}

impl GapCase {
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
        let tenant = format!("t1423-gap-{case_id}-{suffix}");
        let site = format!("{tenant}-site");
        let provider = format!("nf:{tenant}");
        let device = format!("dev-{suffix}");
        let rev = format!("rev-{suffix}");
        let point = format!("urn:openfdd:point:{site}:{device}:sat");
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
            point,
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
        let audit_prefix = format!("{}%", self.tenant);
        let _ = sqlx::query("DELETE FROM ingest_audit WHERE actor LIKE $1")
            .bind(audit_prefix)
            .execute(&self.pool)
            .await;
        let _ = sqlx::query("DELETE FROM ingest_idempotency WHERE tenant_id = $1")
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

    async fn seed_hour(&self, hour: i64) {
        sqlx::query(
            "INSERT INTO sample (ts, site_id, openfdd_key, val, unit, quality)
         VALUES ($1, $2, $3, 70.0, 'degF', 'good')
         ON CONFLICT DO NOTHING",
        )
        .bind(h(hour) + Duration::minutes(10))
        .bind(&self.site)
        .bind(&self.point)
        .execute(&self.pool)
        .await
        .expect("sample row");
    }

    fn test_group(&self) -> IngestDeviceGroup {
        IngestDeviceGroup {
            provider_instance_id: self.provider.clone(),
            equipment_id: self.device.clone(),
            equip_type: "ahu".into(),
            points: vec![PlannedPoint {
                semantic_point_id: self.point.clone(),
                source_point_id: "src-sat".into(),
                canonical_role: "sat".into(),
                kind: None,
                source_unit: Some("degF".into()),
                canonical_unit: None,
                quantity: None,
                history_mode: None,
                cadence_secs: None,
                heartbeat_secs: None,
            }],
        }
    }

    async fn seed_provider_start(&self) {
        sqlx::query(
            "INSERT INTO ingest_device_binding (
            tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
            binding_created_at, provider_data_start, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $6)",
        )
        .bind(&self.tenant)
        .bind(&self.site)
        .bind(&self.provider)
        .bind(&self.device)
        .bind(&self.rev)
        .bind(h(0))
        .bind(h(1))
        .execute(&self.pool)
        .await
        .expect("binding row");
    }

    async fn enqueue(&self, state: &str, start: DateTime<Utc>) -> Uuid {
        let job = NewJob {
            tenant_id: self.tenant.clone(),
            canonical_site: self.site.clone(),
            provider_instance_id: self.provider.clone(),
            device_id: self.device.clone(),
            model_revision: self.rev.clone(),
            logical_window_start: start,
            logical_window_end: start + Duration::hours(1),
            shard: String::new(),
            not_before: Utc::now(),
            estimated_cost: 1,
            requested_points_digest: None,
        };
        let created = postgres::enqueue(&self.pool, &job).await.expect("enqueue");
        let id = match created {
            EnqueueOutcome::Created(view) | EnqueueOutcome::Existing(view) => view.job_id,
        };
        sqlx::query("UPDATE ingest_job SET state = $2 WHERE job_id = $1")
            .bind(id.to_string())
            .bind(state)
            .execute(&self.pool)
            .await
            .expect("state");
        id
    }
}

#[tokio::test]
async fn t1423_3_gap_planner_skips_stored_and_not_expected_hours() {
    let Some(case) = GapCase::open("planner").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-3");
        return;
    };
    case.cleanup().await;
    for hour in [1, 2, 3, 6] {
        case.seed_hour(hour).await;
    }
    case.seed_provider_start().await;
    let group = case.test_group();
    let (plan, jobs) = plan_device_gap_backfill(
        &case.pool,
        DeviceGapBackfillRequest {
            key: case.binding_key(),
            group: &group,
            range_start: h(0),
            range_end: h(9),
            force: false,
            now: Utc::now(),
        },
    )
    .await
    .expect("plan");
    assert_eq!(plan.counts.not_expected, 1);
    assert_eq!(plan.counts.skipped_stored, 4);
    assert_eq!(plan.counts.planned, 3);
    assert_eq!(jobs.len(), 3);
    assert_eq!(jobs[0].logical_window_start, h(4));
    assert_eq!(jobs[0].logical_window_end, h(6));
    assert_eq!(jobs[1].logical_window_start, h(7));
    assert_eq!(jobs[1].logical_window_end, h(8));
    assert_eq!(jobs[2].logical_window_start, h(8));
    assert_eq!(jobs[2].logical_window_end, h(9));
    case.cleanup().await;
}

async fn cancel_harness(case: &GapCase) -> (Arc<AppState>, Router) {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL").expect("database url");
    std::env::set_var("OPENFDD_DATABASE_URL", &url);
    let mut state = AppState::new();
    state.auth = AuthConfig {
        secret: Some("t1423-gap-planner-test-secret-not-a-credential".into()),
        admin_password: None,
        agent_password: None,
        viewer_password: None,
        viewer_tenant_ids: Vec::new(),
    };
    let state = Arc::new(state);
    {
        let mut plane = state.control_plane.write().await;
        *plane = ControlPlane {
            tenants: vec![TenantRecord {
                id: case.tenant.clone(),
                name: "T1423".into(),
                building_ids: vec![case.site.clone()],
            }],
        };
    }
    let app = crate::routes::router(Arc::clone(&state));
    (state, app)
}

async fn call(app: &Router, token: Option<&str>, body: Value) -> (StatusCode, Value) {
    let mut builder = Request::builder()
        .method("POST")
        .uri("/api/ingest/jobs/cancel")
        .header("content-type", "application/json");
    if let Some(token) = token {
        builder = builder.header("authorization", format!("Bearer {token}"));
    }
    let response = app
        .clone()
        .oneshot(builder.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    let parsed = serde_json::from_slice(&bytes).unwrap_or(json!({}));
    (status, parsed)
}

#[tokio::test]
async fn t1423_4_cancel_route_is_operator_scoped_and_idempotent() {
    let _env = crate::test_env_lock::lock_env_async().await;
    let _mt = EnvGuard::set("OPENFDD_MULTI_TENANT", "1");
    let Some(case) = GapCase::open("cancel").await else {
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping T1423-4");
        return;
    };
    case.cleanup().await;
    let queued = case.enqueue(JobState::Queued.as_str(), h(4)).await;
    let retry = case.enqueue(JobState::RetryWait.as_str(), h(5)).await;
    let leased = case.enqueue(JobState::Leased.as_str(), h(6)).await;

    let (state, app) = cancel_harness(&case).await;
    let tenants = vec![case.tenant.clone()];
    let viewer = state
        .auth
        .issue_token_with_tenants("t1423-viewer", Role::Viewer, 600, &tenants)
        .expect("viewer token");
    let operator = state
        .auth
        .issue_token_with_tenants("t1423-operator", Role::Operator, 600, &tenants)
        .expect("operator token");

    let idempotency_key = format!("t1423-cancel-{}", case.tenant);
    let body = json!({
        "idempotency_key": idempotency_key,
        "tenant_id": case.tenant,
        "canonical_site": case.site,
    });

    let (status, _) = call(&app, None, body.clone()).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);

    let (status, _) = call(&app, Some(&viewer), body.clone()).await;
    assert_eq!(status, StatusCode::FORBIDDEN);

    let (status, first) = call(&app, Some(&operator), body.clone()).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(first["cancelled"], 2);
    let (status, second) = call(&app, Some(&operator), body).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(second["cancelled"], 2);
    assert_eq!(first["job_ids"], second["job_ids"]);

    let leased_row: String = sqlx::query_scalar("SELECT state FROM ingest_job WHERE job_id = $1")
        .bind(leased.to_string())
        .fetch_one(&case.pool)
        .await
        .expect("leased state");
    assert_eq!(leased_row, JobState::Leased.as_str());

    for id in [queued, retry] {
        let row: String = sqlx::query_scalar("SELECT state FROM ingest_job WHERE job_id = $1")
            .bind(id.to_string())
            .fetch_one(&case.pool)
            .await
            .expect("state");
        assert_eq!(row, JobState::Cancelled.as_str());
    }
    case.cleanup().await;
}
