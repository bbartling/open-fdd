//! Central connector capability aggregation and the scoped read-only proxy.
//!
//! Capability refresh is explicit: `/api/health` never probes an OT edge.
//! Upstreams come only from server configuration, use the configured bearer,
//! reject redirects, and are bounded by timeout, body size, concurrency,
//! caching, and retry backoff.  User supplied URLs are never accepted.

use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::http::StatusCode;
use chrono::Utc;
use futures_util::StreamExt;
use openfdd_contracts::{
    CapabilitiesAggregateResponse, CapabilityState, ConnectorAction, ConnectorCapability,
    ConnectorHelloResponse, ConnectorProtocol, ConnectorReadRequest, ConnectorReadResponse,
    DeliveryStatus, RecipeObservation, ServiceVersion, UpstreamCapability,
    CAPABILITIES_AGGREGATE_CONTRACT_V1, CAPABILITIES_CONTRACT_V1,
};
use reqwest::redirect::Policy;
use reqwest::Client;
use tokio::sync::{Mutex, Semaphore};
use tokio::time::timeout;
use url::Url;

use crate::state::AppState;

const DEFAULT_TTL: Duration = Duration::from_secs(30);
const MAX_STALE: Duration = Duration::from_secs(300);
const MAX_BODY_BYTES: usize = 256 * 1024;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(3);
const MAX_UPSTREAMS: usize = 32;
const MAX_CONCURRENT_PROBES: usize = 4;

#[derive(Clone)]
struct ConfiguredUpstream {
    edge_id: String,
    base_url: Url,
    token: Option<String>,
}

struct CacheState {
    report: Option<CapabilitiesAggregateResponse>,
    fetched_at: Option<Instant>,
    next_retry_at: Option<Instant>,
    failures: u32,
}

#[derive(Debug, Clone, Copy)]
enum ProbeFailure {
    Unreachable,
    AuthFailure,
    Incompatible,
}

impl ProbeFailure {
    fn state(self) -> CapabilityState {
        match self {
            Self::Unreachable => CapabilityState::Unreachable,
            Self::AuthFailure => CapabilityState::AuthFailure,
            Self::Incompatible => CapabilityState::Incompatible,
        }
    }

    fn message(self) -> &'static str {
        match self {
            Self::Unreachable => "upstream unavailable",
            Self::AuthFailure => "upstream authentication failed",
            Self::Incompatible => "upstream capability contract incompatible",
        }
    }
}

pub struct CapabilitiesAggregator {
    client: Option<Client>,
    upstreams: Vec<ConfiguredUpstream>,
    cache: Mutex<CacheState>,
    refresh_gate: Semaphore,
    probe_gate: Arc<Semaphore>,
    ttl: Duration,
    max_stale: Duration,
}

impl CapabilitiesAggregator {
    pub fn from_env() -> Arc<Self> {
        let (upstreams, config_errors) = configured_upstreams_from_env();
        let client = Client::builder()
            .redirect(Policy::none())
            .connect_timeout(REQUEST_TIMEOUT)
            .timeout(REQUEST_TIMEOUT)
            .build()
            .ok();
        let initial_error = if config_errors.is_empty() {
            None
        } else {
            Some(config_errors.join("; "))
        };
        Arc::new(Self {
            client,
            upstreams,
            cache: Mutex::new(CacheState {
                report: initial_error.map(|error| empty_report(Some(error))),
                fetched_at: None,
                next_retry_at: None,
                failures: 0,
            }),
            refresh_gate: Semaphore::new(1),
            probe_gate: Arc::new(Semaphore::new(MAX_CONCURRENT_PROBES)),
            ttl: env_duration("OPENFDD_CAPABILITIES_CACHE_SECS", DEFAULT_TTL, 1, 300),
            max_stale: env_duration("OPENFDD_CAPABILITIES_MAX_STALE_SECS", MAX_STALE, 30, 3600),
        })
    }

    #[cfg(test)]
    fn for_tests(upstreams: Vec<ConfiguredUpstream>) -> Arc<Self> {
        Arc::new(Self {
            client: Client::builder()
                .redirect(Policy::none())
                .connect_timeout(Duration::from_millis(250))
                .timeout(Duration::from_millis(500))
                .build()
                .ok(),
            upstreams,
            cache: Mutex::new(CacheState {
                report: None,
                fetched_at: None,
                next_retry_at: None,
                failures: 0,
            }),
            refresh_gate: Semaphore::new(1),
            probe_gate: Arc::new(Semaphore::new(MAX_CONCURRENT_PROBES)),
            ttl: Duration::from_millis(20),
            max_stale: Duration::from_millis(100),
        })
    }

    /// Refresh configured upstream hello responses, or return a bounded cached
    /// snapshot while a failed probe is in backoff.
    pub async fn snapshot(&self, central: ConnectorHelloResponse) -> CapabilitiesAggregateResponse {
        let now = Instant::now();
        {
            let cache = self.cache.lock().await;
            if let Some(report) = cache.report.as_ref() {
                if cache
                    .fetched_at
                    .is_some_and(|fetched| now.duration_since(fetched) < self.ttl)
                {
                    return replace_central(report.clone(), central);
                }
                if cache.next_retry_at.is_some_and(|retry| now < retry) {
                    let expired = cache
                        .fetched_at
                        .is_some_and(|fetched| now.duration_since(fetched) > self.max_stale);
                    return stale_report(report.clone(), central, expired);
                }
            }
        }

        let permit = match timeout(Duration::from_secs(2), self.refresh_gate.acquire()).await {
            Ok(Ok(permit)) => permit,
            _ => {
                let cache = self.cache.lock().await;
                if let Some(report) = cache.report.as_ref() {
                    return stale_report(report.clone(), central, true);
                }
                return with_central(empty_report(None), central);
            }
        };
        let _permit = permit;

        // A different request may have filled the cache while this request
        // waited for the refresh gate.
        {
            let cache = self.cache.lock().await;
            if let Some(report) = cache.report.as_ref() {
                if cache
                    .fetched_at
                    .is_some_and(|fetched| Instant::now().duration_since(fetched) < self.ttl)
                {
                    return replace_central(report.clone(), central);
                }
            }
        }

        let upstreams = self.probe_all().await;
        let failed = upstreams.iter().any(|upstream| {
            matches!(
                upstream.state,
                CapabilityState::Unreachable
                    | CapabilityState::AuthFailure
                    | CapabilityState::Incompatible
                    | CapabilityState::Stale
            )
        });
        let mut cache = self.cache.lock().await;
        let report = aggregate_report(central, upstreams);
        cache.report = Some(report.clone());
        cache.fetched_at = Some(Instant::now());
        if failed {
            cache.failures = cache.failures.saturating_add(1);
            let shift = cache.failures.min(5);
            cache.next_retry_at = Some(Instant::now() + Duration::from_secs(2u64.pow(shift)));
        } else {
            cache.failures = 0;
            cache.next_retry_at = None;
        }
        report
    }

    async fn probe_all(&self) -> Vec<UpstreamCapability> {
        if self.upstreams.is_empty() {
            return Vec::new();
        }
        let futures = self
            .upstreams
            .iter()
            .map(|upstream| self.probe_one(upstream));
        futures_util::future::join_all(futures).await
    }

    async fn probe_one(&self, upstream: &ConfiguredUpstream) -> UpstreamCapability {
        let address = redacted_address(&upstream.base_url);
        let previous = {
            let cache = self.cache.lock().await;
            cache.report.as_ref().and_then(|report| {
                report
                    .upstreams
                    .iter()
                    .find(|candidate| candidate.edge_id == upstream.edge_id)
                    .cloned()
            })
        };
        let Some(client) = self.client.as_ref() else {
            return failed_upstream(upstream, previous, ProbeFailure::Incompatible);
        };
        if upstream.token.is_none() && !central_bool("OPENFDD_FIELDBUS_UPSTREAM_ALLOW_ANONYMOUS") {
            return failed_upstream(upstream, previous, ProbeFailure::AuthFailure);
        }
        let Ok(_probe_permit) = timeout(Duration::from_secs(2), self.probe_gate.acquire()).await
        else {
            return failed_upstream(upstream, previous, ProbeFailure::Unreachable);
        };
        let endpoint = match endpoint(&upstream.base_url, "api/connector/hello") {
            Ok(endpoint) => endpoint,
            Err(_) => return failed_upstream(upstream, previous, ProbeFailure::Incompatible),
        };
        let mut request = client.get(endpoint);
        if let Some(token) = upstream.token.as_deref() {
            request = request.bearer_auth(token);
        }
        let response = match timeout(REQUEST_TIMEOUT, request.send()).await {
            Ok(Ok(response)) => response,
            _ => return failed_upstream(upstream, previous, ProbeFailure::Unreachable),
        };
        let status = response.status();
        if status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN {
            return failed_upstream(upstream, previous, ProbeFailure::AuthFailure);
        }
        if !status.is_success() || status.is_redirection() {
            return failed_upstream(upstream, previous, ProbeFailure::Incompatible);
        }
        let body = match bounded_body(response).await {
            Ok(body) => body,
            Err(()) => return failed_upstream(upstream, previous, ProbeFailure::Incompatible),
        };
        let hello = match serde_json::from_slice::<ConnectorHelloResponse>(&body) {
            Ok(hello) if hello.validate().is_ok() => hello,
            _ => return failed_upstream(upstream, previous, ProbeFailure::Incompatible),
        };
        UpstreamCapability {
            edge_id: upstream.edge_id.clone(),
            address,
            state: CapabilityState::Ready,
            hello: Some(hello),
            error: None,
            last_success_at: Some(Utc::now()),
        }
    }

    /// Forward one explicitly requested read through a configured edge.  The
    /// request carries no URL or network address and is scope checked by the
    /// route before this method is called.
    pub async fn proxy_read(
        &self,
        edge_id: &str,
        request: &ConnectorReadRequest,
    ) -> Result<ConnectorReadResponse, ProxyError> {
        request.validate().map_err(|_| ProxyError::BadRequest)?;
        let upstream = self
            .upstreams
            .iter()
            .find(|upstream| upstream.edge_id == edge_id)
            .ok_or(ProxyError::NotConfigured)?;
        if upstream.token.is_none() && !central_bool("OPENFDD_FIELDBUS_UPSTREAM_ALLOW_ANONYMOUS") {
            return Err(ProxyError::AuthFailure);
        }
        let client = self.client.as_ref().ok_or(ProxyError::Incompatible)?;
        let _probe_permit = timeout(Duration::from_secs(2), self.probe_gate.acquire())
            .await
            .map_err(|_| ProxyError::Unreachable)?
            .map_err(|_| ProxyError::Unreachable)?;
        let endpoint = endpoint(&upstream.base_url, "api/connector/read")
            .map_err(|_| ProxyError::Incompatible)?;
        let mut outgoing = client.post(endpoint).json(request);
        if let Some(token) = upstream.token.as_deref() {
            outgoing = outgoing.bearer_auth(token);
        }
        let response = timeout(REQUEST_TIMEOUT, outgoing.send())
            .await
            .map_err(|_| ProxyError::Unreachable)?
            .map_err(|_| ProxyError::Unreachable)?;
        if response.status() == StatusCode::UNAUTHORIZED
            || response.status() == StatusCode::FORBIDDEN
        {
            return Err(ProxyError::AuthFailure);
        }
        if !response.status().is_success() || response.status().is_redirection() {
            return Err(ProxyError::Incompatible);
        }
        let body = bounded_body(response)
            .await
            .map_err(|_| ProxyError::Incompatible)?;
        let result: ConnectorReadResponse =
            serde_json::from_slice(&body).map_err(|_| ProxyError::Incompatible)?;
        if result.request_id != request.request_id || result.scope != request.scope {
            return Err(ProxyError::Incompatible);
        }
        Ok(result)
    }
}

async fn bounded_body(response: reqwest::Response) -> Result<Vec<u8>, ()> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_BODY_BYTES as u64)
    {
        return Err(());
    }
    let mut stream = response.bytes_stream();
    let mut body = Vec::new();
    while let Some(chunk) = timeout(REQUEST_TIMEOUT, stream.next())
        .await
        .map_err(|_| ())?
    {
        let chunk = chunk.map_err(|_| ())?;
        if body.len().saturating_add(chunk.len()) > MAX_BODY_BYTES {
            return Err(());
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProxyError {
    BadRequest,
    NotConfigured,
    Unreachable,
    AuthFailure,
    Incompatible,
}

impl ProxyError {
    pub fn status(self) -> StatusCode {
        match self {
            Self::BadRequest => StatusCode::BAD_REQUEST,
            Self::NotConfigured => StatusCode::NOT_FOUND,
            Self::Unreachable => StatusCode::BAD_GATEWAY,
            Self::AuthFailure => StatusCode::BAD_GATEWAY,
            Self::Incompatible => StatusCode::BAD_GATEWAY,
        }
    }

    pub fn message(self) -> &'static str {
        match self {
            Self::BadRequest => "invalid read proxy request",
            Self::NotConfigured => "edge connector is not configured",
            Self::Unreachable => "edge connector is unreachable",
            Self::AuthFailure => "edge connector authentication failed",
            Self::Incompatible => "edge connector read contract is incompatible",
        }
    }
}

fn failed_upstream(
    upstream: &ConfiguredUpstream,
    previous: Option<UpstreamCapability>,
    failure: ProbeFailure,
) -> UpstreamCapability {
    let stale = previous
        .as_ref()
        .and_then(|previous| previous.hello.as_ref())
        .is_some();
    let last_success_at = previous
        .as_ref()
        .and_then(|previous| previous.last_success_at);
    UpstreamCapability {
        edge_id: upstream.edge_id.clone(),
        address: redacted_address(&upstream.base_url),
        state: if stale {
            CapabilityState::Stale
        } else {
            failure.state()
        },
        hello: previous.and_then(|previous| previous.hello),
        error: Some(failure.message().into()),
        last_success_at,
    }
}

fn stale_report(
    mut report: CapabilitiesAggregateResponse,
    central: ConnectorHelloResponse,
    expired: bool,
) -> CapabilitiesAggregateResponse {
    if expired {
        for upstream in &mut report.upstreams {
            if upstream.state == CapabilityState::Ready {
                upstream.state = CapabilityState::Stale;
            }
        }
    }
    replace_central(report, central)
}

fn replace_central(
    mut report: CapabilitiesAggregateResponse,
    central: ConnectorHelloResponse,
) -> CapabilitiesAggregateResponse {
    report.central = central;
    report.observed_at = Utc::now();
    report
}

fn with_central(
    mut report: CapabilitiesAggregateResponse,
    central: ConnectorHelloResponse,
) -> CapabilitiesAggregateResponse {
    report.central = central;
    report.observed_at = Utc::now();
    report
}

fn aggregate_report(
    central: ConnectorHelloResponse,
    upstreams: Vec<UpstreamCapability>,
) -> CapabilitiesAggregateResponse {
    let mut observed_services = vec!["central".to_string()];
    if !upstreams.is_empty() {
        observed_services.push("fieldbus".into());
    }
    let declared = central.recipe.declared.clone();
    let reconciliation = match declared.as_deref() {
        None => "not_declared",
        Some("csv") if upstreams.is_empty() => "matched",
        Some("central") if upstreams.is_empty() => "matched",
        Some("edge") | Some("standalone") if !upstreams.is_empty() => "matched",
        Some(_) => "observed_extra",
    };
    let recipe = RecipeObservation {
        declared,
        observed_services,
        reconciliation: reconciliation.into(),
    };
    CapabilitiesAggregateResponse {
        schema: CAPABILITIES_AGGREGATE_CONTRACT_V1.into(),
        version: ServiceVersion {
            service: "openfdd-central".into(),
            build: central.version.build.clone(),
            contract: CAPABILITIES_AGGREGATE_CONTRACT_V1.into(),
        },
        central,
        upstreams,
        recipe,
        observed_at: Utc::now(),
    }
}

fn empty_report(error: Option<String>) -> CapabilitiesAggregateResponse {
    let central = ConnectorHelloResponse {
        schema: CAPABILITIES_CONTRACT_V1.into(),
        version: ServiceVersion {
            service: "openfdd-central".into(),
            build: env!("CARGO_PKG_VERSION").into(),
            contract: CAPABILITIES_CONTRACT_V1.into(),
        },
        compiled_protocols: vec![ConnectorProtocol::Mqtt],
        connectors: Vec::new(),
        recipe: RecipeObservation {
            declared: None,
            observed_services: vec!["central".into()],
            reconciliation: "not_declared".into(),
        },
        observed_at: Utc::now(),
    };
    let mut report = aggregate_report(central.clone(), Vec::new());
    if let Some(error) = error {
        report.recipe.reconciliation = error;
    }
    report
}

fn central_bool(name: &str) -> bool {
    std::env::var(name).ok().is_some_and(|value| {
        matches!(
            value.trim().to_ascii_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        )
    })
}

pub fn central_hello(state: &AppState) -> ConnectorHelloResponse {
    let mqtt = central_bool("OPENFDD_MQTT_ENABLED");
    let monitor = state.mqtt_monitor_snapshot();
    let historian = crate::durable_storage::historian_root_present();
    let mqtt_state = if !mqtt {
        DeliveryStatus::Disabled
    } else if monitor.connected {
        DeliveryStatus::Ready
    } else if monitor.errors > 0 {
        DeliveryStatus::Unreachable
    } else {
        DeliveryStatus::Stale
    };
    let durable_state = if historian {
        DeliveryStatus::Ready
    } else {
        DeliveryStatus::Incompatible
    };
    let readiness = if mqtt {
        CapabilityState::Ready
    } else {
        CapabilityState::Disabled
    };
    let source_health = if state
        .last_ingest_at
        .lock()
        .unwrap_or_else(|poison| poison.into_inner())
        .is_some()
    {
        CapabilityState::Ready
    } else {
        CapabilityState::Stale
    };
    let declared = ["OPENFDD_BUILD_RECIPE", "OPENFDD_RECIPE"]
        .into_iter()
        .find_map(|name| {
            std::env::var(name)
                .ok()
                .filter(|value| !value.trim().is_empty())
        });
    ConnectorHelloResponse {
        schema: CAPABILITIES_CONTRACT_V1.into(),
        version: ServiceVersion {
            service: "openfdd-central".into(),
            build: crate::routes::resolve_build_version(),
            contract: CAPABILITIES_CONTRACT_V1.into(),
        },
        compiled_protocols: vec![ConnectorProtocol::Mqtt],
        connectors: vec![ConnectorCapability {
            protocol: ConnectorProtocol::Mqtt,
            compiled: true,
            configured: mqtt,
            enabled: mqtt,
            readiness,
            source_health,
            mqtt_connection: mqtt_state,
            durable_delivery: durable_state,
            supported_actions: vec![ConnectorAction::MetadataRead],
            detail: Some(
                "central MQTT connection and durable historian delivery are separate states".into(),
            ),
        }],
        recipe: RecipeObservation {
            declared,
            observed_services: vec!["central".into()],
            reconciliation: "not_declared".into(),
        },
        observed_at: Utc::now(),
    }
}

fn env_duration(name: &str, default: Duration, min: u64, max: u64) -> Duration {
    let seconds = std::env::var(name)
        .ok()
        .and_then(|raw| raw.parse::<u64>().ok())
        .unwrap_or(default.as_secs())
        .clamp(min, max);
    Duration::from_secs(seconds)
}

fn configured_upstreams_from_env() -> (Vec<ConfiguredUpstream>, Vec<String>) {
    let raw = std::env::var("OPENFDD_FIELDBUS_UPSTREAMS")
        .ok()
        .or_else(|| {
            std::env::var("OPENFDD_FIELDBUS_UPSTREAM_URL")
                .ok()
                .map(|url| {
                    format!(
                        "{}={url}",
                        std::env::var("OPENFDD_EDGE_ID").unwrap_or_else(|_| "fieldbus-1".into())
                    )
                })
        });
    let token = std::env::var("OPENFDD_FIELDBUS_UPSTREAM_TOKEN")
        .or_else(|_| std::env::var("OPENFDD_FIELDBUS_API_KEY"))
        .ok()
        .filter(|token| !token.trim().is_empty());
    let mut upstreams = Vec::new();
    let mut errors = Vec::new();
    for (index, item) in raw
        .unwrap_or_default()
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .enumerate()
    {
        let Some((edge_id, raw_url)) = item.split_once('=') else {
            errors.push(format!("upstream {index} is malformed"));
            continue;
        };
        let edge_id = edge_id.trim();
        if edge_id.is_empty() || edge_id.contains('/') || edge_id.contains("..") {
            errors.push(format!("upstream {index} has an invalid edge id"));
            continue;
        }
        match parse_base_url(raw_url.trim()) {
            Ok(base_url) => upstreams.push(ConfiguredUpstream {
                edge_id: edge_id.into(),
                base_url,
                token: token.clone(),
            }),
            Err(_) => errors.push(format!("upstream {edge_id} has an invalid URL")),
        }
        if upstreams.len() >= MAX_UPSTREAMS {
            break;
        }
    }
    (upstreams, errors)
}

fn parse_base_url(raw: &str) -> Result<Url, ()> {
    let url = Url::parse(raw).map_err(|_| ())?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(());
    }
    let lower = raw.to_ascii_lowercase();
    if lower.contains("%2e")
        || lower.contains("%2f")
        || lower.contains("%5c")
        || raw.contains('\\')
        || raw.split('/').any(|segment| segment == "..")
    {
        return Err(());
    }
    if url
        .path_segments()
        .is_some_and(|mut segments| segments.any(|segment| segment == ".."))
    {
        return Err(());
    }
    Ok(url)
}

fn endpoint(base: &Url, suffix: &str) -> Result<Url, ()> {
    let mut endpoint = base.clone();
    let path = format!(
        "{}/{}",
        base.path().trim_end_matches('/'),
        suffix.trim_start_matches('/')
    );
    endpoint.set_path(&path);
    endpoint.set_query(None);
    endpoint.set_fragment(None);
    Ok(endpoint)
}

fn redacted_address(url: &Url) -> String {
    let _ = url;
    "redacted-configured-upstream".into()
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{routing::get, Json, Router};
    use openfdd_contracts::{ConnectorScope, ReadTarget, READ_PROXY_CONTRACT_V1};
    use std::net::SocketAddr;
    use tokio::net::TcpListener;

    fn central_fixture() -> ConnectorHelloResponse {
        ConnectorHelloResponse {
            schema: CAPABILITIES_CONTRACT_V1.into(),
            version: ServiceVersion {
                service: "central".into(),
                build: "test".into(),
                contract: CAPABILITIES_CONTRACT_V1.into(),
            },
            compiled_protocols: vec![ConnectorProtocol::Mqtt],
            connectors: Vec::new(),
            recipe: RecipeObservation {
                declared: None,
                observed_services: vec!["central".into()],
                reconciliation: "not_declared".into(),
            },
            observed_at: Utc::now(),
        }
    }

    #[test]
    fn upstream_url_validation_rejects_credentials_redirect_targets_and_escapes() {
        assert!(parse_base_url("https://user:secret@example.test").is_err());
        assert!(parse_base_url("https://example.test/a/../b").is_err());
        assert!(parse_base_url("https://example.test/%2e%2e/secret").is_err());
        assert!(parse_base_url("ftp://example.test").is_err());
        let parsed = parse_base_url("https://example.test/fieldbus/").unwrap();
        assert_eq!(redacted_address(&parsed), "redacted-configured-upstream");
    }

    #[tokio::test]
    async fn cached_hello_is_reused_without_second_probe() {
        let app = Router::new().route(
            "/api/connector/hello",
            get(|| async { Json(central_fixture()) }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr: SocketAddr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}")).unwrap(),
            token: Some("test-token".into()),
        }]);
        let first = aggregator.snapshot(central_fixture()).await;
        let second = aggregator.snapshot(central_fixture()).await;
        assert_eq!(first.upstreams[0].state, CapabilityState::Ready);
        assert_eq!(second.upstreams[0].state, CapabilityState::Ready);
        assert_eq!(second.upstreams[0].address, "redacted-configured-upstream");
    }

    #[tokio::test]
    async fn malformed_hello_is_incompatible_and_does_not_leak_url_or_token() {
        let app = Router::new().route("/api/connector/hello", get(|| async { "not-json" }));
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr: SocketAddr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}/fieldbus/")).unwrap(),
            token: Some("do-not-return".into()),
        }]);
        let report = aggregator.snapshot(central_fixture()).await;
        assert_eq!(report.upstreams[0].state, CapabilityState::Incompatible);
        assert!(!serde_json::to_string(&report)
            .unwrap()
            .contains("do-not-return"));
        assert_eq!(report.upstreams[0].address, "redacted-configured-upstream");
    }

    #[test]
    fn proxy_request_shape_is_read_only_and_scoped() {
        let request = ConnectorReadRequest {
            schema: READ_PROXY_CONTRACT_V1.into(),
            request_id: uuid::Uuid::nil(),
            scope: ConnectorScope {
                tenant_id: Some("tenant".into()),
                building_id: "building".into(),
                edge_id: "edge".into(),
            },
            target: ReadTarget::BacnetPriorityArray {
                device_instance: 7,
                object_type: "analog-value".into(),
                object_instance: 1,
            },
        };
        request.validate().unwrap();
        let value = serde_json::to_value(request).unwrap();
        assert!(value.get("url").is_none());
        assert!(value.get("host").is_none());
    }
}
