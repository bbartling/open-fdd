//! Catalog parity for `GET /api/fdd/rules`.
//!
//! PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is set (the Rust CI job).
//! Rows are inserted the way the warehouse seed does — id, sql file, and title
//! only — and the handler must still return the canonical pack. A row whose
//! applicability columns are null stays unknown. An explicit empty kind list
//! means the rule applies to every equipment type.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;
use tower::ServiceExt;

use crate::state::AppState;

const SENTINELS: &[&str] = &["W4A-UNKNOWN", "W4A-ALL", "W4A-TYPED"];

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

fn test_database_url() -> Option<String> {
    std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn json_strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL for the rule catalog fixture"
)]
async fn catalog_matches_canonical_pack_and_distinguishes_unknown_metadata() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
    let _database = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
    let _jwt = EnvGuard::unset("OPENFDD_JWT_SECRET");
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    let _shared_pool = SharedPoolReset::arm();

    let pool = PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("rule catalog postgres fixture");
    apply_registry_schema(&pool).await;
    seed_sparse_pack_and_sentinels(&pool).await;

    let state = Arc::new(AppState::new());
    let app = crate::routes::router(state);
    let body = get_json(&app, "/api/fdd/rules").await;
    assert_eq!(body["ok"], json!(true), "{body}");
    let listed = body["rules"].as_array().expect("rules");

    let pack = fdd_rules::load_registry(&crate::timescale_product::sql_root_for_registry())
        .expect("canonical rule pack");
    assert!(
        pack.rules.len() >= 77,
        "canonical pack shrank: {}",
        pack.rules.len()
    );
    for spec in &pack.rules {
        let row = listed
            .iter()
            .find(|row| row["rule_id"].as_str() == Some(spec.rule_id.as_str()))
            .unwrap_or_else(|| panic!("catalog missing {}", spec.rule_id));
        assert_eq!(
            row["description"].as_str(),
            Some(spec.description.as_str()),
            "{}",
            spec.rule_id
        );
        assert_eq!(
            json_strings(&row["equipment_kinds"]),
            spec.equipment_kinds,
            "{}",
            spec.rule_id
        );
        assert_eq!(
            json_strings(&row["required_roles"]),
            spec.required_roles,
            "{}",
            spec.rule_id
        );
        assert_eq!(
            json_strings(&row["optional_roles"]),
            spec.optional_roles,
            "{}",
            spec.rule_id
        );
        let applicability = if spec.equipment_kinds.is_empty() {
            "all"
        } else {
            "typed"
        };
        assert_eq!(
            row["applicability"].as_str(),
            Some(applicability),
            "{}",
            spec.rule_id
        );
        assert!(
            row["equipment_kinds"].is_array(),
            "{} kinds must be a known array",
            spec.rule_id
        );
    }

    let fc5 = listed
        .iter()
        .find(|row| row["rule_id"] == "FC5")
        .expect("FC5");
    assert_eq!(
        fc5["description"],
        json!("SAT cold when heating commanded (GL36 D)")
    );
    assert_eq!(fc5["equipment_kinds"], json!(["ahu"]));
    assert_eq!(
        fc5["required_roles"],
        json!(["sat", "mat", "htg_valve_pct", "fan_cmd"])
    );
    let fc6 = listed
        .iter()
        .find(|row| row["rule_id"] == "FC6")
        .expect("FC6");
    assert_eq!(fc6["description"], json!("Estimated OA fraction mismatch"));
    assert_eq!(fc6["equipment_kinds"], json!(["ahu"]));
    let fc8 = listed
        .iter()
        .find(|row| row["rule_id"] == "FC8")
        .expect("FC8");
    assert_eq!(fc8["description"], json!("SAT vs MAT while economizing"));
    assert_eq!(fc8["equipment_kinds"], json!(["ahu"]));

    let unknown = listed
        .iter()
        .find(|row| row["rule_id"] == "W4A-UNKNOWN")
        .expect("unknown sentinel");
    assert!(unknown["description"].is_null());
    assert!(unknown["equipment_kinds"].is_null());
    assert!(unknown["required_roles"].is_null());
    assert!(unknown["optional_roles"].is_null());
    assert_eq!(unknown["applicability"], json!("unknown"));

    let all = listed
        .iter()
        .find(|row| row["rule_id"] == "W4A-ALL")
        .expect("applies-to-all sentinel");
    assert_eq!(all["equipment_kinds"], json!([]));
    assert_eq!(all["required_roles"], json!([]));
    assert_eq!(all["optional_roles"], json!([]));
    assert_eq!(all["applicability"], json!("all"));

    let typed = listed
        .iter()
        .find(|row| row["rule_id"] == "W4A-TYPED")
        .expect("db-typed sentinel");
    assert_eq!(typed["equipment_kinds"], json!(["boiler"]));
    assert_eq!(typed["required_roles"], json!(["hw_supply_t"]));
    assert_eq!(typed["optional_roles"], json!([]));
    assert_eq!(typed["applicability"], json!("typed"));

    delete_sentinels(&pool).await;
}

async fn get_json(app: &axum::Router, path: &str) -> Value {
    let response = app
        .clone()
        .oneshot(
            Request::get(path)
                .body(Body::empty())
                .expect("catalog request"),
        )
        .await
        .expect("catalog response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("catalog body");
    let body: Value = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    assert_eq!(status, StatusCode::OK, "{path} {body}");
    body
}

async fn apply_registry_schema(pool: &PgPool) {
    crate::test_ddl::execute_idempotent_ddl(
        pool,
        r#"
        CREATE TABLE IF NOT EXISTS fdd_rule_registry (
          rule_id text PRIMARY KEY,
          sql_file text NOT NULL,
          title text,
          equipment_kinds text[],
          required_roles text[],
          optional_roles text[],
          parity_status text,
          enabled boolean NOT NULL DEFAULT true,
          detail jsonb
        )
        "#,
    )
    .await;
    for column in ["equipment_kinds", "required_roles", "optional_roles"] {
        let statement =
            format!("ALTER TABLE fdd_rule_registry ADD COLUMN IF NOT EXISTS {column} text[]");
        crate::test_ddl::execute_idempotent_ddl(pool, &statement).await;
    }
}

async fn seed_sparse_pack_and_sentinels(pool: &PgPool) {
    delete_sentinels(pool).await;
    let pack = fdd_rules::load_registry(&crate::timescale_product::sql_root_for_registry())
        .expect("canonical rule pack");
    for spec in &pack.rules {
        sqlx::query(
            r#"
            INSERT INTO fdd_rule_registry (rule_id, sql_file, title, enabled)
            VALUES ($1, $2, $3, true)
            ON CONFLICT (rule_id) DO NOTHING
            "#,
        )
        .bind(&spec.rule_id)
        .bind(&spec.sql_file)
        .bind(&spec.rule_id)
        .execute(pool)
        .await
        .expect("sparse pack row");
    }
    sqlx::query(
        r#"
        INSERT INTO fdd_rule_registry (
          rule_id, sql_file, title, enabled,
          equipment_kinds, required_roles, optional_roles
        )
        VALUES ($1, $2, $1, true, $3, $4, $5)
        ON CONFLICT (rule_id) DO UPDATE SET
          equipment_kinds = EXCLUDED.equipment_kinds,
          required_roles = EXCLUDED.required_roles,
          optional_roles = EXCLUDED.optional_roles
        "#,
    )
    .bind("W4A-UNKNOWN")
    .bind("w4a_unknown.sql")
    .bind(Option::<Vec<String>>::None)
    .bind(Option::<Vec<String>>::None)
    .bind(Option::<Vec<String>>::None)
    .execute(pool)
    .await
    .expect("unknown sentinel");
    let empty: Option<Vec<String>> = Some(Vec::new());
    sqlx::query(
        r#"
        INSERT INTO fdd_rule_registry (
          rule_id, sql_file, title, enabled,
          equipment_kinds, required_roles, optional_roles
        )
        VALUES ($1, $2, $1, true, $3, $4, $5)
        ON CONFLICT (rule_id) DO UPDATE SET
          equipment_kinds = EXCLUDED.equipment_kinds,
          required_roles = EXCLUDED.required_roles,
          optional_roles = EXCLUDED.optional_roles
        "#,
    )
    .bind("W4A-ALL")
    .bind("w4a_all.sql")
    .bind(empty.clone())
    .bind(empty.clone())
    .bind(empty)
    .execute(pool)
    .await
    .expect("all sentinel");
    sqlx::query(
        r#"
        INSERT INTO fdd_rule_registry (
          rule_id, sql_file, title, enabled,
          equipment_kinds, required_roles, optional_roles
        )
        VALUES ($1, $2, $1, true, $3, $4, $5)
        ON CONFLICT (rule_id) DO UPDATE SET
          equipment_kinds = EXCLUDED.equipment_kinds,
          required_roles = EXCLUDED.required_roles,
          optional_roles = EXCLUDED.optional_roles
        "#,
    )
    .bind("W4A-TYPED")
    .bind("w4a_typed.sql")
    .bind(Some(vec!["boiler".to_string()]))
    .bind(Some(vec!["hw_supply_t".to_string()]))
    .bind(Some(Vec::<String>::new()))
    .execute(pool)
    .await
    .expect("typed sentinel");
}

async fn delete_sentinels(pool: &PgPool) {
    for rule_id in SENTINELS {
        sqlx::query("DELETE FROM fdd_rule_registry WHERE rule_id = $1")
            .bind(rule_id)
            .execute(pool)
            .await
            .expect("delete sentinel");
    }
}
