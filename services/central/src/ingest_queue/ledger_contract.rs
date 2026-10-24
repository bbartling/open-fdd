//! Contract for `GET /api/ingest/jobs` and `GET /api/ingest/gaps`.
//!
//! The handlers run through the router against the queue. PostgreSQL runs when
//! `OPENFDD_TEST_DATABASE_URL` is set, and is required when
//! `OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED=1`. An empty gap list stays
//! `bounded_windows_only` and does not claim coverage.

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
use crate::state::AppState;

use super::model::{ClaimRequest, FinishOutcome, FinishRequest, JobCounts, NewJob};

const TENANT: &str = "w5c-tenant";
const SITE_GAPS: &str = "w5c-gaps";
const SITE_CLEAR: &str = "w5c-clear";
const PORTAL: &str = "w5c-portal";
const DEVICE_GAPS: &str = "device-a";
const DEVICE_CLEAR: &str = "device-b";
const REVISION: &str = "rev-1";

struct EnvGuard {
    key: &'static str,
    prev: Option<String>,
}

impl EnvGuard {
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

#[derive(Clone, Copy)]
enum Kind {
    Committed,
    Partial,
    Permanent,
    Retry,
}

struct SeedRow {
    job_id: Uuid,
    kind: Kind,
    code: Option<&'static str>,
    counts: JobCounts,
}

#[tokio::test]
#[expect(
    clippy::await_holding_lock,
    reason = "serialize OPENFDD_DATABASE_URL for the ingest ledger contract fixture"
)]
async fn ingest_jobs_and_gaps_contract() {
    let _env = crate::test_env_lock::lock_env();
    let _mt = EnvGuard::unset("OPENFDD_MULTI_TENANT");
    let _queue = EnvGuard::unset("OPENFDD_INGEST_QUEUE");
    let _db = EnvGuard::unset("OPENFDD_DATABASE_URL");
    let workspace = tempfile::tempdir().expect("ledger contract workspace");
    let _ws = crate::test_env_lock::WorkspaceEnv::set(workspace.path());

    run_contract().await;

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
                .expect("ingest ledger postgres fixture");
            super::postgres::apply_schema(&pool)
                .await
                .expect("ingest schema");
            purge_fixture(&pool).await;
            run_contract().await;
            purge_fixture(&pool).await;
        }
        None if required => {
            panic!("OPENFDD_TEST_DATABASE_URL is required for the ingest ledger fixture")
        }
        None => {}
    }
}

async fn run_contract() {
    let mut state = AppState::new();
    state.auth = AuthConfig {
        secret: Some("ingest-ledger-contract-test-secret-not-a-credential".into()),
        admin_password: None,
        agent_password: None,
        viewer_password: None,
        viewer_tenant_ids: Vec::new(),
    };
    let state = Arc::new(state);
    let token = state
        .auth
        .issue_token_with_tenants("w5c-operator", Role::Operator, 600, &[TENANT.into()])
        .expect("ledger contract token");
    let app = crate::routes::router(Arc::clone(&state));
    let seeded = seed(&state).await;
    let partial_id = seeded
        .iter()
        .find(|row| matches!(row.kind, Kind::Partial))
        .map(|row| row.job_id.to_string())
        .expect("partial fixture id");

    let (status, jobs) = call(
        &app,
        &token,
        &format!("/api/ingest/jobs?site_id={SITE_GAPS}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{jobs}");
    assert_bounded_envelope(&jobs, "jobs");
    let job_rows = jobs["jobs"].as_array().expect("jobs array");
    assert_eq!(job_rows.len(), 4, "{jobs}");
    assert!(
        job_rows
            .iter()
            .all(|row| row["canonical_site"] == SITE_GAPS && row["device_id"] == DEVICE_GAPS),
        "{jobs}"
    );
    assert_eq!(jobs["coverage"], "incomplete", "{jobs}");
    let committed = job_rows
        .iter()
        .find(|row| row["state"] == "committed")
        .expect("committed job");
    assert_eq!(committed["coverage"], "complete", "{committed}");
    assert_eq!(
        committed["point_coverage"][0]["disposition"], "present",
        "{committed}"
    );
    let states: Vec<&str> = job_rows
        .iter()
        .filter_map(|row| row["state"].as_str())
        .collect();
    assert_eq!(
        states,
        ["retry_wait", "permanent_failure", "partial", "committed"],
        "{jobs}"
    );
    let partial = job_rows
        .iter()
        .find(|row| row["state"] == "partial")
        .expect("partial job");
    assert_eq!(partial["counts"]["fetched"], 3);
    assert_eq!(partial["counts"]["accepted"], 1);
    assert_eq!(partial["counts"]["rejected"], 2);
    assert_eq!(partial["counts"]["inserted"], 0);
    assert_eq!(partial["safe_error_code"], "upstream_timeout");
    assert_eq!(partial["coverage"], "incomplete", "{partial}");
    assert_eq!(
        partial["point_coverage"][0]["disposition"], "no_sample_received",
        "{partial}"
    );
    assert_ne!(
        partial["point_coverage"][0]["disposition"], "no_sample_expected",
        "{partial}"
    );
    assert!(
        partial["logical_window_start"]
            .as_str()
            .unwrap_or("")
            .contains("2026-01-01T01:00:00"),
        "{partial}"
    );
    assert_eq!(partial["provider_instance_id"], PORTAL);
    assert_eq!(partial["model_revision"], REVISION);
    assert_eq!(partial["job_id"], partial_id);
    assert!(partial["attempt"].is_number(), "{partial}");

    let (status, gaps) = call(
        &app,
        &token,
        &format!("/api/ingest/gaps?site_id={SITE_GAPS}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{gaps}");
    assert_bounded_envelope(&gaps, "gaps");
    assert_eq!(gaps["guarantee"], "bounded_windows_only", "{gaps}");
    assert_eq!(gaps["update_log"], "not_claimed", "{gaps}");
    let gap_rows = gaps["gaps"].as_array().expect("gaps array");
    assert_eq!(gap_rows.len(), 3, "{gaps}");
    assert!(
        gap_rows
            .iter()
            .all(|row| row["job"]["state"] != "committed"),
        "{gaps}"
    );
    assert_eq!(gap_rows[0]["job"]["state"], "partial");
    assert_eq!(gap_rows[0]["recoverable"], true);
    assert_eq!(gap_rows[1]["job"]["state"], "permanent_failure");
    assert_eq!(gap_rows[1]["job"]["safe_error_code"], "retention_exceeded");
    assert_eq!(gap_rows[1]["recoverable"], false);
    assert_eq!(gap_rows[2]["job"]["state"], "retry_wait");
    assert_eq!(gap_rows[2]["recoverable"], true);

    let (status, clear_jobs) = call(
        &app,
        &token,
        &format!("/api/ingest/jobs?site_id={SITE_CLEAR}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{clear_jobs}");
    assert_bounded_envelope(&clear_jobs, "jobs");
    let clear_job_rows = clear_jobs["jobs"].as_array().expect("clear jobs");
    assert_eq!(clear_job_rows.len(), 1, "{clear_jobs}");
    assert_eq!(clear_job_rows[0]["state"], "committed");
    assert_eq!(clear_job_rows[0]["device_id"], DEVICE_CLEAR);
    assert_eq!(clear_job_rows[0]["counts"]["inserted"], 4);

    let (status, clear_gaps) = call(
        &app,
        &token,
        &format!("/api/ingest/gaps?site_id={SITE_CLEAR}"),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{clear_gaps}");
    assert_bounded_envelope(&clear_gaps, "gaps");
    assert_eq!(
        clear_gaps["guarantee"], "bounded_windows_only",
        "{clear_gaps}"
    );
    assert_eq!(clear_gaps["update_log"], "not_claimed", "{clear_gaps}");
    assert_eq!(clear_gaps["coverage"], "not_assessed", "{clear_gaps}");
    assert_eq!(
        clear_gaps["gaps"].as_array().map(Vec::len),
        Some(0),
        "{clear_gaps}"
    );
}

fn assert_bounded_envelope(body: &Value, list_field: &str) {
    assert_eq!(body["ok"], true, "{body}");
    assert!(
        body["request_id"].as_str().is_some_and(|id| !id.is_empty()),
        "{body}"
    );
    assert!(body.get("coverage").is_some(), "{body}");
    assert!(
        body.get(list_field).and_then(Value::as_array).is_some(),
        "{body}"
    );
    assert!(body.get("gapless").is_none(), "{body}");
    assert!(body.get("windows").is_none(), "{body}");
    let text = body.to_string();
    assert!(!text.contains("\"gapless\":true"), "{body}");
    assert!(!text.to_ascii_lowercase().contains("gap-free"), "{body}");
}

async fn seed(state: &AppState) -> Vec<SeedRow> {
    let specs = [
        (
            SITE_GAPS,
            DEVICE_GAPS,
            0,
            Kind::Committed,
            None,
            counts(4, 4, 0, 4),
        ),
        (
            SITE_GAPS,
            DEVICE_GAPS,
            1,
            Kind::Partial,
            Some("upstream_timeout"),
            counts(3, 1, 2, 0),
        ),
        (
            SITE_GAPS,
            DEVICE_GAPS,
            2,
            Kind::Permanent,
            Some("retention_exceeded"),
            counts(0, 0, 0, 0),
        ),
        (
            SITE_GAPS,
            DEVICE_GAPS,
            3,
            Kind::Retry,
            Some("later"),
            counts(0, 0, 0, 0),
        ),
        (
            SITE_CLEAR,
            DEVICE_CLEAR,
            0,
            Kind::Committed,
            None,
            counts(4, 4, 0, 4),
        ),
    ];
    let now = Utc::now();
    let mut rows = Vec::with_capacity(specs.len());
    for (site, device, offset, kind, code, counts) in specs {
        let job = NewJob {
            tenant_id: TENANT.into(),
            canonical_site: site.into(),
            provider_instance_id: PORTAL.into(),
            device_id: device.into(),
            model_revision: REVISION.into(),
            logical_window_start: hour(offset),
            logical_window_end: hour(offset) + Duration::hours(1),
            shard: String::new(),
            not_before: now - Duration::minutes(1),
            estimated_cost: 1,
            requested_points_digest: None,
        };
        let view = match state
            .ingest_queue
            .enqueue(job, now)
            .await
            .expect("enqueue ledger fixture")
        {
            super::model::EnqueueOutcome::Created(view)
            | super::model::EnqueueOutcome::Existing(view) => view,
        };
        rows.push(SeedRow {
            job_id: view.job_id,
            kind,
            code,
            counts,
        });
    }
    if std::env::var("OPENFDD_DATABASE_URL")
        .ok()
        .is_some_and(|value| !value.trim().is_empty())
    {
        mark_postgres(&rows).await;
    } else {
        settle_memory(state, &rows).await;
    }
    rows
}

fn counts(fetched: u32, accepted: u32, rejected: u32, inserted: u32) -> JobCounts {
    JobCounts {
        fetched,
        accepted,
        rejected,
        inserted,
        ..JobCounts::default()
    }
}

async fn settle_memory(state: &AppState, rows: &[SeedRow]) {
    let mut left = rows.len();
    for _ in 0..(rows.len() + 2) {
        if left == 0 {
            return;
        }
        let claimed = state
            .ingest_queue
            .claim(&ClaimRequest {
                owner: "w5c-worker".into(),
                limit: 1,
                now: Utc::now(),
                lease_for: Duration::seconds(120),
            })
            .await
            .expect("claim ledger fixture");
        let Some(job) = claimed.into_iter().next() else {
            panic!("claim returned empty with {left} ledger jobs unsettled");
        };
        let Some(row) = rows.iter().find(|row| row.job_id == job.job_id) else {
            panic!("claimed unexpected job {}", job.job_id);
        };
        let outcome = match row.kind {
            Kind::Committed => FinishOutcome::committed_accounted(row.counts),
            Kind::Partial => FinishOutcome::Partial {
                counts: row.counts,
                code: row.code.unwrap_or("upstream_timeout").to_string(),
                coverage: super::coverage::CoverageReport {
                    summary: "incomplete".into(),
                    points: vec![super::coverage::PointCoverage {
                        point_id: "missing-point".into(),
                        disposition: "no_sample_received".into(),
                        expected_slots: 1,
                        observed_slots: 0,
                        late_slots: 0,
                    }],
                    duplicate_timestamps: 0,
                    out_of_window: 0,
                },
            },
            Kind::Permanent => FinishOutcome::Permanent {
                code: row.code.unwrap_or("retention_exceeded").to_string(),
            },
            Kind::Retry => FinishOutcome::Retry {
                code: row.code.unwrap_or("later").to_string(),
                not_before: Utc::now() + Duration::hours(6),
            },
        };
        state
            .ingest_queue
            .finish(&FinishRequest::new(
                "w5c-worker",
                job.job_id,
                job.fencing_token,
                Utc::now(),
                outcome,
            ))
            .await
            .expect("finish ledger fixture");
        left -= 1;
    }
    panic!("ledger jobs were not settled");
}

async fn mark_postgres(rows: &[SeedRow]) {
    let url = std::env::var("OPENFDD_DATABASE_URL").expect("postgres ledger fixture url");
    let pool = PgPoolOptions::new()
        .max_connections(1)
        .connect(url.trim())
        .await
        .expect("postgres ledger mark");
    for row in rows {
        let (state, code, coverage) = match row.kind {
            Kind::Committed => ("committed", None, "complete"),
            Kind::Partial => (
                "partial",
                row.code.or(Some("upstream_timeout")),
                "incomplete",
            ),
            Kind::Permanent => (
                "permanent_failure",
                row.code.or(Some("retention_exceeded")),
                "not_assessed",
            ),
            Kind::Retry => ("retry_wait", row.code.or(Some("later")), "not_assessed"),
        };
        let job_id = row.job_id.to_string();
        let updated = sqlx::query(
            "UPDATE ingest_job
             SET state = $2,
                 safe_error_code = $3,
                 fetched_count = $4,
                 accepted_count = $5,
                 rejected_count = $6,
                 inserted_count = $7,
                 coverage = $10
             WHERE job_id = $1 AND canonical_site IN ($8, $9)",
        )
        .bind(&job_id)
        .bind(state)
        .bind(code)
        .bind(i32::try_from(row.counts.fetched).unwrap_or(0))
        .bind(i32::try_from(row.counts.accepted).unwrap_or(0))
        .bind(i32::try_from(row.counts.rejected).unwrap_or(0))
        .bind(i32::try_from(row.counts.inserted).unwrap_or(0))
        .bind(SITE_GAPS)
        .bind(SITE_CLEAR)
        .bind(coverage)
        .execute(&pool)
        .await
        .expect("mark ledger job");
        assert_eq!(
            updated.rows_affected(),
            1,
            "ledger job {} not updated",
            row.job_id
        );
        sqlx::query("DELETE FROM ingest_point_coverage WHERE job_id = $1")
            .bind(&job_id)
            .execute(&pool)
            .await
            .expect("clear ledger point coverage");
        let point = match row.kind {
            Kind::Committed => Some(("accounted-point", "present", 1, 1)),
            Kind::Partial => Some(("missing-point", "no_sample_received", 1, 0)),
            Kind::Permanent | Kind::Retry => None,
        };
        if let Some((point_id, disposition, expected, observed)) = point {
            sqlx::query(
                "INSERT INTO ingest_point_coverage (
                    job_id, point_id, disposition, expected_slots, observed_slots, late_slots
                 ) VALUES ($1, $2, $3, $4, $5, 0)",
            )
            .bind(&job_id)
            .bind(point_id)
            .bind(disposition)
            .bind(expected)
            .bind(observed)
            .execute(&pool)
            .await
            .expect("insert ledger point coverage");
        }
    }
}

async fn purge_fixture(pool: &PgPool) {
    for stmt in [
        "DELETE FROM ingest_point_coverage WHERE job_id IN (
            SELECT job_id FROM ingest_job
            WHERE canonical_site IN ('w5c-gaps', 'w5c-clear') OR tenant_id = 'w5c-tenant'
         )",
        "DELETE FROM ingest_applied_sample WHERE tenant_id = 'w5c-tenant'",
        "DELETE FROM ingest_receipt WHERE canonical_site IN ('w5c-gaps', 'w5c-clear') OR tenant_id = 'w5c-tenant'",
        "DELETE FROM ingest_job WHERE canonical_site IN ('w5c-gaps', 'w5c-clear') OR tenant_id = 'w5c-tenant'",
        "DELETE FROM ingest_idempotency WHERE tenant_id = 'w5c-tenant' OR actor = 'w5c-operator'",
    ] {
        sqlx::query(stmt)
            .execute(pool)
            .await
            .expect("purge ledger fixture");
    }
}

fn hour(offset: i64) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-01-01T00:00:00Z")
        .expect("ledger window origin")
        .with_timezone(&Utc)
        + Duration::hours(offset)
}

async fn call(app: &Router, token: &str, path: &str) -> (StatusCode, Value) {
    let request = Request::builder()
        .method("GET")
        .uri(path)
        .header("authorization", format!("Bearer {token}"))
        .body(Body::empty())
        .expect("ledger request");
    let response = app.clone().oneshot(request).await.expect("ledger response");
    let status = response.status();
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("ledger body");
    let body = serde_json::from_slice(&bytes)
        .unwrap_or_else(|_| json!({ "raw": String::from_utf8_lossy(&bytes).into_owned() }));
    (status, body)
}
