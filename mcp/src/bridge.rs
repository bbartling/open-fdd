use reqwest::blocking::Client;
use serde_json::{json, Value};
use std::env;
use std::time::Duration;

pub struct BridgeClient {
    http: Client,
    base: String,
    token: Option<String>,
}

impl BridgeClient {
    pub fn from_env() -> Self {
        let base = env::var("OPENFDD_API_BASE").unwrap_or_else(|_| "http://127.0.0.1:8080".into());
        let token = env::var("OPENFDD_MCP_TOKEN")
            .ok()
            .filter(|t| !t.is_empty())
            .or_else(|| env::var("OPENFDD_INTEGRATOR_TOKEN").ok());
        let http = Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .expect("reqwest client");
        Self { http, base, token }
    }

    pub fn get(&self, path: &str) -> Result<Value, String> {
        let url = format!("{}{}", self.base.trim_end_matches('/'), path);
        let mut req = self.http.get(&url);
        if let Some(t) = &self.token {
            req = req.header("Authorization", format!("Bearer {t}"));
        }
        req.send()
            .map_err(|e| e.to_string())?
            .json()
            .map_err(|e| e.to_string())
    }

    pub fn post(&self, path: &str, body: &Value) -> Result<Value, String> {
        let url = format!("{}{}", self.base.trim_end_matches('/'), path);
        let mut req = self.http.post(&url).json(body);
        if let Some(t) = &self.token {
            req = req.header("Authorization", format!("Bearer {t}"));
        }
        req.send()
            .map_err(|e| e.to_string())?
            .json()
            .map_err(|e| e.to_string())
    }

    pub fn site_update_dry_run(&self) -> Value {
        json!({
            "ok": true,
            "dry_run": true,
            "steps": [
                "./scripts/openfdd_rust_site_backup.sh",
                "NEW_TAG=<tag> ./scripts/openfdd_rust_site_update.sh",
                "./scripts/openfdd_rust_edge_validate.sh",
                "./scripts/openfdd_drivers_validate.sh"
            ],
            "doc": "docs/quick-start/rust-site-lifecycle.md",
            "note": "MCP does not execute site update — operator or bench agent runs scripts on host."
        })
    }

    pub fn ghcr_manifest_check(&self, args: &Value) -> Result<Value, String> {
        let health = self.get("/api/health")?;
        let running = health
            .get("image_tag")
            .or_else(|| health.get("version"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let expected = args
            .get("expected_tag")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .or_else(|| env::var("OPENFDD_IMAGE_TAG").ok())
            .unwrap_or_default();
        Ok(json!({
            "ok": !expected.is_empty() && running == expected,
            "running_tag": running,
            "expected_tag": expected,
            "doc": "scripts/openfdd_rust_check_ghcr_platform.sh"
        }))
    }

    pub fn bench_topology(&self) -> Value {
        if let Ok(path) = env::var("OPENFDD_BENCH_TOPOLOGY_FILE") {
            if let Ok(text) = std::fs::read_to_string(&path) {
                return serde_json::from_str(&text).unwrap_or_else(
                    |e| json!({"ok": false, "error": format!("invalid topology JSON: {e}")}),
                );
            }
        }
        json!({
            "ok": true,
            "note": "Set OPENFDD_BENCH_TOPOLOGY_FILE to a gitignored JSON file with bench IPs.",
            "doc": "docs/agent/bench-driver-setup-wsl-agent.md",
            "bridge": self.base,
            "commission_default": "http://127.0.0.1:9091"
        })
    }

    pub fn driver_status(&self) -> Value {
        let endpoints = [
            ("/api/health", "GET"),
            ("/api/haystack/status", "GET"),
            ("/api/modbus/commission/status", "GET"),
            ("/api/bacnet/commission/status", "GET"),
            ("/api/json-api/poll/status", "GET"),
        ];
        let mut out = serde_json::Map::new();
        for (path, method) in endpoints {
            let key = path.trim_start_matches("/api/").replace('/', "_");
            let result = if method == "GET" {
                self.get(path)
            } else {
                self.post(path, &json!({}))
            };
            out.insert(
                key,
                result.unwrap_or_else(|e| json!({"ok": false, "error": e})),
            );
        }
        json!({"ok": true, "drivers": out})
    }

    pub fn haystack_read(&self, args: &Value) -> Result<Value, String> {
        let body = if args.get("filter").is_some() {
            json!({ "filter": args["filter"] })
        } else if args.get("ids").is_some() {
            json!({ "ids": args["ids"] })
        } else {
            json!({ "filter": "point and cur" })
        };
        self.post("/api/haystack/read", &body)
    }

    pub fn bacnet_read(&self, args: &Value) -> Result<Value, String> {
        let commission =
            env::var("OPENFDD_COMMISSION_BASE").unwrap_or_else(|_| "http://127.0.0.1:9091".into());
        let point_id = args
            .get("point_id")
            .and_then(|v| v.as_str())
            .ok_or("point_id required")?;
        let url = format!("{}/api/bacnet/read", commission.trim_end_matches('/'));
        let mut req = self.http.post(&url).json(&json!({ "point_id": point_id }));
        if let Some(t) = &self.token {
            req = req.header("Authorization", format!("Bearer {t}"));
        }
        req.send()
            .map_err(|e| e.to_string())?
            .json()
            .map_err(|e| e.to_string())
    }
}
