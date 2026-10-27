//! Postgres checkpoint, claim, and atomic publish for incremental FDD (W4b).
//!
//! [`claim`] takes a lease and bumps the fence. Only one live lease exists per
//! scope, so a concurrent run gets [`IncrementalError::Busy`]. [`publish`]
//! locks the checkpoint row, checks the fence and the lease, replaces bucket
//! results, and advances the processed revision in one transaction. A worker
//! whose lease expired, or whose fence was taken over, cannot publish.
//!
//! A run publishes the data revision it read before evaluating. A sample that
//! lands during evaluation has a higher revision, so the next run recomputes
//! its buckets. Results converge; no change is skipped.

use std::collections::BTreeSet;
use std::future::Future;

use chrono::{DateTime, Duration, Utc};
use sqlx::{PgPool, Postgres, Row, Transaction};

use crate::incremental::{
    plan_dirty_buckets, BucketResult, IncrementalError, IncrementalPlan, PlanInput, ResultScope,
};
use crate::revision::{
    changed_ranges_after, current_data_revision, ignorable_catalog_race, schema_statements,
    AnalysisWindow,
};

const INCREMENTAL_SCHEMA_SQL: &str = include_str!("../../../sql/schema/10_incremental_fdd.sql");

/// A live lease on one scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Claim {
    scope: ResultScope,
    owner: String,
    fence: u64,
    processed_revision: Option<u64>,
}

impl Claim {
    pub fn scope(&self) -> &ResultScope {
        &self.scope
    }

    pub fn owner(&self) -> &str {
        &self.owner
    }

    pub fn fence(&self) -> u64 {
        self.fence
    }

    pub fn processed_revision(&self) -> Option<u64> {
        self.processed_revision
    }
}

/// What one incremental run did.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunReport {
    pub fence: u64,
    pub plan: IncrementalPlan,
}

/// Create the checkpoint tables when this database has not applied startup SQL.
pub async fn ensure_incremental_schema(pool: &PgPool) -> Result<(), sqlx::Error> {
    let mut tx = pool.begin().await?;
    let ready: bool = sqlx::query_scalar(
        "SELECT to_regclass('public.fdd_incremental_checkpoint') IS NOT NULL
            AND to_regclass('public.fdd_interval_result') IS NOT NULL",
    )
    .fetch_one(&mut *tx)
    .await?;
    if !ready {
        for statement in schema_statements(INCREMENTAL_SCHEMA_SQL) {
            sqlx::query("SAVEPOINT openfdd_incremental_ddl")
                .execute(&mut *tx)
                .await?;
            match sqlx::query(statement).execute(&mut *tx).await {
                Ok(_) => {}
                Err(err) if ignorable_catalog_race(&err) => {
                    sqlx::query("ROLLBACK TO SAVEPOINT openfdd_incremental_ddl")
                        .execute(&mut *tx)
                        .await?;
                }
                Err(err) => return Err(err),
            }
            sqlx::query("RELEASE SAVEPOINT openfdd_incremental_ddl")
                .execute(&mut *tx)
                .await?;
        }
    }
    tx.commit().await?;
    Ok(())
}

/// Take the scope's lease for `lease`. Fails with `Busy` while another lease is live.
pub async fn claim(
    pool: &PgPool,
    scope: &ResultScope,
    owner: &str,
    lease: Duration,
) -> Result<Claim, IncrementalError> {
    if owner.is_empty() {
        return Err(IncrementalError::EmptyScopeField);
    }
    if lease <= Duration::zero() {
        return Err(IncrementalError::NonPositiveLease);
    }
    let lease_ms = lease.num_milliseconds();
    sqlx::query(
        "INSERT INTO fdd_incremental_checkpoint
           (site_id, rule_id, equipment_id, scope_digest, scope_canonical)
         VALUES ($1, $2, $3, md5($4), $4)
         ON CONFLICT (site_id, rule_id, equipment_id, scope_digest) DO NOTHING",
    )
    .bind(scope.site_id())
    .bind(scope.rule_id())
    .bind(scope.equipment_id())
    .bind(scope.canonical())
    .execute(pool)
    .await?;
    let row = sqlx::query(
        "UPDATE fdd_incremental_checkpoint
         SET fence = fence + 1,
             lease_owner = $5,
             lease_until = now() + ($6::bigint * interval '1 millisecond'),
             updated_at = now()
         WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3
           AND scope_digest = md5($4) AND scope_canonical = $4
           AND (lease_until IS NULL OR lease_until <= now())
         RETURNING fence, processed_revision",
    )
    .bind(scope.site_id())
    .bind(scope.rule_id())
    .bind(scope.equipment_id())
    .bind(scope.canonical())
    .bind(owner)
    .bind(lease_ms)
    .fetch_optional(pool)
    .await?;
    let Some(row) = row else {
        return Err(IncrementalError::Busy);
    };
    Ok(Claim {
        scope: scope.clone(),
        owner: owner.to_string(),
        fence: to_u64(row.try_get("fence")?)?,
        processed_revision: row
            .try_get::<Option<i64>, _>("processed_revision")?
            .map(to_u64)
            .transpose()?,
    })
}

/// Drop this claim's lease without publishing. A stale claim changes nothing.
pub async fn release(pool: &PgPool, claim: &Claim) -> Result<bool, IncrementalError> {
    let done = sqlx::query(
        "UPDATE fdd_incremental_checkpoint
         SET lease_owner = NULL, lease_until = NULL, updated_at = now()
         WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3
           AND scope_digest = md5($4) AND fence = $5 AND lease_owner = $6",
    )
    .bind(claim.scope.site_id())
    .bind(claim.scope.rule_id())
    .bind(claim.scope.equipment_id())
    .bind(claim.scope.canonical())
    .bind(to_i64(claim.fence)?)
    .bind(&claim.owner)
    .execute(pool)
    .await?;
    Ok(done.rows_affected() == 1)
}

/// Replace `results` and advance the checkpoint to `through_revision`, atomically.
pub async fn publish(
    pool: &PgPool,
    claim: &Claim,
    window: AnalysisWindow,
    through_revision: u64,
    results: &[BucketResult],
) -> Result<(), IncrementalError> {
    let grid = claim.scope.grid();
    let on_grid: BTreeSet<DateTime<Utc>> = grid
        .buckets_overlapping(window.start(), window.end())?
        .into_iter()
        .map(|bucket| bucket.start())
        .collect();
    for result in results {
        let bucket = result.bucket();
        if !on_grid.contains(&bucket.start()) || grid.bucket_containing(bucket.start())? != bucket {
            return Err(IncrementalError::ForeignBucket(bucket.start()));
        }
    }
    let mut tx = pool.begin().await?;
    let row = sqlx::query(
        "SELECT fence, lease_owner, (lease_until IS NOT NULL AND lease_until > now()) AS live,
                processed_revision
         FROM fdd_incremental_checkpoint
         WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3 AND scope_digest = md5($4)
         FOR UPDATE",
    )
    .bind(claim.scope.site_id())
    .bind(claim.scope.rule_id())
    .bind(claim.scope.equipment_id())
    .bind(claim.scope.canonical())
    .fetch_one(&mut *tx)
    .await?;
    let current = to_u64(row.try_get("fence")?)?;
    if current != claim.fence {
        return Err(IncrementalError::StaleFence {
            claimed: claim.fence,
            current,
        });
    }
    let owner: Option<String> = row.try_get("lease_owner")?;
    let live: bool = row.try_get("live")?;
    if owner.as_deref() != Some(claim.owner.as_str()) || !live {
        return Err(IncrementalError::LeaseExpired);
    }
    let processed: Option<i64> = row.try_get("processed_revision")?;
    if let Some(processed) = processed.map(to_u64).transpose()? {
        if through_revision < processed {
            return Err(IncrementalError::RevisionRegressed {
                processed,
                requested: through_revision,
            });
        }
    }
    write_results(&mut tx, claim, through_revision, results).await?;
    sqlx::query(
        "UPDATE fdd_incremental_checkpoint
         SET processed_revision = $5, lease_owner = NULL, lease_until = NULL, updated_at = now()
         WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3 AND scope_digest = md5($4)",
    )
    .bind(claim.scope.site_id())
    .bind(claim.scope.rule_id())
    .bind(claim.scope.equipment_id())
    .bind(claim.scope.canonical())
    .bind(to_i64(through_revision)?)
    .execute(&mut *tx)
    .await?;
    tx.commit().await?;
    Ok(())
}

async fn write_results(
    tx: &mut Transaction<'_, Postgres>,
    claim: &Claim,
    through_revision: u64,
    results: &[BucketResult],
) -> Result<(), IncrementalError> {
    if results.is_empty() {
        return Ok(());
    }
    let mut starts = Vec::with_capacity(results.len());
    let mut ends = Vec::with_capacity(results.len());
    let mut faults = Vec::with_capacity(results.len());
    let mut covered = Vec::with_capacity(results.len());
    let mut samples = Vec::with_capacity(results.len());
    for result in results {
        starts.push(result.bucket().start());
        ends.push(result.bucket().end());
        faults.push(result.fault_seconds());
        covered.push(result.covered_seconds());
        samples.push(to_i64(result.sample_count())?);
    }
    sqlx::query(
        "INSERT INTO fdd_interval_result
           (site_id, rule_id, equipment_id, scope_digest, bucket_start, bucket_end,
            fault_seconds, covered_seconds, sample_count, data_revision, fence)
         SELECT $1, $2, $3, md5($4), b_start, b_end, fault, covered, samples, $5, $6
         FROM UNNEST($7::timestamptz[], $8::timestamptz[], $9::float8[], $10::float8[],
                     $11::bigint[]) AS r(b_start, b_end, fault, covered, samples)
         ON CONFLICT (site_id, rule_id, equipment_id, scope_digest, bucket_start) DO UPDATE
         SET bucket_end = EXCLUDED.bucket_end,
             fault_seconds = EXCLUDED.fault_seconds,
             covered_seconds = EXCLUDED.covered_seconds,
             sample_count = EXCLUDED.sample_count,
             data_revision = EXCLUDED.data_revision,
             fence = EXCLUDED.fence,
             computed_at = now()",
    )
    .bind(claim.scope.site_id())
    .bind(claim.scope.rule_id())
    .bind(claim.scope.equipment_id())
    .bind(claim.scope.canonical())
    .bind(to_i64(through_revision)?)
    .bind(to_i64(claim.fence)?)
    .bind(&starts)
    .bind(&ends)
    .bind(&faults)
    .bind(&covered)
    .bind(&samples)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

/// Stored bucket results in `window`, in time order.
pub async fn load_results(
    pool: &PgPool,
    scope: &ResultScope,
    window: AnalysisWindow,
) -> Result<Vec<BucketResult>, IncrementalError> {
    let rows = sqlx::query(
        "SELECT bucket_start, bucket_end, fault_seconds, covered_seconds, sample_count
         FROM fdd_interval_result
         WHERE site_id = $1 AND rule_id = $2 AND equipment_id = $3 AND scope_digest = md5($4)
           AND bucket_start >= $5 AND bucket_end <= $6
         ORDER BY bucket_start",
    )
    .bind(scope.site_id())
    .bind(scope.rule_id())
    .bind(scope.equipment_id())
    .bind(scope.canonical())
    .bind(window.start())
    .bind(window.end())
    .fetch_all(pool)
    .await?;
    let mut out = Vec::with_capacity(rows.len());
    for row in &rows {
        let bucket =
            AnalysisWindow::half_open(row.try_get("bucket_start")?, row.try_get("bucket_end")?)?;
        out.push(BucketResult::new(
            bucket,
            row.try_get("fault_seconds")?,
            row.try_get("covered_seconds")?,
            to_u64(row.try_get("sample_count")?)?,
        )?);
    }
    Ok(out)
}

/// Claim, plan from changed ranges, evaluate dirty buckets, and publish.
///
/// `evaluate(bucket, read_from)` must compute the bucket from inputs in
/// `[read_from, bucket.end)`, where `read_from` is the bucket start minus the
/// scope's lookback. On any error the lease is released and nothing is published.
pub async fn run_incremental<F, Fut>(
    pool: &PgPool,
    scope: &ResultScope,
    owner: &str,
    lease: Duration,
    window: AnalysisWindow,
    input_keys: &BTreeSet<String>,
    mut evaluate: F,
) -> Result<RunReport, IncrementalError>
where
    F: FnMut(AnalysisWindow, DateTime<Utc>) -> Fut,
    Fut: Future<Output = Result<BucketResult, IncrementalError>>,
{
    let claim = claim(pool, scope, owner, lease).await?;
    let outcome = async {
        let through = current_data_revision(pool, scope.site_id()).await?;
        let ranges = changed_ranges_after(
            pool,
            scope.site_id(),
            claim.processed_revision.unwrap_or_default(),
        )
        .await?;
        let stored: BTreeSet<DateTime<Utc>> = load_results(pool, scope, window)
            .await?
            .iter()
            .map(|result| result.bucket().start())
            .collect();
        let plan = plan_dirty_buckets(PlanInput {
            grid: scope.grid(),
            horizon: scope.horizon(),
            window,
            input_keys,
            processed_revision: claim.processed_revision,
            through_revision: through,
            ranges: &ranges,
            stored_buckets: &stored,
        })?;
        let lookback = scope.horizon().lookback();
        let mut results = Vec::with_capacity(plan.buckets.len());
        for bucket in &plan.buckets {
            let read_from = bucket
                .start()
                .checked_sub_signed(lookback)
                .ok_or(IncrementalError::TimeOutOfRange)?;
            let result = evaluate(*bucket, read_from).await?;
            if result.bucket() != *bucket {
                return Err(IncrementalError::ForeignBucket(result.bucket().start()));
            }
            results.push(result);
        }
        publish(pool, &claim, window, plan.through_revision, &results).await?;
        Ok(plan)
    }
    .await;
    match outcome {
        Ok(plan) => Ok(RunReport {
            fence: claim.fence,
            plan,
        }),
        Err(err) => {
            if let Err(release_err) = release(pool, &claim).await {
                tracing::warn!(error = %release_err, "incremental FDD lease release failed");
            }
            Err(err)
        }
    }
}

fn to_u64(value: i64) -> Result<u64, IncrementalError> {
    u64::try_from(value).map_err(|_| IncrementalError::CounterOutOfRange)
}

fn to_i64(value: u64) -> Result<i64, IncrementalError> {
    i64::try_from(value).map_err(|_| IncrementalError::CounterOutOfRange)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;
    use std::sync::{Arc, Mutex};

    use chrono::{Duration, TimeZone, Utc};

    use super::*;
    use crate::incremental::reference::{self, Lcg, Series};
    use crate::incremental::{BucketGrid, RuleHorizon};
    use crate::revision::{
        ensure_revision_schema, ChangedRange, FddResultIdentity, QualityPolicy, RuleParameters,
        SchedulePolicy,
    };

    async fn pool() -> Option<PgPool> {
        let url = std::env::var("OPENFDD_TEST_DATABASE_URL")
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())?;
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(4)
            .connect(&url)
            .await
            .unwrap();
        ensure_revision_schema(&pool).await.unwrap();
        ensure_incremental_schema(&pool).await.unwrap();
        Some(pool)
    }

    fn window() -> AnalysisWindow {
        AnalysisWindow::half_open(
            Utc.with_ymd_and_hms(2026, 11, 1, 3, 0, 0).unwrap(),
            Utc.with_ymd_and_hms(2026, 11, 1, 9, 0, 0).unwrap(),
        )
        .unwrap()
    }

    fn scope(site: &str, limit: &str) -> ResultScope {
        let identity = FddResultIdentity::new(
            0,
            "model-a",
            RuleParameters::try_from_pairs([("limit", limit)]).unwrap(),
            "pack-1",
            window(),
            QualityPolicy::DropBad,
            SchedulePolicy::Sched1,
        );
        ResultScope::new(
            site,
            "rule-confirm",
            "ahu-1",
            &identity,
            BucketGrid::UtcHour,
            RuleHorizon::new(Duration::zero(), reference::confirmation()).unwrap(),
        )
        .unwrap()
    }

    async fn reset(pool: &PgPool, site: &str) {
        for sql in [
            "DELETE FROM fdd_interval_result WHERE site_id = $1",
            "DELETE FROM fdd_incremental_checkpoint WHERE site_id = $1",
            "DELETE FROM sample_changed_range WHERE site_id = $1",
            "DELETE FROM data_revision WHERE site_id = $1",
        ] {
            sqlx::query(sql).bind(site).execute(pool).await.unwrap();
        }
    }

    /// Stand-in for the sample writer's revision bookkeeping.
    async fn record(pool: &PgPool, ranges: &[ChangedRange]) {
        let mut tx = pool.begin().await.unwrap();
        for range in ranges {
            sqlx::query(
                "INSERT INTO data_revision (site_id, revision) VALUES ($1, $2)
                 ON CONFLICT (site_id) DO UPDATE SET revision = GREATEST(data_revision.revision, $2)",
            )
            .bind(&range.site_id)
            .bind(i64::try_from(range.revision).unwrap())
            .execute(&mut *tx)
            .await
            .unwrap();
            sqlx::query(
                "INSERT INTO sample_changed_range
                   (site_id, openfdd_key, revision, range_start, range_end, change_kind)
                 VALUES ($1, $2, $3, $4, $5, $6)",
            )
            .bind(&range.site_id)
            .bind(&range.openfdd_key)
            .bind(i64::try_from(range.revision).unwrap())
            .bind(range.start)
            .bind(range.end)
            .bind(range.kind.as_str())
            .execute(&mut *tx)
            .await
            .unwrap();
        }
        tx.commit().await.unwrap();
    }

    async fn run(
        pool: &PgPool,
        scope: &ResultScope,
        series: &Arc<Mutex<Series>>,
    ) -> Result<RunReport, IncrementalError> {
        let keys = BTreeSet::from([reference::KEY.to_string()]);
        run_incremental(
            pool,
            scope,
            "worker-a",
            Duration::seconds(60),
            window(),
            &keys,
            |bucket, read_from| {
                let series = Arc::clone(series);
                async move {
                    let guard = series
                        .lock()
                        .map_err(|_| IncrementalError::Evaluate("poisoned".into()))?;
                    reference::evaluate(&guard, bucket, read_from)
                }
            },
        )
        .await
    }

    fn full(series: &Series) -> Vec<BucketResult> {
        let lookback = reference::confirmation();
        BucketGrid::UtcHour
            .buckets_overlapping(window().start(), window().end())
            .unwrap()
            .into_iter()
            .map(|bucket| reference::evaluate(series, bucket, bucket.start() - lookback).unwrap())
            .collect()
    }

    /// Runs when `OPENFDD_TEST_DATABASE_URL` is set; otherwise returns early.
    #[tokio::test]
    async fn incremental_runs_match_full_recompute_in_postgres() {
        let Some(pool) = pool().await else {
            return;
        };
        let site = "w4b-incremental-parity";
        reset(&pool, site).await;
        let scope = scope(site, "0.5");
        let mut rng = Lcg::new(11);
        let series = Arc::new(Mutex::new(reference::seed_series(window(), &mut rng)));

        let first = run(&pool, &scope, &series).await.unwrap();
        assert!(first.plan.full);
        assert_eq!(first.plan.buckets.len(), 6);
        let snapshot = series.lock().unwrap().clone();
        assert_eq!(
            load_results(&pool, &scope, window()).await.unwrap(),
            full(&snapshot)
        );
        assert!(full(&snapshot).iter().any(|r| r.fault_seconds() > 0.0));

        for revision in 1..=12_u64 {
            let ranges = {
                let mut guard = series.lock().unwrap();
                let mut ranges = reference::edit(&mut guard, window(), revision, &mut rng);
                for range in &mut ranges {
                    range.site_id = site.to_string();
                }
                ranges
            };
            record(&pool, &ranges).await;
            let report = run(&pool, &scope, &series).await.unwrap();
            assert!(!report.plan.full);
            assert_eq!(report.plan.through_revision, revision);
            assert!(report.plan.buckets.len() < 6 || ranges.is_empty());
            let snapshot = series.lock().unwrap().clone();
            assert_eq!(
                load_results(&pool, &scope, window()).await.unwrap(),
                full(&snapshot),
                "revision {revision}"
            );
        }
        // Nothing changed: nothing recomputed.
        let idle = run(&pool, &scope, &series).await.unwrap();
        assert!(idle.plan.buckets.is_empty());
        reset(&pool, site).await;
    }

    /// Runs when `OPENFDD_TEST_DATABASE_URL` is set; otherwise returns early.
    #[tokio::test]
    async fn concurrent_and_stale_workers_cannot_publish() {
        let Some(pool) = pool().await else {
            return;
        };
        let site = "w4b-incremental-fence";
        reset(&pool, site).await;
        let scope = scope(site, "0.5");
        let bucket = BucketGrid::UtcHour
            .bucket_containing(window().start())
            .unwrap();

        let held = claim(&pool, &scope, "worker-a", Duration::seconds(60))
            .await
            .unwrap();
        assert!(matches!(
            claim(&pool, &scope, "worker-b", Duration::seconds(60)).await,
            Err(IncrementalError::Busy)
        ));
        // A tune is a different scope and is not blocked.
        let tuned = claim(
            &pool,
            &scope_for_tune(site),
            "worker-b",
            Duration::seconds(60),
        )
        .await
        .unwrap();
        assert!(release(&pool, &tuned).await.unwrap());

        // Expire worker-a's lease; worker-b takes over and bumps the fence.
        sqlx::query(
            "UPDATE fdd_incremental_checkpoint SET lease_until = now() - interval '1 second'
             WHERE site_id = $1",
        )
        .bind(site)
        .execute(&pool)
        .await
        .unwrap();
        let takeover = claim(&pool, &scope, "worker-b", Duration::seconds(60))
            .await
            .unwrap();
        assert!(takeover.fence() > held.fence());

        let stale = BucketResult::new(bucket, 600.0, 3600.0, 12).unwrap();
        assert!(matches!(
            publish(&pool, &held, window(), 1, &[stale]).await,
            Err(IncrementalError::StaleFence { .. })
        ));
        assert!(!release(&pool, &held).await.unwrap());
        assert!(load_results(&pool, &scope, window())
            .await
            .unwrap()
            .is_empty());

        let fresh = BucketResult::new(bucket, 300.0, 3600.0, 12).unwrap();
        publish(&pool, &takeover, window(), 1, &[fresh])
            .await
            .unwrap();
        // Late correction replaces the bucket in place.
        let again = claim(&pool, &scope, "worker-b", Duration::seconds(60))
            .await
            .unwrap();
        let corrected = BucketResult::new(bucket, 900.0, 3600.0, 12).unwrap();
        assert!(matches!(
            publish(&pool, &again, window(), 0, &[corrected]).await,
            Err(IncrementalError::RevisionRegressed { .. })
        ));
        publish(&pool, &again, window(), 2, &[corrected])
            .await
            .unwrap();
        assert_eq!(
            load_results(&pool, &scope, window()).await.unwrap(),
            vec![corrected]
        );
        // A bucket off the grid is refused before any write.
        let next = claim(&pool, &scope, "worker-b", Duration::seconds(60))
            .await
            .unwrap();
        let off_grid = BucketResult::new(
            AnalysisWindow::half_open(
                bucket.start() + Duration::minutes(30),
                bucket.end() + Duration::minutes(30),
            )
            .unwrap(),
            0.0,
            10.0,
            1,
        )
        .unwrap();
        assert!(matches!(
            publish(&pool, &next, window(), 3, &[off_grid]).await,
            Err(IncrementalError::ForeignBucket(_))
        ));
        assert!(release(&pool, &next).await.unwrap());
        // Evaluation failure releases the lease and publishes nothing.
        let keys = BTreeSet::from([reference::KEY.to_string()]);
        sqlx::query(
            "UPDATE fdd_incremental_checkpoint SET processed_revision = NULL WHERE site_id = $1",
        )
        .bind(site)
        .execute(&pool)
        .await
        .unwrap();
        let failed = run_incremental(
            &pool,
            &scope,
            "worker-c",
            Duration::seconds(60),
            window(),
            &keys,
            |_, _| async { Err(IncrementalError::Evaluate("boom".into())) },
        )
        .await;
        assert!(matches!(failed, Err(IncrementalError::Evaluate(_))));
        assert_eq!(
            load_results(&pool, &scope, window()).await.unwrap(),
            vec![corrected]
        );
        claim(&pool, &scope, "worker-d", Duration::seconds(60))
            .await
            .unwrap();
        reset(&pool, site).await;
    }

    fn scope_for_tune(site: &str) -> ResultScope {
        scope(site, "0.7")
    }
}
