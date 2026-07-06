//! Deterministic operator hints for external-agent workflows (no LLM).

use serde_json::{json, Value};

pub fn dev_harness_reply(body: &Value) -> Value {
    let message = body
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim()
        .to_lowercase();
    let path = body
        .get("context_path")
        .and_then(|v| v.as_str())
        .unwrap_or("/");

    let hint = if path.starts_with("/csv") {
        "CSV batch import: MCP openfdd_csv_import_preflight / openfdd_csv_import_execute, or host scripts — see docs/drivers/csv-batch.html."
    } else if path.starts_with("/bacnet") {
        "BACnet: MCP openfdd_bacnet_whois or commission reads. Field writes need integrator + approved=true."
    } else if path.starts_with("/sql-fdd") {
        "SQL FDD: test rules on the tab, then Save rule → dashboard or Export PDF report."
    } else if path.starts_with("/model") {
        "Model: assignments link BACnet/CSV points to FDD inputs. MCP: openfdd_model_coverage, openfdd_model_sparql."
    } else {
        "Open-FDD edge — connect an external agent via openfdd-mcp (stdio) or JWT REST /api/agent/tools."
    };

    let reply = if message.is_empty() {
        format!("{hint} What do you want to do on {path}?")
    } else if message.contains("session") || message.contains("ut3") {
        format!(
            "{hint} List sessions: GET /api/csv/import/sessions. Preflight: MCP openfdd_csv_import_preflight."
        )
    } else if message.contains("save") || message.contains("arrow") || message.contains("feather") {
        "Persist CSV: MCP openfdd_csv_import_execute after preflight pass.".into()
    } else if message.contains("help") || message.contains("mcp") {
        "MCP tools: openfdd_health, openfdd_stack_status, openfdd_driver_status, openfdd_csv_*, Haystack/SPARQL. See mcp/README.md.".into()
    } else {
        format!("{hint} You asked: \"{message}\". Use MCP tools or the active tab APIs.")
    };

    json!({
        "ok": true,
        "reply": reply,
        "dev_harness": true,
        "context_path": path,
        "note": "Open-FDD does not ship an embedded chatbot — use external MCP hosts."
    })
}
