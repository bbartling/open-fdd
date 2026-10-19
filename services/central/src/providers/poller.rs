//! Background poll loop for configured provider sites.
//!
//! NF sites enqueue durable completed-hour jobs. They do not sleep `poll_secs`
//! and then fetch `now − 65 minutes`. History errors stay failed.

use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use futures_util::future::BoxFuture;
use tokio::sync::{watch, Semaphore};
use tokio::task::JoinHandle;
use tracing::{debug, info, warn};

use super::ace_stub::AceIotStubDriver;
use super::config::SiteConfig;
use super::error::ProviderErrorCode;
use super::hourly::HourlyPolicy;
use super::hourly_exec::{run_hourly_tick, FetchRequest, HistorySource, SampleWriter, TickInput};
use super::map::HistorySeries;
use super::nf::NfPortalDriver;
use super::registry::{history_supported, HistoryRequest};
use super::store::StoreOpen;
use super::types::{HourlyCoverageHealth, ProviderHealthStatus};
use super::writer;
use super::{DataProvider, Runtime};
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

fn tick_secs() -> u64 {
    std::env::var("OPENFDD_PROVIDER_TICK_SECS")
        .ok()
        .and_then(|v| v.parse().ok())
        .filter(|n| *n >= 5)
        .unwrap_or(30)
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
    if matches!(site.kind, super::types::ProviderKind::Nf) {
        nf_hourly_loop(state, runtime, site, sem, shutdown).await;
        return;
    }
    ace_poll_loop(runtime, site, sem, shutdown).await;
}

async fn nf_hourly_loop(
    state: Arc<AppState>,
    runtime: Arc<Runtime>,
    site: SiteConfig,
    sem: Arc<Semaphore>,
    shutdown: &mut watch::Receiver<bool>,
) {
    let building_id = site.building_id.clone();
    let tenant_id = site.tenant_id.clone();
    let provider_instance_id = site.provider_instance_id.clone();
    let mut driver = match NfPortalDriver::new(
        provider_instance_id.clone(),
        site.endpoint.clone(),
        site.client_id.clone(),
        site.client_secret.clone(),
        site.anonymous,
        super::http_policy::HttpLimits::default(),
    ) {
        Ok(driver) => driver,
        Err(_) => {
            runtime
                .record_error(
                    &building_id,
                    ProviderHealthStatus::Error,
                    Some("config_invalid".into()),
                )
                .await;
            return;
        }
    };
    if !history_supported(&DataProvider::capabilities(&driver)) {
        runtime.note_unimplemented(&building_id).await;
        let _ = shutdown.changed().await;
        return;
    }
    debug!(
        identity = %super::driver_identity(&driver),
        history = DataProvider::capabilities(&driver).fetch_history.path.as_deref().unwrap_or(""),
        %building_id,
        "nf history contract"
    );
    let policy = HourlyPolicy::from_env();
    let owner = std::env::var("OPENFDD_HOURLY_WORKER_ID").unwrap_or_else(|_| "central".into());
    let mut first = true;
    loop {
        let wait = if first { 0 } else { tick_secs() };
        first = false;
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_secs(wait)) => {}
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
        if DataProvider::authenticate(&mut driver).await.is_err() {
            warn!(%building_id, "NF authenticate failed");
            runtime
                .record_error(
                    &building_id,
                    ProviderHealthStatus::AuthFailed,
                    Some("auth_failed".into()),
                )
                .await;
            continue;
        }
        let opened = runtime.hourly_store().await;
        let store = match opened {
            StoreOpen::Durable(store) | StoreOpen::MemoryOnly(store) => store,
            StoreOpen::Unavailable => {
                warn!(%building_id, "hourly job store unavailable");
                runtime
                    .record_error(
                        &building_id,
                        ProviderHealthStatus::Error,
                        Some("job_store_unavailable".into()),
                    )
                    .await;
                continue;
            }
        };
        let resolver = runtime.resolver_for(&tenant_id, &building_id);
        let devices = if resolver.mapped_count() == 0 && site.resolver.mapped_count() > 0 {
            site.resolver.devices()
        } else {
            resolver.devices()
        };
        let now = Utc::now();
        let provider_instance = driver.provider_id().to_string();
        let tick = TickInput {
            now,
            tenant: &tenant_id,
            canonical_site: &building_id,
            provider_instance: &provider_instance,
            devices: &devices,
            policy: &policy,
            owner: &owner,
        };
        let mut source = NfHistory {
            driver: &mut driver,
        };
        let mut sink = HistorianSink {
            state: &state,
            building_id: &building_id,
            provider_instance_id: &provider_instance_id,
        };
        match run_hourly_tick(&store, &tick, &mut source, &mut sink).await {
            Ok(report) => {
                let coverage = HourlyCoverageHealth {
                    durable: report.durable,
                    committed: report.committed,
                    no_source_data: report.no_source_data,
                    failed: report.failed,
                    partial: report.partial,
                    unrecoverable_gaps: report.unrecoverable_gaps,
                    samples_handed_off: u64::try_from(report.samples_handed_off)
                        .unwrap_or(u64::MAX),
                    update_log_status: report.update_log_status.to_string(),
                    detail: report.health_code(),
                };
                let (status, as_error) = if report.blocks_green() {
                    if report.failed > 0 && report.committed == 0 && report.no_source_data == 0 {
                        (ProviderHealthStatus::Error, true)
                    } else {
                        (ProviderHealthStatus::Degraded, false)
                    }
                } else {
                    (ProviderHealthStatus::Ok, false)
                };
                if as_error {
                    runtime
                        .record_hourly(
                            &building_id,
                            status,
                            report.samples_handed_off as u64,
                            Some(report.health_code()),
                            coverage,
                            true,
                        )
                        .await;
                } else {
                    runtime
                        .record_hourly(
                            &building_id,
                            status,
                            report.samples_handed_off as u64,
                            Some(report.health_code()),
                            coverage,
                            false,
                        )
                        .await;
                }
                debug!(%building_id, status = ?status, "hourly tick finished");
            }
            Err(code) => {
                warn!(%building_id, %code, "hourly tick failed");
                runtime
                    .record_error(&building_id, ProviderHealthStatus::Error, Some(code))
                    .await;
            }
        }
    }
}

struct NfHistory<'a> {
    driver: &'a mut NfPortalDriver,
}

impl HistorySource for NfHistory<'_> {
    fn fetch<'a>(
        &'a mut self,
        req: &'a FetchRequest,
    ) -> BoxFuture<'a, Result<Vec<HistorySeries>, super::hourly::FetchError>> {
        Box::pin(async move {
            debug!(
                purpose = %req.purpose,
                device_id = %req.device_id,
                window_start = %req.window_start,
                points = req.point_ids.len(),
                "NF history GET"
            );
            DataProvider::fetch_history(
                self.driver,
                &HistoryRequest {
                    point_ids: req.point_ids.clone(),
                    from: req.from,
                    to: req.to,
                },
            )
            .await
            .map_err(super::nf::fetch_error_from_provider)
        })
    }
}

struct HistorianSink<'a> {
    state: &'a Arc<AppState>,
    building_id: &'a str,
    provider_instance_id: &'a str,
}

impl SampleWriter for HistorianSink<'_> {
    fn write<'a>(
        &'a mut self,
        samples: &'a [super::types::NormalizedSample],
    ) -> BoxFuture<'a, Result<usize, String>> {
        Box::pin(async move {
            let receipt = writer::ingest_samples(
                self.state,
                self.building_id,
                self.provider_instance_id,
                samples,
            )
            .await
            .map_err(|_| "persistence".to_string())?;
            Ok(receipt.persisted_rows)
        })
    }
}

async fn ace_poll_loop(
    runtime: Arc<Runtime>,
    site: SiteConfig,
    sem: Arc<Semaphore>,
    shutdown: &mut watch::Receiver<bool>,
) {
    let _permit = match sem.acquire().await {
        Ok(permit) => permit,
        Err(_) => return,
    };
    let building_id = site.building_id.clone();
    let mut ace = AceIotStubDriver::new(&site.provider_instance_id);
    debug!(identity = %super::driver_identity(&ace), %building_id, "ace driver");
    let now = chrono::Utc::now();
    let history = DataProvider::fetch_history(
        &mut ace,
        &HistoryRequest {
            point_ids: Vec::new(),
            from: now,
            to: now,
        },
    )
    .await;
    if !history_supported(&DataProvider::capabilities(&ace))
        && matches!(
            history,
            Err(ref err) if err.code == ProviderErrorCode::NotImplemented
        )
    {
        info!(%building_id, "Ace IoT history is not implemented");
    }
    runtime.note_unimplemented(&building_id).await;
    drop(_permit);
    let _ = shutdown.wait_for(|stopped| *stopped).await;
}

impl Runtime {
    pub async fn note_unimplemented(&self, building_id: &str) {
        let mut guard = self.health.lock().await;
        if let Some(site) = guard
            .sites
            .iter_mut()
            .find(|site| site.building_id == building_id)
        {
            site.health.status = ProviderHealthStatus::NotImplemented;
            site.health.message = Some("not_implemented".into());
            site.hourly_coverage = None;
        }
    }

    pub async fn record_hourly(
        &self,
        building_id: &str,
        status: ProviderHealthStatus,
        ingested: u64,
        message: Option<String>,
        coverage: HourlyCoverageHealth,
        is_error: bool,
    ) {
        let mut guard = self.health.lock().await;
        if let Some(site) = guard
            .sites
            .iter_mut()
            .find(|s| s.building_id == building_id)
        {
            site.last_poll_at = Some(Utc::now());
            site.last_ingested_points = ingested;
            site.health.status = status;
            site.health.message = message.as_deref().map(super::error::safe_operator_code);
            if coverage.update_log_status.is_empty() {
                site.hourly_coverage = None;
            } else {
                site.hourly_coverage = Some(coverage);
            }
            if is_error {
                site.consecutive_errors = site.consecutive_errors.saturating_add(1);
                site.health.last_error_at = Some(Utc::now());
            } else {
                site.consecutive_errors = 0;
                site.health.last_success_at = Some(Utc::now());
            }
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
            site.health.message = message.as_deref().map(super::error::safe_operator_code);
            site.health.last_error_at = Some(Utc::now());
        }
    }
}
