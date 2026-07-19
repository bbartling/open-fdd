use crate::bridge::BridgeClient;
use crate::gate::require_write_confirm;
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
            tool("openfdd_capabilities", "GET /api/capabilities — central feature contract", json!({})),
            tool("openfdd_stack_status", "GET /api/health/stack — data plane strip (JWT)", json!({})),
            tool("openfdd_faults_status", "GET /api/faults/status — live fault subsystem status", json!({})),
            tool("openfdd_export_meta", "GET /api/export/meta — available export contract", json!({})),
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
            tool("openfdd_csv_import_preview", "POST /api/csv/import/preview — stage CSVs from host path or base64; optional session_id to append", json!({
                "session_id": {"type": "string", "description": "Existing session to append files into"},
                "files": {"type": "array", "description": "Array of {filename, path} or {filename, content_base64}"}
            })),
            tool("openfdd_csv_import_plan", "POST /api/csv/import/plan — append/join plan + validation preview", json!({
                "session_id": {"type": "string"},
                "plan": {"type": "object", "description": "ImportPlan: mode, files, join_alignment, fill_policy, output_dataset_name"}
            })),
            tool("openfdd_ingest_contract", "GET /api/ingest/contract — machine-readable ingest mold (historian_wide_csv, commissioning, import_plan)", json!({})),
            tool("openfdd_csv_import_preflight", "POST /api/csv/import/preflight — strict validation gate; must verdict pass before execute", json!({
                "session_id": {"type": "string"},
                "plan": {"type": "object", "description": "Optional re-plan before validation"}
            })),
            tool("openfdd_csv_workbench_quality", "POST /api/csv-workbench/quality — CSV quality analysis", json!({
                "source_id": {"type": "string"}
            })),
            tool("openfdd_model_commissioning_export", "GET /api/model/commissioning-export — sites/equipment/points/assignments/fdd_rules bundle", json!({})),
            tool("openfdd_model_commissioning_import", "POST /api/model/commissioning-import — fail-closed commissioning bundle (write: confirm + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "payload": {"type": "object"}
            })),
            tool("openfdd_rules_batch", "POST /api/rules/batch — run all active saved FDD SQL rules (write: confirm + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"}
            })),
            tool("openfdd_fdd_rules_save", "POST /api/fdd-rules — save SQL fault rule (write: confirm + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "rule_id": {"type": "string"},
                "name": {"type": "string"},
                "sql": {"type": "string"}
            })),
            tool("openfdd_fdd_rules_activate", "POST /api/fdd-rules/{id}/activate — activate saved rule (write: confirm + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "rule_id": {"type": "string"}
            })),
            tool("openfdd_reports_from_fdd_sql_run", "POST /api/reports/from-fdd-sql-run — PDF report from SQL FDD test run (write: confirm + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "rule_name": {"type": "string"},
                "sql": {"type": "string"},
                "run_result": {"type": "object"}
            })),
            tool("openfdd_integration_smoke", "Agent playbook smoke: health + contract + optional CSV preflight/execute + commissioning/FDD/report writes", json!({
                "import_dir": {"type": "string", "description": "Host path to folder of CSVs for preview"},
                "session_id": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Enable write steps (execute, commissioning, batch, report)"},
                "commissioning": {"type": "object"},
                "run_fdd": {"type": "boolean"},
                "run_report": {"type": "boolean"},
                "report": {"type": "object"}
            })),
            tool("openfdd_historian_query", "GET/POST /api/historian/query — historian pivot rows (optional limit, site_id, equipment_id)", json!({
                "limit": {"type": "integer"},
                "site_id": {"type": "string"},
                "equipment_id": {"type": "string"}
            })),
            tool("openfdd_fdd_rules_list", "GET /api/fdd-rules — list wire/SQL fault rules", json!({})),
            tool("openfdd_fdd_registry", "GET /api/fdd/rules — production DataFusion registry", json!({})),
            tool("openfdd_fdd_equipment", "GET /api/fdd/equipment — loaded equipment IDs and types", json!({})),
            tool("openfdd_fdd_results", "GET /api/fdd/results — latest per-equipment rule outcomes", json!({})),
            tool("openfdd_fdd_series", "GET /api/fdd/series — mapped live display series (max 5000 points)", json!({
                "equipment_id": {"type": "string"},
                "rule_id": {"type": "string"}
            })),
            tool("openfdd_fdd_session_config", "GET /api/fdd/session-config — active units, role map, and typed tuning", json!({})),
            tool("openfdd_fdd_accuracy_snapshot", "Cross-check registry/equipment/result counts against central truth without inventing defaults", json!({})),
            tool("openfdd_fdd_rule_test_sql", "POST /api/fdd-rules/{id}/test-sql — dry-run rule SQL on sample/historian data", json!({
                "rule_id": {"type": "string"},
                "sql": {"type": "string"},
                "params": {"type": "object"},
                "confirmation_seconds": {"type": "integer"}
            })),
            tool("openfdd_fdd_run", "POST /api/fdd/run — execute production registry rules with typed params (write gate)", json!({
                "confirm": {"type": "boolean", "description": "Must be true"},
                "rule_ids": {"type": "array", "items": {"type": "string"}},
                "equipment_id": {"type": "string"},
                "params": {"type": "object", "description": "rule_id → typed parameter overrides"}
            })),
            tool("openfdd_model_assignments_save", "POST /api/model/assignments/save — persist Haystack assignments (write: confirm:true + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "points": {"type": "array"},
                "fault_equation_bindings": {"type": "array"},
                "assignments": {"type": "object", "description": "Alternative wrapper for full assignments doc"}
            })),
            tool("openfdd_reports_draft", "POST /api/reports/draft — create report draft (write: confirm:true + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "title": {"type": "string"},
                "template_id": {"type": "string"},
                "include_branding": {"type": "boolean"}
            })),
            tool("openfdd_reports_patch", "PATCH /api/reports/{id} — update title/sections (write: confirm:true + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "report_id": {"type": "string"},
                "title": {"type": "string"},
                "sections": {"type": "array"}
            })),
            tool("openfdd_reports_render_pdf", "POST /api/reports/{id}/render/pdf — render PDF bundle (write: confirm:true + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "confirm": {"type": "boolean"},
                "report_id": {"type": "string"}
            })),
            tool("openfdd_csv_fusion_preview", "GET /api/csv/import/sessions/{id}/fusion-preview — merged CSV grid for browser review", json!({"session_id": {"type": "string"}, "limit": {"type": "integer"}})),
            tool("openfdd_csv_latest_planned", "GET /api/csv/import/sessions/latest/planned — most recent UT3 plan ready for fusion preview", json!({})),
            tool("openfdd_csv_sessions", "GET /api/csv/import/sessions — list recent import sessions", json!({"limit": {"type": "integer"}})),
            tool("openfdd_csv_import_execute", "POST /api/csv/import/execute — save planned session to Arrow + historian (write: confirm:true + OPENFDD_MCP_ALLOW_WRITES=1)", json!({
                "session_id": {"type": "string"},
                "confirm": {"type": "boolean", "description": "Must be true"}
            })),
            tool("openfdd_datasets", "GET /api/datasets — list Feather/Arrow datasets in registry", json!({})),
            tool("openfdd_timeseries_series", "GET /api/timeseries/series — plot catalog after CSV save", json!({"site_id": {"type": "string"}})),
            tool("openfdd_auth_credentials_hint", "Where MCP/agents find Open-FDD login (workspace/bootstrap_credentials.once.txt, auth.env.local) — no secrets returned", json!({})),
            tool("openfdd_auth_login", "Login as integrator/agent/operator/admin — returns JWT from handoff/env (password never echoed)", json!({
                "role": {"type": "string", "description": "integrator (default), agent, operator, admin"}
            })),
            tool("openfdd_fdd_wires_propose", "POST /api/fdd-wires/propose-assignments — AI map driver points → FDD inputs → rules; syncs wiresheet graph", json!({
                "site_id": {"type": "string"},
                "equipment_type": {"type": "string", "description": "e.g. ahu"}
            })),
            tool("openfdd_fdd_wires_sync", "POST /api/fdd-wires/sync-from-assignments — rebuild FDD wiresheet from saved model assignments", json!({
                "site_id": {"type": "string"},
                "graph_id": {"type": "string", "description": "default graph:live-fdd-validation"}
            })),
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
            "openfdd_capabilities" => self.bridge.get("/api/capabilities"),
            "openfdd_stack_status" => self.bridge.get("/api/health/stack"),
            "openfdd_faults_status" => self.bridge.get("/api/faults/status"),
            "openfdd_export_meta" => self.bridge.get("/api/export/meta"),
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
            "openfdd_csv_import_preview" => self.bridge.csv_import_preview(args),
            "openfdd_csv_import_plan" => self.bridge.csv_import_plan(args),
            "openfdd_ingest_contract" => self.bridge.ingest_contract(),
            "openfdd_csv_import_preflight" => self.bridge.csv_import_preflight(args),
            "openfdd_csv_workbench_quality" => self.bridge.csv_workbench_quality(args),
            "openfdd_model_commissioning_export" => self.bridge.commissioning_export(),
            "openfdd_model_commissioning_import" => {
                require_write_confirm(args, "openfdd_model_commissioning_import")?;
                self.bridge.commissioning_import(args)
            }
            "openfdd_rules_batch" => {
                require_write_confirm(args, "openfdd_rules_batch")?;
                self.bridge.rules_batch()
            }
            "openfdd_fdd_rules_save" => {
                require_write_confirm(args, "openfdd_fdd_rules_save")?;
                let mut body = args.clone();
                if let Some(obj) = body.as_object_mut() {
                    obj.remove("confirm");
                }
                self.bridge.fdd_rules_save(&body)
            }
            "openfdd_fdd_rules_activate" => {
                require_write_confirm(args, "openfdd_fdd_rules_activate")?;
                let rule_id = args
                    .get("rule_id")
                    .and_then(|v| v.as_str())
                    .ok_or("rule_id required")?;
                self.bridge.fdd_rules_activate(rule_id)
            }
            "openfdd_reports_from_fdd_sql_run" => {
                require_write_confirm(args, "openfdd_reports_from_fdd_sql_run")?;
                let mut body = args.clone();
                if let Some(obj) = body.as_object_mut() {
                    obj.remove("confirm");
                }
                self.bridge.reports_from_fdd_sql_run(&body)
            }
            "openfdd_integration_smoke" => {
                if args.get("confirm").and_then(|v| v.as_bool()) == Some(true) {
                    require_write_confirm(args, "openfdd_integration_smoke")?;
                }
                self.bridge.integration_smoke(args)
            }
            "openfdd_historian_query" => self.bridge.historian_query(args),
            "openfdd_fdd_rules_list" => self.bridge.fdd_rules_list(),
            "openfdd_fdd_registry" => self.bridge.get("/api/fdd/rules"),
            "openfdd_fdd_equipment" => self.bridge.get("/api/fdd/equipment"),
            "openfdd_fdd_results" => self.bridge.get("/api/fdd/results"),
            "openfdd_fdd_series" => {
                let equipment_id = args
                    .get("equipment_id")
                    .and_then(Value::as_str)
                    .ok_or("equipment_id required")?;
                let rule_id = args
                    .get("rule_id")
                    .and_then(Value::as_str)
                    .ok_or("rule_id required")?;
                self.bridge.fdd_series(equipment_id, rule_id)
            }
            "openfdd_fdd_session_config" => self.bridge.get("/api/fdd/session-config"),
            "openfdd_fdd_accuracy_snapshot" => self.bridge.fdd_accuracy_snapshot(),
            "openfdd_fdd_rule_test_sql" => self.bridge.fdd_rule_test_sql(args),
            "openfdd_fdd_run" => {
                require_write_confirm(args, "openfdd_fdd_run")?;
                self.bridge.fdd_run(args)
            }
            "openfdd_model_assignments_save" => {
                require_write_confirm(args, "openfdd_model_assignments_save")?;
                self.bridge.model_assignments_save(args)
            }
            "openfdd_reports_draft" => {
                require_write_confirm(args, "openfdd_reports_draft")?;
                self.bridge.reports_draft(args)
            }
            "openfdd_reports_patch" => {
                require_write_confirm(args, "openfdd_reports_patch")?;
                self.bridge.reports_patch(args)
            }
            "openfdd_reports_render_pdf" => {
                require_write_confirm(args, "openfdd_reports_render_pdf")?;
                self.bridge.reports_render_pdf(args)
            }
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
                require_write_confirm(args, "openfdd_csv_import_execute")?;
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
            "openfdd_auth_credentials_hint" => Ok(crate::auth::credentials_hint()),
            "openfdd_auth_login" => {
                let role = args.get("role").and_then(|v| v.as_str()).unwrap_or("integrator");
                let base = std::env::var("OPENFDD_API_BASE")
                    .unwrap_or_else(|_| "http://127.0.0.1:8080".into());
                crate::auth::login_role(role, &base)
            }
            "openfdd_fdd_wires_propose" => self.bridge.post(
                "/api/fdd-wires/propose-assignments",
                &json!({
                    "site_id": args.get("site_id"),
                    "equipment_type": args.get("equipment_type").cloned().unwrap_or(json!("ahu"))
                }),
            ),
            "openfdd_fdd_wires_sync" => self.bridge.post(
                "/api/fdd-wires/sync-from-assignments",
                &json!({
                    "site_id": args.get("site_id"),
                    "graph_id": args.get("graph_id").cloned().unwrap_or(json!("graph:live-fdd-validation"))
                }),
            ),
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lists_production_fdd_accuracy_tools() {
        let server = Server::new(BridgeClient::from_env());
        let tools = server.tools_list();
        let names: Vec<&str> = tools
            .iter()
            .filter_map(|tool| tool.get("name").and_then(Value::as_str))
            .collect();
        for expected in [
            "openfdd_capabilities",
            "openfdd_fdd_registry",
            "openfdd_fdd_equipment",
            "openfdd_fdd_results",
            "openfdd_fdd_series",
            "openfdd_fdd_session_config",
            "openfdd_fdd_accuracy_snapshot",
        ] {
            assert!(names.contains(&expected), "missing MCP tool {expected}");
        }
    }
}
