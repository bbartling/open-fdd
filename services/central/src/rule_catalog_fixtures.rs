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
use sqlx::{PgPool, Row};
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

struct SchemaDrop {
    url: String,
    schema: String,
}

impl Drop for SchemaDrop {
    fn drop(&mut self) {
        let url = std::mem::take(&mut self.url);
        let schema = std::mem::take(&mut self.schema);
        if url.is_empty() || schema.is_empty() {
            return;
        }
        let joined = std::thread::spawn(move || {
            let Ok(rt) = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
            else {
                return;
            };
            rt.block_on(async move {
                let Ok(pool) = sqlx::postgres::PgPoolOptions::new()
                    .max_connections(1)
                    .connect(&url)
                    .await
                else {
                    return;
                };
                let _ = sqlx::query(&format!("DROP SCHEMA IF EXISTS {schema} CASCADE"))
                    .execute(&pool)
                    .await;
            });
        });
        let _ = joined.join();
    }
}

fn assert_safe_schema(schema: &str) {
    assert!(
        !schema.is_empty()
            && schema
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_'),
        "schema name {schema}"
    );
}

async fn private_catalogue_pool(url: &str) -> (sqlx::PgPool, String) {
    private_catalogue_pool_sized(url, 1).await
}

async fn private_catalogue_pool_sized(url: &str, max_connections: u32) -> (sqlx::PgPool, String) {
    let schema = format!("w2a_{}", uuid::Uuid::new_v4().simple());
    assert_safe_schema(&schema);
    let admin = sqlx::postgres::PgPoolOptions::new()
        .max_connections(1)
        .connect(url)
        .await
        .expect("catalogue admin connection");
    sqlx::query(&format!("CREATE SCHEMA {schema}"))
        .execute(&admin)
        .await
        .expect("create catalogue schema");
    admin.close().await;
    let search_path = schema.clone();
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(max_connections)
        .after_connect(move |conn, _| {
            let search_path = search_path.clone();
            Box::pin(async move {
                sqlx::query(&format!("SET search_path TO {search_path}"))
                    .execute(&mut *conn)
                    .await?;
                Ok(())
            })
        })
        .connect(url)
        .await
        .expect("catalogue pool");
    (pool, schema)
}

async fn catalogue_snapshot(pool: &PgPool) -> Vec<(String, bool, Option<String>)> {
    let rows = sqlx::query(
        r#"
        SELECT rule_id, enabled, detail::text AS detail
        FROM fdd_rule_registry
        ORDER BY rule_id
        "#,
    )
    .fetch_all(pool)
    .await
    .expect("catalogue snapshot");
    rows.into_iter()
        .map(|row| {
            (
                row.get::<String, _>("rule_id"),
                row.get::<bool, _>("enabled"),
                row.get::<Option<String>, _>("detail"),
            )
        })
        .collect()
}

fn tunable_rule(pack: &fdd_rules::RuleRegistry) -> (&fdd_rules::RuleSpec, String, f64) {
    let rule = pack
        .rules
        .iter()
        .find(|rule| !rule.parameters.is_empty())
        .expect("pack has a tunable rule");
    let mut keys: Vec<&String> = rule.parameters.keys().collect();
    keys.sort();
    let key = keys[0].clone();
    let def = &rule.parameters[&key];
    let value = if (def.min - def.default).abs() > f64::EPSILON {
        def.min
    } else {
        def.max
    };
    (rule, key, value)
}

async fn set_overrides(pool: &PgPool, rule_id: &str, overrides: &serde_json::Map<String, Value>) {
    let updated = sqlx::query(
        r#"
        UPDATE fdd_rule_registry
        SET detail = jsonb_set(COALESCE(detail, '{}'::jsonb), '{overrides}', $2::jsonb, true)
        WHERE rule_id = $1
        "#,
    )
    .bind(rule_id)
    .bind(Value::Object(overrides.clone()))
    .execute(pool)
    .await
    .expect("write overrides");
    assert_eq!(updated.rows_affected(), 1, "override target {rule_id}");
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_SQL_ROOT while the catalogue fixture is connected"
)]
async fn catalogue_startup_reconciles_fresh_upgraded_override_and_series() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _lock = crate::test_env_lock::lock_env();
    let pack = fdd_rules::load_registry(&crate::timescale_product::sql_root_for_registry())
        .expect("canonical rule pack");
    assert!(!pack.rules.is_empty(), "pack has rules");
    let (tunable, param_key, edited) = tunable_rule(&pack);
    let tunable_id = tunable.rule_id.clone();
    let plotted = pack
        .rules
        .iter()
        .find(|rule| !rule.required_roles.is_empty() || !rule.optional_roles.is_empty())
        .expect("plotted rule");
    let plotted_id = plotted.rule_id.clone();

    let (pool, schema) = private_catalogue_pool(&url).await;
    let _schema = SchemaDrop {
        url: url.clone(),
        schema,
    };
    let tsdb = fdd_tsdb::Tsdb::from_pool(pool.clone());

    let fresh_version = crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb)
        .await
        .expect("fresh startup");
    let listed = crate::timescale_analytics::fdd_registry(&tsdb)
        .await
        .expect("fresh api list");
    assert_eq!(listed["ok"], json!(true), "{listed}");
    assert_eq!(listed["catalogue_version"], json!(fresh_version));
    let fresh_rules = listed["rules"].as_array().expect("rules");
    assert_eq!(fresh_rules.len(), pack.rules.len(), "{listed}");
    assert_eq!(listed["count"], json!(pack.rules.len()));
    assert!(fresh_rules.iter().all(|row| {
        row["enabled"] == json!(true)
            && row["removed"] == json!(false)
            && row["overrides"]
                .as_object()
                .is_some_and(|obj| obj.is_empty())
    }));
    let fresh_snap = catalogue_snapshot(&pool).await;
    let repeated = crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb)
        .await
        .expect("repeated startup");
    assert_eq!(repeated, fresh_version);
    assert_eq!(catalogue_snapshot(&pool).await, fresh_snap);

    sqlx::query("DROP TABLE fdd_rule_registry")
        .execute(&pool)
        .await
        .expect("drop catalogue");
    sqlx::query("DROP TABLE seed_meta")
        .execute(&pool)
        .await
        .expect("drop version");
    crate::test_ddl::execute_idempotent_ddl(
        &pool,
        r#"
        CREATE TABLE fdd_rule_registry (
          rule_id text PRIMARY KEY,
          sql_file text NOT NULL,
          title text,
          enabled boolean NOT NULL DEFAULT true
        )
        "#,
    )
    .await;
    sqlx::query(
        r#"
        INSERT INTO fdd_rule_registry (rule_id, sql_file, title, enabled)
        VALUES ($1, 'previous.sql', 'previous title', false)
        "#,
    )
    .bind(&tunable_id)
    .execute(&pool)
    .await
    .expect("upgraded row");

    let upgraded_version = crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb)
        .await
        .expect("upgraded startup");
    assert_ne!(upgraded_version, "");
    let upgraded = crate::timescale_analytics::fdd_registry(&tsdb)
        .await
        .expect("upgraded list");
    let upgraded_rules = upgraded["rules"].as_array().expect("rules");
    assert_eq!(upgraded_rules.len(), pack.rules.len());
    let disabled = upgraded_rules
        .iter()
        .find(|row| row["rule_id"] == json!(tunable_id))
        .expect("disabled rule remains listed");
    assert_eq!(disabled["enabled"], json!(false), "{disabled}");
    assert_eq!(
        disabled["description"].as_str(),
        Some(tunable.description.as_str())
    );

    let mut overrides = serde_json::Map::new();
    open_fdd_edge_prototype::fdd::registry_api::edit_rule_override(
        tunable,
        &mut overrides,
        &param_key,
        edited,
    )
    .expect("tuner edit");
    set_overrides(&pool, &tunable_id, &overrides).await;
    sqlx::query(
        r#"
        INSERT INTO fdd_rule_registry (rule_id, sql_file, title, enabled, detail)
        VALUES ($1, 'retired.sql', 'retired', true, $2::jsonb)
        "#,
    )
    .bind("W2A-RETIRED")
    .bind(json!({
        "catalogue_source": "pack",
        "pack_version": "previous",
        "removed": false,
        "overrides": {},
    }))
    .execute(&pool)
    .await
    .expect("retired pack rule");
    sqlx::query(
        r#"
        INSERT INTO fdd_rule_registry (rule_id, sql_file, title, enabled)
        VALUES ('W2A-LOCAL', 'local.sql', 'local', true)
        "#,
    )
    .execute(&pool)
    .await
    .expect("operator row");

    crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb)
        .await
        .expect("reconcile after edit");
    let edited_list = crate::timescale_analytics::fdd_registry(&tsdb)
        .await
        .expect("list after edit");
    let edited_rules = edited_list["rules"].as_array().expect("rules");
    assert_eq!(edited_rules.len(), pack.rules.len() + 1, "{edited_list}");
    let tuned = edited_rules
        .iter()
        .find(|row| row["rule_id"] == json!(tunable_id))
        .expect("tuned rule");
    assert_eq!(tuned["enabled"], json!(false));
    assert_eq!(
        tuned["overrides"][&param_key].as_f64(),
        Some(edited),
        "{tuned}"
    );
    assert!(edited_rules
        .iter()
        .all(|row| row["rule_id"] != "W2A-RETIRED"));
    assert!(edited_rules.iter().any(|row| row["rule_id"] == "W2A-LOCAL"));
    let retired: bool = sqlx::query_scalar(
        r#"SELECT COALESCE(detail->>'removed', 'false') = 'true' FROM fdd_rule_registry WHERE rule_id = 'W2A-RETIRED'"#,
    )
    .fetch_one(&pool)
    .await
    .expect("retired flag");
    assert!(retired, "removed pack rule stays in the table");
    let retired_enabled: bool =
        sqlx::query_scalar("SELECT enabled FROM fdd_rule_registry WHERE rule_id = 'W2A-RETIRED'")
            .fetch_one(&pool)
            .await
            .expect("retired enabled");
    assert!(retired_enabled, "removal does not rewrite enabled");

    let after_edit = catalogue_snapshot(&pool).await;
    crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb)
        .await
        .expect("startup again");
    assert_eq!(catalogue_snapshot(&pool).await, after_edit);

    open_fdd_edge_prototype::fdd::registry_api::restore_catalogue_overrides(&mut overrides);
    assert!(overrides.is_empty());
    set_overrides(&pool, &tunable_id, &overrides).await;
    let restored = crate::timescale_analytics::fdd_registry(&tsdb)
        .await
        .expect("list after restore");
    let restored_row = restored["rules"]
        .as_array()
        .expect("rules")
        .iter()
        .find(|row| row["rule_id"] == json!(tunable_id))
        .expect("restored rule");
    assert!(restored_row["overrides"]
        .as_object()
        .is_some_and(|obj| obj.is_empty()));
    assert_eq!(restored_row["enabled"], json!(false));

    let site = format!("cat{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
    let equipment = format!("eq{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
    crate::test_ddl::execute_idempotent_ddl(
        &pool,
        r#"
        CREATE TABLE fdd_run (
          run_id bigserial PRIMARY KEY,
          site_id text NOT NULL,
          equipment_id text NOT NULL,
          rule_id text NOT NULL,
          window_start timestamptz NOT NULL,
          window_end timestamptz NOT NULL,
          status text NOT NULL
        )
        "#,
    )
    .await;
    let before_run: bool = sqlx::query_scalar(
        "SELECT EXISTS (SELECT 1 FROM fdd_run WHERE site_id = $1 AND rule_id = $2)",
    )
    .bind(&site)
    .bind(&plotted_id)
    .fetch_one(&pool)
    .await
    .expect("run lookup");
    assert!(!before_run);
    let plotted_row = restored["rules"]
        .as_array()
        .expect("rules")
        .iter()
        .find(|row| row["rule_id"] == json!(plotted_id))
        .expect("plotted catalogue row");
    let required = json_strings(&plotted_row["required_roles"]);
    let optional = json_strings(&plotted_row["optional_roles"]);
    let unavailable = open_fdd_edge_prototype::fdd::registry_api::series_roles_after_run(
        before_run, false, &required, &optional,
    );
    assert!(
        unavailable
            .as_ref()
            .is_err_and(|err| err.contains("unavailable")),
        "{unavailable:?}"
    );
    sqlx::query(
        r#"
        INSERT INTO fdd_run (site_id, equipment_id, rule_id, window_start, window_end, status)
        VALUES ($1, $2, $3, now(), now() + interval '1 hour', 'ok')
        "#,
    )
    .bind(&site)
    .bind(&equipment)
    .bind(&plotted_id)
    .execute(&pool)
    .await
    .expect("record run");
    let after_run: bool = sqlx::query_scalar(
        "SELECT EXISTS (SELECT 1 FROM fdd_run WHERE site_id = $1 AND rule_id = $2)",
    )
    .bind(&site)
    .bind(&plotted_id)
    .fetch_one(&pool)
    .await
    .expect("run present");
    let selected = open_fdd_edge_prototype::fdd::registry_api::series_roles_after_run(
        after_run,
        plotted_row["removed"].as_bool().expect("removed flag"),
        &required,
        &optional,
    )
    .expect("series after run");
    let spec = pack
        .rules
        .iter()
        .find(|rule| rule.rule_id == plotted_id)
        .expect("plotted spec");
    let from_pack = open_fdd_edge_prototype::fdd::registry_api::series_roles_after_run(
        true,
        false,
        &spec.required_roles,
        &spec.optional_roles,
    )
    .expect("pack series");
    assert_eq!(selected, from_pack);
    assert!(!selected.is_empty());
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_SQL_ROOT while concurrent catalogue startups share one database"
)]
async fn catalogue_repeated_startup_and_concurrent_lists_do_not_duplicate() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _lock = crate::test_env_lock::lock_env();
    let pack = fdd_rules::load_registry(&crate::timescale_product::sql_root_for_registry())
        .expect("canonical rule pack");
    let (pool, schema) = private_catalogue_pool_sized(&url, 4).await;
    let _schema = SchemaDrop {
        url: url.clone(),
        schema,
    };
    let tsdb = fdd_tsdb::Tsdb::from_pool(pool.clone());

    let (first, second) = tokio::join!(
        crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb),
        crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb),
    );
    let first = first.expect("concurrent startup");
    let second = second.expect("concurrent startup peer");
    assert_eq!(first, second);
    let listed = crate::timescale_analytics::fdd_registry(&tsdb)
        .await
        .expect("list after concurrent startup");
    assert_eq!(listed["count"], json!(pack.rules.len()), "{listed}");
    let rows: i64 = sqlx::query_scalar("SELECT count(*)::bigint FROM fdd_rule_registry")
        .fetch_one(&pool)
        .await
        .expect("row count");
    let distinct: i64 =
        sqlx::query_scalar("SELECT count(DISTINCT rule_id)::bigint FROM fdd_rule_registry")
            .fetch_one(&pool)
            .await
            .expect("distinct rules");
    assert_eq!(
        rows, distinct,
        "catalogue primary key kept one row per rule"
    );
    assert_eq!(rows as usize, pack.rules.len());

    let snap = catalogue_snapshot(&pool).await;
    let again = crate::timescale_analytics::reconcile_catalogue_on_startup_with(&tsdb)
        .await
        .expect("repeated startup");
    assert_eq!(again, first);
    assert_eq!(catalogue_snapshot(&pool).await, snap);

    let stamp = catalogue_version_stamp(&pool).await;
    let (left, right) = tokio::join!(
        crate::timescale_analytics::fdd_registry(&tsdb),
        crate::timescale_analytics::fdd_registry(&tsdb),
    );
    let left = left.expect("concurrent list");
    let right = right.expect("concurrent list peer");
    assert_eq!(left["count"], json!(pack.rules.len()));
    assert_eq!(right["count"], json!(pack.rules.len()));
    assert_eq!(left["catalogue_version"], json!(first));
    assert_eq!(catalogue_snapshot(&pool).await, snap);
    assert_eq!(
        catalogue_version_stamp(&pool).await,
        stamp,
        "a current catalogue list must not rewrite rows"
    );
    let held: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint FROM pg_locks WHERE locktype = 'advisory' AND classid = 0 AND objid = 4040530042",
    )
    .fetch_one(&pool)
    .await
    .expect("advisory locks");
    assert_eq!(held, 0, "catalogue lock is transaction scoped");
}

async fn catalogue_version_stamp(pool: &PgPool) -> (String, String) {
    let row = sqlx::query(
        "SELECT value, updated_at::text AS updated_at FROM seed_meta WHERE key = 'fdd_rule_catalogue_version'",
    )
    .fetch_one(pool)
    .await
    .expect("catalogue version stamp");
    (row.get("value"), row.get("updated_at"))
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_SQL_ROOT while the catalogue fixture is connected"
)]
async fn catalogue_api_lists_pack_and_fails_when_unavailable() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _lock = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
    let _database = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
    let _jwt = EnvGuard::unset("OPENFDD_JWT_SECRET");
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    let _shared_pool = SharedPoolReset::arm();

    let pool = PgPoolOptions::new()
        .max_connections(1)
        .connect(&url)
        .await
        .expect("api catalogue postgres");
    apply_registry_schema(&pool).await;
    let state = Arc::new(AppState::new());
    let app = crate::routes::router(state);
    let body = get_json(&app, "/api/fdd/rules").await;
    assert_eq!(body["ok"], json!(true), "{body}");
    let pack = fdd_rules::load_registry(&crate::timescale_product::sql_root_for_registry())
        .expect("canonical rule pack");
    let listed = body["rules"].as_array().expect("rules");
    for spec in &pack.rules {
        let row = listed
            .iter()
            .find(|row| row["rule_id"].as_str() == Some(spec.rule_id.as_str()))
            .unwrap_or_else(|| panic!("api list missing {}", spec.rule_id));
        assert_eq!(row["description"].as_str(), Some(spec.description.as_str()));
        assert_eq!(row["removed"], json!(false));
    }
    let pack_rows = listed
        .iter()
        .filter(|row| {
            pack.rules
                .iter()
                .any(|spec| row["rule_id"].as_str() == Some(spec.rule_id.as_str()))
        })
        .count();
    assert_eq!(pack_rows, pack.rules.len());
    assert!(body["catalogue_version"]
        .as_str()
        .is_some_and(|version| !version.is_empty()));

    let missing = tempfile::tempdir().expect("missing pack");
    let _root = EnvGuard::set(
        "OPENFDD_SQL_ROOT",
        missing.path().to_str().expect("temp path"),
    );
    fdd_tsdb::clear_shared_pool();
    let broken = get_json(&app, "/api/fdd/rules").await;
    assert_eq!(broken["ok"], json!(false), "{broken}");
    assert!(
        broken["error"]
            .as_str()
            .is_some_and(|msg| msg.contains("unavailable")),
        "{broken}"
    );
    let broken_rules = broken.get("rules").cloned().unwrap_or(json!([]));
    assert_eq!(broken_rules, json!([]), "{broken}");

    std::fs::write(missing.path().join("registry.yaml"), "rules: []").expect("empty pack");
    fdd_tsdb::clear_shared_pool();
    let empty = get_json(&app, "/api/fdd/rules").await;
    assert_eq!(empty["ok"], json!(false), "{empty}");
    assert!(
        empty["error"]
            .as_str()
            .is_some_and(|msg| msg.contains("unavailable") && msg.contains("no rules")),
        "{empty}"
    );
}
