//! In-app operator chat — Ollama when available, tool-augmented fallback otherwise.

use crate::csv_ingest;
use crate::dashboard;
use crate::faults;
use crate::model::query;
use serde_json::{json, Value};

use super::codex_relay;
use super::cursor_relay;
use super::ollama;

pub fn config_json() -> Value {
    let ollama_status = ollama::probe_status();
    let cursor_status = cursor_relay::status_json();
    let cursor_ok = cursor_relay::probe_quick().is_some();
    let codex_status = codex_relay::status_json();
    let codex_ok = codex_relay::probe_quick().is_some();
    let mut sources = vec!["tools"];
    if codex_ok {
        sources.insert(0, "codex");
    }
    if cursor_ok {
        sources.push("cursor");
    }
    sources.push("ollama");
    let ws = crate::validation::profile::workspace_dir();
    json!({
        "ok": true,
        "codex": codex_status,
        "codex_chat_enabled": codex_ok,
        "cursor": cursor_status,
        "cursor_chat_enabled": cursor_ok,
        "ollama": ollama_status,
        "chat_endpoint": "/api/agent/chat",
        "sources": sources,
        "agent_providers": {
            "in_app_priority": sources,
            "external_mcp_hosts": ["Cursor", "Claude Desktop", "Codex CLI", "OpenClaw", "VS Code Copilot"],
            "local_llm": "Ollama — llama3.2, Hermes, Mistral, or any model in workspace/ollama.env.local"
        },
        "credentials_hint": {
            "bootstrap_handoff": ws.join("bootstrap_credentials.once.txt").display().to_string(),
            "auth_env_local": ws.join("auth.env.local").display().to_string(),
            "preferred_mcp_role": "integrator",
            "write_tools_role": "agent",
            "mcp_tools": ["openfdd_auth_credentials_hint", "openfdd_auth_login"],
            "shell": "scripts/openfdd_auth_lib.sh → openfdd_auth_login_token",
            "note": "Passwords live in bootstrap_credentials.once.txt (one-time) or OPENFDD_*_PASSWORD env — bcrypt hashes in auth.env.local are NOT login passwords"
        }
    })
}

pub fn chat_reply(body: &Value) -> Value {
    let message = body
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let path = body
        .get("context_path")
        .and_then(|v| v.as_str())
        .unwrap_or("/");
    let model = body.get("model").and_then(|v| v.as_str());

    if message.is_empty() {
        return json!({"ok": false, "error": "message required"});
    }

    let snapshot = gather_live_context(path, message);
    let history = parse_history(body.get("history"));

    let chat_body = json!({
        "message": message,
        "context_path": path,
        "history": history,
        "live": snapshot.get("live")
    });

    if let Ok(codex) = codex_relay::chat(&chat_body) {
        if codex.get("ok").and_then(|v| v.as_bool()) == Some(true) {
            return json!({
                "ok": true,
                "reply": codex.get("reply").cloned().unwrap_or(json!("")),
                "thinking": "",
                "source": "codex",
                "ollama_ok": false,
                "context_path": path,
                "tools_used": snapshot.get("tools_used"),
                "duration_ms": codex.get("duration_ms").cloned().unwrap_or(Value::Null),
                "agent": codex.get("agent").cloned().unwrap_or(Value::Null)
            });
        }
    }

    if let Ok(cursor) = cursor_relay::chat(&chat_body) {
        if cursor.get("ok").and_then(|v| v.as_bool()) == Some(true) {
            return json!({
                "ok": true,
                "reply": cursor.get("reply").cloned().unwrap_or(json!("")),
                "thinking": "",
                "source": "cursor",
                "ollama_ok": false,
                "context_path": path,
                "tools_used": snapshot.get("tools_used"),
                "duration_ms": cursor.get("duration_ms").cloned().unwrap_or(Value::Null),
                "agent_id": cursor.get("agent_id").cloned().unwrap_or(Value::Null)
            });
        }
    }

    if let Some(base) = ollama::probe_quick() {
        if let Ok(llm) = try_ollama_reply_at(&base, path, message, &snapshot, &history, model) {
            return json!({
                "ok": true,
                "reply": llm.content,
                "thinking": llm.thinking,
                "source": "ollama",
                "ollama_ok": true,
                "context_path": path,
                "tools_used": snapshot.get("tools_used"),
                "duration_ms": llm.duration_ms,
                "eval_count": llm.eval_count
            });
        }
    }

    let cfg = ollama::load_config();
    let reply = tools_reply(path, message, &snapshot);
    json!({
        "ok": true,
        "reply": reply,
        "thinking": "",
        "source": "tools",
        "ollama_ok": false,
        "ollama_error": format!("Ollama unreachable at {}", cfg.base_url),
        "context_path": path,
        "tools_used": snapshot.get("tools_used"),
        "note": "Start Codex relay: ./scripts/openfdd_codex_chat_relay.sh (after codex login)"
    })
}

pub fn cancel_reply() -> Value {
    let codex = codex_relay::cancel_active();
    json!({
        "ok": true,
        "codex": codex,
        "note": "In-flight chat may return an error after cancel"
    })
}

pub fn reset_reply() -> Value {
    let codex_cancel = codex_relay::cancel_active();
    let codex_reset = codex_relay::reset_session();
    json!({
        "ok": true,
        "codex_cancel": codex_cancel,
        "codex_reset": codex_reset,
        "note": "Codex session cleared; next chat starts fresh. Clear browser chat separately if needed."
    })
}

fn parse_history(raw: Option<&Value>) -> Vec<Value> {
    let Some(arr) = raw.and_then(|v| v.as_array()) else {
        return Vec::new();
    };
    arr.iter()
        .filter_map(|turn| {
            let role = turn.get("role").and_then(|v| v.as_str())?;
            let content = turn.get("content").and_then(|v| v.as_str())?.trim();
            if content.is_empty() || content == "…" {
                return None;
            }
            Some(json!({"role": role, "content": content}))
        })
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .take(12)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect()
}

fn gather_live_context(path: &str, message: &str) -> Value {
    let lower = message.to_lowercase();
    let mut tools: Vec<&str> = Vec::new();
    let mut data = json!({});

    let want_stack = path.contains("host")
        || lower.contains("health")
        || lower.contains("stack")
        || lower.contains("status");
    if want_stack {
        tools.push("stack_health");
        data["stack"] = dashboard::stack_health();
    }

    let want_faults = path.contains("fault") || lower.contains("fault") || lower.contains("fdd");
    if want_faults {
        tools.push("faults_status");
        data["faults"] = faults::status_json();
    }

    let want_csv = path.starts_with("/csv") || lower.contains("csv") || lower.contains("session");
    if want_csv {
        tools.push("csv_sessions");
        data["csv_sessions"] = csv_ingest::list_sessions_handler(8);
        tools.push("datasets");
        data["datasets"] = csv_ingest::dataset::list_datasets();
    }

    let want_model = path.contains("model")
        || lower.contains("model")
        || lower.contains("coverage")
        || lower.contains("sparql")
        || lower.contains("assign");
    if want_model {
        tools.push("model_coverage");
        data["model_coverage"] = query::model_coverage();
    }

    if tools.is_empty() {
        tools.push("stack_health");
        data["stack"] = dashboard::stack_health();
    }

    json!({
        "tab": path,
        "tools_used": tools,
        "live": data
    })
}

fn system_prompt(path: &str, snapshot: &Value) -> String {
    format!(
        "You are the Open-FDD bench operator assistant. Tab context: {path}. \
         Answer using the live JSON snapshot when relevant. Be concise and actionable. \
         Never suggest unsupervised BACnet/Modbus/Haystack writes — integrator approval required. \
         For CSV merges prefer append on Date for school kW files; join weather on time_local. \
         Live snapshot:\n{}",
        serde_json::to_string_pretty(snapshot.get("live").unwrap_or(&Value::Null))
            .unwrap_or_else(|_| "{}".into())
    )
}

fn try_ollama_reply_at(
    base: &str,
    path: &str,
    message: &str,
    snapshot: &Value,
    history: &[Value],
    model: Option<&str>,
) -> Result<ollama::ChatResult, String> {
    let mut messages = vec![json!({
        "role": "system",
        "content": system_prompt(path, snapshot)
    })];
    messages.extend(history.iter().cloned());
    messages.push(json!({"role": "user", "content": message}));
    ollama::chat_at(base, &messages, model)
}

fn tools_reply(path: &str, message: &str, snapshot: &Value) -> String {
    let lower = message.to_lowercase();
    let live = snapshot.get("live").cloned().unwrap_or(json!({}));
    let tools = snapshot
        .get("tools_used")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|v| v.as_str()).collect::<Vec<_>>())
        .unwrap_or_default();

    let mut lines = vec![format!(
        "**Open-FDD assist** (tab `{path}`) — tool mode (Ollama offline)."
    )];

    if tools.contains(&"stack_health") {
        if let Some(stack) = live.get("stack") {
            let ver = stack
                .pointer("/bridge/version")
                .or_else(|| stack.get("version"))
                .and_then(|v| v.as_str())
                .unwrap_or("?");
            lines.push(format!(
                "Stack: bridge v{ver} — use Host stats or /api/health/stack for detail."
            ));
        }
    }

    if tools.contains(&"faults_status") {
        if let Some(f) = live.get("faults") {
            let active = f.get("active_count").and_then(|v| v.as_u64()).unwrap_or(0);
            lines.push(format!(
                "Faults: {active} active — open Dashboard or SQL FDD Rules."
            ));
        }
    }

    if tools.contains(&"csv_sessions") {
        if let Some(s) = live.get("csv_sessions") {
            let n = s
                .get("sessions")
                .and_then(|v| v.as_array())
                .map(|a| a.len())
                .unwrap_or(0);
            lines.push(format!("CSV import sessions: {n} recent — open CSV Fusion sidecart or /api/csv/import/sessions."));
        }
    }

    if tools.contains(&"model_coverage") {
        if let Some(c) = live.get("model_coverage") {
            let mapped = c.get("mapped_points").and_then(|v| v.as_u64()).unwrap_or(0);
            let unmapped = c
                .get("unmapped_points")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            lines.push(format!(
                "Model: {mapped} mapped / {unmapped} unmapped points."
            ));
        }
    }

    if lower.contains("help") || lower.contains("mcp") || lower.contains("codex") {
        lines.push(
            "External agents: Cursor/Codex + MCP sidecar (mcp/README.md) or JWT REST /api/agent/tools.".into(),
        );
    }

    if lower.contains("docker") || lower.contains("ollama") {
        lines.push(
            "Docker: `docker compose -f docker/compose.edge.rust.yml --profile ai up -d` then set workspace/ollama.env.local (see ollama.env.local.example).".into(),
        );
    }

    if lines.len() == 1 {
        lines.push(format!(
            "You asked: \"{message}\". I pulled live data for: {}. Enable Ollama for richer answers.",
            tools.join(", ")
        ));
    }

    lines.join("\n\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chat_requires_message() {
        let out = chat_reply(&json!({}));
        assert_eq!(out.get("ok"), Some(&json!(false)));
    }

    #[test]
    fn tools_reply_without_ollama() {
        let out = chat_reply(&json!({
            "message": "stack health?",
            "context_path": "/"
        }));
        assert_eq!(out.get("ok"), Some(&json!(true)));
        let source = out.get("source").and_then(|v| v.as_str()).unwrap_or("");
        assert!(
            matches!(source, "codex" | "tools" | "ollama" | "cursor"),
            "unexpected source: {source}"
        );
        let reply = out.get("reply").and_then(|v| v.as_str()).unwrap_or("");
        assert!(
            !reply.is_empty(),
            "reply should be non-empty for source {source}"
        );
        if source == "tools" {
            assert!(
                reply.contains("Open-FDD"),
                "tools fallback should mention Open-FDD"
            );
        }
    }
}
