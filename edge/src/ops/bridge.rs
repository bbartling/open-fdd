//! openfdd-bridge facade: API, dashboard, historian.

pub fn status_json() -> &'static str {
    r#"{"ok":true,"service":"openfdd-bridge","role":"API + dashboard + historian","auth":"jwt","dashboard":"served_by_rust","historian":"arrow-shaped rows","fdd":"datafusion_sql_only"}"#
}

pub fn ui_tabs_json() -> &'static str {
    r#"{
      "ok":true,
      "tabs":[
        {"id":"building","label":"Building Dashboard","ported":true,"rust_route":"/api/building/checkin"},
        {"id":"bridge","label":"Bridge API","ported":true,"rust_route":"/api/bridge/status"},
        {"id":"commission","label":"BACnet Commission","ported":true,"rust_route":"/api/bacnet/commission/status"},
        {"id":"poll","label":"BACnet Poll","ported":true,"rust_route":"/api/bacnet/poll/status"},
        {"id":"haystack","label":"Haystack Model","ported":true,"replaces":"Niagara","rust_route":"/api/haystack/read"},
        {"id":"modbus","label":"Modbus","ported":true,"rust_route":"/api/modbus/points"},
        {"id":"json","label":"JSON API","ported":true,"rust_route":"/api/json-api/sources"},
        {"id":"rulelab","label":"Rule Lab","ported":true,"rust_route":"/api/rules/save"},
        {"id":"fdd","label":"DataFusion FDD","ported":true,"rust_route":"/api/fdd/run"},
        {"id":"algorithms","label":"CDL Algorithms","ported":true,"rust_route":"/api/control/cdl/status"},
        {"id":"reports","label":"RCx Reports","ported":true,"rust_route":"/api/reports/rcx/generate"},
        {"id":"agent","label":"AI Agent API","ported":true,"rust_route":"/api/agent/tools"},
        {"id":"ops","label":"Ops / Stack","ported":true,"rust_route":"/api/health/stack"}
      ],
      "removed_or_deferred":[
        {"id":"mcp-rag","reason":"MCP later per project direction"},
        {"id":"ollama","reason":"local LLM panel deferred; agent API remains JSON/JWT"},
        {"id":"niagara-websocket","reason":"converted to Haystack gateway"}
      ],
      "forbidden":["python","pyarrow","pandas","brick-rdflib-ui"]
    }"#
}
