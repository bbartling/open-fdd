import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, devRunScript, hasToken } from "../lib/api";
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
    error?: string;
  };
  cursor_chat_enabled?: boolean;
  cursor?: { ok?: boolean; base_url?: string; model?: string; error?: string };
  ollama?: {
    api_ok?: boolean;
    configured_model?: string;
    models_installed?: string[];
    interactive_chat_enabled?: boolean;
    error?: string;
  };
  chat_endpoint?: string;
  credentials_hint?: {
    bootstrap_handoff?: string;
    auth_env_local?: string;
    mcp_tools?: string[];
  };
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

  const runDev = useCallback(async (script: "ui_dev" | "codex_setup" | "codex_reset", label: string) => {
    setActionBusy(true);
    setActionMsg("");
    setError("");
    try {
      const res = await devRunScript(script);
      if (!res.ok) throw new Error(res.error ?? `failed to start ${label}`);
      setActionMsg(res.hint ?? `${label} started.`);
      if (script !== "ui_dev") await refresh();
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setActionBusy(false);
    }
  }, [refresh]);

  const ollama = config?.ollama;
  const codex = config?.codex;
  const cursor = config?.cursor;

  return (
    <div className="page page-wide">
      <PageHeader
        title="AI integrations"
        subtitle="Codex → Cursor → Ollama → bridge tools. MCP agents (Cursor, Claude, OpenClaw) use JWT from workspace credentials."
      />

      {!hasToken() ? (
        <p className="muted">
          <Link to="/login">Sign in</Link> to view integration status.
        </p>
      ) : null}

      {error ? <p className="error">{error}</p> : null}
      {actionMsg ? <p className="muted">{actionMsg}</p> : null}

      <section className="panel">
        <h3 className="panel-title">Local dev stack</h3>
        <p className="muted">One-click helpers (edge dev mode only). Passwords: bootstrap handoff or auth.env.local.</p>
        <div className="toolbar">
          <button
            type="button"
            className="primary-btn"
            disabled={actionBusy}
            onClick={() => void runDev("ui_dev", "UI dev server")}
          >
            Start UI dev (:5173)
          </button>
          <button
            type="button"
            className="secondary-btn"
            disabled={actionBusy}
            onClick={() => void runDev("codex_setup", "Codex relay")}
          >
            Start Codex relay
          </button>
          <button
            type="button"
            className="secondary-btn"
            disabled={actionBusy}
            onClick={() => void runDev("codex_reset", "Codex reset")}
          >
            Reset Codex relay
          </button>
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void refresh()}>
            {busy ? "Checking…" : "Refresh status"}
          </button>
        </div>
      </section>

      <section className="panel">
        <h3 className="panel-title">MCP & credentials</h3>
        <p className="muted">
          MCP tools: <code>openfdd_auth_credentials_hint</code>, <code>openfdd_auth_login</code>,{" "}
          <code>openfdd_model_assignments_save</code>. Handoff:{" "}
          <code>{config?.credentials_hint?.bootstrap_handoff ?? "workspace/bootstrap_credentials.once.txt"}</code>
        </p>
      </section>

      <section className="panel">
        <h3 className="panel-title">Agent providers</h3>
        <div className="status-kv-grid">
          <div className="status-kv">
            <span className="status-kv-label">Codex</span>
            <span className={`status-kv-value ${config?.codex_chat_enabled ? "ok" : ""}`}>
              {config?.codex_chat_enabled ? "online" : "offline (optional)"}
            </span>
          </div>
          <div className="status-kv">
            <span className="status-kv-label">Cursor</span>
            <span className={`status-kv-value ${config?.cursor_chat_enabled ? "ok" : ""}`}>
              {config?.cursor_chat_enabled ? "online" : "offline (optional)"}
            </span>
          </div>
          <div className="status-kv">
            <span className="status-kv-label">Ollama</span>
            <span className={`status-kv-value ${ollama?.api_ok ? "ok" : ""}`}>
              {ollama?.api_ok ? ollama.configured_model ?? "reachable" : "offline (optional)"}
            </span>
          </div>
        </div>
        {!config?.codex_chat_enabled && !config?.cursor_chat_enabled && !ollama?.api_ok ? (
          <p className="muted">
            No external LLM relay required — dashboard insight and Agent assist tools fallback use live bridge data.
            Start Codex or Ollama when you want richer chat.
          </p>
        ) : null}
        {codex?.error && !config?.codex_chat_enabled ? (
          <p className="muted">Codex: {codex.error}</p>
        ) : null}
      </section>

      <section className="panel">
        <h3 className="panel-title">Chat session</h3>
        <div className="toolbar">
          <button type="button" className="secondary-btn" disabled={!hasToken()} onClick={() => notifyClearAgentChat()}>
            Clear chat history
          </button>
          <button
            type="button"
            className="secondary-btn"
            disabled={!hasToken() || actionBusy}
            onClick={() => void apiFetch("/api/agent/reset", { method: "POST" }).then(() => refresh())}
          >
            Restart agent session
          </button>
        </div>
      </section>
    </div>
  );
}
