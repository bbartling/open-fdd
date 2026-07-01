//! External-agent integration metadata — MCP + REST; no embedded chatbot.

use crate::validation::profile::workspace_dir;
use serde_json::{json, Value};

pub fn config_json() -> Value {
    let ws = workspace_dir();
    json!({
        "ok": true,
        "embedded_chat": false,
        "external_agent_workflow": true,
        "mcp_binary": "openfdd-mcp",
        "tools_endpoint": "/api/agent/tools",
        "manifest_endpoint": "/api/agent/manifest",
        "mcp_docs": "mcp/README.md",
        "example_hosts": [
            "Codex CLI",
            "Cursor",
            "Claude Desktop",
            "OpenClaw",
            "Any MCP-compatible host"
        ],
        "credentials_hint": {
            "bootstrap_handoff": ws.join("bootstrap_credentials.once.txt").display().to_string(),
            "auth_env_local": ws.join("auth.env.local").display().to_string(),
            "preferred_mcp_role": "integrator",
            "write_tools_role": "agent",
            "mcp_tools": ["openfdd_auth_credentials_hint", "openfdd_auth_login"],
            "shell": "scripts/openfdd_auth_lib.sh → openfdd_auth_login_token",
            "note": "Passwords live in bootstrap_credentials.once.txt (one-time) or OPENFDD_*_PASSWORD env — bcrypt hashes in auth.env.local are NOT login passwords"
        },
        "workflow": [
            "Start Open-FDD edge on LAN/VPN",
            "Obtain integrator or agent JWT",
            "Run openfdd-mcp outside the web UI (stdio)",
            "Connect external agent to MCP or REST",
            "Read tools first; writes need OPENFDD_MCP_ALLOW_WRITES=1 and confirm:true",
            "Never print secrets; BACnet writes need explicit human approval"
        ]
    })
}
