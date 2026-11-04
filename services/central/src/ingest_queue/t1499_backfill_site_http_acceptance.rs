//! HTTP acceptance for `POST /api/ingest/backfill/site` (#1499).

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

use crate::auth::{AuthConfig, Role};
use crate::providers::committed_model::{
    CommittedEquipment, CommittedModel, CommittedPoint, SCHEMA,
};
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

struct SiteCase {
    tenant: String,
    site: String,
    connection: String,
    plan_slug: String,
    rev: String,
    pool: PgPool,
}

impl SiteCase {
    async fn open(label: &str) -> Option<Self> {
        let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .filter(|value| !value.trim().is_empty())?;
        let pool = PgPoolOptions::new()
            .max_connections(3)
            .connect(url.trim())
            .await
            .expect("postgres");
        crate::ingest_queue::test_schema::apply_ingest_queue_schema(&pool)
            .await
            .expect("schema");
        let suffix = &Uuid::new_v4().simple().to_string()[..10];
        let tenant = format!("t1499-{label}-{suffix}");
        let site = format!("{tenant}-site");
        let plan_slug = format!("nf-{suffix}");
        let connection = format!("nf:{plan_slug}");
        let rev = format!("rev-{suffix}");
        sqlx::query("INSERT INTO site (site_id) VALUES ($1) ON CONFLICT DO NOTHING")
            .bind(&site)
            .execute(&pool)
            .await
            .expect("site row");
        Some(Self {
            tenant,
            site,
            connection,
            plan_slug,
            rev,
            pool,
        })
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

    fn point_key(&self, device: &str, stem: &str) -> String {
        format!("urn:openfdd:point:{}:{device}:{stem}", self.site)
    }

    async fn seed_point_map(&self, device: &str, portal: &str, openfdd_key: &str, role: &str) {
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
        .bind(portal)
        .bind(role)
        .bind(device)
        .execute(&self.pool)
        .await
        .expect("point_map");
    }

    async fn seed_binding(&self, device: &str, provider_start: DateTime<Utc>) {
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
        .bind(&self.connection)
        .bind(device)
        .bind(&self.rev)
        .bind(h(0))
        .bind(provider_start)
        .execute(&self.pool)
        .await
        .expect("binding");
    }

    async fn insert_sample(&self, openfdd_key: &str, at: DateTime<Utc>) {
        sqlx::query(
            "INSERT INTO sample (ts, site_id, openfdd_key, val, unit, quality)
         VALUES ($1, $2, $3, 1.0, 'degF', 'good')",
        )
        .bind(at)
        .bind(&self.site)
        .bind(openfdd_key)
        .execute(&self.pool)
        .await
        .expect("sample");
    }

    fn equipment(&self, device: &str, portal: &str) -> CommittedEquipment {
        CommittedEquipment {
            equipment_id: device.into(),
            equip_type: "ahu".into(),
            points: vec![CommittedPoint {
                point_id: self.point_key(device, "sat"),
                provider_point_id: portal.into(),
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
                primary_reference: false,
            }],
        }
    }

    fn provider_sites_json(&self) -> String {
        format!(
            r#"[{{"building_id":"{site}","tenant_id":"{tenant}","provider_instance_id":"{conn}","provider":"nf","endpoint":"https://portal.example","auth_mode":"anonymous"}}]"#,
            site = self.site,
            tenant = self.tenant,
            conn = self.connection,
        )
    }
}

async fn harness(case: &SiteCase) -> (Arc<AppState>, Router, String) {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL").expect("database url");
    std::env::set_var("OPENFDD_DATABASE_URL", &url);
    let _sites = EnvGuard::set("OPENFDD_PROVIDER_SITES", &case.provider_sites_json());
    let mut state = AppState::new();
    state.auth = AuthConfig {
        secret: Some("t1499-site-backfill-test-secret-not-a-credential".into()),
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
                name: "T1499".into(),
                building_ids: vec![case.site.clone()],
            }],
        };
    }
    let token = state
        .auth
        .issue_token_with_tenants(
            "t1499-operator",
            Role::Operator,
            600,
            &[case.tenant.clone()],
        )
        .expect("token");
    let app = crate::routes::router(Arc::clone(&state));
    (state, app, token)
}

async fn post_site(app: &Router, token: &str, body: Value) -> (StatusCode, Value) {
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .method("POST")
                .uri("/api/ingest/backfill/site")
                .header("authorization", format!("Bearer {token}"))
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .unwrap();
    let parsed = serde_json::from_slice(&bytes).unwrap_or(json!({}));
    (status, parsed)
}

fn site_body(
    case: &SiteCase,
    key: &str,
    provider: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> Value {
    json!({
        "idempotency_key": key,
        "tenant_id": case.tenant,
        "canonical_site": case.site,
        "provider_instance_id": provider,
        "start": start,
        "end": end,
        "force": false,
    })
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL for ingest site backfill HTTP matrix"
)]
async fn t1499_backfill_site_http_acceptance() {
    let required = std::env::var("OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
    let Some(url) = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .filter(|value| !value.trim().is_empty())
    else {
        if required {
            panic!("OPENFDD_TEST_DATABASE_URL is required for t1499 site backfill HTTP acceptance");
        }
        eprintln!("OPENFDD_TEST_DATABASE_URL unset; skipping t1499 site backfill HTTP acceptance");
        return;
    };
    let _lock = crate::test_env_lock::lock_env();
    let _mt = EnvGuard::set("OPENFDD_MULTI_TENANT", "1");
    let _db = EnvGuard::set("OPENFDD_DATABASE_URL", url.trim());

    let case = SiteCase::open("http").await.expect("case");
    case.cleanup().await;

    // Unknown provider → 404 unknown_provider.
    {
        let (state, app, token) = harness(&case).await;
        state
            .providers
            .models
            .lock()
            .unwrap()
            .try_activate(
                None,
                &CommittedModel {
                    schema: SCHEMA.into(),
                    tenant_id: case.tenant.clone(),
                    site_id: case.site.clone(),
                    provider_instance_id: case.plan_slug.clone(),
                    truncated: false,
                    equipment: vec![case.equipment("DEV_A", "src-a")],
                },
            )
            .expect("plan");
        let (status, body) = post_site(
            &app,
            &token,
            site_body(&case, "t1499-unknown", "nf:missing-provider", h(0), h(2)),
        )
        .await;
        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(
            body.pointer("/error/code").and_then(Value::as_str),
            Some("unknown_provider")
        );
    }

    case.cleanup().await;

    // Two devices → two explained gap plans; top-level already_covered when fully stored.
    {
        let (state, app, token) = harness(&case).await;
        let dev_a = "AHU_A";
        let dev_b = "AHU_B";
        state
            .providers
            .models
            .lock()
            .unwrap()
            .try_activate(
                None,
                &CommittedModel {
                    schema: SCHEMA.into(),
                    tenant_id: case.tenant.clone(),
                    site_id: case.site.clone(),
                    provider_instance_id: case.plan_slug.clone(),
                    truncated: false,
                    equipment: vec![
                        case.equipment(dev_a, "src-a"),
                        case.equipment(dev_b, "src-b"),
                    ],
                },
            )
            .expect("two-device plan");
        for (device, portal) in [(dev_a, "src-a"), (dev_b, "src-b")] {
            let key = case.point_key(device, "sat");
            case.seed_point_map(device, portal, &key, "sat").await;
            case.seed_binding(device, h(0)).await;
            for hour in [1, 2] {
                case.insert_sample(&key, h(hour) + Duration::minutes(5))
                    .await;
            }
        }
        let (status, body) = post_site(
            &app,
            &token,
            site_body(&case, "t1499-two-devices", &case.connection, h(0), h(3)),
        )
        .await;
        assert_eq!(status, StatusCode::ACCEPTED);
        let plans = body["gap_plans"].as_array().expect("gap_plans");
        assert_eq!(plans.len(), 2, "{body}");
        for device in [dev_a, dev_b] {
            let row = plans
                .iter()
                .find(|row| row["device_id"].as_str() == Some(device))
                .unwrap_or_else(|| panic!("missing plan for {device}: {body}"));
            assert_eq!(row["outcome"].as_str(), Some("already_covered"));
            assert!(row.get("counts").is_some());
        }
        assert_eq!(body["outcome"].as_str(), Some("already_covered"));
        assert_eq!(body["jobs"].as_u64(), Some(0));
    }

    case.cleanup().await;

    // Slug plan + connection id → device_not_in_plan (unmatched group lookup).
    {
        let (state, app, token) = harness(&case).await;
        let dev = "SLUG_DEV";
        state
            .providers
            .models
            .lock()
            .unwrap()
            .try_activate(
                None,
                &CommittedModel {
                    schema: SCHEMA.into(),
                    tenant_id: case.tenant.clone(),
                    site_id: case.site.clone(),
                    provider_instance_id: case.plan_slug.clone(),
                    truncated: false,
                    equipment: vec![case.equipment(dev, "src-slug")],
                },
            )
            .expect("slug plan");
        case.seed_binding(dev, h(0)).await;
        let (status, body) = post_site(
            &app,
            &token,
            site_body(&case, "t1499-slug", &case.connection, h(0), h(2)),
        )
        .await;
        assert_eq!(status, StatusCode::ACCEPTED);
        let plans = body["gap_plans"].as_array().expect("gap_plans");
        assert_eq!(plans.len(), 1);
        assert_eq!(plans[0]["device_id"].as_str(), Some(dev));
        assert_eq!(plans[0]["outcome"].as_str(), Some("device_not_in_plan"));
    }

    case.cleanup().await;

    // Distinguish already_covered vs enqueued on the same request.
    {
        let (state, app, token) = harness(&case).await;
        let covered = "COV_DEV";
        let gap = "GAP_DEV";
        state
            .providers
            .models
            .lock()
            .unwrap()
            .try_activate(
                None,
                &CommittedModel {
                    schema: SCHEMA.into(),
                    tenant_id: case.tenant.clone(),
                    site_id: case.site.clone(),
                    provider_instance_id: case.plan_slug.clone(),
                    truncated: false,
                    equipment: vec![
                        case.equipment(covered, "src-cov"),
                        case.equipment(gap, "src-gap"),
                    ],
                },
            )
            .expect("mixed plan");
        let cov_key = case.point_key(covered, "sat");
        let gap_key = case.point_key(gap, "sat");
        case.seed_point_map(covered, "src-cov", &cov_key, "sat")
            .await;
        case.seed_point_map(gap, "src-gap", &gap_key, "sat").await;
        case.seed_binding(covered, h(0)).await;
        case.seed_binding(gap, h(0)).await;
        for hour in [1, 2] {
            case.insert_sample(&cov_key, h(hour) + Duration::minutes(5))
                .await;
        }
        case.insert_sample(&gap_key, h(1) + Duration::minutes(5))
            .await;
        let (status, body) = post_site(
            &app,
            &token,
            site_body(&case, "t1499-mixed", &case.connection, h(0), h(3)),
        )
        .await;
        assert_eq!(status, StatusCode::ACCEPTED);
        let plans = body["gap_plans"].as_array().expect("gap_plans");
        assert_eq!(plans.len(), 2);
        let cov_row = plans
            .iter()
            .find(|row| row["device_id"].as_str() == Some(covered))
            .expect("covered row");
        let gap_row = plans
            .iter()
            .find(|row| row["device_id"].as_str() == Some(gap))
            .expect("gap row");
        assert_eq!(cov_row["outcome"].as_str(), Some("already_covered"));
        assert_eq!(gap_row["outcome"].as_str(), Some("enqueued"));
        assert!(body["jobs"].as_u64().unwrap_or(0) > 0);
        assert_ne!(body["outcome"].as_str(), Some("already_covered"));
    }

    case.cleanup().await;
}
