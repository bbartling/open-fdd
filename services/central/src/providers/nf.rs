//! Normal Framework portal HTTPS driver (OAuth + point/query).

use std::time::Duration;

use chrono::{DateTime, Timelike, Utc};
use reqwest::Client;
use serde::Deserialize;
use serde_json::Value;

use super::hourly::FetchError;
use super::map::{HistorySeries, RawProviderPoint};

const USER_AGENT: &str = "openfdd-central-nf/1.0";

#[derive(Debug, Clone)]
pub struct NfPortalDriver {
    pub endpoint: String,
    pub client_id: Option<String>,
    pub client_secret: Option<String>,
    client: Client,
    token: Option<String>,
    provider_id: String,
}

impl NfPortalDriver {
    pub fn new(
        building_id: &str,
        endpoint: impl Into<String>,
        client_id: Option<String>,
        client_secret: Option<String>,
    ) -> Self {
        let client = Client::builder()
            .user_agent(USER_AGENT)
            .timeout(Duration::from_secs(60))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .expect("nf reqwest client");
        Self {
            endpoint: endpoint.into(),
            client_id,
            client_secret,
            client,
            token: None,
            provider_id: format!("nf:{building_id}"),
        }
    }

    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub async fn authenticate(&mut self) -> Result<(), String> {
        let (Some(id), Some(secret)) = (&self.client_id, &self.client_secret) else {
            // Fail closed: missing OAuth pair is a configuration error for HTTPS portals.
            // Explicit lab anonymous mode requires OPENFDD_NF_ALLOW_ANONYMOUS=1.
            let allow_anon = std::env::var("OPENFDD_NF_ALLOW_ANONYMOUS")
                .ok()
                .is_some_and(|v| matches!(v.trim(), "1" | "true" | "TRUE" | "yes" | "YES"));
            if allow_anon {
                return Ok(());
            }
            return Err(
                "nf oauth not configured (set client_id/client_secret or OPENFDD_NF_ALLOW_ANONYMOUS=1)"
                    .into(),
            );
        };
        let url = format!("{}/api/v1/auth/token", self.endpoint);
        let body = serde_json::json!({
            "client_id": id,
            "client_secret": secret,
            "grant_type": "client_credentials",
        });
        let resp = self
            .client
            .post(&url)
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("token request: {e}"))?;
        let status = resp.status();
        let text = resp.text().await.map_err(|e| format!("token body: {e}"))?;
        if !status.is_success() {
            return Err(format!("token HTTP {status}: {}", truncate(&text, 400)));
        }
        self.token = Some(parse_token_json(&text)?);
        Ok(())
    }

    /// Catalog read (`POST /api/v1/point/query`).
    ///
    /// Hourly jobs do not call this. Point discovery stays a separate POST from
    /// history, which is GET-only.
    #[expect(
        dead_code,
        reason = "catalog POST is not part of the hourly GET worker"
    )]
    pub async fn query_points(&self, page_size: u32) -> Result<Vec<RawProviderPoint>, String> {
        let url = format!("{}/api/v1/point/query", self.endpoint);
        let mut req = self
            .client
            .post(&url)
            .header("Content-Type", "application/json")
            .json(&serde_json::json!({ "pageSize": page_size }));
        if let Some(token) = self.token.as_deref().filter(|t| !t.is_empty()) {
            req = req.bearer_auth(token);
        }
        let resp = req.send().await.map_err(|e| format!("point/query: {e}"))?;
        let status = resp.status();
        let text = resp
            .text()
            .await
            .map_err(|e| format!("point/query body: {e}"))?;
        if !status.is_success() {
            return Err(format!(
                "point/query HTTP {status}: {}",
                truncate(&text, 400)
            ));
        }
        parse_point_query_json(&text)
    }

    /// Read one history page via GetData (`GET /api/v1/point/data`).
    ///
    /// `POST /api/v1/point/data` is AddPointsData (a write). This method never
    /// uses POST. Docs: https://docs.normal.dev/concepts/points/
    pub async fn read_history_page(
        &self,
        uuids: &[String],
        from: DateTime<Utc>,
        to: DateTime<Utc>,
    ) -> Result<Vec<HistorySeries>, FetchError> {
        if uuids.is_empty() {
            return Ok(Vec::new());
        }
        debug_assert_eq!(history_http_method(), "GET");
        let url = build_history_read_url(&self.endpoint, uuids, from, to);
        let mut req = match history_http_method() {
            "GET" => self.client.get(&url),
            _ => return Err(FetchError::Contract),
        };
        if let Some(token) = self.token.as_deref().filter(|t| !t.is_empty()) {
            req = req.bearer_auth(token);
        }
        let resp = req.send().await.map_err(|_| FetchError::Transport)?;
        let status = resp.status();
        let retry_after = retry_after_secs(resp.headers());
        let text = resp.text().await.map_err(|_| FetchError::Transport)?;
        if !status.is_success() {
            tracing::warn!(status = status.as_u16(), "NF history read failed");
            return Err(super::hourly::classify_history_status(
                status.as_u16(),
                retry_after,
            ));
        }
        parse_get_data_page(&text).map_err(|_| FetchError::Contract)
    }
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
        url.push_str(&percent_encode(uuid));
    }
    url
}

fn percent_encode(raw: &str) -> String {
    let mut out = String::new();
    for b in raw.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

fn retry_after_secs(headers: &reqwest::header::HeaderMap) -> Option<u64> {
    let value = headers.get(reqwest::header::RETRY_AFTER)?.to_str().ok()?;
    value.trim().parse().ok()
}

fn truncate(s: &str, max: usize) -> String {
    let mut out = String::new();
    for (i, ch) in s.chars().enumerate() {
        if i >= max {
            out.push('…');
            break;
        }
        out.push(ch);
    }
    out
}

pub fn parse_token_json(text: &str) -> Result<String, String> {
    let body: Value = serde_json::from_str(text).map_err(|e| format!("token JSON: {e}"))?;
    body.get("accessToken")
        .or_else(|| body.get("access_token"))
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .ok_or_else(|| format!("no accessToken in response: {body:?}"))
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
}

pub fn parse_point_query_json(text: &str) -> Result<Vec<RawProviderPoint>, String> {
    let parsed: PointQueryResponse =
        serde_json::from_str(text).map_err(|e| format!("point/query JSON: {e}"))?;
    let mut out = Vec::new();
    for pt in parsed.points {
        let provider_point_id = pt
            .uuid
            .or(pt.id)
            .filter(|s| !s.trim().is_empty())
            .ok_or_else(|| "point missing uuid/id".to_string())?;
        let latest = pt.latest_value.unwrap_or(NfLatestValue {
            double: None,
            ts: None,
        });
        let Some(val) = latest.double else {
            continue;
        };
        let ts = latest
            .ts
            .as_deref()
            .and_then(parse_ts)
            .unwrap_or_else(Utc::now);
        let unit = pt.units.filter(|u| !u.is_empty());
        out.push(RawProviderPoint {
            provider_point_id,
            display_name: pt.name,
            ts,
            val,
            unit,
            attrs: pt.attrs.unwrap_or_default(),
        });
    }
    Ok(out)
}

fn parse_ts(raw: &str) -> Option<DateTime<Utc>> {
    let dt = DateTime::parse_from_rfc3339(raw)
        .ok()
        .map(|dt| dt.with_timezone(&Utc))
        .or_else(|| {
            chrono::NaiveDateTime::parse_from_str(raw, "%Y-%m-%dT%H:%M:%S%.fZ")
                .ok()
                .map(|ndt| ndt.and_utc())
        })?;
    // NF history stamps carry leftover nanos. Store whole seconds so an
    // overlapping hourly pull upserts the same row instead of a twin.
    Some(dt.with_nanosecond(0).unwrap_or(dt))
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
}

pub fn parse_get_data_page(text: &str) -> Result<Vec<HistorySeries>, String> {
    let parsed: GetDataResponse =
        serde_json::from_str(text).map_err(|e| format!("point/data JSON: {e}"))?;
    let mut out = Vec::new();
    for series in parsed.data {
        let Some(provider_point_id) = series.uuid.filter(|s| !s.trim().is_empty()) else {
            continue;
        };
        let mut samples = Vec::new();
        for value in series.values {
            let Some(val) = value.double.or(value.real) else {
                continue;
            };
            let Some(ts) = value.ts.as_deref().and_then(parse_ts) else {
                continue;
            };
            samples.push(RawProviderPoint {
                provider_point_id: provider_point_id.clone(),
                display_name: None,
                ts,
                val,
                unit: None,
                attrs: serde_json::Map::new(),
            });
        }
        out.push(HistorySeries {
            provider_point_id,
            samples,
        });
    }
    Ok(out)
}

#[cfg(test)]
pub fn parse_get_data_json(text: &str) -> Result<Vec<RawProviderPoint>, String> {
    Ok(parse_get_data_page(text)?
        .into_iter()
        .flat_map(|series| series.samples)
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    const TOKEN_FIXTURE: &str = r#"{"accessToken":"tok-abc","expiresIn":3600}"#;

    const POINTS_FIXTURE: &str = r#"{
      "points": [
        {
          "name": "OA-T",
          "uuid": "11111111-2222-3333-4444-555555555555",
          "units": "°F",
          "latestValue": { "double": 72.5, "ts": "2026-10-18T12:00:00Z" },
          "attrs": { "type": "OBJECT_ANALOG_INPUT" }
        },
        {
          "name": "no-value",
          "id": "pt-no-val",
          "latestValue": {}
        }
      ]
    }"#;

    #[test]
    fn parses_token_access_token_snake() {
        let tok = parse_token_json(r#"{"access_token":"snake-tok"}"#).unwrap();
        assert_eq!(tok, "snake-tok");
    }

    #[test]
    fn parses_token_camel_case() {
        assert_eq!(parse_token_json(TOKEN_FIXTURE).unwrap(), "tok-abc");
    }

    #[test]
    fn parses_point_query_fixture() {
        let pts = parse_point_query_json(POINTS_FIXTURE).unwrap();
        assert_eq!(pts.len(), 1);
        assert_eq!(
            pts[0].provider_point_id,
            "11111111-2222-3333-4444-555555555555"
        );
        assert!((pts[0].val - 72.5).abs() < f64::EPSILON);
        assert_eq!(pts[0].display_name.as_deref(), Some("OA-T"));
    }

    #[test]
    fn parses_get_data_and_truncates_nanos() {
        let raw = r#"{
          "data": [{
            "uuid": "f93888d3-e498-3a30-a881-eb5cbd4c40a8",
            "values": [
              {"ts": "2026-10-18T22:51:00.000000321Z", "double": 76.1},
              {"ts": "2026-10-18T22:52:00Z", "real": 76.2}
            ]
          }]
        }"#;
        let pts = parse_get_data_json(raw).unwrap();
        assert_eq!(pts.len(), 2);
        assert_eq!(pts[0].ts.timestamp_subsec_nanos(), 0);
        assert!((pts[1].val - 76.2).abs() < f64::EPSILON);
    }

    #[test]
    fn history_read_is_get_and_keeps_explicit_empty_series() {
        assert_eq!(history_http_method(), "GET");
        let from = Utc.with_ymd_and_hms(2026, 10, 19, 9, 0, 0).unwrap();
        let to = Utc.with_ymd_and_hms(2026, 10, 19, 10, 0, 0).unwrap();
        let url = build_history_read_url(
            "https://portal.example",
            &["uuid-a".into(), "uuid b".into()],
            from,
            to,
        );
        assert!(url.starts_with("https://portal.example/api/v1/point/data?"));
        assert!(url.contains("from.seconds="));
        assert!(url.contains("uuids=uuid-a"));
        assert!(url.contains("uuids=uuid%20b"));
        assert!(!url.contains("POST"));
        let page = parse_get_data_page(
            r#"{"data":[{"uuid":"present","values":[]},{"uuid":"has","values":[{"ts":"2026-10-19T09:01:00Z","double":1.0}]}]}"#,
        )
        .unwrap();
        assert_eq!(page.len(), 2);
        assert!(page[0].samples.is_empty());
        assert_eq!(page[1].samples.len(), 1);
    }
}
