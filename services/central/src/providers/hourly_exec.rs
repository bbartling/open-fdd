//! One scheduler tick: enqueue completed hours, claim, GET history, receipt.
//!
//! A history error is a failed job. It is not an empty successful page.
//! Checkpoint moves only through a committed contiguous prefix.

use chrono::{DateTime, Duration, Utc};
use futures_util::future::BoxFuture;

use super::coverage::{build_coverage_ledger, CoverageLedger, LedgerInput};
use super::hourly::{
    assess_page, catch_up_windows, completed_hour_end, model_revision, reconciliation_windows,
    retry_delay_secs, shard_ids, stagger_secs, CoverageOutcome, FetchError, HourlyPolicy,
    LogicalWindow, UPDATE_LOG_STATUS,
};
use super::map::{normalize_mapped, DevicePoints, HistorySeries, RawProviderPoint, ResolvedRole};
use super::store::{
    CheckpointKey, CommitPatch, FailPatch, GapDraft, HourlyStore, JobRecord, JobState, NewJob,
    ReceiptDraft, SeriesFact,
};
use super::types::NormalizedSample;

#[derive(Debug, Clone)]
pub struct FetchRequest {
    pub point_ids: Vec<String>,
    pub from: DateTime<Utc>,
    pub to: DateTime<Utc>,
    pub purpose: String,
    pub device_id: String,
    pub window_start: DateTime<Utc>,
}

pub trait HistorySource: Send {
    fn fetch<'a>(
        &'a mut self,
        req: &'a FetchRequest,
    ) -> BoxFuture<'a, Result<Vec<HistorySeries>, FetchError>>;
}

pub trait SampleWriter: Send {
    fn write<'a>(
        &'a mut self,
        samples: &'a [NormalizedSample],
    ) -> BoxFuture<'a, Result<usize, String>>;
}

pub struct TickInput<'a> {
    pub now: DateTime<Utc>,
    pub tenant: &'a str,
    pub canonical_site: &'a str,
    pub provider_instance: &'a str,
    pub devices: &'a [DevicePoints],
    pub policy: &'a HourlyPolicy,
    pub owner: &'a str,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TickReport {
    pub committed: u32,
    pub no_source_data: u32,
    pub failed: u32,
    pub partial: u32,
    pub samples_handed_off: usize,
    pub unrecoverable_gaps: u32,
    pub durable: bool,
    pub last_safe_code: Option<String>,
    pub fetches: u32,
    pub update_log_status: &'static str,
    pub ledger: CoverageLedger,
}

impl TickReport {
    pub fn health_code(&self) -> String {
        if !self.durable {
            return format!("job_store_memory; {UPDATE_LOG_STATUS}");
        }
        if self.failed > 0 && self.committed == 0 && self.no_source_data == 0 {
            return self
                .last_safe_code
                .clone()
                .unwrap_or_else(|| "history_failed".into());
        }
        if self.failed > 0 || self.partial > 0 || self.unrecoverable_gaps > 0 {
            return format!(
                "degraded; failed={}; partial={}; unrecoverable={}; {UPDATE_LOG_STATUS}",
                self.failed, self.partial, self.unrecoverable_gaps
            );
        }
        if self.committed > 0 || self.no_source_data > 0 {
            return format!("committed; {UPDATE_LOG_STATUS}");
        }
        format!("waiting_completed_hour; {UPDATE_LOG_STATUS}")
    }

    pub fn blocks_green(&self) -> bool {
        !self.durable
            || self.failed > 0
            || self.partial > 0
            || self.unrecoverable_gaps > 0
            || (self.committed == 0 && self.no_source_data == 0)
    }
}

pub async fn run_hourly_tick(
    store: &HourlyStore,
    input: &TickInput<'_>,
    fetch: &mut dyn HistorySource,
    writer: &mut dyn SampleWriter,
) -> Result<TickReport, String> {
    let mut report = TickReport {
        committed: 0,
        no_source_data: 0,
        failed: 0,
        partial: 0,
        samples_handed_off: 0,
        unrecoverable_gaps: 0,
        durable: store.is_durable(),
        last_safe_code: None,
        fetches: 0,
        update_log_status: UPDATE_LOG_STATUS,
        ledger: CoverageLedger::pending(),
    };
    let mut active = Vec::new();
    for device in input.devices {
        let mut points = device.points.clone();
        points.sort_by(|a, b| a.provider_point_id.cmp(&b.provider_point_id));
        if points.is_empty() {
            continue;
        }
        let revision = model_revision(
            &device.device_id,
            &points
                .iter()
                .map(|p| {
                    (
                        p.provider_point_id.clone(),
                        p.role.clone(),
                        p.equip_type.clone(),
                    )
                })
                .collect::<Vec<_>>(),
        );
        active.push((device.device_id.clone(), revision.clone()));
        let key = scope_key(input, &device.device_id, &revision);
        ensure_origin(store, input, &key).await?;
        close_unrecoverable(store, input, &key).await?;
        enqueue_device(store, input, &key, &points).await?;
        enqueue_reconcile(store, input, &key, &points).await?;
    }
    store
        .cancel_stale(input.canonical_site, input.provider_instance, &active)
        .await?;
    let claimed = store
        .claim(
            input.canonical_site,
            input.now,
            input.policy.max_claims_per_tick,
            input.owner,
            input.policy.lease,
        )
        .await?;
    for job in claimed {
        execute_job(store, input, &job, fetch, writer, &mut report).await?;
        if job.purpose == "hourly" {
            let key = scope_key(input, &job.device_id, &job.model_revision);
            advance_checkpoint(store, &key).await?;
        }
    }
    report.unrecoverable_gaps = store.gap_count(input.canonical_site).await?;
    let jobs = store.list_jobs(input.canonical_site).await?;
    let receipts = store.list_receipts(input.canonical_site).await?;
    let gaps = store.list_gaps(input.canonical_site).await?;
    report.ledger = build_coverage_ledger(&LedgerInput {
        jobs: &jobs,
        receipts: &receipts,
        gaps: &gaps,
        now: input.now,
        policy: input.policy,
        durable_store: store.is_durable(),
        latest_samples: &[],
    });
    Ok(report)
}

fn scope_key(input: &TickInput<'_>, device_id: &str, revision: &str) -> CheckpointKey {
    CheckpointKey {
        tenant: input.tenant.to_string(),
        canonical_site: input.canonical_site.to_string(),
        provider_instance: input.provider_instance.to_string(),
        device_id: device_id.to_string(),
        model_revision: revision.to_string(),
    }
}

async fn ensure_origin(
    store: &HourlyStore,
    input: &TickInput<'_>,
    key: &CheckpointKey,
) -> Result<(), String> {
    if store.checkpoint(key).await?.is_some() {
        return Ok(());
    }
    let (due, unrec) = catch_up_windows(None, input.now, input.policy);
    let anchor = unrec
        .first()
        .map(|w| w.start)
        .or_else(|| due.first().map(|w| w.start))
        .unwrap_or_else(|| completed_hour_end(input.now, input.policy.publication_delay));
    store.put_checkpoint(key, anchor).await
}

async fn close_unrecoverable(
    store: &HourlyStore,
    input: &TickInput<'_>,
    key: &CheckpointKey,
) -> Result<(), String> {
    let Some(cp) = store.checkpoint(key).await? else {
        return Ok(());
    };
    let (_due, unrec) = catch_up_windows(Some(cp), input.now, input.policy);
    if unrec.first().map(|w| w.start) != Some(cp) || unrec.is_empty() {
        return Ok(());
    }
    for window in &unrec {
        store
            .insert_gap(&gap_for(key, *window, "outside_retention", "unrecoverable"))
            .await?;
    }
    store.put_checkpoint(key, unrec[unrec.len() - 1].end).await
}

async fn enqueue_device(
    store: &HourlyStore,
    input: &TickInput<'_>,
    key: &CheckpointKey,
    points: &[super::map::MappedPoint],
) -> Result<(), String> {
    let Some(cp) = store.checkpoint(key).await? else {
        return Ok(());
    };
    let (due, _) = catch_up_windows(Some(cp), input.now, input.policy);
    let ids: Vec<String> = points.iter().map(|p| p.provider_point_id.clone()).collect();
    let shards = shard_ids(&ids, input.policy.points_per_shard);
    let shard_count = i32::try_from(shards.len()).unwrap_or(0);
    for window in due {
        for (index, shard) in shards.iter().enumerate() {
            let job = new_window_job(
                key,
                window,
                index,
                shard_count,
                JobPurpose::Hourly,
                due_at(window, input, &key.device_id),
                shard.clone(),
            );
            store.insert_job_if_absent(&job).await?;
        }
    }
    Ok(())
}

async fn enqueue_reconcile(
    store: &HourlyStore,
    input: &TickInput<'_>,
    key: &CheckpointKey,
    points: &[super::map::MappedPoint],
) -> Result<(), String> {
    let Some(cp) = store.checkpoint(key).await? else {
        return Ok(());
    };
    let ids: Vec<String> = points.iter().map(|p| p.provider_point_id.clone()).collect();
    let shards = shard_ids(&ids, input.policy.points_per_shard);
    let shard_count = i32::try_from(shards.len()).unwrap_or(0);
    let sweep = completed_hour_end(input.now, input.policy.publication_delay).timestamp();
    for window in reconciliation_windows(cp, input.policy.reconcile_hours) {
        let existing = store.shard_count_for(key, window).await?;
        if !store.hourly_committed(key, window, existing).await? {
            continue;
        }
        for (index, shard) in shards.iter().enumerate() {
            let job = new_window_job(
                key,
                window,
                index,
                shard_count.max(existing),
                JobPurpose::Reconcile(sweep),
                input.now,
                shard.clone(),
            );
            store.insert_job_if_absent(&job).await?;
        }
    }
    Ok(())
}

enum JobPurpose {
    Hourly,
    Reconcile(i64),
}

fn new_window_job(
    key: &CheckpointKey,
    window: LogicalWindow,
    shard: usize,
    shard_count: i32,
    purpose: JobPurpose,
    not_before: DateTime<Utc>,
    point_ids: Vec<String>,
) -> NewJob {
    let (purpose, generation) = match purpose {
        JobPurpose::Hourly => ("hourly", 0),
        JobPurpose::Reconcile(generation) => ("reconcile", generation),
    };
    NewJob {
        tenant: key.tenant.clone(),
        canonical_site: key.canonical_site.clone(),
        provider_instance: key.provider_instance.clone(),
        device_id: key.device_id.clone(),
        model_revision: key.model_revision.clone(),
        window_start: window.start,
        window_end: window.end,
        shard: i32::try_from(shard).unwrap_or(0),
        shard_count,
        purpose: purpose.to_string(),
        generation,
        not_before,
        point_ids,
    }
}

fn due_at(window: LogicalWindow, input: &TickInput<'_>, device_id: &str) -> DateTime<Utc> {
    window.end
        + input.policy.publication_delay
        + Duration::seconds(stagger_secs(device_id, input.policy.stagger_spread_secs))
}

fn gap_for(
    key: &CheckpointKey,
    window: LogicalWindow,
    reason: &str,
    recoverability: &str,
) -> GapDraft {
    GapDraft {
        tenant: key.tenant.clone(),
        canonical_site: key.canonical_site.clone(),
        provider_instance: key.provider_instance.clone(),
        device_id: key.device_id.clone(),
        model_revision: key.model_revision.clone(),
        window_start: window.start,
        window_end: window.end,
        reason: reason.to_string(),
        recoverability: recoverability.to_string(),
    }
}

async fn advance_checkpoint(store: &HourlyStore, key: &CheckpointKey) -> Result<(), String> {
    for _ in 0..48 {
        let Some(cp) = store.checkpoint(key).await? else {
            break;
        };
        let window = LogicalWindow {
            start: cp,
            end: cp + Duration::seconds(3600),
        };
        let shards = store.shard_count_for(key, window).await?;
        if shards <= 0 || !store.hourly_committed(key, window, shards).await? {
            break;
        }
        store.put_checkpoint(key, window.end).await?;
    }
    Ok(())
}

async fn execute_job(
    store: &HourlyStore,
    input: &TickInput<'_>,
    job: &JobRecord,
    fetch: &mut dyn HistorySource,
    writer: &mut dyn SampleWriter,
    report: &mut TickReport,
) -> Result<(), String> {
    let req = FetchRequest {
        point_ids: job.point_ids.clone(),
        from: job.window_start - input.policy.overlap,
        to: job.window_end,
        purpose: job.purpose.clone(),
        device_id: job.device_id.clone(),
        window_start: job.window_start,
    };
    report.fetches = report.fetches.saturating_add(1);
    let page = match fetch.fetch(&req).await {
        Ok(page) => page,
        Err(err) => {
            note_failure(store, input, job, &err, report).await?;
            return Ok(());
        }
    };
    let logical = LogicalWindow {
        start: job.window_start,
        end: job.window_end,
    };
    let assessed = assess_page(&job.point_ids, &page, logical, input.policy.overlap);
    let device = input.devices.iter().find(|d| d.device_id == job.device_id);
    let (normalized, unmapped) = match device {
        Some(device) => normalize_device(
            input.canonical_site,
            input.provider_instance,
            &device.device_id,
            &device.points,
            &assessed.accepted,
        ),
        None => (Vec::new(), assessed.accepted.len()),
    };
    if unmapped > 0 || assessed.outcome == CoverageOutcome::Partial {
        if !normalized.is_empty() {
            match writer.write(&normalized).await {
                Ok(n) => report.samples_handed_off = report.samples_handed_off.saturating_add(n),
                Err(_) => {
                    note_failure(store, input, job, &FetchError::Persistence, report).await?;
                    return Ok(());
                }
            }
        }
        let err = if unmapped > 0 {
            FetchError::Unmapped
        } else {
            FetchError::PartialSeries
        };
        note_failure(store, input, job, &err, report).await?;
        report.partial = report.partial.saturating_add(1);
        return Ok(());
    }
    let writer_acknowledged = if normalized.is_empty() {
        0
    } else {
        match writer.write(&normalized).await {
            Ok(n) => {
                report.samples_handed_off = report.samples_handed_off.saturating_add(n);
                i32::try_from(n).unwrap_or(i32::MAX)
            }
            Err(_) => {
                note_failure(store, input, job, &FetchError::Persistence, report).await?;
                return Ok(());
            }
        }
    };
    let outcome = if assessed.outcome == CoverageOutcome::NoSourceData {
        "no_source_data"
    } else {
        "samples"
    };
    let receipt = ReceiptDraft {
        receipt_id: format!("{}:{}", job.job_id, job.attempt),
        job_id: job.job_id.clone(),
        outcome: outcome.into(),
        fetched_count: i32::try_from(assessed.fetched).unwrap_or(i32::MAX),
        accepted_count: i32::try_from(assessed.accepted.len()).unwrap_or(i32::MAX),
        rejected_count: i32::try_from(assessed.rejected + unmapped).unwrap_or(i32::MAX),
        overlap_count: i32::try_from(assessed.overlap_count).unwrap_or(i32::MAX),
        writer_acknowledged,
        safe_code: outcome.into(),
        series_facts: series_facts(
            &job.point_ids,
            &assessed.missing,
            &assessed.accepted,
            logical,
        ),
    };
    let ok = store
        .commit(
            &job.job_id,
            job.fencing_token,
            input.owner,
            &CommitPatch {
                receipt,
                now: input.now,
            },
        )
        .await?;
    if !ok {
        report.failed = report.failed.saturating_add(1);
        report.last_safe_code = Some("stale_fence".into());
        return Ok(());
    }
    if outcome == "no_source_data" {
        report.no_source_data = report.no_source_data.saturating_add(1);
    } else {
        report.committed = report.committed.saturating_add(1);
    }
    Ok(())
}

fn series_facts(
    requested: &[String],
    missing: &[String],
    accepted: &[RawProviderPoint],
    window: LogicalWindow,
) -> Vec<SeriesFact> {
    requested
        .iter()
        .map(|id| {
            let missing_series = missing.iter().any(|item| item == id);
            let mut count = 0u32;
            let mut newest: Option<chrono::DateTime<chrono::Utc>> = None;
            if !missing_series {
                for sample in accepted {
                    if &sample.provider_point_id != id
                        || sample.ts < window.start
                        || sample.ts >= window.end
                    {
                        continue;
                    }
                    count = count.saturating_add(1);
                    newest = Some(newest.map(|ts| ts.max(sample.ts)).unwrap_or(sample.ts));
                }
            }
            SeriesFact {
                provider_point_id: id.clone(),
                in_window_samples: count,
                newest_ts: newest,
                missing: missing_series,
            }
        })
        .collect()
}

fn normalize_device(
    site: &str,
    provider_instance_id: &str,
    device_id: &str,
    points: &[super::map::MappedPoint],
    raws: &[super::map::RawProviderPoint],
) -> (Vec<NormalizedSample>, usize) {
    let mut out = Vec::new();
    let mut unmapped = 0usize;
    for raw in raws {
        let Some(point) = points
            .iter()
            .find(|p| p.provider_point_id == raw.provider_point_id)
        else {
            unmapped += 1;
            continue;
        };
        out.push(normalize_mapped(
            site,
            provider_instance_id,
            raw,
            &ResolvedRole::binding(
                device_id,
                point.role.clone(),
                point.equip_type.clone(),
                None,
            ),
        ));
    }
    (out, unmapped)
}

async fn note_failure(
    store: &HourlyStore,
    input: &TickInput<'_>,
    job: &JobRecord,
    err: &FetchError,
    report: &mut TickReport,
) -> Result<(), String> {
    let permanent = err.immediate_permanent() || job.attempt >= input.policy.max_attempts;
    let mut delay = retry_delay_secs(job.attempt);
    if let Some(retry_after) = err.retry_after_secs() {
        delay = delay.max(i64::try_from(retry_after).unwrap_or(delay));
    }
    delay += stagger_secs(
        &format!("{}:{}", job.job_id, job.attempt),
        input.policy.retry_jitter_secs,
    );
    let code = err.code().to_string();
    let state = if permanent {
        JobState::PermanentFailure
    } else if code == "partial_series" {
        JobState::Partial
    } else {
        JobState::RetryWait
    };
    let key = scope_key(input, &job.device_id, &job.model_revision);
    let gap = permanent.then(|| {
        gap_for(
            &key,
            LogicalWindow {
                start: job.window_start,
                end: job.window_end,
            },
            &code,
            if err.immediate_permanent() {
                "blocked"
            } else {
                "retry_exhausted"
            },
        )
    });
    let applied = store
        .fail(
            &job.job_id,
            job.fencing_token,
            input.owner,
            &FailPatch {
                now: input.now,
                state,
                not_before: if permanent {
                    None
                } else {
                    Some(input.now + Duration::seconds(delay))
                },
                safe_error_code: code.clone(),
                gap,
            },
        )
        .await?;
    if applied {
        report.failed = report.failed.saturating_add(1);
        report.last_safe_code = Some(code);
    } else {
        report.failed = report.failed.saturating_add(1);
        report.last_safe_code = Some("stale_fence".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::map::{MappedPoint, RawProviderPoint};
    use chrono::TimeZone;
    use std::sync::Mutex as StdMutex;

    fn ts(hour: u32, min: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 19, hour, min, 0).unwrap()
    }

    fn policy() -> HourlyPolicy {
        HourlyPolicy {
            stagger_spread_secs: 0,
            retry_jitter_secs: 0,
            reconcile_hours: 2,
            max_claims_per_tick: 8,
            bootstrap: Duration::seconds(24 * 3600),
            ..HourlyPolicy::default()
        }
    }

    fn device(points: &[&str]) -> DevicePoints {
        DevicePoints {
            device_id: "dev-1".into(),
            points: points
                .iter()
                .map(|id| MappedPoint {
                    provider_point_id: (*id).to_string(),
                    role: "zone-temp".into(),
                    equip_type: Some("ahu".into()),
                })
                .collect(),
        }
    }

    struct ScriptFetch {
        results: StdMutex<Vec<Result<Vec<HistorySeries>, FetchError>>>,
        calls: StdMutex<Vec<FetchRequest>>,
    }

    impl HistorySource for ScriptFetch {
        fn fetch<'a>(
            &'a mut self,
            req: &'a FetchRequest,
        ) -> BoxFuture<'a, Result<Vec<HistorySeries>, FetchError>> {
            Box::pin(async move {
                self.calls.lock().expect("calls").push(req.clone());
                let mut queue = self.results.lock().expect("results");
                if queue.is_empty() {
                    return Err(FetchError::Transport);
                }
                queue.remove(0)
            })
        }
    }

    struct MemWrite {
        batches: StdMutex<Vec<Vec<NormalizedSample>>>,
        fail: bool,
    }

    impl SampleWriter for MemWrite {
        fn write<'a>(
            &'a mut self,
            samples: &'a [NormalizedSample],
        ) -> BoxFuture<'a, Result<usize, String>> {
            Box::pin(async move {
                if self.fail {
                    return Err("persistence".into());
                }
                self.batches.lock().expect("batches").push(samples.to_vec());
                Ok(samples.len())
            })
        }
    }

    fn series(id: &str, samples: Vec<RawProviderPoint>) -> HistorySeries {
        HistorySeries {
            provider_point_id: id.into(),
            samples,
        }
    }

    fn point(id: &str, hour: u32, min: u32, val: f64) -> RawProviderPoint {
        RawProviderPoint {
            provider_point_id: id.into(),
            display_name: None,
            ts: ts(hour, min),
            val,
            unit: None,
            source_quality: None,
            attrs: serde_json::Map::new(),
        }
    }

    fn input<'a>(
        now: DateTime<Utc>,
        devices: &'a [DevicePoints],
        policy: &'a HourlyPolicy,
    ) -> TickInput<'a> {
        TickInput {
            now,
            tenant: "default",
            canonical_site: "site-a",
            provider_instance: "nf:site-a",
            devices,
            policy,
            owner: "worker-a",
        }
    }

    #[tokio::test]
    async fn history_error_is_not_empty_success() {
        let store = HourlyStore::memory();
        let mut policy = policy();
        policy.bootstrap = Duration::seconds(3600);
        let devices = vec![device(&["p1"])];
        let now = ts(10, 5);
        let mut fetch = ScriptFetch {
            results: StdMutex::new(vec![Err(FetchError::Transport)]),
            calls: StdMutex::new(Vec::new()),
        };
        let mut writer = MemWrite {
            batches: StdMutex::new(Vec::new()),
            fail: false,
        };
        let report = run_hourly_tick(
            &store,
            &input(now, &devices, &policy),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
        assert_eq!(report.committed, 0);
        assert_eq!(report.no_source_data, 0);
        assert!(report.failed >= 1);
        assert!(report.blocks_green());
        assert_eq!(report.last_safe_code.as_deref(), Some("transport"));
        assert!(writer.batches.lock().unwrap().is_empty());
        let jobs = store.list_jobs("site-a").await.unwrap();
        assert!(jobs.iter().any(|job| job.state == JobState::RetryWait));
        assert!(jobs.iter().all(|job| job.state != JobState::Committed));
    }

    #[tokio::test]
    async fn copies_every_sample_and_advances_only_the_contiguous_prefix() {
        let store = HourlyStore::memory();
        let mut policy = policy();
        policy.max_claims_per_tick = 1;
        let devices = vec![device(&["p1"])];
        let anchor = ts(8, 0);
        let now = ts(13, 5);
        // Seed the origin the way a previous process would have left it.
        let key = CheckpointKey {
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: model_revision(
                "dev-1",
                &[("p1".into(), "zone-temp".into(), Some("ahu".into()))],
            ),
        };
        store.put_checkpoint(&key, anchor).await.unwrap();
        let mut samples = Vec::new();
        for minute in 0..60 {
            samples.push(point("p1", 12, 0, f64::from(minute)));
            samples.last_mut().unwrap().ts = ts(12, 0) + Duration::seconds(i64::from(minute) * 60);
        }
        let mut fetch = ScriptFetch {
            results: StdMutex::new(vec![Ok(vec![series("p1", samples)])]),
            calls: StdMutex::new(Vec::new()),
        };
        let mut writer = MemWrite {
            batches: StdMutex::new(Vec::new()),
            fail: false,
        };
        let report = run_hourly_tick(
            &store,
            &input(now, &devices, &policy),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
        assert_eq!(report.committed, 1);
        let calls = fetch.calls.lock().unwrap().clone();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].purpose, "hourly");
        assert_eq!(calls[0].device_id, "dev-1");
        assert_eq!(calls[0].window_start, ts(12, 0));
        assert_eq!(calls[0].from, ts(12, 0) - Duration::seconds(300));
        assert_eq!(calls[0].to, ts(13, 0));
        let batch = writer.batches.lock().unwrap().clone();
        assert_eq!(batch.len(), 1);
        assert_eq!(batch[0].len(), 60);
        assert!((batch[0][0].val - batch[0][59].val).abs() > 1.0);
        assert_eq!(store.checkpoint(&key).await.unwrap(), Some(anchor));
    }

    #[tokio::test]
    async fn catch_up_commits_the_prefix_before_a_later_hour() {
        let store = HourlyStore::memory();
        let mut policy = policy();
        policy.max_claims_per_tick = 8;
        policy.reconcile_hours = 0;
        let devices = vec![device(&["p1"])];
        let key = CheckpointKey {
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: model_revision(
                "dev-1",
                &[("p1".into(), "zone-temp".into(), Some("ahu".into()))],
            ),
        };
        store.put_checkpoint(&key, ts(8, 0)).await.unwrap();
        let mut pages = Vec::new();
        for hour in 8..13 {
            pages.push(Ok(vec![series("p1", vec![point("p1", hour, 30, 70.0)])]));
        }
        let mut fetch = ScriptFetch {
            results: StdMutex::new(pages),
            calls: StdMutex::new(Vec::new()),
        };
        let mut writer = MemWrite {
            batches: StdMutex::new(Vec::new()),
            fail: false,
        };
        let report = run_hourly_tick(
            &store,
            &input(ts(13, 5), &devices, &policy),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
        assert_eq!(report.committed, 5);
        assert_eq!(
            writer
                .batches
                .lock()
                .unwrap()
                .iter()
                .map(|b| b.len())
                .sum::<usize>(),
            5
        );
        assert_eq!(store.checkpoint(&key).await.unwrap(), Some(ts(13, 0)));
        let starts: Vec<_> = fetch
            .calls
            .lock()
            .unwrap()
            .iter()
            .map(|c| c.window_start)
            .collect();
        assert!(starts.contains(&ts(8, 0)));
        assert!(starts.contains(&ts(12, 0)));
        assert!(!starts.iter().any(|s| *s < ts(8, 0)));
    }

    #[tokio::test]
    async fn explicit_empty_commits_separately_from_a_missing_series() {
        let store = HourlyStore::memory();
        let mut policy = policy();
        policy.reconcile_hours = 0;
        policy.bootstrap = Duration::seconds(3600);
        let devices = vec![device(&["p1"])];
        let now = ts(10, 5);
        let mut fetch = ScriptFetch {
            results: StdMutex::new(vec![Ok(vec![series("p1", Vec::new())])]),
            calls: StdMutex::new(Vec::new()),
        };
        let mut writer = MemWrite {
            batches: StdMutex::new(Vec::new()),
            fail: false,
        };
        let report = run_hourly_tick(
            &store,
            &input(now, &devices, &policy),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
        assert_eq!(report.no_source_data, 1);
        assert_eq!(report.committed, 0);
        assert!(writer.batches.lock().unwrap().is_empty());
        assert!(!report.blocks_green() || !report.durable);

        let store = HourlyStore::memory();
        policy.bootstrap = Duration::seconds(3600);
        let devices = vec![device(&["p1", "p2"])];
        let mut fetch = ScriptFetch {
            results: StdMutex::new(vec![Ok(vec![series("p1", vec![point("p1", 9, 10, 1.0)])])]),
            calls: StdMutex::new(Vec::new()),
        };
        let mut writer = MemWrite {
            batches: StdMutex::new(Vec::new()),
            fail: false,
        };
        let report = run_hourly_tick(
            &store,
            &input(now, &devices, &policy),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
        assert_eq!(report.no_source_data, 0);
        assert!(report.partial >= 1);
        assert!(report.blocks_green());
        let jobs = store.list_jobs("site-a").await.unwrap();
        assert!(jobs.iter().all(|job| job.state != JobState::Committed));
    }

    #[tokio::test]
    async fn retention_gap_is_not_fetched_or_marked_green() {
        let store = HourlyStore::memory();
        let mut policy = policy();
        policy.retention = Duration::seconds(2 * 3600);
        policy.reconcile_hours = 0;
        let devices = vec![device(&["p1"])];
        let key = CheckpointKey {
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: model_revision(
                "dev-1",
                &[("p1".into(), "zone-temp".into(), Some("ahu".into()))],
            ),
        };
        store.put_checkpoint(&key, ts(8, 0)).await.unwrap();
        let mut fetch = ScriptFetch {
            results: StdMutex::new(vec![Ok(vec![series("p1", vec![point("p1", 12, 10, 1.0)])])]),
            calls: StdMutex::new(Vec::new()),
        };
        let mut writer = MemWrite {
            batches: StdMutex::new(Vec::new()),
            fail: false,
        };
        let report = run_hourly_tick(
            &store,
            &input(ts(13, 5), &devices, &policy),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
        assert!(report.unrecoverable_gaps > 0);
        assert!(report.blocks_green());
        for call in fetch.calls.lock().unwrap().iter() {
            assert!(call.window_start >= ts(11, 0));
        }
        assert!(report.ledger.rows.iter().any(|row| {
            row.retention == crate::providers::coverage::RetentionState::UnrecoverableExpiry
        }));
        assert!(!report.ledger.gapless);
        assert_eq!(report.ledger.update_log_http, 403);
        assert!(report.ledger.rows.iter().all(|row| !row.gapless));
        assert!(report.ledger.rows.iter().all(|row| !row.from_latest_sample));
    }

    #[tokio::test]
    async fn ledger_reads_receipts_and_does_not_claim_gapless() {
        let store = HourlyStore::memory();
        let mut policy = policy();
        policy.bootstrap = Duration::seconds(3600);
        policy.reconcile_hours = 2;
        let devices = vec![device(&["p1"])];
        let mut samples = Vec::new();
        for minute in 0..60 {
            let mut sample = point("p1", 9, 0, f64::from(minute));
            sample.ts = ts(9, 0) + Duration::seconds(i64::from(minute) * 60);
            samples.push(sample);
        }
        let mut fetch = ScriptFetch {
            results: StdMutex::new(vec![Ok(vec![series("p1", samples)])]),
            calls: StdMutex::new(Vec::new()),
        };
        let mut writer = MemWrite {
            batches: StdMutex::new(Vec::new()),
            fail: false,
        };
        let report = run_hourly_tick(
            &store,
            &input(ts(10, 5), &devices, &policy),
            &mut fetch,
            &mut writer,
        )
        .await
        .unwrap();
        assert_eq!(report.committed, 1);
        assert!(!report.ledger.gapless);
        assert!(report.ledger.update_log_status.contains("not_gapless"));
        assert_eq!(report.ledger.update_log_http, 403);
        assert_eq!(report.ledger.ignored_latest_samples, 0);
        let row = report
            .ledger
            .rows
            .iter()
            .find(|row| row.provider_point_id == "p1")
            .unwrap();
        assert_eq!(
            row.transport_probe,
            crate::providers::coverage::TransportProbe::Ok
        );
        assert_eq!(
            row.requested_window,
            crate::providers::coverage::WindowCompleteness::Complete
        );
        assert_eq!(
            row.durable_commit,
            crate::providers::coverage::DurableCommit::MemoryReceipt
        );
        assert_eq!(
            row.source_freshness,
            crate::providers::coverage::SourceFreshness::WithinCadence
        );
        assert_eq!(
            row.late_reconciliation,
            crate::providers::coverage::LateReconciliation::Pending
        );
        assert!(report.ledger.durable_frontier.is_none());
        assert_eq!(report.ledger.frontier, Some(ts(10, 0)));
        assert!(report.health_code().contains("not_gapless"));
    }
}
