//! Background poll loop for configured provider sites.

use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use tokio::sync::{watch, Semaphore};
use tokio::task::JoinHandle;
use tracing::{debug, info, warn};

use super::ace_stub::AceIotStubDriver;
use super::config::SiteConfig;
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
}

fn page_size() -> u32 {
    std::env::var("OPENFDD_PROVIDER_PAGE_SIZE")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|n| *n > 0)
        .unwrap_or(200)
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
            let mut shutdown_site = shutdown.clone();
            handles.push(tokio::spawn(async move {
                site_poll_loop(state, runtime, site, sem, &mut shutdown_site).await;
            }));
        }
        let _ = shutdown.wait_for(|v| *v).await;
        for handle in handles {
            let _ = handle.await;
        }
        info!("provider poller stopped");
    })
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
    let mut nf = if matches!(kind, super::types::ProviderKind::Nf) {
        Some(NfPortalDriver::new(
            &building_id,
            endpoint,
            client_id,
            client_secret,
        ))
    } else {
        None
    };
    let mut ace = AceIotStubDriver::new(&building_id);

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
                poll_nf_site(&state, &building_id, driver, &resolver, page_size()).await
            }
            super::types::ProviderKind::AceIot => {
                poll_ace_site(&building_id, &mut ace).await
            }
        };

        match result {
            Ok(ingested) => {
                backoff_secs = poll_secs;
                runtime
                    .record_success(&building_id, ingested as u64, ProviderHealthStatus::Ok, None)
                    .await;
                debug!(%building_id, ingested, "provider poll ok");
            }
            Err(err) => {
                backoff_secs = if backoff_secs == 0 {
                    poll_secs.max(30)
                } else {
                    (backoff_secs.saturating_mul(2)).min(900)
                };
                warn!(%building_id, %err, next_backoff_secs = backoff_secs, "provider poll failed");
                runtime
                    .record_error(
                        &building_id,
                        ProviderHealthStatus::Error,
                        Some(err),
                    )
                    .await;
            }
        }
    }
}

async fn poll_nf_site(
    state: &Arc<AppState>,
    building_id: &str,
    driver: &mut NfPortalDriver,
    resolver: &RoleResolver,
    page_size: u32,
) -> Result<usize, String> {
    driver.authenticate().await?;
    let latest = driver.query_points(page_size).await?;
    let now = Utc::now();
    // One hour of history plus five minutes of overlap. Timescale upsert on
    // (site, key, ts) drops the overlap instead of inserting a second row.
    let from = now - chrono::Duration::minutes(65);
    let history = match driver
        .fetch_history(&resolver.provider_point_ids(), from, now)
        .await
    {
        Ok(rows) => rows,
        Err(err) => {
            warn!(%building_id, %err, "NF GetData failed; keeping latest-value scrape only");
            Vec::new()
        }
    };
    let mut raw = history;
    raw.extend(latest);
    let mut samples = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for point in &raw {
        let Some(resolved) = resolver.resolve(&point.provider_point_id) else {
            continue;
        };
        let key = (point.provider_point_id.clone(), point.ts.timestamp());
        if !seen.insert(key) {
            continue;
        }
        samples.push(normalize_mapped(building_id, point, resolved));
    }
    writer::ingest_samples(state, building_id, &samples)
        .await
        .map_err(|e| e.to_string())
}

async fn poll_ace_site(building_id: &str, ace: &mut AceIotStubDriver) -> Result<usize, String> {
    let _ = building_id;
    ace.authenticate().await?;
    ace.query_points().await.map(|_| 0)
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
            site.health.message = message;
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
            site.health.message = message;
            site.health.last_error_at = Some(Utc::now());
        }
    }
}
