//! Active-tenant switching keeps stored membership and scopes historian reads
//! to the active tenant. The fixture is a real PostgreSQL database and the
//! product router.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::response::Response;
use serde_json::{json, Value};
use tower::ServiceExt;

use crate::auth::AuthConfig;
use crate::state::AppState;
use crate::tenant::{ControlPlane, TenantRecord};
use crate::test_env_lock::{lock_env, WorkspaceEnv};
use crate::user_store::{UserRecord, UserStore};

const SECRET: &str = "w2c-tenant-switch-fixture-secret-32b";

struct EnvSet {
    prev: Vec<(&'static str, Option<String>)>,
}

impl EnvSet {
    fn set(pairs: &[(&'static str, Option<&str>)]) -> Self {
        let prev = pairs
            .iter()
            .map(|(key, value)| {
                let old = std::env::var(key).ok();
                match value {
                    Some(next) => std::env::set_var(key, next),
                    None => std::env::remove_var(key),
                }
                (*key, old)
            })
            .collect();
        Self { prev }
    }
}

impl Drop for EnvSet {
    fn drop(&mut self) {
        for (key, old) in self.prev.drain(..) {
            match old {
                Some(value) => std::env::set_var(key, value),
                None => std::env::remove_var(key),
            }
        }
    }
}

struct SharedPoolReset;

impl SharedPoolReset {
    fn arm() -> Self {
        fdd_tsdb::clear_shared_pool();
        Self
    }
}

impl Drop for SharedPoolReset {
    fn drop(&mut self) {
        fdd_tsdb::clear_shared_pool();
    }
}

fn postgres_url() -> String {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "postgresql://openfdd:openfdd@127.0.0.1:5432/openfdd".into())
}

fn operator(username: &str, tenant_ids: Vec<String>) -> UserRecord {
    UserRecord {
        username: username.into(),
        user_id: String::new(),
        role: "operator".into(),
        tenant_ids,
        password_env: None,
        password: Some("w2c-fixture".into()),
        disabled: false,
        session_version: 0,
    }
}

async fn read_json(response: Response) -> (StatusCode, Value) {
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    let body = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    (status, body)
}

fn authed(method: &str, uri: &str, token: &str, body: Option<&Value>) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {token}"));
    if body.is_some() {
        builder = builder.header("content-type", "application/json");
    }
    let payload = body.map(|value| value.to_string()).unwrap_or_default();
    builder.body(Body::from(payload)).expect("request")
}

fn string_list(value: &Value) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|item| item.as_str().map(str::to_string))
        .collect()
}

async fn equipment_count(pool: &sqlx::PgPool, building_id: &str) -> i64 {
    sqlx::query_scalar("SELECT COUNT(*)::bigint FROM equipment WHERE building_id = $1")
        .bind(building_id)
        .fetch_one(pool)
        .await
        .expect("equipment count")
}

/// A → B → A through the product handlers. Membership stays on the token.
/// Historian rows for the other tenant stay in PostgreSQL and are denied.
#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "OPENFDD_WORKSPACE and the multi-tenant flag are process-global for these handler calls"
)]
async fn switch_active_tenant_keeps_membership_and_denies_foreign_reads() {
    let _env_lock = lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _workspace_env = WorkspaceEnv::set(workspace.path());
    let _flags = EnvSet::set(&[
        ("OPENFDD_MULTI_TENANT", Some("1")),
        ("OPENFDD_HISTORIAN", None),
        ("OPENFDD_DATABASE_URL", None),
    ]);

    let suffix = uuid::Uuid::new_v4().simple().to_string();
    let tenant_a = format!("w2c_a_{suffix}");
    let tenant_b = format!("w2c_b_{suffix}");
    let site_a = format!("w2c_site_a_{suffix}");
    let site_b = format!("w2c_site_b_{suffix}");
    let equip_a = format!("w2c_equip_a_{suffix}");
    let equip_b = format!("w2c_equip_b_{suffix}");
    let member = format!("w2c_member_{suffix}");
    let only_a = format!("w2c_only_a_{suffix}");

    let mut plane = ControlPlane::default();
    plane
        .upsert_tenant(TenantRecord {
            id: tenant_a.clone(),
            name: "Tenant A".into(),
            building_ids: vec![site_a.clone()],
        })
        .expect("tenant a");
    plane
        .upsert_tenant(TenantRecord {
            id: tenant_b.clone(),
            name: "Tenant B".into(),
            building_ids: vec![site_b.clone()],
        })
        .expect("tenant b");
    plane.save(workspace.path()).expect("save tenants");

    let mut users = UserStore::default();
    users
        .upsert(operator(&member, vec![tenant_a.clone(), tenant_b.clone()]))
        .expect("member");
    users
        .upsert(operator(&only_a, vec![tenant_a.clone()]))
        .expect("only a");
    users.save(workspace.path()).expect("save users");

    let mut state = AppState::new();
    state.auth = AuthConfig {
        secret: Some(SECRET.into()),
        admin_password: None,
        agent_password: None,
        viewer_password: None,
        viewer_tenant_ids: Vec::new(),
    };
    let login = state
        .auth
        .issue_token_with_tenants(
            &member,
            crate::auth::Role::Operator,
            3600,
            &[tenant_a.clone(), tenant_b.clone()],
        )
        .expect("login token");
    let only = state
        .auth
        .issue_token_with_tenants(
            &only_a,
            crate::auth::Role::Operator,
            3600,
            std::slice::from_ref(&tenant_a),
        )
        .expect("single membership token");
    let login_claims = state.auth.decode_claims(&login).expect("decode login");
    assert_eq!(
        login_claims.tenant_ids,
        vec![tenant_a.clone(), tenant_b.clone()],
        "login keeps both memberships"
    );
    assert_eq!(
        login_claims.active_tenant_id.as_deref(),
        Some(tenant_a.as_str())
    );

    let url = postgres_url();
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("connect postgres fixture");
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
    ] {
        sqlx::query(statement).execute(&pool).await.expect("schema");
    }
    for (site, equip) in [(&site_a, &equip_a), (&site_b, &equip_b)] {
        sqlx::query("DELETE FROM equipment WHERE building_id = $1")
            .bind(site)
            .execute(&pool)
            .await
            .expect("clear equipment");
        sqlx::query("DELETE FROM building WHERE building_id = $1")
            .bind(site)
            .execute(&pool)
            .await
            .expect("clear building");
        sqlx::query("DELETE FROM site WHERE site_id = $1")
            .bind(site)
            .execute(&pool)
            .await
            .expect("clear site");
        sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1)")
            .bind(site)
            .execute(&pool)
            .await
            .expect("insert site");
        sqlx::query("INSERT INTO building (building_id, site_id, dis) VALUES ($1, $1, $1)")
            .bind(site)
            .execute(&pool)
            .await
            .expect("insert building");
        sqlx::query(
            "INSERT INTO equipment (building_id, equipment_id, equip_type) VALUES ($1, $2, 'ahu')",
        )
        .bind(site)
        .bind(equip)
        .execute(&pool)
        .await
        .expect("insert equipment");
    }

    let _historian = EnvSet::set(&[
        ("OPENFDD_HISTORIAN", Some("timescale")),
        ("OPENFDD_DATABASE_URL", Some(&url)),
    ]);
    // A previous test may have cached the shared pool on a runtime that has
    // already ended. Drop it, and drop ours when this test ends.
    let _shared_pool = SharedPoolReset::arm();
    let state = Arc::new(state);
    let app = crate::routes::router(Arc::clone(&state));

    let (status, body) = read_json(
        app.clone()
            .oneshot(authed(
                "POST",
                "/api/tenants/select",
                &only,
                Some(&json!({ "tenant_id": tenant_b })),
            ))
            .await
            .expect("only-a select"),
    )
    .await;
    assert_eq!(
        status,
        StatusCode::FORBIDDEN,
        "single membership select {body}"
    );
    assert_eq!(
        body.get("ok").and_then(|v| v.as_bool()),
        Some(false),
        "{body}"
    );

    let (status, body) = read_json(
        app.clone()
            .oneshot(authed(
                "GET",
                &format!("/api/fdd/equipment?building_id={site_b}"),
                &only,
                None,
            ))
            .await
            .expect("only-a foreign read"),
    )
    .await;
    assert_eq!(
        status,
        StatusCode::FORBIDDEN,
        "single membership read {body}"
    );
    assert_eq!(
        body.get("ok").and_then(|v| v.as_bool()),
        Some(false),
        "{body}"
    );
    assert_eq!(equipment_count(&pool, &site_b).await, 1);

    let (status, body) = read_json(
        app.clone()
            .oneshot(authed(
                "POST",
                "/api/tenants/select",
                &login,
                Some(&json!({ "tenant_id": tenant_b })),
            ))
            .await
            .expect("select b"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "select B {body}");
    assert_eq!(body["active_tenant_id"], tenant_b);
    let token_b = body["access_token"]
        .as_str()
        .or_else(|| body["token"].as_str())
        .expect("reminted token")
        .to_string();
    let claims_b = state.auth.decode_claims(&token_b).expect("decode B");
    assert_eq!(
        claims_b.tenant_ids,
        vec![tenant_a.clone(), tenant_b.clone()],
        "remint keeps membership A"
    );
    assert_eq!(
        claims_b.active_tenant_id.as_deref(),
        Some(tenant_b.as_str())
    );

    let (status, me) = read_json(
        app.clone()
            .oneshot(authed("GET", "/api/auth/me", &token_b, None))
            .await
            .expect("me after B"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{me}");
    assert_eq!(me["active_tenant_id"], tenant_b);
    assert_eq!(
        string_list(&me["tenant_ids"]),
        vec![tenant_a.clone(), tenant_b.clone()]
    );

    let (status, listed) = read_json(
        app.clone()
            .oneshot(authed("GET", "/api/tenants", &token_b, None))
            .await
            .expect("list after B"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{listed}");
    let mut listed_ids = listed["tenants"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|tenant| tenant.get("id").and_then(|id| id.as_str()))
        .map(str::to_string)
        .collect::<Vec<_>>();
    listed_ids.sort();
    let mut expected = vec![tenant_a.clone(), tenant_b.clone()];
    expected.sort();
    assert_eq!(
        listed_ids, expected,
        "membership list stays stable {listed}"
    );
    let visible = string_list(&listed["buildings_visible"]);
    assert!(visible.contains(&site_b), "active buildings {visible:?}");
    assert!(
        !visible.contains(&site_a),
        "other tenant hidden {visible:?}"
    );

    let (status, own_b) = read_json(
        app.clone()
            .oneshot(authed(
                "GET",
                &format!("/api/fdd/equipment?building_id={site_b}"),
                &token_b,
                None,
            ))
            .await
            .expect("read B"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{own_b}");
    assert_eq!(own_b["ok"], true, "{own_b}");
    assert_eq!(own_b["count"], 1, "{own_b}");
    assert_eq!(own_b["equipment"][0]["equipment_id"], equip_b);

    let before_a = equipment_count(&pool, &site_a).await;
    let (status, foreign) = read_json(
        app.clone()
            .oneshot(authed(
                "GET",
                &format!("/api/fdd/equipment?building_id={site_a}"),
                &token_b,
                None,
            ))
            .await
            .expect("read A while active B"),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{foreign}");
    assert_eq!(foreign.get("ok").and_then(|v| v.as_bool()), Some(false));
    assert_eq!(equipment_count(&pool, &site_a).await, before_a);

    let (status, body) = read_json(
        app.clone()
            .oneshot(authed(
                "POST",
                "/api/tenants/select",
                &token_b,
                Some(&json!({ "tenant_id": tenant_a })),
            ))
            .await
            .expect("select a"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "switch back A {body}");
    let token_a = body["access_token"]
        .as_str()
        .or_else(|| body["token"].as_str())
        .expect("token A")
        .to_string();
    let claims_a = state.auth.decode_claims(&token_a).expect("decode A");
    assert_eq!(
        claims_a.tenant_ids,
        vec![tenant_a.clone(), tenant_b.clone()]
    );
    assert_eq!(
        claims_a.active_tenant_id.as_deref(),
        Some(tenant_a.as_str())
    );

    let (status, own_a) = read_json(
        app.clone()
            .oneshot(authed(
                "GET",
                &format!("/api/fdd/equipment?building_id={site_a}"),
                &token_a,
                None,
            ))
            .await
            .expect("read A"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{own_a}");
    assert_eq!(own_a["equipment"][0]["equipment_id"], equip_a);
    let (status, foreign_b) = read_json(
        app.clone()
            .oneshot(authed(
                "GET",
                &format!("/api/fdd/equipment?building_id={site_b}"),
                &token_a,
                None,
            ))
            .await
            .expect("read B while active A"),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{foreign_b}");
    assert_eq!(equipment_count(&pool, &site_b).await, 1);

    let (status, previous) = read_json(
        app.clone()
            .oneshot(authed("GET", "/api/auth/me", &login, None))
            .await
            .expect("previous token"),
    )
    .await;
    assert_eq!(
        status,
        StatusCode::OK,
        "previous token still authenticates {previous}"
    );
    assert_eq!(previous["active_tenant_id"], tenant_a);
    assert_eq!(
        string_list(&previous["tenant_ids"]),
        vec![tenant_a.clone(), tenant_b.clone()]
    );
    let (status, previous_foreign) = read_json(
        app.clone()
            .oneshot(authed(
                "GET",
                &format!("/api/fdd/equipment?building_id={site_b}"),
                &login,
                None,
            ))
            .await
            .expect("previous token foreign read"),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{previous_foreign}");

    let mut users = UserStore::load_or_empty(workspace.path());
    users.set_disabled(&member, true).expect("disable");
    users.save(workspace.path()).expect("save disable");
    let (status, revoked_old) = read_json(
        app.clone()
            .oneshot(authed("GET", "/api/auth/me", &login, None))
            .await
            .expect("revoked previous"),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{revoked_old}");
    let (status, revoked_new) = read_json(
        app.clone()
            .oneshot(authed("GET", "/api/auth/me", &token_a, None))
            .await
            .expect("revoked current"),
    )
    .await;
    assert_eq!(status, StatusCode::UNAUTHORIZED, "{revoked_new}");

    for site in [&site_a, &site_b] {
        sqlx::query("DELETE FROM equipment WHERE building_id = $1")
            .bind(site)
            .execute(&pool)
            .await
            .expect("cleanup equipment");
        sqlx::query("DELETE FROM building WHERE building_id = $1")
            .bind(site)
            .execute(&pool)
            .await
            .expect("cleanup building");
        sqlx::query("DELETE FROM site WHERE site_id = $1")
            .bind(site)
            .execute(&pool)
            .await
            .expect("cleanup site");
    }
}
