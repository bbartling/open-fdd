//! Per-site NF history transport: portal REST or PointManager gRPC.
//!
//! Both transports return the same `HistorySeries` into the same queue,
//! planner, and single Timescale writer. The site config picks exactly one.
//! A failure on one transport is reported as that transport's failure; this
//! module never retries a window on the other transport.
//!
//! The gRPC bearer comes from the NF token endpoint (`AuthService.IssueToken`)
//! through the same `NfPortalDriver`. Inventory sync stays on the portal REST
//! read in both modes.

use chrono::{DateTime, Utc};
use openfdd_nf_grpc::{
    BearerToken, HistoryPage, HistoryWindow, Limits, NfGrpcError, NfReadClient, SampleScalar,
    MAX_UUIDS,
};

use super::config::{SiteConfig, SiteTransport};
use super::error::ProviderError;
use super::hourly::FetchError;
use super::http_policy::{
    HttpLimits, MAX_HISTORY_WINDOW, MAX_SAMPLES_PER_RESPONSE, MAX_UUIDS_TOTAL,
};
use super::map::{HistoryFetchPage, RawProviderPoint};
use super::nf::{admit_source_ts, group_history, valid_point_id, NfPortalDriver};

/// One history read failure, tagged with the transport that produced it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HistoryFailure {
    Rest(FetchError),
    Grpc(NfGrpcError),
}

impl HistoryFailure {
    /// Stable operator code. gRPC codes carry a `grpc_` prefix so health and
    /// queue rows show which transport failed and the exact status category.
    pub fn code(&self) -> String {
        match self {
            Self::Rest(err) => err.code().to_string(),
            Self::Grpc(err) => format!("grpc_{}", err.as_str()),
        }
    }

    pub fn ingest_queue_label(&self) -> String {
        match self {
            Self::Rest(err) => err.ingest_queue_label(),
            Self::Grpc(err) => format!("grpc_{}", err.as_str()),
        }
    }

    /// Category for the hourly scheduler.
    pub fn fetch_error(&self) -> FetchError {
        match self {
            Self::Rest(err) => err.clone(),
            Self::Grpc(err) => fetch_error_from_grpc(*err),
        }
    }
}

/// Map gRPC client categories onto the scheduler's retry classes.
pub fn fetch_error_from_grpc(err: NfGrpcError) -> FetchError {
    match err {
        NfGrpcError::AuthNotConfigured | NfGrpcError::AuthFailed | NfGrpcError::Forbidden => {
            FetchError::Auth
        }
        NfGrpcError::Throttled => FetchError::Throttled {
            retry_after_secs: None,
        },
        NfGrpcError::Unimplemented => FetchError::NotImplemented,
        NfGrpcError::InvalidArgument
        | NfGrpcError::NotFound
        | NfGrpcError::ResponseTooLarge
        | NfGrpcError::RequestTooLarge
        | NfGrpcError::Contract => FetchError::Contract,
        NfGrpcError::DeadlineExceeded
        | NfGrpcError::Unavailable
        | NfGrpcError::Internal
        | NfGrpcError::Cancelled
        | NfGrpcError::Transport
        | NfGrpcError::TlsRequired
        | NfGrpcError::Config => FetchError::Transport,
    }
}

struct GrpcSession {
    endpoint: String,
    limits: Limits,
    client: Option<NfReadClient>,
}

/// NF driver plus the site's selected history transport.
pub struct NfTransport {
    driver: NfPortalDriver,
    grpc: Option<GrpcSession>,
}

impl std::fmt::Debug for NfTransport {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("NfTransport")
            .field("driver", &self.driver)
            .field("transport", &self.transport())
            .finish()
    }
}

impl NfTransport {
    pub fn for_site(site: &SiteConfig) -> Result<Self, ProviderError> {
        let driver = NfPortalDriver::new(
            site.provider_instance_id.clone(),
            site.endpoint.clone(),
            site.client_id.clone(),
            site.client_secret.clone(),
            site.anonymous,
            HttpLimits::default(),
        )?;
        Ok(Self::with_driver(driver, site.transport, &site.endpoint))
    }

    pub fn with_driver(driver: NfPortalDriver, transport: SiteTransport, endpoint: &str) -> Self {
        let grpc = match transport {
            SiteTransport::Rest => None,
            SiteTransport::Grpc => Some(GrpcSession {
                endpoint: endpoint.to_string(),
                limits: Limits::default(),
                client: None,
            }),
        };
        Self { driver, grpc }
    }

    #[cfg(test)]
    pub(crate) fn with_grpc_client(driver: NfPortalDriver, client: NfReadClient) -> Self {
        Self {
            driver,
            grpc: Some(GrpcSession {
                endpoint: String::new(),
                limits: Limits::default(),
                client: Some(client),
            }),
        }
    }

    pub fn transport(&self) -> SiteTransport {
        if self.grpc.is_some() {
            SiteTransport::Grpc
        } else {
            SiteTransport::Rest
        }
    }

    pub fn driver(&self) -> &NfPortalDriver {
        &self.driver
    }

    /// Token and inventory calls stay on the portal driver.
    pub fn driver_mut(&mut self) -> &mut NfPortalDriver {
        &mut self.driver
    }

    pub async fn read_history_page(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<HistoryFetchPage, HistoryFailure> {
        let Some(session) = self.grpc.as_mut() else {
            return self
                .driver
                .read_history_page(uuids, from, to)
                .await
                .map_err(HistoryFailure::Rest);
        };
        read_grpc_history(&mut self.driver, session, uuids, from, to).await
    }
}

async fn read_grpc_history(
    driver: &mut NfPortalDriver,
    session: &mut GrpcSession,
    uuids: &[String],
    from: DateTime<Utc>,
    to: DateTime<Utc>,
) -> Result<HistoryFetchPage, HistoryFailure> {
    if uuids.is_empty() {
        return Ok(HistoryFetchPage {
            series: Vec::new(),
            complete: true,
        });
    }
    // Same request bounds as the REST read.
    if uuids.len() > MAX_UUIDS_TOTAL || to < from || to - from > MAX_HISTORY_WINDOW {
        return Err(HistoryFailure::Rest(FetchError::Contract));
    }
    if uuids.iter().any(|uuid| !valid_point_id(uuid)) {
        return Err(HistoryFailure::Rest(FetchError::Contract));
    }
    // REST sends whole seconds (`from.seconds`). Keep the same window.
    let from_s = DateTime::from_timestamp(from.timestamp(), 0)
        .ok_or(HistoryFailure::Rest(FetchError::Contract))?;
    let to_s = DateTime::from_timestamp(to.timestamp(), 0)
        .ok_or(HistoryFailure::Rest(FetchError::Contract))?;
    let window =
        HistoryWindow::new(Some(from_s), Some(to_s), 0, false).map_err(HistoryFailure::Grpc)?;
    // One re-issue on UNAUTHENTICATED, like the REST 401 retry. Never a
    // switch to the REST history read.
    for attempt in 0..2 {
        let token = driver
            .grpc_bearer()
            .await
            .map_err(|_| HistoryFailure::Rest(FetchError::Auth))?;
        let bearer = BearerToken::new(&token).map_err(HistoryFailure::Grpc)?;
        let client = match session.client.as_mut() {
            Some(client) => {
                client.replace_bearer(bearer);
                client
            }
            None => {
                let connected = NfReadClient::connect(&session.endpoint, bearer, session.limits)
                    .await
                    .map_err(HistoryFailure::Grpc)?;
                session.client.insert(connected)
            }
        };
        match read_chunks(client, uuids, &window).await {
            Err(NfGrpcError::AuthFailed) if attempt == 0 => {
                driver.forget_token();
            }
            Err(err) => return Err(HistoryFailure::Grpc(err)),
            Ok(points) => {
                return Ok(HistoryFetchPage {
                    series: group_history(points),
                    complete: true,
                });
            }
        }
    }
    Err(HistoryFailure::Grpc(NfGrpcError::AuthFailed))
}

async fn read_chunks(
    client: &mut NfReadClient,
    uuids: &[String],
    window: &HistoryWindow,
) -> Result<Vec<RawProviderPoint>, NfGrpcError> {
    let mut out = Vec::new();
    for chunk in uuids.chunks(MAX_UUIDS) {
        let ids: Vec<&str> = chunk.iter().map(String::as_str).collect();
        let page = client.point_history(&ids, window).await?;
        let points = raw_points_from_grpc(page)?;
        if out.len().saturating_add(points.len()) > MAX_SAMPLES_PER_RESPONSE {
            return Err(NfGrpcError::ResponseTooLarge);
        }
        out.extend(points);
    }
    Ok(out)
}

/// Same admission rules as `parse_get_data_json`: numeric `double`/`real`
/// only, shared timestamp gate, invalid uuids skipped, sample cap. GetData
/// carries no units or quality, matching the REST JSON for the same RPC.
pub fn raw_points_from_grpc(page: HistoryPage) -> Result<Vec<RawProviderPoint>, NfGrpcError> {
    let mut out = Vec::new();
    for series in page.series {
        if !valid_point_id(series.uuid.trim()) {
            continue;
        }
        for sample in series.samples {
            let val = match sample.value {
                SampleScalar::Double(number) => number,
                SampleScalar::Real(number) => real_as_json_decimal(number)?,
                _ => continue,
            };
            // REST JSON cannot carry NaN/Inf as a number; that page is a
            // contract error there, so it is one here too.
            if !val.is_finite() {
                return Err(NfGrpcError::Contract);
            }
            let Some(ts) = admit_source_ts(sample.at) else {
                continue;
            };
            out.push(RawProviderPoint {
                provider_point_id: series.uuid.clone(),
                display_name: None,
                ts,
                val,
                unit: None,
                source_quality: None,
                attrs: serde_json::Map::new(),
            });
            if out.len() > MAX_SAMPLES_PER_RESPONSE {
                return Err(NfGrpcError::ResponseTooLarge);
            }
        }
    }
    Ok(out)
}

/// The REST gateway prints a proto `float` as its shortest decimal, and the
/// REST parser reads that decimal as `f64`. Do the same so `71.3f32` lands as
/// `71.3`, not `71.30000305175781`.
fn real_as_json_decimal(number: f32) -> Result<f64, NfGrpcError> {
    if !number.is_finite() {
        return Err(NfGrpcError::Contract);
    }
    number
        .to_string()
        .parse::<f64>()
        .map_err(|_| NfGrpcError::Contract)
}

#[cfg(test)]
#[path = "nf_transport_tests.rs"]
mod tests;
