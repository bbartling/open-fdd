//! Device-hour coverage ledger.
//!
//! This is a read model over N5 hourly jobs, receipts, and gaps. A device-hour
//! becomes covered only when every shard of that history window is durably
//! committed and has a receipt. A latest sample is not an input. Memory-store
//! commits do not advance coverage. NF `GET /api/v1/point/updates/data` returned
//! HTTP 403, so this ledger does not describe a gapless cursor.

use chrono::{DateTime, Duration, Utc};
use serde::Serialize;

use super::hourly::{
    COVERAGE_GUARANTEE, UPDATE_LOG_HTTP, UPDATE_LOG_OBSERVED_ON, UPDATE_LOG_PATH, UPDATE_LOG_STATUS,
};
use super::store::{GapDraft, JobRecord, JobState, ReceiptDraft};

pub const HISTORY_WINDOW_SOURCE: &str = "history_window";
pub const ADVANCED_FROM_COMMIT: &str = "durable_committed_history_window";
pub const NOT_ADVANCED: &str = "not_advanced";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LedgerQuery {
    pub durable: bool,
    pub reconcile_hours: i64,
    pub truncated: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DeviceHourRow {
    pub device_id: String,
    pub model_revision: String,
    pub window_start: DateTime<Utc>,
    pub window_end: DateTime<Utc>,
    pub status: String,
    pub covered: bool,
    pub durable: bool,
    pub source: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub receipt_ids: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gap_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub recoverability: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reconcile_state: Option<String>,
    pub within_reconcile_bound: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct DeviceCoverage {
    pub device_id: String,
    pub model_revision: String,
    pub covered_through: Option<DateTime<Utc>>,
    pub advanced_from: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UpdateLogStatement {
    pub method_path: String,
    pub http_status: u16,
    pub observed_on: String,
    pub called: bool,
    pub gapless: bool,
    pub status: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CoverageLedger {
    pub gapless: bool,
    pub guarantee: String,
    pub update_log: UpdateLogStatement,
    pub durable: bool,
    pub truncated: bool,
    pub reconcile_hours: i64,
    pub devices: Vec<DeviceCoverage>,
    pub hours: Vec<DeviceHourRow>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct WindowKey {
    device_id: String,
    model_revision: String,
    window_start: DateTime<Utc>,
    window_end: DateTime<Utc>,
}

pub fn update_log_statement() -> UpdateLogStatement {
    UpdateLogStatement {
        method_path: UPDATE_LOG_PATH.to_string(),
        http_status: UPDATE_LOG_HTTP,
        observed_on: UPDATE_LOG_OBSERVED_ON.to_string(),
        called: false,
        gapless: false,
        status: UPDATE_LOG_STATUS.to_string(),
    }
}

pub fn project_ledger(
    jobs: &[JobRecord],
    gaps: &[GapDraft],
    receipts: &[ReceiptDraft],
    query: &LedgerQuery,
) -> CoverageLedger {
    let receipt_by_id: std::collections::HashMap<&str, &ReceiptDraft> = receipts
        .iter()
        .map(|receipt| (receipt.receipt_id.as_str(), receipt))
        .collect();
    let mut keys: Vec<WindowKey> = Vec::new();
    for job in jobs {
        if is_history_job(job) {
            push_key(
                &mut keys,
                &job.device_id,
                &job.model_revision,
                job.window_start,
                job.window_end,
            );
        }
    }
    for gap in gaps {
        push_key(
            &mut keys,
            &gap.device_id,
            &gap.model_revision,
            gap.window_start,
            gap.window_end,
        );
    }
    keys.sort_by(|a, b| {
        (&a.device_id, &a.model_revision, a.window_start).cmp(&(
            &b.device_id,
            &b.model_revision,
            b.window_start,
        ))
    });
    keys.dedup_by(|a, b| {
        a.device_id == b.device_id
            && a.model_revision == b.model_revision
            && a.window_start == b.window_start
            && a.window_end == b.window_end
    });

    let mut hours = Vec::new();
    for key in &keys {
        let hourly: Vec<&JobRecord> = jobs
            .iter()
            .filter(|job| job.purpose == "hourly" && same_window(job, key))
            .collect();
        let reconcile_state = reconcile_state(jobs, key);
        let gap = gaps.iter().find(|gap| {
            gap.device_id == key.device_id
                && gap.model_revision == key.model_revision
                && gap.window_start == key.window_start
                && gap.window_end == key.window_end
        });
        let (status, covered, receipt_ids) =
            classify_hour(&hourly, &receipt_by_id, query.durable, gap);
        hours.push(DeviceHourRow {
            device_id: key.device_id.clone(),
            model_revision: key.model_revision.clone(),
            window_start: key.window_start,
            window_end: key.window_end,
            status,
            covered,
            durable: query.durable,
            source: HISTORY_WINDOW_SOURCE.to_string(),
            receipt_ids,
            gap_reason: gap.map(|gap| gap.reason.clone()),
            recoverability: gap.map(|gap| gap.recoverability.clone()),
            reconcile_state,
            within_reconcile_bound: false,
        });
    }

    let mut devices = Vec::new();
    let mut index = 0;
    while index < hours.len() {
        let device_id = hours[index].device_id.clone();
        let revision = hours[index].model_revision.clone();
        let start = index;
        while index < hours.len()
            && hours[index].device_id == device_id
            && hours[index].model_revision == revision
        {
            index += 1;
        }
        let covered_through = if query.truncated {
            None
        } else {
            contiguous_covered(&hours[start..index])
        };
        for row in &mut hours[start..index] {
            row.within_reconcile_bound =
                in_reconcile_bound(row.window_end, covered_through, query.reconcile_hours);
        }
        devices.push(DeviceCoverage {
            device_id,
            model_revision: revision,
            covered_through,
            advanced_from: if covered_through.is_some() {
                ADVANCED_FROM_COMMIT.to_string()
            } else {
                NOT_ADVANCED.to_string()
            },
        });
    }
    hours.sort_by(|a, b| {
        b.window_start
            .cmp(&a.window_start)
            .then(a.device_id.cmp(&b.device_id))
    });

    CoverageLedger {
        gapless: false,
        guarantee: COVERAGE_GUARANTEE.to_string(),
        update_log: update_log_statement(),
        durable: query.durable,
        truncated: query.truncated,
        reconcile_hours: query.reconcile_hours,
        devices,
        hours,
    }
}

fn is_history_job(job: &JobRecord) -> bool {
    job.purpose == "hourly" || job.purpose == "reconcile"
}

fn push_key(
    keys: &mut Vec<WindowKey>,
    device_id: &str,
    model_revision: &str,
    window_start: DateTime<Utc>,
    window_end: DateTime<Utc>,
) {
    keys.push(WindowKey {
        device_id: device_id.to_string(),
        model_revision: model_revision.to_string(),
        window_start,
        window_end,
    });
}

fn same_window(job: &JobRecord, key: &WindowKey) -> bool {
    job.device_id == key.device_id
        && job.model_revision == key.model_revision
        && job.window_start == key.window_start
        && job.window_end == key.window_end
}

fn reconcile_state(jobs: &[JobRecord], key: &WindowKey) -> Option<String> {
    let mut found: Vec<&JobRecord> = jobs
        .iter()
        .filter(|job| job.purpose == "reconcile" && same_window(job, key))
        .collect();
    found.sort_by_key(|job| job.generation);
    found.last().map(|job| job.state.as_str().to_string())
}

fn classify_hour(
    hourly: &[&JobRecord],
    receipts: &std::collections::HashMap<&str, &ReceiptDraft>,
    durable: bool,
    gap: Option<&GapDraft>,
) -> (String, bool, Vec<String>) {
    if hourly.is_empty() {
        return ("gap".into(), false, Vec::new());
    }
    let shard_count = hourly.iter().map(|job| job.shard_count).max().unwrap_or(0);
    let mut receipt_ids = Vec::new();
    let mut outcomes = Vec::new();
    let fully_committed = shard_count > 0
        && (0..shard_count).all(|shard| {
            hourly.iter().any(|job| {
                if job.shard != shard || job.state != JobState::Committed {
                    return false;
                }
                let Some(receipt_id) = job.receipt_id.as_deref() else {
                    return false;
                };
                let Some(receipt) = receipts.get(receipt_id) else {
                    return false;
                };
                if !receipt_ids.iter().any(|id: &String| id == receipt_id) {
                    receipt_ids.push(receipt_id.to_string());
                    outcomes.push(receipt.outcome.clone());
                }
                true
            })
        });
    if fully_committed {
        let status = if outcomes.iter().all(|outcome| outcome == "no_source_data") {
            "no_source_data"
        } else {
            "committed"
        };
        if durable {
            return (status.into(), true, receipt_ids);
        }
        return ("not_durable".into(), false, receipt_ids);
    }
    if hourly.iter().any(|job| job.state == JobState::Partial) {
        return ("partial".into(), false, receipt_ids);
    }
    if hourly
        .iter()
        .any(|job| job.state == JobState::PermanentFailure)
        && hourly.iter().all(|job| {
            matches!(
                job.state,
                JobState::PermanentFailure | JobState::Cancelled | JobState::Committed
            )
        })
    {
        let _ = gap;
        return ("failed".into(), false, receipt_ids);
    }
    ("pending".into(), false, receipt_ids)
}

fn contiguous_covered(rows: &[DeviceHourRow]) -> Option<DateTime<Utc>> {
    let mut expect: Option<DateTime<Utc>> = None;
    let mut cursor = None;
    for row in rows {
        if let Some(next) = expect {
            if row.window_start != next {
                break;
            }
        }
        if !row.covered {
            break;
        }
        cursor = Some(row.window_end);
        expect = Some(row.window_end);
    }
    cursor
}

fn in_reconcile_bound(
    window_end: DateTime<Utc>,
    covered_through: Option<DateTime<Utc>>,
    hours: i64,
) -> bool {
    let Some(end) = covered_through else {
        return false;
    };
    if hours <= 0 || window_end > end {
        return false;
    }
    window_end > end - Duration::hours(hours)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn ts(hour: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 10, 19, hour, 0, 0).unwrap()
    }

    fn job(
        purpose: &str,
        hour: u32,
        state: JobState,
        receipt: Option<&str>,
        generation: i64,
    ) -> JobRecord {
        JobRecord {
            job_id: format!("{purpose}-{hour}-{generation}"),
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: "rev".into(),
            window_start: ts(hour),
            window_end: ts(hour) + Duration::hours(1),
            shard: 0,
            shard_count: 1,
            purpose: purpose.into(),
            generation,
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
            received_at: Some(ts(hour)),
            committed_at: Some(ts(hour)),
            safe_error_code: None,
            receipt_id: receipt.map(str::to_string),
        }
    }

    fn receipt(id: &str, outcome: &str) -> ReceiptDraft {
        ReceiptDraft {
            receipt_id: id.into(),
            job_id: id.into(),
            outcome: outcome.into(),
            fetched_count: 1,
            accepted_count: 1,
            rejected_count: 0,
            overlap_count: 0,
            writer_acknowledged: 1,
            safe_code: outcome.into(),
        }
    }

    fn gap(hour: u32, reason: &str) -> GapDraft {
        GapDraft {
            tenant: "default".into(),
            canonical_site: "site-a".into(),
            provider_instance: "nf:site-a".into(),
            device_id: "dev-1".into(),
            model_revision: "rev".into(),
            window_start: ts(hour),
            window_end: ts(hour) + Duration::hours(1),
            reason: reason.into(),
            recoverability: "unrecoverable".into(),
        }
    }

    fn query(durable: bool) -> LedgerQuery {
        LedgerQuery {
            durable,
            reconcile_hours: 2,
            truncated: false,
        }
    }

    #[test]
    fn durable_commits_advance_and_latest_does_not() {
        let jobs = vec![
            job("hourly", 8, JobState::Committed, Some("r8"), 0),
            job("hourly", 9, JobState::Committed, Some("r9"), 0),
            job("latest", 10, JobState::Committed, Some("latest"), 0),
        ];
        let receipts = vec![receipt("r8", "samples"), receipt("r9", "samples")];
        let mut narrow = query(true);
        narrow.reconcile_hours = 1;
        let ledger = project_ledger(&jobs, &[], &receipts, &narrow);
        assert!(!ledger.gapless);
        assert_eq!(ledger.update_log.http_status, 403);
        assert_eq!(ledger.update_log.method_path, UPDATE_LOG_PATH);
        assert!(!ledger.update_log.called);
        assert!(ledger.guarantee.contains("not gapless"));
        assert!(ledger.guarantee.contains("403"));
        assert_eq!(ledger.devices.len(), 1);
        assert_eq!(ledger.devices[0].covered_through, Some(ts(10)));
        assert_eq!(ledger.devices[0].advanced_from, ADVANCED_FROM_COMMIT);
        assert!(ledger
            .hours
            .iter()
            .all(|row| row.source == HISTORY_WINDOW_SOURCE));
        assert!(ledger.hours.iter().all(|row| row.covered));
        assert_eq!(ledger.hours.len(), 2);
        assert!(ledger
            .hours
            .iter()
            .any(|row| row.window_start == ts(9) && row.within_reconcile_bound));
        assert!(ledger
            .hours
            .iter()
            .any(|row| row.window_start == ts(8) && !row.within_reconcile_bound));
    }

    #[test]
    fn memory_commits_and_holes_do_not_advance() {
        let jobs = vec![
            job("hourly", 8, JobState::Committed, Some("r8"), 0),
            job("hourly", 10, JobState::Committed, Some("r10"), 0),
        ];
        let receipts = vec![receipt("r8", "samples"), receipt("r10", "no_source_data")];
        let memory = project_ledger(&jobs, &[], &receipts, &query(false));
        assert!(memory.devices[0].covered_through.is_none());
        assert!(memory.hours.iter().all(|row| !row.covered));
        assert!(memory.hours.iter().all(|row| row.status == "not_durable"));

        let durable = project_ledger(&jobs, &[], &receipts, &query(true));
        assert_eq!(durable.devices[0].covered_through, Some(ts(9)));
        assert!(durable.hours.iter().any(|row| row.window_start == ts(10)
            && row.covered
            && row.status == "no_source_data"));
    }

    #[test]
    fn gap_and_reconcile_do_not_cover_a_missing_commit() {
        let jobs = vec![
            job("hourly", 8, JobState::Committed, Some("r8"), 0),
            job("reconcile", 8, JobState::Committed, Some("rec"), 99),
            job("reconcile", 9, JobState::Queued, None, 99),
        ];
        let ledger = project_ledger(
            &jobs,
            &[gap(9, "outside_retention")],
            &[receipt("r8", "samples")],
            &query(true),
        );
        assert_eq!(ledger.devices[0].covered_through, Some(ts(9)));
        let gap_row = ledger
            .hours
            .iter()
            .find(|row| row.window_start == ts(9))
            .unwrap();
        assert!(!gap_row.covered);
        assert_eq!(gap_row.status, "gap");
        assert_eq!(gap_row.gap_reason.as_deref(), Some("outside_retention"));
        assert!(
            gap_row.reconcile_state.is_none()
                || gap_row.reconcile_state.as_deref() == Some("queued")
        );
        let covered = ledger
            .hours
            .iter()
            .find(|row| row.window_start == ts(8))
            .unwrap();
        assert!(covered.covered);
        assert_eq!(covered.reconcile_state.as_deref(), Some("committed"));
        assert!(covered.within_reconcile_bound);
    }

    #[test]
    fn truncated_snapshot_does_not_publish_a_cursor() {
        let jobs = vec![job("hourly", 8, JobState::Committed, Some("r8"), 0)];
        let mut query = query(true);
        query.truncated = true;
        let ledger = project_ledger(&jobs, &[], &[receipt("r8", "samples")], &query);
        assert!(ledger.truncated);
        assert!(ledger.devices[0].covered_through.is_none());
        assert_eq!(ledger.devices[0].advanced_from, NOT_ADVANCED);
        assert!(ledger.hours[0].covered);
    }
}
