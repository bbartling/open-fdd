//! Per-device ingest binding metadata (#1423): provider data start and creation time.

use std::collections::{BTreeMap, BTreeSet};

use chrono::{DateTime, Duration, Utc};
use sqlx::PgPool;

use super::coverage::{
    expectation_from_fields, reconcile, PointExpectation, PointObservation, ReconcileInput,
    COMPLETE, NOT_ASSESSED,
};
use super::model::{is_hour_start, JobView, QueueError};

fn sample_table_missing(err: &sqlx::Error) -> bool {
    matches!(
        err,
        sqlx::Error::Database(db) if db.code().as_deref() == Some("42P01")
    )
}

fn ingest_table_missing(err: &sqlx::Error) -> bool {
    sample_table_missing(err)
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct DeviceBindingKey {
    pub tenant_id: String,
    pub canonical_site: String,
    pub provider_instance_id: String,
    pub device_id: String,
    pub model_revision: String,
}

impl DeviceBindingKey {
    pub fn from_job(job: &JobView) -> Self {
        Self {
            tenant_id: job.tenant_id.clone(),
            canonical_site: job.canonical_site.clone(),
            provider_instance_id: job.provider_instance_id.clone(),
            device_id: job.device_id.clone(),
            model_revision: job.model_revision.clone(),
        }
    }
}

/// One planned point: historian key plus coverage identity used on receipts.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DevicePointCoverage {
    pub openfdd_key: String,
    pub coverage_point_id: String,
    pub history_mode: Option<String>,
    pub cadence_secs: Option<u64>,
    pub heartbeat_secs: Option<u64>,
}

impl DevicePointCoverage {
    fn expectation(&self, last_sample_at: Option<DateTime<Utc>>) -> PointExpectation {
        PointExpectation {
            point_id: self.coverage_point_id.clone(),
            expectation: expectation_from_fields(
                self.history_mode.as_deref(),
                self.cadence_secs,
                self.heartbeat_secs,
                last_sample_at,
            ),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeviceBindingState {
    pub binding_created_at: DateTime<Utc>,
    pub provider_data_start: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Copy)]
pub struct EnsureBindingInput<'a> {
    pub key: &'a DeviceBindingKey,
    pub planning_range_start: DateTime<Utc>,
    pub now: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy)]
pub struct LearnProviderDataStartInput<'a> {
    pub key: &'a DeviceBindingKey,
    pub candidate: DateTime<Utc>,
    pub now: DateTime<Utc>,
}

pub async fn ensure_binding_row(
    pool: &PgPool,
    input: EnsureBindingInput<'_>,
) -> Result<DeviceBindingState, QueueError> {
    let binding_created_at = if input.planning_range_start < input.now {
        input.planning_range_start
    } else {
        input.now
    };
    let row = sqlx::query_as::<_, (DateTime<Utc>, Option<DateTime<Utc>>)>(
        "INSERT INTO ingest_device_binding (
            tenant_id, canonical_site, provider_instance_id, device_id, model_revision,
            binding_created_at, updated_at
         ) VALUES ($1, $2, $3, $4, $5, $6, $6)
         ON CONFLICT (tenant_id, canonical_site, provider_instance_id, device_id, model_revision)
         DO UPDATE SET updated_at = ingest_device_binding.updated_at
         RETURNING binding_created_at, provider_data_start",
    )
    .bind(&input.key.tenant_id)
    .bind(&input.key.canonical_site)
    .bind(&input.key.provider_instance_id)
    .bind(&input.key.device_id)
    .bind(&input.key.model_revision)
    .bind(binding_created_at)
    .fetch_one(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(DeviceBindingState {
        binding_created_at: row.0,
        provider_data_start: row.1,
    })
}

pub async fn learn_provider_data_start(
    pool: &PgPool,
    input: LearnProviderDataStartInput<'_>,
) -> Result<Option<DateTime<Utc>>, QueueError> {
    let row = sqlx::query_scalar::<_, Option<DateTime<Utc>>>(
        "UPDATE ingest_device_binding
         SET provider_data_start = CASE
             WHEN provider_data_start IS NULL OR $6 < provider_data_start THEN $6
             ELSE provider_data_start
           END,
           updated_at = $7
         WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
           AND device_id = $4 AND model_revision = $5
         RETURNING provider_data_start",
    )
    .bind(&input.key.tenant_id)
    .bind(&input.key.canonical_site)
    .bind(&input.key.provider_instance_id)
    .bind(&input.key.device_id)
    .bind(&input.key.model_revision)
    .bind(input.candidate)
    .bind(input.now)
    .fetch_optional(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(row.flatten())
}

pub async fn load_binding_state(
    pool: &PgPool,
    key: &DeviceBindingKey,
) -> Result<Option<DeviceBindingState>, QueueError> {
    let row = sqlx::query_as::<_, (DateTime<Utc>, Option<DateTime<Utc>>)>(
        "SELECT binding_created_at, provider_data_start
         FROM ingest_device_binding
         WHERE tenant_id = $1 AND canonical_site = $2 AND provider_instance_id = $3
           AND device_id = $4 AND model_revision = $5",
    )
    .bind(&key.tenant_id)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance_id)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .fetch_optional(pool)
    .await
    .map_err(|err| QueueError::Db(super::model::redact_db_text(&err.to_string())))?;
    Ok(row.map(|(created, start)| DeviceBindingState {
        binding_created_at: created,
        provider_data_start: start,
    }))
}

/// Hours in `[range_start, range_end)` where every planned point is accounted for
/// (Timescale samples and/or committed retrieval receipts), not merely where any
/// point has a row.
pub async fn stored_hour_starts_for_device(
    pool: &PgPool,
    key: &DeviceBindingKey,
    site_id: &str,
    points: &[DevicePointCoverage],
    range_start: DateTime<Utc>,
    range_end: DateTime<Utc>,
) -> Result<Vec<DateTime<Utc>>, QueueError> {
    if points.is_empty() {
        return Ok(Vec::new());
    }
    if range_end <= range_start {
        return Ok(Vec::new());
    }
    let openfdd_keys: Vec<String> = points
        .iter()
        .map(|point| point.openfdd_key.clone())
        .collect();
    let samples = load_samples(pool, site_id, &openfdd_keys, range_start, range_end).await?;
    let last_before = load_last_sample_before(pool, site_id, &openfdd_keys, range_start).await?;
    let receipt_hours =
        load_receipt_accounted_hours(pool, key, points, range_start, range_end).await?;
    Ok(fully_stored_hour_starts(
        points,
        &samples,
        &last_before,
        &receipt_hours,
        range_start,
        range_end,
    ))
}

/// Scheduling hint only: newest sample across selected keys (not per-point completeness).
pub async fn last_stored_ts_for_device(
    pool: &PgPool,
    site_id: &str,
    openfdd_keys: &[String],
) -> Result<Option<DateTime<Utc>>, QueueError> {
    if openfdd_keys.is_empty() {
        return Ok(None);
    }
    let row = match sqlx::query_scalar::<_, Option<DateTime<Utc>>>(
        "SELECT max(ts) FROM sample WHERE site_id = $1 AND openfdd_key = ANY($2)",
    )
    .bind(site_id)
    .bind(openfdd_keys)
    .fetch_one(pool)
    .await
    {
        Ok(row) => row,
        Err(err) if sample_table_missing(&err) => None,
        Err(err) => {
            return Err(QueueError::Db(super::model::redact_db_text(
                &err.to_string(),
            )));
        }
    };
    Ok(row)
}

async fn load_samples(
    pool: &PgPool,
    site_id: &str,
    openfdd_keys: &[String],
    range_start: DateTime<Utc>,
    range_end: DateTime<Utc>,
) -> Result<BTreeMap<String, Vec<DateTime<Utc>>>, QueueError> {
    let rows = match sqlx::query_as::<_, (String, DateTime<Utc>)>(
        "SELECT openfdd_key, ts
         FROM sample
         WHERE site_id = $1 AND openfdd_key = ANY($2)
           AND ts >= $3 AND ts < $4
         ORDER BY openfdd_key, ts",
    )
    .bind(site_id)
    .bind(openfdd_keys)
    .bind(range_start)
    .bind(range_end)
    .fetch_all(pool)
    .await
    {
        Ok(rows) => rows,
        Err(err) if sample_table_missing(&err) => Vec::new(),
        Err(err) => {
            return Err(QueueError::Db(super::model::redact_db_text(
                &err.to_string(),
            )));
        }
    };
    let mut out: BTreeMap<String, Vec<DateTime<Utc>>> = BTreeMap::new();
    for (key, ts) in rows {
        out.entry(key).or_default().push(ts);
    }
    Ok(out)
}

async fn load_last_sample_before(
    pool: &PgPool,
    site_id: &str,
    openfdd_keys: &[String],
    before: DateTime<Utc>,
) -> Result<BTreeMap<String, Option<DateTime<Utc>>>, QueueError> {
    let rows = match sqlx::query_as::<_, (String, DateTime<Utc>)>(
        "SELECT openfdd_key, max(ts) AS last_ts
         FROM sample
         WHERE site_id = $1 AND openfdd_key = ANY($2) AND ts < $3
         GROUP BY openfdd_key",
    )
    .bind(site_id)
    .bind(openfdd_keys)
    .bind(before)
    .fetch_all(pool)
    .await
    {
        Ok(rows) => rows,
        Err(err) if sample_table_missing(&err) => Vec::new(),
        Err(err) => {
            return Err(QueueError::Db(super::model::redact_db_text(
                &err.to_string(),
            )));
        }
    };
    let mut out: BTreeMap<String, Option<DateTime<Utc>>> = BTreeMap::new();
    for (key, ts) in rows {
        out.insert(key, Some(ts));
    }
    Ok(out)
}

async fn load_receipt_accounted_hours(
    pool: &PgPool,
    key: &DeviceBindingKey,
    points: &[DevicePointCoverage],
    range_start: DateTime<Utc>,
    range_end: DateTime<Utc>,
) -> Result<BTreeSet<DateTime<Utc>>, QueueError> {
    let rows = match sqlx::query_as::<_, (DateTime<Utc>, DateTime<Utc>, String, String)>(
        "SELECT j.logical_window_start, j.logical_window_end, ipc.point_id, ipc.disposition
         FROM ingest_job j
         INNER JOIN ingest_point_coverage ipc ON ipc.job_id = j.job_id
         WHERE j.tenant_id = $1 AND j.canonical_site = $2
           AND j.provider_instance_id = $3 AND j.device_id = $4 AND j.model_revision = $5
           AND j.state = 'committed' AND j.coverage = 'complete'
           AND j.logical_window_end > $6 AND j.logical_window_start < $7",
    )
    .bind(&key.tenant_id)
    .bind(&key.canonical_site)
    .bind(&key.provider_instance_id)
    .bind(&key.device_id)
    .bind(&key.model_revision)
    .bind(range_start)
    .bind(range_end)
    .fetch_all(pool)
    .await
    {
        Ok(rows) => rows,
        Err(err) if ingest_table_missing(&err) => Vec::new(),
        Err(err) => {
            return Err(QueueError::Db(super::model::redact_db_text(
                &err.to_string(),
            )));
        }
    };
    if rows.is_empty() {
        return Ok(BTreeSet::new());
    }
    let expected: BTreeSet<String> = points
        .iter()
        .map(|point| point.coverage_point_id.clone())
        .collect();
    let mut windows: BTreeMap<(DateTime<Utc>, DateTime<Utc>), BTreeMap<String, String>> =
        BTreeMap::new();
    for (start, end, point_id, disposition) in rows {
        if !expected.contains(&point_id) {
            continue;
        }
        windows
            .entry((start, end))
            .or_default()
            .insert(point_id, disposition);
    }
    let mut hours = BTreeSet::new();
    let mut cursor = range_start;
    while cursor < range_end {
        if !is_hour_start(cursor) {
            cursor += Duration::hours(1);
            continue;
        }
        let hour_end = cursor + Duration::hours(1);
        let accounted = windows.iter().any(|((start, end), dispositions)| {
            *start <= cursor
                && *end >= hour_end
                && expected.iter().all(|point_id| {
                    dispositions
                        .get(point_id)
                        .is_some_and(|disp| super::coverage::point_disposition_accounted(disp))
                })
        });
        if accounted {
            hours.insert(cursor);
        }
        cursor = hour_end;
    }
    Ok(hours)
}

fn fully_stored_hour_starts(
    points: &[DevicePointCoverage],
    samples: &BTreeMap<String, Vec<DateTime<Utc>>>,
    last_before: &BTreeMap<String, Option<DateTime<Utc>>>,
    receipt_hours: &BTreeSet<DateTime<Utc>>,
    range_start: DateTime<Utc>,
    range_end: DateTime<Utc>,
) -> Vec<DateTime<Utc>> {
    let mut last_seen: BTreeMap<String, Option<DateTime<Utc>>> = BTreeMap::new();
    for point in points {
        last_seen.insert(
            point.coverage_point_id.clone(),
            last_before.get(&point.openfdd_key).copied().flatten(),
        );
    }
    let mut stored = Vec::new();
    let mut cursor = range_start;
    while cursor < range_end {
        if !is_hour_start(cursor) {
            cursor += Duration::hours(1);
            continue;
        }
        let hour_end = cursor + Duration::hours(1);
        if receipt_hours.contains(&cursor) {
            stored.push(cursor);
            advance_last_seen(points, samples, &mut last_seen, cursor, hour_end);
            cursor = hour_end;
            continue;
        }
        if hour_accounted_from_samples(points, samples, &last_seen, cursor, hour_end) {
            stored.push(cursor);
        }
        advance_last_seen(points, samples, &mut last_seen, cursor, hour_end);
        cursor = hour_end;
    }
    stored
}

fn advance_last_seen(
    points: &[DevicePointCoverage],
    samples: &BTreeMap<String, Vec<DateTime<Utc>>>,
    last_seen: &mut BTreeMap<String, Option<DateTime<Utc>>>,
    hour_start: DateTime<Utc>,
    hour_end: DateTime<Utc>,
) {
    for point in points {
        let Some(series) = samples.get(&point.openfdd_key) else {
            continue;
        };
        let mut max_in_hour = None;
        for ts in series {
            if *ts >= hour_start && *ts < hour_end {
                max_in_hour = Some(*ts);
            }
        }
        if let Some(ts) = max_in_hour {
            let entry = last_seen
                .entry(point.coverage_point_id.clone())
                .or_insert(None);
            *entry = Some(entry.map_or(ts, |prev| prev.max(ts)));
        }
    }
}

fn hour_accounted_from_samples(
    points: &[DevicePointCoverage],
    samples: &BTreeMap<String, Vec<DateTime<Utc>>>,
    last_seen: &BTreeMap<String, Option<DateTime<Utc>>>,
    hour_start: DateTime<Utc>,
    hour_end: DateTime<Utc>,
) -> bool {
    let expectations: Vec<PointExpectation> = points
        .iter()
        .map(|point| point.expectation(last_seen.get(&point.coverage_point_id).copied().flatten()))
        .collect();
    let observations: Vec<PointObservation> = points
        .iter()
        .map(|point| {
            let timestamps = samples
                .get(&point.openfdd_key)
                .map(|series| {
                    series
                        .iter()
                        .copied()
                        .filter(|ts| *ts >= hour_start && *ts < hour_end)
                        .collect()
                })
                .unwrap_or_default();
            PointObservation {
                point_id: point.coverage_point_id.clone(),
                returned: true,
                timestamps,
            }
        })
        .collect();
    let Ok(report) = reconcile(&ReconcileInput {
        start: hour_start,
        end: hour_end,
        expectations: &expectations,
        observations: &observations,
        prior: &[],
        response_complete: true,
    }) else {
        return false;
    };
    report.allows_commit() && (report.summary == COMPLETE || report.summary == NOT_ASSESSED)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn h(n: i64) -> DateTime<Utc> {
        DateTime::parse_from_rfc3339("2026-06-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc)
            + Duration::hours(n)
    }

    fn interval_point(key: &str, cadence: u64) -> DevicePointCoverage {
        DevicePointCoverage {
            openfdd_key: key.into(),
            coverage_point_id: format!("src-{key}"),
            history_mode: Some("interval".into()),
            cadence_secs: Some(cadence),
            heartbeat_secs: None,
        }
    }

    fn cov_point(key: &str) -> DevicePointCoverage {
        DevicePointCoverage {
            openfdd_key: key.into(),
            coverage_point_id: format!("src-{key}"),
            history_mode: Some("cov".into()),
            cadence_secs: None,
            heartbeat_secs: None,
        }
    }

    #[test]
    fn hour_requires_every_point_not_any_point() {
        let p1 = "urn:openfdd:point:site:dev:p1";
        let p2 = "urn:openfdd:point:site:dev:p2";
        let points = vec![
            DevicePointCoverage {
                openfdd_key: p1.into(),
                coverage_point_id: "src-p1".into(),
                history_mode: None,
                cadence_secs: None,
                heartbeat_secs: None,
            },
            DevicePointCoverage {
                openfdd_key: p2.into(),
                coverage_point_id: "src-p2".into(),
                history_mode: None,
                cadence_secs: None,
                heartbeat_secs: None,
            },
        ];
        let mut samples = BTreeMap::new();
        samples.insert(p1.into(), vec![h(1) + Duration::minutes(10)]);
        let stored = fully_stored_hour_starts(
            &points,
            &samples,
            &BTreeMap::new(),
            &BTreeSet::new(),
            h(0),
            h(3),
        );
        assert!(stored.is_empty(), "P2 missing in hour 1: {stored:?}");
    }

    #[test]
    fn periodic_missing_internal_hour_stays_a_gap_with_current_last_sample() {
        let key = "urn:openfdd:point:site:dev:sat";
        let points = vec![interval_point(key, 3600)];
        let mut samples = BTreeMap::new();
        samples.insert(
            key.into(),
            vec![h(3) + Duration::minutes(5), h(6) + Duration::minutes(5)],
        );
        let stored = fully_stored_hour_starts(
            &points,
            &samples,
            &BTreeMap::new(),
            &BTreeSet::new(),
            h(0),
            h(8),
        );
        assert_eq!(stored, vec![h(3), h(6)]);
        assert!(!stored.contains(&h(4)));
        assert!(!stored.contains(&h(5)));
    }

    #[test]
    fn cov_sparse_empty_window_is_accounted_not_a_gap() {
        let key = "urn:openfdd:point:site:dev:status";
        let points = vec![cov_point(key)];
        let stored = fully_stored_hour_starts(
            &points,
            &BTreeMap::new(),
            &BTreeMap::new(),
            &BTreeSet::new(),
            h(0),
            h(2),
        );
        assert_eq!(stored, vec![h(0), h(1)]);
    }

    #[test]
    fn periodic_hour_needs_all_cadence_slots() {
        let key = "urn:openfdd:point:site:dev:sat";
        let points = vec![interval_point(key, 900)];
        let mut samples = BTreeMap::new();
        samples.insert(key.into(), vec![h(1) + Duration::minutes(10)]);
        let stored = fully_stored_hour_starts(
            &points,
            &samples,
            &BTreeMap::new(),
            &BTreeSet::new(),
            h(0),
            h(3),
        );
        assert!(
            stored.is_empty(),
            "one 15-min slot does not cover hour: {stored:?}"
        );
    }
}
