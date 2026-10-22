//! Site deletion shared by admin user cascade and dataset delete.
//!
//! The HTTP handlers stay in `routes`. This module purges Timescale, the
//! workspace dataset, and linked jobs. User cascade purges only sites that no
//! remaining account can reach. A second purge of an already-empty site
//! succeeds and deletes nothing.

use std::path::Path;

use serde_json::{json, Value};

use crate::admin_cp::{plan_user_cascade_delete, UserCascadePlan};
use crate::tenant::ControlPlane;
use crate::user_store::UserStore;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SitePurgeReport {
    pub building_id: String,
    pub jobs_deleted: usize,
    pub timescale_rows_deleted: u64,
}

impl SitePurgeReport {
    pub fn to_json(&self) -> Value {
        json!({
            "building_id": self.building_id,
            "jobs_deleted": self.jobs_deleted,
            "timescale_rows_deleted": self.timescale_rows_deleted,
        })
    }
}

#[derive(Debug)]
pub struct SitePurgeError {
    pub building_id: String,
    pub message: String,
    pub jobs_deleted: usize,
    pub job_errors: Vec<String>,
    pub timescale_rows_deleted: u64,
}

#[derive(Debug)]
pub struct UserCascadeOutcome {
    pub plan: UserCascadePlan,
    pub purged: Vec<SitePurgeReport>,
}

impl UserCascadeOutcome {
    pub fn purged_json(&self) -> Vec<Value> {
        self.purged.iter().map(SitePurgeReport::to_json).collect()
    }
}

#[derive(Debug)]
pub struct PartialCascade {
    pub plan: UserCascadePlan,
    pub purged: Vec<SitePurgeReport>,
    pub errors: Vec<String>,
}

impl PartialCascade {
    pub fn purged_json(&self) -> Vec<Value> {
        self.purged.iter().map(SitePurgeReport::to_json).collect()
    }
}

#[derive(Debug)]
pub enum UserCascadeError {
    NotFound(String),
    Store(String),
    Partial(Box<PartialCascade>),
}

/// Purge one site from Timescale, the workspace dataset, and linked jobs.
///
/// Missing files, zero historian rows, and no jobs are success. An invalid id
/// fails before any delete.
pub async fn purge_site(building_id: &str) -> Result<SitePurgeReport, SitePurgeError> {
    let id = building_id.trim();
    if !building_id_ok(id) {
        return Err(SitePurgeError {
            building_id: building_id.to_string(),
            message: "invalid building id".into(),
            jobs_deleted: 0,
            job_errors: Vec::new(),
            timescale_rows_deleted: 0,
        });
    }
    let id = id.to_string();
    let timescale_rows_deleted = match purge_historian(&id).await {
        Ok(rows) => rows,
        Err(message) => {
            return Err(SitePurgeError {
                building_id: id,
                message,
                jobs_deleted: 0,
                job_errors: Vec::new(),
                timescale_rows_deleted: 0,
            });
        }
    };
    if let Err(message) = delete_dataset_files(&id).await {
        return Err(SitePurgeError {
            building_id: id,
            message: format!(
                "Timescale purge completed but workspace dataset delete failed: {message}"
            ),
            jobs_deleted: 0,
            job_errors: Vec::new(),
            timescale_rows_deleted,
        });
    }
    let (jobs_deleted, job_errors) = crate::jobs::delete_jobs_for_site(&id);
    if !job_errors.is_empty() {
        let joined = job_errors.join("; ");
        return Err(SitePurgeError {
            building_id: id,
            message: format!("site data purged but job delete failed: {joined}"),
            jobs_deleted,
            job_errors,
            timescale_rows_deleted,
        });
    }
    Ok(SitePurgeReport {
        building_id: id,
        jobs_deleted,
        timescale_rows_deleted,
    })
}

/// Purge sites the user owns alone, then remove the account.
///
/// Shared sites stay. The account stays when any sole-owned purge fails, so a
/// later call can finish the remaining sites without deleting them twice.
pub async fn delete_user_cascade(
    workspace: &Path,
    username: &str,
) -> Result<UserCascadeOutcome, UserCascadeError> {
    let mut store = UserStore::load_or_empty(workspace);
    let plane = ControlPlane::load_or_legacy(workspace);
    let plan =
        plan_user_cascade_delete(&store, &plane, username).map_err(UserCascadeError::NotFound)?;
    let mut purged = Vec::new();
    let mut errors = Vec::new();
    for building_id in &plan.buildings_to_purge {
        match purge_site(building_id).await {
            Ok(report) => purged.push(report),
            Err(err) => errors.push(format!("{}: {}", err.building_id, err.message)),
        }
    }
    if !errors.is_empty() {
        return Err(UserCascadeError::Partial(Box::new(PartialCascade {
            plan,
            purged,
            errors,
        })));
    }
    store.remove(username).map_err(UserCascadeError::NotFound)?;
    store.save(workspace).map_err(UserCascadeError::Store)?;
    Ok(UserCascadeOutcome { plan, purged })
}

fn building_id_ok(id: &str) -> bool {
    !id.is_empty()
        && id
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-')
}

async fn purge_historian(building_id: &str) -> Result<u64, String> {
    match fdd_tsdb::Tsdb::connect_from_env().await {
        Ok(tsdb) => tsdb
            .purge_building(building_id)
            .await
            .map_err(|err| safe_historian_error(&err)),
        Err(fdd_tsdb::TsdbError::MissingDatabaseUrl) => Ok(0),
        Err(err) => Err(safe_historian_error(&err)),
    }
}

fn safe_historian_error(err: &impl std::fmt::Display) -> String {
    let text = err.to_string();
    let lower = text.to_ascii_lowercase();
    if text.contains("://") || lower.contains("password") {
        "historian purge failed".to_string()
    } else {
        text.chars().take(300).collect()
    }
}

async fn delete_dataset_files(building_id: &str) -> Result<(), String> {
    let id = building_id.to_string();
    match tokio::task::spawn_blocking(move || {
        open_fdd_edge_prototype::csv_ingest::delete_dataset(&id)
    })
    .await
    {
        Ok(Ok(())) => Ok(()),
        Ok(Err(err)) => Err(err),
        Err(err) => Err(format!("dataset delete task failed: {err}")),
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use axum::Router;
    use chrono::{Duration as ChronoDuration, Utc};
    use fdd_tsdb::{SampleRow, Tsdb, UpsertBatch};
    use serde_json::{json, Value};
    use tower::ServiceExt;

    use crate::routes::router;
    use crate::state::AppState;
    use crate::tenant::{ControlPlane, TenantRecord};
    use crate::user_store::{UserRecord, UserStore};

    const EQUIP: &str = "w1cunit";

    fn fixture_database_url() -> Option<String> {
        let url = std::env::var("OPENFDD_LIFECYCLE_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        if url.is_none()
            && std::env::var("OPENFDD_LIFECYCLE_DATABASE_REQUIRED")
                .ok()
                .is_some_and(|value| matches!(value.trim(), "1" | "true" | "yes"))
        {
            panic!("OPENFDD_LIFECYCLE_DATABASE_URL is required for this run");
        }
        url
    }

    fn assert_disposable(id: &str) {
        let upper = id.to_ascii_uppercase();
        assert!(
            upper != "BUILDING_50"
                && upper != "BOSSPI"
                && !upper.contains("BUILDING_50")
                && !upper.contains("BOSSPI"),
            "refusing protected site id"
        );
        assert!(
            !id.is_empty()
                && id
                    .chars()
                    .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-'),
            "fixture id must be a disposable building id"
        );
    }

    fn disposable(prefix: &str) -> String {
        let id = format!("{prefix}{}", uuid::Uuid::new_v4().simple());
        assert_disposable(&id);
        id
    }

    struct EnvRestore {
        saved: Vec<(&'static str, Option<String>)>,
    }

    impl EnvRestore {
        fn capture(keys: &[&'static str]) -> Self {
            Self {
                saved: keys
                    .iter()
                    .map(|key| (*key, std::env::var(key).ok()))
                    .collect(),
            }
        }
    }

    impl Drop for EnvRestore {
        fn drop(&mut self) {
            for (key, value) in self.saved.drain(..) {
                match value {
                    Some(value) => std::env::set_var(key, value),
                    None => std::env::remove_var(key),
                }
            }
        }
    }

    struct DbCleanup {
        url: String,
        ids: Vec<String>,
    }

    impl Drop for DbCleanup {
        fn drop(&mut self) {
            let url = self.url.clone();
            let ids: Vec<String> = self
                .ids
                .drain(..)
                .filter(|id| {
                    let upper = id.to_ascii_uppercase();
                    upper != "BUILDING_50"
                        && upper != "BOSSPI"
                        && !upper.contains("BUILDING_50")
                        && !upper.contains("BOSSPI")
                })
                .collect();
            if ids.is_empty() {
                return;
            }
            let _ = std::thread::spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("cleanup runtime");
                runtime.block_on(async move {
                    let Ok(tsdb) = Tsdb::connect(&url).await else {
                        return;
                    };
                    for id in ids {
                        let _ = tsdb.purge_building(&id).await;
                    }
                });
            })
            .join();
        }
    }

    struct Harness {
        app: Router,
        tsdb: Tsdb,
        workspace: PathBuf,
        _env: EnvRestore,
        _lock: std::sync::MutexGuard<'static, ()>,
        cleanup: DbCleanup,
    }

    async fn ensure_schema(tsdb: &Tsdb) {
        static ONCE: tokio::sync::OnceCell<()> = tokio::sync::OnceCell::const_new();
        ONCE.get_or_init(|| async {
            for stmt in crate::db_lifecycle::forward_statements() {
                sqlx::query(&stmt)
                    .execute(tsdb.pool())
                    .await
                    .unwrap_or_else(|err| {
                        let preview: String = stmt.chars().take(120).collect();
                        panic!("schema statement failed ({preview}): {err}");
                    });
            }
        })
        .await;
    }

    #[expect(
        clippy::await_holding_lock,
        reason = "serialize OPENFDD_* env while the disposable historian fixture is connected"
    )]
    async fn harness() -> Option<Harness> {
        let url = fixture_database_url()?;
        let _lock = crate::test_env_lock::lock_env();
        let workspace = tempfile::tempdir().expect("temp workspace").keep();
        let _env = EnvRestore::capture(&[
            "OPENFDD_WORKSPACE",
            "OPENFDD_DATABASE_URL",
            "OPENFDD_HISTORIAN",
            "OPENFDD_JWT_SECRET",
            "OPENFDD_MULTI_TENANT",
            "OPENFDD_ADMIN_PASSWORD",
            "OPENFDD_RESET_DB",
            "OPENFDD_ALLOW_DESTRUCTIVE_DB",
        ]);
        std::env::set_var("OPENFDD_WORKSPACE", &workspace);
        std::env::set_var("OPENFDD_DATABASE_URL", &url);
        std::env::set_var("OPENFDD_HISTORIAN", "timescale");
        std::env::remove_var("OPENFDD_JWT_SECRET");
        std::env::remove_var("OPENFDD_MULTI_TENANT");
        std::env::remove_var("OPENFDD_RESET_DB");
        std::env::remove_var("OPENFDD_ALLOW_DESTRUCTIVE_DB");
        let tsdb = Tsdb::connect(&url)
            .await
            .expect("connect disposable timescale");
        ensure_schema(&tsdb).await;
        let state = std::sync::Arc::new(AppState::new());
        let app = router(std::sync::Arc::clone(&state));
        Some(Harness {
            app,
            tsdb,
            workspace,
            _env,
            _lock,
            cleanup: DbCleanup {
                url,
                ids: Vec::new(),
            },
        })
    }

    fn track(h: &mut Harness, id: &str) {
        assert_disposable(id);
        h.cleanup.ids.push(id.to_string());
    }

    async fn seed_site(h: &Harness, site: &str) {
        assert_disposable(site);
        h.tsdb
            .ensure_site_building(site)
            .await
            .expect("site building");
        h.tsdb
            .upsert_equipment(site, EQUIP, Some("ahu"))
            .await
            .expect("equipment");
        let mut batch = UpsertBatch::default();
        for minutes in 0..3 {
            let mut row = SampleRow::new(
                Utc::now() - ChronoDuration::minutes(minutes),
                site,
                format!("{EQUIP}.sat"),
                Some(70.0 + minutes as f64),
            );
            row.equipment_id = Some(EQUIP.to_string());
            row.role = Some("sat".to_string());
            row.unit = Some("degF".to_string());
            batch.push(row);
        }
        h.tsdb.upsert_samples(&batch).await.expect("samples");
        let job_id = format!("job-{site}");
        let receipt_id = format!("rcpt-{site}");
        let gap_id = format!("gap-{site}");
        sqlx::query(
            "INSERT INTO fdd_run (site_id, equipment_id, rule_id, window_start, window_end, status)
             VALUES ($1, $2, 'FC1', now() - interval '1 hour', now(), 'ok')",
        )
        .bind(site)
        .bind(EQUIP)
        .execute(h.tsdb.pool())
        .await
        .expect("fdd_run");
        sqlx::query(
            "INSERT INTO analytics_result
                (building_id, query_id, query_version, window_key, config_hash, payload)
             VALUES ($1, 'equipment-inspect', 'equipment-inspect-v1', 'all', 'fixture', '{}'::jsonb)",
        )
        .bind(site)
        .execute(h.tsdb.pool())
        .await
        .expect("analytics_result");
        sqlx::query("INSERT INTO batch_job (kind, site_id, status) VALUES ('fixture', $1, 'done')")
            .bind(site)
            .execute(h.tsdb.pool())
            .await
            .expect("batch_job");
        sqlx::query(
            "INSERT INTO ingest_job (
                job_id, tenant_id, canonical_site, provider_instance_id, device_id,
                model_revision, logical_window_start, logical_window_end, shard, state, not_before
             ) VALUES (
                $1, 'fixture', $2, 'fixture', 'device', 'rev',
                now() - interval '1 hour', now(), '', 'committed', now()
             )",
        )
        .bind(&job_id)
        .bind(site)
        .execute(h.tsdb.pool())
        .await
        .expect("ingest_job");
        sqlx::query(
            "INSERT INTO ingest_receipt (
                receipt_id, job_id, tenant_id, canonical_site, fencing_token, committed_at, counts
             ) VALUES ($1, $2, 'fixture', $3, 1, now(), '{}'::jsonb)",
        )
        .bind(&receipt_id)
        .bind(&job_id)
        .bind(site)
        .execute(h.tsdb.pool())
        .await
        .expect("ingest_receipt");
        sqlx::query(
            "INSERT INTO provider_hourly_job (
                job_id, tenant, canonical_site, provider_instance, device_id, model_revision,
                window_start, window_end, shard, shard_count, purpose, generation, state, point_ids
             ) VALUES (
                $1, 'fixture', $2, 'fixture', 'device', 'rev',
                now() - interval '1 hour', now(), 0, 1, 'fixture', 1, 'committed', '[]'::jsonb
             )",
        )
        .bind(&job_id)
        .bind(site)
        .execute(h.tsdb.pool())
        .await
        .expect("provider_hourly_job");
        sqlx::query(
            "INSERT INTO provider_hourly_receipt (
                receipt_id, job_id, outcome, fetched_count, accepted_count, rejected_count,
                overlap_count, writer_acknowledged, safe_code
             ) VALUES ($1, $2, 'ok', 1, 1, 0, 0, 1, 'ok')",
        )
        .bind(&receipt_id)
        .bind(&job_id)
        .execute(h.tsdb.pool())
        .await
        .expect("provider_hourly_receipt");
        sqlx::query(
            "INSERT INTO provider_hourly_checkpoint (
                tenant, canonical_site, provider_instance, device_id, model_revision, contiguous_end
             ) VALUES ('fixture', $1, 'fixture', 'device', 'rev', now())",
        )
        .bind(site)
        .execute(h.tsdb.pool())
        .await
        .expect("provider_hourly_checkpoint");
        sqlx::query(
            "INSERT INTO provider_hourly_gap (
                gap_id, tenant, canonical_site, provider_instance, device_id, model_revision,
                window_start, window_end, reason, recoverability
             ) VALUES (
                $1, 'fixture', $2, 'fixture', 'device', 'rev',
                now() - interval '1 hour', now(), 'fixture', 'none'
             )",
        )
        .bind(&gap_id)
        .bind(site)
        .execute(h.tsdb.pool())
        .await
        .expect("provider_hourly_gap");

        let dataset = h.workspace.join("data/datasets").join(site);
        std::fs::create_dir_all(&dataset).expect("dataset dir");
        std::fs::write(dataset.join("marker.txt"), b"fixture").expect("dataset marker");
        let package = h.workspace.join("data/csv_buildings").join(site);
        std::fs::create_dir_all(&package).expect("package dir");
        std::fs::write(package.join("marker.txt"), b"fixture").expect("package marker");
        let job = crate::jobs::create_job(
            &format!("fixture {site}"),
            Some(site.to_string()),
            None,
            None,
            None,
            Vec::new(),
            None,
        )
        .expect("job");
        assert!(crate::jobs::load_job(&job.job_id).is_ok());
    }

    async fn dimension_rows(tsdb: &Tsdb, site: &str) -> i64 {
        let mut total = 0i64;
        for (table, column) in [
            ("sample", "site_id"),
            ("equipment", "building_id"),
            ("fdd_run", "site_id"),
            ("analytics_result", "building_id"),
            ("role_map", "building_id"),
            ("point_map", "site_id"),
            ("building", "building_id"),
            ("site", "site_id"),
            ("batch_job", "site_id"),
            ("ingest_job", "canonical_site"),
            ("ingest_receipt", "canonical_site"),
            ("provider_hourly_job", "canonical_site"),
            ("provider_hourly_checkpoint", "canonical_site"),
            ("provider_hourly_gap", "canonical_site"),
        ] {
            let sql = format!("SELECT count(*)::bigint FROM {table} WHERE {column} = $1");
            let n: i64 = sqlx::query_scalar(&sql)
                .bind(site)
                .fetch_one(tsdb.pool())
                .await
                .unwrap_or_else(|err| panic!("count {table}: {err}"));
            total += n;
        }
        let receipts: i64 = sqlx::query_scalar(
            "SELECT count(*)::bigint FROM provider_hourly_receipt
             WHERE job_id IN (SELECT job_id FROM provider_hourly_job WHERE canonical_site = $1)
                OR job_id = $2",
        )
        .bind(site)
        .bind(format!("job-{site}"))
        .fetch_one(tsdb.pool())
        .await
        .expect("receipt count");
        total + receipts
    }

    async fn http(app: &Router, request: Request<Body>) -> (StatusCode, Value) {
        let response = app.clone().oneshot(request).await.expect("router response");
        let status = response.status();
        let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("body");
        let value = serde_json::from_slice(&bytes)
            .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
        (status, value)
    }

    async fn api_reads(app: &Router, site: &str) -> (i64, usize, usize, bool) {
        let (status, equipment) = http(
            app,
            Request::get(format!("/api/fdd/equipment?building_id={site}"))
                .body(Body::empty())
                .expect("equipment request"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "equipment body {equipment}");
        let count = equipment
            .get("count")
            .and_then(Value::as_i64)
            .unwrap_or_else(|| panic!("equipment count missing: {equipment}"));

        let inspect_body = json!({
            "building_id": site,
            "equipment_ids": [EQUIP],
            "max_points": 50
        })
        .to_string();
        let (status, inspect) = http(
            app,
            Request::post("/api/analytics/inspect")
                .header("content-type", "application/json")
                .body(Body::from(inspect_body))
                .expect("inspect request"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "inspect body {inspect}");
        let points = inspect
            .get("points")
            .and_then(Value::as_array)
            .map(Vec::len)
            .unwrap_or(0);

        let iri = format!("urn:openfdd:site/{site}/equip/{EQUIP}/point/sat");
        let query = url::form_urlencoded::Serializer::new(String::new())
            .append_pair("point_iri", &iri)
            .append_pair("include_history", "true")
            .append_pair("max_points", "50")
            .finish();
        let (status, resolved) = http(
            app,
            Request::get(format!("/api/model/point-resolve?{query}"))
                .body(Body::empty())
                .expect("point resolve request"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "point resolve body {resolved}");
        let samples = resolved
            .pointer("/history/samples")
            .and_then(Value::as_array)
            .map(Vec::len)
            .unwrap_or(0);

        let (status, datasets) = http(
            app,
            Request::get(format!("/api/datasets?building_id={site}"))
                .body(Body::empty())
                .expect("datasets request"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "datasets body {datasets}");
        let listed = datasets
            .get("datasets")
            .and_then(Value::as_array)
            .is_some_and(|rows| {
                rows.iter().any(|row| {
                    row.get("id").and_then(Value::as_str) == Some(site)
                        || row.get("building_id").and_then(Value::as_str) == Some(site)
                })
            });
        (count, points, samples, listed)
    }

    fn save_users(workspace: &std::path::Path, users: Vec<UserRecord>, tenants: Vec<TenantRecord>) {
        let mut store = UserStore::default();
        for user in users {
            store.upsert(user).expect("upsert user");
        }
        store.save(workspace).expect("save users");
        let mut plane = ControlPlane::default();
        for tenant in tenants {
            plane.upsert_tenant(tenant).expect("upsert tenant");
        }
        plane.save(workspace).expect("save tenants");
    }

    fn marker_exists(workspace: &std::path::Path, site: &str) -> bool {
        workspace
            .join("data/datasets")
            .join(site)
            .join("marker.txt")
            .is_file()
            || workspace
                .join("data/csv_buildings")
                .join(site)
                .join("marker.txt")
                .is_file()
    }

    /// One runtime owns `Tsdb::connect_from_env`. Separate tests drop that
    /// runtime and the next handler waits out the pool.
    #[tokio::test]
    async fn site_lifecycle_purges_owned_sites() {
        user_cascade_purges_sole_site_and_keeps_shared_site().await;
        dataset_delete_purges_historian_and_repeat_is_idempotent().await;
        partial_cascade_keeps_the_user_until_retry().await;
    }

    async fn user_cascade_purges_sole_site_and_keeps_shared_site() {
        let Some(mut h) = harness().await else {
            eprintln!("skip: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let sole = disposable("w1csole");
        let shared = disposable("w1cshare");
        track(&mut h, &sole);
        track(&mut h, &shared);
        seed_site(&h, &sole).await;
        seed_site(&h, &shared).await;
        let owner = disposable("w1cown");
        let peer = disposable("w1cpeer");
        let solo_tenant = disposable("w1ctsolo");
        let shared_tenant = disposable("w1ctshare");
        save_users(
            &h.workspace,
            vec![
                UserRecord {
                    username: owner.clone(),
                    user_id: String::new(),
                    role: "operator".into(),
                    tenant_ids: vec![solo_tenant.clone(), shared_tenant.clone()],
                    password_env: None,
                    password: Some("fixture".into()),
                    disabled: false,
                    session_version: 0,
                },
                UserRecord {
                    username: peer.clone(),
                    user_id: String::new(),
                    role: "operator".into(),
                    tenant_ids: vec![shared_tenant.clone()],
                    password_env: None,
                    password: Some("fixture".into()),
                    disabled: false,
                    session_version: 0,
                },
            ],
            vec![
                TenantRecord {
                    id: solo_tenant,
                    name: "solo".into(),
                    building_ids: vec![sole.clone()],
                },
                TenantRecord {
                    id: shared_tenant,
                    name: "shared".into(),
                    building_ids: vec![shared.clone()],
                },
            ],
        );

        let sole_before = api_reads(&h.app, &sole).await;
        let shared_before = api_reads(&h.app, &shared).await;
        assert!(
            sole_before.0 >= 1,
            "sole equipment before delete: {sole_before:?}"
        );
        assert!(
            sole_before.1 >= 1,
            "sole inspect before delete: {sole_before:?}"
        );
        assert!(
            sole_before.2 >= 1,
            "sole history before delete: {sole_before:?}"
        );
        assert!(sole_before.3, "sole site missing from dataset list");
        assert!(shared_before.0 >= 1 && shared_before.1 >= 1 && shared_before.2 >= 1);
        let sole_rows = dimension_rows(&h.tsdb, &sole).await;
        let shared_rows = dimension_rows(&h.tsdb, &shared).await;
        assert!(sole_rows > 0 && shared_rows > 0);

        let (status, body) = http(
            &h.app,
            Request::delete(format!("/api/admin/users/{owner}?confirm=true"))
                .body(Body::empty())
                .expect("delete user"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "delete user body {body}");
        assert_eq!(
            body.get("ok").and_then(Value::as_bool),
            Some(true),
            "{body}"
        );
        let purged = body
            .get("purged")
            .and_then(Value::as_array)
            .unwrap_or_else(|| panic!("purged missing: {body}"));
        assert!(
            purged.iter().any(|row| {
                row.get("building_id").and_then(Value::as_str) == Some(sole.as_str())
                    && row
                        .get("timescale_rows_deleted")
                        .and_then(Value::as_u64)
                        .unwrap_or(0)
                        > 0
            }),
            "sole site historian rows were not reported purged: {body}"
        );
        assert!(
            !purged
                .iter()
                .any(|row| row.get("building_id").and_then(Value::as_str) == Some(shared.as_str())),
            "shared site was purged: {body}"
        );
        let skipped = body
            .pointer("/plan/buildings_shared_skipped")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        assert!(
            skipped.iter().any(|v| v.as_str() == Some(shared.as_str())),
            "shared site not listed as skipped: {body}"
        );

        let sole_after = api_reads(&h.app, &sole).await;
        assert_eq!(sole_after.0, 0, "equipment still readable: {sole_after:?}");
        assert_eq!(sole_after.1, 0, "inspect still readable: {sole_after:?}");
        assert_eq!(
            sole_after.2, 0,
            "point history still readable: {sole_after:?}"
        );
        assert!(!sole_after.3, "purged site still listed: {sole_after:?}");
        assert_eq!(dimension_rows(&h.tsdb, &sole).await, 0);
        assert!(!marker_exists(&h.workspace, &sole));

        let shared_after = api_reads(&h.app, &shared).await;
        assert_eq!(shared_after.0, shared_before.0);
        assert!(shared_after.1 >= 1 && shared_after.2 >= 1 && shared_after.3);
        assert_eq!(dimension_rows(&h.tsdb, &shared).await, shared_rows);
        assert!(marker_exists(&h.workspace, &shared));
        let users = UserStore::load_or_empty(&h.workspace);
        assert!(users.get(&owner).is_none());
        assert!(users.get(&peer).is_some());

        let (status, again) = http(
            &h.app,
            Request::delete(format!("/api/datasets?id={sole}"))
                .body(Body::empty())
                .expect("repeat dataset delete"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{again}");
        assert_eq!(
            again.get("ok").and_then(Value::as_bool),
            Some(true),
            "{again}"
        );
        assert_eq!(
            again.get("timescale_rows_deleted").and_then(Value::as_u64),
            Some(0),
            "repeat purge changed historian rows: {again}"
        );
        assert_eq!(dimension_rows(&h.tsdb, &sole).await, 0);
        assert_eq!(dimension_rows(&h.tsdb, &shared).await, shared_rows);
        assert_eq!(api_reads(&h.app, &shared).await.0, shared_before.0);
    }

    async fn dataset_delete_purges_historian_and_repeat_is_idempotent() {
        let Some(mut h) = harness().await else {
            eprintln!("skip: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let site = disposable("w1cds");
        track(&mut h, &site);
        seed_site(&h, &site).await;
        let before = api_reads(&h.app, &site).await;
        assert!(before.0 >= 1 && before.1 >= 1 && before.2 >= 1 && before.3);
        let rows_before = dimension_rows(&h.tsdb, &site).await;
        assert!(rows_before > 0);

        let (status, body) = http(
            &h.app,
            Request::delete(format!("/api/datasets?id={site}"))
                .body(Body::empty())
                .expect("dataset delete"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert_eq!(
            body.get("ok").and_then(Value::as_bool),
            Some(true),
            "{body}"
        );
        assert!(
            body.get("timescale_rows_deleted")
                .and_then(Value::as_u64)
                .unwrap_or(0)
                > 0,
            "dataset delete did not report historian rows: {body}"
        );
        let after = api_reads(&h.app, &site).await;
        assert_eq!(after, (0, 0, 0, false), "history still readable: {after:?}");
        assert_eq!(dimension_rows(&h.tsdb, &site).await, 0);
        assert!(!marker_exists(&h.workspace, &site));

        let (status, again) = http(
            &h.app,
            Request::delete(format!("/api/datasets?building_id={site}"))
                .body(Body::empty())
                .expect("repeat dataset delete"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{again}");
        assert_eq!(
            again.get("ok").and_then(Value::as_bool),
            Some(true),
            "{again}"
        );
        assert_eq!(
            again.get("timescale_rows_deleted").and_then(Value::as_u64),
            Some(0)
        );
        assert_eq!(again.get("jobs_deleted").and_then(Value::as_u64), Some(0));
        assert_eq!(dimension_rows(&h.tsdb, &site).await, 0);
        assert_eq!(api_reads(&h.app, &site).await, (0, 0, 0, false));
    }

    async fn partial_cascade_keeps_the_user_until_retry() {
        let Some(mut h) = harness().await else {
            eprintln!("skip: OPENFDD_LIFECYCLE_DATABASE_URL unset");
            return;
        };
        let site = disposable("w1cpart");
        track(&mut h, &site);
        seed_site(&h, &site).await;
        let shared = disposable("w1cpartshare");
        track(&mut h, &shared);
        seed_site(&h, &shared).await;
        let owner = disposable("w1cpartown");
        let peer = disposable("w1cpartpeer");
        let solo_tenant = disposable("w1cpartsolo");
        let shared_tenant = disposable("w1cpartten");
        let bad_building = "bad id";
        save_users(
            &h.workspace,
            vec![
                UserRecord {
                    username: owner.clone(),
                    user_id: String::new(),
                    role: "operator".into(),
                    tenant_ids: vec![solo_tenant.clone(), shared_tenant.clone()],
                    password_env: None,
                    password: Some("fixture".into()),
                    disabled: false,
                    session_version: 0,
                },
                UserRecord {
                    username: peer,
                    user_id: String::new(),
                    role: "operator".into(),
                    tenant_ids: vec![shared_tenant.clone()],
                    password_env: None,
                    password: Some("fixture".into()),
                    disabled: false,
                    session_version: 0,
                },
            ],
            vec![
                TenantRecord {
                    id: solo_tenant.clone(),
                    name: "solo".into(),
                    building_ids: vec![site.clone(), bad_building.to_string()],
                },
                TenantRecord {
                    id: shared_tenant,
                    name: "shared".into(),
                    building_ids: vec![shared.clone()],
                },
            ],
        );
        let shared_rows = dimension_rows(&h.tsdb, &shared).await;

        let (status, body) = http(
            &h.app,
            Request::delete(format!("/api/admin/users/{owner}?confirm=true"))
                .body(Body::empty())
                .expect("partial delete"),
        )
        .await;
        assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR, "{body}");
        assert_eq!(
            body.get("ok").and_then(Value::as_bool),
            Some(false),
            "{body}"
        );
        let error = body.get("error").and_then(Value::as_str).unwrap_or("");
        assert!(
            error.contains("user not removed"),
            "partial failure claimed success: {body}"
        );
        assert!(
            UserStore::load_or_empty(&h.workspace).get(&owner).is_some(),
            "user removed despite purge failure"
        );
        assert_eq!(dimension_rows(&h.tsdb, &shared).await, shared_rows);
        assert!(marker_exists(&h.workspace, &shared));

        let mut plane = ControlPlane::load_or_legacy(&h.workspace);
        plane
            .upsert_tenant(TenantRecord {
                id: solo_tenant,
                name: "solo".into(),
                building_ids: vec![site.clone()],
            })
            .expect("drop invalid building");
        plane.save(&h.workspace).expect("save plane");

        let (status, retry) = http(
            &h.app,
            Request::delete(format!("/api/admin/users/{owner}?confirm=true"))
                .body(Body::empty())
                .expect("retry delete"),
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{retry}");
        assert_eq!(
            retry.get("ok").and_then(Value::as_bool),
            Some(true),
            "{retry}"
        );
        assert!(UserStore::load_or_empty(&h.workspace).get(&owner).is_none());
        assert_eq!(api_reads(&h.app, &site).await, (0, 0, 0, false));
        assert_eq!(dimension_rows(&h.tsdb, &site).await, 0);
        assert_eq!(dimension_rows(&h.tsdb, &shared).await, shared_rows);
        assert!(api_reads(&h.app, &shared).await.0 >= 1);
    }
}
