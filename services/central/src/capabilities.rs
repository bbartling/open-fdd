//! Central connector capability aggregation and the scoped read-only proxy.
//!
//! Capability refresh is explicit: `/api/health` never probes an OT edge.
//! Upstreams come only from server configuration, use the configured bearer,
//! reject redirects, and are bounded by timeout, body size, concurrency,
//! caching, and retry backoff.  User supplied URLs are never accepted.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::{Duration, Instant};

use axum::http::StatusCode;
use chrono::Utc;
use futures_util::StreamExt;
use openfdd_contracts::{
    CapabilitiesAggregateResponse, CapabilityState, ConnectorAction, ConnectorCapability,
    ConnectorHelloResponse, ConnectorInventoryRequest, ConnectorInventoryResponse,
    ConnectorProtocol, ConnectorReadRequest, ConnectorReadResponse, ConnectorReadResult,
    DeliveryStatus, PriorityHistoryRequest, PriorityHistoryResponse, PriorityHistoryTriggerRequest,
    PriorityHistoryTriggerResponse, ReadValueState, RecipeObservation, ServiceVersion,
    UpstreamCapability, CAPABILITIES_AGGREGATE_CONTRACT_V1, CAPABILITIES_CONTRACT_V1,
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
pub(crate) struct ConfiguredUpstream {
    /// Scope is part of the server-side configuration. It is never accepted
    /// from the browser or copied from an untrusted upstream response.
    pub(crate) tenant_id: String,
    pub(crate) building_id: String,
    pub(crate) edge_id: String,
    pub(crate) base_url: Url,
    pub(crate) token: Option<String>,
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
    config_error: Option<String>,
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
        let config_error = (!config_errors.is_empty())
            .then_some("one or more configured fieldbus upstreams are invalid".to_string());
        Arc::new(Self {
            client,
            upstreams,
            config_error: config_error.clone(),
            cache: Mutex::new(CacheState {
                report: config_error.map(|error| empty_report(Some(error))),
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
    pub(crate) fn for_tests(upstreams: Vec<ConfiguredUpstream>) -> Arc<Self> {
        Arc::new(Self {
            client: Client::builder()
                .redirect(Policy::none())
                .connect_timeout(Duration::from_millis(250))
                .timeout(Duration::from_millis(500))
                .build()
                .ok(),
            upstreams,
            config_error: None,
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

    /// Return only upstreams whose trusted configured scope belongs to the
    /// authenticated tenant/building context. The caller still applies its
    /// edge-shadow consistency check before returning a public report.
    pub fn authorized_edge_ids(&self, ctx: &crate::tenant::TenantContext) -> HashSet<String> {
        self.upstreams
            .iter()
            .filter(|upstream| {
                ctx.allow_building(&upstream.building_id)
                    && (ctx.hub_admin
                        || ctx.tenant_id.as_deref() == Some(upstream.tenant_id.as_str()))
            })
            .map(|upstream| upstream.edge_id.clone())
            .collect()
    }

    pub fn configured_scope(&self, edge_id: &str) -> Option<(&str, &str)> {
        self.upstreams
            .iter()
            .find(|upstream| upstream.edge_id == edge_id)
            .map(|upstream| (upstream.tenant_id.as_str(), upstream.building_id.as_str()))
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
        let mut report = aggregate_report(central, upstreams);
        report.diagnostic = self.config_error.clone();
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
            Ok(hello) => match sanitize_hello(hello) {
                Ok(hello) => hello,
                Err(()) => return failed_upstream(upstream, previous, ProbeFailure::Incompatible),
            },
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
        if upstream.tenant_id != request.scope.tenant_id
            || upstream.building_id != request.scope.building_id
        {
            return Err(ProxyError::BadRequest);
        }
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
        let result =
            sanitize_public_read_response(result, request).map_err(|_| ProxyError::Incompatible)?;
        if !result.ok {
            return Err(ProxyError::Rejected);
        }
        Ok(result)
    }

    /// Forward one explicitly requested inventory page through a configured
    /// edge. Inventory is a trusted configuration projection; the central
    /// service never supplies a URL or asks the edge to discover OT devices.
    pub async fn proxy_inventory(
        &self,
        edge_id: &str,
        request: &ConnectorInventoryRequest,
    ) -> Result<ConnectorInventoryResponse, ProxyError> {
        request.validate().map_err(|_| ProxyError::BadRequest)?;
        let upstream = self
            .upstreams
            .iter()
            .find(|upstream| upstream.edge_id == edge_id)
            .ok_or(ProxyError::NotConfigured)?;
        if upstream.tenant_id != request.scope.tenant_id
            || upstream.building_id != request.scope.building_id
        {
            return Err(ProxyError::BadRequest);
        }
        if upstream.token.is_none() && !central_bool("OPENFDD_FIELDBUS_UPSTREAM_ALLOW_ANONYMOUS") {
            return Err(ProxyError::AuthFailure);
        }
        let client = self.client.as_ref().ok_or(ProxyError::Incompatible)?;
        let _probe_permit = timeout(Duration::from_secs(2), self.probe_gate.acquire())
            .await
            .map_err(|_| ProxyError::Unreachable)?
            .map_err(|_| ProxyError::Unreachable)?;
        let endpoint = endpoint(&upstream.base_url, "api/connector/inventory")
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
        let result: ConnectorInventoryResponse =
            serde_json::from_slice(&body).map_err(|_| ProxyError::Incompatible)?;
        result
            .validate_for(request)
            .map_err(|_| ProxyError::Incompatible)?;
        Ok(result)
    }

    /// Forward one bounded, read-only priority history page through the
    /// configured edge. This is a history projection only; central never
    /// asks the edge to discover, write, release, or remediate an OT value.
    pub async fn proxy_priority_history(
        &self,
        edge_id: &str,
        request: &PriorityHistoryRequest,
    ) -> Result<PriorityHistoryResponse, ProxyError> {
        request.validate().map_err(|_| ProxyError::BadRequest)?;
        let upstream = self
            .upstreams
            .iter()
            .find(|upstream| upstream.edge_id == edge_id)
            .ok_or(ProxyError::NotConfigured)?;
        if upstream.tenant_id != request.scope.tenant_id
            || upstream.building_id != request.scope.building_id
        {
            return Err(ProxyError::BadRequest);
        }
        if upstream.token.is_none() && !central_bool("OPENFDD_FIELDBUS_UPSTREAM_ALLOW_ANONYMOUS") {
            return Err(ProxyError::AuthFailure);
        }
        let client = self.client.as_ref().ok_or(ProxyError::Incompatible)?;
        let _probe_permit = timeout(Duration::from_secs(2), self.probe_gate.acquire())
            .await
            .map_err(|_| ProxyError::Unreachable)?
            .map_err(|_| ProxyError::Unreachable)?;
        let endpoint = endpoint(&upstream.base_url, "api/connector/priority-history")
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
        let response: PriorityHistoryResponse =
            serde_json::from_slice(&body).map_err(|_| ProxyError::Incompatible)?;
        sanitize_public_priority_history(response, request).map_err(|_| ProxyError::Incompatible)
    }

    pub async fn proxy_priority_history_trigger(
        &self,
        edge_id: &str,
        request: &PriorityHistoryTriggerRequest,
    ) -> Result<PriorityHistoryTriggerResponse, ProxyError> {
        request.validate().map_err(|_| ProxyError::BadRequest)?;
        let upstream = self
            .upstreams
            .iter()
            .find(|upstream| upstream.edge_id == edge_id)
            .ok_or(ProxyError::NotConfigured)?;
        if upstream.tenant_id != request.scope.tenant_id
            || upstream.building_id != request.scope.building_id
        {
            return Err(ProxyError::BadRequest);
        }
        if upstream.token.is_none() && !central_bool("OPENFDD_FIELDBUS_UPSTREAM_ALLOW_ANONYMOUS") {
            return Err(ProxyError::AuthFailure);
        }
        let client = self.client.as_ref().ok_or(ProxyError::Incompatible)?;
        let _probe_permit = timeout(Duration::from_secs(2), self.probe_gate.acquire())
            .await
            .map_err(|_| ProxyError::Unreachable)?
            .map_err(|_| ProxyError::Unreachable)?;
        let endpoint = endpoint(&upstream.base_url, "api/connector/priority-history/trigger")
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
        let response: PriorityHistoryTriggerResponse =
            serde_json::from_slice(&body).map_err(|_| ProxyError::Incompatible)?;
        response
            .validate_for(request)
            .map_err(|_| ProxyError::Incompatible)?;
        Ok(response)
    }
}

/// Validate and reduce every connector read to the public DTO surface.  The
/// connector is allowed to keep detailed BACnet diagnostics internally, but
/// those details must not cross the central API boundary in a priority slot or
/// failed response.
fn sanitize_public_read_response(
    mut response: ConnectorReadResponse,
    request: &ConnectorReadRequest,
) -> Result<ConnectorReadResponse, ()> {
    // Validate target correlation and slot semantics before reducing any
    // diagnostics.  In particular, a contradictory NULL/value/error payload
    // is malformed and must not be laundered into a plausible slot by the
    // sanitizer below.
    response.validate_for(request).map_err(|_| ())?;
    if response.ok {
        match response.result.as_mut() {
            Some(ConnectorReadResult::Metadata { hello }) => {
                *hello = sanitize_hello(hello.clone())?;
            }
            Some(ConnectorReadResult::PriorityArray(array)) => {
                for slot in &mut array.slots {
                    if matches!(slot.state, ReadValueState::Error | ReadValueState::Unknown) {
                        // The structure was validated above. Replace only a
                        // valid diagnostic string; preserve the typed state
                        // and its already validated value/null semantics.
                        if slot.error.is_some() {
                            slot.error = Some("priority slot unavailable".into());
                        }
                    }
                }
            }
            Some(ConnectorReadResult::Point(_)) | None => {}
        }
    } else {
        // Do not forward connector free text, addresses, or BACnet exception
        // names.  The typed status remains useful while the public message is
        // stable and intentionally generic.
        response.result = None;
        response.capability_contract = None;
        response.error = Some(openfdd_contracts::ReadError {
            code: "upstream_rejected".into(),
            message: "connector read rejected".into(),
        });
    }
    response.validate_for(request).map_err(|_| ())?;
    Ok(response)
}

fn sanitize_public_priority_history(
    mut response: PriorityHistoryResponse,
    request: &PriorityHistoryRequest,
) -> Result<PriorityHistoryResponse, ()> {
    response.validate_for(request).map_err(|_| ())?;
    for record in &mut response.records {
        for slot in &mut record.snapshot.slots {
            if matches!(slot.state, ReadValueState::Error | ReadValueState::Unknown)
                && slot.error.is_some()
            {
                slot.error = Some("priority slot unavailable".into());
            }
        }
    }
    response.validate_for(request).map_err(|_| ())?;
    Ok(response)
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
    Rejected,
}

impl ProxyError {
    pub fn status(self) -> StatusCode {
        match self {
            Self::BadRequest => StatusCode::BAD_REQUEST,
            Self::NotConfigured => StatusCode::NOT_FOUND,
            Self::Unreachable => StatusCode::BAD_GATEWAY,
            Self::AuthFailure => StatusCode::BAD_GATEWAY,
            Self::Incompatible => StatusCode::BAD_GATEWAY,
            Self::Rejected => StatusCode::BAD_GATEWAY,
        }
    }

    pub fn message(self) -> &'static str {
        match self {
            Self::BadRequest => "invalid read proxy request",
            Self::NotConfigured => "edge connector is not configured",
            Self::Unreachable => "edge connector is unreachable",
            Self::AuthFailure => "edge connector authentication failed",
            Self::Incompatible => "edge connector read contract is incompatible",
            Self::Rejected => "edge connector rejected the read",
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
    reconcile_aggregate_recipe(&mut report);
    report.generated_at = Utc::now();
    report
}

fn with_central(
    mut report: CapabilitiesAggregateResponse,
    central: ConnectorHelloResponse,
) -> CapabilitiesAggregateResponse {
    report.central = central;
    reconcile_aggregate_recipe(&mut report);
    report.generated_at = Utc::now();
    report
}

fn aggregate_report(
    central: ConnectorHelloResponse,
    upstreams: Vec<UpstreamCapability>,
) -> CapabilitiesAggregateResponse {
    let declared = central.recipe.declared.clone();
    let mut report = CapabilitiesAggregateResponse {
        schema: CAPABILITIES_AGGREGATE_CONTRACT_V1.into(),
        version: ServiceVersion {
            service: "openfdd-central".into(),
            build: central.version.build.clone(),
            contract: CAPABILITIES_AGGREGATE_CONTRACT_V1.into(),
        },
        central,
        upstreams,
        recipe: RecipeObservation {
            declared,
            configured_services: Vec::new(),
            observed_services: Vec::new(),
            unobserved_services: Vec::new(),
            reconciliation: "declared_missing".into(),
        },
        diagnostic: None,
        generated_at: Utc::now(),
        observed_at: Utc::now(),
    };
    reconcile_aggregate_recipe(&mut report);
    report
}

fn reconcile_aggregate_recipe(report: &mut CapabilitiesAggregateResponse) {
    let mut configured_services = report.central.recipe.configured_services.clone();
    if !report.upstreams.is_empty() {
        // Presence in this server-side allowlisted upstream list is
        // configuration evidence. It is intentionally not copied into
        // observed_services below unless a validated ready hello arrived.
        configured_services.push("fieldbus".into());
    }
    configured_services.sort();
    configured_services.dedup();

    let mut observed_services = report.central.recipe.observed_services.clone();
    if report.upstreams.iter().any(|upstream| {
        upstream.state == CapabilityState::Ready
            && upstream.hello.as_ref().is_some_and(|hello| {
                hello
                    .recipe
                    .observed_services
                    .iter()
                    .any(|service| service == "fieldbus")
            })
    }) {
        observed_services.push("fieldbus".into());
    }
    observed_services.sort();
    observed_services.dedup();
    let declared = report.central.recipe.declared.clone();
    let reconciliation = RecipeObservation::reconcile(
        declared.as_deref(),
        &configured_services,
        &observed_services,
    );
    let unobserved_services =
        RecipeObservation::missing_services(declared.as_deref(), &observed_services);
    report.recipe = RecipeObservation {
        declared,
        configured_services,
        observed_services,
        unobserved_services,
        reconciliation: reconciliation.into(),
    };
}

/// Restrict an aggregate to the edge ids authorized by the authenticated
/// request. The cache may contain a wider server-side snapshot, but it is
/// never serialized across this boundary.
pub fn restrict_to_edges(
    mut report: CapabilitiesAggregateResponse,
    allowed_edges: &HashSet<String>,
) -> CapabilitiesAggregateResponse {
    report
        .upstreams
        .retain(|upstream| allowed_edges.contains(&upstream.edge_id));
    reconcile_aggregate_recipe(&mut report);
    report.generated_at = Utc::now();
    report
}

fn sanitize_hello(mut hello: ConnectorHelloResponse) -> Result<ConnectorHelloResponse, ()> {
    if hello.schema != CAPABILITIES_CONTRACT_V1
        || hello.version.contract != CAPABILITIES_CONTRACT_V1
        || hello.version.service != "openfdd-fieldbus"
    {
        return Err(());
    }
    // Free text from a connector is not a public diagnostic channel. Keep
    // only the typed protocol/action/state fields at this boundary.
    for connector in &mut hello.connectors {
        connector.detail = None;
    }
    hello.recipe.declared = hello
        .recipe
        .declared
        .filter(|value| matches!(value.as_str(), "edge" | "standalone" | "central" | "csv"));
    hello
        .recipe
        .configured_services
        .retain(|service| matches!(service.as_str(), "fieldbus" | "mqtt" | "central"));
    hello
        .recipe
        .observed_services
        .retain(|service| matches!(service.as_str(), "fieldbus" | "mqtt" | "central"));
    hello
        .recipe
        .unobserved_services
        .retain(|service| matches!(service.as_str(), "fieldbus" | "mqtt" | "central" | "web"));
    hello.recipe.reconciliation = RecipeObservation::reconcile(
        hello.recipe.declared.as_deref(),
        &hello.recipe.configured_services,
        &hello.recipe.observed_services,
    )
    .into();
    hello.recipe.unobserved_services = RecipeObservation::missing_services(
        hello.recipe.declared.as_deref(),
        &hello.recipe.observed_services,
    );
    hello.validate().map_err(|_| ())?;
    Ok(hello)
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
            configured_services: vec!["central".into()],
            observed_services: vec!["central".into()],
            unobserved_services: vec![],
            reconciliation: "not_declared".into(),
        },
        observed_at: Utc::now(),
    };
    let report = aggregate_report(central.clone(), Vec::new());
    let mut report = report;
    report.diagnostic = error;
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

fn declared_recipe() -> Option<String> {
    ["OPENFDD_BUILD_RECIPE", "OPENFDD_RECIPE"]
        .into_iter()
        .find_map(|name| {
            std::env::var(name)
                .ok()
                .map(|value| value.trim().to_string())
                .filter(|value| matches!(value.as_str(), "edge" | "standalone" | "central" | "csv"))
        })
}

pub fn central_hello(state: &AppState) -> ConnectorHelloResponse {
    const DURABLE_FRESHNESS: Duration = Duration::from_secs(5 * 60);
    const SOURCE_FRESHNESS: Duration = Duration::from_secs(5 * 60);
    let mqtt_enabled = central_bool("OPENFDD_MQTT_ENABLED");
    let mqtt_configured = std::env::var("OPENFDD_MQTT_HOST")
        .ok()
        .is_some_and(|host| !host.trim().is_empty());
    let monitor = state.mqtt_monitor_snapshot();
    let historian = crate::durable_storage::historian_root_present();
    let last_durable_at = *state
        .last_durable_at
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let last_ingest_at = *state
        .last_ingest_at
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let mqtt_state = if !mqtt_enabled {
        DeliveryStatus::Disabled
    } else if !mqtt_configured {
        DeliveryStatus::NotConfigured
    } else if monitor.connected {
        DeliveryStatus::Ready
    } else if monitor.errors > 0 {
        DeliveryStatus::Unreachable
    } else {
        DeliveryStatus::Checking
    };
    let durable_state = if !historian {
        DeliveryStatus::Incompatible
    } else if last_durable_at.as_ref().is_some_and(|observed| {
        Utc::now()
            .signed_duration_since(observed)
            .to_std()
            .is_ok_and(|age| age <= DURABLE_FRESHNESS)
    }) {
        DeliveryStatus::Ready
    } else if last_durable_at.is_some() {
        DeliveryStatus::Stale
    } else {
        DeliveryStatus::Unknown
    };
    let readiness = if !mqtt_enabled {
        CapabilityState::Disabled
    } else if !mqtt_configured {
        CapabilityState::NotConfigured
    } else if monitor.connected {
        CapabilityState::Ready
    } else {
        CapabilityState::Checking
    };
    let source_health = if last_ingest_at.as_ref().is_some_and(|observed| {
        Utc::now()
            .signed_duration_since(observed)
            .to_std()
            .is_ok_and(|age| age <= SOURCE_FRESHNESS)
    }) {
        CapabilityState::Ready
    } else if last_ingest_at.is_some() {
        CapabilityState::Stale
    } else {
        CapabilityState::Checking
    };
    let declared = declared_recipe();
    let configured_services = {
        let mut services = vec!["central".to_string()];
        if mqtt_configured {
            services.push("mqtt".into());
        }
        services
    };
    let observed_services = {
        let mut services = vec!["central".to_string()];
        if mqtt_state == DeliveryStatus::Ready {
            services.push("mqtt".into());
        }
        services
    };
    let reconciliation = RecipeObservation::reconcile(
        declared.as_deref(),
        &configured_services,
        &observed_services,
    );
    let unobserved_services =
        RecipeObservation::missing_services(declared.as_deref(), &observed_services);
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
            configured: mqtt_configured,
            enabled: mqtt_enabled,
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
            configured_services,
            observed_services,
            unobserved_services,
            reconciliation: reconciliation.into(),
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
    let mut upstreams: Vec<ConfiguredUpstream> = Vec::new();
    let mut errors = Vec::new();
    for (index, item) in raw
        .unwrap_or_default()
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .enumerate()
    {
        let Some((scope_key, raw_url)) = item.split_once('=') else {
            errors.push(format!("upstream {index} is malformed"));
            continue;
        };
        let Ok((tenant_id, building_id, edge_id)) = configured_scope(scope_key.trim()) else {
            errors.push(format!(
                "upstream {index} has an invalid tenant/building/edge scope"
            ));
            continue;
        };
        if upstreams.iter().any(|upstream| upstream.edge_id == edge_id) {
            errors.push(format!("upstream {edge_id} is configured more than once"));
            continue;
        }
        match parse_base_url(raw_url.trim()) {
            Ok(base_url) => upstreams.push(ConfiguredUpstream {
                tenant_id,
                building_id,
                edge_id,
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

/// Parse the trusted scope prefix used by `OPENFDD_FIELDBUS_UPSTREAMS`.
/// Entries use `tenant|building|edge=https://...`. A one-part legacy entry is
/// accepted only when the process has explicit `OPENFDD_TENANT_ID` and
/// `OPENFDD_BUILDING_ID` bindings; otherwise it is rejected fail-closed.
fn configured_scope(raw: &str) -> Result<(String, String, String), ()> {
    let parts: Vec<_> = raw.split('|').map(str::trim).collect();
    let (tenant_id, building_id, edge_id) = match parts.as_slice() {
        [tenant_id, building_id, edge_id] => (
            (*tenant_id).to_string(),
            (*building_id).to_string(),
            (*edge_id).to_string(),
        ),
        [edge_id] => (
            std::env::var("OPENFDD_TENANT_ID").map_err(|_| ())?,
            std::env::var("OPENFDD_BUILDING_ID").map_err(|_| ())?,
            (*edge_id).to_string(),
        ),
        _ => return Err(()),
    };
    for value in [&tenant_id, &building_id, &edge_id] {
        if value.trim().is_empty()
            || value.contains('/')
            || value.contains('\\')
            || value.contains("..")
        {
            return Err(());
        }
    }
    Ok((tenant_id, building_id, edge_id))
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
    use axum::{
        body::Body,
        response::{Redirect, Response},
        routing::{get, post},
        Json, Router,
    };
    use bytes::Bytes;
    use openfdd_contracts::{
        ConnectorInventoryRequest, ConnectorInventoryResponse, ConnectorReadRequest,
        ConnectorReadResponse, ConnectorReadResult, ConnectorScope, InventoryAvailability,
        InventoryCommandability, InventoryProvenance, InventoryRecord, PriorityHistoryRecord,
        PriorityHistoryRequest, PriorityHistoryResponse, PriorityScanStatus, PriorityScanTarget,
        ReadPriorityArrayResult, ReadPrioritySlot, ReadTarget, ReadValueState,
        CONNECTOR_INVENTORY_CONTRACT_V1, PRIORITY_SCAN_CONTRACT_V1, READ_PROXY_CONTRACT_V1,
    };
    use std::convert::Infallible;
    use std::net::SocketAddr;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc as StdArc;
    use tokio::net::TcpListener;

    fn central_fixture() -> ConnectorHelloResponse {
        ConnectorHelloResponse {
            schema: CAPABILITIES_CONTRACT_V1.into(),
            version: ServiceVersion {
                service: "openfdd-fieldbus".into(),
                build: "test".into(),
                contract: CAPABILITIES_CONTRACT_V1.into(),
            },
            compiled_protocols: vec![ConnectorProtocol::Mqtt],
            connectors: Vec::new(),
            recipe: RecipeObservation {
                declared: None,
                configured_services: vec!["central".into()],
                observed_services: vec!["central".into()],
                unobserved_services: vec![],
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

    #[test]
    fn configured_upstream_scope_requires_tenant_building_and_edge_binding() {
        assert_eq!(
            configured_scope("tenant-a|building-a|edge-a").unwrap(),
            ("tenant-a".into(), "building-a".into(), "edge-a".into())
        );
        assert!(configured_scope("tenant-a|building-a").is_err());
        assert!(configured_scope("tenant-a|building-a|../edge").is_err());
    }

    #[test]
    fn recipe_matching_uses_the_documented_compose_matrix() {
        let central = |observed: &[&str]| {
            RecipeObservation::reconcile(
                Some("central"),
                &["central".into(), "mqtt".into(), "web".into()],
                &observed
                    .iter()
                    .map(|value| (*value).to_string())
                    .collect::<Vec<_>>(),
            )
        };
        assert_eq!(central(&["central"]), "declared_missing");
        assert_eq!(central(&["central", "mqtt"]), "declared_missing");
        assert_eq!(central(&["central", "mqtt", "web"]), "matched");

        let standalone_configured = vec![
            "central".into(),
            "fieldbus".into(),
            "mqtt".into(),
            "web".into(),
        ];
        let only_fieldbus = vec!["fieldbus".into()];
        assert_eq!(
            RecipeObservation::reconcile(
                Some("standalone"),
                &standalone_configured,
                &only_fieldbus,
            ),
            "declared_missing"
        );
        assert_eq!(
            RecipeObservation::reconcile(
                Some("standalone"),
                &standalone_configured,
                &[
                    "central".into(),
                    "fieldbus".into(),
                    "mqtt".into(),
                    "web".into(),
                ],
            ),
            "matched"
        );

        assert_eq!(
            RecipeObservation::reconcile(
                Some("csv"),
                &["central".into(), "web".into()],
                &["central".into(), "web".into()],
            ),
            "matched"
        );
        assert_eq!(
            RecipeObservation::reconcile(Some("edge"), &["fieldbus".into()], &["fieldbus".into()],),
            "matched"
        );
        // Edge compose uses an external broker; an optional local MQTT
        // connector must not make the documented fieldbus recipe incomplete.
        assert_eq!(
            RecipeObservation::reconcile(
                Some("edge"),
                &["fieldbus".into(), "mqtt".into()],
                &["fieldbus".into()],
            ),
            "matched"
        );
    }

    #[test]
    fn failed_configured_upstream_is_not_recipe_observation() {
        let mut central = central_fixture();
        central.recipe.declared = Some("standalone".into());
        central.recipe.configured_services = vec![
            "central".into(),
            "mqtt".into(),
            "fieldbus".into(),
            "web".into(),
        ];
        central.recipe.observed_services = vec!["central".into(), "mqtt".into()];
        let report = aggregate_report(
            central,
            vec![UpstreamCapability {
                edge_id: "edge-a".into(),
                address: "redacted-configured-upstream".into(),
                state: CapabilityState::Unreachable,
                hello: None,
                error: Some("upstream unavailable".into()),
                last_success_at: None,
            }],
        );
        assert_eq!(
            report.recipe.configured_services,
            ["central", "fieldbus", "mqtt", "web"]
        );
        assert_eq!(report.recipe.observed_services, ["central", "mqtt"]);
        assert_eq!(report.recipe.unobserved_services, ["fieldbus", "web"]);
        assert_eq!(report.recipe.reconciliation, "declared_missing");
    }

    #[tokio::test]
    async fn cached_hello_is_reused_without_second_probe() {
        let calls = StdArc::new(AtomicUsize::new(0));
        let calls_for_handler = StdArc::clone(&calls);
        let app = Router::new().route(
            "/api/connector/hello",
            get(move || {
                calls_for_handler.fetch_add(1, Ordering::Relaxed);
                async { Json(central_fixture()) }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr: SocketAddr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}")).unwrap(),
            token: Some("test-token".into()),
        }]);
        let first = aggregator.snapshot(central_fixture()).await;
        let second = aggregator.snapshot(central_fixture()).await;
        assert_eq!(first.upstreams[0].state, CapabilityState::Ready);
        assert_eq!(second.upstreams[0].state, CapabilityState::Ready);
        assert_eq!(second.upstreams[0].address, "redacted-configured-upstream");
        assert_eq!(calls.load(Ordering::Relaxed), 1);
        assert_eq!(
            first.upstreams[0].hello.as_ref().unwrap().observed_at,
            second.upstreams[0].hello.as_ref().unwrap().observed_at
        );
    }

    #[test]
    fn public_hello_sanitizer_removes_free_text_and_recomputes_recipe() {
        let mut hello = central_fixture();
        hello.recipe.declared = Some("edge".into());
        hello.recipe.configured_services = vec!["fieldbus".into(), "mqtt".into()];
        hello.recipe.observed_services = vec!["fieldbus".into(), "https://internal".into()];
        hello.recipe.reconciliation = "https://internal/secret".into();
        hello.connectors.push(ConnectorCapability {
            protocol: ConnectorProtocol::Bacnet,
            compiled: true,
            configured: true,
            enabled: true,
            readiness: CapabilityState::Ready,
            source_health: CapabilityState::Unknown,
            mqtt_connection: DeliveryStatus::Unknown,
            durable_delivery: DeliveryStatus::Unknown,
            supported_actions: vec![ConnectorAction::MetadataRead],
            detail: Some("https://user:secret@internal".into()),
        });
        let sanitized = sanitize_hello(hello).unwrap();
        assert!(sanitized.connectors[0].detail.is_none());
        assert_eq!(sanitized.recipe.reconciliation, "matched");
        assert!(!serde_json::to_string(&sanitized)
            .unwrap()
            .contains("internal"));
    }

    #[test]
    fn public_read_sanitizer_reduces_priority_errors_to_stable_codes() {
        let request = ConnectorReadRequest {
            schema: READ_PROXY_CONTRACT_V1.into(),
            request_id: uuid::Uuid::nil(),
            scope: ConnectorScope {
                tenant_id: "tenant-a".into(),
                building_id: "building-a".into(),
                edge_id: "edge-a".into(),
            },
            target: ReadTarget::BacnetPriorityArray {
                device_instance: 7,
                object_type: "analog-output".into(),
                object_instance: 4,
            },
        };
        let slots: Vec<ReadPrioritySlot> = (1..=16)
            .map(|priority_level| ReadPrioritySlot {
                priority_level,
                state: if priority_level == 3 {
                    ReadValueState::Error
                } else {
                    ReadValueState::Null
                },
                value_type: if priority_level == 3 {
                    "error".into()
                } else {
                    "null".into()
                },
                value: None,
                error: (priority_level == 3).then_some("tcp://10.0.0.7:47808 secret".into()),
            })
            .collect();
        let response_for = |slots| {
            ConnectorReadResponse::success(
                &request,
                ConnectorReadResult::PriorityArray(ReadPriorityArrayResult {
                    device_instance: 7,
                    object_type: "analog-output".into(),
                    object_instance: 4,
                    slots,
                    state: "supported".into(),
                    observed_at: Utc::now(),
                }),
            )
        };
        let response = response_for(slots.clone());
        let sanitized = sanitize_public_read_response(response, &request).unwrap();
        let encoded = serde_json::to_string(&sanitized).unwrap();
        assert!(!encoded.contains("10.0.0.7"));
        assert_eq!(
            sanitized.result.as_ref().and_then(|result| match result {
                ConnectorReadResult::PriorityArray(array) => array.slots[2].error.as_deref(),
                _ => None,
            }),
            Some("priority slot unavailable")
        );

        for (state, value, error) in [
            (ReadValueState::Null, Some(serde_json::json!(1.0)), None),
            (ReadValueState::Value, None, Some("internal detail".into())),
            (
                ReadValueState::Error,
                Some(serde_json::json!(1.0)),
                Some("internal detail".into()),
            ),
            (
                ReadValueState::Unknown,
                Some(serde_json::json!(1.0)),
                Some("internal detail".into()),
            ),
        ] {
            let mut contradictory = slots.clone();
            contradictory[0].state = state;
            contradictory[0].value = value;
            contradictory[0].error = error;
            assert!(sanitize_public_read_response(response_for(contradictory), &request).is_err());
        }
    }

    #[test]
    fn public_priority_history_sanitizer_removes_edge_diagnostics() {
        let scope = ConnectorScope {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
        };
        let request = PriorityHistoryRequest {
            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
            request_id: uuid::Uuid::nil(),
            scope: scope.clone(),
            page_size: 10,
            cursor: None,
            target: None,
        };
        let target = PriorityScanTarget {
            device_instance: 7,
            object_type: "analog-output".into(),
            object_instance: 4,
        };
        let snapshot = ReadPriorityArrayResult {
            device_instance: target.device_instance,
            object_type: target.object_type.clone(),
            object_instance: target.object_instance,
            slots: (1..=16)
                .map(|priority_level| ReadPrioritySlot {
                    priority_level,
                    state: if priority_level == 3 {
                        ReadValueState::Error
                    } else {
                        ReadValueState::Null
                    },
                    value_type: if priority_level == 3 {
                        "error".into()
                    } else {
                        "null".into()
                    },
                    value: None,
                    error: (priority_level == 3)
                        .then_some("BACnet tcp://10.0.0.7:47808 secret".into()),
                })
                .collect(),
            state: "supported".into(),
            observed_at: Utc::now(),
        };
        let response = PriorityHistoryResponse {
            schema: PRIORITY_SCAN_CONTRACT_V1.into(),
            request_id: request.request_id,
            scope: scope.clone(),
            revision: "history-0000000000000001".into(),
            captured_at: Utc::now(),
            records: vec![PriorityHistoryRecord {
                sequence: 1,
                target,
                snapshot,
                label: None,
                source: "scheduled_scan".into(),
            }],
            next_cursor: None,
            scanner: PriorityScanStatus {
                schema: PRIORITY_SCAN_CONTRACT_V1.into(),
                scope,
                enabled: false,
                interval_secs: 3_600,
                max_points_per_device: 100,
                catch_up: false,
                read_only: true,
                discovery_enabled: false,
                writes_enabled: false,
                last_started_at: None,
                last_completed_at: None,
                next_due_at: None,
                last_device_identity: None,
                last_error: None,
                records_retained: 1,
            },
        };
        let sanitized = sanitize_public_priority_history(response, &request).unwrap();
        let encoded = serde_json::to_string(&sanitized).unwrap();
        assert!(!encoded.contains("10.0.0.7"));
        assert_eq!(
            sanitized.records[0].snapshot.slots[2].error.as_deref(),
            Some("priority slot unavailable")
        );

        let mut foreign_scanner = sanitized.clone();
        foreign_scanner.scanner.scope.edge_id = "edge-foreign".into();
        assert!(sanitize_public_priority_history(foreign_scanner, &request).is_err());
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
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
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

    #[tokio::test]
    async fn redirect_is_not_followed_and_is_incompatible() {
        let redirected_calls = StdArc::new(AtomicUsize::new(0));
        let redirected_calls_for_handler = StdArc::clone(&redirected_calls);
        let app = Router::new()
            .route(
                "/api/connector/hello",
                get(|| async { Redirect::temporary("/redirected") }),
            )
            .route(
                "/redirected",
                get(move || {
                    redirected_calls_for_handler.fetch_add(1, Ordering::Relaxed);
                    async { Json(central_fixture()) }
                }),
            );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}")).unwrap(),
            token: Some("test-token".into()),
        }]);
        let report = aggregator.snapshot(central_fixture()).await;
        assert_eq!(report.upstreams[0].state, CapabilityState::Incompatible);
        assert_eq!(redirected_calls.load(Ordering::Relaxed), 0);
    }

    #[tokio::test]
    async fn oversized_hello_body_is_rejected_before_publication() {
        let body = "x".repeat(MAX_BODY_BYTES + 1);
        let app = Router::new().route(
            "/api/connector/hello",
            get(move || {
                let body = body.clone();
                async move { body }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}")).unwrap(),
            token: Some("test-token".into()),
        }]);
        let report = aggregator.snapshot(central_fixture()).await;
        assert_eq!(report.upstreams[0].state, CapabilityState::Incompatible);
    }

    #[tokio::test]
    async fn stalled_hello_is_bounded_and_enters_failure_backoff() {
        let calls = StdArc::new(AtomicUsize::new(0));
        let calls_for_handler = StdArc::clone(&calls);
        let app = Router::new().route(
            "/api/connector/hello",
            get(move || {
                calls_for_handler.fetch_add(1, Ordering::Relaxed);
                async {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    Json(central_fixture())
                }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}")).unwrap(),
            token: Some("test-token".into()),
        }]);
        let first = aggregator.snapshot(central_fixture()).await;
        assert_eq!(first.upstreams[0].state, CapabilityState::Unreachable);
        tokio::time::sleep(Duration::from_millis(30)).await;
        let second = aggregator.snapshot(central_fixture()).await;
        assert_eq!(second.upstreams[0].state, CapabilityState::Unreachable);
        assert_eq!(calls.load(Ordering::Relaxed), 1);
    }

    #[tokio::test]
    async fn stalled_hello_body_after_headers_is_bounded() {
        let app = Router::new().route(
            "/api/connector/hello",
            get(|| async {
                let stream = futures_util::stream::once(async {
                    Ok::<Bytes, Infallible>(Bytes::from_static(b"{\"schema\":\""))
                })
                .chain(futures_util::stream::pending::<Result<Bytes, Infallible>>());
                Response::builder()
                    .status(StatusCode::OK)
                    .header("content-type", "application/json")
                    .body(Body::from_stream(stream))
                    .unwrap()
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}")).unwrap(),
            token: Some("test-token".into()),
        }]);
        let report = aggregator.snapshot(central_fixture()).await;
        assert_eq!(report.upstreams[0].state, CapabilityState::Incompatible);
    }

    #[test]
    fn proxy_request_shape_is_read_only_and_scoped() {
        let request = ConnectorReadRequest {
            schema: READ_PROXY_CONTRACT_V1.into(),
            request_id: uuid::Uuid::nil(),
            scope: ConnectorScope {
                tenant_id: "tenant".into(),
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

    #[tokio::test]
    async fn inventory_proxy_is_typed_correlated_and_scope_bound() {
        let calls = StdArc::new(AtomicUsize::new(0));
        let calls_for_handler = StdArc::clone(&calls);
        let app = Router::new().route(
            "/api/connector/inventory",
            post(move |Json(request): Json<ConnectorInventoryRequest>| {
                let call = calls_for_handler.fetch_add(1, Ordering::Relaxed);
                async move {
                    let request_id = if call == 0 {
                        request.request_id
                    } else {
                        uuid::Uuid::new_v4()
                    };
                    if call == 2 {
                        return Json(ConnectorInventoryResponse {
                            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
                            request_id: request.request_id,
                            scope: request.scope.clone(),
                            protocols: Vec::new(),
                            revision: "config-test".into(),
                            captured_at: Utc::now(),
                            provenance: InventoryProvenance::TrustedConfiguration,
                            records: Vec::new(),
                            next_cursor: Some(
                                request.cursor_for_revision("config-test", 1).unwrap(),
                            ),
                        });
                    }
                    if call == 3 {
                        return Json(ConnectorInventoryResponse {
                            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
                            request_id: request.request_id,
                            scope: request.scope,
                            protocols: vec![ConnectorProtocol::Bacnet],
                            revision: "config-test".into(),
                            captured_at: Utc::now(),
                            provenance: InventoryProvenance::TrustedConfiguration,
                            records: vec![InventoryRecord::Device {
                                device_id: "192.0.2.10:47808".into(),
                                protocol: ConnectorProtocol::Bacnet,
                                display_name: "Configured BACnet device".into(),
                                availability: InventoryAvailability::Configured,
                                commandability: InventoryCommandability::Unknown,
                                actions: vec![ConnectorAction::MetadataRead],
                            }],
                            next_cursor: None,
                        });
                    }
                    Json(ConnectorInventoryResponse {
                        schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
                        request_id,
                        scope: request.scope,
                        protocols: vec![ConnectorProtocol::Bacnet],
                        revision: "config-test".into(),
                        captured_at: Utc::now(),
                        provenance: InventoryProvenance::TrustedConfiguration,
                        records: vec![InventoryRecord::Device {
                            device_id: "bacnet:device:7".into(),
                            protocol: ConnectorProtocol::Bacnet,
                            display_name: "Configured BACnet device".into(),
                            availability: InventoryAvailability::Configured,
                            commandability: InventoryCommandability::Unknown,
                            actions: vec![ConnectorAction::MetadataRead],
                        }],
                        next_cursor: None,
                    })
                }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        let aggregator = CapabilitiesAggregator::for_tests(vec![ConfiguredUpstream {
            tenant_id: "tenant-a".into(),
            building_id: "building-a".into(),
            edge_id: "edge-a".into(),
            base_url: Url::parse(&format!("http://{addr}")).unwrap(),
            token: Some("test-token".into()),
        }]);
        let request = ConnectorInventoryRequest {
            schema: CONNECTOR_INVENTORY_CONTRACT_V1.into(),
            request_id: uuid::Uuid::nil(),
            scope: ConnectorScope {
                tenant_id: "tenant-a".into(),
                building_id: "building-a".into(),
                edge_id: "edge-a".into(),
            },
            protocols: vec![ConnectorProtocol::Bacnet],
            page_size: 10,
            cursor: None,
        };
        let response = aggregator
            .proxy_inventory("edge-a", &request)
            .await
            .unwrap();
        response.validate_for(&request).unwrap();
        assert_eq!(response.records.len(), 1);
        assert_eq!(calls.load(Ordering::Relaxed), 1);

        let mismatch = aggregator.proxy_inventory("edge-a", &request).await;
        assert_eq!(mismatch, Err(ProxyError::Incompatible));
        let mut foreign = request.clone();
        foreign.scope.tenant_id = "tenant-b".into();
        assert_eq!(
            aggregator.proxy_inventory("edge-a", &foreign).await,
            Err(ProxyError::BadRequest)
        );
        assert_eq!(calls.load(Ordering::Relaxed), 2);
        assert_eq!(
            aggregator.proxy_inventory("edge-a", &request).await,
            Err(ProxyError::Incompatible)
        );
        assert_eq!(calls.load(Ordering::Relaxed), 3);
        assert_eq!(
            aggregator.proxy_inventory("edge-a", &request).await,
            Err(ProxyError::Incompatible)
        );
        assert_eq!(calls.load(Ordering::Relaxed), 4);
    }
}
