//! Background poll loop for configured provider sites.
//!
//! NF and Open-Meteo sites enqueue durable completed-hour jobs. They do not
//! sleep `poll_secs` and then fetch `now − 65 minutes`. History errors stay
//! failed. Ace stays a NotImplemented stub.

use std::sync::Arc;
use std::time::Duration;

use chrono::{DateTime, Duration as ChronoDuration, Utc};
use futures_util::future::BoxFuture;
use tokio::sync::{watch, Semaphore};
use tokio::task::JoinHandle;
use tracing::{debug, info, warn};

use super::ace_stub::AceIotStubDriver;
use super::config::SiteConfig;
use super::hourly::{assess_page, HourlyPolicy, LogicalWindow, UPDATE_LOG_STATUS};
use super::hourly_exec::{run_hourly_tick, FetchRequest, HistorySource, SampleWriter, TickInput};
use super::map::{normalize_mapped, DevicePoints, HistorySeries, ResolvedRole, RoleResolver};
use super::meteo::OpenMeteoDriver;
use super::nf::NfPortalDriver;
use super::store::StoreOpen;
use super::types::{HourlyCoverageHealth, ProviderHealthStatus};
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

/// Await the hourly site loops. The shared queue calls this only in explicit
/// legacy mode (`OPENFDD_PROVIDER_POLL_MODE=legacy` and
/// `OPENFDD_ALLOW_UNSAFE_POLLER=1`).
pub async fn run_legacy_site_loops(state: Arc<AppState>, shutdown: &mut watch::Receiver<bool>) {
    let runtime = Arc::clone(&state.providers);
    let handle = spawn_with_shutdown(Arc::clone(&state), runtime, shutdown.clone());
    let _ = shutdown.wait_for(|v| *v).await;
    let _ = handle.await;
}

/// Samples inside `[start, end)` for one device. Overlap is zero: the queue
/// job already names its own window.
pub struct WindowAccept {
    pub samples: Vec<super::types::NormalizedSample>,
}

pub fn accept_device_window(
    building_id: &str,
    provider_instance_id: &str,
    device: &DevicePoints,
    page: &[HistorySeries],
    window: LogicalWindow,
) -> WindowAccept {
    let ids: Vec<String> = device
        .points
        .iter()
        .map(|point| point.provider_point_id.clone())
        .collect();
    let assessed = assess_page(&ids, page, window, ChronoDuration::seconds(0));
    let mut samples = Vec::new();
    for raw in &assessed.accepted {
        let Some(point) = device
            .points
            .iter()
            .find(|point| point.provider_point_id == raw.provider_point_id)
        else {
            continue;
        };
        samples.push(normalize_mapped(
            building_id,
            provider_instance_id,
            raw,
            &ResolvedRole::binding(
                &device.device_id,
                point.role.clone(),
                point.equip_type.clone(),
                None,
            ),
        ));
    }
    WindowAccept { samples }
}

fn chosen_resolver<'a>(live: &'a RoleResolver, site: &'a RoleResolver) -> &'a RoleResolver {
    if live.mapped_count() == 0 && site.mapped_count() > 0 {
        site
    } else {
        live
    }
}

/// GET one claimed queue window for one device and record provider health.
/// History stays `GET /api/v1/point/data`. This does not call `run_hourly_tick`.
pub async fn execute_window(
    state: &Arc<AppState>,
    site: &SiteConfig,
    device_id: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> Result<usize, String> {
    if !matches!(site.kind, super::types::ProviderKind::Nf) {
        return Err("not_implemented".into());
    }
    if end <= start {
        return Err("invalid_window".into());
    }
    let runtime = Arc::clone(&state.providers);
    let mut driver = NfPortalDriver::new(
        site.provider_instance_id.clone(),
        site.endpoint.clone(),
        site.client_id.clone(),
        site.client_secret.clone(),
        site.anonymous,
        super::http_policy::HttpLimits::default(),
    )
    .map_err(|_| "config_invalid".to_string())?;
    if driver.authenticate().await.is_err() {
        runtime
            .record_error(
                &site.building_id,
                ProviderHealthStatus::AuthFailed,
                Some("auth_failed".into()),
            )
            .await;
        return Err("auth_failed".into());
    }
    let live = runtime.resolver_for(&site.tenant_id, &site.building_id);
    let devices = chosen_resolver(&live, &site.resolver).devices();
    let Some(device) = devices
        .into_iter()
        .find(|device| device.device_id == device_id)
    else {
        runtime
            .record_error(
                &site.building_id,
                ProviderHealthStatus::Error,
                Some("device_unmapped".into()),
            )
            .await;
        return Err("device_unmapped".into());
    };
    let ids: Vec<String> = device
        .points
        .iter()
        .map(|point| point.provider_point_id.clone())
        .collect();
    let page = match driver.read_history_page(&ids, start, end).await {
        Ok(page) => page,
        Err(err) => {
            let code = err.code().to_string();
            runtime
                .record_error(
                    &site.building_id,
                    ProviderHealthStatus::Error,
                    Some(code.clone()),
                )
                .await;
            return Err(code);
        }
    };
    let accepted = accept_device_window(
        &site.building_id,
        &site.provider_instance_id,
        &device,
        &page,
        LogicalWindow { start, end },
    );
    let persisted = if accepted.samples.is_empty() {
        0
    } else {
        match writer::ingest_samples(
            state,
            &site.building_id,
            &site.provider_instance_id,
            &accepted.samples,
        )
        .await
        {
            Ok(receipt) => receipt.persisted_rows,
            Err(_) => {
                runtime
                    .record_error(
                        &site.building_id,
                        ProviderHealthStatus::Error,
                        Some("persistence".into()),
                    )
                    .await;
                return Err("persistence".into());
            }
        }
    };
    let ingested = u64::try_from(persisted).unwrap_or(u64::MAX);
    runtime
        .record_hourly(
            &site.building_id,
            ProviderHealthStatus::Ok,
            ingested,
            None,
            HourlyCoverageHealth {
                durable: true,
                committed: 1,
                samples_handed_off: ingested,
                update_log_status: UPDATE_LOG_STATUS.into(),
                detail: "queue_window".into(),
                ..HourlyCoverageHealth::default()
            },
            false,
        )
        .await;
    Ok(persisted)
}

async fn site_poll_loop(
    state: Arc<AppState>,
    runtime: Arc<Runtime>,
    site: SiteConfig,
    sem: Arc<Semaphore>,
    shutdown: &mut watch::Receiver<bool>,
) {
    match site.kind {
        super::types::ProviderKind::Nf => {
            nf_hourly_loop(state, runtime, site, sem, shutdown).await;
        }
        super::types::ProviderKind::OpenMeteo => {
            meteo_hourly_loop(state, runtime, site, sem, shutdown).await;
        }
        super::types::ProviderKind::AceIot => {
            ace_poll_loop(runtime, site, sem, shutdown).await;
        }
    }
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
    debug!(
        identity = %super::driver_identity(&driver),
        %building_id,
        "nf driver"
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
        if driver.authenticate().await.is_err() {
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
        let live = runtime.resolver_for(&tenant_id, &building_id);
        let devices = chosen_resolver(&live, &site.resolver).devices();
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
                let ledger = report.ledger.clone();
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
                            coverage.clone(),
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
                runtime.record_ledger(&building_id, ledger).await;
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

async fn meteo_hourly_loop(
    state: Arc<AppState>,
    runtime: Arc<Runtime>,
    site: SiteConfig,
    sem: Arc<Semaphore>,
    shutdown: &mut watch::Receiver<bool>,
) {
    let building_id = site.building_id.clone();
    let provider_instance_id = site.provider_instance_id.clone();
    let (Some(latitude), Some(longitude)) = (site.latitude, site.longitude) else {
        runtime
            .record_error(
                &building_id,
                ProviderHealthStatus::Error,
                Some("meteo_coordinates".into()),
            )
            .await;
        return;
    };
    let mut driver = match OpenMeteoDriver::new(
        provider_instance_id.clone(),
        site.endpoint.clone(),
        latitude,
        longitude,
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
        if driver.authenticate().is_err() {
            warn!(%building_id, "Open-Meteo origin rejected");
            runtime
                .record_error(
                    &building_id,
                    ProviderHealthStatus::Error,
                    Some("config_invalid".into()),
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
        let devices = site.resolver.devices();
        let now = Utc::now();
        let provider_instance = driver.provider_id().to_string();
        let tick = TickInput {
            now,
            tenant: "default",
            canonical_site: &building_id,
            provider_instance: &provider_instance,
            devices: &devices,
            policy: &policy,
            owner: &owner,
        };
        let mut source = MeteoHistory {
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
                runtime
                    .record_hourly(
                        &building_id,
                        status,
                        report.samples_handed_off as u64,
                        Some(report.health_code()),
                        coverage,
                        as_error,
                    )
                    .await;
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
            self.driver
                .read_history_page(&req.point_ids, req.from, req.to)
                .await
        })
    }
}

struct MeteoHistory<'a> {
    driver: &'a mut OpenMeteoDriver,
}

impl HistorySource for MeteoHistory<'_> {
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
                "Open-Meteo history GET"
            );
            self.driver
                .read_history_page(&req.point_ids, req.from, req.to)
                .await
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
    let building_id = site.building_id.clone();
    let poll_secs = site.poll_secs;
    let mut backoff_secs = 0u64;
    let mut ace = AceIotStubDriver::new(&site.provider_instance_id);
    debug!(identity = %super::driver_identity(&ace), %building_id, "ace driver");
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
        match poll_ace_site(&building_id, &mut ace).await {
            Ok(ingested) => {
                backoff_secs = poll_secs;
                runtime
                    .record_success(
                        &building_id,
                        ingested as u64,
                        ProviderHealthStatus::Ok,
                        None,
                    )
                    .await;
            }
            Err(err) => {
                if super::error::safe_operator_code(&err) == "not_implemented" {
                    backoff_secs = poll_secs;
                    runtime
                        .record_error(
                            &building_id,
                            ProviderHealthStatus::NotImplemented,
                            Some("not_implemented".into()),
                        )
                        .await;
                    continue;
                }
                backoff_secs = if backoff_secs == 0 {
                    poll_secs.max(30)
                } else {
                    backoff_secs.saturating_mul(2).min(900)
                };
                warn!(%building_id, %err, next_backoff_secs = backoff_secs, "provider poll failed");
                runtime
                    .record_error(&building_id, ProviderHealthStatus::Error, Some(err))
                    .await;
            }
        }
    }
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
        self.record_hourly(
            building_id,
            status,
            ingested,
            message,
            HourlyCoverageHealth::default(),
            false,
        )
        .await;
    }

    pub async fn record_ledger(&self, building_id: &str, ledger: super::types::CoverageLedger) {
        let mut guard = self.health.lock().await;
        if let Some(site) = guard
            .sites
            .iter_mut()
            .find(|site| site.building_id == building_id)
        {
            site.coverage_ledger = Some(ledger);
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
            site.health.status = status;
            site.health.message = message.as_deref().map(super::error::safe_operator_code);
            if status == ProviderHealthStatus::NotImplemented {
                return;
            }
            site.consecutive_errors = site.consecutive_errors.saturating_add(1);
            site.health.last_error_at = Some(Utc::now());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::map::{DevicePoints, MappedPoint, RawProviderPoint};
    use chrono::TimeZone;

    fn minute_series(point_id: &str, start: DateTime<Utc>, n: i64) -> HistorySeries {
        let mut samples = Vec::new();
        for offset in 0..n {
            samples.push(RawProviderPoint {
                provider_point_id: point_id.to_string(),
                display_name: None,
                ts: start + ChronoDuration::minutes(offset),
                val: offset as f64,
                unit: Some("degF".into()),
                source_quality: None,
                attrs: serde_json::Map::new(),
            });
        }
        HistorySeries {
            provider_point_id: point_id.to_string(),
            samples,
        }
    }

    #[test]
    fn past_hour_keeps_sixty_minute_samples() {
        let start = Utc.with_ymd_and_hms(2026, 3, 1, 12, 0, 0).unwrap();
        let end = start + ChronoDuration::hours(1);
        let point = "11111111-1111-4111-8111-111111111111";
        let mut page = minute_series(point, start, 60);
        page.samples.push(RawProviderPoint {
            provider_point_id: point.into(),
            display_name: None,
            ts: end,
            val: 99.0,
            unit: None,
            source_quality: None,
            attrs: serde_json::Map::new(),
        });
        let device = DevicePoints {
            device_id: "device-a".into(),
            points: vec![MappedPoint {
                provider_point_id: point.into(),
                role: "sat".into(),
                equip_type: Some("ahu".into()),
            }],
        };
        let accepted = accept_device_window(
            "site-a",
            "nf:site-a",
            &device,
            &[page],
            LogicalWindow { start, end },
        );
        assert_eq!(accepted.samples.len(), 60);
        assert!(accepted.samples.iter().all(|sample| sample.ts < end));
    }

    #[tokio::test]
    async fn accepted_window_sets_last_success_at() {
        let runtime = super::super::Runtime::health_only_for_test("site-a");
        runtime
            .record_hourly(
                "site-a",
                ProviderHealthStatus::Ok,
                60,
                None,
                HourlyCoverageHealth {
                    samples_handed_off: 60,
                    update_log_status: UPDATE_LOG_STATUS.into(),
                    detail: "queue_window".into(),
                    ..HourlyCoverageHealth::default()
                },
                false,
            )
            .await;
        let snap = runtime.health_snapshot().await;
        let site = snap
            .sites
            .iter()
            .find(|site| site.building_id == "site-a")
            .expect("health row");
        assert!(site.health.last_success_at.is_some());
        assert_eq!(site.last_ingested_points, 60);
        assert_eq!(site.health.status, ProviderHealthStatus::Ok);
    }
}
