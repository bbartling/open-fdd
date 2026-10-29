//! 4.0.2 env portal upgraded onto the current scheduler.
//!
//! The committed plan slug (`nf-bosspi`) and the site connection id
//! (`nf:nf-bosspi`) differ by construction. Tenant `lab` lives on the provider
//! env, not in `tenants.json`. Memory runs on every `cargo test`. PostgreSQL
//! runs when `OPENFDD_TEST_DATABASE_URL` is set, and is required when
//! `OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED=1`.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::Router;
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::auth::{AuthConfig, Role};
use crate::state::AppState;

use super::model::{NewJob, MODEL_REVISION_BOOTSTRAP};

const TENANT: &str = "lab";
const SITE: &str = "BOSSPI";
const CONNECTION: &str = "nf:nf-bosspi";
const DEVICE: &str = "NF_EDGE";

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

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize provider env and workspace for the 4.0.2 upgrade fixture"
)]
async fn upgraded_portal_enqueues_due_windows_and_accepts_backfill() {
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().unwrap();
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let _sites = EnvGuard::set("OPENFDD_PROVIDER_SITES", &portal_env());
    let _poll = EnvGuard::set("OPENFDD_PROVIDER_POLL", "1");
    let _catchup = EnvGuard::set("OPENFDD_INGEST_CATCHUP_HOURS", "2");
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    let _queue = EnvGuard::unset("OPENFDD_INGEST_QUEUE");
    let _db = EnvGuard::unset("OPENFDD_DATABASE_URL");

    run_upgrade(workspace.path()).await;

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
                .expect("upgrade postgres fixture");
            super::postgres::apply_schema(&pool)
                .await
                .expect("ingest schema");
            purge_fixture(&pool).await;
            run_upgrade(workspace.path()).await;
            purge_fixture(&pool).await;
        }
        None if required => {
            panic!("OPENFDD_TEST_DATABASE_URL is required for the upgrade fixture")
        }
        None => {}
    }
}

async fn run_upgrade(workspace: &std::path::Path) {
    std::env::remove_var("OPENFDD_MULTI_TENANT");
    let (state, app, operator, hub) = harness().await;
    assert_eq!(state.providers.sites.len(), 1, "env site did not load");
    assert_eq!(state.providers.sites[0].provider_instance_id, CONNECTION);
    assert_eq!(state.providers.sites[0].tenant_id, TENANT);
    assert_eq!(state.providers.sites[0].building_id, SITE);

    let (status, health) = call(&app, &operator, "GET", "/api/providers/health", None).await;
    assert_eq!(status, StatusCode::OK, "{health}");
    assert_eq!(health["poll_enabled"], true, "{health}");
    assert_eq!(health["ok"], false, "{health}");
    let site = &health["sites"][0];
    assert_eq!(site["building_id"], SITE, "{health}");
    assert_eq!(site["provider_instance_id"], CONNECTION, "{health}");
    assert_eq!(site["poll_secs"], 3600, "{health}");
    assert_eq!(site["health"]["status"], "degraded", "{health}");
    assert_eq!(site["health"]["message"], "awaiting_poll", "{health}");
    assert!(site["last_poll_at"].is_null(), "{health}");

    let (status, tenants) = call(&app, &operator, "GET", "/api/tenants", None).await;
    assert_eq!(status, StatusCode::OK, "{tenants}");
    assert!(
        !tenant_ids(&tenants).iter().any(|id| id == TENANT),
        "env tenant was seeded into the admin list: {tenants}"
    );

    let seeded = DateTime::parse_from_rfc3339("2024-01-01T00:00:00Z")
        .unwrap()
        .with_timezone(&Utc);
    state
        .ingest_queue
        .enqueue(
            NewJob {
                tenant_id: TENANT.into(),
                canonical_site: SITE.into(),
                provider_instance_id: CONNECTION.into(),
                device_id: DEVICE.into(),
                model_revision: MODEL_REVISION_BOOTSTRAP.into(),
                logical_window_start: seeded,
                logical_window_end: seeded + Duration::hours(1),
                shard: String::new(),
                not_before: Utc::now(),
                estimated_cost: 1,
                requested_points_digest: None,
            },
            Utc::now(),
        )
        .await
        .expect("seed 4.0.2 bootstrap job");

    let enqueued = super::worker::enqueue_due_windows(&state, Utc::now())
        .await
        .expect("due windows");
    assert_eq!(enqueued, 2, "catch-up did not enqueue both due hours");

    let (status, listed) = call(
        &app,
        &operator,
        "GET",
        &format!("/api/ingest/jobs?site_id={SITE}&limit=50"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    let jobs = jobs_of(&listed);
    assert_eq!(jobs.len(), 3, "{listed}");
    let bootstrap: Vec<_> = jobs
        .iter()
        .filter(|job| job["model_revision"] == MODEL_REVISION_BOOTSTRAP)
        .collect();
    assert_eq!(bootstrap.len(), 1, "{listed}");
    assert_eq!(bootstrap[0]["state"], "queued", "{listed}");
    assert_eq!(bootstrap[0]["provider_instance_id"], CONNECTION, "{listed}");
    let fresh: Vec<_> = jobs
        .iter()
        .filter(|job| job["model_revision"] != MODEL_REVISION_BOOTSTRAP)
        .collect();
    assert_eq!(fresh.len(), 2, "{listed}");
    let revision = fresh[0]["model_revision"].as_str().unwrap_or("");
    assert!(!revision.is_empty() && revision != MODEL_REVISION_BOOTSTRAP);
    for job in &fresh {
        assert_eq!(job["tenant_id"], TENANT, "{job}");
        assert_eq!(job["canonical_site"], SITE, "{job}");
        assert_eq!(job["provider_instance_id"], CONNECTION, "{job}");
        assert_eq!(job["device_id"], DEVICE, "{job}");
        assert_eq!(job["model_revision"], revision, "{job}");
        assert_eq!(job["state"], "queued", "{job}");
    }

    let (status, before) = call(
        &app,
        &operator,
        "GET",
        &format!("/api/ingest/gaps?view=status&site_id={SITE}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{before}");
    assert_eq!(before["state"], "not_assessed", "{before}");
    let provider = &before["providers"][0];
    assert_eq!(provider["schedule"]["mode"], "periodic", "{before}");
    assert!(provider["schedule"]["timezone"].is_null(), "{before}");
    assert!(provider["next_run"].is_string(), "{before}");
    assert!(provider["planned_through"].is_string(), "{before}");
    assert_eq!(provider["status"]["model_revision"], revision, "{before}");
    assert_eq!(provider["status"]["approved_points"], 1, "{before}");
    assert_eq!(provider["status"]["discovered_points"], 1, "{before}");
    assert_eq!(
        provider["status"]["devices"][0]["device_id"], DEVICE,
        "{before}"
    );
    assert!(provider["status"]["verified_through"].is_null(), "{before}");
    assert!(provider["status"]["oldest_gap"].is_null(), "{before}");

    state
        .ingest_queue
        .advance_cursor(
            &super::cursor::CursorKey {
                tenant_id: TENANT.into(),
                canonical_site: SITE.into(),
                provider_instance_id: CONNECTION.into(),
                device_id: DEVICE.into(),
                model_revision: revision.into(),
            },
            Utc::now(),
        )
        .await
        .expect("advance cursor over queued windows");
    let (status, queued) = call(
        &app,
        &operator,
        "GET",
        &format!("/api/ingest/gaps?view=status&site_id={SITE}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{queued}");
    assert_eq!(queued["state"], "behind", "{queued}");
    let device = &queued["providers"][0]["status"]["devices"][0];
    assert_eq!(device["state"], "behind", "{queued}");
    assert_eq!(device["hole"]["state"], "queued", "{queued}");
    assert_ne!(queued["state"], "verified", "{queued}");

    let (status, missing) = call(
        &app,
        &operator,
        "GET",
        "/api/ingest/gaps?view=status&site_id=NOT_A_SITE",
        None,
    )
    .await;
    assert_eq!(status, StatusCode::NOT_FOUND, "{missing}");
    let (status, bad_view) = call(
        &app,
        &operator,
        "GET",
        &format!("/api/ingest/gaps?view=summary&site_id={SITE}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{bad_view}");
    assert_eq!(bad_view["error"]["code"], "invalid_view", "{bad_view}");
    let (status, plain) = call(
        &app,
        &operator,
        "GET",
        &format!("/api/ingest/gaps?site_id={SITE}"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{plain}");
    assert!(plain["gaps"].is_array(), "gap list without view: {plain}");

    let (status, created) = call(
        &app,
        &operator,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w9-upgrade-backfill",
            hour("2025-06-01T00:00:00Z"),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{created}");
    let job = &created["jobs"][0];
    assert_eq!(job["tenant_id"], TENANT, "{created}");
    assert_eq!(job["canonical_site"], SITE, "{created}");
    assert_eq!(job["provider_instance_id"], CONNECTION, "{created}");
    assert_eq!(job["device_id"], DEVICE, "{created}");
    assert_eq!(job["model_revision"], revision, "{created}");
    assert_ne!(job["model_revision"], MODEL_REVISION_BOOTSTRAP, "{created}");

    std::env::set_var("OPENFDD_MULTI_TENANT", "1");
    let (status, hub_created) = call(
        &app,
        &hub,
        "POST",
        "/api/ingest/backfill",
        Some(backfill(
            "w9-upgrade-hub-backfill",
            hour("2025-06-01T01:00:00Z"),
        )),
    )
    .await;
    assert_eq!(status, StatusCode::ACCEPTED, "{hub_created}");
    assert_eq!(hub_created["jobs"][0]["tenant_id"], TENANT, "{hub_created}");
    assert_eq!(
        hub_created["jobs"][0]["provider_instance_id"], CONNECTION,
        "{hub_created}"
    );
    assert_eq!(
        hub_created["jobs"][0]["model_revision"], revision,
        "{hub_created}"
    );

    let (status, listed) = call(
        &app,
        &hub,
        "GET",
        &format!("/api/ingest/jobs?site_id={SITE}&limit=50"),
        None,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    let jobs = jobs_of(&listed);
    assert_eq!(
        jobs.iter()
            .filter(|job| job["model_revision"] == MODEL_REVISION_BOOTSTRAP)
            .count(),
        1,
        "bootstrap row was removed: {listed}"
    );
    let (status, tenants) = call(&app, &hub, "GET", "/api/tenants", None).await;
    assert_eq!(status, StatusCode::OK, "{tenants}");
    assert!(
        !tenant_ids(&tenants).iter().any(|id| id == TENANT),
        "{tenants}"
    );
    assert!(
        !crate::tenant::ControlPlane::path_under_workspace(workspace).exists(),
        "upgrade wrote tenants.json"
    );
}

async fn harness() -> (Arc<AppState>, Router, String, String) {
    let mut state = AppState::new();
    state.auth = AuthConfig {
        secret: Some("upgrade-portal-test-secret-not-a-credential".into()),
        admin_password: None,
        agent_password: None,
        viewer_password: None,
        viewer_tenant_ids: Vec::new(),
    };
    let state = Arc::new(state);
    let operator = state
        .auth
        .issue_token_with_tenants("w9-operator", Role::Operator, 600, &[])
        .unwrap();
    let hub = state
        .auth
        .issue_token_with_tenants("w9-hub", Role::Admin, 600, &[])
        .unwrap();
    let app = crate::routes::router(Arc::clone(&state));
    (state, app, operator, hub)
}

fn portal_env() -> String {
    r#"{
        "building_id": "BOSSPI",
        "tenant_id": "lab",
        "provider": "nf",
        "provider_instance_id": "nf-bosspi",
        "endpoint": "https://portal.example",
        "auth_mode": "anonymous",
        "poll_secs": 3600,
        "point_map": [{
            "provider_point_id": "sat-1",
            "equipment_id": "NF_EDGE",
            "role": "supply-air-temp",
            "equip_type": "ahu",
            "unit": "degF"
        }]
    }"#
    .to_string()
}

fn backfill(key: &str, start: DateTime<Utc>) -> Value {
    json!({
        "idempotency_key": key,
        "tenant_id": TENANT,
        "canonical_site": SITE,
        "provider_instance_id": CONNECTION,
        "device_id": DEVICE,
        "model_revision": MODEL_REVISION_BOOTSTRAP,
        "windows": [{
            "start": start,
            "end": start + Duration::hours(1),
        }],
        "force": true,
    })
}

fn hour(raw: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(raw)
        .unwrap()
        .with_timezone(&Utc)
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

fn jobs_of(body: &Value) -> Vec<Value> {
    body["jobs"].as_array().cloned().unwrap_or_default()
}

fn tenant_ids(body: &Value) -> Vec<String> {
    body["tenants"]
        .as_array()
        .map(|rows| {
            rows.iter()
                .filter_map(|row| row["id"].as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

async fn purge_fixture(pool: &PgPool) {
    for stmt in [
        "DELETE FROM ingest_receipt WHERE tenant_id = 'lab' AND canonical_site = 'BOSSPI'",
        "DELETE FROM ingest_job WHERE tenant_id = 'lab' AND canonical_site = 'BOSSPI'",
        "DELETE FROM ingest_coverage_cursor WHERE tenant_id = 'lab' AND canonical_site = 'BOSSPI'",
        "DELETE FROM ingest_idempotency WHERE tenant_id = 'lab' OR actor IN ('w9-operator', 'w9-hub')",
        "DELETE FROM ingest_audit WHERE actor IN ('w9-operator', 'w9-hub')",
    ] {
        sqlx::query(stmt)
            .execute(pool)
            .await
            .expect("purge upgrade fixture");
    }
}
