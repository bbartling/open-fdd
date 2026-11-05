//! Outbound provider HTTP policy: canonical origins, no redirects, TLS on,
//! connect/read/total deadlines, and a streamed byte ceiling.

use std::net::IpAddr;
use std::time::Duration;

use futures_util::StreamExt;
use reqwest::redirect::Policy;
use reqwest::Client;

use super::error::{ProviderError, ProviderErrorCode};

pub const DEFAULT_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
pub const DEFAULT_TOTAL_TIMEOUT: Duration = Duration::from_secs(45);
pub const DEFAULT_MAX_BODY_BYTES: usize = 8 * 1024 * 1024;
pub const MAX_UUIDS_PER_REQUEST: usize = 50;
pub const MAX_UUIDS_TOTAL: usize = 2_000;
pub const MAX_SAMPLES_PER_RESPONSE: usize = 50_000;
pub const MAX_ID_LEN: usize = 128;
pub const MAX_HISTORY_WINDOW: chrono::Duration = chrono::Duration::hours(6);

#[derive(Debug, Clone, Copy)]
pub struct HttpLimits {
    pub connect: Duration,
    pub total: Duration,
    pub max_body_bytes: usize,
}

impl Default for HttpLimits {
    fn default() -> Self {
        Self {
            connect: DEFAULT_CONNECT_TIMEOUT,
            total: DEFAULT_TOTAL_TIMEOUT,
            max_body_bytes: DEFAULT_MAX_BODY_BYTES,
        }
    }
}

/// Build the only provider HTTP client. Builder failure is returned; callers
/// must not substitute a client that follows redirects or disables TLS.
pub fn build_provider_client(limits: HttpLimits) -> Result<Client, ProviderError> {
    Client::builder()
        .user_agent("openfdd-central-nf/1.0")
        .connect_timeout(limits.connect)
        .timeout(limits.total)
        .redirect(Policy::none())
        .build()
        .map_err(|_| ProviderError::config())
}

/// Read the body up to `max_bytes`. `Content-Length` above the cap is rejected
/// before the body is buffered. Chunked bodies are counted as they arrive.
/// Gzip is not enabled on this client, so the cap is the wire size.
pub async fn read_body_bounded(
    resp: reqwest::Response,
    max_bytes: usize,
    deadline: tokio::time::Instant,
) -> Result<Vec<u8>, ProviderError> {
    if let Some(len) = resp.content_length() {
        if len > max_bytes as u64 {
            return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
        }
    }
    let mut stream = resp.bytes_stream();
    let mut buf = Vec::new();
    loop {
        let now = tokio::time::Instant::now();
        if now >= deadline {
            return Err(ProviderError::new(ProviderErrorCode::DeadlineExceeded));
        }
        let remaining = deadline.saturating_duration_since(now);
        let next = match tokio::time::timeout(remaining, stream.next()).await {
            Ok(item) => item,
            Err(_) => return Err(ProviderError::new(ProviderErrorCode::DeadlineExceeded)),
        };
        match next {
            None => break,
            Some(Err(_)) => return Err(ProviderError::transport()),
            Some(Ok(chunk)) => {
                if buf.len().saturating_add(chunk.len()) > max_bytes {
                    return Err(ProviderError::new(ProviderErrorCode::BodyTooLarge));
                }
                buf.extend_from_slice(&chunk);
            }
        }
    }
    Ok(buf)
}

pub fn status_error(status: reqwest::StatusCode, retry_after: Option<u64>) -> ProviderError {
    let code = status.as_u16();
    if status.is_redirection() {
        return ProviderError::new(ProviderErrorCode::RedirectRejected).with_status(code);
    }
    if code == 401 {
        return ProviderError::new(ProviderErrorCode::AuthFailed).with_status(code);
    }
    if code == 403 {
        return ProviderError::new(ProviderErrorCode::Forbidden).with_status(code);
    }
    if code == 429 {
        let mut err = ProviderError::new(ProviderErrorCode::Throttled).with_status(code);
        if let Some(secs) = retry_after {
            err = err.with_retry_after(secs);
        }
        return err;
    }
    if code >= 500 {
        return ProviderError::transport().with_status(code);
    }
    ProviderError::contract().with_status(code)
}

/// Parse `Retry-After` delta-seconds only. HTTP-date and junk are ignored.
pub fn retry_after_secs(header: &str) -> Option<u64> {
    let raw = header.trim();
    if raw.is_empty() || !raw.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    raw.parse::<u64>().ok().filter(|n| *n <= 3_600)
}

/// Canonical portal origin. Cloud drivers are HTTPS. Userinfo, query, fragment,
/// and non-origin paths are rejected. Literal private, loopback, link-local,
/// and cloud-metadata addresses are rejected unless `allow_private_network`.
/// Plain HTTP is accepted only for loopback when `allow_insecure_http` is set
/// (explicit lab mode). TLS verification is unchanged: this function never
/// disables certificate checks.
pub fn canonicalize_provider_endpoint(
    raw: &str,
    allow_insecure_http: bool,
    allow_private_network: bool,
) -> Result<String, String> {
    let url = url::Url::parse(raw.trim()).map_err(|_| "invalid_endpoint".to_string())?;
    if !url.username().is_empty() || url.password().is_some() {
        return Err("endpoint_userinfo".into());
    }
    if url.query().is_some() {
        return Err("endpoint_query".into());
    }
    if url.fragment().is_some() {
        return Err("endpoint_fragment".into());
    }
    let path = url.path();
    if path != "/" && !path.is_empty() {
        return Err("endpoint_path".into());
    }
    let host = url
        .host_str()
        .ok_or_else(|| "endpoint_host".to_string())?
        .to_string();
    let private_ok = allow_private_network || allow_insecure_http;
    if host_blocked(&host, private_ok) {
        return Err("endpoint_network_scope".into());
    }
    match url.scheme() {
        "https" => {}
        "http" if allow_insecure_http && host_is_loopback(&host) => {}
        "http" => return Err("endpoint_https_required".into()),
        _ => return Err("endpoint_scheme".into()),
    }
    match url.origin() {
        url::Origin::Tuple(scheme, origin_host, port) => {
            let default_port =
                (scheme == "https" && port == 443) || (scheme == "http" && port == 80);
            if default_port {
                Ok(format!("{scheme}://{origin_host}"))
            } else {
                Ok(format!("{scheme}://{origin_host}:{port}"))
            }
        }
        _ => Err("endpoint_scheme".into()),
    }
}

fn host_is_loopback(host: &str) -> bool {
    let lower = host.trim_matches(['[', ']']).to_ascii_lowercase();
    if lower == "localhost" || lower.ends_with(".localhost") {
        return true;
    }
    matches!(lower.parse::<IpAddr>(), Ok(ip) if ip.is_loopback())
}

fn host_blocked(host: &str, allow_private: bool) -> bool {
    let lower = host.trim_matches(['[', ']']).to_ascii_lowercase();
    if lower == "metadata.google.internal" {
        return true;
    }
    if lower == "localhost" || lower.ends_with(".localhost") {
        return !allow_private;
    }
    if let Ok(ip) = lower.parse::<IpAddr>() {
        if is_metadata_ip(ip) {
            return true;
        }
        if is_disallowed_literal(ip) {
            return !allow_private;
        }
    }
    false
}

fn is_metadata_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => v4.octets() == [169, 254, 169, 254],
        IpAddr::V6(_) => false,
    }
}

fn is_disallowed_literal(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            v4.is_private()
                || v4.is_loopback()
                || v4.is_link_local()
                || v4.is_unspecified()
                || v4.is_broadcast()
                || v4.is_documentation()
        }
        IpAddr::V6(v6) => {
            v6.is_loopback()
                || v6.is_unspecified()
                || v6.is_multicast()
                || is_unique_local(v6)
                || (v6.segments()[0] & 0xffc0) == 0xfe80
        }
    }
}

fn is_unique_local(v6: std::net::Ipv6Addr) -> bool {
    (v6.segments()[0] & 0xfe00) == 0xfc00
}

/// Stable connection id. An explicit id is used when the operator sets one.
/// Otherwise the id mixes kind, building, and canonical endpoint so two
/// portals for one building do not share `{kind}:{building}`.
pub fn connection_id(
    kind: &str,
    building_id: &str,
    endpoint: &str,
    explicit: Option<&str>,
) -> Result<String, String> {
    if let Some(id) = explicit.map(str::trim).filter(|s| !s.is_empty()) {
        if !valid_explicit_id(id) {
            return Err("provider_instance_id".into());
        }
        return Ok(format!("{kind}:{id}"));
    }
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(kind.as_bytes());
    hasher.update(b"|");
    hasher.update(building_id.as_bytes());
    hasher.update(b"|");
    hasher.update(endpoint.as_bytes());
    let digest = hex::encode(hasher.finalize());
    Ok(format!("{kind}:{building_id}:{}", &digest[..12]))
}

fn valid_explicit_id(id: &str) -> bool {
    let chars = id.chars().count();
    (1..=80).contains(&chars)
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | ':' | '-'))
}

/// Connection id (`nf:nf-bosspi`, `nf:SITE:digest`) and the committed-plan slug
/// (`nf-bosspi`, `nf-SITE-digest`) name one provider. The plan slug cannot
/// contain `:`, so an exact string compare drops every env-configured site.
pub fn provider_ids_equivalent(left: &str, right: &str) -> bool {
    if left == right {
        return true;
    }
    if !left.is_empty() && left.replace(':', "-") == right.replace(':', "-") {
        return true;
    }
    explicit_connection_matches(left, right) || explicit_connection_matches(right, left)
}

/// `{kind}:{explicit}` where `explicit` is the plan slug (no further colon).
fn explicit_connection_matches(connection: &str, model_slug: &str) -> bool {
    let Some((kind, explicit)) = connection.split_once(':') else {
        return false;
    };
    if explicit.is_empty() || explicit.contains(':') || model_slug.is_empty() {
        return false;
    }
    matches!(kind, "nf" | "ace_iot" | "open_meteo") && explicit == model_slug
}

pub fn acceptable_unit(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() || trimmed.chars().count() > 32 {
        return None;
    }
    if trimmed
        .chars()
        .any(|c| c.is_control() || matches!(c, '<' | '>' | '"' | '\'' | '\\'))
    {
        return None;
    }
    Some(trimmed.to_string())
}

/// Map a source quality token. Empty means the source omitted quality.
/// Unknown tokens are a quarantine (`Err`).
pub fn canonicalize_quality(raw: &str) -> Result<Option<String>, ()> {
    let token = raw.trim().to_ascii_lowercase();
    if token.is_empty() {
        return Ok(None);
    }
    match token.as_str() {
        "good" | "ok" | "0" => Ok(Some("good".into())),
        "uncertain" | "warning" | "1" => Ok(Some("uncertain".into())),
        "bad" | "fault" | "error" | "2" => Ok(Some("bad".into())),
        "stale" | "3" => Ok(Some("stale".into())),
        _ => Err(()),
    }
}

pub fn quality_from_json(value: Option<&serde_json::Value>) -> Result<Option<String>, ()> {
    let Some(value) = value else {
        return Ok(None);
    };
    match value {
        serde_json::Value::Null => Ok(None),
        serde_json::Value::String(s) => canonicalize_quality(s),
        serde_json::Value::Number(n) => canonicalize_quality(&n.to_string()),
        serde_json::Value::Bool(true) => Ok(Some("good".into())),
        serde_json::Value::Bool(false) => Ok(Some("bad".into())),
        serde_json::Value::Array(_) | serde_json::Value::Object(_) => Err(()),
    }
}

/// Timescale `timestamptz` stores microseconds. Floor sub-microsecond noise so
/// replay of the same source instant is stable. Whole seconds are not collapsed.
pub fn floor_timestamp_micros(dt: chrono::DateTime<chrono::Utc>) -> chrono::DateTime<chrono::Utc> {
    let extra = dt.timestamp_subsec_nanos() % 1_000;
    dt - chrono::Duration::nanoseconds(i64::from(extra))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn https_origin_strips_default_port() {
        let origin =
            canonicalize_provider_endpoint("https://portal.example/ ", false, false).unwrap();
        assert_eq!(origin, "https://portal.example");
    }

    #[test]
    fn rejects_userinfo_query_fragment_http_and_metadata() {
        assert_eq!(
            canonicalize_provider_endpoint("https://user:pw@portal.example", false, false),
            Err("endpoint_userinfo".into())
        );
        assert_eq!(
            canonicalize_provider_endpoint("https://portal.example/api?x=1", false, false),
            Err("endpoint_query".into())
        );
        assert_eq!(
            canonicalize_provider_endpoint("https://portal.example/#frag", false, false),
            Err("endpoint_fragment".into())
        );
        assert_eq!(
            canonicalize_provider_endpoint("http://portal.example", false, false),
            Err("endpoint_https_required".into())
        );
        assert_eq!(
            canonicalize_provider_endpoint("https://169.254.169.254", false, true),
            Err("endpoint_network_scope".into())
        );
        assert_eq!(
            canonicalize_provider_endpoint("https://10.1.2.3", false, false),
            Err("endpoint_network_scope".into())
        );
        assert!(canonicalize_provider_endpoint("https://10.1.2.3", false, true).is_ok());
    }

    #[test]
    fn insecure_http_only_for_loopback_lab() {
        assert_eq!(
            canonicalize_provider_endpoint("http://127.0.0.1:9", true, false).unwrap(),
            "http://127.0.0.1:9"
        );
        assert_eq!(
            canonicalize_provider_endpoint("http://portal.example", true, false),
            Err("endpoint_https_required".into())
        );
    }

    #[test]
    fn connection_id_depends_on_endpoint_not_only_building() {
        let a = connection_id("nf", "SITE", "https://a.example", None).unwrap();
        let b = connection_id("nf", "SITE", "https://b.example", None).unwrap();
        assert_ne!(a, b);
        assert_ne!(a, "nf:SITE");
        let explicit = connection_id("nf", "SITE", "https://a.example", Some("portal-1")).unwrap();
        assert_eq!(explicit, "nf:portal-1");
    }

    #[test]
    fn connection_id_matches_the_plan_slug() {
        assert!(provider_ids_equivalent("nf:nf-bosspi", "nf-bosspi"));
        assert!(provider_ids_equivalent("nf-bosspi", "nf:nf-bosspi"));
        assert!(provider_ids_equivalent(
            "nf:SITE:abc123def456",
            "nf-SITE-abc123def456"
        ));
        assert!(provider_ids_equivalent("nf:portal-1", "portal-1"));
        assert!(provider_ids_equivalent("ace_iot:edge-1", "edge-1"));
        assert!(!provider_ids_equivalent("nf:nf-bosspi", "nf-other"));
        assert!(!provider_ids_equivalent("nf:SITE:abc", "nf-SITE-def"));
        assert!(!provider_ids_equivalent("nf:portal-1", "portal-2"));
    }

    #[test]
    fn client_builder_does_not_panic() {
        assert!(build_provider_client(HttpLimits::default()).is_ok());
    }

    #[test]
    fn unknown_quality_is_quarantine() {
        assert_eq!(
            canonicalize_quality("good").unwrap().as_deref(),
            Some("good")
        );
        assert!(canonicalize_quality("CANARY").is_err());
        assert!(acceptable_unit("°F").is_some());
        assert!(acceptable_unit("bad\nunit").is_none());
    }
}
