//! Read-only Haystack client wrapper (mirrors `app/haystack_client.py`).

use std::collections::HashMap;
use std::sync::Arc;

use haystack_client::transport::http::HttpTransport;
use haystack_client::HaystackClient;
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

pub struct HaystackService {
    settings: HaystackSettings,
    client: Arc<Mutex<Option<HaystackClient<HttpTransport>>>>,
}

impl HaystackService {
    pub fn new(settings: HaystackSettings) -> Self {
        Self {
            settings,
            client: Arc::new(Mutex::new(None)),
        }
    }

    pub async fn close(&self) {
        if let Some(client) = self.client.lock().await.take() {
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
            let client = match self.settings.auth_mode {
                HaystackAuthMode::Basic => {
                    return Err(
                        "Haystack Basic auth is not supported with the pinned rusty-haystack client (use SCRAM)"
                            .into(),
                    );
                }
                HaystackAuthMode::Scram => HaystackClient::connect(
                    &self.settings.base_url,
                    &self.settings.username,
                    &self.settings.password,
                )
                .await
                .map_err(|e| e.to_string())?,
            };
            *guard = Some(client);
        }
        Ok(())
    }

    pub async fn about(&self) -> Result<HGrid, String> {
        self.check_op("about").map_err(|e| e.to_string())?;
        self.ensure_client().await?;
        let guard = self.client.lock().await;
        guard
            .as_ref()
            .unwrap()
            .about()
            .await
            .map_err(|e| e.to_string())
    }

    pub async fn read(&self, filter: &str) -> Result<HGrid, String> {
        self.check_op("read").map_err(|e| e.to_string())?;
        self.ensure_client().await?;
        let guard = self.client.lock().await;
        guard
            .as_ref()
            .unwrap()
            .read(filter, None)
            .await
            .map_err(|e| e.to_string())
    }

    pub async fn nav(&self, nav_id: Option<&str>) -> Result<HGrid, String> {
        self.check_op("nav").map_err(|e| e.to_string())?;
        self.ensure_client().await?;
        let guard = self.client.lock().await;
        guard
            .as_ref()
            .unwrap()
            .nav(nav_id)
            .await
            .map_err(|e| e.to_string())
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
        let client = guard.as_ref().unwrap();
        let mut out = HashMap::new();
        for id in ids {
            let grid = client.his_read(id, &rng).await.map_err(|e| e.to_string())?;
            out.insert(id.clone(), grid);
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
