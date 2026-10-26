//! One scheduler owner plus leased workers. API replicas do not poll.

use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tracing::{info, warn};
use uuid::Uuid;

use crate::providers::poller;
use crate::providers::types::ProviderKind;
use crate::state::AppState;

use super::client::{Coordination, QueueClient};
use crate::providers::committed_model::IngestPlan;

use super::coverage::{
    expectation_from_fields, reconcile, CoverageError, PointExpectation, PointObservation,
    ReconcileInput, INCOMPLETE,
};
use super::model::{
    points_digest, revision_still_owns, AppliedSample, FinishOutcome, FinishRequest, JobCounts,
    JobView, QueueError,
};
use super::schedule::{self, ScheduleDevice};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProcessRole {
    Api,
    Worker,
    Combined,
}

pub fn process_role() -> ProcessRole {
    match std::env::var("OPENFDD_PROCESS_ROLE")
        .ok()
        .map(|value| value.trim().to_ascii_lowercase())
        .as_deref()
    {
        Some("api") => ProcessRole::Api,
        Some("worker") => ProcessRole::Worker,
        Some("combined" | "all") | None => ProcessRole::Combined,
        Some(_) => ProcessRole::Combined,
    }
}

pub fn poll_enabled() -> bool {
    std::env::var("OPENFDD_PROVIDER_POLL")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
}

pub fn starts_independent_site_loops() -> bool {
    process_role() != ProcessRole::Api && legacy_poll_mode() && unsafe_poller_allowed()
}

pub fn spawn_with_shutdown(
    state: Arc<AppState>,
    mut shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        if !poll_enabled() {
            info!("OPENFDD_PROVIDER_POLL not enabled; provider worker idle");
            return;
        }
        if process_role() == ProcessRole::Api {
            info!("OPENFDD_PROCESS_ROLE=api; this process does not start provider pollers");
            return;
        }
        if starts_independent_site_loops() {
            warn!(
                "OPENFDD_PROVIDER_POLL_MODE=legacy with OPENFDD_ALLOW_UNSAFE_POLLER=1; independent site loops are not replica-safe"
            );
            poller::run_legacy_site_loops(state, &mut shutdown).await;
            return;
        }
        match QueueClient::coordination() {
            Coordination::Postgres | Coordination::ExplicitMemory => {
                run_queue_worker(state, &mut shutdown).await;
            }
            Coordination::Unavailable => {
                warn!(
                    "shared ingest queue unavailable; not starting per-site pollers. Set OPENFDD_DATABASE_URL for replicas or OPENFDD_INGEST_QUEUE=memory for one process"
                );
            }
        }
    })
}

async fn run_queue_worker(state: Arc<AppState>, shutdown: &mut watch::Receiver<bool>) {
    let owner = worker_id();
    info!(%owner, "ingest queue worker starting");
    let mut ticker = tokio::time::interval(Duration::from_secs(tick_secs()));
    loop {
        tokio::select! {
            _ = ticker.tick() => {}
            changed = shutdown.changed() => {
                if changed.is_err() || *shutdown.borrow() {
                    break;
                }
            }
        }
        if *shutdown.borrow() {
            break;
        }
        if let Err(err) = tick(&state, &owner).await {
            warn!(error = %err, "ingest queue tick failed");
        }
    }
    info!(%owner, "ingest queue worker stopped");
}

async fn tick(state: &Arc<AppState>, owner: &str) -> Result<(), String> {
    let now = Utc::now();
    let ttl = chrono::Duration::seconds(30);
    if let Some(grant) = state
        .ingest_queue
        .try_scheduler(owner, now, ttl)
        .await
        .map_err(|err| err.to_string())?
    {
        let still_owner = state
            .ingest_queue
            .renew_scheduler(owner, grant.fencing_token, now, ttl)
            .await
            .map_err(|err| err.to_string())?;
        if !still_owner {
            return Ok(());
        }
        enqueue_due_windows(state, now).await?;
    }
    let claimed = state
        .ingest_queue
        .claim(&super::model::ClaimRequest {
            owner: owner.to_string(),
            limit: max_concurrent(),
            now,
            lease_for: chrono::Duration::seconds(180),
        })
        .await
        .map_err(|err| err.to_string())?;
    let mut tasks = Vec::new();
    for job in claimed {
        let state = Arc::clone(state);
        let owner = owner.to_string();
        tasks.push(tokio::spawn(async move {
            let decision = execute_job(&state, &job).await;
            let mut finish = FinishRequest::new(
                owner,
                job.job_id,
                job.fencing_token,
                Utc::now(),
                decision.outcome,
            );
            finish.active_model_revision = decision.active_model_revision;
            finish.active_points_digest = decision.active_points_digest;
            finish.applied_samples = decision.applied_samples;
            if let Err(err) = state.ingest_queue.finish(&finish).await {
                warn!(job_id = %job.job_id, error = %err, "ingest finish rejected");
            }
        }));
    }
    for task in tasks {
        if let Err(err) = task.await {
            warn!(error = %err, "ingest worker task ended");
        }
    }
    Ok(())
}

struct WindowDecision {
    outcome: FinishOutcome,
    applied_samples: Vec<AppliedSample>,
    active_model_revision: Option<String>,
    active_points_digest: Option<String>,
}

impl WindowDecision {
    fn bare(outcome: FinishOutcome) -> Self {
        Self {
            outcome,
            applied_samples: Vec::new(),
            active_model_revision: None,
            active_points_digest: None,
        }
    }
}

async fn execute_job(state: &Arc<AppState>, job: &JobView) -> WindowDecision {
    let plan = {
        let models = state
            .providers
            .models
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match models.active_plan(&job.tenant_id, &job.canonical_site) {
            Some(plan) if committed_tuple_matches(job, plan) => Some(plan.clone()),
            Some(_) | None => None,
        }
    };
    let Some(plan) = plan else {
        return WindowDecision::bare(FinishOutcome::Permanent {
            code: "plan_identity_mismatch".into(),
        });
    };
    let active_revision = Some(plan.revision_id.clone());
    let expectations = expectations_for(&plan, job);
    let active_digest = Some(points_digest(
        &expectations
            .iter()
            .map(|point| point.point_id.clone())
            .collect::<Vec<_>>(),
    ));
    if !revision_still_owns(&job.model_revision, plan.revision_id.as_str()) {
        return WindowDecision {
            outcome: FinishOutcome::Permanent {
                code: "model_revision_changed".into(),
            },
            applied_samples: Vec::new(),
            active_model_revision: active_revision,
            active_points_digest: active_digest,
        };
    }
    let Some(site) = state.providers.sites.iter().find(|site| {
        site.building_id == job.canonical_site
            && site.tenant_id == job.tenant_id
            && crate::providers::http_policy::provider_ids_equivalent(
                &site.provider_instance_id,
                &job.provider_instance_id,
            )
    }) else {
        return WindowDecision::bare(FinishOutcome::Permanent {
            code: "site_not_configured".into(),
        });
    };
    if matches!(site.kind, ProviderKind::AceIot) {
        return WindowDecision::bare(FinishOutcome::Permanent {
            code: "not_implemented".into(),
        });
    }
    let page = match poller::fetch_device_window(
        state,
        site,
        &job.device_id,
        job.logical_window_start,
        job.logical_window_end,
    )
    .await
    {
        Ok(page) => page,
        Err(err) => {
            return WindowDecision::bare(finish_for_poll_error(state, job, &err).await);
        }
    };
    let plan_after = {
        let models = state
            .providers
            .models
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        models
            .active_plan(&job.tenant_id, &job.canonical_site)
            .filter(|active| committed_tuple_matches(job, active))
            .map(|active| active.revision_id.clone())
    };
    if plan_after.as_deref() != Some(plan.revision_id.as_str()) {
        return WindowDecision {
            outcome: FinishOutcome::Permanent {
                code: "model_revision_changed".into(),
            },
            applied_samples: Vec::new(),
            active_model_revision: plan_after,
            active_points_digest: active_digest,
        };
    }
    let observations = observations_for(&expectations, &page);
    let response_complete = page
        .iter()
        .map(|series| series.samples.len())
        .sum::<usize>()
        < crate::providers::http_policy::MAX_SAMPLES_PER_RESPONSE;
    let coverage = reconcile(&ReconcileInput {
        start: job.logical_window_start,
        end: job.logical_window_end,
        expectations: &expectations,
        observations: &observations,
        prior: &job.point_coverage,
        response_complete,
    });
    let coverage = match coverage {
        Ok(report) => report,
        Err(CoverageError::InvalidWindow) => {
            return WindowDecision::bare(FinishOutcome::Permanent {
                code: "invalid_window".into(),
            });
        }
        Err(CoverageError::PayloadBound) => {
            record_window_health(state, &job.canonical_site, 0, 0, 1, 0, "payload_bound").await;
            return WindowDecision::bare(FinishOutcome::Partial {
                counts: JobCounts::default(),
                code: "payload_bound".into(),
                coverage: super::coverage::CoverageReport {
                    summary: INCOMPLETE.to_string(),
                    points: Vec::new(),
                    duplicate_timestamps: 0,
                    out_of_window: 0,
                },
            });
        }
    };
    let device = device_for_write(&plan, job);
    let applied = applied_samples(&page, job.logical_window_start, job.logical_window_end);
    let written = match persist_window(state, site, device.as_ref(), job, &page, &applied).await {
        Ok(receipt) => receipt,
        Err(PersistFailure::StaleFence) => {
            warn!(job_id = %job.job_id, "ingest lease lost before the canonical write; nothing written");
            return WindowDecision::bare(FinishOutcome::Retry {
                code: "stale_fence".into(),
                not_before: Utc::now(),
            });
        }
        Err(PersistFailure::Poll(err)) => {
            return WindowDecision::bare(finish_for_poll_error(state, job, &err).await);
        }
    };
    let outcome = decide_window(&DecideWindow {
        job_revision: &job.model_revision,
        active_revision: Some(plan.revision_id.as_str()),
        job_digest: None,
        active_digest: None,
        coverage: &coverage,
        attempt: job.attempt,
        now: Utc::now(),
        written: &written,
        applied: &applied,
    });
    let committed = u32::from(matches!(outcome, FinishOutcome::Committed { .. }));
    let partial = u32::from(matches!(outcome, FinishOutcome::Partial { .. }));
    let failed = u32::from(matches!(
        outcome,
        FinishOutcome::Retry { .. } | FinishOutcome::Permanent { .. }
    ));
    let detail = if coverage.allows_commit() {
        coverage.summary.clone()
    } else {
        coverage.block_code()
    };
    let handed = u64::try_from(written.persisted_rows).unwrap_or(u64::MAX);
    record_window_health(
        state,
        &job.canonical_site,
        committed,
        partial,
        failed,
        handed,
        detail.as_str(),
    )
    .await;
    WindowDecision {
        outcome,
        applied_samples: applied,
        active_model_revision: active_revision,
        active_points_digest: active_digest,
    }
}

enum PersistFailure {
    /// The claim no longer owns the window. Nothing reached canonical history.
    StaleFence,
    Poll(String),
}

const EMPTY_RECEIPT: crate::providers::writer::ProviderIngestReceipt =
    crate::providers::writer::ProviderIngestReceipt {
        submitted: 0,
        eligible: 0,
        skipped: 0,
        persisted_rows: 0,
        inserted_rows: 0,
        updated_rows: 0,
    };

/// Canonical samples and ledger rows for one claimed window. With a shared
/// Postgres queue the lease check, the Timescale upsert, and the ledger rows
/// commit in one transaction. The process-memory queue has no shared fence
/// and keeps the live-writer path.
async fn persist_window(
    state: &Arc<AppState>,
    site: &crate::providers::config::SiteConfig,
    device: Option<&crate::providers::map::DevicePoints>,
    job: &JobView,
    page: &[crate::providers::map::HistorySeries],
    applied: &[AppliedSample],
) -> Result<crate::providers::writer::ProviderIngestReceipt, PersistFailure> {
    if crate::timescale_historian::historian_is_timescale() {
        let accepted = device.map(|device| {
            poller::accept_device_window(
                &site.building_id,
                &site.provider_instance_id,
                device,
                page,
                crate::providers::hourly::LogicalWindow {
                    start: job.logical_window_start,
                    end: job.logical_window_end,
                },
            )
            .samples
        });
        let samples = accepted.unwrap_or_default();
        let projected = crate::providers::writer::canonical_rows(&site.building_id, &samples)
            .map_err(|err| PersistFailure::Poll(err.code.as_str().to_string()))?;
        let equip_type = device.and_then(|device| {
            device
                .points
                .iter()
                .find_map(|point| point.equip_type.as_deref())
        });
        let window = super::postgres::CanonicalWindow {
            equip_type,
            rows: &projected.rows,
            applied,
        };
        match state
            .ingest_queue
            .commit_window(job, Utc::now(), &window)
            .await
        {
            Ok(Some(write)) => {
                if !samples.is_empty() {
                    state.note_ingest_ok();
                }
                return Ok(crate::providers::writer::ProviderIngestReceipt {
                    submitted: samples.len(),
                    eligible: projected.rows.len(),
                    skipped: projected.skipped,
                    persisted_rows: usize::try_from(write.samples.persisted())
                        .unwrap_or(usize::MAX),
                    inserted_rows: usize::try_from(write.samples.inserted).unwrap_or(usize::MAX),
                    updated_rows: usize::try_from(write.samples.updated).unwrap_or(usize::MAX),
                });
            }
            Ok(None) => {}
            Err(QueueError::StaleFence) => return Err(PersistFailure::StaleFence),
            Err(err) => {
                warn!(job_id = %job.job_id, error = %err, "fenced canonical write failed");
                state
                    .providers
                    .record_error(
                        &site.building_id,
                        crate::providers::types::ProviderHealthStatus::Error,
                        Some("persistence".into()),
                    )
                    .await;
                return Err(PersistFailure::Poll("persistence".into()));
            }
        }
    }
    let written = match device {
        Some(device) => poller::write_device_window(
            state,
            site,
            device,
            page,
            job.logical_window_start,
            job.logical_window_end,
        )
        .await
        .map_err(PersistFailure::Poll)?,
        None => EMPTY_RECEIPT,
    };
    if let Err(err) = state.ingest_queue.apply_samples(job, applied).await {
        warn!(job_id = %job.job_id, error = %err, "ingest apply ledger rejected");
        return Err(PersistFailure::Poll("persistence".into()));
    }
    Ok(written)
}

fn expectations_for(plan: &IngestPlan, job: &JobView) -> Vec<PointExpectation> {
    plan.groups
        .iter()
        .find(|group| {
            group.equipment_id == job.device_id
                && crate::providers::http_policy::provider_ids_equivalent(
                    &group.provider_instance_id,
                    &job.provider_instance_id,
                )
        })
        .map(|group| {
            group
                .points
                .iter()
                .map(|point| PointExpectation {
                    point_id: point.source_point_id.clone(),
                    expectation: expectation_from_fields(
                        point.history_mode.as_deref(),
                        point.cadence_secs,
                        point.heartbeat_secs,
                        None,
                    ),
                })
                .collect()
        })
        .unwrap_or_default()
}

fn observations_for(
    expectations: &[PointExpectation],
    page: &[crate::providers::map::HistorySeries],
) -> Vec<PointObservation> {
    expectations
        .iter()
        .map(|expected| {
            let series = page
                .iter()
                .find(|series| series.provider_point_id == expected.point_id);
            PointObservation {
                point_id: expected.point_id.clone(),
                returned: series.is_some(),
                timestamps: series
                    .map(|series| series.samples.iter().map(|sample| sample.ts).collect())
                    .unwrap_or_default(),
            }
        })
        .collect()
}

fn device_for_write(
    plan: &IngestPlan,
    job: &JobView,
) -> Option<crate::providers::map::DevicePoints> {
    let group = plan.groups.iter().find(|group| {
        group.equipment_id == job.device_id
            && crate::providers::http_policy::provider_ids_equivalent(
                &group.provider_instance_id,
                &job.provider_instance_id,
            )
    })?;
    Some(crate::providers::map::DevicePoints {
        device_id: job.device_id.clone(),
        points: group
            .points
            .iter()
            .map(|point| crate::providers::map::MappedPoint {
                provider_point_id: point.source_point_id.clone(),
                role: point.canonical_role.clone(),
                equip_type: Some(group.equip_type.clone()),
                configured_units: point.source_unit.clone(),
            })
            .collect(),
    })
}

fn applied_samples(
    page: &[crate::providers::map::HistorySeries],
    start: chrono::DateTime<Utc>,
    end: chrono::DateTime<Utc>,
) -> Vec<AppliedSample> {
    let mut out = Vec::new();
    for series in page {
        for sample in &series.samples {
            if sample.ts < start || sample.ts >= end {
                continue;
            }
            if out.iter().any(|row: &AppliedSample| {
                row.point_id == series.provider_point_id && row.ts == sample.ts
            }) {
                continue;
            }
            out.push(AppliedSample {
                point_id: series.provider_point_id.clone(),
                ts: sample.ts,
                value_bits: sample.val.to_bits(),
            });
        }
    }
    out
}

struct DecideWindow<'a> {
    job_revision: &'a str,
    active_revision: Option<&'a str>,
    job_digest: Option<&'a str>,
    active_digest: Option<&'a str>,
    coverage: &'a super::coverage::CoverageReport,
    attempt: u32,
    now: chrono::DateTime<Utc>,
    written: &'a crate::providers::writer::ProviderIngestReceipt,
    applied: &'a [AppliedSample],
}

fn decide_window(input: &DecideWindow<'_>) -> FinishOutcome {
    if let Some(active) = input.active_revision {
        if !revision_still_owns(input.job_revision, active) {
            return FinishOutcome::Permanent {
                code: "model_revision_changed".into(),
            };
        }
    }
    if let (Some(stored), Some(active)) = (input.job_digest, input.active_digest) {
        if stored != active {
            return FinishOutcome::Permanent {
                code: "model_revision_changed".into(),
            };
        }
    }
    let counts = JobCounts {
        fetched: u32::try_from(input.applied.len()).unwrap_or(u32::MAX),
        accepted: u32::try_from(input.written.eligible).unwrap_or(u32::MAX),
        rejected: u32::try_from(input.written.skipped).unwrap_or(0),
        inserted: u32::try_from(input.written.inserted_rows).unwrap_or(u32::MAX),
        updated: 0,
        unchanged: u32::try_from(
            input
                .written
                .persisted_rows
                .saturating_sub(input.written.inserted_rows),
        )
        .unwrap_or(0),
    };
    if input.coverage.allows_commit() {
        return FinishOutcome::Committed {
            counts,
            coverage: input.coverage.clone(),
        };
    }
    if input.coverage.retryable_source_failure() {
        return classify_poll_error(SOURCE_RETRY, input.attempt, input.now);
    }
    FinishOutcome::Partial {
        counts,
        code: input.coverage.block_code(),
        coverage: input.coverage.clone(),
    }
}

const SOURCE_RETRY: &str = "source_unavailable";

async fn record_window_health(
    state: &Arc<AppState>,
    building_id: &str,
    committed: u32,
    partial: u32,
    failed: u32,
    samples_handed_off: u64,
    detail: &str,
) {
    let status = if partial > 0 || failed > 0 {
        crate::providers::types::ProviderHealthStatus::Degraded
    } else {
        crate::providers::types::ProviderHealthStatus::Ok
    };
    state
        .providers
        .record_hourly(
            building_id,
            status,
            0,
            Some(detail.to_string()),
            crate::providers::types::HourlyCoverageHealth {
                durable: true,
                committed,
                partial,
                failed,
                samples_handed_off,
                update_log_status: crate::providers::hourly::UPDATE_LOG_STATUS.to_string(),
                detail: detail.to_string(),
                ..crate::providers::types::HourlyCoverageHealth::default()
            },
            failed > 0,
        )
        .await;
}

async fn finish_for_poll_error(state: &Arc<AppState>, job: &JobView, err: &str) -> FinishOutcome {
    if err == "device_unmapped" {
        return FinishOutcome::Permanent {
            code: err.to_string(),
        };
    }
    if portal_throttled(err) {
        if let Err(note_err) = state
            .ingest_queue
            .note_throttle(
                &job.provider_instance_id,
                Utc::now(),
                chrono::Duration::seconds(60),
            )
            .await
        {
            warn!(error = %note_err, "portal throttle note failed");
        }
    }
    classify_poll_error(err, job.attempt, Utc::now())
}

fn classify_poll_error(err: &str, attempt: u32, now: chrono::DateTime<Utc>) -> FinishOutcome {
    if err == "device_unmapped" || err == "not_implemented" {
        return FinishOutcome::Permanent {
            code: err.to_string(),
        };
    }
    let code = if err == "source_unavailable" {
        "source_unavailable".to_string()
    } else if portal_throttled(err) {
        "throttled".to_string()
    } else if portal_timeout(err) {
        "timeout".to_string()
    } else if err == "persistence" || err == "auth_failed" {
        err.to_string()
    } else {
        "provider_poll_failed".to_string()
    };
    if attempt >= 8 {
        FinishOutcome::Permanent { code }
    } else {
        let backoff = (30i64 * 2i64.saturating_pow(attempt.saturating_sub(1))).min(900);
        FinishOutcome::Retry {
            code,
            not_before: now + chrono::Duration::seconds(backoff),
        }
    }
}

fn portal_timeout(err: &str) -> bool {
    let lower = err.to_ascii_lowercase();
    lower.contains("timeout") || lower.contains("timed out") || lower.contains("deadline")
}

fn portal_throttled(err: &str) -> bool {
    let lower = err.to_ascii_lowercase();
    lower.contains("429") || lower.contains("too many") || lower.contains("throttled")
}

/// Plan due windows and enqueue them. Identity mismatches are warned and
/// written onto provider health; they are not dropped quietly.
pub(crate) async fn enqueue_due_windows(
    state: &Arc<AppState>,
    now: chrono::DateTime<Utc>,
) -> Result<usize, String> {
    let (devices, mismatches) = devices_from_state(state);
    for (building_id, code) in &mismatches {
        state.providers.note_plan_identity(building_id, code).await;
    }
    let planned = schedule::due_windows(
        now,
        chrono::Duration::seconds(publication_delay_secs() as i64),
        catchup_hours(),
        300,
        crate::providers::hourly::HourlyPolicy::from_env().window_secs,
        &devices,
    );
    let count = planned.len();
    for job in planned {
        state
            .ingest_queue
            .enqueue(job, now)
            .await
            .map_err(|err| err.to_string())?;
    }
    Ok(count)
}

fn devices_from_state(state: &AppState) -> (Vec<ScheduleDevice>, Vec<(String, &'static str)>) {
    let mut devices = Vec::new();
    let mut mismatches = Vec::new();
    for site in &state.providers.sites {
        let plan = {
            let models = state
                .providers
                .models
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            models
                .active_plan(&site.tenant_id, &site.building_id)
                .cloned()
        };
        let Some(plan) = plan else {
            warn!(
                building_id = %site.building_id,
                tenant_id = %site.tenant_id,
                provider_instance_id = %site.provider_instance_id,
                reason = "plan_not_committed",
                "ingest site skipped; no committed ingest plan"
            );
            mismatches.push((site.building_id.clone(), "plan_not_committed"));
            continue;
        };
        match crate::providers::committed_model::schedule_plan_devices(
            &site.tenant_id,
            &site.building_id,
            &site.provider_instance_id,
            &plan,
        ) {
            Ok(planned) => {
                devices.extend(planned.into_iter().map(|device| {
                    let point_ids = plan
                        .groups
                        .iter()
                        .find(|group| group.equipment_id == device.equipment_id)
                        .map(|group| {
                            group
                                .points
                                .iter()
                                .map(|point| point.source_point_id.clone())
                                .collect()
                        })
                        .unwrap_or_default();
                    ScheduleDevice {
                        tenant_id: site.tenant_id.clone(),
                        canonical_site: site.building_id.clone(),
                        provider_instance_id: device.provider_instance_id,
                        device_id: device.equipment_id,
                        model_revision: device.revision_id,
                        estimated_cost: device.estimated_cost,
                        point_ids,
                    }
                }));
            }
            Err(code) => {
                let plan_providers: Vec<&str> = plan
                    .groups
                    .iter()
                    .map(|group| group.provider_instance_id.as_str())
                    .collect();
                warn!(
                    building_id = %site.building_id,
                    tenant_id = %site.tenant_id,
                    provider_instance_id = %site.provider_instance_id,
                    plan_tenant_id = %plan.tenant_id,
                    plan_site_id = %plan.site_id,
                    plan_providers = ?plan_providers,
                    reason = code,
                    "ingest site skipped; committed plan identity does not match the configured site"
                );
                mismatches.push((site.building_id.clone(), code));
            }
        }
    }
    (devices, mismatches)
}

pub(crate) fn committed_tuple_matches(job: &JobView, plan: &IngestPlan) -> bool {
    let revision_ok = job.model_revision == plan.revision_id
        || job.model_revision == super::model::MODEL_REVISION_BOOTSTRAP;
    revision_ok
        && job.tenant_id == plan.tenant_id
        && job.canonical_site == plan.site_id
        && plan.groups.iter().any(|group| {
            group.equipment_id == job.device_id
                && crate::providers::http_policy::provider_ids_equivalent(
                    &group.provider_instance_id,
                    &job.provider_instance_id,
                )
        })
}

fn worker_id() -> String {
    std::env::var("OPENFDD_WORKER_ID")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| {
            let host = std::env::var("HOSTNAME").unwrap_or_else(|_| "worker".into());
            format!("{host}-{}", Uuid::new_v4().simple())
        })
}

fn legacy_poll_mode() -> bool {
    std::env::var("OPENFDD_PROVIDER_POLL_MODE")
        .ok()
        .is_some_and(|value| value.trim().eq_ignore_ascii_case("legacy"))
}

fn unsafe_poller_allowed() -> bool {
    std::env::var("OPENFDD_ALLOW_UNSAFE_POLLER")
        .ok()
        .is_some_and(|value| matches!(value.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
}

fn env_tick_secs(key: &str) -> Option<u64> {
    std::env::var(key)
        .ok()
        .and_then(|value| value.trim().parse().ok())
        .filter(|value| *value >= 5)
}

fn tick_secs() -> u64 {
    env_tick_secs("OPENFDD_PROVIDER_TICK_SECS")
        .or_else(|| env_tick_secs("OPENFDD_INGEST_TICK_SECS"))
        .unwrap_or(15)
}

fn publication_delay_secs() -> u64 {
    std::env::var("OPENFDD_INGEST_PUBLICATION_DELAY_SECS")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(300)
}

fn catchup_hours() -> u32 {
    std::env::var("OPENFDD_INGEST_CATCHUP_HOURS")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(6)
        .clamp(1, super::model::MAX_CATCHUP_HOURS)
}

fn max_concurrent() -> usize {
    std::env::var("OPENFDD_PROVIDER_MAX_CONCURRENT")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value > 0)
        .unwrap_or(2)
        .clamp(1, 32)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn api_role_never_starts_independent_pollers() {
        let _guard = crate::test_env_lock::lock_env();
        let prev_role = std::env::var("OPENFDD_PROCESS_ROLE").ok();
        let prev_mode = std::env::var("OPENFDD_PROVIDER_POLL_MODE").ok();
        let prev_unsafe = std::env::var("OPENFDD_ALLOW_UNSAFE_POLLER").ok();
        std::env::set_var("OPENFDD_PROCESS_ROLE", "api");
        std::env::set_var("OPENFDD_PROVIDER_POLL_MODE", "legacy");
        std::env::set_var("OPENFDD_ALLOW_UNSAFE_POLLER", "1");
        assert!(!starts_independent_site_loops());
        std::env::set_var("OPENFDD_PROCESS_ROLE", "worker");
        assert!(starts_independent_site_loops());
        std::env::remove_var("OPENFDD_ALLOW_UNSAFE_POLLER");
        assert!(!starts_independent_site_loops());
        restore("OPENFDD_PROCESS_ROLE", prev_role);
        restore("OPENFDD_PROVIDER_POLL_MODE", prev_mode);
        restore("OPENFDD_ALLOW_UNSAFE_POLLER", prev_unsafe);
    }

    #[test]
    fn unmapped_device_does_not_retry() {
        let now = Utc::now();
        assert!(matches!(
            classify_poll_error("device_unmapped", 1, now),
            FinishOutcome::Permanent { code } if code == "device_unmapped"
        ));
        assert!(matches!(
            classify_poll_error("auth_failed", 1, now),
            FinishOutcome::Retry { .. }
        ));
    }

    #[test]
    fn provider_tick_secs_overrides_ingest_tick() {
        let _guard = crate::test_env_lock::lock_env();
        let prev_provider = std::env::var("OPENFDD_PROVIDER_TICK_SECS").ok();
        let prev_ingest = std::env::var("OPENFDD_INGEST_TICK_SECS").ok();
        std::env::set_var("OPENFDD_INGEST_TICK_SECS", "40");
        std::env::remove_var("OPENFDD_PROVIDER_TICK_SECS");
        assert_eq!(tick_secs(), 40);
        std::env::set_var("OPENFDD_PROVIDER_TICK_SECS", "15");
        assert_eq!(tick_secs(), 15);
        std::env::set_var("OPENFDD_PROVIDER_TICK_SECS", "1");
        assert_eq!(tick_secs(), 40);
        std::env::remove_var("OPENFDD_PROVIDER_TICK_SECS");
        std::env::remove_var("OPENFDD_INGEST_TICK_SECS");
        assert_eq!(tick_secs(), 15);
        restore("OPENFDD_PROVIDER_TICK_SECS", prev_provider);
        restore("OPENFDD_INGEST_TICK_SECS", prev_ingest);
    }

    fn restore(key: &str, prev: Option<String>) {
        match prev {
            Some(value) => std::env::set_var(key, value),
            None => std::env::remove_var(key),
        }
    }

    #[test]
    fn schedule_uses_the_committed_plan_tuple() {
        let plan = crate::providers::committed_model::IngestPlan {
            schema: "plan".into(),
            revision_id: "rev-plan".into(),
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            groups: vec![crate::providers::committed_model::IngestDeviceGroup {
                provider_instance_id: "portal-a".into(),
                equipment_id: "device-a".into(),
                equip_type: "ahu".into(),
                points: vec![],
            }],
            withheld: Vec::new(),
        };
        let devices = crate::providers::committed_model::schedule_plan_devices(
            "tenant-a", "site-a", "portal-a", &plan,
        )
        .expect("matching plan");
        assert_eq!(devices.len(), 1);
        assert_eq!(devices[0].revision_id, "rev-plan");
        assert_eq!(devices[0].equipment_id, "device-a");
        assert_eq!(
            crate::providers::committed_model::schedule_plan_devices(
                "tenant-b", "site-a", "portal-a", &plan,
            ),
            Err("plan_tenant_mismatch")
        );
        let job = JobView {
            job_id: Uuid::nil(),
            tenant_id: "tenant-a".into(),
            canonical_site: "site-a".into(),
            provider_instance_id: "portal-b".into(),
            device_id: "device-a".into(),
            model_revision: "rev-plan".into(),
            logical_window_start: Utc::now(),
            logical_window_end: Utc::now(),
            shard: String::new(),
            state: "queued".into(),
            attempt: 0,
            not_before: Utc::now(),
            lease_owner: None,
            lease_expiry: None,
            fencing_token: 0,
            estimated_cost: 1,
            safe_error_code: None,
            receipt_id: None,
            coverage: "not_assessed".into(),
            point_coverage: Vec::new(),
            counts: JobCounts::default(),
            server_request_id: None,
        };
        assert!(!committed_tuple_matches(&job, &plan));
    }

    #[tokio::test]
    async fn execution_stops_when_the_committed_tuple_does_not_match() {
        let state = Arc::new(crate::state::AppState::new());
        let job = JobView {
            job_id: Uuid::nil(),
            tenant_id: "tenant-a".into(),
            canonical_site: "site-a".into(),
            provider_instance_id: "portal-a".into(),
            device_id: "device-a".into(),
            model_revision: "rev-plan".into(),
            logical_window_start: Utc::now(),
            logical_window_end: Utc::now(),
            shard: String::new(),
            state: "leased".into(),
            attempt: 1,
            not_before: Utc::now(),
            lease_owner: Some("worker".into()),
            lease_expiry: Some(Utc::now()),
            fencing_token: 1,
            estimated_cost: 1,
            safe_error_code: None,
            receipt_id: None,
            coverage: "not_assessed".into(),
            point_coverage: Vec::new(),
            counts: JobCounts::default(),
            server_request_id: None,
        };
        let outcome = execute_job(&state, &job).await;
        assert!(matches!(
            outcome.outcome,
            FinishOutcome::Permanent { code } if code == "plan_identity_mismatch"
        ));
    }

    #[test]
    fn throttled_and_timeout_retry_without_committing() {
        let now = Utc::now();
        match classify_poll_error("429 too many", 1, now) {
            FinishOutcome::Retry { code, not_before } => {
                assert_eq!(code, "throttled");
                assert!(not_before > now);
            }
            other => panic!("expected retry, got {other:?}"),
        }
        match classify_poll_error("context deadline exceeded", 2, now) {
            FinishOutcome::Retry { code, .. } => assert_eq!(code, "timeout"),
            other => panic!("expected timeout retry, got {other:?}"),
        }
        assert!(matches!(
            classify_poll_error("429", 8, now),
            FinishOutcome::Permanent { code } if code == "throttled"
        ));
    }

    #[test]
    fn model_change_and_partial_coverage_do_not_commit() {
        let now = Utc::now();
        let gap = super::super::coverage::CoverageReport {
            summary: "incomplete".into(),
            points: vec![super::super::coverage::PointCoverage {
                point_id: "sat".into(),
                disposition: "genuine_gap".into(),
                expected_slots: 1,
                observed_slots: 0,
                late_slots: 0,
            }],
            duplicate_timestamps: 0,
            out_of_window: 0,
        };
        let written = crate::providers::writer::ProviderIngestReceipt {
            submitted: 0,
            eligible: 0,
            skipped: 0,
            persisted_rows: 0,
            inserted_rows: 0,
            updated_rows: 0,
        };
        let changed = decide_window(&DecideWindow {
            job_revision: "rev-old",
            active_revision: Some("rev-new"),
            job_digest: Some("digest-a"),
            active_digest: Some("digest-a"),
            coverage: &super::super::coverage::CoverageReport::accounted("sat"),
            attempt: 1,
            now,
            written: &written,
            applied: &[],
        });
        assert!(matches!(
            changed,
            FinishOutcome::Permanent { code } if code == "model_revision_changed"
        ));
        let partial = decide_window(&DecideWindow {
            job_revision: "rev-old",
            active_revision: Some("rev-old"),
            job_digest: None,
            active_digest: None,
            coverage: &gap,
            attempt: 1,
            now,
            written: &written,
            applied: &[],
        });
        assert!(matches!(
            partial,
            FinishOutcome::Partial { code, .. } if code == "genuine_gap"
        ));
    }
}
