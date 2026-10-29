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
use super::hourly::{assess_page, HourlyPolicy, LogicalWindow};
use super::hourly_exec::{run_hourly_tick, FetchRequest, HistorySource, SampleWriter, TickInput};
use super::map::{
    normalize_mapped, DevicePoints, HistoryFetchPage, HistorySeries, ResolvedRole, RoleResolver,
};
use super::meteo::OpenMeteoDriver;
use super::nf_transport::NfTransport;
use super::store::StoreOpen;
use super::types::{HourlyCoverageHealth, ProviderHealthStatus};
use super::writer;
use super::Runtime;
use crate::state::AppState;

/// Portal page size. A full page is fetched again at the next offset until
/// `totalCount` is met or a short page ends the result.
const INVENTORY_PAGE_SIZE: u32 = 500;

fn poll_enabled() -> bool {
    std::env::var("OPENFDD_PROVIDER_POLL")
        .ok()
        .is_some_and(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes" | "YES"))
}

fn max_concurrent() -> Result<usize, String> {
    crate::ingest_queue::portal_env::provider_max_concurrent_from_env().and_then(|value| {
        usize::try_from(value).map_err(|_| "OPENFDD_PROVIDER_MAX_CONCURRENT overflow".into())
    })
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
        let concurrent = match max_concurrent() {
            Ok(value) => value,
            Err(err) => {
                warn!(error = %err, "invalid OPENFDD_PROVIDER_MAX_CONCURRENT; provider poller idle");
                return;
            }
        };
        let sem = Arc::new(Semaphore::new(concurrent));
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
    /// Portal unit disagreed with the site file, or the canonical value is
    /// outside the role's range. Those samples are not written.
    pub unit_flags: Vec<UnitFlag>,
}

/// Why one sample was withheld instead of written in canonical units.
#[derive(Debug, Clone, PartialEq)]
pub enum UnitFlag {
    /// NF and the site file name different units. Neither value is written.
    Mismatch { nf_unit: String, json_units: String },
    /// Value is outside the role range after conversion to canonical units.
    Range { canonical: f64, low: f64, high: f64 },
}

impl std::fmt::Display for UnitFlag {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Mismatch {
                nf_unit,
                json_units,
            } => write!(f, "nf_unit_mismatch nf={nf_unit} json={json_units}"),
            Self::Range {
                canonical,
                low,
                high,
            } => write!(f, "nf_unit_range value={canonical} bounds={low}..{high}"),
        }
    }
}

/// Historian temperature unit. SQL FDD stores °F (`imperial-f-v1`).
const CANONICAL_TEMPERATURE_UNIT: &str = "degF";

#[derive(Clone, PartialEq, Eq)]
enum UnitClass {
    Celsius,
    Fahrenheit,
    Percent,
    Other(String),
}

fn unit_token(raw: &str) -> String {
    raw.chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .flat_map(|c| c.to_lowercase())
        .collect()
}

fn unknown_unit_token(token: &str) -> bool {
    matches!(
        token,
        "unknown"
            | "unitsunknown"
            | "none"
            | "null"
            | "na"
            | "nounits"
            | "unitsnounits"
            | "notavailable"
    )
}

/// `None` means the portal omitted the unit or reported it as unknown.
fn classify_unit(raw: &str) -> Option<UnitClass> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed == "%" || trimmed.eq_ignore_ascii_case("%rh") {
        return Some(UnitClass::Percent);
    }
    let token = unit_token(trimmed);
    if token.is_empty() || unknown_unit_token(&token) {
        return None;
    }
    Some(match token.as_str() {
        "c" | "degc" | "celsius" | "degreescelsius" | "centigrade" => UnitClass::Celsius,
        "f" | "degf" | "fahrenheit" | "degreesfahrenheit" => UnitClass::Fahrenheit,
        "percent" | "percentrelativehumidity" | "rh" | "pct" => UnitClass::Percent,
        _ => UnitClass::Other(token),
    })
}

fn attr_owned(attrs: &serde_json::Map<String, serde_json::Value>, key: &str) -> Option<String> {
    attrs
        .get(key)
        .and_then(|value| value.as_str())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn put_attr(attrs: &mut serde_json::Map<String, serde_json::Value>, key: &str, value: &str) {
    if value.is_empty() {
        return;
    }
    attrs.insert(
        key.to_string(),
        serde_json::Value::String(value.to_string()),
    );
}

/// Hot-water temperatures sit above the air-side band. Role match is exact.
fn temperature_bounds(role: &str) -> (f64, f64) {
    let sql = fdd_core::columns::haystack_point_to_role(role);
    let hot_water = matches!(
        sql.as_str(),
        "hw_supply_t" | "hw_return_t" | "hw_supply_temp" | "hw_return_temp"
    ) || matches!(
        role.trim().to_ascii_lowercase().as_str(),
        "hw-supply-temp" | "hw-return-temp" | "hot-water-supply-temp" | "hot-water-return-temp"
    );
    if hot_water {
        (32.0, 220.0)
    } else {
        (-40.0, 130.0)
    }
}

struct AdmittedUnit {
    class: UnitClass,
    source: String,
    from: &'static str,
}

/// Convert one portal sample into canonical units before the Timescale write.
///
/// The site-file `units` value is used only when NF omitted the unit or reported
/// it as unknown. A disagreement is returned and the sample is left unchanged.
pub fn apply_nf_unit_policy(sample: &mut super::types::NormalizedSample) -> Result<(), UnitFlag> {
    if attr_owned(&sample.attrs, "nf_unit_policy").as_deref() == Some("applied") {
        return Ok(());
    }
    let reported_nf = attr_owned(&sample.attrs, "nf_unit");
    let configured = attr_owned(&sample.attrs, "configured_units");
    let stamped =
        sample.attrs.contains_key("nf_unit") || sample.attrs.contains_key("configured_units");
    let nf_unit = if stamped {
        reported_nf
    } else {
        sample
            .unit
            .as_deref()
            .map(str::trim)
            .filter(|unit| !unit.is_empty())
            .map(str::to_string)
    };
    let nf_class = nf_unit.as_deref().and_then(classify_unit);
    let json_class = configured.as_deref().and_then(classify_unit);
    let admitted = match (nf_class, json_class) {
        (Some(left), Some(right)) if left != right => {
            return Err(UnitFlag::Mismatch {
                nf_unit: nf_unit.unwrap_or_default(),
                json_units: configured.unwrap_or_default(),
            });
        }
        (None, Some(class)) => AdmittedUnit {
            class,
            source: configured.unwrap_or_default(),
            from: "provider_sites",
        },
        (Some(class), _) => AdmittedUnit {
            class,
            source: nf_unit.unwrap_or_default(),
            from: "nf",
        },
        (None, None) => {
            put_attr(&mut sample.attrs, "nf_unit_policy", "applied");
            return Ok(());
        }
    };
    if matches!(admitted.class, UnitClass::Celsius | UnitClass::Fahrenheit) {
        let canonical = match admitted.class {
            UnitClass::Celsius => fdd_core::celsius_to_fahrenheit(sample.val),
            _ => sample.val,
        };
        let (low, high) = temperature_bounds(&sample.role);
        if !canonical.is_finite() || canonical < low || canonical > high {
            return Err(UnitFlag::Range {
                canonical,
                low,
                high,
            });
        }
        sample.val = canonical;
        sample.unit = Some(CANONICAL_TEMPERATURE_UNIT.to_string());
        put_attr(&mut sample.attrs, "source_unit", &admitted.source);
        put_attr(
            &mut sample.attrs,
            "canonical_unit",
            CANONICAL_TEMPERATURE_UNIT,
        );
        put_attr(&mut sample.attrs, "unit_from", admitted.from);
    } else {
        put_attr(&mut sample.attrs, "source_unit", &admitted.source);
        // An unknown portal token must not stay on the row once the site file named the unit.
        let replace_unit = admitted.from == "provider_sites"
            || sample.unit.as_deref().is_none_or(|unit| unit.is_empty());
        if replace_unit {
            sample.unit = Some(admitted.source);
        }
    }
    put_attr(&mut sample.attrs, "nf_unit_policy", "applied");
    Ok(())
}

pub(crate) fn canonicalize_nf_samples(
    samples: Vec<super::types::NormalizedSample>,
) -> (Vec<super::types::NormalizedSample>, Vec<UnitFlag>) {
    let mut ready = Vec::with_capacity(samples.len());
    let mut flags = Vec::new();
    for mut sample in samples {
        match apply_nf_unit_policy(&mut sample) {
            Ok(()) => ready.push(sample),
            Err(flag) => {
                warn!(
                    code = "nf_unit_flag",
                    flag = %flag,
                    provider_point_id = %sample.provider_point_id,
                    role = %sample.role,
                    "NF unit policy withheld a sample"
                );
                flags.push(flag);
            }
        }
    }
    (ready, flags)
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
                point.configured_units.clone(),
            ),
        ));
    }
    let (samples, unit_flags) = canonicalize_nf_samples(samples);
    WindowAccept {
        samples,
        unit_flags,
    }
}

fn chosen_resolver<'a>(live: &'a RoleResolver, site: &'a RoleResolver) -> &'a RoleResolver {
    // A committed plan with no devices is a finished empty inventory. Only a
    // missing plan (no revision) falls back to the site resolver.
    if live.model_revision().is_none() && site.mapped_count() > 0 {
        site
    } else {
        live
    }
}

/// GET one claimed queue window. This does not write samples and does not
/// mark the window committed. History stays `GET /api/v1/point/data`.
pub async fn fetch_device_window(
    state: &Arc<AppState>,
    site: &SiteConfig,
    device_id: &str,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> Result<HistoryFetchPage, String> {
    if !matches!(site.kind, super::types::ProviderKind::Nf) {
        return Err("not_implemented".into());
    }
    if end <= start {
        return Err("invalid_window".into());
    }
    let runtime = Arc::clone(&state.providers);
    let mut transport = NfTransport::for_site(site).map_err(|_| "config_invalid".to_string())?;
    if transport.driver_mut().authenticate().await.is_err() {
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
    let page = match transport.read_history_page(&ids, start, end).await {
        Ok(page) => page,
        Err(err) => {
            let code = err.ingest_queue_label();
            runtime
                .record_error(
                    &site.building_id,
                    ProviderHealthStatus::Error,
                    Some(code.clone()),
                )
                .await;
            if code.starts_with("throttled") {
                runtime.record_portal_throttle(&site.building_id).await;
            }
            return Err(code);
        }
    };
    if page.complete {
        runtime.clear_portal_throttle(&site.building_id).await;
    }
    Ok(page)
}

/// Write samples that already fall inside `[start, end)`. A successful write
/// is not a coverage commit.
pub async fn write_device_window(
    state: &Arc<AppState>,
    site: &SiteConfig,
    device: &DevicePoints,
    page: &[HistorySeries],
    start: DateTime<Utc>,
    end: DateTime<Utc>,
) -> Result<super::writer::ProviderIngestReceipt, String> {
    let accepted = accept_device_window(
        &site.building_id,
        &site.provider_instance_id,
        device,
        page,
        LogicalWindow { start, end },
    );
    if !accepted.unit_flags.is_empty() {
        warn!(
            building_id = %site.building_id,
            withheld = accepted.unit_flags.len(),
            "NF unit policy withheld samples before the Timescale write"
        );
    }
    if accepted.samples.is_empty() {
        return Ok(super::writer::ProviderIngestReceipt {
            submitted: 0,
            eligible: 0,
            skipped: 0,
            persisted_rows: 0,
            inserted_rows: 0,
            updated_rows: 0,
        });
    }
    match writer::ingest_samples(
        state,
        &site.building_id,
        &site.provider_instance_id,
        &accepted.samples,
    )
    .await
    {
        Ok(receipt) => Ok(receipt),
        Err(_) => {
            state
                .providers
                .record_error(
                    &site.building_id,
                    ProviderHealthStatus::Error,
                    Some("persistence".into()),
                )
                .await;
            Err("persistence".into())
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
    let mut transport = match NfTransport::for_site(&site) {
        Ok(transport) => transport,
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
        identity = %super::driver_identity(transport.driver()),
        transport = transport.transport().as_str(),
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
        if transport.driver_mut().authenticate().await.is_err() {
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
        let inventory_note = match transport
            .driver_mut()
            .query_inventory(INVENTORY_PAGE_SIZE)
            .await
        {
            Ok(snapshot) => {
                let outcome =
                    super::inventory_sync::apply(&runtime, &state.haystack_rdf, &site, &snapshot)
                        .await;
                if !snapshot.complete {
                    let code = snapshot
                        .diagnostics
                        .reason
                        .clone()
                        .unwrap_or_else(|| "inventory_incomplete".to_string());
                    warn!(%building_id, reason = %code, "NF inventory incomplete; last plan kept");
                    Some(code)
                } else if !outcome.errors.is_empty() {
                    warn!(%building_id, errors = ?outcome.errors, "NF inventory sync incomplete");
                    outcome.errors.first().cloned()
                } else {
                    None
                }
            }
            Err(_) => {
                warn!(%building_id, "NF inventory read failed; model left as last synced");
                Some("inventory_read_failed".to_string())
            }
        };
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
        let provider_instance = transport.driver().provider_id().to_string();
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
            transport: &mut transport,
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
                if let Some(code) = inventory_note {
                    if !as_error {
                        runtime
                            .record_error(&building_id, ProviderHealthStatus::Degraded, Some(code))
                            .await;
                    }
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
    transport: &'a mut NfTransport,
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
                transport = self.transport.transport().as_str(),
                "NF history read"
            );
            self.transport
                .read_history_page(&req.point_ids, req.from, req.to)
                .await
                .map_err(|failure| {
                    warn!(
                        device_id = %req.device_id,
                        code = %failure.code(),
                        "NF history read failed"
                    );
                    failure.fetch_error()
                })
                .and_then(|page| {
                    if page.complete {
                        Ok(page.series)
                    } else {
                        Err(super::hourly::FetchError::PartialSeries)
                    }
                })
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
                .map(|page| page.series)
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
            let (ready, _) = canonicalize_nf_samples(samples.to_vec());
            let receipt = writer::ingest_samples(
                self.state,
                self.building_id,
                self.provider_instance_id,
                &ready,
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

    pub async fn record_portal_throttle(&self, building_id: &str) {
        let mut guard = self.health.lock().await;
        if let Some(site) = guard
            .sites
            .iter_mut()
            .find(|s| s.building_id == building_id)
        {
            let now = Utc::now();
            site.portal_throttle_count = site.portal_throttle_count.saturating_add(1);
            if site.portal_throttled_since.is_none() {
                site.portal_throttled_since = Some(now);
            }
            site.health.status = ProviderHealthStatus::Degraded;
            site.health.message = Some("throttled".into());
        }
    }

    pub async fn clear_portal_throttle(&self, building_id: &str) {
        let mut guard = self.health.lock().await;
        if let Some(site) = guard
            .sites
            .iter_mut()
            .find(|s| s.building_id == building_id)
        {
            site.portal_throttle_count = 0;
            site.portal_throttled_since = None;
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
                configured_units: None,
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
                    update_log_status: super::super::hourly::UPDATE_LOG_STATUS.into(),
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

    #[test]
    fn empty_committed_plan_is_not_replaced_by_the_site_resolver() {
        use crate::providers::committed_model::{
            model_from_point_map, CommittedModelStore, ModelScope,
        };
        use crate::providers::map::{PointMapEntry, RoleResolver};
        let scope = ModelScope {
            tenant_id: "tenant-a".into(),
            site_id: "site-a".into(),
            provider_instance_id: "nf-conn-a".into(),
        };
        let model = model_from_point_map(&scope, &[]).unwrap();
        let mut store = CommittedModelStore::default();
        store.try_activate(None, &model).unwrap();
        let plan = store.active_plan("tenant-a", "site-a").unwrap().clone();
        let live = RoleResolver::from_plan(&plan);
        let site = RoleResolver::from_point_map(&[PointMapEntry {
            provider_point_id: "pt-site".into(),
            semantic_point_id: None,
            equipment_id: "EQ_MAIN".into(),
            role: "sat".into(),
            equip_type: Some("ahu".into()),
            unit: None,
            units: None,
            kind: None,
            provisional: false,
        }])
        .unwrap();
        let chosen = chosen_resolver(&live, &site);
        assert_eq!(chosen.mapped_count(), 0);
        assert!(chosen.model_revision().is_some());
        let unset = RoleResolver::default();
        let fallback = chosen_resolver(&unset, &site);
        assert_eq!(fallback.mapped_count(), 1);
    }

    fn zoned(
        point_id: &str,
        role: &str,
        val: f64,
        nf_unit: Option<&str>,
        json_units: Option<&str>,
    ) -> WindowAccept {
        let start = Utc.with_ymd_and_hms(2026, 6, 1, 12, 0, 0).unwrap();
        let device = DevicePoints {
            device_id: "device-a".into(),
            points: vec![MappedPoint {
                provider_point_id: point_id.into(),
                role: role.into(),
                equip_type: Some("vav".into()),
                configured_units: json_units.map(str::to_string),
            }],
        };
        let page = HistorySeries {
            provider_point_id: point_id.into(),
            samples: vec![RawProviderPoint {
                provider_point_id: point_id.into(),
                display_name: None,
                ts: start,
                val,
                unit: nf_unit.map(str::to_string),
                source_quality: None,
                attrs: serde_json::Map::new(),
            }],
        };
        accept_device_window(
            "site-a",
            "nf:site-a",
            &device,
            &[page],
            LogicalWindow {
                start,
                end: start + ChronoDuration::hours(1),
            },
        )
    }

    #[test]
    fn celsius_portal_unit_is_stored_as_fahrenheit() {
        let accepted = zoned(
            "11111111-1111-4111-8111-111111111111",
            "zone-air-temp",
            21.0,
            Some("DEGREES_CELSIUS"),
            None,
        );
        assert!(accepted.unit_flags.is_empty());
        assert_eq!(accepted.samples.len(), 1);
        let sample = &accepted.samples[0];
        assert!((sample.val - 69.8).abs() < 1e-9);
        assert_eq!(sample.unit.as_deref(), Some("degF"));
        assert_eq!(
            sample.attrs.get("source_unit").and_then(|v| v.as_str()),
            Some("DEGREES_CELSIUS")
        );
        let again = {
            let mut copy = sample.clone();
            apply_nf_unit_policy(&mut copy).unwrap();
            copy.val
        };
        assert!((again - sample.val).abs() < 1e-9);
    }

    #[test]
    fn unknown_portal_unit_uses_the_site_file() {
        let accepted = zoned(
            "22222222-2222-4222-8222-222222222222",
            "zone-air-temp",
            0.0,
            Some("UNITS_UNKNOWN"),
            Some("degC"),
        );
        assert!(accepted.unit_flags.is_empty());
        let sample = &accepted.samples[0];
        assert!((sample.val - 32.0).abs() < 1e-9);
        assert_eq!(sample.unit.as_deref(), Some("degF"));
        assert_eq!(
            sample.attrs.get("source_unit").and_then(|v| v.as_str()),
            Some("degC")
        );
        assert_eq!(
            sample.attrs.get("unit_from").and_then(|v| v.as_str()),
            Some("provider_sites")
        );
        assert_eq!(
            sample.attrs.get("nf_unit").and_then(|v| v.as_str()),
            Some("UNITS_UNKNOWN")
        );
        let humidity = zoned(
            "77777777-7777-4777-8777-777777777777",
            "outside-air-humidity",
            40.0,
            Some("UNITS_UNKNOWN"),
            Some("%"),
        );
        assert!(humidity.unit_flags.is_empty());
        assert_eq!(humidity.samples[0].unit.as_deref(), Some("%"));
        assert!((humidity.samples[0].val - 40.0).abs() < 1e-9);
    }

    #[test]
    fn portal_and_site_file_unit_mismatch_is_flagged() {
        let accepted = zoned(
            "33333333-3333-4333-8333-333333333333",
            "zone-air-temp",
            21.0,
            Some("DEGREES_CELSIUS"),
            Some("degF"),
        );
        assert!(accepted.samples.is_empty());
        assert_eq!(
            accepted.unit_flags,
            vec![UnitFlag::Mismatch {
                nf_unit: "DEGREES_CELSIUS".into(),
                json_units: "degF".into(),
            }]
        );
    }

    #[test]
    fn range_check_uses_the_converted_value() {
        let hot = zoned(
            "44444444-4444-4444-8444-444444444444",
            "zone-air-temp",
            90.0,
            Some("DEGREES_CELSIUS"),
            None,
        );
        assert!(hot.samples.is_empty());
        match &hot.unit_flags[..] {
            [UnitFlag::Range {
                canonical,
                low,
                high,
            }] => {
                assert!((canonical - 194.0).abs() < 1e-9);
                assert_eq!(*low, -40.0);
                assert_eq!(*high, 130.0);
            }
            other => panic!("expected range flag, got {other:?}"),
        }
        let plant = zoned(
            "55555555-5555-4555-8555-555555555555",
            "hw-supply-temp",
            90.0,
            Some("DEGREES_CELSIUS"),
            None,
        );
        assert!(plant.unit_flags.is_empty());
        assert!((plant.samples[0].val - 194.0).abs() < 1e-9);
    }

    #[test]
    fn percent_samples_stay_on_the_reported_unit() {
        let accepted = zoned(
            "66666666-6666-4666-8666-666666666666",
            "damper",
            40.0,
            Some("PERCENT"),
            None,
        );
        assert!(accepted.unit_flags.is_empty());
        let sample = &accepted.samples[0];
        assert!((sample.val - 40.0).abs() < 1e-9);
        assert_eq!(sample.unit.as_deref(), Some("PERCENT"));
        assert_eq!(
            sample.attrs.get("source_unit").and_then(|v| v.as_str()),
            Some("PERCENT")
        );
    }
}
