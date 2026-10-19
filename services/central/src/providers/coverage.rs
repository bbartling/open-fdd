//! Per-series coverage ledger (N7).
//!
//! Each row separates transport, requested-window completeness, durable commit,
//! source freshness, late reconciliation, and retention expiry. A latest-value
//! sample is not a row and cannot move the frontier. NF update-log
//! `GET /api/v1/point/updates/data` returned HTTP 403, so `gapless` stays false.
//! Reconciliation is only the recent `reconcile_hours` bound.

use std::collections::BTreeMap;

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};

use super::hourly::{completed_hour_end, HourlyPolicy, UPDATE_LOG_HTTP, UPDATE_LOG_STATUS};
use super::store::{GapDraft, JobRecord, JobState, ReceiptDraft, SeriesFact};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransportProbe {
    NotRun,
    Ok,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WindowCompleteness {
    Unknown,
    Complete,
    NoSourceData,
    Partial,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DurableCommit {
    None,
    /// Receipt is in the process-memory job store. Not a durable commit.
    MemoryReceipt,
    /// Receipt is in Postgres with the hourly job.
    DurableReceipt,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceFreshness {
    Unknown,
    NoSamples,
    /// One in-window sample is not a cadence proof.
    SingleSample,
    WithinCadence,
    Stale,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LateReconciliation {
    OutsideBound,
    Pending,
    Reconciled,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RetentionState {
    Inside,
    UnrecoverableExpiry,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LedgerScope {
    Series,
    DeviceRetention,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SeriesWindowLedger {
    pub scope: LedgerScope,
    pub device_id: String,
    pub provider_point_id: String,
    pub window_start: DateTime<Utc>,
    pub window_end: DateTime<Utc>,
    pub transport_probe: TransportProbe,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transport_code: Option<String>,
    pub requested_window: WindowCompleteness,
    pub durable_commit: DurableCommit,
    pub source_freshness: SourceFreshness,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub newest_source_ts: Option<DateTime<Utc>>,
    pub late_reconciliation: LateReconciliation,
    pub retention: RetentionState,
    /// Always false while the NF update log is unavailable.
    pub gapless: bool,
    pub update_log_status: String,
    /// Always false. Latest scrapes are not ledger inputs.
    pub from_latest_sample: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LatestProbe {
    pub provider_point_id: String,
    pub ts: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CoverageLedger {
    pub rows: Vec<SeriesWindowLedger>,
    pub gapless: bool,
    pub update_log_status: String,
    pub update_log_http: u16,
    /// Contiguous history coverage. Latest samples cannot move this.
    pub frontier: Option<DateTime<Utc>>,
    /// Same prefix, and only where the receipt is in Postgres.
    pub durable_frontier: Option<DateTime<Utc>>,
    pub ignored_latest_samples: usize,
}

impl CoverageLedger {
    pub fn pending() -> Self {
        Self {
            rows: Vec::new(),
            gapless: false,
            update_log_status: UPDATE_LOG_STATUS.into(),
            update_log_http: UPDATE_LOG_HTTP,
            frontier: None,
            durable_frontier: None,
            ignored_latest_samples: 0,
        }
    }
}

pub struct LedgerInput<'a> {
    pub jobs: &'a [JobRecord],
    pub receipts: &'a [ReceiptDraft],
    pub gaps: &'a [GapDraft],
    pub now: DateTime<Utc>,
    pub policy: &'a HourlyPolicy,
    pub durable_store: bool,
    /// Accepted and ignored. A latest scrape must not add rows or move the frontier.
    pub latest_samples: &'a [LatestProbe],
}

pub fn build_coverage_ledger(input: &LedgerInput<'_>) -> CoverageLedger {
    let mut rows = Vec::new();
    let mut hourly: BTreeMap<RowKey, &JobRecord> = BTreeMap::new();
    let mut reconcile: BTreeMap<RowKey, &JobRecord> = BTreeMap::new();
    for job in input.jobs {
        if job.purpose != "hourly" && job.purpose != "reconcile" {
            continue;
        }
        for point_id in &job.point_ids {
            let key = RowKey {
                device_id: job.device_id.clone(),
                model_revision: job.model_revision.clone(),
                provider_point_id: point_id.clone(),
                window_start: job.window_start,
            };
            let slot = if job.purpose == "hourly" {
                &mut hourly
            } else {
                &mut reconcile
            };
            match slot.get(&key) {
                Some(existing) if rank(existing) >= rank(job) => {}
                _ => {
                    slot.insert(key, job);
                }
            }
        }
    }
    for (key, job) in &hourly {
        let receipt = job
            .receipt_id
            .as_ref()
            .and_then(|id| input.receipts.iter().find(|row| &row.receipt_id == id));
        let fact = receipt.and_then(|row| {
            row.series_facts
                .iter()
                .find(|fact| fact.provider_point_id == key.provider_point_id)
        });
        let reconcile_job = reconcile.get(key).copied();
        rows.push(series_row(key, job, fact, receipt, reconcile_job, input));
    }
    for gap in input.gaps {
        if gap.recoverability != "unrecoverable" {
            continue;
        }
        rows.push(retention_row(gap));
    }
    rows.sort_by(|a, b| {
        (
            &a.device_id,
            &a.provider_point_id,
            a.window_start,
            a.scope as u8,
        )
            .cmp(&(
                &b.device_id,
                &b.provider_point_id,
                b.window_start,
                b.scope as u8,
            ))
    });
    let frontier = frontier_of(&rows, false);
    let durable_frontier = frontier_of(&rows, true);
    CoverageLedger {
        rows,
        gapless: false,
        update_log_status: UPDATE_LOG_STATUS.into(),
        update_log_http: UPDATE_LOG_HTTP,
        frontier,
        durable_frontier,
        ignored_latest_samples: input.latest_samples.len(),
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct RowKey {
    device_id: String,
    model_revision: String,
    provider_point_id: String,
    window_start: DateTime<Utc>,
}

fn rank(job: &JobRecord) -> u8 {
    match job.state {
        JobState::Committed => 5,
        JobState::Partial => 4,
        JobState::PermanentFailure => 3,
        JobState::RetryWait => 2,
        JobState::Leased => 1,
        JobState::Queued | JobState::Cancelled => 0,
    }
}

fn series_row(
    key: &RowKey,
    job: &JobRecord,
    fact: Option<&SeriesFact>,
    receipt: Option<&ReceiptDraft>,
    reconcile_job: Option<&JobRecord>,
    input: &LedgerInput<'_>,
) -> SeriesWindowLedger {
    let (transport_probe, transport_code) = transport_of(job);
    let retention = retention_of(input.gaps, &job.device_id, job.window_start);
    let requested_window = completeness_of(transport_probe, job, fact, receipt);
    let durable_commit = commit_of(job, receipt, input.durable_store);
    SeriesWindowLedger {
        scope: LedgerScope::Series,
        device_id: key.device_id.clone(),
        provider_point_id: key.provider_point_id.clone(),
        window_start: job.window_start,
        window_end: job.window_end,
        transport_probe,
        transport_code,
        requested_window,
        durable_commit,
        source_freshness: freshness_of(fact, job.window_end, input.policy.source_cadence),
        newest_source_ts: fact.and_then(|fact| fact.newest_ts),
        late_reconciliation: reconcile_of(
            job.window_start,
            job.window_end,
            reconcile_job,
            input.now,
            input.policy,
        ),
        retention,
        gapless: false,
        update_log_status: UPDATE_LOG_STATUS.into(),
        from_latest_sample: false,
    }
}

fn retention_row(gap: &GapDraft) -> SeriesWindowLedger {
    SeriesWindowLedger {
        scope: LedgerScope::DeviceRetention,
        device_id: gap.device_id.clone(),
        provider_point_id: String::new(),
        window_start: gap.window_start,
        window_end: gap.window_end,
        transport_probe: TransportProbe::NotRun,
        transport_code: Some(gap.reason.clone()),
        requested_window: WindowCompleteness::Unknown,
        durable_commit: DurableCommit::None,
        source_freshness: SourceFreshness::Unknown,
        newest_source_ts: None,
        late_reconciliation: LateReconciliation::OutsideBound,
        retention: RetentionState::UnrecoverableExpiry,
        gapless: false,
        update_log_status: UPDATE_LOG_STATUS.into(),
        from_latest_sample: false,
    }
}

fn transport_of(job: &JobRecord) -> (TransportProbe, Option<String>) {
    let code = job.safe_error_code.clone();
    match job.state {
        JobState::Committed => (TransportProbe::Ok, None),
        JobState::Partial => (TransportProbe::Ok, code),
        JobState::PermanentFailure | JobState::RetryWait => {
            if matches!(code.as_deref(), Some("partial_series" | "unmapped")) {
                (TransportProbe::Ok, code)
            } else {
                (TransportProbe::Failed, code)
            }
        }
        JobState::Queued | JobState::Leased | JobState::Cancelled => (TransportProbe::NotRun, code),
    }
}

fn completeness_of(
    transport: TransportProbe,
    job: &JobRecord,
    fact: Option<&SeriesFact>,
    receipt: Option<&ReceiptDraft>,
) -> WindowCompleteness {
    if transport != TransportProbe::Ok {
        return WindowCompleteness::Unknown;
    }
    if let Some(fact) = fact {
        if fact.missing {
            return WindowCompleteness::Partial;
        }
        if fact.in_window_samples == 0 {
            return WindowCompleteness::NoSourceData;
        }
        return WindowCompleteness::Complete;
    }
    if matches!(job.state, JobState::Partial) {
        return WindowCompleteness::Partial;
    }
    match receipt.map(|row| row.outcome.as_str()) {
        Some("no_source_data") => WindowCompleteness::NoSourceData,
        Some("samples") => WindowCompleteness::Complete,
        _ => WindowCompleteness::Unknown,
    }
}

fn commit_of(
    job: &JobRecord,
    receipt: Option<&ReceiptDraft>,
    durable_store: bool,
) -> DurableCommit {
    let Some(receipt) = receipt else {
        return DurableCommit::None;
    };
    if job.state != JobState::Committed {
        return DurableCommit::None;
    }
    if receipt.outcome == "samples"
        && receipt.accepted_count > 0
        && receipt.writer_acknowledged <= 0
    {
        return DurableCommit::None;
    }
    if durable_store {
        DurableCommit::DurableReceipt
    } else {
        DurableCommit::MemoryReceipt
    }
}

fn freshness_of(
    fact: Option<&SeriesFact>,
    window_end: DateTime<Utc>,
    cadence: Duration,
) -> SourceFreshness {
    let Some(fact) = fact else {
        return SourceFreshness::Unknown;
    };
    if fact.missing {
        return SourceFreshness::Unknown;
    }
    if fact.in_window_samples == 0 {
        return SourceFreshness::NoSamples;
    }
    if fact.in_window_samples == 1 {
        return SourceFreshness::SingleSample;
    }
    let Some(newest) = fact.newest_ts else {
        return SourceFreshness::Stale;
    };
    let slack = cadence * 3;
    if newest + slack >= window_end {
        SourceFreshness::WithinCadence
    } else {
        SourceFreshness::Stale
    }
}

fn retention_of(gaps: &[GapDraft], device_id: &str, window_start: DateTime<Utc>) -> RetentionState {
    if gaps.iter().any(|gap| {
        gap.device_id == device_id
            && gap.window_start == window_start
            && gap.recoverability == "unrecoverable"
    }) {
        RetentionState::UnrecoverableExpiry
    } else {
        RetentionState::Inside
    }
}

fn reconcile_of(
    window_start: DateTime<Utc>,
    window_end: DateTime<Utc>,
    job: Option<&JobRecord>,
    now: DateTime<Utc>,
    policy: &HourlyPolicy,
) -> LateReconciliation {
    if !in_reconcile_bound(window_start, window_end, now, policy) {
        return LateReconciliation::OutsideBound;
    }
    match job.map(|job| job.state) {
        Some(JobState::Committed) => LateReconciliation::Reconciled,
        Some(JobState::PermanentFailure | JobState::RetryWait | JobState::Partial) => {
            LateReconciliation::Failed
        }
        Some(JobState::Queued | JobState::Leased) => LateReconciliation::Pending,
        Some(JobState::Cancelled) | None => LateReconciliation::Pending,
    }
}

fn in_reconcile_bound(
    window_start: DateTime<Utc>,
    window_end: DateTime<Utc>,
    now: DateTime<Utc>,
    policy: &HourlyPolicy,
) -> bool {
    if policy.reconcile_hours <= 0 {
        return false;
    }
    let horizon = completed_hour_end(now, policy.publication_delay);
    let oldest = horizon - Duration::seconds(policy.reconcile_hours.saturating_mul(3600));
    window_start >= oldest && window_end <= horizon
}

fn covered(row: &SeriesWindowLedger, durable_only: bool) -> bool {
    if row.scope != LedgerScope::Series || row.from_latest_sample || row.gapless {
        return false;
    }
    if row.retention != RetentionState::Inside || row.transport_probe != TransportProbe::Ok {
        return false;
    }
    if !matches!(
        row.requested_window,
        WindowCompleteness::Complete | WindowCompleteness::NoSourceData
    ) {
        return false;
    }
    match row.durable_commit {
        DurableCommit::DurableReceipt => true,
        DurableCommit::MemoryReceipt => !durable_only,
        DurableCommit::None => false,
    }
}

fn frontier_of(rows: &[SeriesWindowLedger], durable_only: bool) -> Option<DateTime<Utc>> {
    let mut groups: BTreeMap<(String, String), Vec<&SeriesWindowLedger>> = BTreeMap::new();
    for row in rows {
        if row.scope != LedgerScope::Series {
            continue;
        }
        groups
            .entry((row.device_id.clone(), row.provider_point_id.clone()))
            .or_default()
            .push(row);
    }
    if groups.is_empty() {
        return None;
    }
    let mut frontiers = Vec::new();
    for group in groups.values_mut() {
        group.sort_by_key(|row| row.window_start);
        let mut cursor: Option<DateTime<Utc>> = None;
        let mut started = false;
        for row in group.iter() {
            if row.retention == RetentionState::UnrecoverableExpiry && cursor.is_none() && !started
            {
                continue;
            }
            started = true;
            if !covered(row, durable_only) {
                break;
            }
            if let Some(end) = cursor {
                if row.window_start != end {
                    break;
                }
            }
            cursor = Some(row.window_end);
        }
        frontiers.push(cursor);
    }
    if frontiers.iter().any(Option::is_none) {
        return None;
    }
    frontiers.into_iter().flatten().min()
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(hour: u32, min: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 19, hour, min, 0).unwrap()
    }

    fn policy(reconcile_hours: i64) -> HourlyPolicy {
        HourlyPolicy {
            reconcile_hours,
            ..HourlyPolicy::default()
        }
    }

    fn job(
        purpose: &str,
        state: JobState,
        start_hour: u32,
        point: &str,
        receipt: Option<&str>,
        code: Option<&str>,
    ) -> JobRecord {
        JobRecord {
            job_id: format!("{purpose}-{start_hour}-{point}"),
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: "rev".into(),
            window_start: ts(start_hour, 0),
            window_end: ts(start_hour + 1, 0),
            shard: 0,
            shard_count: 1,
            purpose: purpose.into(),
            generation: 0,
            state,
            attempt: 1,
            not_before: None,
            lease_owner: None,
            lease_expiry: None,
            fencing_token: 1,
            point_ids: vec![point.into()],
            fetched_count: 0,
            accepted_count: 0,
            rejected_count: 0,
            overlap_count: 0,
            writer_acknowledged: 0,
            received_at: None,
            committed_at: None,
            safe_error_code: code.map(str::to_string),
            receipt_id: receipt.map(str::to_string),
        }
    }

    fn receipt(
        id: &str,
        outcome: &str,
        samples: u32,
        newest_min: u32,
        missing: bool,
    ) -> ReceiptDraft {
        ReceiptDraft {
            receipt_id: id.into(),
            job_id: id.into(),
            outcome: outcome.into(),
            fetched_count: i32::try_from(samples).unwrap_or(0),
            accepted_count: i32::try_from(samples).unwrap_or(0),
            rejected_count: 0,
            overlap_count: 0,
            writer_acknowledged: i32::try_from(samples).unwrap_or(0),
            safe_code: outcome.into(),
            series_facts: vec![SeriesFact {
                provider_point_id: "p1".into(),
                in_window_samples: samples,
                newest_ts: if samples == 0 {
                    None
                } else {
                    Some(ts(9, newest_min))
                },
                missing,
            }],
        }
    }

    fn build(
        jobs: &[JobRecord],
        receipts: &[ReceiptDraft],
        gaps: &[GapDraft],
        latest: &[LatestProbe],
        durable: bool,
        reconcile_hours: i64,
    ) -> CoverageLedger {
        build_coverage_ledger(&LedgerInput {
            jobs,
            receipts,
            gaps,
            now: ts(13, 5),
            policy: &policy(reconcile_hours),
            durable_store: durable,
            latest_samples: latest,
        })
    }

    #[test]
    fn latest_sample_does_not_advance_the_ledger() {
        let empty = build(&[], &[], &[], &[], false, 2);
        assert!(empty.rows.is_empty());
        assert!(empty.frontier.is_none());
        assert!(!empty.gapless);
        assert_eq!(empty.update_log_http, 403);
        assert!(empty.update_log_status.contains("not_gapless"));

        let latest = [LatestProbe {
            provider_point_id: "p1".into(),
            ts: ts(12, 30),
        }];
        let ignored = build(&[], &[], &[], &latest, false, 2);
        assert_eq!(ignored.rows, empty.rows);
        assert_eq!(ignored.frontier, empty.frontier);
        assert_eq!(ignored.ignored_latest_samples, 1);

        let mut latest_job = job("latest", JobState::Committed, 12, "p1", Some("lat"), None);
        latest_job.accepted_count = 1;
        latest_job.writer_acknowledged = 1;
        let sneaky = build(
            &[latest_job],
            &[receipt("lat", "samples", 1, 30, false)],
            &[],
            &latest,
            true,
            2,
        );
        assert!(sneaky.rows.is_empty());
        assert!(sneaky.frontier.is_none());
        assert!(sneaky.durable_frontier.is_none());
        assert!(sneaky.rows.iter().all(|row| !row.from_latest_sample));
    }

    #[test]
    fn axes_stay_separate_and_memory_is_not_durable() {
        let mut hourly = job(
            "hourly",
            JobState::Committed,
            9,
            "p1",
            Some("r-samples"),
            None,
        );
        hourly.job_id = "r-samples".into();
        let facts = receipt("r-samples", "samples", 60, 59, false);
        let mut facts = facts;
        facts.series_facts[0].newest_ts = Some(ts(9, 59));
        facts.series_facts[0].in_window_samples = 60;
        let memory = build(
            std::slice::from_ref(&hourly),
            std::slice::from_ref(&facts),
            &[],
            &[],
            false,
            0,
        );
        let row = &memory.rows[0];
        assert_eq!(row.transport_probe, TransportProbe::Ok);
        assert_eq!(row.requested_window, WindowCompleteness::Complete);
        assert_eq!(row.durable_commit, DurableCommit::MemoryReceipt);
        assert_eq!(row.source_freshness, SourceFreshness::WithinCadence);
        assert_eq!(row.retention, RetentionState::Inside);
        assert_eq!(row.late_reconciliation, LateReconciliation::OutsideBound);
        assert!(!row.gapless);
        assert_eq!(memory.frontier, Some(ts(10, 0)));
        assert!(memory.durable_frontier.is_none());

        let durable = build(
            std::slice::from_ref(&hourly),
            std::slice::from_ref(&facts),
            &[],
            &[],
            true,
            0,
        );
        assert_eq!(durable.durable_frontier, Some(ts(10, 0)));
        assert_eq!(
            durable.rows[0].durable_commit,
            DurableCommit::DurableReceipt
        );
    }

    #[test]
    fn transport_failure_and_partial_do_not_move_the_frontier() {
        let failed = job(
            "hourly",
            JobState::RetryWait,
            9,
            "p1",
            None,
            Some("transport"),
        );
        let ledger = build(std::slice::from_ref(&failed), &[], &[], &[], true, 2);
        assert_eq!(ledger.rows[0].transport_probe, TransportProbe::Failed);
        assert_eq!(ledger.rows[0].transport_code.as_deref(), Some("transport"));
        assert_eq!(ledger.rows[0].requested_window, WindowCompleteness::Unknown);
        assert_eq!(ledger.rows[0].durable_commit, DurableCommit::None);
        assert!(ledger.frontier.is_none());

        let partial = job(
            "hourly",
            JobState::Partial,
            9,
            "p1",
            None,
            Some("partial_series"),
        );
        let ledger = build(std::slice::from_ref(&partial), &[], &[], &[], true, 2);
        assert_eq!(ledger.rows[0].transport_probe, TransportProbe::Ok);
        assert_eq!(ledger.rows[0].requested_window, WindowCompleteness::Partial);
        assert_eq!(ledger.rows[0].durable_commit, DurableCommit::None);
        assert!(ledger.frontier.is_none());
    }

    #[test]
    fn single_history_sample_is_not_within_cadence() {
        let hourly = job("hourly", JobState::Committed, 9, "p1", Some("r1"), None);
        let facts = receipt("r1", "samples", 1, 30, false);
        let ledger = build(
            std::slice::from_ref(&hourly),
            std::slice::from_ref(&facts),
            &[],
            &[],
            true,
            0,
        );
        assert_eq!(
            ledger.rows[0].source_freshness,
            SourceFreshness::SingleSample
        );
        assert_eq!(
            ledger.rows[0].requested_window,
            WindowCompleteness::Complete
        );
        assert_eq!(ledger.frontier, Some(ts(10, 0)));
        let with_latest = build(
            std::slice::from_ref(&hourly),
            std::slice::from_ref(&facts),
            &[],
            &[LatestProbe {
                provider_point_id: "p1".into(),
                ts: ts(12, 1),
            }],
            true,
            0,
        );
        assert_eq!(with_latest.frontier, ledger.frontier);
        assert_eq!(with_latest.rows.len(), ledger.rows.len());
    }

    #[test]
    fn explicit_empty_is_no_source_data_not_a_transport_success_alone() {
        let hourly = job("hourly", JobState::Committed, 9, "p1", Some("empty"), None);
        let facts = receipt("empty", "no_source_data", 0, 0, false);
        let ledger = build(
            std::slice::from_ref(&hourly),
            std::slice::from_ref(&facts),
            &[],
            &[],
            true,
            0,
        );
        assert_eq!(
            ledger.rows[0].requested_window,
            WindowCompleteness::NoSourceData
        );
        assert_eq!(ledger.rows[0].source_freshness, SourceFreshness::NoSamples);
        assert_eq!(ledger.rows[0].durable_commit, DurableCommit::DurableReceipt);
        assert_eq!(ledger.frontier, Some(ts(10, 0)));
    }

    #[test]
    fn writer_ack_missing_is_not_a_durable_commit() {
        let hourly = job("hourly", JobState::Committed, 9, "p1", Some("r"), None);
        let mut facts = receipt("r", "samples", 4, 50, false);
        facts.writer_acknowledged = 0;
        facts.accepted_count = 4;
        let ledger = build(
            std::slice::from_ref(&hourly),
            std::slice::from_ref(&facts),
            &[],
            &[],
            true,
            0,
        );
        assert_eq!(ledger.rows[0].durable_commit, DurableCommit::None);
        assert_eq!(
            ledger.rows[0].requested_window,
            WindowCompleteness::Complete
        );
        assert!(ledger.frontier.is_none());
    }

    #[test]
    fn reconciliation_is_bounded_to_recent_windows() {
        let mut jobs = Vec::new();
        let mut receipts = Vec::new();
        for hour in 8..13 {
            let id = format!("h{hour}");
            let mut row = job("hourly", JobState::Committed, hour, "p1", Some(&id), None);
            row.job_id = id.clone();
            jobs.push(row);
            let mut fact = receipt(&id, "samples", 10, 59, false);
            fact.series_facts[0].newest_ts = Some(ts(hour, 59));
            receipts.push(fact);
        }
        jobs.push(job(
            "reconcile",
            JobState::Committed,
            12,
            "p1",
            Some("rec12"),
            None,
        ));
        jobs.push(job(
            "reconcile",
            JobState::RetryWait,
            11,
            "p1",
            None,
            Some("transport"),
        ));
        let ledger = build(&jobs, &receipts, &[], &[], true, 2);
        let by_hour = |hour: u32| {
            ledger
                .rows
                .iter()
                .find(|row| row.scope == LedgerScope::Series && row.window_start == ts(hour, 0))
                .unwrap()
        };
        assert_eq!(
            by_hour(8).late_reconciliation,
            LateReconciliation::OutsideBound
        );
        assert_eq!(
            by_hour(10).late_reconciliation,
            LateReconciliation::OutsideBound
        );
        assert_eq!(by_hour(11).late_reconciliation, LateReconciliation::Failed);
        assert_eq!(
            by_hour(12).late_reconciliation,
            LateReconciliation::Reconciled
        );
        assert!(ledger.rows.iter().all(|row| !row.gapless));
        assert_eq!(ledger.frontier, Some(ts(13, 0)));
    }

    #[test]
    fn retention_expiry_is_unrecoverable_and_not_covered() {
        let gap = GapDraft {
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: "rev".into(),
            window_start: ts(8, 0),
            window_end: ts(9, 0),
            reason: "outside_retention".into(),
            recoverability: "unrecoverable".into(),
        };
        let hourly = job("hourly", JobState::Committed, 11, "p1", Some("r11"), None);
        let mut facts = receipt("r11", "samples", 8, 59, false);
        facts.series_facts[0].newest_ts = Some(ts(11, 59));
        let ledger = build(
            std::slice::from_ref(&hourly),
            std::slice::from_ref(&facts),
            std::slice::from_ref(&gap),
            &[],
            true,
            0,
        );
        let expired = ledger
            .rows
            .iter()
            .find(|row| row.scope == LedgerScope::DeviceRetention)
            .unwrap();
        assert_eq!(expired.retention, RetentionState::UnrecoverableExpiry);
        assert_eq!(expired.transport_probe, TransportProbe::NotRun);
        assert_eq!(expired.durable_commit, DurableCommit::None);
        assert_eq!(expired.requested_window, WindowCompleteness::Unknown);
        assert!(!expired.gapless);
        assert_eq!(ledger.frontier, Some(ts(12, 0)));
    }
}
