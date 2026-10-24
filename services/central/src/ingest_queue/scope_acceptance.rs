//! Handler coverage for tenant-scoped ingest idempotency, backfill identity, and queue metrics.
//!
//! Memory runs on every `cargo test`. PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL`
//! is set, and is required when `OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED=1`.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::Router;
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};
use tower::ServiceExt;
use uuid::Uuid;

use crate::auth::{AuthConfig, Role};
use crate::providers::committed_model::{
    CommittedEquipment, CommittedModel, CommittedPoint, SCHEMA,
};
use crate::state::AppState;
use crate::tenant::{ControlPlane, TenantRecord};

use super::model::{ClaimRequest, FinishOutcome, FinishRequest, JobCounts, NewJob};

const TENANT_A: &str = "w2a-tenant-a";
const TENANT_B: &str = "w2a-tenant-b";
const TENANT_EMPTY: &str = "w2a-empty";
const SITE_A: &str = "w2a-site-a";
const SITE_B: &str = "w2a-site-b";
const SITE_SHARED: &str = "w2a-shared";
const SITE_BARE: &str = "w2a-bare";
const PORTAL_A: &str = "w2a-portal-a";
const PORTAL_B: &str = "w2a-portal-b";
const PORTAL_SHARED_A: &str = "w2a-portal-shared-a";
const PORTAL_SHARED_B: &str = "w2a-portal-shared-b";
const DEVICE: &str = "AHU_1";

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

    fn unset(key: &'static str) -> Self {
        let prev = std::env::var(key).ok();
        std::env::remove_var(key);
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

struct Plans {
    site_a: String,
    site_b: String,
    shared_a: String,
    shared_b: String,
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL and workspace for the ingest scope matrix"
)]
async fn ingest_idempotency_backfill_and_metrics_are_tenant_scoped() {
    let _env = crate::test_env_lock::lock_env();
    let _mt = EnvGuard::set("OPENFDD_MULTI_TENANT", "1");
    let _db = EnvGuard::unset("OPENFDD_DATABASE_URL");
    let workspace = tempfile::tempdir().unwrap();
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());

    run_matrix().await;

    let required = std::env::var("OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    match url {
        Some(url) => {
            std::env::set_var("OPENFDD_DATABASE_URL", &url);
            let pool = PgPoolOptions::new()
                .max_connections(2)
                .connect(&url)
                .await
                .expect("ingest scope postgres fixture");
            super::postgres::apply_schema(&pool)
                .await
                .expect("ingest schema");
            let lease = snapshot_scheduler(&pool).await;
            purge_fixture(&pool).await;
            run_matrix().await;
            purge_fixture(&pool).await;
            restore_scheduler(&pool, lease).await;
        }
        None if required => {
            panic!("OPENFDD_TEST_DATABASE_URL is required for the ingest scope fixture")
        }
        None => {}
    }
}

async fn run_matrix() {
    let (state, app, plans) = harness().await;
    let tokens = tokens(&state);

    let (status, body) = call(
        &app,
        &tokens.viewer,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-viewer-key",
            None,
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(0),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{body}");
    assert_eq!(error_code(&body), "forbidden");

    let (status, body) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-foreign-site",
            None,
            SITE_B,
            PORTAL_B,
            DEVICE,
            None,
            hour(0),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_eq!(error_code(&body), "not_found");

    let (status, body) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-body-tenant",
            Some(TENANT_B),
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(0),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(error_code(&body), "identity_mismatch");

    let (status, body) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-missing-plan",
            None,
            SITE_BARE,
            PORTAL_A,
            DEVICE,
            None,
            hour(0),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(error_code(&body), "plan_not_committed");

    for (key, provider, device, revision, label) in [
        (
            "w2a-bad-provider",
            "w2a-other-portal",
            DEVICE,
            None,
            "provider",
        ),
        ("w2a-bad-device", PORTAL_A, "AHU_9", None, "device"),
        (
            "w2a-bad-revision",
            PORTAL_A,
            DEVICE,
            Some("not-the-plan"),
            "revision",
        ),
    ] {
        let (status, body) = call(
            &app,
            &tokens.operator_a,
            "POST",
            "/api/ingest/backfill",
            Some(backfill(
                key,
                None,
                SITE_A,
                provider,
                device,
                revision,
                hour(0),
            )),
        )
        .await;
        assert_eq!(status, StatusCode::CONFLICT, "{label} {body}");
        assert_eq!(error_code(&body), "identity_mismatch", "{label}");
    }

    let (status, created) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-key-replay-a",
            None,
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(0),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{created}");
    let job_a = job_id(&created);
    assert_eq!(created["jobs"][0]["tenant_id"], TENANT_A);
    assert_eq!(created["jobs"][0]["canonical_site"], SITE_A);
    assert_eq!(created["jobs"][0]["provider_instance_id"], PORTAL_A);
    assert_eq!(created["jobs"][0]["device_id"], DEVICE);
    assert_eq!(created["jobs"][0]["model_revision"], plans.site_a);

    let (status, replay) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-key-replay-a",
            None,
            SITE_A,
            PORTAL_A,
            DEVICE,
            Some(plans.site_a.as_str()),
            hour(0),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{replay}");
    assert_eq!(job_id(&replay), job_a);

    let (status, conflict) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-key-replay-a",
            None,
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(3),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{conflict}");
    assert_eq!(error_code(&conflict), "idempotency_conflict");
    assert_hides(&conflict, &job_a);

    let (status, other_actor) = call(
        &app,
        &tokens.operator_a2,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-key-replay-a",
            None,
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(4),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{other_actor}");
    let job_a2 = job_id(&other_actor);
    assert_ne!(job_a2, job_a);
    assert_eq!(other_actor["jobs"][0]["tenant_id"], TENANT_A);
    assert_hides(&other_actor, &job_a);

    let (status, tenant_b) = call(
        &app,
        &tokens.operator_b,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-key-replay-a",
            None,
            SITE_B,
            PORTAL_B,
            DEVICE,
            None,
            hour(0),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{tenant_b}");
    let job_b = job_id(&tenant_b);
    assert_ne!(job_b, job_a);
    assert_eq!(tenant_b["jobs"][0]["tenant_id"], TENANT_B);
    assert_eq!(tenant_b["jobs"][0]["model_revision"], plans.site_b);
    assert_hides(&tenant_b, &job_a);

    let (status, body) = call(
        &app,
        &tokens.operator_a,
        "GET",
        &format!("/api/ingest/jobs/{job_b}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_hides(&body, &job_b);

    let (status, body) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-shared-cross-tenant",
            Some(TENANT_B),
            SITE_SHARED,
            PORTAL_SHARED_B,
            DEVICE,
            None,
            hour(1),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(error_code(&body), "identity_mismatch");

    let (status, body) = call(
        &app,
        &tokens.operator_b,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-shared-cross-provider",
            None,
            SITE_SHARED,
            PORTAL_SHARED_A,
            DEVICE,
            None,
            hour(1),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(error_code(&body), "identity_mismatch");

    let (status, shared_b) = call(
        &app,
        &tokens.operator_b,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-shared-b",
            None,
            SITE_SHARED,
            PORTAL_SHARED_B,
            DEVICE,
            None,
            hour(1),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{shared_b}");
    let job_shared_b = job_id(&shared_b);
    assert_eq!(shared_b["jobs"][0]["tenant_id"], TENANT_B);
    assert_eq!(shared_b["jobs"][0]["model_revision"], plans.shared_b);

    let (status, body) = call(
        &app,
        &tokens.operator_a,
        "GET",
        &format!("/api/ingest/jobs/{job_shared_b}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{body}");
    assert_hides(&body, &job_shared_b);

    let (status, listed) = call(
        &app,
        &tokens.operator_a,
        "GET",
        &format!("/api/ingest/jobs?site_id={SITE_SHARED}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    assert_hides(&listed, &job_shared_b);

    let (status, shared_a) = call(
        &app,
        &tokens.operator_a,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-shared-a",
            Some(TENANT_A),
            SITE_SHARED,
            PORTAL_SHARED_A,
            DEVICE,
            None,
            hour(1),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{shared_a}");
    let job_shared_a = job_id(&shared_a);
    assert_eq!(shared_a["jobs"][0]["tenant_id"], TENANT_A);
    assert_eq!(shared_a["jobs"][0]["provider_instance_id"], PORTAL_SHARED_A);
    assert_eq!(shared_a["jobs"][0]["model_revision"], plans.shared_a);
    assert_ne!(job_shared_a, job_shared_b);

    let (status, body) = call(
        &app,
        &tokens.hub,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-hub-omitted",
            None,
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(5),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");
    assert_eq!(error_code(&body), "tenant_required");

    let (status, body) = call(
        &app,
        &tokens.hub,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-hub-wrong-site",
            Some(TENANT_B),
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(5),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(error_code(&body), "identity_mismatch");

    let (status, hub_job) = call(
        &app,
        &tokens.hub,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w2a-hub-explicit",
            Some(TENANT_A),
            SITE_A,
            PORTAL_A,
            DEVICE,
            None,
            hour(5),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{hub_job}");
    assert_eq!(hub_job["jobs"][0]["tenant_id"], TENANT_A);
    assert_eq!(hub_job["jobs"][0]["model_revision"], plans.site_a);
    assert_ne!(job_id(&hub_job), job_a);

    let (status, a_before) = call(&app, &tokens.operator_a, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{a_before}");
    let (status, b_before) = call(&app, &tokens.operator_b, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{b_before}");
    let (status, hub_before) = call(&app, &tokens.hub, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{hub_before}");
    assert!(
        a_before["metrics"]["scheduler_owner"].is_null(),
        "{a_before}"
    );
    assert!(
        b_before["metrics"]["scheduler_owner"].is_null(),
        "{b_before}"
    );

    state
        .ingest_queue
        .enqueue(
            NewJob {
                tenant_id: TENANT_B.into(),
                canonical_site: SITE_B.into(),
                provider_instance_id: PORTAL_B.into(),
                device_id: "AHU_2".into(),
                model_revision: plans.site_b.clone(),
                logical_window_start: hour(8),
                logical_window_end: hour(8) + Duration::hours(1),
                shard: String::new(),
                not_before: Utc::now() - Duration::hours(2),
                estimated_cost: 1,
                requested_points_digest: None,
            },
            Utc::now(),
        )
        .await
        .expect("enqueue tenant b backlog");

    let (status, a_after) = call(&app, &tokens.operator_a, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{a_after}");
    assert_eq!(
        ready(&a_after),
        ready(&a_before),
        "tenant a metrics changed after tenant b work\nbefore={a_before}\nafter={a_after}"
    );
    assert!(a_after["metrics"]["scheduler_owner"].is_null(), "{a_after}");
    let (status, b_after) = call(&app, &tokens.operator_b, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{b_after}");
    assert!(
        ready(&b_after) >= ready(&b_before).saturating_add(1),
        "{b_after}"
    );
    let (status, hub_after) = call(&app, &tokens.hub, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{hub_after}");
    assert!(
        ready(&hub_after) >= ready(&hub_before).saturating_add(1),
        "{hub_after}"
    );

    let grant = state
        .ingest_queue
        .try_scheduler("w2a-scheduler", Utc::now(), Duration::seconds(60))
        .await
        .expect("scheduler");
    assert!(grant.is_some(), "scheduler lease was not acquired");
    let (status, hub_sched) = call(&app, &tokens.hub, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{hub_sched}");
    assert_eq!(
        hub_sched["metrics"]["scheduler_owner"].as_str(),
        Some("w2a-scheduler"),
        "{hub_sched}"
    );
    let (status, a_sched) = call(&app, &tokens.operator_a, "GET", "/api/ingest/queue", None).await;
    assert_eq!(status, StatusCode::OK, "{a_sched}");
    assert!(a_sched["metrics"]["scheduler_owner"].is_null(), "{a_sched}");

    for token in [&tokens.empty, &tokens.unscoped] {
        for path in ["/api/ingest/queue", "/api/ingest/queue/scale-preview"] {
            let (status, body) = call(&app, token, "GET", path, None).await;
            assert_eq!(status, StatusCode::FORBIDDEN, "{path} {body}");
            assert_eq!(error_code(&body), "forbidden", "{path}");
        }
    }
    let (status, preview_a) = call(
        &app,
        &tokens.operator_a,
        "GET",
        "/api/ingest/queue/scale-preview",
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview_a}");
    assert!(preview_a.get("decision").is_some(), "{preview_a}");
    let (status, preview_b) = call(
        &app,
        &tokens.operator_b,
        "GET",
        "/api/ingest/queue/scale-preview",
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{preview_b}");

    let held = hold_jobs(&state, &[parse_job(&job_shared_a), parse_job(&job_a)]).await;
    let receipt_job = held
        .iter()
        .find(|job| job.job_id == parse_job(&job_shared_a))
        .unwrap()
        .clone();
    let retry_job = held
        .iter()
        .find(|job| job.job_id == parse_job(&job_a))
        .unwrap()
        .clone();
    state
        .ingest_queue
        .finish(&FinishRequest::new(
            "w2a-worker",
            retry_job.job_id,
            retry_job.fencing_token,
            Utc::now(),
            FinishOutcome::Permanent {
                code: "operator_hold".into(),
            },
        ))
        .await
        .expect("permanent finish");

    let (status, retried) = call(
        &app,
        &tokens.operator_a,
        "POST",
        &format!("/api/ingest/jobs/{job_a}/retry"),
        Some(json!({ "idempotency_key": "w2a-retry-key-a" })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{retried}");
    assert_eq!(retried["job"]["job_id"], job_a);
    assert_eq!(retried["job"]["tenant_id"], TENANT_A);

    let (status, retried_again) = call(
        &app,
        &tokens.operator_a,
        "POST",
        &format!("/api/ingest/jobs/{job_a}/retry"),
        Some(json!({ "idempotency_key": "w2a-retry-key-a" })),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{retried_again}");
    assert_eq!(retried_again["job"]["job_id"], job_a);

    let (status, other_retry) = call(
        &app,
        &tokens.operator_a2,
        "POST",
        &format!("/api/ingest/jobs/{job_a}/retry"),
        Some(json!({ "idempotency_key": "w2a-retry-key-a" })),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{other_retry}");
    assert_eq!(error_code(&other_retry), "not_retryable");
    assert!(other_retry.get("job").is_none(), "{other_retry}");

    let (status, foreign_retry) = call(
        &app,
        &tokens.operator_b,
        "POST",
        &format!("/api/ingest/jobs/{job_a}/retry"),
        Some(json!({ "idempotency_key": "w2a-retry-key-a" })),
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{foreign_retry}");
    assert_hides(&foreign_retry, &job_a);

    let receipt = state
        .ingest_queue
        .finish(&FinishRequest::new(
            "w2a-worker",
            receipt_job.job_id,
            receipt_job.fencing_token,
            Utc::now(),
            FinishOutcome::committed_accounted(JobCounts {
                fetched: 1,
                accepted: 1,
                inserted: 1,
                ..JobCounts::default()
            }),
        ))
        .await
        .expect("commit receipt")
        .expect("receipt row");
    assert_eq!(receipt.tenant_id, TENANT_A);
    assert_eq!(receipt.canonical_site, SITE_SHARED);
    assert_eq!(receipt.provider_instance_id, PORTAL_SHARED_A);
    assert_eq!(receipt.device_id, DEVICE);
    assert_eq!(receipt.model_revision, plans.shared_a);

    let path = format!("/api/ingest/receipts/{}", receipt.receipt_id);
    let (status, seen) = call(&app, &tokens.operator_a, "GET", &path, None).await;
    assert_eq!(status, StatusCode::OK, "{seen}");
    assert_eq!(seen["receipt"]["tenant_id"], TENANT_A);
    assert_eq!(seen["receipt"]["canonical_site"], SITE_SHARED);
    assert_eq!(seen["receipt"]["provider_instance_id"], PORTAL_SHARED_A);
    assert_eq!(seen["receipt"]["device_id"], DEVICE);
    assert_eq!(seen["receipt"]["model_revision"], plans.shared_a);
    let (status, hidden) = call(&app, &tokens.operator_b, "GET", &path, None).await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{hidden}");
    assert_hides(&hidden, &receipt.receipt_id.to_string());
}

struct Tokens {
    operator_a: String,
    operator_a2: String,
    operator_b: String,
    viewer: String,
    hub: String,
    empty: String,
    unscoped: String,
}

fn tokens(state: &AppState) -> Tokens {
    let a = vec![TENANT_A.to_string()];
    let b = vec![TENANT_B.to_string()];
    let empty = vec![TENANT_EMPTY.to_string()];
    Tokens {
        operator_a: state
            .auth
            .issue_token_with_tenants("w2a-operator-a", Role::Operator, 600, &a)
            .unwrap(),
        operator_a2: state
            .auth
            .issue_token_with_tenants("w2a-operator-a2", Role::Operator, 600, &a)
            .unwrap(),
        operator_b: state
            .auth
            .issue_token_with_tenants("w2a-operator-b", Role::Operator, 600, &b)
            .unwrap(),
        viewer: state
            .auth
            .issue_token_with_tenants("w2a-viewer-a", Role::Viewer, 600, &a)
            .unwrap(),
        hub: state
            .auth
            .issue_token_with_tenants("w2a-hub", Role::Admin, 600, &[])
            .unwrap(),
        empty: state
            .auth
            .issue_token_with_tenants("w2a-empty-user", Role::Operator, 600, &empty)
            .unwrap(),
        unscoped: state
            .auth
            .issue_token_with_tenants("w2a-unscoped", Role::Operator, 600, &[])
            .unwrap(),
    }
}

async fn harness() -> (Arc<AppState>, Router, Plans) {
    let mut state = AppState::new();
    state.auth = AuthConfig {
        secret: Some("ingest-scope-matrix-test-secret-not-a-credential".into()),
        admin_password: None,
        agent_password: None,
        viewer_password: None,
        viewer_tenant_ids: Vec::new(),
    };
    let state = Arc::new(state);
    {
        let mut plane = state.control_plane.write().await;
        *plane = ControlPlane {
            tenants: vec![
                TenantRecord {
                    id: TENANT_A.into(),
                    name: "A".into(),
                    building_ids: vec![SITE_A.into(), SITE_SHARED.into(), SITE_BARE.into()],
                },
                TenantRecord {
                    id: TENANT_B.into(),
                    name: "B".into(),
                    building_ids: vec![SITE_B.into(), SITE_SHARED.into()],
                },
                TenantRecord {
                    id: TENANT_EMPTY.into(),
                    name: "Empty".into(),
                    building_ids: Vec::new(),
                },
            ],
        };
    }
    let plans = {
        let mut models = state
            .providers
            .models
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        Plans {
            site_a: activate(&mut models, TENANT_A, SITE_A, PORTAL_A, "sat-a"),
            site_b: activate(&mut models, TENANT_B, SITE_B, PORTAL_B, "sat-b"),
            shared_a: activate(
                &mut models,
                TENANT_A,
                SITE_SHARED,
                PORTAL_SHARED_A,
                "sat-shared-a",
            ),
            shared_b: activate(
                &mut models,
                TENANT_B,
                SITE_SHARED,
                PORTAL_SHARED_B,
                "sat-shared-b",
            ),
        }
    };
    let app = crate::routes::router(Arc::clone(&state));
    (state, app, plans)
}

fn activate(
    models: &mut crate::providers::committed_model::CommittedModelStore,
    tenant: &str,
    site: &str,
    portal: &str,
    source: &str,
) -> String {
    let model = CommittedModel {
        schema: SCHEMA.into(),
        tenant_id: tenant.into(),
        site_id: site.into(),
        provider_instance_id: portal.into(),
        truncated: false,
        equipment: vec![CommittedEquipment {
            equipment_id: DEVICE.into(),
            equip_type: "ahu".into(),
            points: vec![CommittedPoint {
                point_id: format!("urn:openfdd:point:{site}:{DEVICE}:sat"),
                provider_point_id: source.into(),
                canonical_role: Some("sat".into()),
                selection_status: "approved".into(),
                fdd_ready: true,
                unit: Some("degF".into()),
                canonical_unit: None,
                kind: Some("Number".into()),
                quantity: None,
                provisional: false,
                display_name: None,
                history_mode: None,
                cadence_secs: None,
                heartbeat_secs: None,
            }],
        }],
    };
    models
        .try_activate(None, &model)
        .unwrap_or_else(|err| panic!("activate {tenant}/{site}: {err}"))
        .revision_id
}

fn backfill(
    key: &str,
    tenant: Option<&str>,
    site: &str,
    portal: &str,
    device: &str,
    revision: Option<&str>,
    start: DateTime<Utc>,
) -> Value {
    json!({
        "idempotency_key": key,
        "tenant_id": tenant,
        "canonical_site": site,
        "provider_instance_id": portal,
        "device_id": device,
        "model_revision": revision,
        "windows": [{
            "start": start,
            "end": start + Duration::hours(1),
        }],
    })
}

fn hour(offset: i64) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
        + Duration::hours(offset)
}

async fn call(
    app: &Router,
    token: &str,
    method: &str,
    path: &str,
    body: Option<Value>,
) -> (StatusCode, Value) {
    let request = Request::builder()
        .method(method)
        .uri(path)
        .header("authorization", format!("Bearer {token}"))
        .header("content-type", "application/json")
        .body(Body::from(
            body.map(|value| value.to_string()).unwrap_or_default(),
        ))
        .unwrap();
    let response = app.clone().oneshot(request).await.unwrap();
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    let body = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    (status, body)
}

fn error_code(body: &Value) -> String {
    body.pointer("/error/code")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string()
}

fn job_id(body: &Value) -> String {
    body["jobs"][0]["job_id"].as_str().unwrap_or("").to_string()
}

fn ready(body: &Value) -> u64 {
    body["metrics"]["ready_backlog"].as_u64().unwrap_or(0)
}

fn assert_hides(body: &Value, id: &str) {
    assert!(!body.to_string().contains(id), "{body}");
}

fn parse_job(job_id: &str) -> Uuid {
    Uuid::parse_str(job_id).unwrap()
}

async fn hold_jobs(state: &AppState, wanted: &[Uuid]) -> Vec<super::model::JobView> {
    let mut held = Vec::new();
    for _ in 0..32 {
        if wanted.iter().all(|id| {
            held.iter()
                .any(|job: &super::model::JobView| job.job_id == *id)
        }) {
            return held;
        }
        let claimed = state
            .ingest_queue
            .claim(&ClaimRequest {
                owner: "w2a-worker".into(),
                limit: 1,
                now: Utc::now(),
                lease_for: Duration::seconds(180),
            })
            .await
            .expect("claim");
        let Some(job) = claimed.into_iter().next() else {
            break;
        };
        if wanted.contains(&job.job_id) {
            held.push(job);
            continue;
        }
        state
            .ingest_queue
            .finish(&FinishRequest::new(
                "w2a-worker",
                job.job_id,
                job.fencing_token,
                Utc::now(),
                FinishOutcome::Retry {
                    code: "later".into(),
                    not_before: Utc::now() + Duration::hours(6),
                },
            ))
            .await
            .expect("defer claim");
    }
    panic!("jobs {wanted:?} were not claimed; held {}", held.len());
}

struct SchedulerSnap {
    owner: String,
    fencing_token: i64,
    expires_at: DateTime<Utc>,
}

async fn snapshot_scheduler(pool: &PgPool) -> Option<SchedulerSnap> {
    let row = sqlx::query(
        "SELECT owner, fencing_token, expires_at FROM ingest_scheduler_lease WHERE lease_name = 'scheduler'",
    )
    .fetch_optional(pool)
    .await
    .expect("read scheduler lease");
    row.map(|row| SchedulerSnap {
        owner: row.try_get("owner").unwrap(),
        fencing_token: row.try_get("fencing_token").unwrap(),
        expires_at: row.try_get("expires_at").unwrap(),
    })
}

async fn restore_scheduler(pool: &PgPool, snap: Option<SchedulerSnap>) {
    match snap {
        Some(snap) => {
            sqlx::query(
                "INSERT INTO ingest_scheduler_lease (lease_name, owner, fencing_token, expires_at)
                 VALUES ('scheduler', $1, $2, $3)
                 ON CONFLICT (lease_name) DO UPDATE SET
                   owner = EXCLUDED.owner,
                   fencing_token = EXCLUDED.fencing_token,
                   expires_at = EXCLUDED.expires_at",
            )
            .bind(snap.owner)
            .bind(snap.fencing_token)
            .bind(snap.expires_at)
            .execute(pool)
            .await
            .expect("restore scheduler lease");
        }
        None => {
            sqlx::query(
                "DELETE FROM ingest_scheduler_lease WHERE lease_name = 'scheduler' AND owner = 'w2a-scheduler'",
            )
            .execute(pool)
            .await
            .expect("clear fixture scheduler lease");
        }
    }
}

async fn purge_fixture(pool: &PgPool) {
    for stmt in [
        "DELETE FROM ingest_receipt WHERE tenant_id LIKE 'w2a-%' OR canonical_site LIKE 'w2a-%'",
        "DELETE FROM ingest_job WHERE tenant_id LIKE 'w2a-%' OR canonical_site LIKE 'w2a-%'",
        "DELETE FROM ingest_idempotency WHERE tenant_id LIKE 'w2a-%' OR actor LIKE 'w2a-%'",
        "DELETE FROM ingest_audit WHERE actor LIKE 'w2a-%'",
        "DELETE FROM ingest_portal_budget WHERE provider_instance_id LIKE 'w2a-%'",
    ] {
        sqlx::query(stmt)
            .execute(pool)
            .await
            .expect("purge fixture");
    }
}
