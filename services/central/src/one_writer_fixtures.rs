//! One telemetry writer: NF portal polls and CSV package import / append reach
//! `sample` only through `fdd_tsdb::writer`, replays leave rows unchanged, and
//! nothing columnar is written to disk.
//!
//! PostgreSQL runs when `OPENFDD_TEST_DATABASE_URL` is set; otherwise the test
//! returns early. A row trigger scoped to this fixture's two sites records
//! `current_query()` for every insert or update on `sample`, so a writer that
//! bypasses `fdd_tsdb::writer` shows up as an unknown statement.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{Request, StatusCode};
use serde_json::{json, Value};
use sqlx::PgPool;
use tower::ServiceExt;

use crate::live_historian::LiveWriter;
use crate::state::AppState;

const NF_SITE: &str = "WP2C_ONE_WRITER_NF";
const CSV_SITE: &str = "WP2C_ONE_WRITER_CSV";
const COLUMNAR_EXTENSIONS: &[&str] = &["parquet", "arrow", "feather", "ipc"];

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

async fn install_write_log(pool: &PgPool) {
    for statement in [
        "CREATE TABLE IF NOT EXISTS wp2c_sample_write_log (
            id bigserial PRIMARY KEY,
            site_id text NOT NULL,
            op text NOT NULL,
            query text NOT NULL
        )",
        "CREATE OR REPLACE FUNCTION wp2c_log_sample_write() RETURNS trigger
         LANGUAGE plpgsql AS $fn$
         BEGIN
           INSERT INTO wp2c_sample_write_log (site_id, op, query)
           VALUES (NEW.site_id, TG_OP, current_query());
           RETURN NEW;
         END
         $fn$",
        "DROP TRIGGER IF EXISTS wp2c_sample_write_log ON sample",
        "CREATE TRIGGER wp2c_sample_write_log AFTER INSERT OR UPDATE ON sample
         FOR EACH ROW
         WHEN (NEW.site_id IN ('WP2C_ONE_WRITER_NF', 'WP2C_ONE_WRITER_CSV'))
         EXECUTE FUNCTION wp2c_log_sample_write()",
    ] {
        crate::test_ddl::execute_idempotent_ddl(pool, statement).await;
    }
    for site in [NF_SITE, CSV_SITE] {
        sqlx::query("DELETE FROM wp2c_sample_write_log WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await
            .expect("clear write log");
    }
}

async fn remove_write_log(pool: &PgPool) {
    crate::test_ddl::execute_idempotent_ddl(
        pool,
        "DROP TRIGGER IF EXISTS wp2c_sample_write_log ON sample",
    )
    .await;
    for site in [NF_SITE, CSV_SITE] {
        sqlx::query("DELETE FROM wp2c_sample_write_log WHERE site_id = $1")
            .bind(site)
            .execute(pool)
            .await
            .expect("clear write log");
    }
}

async fn apply_result_cache_schema(pool: &PgPool) {
    crate::test_ddl::execute_idempotent_ddl(
        pool,
        "CREATE TABLE IF NOT EXISTS analytics_result (
            building_id text NOT NULL,
            query_id text NOT NULL,
            query_version text NOT NULL,
            window_key text NOT NULL,
            config_hash text NOT NULL,
            stale boolean NOT NULL DEFAULT false,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (building_id, query_id, query_version, window_key, config_hash)
        )",
    )
    .await;
    for statement in crate::db_lifecycle::statements(include_str!(
        "../../../sql/schema/08_analytics_result_cache.sql"
    )) {
        crate::test_ddl::execute_idempotent_ddl(pool, &statement).await;
    }
}

/// `(op, query)` for every row write on `site`, oldest first.
async fn write_log(pool: &PgPool, site: &str) -> Vec<(String, String)> {
    sqlx::query_as("SELECT op, query FROM wp2c_sample_write_log WHERE site_id = $1 ORDER BY id")
        .bind(site)
        .fetch_all(pool)
        .await
        .expect("write log")
}

/// `(openfdd_key, ts, val, unit)` for `site`, ordered.
async fn site_rows(
    pool: &PgPool,
    site: &str,
) -> Vec<(String, String, Option<f64>, Option<String>)> {
    sqlx::query_as(
        "SELECT openfdd_key, to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS'), val, unit
         FROM sample WHERE site_id = $1 ORDER BY openfdd_key, ts",
    )
    .bind(site)
    .fetch_all(pool)
    .await
    .expect("site rows")
}

fn assert_only_writer_statements(log: &[(String, String)], label: &str) {
    let known = [
        fdd_tsdb::writer::WRITE_ROWS_SQL.trim(),
        fdd_tsdb::writer::PROMOTE_STAGE_SQL.trim(),
    ];
    for (op, query) in log {
        assert!(
            known.contains(&query.trim()),
            "{label}: {op} on sample did not come from fdd_tsdb::writer: {query}"
        );
    }
}

fn nf_envelope(sat: f64, rat: f64) -> openfdd_contracts::TelemetryEnvelope {
    let observed = chrono::DateTime::parse_from_rfc3339("2024-02-01T00:00:00Z")
        .expect("observed_at")
        .with_timezone(&chrono::Utc);
    let point = |id: &str, role: &str, value: f64| openfdd_contracts::TelemetryPoint {
        id: id.into(),
        display_name: None,
        kind: None,
        value: json!(value),
        unit: Some("degF".into()),
        quality: openfdd_contracts::Quality::Good,
        observed_at: Some(observed),
        tags: json!({
            "building_id": NF_SITE,
            "equipment_id": "AHU_1",
            "equipType": "ahu",
            "role": role,
        })
        .as_object()
        .cloned()
        .unwrap_or_default(),
    };
    openfdd_contracts::TelemetryEnvelope::new(
        NF_SITE,
        "wp2c-edge",
        openfdd_contracts::Protocol::Bacnet,
        1,
        vec![point("nf-sat", "sat", sat), point("nf-rat", "rat", rat)],
    )
}

/// One NF portal poll through the product live writer. The writer thread owns
/// its own runtime, so the shared pool is reset on both sides of the call.
async fn nf_poll(
    envelope: &openfdd_contracts::TelemetryEnvelope,
) -> crate::live_historian::LiveHistorianIngest {
    fdd_tsdb::clear_shared_pool();
    let writer = LiveWriter::start();
    let report = writer.ingest(NF_SITE, envelope).await.expect("nf ingest");
    drop(writer);
    fdd_tsdb::clear_shared_pool();
    report
}

fn package_zip() -> Vec<u8> {
    use std::io::Write;
    let manifest = format!(
        r#"{{"schema_version":"openfdd_package_v1","building_id":"{CSV_SITE}","grid_minutes":5,"timezone":"UTC"}}"#
    );
    let map = r#"{"equipType":"ahu","points":{"fan-cmd":"SF_SPD","duct-static-pressure":"DA_P","duct-static-pressure-sp":"DA_P_SP"}}"#;
    let mut history = String::from("timestamp_utc,SF_SPD,DA_P,DA_P_SP\n");
    for minute in [0, 5, 10, 15, 20, 25] {
        history.push_str(&format!("2024-01-01T00:{minute:02}:00Z,0.95,0.4,1.4\n"));
    }
    let mut cursor = std::io::Cursor::new(Vec::new());
    {
        let mut zw = zip::ZipWriter::new(&mut cursor);
        let opts = zip::write::SimpleFileOptions::default();
        for (name, content) in [
            ("manifest.json", manifest.as_str()),
            ("AHU_1/history_wide.json", map),
            ("AHU_1/history_wide.csv", history.as_str()),
        ] {
            zw.start_file(name, opts).expect("zip entry");
            zw.write_all(content.as_bytes()).expect("zip write");
        }
        zw.finish().expect("zip finish");
    }
    cursor.into_inner()
}

async fn send(app: &axum::Router, request: Request<Body>) -> (StatusCode, Value) {
    let response = app.clone().oneshot(request).await.expect("response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("body");
    let body = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    (status, body)
}

async fn csv_import(app: &axum::Router) -> (StatusCode, Value) {
    send(
        app,
        Request::post("/api/csv/import/package")
            .header("content-type", "application/zip")
            .body(Body::from(package_zip()))
            .expect("import request"),
    )
    .await
}

async fn csv_append(app: &axum::Router) -> (StatusCode, Value) {
    let payload = json!({
        "confirm": true,
        "building_id": CSV_SITE,
        "equipment_id": "AHU_1",
        "csv": "timestamp_utc,SF_SPD,DA_P,DA_P_SP\n2024-01-01T00:30:00Z,0.8,0.5,1.4\n",
    });
    send(
        app,
        Request::post("/api/csv/import/package/append")
            .header("content-type", "application/json")
            .body(Body::from(payload.to_string()))
            .expect("append request"),
    )
    .await
}

fn columnar_files(root: &std::path::Path) -> Vec<String> {
    let mut found = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                if path.file_name().and_then(|n| n.to_str()) == Some("analytics_results") {
                    found.push(path.display().to_string());
                }
                stack.push(path);
            } else if path
                .extension()
                .and_then(|ext| ext.to_str())
                .is_some_and(|ext| COLUMNAR_EXTENSIONS.contains(&ext.to_ascii_lowercase().as_str()))
            {
                found.push(path.display().to_string());
            }
        }
    }
    found
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL and OPENFDD_WORKSPACE for the one-writer fixture"
)]
async fn nf_poll_and_csv_import_share_one_writer_and_replay_is_idempotent() {
    let Some(url) = test_database_url() else {
        return;
    };
    let _env = crate::test_env_lock::lock_env();
    let workspace = tempfile::tempdir().expect("workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());
    let _storage = EnvGuard::unset("OPENFDD_STORAGE_URL");
    let _cache_root = EnvGuard::unset("OPENFDD_ANALYTICS_CACHE_ROOT");
    let _historian = EnvGuard::set("OPENFDD_HISTORIAN", "timescale");
    let _database = EnvGuard::set("OPENFDD_DATABASE_URL", &url);
    let _jwt = EnvGuard::unset("OPENFDD_JWT_SECRET");
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    let _shed = EnvGuard::set("OPENFDD_MEMORY_SHED_FRACTION", "0.99");
    let _abort = EnvGuard::set("OPENFDD_MEMORY_ABORT_FRACTION", "1.0");

    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(2)
        .connect(&url)
        .await
        .expect("one-writer postgres");
    crate::package_preflight_fixtures::apply_schema(&pool).await;
    apply_result_cache_schema(&pool).await;
    for site in [NF_SITE, CSV_SITE] {
        crate::package_preflight_fixtures::purge_site(&pool, site).await;
    }
    install_write_log(&pool).await;

    // NF portal poll: first write inserts, replay is a no-op, a changed value updates.
    let first = nf_poll(&nf_envelope(55.0, 72.0)).await;
    assert_eq!(first.inserted_rows, 2, "{first:?}");
    let after_first = site_rows(&pool, NF_SITE).await;
    assert_eq!(after_first.len(), 2, "{after_first:?}");
    let replay = nf_poll(&nf_envelope(55.0, 72.0)).await;
    assert_eq!(
        (replay.inserted_rows, replay.updated_rows),
        (0, 0),
        "{replay:?}"
    );
    assert_eq!(site_rows(&pool, NF_SITE).await, after_first);
    assert_eq!(
        write_log(&pool, NF_SITE).await.len(),
        2,
        "NF replay wrote rows"
    );
    let changed = nf_poll(&nf_envelope(56.0, 72.0)).await;
    assert_eq!(
        (changed.inserted_rows, changed.updated_rows),
        (0, 1),
        "{changed:?}"
    );
    let nf_log = write_log(&pool, NF_SITE).await;
    assert_eq!(nf_log.len(), 3, "{nf_log:?}");
    assert_only_writer_statements(&nf_log, "NF poll");
    assert!(nf_log
        .iter()
        .all(|(_, q)| q.trim() == fdd_tsdb::writer::WRITE_ROWS_SQL.trim()));

    // CSV package import, then the same package again.
    let app = crate::routes::router(Arc::new(AppState::new()));
    let (status, body) = csv_import(&app).await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["ok"], json!(true), "{body}");
    assert_eq!(body["historian"], json!("timescale"), "{body}");
    let imported = site_rows(&pool, CSV_SITE).await;
    assert_eq!(imported.len(), 18, "{imported:?}");
    let (status, body) = csv_import(&app).await;
    assert_eq!(status, StatusCode::OK, "replay {body}");
    assert_eq!(body["ok"], json!(true), "replay {body}");
    assert_eq!(
        site_rows(&pool, CSV_SITE).await,
        imported,
        "import replay changed rows"
    );

    // CSV append goes through the same batch statement as the NF poll.
    let before_append = write_log(&pool, CSV_SITE).await.len();
    let (status, body) = csv_append(&app).await;
    assert_eq!(status, StatusCode::OK, "append {body}");
    assert_eq!(body["ok"], json!(true), "append {body}");
    let appended = site_rows(&pool, CSV_SITE).await;
    assert_eq!(appended.len(), 21, "{appended:?}");
    let append_log = write_log(&pool, CSV_SITE).await;
    assert!(append_log.len() > before_append, "append wrote nothing");
    assert!(append_log[before_append..]
        .iter()
        .all(|(_, q)| q.trim() == fdd_tsdb::writer::WRITE_ROWS_SQL.trim()));
    let (status, body) = csv_append(&app).await;
    assert_eq!(status, StatusCode::OK, "append replay {body}");
    assert_eq!(
        site_rows(&pool, CSV_SITE).await,
        appended,
        "append replay changed rows"
    );
    assert_eq!(
        write_log(&pool, CSV_SITE).await.len(),
        append_log.len(),
        "append replay wrote rows"
    );

    let csv_log = write_log(&pool, CSV_SITE).await;
    assert_only_writer_statements(&csv_log, "CSV import");
    assert!(csv_log
        .iter()
        .any(|(_, q)| q.trim() == fdd_tsdb::writer::PROMOTE_STAGE_SQL.trim()));

    // Derived results land in PostgreSQL, not under the workspace.
    let store = crate::analytics::result_store::ResultStore::Postgres(Arc::new(
        fdd_tsdb::Tsdb::from_pool(pool.clone()),
    ));
    let key = fdd_store::AnalyticsCacheKey {
        building_id: CSV_SITE.into(),
        query_id: "wp2c-one-writer".into(),
        query_version: "v1".into(),
        window_start: "open".into(),
        window_end: "open".into(),
        config_hash: "h".into(),
    };
    let table = fdd_store::AnalyticsResultTable {
        rows: vec![json!({"equipment_id": "AHU_1"})],
        equipment: Vec::new(),
        points: Vec::new(),
        skipped: Vec::new(),
        warnings: Vec::new(),
        coverage: None,
        engine: "timescale-sql".into(),
        result_query_version: "v1".into(),
    };
    let provenance = fdd_store::CacheProvenance {
        building_id: key.building_id.clone(),
        query_id: key.query_id.clone(),
        query_version: key.query_version.clone(),
        window_start: key.window_start.clone(),
        window_end: key.window_end.clone(),
        config_hash: key.config_hash.clone(),
        watermark_order: 1,
        watermark_utc: "2024-01-01T00:30:00Z".into(),
        generated_at: "2024-01-01T00:30:00Z".into(),
        engine: "timescale-sql".into(),
        result_query_version: "v1".into(),
        result_contract: "analytics-result-contract-v2".into(),
        sql_pack: "wp2c".into(),
        model_revision: "wp2c".into(),
        watermark_source: "timescale".into(),
        watermark_status: "known".into(),
        coverage: "samples=21".into(),
    };
    store
        .write(&key, &table, &provenance)
        .await
        .expect("result cache write");
    assert!(store.read(&key).await.expect("result cache read").is_some());

    let files = columnar_files(workspace.path());
    assert!(files.is_empty(), "columnar files on disk: {files:?}");

    sqlx::query("DELETE FROM analytics_result WHERE building_id = $1")
        .bind(CSV_SITE)
        .execute(&pool)
        .await
        .expect("cache cleanup");
    remove_write_log(&pool).await;
    for site in [NF_SITE, CSV_SITE] {
        crate::package_preflight_fixtures::purge_site(&pool, site).await;
    }
    fdd_tsdb::clear_shared_pool();
}
