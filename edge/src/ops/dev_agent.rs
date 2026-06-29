//! Dev-only assistant stub — rule-based replies until Ollama/Codex sidecar ships in production.

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
        "CSV: drop files on the wiresheet, or ask your Cursor MCP agent to upload via \
         openfdd_csv_sessions / openfdd_csv_fusion_preview / openfdd_csv_import_execute."
    } else if path.starts_with("/bacnet") {
        "BACnet: use MCP openfdd_bacnet_whois or commission reads. Field writes need integrator + approved=true."
    } else if path.starts_with("/sql-fdd") {
        "SQL FDD: test rules on the tab, then Save rule → dashboard or Export PDF report."
    } else if path.starts_with("/model") {
        "Model: assignments link BACnet/CSV points to FDD inputs. MCP: openfdd_model_coverage, openfdd_model_sparql."
    } else {
        "Open-FDD dev harness — production will use Ollama/Codex. For now use Cursor MCP (openfdd-mcp sidecar)."
    };

    let reply = if message.is_empty() {
        format!("{hint} What do you want to do on {path}?")
    } else if message.contains("session") || message.contains("ut3") {
        format!(
            "{hint} List sessions: GET /api/csv/import/sessions. Load fusion: \
             /csv?session=<id> or MCP openfdd_csv_fusion_preview."
        )
    } else if message.contains("save") || message.contains("arrow") || message.contains("feather") {
        "Save merged data: MCP openfdd_csv_import_execute (after fusion preview) or Commit on CSV tab when preview looks right.".into()
    } else if message.contains("help") || message.contains("mcp") {
        "MCP tools: openfdd_health, openfdd_stack_status, openfdd_driver_status, CSV fusion tools, Haystack/SPARQL. See mcp/README.md.".into()
    } else {
        format!("{hint} You asked: \"{message}\". Use MCP tools or the active tab APIs; this harness does not call an LLM yet.")
    };

    json!({
        "ok": true,
        "reply": reply,
        "dev_harness": true,
        "context_path": path,
        "note": "Replace with Ollama/Codex in production; Cursor MCP is the full agent today."
    })
}
