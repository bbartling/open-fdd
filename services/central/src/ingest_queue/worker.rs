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

use super::model::{FinishOutcome, FinishRequest, JobCounts, JobView};
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
            let outcome = execute_job(&state, &job).await;
            let finish = FinishRequest {
                owner,
                job_id: job.job_id,
                fencing_token: job.fencing_token,
                now: Utc::now(),
                outcome,
            };
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

async fn execute_job(state: &Arc<AppState>, job: &JobView) -> FinishOutcome {
    let identity_ok = {
        let models = state
            .providers
            .models
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match models.active_plan(&job.tenant_id, &job.canonical_site) {
            Some(plan) => committed_tuple_matches(job, plan),
            None => false,
        }
    };
    if !identity_ok {
        return FinishOutcome::Permanent {
            code: "plan_identity_mismatch".into(),
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
        return FinishOutcome::Permanent {
            code: "site_not_configured".into(),
        };
    };
    if matches!(site.kind, ProviderKind::AceIot) {
        return FinishOutcome::Permanent {
            code: "not_implemented".into(),
        };
    }
    match poller::execute_window(
        state,
        site,
        &job.device_id,
        job.logical_window_start,
        job.logical_window_end,
    )
    .await
    {
        Ok(ingested) => match u32::try_from(ingested) {
            Ok(count) => FinishOutcome::Committed {
                counts: JobCounts {
                    fetched: count,
                    accepted: count,
                    inserted: count,
                    ..JobCounts::default()
                },
            },
            Err(_) => FinishOutcome::Partial {
                counts: JobCounts::default(),
                code: "count_overflow".into(),
            },
        },
        Err(err) => finish_for_poll_error(state, job, &err).await,
    }
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
    if err == "device_unmapped" {
        return FinishOutcome::Permanent {
            code: err.to_string(),
        };
    }
    if attempt >= 8 {
        FinishOutcome::Permanent {
            code: "provider_poll_failed".into(),
        }
    } else {
        let backoff = (30i64 * 2i64.saturating_pow(attempt.saturating_sub(1))).min(900);
        FinishOutcome::Retry {
            code: "provider_poll_failed".into(),
            not_before: now + chrono::Duration::seconds(backoff),
        }
    }
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
                devices.extend(planned.into_iter().map(|device| ScheduleDevice {
                    tenant_id: site.tenant_id.clone(),
                    canonical_site: site.building_id.clone(),
                    provider_instance_id: device.provider_instance_id,
                    device_id: device.equipment_id,
                    model_revision: device.revision_id,
                    estimated_cost: device.estimated_cost,
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
            counts: JobCounts::default(),
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
            counts: JobCounts::default(),
        };
        let outcome = execute_job(&state, &job).await;
        assert!(matches!(
            outcome,
            FinishOutcome::Permanent { code } if code == "plan_identity_mismatch"
        ));
    }
}
