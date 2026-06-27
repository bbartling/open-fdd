//! Haystack HTTP client using `rusty-haystack-client` (SCRAM) and Basic auth for nHaystack/Niagara.

use crate::drivers::haystack::config::HaystackConfig;
use haystack_client::HaystackClient;
use haystack_core::codecs::codec_for;
use haystack_core::data::{HCol, HDict, HGrid};
use haystack_core::kinds::{HRef, Kind, Number};
use once_cell::sync::Lazy;
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use serde_json::{json, Value};
use std::time::Duration;
use tokio::runtime::Runtime;

static RT: Lazy<Runtime> = Lazy::new(|| Runtime::new().expect("haystack tokio runtime"));

pub fn block_on<F: std::future::Future>(f: F) -> F::Output {
    RT.block_on(f)
}

pub fn grid_to_json(grid: &HGrid) -> Value {
    let codec = match codec_for("application/json") {
        Some(c) => c,
        None => return json!({"ok": false, "error": "json codec unavailable"}),
    };
    match codec.encode_grid(grid) {
        Ok(text) => serde_json::from_str(&text).unwrap_or(json!({"raw": text})),
        Err(e) => json!({"ok": false, "error": e.to_string()}),
    }
}

pub fn client_error_json(err: &haystack_client::ClientError) -> Value {
    json!({
        "ok": false,
        "error": err.to_string()
    })
}

struct BasicHaystackClient {
    http: reqwest::blocking::Client,
    base_url: String,
    username: String,
    password: String,
    format: String,
}

impl BasicHaystackClient {
    fn new(cfg: &HaystackConfig, user: &str, pass: &str) -> Result<Self, String> {
        let mut builder = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(cfg.timeout_seconds.max(1)));
        if !cfg.tls_verify {
            builder = builder.danger_accept_invalid_certs(true);
        }
        let http = builder
            .build()
            .map_err(|e| format!("HTTP client build failed: {e}"))?;
        Ok(Self {
            http,
            base_url: cfg.base_url.trim_end_matches('/').to_string(),
            username: user.to_string(),
            password: pass.to_string(),
            format: "application/json".to_string(),
        })
    }

    fn auth_header(&self) -> String {
        use base64::Engine;
        let token = base64::engine::general_purpose::STANDARD
            .encode(format!("{}:{}", self.username, self.password));
        format!("Basic {token}")
    }

    fn call(&self, op: &str, req: &HGrid) -> Result<HGrid, String> {
        let url = format!("{}/{}", self.base_url, op);
        let codec = codec_for(&self.format).ok_or_else(|| "unsupported codec".to_string())?;
        let body = codec.encode_grid(req).map_err(|e| e.to_string())?;
        let get_ops = ["about", "ops", "formats"];
        let resp = if get_ops.contains(&op) {
            self.http
                .get(&url)
                .header(AUTHORIZATION, self.auth_header())
                .header("Accept", &self.format)
                .send()
                .map_err(|e| e.to_string())?
        } else {
            self.http
                .post(&url)
                .header(AUTHORIZATION, self.auth_header())
                .header(CONTENT_TYPE, codec.mime_type())
                .header("Accept", &self.format)
                .body(body)
                .send()
                .map_err(|e| e.to_string())?
        };
        if !resp.status().is_success() {
            return Err(format!("HTTP {} from {op}", resp.status()));
        }
        let text = resp.text().map_err(|e| e.to_string())?;
        codec.decode_grid(&text).map_err(|e| e.to_string())
    }

    fn about(&self) -> Result<HGrid, String> {
        self.call("about", &HGrid::new())
    }

    fn ops(&self) -> Result<HGrid, String> {
        self.call("ops", &HGrid::new())
    }

    fn nav(&self, nav_id: Option<&str>) -> Result<HGrid, String> {
        let mut row = HDict::new();
        if let Some(id) = nav_id {
            row.set("navId", Kind::Str(id.to_string()));
        }
        let grid = HGrid::from_parts(HDict::new(), vec![HCol::new("navId")], vec![row]);
        self.call("nav", &grid)
    }

    fn read_filter(&self, filter: &str, limit: Option<usize>) -> Result<HGrid, String> {
        let mut row = HDict::new();
        row.set("filter", Kind::Str(filter.to_string()));
        if let Some(lim) = limit {
            row.set("limit", Kind::Number(Number::unitless(lim as f64)));
        }
        let cols = if limit.is_some() {
            vec![HCol::new("filter"), HCol::new("limit")]
        } else {
            vec![HCol::new("filter")]
        };
        let grid = HGrid::from_parts(HDict::new(), cols, vec![row]);
        self.call("read", &grid)
    }

    fn read_by_ids(&self, ids: &[String]) -> Result<HGrid, String> {
        let rows: Vec<HDict> = ids
            .iter()
            .map(|id| {
                let mut d = HDict::new();
                d.set("id", Kind::Ref(HRef::from_val(id)));
                d
            })
            .collect();
        let grid = HGrid::from_parts(HDict::new(), vec![HCol::new("id")], rows);
        self.call("read", &grid)
    }

    fn point_write(
        &self,
        point_id: &str,
        value: Option<f64>,
        level: Option<u8>,
        release: bool,
        who: Option<&str>,
    ) -> Result<HGrid, String> {
        let mut row = HDict::new();
        row.set("id", Kind::Ref(HRef::from_val(point_id)));
        let mut cols = vec![HCol::new("id")];
        if release {
            if let Some(l) = level {
                row.set("level", Kind::Number(Number::unitless(l as f64)));
                cols.push(HCol::new("level"));
            }
        } else if let Some(v) = value {
            row.set("val", Kind::Number(Number::unitless(v)));
            cols.push(HCol::new("val"));
            if let Some(l) = level {
                row.set("level", Kind::Number(Number::unitless(l as f64)));
                cols.push(HCol::new("level"));
            }
        } else {
            return Err("value required unless release=true".to_string());
        }
        if let Some(w) = who {
            row.set("who", Kind::Str(w.to_string()));
            cols.push(HCol::new("who"));
        }
        let grid = HGrid::from_parts(HDict::new(), cols, vec![row]);
        self.call("pointWrite", &grid)
    }
}

enum LiveClient {
    Basic(BasicHaystackClient),
    Scram(HaystackClient<haystack_client::transport::http::HttpTransport>),
}

impl LiveClient {
    fn connect(cfg: &HaystackConfig) -> Result<Self, Value> {
        let (user, pass) = cfg.resolve_credentials();
        let user =
            user.ok_or_else(|| json!({"ok": false, "error": "Haystack username not configured"}))?;
        let pass =
            pass.ok_or_else(|| json!({"ok": false, "error": "Haystack password not configured"}))?;
        let mode = cfg.auth_mode.to_ascii_lowercase();
        if mode == "scram" || mode == "bearer" {
            let base = cfg.base_url.clone();
            let u = user.clone();
            let p = pass.clone();
            let client = block_on(async { HaystackClient::connect(&base, &u, &p).await });
            match client {
                Ok(c) => Ok(LiveClient::Scram(c)),
                Err(e) => Err(client_error_json(&e)),
            }
        } else {
            BasicHaystackClient::new(cfg, &user, &pass)
                .map(LiveClient::Basic)
                .map_err(|e| json!({"ok": false, "error": e, "auth_mode": cfg.auth_mode}))
        }
    }

    fn about(&self) -> Result<HGrid, Value> {
        match self {
            LiveClient::Basic(c) => c.about().map_err(|e| json!({"ok": false, "error": e})),
            LiveClient::Scram(c) => block_on(c.about()).map_err(|e| client_error_json(&e)),
        }
    }

    fn ops(&self) -> Result<HGrid, Value> {
        match self {
            LiveClient::Basic(c) => c.ops().map_err(|e| json!({"ok": false, "error": e})),
            LiveClient::Scram(c) => block_on(c.ops()).map_err(|e| client_error_json(&e)),
        }
    }

    fn nav(&self, nav_id: Option<&str>) -> Result<HGrid, Value> {
        match self {
            LiveClient::Basic(c) => c.nav(nav_id).map_err(|e| json!({"ok": false, "error": e})),
            LiveClient::Scram(c) => block_on(c.nav(nav_id)).map_err(|e| client_error_json(&e)),
        }
    }

    fn read_filter(&self, filter: &str, limit: Option<usize>) -> Result<HGrid, Value> {
        match self {
            LiveClient::Basic(c) => c
                .read_filter(filter, limit)
                .map_err(|e| json!({"ok": false, "error": e})),
            LiveClient::Scram(c) => {
                block_on(c.read(filter, limit)).map_err(|e| client_error_json(&e))
            }
        }
    }

    fn read_by_ids(&self, ids: &[String]) -> Result<HGrid, Value> {
        if ids.is_empty() {
            return Ok(HGrid::new());
        }
        match self {
            LiveClient::Basic(c) => c
                .read_by_ids(ids)
                .map_err(|e| json!({"ok": false, "error": e})),
            LiveClient::Scram(c) => {
                let refs: Vec<&str> = ids.iter().map(String::as_str).collect();
                block_on(c.read_by_ids(&refs)).map_err(|e| client_error_json(&e))
            }
        }
    }

    fn point_write(
        &self,
        point_id: &str,
        value: Option<f64>,
        level: Option<u8>,
        release: bool,
        who: Option<&str>,
    ) -> Result<HGrid, Value> {
        match self {
            LiveClient::Basic(c) => c
                .point_write(point_id, value, level, release, who)
                .map_err(|e| json!({"ok": false, "error": e})),
            LiveClient::Scram(_) => Err(json!({
                "ok": false,
                "error": "pointWrite requires basic auth (nHaystack/Niagara); SCRAM stations are read-only in this release"
            })),
        }
    }
}

pub fn test_connection(cfg: &HaystackConfig) -> Value {
    if !cfg.is_configured() {
        return json!({
            "ok": true,
            "enabled": false,
            "status": "disabled",
            "message": "Haystack is disabled or not configured"
        });
    }
    match LiveClient::connect(cfg) {
        Ok(client) => match client.about() {
            Ok(grid) => {
                let about = grid_to_json(&grid);
                json!({
                    "ok": true,
                    "enabled": true,
                    "status": "connected",
                    "source_id": cfg.source_id,
                    "message": "Haystack connection OK",
                    "about": about,
                    "config": cfg.redacted_summary()
                })
            }
            Err(err) => json!({
                "ok": false,
                "enabled": true,
                "status": "error",
                "source_id": cfg.source_id,
                "message": "Haystack about failed",
                "errors": [err]
            }),
        },
        Err(err) => json!({
            "ok": false,
            "enabled": true,
            "status": "error",
            "source_id": cfg.source_id,
            "message": "Haystack connect failed",
            "errors": [err]
        }),
    }
}

fn not_configured_response(cfg: &HaystackConfig, op: &str) -> Value {
    json!({
        "ok": false,
        "enabled": false,
        "status": "not_configured",
        "source_id": cfg.source_id,
        "message": format!(
            "Haystack {op} requires base_url configuration or OPENFDD_HAYSTACK_FIXTURE=1 for labeled CI fixture data"
        ),
        "config": cfg.redacted_summary()
    })
}

pub fn about(cfg: &HaystackConfig) -> Value {
    if !cfg.effective_enabled() {
        return disabled_response(cfg);
    }
    if cfg.fixture_mode() {
        return json!({
            "ok": true,
            "enabled": true,
            "status": "fixture",
            "source_id": cfg.source_id,
            "records": fixture::fixture_about()
        });
    }
    if !cfg.is_configured() {
        return not_configured_response(cfg, "about");
    }
    match LiveClient::connect(cfg) {
        Ok(client) => match client.about() {
            Ok(grid) => json!({
                "ok": true,
                "enabled": true,
                "status": "live",
                "source_id": cfg.source_id,
                "records": grid_to_json(&grid)
            }),
            Err(err) => error_response(cfg, "about failed", err),
        },
        Err(err) => error_response(cfg, "connect failed", err),
    }
}

pub fn ops(cfg: &HaystackConfig) -> Value {
    if !cfg.effective_enabled() {
        return disabled_response(cfg);
    }
    if cfg.fixture_mode() {
        return json!({
            "ok": true,
            "enabled": true,
            "status": "fixture",
            "source_id": cfg.source_id,
            "records": fixture::fixture_ops()
        });
    }
    if !cfg.is_configured() {
        return not_configured_response(cfg, "ops");
    }
    match LiveClient::connect(cfg) {
        Ok(client) => match client.ops() {
            Ok(grid) => json!({
                "ok": true,
                "enabled": true,
                "status": "live",
                "source_id": cfg.source_id,
                "records": grid_to_json(&grid)
            }),
            Err(err) => error_response(cfg, "ops failed", err),
        },
        Err(err) => error_response(cfg, "connect failed", err),
    }
}

pub fn nav(cfg: &HaystackConfig, payload: &Value) -> Value {
    if !cfg.effective_enabled() {
        return disabled_response(cfg);
    }
    let nav_id = payload
        .get("navId")
        .or_else(|| payload.get("nav_id"))
        .and_then(|v| v.as_str());
    if cfg.fixture_mode() {
        let grid = fixture::fixture_grid();
        return json!({
            "ok": true,
            "enabled": true,
            "status": "fixture",
            "source_id": cfg.source_id,
            "records": grid
        });
    }
    if !cfg.is_configured() {
        return not_configured_response(cfg, "nav");
    }
    match LiveClient::connect(cfg) {
        Ok(client) => match client.nav(nav_id) {
            Ok(grid) => json!({
                "ok": true,
                "enabled": true,
                "status": "live",
                "source_id": cfg.source_id,
                "records": grid_to_json(&grid)
            }),
            Err(err) => error_response(cfg, "nav failed", err),
        },
        Err(err) => error_response(cfg, "connect failed", err),
    }
}

pub fn read(cfg: &HaystackConfig, payload: &Value) -> Value {
    if !cfg.effective_enabled() {
        return disabled_response(cfg);
    }
    if cfg.fixture_mode() {
        let grid = fixture::fixture_grid();
        return json!({
            "ok": true,
            "enabled": true,
            "status": "fixture",
            "source_id": cfg.source_id,
            "records": grid
        });
    }
    if !cfg.is_configured() {
        return not_configured_response(cfg, "read");
    }
    let ids: Vec<String> = payload
        .get("ids")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let filter = payload
        .get("filter")
        .and_then(|v| v.as_str())
        .or(cfg.filter.as_deref())
        .unwrap_or("point");
    let limit = payload
        .get("limit")
        .and_then(|v| v.as_u64())
        .map(|n| n as usize);
    match LiveClient::connect(cfg) {
        Ok(client) => {
            let grid = if ids.is_empty() {
                client.read_filter(filter, limit)
            } else {
                client.read_by_ids(&ids)
            };
            match grid {
                Ok(g) => json!({
                    "ok": true,
                    "enabled": true,
                    "status": "live",
                    "source_id": cfg.source_id,
                    "records": grid_to_json(&g)
                }),
                Err(err) => error_response(cfg, "read failed", err),
            }
        }
        Err(err) => error_response(cfg, "connect failed", err),
    }
}

pub fn write(cfg: &HaystackConfig, payload: &Value) -> Value {
    if !cfg.effective_enabled() {
        return disabled_response(cfg);
    }
    if cfg.fixture_mode() {
        return json!({
            "ok": false,
            "enabled": true,
            "status": "fixture",
            "source_id": cfg.source_id,
            "message": "Haystack pointWrite is not supported in fixture mode"
        });
    }
    if !cfg.is_configured() {
        return not_configured_response(cfg, "pointWrite");
    }
    let point_id = payload
        .get("id")
        .or_else(|| payload.get("point_id"))
        .and_then(|v| v.as_str());
    let Some(point_id) = point_id else {
        return json!({"ok": false, "error": "id (Haystack ref) required"});
    };
    let release = payload
        .get("release")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    let value = payload.get("value").or_else(|| payload.get("val")).and_then(|v| {
        v.as_f64()
            .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
    });
    let level = payload
        .get("level")
        .and_then(|v| v.as_u64())
        .map(|n| n as u8);
    let who = payload
        .get("who")
        .and_then(|v| v.as_str())
        .or(Some("openfdd"));
    match LiveClient::connect(cfg) {
        Ok(client) => match client.point_write(point_id, value, level, release, who) {
            Ok(grid) => json!({
                "ok": true,
                "enabled": true,
                "status": "live",
                "source_id": cfg.source_id,
                "message": if release { "pointWrite release OK" } else { "pointWrite OK" },
                "records": grid_to_json(&grid)
            }),
            Err(err) => error_response(cfg, "pointWrite failed", err),
        },
        Err(err) => error_response(cfg, "connect failed", err),
    }
}

fn disabled_response(cfg: &HaystackConfig) -> Value {
    json!({
        "ok": true,
        "enabled": false,
        "status": "disabled",
        "source_id": cfg.source_id,
        "message": "Haystack is disabled or not configured",
        "config": cfg.redacted_summary()
    })
}

fn error_response(cfg: &HaystackConfig, message: &str, err: Value) -> Value {
    json!({
        "ok": false,
        "enabled": cfg.effective_enabled(),
        "status": "error",
        "source_id": cfg.source_id,
        "message": message,
        "errors": [err],
        "warnings": []
    })
}

use super::fixture;

#[cfg(test)]
mod tests {
    use super::super::config::redact_secret;

    #[test]
    fn redact_secret_masks_password() {
        assert_eq!(redact_secret("secret"), "***");
    }
}
