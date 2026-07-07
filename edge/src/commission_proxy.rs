//! Bridge → commission HTTP proxy for field BACnet when the local server shadows Who-Is.

use std::env;
use std::time::Duration;

pub fn commission_base() -> String {
    env::var("OPENFDD_COMMISSION_BASE").unwrap_or_else(|_| "http://127.0.0.1:9091".into())
}

pub fn should_proxy_bacnet() -> bool {
    if env::var("OPENFDD_BACNET_COMMISSION_PROXY")
        .map(|v| v == "0" || v.eq_ignore_ascii_case("false"))
        .unwrap_or(false)
    {
        return false;
    }
    env::var("SERVICE_MODE").unwrap_or_else(|_| "bridge".into()) == "bridge"
}

pub fn proxy_auth_header(headers: &[(String, String)]) -> Option<String> {
    headers
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case("authorization"))
        .map(|(_, v)| v.clone())
}

pub fn proxy_post(path: &str, body: &str, auth: Option<&str>) -> Result<String, String> {
    let url = format!("{}{}", commission_base().trim_end_matches('/'), path);
    let mut req = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(120))
        .build()
        .map_err(|e| e.to_string())?
        .post(url)
        .header("Content-Type", "application/json");
    if let Some(token) = auth {
        req = req.header("Authorization", token);
    }
    let resp = req
        .body(body.to_string())
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let text = resp.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!("commission proxy {path} -> HTTP {status}: {text}"));
    }
    Ok(text)
}
