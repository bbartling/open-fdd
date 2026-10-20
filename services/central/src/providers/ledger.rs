//! Coverage ledger (N7) over N5 hourly jobs, receipts, checkpoints, and gaps.
//!
//! The axes are independent:
//! transport probe, requested-window completeness, durable commit, source
//! freshness, late reconciliation, and unrecoverable retention expiry.
//! A latest sample is not an input. Bounded time-range reads plus a recent
//! reconciliation sweep are not a gapless update log.

use std::collections::{BTreeMap, HashMap};

use chrono::{DateTime, Utc};

use super::hourly::{completed_window_end, HourlyPolicy, UPDATE_LOG_STATUS};
use super::store::{CoverageFacts, JobRecord, JobState};
use super::types::{AxisId, AxisState, CoverageGuarantee, CoverageLedger, LedgerAxis};

pub struct LedgerContext {
    pub durable_store: bool,
    pub now: DateTime<Utc>,
    pub policy: HourlyPolicy,
}

pub fn build_ledger(facts: &CoverageFacts, ctx: &LedgerContext) -> CoverageLedger {
    let ledger = assemble(facts, ctx);
    observe_latest_sample(ledger, 0, None)
}

/// Latest scrapes do not move checkpoints, receipts, or any ledger axis.
pub fn observe_latest_sample(
    ledger: CoverageLedger,
    samples: u64,
    newest: Option<DateTime<Utc>>,
) -> CoverageLedger {
    let _ = (samples, newest);
    debug_assert!(!ledger.advanced_by_latest_sample);
    debug_assert!(!ledger.gapless);
    ledger
}

#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "conformance tests read one ledger axis without comparing the whole snapshot"
    )
)]
#[expect(
    clippy::expect_used,
    reason = "assemble inserts every AxisId; a missing axis is a programming bug, and Option would change the test helper contract"
)]
pub fn axis(ledger: &CoverageLedger, id: AxisId) -> &LedgerAxis {
    ledger
        .axes
        .iter()
        .find(|axis| axis.id == id)
        .expect("ledger contains every axis")
}

fn assemble(facts: &CoverageFacts, ctx: &LedgerContext) -> CoverageLedger {
    let outcomes = receipt_outcomes(facts);
    let windows = rollup_hourly(&facts.jobs, &outcomes);
    let windows_complete = count_u32(windows.iter().filter(|w| w.class == WindowClass::Complete));
    let windows_incomplete = count_u32(
        windows
            .iter()
            .filter(|w| w.class == WindowClass::Incomplete),
    );
    let windows_pending = count_u32(windows.iter().filter(|w| w.class == WindowClass::Pending));
    let transport_failures = count_u32(facts.jobs.iter().filter(|job| transport_failure(job)));
    let probe_ok = count_u32(facts.jobs.iter().filter(|job| probe_succeeded(job)));
    let durable_receipts = count_u32(
        facts
            .jobs
            .iter()
            .filter(|job| durable_receipt(job, &outcomes)),
    );
    let reconcile_committed = count_u32(
        facts
            .jobs
            .iter()
            .filter(|job| job.purpose == "reconcile" && job.state == JobState::Committed),
    );
    let reconcile_open = count_u32(facts.jobs.iter().filter(|job| {
        job.purpose == "reconcile"
            && !matches!(job.state, JobState::Committed | JobState::Cancelled)
    }));
    let unrecoverable_gaps =
        count_u32(facts.gaps.iter().filter(|gap| {
            gap.recoverability == "unrecoverable" || gap.reason == "outside_retention"
        }));
    let reconcile_hours = ctx.policy.reconcile_hours.max(0);
    let guarantee = CoverageGuarantee {
        mode: "bounded_time_range_plus_recent_reconcile".into(),
        history_method: "GET".into(),
        history_path: "/api/v1/point/data".into(),
        update_log_method: "GET".into(),
        update_log_path: "/api/v1/point/updates/data".into(),
        update_log_observed_http: 403,
        update_log_called: false,
        update_log_status: UPDATE_LOG_STATUS.into(),
        reconcile_hours,
        gapless: false,
        statement: format!(
            "NF update log GET /api/v1/point/updates/data returned HTTP 403 on the lab key. History is bounded GET /api/v1/point/data plus recent reconciliation of {reconcile_hours} hour(s). Range polling is not gapless."
        ),
    };
    CoverageLedger {
        axes: vec![
            transport_axis(transport_failures, probe_ok),
            window_axis(windows_complete, windows_incomplete, windows_pending),
            durable_axis(ctx.durable_store, &facts.jobs, durable_receipts),
            freshness_axis(facts, ctx),
            reconcile_axis(reconcile_hours, reconcile_committed, reconcile_open),
            retention_axis(unrecoverable_gaps, !facts.checkpoints.is_empty()),
        ],
        guarantee,
        windows_complete,
        windows_incomplete,
        windows_pending,
        transport_failures,
        durable_receipts,
        reconcile_committed,
        reconcile_open,
        unrecoverable_gaps,
        gapless: false,
        advanced_by_latest_sample: false,
    }
}

fn receipt_outcomes(facts: &CoverageFacts) -> HashMap<String, String> {
    facts
        .receipts
        .iter()
        .map(|receipt| (receipt.receipt_id.clone(), receipt.outcome.clone()))
        .collect()
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum WindowClass {
    Complete,
    Incomplete,
    Pending,
}

struct WindowRollup {
    class: WindowClass,
}

fn rollup_hourly(jobs: &[JobRecord], outcomes: &HashMap<String, String>) -> Vec<WindowRollup> {
    let mut groups: BTreeMap<(String, String, i64, i64), Vec<&JobRecord>> = BTreeMap::new();
    for job in jobs {
        if job.purpose != "hourly" || job.generation != 0 {
            continue;
        }
        groups
            .entry((
                job.device_id.clone(),
                job.model_revision.clone(),
                job.window_start.timestamp(),
                job.window_end.timestamp(),
            ))
            .or_default()
            .push(job);
    }
    groups
        .into_values()
        .map(|group| WindowRollup {
            class: classify_window(&group, outcomes),
        })
        .collect()
}

fn classify_window(group: &[&JobRecord], outcomes: &HashMap<String, String>) -> WindowClass {
    let shard_count = group.iter().map(|job| job.shard_count).max().unwrap_or(0);
    if shard_count <= 0 {
        return WindowClass::Incomplete;
    }
    let mut committed_ok = vec![false; usize::try_from(shard_count).unwrap_or(0)];
    let mut pending = vec![false; committed_ok.len()];
    for job in group {
        let Some(index) = usize::try_from(job.shard).ok() else {
            return WindowClass::Incomplete;
        };
        if index >= committed_ok.len() {
            return WindowClass::Incomplete;
        }
        match job.state {
            JobState::Committed => {
                committed_ok[index] = receipt_covers_commit(job, outcomes);
            }
            JobState::Queued | JobState::Leased => pending[index] = true,
            JobState::RetryWait
            | JobState::Partial
            | JobState::PermanentFailure
            | JobState::Cancelled => {}
        }
    }
    if committed_ok.iter().all(|ok| *ok) {
        WindowClass::Complete
    } else if pending.iter().all(|wait| *wait) && committed_ok.iter().all(|ok| !*ok) {
        WindowClass::Pending
    } else {
        WindowClass::Incomplete
    }
}

fn receipt_covers_commit(job: &JobRecord, outcomes: &HashMap<String, String>) -> bool {
    let Some(receipt_id) = job.receipt_id.as_deref() else {
        return false;
    };
    let Some(outcome) = outcomes.get(receipt_id) else {
        return false;
    };
    matches!(outcome.as_str(), "samples" | "no_source_data")
        && job.writer_acknowledged >= job.accepted_count
}

fn transport_failure(job: &JobRecord) -> bool {
    job.safe_error_code
        .as_deref()
        .is_some_and(|code| matches!(code, "transport" | "deadline_exceeded"))
}

fn probe_succeeded(job: &JobRecord) -> bool {
    matches!(job.state, JobState::Committed | JobState::Partial)
}

fn durable_receipt(job: &JobRecord, outcomes: &HashMap<String, String>) -> bool {
    job.state == JobState::Committed && receipt_covers_commit(job, outcomes)
}

fn transport_axis(failures: u32, probe_ok: u32) -> LedgerAxis {
    let (state, detail) = if failures > 0 && probe_ok == 0 {
        (
            AxisState::Failed,
            format!("history transport probe failed ({failures}); a latest sample is not a probe"),
        )
    } else if failures > 0 {
        (
            AxisState::Degraded,
            format!(
                "history transport probe failed for {failures} job(s) beside {probe_ok} page(s)"
            ),
        )
    } else if probe_ok > 0 {
        (
            AxisState::Ok,
            "history GET returned a page for the requested window".into(),
        )
    } else {
        (
            AxisState::Unknown,
            "no history transport probe yet; a latest sample does not count".into(),
        )
    };
    LedgerAxis {
        id: AxisId::TransportProbe,
        state,
        detail,
    }
}

fn window_axis(complete: u32, incomplete: u32, pending: u32) -> LedgerAxis {
    let (state, detail) = if complete == 0 && incomplete == 0 && pending == 0 {
        (
            AxisState::Unknown,
            "no requested history window; one latest sample does not complete a window".into(),
        )
    } else if incomplete > 0 {
        (
            AxisState::Degraded,
            format!(
                "requested windows complete={complete} incomplete={incomplete} pending={pending}"
            ),
        )
    } else if pending > 0 {
        (
            AxisState::Unknown,
            format!("requested windows still pending={pending}; complete={complete}"),
        )
    } else {
        (
            AxisState::Ok,
            format!("requested windows complete={complete}"),
        )
    };
    LedgerAxis {
        id: AxisId::RequestedWindowCompleteness,
        state,
        detail,
    }
}

fn durable_axis(durable_store: bool, jobs: &[JobRecord], receipts: u32) -> LedgerAxis {
    let committed = count_u32(jobs.iter().filter(|job| job.state == JobState::Committed));
    let (state, detail) = if !durable_store {
        (
            AxisState::NotClaimed,
            "job store is memory; receipts are not a durable commit".into(),
        )
    } else if committed == 0 {
        (
            AxisState::Unknown,
            "no committed history receipt in the durable store".into(),
        )
    } else if receipts < committed {
        (
            AxisState::Failed,
            format!("durable store is missing a covering receipt for {committed} committed job(s)"),
        )
    } else {
        (AxisState::Ok, format!("durable receipts={receipts}"))
    };
    LedgerAxis {
        id: AxisId::DurableCommit,
        state,
        detail,
    }
}

fn freshness_axis(facts: &CoverageFacts, ctx: &LedgerContext) -> LedgerAxis {
    let Some(oldest) = facts
        .checkpoints
        .iter()
        .map(|checkpoint| checkpoint.contiguous_end)
        .min()
    else {
        return LedgerAxis {
            id: AxisId::SourceFreshness,
            state: AxisState::Unknown,
            detail: "no history cursor; a latest sample does not establish freshness".into(),
        };
    };
    let horizon = completed_window_end(
        ctx.now,
        ctx.policy.publication_delay,
        ctx.policy.window_secs,
    );
    if oldest >= horizon {
        LedgerAxis {
            id: AxisId::SourceFreshness,
            state: AxisState::Ok,
            detail: "history cursor covers the last completed hour".into(),
        }
    } else {
        LedgerAxis {
            id: AxisId::SourceFreshness,
            state: AxisState::Degraded,
            detail: "history cursor lags the completed hour; not inferred from a latest sample"
                .into(),
        }
    }
}

fn reconcile_axis(hours: i64, committed: u32, open: u32) -> LedgerAxis {
    let (state, detail) = if hours <= 0 {
        (
            AxisState::NotClaimed,
            "reconcile sweep disabled; range polling is not gapless".into(),
        )
    } else if open > 0 {
        (
            AxisState::Degraded,
            format!(
                "bounded reconcile of {hours} hour(s) has {open} open job(s); range polling is not gapless"
            ),
        )
    } else if committed > 0 {
        (
            AxisState::Ok,
            format!(
                "bounded reconcile of {hours} hour(s) committed {committed} job(s); range polling is not gapless"
            ),
        )
    } else {
        (
            AxisState::Unknown,
            format!(
                "bounded reconcile of {hours} hour(s) has not run; range polling is not gapless"
            ),
        )
    };
    LedgerAxis {
        id: AxisId::LateReconciliation,
        state,
        detail,
    }
}

fn retention_axis(gaps: u32, has_cursor: bool) -> LedgerAxis {
    let (state, detail) = if gaps > 0 {
        (
            AxisState::Degraded,
            format!("unrecoverable retention gaps={gaps}; those hours were not fetched"),
        )
    } else if has_cursor {
        (
            AxisState::Ok,
            "no unrecoverable retention gap recorded".into(),
        )
    } else {
        (
            AxisState::Unknown,
            "retention has not been evaluated".into(),
        )
    };
    LedgerAxis {
        id: AxisId::UnrecoverableRetention,
        state,
        detail,
    }
}

fn count_u32<T>(iter: impl Iterator<Item = T>) -> u32 {
    u32::try_from(iter.count()).unwrap_or(u32::MAX)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::store::{CheckpointFact, GapDraft, ReceiptFact};
    use chrono::{Duration, TimeZone};

    fn ts(hour: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 19, hour, 0, 0).unwrap()
    }

    fn ctx(durable: bool) -> LedgerContext {
        LedgerContext {
            durable_store: durable,
            now: ts(10) + Duration::minutes(5),
            policy: HourlyPolicy {
                reconcile_hours: 2,
                stagger_spread_secs: 0,
                ..HourlyPolicy::default()
            },
        }
    }

    fn job(state: JobState, purpose: &str, receipt: Option<&str>) -> JobRecord {
        JobRecord {
            job_id: format!("{purpose}-{}", state.as_str()),
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: "rev".into(),
            window_start: ts(9),
            window_end: ts(10),
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
            point_ids: vec!["p1".into()],
            fetched_count: 1,
            accepted_count: 1,
            rejected_count: 0,
            overlap_count: 0,
            writer_acknowledged: 1,
            received_at: Some(ts(10)),
            committed_at: None,
            safe_error_code: None,
            receipt_id: receipt.map(str::to_string),
        }
    }

    fn facts_with(job: JobRecord, outcome: &str) -> CoverageFacts {
        let receipt_id = job.receipt_id.clone().unwrap_or_else(|| "r".into());
        CoverageFacts {
            jobs: vec![job],
            gaps: Vec::new(),
            checkpoints: vec![CheckpointFact {
                device_id: "dev-1".into(),
                model_revision: "rev".into(),
                contiguous_end: ts(10),
            }],
            receipts: vec![ReceiptFact {
                receipt_id,
                job_id: "job".into(),
                outcome: outcome.into(),
            }],
        }
    }

    #[test]
    fn empty_ledger_states_the_403_and_ignores_a_latest_sample() {
        let ledger = build_ledger(&CoverageFacts::default(), &ctx(true));
        assert!(!ledger.gapless);
        assert!(!ledger.advanced_by_latest_sample);
        assert!(!ledger.guarantee.gapless);
        assert!(!ledger.guarantee.update_log_called);
        assert_eq!(ledger.guarantee.update_log_observed_http, 403);
        assert_eq!(ledger.guarantee.history_method, "GET");
        assert_eq!(ledger.guarantee.history_path, "/api/v1/point/data");
        assert_eq!(
            ledger.guarantee.update_log_path,
            "/api/v1/point/updates/data"
        );
        assert!(ledger.guarantee.statement.contains("HTTP 403"));
        assert!(ledger.guarantee.statement.contains("not gapless"));
        assert_eq!(ledger.windows_complete, 0);
        assert_eq!(
            axis(&ledger, AxisId::SourceFreshness).state,
            AxisState::Unknown
        );
        assert_eq!(
            axis(&ledger, AxisId::RequestedWindowCompleteness).state,
            AxisState::Unknown
        );
        let advanced = observe_latest_sample(ledger.clone(), 1, Some(ts(10)));
        assert_eq!(advanced, ledger);
    }

    #[test]
    fn transport_failure_does_not_complete_a_window_or_a_durable_commit() {
        let mut failed = job(JobState::RetryWait, "hourly", None);
        failed.safe_error_code = Some("transport".into());
        failed.writer_acknowledged = 0;
        failed.accepted_count = 0;
        let facts = CoverageFacts {
            jobs: vec![failed],
            ..CoverageFacts::default()
        };
        let ledger = build_ledger(&facts, &ctx(true));
        assert_eq!(
            axis(&ledger, AxisId::TransportProbe).state,
            AxisState::Failed
        );
        assert_eq!(ledger.windows_complete, 0);
        assert_eq!(
            axis(&ledger, AxisId::RequestedWindowCompleteness).state,
            AxisState::Degraded
        );
        assert_eq!(
            axis(&ledger, AxisId::DurableCommit).state,
            AxisState::Unknown
        );
        assert_ne!(axis(&ledger, AxisId::SourceFreshness).state, AxisState::Ok);
    }

    #[test]
    fn one_accepted_sample_on_a_partial_page_is_not_window_completeness() {
        let partial = job(JobState::Partial, "hourly", None);
        let facts = CoverageFacts {
            jobs: vec![partial],
            ..CoverageFacts::default()
        };
        let ledger = build_ledger(&facts, &ctx(true));
        assert_eq!(ledger.windows_complete, 0);
        assert_eq!(
            axis(&ledger, AxisId::RequestedWindowCompleteness).state,
            AxisState::Degraded
        );
        assert_eq!(axis(&ledger, AxisId::TransportProbe).state, AxisState::Ok);
        assert_eq!(
            axis(&ledger, AxisId::DurableCommit).state,
            AxisState::Unknown
        );
    }

    #[test]
    fn durable_commit_requires_the_postgres_store_and_a_receipt() {
        let committed = job(JobState::Committed, "hourly", Some("r-1"));
        let memory = build_ledger(&facts_with(committed.clone(), "samples"), &ctx(false));
        assert_eq!(memory.windows_complete, 1);
        assert_eq!(
            axis(&memory, AxisId::DurableCommit).state,
            AxisState::NotClaimed
        );
        let durable = build_ledger(&facts_with(committed, "samples"), &ctx(true));
        assert_eq!(axis(&durable, AxisId::DurableCommit).state, AxisState::Ok);
        assert_eq!(durable.durable_receipts, 1);
        assert_eq!(
            axis(&durable, AxisId::RequestedWindowCompleteness).state,
            AxisState::Ok
        );
        assert!(!durable.gapless);
    }

    #[test]
    fn short_writer_ack_is_not_a_durable_receipt() {
        let mut committed = job(JobState::Committed, "hourly", Some("r-1"));
        committed.accepted_count = 60;
        committed.writer_acknowledged = 1;
        let ledger = build_ledger(&facts_with(committed, "samples"), &ctx(true));
        assert_eq!(ledger.windows_complete, 0);
        assert_eq!(
            axis(&ledger, AxisId::DurableCommit).state,
            AxisState::Failed
        );
    }

    #[test]
    fn reconcile_commit_stays_bounded_and_retention_stays_separate() {
        let mut reconcile = job(JobState::Committed, "reconcile", Some("r-2"));
        reconcile.generation = 1_700_000_000;
        let mut facts = facts_with(reconcile, "samples");
        facts.gaps.push(GapDraft {
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: "rev".into(),
            window_start: ts(8),
            window_end: ts(9),
            reason: "outside_retention".into(),
            recoverability: "unrecoverable".into(),
        });
        facts.checkpoints[0].contiguous_end = ts(9);
        let ledger = build_ledger(&facts, &ctx(true));
        assert_eq!(
            axis(&ledger, AxisId::LateReconciliation).state,
            AxisState::Ok
        );
        assert!(axis(&ledger, AxisId::LateReconciliation)
            .detail
            .contains("not gapless"));
        assert_eq!(
            axis(&ledger, AxisId::UnrecoverableRetention).state,
            AxisState::Degraded
        );
        assert_eq!(ledger.unrecoverable_gaps, 1);
        assert_eq!(ledger.windows_complete, 0);
        assert!(!ledger.gapless);
        assert!(ledger.guarantee.statement.contains("HTTP 403"));
    }
}
