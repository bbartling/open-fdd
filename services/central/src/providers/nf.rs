//! Normal Framework portal HTTPS driver. The LAN gRPC history transport
//! (`nf_transport.rs`) reuses its token, point-id and timestamp rules.
//!
//! History reads are `GET /api/v1/point/data`. `POST` on that path is a write
//! and is never used here. OAuth token calls are `POST /api/v1/auth/token`.

use std::collections::{HashMap, HashSet};
use std::fmt;
use std::hash::{Hash, Hasher};
use std::sync::Mutex;

use chrono::{DateTime, Datelike, Utc};
use reqwest::Client;
use serde::Deserialize;
use serde_json::Value;

use super::driver_limits::HistoryDriverLimits;
use super::error::{ProviderError, ProviderErrorCode};
use super::hourly::{classify_history_status, FetchError};
use super::http_policy::{
    acceptable_unit, build_provider_client, floor_timestamp_micros, quality_from_json,
    read_body_bounded, retry_after_secs, status_error, HttpLimits, MAX_ID_LEN,
    MAX_SAMPLES_PER_RESPONSE,
};
use super::map::{HistoryFetchPage, HistorySeries, RawProviderPoint};
use super::types::{ProviderHealth, ProviderHealthStatus, ProviderKind};

/// Raw samples from one bounded history read plus an explicit completeness flag.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PagedHistoryPoints {
    pub points: Vec<RawProviderPoint>,
    pub complete: bool,
}

#[derive(Clone)]
pub struct NfPortalDriver {
    endpoint: String,
    client_id: Option<String>,
    client_secret: Option<String>,
    anonymous: bool,
    client: Client,
    limits: HttpLimits,
    token: Option<String>,
    token_expires_at: Option<DateTime<Utc>>,
    provider_id: String,
}

impl fmt::Debug for NfPortalDriver {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("NfPortalDriver")
            .field("endpoint", &self.endpoint)
            .field("anonymous", &self.anonymous)
            .field("client_id", &self.client_id.as_ref().map(|_| "<set>"))
            .field(
                "client_secret",
                &self.client_secret.as_ref().map(|_| "<set>"),
            )
            .field("token", &self.token.as_ref().map(|_| "<set>"))
            .field("provider_id", &self.provider_id)
            .finish()
    }
}

impl NfPortalDriver {
    pub fn new(
        provider_instance_id: impl Into<String>,
        endpoint: impl Into<String>,
        client_id: Option<String>,
        client_secret: Option<String>,
        anonymous: bool,
        limits: HttpLimits,
    ) -> Result<Self, ProviderError> {
        let client = build_provider_client(limits)?;
        Ok(Self {
            endpoint: endpoint.into(),
            client_id,
            client_secret,
            anonymous,
            client,
            limits,
            token: None,
            token_expires_at: None,
            provider_id: provider_instance_id.into(),
        })
    }

    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub fn history_driver_limits(&self) -> HistoryDriverLimits {
        HistoryDriverLimits::nf_portal()
    }

    pub fn health(&self, status: ProviderHealthStatus, message: Option<String>) -> ProviderHealth {
        ProviderHealth {
            provider_id: self.provider_id.clone(),
            kind: ProviderKind::Nf,
            status,
            message,
            last_success_at: None,
            last_error_at: None,
        }
    }

    fn token_fresh(&self) -> bool {
        match (&self.token, self.token_expires_at) {
            (Some(token), Some(exp)) if !token.is_empty() => {
                Utc::now() + chrono::Duration::seconds(60) < exp
            }
            _ => false,
        }
    }

    pub async fn authenticate(&mut self) -> Result<(), ProviderError> {
        if self.anonymous {
            return Ok(());
        }
        let Some(credential_tag) = self.credential_tag() else {
            return Err(ProviderError::auth_not_configured());
        };
        if self.token_fresh() {
            return Ok(());
        }
        if let Some((token, expires_at)) =
            load_cached_token(&self.provider_id, &self.endpoint, credential_tag)
        {
            self.token = Some(token);
            self.token_expires_at = Some(expires_at);
            return Ok(());
        }
        self.authenticate_force().await
    }

    /// Token for the gRPC transport, issued by the same NF token endpoint
    /// (`AuthService.IssueToken`). This is token issuance, not a history
    /// fallback. The value goes straight into a redacted `BearerToken`.
    pub(crate) async fn grpc_bearer(&mut self) -> Result<String, ProviderError> {
        if self.anonymous {
            return Err(ProviderError::auth_not_configured());
        }
        self.authenticate().await?;
        if !self.token_fresh() {
            self.authenticate_force().await?;
        }
        self.token
            .clone()
            .filter(|token| !token.is_empty())
            .ok_or_else(|| ProviderError::new(ProviderErrorCode::AuthFailed))
    }

    /// Drop a token the gRPC server rejected so the next call re-issues it.
    pub(crate) fn forget_token(&mut self) {
        if let (Some(tag), Some(rejected)) = (self.credential_tag(), self.token.clone()) {
            forget_cached_token_if_matches(&self.provider_id, &self.endpoint, tag, &rejected);
        }
        self.token = None;
        self.token_expires_at = None;
    }

    async fn authenticate_force(&mut self) -> Result<(), ProviderError> {
        let (Some(id), Some(secret)) = (&self.client_id, &self.client_secret) else {
            return Err(ProviderError::auth_not_configured());
        };
        let url = format!("{}/api/v1/auth/token", self.endpoint);
        let body = serde_json::json!({
            "client_id": id,
            "client_secret": secret,
            "grant_type": "client_credentials",
        });
        let deadline = tokio::time::Instant::now() + self.limits.total;
        let response = self.dispatch(&url, Some(body), false).await?;
        let status = response.status();
        if status.is_redirection() {
            return Err(status_error(status, None));
        }
        let bytes = read_body_bounded(response, self.limits.max_body_bytes, deadline).await?;
        if !status.is_success() {
            return Err(status_error(status, None));
        }
        let text = std::str::from_utf8(&bytes).map_err(|_| ProviderError::contract())?;
        let (token, expires_in) = parse_token_json(text)?;
        let ttl = expires_in.unwrap_or(300).max(0);
        self.token = Some(token);
        self.token_expires_at = if ttl == 0 {
            Some(Utc::now())
        } else {
            Some(Utc::now() + chrono::Duration::seconds(ttl))
        };
        if let (Some(tag), Some(cached), Some(expires_at)) = (
            self.credential_tag(),
            self.token.clone(),
            self.token_expires_at,
        ) {
            store_cached_token(&self.provider_id, &self.endpoint, tag, cached, expires_at);
        }
        Ok(())
    }

    fn credential_tag(&self) -> Option<u64> {
        let id = self
            .client_id
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())?;
        let secret = self
            .client_secret
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())?;
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        id.hash(&mut hasher);
        secret.hash(&mut hasher);
        Some(hasher.finish())
    }

    pub async fn query_points(
        &mut self,
        page_size: u32,
    ) -> Result<Vec<RawProviderPoint>, ProviderError> {
        let page_size = page_size.clamp(1, 500);
        let url = format!("{}/api/v1/point/query", self.endpoint);
        let (status, bytes, retry_after) = self
            .send(
                &url,
                Some(serde_json::json!({ "pageSize": page_size })),
                true,
                true,
            )
            .await?;
        self.ensure_success(status, retry_after)?;
        let text = std::str::from_utf8(&bytes).map_err(|_| ProviderError::contract())?;
        parse_point_query_json(text)
    }

    /// Portal inventory through the read-only point query, one page at a time.
    ///
    /// Normal Framework `GetPoints` (`POST /api/v1/point/query`) pages with
    /// `pageSize` and `pageOffset` and reports `totalCount`. `version` is the
    /// snapshot token when the portal sends one. History stays
    /// `GET /api/v1/point/data`.
    ///
    /// The walk stops when `totalCount` is reached, when a short page ends a
    /// result that did not advertise a total, or when the byte, time, or page
    /// budget is exhausted. A later-page failure returns the pages already
    /// accepted and `complete: false`. The first page's failure is an error,
    /// so a transport failure with no page does not look like an empty inventory.
    pub async fn query_inventory(
        &mut self,
        page_size: u32,
    ) -> Result<super::inventory_sync::InventorySnapshot, ProviderError> {
        let page_size = page_size.clamp(1, MAX_INVENTORY_PAGE_SIZE);
        let url = format!("{}/api/v1/point/query", self.endpoint);
        let deadline = tokio::time::Instant::now() + self.limits.total;
        let budget = self.limits.max_body_bytes;
        let mut pages: Vec<String> = Vec::new();
        let mut bytes_read: usize = 0;
        let mut offset: u64 = 0;
        loop {
            if pages.len() >= MAX_INVENTORY_PAGES {
                return annotate_inventory(
                    &pages,
                    page_size,
                    bytes_read,
                    Some("budget_pages".to_string()),
                );
            }
            if tokio::time::Instant::now() >= deadline {
                if pages.is_empty() {
                    return Err(ProviderError::new(ProviderErrorCode::DeadlineExceeded));
                }
                return annotate_inventory(
                    &pages,
                    page_size,
                    bytes_read,
                    Some("budget_time".to_string()),
                );
            }
            if bytes_read >= budget {
                if pages.is_empty() {
                    return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
                }
                return annotate_inventory(
                    &pages,
                    page_size,
                    bytes_read,
                    Some("budget_bytes".to_string()),
                );
            }
            let remaining = budget.saturating_sub(bytes_read);
            let body = serde_json::json!({
                "pageSize": page_size,
                "pageOffset": offset.to_string(),
                "sortField": "uuid",
                "sortOrder": "ASC",
            });
            let fetched = self
                .send_bounded(&url, Some(body), true, true, deadline, remaining)
                .await;
            let bytes = match fetched {
                Ok((_status, bytes, _retry)) => bytes,
                Err(err) => {
                    if pages.is_empty() {
                        return Err(err);
                    }
                    return annotate_inventory(
                        &pages,
                        page_size,
                        bytes_read,
                        Some(later_page_reason(&err).to_string()),
                    );
                }
            };
            bytes_read = bytes_read.saturating_add(bytes.len());
            let text = match std::str::from_utf8(&bytes) {
                Ok(text) => text.to_string(),
                Err(_) => {
                    if pages.is_empty() {
                        return Err(ProviderError::contract());
                    }
                    return annotate_inventory(
                        &pages,
                        page_size,
                        bytes_read,
                        Some("contract".to_string()),
                    );
                }
            };
            pages.push(text);
            let snap = match fold_inventory_pages(&pages, page_size) {
                Ok(snap) => snap,
                Err(err) => {
                    pages.pop();
                    if pages.is_empty() {
                        return Err(err);
                    }
                    return annotate_inventory(
                        &pages,
                        page_size,
                        bytes_read,
                        Some("contract".to_string()),
                    );
                }
            };
            let waiting = !snap.complete && snap.diagnostics.reason.as_deref() == Some("truncated");
            if !waiting {
                return Ok(stamp_inventory_bytes(snap, bytes_read));
            }
            offset = u64::try_from(snap.source_points).unwrap_or(u64::MAX);
        }
    }

    /// Read history via GetData (`GET /api/v1/point/data`).
    pub async fn fetch_history(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<PagedHistoryPoints, ProviderError> {
        let limits = self.history_driver_limits();
        if uuids.is_empty() {
            return Ok(PagedHistoryPoints {
                points: Vec::new(),
                complete: true,
            });
        }
        if uuids.len() > limits.max_points_total {
            return Err(ProviderError::new(ProviderErrorCode::Contract));
        }
        if to < from || to - from > limits.max_history_span {
            return Err(ProviderError::new(ProviderErrorCode::Contract));
        }
        let mut out = Vec::new();
        let mut seen: HashSet<(String, DateTime<Utc>)> = HashSet::new();
        let mut complete = true;
        for chunk in uuids.chunks(limits.max_points_per_request) {
            let page = self
                .fetch_history_chunk_paged(chunk, from, to, &limits)
                .await?;
            merge_history_samples(&mut out, page.points, &mut seen);
            if !page.complete {
                complete = false;
            }
        }
        Ok(PagedHistoryPoints {
            points: out,
            complete,
        })
    }

    /// One history page for the hourly scheduler. Transport stays the bounded
    /// GET used by `fetch_history`. `POST /api/v1/point/data` is a write.
    pub async fn read_history_page(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<HistoryFetchPage, FetchError> {
        debug_assert_eq!(history_http_method(), "GET");
        self.fetch_history(uuids, from, to)
            .await
            .map(|paged| HistoryFetchPage {
                series: group_history(paged.points),
                complete: paged.complete,
            })
            .map_err(fetch_error_from_provider)
    }

    pub(crate) async fn fetch_history_chunk_paged(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
        limits: &HistoryDriverLimits,
    ) -> Result<PagedHistoryPoints, ProviderError> {
        for uuid in uuids {
            if !valid_point_id(uuid) {
                return Err(ProviderError::new(ProviderErrorCode::InvalidSample));
            }
        }
        if !limits.supports_paging {
            let points = self
                .fetch_history_chunk_once(uuids, from, to, limits)
                .await?;
            return Ok(PagedHistoryPoints {
                points,
                complete: true,
            });
        }
        let mut out = Vec::new();
        let mut seen: HashSet<(String, DateTime<Utc>)> = HashSet::new();
        let mut complete = true;
        for uuid in uuids {
            let point = self
                .fetch_history_point_paged(uuid, from, to, limits)
                .await?;
            merge_history_samples(&mut out, point.points, &mut seen);
            if !point.complete {
                complete = false;
            }
        }
        Ok(PagedHistoryPoints {
            points: out,
            complete,
        })
    }

    async fn fetch_history_point_paged(
        &mut self,
        uuid: &str,
        from: DateTime<Utc>,
        to: DateTime<Utc>,
        limits: &HistoryDriverLimits,
    ) -> Result<PagedHistoryPoints, ProviderError> {
        let mut out = Vec::new();
        let mut seen: HashSet<(String, DateTime<Utc>)> = HashSet::new();
        let mut cursor = from;
        for _ in 0..limits.max_history_pages {
            let page = self
                .fetch_history_chunk_once(&[uuid.to_string()], cursor, to, limits)
                .await?;
            let capped = page.len() >= limits.max_samples_per_response;
            merge_history_samples(&mut out, page, &mut seen);
            if !capped {
                return Ok(PagedHistoryPoints {
                    points: out,
                    complete: true,
                });
            }
            let Some(next) = next_history_page_start_for_point(&out, uuid, cursor, to) else {
                return Ok(PagedHistoryPoints {
                    points: out,
                    complete: false,
                });
            };
            cursor = next;
        }
        Ok(PagedHistoryPoints {
            points: out,
            complete: false,
        })
    }

    async fn fetch_history_chunk_once(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
        limits: &HistoryDriverLimits,
    ) -> Result<Vec<RawProviderPoint>, ProviderError> {
        debug_assert_eq!(history_http_method(), "GET");
        let url = build_history_read_url(&self.endpoint, uuids, from, to);
        let (status, bytes, retry_after) = self.send(&url, None, true, true).await?;
        self.ensure_success(status, retry_after)?;
        let text = std::str::from_utf8(&bytes).map_err(|_| ProviderError::contract())?;
        parse_get_data_json_with_cap(text, limits.max_samples_per_response)
    }

    fn ensure_success(
        &self,
        status: reqwest::StatusCode,
        retry_after: Option<u64>,
    ) -> Result<(), ProviderError> {
        if status.is_success() {
            Ok(())
        } else {
            Err(status_error(status, retry_after))
        }
    }

    /// `json_body` selects POST. History passes `None` and stays a GET.
    /// `allow_auth_retry` refreshes a cached token once on HTTP 401.
    async fn send(
        &mut self,
        url: &str,
        json_body: Option<Value>,
        bearer: bool,
        allow_auth_retry: bool,
    ) -> Result<(reqwest::StatusCode, Vec<u8>, Option<u64>), ProviderError> {
        let deadline = tokio::time::Instant::now() + self.limits.total;
        self.send_bounded(
            url,
            json_body,
            bearer,
            allow_auth_retry,
            deadline,
            self.limits.max_body_bytes,
        )
        .await
    }

    /// One request under an explicit deadline and byte cap. Inventory pages
    /// share one deadline and one total byte budget.
    async fn send_bounded(
        &mut self,
        url: &str,
        json_body: Option<Value>,
        bearer: bool,
        allow_auth_retry: bool,
        deadline: tokio::time::Instant,
        max_bytes: usize,
    ) -> Result<(reqwest::StatusCode, Vec<u8>, Option<u64>), ProviderError> {
        let attempts = if allow_auth_retry { 2 } else { 1 };
        for attempt in 0..attempts {
            if tokio::time::Instant::now() >= deadline {
                return Err(ProviderError::new(ProviderErrorCode::DeadlineExceeded));
            }
            if bearer && !self.anonymous && !self.token_fresh() {
                self.authenticate_force().await?;
            }
            let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
            let response = match tokio::time::timeout(
                remaining,
                self.dispatch(url, json_body.clone(), bearer),
            )
            .await
            {
                Ok(Ok(response)) => response,
                Ok(Err(err)) => return Err(err),
                Err(_) => return Err(ProviderError::new(ProviderErrorCode::DeadlineExceeded)),
            };
            let status = response.status();
            let retry_after = response
                .headers()
                .get(reqwest::header::RETRY_AFTER)
                .and_then(|v| v.to_str().ok())
                .and_then(retry_after_secs);
            if status.as_u16() == 401
                && allow_auth_retry
                && attempt + 1 < attempts
                && !self.anonymous
            {
                if let (Some(tag), Some(rejected)) = (self.credential_tag(), self.token.clone()) {
                    forget_cached_token_if_matches(
                        &self.provider_id,
                        &self.endpoint,
                        tag,
                        &rejected,
                    );
                }
                self.token = None;
                self.token_expires_at = None;
                continue;
            }
            if status.is_redirection() {
                return Err(status_error(status, None));
            }
            let bytes = read_body_bounded(response, max_bytes, deadline).await?;
            if !status.is_success() {
                return Err(status_error(status, retry_after));
            }
            return Ok((status, bytes, retry_after));
        }
        Err(ProviderError::new(ProviderErrorCode::AuthFailed).with_status(401))
    }

    async fn dispatch(
        &self,
        url: &str,
        json_body: Option<Value>,
        bearer: bool,
    ) -> Result<reqwest::Response, ProviderError> {
        let mut req = if let Some(body) = json_body {
            self.client.post(url).json(&body)
        } else {
            self.client.get(url)
        };
        if bearer {
            if let Some(token) = self.token.as_deref().filter(|t| !t.is_empty()) {
                req = req.bearer_auth(token);
            }
        }
        req.send().await.map_err(|err| {
            if err.is_timeout() {
                ProviderError::new(ProviderErrorCode::DeadlineExceeded)
            } else {
                ProviderError::transport()
            }
        })
    }
}

pub(crate) fn valid_point_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= MAX_ID_LEN
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

/// History polling is a GET. POST on `/api/v1/point/data` writes upstream.
pub fn history_http_method() -> &'static str {
    "GET"
}

pub fn build_history_read_url(
    endpoint: &str,
    uuids: &[String],
    from: DateTime<Utc>,
    to: DateTime<Utc>,
) -> String {
    let mut url = format!(
        "{}/api/v1/point/data?from.seconds={}&to.seconds={}",
        endpoint.trim_end_matches('/'),
        from.timestamp(),
        to.timestamp()
    );
    for uuid in uuids {
        url.push_str("&uuids=");
        url.push_str(uuid);
    }
    url
}

fn fetch_error_from_provider(err: ProviderError) -> FetchError {
    if let Some(status) = err.http_status {
        return classify_history_status(status, err.retry_after_secs);
    }
    match err.code {
        ProviderErrorCode::AuthFailed
        | ProviderErrorCode::AuthNotConfigured
        | ProviderErrorCode::Forbidden => FetchError::Auth,
        ProviderErrorCode::Throttled => FetchError::Throttled {
            retry_after_secs: err.retry_after_secs,
        },
        ProviderErrorCode::Contract
        | ProviderErrorCode::InvalidSample
        | ProviderErrorCode::BodyTooLarge
        | ProviderErrorCode::RedirectRejected => FetchError::Contract,
        ProviderErrorCode::Persistence => FetchError::Persistence,
        ProviderErrorCode::NotImplemented => FetchError::NotImplemented,
        ProviderErrorCode::HistoryIncomplete => FetchError::PartialSeries,
        ProviderErrorCode::Transport
        | ProviderErrorCode::DeadlineExceeded
        | ProviderErrorCode::Config => FetchError::Transport,
    }
}

pub(crate) fn group_history(points: Vec<RawProviderPoint>) -> Vec<HistorySeries> {
    let mut grouped: std::collections::BTreeMap<String, Vec<RawProviderPoint>> =
        std::collections::BTreeMap::new();
    for point in points {
        grouped
            .entry(point.provider_point_id.clone())
            .or_default()
            .push(point);
    }
    grouped
        .into_iter()
        .map(|(provider_point_id, samples)| HistorySeries {
            provider_point_id,
            samples,
        })
        .collect()
}

struct CachedPortalToken {
    token: String,
    expires_at: DateTime<Utc>,
}

fn portal_token_cache() -> &'static Mutex<HashMap<String, CachedPortalToken>> {
    static CACHE: std::sync::OnceLock<Mutex<HashMap<String, CachedPortalToken>>> =
        std::sync::OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn portal_cache_key(provider_id: &str, endpoint: &str, credential_tag: u64) -> String {
    format!("{provider_id}\n{endpoint}\n{credential_tag:x}")
}

fn load_cached_token(
    provider_id: &str,
    endpoint: &str,
    credential_tag: u64,
) -> Option<(String, DateTime<Utc>)> {
    let guard = portal_token_cache()
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let entry = guard.get(&portal_cache_key(provider_id, endpoint, credential_tag))?;
    if Utc::now() + chrono::Duration::seconds(60) < entry.expires_at {
        Some((entry.token.clone(), entry.expires_at))
    } else {
        None
    }
}

fn store_cached_token(
    provider_id: &str,
    endpoint: &str,
    credential_tag: u64,
    token: String,
    expires_at: DateTime<Utc>,
) {
    if token.is_empty() {
        return;
    }
    let mut guard = portal_token_cache()
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    guard.insert(
        portal_cache_key(provider_id, endpoint, credential_tag),
        CachedPortalToken { token, expires_at },
    );
}

fn forget_cached_token_if_matches(
    provider_id: &str,
    endpoint: &str,
    credential_tag: u64,
    rejected: &str,
) {
    let mut guard = portal_token_cache()
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let key = portal_cache_key(provider_id, endpoint, credential_tag);
    let same = guard.get(&key).is_some_and(|entry| entry.token == rejected);
    if same {
        guard.remove(&key);
    }
}

pub fn parse_token_json(text: &str) -> Result<(String, Option<i64>), ProviderError> {
    let body: Value = serde_json::from_str(text).map_err(|_| ProviderError::contract())?;
    let token = body
        .get("accessToken")
        .or_else(|| body.get("access_token"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(ProviderError::contract)?;
    let expires = body
        .get("expiresIn")
        .or_else(|| body.get("expires_in"))
        .and_then(|v| v.as_i64());
    Ok((token.to_string(), expires))
}

#[derive(Debug, Deserialize)]
struct PointQueryResponse {
    #[serde(default)]
    points: Vec<NfPoint>,
    /// Portal result size. NF sends this as a string. Absent means this page
    /// does not prove how many points exist.
    #[serde(default, rename = "totalCount", alias = "total_count")]
    total_count: Option<Value>,
    /// Snapshot token. Every page of one walk must carry the same value.
    #[serde(default, alias = "snapshotVersion")]
    version: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct NfPoint {
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    uuid: Option<String>,
    #[serde(default)]
    id: Option<String>,
    #[serde(default)]
    latest_value: Option<NfLatestValue>,
    #[serde(default)]
    units: Option<String>,
    #[serde(default)]
    attrs: Option<serde_json::Map<String, Value>>,
}

#[derive(Debug, Deserialize)]
struct NfLatestValue {
    #[serde(default)]
    double: Option<f64>,
    #[serde(default)]
    ts: Option<String>,
    #[serde(default)]
    quality: Option<Value>,
}

pub fn parse_point_query_json(text: &str) -> Result<Vec<RawProviderPoint>, ProviderError> {
    let parsed: PointQueryResponse =
        serde_json::from_str(text).map_err(|_| ProviderError::contract())?;
    let mut out = Vec::new();
    for pt in parsed.points {
        let Some(provider_point_id) = pt.uuid.or(pt.id).filter(|s| valid_point_id(s.trim())) else {
            continue;
        };
        let Some(latest) = pt.latest_value else {
            continue;
        };
        let Some(val) = latest.double else {
            continue;
        };
        let Some(ts) = latest.ts.as_deref().and_then(parse_source_ts) else {
            continue;
        };
        let unit = match pt.units.as_deref() {
            Some(raw) => match acceptable_unit(raw) {
                Some(unit) => Some(unit),
                None => continue,
            },
            None => None,
        };
        let source_quality = match quality_from_json(latest.quality.as_ref()) {
            Ok(q) => q,
            Err(()) => continue,
        };
        out.push(RawProviderPoint {
            provider_point_id,
            display_name: pt.name,
            ts,
            val,
            unit,
            source_quality,
            attrs: pt.attrs.unwrap_or_default(),
        });
        if out.len() > MAX_SAMPLES_PER_RESPONSE {
            return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
        }
    }
    Ok(out)
}

const MAX_INVENTORY_PAGE_SIZE: u32 = 500;
const MAX_INVENTORY_PAGES: usize = 64;
const MAX_SNAPSHOT_VERSION_LEN: usize = 128;

struct ParsedInventoryPage {
    points: Vec<super::inventory_sync::InventoryPoint>,
    source_points: usize,
    total_count: Option<u64>,
    version: Option<String>,
    /// The same portal point id appeared twice in this page.
    duplicate: bool,
}

#[derive(Default)]
struct InventoryWalk {
    pages: Vec<ParsedInventoryPage>,
    source_points: u64,
    total_count: Option<u64>,
    version: Option<String>,
    seen: std::collections::HashSet<String>,
}

impl InventoryWalk {
    /// Accept one page or reject it without merging. A rejected page leaves
    /// the pages already accepted unchanged.
    fn integrate(&mut self, page: ParsedInventoryPage, page_size: u32) -> Result<(), String> {
        if page.duplicate {
            return Err("duplicate_point".to_string());
        }
        let after = self.source_points.saturating_add(page.source_points as u64);
        let total = match (self.pages.is_empty(), self.total_count, page.total_count) {
            (true, _, total) => total,
            (false, None, None) => None,
            (false, None, Some(total)) if total == after => Some(total),
            (false, Some(prev), Some(total)) if prev == total => Some(prev),
            _ => return Err("snapshot_changed".to_string()),
        };
        let version = match (self.pages.is_empty(), &self.version, &page.version) {
            (true, _, version) => version.clone(),
            (false, None, None) => None,
            (false, None, Some(version)) => Some(version.clone()),
            (false, Some(prev), Some(version)) if prev == version => Some(prev.clone()),
            _ => return Err("snapshot_changed".to_string()),
        };
        if page.source_points > page_size as usize && total != Some(after) {
            return Err("page_overflow".to_string());
        }
        if total.is_some_and(|total| after > total) {
            return Err("count_mismatch".to_string());
        }
        // A short page before the advertised total is not a place to resume.
        if page.source_points < page_size as usize && total.is_some_and(|total| after < total) {
            return Err("short_page".to_string());
        }
        for point in &page.points {
            if self.seen.contains(&point.portal_point_id) {
                return Err("duplicate_point".to_string());
            }
        }
        for point in &page.points {
            self.seen.insert(point.portal_point_id.clone());
        }
        self.total_count = total;
        self.version = version;
        self.source_points = after;
        self.pages.push(page);
        Ok(())
    }

    fn finish(
        self,
        page_size: u32,
        bytes_read: usize,
        forced: Option<String>,
    ) -> super::inventory_sync::InventorySnapshot {
        use super::inventory_sync::{InventoryDiagnostics, InventorySnapshot};
        let complete = forced.is_none() && sequence_complete(&self, page_size);
        let reason = if complete {
            None
        } else {
            Some(forced.unwrap_or_else(|| infer_incomplete_reason(&self)))
        };
        let pages_fetched = u32::try_from(self.pages.len()).unwrap_or(u32::MAX);
        let mut points = Vec::new();
        for page in self.pages {
            points.extend(page.points);
        }
        InventorySnapshot {
            points,
            source_points: usize::try_from(self.source_points).unwrap_or(usize::MAX),
            complete,
            diagnostics: InventoryDiagnostics {
                pages_fetched,
                bytes_read: u64::try_from(bytes_read).unwrap_or(u64::MAX),
                total_count: self.total_count,
                snapshot_version: self.version,
                reason,
            },
        }
    }
}

fn sequence_complete(walk: &InventoryWalk, page_size: u32) -> bool {
    if walk.pages.is_empty() {
        return false;
    }
    if let Some(total) = walk.total_count {
        return walk.source_points == total;
    }
    let last_short = walk
        .pages
        .last()
        .is_some_and(|page| page.source_points < page_size as usize);
    walk.source_points > 0 && last_short
}

fn infer_incomplete_reason(walk: &InventoryWalk) -> String {
    if walk.pages.is_empty() || walk.source_points == 0 {
        return "missing_total".to_string();
    }
    if let Some(total) = walk.total_count {
        if walk.source_points > total {
            return "count_mismatch".to_string();
        }
    }
    "truncated".to_string()
}

fn later_page_reason(err: &ProviderError) -> &'static str {
    match err.code {
        ProviderErrorCode::DeadlineExceeded => "budget_time",
        ProviderErrorCode::BodyTooLarge => "budget_bytes",
        ProviderErrorCode::Contract | ProviderErrorCode::InvalidSample => "contract",
        _ => "interrupted",
    }
}

fn optional_count(value: Option<Value>) -> Result<Option<u64>, ProviderError> {
    match value {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(number)) => number
            .as_u64()
            .map(Some)
            .ok_or_else(ProviderError::contract),
        Some(Value::String(text)) => {
            let text = text.trim();
            if text.is_empty() {
                Ok(None)
            } else {
                text.parse::<u64>()
                    .map(Some)
                    .map_err(|_| ProviderError::contract())
            }
        }
        Some(_) => Err(ProviderError::contract()),
    }
}

fn snapshot_version(raw: Option<String>) -> Result<Option<String>, ProviderError> {
    let Some(text) = raw else {
        return Ok(None);
    };
    let text = text.trim();
    if text.is_empty() {
        return Ok(None);
    }
    if text.len() > MAX_SNAPSHOT_VERSION_LEN || text.chars().any(char::is_control) {
        return Err(ProviderError::contract());
    }
    Ok(Some(text.to_string()))
}

fn fold_inventory_pages(
    pages: &[String],
    page_size: u32,
) -> Result<super::inventory_sync::InventorySnapshot, ProviderError> {
    if let [only] = pages {
        parse_inventory_json(only, page_size)
    } else {
        let refs: Vec<&str> = pages.iter().map(String::as_str).collect();
        assemble_inventory_pages(&refs, page_size)
    }
}

fn annotate_inventory(
    pages: &[String],
    page_size: u32,
    bytes_read: usize,
    reason: Option<String>,
) -> Result<super::inventory_sync::InventorySnapshot, ProviderError> {
    let mut snap = fold_inventory_pages(pages, page_size)?;
    snap.complete = false;
    if let Some(reason) = reason {
        snap.diagnostics.reason = Some(reason);
    }
    Ok(stamp_inventory_bytes(snap, bytes_read))
}

fn stamp_inventory_bytes(
    mut snap: super::inventory_sync::InventorySnapshot,
    bytes_read: usize,
) -> super::inventory_sync::InventorySnapshot {
    snap.diagnostics.bytes_read = u64::try_from(bytes_read).unwrap_or(u64::MAX);
    snap
}

/// Fold already-fetched portal pages with the same acceptance rules as the
/// live walk: stable `totalCount` and `version`, no duplicate point ids, and
/// completeness only when the total is proven or a short page ends the result.
pub(crate) fn assemble_inventory_pages(
    bodies: &[&str],
    page_size: u32,
) -> Result<super::inventory_sync::InventorySnapshot, ProviderError> {
    let page_size = page_size.clamp(1, MAX_INVENTORY_PAGE_SIZE);
    let mut walk = InventoryWalk::default();
    let mut forced = None;
    for body in bodies {
        if sequence_complete(&walk, page_size) {
            break;
        }
        let page = parse_inventory_page(body)?;
        if let Err(reason) = walk.integrate(page, page_size) {
            forced = Some(reason);
            break;
        }
        if sequence_complete(&walk, page_size) || last_page_is_short(&walk, page_size) {
            break;
        }
    }
    Ok(walk.finish(page_size, 0, forced))
}

fn last_page_is_short(walk: &InventoryWalk, page_size: u32) -> bool {
    walk.pages
        .last()
        .is_some_and(|page| page.source_points < page_size as usize)
}

/// Point query response → inventory snapshot. Unlike the latest-value parser,
/// a point needs no `latestValue`; identity and portal tags are enough.
///
/// A point joins the model when its attrs carry `equipRef`. A custom `role`
/// is optional: a point with Haystack markers and no role stays in the
/// inventory. Typed `kind`, `tz`, `his`, `hisMode`, `enum`, and `airRef` are
/// kept.
///
/// One response is complete when `totalCount` equals the points in that
/// response, including `totalCount: 0` (an empty inventory the portal
/// finished on purpose). A response with no `totalCount` is complete only
/// when it is a short page (`0 < points < pageSize`). A full page without a
/// total is truncated. An empty body with no total is not an empty inventory.
pub fn parse_inventory_json(
    text: &str,
    page_size: u32,
) -> Result<super::inventory_sync::InventorySnapshot, ProviderError> {
    assemble_inventory_pages(&[text], page_size)
}

fn parse_inventory_page(text: &str) -> Result<ParsedInventoryPage, ProviderError> {
    use super::inventory_sync::InventoryPoint;
    let parsed: PointQueryResponse =
        serde_json::from_str(text).map_err(|_| ProviderError::contract())?;
    let source_points = parsed.points.len();
    if source_points > MAX_SAMPLES_PER_RESPONSE {
        return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
    }
    let total_count = optional_count(parsed.total_count)?;
    let version = snapshot_version(parsed.version)?;
    let mut points = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut duplicate = false;
    for pt in parsed.points {
        let Some(portal_point_id) = pt.uuid.or(pt.id).map(|s| s.trim().to_string()) else {
            continue;
        };
        if !valid_point_id(&portal_point_id) {
            continue;
        }
        if !seen.insert(portal_point_id.clone()) {
            duplicate = true;
            continue;
        }
        let attrs = pt.attrs.unwrap_or_default();
        let Some(equipment_id) = attr_str(&attrs, "equipRef").filter(|id| valid_equipment_id(id))
        else {
            continue;
        };
        let role = attr_str(&attrs, "role")
            .map(|raw| fdd_core::columns::haystack_point_to_role(&raw))
            .filter(|role| valid_tag(role))
            .unwrap_or_default();
        let kind = attr_str(&attrs, "kind")
            .filter(|kind| matches!(kind.as_str(), "Number" | "Bool" | "Str"))
            .or_else(|| {
                attr_str(&attrs, "type")
                    .as_deref()
                    .and_then(kind_from_nf_type)
                    .map(str::to_string)
            });
        let (ref_rel, ref_id) = attr_str(&attrs, "airRef")
            .filter(|id| valid_equipment_id(id))
            .map(|id| (Some("airRef".to_string()), Some(id)))
            .unwrap_or((None, None));
        points.push(InventoryPoint {
            portal_point_id,
            display_name: pt
                .name
                .map(|n| n.trim().to_string())
                .filter(|n| !n.is_empty()),
            unit: pt
                .units
                .as_deref()
                .and_then(acceptable_unit)
                .or_else(|| attr_str(&attrs, "unit").and_then(|unit| acceptable_unit(&unit))),
            equipment_id,
            equip_type: attr_str(&attrs, "equipType")
                .map(|t| t.to_ascii_lowercase())
                .filter(|t| valid_tag(t)),
            equip_dis: attr_str(&attrs, "equipDis"),
            equip_markers: attr_markers(&attrs, "equipMarkers"),
            role,
            markers: attr_markers(&attrs, "markers"),
            kind,
            tz: attr_str(&attrs, "tz"),
            his: attr_marker_bool(&attrs, "his"),
            his_mode: attr_str(&attrs, "hisMode"),
            enum_value: attr_str(&attrs, "enum"),
            ref_rel,
            ref_id,
        });
    }
    Ok(ParsedInventoryPage {
        points,
        source_points,
        total_count,
        version,
        duplicate,
    })
}

fn kind_from_nf_type(raw: &str) -> Option<&'static str> {
    match raw {
        "OBJECT_ANALOG_INPUT" | "OBJECT_ANALOG_OUTPUT" | "OBJECT_ANALOG_VALUE" => Some("Number"),
        "OBJECT_BINARY_INPUT" | "OBJECT_BINARY_OUTPUT" | "OBJECT_BINARY_VALUE" => Some("Bool"),
        "OBJECT_MULTISTATE_INPUT"
        | "OBJECT_MULTISTATE_OUTPUT"
        | "OBJECT_MULTISTATE_VALUE"
        | "OBJECT_CHARACTERSTRING_VALUE" => Some("Str"),
        _ => None,
    }
}

fn attr_marker_bool(attrs: &serde_json::Map<String, Value>, key: &str) -> Option<bool> {
    match attrs.get(key) {
        Some(Value::Bool(value)) => Some(*value),
        Some(Value::String(value)) => {
            let token = value.trim();
            if token.eq_ignore_ascii_case("true") || token.eq_ignore_ascii_case("m") {
                Some(true)
            } else if token.eq_ignore_ascii_case("false") {
                Some(false)
            } else {
                None
            }
        }
        _ => None,
    }
}

fn attr_str(attrs: &serde_json::Map<String, Value>, key: &str) -> Option<String> {
    attrs
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty() && s.chars().count() <= 256 && !s.chars().any(char::is_control))
        .map(str::to_string)
}

fn attr_markers(attrs: &serde_json::Map<String, Value>, key: &str) -> Vec<String> {
    let raw: Vec<String> = match attrs.get(key) {
        Some(Value::String(s)) => s.split([',', ' ', ';']).map(str::to_string).collect(),
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(Value::as_str)
            .map(str::to_string)
            .collect(),
        _ => Vec::new(),
    };
    let mut out: Vec<String> = raw
        .into_iter()
        .map(|m| m.trim().to_string())
        .filter(|m| valid_marker(m))
        .collect();
    out.sort();
    out.dedup();
    out
}

fn valid_equipment_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 128
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
}

fn valid_tag(tag: &str) -> bool {
    !tag.is_empty()
        && tag.len() <= 64
        && tag
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
}

fn valid_marker(marker: &str) -> bool {
    !marker.is_empty()
        && marker.len() <= 64
        && marker
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_'))
}

fn parse_source_ts(raw: &str) -> Option<DateTime<Utc>> {
    let dt = DateTime::parse_from_rfc3339(raw)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.fZ")
                .ok()
                .map(|ndt| ndt.and_utc())
        })?;
    admit_source_ts(dt)
}

/// Shared timestamp gate for REST and gRPC history: floor to microseconds,
/// drop pre-1990 and more than 15 minutes in the future.
pub(crate) fn admit_source_ts(dt: DateTime<Utc>) -> Option<DateTime<Utc>> {
    let dt = floor_timestamp_micros(dt);
    if dt.year() < 1990 {
        return None;
    }
    if dt > Utc::now() + chrono::Duration::minutes(15) {
        return None;
    }
    Some(dt)
}

#[derive(Debug, Deserialize)]
struct GetDataResponse {
    #[serde(default)]
    data: Vec<GetDataSeries>,
}

#[derive(Debug, Deserialize)]
struct GetDataSeries {
    #[serde(default)]
    uuid: Option<String>,
    #[serde(default)]
    units: Option<String>,
    #[serde(default)]
    values: Vec<NfHistoryValue>,
}

#[derive(Debug, Deserialize)]
struct NfHistoryValue {
    #[serde(default)]
    ts: Option<String>,
    #[serde(default)]
    double: Option<f64>,
    #[serde(default)]
    real: Option<f64>,
    #[serde(default)]
    quality: Option<Value>,
}

pub fn merge_history_samples(
    out: &mut Vec<RawProviderPoint>,
    page: Vec<RawProviderPoint>,
    seen: &mut HashSet<(String, DateTime<Utc>)>,
) {
    for sample in page {
        let key = (sample.provider_point_id.clone(), sample.ts);
        if seen.insert(key) {
            out.push(sample);
        }
    }
}

pub(crate) fn next_history_page_start_for_point(
    samples: &[RawProviderPoint],
    point_id: &str,
    window_from: DateTime<Utc>,
    window_to: DateTime<Utc>,
) -> Option<DateTime<Utc>> {
    let max_ts = samples
        .iter()
        .filter(|row| row.provider_point_id == point_id)
        .map(|row| row.ts)
        .max()?;
    let next = max_ts + chrono::Duration::microseconds(1);
    if next >= window_to || next <= window_from {
        None
    } else {
        Some(next)
    }
}

pub fn parse_get_data_json_with_cap(
    text: &str,
    sample_cap: usize,
) -> Result<Vec<RawProviderPoint>, ProviderError> {
    let parsed: GetDataResponse =
        serde_json::from_str(text).map_err(|_| ProviderError::contract())?;
    let mut out = Vec::new();
    for series in parsed.data {
        let Some(provider_point_id) = series.uuid.filter(|s| valid_point_id(s.trim())) else {
            continue;
        };
        let unit = match series.units.as_deref() {
            Some(raw) => match acceptable_unit(raw) {
                Some(unit) => Some(unit),
                None => continue,
            },
            None => None,
        };
        for value in series.values {
            let Some(val) = value.double.or(value.real) else {
                continue;
            };
            let Some(ts) = value.ts.as_deref().and_then(parse_source_ts) else {
                continue;
            };
            let source_quality = match quality_from_json(value.quality.as_ref()) {
                Ok(q) => q,
                Err(()) => continue,
            };
            out.push(RawProviderPoint {
                provider_point_id: provider_point_id.clone(),
                display_name: None,
                ts,
                val,
                unit: unit.clone(),
                source_quality,
                attrs: serde_json::Map::new(),
            });
            if out.len() > sample_cap {
                return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
            }
        }
    }
    Ok(out)
}

#[cfg(test)]
pub fn parse_get_data_json(text: &str) -> Result<Vec<RawProviderPoint>, ProviderError> {
    parse_get_data_json_with_cap(text, MAX_SAMPLES_PER_RESPONSE)
}

#[cfg(test)]
pub(crate) fn synthetic_inventory_bodies(n: usize, page_size: usize) -> Vec<String> {
    let page_size = page_size.max(1);
    let points: Vec<serde_json::Value> = (0..n)
        .map(|index| {
            let last = index + 1 == n;
            let equip = if last { "EQ_FINAL" } else { "EQ_MAIN" };
            let role = if last {
                "sat".to_string()
            } else {
                format!("r{index:03}")
            };
            serde_json::json!({
                "uuid": format!("pt-{index:04}"),
                "attrs": {
                    "equipRef": equip,
                    "equipType": "ahu",
                    "role": role,
                    "kind": "Number",
                    "markers": "sensor"
                }
            })
        })
        .collect();
    if n == 0 {
        return vec![serde_json::json!({
            "points": [],
            "totalCount": "0",
            "version": "snap-1"
        })
        .to_string()];
    }
    points
        .chunks(page_size)
        .map(|chunk| {
            serde_json::json!({
                "points": chunk,
                "totalCount": n.to_string(),
                "version": "snap-1"
            })
            .to_string()
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::super::http_policy::HttpLimits;
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    const TOKEN_FIXTURE: &str = r#"{"accessToken":"tok-abc","expiresIn":3600}"#;

    const POINTS_FIXTURE: &str = r#"{
      "points": [
        {
          "name": "OA-T",
          "uuid": "11111111-2222-3333-4444-555555555555",
          "units": "°F",
          "latestValue": { "double": 72.5, "ts": "2026-10-18T12:00:00.123456789Z", "quality": "good" },
          "attrs": { "type": "OBJECT_ANALOG_INPUT" }
        },
        {
          "name": "missing-ts",
          "uuid": "22222222-2222-3333-4444-555555555555",
          "latestValue": { "double": 1.0 }
        },
        {
          "name": "no-value",
          "id": "pt-no-val",
          "latestValue": {}
        }
      ]
    }"#;

    fn lab_driver(port: u16, secret: &str, limits: HttpLimits) -> NfPortalDriver {
        NfPortalDriver::new(
            "nf:test",
            format!("http://127.0.0.1:{port}"),
            Some("lab-id".into()),
            Some(secret.into()),
            false,
            limits,
        )
        .unwrap()
    }

    async fn read_http_request(sock: &mut tokio::net::TcpStream) -> String {
        let mut buf = vec![0u8; 8192];
        let mut got = Vec::new();
        loop {
            let n = tokio::time::timeout(Duration::from_secs(2), sock.read(&mut buf))
                .await
                .expect("read timeout")
                .expect("read");
            if n == 0 {
                break;
            }
            got.extend_from_slice(&buf[..n]);
            if got.windows(4).any(|w| w == b"\r\n\r\n") {
                break;
            }
        }
        String::from_utf8_lossy(&got).to_string()
    }

    #[test]
    fn parses_token_without_echoing_body() {
        assert_eq!(parse_token_json(TOKEN_FIXTURE).unwrap().0, "tok-abc");
        assert_eq!(
            parse_token_json(r#"{"access_token":"snake-tok"}"#)
                .unwrap()
                .0,
            "snake-tok"
        );
        let err = parse_token_json(r#"{"echo":"CANARY-SECRET-VALUE"}"#).unwrap_err();
        assert!(!err.to_string().contains("CANARY"));
        let debug = format!(
            "{:?}",
            NfPortalDriver::new(
                "nf:test",
                "https://portal.example",
                Some("id".into()),
                Some("CANARY-SECRET-VALUE".into()),
                false,
                HttpLimits::default(),
            )
            .unwrap()
        );
        assert!(!debug.contains("CANARY-SECRET-VALUE"));
    }

    #[test]
    fn parses_point_query_keeps_micros_and_skips_missing_time() {
        let pts = parse_point_query_json(POINTS_FIXTURE).unwrap();
        assert_eq!(pts.len(), 1);
        assert_eq!(
            pts[0].provider_point_id,
            "11111111-2222-3333-4444-555555555555"
        );
        assert_eq!(pts[0].ts.timestamp_subsec_micros(), 123_456);
        assert_eq!(pts[0].unit.as_deref(), Some("°F"));
        assert_eq!(pts[0].source_quality.as_deref(), Some("good"));
        assert_ne!(pts[0].ts, Utc::now());
    }

    #[test]
    fn history_keeps_subsecond_unit_and_quality() {
        let raw = r#"{
          "data": [{
            "uuid": "f93888d3-e498-3a30-a881-eb5cbd4c40a8",
            "units": "°F",
            "values": [
              {"ts": "2026-10-18T22:51:00.123456789Z", "double": 76.1, "quality": "uncertain"},
              {"ts": "2026-10-18T22:52:00Z", "real": 76.2},
              {"ts": "2099-01-01T00:00:00Z", "double": 1.0},
              {"double": 9.0},
              {"ts": "2026-10-18T22:53:00Z", "double": 1.0, "quality": "CANARY"}
            ]
          }]
        }"#;
        let pts = parse_get_data_json(raw).unwrap();
        assert_eq!(pts.len(), 2);
        assert_eq!(pts[0].ts.timestamp_subsec_micros(), 123_456);
        assert!((pts[1].val - 76.2).abs() < f64::EPSILON);
        assert_eq!(pts[0].unit.as_deref(), Some("°F"));
        assert_eq!(pts[0].source_quality.as_deref(), Some("uncertain"));
        assert!(pts[1].source_quality.is_none());
    }

    #[tokio::test]
    async fn oauth_redirect_does_not_forward_secret_body() {
        let token_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let token_port = token_listener.local_addr().unwrap().port();
        let sink_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let sink_port = sink_listener.local_addr().unwrap().port();
        let secret = "CANARY-SECRET-VALUE";
        let sink_hit = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let sink_flag = std::sync::Arc::clone(&sink_hit);
        let sink = tokio::spawn(async move {
            if let Ok(Ok((mut sock, _))) =
                tokio::time::timeout(Duration::from_millis(800), sink_listener.accept()).await
            {
                sink_flag.store(true, std::sync::atomic::Ordering::SeqCst);
                let _ = read_http_request(&mut sock).await;
            }
        });
        let redirect = format!(
            "HTTP/1.1 307 Temporary Redirect\r\nLocation: http://127.0.0.1:{sink_port}/stolen\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        );
        let token_task = tokio::spawn(async move {
            let (mut sock, _) = token_listener.accept().await.unwrap();
            let req = read_http_request(&mut sock).await;
            let _ = sock.write_all(redirect.as_bytes()).await;
            req
        });
        let mut driver = lab_driver(token_port, secret, HttpLimits::default());
        let err = driver.authenticate().await.unwrap_err();
        let seen = token_task.await.unwrap();
        sink.await.unwrap();
        assert!(seen.starts_with("POST /api/v1/auth/token"));
        assert!(
            seen.contains(secret),
            "local token endpoint still receives the JSON body"
        );
        assert!(
            !sink_hit.load(std::sync::atomic::Ordering::SeqCst),
            "redirect target must not receive the OAuth body"
        );
        let rendered = err.to_string();
        assert!(rendered.contains("redirect_rejected"));
        assert!(!rendered.contains(secret));
        assert!(!rendered.contains("stolen"));
    }

    #[tokio::test]
    async fn error_bodies_and_unicode_do_not_leak_or_panic() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let body = format!("{}€ CANARY-SECRET-VALUE", "A".repeat(399));
        let payload = format!(
            "HTTP/1.1 401 Unauthorized\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            body.len(),
            body
        );
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let _ = read_http_request(&mut sock).await;
            let _ = sock.write_all(payload.as_bytes()).await;
        });
        let mut driver = lab_driver(port, "CANARY-SECRET-VALUE", HttpLimits::default());
        let err = driver.authenticate().await.unwrap_err();
        let rendered = format!("{err}");
        assert!(rendered.contains("auth_failed"));
        assert!(!rendered.contains("CANARY"));
        assert!(!rendered.contains('€'));
    }

    #[tokio::test]
    async fn oversized_chunked_body_is_rejected() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let _ = read_http_request(&mut sock).await;
            let _ = sock
                .write_all(
                    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n",
                )
                .await;
            let chunk = vec![b'x'; 1024];
            for _ in 0..8 {
                let _ = sock
                    .write_all(format!("{:X}\r\n", chunk.len()).as_bytes())
                    .await;
                let _ = sock.write_all(&chunk).await;
                let _ = sock.write_all(b"\r\n").await;
            }
            let _ = sock.write_all(b"0\r\n\r\n").await;
        });
        let limits = HttpLimits {
            max_body_bytes: 1500,
            ..HttpLimits::default()
        };
        let mut driver = lab_driver(port, "secret", limits);
        let err = driver.authenticate().await.unwrap_err();
        assert!(err.to_string().contains("body_too_large"));
    }

    #[test]
    fn rejected_token_does_not_drop_a_newer_cache_entry() {
        let provider = "nf:race-test";
        let endpoint = "http://portal.example/race-test";
        let tag = 7_u64;
        let expires = Utc::now() + chrono::Duration::hours(1);
        store_cached_token(provider, endpoint, tag, "new-token".into(), expires);
        forget_cached_token_if_matches(provider, endpoint, tag, "old-token");
        let (token, _) = load_cached_token(provider, endpoint, tag).expect("newer token stays");
        assert_eq!(token, "new-token");
        forget_cached_token_if_matches(provider, endpoint, tag, "new-token");
        assert!(load_cached_token(provider, endpoint, tag).is_none());
    }

    #[tokio::test]
    async fn second_driver_reuses_portal_token() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let _ = read_http_request(&mut sock).await;
            let body = TOKEN_FIXTURE;
            let payload = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = sock.write_all(payload.as_bytes()).await;
        });
        let mut first = lab_driver(port, "secret", HttpLimits::default());
        first.authenticate().await.unwrap();
        let mut second = lab_driver(port, "secret", HttpLimits::default());
        second.authenticate().await.unwrap();
        assert!(second.token_fresh());
        let mut rotated = NfPortalDriver::new(
            "nf:test",
            format!("http://127.0.0.1:{port}"),
            Some("lab-id".into()),
            Some("other-secret".into()),
            false,
            HttpLimits::default(),
        )
        .unwrap();
        let err = rotated.authenticate().await.unwrap_err();
        assert!(err.to_string().contains("auth") || err.to_string().contains("transport"));
        let mut missing = NfPortalDriver::new(
            "nf:test",
            format!("http://127.0.0.1:{port}"),
            None,
            None,
            false,
            HttpLimits::default(),
        )
        .unwrap();
        assert!(missing
            .authenticate()
            .await
            .unwrap_err()
            .to_string()
            .contains("auth_not_configured"));
    }

    #[tokio::test]
    async fn hourly_window_is_get_after_token_and_a_failure_is_not_success() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let to = Utc::now() - chrono::Duration::minutes(30);
        let from = to - chrono::Duration::hours(1);
        let sample_ts = (from + chrono::Duration::minutes(15))
            .to_rfc3339_opts(chrono::SecondsFormat::Secs, true);
        let history_body = format!(
            r#"{{"data":[{{"uuid":"11111111-2222-3333-4444-555555555555","values":[{{"double":70.5,"ts":"{sample_ts}","quality":"good"}}]}}]}}"#
        );
        let requests = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
        let recorded = std::sync::Arc::clone(&requests);
        tokio::spawn(async move {
            for step in 0..3 {
                let (mut sock, _) = listener.accept().await.unwrap();
                let req = read_http_request(&mut sock).await;
                recorded.lock().await.push(req);
                let body = if step == 0 {
                    TOKEN_FIXTURE.to_string()
                } else if step == 1 {
                    history_body.clone()
                } else {
                    r#"{"error":"upstream"}"#.to_string()
                };
                let status = if step == 2 {
                    "503 Service Unavailable"
                } else {
                    "200 OK"
                };
                let payload = format!(
                    "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = sock.write_all(payload.as_bytes()).await;
            }
        });
        let mut driver = lab_driver(port, "secret", HttpLimits::default());
        driver.authenticate().await.unwrap();
        let page = driver
            .fetch_history(&["11111111-2222-3333-4444-555555555555".into()], from, to)
            .await
            .unwrap();
        assert_eq!(page.points.len(), 1);
        assert!(page.complete);
        assert!((page.points[0].val - 70.5).abs() < 1e-9);
        let err = driver
            .fetch_history(&["11111111-2222-3333-4444-555555555555".into()], from, to)
            .await
            .unwrap_err();
        assert!(
            err.to_string().contains("unavailable")
                || err.to_string().contains("http")
                || err.to_string().contains("5"),
            "{err}"
        );
        let seen = requests.lock().await.clone();
        assert!(
            seen[0].starts_with("POST /api/v1/auth/token"),
            "{}",
            seen[0]
        );
        assert!(
            seen[1].starts_with("GET /api/v1/point/data?"),
            "{}",
            seen[1]
        );
        assert!(seen[1].contains("from.seconds="), "{}", seen[1]);
        assert!(
            seen[1].contains("11111111-2222-3333-4444-555555555555"),
            "{}",
            seen[1]
        );
        assert!(seen
            .iter()
            .all(|req| !req.starts_with("POST /api/v1/point/data")));
    }

    #[tokio::test]
    async fn stalled_body_hits_deadline_and_history_is_get() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let seen = std::sync::Arc::new(tokio::sync::Mutex::new(String::new()));
        let seen_task = std::sync::Arc::clone(&seen);
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let req = read_http_request(&mut sock).await;
            *seen_task.lock().await = req;
            let _ = sock
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\n")
                .await;
            tokio::time::sleep(Duration::from_secs(5)).await;
        });
        let limits = HttpLimits {
            connect: Duration::from_millis(200),
            total: Duration::from_millis(400),
            max_body_bytes: 1024,
        };
        let mut driver = lab_driver(port, "secret", limits);
        driver.anonymous = true;
        driver.client_id = None;
        driver.client_secret = None;
        let from = Utc::now() - chrono::Duration::minutes(30);
        let err = driver
            .fetch_history(
                &["11111111-2222-3333-4444-555555555555".into()],
                from,
                Utc::now(),
            )
            .await
            .unwrap_err();
        assert!(
            err.to_string().contains("deadline_exceeded") || err.to_string().contains("transport"),
            "{err}"
        );
        let req = seen.lock().await.clone();
        assert!(req.starts_with("GET /api/v1/point/data?"), "{req}");
        assert!(!req.starts_with("POST"));
    }

    fn bodies_of(n: usize) -> Vec<String> {
        synthetic_inventory_bodies(n, 500)
    }

    #[test]
    fn page_boundaries_match_total_count() {
        for n in [1_usize, 499, 500] {
            let bodies = bodies_of(n);
            assert_eq!(bodies.len(), 1, "{n}");
            let snap = assemble_inventory_pages(&[&bodies[0]], 500).unwrap();
            assert!(snap.complete, "{n}");
            assert_eq!(snap.source_points, n);
            assert_eq!(snap.diagnostics.pages_fetched, 1);
            assert_eq!(snap.diagnostics.total_count, Some(n as u64));
            assert_eq!(snap.diagnostics.snapshot_version.as_deref(), Some("snap-1"));
            assert!(snap.diagnostics.reason.is_none());
            assert!(snap.points.iter().any(|pt| pt.equipment_id == "EQ_FINAL"));
        }
        let empty = bodies_of(0);
        let snap = assemble_inventory_pages(&[&empty[0]], 500).unwrap();
        assert!(snap.complete, "totalCount 0 is a finished empty inventory");
        assert_eq!(snap.source_points, 0);
        assert!(snap.points.is_empty());

        let unspecified = assemble_inventory_pages(&[r#"{"points":[]}"#], 500).unwrap();
        assert!(!unspecified.complete);
        assert_eq!(
            unspecified.diagnostics.reason.as_deref(),
            Some("missing_total")
        );

        let full = bodies_of(500);
        let mut bare: serde_json::Value = serde_json::from_str(&full[0]).unwrap();
        bare.as_object_mut().unwrap().remove("totalCount");
        bare.as_object_mut().unwrap().remove("version");
        let bare = bare.to_string();
        let truncated = assemble_inventory_pages(&[&bare], 500).unwrap();
        assert!(!truncated.complete);
        assert_eq!(truncated.diagnostics.reason.as_deref(), Some("truncated"));
        let proved = assemble_inventory_pages(&[&bare, r#"{"points":[]}"#], 500).unwrap();
        assert!(proved.complete, "empty next page ends a 500-point result");
        assert_eq!(proved.source_points, 500);
        assert_eq!(proved.diagnostics.pages_fetched, 2);
    }

    #[test]
    fn multipage_keeps_the_final_device_and_rejects_a_moved_snapshot() {
        let bodies = bodies_of(501);
        assert_eq!(bodies.len(), 2);
        assert!(!bodies[0].contains("EQ_FINAL"));
        assert!(bodies[1].contains("EQ_FINAL"));
        let snap = assemble_inventory_pages(&[&bodies[0], &bodies[1]], 500).unwrap();
        assert!(snap.complete);
        assert_eq!(snap.source_points, 501);
        assert_eq!(snap.points.len(), 501);
        assert_eq!(snap.diagnostics.pages_fetched, 2);
        assert!(snap.points.iter().any(|pt| pt.equipment_id == "EQ_FINAL"));

        let only_first = assemble_inventory_pages(&[&bodies[0]], 500).unwrap();
        assert!(!only_first.complete);
        assert!(!only_first
            .points
            .iter()
            .any(|pt| pt.equipment_id == "EQ_FINAL"));

        let mut moved: serde_json::Value = serde_json::from_str(&bodies[1]).unwrap();
        moved["version"] = serde_json::json!("snap-2");
        let moved = moved.to_string();
        let changed = assemble_inventory_pages(&[&bodies[0], &moved], 500).unwrap();
        assert!(!changed.complete);
        assert_eq!(
            changed.diagnostics.reason.as_deref(),
            Some("snapshot_changed")
        );
        assert_eq!(changed.diagnostics.pages_fetched, 1);

        let mut dup: serde_json::Value = serde_json::from_str(&bodies[1]).unwrap();
        dup["points"][0]["uuid"] = serde_json::json!("pt-0000");
        let dup = dup.to_string();
        let duplicate = assemble_inventory_pages(&[&bodies[0], &dup], 500).unwrap();
        assert!(!duplicate.complete);
        assert_eq!(
            duplicate.diagnostics.reason.as_deref(),
            Some("duplicate_point")
        );
        assert!(!duplicate
            .points
            .iter()
            .any(|pt| pt.equipment_id == "EQ_FINAL"));
    }

    async fn read_http_message(sock: &mut tokio::net::TcpStream) -> (String, Vec<u8>) {
        let mut buf = Vec::new();
        let mut tmp = [0u8; 4096];
        let header_end = loop {
            let n = tokio::time::timeout(Duration::from_secs(2), sock.read(&mut tmp))
                .await
                .expect("header timeout")
                .expect("header read");
            if n == 0 {
                break 0;
            }
            buf.extend_from_slice(&tmp[..n]);
            if let Some(pos) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                break pos + 4;
            }
        };
        let headers = String::from_utf8_lossy(&buf[..header_end]).to_string();
        let len = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                if name.eq_ignore_ascii_case("content-length") {
                    value.trim().parse::<usize>().ok()
                } else {
                    None
                }
            })
            .unwrap_or(0);
        while buf.len() < header_end + len {
            let n = tokio::time::timeout(Duration::from_secs(2), sock.read(&mut tmp))
                .await
                .expect("body timeout")
                .expect("body read");
            if n == 0 {
                break;
            }
            buf.extend_from_slice(&tmp[..n]);
        }
        let body = buf
            .get(header_end..header_end + len)
            .unwrap_or(&[])
            .to_vec();
        (headers, body)
    }

    fn write_http(status: &str, body: &str) -> Vec<u8> {
        format!(
            "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
        .into_bytes()
    }

    #[derive(Clone, Copy)]
    enum LaterPage {
        Ok,
        Interrupt,
        Delay,
    }

    struct PagePortal {
        port: u16,
        offsets: std::sync::Arc<tokio::sync::Mutex<Vec<u64>>>,
    }

    impl PagePortal {
        async fn start(pages: Vec<String>, page_size: u64, later: LaterPage) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let port = listener.local_addr().unwrap().port();
            let offsets = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
            let recorded = std::sync::Arc::clone(&offsets);
            tokio::spawn(async move {
                loop {
                    let Ok((mut sock, _)) = listener.accept().await else {
                        break;
                    };
                    let (headers, body) = read_http_message(&mut sock).await;
                    if !headers.starts_with("POST /api/v1/point/query") {
                        let _ = sock
                            .write_all(&write_http("404 Not Found", r#"{"points":[]}"#))
                            .await;
                        continue;
                    }
                    let parsed: serde_json::Value =
                        serde_json::from_slice(&body).unwrap_or_default();
                    let offset = parsed
                        .get("pageOffset")
                        .and_then(|v| v.as_str())
                        .and_then(|v| v.parse::<u64>().ok())
                        .unwrap_or(0);
                    recorded.lock().await.push(offset);
                    if offset > 0 {
                        match later {
                            LaterPage::Interrupt => {
                                let _ = sock
                                    .write_all(&write_http(
                                        "503 Service Unavailable",
                                        r#"{"points":[]}"#,
                                    ))
                                    .await;
                                continue;
                            }
                            LaterPage::Delay => {
                                tokio::time::sleep(Duration::from_secs(1)).await;
                            }
                            LaterPage::Ok => {}
                        }
                    }
                    let index = usize::try_from(offset / page_size).unwrap_or(usize::MAX);
                    let payload = pages
                        .get(index)
                        .map(String::as_str)
                        .unwrap_or(r#"{"points":[]}"#);
                    let _ = sock.write_all(&write_http("200 OK", payload)).await;
                }
            });
            Self { port, offsets }
        }
    }

    fn anon_driver(port: u16, limits: HttpLimits) -> NfPortalDriver {
        NfPortalDriver::new(
            "nf:test",
            format!("http://127.0.0.1:{port}"),
            None,
            None,
            true,
            limits,
        )
        .unwrap()
    }

    #[tokio::test]
    async fn driver_pages_501_points_and_stops_on_a_failed_later_page() {
        let pages = bodies_of(501);
        let portal = PagePortal::start(pages, 500, LaterPage::Ok).await;
        let mut driver = anon_driver(portal.port, HttpLimits::default());
        let snap = driver.query_inventory(500).await.unwrap();
        assert!(snap.complete);
        assert_eq!(snap.source_points, 501);
        assert_eq!(snap.diagnostics.pages_fetched, 2);
        assert!(snap.points.iter().any(|pt| pt.equipment_id == "EQ_FINAL"));
        let offsets = portal.offsets.lock().await.clone();
        assert_eq!(offsets, vec![0, 500]);

        let failed = PagePortal::start(bodies_of(501), 500, LaterPage::Interrupt).await;
        let mut driver = anon_driver(failed.port, HttpLimits::default());
        let partial = driver.query_inventory(500).await.unwrap();
        assert!(!partial.complete);
        assert_eq!(partial.diagnostics.reason.as_deref(), Some("interrupted"));
        assert_eq!(partial.diagnostics.pages_fetched, 1);
        assert!(!partial
            .points
            .iter()
            .any(|pt| pt.equipment_id == "EQ_FINAL"));
    }

    #[tokio::test]
    async fn later_page_respects_time_and_byte_budgets() {
        let delayed =
            PagePortal::start(synthetic_inventory_bodies(2, 1), 1, LaterPage::Delay).await;
        let mut driver = anon_driver(
            delayed.port,
            HttpLimits {
                connect: Duration::from_millis(200),
                total: Duration::from_millis(300),
                max_body_bytes: 1024 * 1024,
            },
        );
        let snap = driver.query_inventory(1).await.unwrap();
        assert!(!snap.complete);
        assert_eq!(snap.diagnostics.reason.as_deref(), Some("budget_time"));
        assert_eq!(snap.diagnostics.pages_fetched, 1);

        let pages = synthetic_inventory_bodies(2, 1);
        let budget = pages[0].len();
        let limited = PagePortal::start(pages, 1, LaterPage::Ok).await;
        let mut driver = anon_driver(
            limited.port,
            HttpLimits {
                max_body_bytes: budget,
                ..HttpLimits::default()
            },
        );
        let snap = driver.query_inventory(1).await.unwrap();
        assert!(!snap.complete);
        assert_eq!(snap.diagnostics.reason.as_deref(), Some("budget_bytes"));
        assert_eq!(snap.source_points, 1);
        assert_eq!(limited.offsets.lock().await.clone(), vec![0]);
    }
}
