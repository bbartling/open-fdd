//! Durable verified-coverage cursor per device and committed model revision.
//!
//! `verified_through` only moves forward, and only across windows whose every
//! job for that instant is committed. The first instant that is not covered is
//! reported as a hole with the blocking job state and code, or `not_scheduled`
//! when no job covers it.

use chrono::{DateTime, Utc};
use serde::Serialize;
use sqlx::{PgPool, Row};

use super::model::{JobState, QueueError};

pub const NOT_SCHEDULED: &str = "not_scheduled";

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize)]
pub struct CursorKey {
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CursorHole {
    pub at: DateTime<Utc>,
    pub state: String,
    pub code: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CoverageCursor {
    #[serde(flatten)]
    pub key: CursorKey,
    pub verified_through: DateTime<Utc>,
    pub hole: Option<CursorHole>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowState {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub state: String,
    pub code: Option<String>,
}

/// Advance from `current` (or the earliest window when there is no cursor yet).
/// Returns `None` only when there is no cursor and no window.
pub fn walk(
    current: Option<DateTime<Utc>>,
    windows: &[WindowState],
) -> Option<(DateTime<Utc>, Option<CursorHole>)> {
    let mut cursor = match current {
        Some(at) => at,
        None => windows.iter().map(|window| window.start).min()?,
    };
    // Each step moves past at least one window end, so the loop is bounded.
    for _ in 0..=windows.len() {
        let covering: Vec<&WindowState> = windows
            .iter()
            .filter(|window| window.start <= cursor && cursor < window.end)
            .collect();
        if let Some(blocker) = covering
            .iter()
            .find(|window| window.state != JobState::Committed.as_str())
        {
            let hole = CursorHole {
                at: cursor,
                state: blocker.state.clone(),
                code: blocker.code.clone(),
            };
            return Some((cursor, Some(hole)));
        }
        let Some(next) = covering.iter().map(|window| window.end).min() else {
            let later = windows.iter().any(|window| window.start > cursor);
            let hole = later.then(|| CursorHole {
                at: cursor,
                state: NOT_SCHEDULED.into(),
                code: None,
            });
            return Some((cursor, hole));
        };
        cursor = next;
    }
    Some((cursor, None))
}

/// Recompute and store the cursor for one device revision in one transaction.
pub async fn advance_postgres(
    pool: &PgPool,
    key: &CursorKey,
    now: DateTime<Utc>,
) -> Result<Option<CoverageCursor>, QueueError> {
    let mut tx = pool.begin().await.map_err(db_err)?;
    let current: Option<DateTime<Utc>> = sqlx::query_scalar(
        "SELECT verified_through FROM ingest_coverage_cursor
         WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
           AND device_id = $4 AND model_revision = $5
         FOR UPDATE",
    )
    .bind(&key.tenant_id)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance_id)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .fetch_optional(&mut *tx)
    .await
    .map_err(db_err)?;
    let rows = sqlx::query(
        "SELECT logical_window_start, logical_window_end, state, safe_error_code
         FROM ingest_job
         WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
           AND device_id = $4 AND model_revision = $5
           AND ($6::timestamptz IS NULL OR logical_window_end > $6)
         ORDER BY logical_window_start",
    )
    .bind(&key.tenant_id)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance_id)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .bind(current)
    .fetch_all(&mut *tx)
    .await
    .map_err(db_err)?;
    let mut windows = Vec::with_capacity(rows.len());
    for row in &rows {
        windows.push(WindowState {
            start: row.try_get("logical_window_start").map_err(db_err)?,
            end: row.try_get("logical_window_end").map_err(db_err)?,
            state: row.try_get("state").map_err(db_err)?,
            code: row.try_get("safe_error_code").map_err(db_err)?,
        });
    }
    let Some((verified_through, hole)) = walk(current, &windows) else {
        tx.commit().await.map_err(db_err)?;
        return Ok(None);
    };
    sqlx::query(
        "INSERT INTO ingest_coverage_cursor (
            tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
            verified_through, hole_at, hole_state, hole_code, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
         ON CONFLICT (tenant_id, canonical_site, provider_instance_id, device_id, model_revision)
         DO UPDATE SET
            verified_through = GREATEST(
                ingest_coverage_cursor.verified_through, EXCLUDED.verified_through
            ),
            hole_at = CASE
                WHEN EXCLUDED.verified_through >= ingest_coverage_cursor.verified_through
                THEN EXCLUDED.hole_at ELSE ingest_coverage_cursor.hole_at END,
            hole_state = CASE
                WHEN EXCLUDED.verified_through >= ingest_coverage_cursor.verified_through
                THEN EXCLUDED.hole_state ELSE ingest_coverage_cursor.hole_state END,
            hole_code = CASE
                WHEN EXCLUDED.verified_through >= ingest_coverage_cursor.verified_through
                THEN EXCLUDED.hole_code ELSE ingest_coverage_cursor.hole_code END,
            updated_at = EXCLUDED.updated_at",
    )
    .bind(&key.tenant_id)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance_id)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .bind(verified_through)
    .bind(hole.as_ref().map(|hole| hole.at))
    .bind(hole.as_ref().map(|hole| hole.state.clone()))
    .bind(hole.as_ref().and_then(|hole| hole.code.clone()))
    .bind(now)
    .execute(&mut *tx)
    .await
    .map_err(db_err)?;
    tx.commit().await.map_err(db_err)?;
    Ok(Some(CoverageCursor {
        key: key.clone(),
        verified_through,
        hole,
        updated_at: now,
    }))
}

fn db_err(err: sqlx::Error) -> QueueError {
    QueueError::Db(super::model::redact_db_text(&err.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(hour: i64) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-10-19T05:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
            + chrono::Duration::hours(hour)
    }

    fn window(hour: i64, state: &str, code: Option<&str>) -> WindowState {
        WindowState {
            start: at(hour),
            end: at(hour + 1),
            state: state.into(),
            code: code.map(str::to_string),
        }
    }

    #[test]
    fn walk_stops_at_the_first_unverified_window() {
        let windows = vec![
            window(0, "committed", None),
            window(1, "committed", None),
            window(2, "retry_wait", Some("genuine_gap")),
            window(3, "committed", None),
        ];
        let (through, hole) = walk(None, &windows).unwrap();
        assert_eq!(through, at(2));
        let hole = hole.unwrap();
        assert_eq!(hole.state, "retry_wait");
        assert_eq!(hole.code.as_deref(), Some("genuine_gap"));
    }

    #[test]
    fn walk_reports_unscheduled_holes_and_never_regresses() {
        let windows = vec![window(0, "committed", None), window(2, "committed", None)];
        let (through, hole) = walk(None, &windows).unwrap();
        assert_eq!(through, at(1));
        assert_eq!(hole.unwrap().state, NOT_SCHEDULED);
        let (through, hole) = walk(Some(at(5)), &windows).unwrap();
        assert_eq!(through, at(5));
        assert!(hole.is_none());
        assert!(walk(None, &[]).is_none());
    }

    #[test]
    fn walk_needs_every_overlapping_job_committed() {
        let mut shard = window(1, "partial", Some("genuine_gap"));
        shard.start = at(1);
        let windows = vec![
            window(0, "committed", None),
            window(1, "committed", None),
            shard,
        ];
        let (through, hole) = walk(None, &windows).unwrap();
        assert_eq!(through, at(1));
        assert_eq!(hole.unwrap().state, "partial");
        let all = vec![window(0, "committed", None), window(1, "committed", None)];
        assert_eq!(walk(None, &all).unwrap(), (at(2), None));
    }

    fn pg_key(tenant: &str) -> CursorKey {
        CursorKey {
            tenant_id: tenant.into(),
            canonical_site: "w5a-site".into(),
            provider_instance_id: "nf:w5a".into(),
            device_id: "AHU_1".into(),
            model_revision: "rev-w5a".into(),
        }
    }

    async fn pg_job(pool: &PgPool, key: &CursorKey, hour: i64) -> uuid::Uuid {
        let job = super::super::model::NewJob {
            tenant_id: key.tenant_id.clone(),
            canonical_site: key.canonical_site.clone(),
            provider_instance_id: key.provider_instance_id.clone(),
            device_id: key.device_id.clone(),
            model_revision: key.model_revision.clone(),
            logical_window_start: at(hour),
            logical_window_end: at(hour + 1),
            shard: String::new(),
            not_before: at(0),
            estimated_cost: 1,
            requested_points_digest: None,
        };
        match super::super::postgres::enqueue(pool, &job).await.unwrap() {
            super::super::model::EnqueueOutcome::Created(view) => view.job_id,
            super::super::model::EnqueueOutcome::Existing(view) => {
                panic!("expected a new job, found {}", view.job_id)
            }
        }
    }

    async fn pg_set(pool: &PgPool, job: uuid::Uuid, state: &str, code: Option<&str>) {
        sqlx::query("UPDATE ingest_job SET state = $2, safe_error_code = $3 WHERE job_id = $1")
            .bind(job.to_string())
            .bind(state)
            .bind(code)
            .execute(pool)
            .await
            .unwrap();
    }

    #[tokio::test]
    #[expect(
        clippy::await_holding_lock,
        reason = "serialize ingest queue DDL with other queue fixtures"
    )]
    async fn postgres_cursor_advances_holds_and_never_regresses() {
        let required = std::env::var("OPENFDD_INGEST_SCOPE_DATABASE_REQUIRED")
            .ok()
            .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
        let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        let Some(url) = url else {
            assert!(
                !required,
                "OPENFDD_TEST_DATABASE_URL is required for the cursor fixture"
            );
            return;
        };
        let _env = crate::test_env_lock::lock_env();
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
            .unwrap();
        super::super::postgres::apply_schema(&pool).await.unwrap();
        let tenant = format!("w5a-{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
        let key = pg_key(&tenant);

        // No jobs: no cursor row.
        assert!(advance_postgres(&pool, &key, at(30))
            .await
            .unwrap()
            .is_none());

        let jobs = [
            pg_job(&pool, &key, 0).await,
            pg_job(&pool, &key, 1).await,
            pg_job(&pool, &key, 2).await,
            pg_job(&pool, &key, 3).await,
        ];
        pg_set(&pool, jobs[0], "committed", None).await;
        pg_set(&pool, jobs[1], "committed", None).await;
        pg_set(&pool, jobs[2], "retry_wait", Some("genuine_gap")).await;
        pg_set(&pool, jobs[3], "committed", None).await;
        let cursor = advance_postgres(&pool, &key, at(30))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(cursor.verified_through, at(2));
        let hole = cursor.hole.clone().unwrap();
        assert_eq!(hole.at, at(2));
        assert_eq!(hole.state, "retry_wait");
        assert_eq!(hole.code.as_deref(), Some("genuine_gap"));

        // Other revisions of the same device do not move this cursor.
        let mut other = key.clone();
        other.model_revision = "rev-other".into();
        let other_job = pg_job(&pool, &other, 2).await;
        pg_set(&pool, other_job, "committed", None).await;
        let again = advance_postgres(&pool, &key, at(31))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(again.verified_through, at(2));

        // Repair the hole: the cursor reaches the end of the last window.
        pg_set(&pool, jobs[2], "committed", None).await;
        let repaired = advance_postgres(&pool, &key, at(32))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(repaired.verified_through, at(4));
        assert!(repaired.hole.is_none());

        // A later failure behind the cursor never moves it back.
        pg_set(&pool, jobs[1], "retry_wait", Some("genuine_gap")).await;
        let held = advance_postgres(&pool, &key, at(33))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(held.verified_through, at(4));
        let stored: DateTime<Utc> = sqlx::query_scalar(
            "SELECT verified_through FROM ingest_coverage_cursor
             WHERE tenant_id = $1 AND model_revision = 'rev-w5a'",
        )
        .bind(&tenant)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(stored, at(4));

        // A skipped hour after the cursor is reported as not scheduled.
        let late = pg_job(&pool, &key, 6).await;
        pg_set(&pool, late, "committed", None).await;
        let gap = advance_postgres(&pool, &key, at(34))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(gap.verified_through, at(4));
        let hole = gap.hole.unwrap();
        assert_eq!(hole.at, at(4));
        assert_eq!(hole.state, NOT_SCHEDULED);

        for sql in [
            "DELETE FROM ingest_coverage_cursor WHERE tenant_id = $1",
            "DELETE FROM ingest_job WHERE tenant_id = $1",
        ] {
            sqlx::query(sql).bind(&tenant).execute(&pool).await.unwrap();
        }
    }
}
