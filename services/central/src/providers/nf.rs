//! Normal Framework portal HTTPS driver.
//!
//! History reads are `GET /api/v1/point/data`. `POST` on that path is a write
//! and is never used here. OAuth token calls are `POST /api/v1/auth/token`.

use std::collections::HashMap;
use std::fmt;
use std::sync::Mutex;

use chrono::{DateTime, Datelike, Utc};
use reqwest::Client;
use serde::Deserialize;
use serde_json::Value;

use super::error::{ProviderError, ProviderErrorCode};
use super::hourly::{classify_history_status, FetchError};
use super::http_policy::{
    acceptable_unit, build_provider_client, floor_timestamp_micros, quality_from_json,
    read_body_bounded, retry_after_secs, status_error, HttpLimits, MAX_HISTORY_WINDOW, MAX_ID_LEN,
    MAX_SAMPLES_PER_RESPONSE, MAX_UUIDS_PER_REQUEST, MAX_UUIDS_TOTAL,
};
use super::map::{HistorySeries, RawProviderPoint};
use super::types::{ProviderHealth, ProviderHealthStatus, ProviderKind};

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
        if self.token_fresh() {
            return Ok(());
        }
        if let Some((token, expires_at)) = load_cached_token(&self.provider_id, &self.endpoint) {
            self.token = Some(token);
            self.token_expires_at = Some(expires_at);
            return Ok(());
        }
        self.authenticate_force().await?;
        if let (Some(token), Some(expires_at)) = (&self.token, self.token_expires_at) {
            store_cached_token(&self.provider_id, &self.endpoint, token.clone(), expires_at);
        }
        Ok(())
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
        Ok(())
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

    /// Read history via GetData (`GET /api/v1/point/data`).
    pub async fn fetch_history(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<Vec<RawProviderPoint>, ProviderError> {
        if uuids.is_empty() {
            return Ok(Vec::new());
        }
        if uuids.len() > MAX_UUIDS_TOTAL {
            return Err(ProviderError::new(ProviderErrorCode::Contract));
        }
        if to < from || to - from > MAX_HISTORY_WINDOW {
            return Err(ProviderError::new(ProviderErrorCode::Contract));
        }
        let mut out = Vec::new();
        for chunk in uuids.chunks(MAX_UUIDS_PER_REQUEST) {
            let page = self.fetch_history_chunk(chunk, from, to).await?;
            if out.len().saturating_add(page.len()) > MAX_SAMPLES_PER_RESPONSE {
                return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
            }
            out.extend(page);
        }
        Ok(out)
    }

    /// One history page for the hourly scheduler. Transport stays the bounded
    /// GET used by `fetch_history`. `POST /api/v1/point/data` is a write.
    pub async fn read_history_page(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<Vec<HistorySeries>, FetchError> {
        debug_assert_eq!(history_http_method(), "GET");
        super::DataProvider::fetch_history(self, uuids, from, to)
            .await
            .map_err(fetch_error_from_provider)
    }

    async fn fetch_history_chunk(
        &mut self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<Vec<RawProviderPoint>, ProviderError> {
        for uuid in uuids {
            if !valid_point_id(uuid) {
                return Err(ProviderError::new(ProviderErrorCode::InvalidSample));
            }
        }
        debug_assert_eq!(history_http_method(), "GET");
        let url = build_history_read_url(&self.endpoint, uuids, from, to);
        let (status, bytes, retry_after) = self.send(&url, None, true, true).await?;
        self.ensure_success(status, retry_after)?;
        let text = std::str::from_utf8(&bytes).map_err(|_| ProviderError::contract())?;
        parse_get_data_json(text)
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
        let attempts = if allow_auth_retry { 2 } else { 1 };
        for attempt in 0..attempts {
            if bearer && !self.anonymous && !self.token_fresh() {
                self.authenticate_force().await?;
            }
            let deadline = tokio::time::Instant::now() + self.limits.total;
            let response = self.dispatch(url, json_body.clone(), bearer).await?;
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
                self.token = None;
                self.token_expires_at = None;
                continue;
            }
            if status.is_redirection() {
                return Err(status_error(status, None));
            }
            let bytes = read_body_bounded(response, self.limits.max_body_bytes, deadline).await?;
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

fn valid_point_id(id: &str) -> bool {
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

fn portal_cache_key(provider_id: &str, endpoint: &str) -> String {
    format!("{provider_id}\n{endpoint}")
}

fn load_cached_token(provider_id: &str, endpoint: &str) -> Option<(String, DateTime<Utc>)> {
    let guard = portal_token_cache()
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let entry = guard.get(&portal_cache_key(provider_id, endpoint))?;
    if Utc::now() + chrono::Duration::seconds(60) < entry.expires_at {
        Some((entry.token.clone(), entry.expires_at))
    } else {
        None
    }
}

fn store_cached_token(provider_id: &str, endpoint: &str, token: String, expires_at: DateTime<Utc>) {
    if token.is_empty() {
        return;
    }
    let mut guard = portal_token_cache()
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    guard.insert(
        portal_cache_key(provider_id, endpoint),
        CachedPortalToken { token, expires_at },
    );
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

fn parse_source_ts(raw: &str) -> Option<DateTime<Utc>> {
    let dt = DateTime::parse_from_rfc3339(raw)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.fZ")
                .ok()
                .map(|ndt| ndt.and_utc())
        })?;
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

pub fn parse_get_data_json(text: &str) -> Result<Vec<RawProviderPoint>, ProviderError> {
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
            if out.len() > MAX_SAMPLES_PER_RESPONSE {
                return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
            }
        }
    }
    Ok(out)
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
        let points = driver
            .fetch_history(&["11111111-2222-3333-4444-555555555555".into()], from, to)
            .await
            .unwrap();
        assert_eq!(points.len(), 1);
        assert!((points[0].val - 70.5).abs() < 1e-9);
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
}
