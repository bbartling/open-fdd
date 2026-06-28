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
        vec![
            tool("openfdd_bench_topology", "Bench NIC, API bases, driver endpoints (from OPENFDD_BENCH_TOPOLOGY_FILE or doc pointer)", json!({})),
            tool("openfdd_driver_status", "Poll bridge driver status endpoints", json!({})),
            tool("openfdd_health", "GET /api/health", json!({})),
            tool("openfdd_haystack_status", "GET /api/haystack/status", json!({})),
            tool("openfdd_haystack_test", "POST /api/haystack/test", json!({})),
            tool("openfdd_haystack_read", "POST /api/haystack/read", json!({"filter": {"type": "string"}})),
            tool("openfdd_bacnet_read", "BACnet read via commission API", json!({"point_id": {"type": "string"}})),
        ]
    }

    fn tools_call(&self, params: &Value) -> Result<Value, String> {
        let name = params
            .get("name")
            .and_then(|n| n.as_str())
            .ok_or("missing tool name")?;
        let args = params.get("arguments").cloned().unwrap_or(json!({}));

        let payload = match name {
            "openfdd_bench_topology" => self.bridge.bench_topology(),
            "openfdd_driver_status" => self.bridge.driver_status(),
            "openfdd_health" => self.bridge.get("/api/health")?,
            "openfdd_haystack_status" => self.bridge.get("/api/haystack/status")?,
            "openfdd_haystack_test" => self.bridge.post("/api/haystack/test", &json!({}))?,
            "openfdd_haystack_read" => self.bridge.haystack_read(&args)?,
            "openfdd_bacnet_read" => self.bridge.bacnet_read(&args)?,
            other => return Err(format!("unknown tool: {other}")),
        };

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
