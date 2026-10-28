//! Open-Meteo public weather adapter.
//!
//! Read-only GET against an allowlisted origin. No credentials are attached.
//! `provider_point_id` is the Open-Meteo series id. Equipment and Haystack role
//! come from the site point map, not from names in the payload.

use chrono::{DateTime, Utc};
use reqwest::Client;
use serde_json::Value;

use super::error::{ProviderError, ProviderErrorCode};
use super::hourly::{classify_history_status, FetchError};
use super::http_policy::{
    acceptable_unit, build_provider_client, floor_timestamp_micros, read_body_bounded,
    retry_after_secs, status_error, HttpLimits, MAX_SAMPLES_PER_RESPONSE,
};
use super::map::{HistoryFetchPage, HistorySeries, RawProviderPoint};
use super::types::{ProviderHealth, ProviderHealthStatus, ProviderKind};

pub const MAX_METEO_SERIES: usize = 8;
pub const MAX_METEO_HOURS: usize = 72;
pub const MAX_METEO_WINDOW: chrono::Duration = chrono::Duration::hours(48);

const SERIES: &[&str] = &[
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "wind_speed_10m",
    "wind_direction_10m",
    "surface_pressure",
    "precipitation",
    "cloud_cover",
    "shortwave_radiation",
];

const PUBLIC_HOSTS: &[&str] = &[
    "api.open-meteo.com",
    "historical-forecast-api.open-meteo.com",
    "archive-api.open-meteo.com",
];

#[derive(Clone)]
pub struct OpenMeteoDriver {
    endpoint: String,
    latitude: f64,
    longitude: f64,
    client: Client,
    limits: HttpLimits,
    provider_id: String,
}

impl OpenMeteoDriver {
    pub fn new(
        provider_instance_id: impl Into<String>,
        endpoint: impl Into<String>,
        latitude: f64,
        longitude: f64,
        limits: HttpLimits,
    ) -> Result<Self, ProviderError> {
        let endpoint = endpoint.into();
        if !driver_origin_allowed(&endpoint) || !valid_coords(latitude, longitude) {
            return Err(ProviderError::config());
        }
        let client = build_provider_client(limits)?;
        Ok(Self {
            endpoint,
            latitude,
            longitude,
            client,
            limits,
            provider_id: provider_instance_id.into(),
        })
    }

    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub fn health(&self, status: ProviderHealthStatus, message: Option<String>) -> ProviderHealth {
        ProviderHealth {
            provider_id: self.provider_id.clone(),
            kind: ProviderKind::OpenMeteo,
            status,
            message,
            last_success_at: None,
            last_error_at: None,
        }
    }

    /// Public API. There is no token exchange.
    pub fn authenticate(&self) -> Result<(), ProviderError> {
        if self.provider_id.is_empty() || !driver_origin_allowed(&self.endpoint) {
            return Err(ProviderError::config());
        }
        Ok(())
    }

    /// Latest-without-a-map is empty. Ingest calls [`Self::fetch_history`]
    /// with the site's mapped series ids so the adapter does not invent a catalog.
    pub fn fetch_latest(&self) -> Result<Vec<RawProviderPoint>, ProviderError> {
        if !valid_coords(self.latitude, self.longitude) {
            return Err(ProviderError::config());
        }
        Ok(Vec::new())
    }

    /// GET hourly history and keep samples inside `[from, to]`.
    ///
    /// An empty `series` list returns no rows. Callers pass mapped series ids.
    pub async fn fetch_history(
        &mut self,
        series: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<Vec<RawProviderPoint>, ProviderError> {
        if series.is_empty() {
            return Ok(Vec::new());
        }
        let url = forecast_request_url(
            &self.endpoint,
            self.latitude,
            self.longitude,
            series,
            from,
            to,
        )?;
        let deadline = tokio::time::Instant::now() + self.limits.total;
        let response = self.client.get(&url).send().await.map_err(|err| {
            if err.is_timeout() {
                ProviderError::new(ProviderErrorCode::DeadlineExceeded)
            } else if err.is_redirect() {
                ProviderError::new(ProviderErrorCode::RedirectRejected)
            } else {
                ProviderError::transport()
            }
        })?;
        let status = response.status();
        let retry_after = response
            .headers()
            .get(reqwest::header::RETRY_AFTER)
            .and_then(|v| v.to_str().ok())
            .and_then(retry_after_secs);
        if !status.is_success() {
            return Err(status_error(status, retry_after));
        }
        let bytes = read_body_bounded(response, self.limits.max_body_bytes, deadline).await?;
        let text = std::str::from_utf8(&bytes).map_err(|_| ProviderError::contract())?;
        parse_hourly_json(text, series, from, to)
    }

    /// One history page for the hourly scheduler. Transport stays the bounded GET
    /// used by [`Self::fetch_history`].
    pub async fn read_history_page(
        &mut self,
        series: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<map::HistoryFetchPage, FetchError> {
        let points = self
            .fetch_history(series, from, to)
            .await
            .map_err(fetch_error_from_provider)?;
        let mut grouped: std::collections::BTreeMap<String, Vec<RawProviderPoint>> =
            std::collections::BTreeMap::new();
        for point in points {
            grouped
                .entry(point.provider_point_id.clone())
                .or_default()
                .push(point);
        }
        Ok(map::HistoryFetchPage {
            series: grouped
                .into_iter()
                .map(|(provider_point_id, samples)| HistorySeries {
                    provider_point_id,
                    samples,
                })
                .collect(),
            complete: true,
        })
    }
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
        _ => FetchError::Transport,
    }
}

pub fn series_allowed(id: &str) -> bool {
    SERIES.contains(&id)
}

pub fn public_origin(origin: &str) -> bool {
    match url::Url::parse(origin) {
        Ok(url) if url.scheme() == "https" => url
            .host_str()
            .is_some_and(|host| PUBLIC_HOSTS.contains(&host)),
        _ => false,
    }
}

fn driver_origin_allowed(origin: &str) -> bool {
    if public_origin(origin) {
        return true;
    }
    // Loopback is the offline HTTP fixture. Production config uses `public_origin`.
    match url::Url::parse(origin) {
        Ok(url) if matches!(url.scheme(), "http" | "https") => url.host_str().is_some_and(|host| {
            let host = host.trim_matches(['[', ']']);
            host == "127.0.0.1" || host.eq_ignore_ascii_case("localhost")
        }),
        _ => false,
    }
}

pub fn valid_coords(latitude: f64, longitude: f64) -> bool {
    latitude.is_finite()
        && longitude.is_finite()
        && (-90.0..=90.0).contains(&latitude)
        && (-180.0..=180.0).contains(&longitude)
}

pub fn forecast_request_url(
    origin: &str,
    latitude: f64,
    longitude: f64,
    series: &[String],
    from: DateTime<Utc>,
    to: DateTime<Utc>,
) -> Result<String, ProviderError> {
    if !valid_coords(latitude, longitude) || !driver_origin_allowed(origin) {
        return Err(ProviderError::config());
    }
    if to < from || to - from > MAX_METEO_WINDOW {
        return Err(ProviderError::new(ProviderErrorCode::Contract));
    }
    if series.is_empty() || series.len() > MAX_METEO_SERIES {
        return Err(ProviderError::new(ProviderErrorCode::Contract));
    }
    let mut ids: Vec<&str> = Vec::with_capacity(series.len());
    for id in series {
        if !series_allowed(id) || ids.contains(&id.as_str()) {
            return Err(ProviderError::new(ProviderErrorCode::Contract));
        }
        ids.push(id);
    }
    ids.sort_unstable();
    let mut url = url::Url::parse(origin).map_err(|_| ProviderError::config())?;
    url.set_path(api_path(url.host_str()));
    {
        let mut pairs = url.query_pairs_mut();
        pairs.append_pair("latitude", &format!("{latitude:.6}"));
        pairs.append_pair("longitude", &format!("{longitude:.6}"));
        pairs.append_pair("hourly", &ids.join(","));
        pairs.append_pair("start_date", &from.format("%Y-%m-%d").to_string());
        pairs.append_pair("end_date", &to.format("%Y-%m-%d").to_string());
        pairs.append_pair("timezone", "UTC");
        pairs.append_pair("temperature_unit", "fahrenheit");
        pairs.append_pair("wind_speed_unit", "mph");
        pairs.append_pair("timeformat", "iso8601");
    }
    Ok(url.to_string())
}

fn api_path(host: Option<&str>) -> &'static str {
    if host == Some("archive-api.open-meteo.com") {
        "/v1/archive"
    } else {
        "/v1/forecast"
    }
}

/// Parse an Open-Meteo hourly payload. `series` is the requested allowlist.
/// Hours outside `[from, to]`, nulls, and non-finite values are dropped.
/// Keys that were not requested, including display-name decoys, are ignored.
pub fn parse_hourly_json(
    text: &str,
    series: &[String],
    from: DateTime<Utc>,
    to: DateTime<Utc>,
) -> Result<Vec<RawProviderPoint>, ProviderError> {
    if to < from || to - from > MAX_METEO_WINDOW {
        return Err(ProviderError::new(ProviderErrorCode::Contract));
    }
    let root: Value = serde_json::from_str(text).map_err(|_| ProviderError::contract())?;
    if root.get("error").and_then(Value::as_bool) == Some(true) {
        return Err(ProviderError::contract());
    }
    let hourly = root
        .get("hourly")
        .and_then(Value::as_object)
        .ok_or_else(ProviderError::contract)?;
    let times = hourly
        .get("time")
        .and_then(Value::as_array)
        .ok_or_else(ProviderError::contract)?;
    if times.len() > MAX_METEO_HOURS {
        return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
    }
    let units = root.get("hourly_units").and_then(Value::as_object);
    let mut out = Vec::new();
    for id in series {
        if !series_allowed(id) {
            return Err(ProviderError::new(ProviderErrorCode::Contract));
        }
        let values = hourly
            .get(id)
            .and_then(Value::as_array)
            .ok_or_else(ProviderError::contract)?;
        if values.len() != times.len() {
            return Err(ProviderError::contract());
        }
        let unit = match units.and_then(|map| map.get(id)).and_then(Value::as_str) {
            Some(raw) => match acceptable_unit(raw) {
                Some(unit) => Some(unit),
                None => continue,
            },
            None => None,
        };
        for (idx, value) in values.iter().enumerate() {
            if value.is_null() {
                continue;
            }
            let Some(val) = value.as_f64().filter(|n| n.is_finite()) else {
                continue;
            };
            let Some(stamp) = times
                .get(idx)
                .and_then(Value::as_str)
                .and_then(parse_meteo_ts)
            else {
                continue;
            };
            if stamp < from || stamp > to {
                continue;
            }
            out.push(RawProviderPoint {
                provider_point_id: id.clone(),
                display_name: None,
                ts: stamp,
                val,
                unit: unit.clone(),
                source_quality: None,
                attrs: serde_json::Map::new(),
            });
            if out.len() > MAX_SAMPLES_PER_RESPONSE {
                return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
            }
        }
    }
    Ok(out)
}

fn parse_meteo_ts(raw: &str) -> Option<DateTime<Utc>> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(trimmed) {
        return Some(floor_timestamp_micros(dt.with_timezone(&Utc)));
    }
    let stamped = if trimmed.len() == 16 {
        format!("{trimmed}:00Z")
    } else if trimmed.ends_with('Z') || trimmed.contains('+') || trimmed.contains("GMT") {
        trimmed.to_string()
    } else {
        format!("{trimmed}Z")
    };
    DateTime::parse_from_rfc3339(&stamped)
        .ok()
        .map(|dt| floor_timestamp_micros(dt.with_timezone(&Utc)))
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;
    use chrono::TimeZone;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    const FIXTURE: &str = include_str!("fixtures/open_meteo_hourly.json");

    fn utc(y: i32, m: u32, d: u32, h: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(y, m, d, h, 0, 0).unwrap()
    }

    fn series3() -> Vec<String> {
        vec![
            "temperature_2m".into(),
            "relative_humidity_2m".into(),
            "dew_point_2m".into(),
        ]
    }

    #[test]
    fn public_hosts_and_coords() {
        assert!(public_origin("https://api.open-meteo.com"));
        assert!(public_origin(
            "https://historical-forecast-api.open-meteo.com"
        ));
        assert!(public_origin("https://archive-api.open-meteo.com"));
        assert!(!public_origin("http://api.open-meteo.com"));
        assert!(!public_origin("https://evil.open-meteo.com.example"));
        assert!(!public_origin("https://127.0.0.1"));
        assert!(valid_coords(43.07, -89.4));
        assert!(!valid_coords(f64::NAN, 0.0));
        assert!(!valid_coords(91.0, 0.0));
    }

    #[test]
    fn request_url_is_bounded_get_query() {
        let url = forecast_request_url(
            "https://archive-api.open-meteo.com",
            43.07,
            -89.4,
            &series3(),
            utc(2026, 10, 18, 14),
            utc(2026, 10, 18, 16),
        )
        .unwrap();
        let parsed = url::Url::parse(&url).unwrap();
        assert_eq!(parsed.scheme(), "https");
        assert_eq!(parsed.host_str(), Some("archive-api.open-meteo.com"));
        assert_eq!(parsed.path(), "/v1/archive");
        let pairs: Vec<(String, String)> = parsed
            .query_pairs()
            .map(|(k, v)| (k.into_owned(), v.into_owned()))
            .collect();
        assert!(
            pairs
                .iter()
                .any(|(k, v)| k == "hourly"
                    && v == "dew_point_2m,relative_humidity_2m,temperature_2m")
        );
        assert!(pairs.iter().any(|(k, v)| k == "timezone" && v == "UTC"));
        assert!(pairs
            .iter()
            .any(|(k, v)| k == "temperature_unit" && v == "fahrenheit"));
        assert!(!url.contains("client_secret"));
        assert!(!url.contains("POST"));
        let wide = forecast_request_url(
            "https://api.open-meteo.com",
            43.07,
            -89.4,
            &series3(),
            utc(2026, 10, 16, 0),
            utc(2026, 10, 18, 1),
        );
        assert_eq!(wide.unwrap_err().code, ProviderErrorCode::Contract);
        let mut too_many = series3();
        for idx in 0..6 {
            too_many.push(format!("extra-{idx}"));
        }
        assert!(forecast_request_url(
            "https://api.open-meteo.com",
            1.0,
            2.0,
            &too_many,
            utc(2026, 10, 18, 0),
            utc(2026, 10, 18, 1),
        )
        .is_err());
    }

    #[test]
    fn error_body_does_not_leak_and_null_hour_is_skipped() {
        let err = parse_hourly_json(
            r#"{"error":true,"reason":"CANARY-SECRET-VALUE"}"#,
            &series3(),
            utc(2026, 10, 18, 14),
            utc(2026, 10, 18, 16),
        )
        .unwrap_err();
        let rendered = err.to_string();
        assert!(rendered.contains("contract"));
        assert!(!rendered.contains("CANARY"));
        let raw = parse_hourly_json(
            FIXTURE,
            &series3(),
            utc(2026, 10, 18, 15),
            utc(2026, 10, 18, 15),
        )
        .unwrap();
        assert!(raw.iter().all(|point| point.ts == utc(2026, 10, 18, 15)));
        assert!(raw
            .iter()
            .all(|point| point.provider_point_id != "temperature_2m"));
        assert_eq!(raw.len(), 2);
    }

    #[test]
    fn unacceptable_unit_drops_the_series() {
        let raw = parse_hourly_json(
            FIXTURE,
            &["wind_speed_10m".into()],
            utc(2026, 10, 18, 14),
            utc(2026, 10, 18, 16),
        )
        .unwrap();
        assert!(raw.is_empty());
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

    #[tokio::test]
    async fn history_get_uses_fixture_and_not_the_live_api() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let body = FIXTURE.to_string();
        let seen = std::sync::Arc::new(tokio::sync::Mutex::new(String::new()));
        let seen_task = std::sync::Arc::clone(&seen);
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let req = read_http_request(&mut sock).await;
            *seen_task.lock().await = req;
            let payload = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            let _ = sock.write_all(payload.as_bytes()).await;
        });
        let mut driver = OpenMeteoDriver::new(
            "open_meteo:lab",
            format!("http://127.0.0.1:{port}"),
            43.07,
            -89.4,
            HttpLimits::default(),
        )
        .unwrap();
        let page = driver
            .read_history_page(&series3(), utc(2026, 10, 18, 14), utc(2026, 10, 18, 16))
            .await
            .unwrap();
        let points: usize = page.iter().map(|series| series.samples.len()).sum();
        assert_eq!(points, 8);
        assert_eq!(page.len(), 3);
        assert!(page
            .iter()
            .all(|series| series3().contains(&series.provider_point_id)));
        let req = seen.lock().await.clone();
        assert!(req.starts_with("GET /v1/forecast?"), "{req}");
        assert!(!req.starts_with("POST"));
        assert!(req.contains("temperature_2m"));
        assert!(!req.contains("client_secret"));
    }

    #[tokio::test]
    async fn oversized_body_and_stall_are_typed() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let _ = read_http_request(&mut sock).await;
            let _ = sock
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 5000\r\nConnection: close\r\n\r\n")
                .await;
        });
        let limits = HttpLimits {
            max_body_bytes: 64,
            ..HttpLimits::default()
        };
        let mut driver = OpenMeteoDriver::new(
            "open_meteo:lab",
            format!("http://127.0.0.1:{port}"),
            43.07,
            -89.4,
            limits,
        )
        .unwrap();
        let err = driver
            .fetch_history(&series3(), utc(2026, 10, 18, 14), utc(2026, 10, 18, 16))
            .await
            .unwrap_err();
        assert!(err.to_string().contains("body_too_large"), "{err}");

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let _ = read_http_request(&mut sock).await;
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
        let mut driver = OpenMeteoDriver::new(
            "open_meteo:lab",
            format!("http://127.0.0.1:{port}"),
            43.07,
            -89.4,
            limits,
        )
        .unwrap();
        let err = driver
            .fetch_history(&series3(), utc(2026, 10, 18, 14), utc(2026, 10, 18, 16))
            .await
            .unwrap_err();
        assert!(
            err.to_string().contains("deadline_exceeded") || err.to_string().contains("transport"),
            "{err}"
        );
    }

    #[tokio::test]
    async fn redirect_is_not_followed() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        tokio::spawn(async move {
            let (mut sock, _) = listener.accept().await.unwrap();
            let _ = read_http_request(&mut sock).await;
            let _ = sock
                .write_all(
                    b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1/stolen\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .await;
        });
        let mut driver = OpenMeteoDriver::new(
            "open_meteo:lab",
            format!("http://127.0.0.1:{port}"),
            43.07,
            -89.4,
            HttpLimits::default(),
        )
        .unwrap();
        let err = driver
            .fetch_history(&series3(), utc(2026, 10, 18, 14), utc(2026, 10, 18, 16))
            .await
            .unwrap_err();
        let rendered = err.to_string();
        assert!(
            rendered.contains("redirect_rejected") || rendered.contains("transport"),
            "{rendered}"
        );
        assert!(!rendered.contains("stolen"));
    }
}
