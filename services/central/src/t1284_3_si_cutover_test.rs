//! T1284-3 (CI, Postgres): SI cutover dry-run, idempotency, token gate, authz.

use chrono::{TimeZone, Utc};
use fdd_tsdb::{
    apply_sample_cutover_tx, dry_run_site, invalidate_derived_results_tx, SampleRow, Tsdb,
    UpsertBatch, QUALITY_UNIT_UNDECLARED,
};
use sqlx::postgres::PgPoolOptions;
use tokio::sync::OnceCell;

async fn pool() -> Option<sqlx::PgPool> {
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
        .ok()
        .filter(|v| !v.trim().is_empty())?;
    PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .ok()
}

async fn schema(pool: &sqlx::PgPool) {
    crate::portal_inventory_fixtures::apply_schema(pool).await;
    // 12_si_cutover.sql alters the derived-result tables, so they must exist first.
    static DERIVED: OnceCell<()> = OnceCell::const_new();
    DERIVED
        .get_or_init(|| async {
            for blob in [
                include_str!("../../../sql/schema/01_bps_core.sql"),
                include_str!("../../../sql/schema/02_openfdd_dims.sql"),
                include_str!("../../../sql/schema/08_analytics_result_cache.sql"),
                include_str!("../../../sql/schema/10_incremental_fdd.sql"),
            ] {
                for sql in blob.split(';') {
                    let stmt = sql.trim();
                    if !stmt.is_empty() {
                        crate::test_ddl::execute_idempotent_ddl(pool, stmt).await;
                    }
                }
            }
        })
        .await;
    for sql in include_str!("../../../sql/schema/11_point_map_binding_metadata.sql").split(';') {
        let stmt = sql.trim();
        if !stmt.is_empty() {
            crate::test_ddl::execute_idempotent_ddl(pool, stmt).await;
        }
    }
    fdd_tsdb::ensure_si_cutover_schema(pool)
        .await
        .expect("si cutover schema");
    for sql in include_str!("../../../sql/schema/09_data_revision.sql").split(';') {
        let stmt = sql.trim();
        if !stmt.is_empty() {
            crate::test_ddl::execute_idempotent_ddl(pool, stmt).await;
        }
    }
}

async fn schema_with_fdd_tables(pool: &sqlx::PgPool) {
    schema(pool).await;
}

async fn superseded_counts(pool: &sqlx::PgPool, site: &str, rev: i64) -> (i64, i64, i64) {
    let q = |sql: &'static str| {
        let site = site.to_string();
        async move {
            let n: i64 = sqlx::query_scalar(sql)
                .bind(site)
                .bind(rev)
                .fetch_one(pool)
                .await
                .expect("superseded count");
            n
        }
    };
    (
        q("SELECT count(*) FROM fdd_run WHERE site_id = $1 AND superseded_by_revision = $2").await,
        q("SELECT count(*) FROM fdd_interval_result WHERE site_id = $1 AND superseded_by_revision = $2").await,
        q("SELECT count(*) FROM analytics_result WHERE building_id = $1 AND superseded_by_revision = $2 AND stale IS TRUE").await,
    )
}

fn sample(
    site: &str,
    key: &str,
    equip: &str,
    role: &str,
    ts: chrono::DateTime<Utc>,
    val: f64,
    unit: &str,
) -> SampleRow {
    let mut row = SampleRow::new(ts, site, key, Some(val));
    row.equipment_id = Some(equip.into());
    row.role = Some(role.into());
    row.unit = Some(unit.into());
    row
}

async fn derived_row_counts(pool: &sqlx::PgPool, site: &str) -> (i64, i64, i64) {
    let runs: i64 = sqlx::query_scalar("SELECT count(*) FROM fdd_run WHERE site_id = $1")
        .bind(site)
        .fetch_one(pool)
        .await
        .expect("fdd_run count");
    let intervals: i64 =
        sqlx::query_scalar("SELECT count(*) FROM fdd_interval_result WHERE site_id = $1")
            .bind(site)
            .fetch_one(pool)
            .await
            .expect("fdd_interval_result count");
    let cache: i64 =
        sqlx::query_scalar("SELECT count(*) FROM analytics_result WHERE building_id = $1")
            .bind(site)
            .fetch_one(pool)
            .await
            .expect("analytics_result count");
    (runs, intervals, cache)
}

async fn seed_convertible_site(pool: &sqlx::PgPool, site: &str) {
    let ts = Utc.with_ymd_and_hms(2026, 7, 1, 0, 0, 0).unwrap();
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(site)
        .execute(pool)
        .await
        .expect("site");
    sqlx::query(
        r#"
        INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, unit, quantity)
        VALUES ($1, $2, 'h1', 'oa_t', 'degF', 'absolute_temperature')
        "#,
    )
    .bind(site)
    .bind(format!("{site}.AHU.oa_t"))
    .execute(pool)
    .await
    .expect("point_map");
    let tsdb = Tsdb::from_pool(pool.clone());
    let mut batch = UpsertBatch::default();
    batch.push(sample(
        site,
        &format!("{site}.AHU.oa_t"),
        "AHU",
        "oa_t",
        ts,
        50.0,
        "degF",
    ));
    tsdb.upsert_samples(&batch).await.expect("upsert");
}

async fn clear_cutover_token(pool: &sqlx::PgPool) {
    sqlx::query("DELETE FROM seed_meta WHERE key = 'si_cutover_token'")
        .execute(pool)
        .await
        .expect("clear token");
}

#[tokio::test]
async fn t1284_3_dry_run_rows_match_conversion_and_rerun_zero() {
    let Some(pool) = pool().await else {
        return;
    };
    schema(&pool).await;
    let site = format!("T1284_3_{}", uuid::Uuid::new_v4().simple());
    seed_convertible_site(&pool, &site).await;

    let dry = dry_run_site(&pool, &site, 0).await.expect("dry-run");
    assert_eq!(dry.rows_to_convert, 1, "{dry:?}");

    let mut tx = pool.begin().await.expect("tx");
    let first = apply_sample_cutover_tx(&mut tx, &dry)
        .await
        .expect("cutover");
    invalidate_derived_results_tx(&mut tx, &site)
        .await
        .expect("invalidate");
    tx.commit().await.expect("commit");
    assert_eq!(first.rows_converted, 1);

    let val: f64 = sqlx::query_scalar("SELECT val FROM sample WHERE site_id = $1 LIMIT 1")
        .bind(&site)
        .fetch_one(&pool)
        .await
        .expect("val");
    assert!((val - 10.0).abs() < 1e-6, "50°F → 10°C, got {val}");

    let dry2 = dry_run_site(&pool, &site, 0).await.expect("dry-run2");
    assert_eq!(dry2.rows_to_convert, 0);
    let mut tx2 = pool.begin().await.expect("tx2");
    let second = apply_sample_cutover_tx(&mut tx2, &dry2)
        .await
        .expect("cutover2");
    tx2.commit().await.expect("commit2");
    assert_eq!(second.rows_converted, 0);
}

#[tokio::test]
async fn t1284_3_cutover_does_not_delete_derived_rows_marks_cache_stale() {
    let Some(pool) = pool().await else {
        return;
    };
    schema_with_fdd_tables(&pool).await;
    let site = format!("T1284_3D_{}", uuid::Uuid::new_v4().simple());
    seed_convertible_site(&pool, &site).await;
    let ts = Utc.with_ymd_and_hms(2026, 7, 1, 0, 0, 0).unwrap();
    sqlx::query(
        "INSERT INTO fdd_run (site_id, equipment_id, rule_id, window_start, window_end, status)
         VALUES ($1, 'AHU', 'FC1', $2, $2 + interval '1 hour', 'ok')",
    )
    .bind(&site)
    .bind(ts)
    .execute(&pool)
    .await
    .expect("fdd_run");
    sqlx::query(
        "INSERT INTO fdd_interval_result
           (site_id, rule_id, equipment_id, scope_digest, bucket_start, bucket_end,
            fault_seconds, covered_seconds, sample_count, data_revision, fence)
         VALUES ($1, 'FC1', 'AHU', md5('scope'), $2, $2 + interval '15 minutes',
                 0, 900, 1, 1, 1)",
    )
    .bind(&site)
    .bind(ts)
    .execute(&pool)
    .await
    .expect("fdd_interval_result");
    sqlx::query(
        "INSERT INTO analytics_result
            (building_id, query_id, query_version, window_key, config_hash, stale, payload)
         VALUES ($1, 'equipment-inspect', 'equipment-inspect-v1', 'all', 'fixture', false, '{}'::jsonb)",
    )
    .bind(&site)
    .execute(&pool)
    .await
    .expect("analytics_result");

    let before = derived_row_counts(&pool, &site).await;
    assert_eq!(before, (1, 1, 1));

    let dry = dry_run_site(&pool, &site, 0).await.expect("dry-run");
    let mut tx = pool.begin().await.expect("tx");
    apply_sample_cutover_tx(&mut tx, &dry)
        .await
        .expect("cutover");
    invalidate_derived_results_tx(&mut tx, &site)
        .await
        .expect("invalidate");
    tx.commit().await.expect("commit");

    let after = derived_row_counts(&pool, &site).await;
    assert_eq!(
        after, before,
        "fdd_run / interval / analytics rows must remain"
    );

    let revision: i64 = sqlx::query_scalar("SELECT revision FROM data_revision WHERE site_id = $1")
        .bind(&site)
        .fetch_one(&pool)
        .await
        .expect("data_revision");
    assert!(revision >= 1, "sample cutover must bump data_revision");
    assert_eq!(
        superseded_counts(&pool, &site, revision).await,
        (1, 1, 1),
        "every derived row must be invalidated by the cutover revision"
    );

    // Re-invalidating is idempotent: no row count change, no re-stamp.
    let mut tx = pool.begin().await.expect("tx2");
    let again = invalidate_derived_results_tx(&mut tx, &site)
        .await
        .expect("invalidate2")
        .expect("revision present");
    tx.commit().await.expect("commit2");
    assert_eq!(
        (again.fdd_runs, again.fdd_intervals, again.analytics_results),
        (0, 0, 0)
    );
    assert_eq!(derived_row_counts(&pool, &site).await, before);
}

#[tokio::test]
async fn t1284_3_delta_param_rename_map_scale_only() {
    let contract = fdd_core::MetricUnitsContract::load_embedded().expect("contract");
    let got = contract
        .convert_to_canonical("temperature_difference", 9.0, "degF_delta")
        .expect("delta");
    assert!((got - 5.0).abs() < 1e-6, "9 Δ°F → 5 Δ°C, got {got}");
}

#[tokio::test]
async fn t1284_3_unresolved_series_blocks_cutover() {
    let Some(pool) = pool().await else {
        return;
    };
    schema(&pool).await;
    let site = format!("T1284_3U_{}", uuid::Uuid::new_v4().simple());
    let ts = Utc.with_ymd_and_hms(2026, 7, 2, 0, 0, 0).unwrap();
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&site)
        .execute(&pool)
        .await
        .expect("site");
    sqlx::query(
        r#"
        INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, quantity)
        VALUES ($1, $2, 'h1', 'oa_t', 'absolute_temperature')
        "#,
    )
    .bind(&site)
    .bind(format!("{site}.AHU.oa_t"))
    .execute(&pool)
    .await
    .expect("point_map");
    let tsdb = Tsdb::from_pool(pool.clone());
    let mut batch = UpsertBatch::default();
    let mut row = sample(
        &site,
        &format!("{site}.AHU.oa_t"),
        "AHU",
        "oa_t",
        ts,
        50.0,
        "degF",
    );
    row.quality = Some(QUALITY_UNIT_UNDECLARED.into());
    batch.push(row);
    tsdb.upsert_samples(&batch).await.expect("upsert");

    let dry = dry_run_site(&pool, &site, 0).await.expect("dry-run");
    assert!(!dry.unresolved_series.is_empty());
    let mut tx = pool.begin().await.expect("tx");
    let err = apply_sample_cutover_tx(&mut tx, &dry).await.unwrap_err();
    assert!(matches!(
        err,
        fdd_tsdb::SiCutoverError::UnresolvedSeries { .. }
    ));
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize workspace env with other admin route tests"
)]
async fn t1284_3_viewer_gets_403_on_dry_run_route() {
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    let _env_lock = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("tempdir");
    let _workspace = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let mut state = crate::state::AppState::new();
    state.auth = crate::auth::AuthConfig {
        secret: Some("t1284-3-si-cutover-viewer-deny".into()),
        admin_password: None,
        agent_password: None,
        viewer_password: None,
        viewer_tenant_ids: Vec::new(),
    };
    let state = std::sync::Arc::new(state);
    let app = crate::routes::router(std::sync::Arc::clone(&state));
    let viewer = state
        .auth
        .issue_token_with_tenants("viewer-cutover", crate::auth::Role::Viewer, 60, &[])
        .expect("token");
    let req = Request::builder()
        .uri("/api/admin/si-cutover/dry-run")
        .header("authorization", format!("Bearer {viewer}"))
        .body(Body::empty())
        .expect("request");
    let resp = app.oneshot(req).await.expect("response");
    assert_eq!(resp.status(), StatusCode::FORBIDDEN);
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL with other Timescale admin tests"
)]
async fn t1284_3_post_token_single_use_confirm_and_authz() {
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use axum::Router;
    use serde_json::json;
    use tower::ServiceExt;

    let Some(pool) = pool().await else {
        return;
    };
    let _env_lock = crate::test_env_lock::lock_env();
    let url = std::env::var("OPENFDD_TEST_DATABASE_URL").expect("db url");
    std::env::set_var("OPENFDD_DATABASE_URL", &url);
    std::env::set_var("OPENFDD_HISTORIAN", "timescale");
    const TOKEN: &str = "t1284-3-cutover-token-fixture";
    std::env::set_var("OPENFDD_SI_CUTOVER_TOKEN", TOKEN);
    fdd_tsdb::clear_shared_pool();

    schema(&pool).await;
    let site = format!("T1284_3P_{}", uuid::Uuid::new_v4().simple());
    seed_convertible_site(&pool, &site).await;
    clear_cutover_token(&pool).await;

    let workspace = tempfile::tempdir().expect("tempdir");
    let _workspace = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let mut state = crate::state::AppState::new();
    state.auth = crate::auth::AuthConfig {
        secret: Some("t1284-3-si-cutover-post-auth".into()),
        admin_password: None,
        agent_password: None,
        viewer_password: None,
        viewer_tenant_ids: Vec::new(),
    };
    let state = std::sync::Arc::new(state);
    let app = crate::routes::router(std::sync::Arc::clone(&state));
    let hub = state
        .auth
        .issue_token_with_tenants("hub-cutover", crate::auth::Role::Admin, 600, &[])
        .expect("hub");
    let viewer = state
        .auth
        .issue_token_with_tenants("viewer-cutover-post", crate::auth::Role::Viewer, 600, &[])
        .expect("viewer");

    async fn post_json(
        app: &Router,
        token: &str,
        body: serde_json::Value,
    ) -> (StatusCode, serde_json::Value) {
        let req = Request::builder()
            .method("POST")
            .uri("/api/admin/si-cutover")
            .header("authorization", format!("Bearer {token}"))
            .header("content-type", "application/json")
            .body(Body::from(body.to_string()))
            .expect("request");
        let resp = app.clone().oneshot(req).await.expect("response");
        let status = resp.status();
        let bytes = axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .expect("body");
        let parsed: serde_json::Value = serde_json::from_slice(&bytes)
            .unwrap_or(json!({ "raw": String::from_utf8_lossy(&bytes) }));
        (status, parsed)
    }

    let (status, body) = post_json(
        &app,
        &viewer,
        json!({"confirm": true, "token": TOKEN, "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{body}");

    let (status, body) = post_json(
        &app,
        &hub,
        json!({"confirm": false, "token": TOKEN, "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(status, StatusCode::BAD_REQUEST, "{body}");

    let (status, body) = post_json(
        &app,
        &hub,
        json!({"token": TOKEN, "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(
        status,
        StatusCode::UNPROCESSABLE_ENTITY,
        "missing confirm: {body}"
    );

    let (status, body) = post_json(
        &app,
        &hub,
        json!({"confirm": true, "token": "wrong-token", "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{body}");

    let (status, body) = post_json(
        &app,
        &hub,
        json!({"confirm": true, "token": "", "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "empty token: {body}");

    let unchanged = dry_run_site(&pool, &site, 0)
        .await
        .expect("dry-run after rejected posts");
    assert_eq!(
        unchanged.rows_to_convert, 1,
        "rejected posts must not convert"
    );

    let (status, body) = post_json(
        &app,
        &hub,
        json!({"confirm": true, "token": TOKEN, "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["ok"], true);
    assert_eq!(body["sites"][0]["rows_converted"], 1);

    let (status, body) = post_json(
        &app,
        &hub,
        json!({"confirm": true, "token": TOKEN, "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT, "{body}");
    assert_eq!(body["ok"], false);
    assert_eq!(body["error"], "cutover token already used");

    let (status, body) = post_json(
        &app,
        &viewer,
        json!({"confirm": true, "token": TOKEN, "site_ids": [site.clone()]}),
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "viewer after use: {body}");

    let dry2 = dry_run_site(&pool, &site, 0)
        .await
        .expect("dry-run after post");
    assert_eq!(dry2.rows_to_convert, 0);
}
