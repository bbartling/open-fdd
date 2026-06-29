import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, hasToken } from "../lib/api";
import { notifyClearAgentChat } from "../lib/agentChatStore";
import { formatApiError } from "../lib/formatApiError";

type AgentConfig = {
  ok?: boolean;
  codex_chat_enabled?: boolean;
  codex?: {
    ok?: boolean;
    base_url?: string;
    codex_logged_in?: boolean;
    openfdd_mcp_configured?: boolean;
    model?: string;
    agent?: string;
    error?: string;
    hint?: string;
  };
  cursor_chat_enabled?: boolean;
  cursor?: {
    ok?: boolean;
    base_url?: string;
    has_api_key?: boolean;
    model?: string;
    agent_id?: string;
    error?: string;
    hint?: string;
  };
  ollama?: {
    api_ok?: boolean;
    base_url?: string;
    active_base_url?: string;
    configured_model?: string;
    models_installed?: string[];
    interactive_chat_enabled?: boolean;
    error?: string;
  };
  chat_endpoint?: string;
};

export default function AgentPage() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!hasToken()) return;
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<AgentConfig>("/api/agent/config");
      setConfig(out);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const clearChatHistory = useCallback(() => {
    notifyClearAgentChat();
    setActionMsg("Chat history cleared in this browser.");
  }, []);

  const restartAgent = useCallback(async () => {
    if (!hasToken()) return;
    setActionBusy(true);
    setActionMsg("");
    setError("");
    try {
      await apiFetch("/api/agent/reset", { method: "POST" });
      setActionMsg("Agent session restarted — next prompt starts a fresh Codex run.");
      await refresh();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setActionBusy(false);
    }
  }, [refresh]);

  const ollama = config?.ollama;
  const cursor = config?.cursor;
  const codex = config?.codex;

  return (
    <div className="page page-wide">
      <PageHeader
        title="AI integrations"
        subtitle="In-app chat: Codex → Cursor → Ollama (Hermes/llama/etc.) → live bridge tools. External agents use MCP + JWT from workspace credentials."
      />

      {!hasToken() ? (
        <p className="muted">
          <Link to="/login">Sign in</Link> to view integration status and use the agent panel on the right.
        </p>
      ) : null}

      {error ? <p className="error">{error}</p> : null}
      {actionMsg ? <p className="muted">{actionMsg}</p> : null}

      <section className="panel">
        <div className="toolbar">
          <h3 className="panel-title">Chat session</h3>
        </div>
        <p className="muted">
          Clear local chat history in the agent rail, or restart the Codex relay session (cancels in-flight work and
          drops server-side session state).
        </p>
        <div className="toolbar">
          <button type="button" className="secondary-btn" disabled={!hasToken()} onClick={clearChatHistory}>
            Clear chat history
          </button>
          <button
            type="button"
            className="secondary-btn"
            disabled={!hasToken() || actionBusy}
            onClick={() => void restartAgent()}
          >
            {actionBusy ? "Restarting…" : "Restart agent"}
          </button>
        </div>
      </section>

      <section className="panel">
        <h3 className="panel-title">MCP credentials (Cursor, Claude, Codex, OpenClaw)</h3>
        <p className="muted">
          MCP sidecar reads login from the host workspace — not from the browser session. One-time passwords:{" "}
          <code>workspace/bootstrap_credentials.once.txt</code> (delete after saving). Ongoing:{" "}
          <code>workspace/auth.env.local</code> + <code>OPENFDD_INTEGRATOR_PASSWORD</code> env or{" "}
          <code>scripts/openfdd_auth_lib.sh</code>.
        </p>
        <ul className="muted">
          <li>
            MCP tools: <code>openfdd_auth_credentials_hint</code>, <code>openfdd_auth_login</code> (returns JWT only)
          </li>
          <li>
            Model + FDD wiresheet: <code>openfdd_model_assignments_save</code> then{" "}
            <code>openfdd_fdd_wires_sync</code> — or save auto-syncs wiresheet
          </li>
          <li>
            Dashboard login (UI): integrator role from bootstrap handoff file
          </li>
        </ul>
      </section>

      <section className="panel">
        <div className="toolbar">
          <h3 className="panel-title">Codex CLI (in-app chat)</h3>
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void refresh()}>
            {busy ? "Checking…" : "Refresh status"}
          </button>
        </div>
        <p className="muted">
          <strong>Agent assist</strong> uses Codex via <code>./scripts/openfdd_agent_chat_setup.sh</code> — JWT +
          openfdd MCP auto-wired. Scratch CSV scripts: <code>workspace/agent-toolshed/</code> (gitignored).
        </p>
        <div className="status-kv-grid">
          <div className="status-kv">
            <span className="status-kv-label">Relay</span>
            <span className={`status-kv-value ${config?.codex_chat_enabled ? "ok" : "error"}`}>
              {config?.codex_chat_enabled ? "connected" : "offline"}
            </span>
          </div>
          <div className="status-kv">
            <span className="status-kv-label">MCP</span>
            <span className={`status-kv-value ${codex?.openfdd_mcp_configured ? "ok" : ""}`}>
              {codex?.openfdd_mcp_configured ? "openfdd" : "not listed"}
            </span>
          </div>
          {codex?.base_url ? (
            <div className="status-kv">
              <span className="status-kv-label">URL</span>
              <span className="status-kv-value">{codex.base_url}</span>
            </div>
          ) : null}
        </div>
        {codex?.error && !config?.codex_chat_enabled ? <p className="error">{codex.error}</p> : null}
        <p className="muted">
          Setup: <code>codex login</code> then <code>./scripts/openfdd_agent_chat_setup.sh</code> · Reset:{" "}
          <code>./scripts/openfdd_agent_chat_reset.sh</code>
        </p>
      </section>

      <section className="panel">
        <div className="toolbar">
          <h3 className="panel-title">Cursor SDK (optional)</h3>
        </div>
        <p className="muted">
          <strong>Agent assist</strong> uses the local Cursor SDK relay when running:{" "}
          <code>./scripts/openfdd_cursor_chat_relay.sh</code>
        </p>
        <div className="status-kv-grid">
          <div className="status-kv">
            <span className="status-kv-label">Relay</span>
            <span className={`status-kv-value ${config?.cursor_chat_enabled ? "ok" : "error"}`}>
              {config?.cursor_chat_enabled ? "connected" : "offline"}
            </span>
          </div>
          {cursor?.base_url ? (
            <div className="status-kv">
              <span className="status-kv-label">URL</span>
              <span className="status-kv-value">{cursor.base_url}</span>
            </div>
          ) : null}
          {cursor?.model ? (
            <div className="status-kv">
              <span className="status-kv-label">Model</span>
              <span className="status-kv-value">{cursor.model}</span>
            </div>
          ) : null}
        </div>
        {cursor?.error && !config?.cursor_chat_enabled ? <p className="error">{cursor.error}</p> : null}
        <details className="agent-settings-details">
          <summary>Docker setup</summary>
          <pre className="code-block">
{`cp workspace/cursor.env.local.example workspace/cursor.env.local
# Set CURSOR_API_KEY; OFDD_CURSOR_CHAT_URL=http://openfdd-cursor-relay:8787

OPENFDD_COMPOSE_ROOT=$PWD docker compose \\
  -f docker/compose.edge.rust.yml \\
  --profile desktop-json-csv --profile cursor up -d`}
          </pre>
        </details>
        <p className="muted">
          Setup: <code>cp workspace/cursor.env.local.example workspace/cursor.env.local</code> — add{" "}
          <code>CURSOR_API_KEY</code> from cursor.com/settings.
        </p>
      </section>

      <section className="panel">
        <div className="toolbar">
          <h3 className="panel-title">Ollama (production / offline LLM)</h3>
        </div>
        <p className="muted">
          Fallback when Cursor relay is off. Production benches can use Ollama in Docker instead of Cursor.
        </p>
        <div className="status-kv-grid">
          <div className="status-kv">
            <span className="status-kv-label">API</span>
            <span className={`status-kv-value ${ollama?.api_ok ? "ok" : "error"}`}>
              {ollama?.api_ok ? "reachable" : "offline"}
            </span>
          </div>
          <div className="status-kv">
            <span className="status-kv-label">Chat</span>
            <span className={`status-kv-value ${ollama?.interactive_chat_enabled ? "ok" : ""}`}>
              {ollama?.interactive_chat_enabled ? "enabled" : "tool-only fallback"}
            </span>
          </div>
          {ollama?.configured_model ? (
            <div className="status-kv">
              <span className="status-kv-label">Model</span>
              <span className="status-kv-value">{ollama.configured_model}</span>
            </div>
          ) : null}
          {ollama?.active_base_url || ollama?.base_url ? (
            <div className="status-kv">
              <span className="status-kv-label">Base URL</span>
              <span className="status-kv-value">{ollama.active_base_url || ollama.base_url}</span>
            </div>
          ) : null}
        </div>
        {ollama?.models_installed?.length ? (
          <p className="muted">Installed: {ollama.models_installed.slice(0, 6).join(", ")}</p>
        ) : null}
        {ollama?.error && !ollama.api_ok ? <p className="error">{ollama.error}</p> : null}
        <details className="agent-settings-details">
          <summary>Docker setup</summary>
          <pre className="code-block">
{`docker exec openfdd-ollama ollama pull llama3.2

cp workspace/ollama.env.local.example workspace/ollama.env.local
# OFDD_OLLAMA_BASE_URL=http://ollama:11434

OPENFDD_COMPOSE_ROOT=$PWD docker compose \\
  -f docker/compose.edge.rust.yml \\
  --profile desktop-json-csv --profile ai up -d`}
          </pre>
        </details>
        <p className="muted">
          Config file: <code>workspace/ollama.env.local</code> (see <code>ollama.env.local.example</code>). Host metrics:{" "}
          <Link to="/host">Host stats</Link>.
        </p>
      </section>

      <section className="panel">
        <h3 className="panel-title">Using chat on any tab</h3>
        <p>
          After sign-in, open CSV Fusion, BACnet, SQL FDD, or any workspace tab — the <strong>Agent assist</strong> rail
          on the right stays in context (<code>{config?.chat_endpoint ?? "/api/agent/chat"}</code>).
        </p>
        <p className="muted">
          Examples: “How many CSV sessions?” on CSV · “Model coverage?” on Model · “Stack health?” on Dashboard.
        </p>
      </section>
    </div>
  );
}
