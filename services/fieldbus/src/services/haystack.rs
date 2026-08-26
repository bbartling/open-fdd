//! Read-only Haystack client wrapper.
//!
//! - **SCRAM**: rusty-haystack `HaystackClient::connect` (SkySpark / rusty-haystack server).
//! - **Basic**: reqwest + Zinc decode via haystack_core (Niagara nHaystack). Stays on
//!   rusty-haystack v0.8.1 so we do not pull tip 0.9 (rustc 1.97 / rand conflict).

use std::collections::HashMap;
use std::sync::Arc;

use haystack_client::transport::http::HttpTransport;
use haystack_client::HaystackClient;
use haystack_core::codecs::zinc;
use haystack_core::data::HGrid;
use haystack_core::kinds::Kind;
use serde_json::{json, Value};
use tokio::sync::Mutex;

use crate::config::{HaystackAuthMode, HaystackSettings};

const READ_ONLY_OPS: &[&str] = &[
    "about", "ops", "formats", "read", "nav", "his_read", "defs", "libs",
];

#[derive(Debug)]
pub struct HaystackNotAllowedError(pub String);

impl std::fmt::Display for HaystackNotAllowedError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for HaystackNotAllowedError {}

enum ClientInner {
    Scram(HaystackClient<HttpTransport>),
    Basic(BasicHaystackHttp),
}

/// Niagara-friendly HTTP Basic + Zinc client (no SCRAM handshake).
struct BasicHaystackHttp {
    http: reqwest::Client,
    base_url: String,
    username: String,
    password: String,
}

impl BasicHaystackHttp {
    fn new(settings: &HaystackSettings) -> Result<Self, String> {
        let http = reqwest::Client::builder()
            .danger_accept_invalid_certs(!settings.tls_verify)
            .timeout(std::time::Duration::from_secs(30))
            .build()
            .map_err(|e| e.to_string())?;
        Ok(Self {
            http,
            base_url: settings.base_url.trim_end_matches('/').to_string(),
            username: settings.username.clone(),
            password: settings.password.clone(),
        })
    }

    async fn get_zinc(&self, path: &str, query: &[(&str, String)]) -> Result<HGrid, String> {
        let url = format!("{}{}", self.base_url, path);
        let mut req = self
            .http
            .get(&url)
            .basic_auth(&self.username, Some(&self.password))
            .header("Accept", "text/zinc");
        if !query.is_empty() {
            req = req.query(query);
        }
        let resp = req.send().await.map_err(|e| e.to_string())?;
        let status = resp.status();
        let body = resp.text().await.map_err(|e| e.to_string())?;
        if !status.is_success() {
            return Err(format!(
                "haystack HTTP {status}: {}",
                body.chars().take(240).collect::<String>()
            ));
        }
        zinc::decode_grid(&body).map_err(|e| e.to_string())
    }

    async fn about(&self) -> Result<HGrid, String> {
        self.get_zinc("/about", &[]).await
    }

    async fn read(&self, filter: &str) -> Result<HGrid, String> {
        self.get_zinc("/read", &[("filter", filter.to_string())])
            .await
    }

    async fn nav(&self, nav_id: Option<&str>) -> Result<HGrid, String> {
        let q: Vec<(&str, String)> = match nav_id {
            Some(id) if !id.is_empty() => vec![("navId", id.to_string())],
            _ => vec![],
        };
        self.get_zinc("/nav", &q).await
    }

    async fn his_read(&self, id: &str, range: &str) -> Result<HGrid, String> {
        self.get_zinc(
            "/hisRead",
            &[("id", id.to_string()), ("range", range.to_string())],
        )
        .await
    }
}

pub struct HaystackService {
    settings: HaystackSettings,
    client: Arc<Mutex<Option<ClientInner>>>,
}

impl HaystackService {
    pub fn new(settings: HaystackSettings) -> Self {
        Self {
            settings,
            client: Arc::new(Mutex::new(None)),
        }
    }

    pub async fn close(&self) {
        let mut guard = self.client.lock().await;
        if let Some(ClientInner::Scram(client)) = guard.take() {
            let _ = client.close().await;
        }
    }

    fn check_op(&self, op: &str) -> Result<(), HaystackNotAllowedError> {
        if READ_ONLY_OPS.contains(&op) {
            Ok(())
        } else {
            Err(HaystackNotAllowedError(format!(
                "Haystack op '{op}' is not allowlisted (read-only gateway)"
            )))
        }
    }

    async fn ensure_client(&self) -> Result<(), String> {
        let mut guard = self.client.lock().await;
        if guard.is_none() {
            let inner = match self.settings.auth_mode {
                HaystackAuthMode::Basic => {
                    ClientInner::Basic(BasicHaystackHttp::new(&self.settings)?)
                }
                HaystackAuthMode::Scram => ClientInner::Scram(
                    HaystackClient::connect(
                        &self.settings.base_url,
                        &self.settings.username,
                        &self.settings.password,
                    )
                    .await
                    .map_err(|e| e.to_string())?,
                ),
            };
            *guard = Some(inner);
        }
        Ok(())
    }

    pub async fn about(&self) -> Result<HGrid, String> {
        self.check_op("about").map_err(|e| e.to_string())?;
        self.ensure_client().await?;
        let guard = self.client.lock().await;
        match guard.as_ref().unwrap() {
            ClientInner::Scram(c) => c.about().await.map_err(|e| e.to_string()),
            ClientInner::Basic(c) => c.about().await,
        }
    }

    pub async fn read(&self, filter: &str) -> Result<HGrid, String> {
        self.check_op("read").map_err(|e| e.to_string())?;
        self.ensure_client().await?;
        let guard = self.client.lock().await;
        match guard.as_ref().unwrap() {
            ClientInner::Scram(c) => c.read(filter, None).await.map_err(|e| e.to_string()),
            ClientInner::Basic(c) => c.read(filter).await,
        }
    }

    pub async fn nav(&self, nav_id: Option<&str>) -> Result<HGrid, String> {
        self.check_op("nav").map_err(|e| e.to_string())?;
        self.ensure_client().await?;
        let guard = self.client.lock().await;
        match guard.as_ref().unwrap() {
            ClientInner::Scram(c) => c.nav(nav_id).await.map_err(|e| e.to_string()),
            ClientInner::Basic(c) => c.nav(nav_id).await,
        }
    }

    pub async fn his_read(
        &self,
        ids: &[String],
        range_start: Option<&str>,
        range_end: Option<&str>,
    ) -> Result<HashMap<String, HGrid>, String> {
        self.check_op("his_read").map_err(|e| e.to_string())?;
        self.ensure_client().await?;
        let rng = match (range_start, range_end) {
            (Some(s), Some(e)) => format!("{s},{e}"),
            (Some(s), None) => s.to_string(),
            _ => "today".into(),
        };
        let guard = self.client.lock().await;
        let mut out = HashMap::new();
        match guard.as_ref().unwrap() {
            ClientInner::Scram(client) => {
                for id in ids {
                    let grid = client.his_read(id, &rng).await.map_err(|e| e.to_string())?;
                    out.insert(id.clone(), grid);
                }
            }
            ClientInner::Basic(client) => {
                for id in ids {
                    let grid = client.his_read(id, &rng).await?;
                    out.insert(id.clone(), grid);
                }
            }
        }
        Ok(out)
    }
}

pub fn grid_to_json(grid: &HGrid) -> Value {
    let cols: Vec<_> = grid.col_names().map(String::from).collect();
    let rows: Vec<_> = grid
        .iter()
        .map(|row| {
            let mut map = serde_json::Map::new();
            for (k, v) in row.iter() {
                map.insert(k.to_string(), kind_to_json(v));
            }
            Value::Object(map)
        })
        .collect();
    json!({
        "cols": cols,
        "rows": rows,
        "count": rows.len(),
    })
}

fn kind_to_json(kind: &Kind) -> Value {
    match kind {
        Kind::Null => Value::Null,
        Kind::Bool(b) => json!(b),
        Kind::Number(n) => json!(n.to_string()),
        Kind::Str(s) => json!(s),
        Kind::Ref(r) => json!(r.to_string()),
        Kind::Uri(u) => json!(u.to_string()),
        Kind::Symbol(s) => json!(s.to_string()),
        Kind::Date(d) => json!(d.to_string()),
        Kind::Time(t) => json!(t.format("%H:%M:%S").to_string()),
        Kind::DateTime(dt) => json!(dt.to_string()),
        Kind::Coord(c) => json!(c.to_string()),
        Kind::XStr(x) => json!(x.to_string()),
        Kind::Marker | Kind::NA | Kind::Remove => json!(kind.to_string()),
        Kind::List(items) => json!(items.iter().map(kind_to_json).collect::<Vec<_>>()),
        Kind::Dict(d) => {
            let mut map = serde_json::Map::new();
            for (k, v) in d.iter() {
                map.insert(k.to_string(), kind_to_json(v));
            }
            Value::Object(map)
        }
        Kind::Grid(g) => grid_to_json(g),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::HaystackSettings;

    #[test]
    fn readonly_blocks_write_ops() {
        let svc = HaystackService::new(HaystackSettings::default());
        assert!(svc.check_op("about").is_ok());
        assert!(svc.check_op("read").is_ok());
        assert!(svc.check_op("pointWrite").is_err());
    }
}
