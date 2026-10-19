//! Background poll loop for configured provider sites.

use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use tokio::sync::{watch, Semaphore};
use tokio::task::JoinHandle;
use tracing::{debug, info, warn};

use super::ace_stub::AceIotStubDriver;
use super::config::SiteConfig;
use super::error::safe_operator_code;
use super::http_policy::HttpLimits;
use super::map::{normalize_mapped, RoleResolver};
use super::nf::NfPortalDriver;
use super::types::ProviderHealthStatus;
use super::writer;
use super::Runtime;
use crate::state::AppState;

fn poll_enabled() -> bool {
    std::env::var("OPENFDD_PROVIDER_POLL")
        .ok()
        .is_some_and(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
}

fn max_concurrent() -> usize {
    std::env::var("OPENFDD_PROVIDER_MAX_CONCURRENT")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|n| *n > 0)
        .unwrap_or(2)
        .clamp(1, 16)
}

fn page_size() -> u32 {
    std::env::var("OPENFDD_PROVIDER_PAGE_SIZE")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|n| *n > 0)
        .unwrap_or(200)
        .clamp(1, 500)
}

pub fn spawn_with_shutdown(
    state: Arc<AppState>,
    runtime: Arc<Runtime>,
    mut shutdown: watch::Receiver<bool>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        if !poll_enabled() {
            info!("OPENFDD_PROVIDER_POLL not enabled; provider poller idle");
            return;
        }
        let sites = runtime.sites.clone();
        if sites.is_empty() {
            info!("no OPENFDD_PROVIDER_SITES configured; provider poller idle");
            return;
        }
        info!(sites = sites.len(), "provider poller starting");
        let sem = Arc::new(Semaphore::new(max_concurrent()));
        let mut handles = Vec::new();
        for site in sites {
            let state = Arc::clone(&state);
            let runtime = Arc::clone(&runtime);
            let sem = Arc::clone(&sem);
            let shutdown_site = shutdown.clone();
            handles.push(tokio::spawn(async move {
                supervise_site(state, runtime, site, sem, shutdown_site).await;
            }));
        }
        let _ = shutdown.wait_for(|v| *v).await;
        for handle in handles {
            let _ = handle.await;
        }
        info!("provider poller stopped");
    })
}

async fn supervise_site(
    state: Arc<AppState>,
    runtime: Arc<Runtime>,
    site: SiteConfig,
    sem: Arc<Semaphore>,
    shutdown: watch::Receiver<bool>,
) {
    let building_id = site.building_id.clone();
    let mut restarts = 0u32;
    loop {
        let state = Arc::clone(&state);
        let runtime_task = Arc::clone(&runtime);
        let site = site.clone();
        let sem = Arc::clone(&sem);
        let mut shutdown_task = shutdown.clone();
        let joined = tokio::spawn(async move {
            site_poll_loop(state, runtime_task, site, sem, &mut shutdown_task).await;
        })
        .await;
        match joined {
            Ok(()) => return,
            Err(err) if err.is_panic() => {
                restarts = restarts.saturating_add(1);
                runtime
                    .record_error(
                        &building_id,
                        ProviderHealthStatus::Error,
                        Some("site_task_exited".into()),
                    )
                    .await;
                if restarts >= 5 {
                    warn!(%building_id, "provider site task stopped after repeated exits");
                    return;
                }
                let pause = Duration::from_secs(5u64.saturating_mul(u64::from(restarts)).min(60));
                let mut shutdown_wait = shutdown.clone();
                tokio::select! {
                    _ = tokio::time::sleep(pause) => {}
                    _ = shutdown_wait.wait_for(|v| *v) => return,
                }
            }
            Err(_) => return,
        }
    }
}

async fn site_poll_loop(
    state: Arc<AppState>,
    runtime: Arc<Runtime>,
    site: SiteConfig,
    sem: Arc<Semaphore>,
    shutdown: &mut watch::Receiver<bool>,
) {
    let building_id = site.building_id.clone();
    let poll_secs = site.poll_secs;
    // First tick is immediate; later ticks use poll_secs (lab default 300).
    let mut backoff_secs = 0u64;
    let kind = site.kind;
    let endpoint = site.endpoint.clone();
    let client_id = site.client_id.clone();
    let client_secret = site.client_secret.clone();
    let resolver = site.resolver;
    let anonymous = site.anonymous;
    let provider_instance_id = site.provider_instance_id.clone();
    let mut nf = if matches!(kind, super::types::ProviderKind::Nf) {
        match NfPortalDriver::new(
            provider_instance_id.clone(),
            endpoint,
            client_id,
            client_secret,
            anonymous,
            HttpLimits::default(),
        ) {
            Ok(driver) => Some(driver),
            Err(err) => {
                runtime
                    .record_error(
                        &building_id,
                        ProviderHealthStatus::Error,
                        Some(safe_operator_code(&err.to_string())),
                    )
                    .await;
                let _ = shutdown.wait_for(|v| *v).await;
                return;
            }
        }
    } else {
        None
    };
    let mut ace = AceIotStubDriver::new(&provider_instance_id);

    loop {
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_secs(backoff_secs)) => {}
            changed = shutdown.changed() => {
                if changed.is_err() || *shutdown.borrow() {
                    return;
                }
                continue;
            }
        }

        let _permit = match sem.acquire().await {
            Ok(p) => p,
            Err(_) => return,
        };

        let result = match kind {
            super::types::ProviderKind::Nf => {
                let driver = nf.as_mut().expect("nf driver");
                poll_nf_site(
                    &state,
                    &building_id,
                    &provider_instance_id,
                    driver,
                    &resolver,
                    page_size(),
                )
                .await
            }
            super::types::ProviderKind::AceIot => poll_ace_site(&building_id, &mut ace).await,
        };

        match result {
            Ok(outcome) => {
                backoff_secs = poll_secs;
                runtime
                    .record_success(
                        &building_id,
                        outcome.persisted_rows,
                        outcome.status,
                        outcome.message,
                    )
                    .await;
                debug!(
                    %building_id,
                    persisted = outcome.persisted_rows,
                    status = ?outcome.status,
                    "provider poll finished"
                );
            }
            Err(err) => {
                backoff_secs = if backoff_secs == 0 {
                    poll_secs.max(30)
                } else {
                    (backoff_secs.saturating_mul(2)).min(900)
                };
                let code = safe_operator_code(&err.to_string());
                warn!(%building_id, code = %code, next_backoff_secs = backoff_secs, "provider poll failed");
                let status = if code == "auth_failed" || code == "auth_not_configured" {
                    ProviderHealthStatus::AuthFailed
                } else {
                    ProviderHealthStatus::Error
                };
                runtime.record_error(&building_id, status, Some(code)).await;
            }
        }
    }
}

struct PollOutcome {
    persisted_rows: u64,
    status: ProviderHealthStatus,
    message: Option<String>,
}

async fn poll_nf_site(
    state: &Arc<AppState>,
    building_id: &str,
    provider_instance_id: &str,
    driver: &mut NfPortalDriver,
    resolver: &RoleResolver,
    page_size: u32,
) -> Result<PollOutcome, super::error::ProviderError> {
    driver.authenticate().await?;
    let latest = driver.query_points(page_size).await?;
    let now = Utc::now();
    // Prototype window until N5 durable hourly jobs. History stays a GET.
    let from = now - chrono::Duration::minutes(65);
    let (history, history_code) = match driver
        .fetch_history(&resolver.provider_point_ids(), from, now)
        .await
    {
        Ok(rows) => (rows, None),
        Err(err) => {
            let code = safe_operator_code(&err.to_string());
            let incomplete = super::error::ProviderError::new(
                super::error::ProviderErrorCode::HistoryIncomplete,
            );
            warn!(%building_id, code = %code, marker = %incomplete, "NF history incomplete");
            (Vec::new(), Some(incomplete.code.as_str().to_string()))
        }
    };
    let receipt = ingest_mapped(
        state,
        building_id,
        provider_instance_id,
        resolver,
        latest,
        history,
    )
    .await?;
    let (status, message) = if history_code.is_some() {
        (
            ProviderHealthStatus::Degraded,
            Some("history_incomplete".into()),
        )
    } else if receipt.submitted > 0 && receipt.persisted_rows == 0 {
        (
            ProviderHealthStatus::Degraded,
            Some("nothing_persisted".into()),
        )
    } else {
        (ProviderHealthStatus::Ok, None)
    };
    let snapshot = driver.health(status, message);
    if snapshot.provider_id != provider_instance_id || driver.provider_id() != provider_instance_id
    {
        return Err(super::error::ProviderError::new(
            super::error::ProviderErrorCode::Config,
        ));
    }
    Ok(PollOutcome {
        persisted_rows: receipt.persisted_rows as u64,
        status: snapshot.status,
        message: snapshot.message,
    })
}

async fn ingest_mapped(
    state: &Arc<AppState>,
    building_id: &str,
    provider_instance_id: &str,
    resolver: &RoleResolver,
    latest: Vec<super::map::RawProviderPoint>,
    history: Vec<super::map::RawProviderPoint>,
) -> Result<writer::ProviderIngestReceipt, super::error::ProviderError> {
    let mut raw = history;
    raw.extend(latest);
    let mut samples = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for point in &raw {
        let Some(resolved) = resolver.resolve(&point.provider_point_id) else {
            continue;
        };
        let key = (point.provider_point_id.clone(), point.ts.timestamp_micros());
        if !seen.insert(key) {
            continue;
        }
        samples.push(normalize_mapped(
            building_id,
            provider_instance_id,
            point,
            resolved,
        ));
    }
    writer::ingest_samples(state, building_id, provider_instance_id, &samples).await
}

async fn poll_ace_site(
    building_id: &str,
    ace: &mut AceIotStubDriver,
) -> Result<PollOutcome, super::error::ProviderError> {
    let _ = building_id;
    let health = ace.health();
    if health.provider_id != ace.provider_id() {
        return Err(super::error::ProviderError::new(
            super::error::ProviderErrorCode::Config,
        ));
    }
    ace.authenticate().await.map_err(|_| {
        super::error::ProviderError::new(super::error::ProviderErrorCode::NotImplemented)
    })?;
    let _ = ace.query_points().await.map_err(|_| {
        super::error::ProviderError::new(super::error::ProviderErrorCode::NotImplemented)
    })?;
    Ok(PollOutcome {
        persisted_rows: 0,
        status: ProviderHealthStatus::NotImplemented,
        message: Some("not_implemented".into()),
    })
}

impl Runtime {
    pub async fn record_success(
        &self,
        building_id: &str,
        ingested: u64,
        status: ProviderHealthStatus,
        message: Option<String>,
    ) {
        let mut guard = self.health.lock().await;
        if let Some(site) = guard
            .sites
            .iter_mut()
            .find(|s| s.building_id == building_id)
        {
            site.last_poll_at = Some(Utc::now());
            site.last_ingested_points = ingested;
            site.consecutive_errors = 0;
            site.health.status = status;
            site.health.message = message.as_deref().map(safe_operator_code);
            site.health.last_success_at = Some(Utc::now());
        }
    }

    pub async fn record_error(
        &self,
        building_id: &str,
        status: ProviderHealthStatus,
        message: Option<String>,
    ) {
        let mut guard = self.health.lock().await;
        if let Some(site) = guard
            .sites
            .iter_mut()
            .find(|s| s.building_id == building_id)
        {
            site.last_poll_at = Some(Utc::now());
            site.consecutive_errors = site.consecutive_errors.saturating_add(1);
            site.health.status = status;
            site.health.message = message.as_deref().map(safe_operator_code);
            site.health.last_error_at = Some(Utc::now());
        }
    }
}
