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
use super::model::{FinishOutcome, FinishRequest, JobCounts, JobView, MODEL_REVISION_BOOTSTRAP};
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
        let planned = schedule::due_windows(
            now,
            chrono::Duration::seconds(publication_delay_secs() as i64),
            catchup_hours(),
            300,
            &devices_from_state(state),
        );
        for job in planned {
            state
                .ingest_queue
                .enqueue(job, now)
                .await
                .map_err(|err| err.to_string())?;
        }
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
    let Some(site) = state
        .providers
        .sites
        .iter()
        .find(|site| site.building_id == job.canonical_site)
    else {
        return FinishOutcome::Permanent {
            code: "site_not_configured".into(),
        };
    };
    if matches!(site.kind, ProviderKind::AceIot) {
        return FinishOutcome::Permanent {
            code: "not_implemented".into(),
        };
    }
    match poller::execute_site(state, site).await {
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
        Err(err) => {
            if portal_throttled(&err) {
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
            if job.attempt >= 8 {
                FinishOutcome::Permanent {
                    code: "provider_poll_failed".into(),
                }
            } else {
                let backoff = (30i64 * 2i64.saturating_pow(job.attempt.saturating_sub(1))).min(900);
                FinishOutcome::Retry {
                    code: "provider_poll_failed".into(),
                    not_before: Utc::now() + chrono::Duration::seconds(backoff),
                }
            }
        }
    }
}

fn portal_throttled(err: &str) -> bool {
    let lower = err.to_ascii_lowercase();
    lower.contains("429") || lower.contains("too many") || lower.contains("throttled")
}

fn devices_from_state(state: &AppState) -> Vec<ScheduleDevice> {
    let mut devices = Vec::new();
    for site in &state.providers.sites {
        let tenant_id = if site.tenant_id.is_empty() {
            std::env::var("OPENFDD_INGEST_TENANT_ID").unwrap_or_else(|_| "legacy".into())
        } else {
            site.tenant_id.clone()
        };
        let provider_instance_id = site.provider_instance_id.clone();
        let mut equipment = site.resolver.equipment_ids();
        if equipment.is_empty() {
            equipment.push(site.building_id.clone());
        }
        for device_id in equipment {
            let estimated =
                u32::try_from(site.resolver.point_count_for_equipment(&device_id)).unwrap_or(1);
            devices.push(ScheduleDevice {
                tenant_id: tenant_id.clone(),
                canonical_site: site.building_id.clone(),
                provider_instance_id: provider_instance_id.clone(),
                device_id,
                model_revision: MODEL_REVISION_BOOTSTRAP.into(),
                estimated_cost: estimated.max(1),
            });
        }
    }
    devices
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

fn tick_secs() -> u64 {
    std::env::var("OPENFDD_INGEST_TICK_SECS")
        .ok()
        .and_then(|value| value.parse().ok())
        .filter(|value| *value >= 5)
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

    fn restore(key: &str, prev: Option<String>) {
        match prev {
            Some(value) => std::env::set_var(key, value),
            None => std::env::remove_var(key),
        }
    }
}
