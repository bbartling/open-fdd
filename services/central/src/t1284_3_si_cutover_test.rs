//! T1284-3 (CI, Postgres): SI cutover dry-run, idempotency, token gate, authz.

use chrono::{TimeZone, Utc};
use fdd_tsdb::{
    apply_sample_cutover_tx, dry_run_site, ensure_si_cutover_schema, invalidate_derived_results,
    SampleRow, Tsdb, UpsertBatch, QUALITY_UNIT_UNDECLARED,
};
use sqlx::postgres::PgPoolOptions;

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
    for sql in include_str!("../../../sql/schema/11_point_map_binding_metadata.sql").split(';') {
        let stmt = sql.trim();
        if !stmt.is_empty() {
            crate::test_ddl::execute_idempotent_ddl(pool, stmt).await;
        }
    }
    fdd_tsdb::ensure_si_cutover_schema(pool)
        .await
        .expect("si cutover schema");
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

#[tokio::test]
async fn t1284_3_dry_run_rows_match_conversion_and_rerun_zero() {
    let Some(pool) = pool().await else {
        return;
    };
    schema(&pool).await;
    let site = format!("T1284_3_{}", uuid::Uuid::new_v4().simple());
    let ts = Utc.with_ymd_and_hms(2026, 7, 1, 0, 0, 0).unwrap();
    sqlx::query("INSERT INTO site (site_id, dis) VALUES ($1, $1) ON CONFLICT DO NOTHING")
        .bind(&site)
        .execute(&pool)
        .await
        .expect("site");
    sqlx::query(
        r#"
        INSERT INTO point_map (site_id, openfdd_key, haystack_id, role, unit, quantity)
        VALUES ($1, $2, 'h1', 'oa_t', 'degF', 'absolute_temperature')
        "#,
    )
    .bind(&site)
    .bind(format!("{site}.AHU.oa_t"))
    .execute(&pool)
    .await
    .expect("point_map");
    let tsdb = Tsdb::from_pool(pool.clone());
    let mut batch = UpsertBatch::default();
    batch.push(sample(
        &site,
        &format!("{site}.AHU.oa_t"),
        "AHU",
        "oa_t",
        ts,
        50.0,
        "degF",
    ));
    tsdb.upsert_samples(&batch).await.expect("upsert");

    let dry = dry_run_site(&pool, &site, 0).await.expect("dry-run");
    assert_eq!(dry.rows_to_convert, 1, "{dry:?}");

    let mut tx = pool.begin().await.expect("tx");
    let first = apply_sample_cutover_tx(&mut tx, &dry)
        .await
        .expect("cutover");
    invalidate_derived_results(&mut tx, &site)
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
