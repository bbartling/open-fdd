use crate::bridge::BridgeClient;
use serde_json::{json, Value};
use std::io::{self, BufRead, Write};

const INSTRUCTIONS: &str = include_str!("../INSTRUCTIONS.md");

pub struct Server {
    bridge: BridgeClient,
}

impl Server {
    pub fn new(bridge: BridgeClient) -> Self {
        Self { bridge }
    }

    pub fn run_stdio(&self) -> Result<(), String> {
        let stdin = io::stdin();
        let mut stdout = io::stdout();
        for line in stdin.lock().lines() {
            let line = line.map_err(|e| e.to_string())?;
            if line.trim().is_empty() {
                continue;
            }
            let req: Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
            let id = req.get("id").cloned();
            let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");
            let params = req.get("params").cloned().unwrap_or(json!({}));

            let result = match method {
                "initialize" => Ok(json!({
                    "protocolVersion": "2024-11-05",
                    "capabilities": { "tools": {} },
                    "serverInfo": {
                        "name": "openfdd-mcp",
                        "version": env!("CARGO_PKG_VERSION")
                    },
                    "instructions": INSTRUCTIONS
                })),
                "notifications/initialized" | "initialized" => Ok(json!({})),
                "tools/list" => Ok(json!({ "tools": self.tools_list() })),
                "tools/call" => self.tools_call(&params),
                "ping" => Ok(json!({})),
                _ => Err(format!("unknown method: {method}")),
            };

            let resp = match result {
                Ok(value) => json!({ "jsonrpc": "2.0", "id": id, "result": value }),
                Err(e) => json!({
                    "jsonrpc": "2.0",
                    "id": id,
                    "error": { "code": -32000, "message": e }
                }),
            };
            writeln!(stdout, "{}", resp).map_err(|e| e.to_string())?;
            stdout.flush().map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    fn tools_list(&self) -> Vec<Value> {
        let mut tools = vec![
            tool("openfdd_bench_topology", "Bench NIC, API bases, driver endpoints (from OPENFDD_BENCH_TOPOLOGY_FILE or doc pointer)", json!({})),
            tool("openfdd_driver_status", "Poll bridge driver status endpoints", json!({})),
            tool("openfdd_health", "GET /api/health (public liveness)", json!({})),
            tool("openfdd_stack_status", "GET /api/health/stack — data plane strip (JWT)", json!({})),
            tool("openfdd_haystack_status", "GET /api/haystack/status", json!({})),
            tool("openfdd_haystack_test", "POST /api/haystack/test", json!({})),
            tool("openfdd_haystack_read", "POST /api/haystack/read", json!({"filter": {"type": "string"}})),
            tool("openfdd_bacnet_whois", "POST /api/bacnet/whois — BACnet discovery", json!({})),
            tool("openfdd_bacnet_read", "BACnet read via commission API", json!({"point_id": {"type": "string"}})),
            tool("openfdd_validation_run_status", "GET /api/historian/validation/status", json!({})),
            tool("openfdd_reports_list", "GET /api/reports — generated report index", json!({})),
            tool("openfdd_site_update_dry_run", "Site update checklist (no writes) — run scripts/openfdd_rust_site_update.sh with DRY_RUN on bench", json!({})),
            tool("openfdd_ghcr_manifest_check", "Compare running image_tag from /api/health with expected OPENFDD_IMAGE_TAG", json!({"expected_tag": {"type": "string"}})),
            tool("openfdd_model_sparql_catalog", "GET /api/model/sparql/predefined — Haystack RDF query catalog", json!({})),
            tool("openfdd_model_sparql", "POST /api/model/sparql — read-only SELECT over Haystack RDF", json!({"query": {"type": "string"}})),
            tool("openfdd_model_sites", "GET /api/model/sites", json!({})),
            tool("openfdd_model_coverage", "GET /api/dashboard/model-coverage", json!({})),
            tool("openfdd_csv_fusion_preview", "GET /api/csv/import/sessions/{id}/fusion-preview — merged CSV grid for browser review", json!({"session_id": {"type": "string"}, "limit": {"type": "integer"}})),
            tool("openfdd_csv_latest_planned", "GET /api/csv/import/sessions/latest/planned — most recent UT3 plan ready for fusion preview", json!({})),
            tool("openfdd_csv_sessions", "GET /api/csv/import/sessions — list recent import sessions", json!({"limit": {"type": "integer"}})),
            tool("openfdd_csv_import_execute", "POST /api/csv/import/execute — save planned session to Arrow + historian (human confirms after preview)", json!({"session_id": {"type": "string"}})),
            tool("openfdd_datasets", "GET /api/datasets — list Feather/Arrow datasets in registry", json!({})),
            tool("openfdd_timeseries_series", "GET /api/timeseries/series — plot catalog after CSV save", json!({"site_id": {"type": "string"}})),
        ];
        // Bench profile short aliases (same handlers as openfdd_* tools).
        for (alias, target) in [
            ("site_health", "openfdd_health"),
            ("stack_status", "openfdd_stack_status"),
            ("haystack_test", "openfdd_haystack_test"),
            ("driver_poll_status", "openfdd_driver_status"),
            ("bacnet_whois", "openfdd_bacnet_whois"),
            ("validation_run_status", "openfdd_validation_run_status"),
            ("report_list", "openfdd_reports_list"),
        ] {
            tools.push(tool(alias, &format!("Alias for {target}"), json!({})));
        }
        tools
    }

    fn dispatch_tool(&self, name: &str, args: &Value) -> Result<Value, String> {
        let canonical = match name {
            "site_health" => "openfdd_health",
            "stack_status" => "openfdd_stack_status",
            "haystack_test" => "openfdd_haystack_test",
            "driver_poll_status" => "openfdd_driver_status",
            "bacnet_whois" => "openfdd_bacnet_whois",
            "validation_run_status" => "openfdd_validation_run_status",
            "report_list" => "openfdd_reports_list",
            other => other,
        };
        match canonical {
            "openfdd_bench_topology" => Ok(self.bridge.bench_topology()),
            "openfdd_driver_status" => Ok(self.bridge.driver_status()),
            "openfdd_health" => self.bridge.get("/api/health"),
            "openfdd_stack_status" => self.bridge.get("/api/health/stack"),
            "openfdd_haystack_status" => self.bridge.get("/api/haystack/status"),
            "openfdd_haystack_test" => self.bridge.post("/api/haystack/test", &json!({})),
            "openfdd_haystack_read" => self.bridge.haystack_read(args),
            "openfdd_bacnet_whois" => self.bridge.post("/api/bacnet/whois", &json!({})),
            "openfdd_bacnet_read" => self.bridge.bacnet_read(args),
            "openfdd_validation_run_status" => self.bridge.get("/api/historian/validation/status"),
            "openfdd_reports_list" => self.bridge.get("/api/reports"),
            "openfdd_site_update_dry_run" => Ok(self.bridge.site_update_dry_run()),
            "openfdd_ghcr_manifest_check" => self.bridge.ghcr_manifest_check(args),
            "openfdd_model_sparql_catalog" => self.bridge.get("/api/model/sparql/predefined"),
            "openfdd_model_sparql" => {
                let query = args
                    .get("query")
                    .and_then(|v| v.as_str())
                    .ok_or("query required")?;
                self.bridge
                    .post("/api/model/sparql", &json!({ "query": query }))
            }
            "openfdd_model_sites" => self.bridge.get("/api/model/sites"),
            "openfdd_model_coverage" => self.bridge.get("/api/dashboard/model-coverage"),
            "openfdd_csv_fusion_preview" => {
                let session_id = args
                    .get("session_id")
                    .and_then(|v| v.as_str())
                    .ok_or("session_id required")?;
                let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(2000);
                self.bridge.get(&format!(
                    "/api/csv/import/sessions/{session_id}/fusion-preview?limit={limit}"
                ))
            }
            "openfdd_csv_latest_planned" => {
                self.bridge.get("/api/csv/import/sessions/latest/planned")
            }
            "openfdd_csv_sessions" => {
                let limit = args.get("limit").and_then(|v| v.as_u64()).unwrap_or(20);
                self.bridge
                    .get(&format!("/api/csv/import/sessions?limit={limit}"))
            }
            "openfdd_csv_import_execute" => {
                let session_id = args
                    .get("session_id")
                    .and_then(|v| v.as_str())
                    .ok_or("session_id required")?;
                self.bridge.post(
                    "/api/csv/import/execute",
                    &json!({ "session_id": session_id, "confirm": true }),
                )
            }
            "openfdd_datasets" => self.bridge.get("/api/datasets"),
            "openfdd_timeseries_series" => {
                let site = args.get("site_id").and_then(|v| v.as_str()).unwrap_or("");
                if site.is_empty() {
                    self.bridge.get("/api/timeseries/series")
                } else {
                    self.bridge
                        .get(&format!("/api/timeseries/series?site_id={site}"))
                }
            }
            other => Err(format!("unknown tool: {other}")),
        }
    }

    fn tools_call(&self, params: &Value) -> Result<Value, String> {
        let name = params
            .get("name")
            .and_then(|n| n.as_str())
            .ok_or("missing tool name")?;
        let args = params.get("arguments").cloned().unwrap_or(json!({}));

        let payload = self.dispatch_tool(name, &args)?;

        Ok(json!({
            "content": [{ "type": "text", "text": serde_json::to_string_pretty(&payload).unwrap_or_else(|_| payload.to_string()) }],
            "isError": payload.get("ok").and_then(|v| v.as_bool()) == Some(false)
        }))
    }
}

fn tool(name: &str, description: &str, schema: Value) -> Value {
    json!({
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": schema.as_object().cloned().unwrap_or_default(),
            "additionalProperties": false
        }
    })
}
