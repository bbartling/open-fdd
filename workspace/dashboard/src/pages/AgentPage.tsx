import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type AgentConfig = {
  ok?: boolean;
  embedded_chat?: boolean;
  external_agent_workflow?: boolean;
  mcp_binary?: string;
  tools_endpoint?: string;
  manifest_endpoint?: string;
  mcp_docs?: string;
  example_hosts?: string[];
  workflow?: string[];
  credentials_hint?: {
    bootstrap_handoff?: string;
    auth_env_local?: string;
    mcp_tools?: string[];
    note?: string;
  };
};

export default function AgentPage() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [toolCount, setToolCount] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!hasToken()) return;
    setBusy(true);
    setError("");
    try {
      const [cfg, tools] = await Promise.all([
        apiFetch<AgentConfig>("/api/agent/config"),
        apiFetch<{ tools?: unknown[] }>("/api/agent/tools"),
      ]);
      setConfig(cfg);
      setToolCount(tools.tools?.length ?? 0);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="page page-wide">
      <PageHeader
        title="External agents"
        subtitle="Open-FDD does not ship an embedded chatbot. Connect Codex CLI, Cursor, Claude Desktop, OpenClaw, or any MCP host through optional openfdd-mcp (stdio) or JWT REST."
      />

      {error ? <p className="error">{error}</p> : null}

      <div className="panel">
        <h3 className="panel-title">Architecture</h3>
        <p>
          Open-FDD is the edge FDD platform. The agent is the operator <strong>outside</strong> the
          platform — vendor-neutral, local-first, read-first by default.
        </p>
        <ul>
          <li>
            <code>openfdd-mcp</code> — stdio MCP server bundled in{" "}
            <code>ghcr.io/bbartling/openfdd-edge-rust</code> (or slim <code>openfdd-mcp</code> image)
          </li>
          <li>
            REST — <code>/api/agent/tools</code> catalog; same JWT auth as the dashboard
          </li>
          <li>
            Writes — <code>OPENFDD_MCP_ALLOW_WRITES=1</code> and <code>confirm:true</code> on mutating
            tools; BACnet writes need explicit human approval
          </li>
        </ul>
        <p>
          Full setup: <Link to="/">dashboard</Link> healthy → obtain integrator JWT → wire MCP in your
          external tool. See <a href="https://github.com/bbartling/open-fdd/blob/master/mcp/README.md">mcp/README.md</a>{" "}
          and <a href="https://github.com/bbartling/open-fdd/blob/master/docs/examples/external-agents.md">docs/examples/external-agents.md</a>.
        </p>
      </div>

      {config ? (
        <div className="panel">
          <h3 className="panel-title">Edge status</h3>
          <p className="muted">
            {busy ? "Refreshing…" : null}
            Embedded chat: {config.embedded_chat === false ? "disabled" : "unknown"} · MCP binary:{" "}
            <code>{config.mcp_binary ?? "openfdd-mcp"}</code>
            {toolCount != null ? ` · ${toolCount} REST tools cataloged` : null}
          </p>
          {config.workflow?.length ? (
            <ol>
              {config.workflow.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          ) : null}
          {config.example_hosts?.length ? (
            <p className="muted">Example external hosts: {config.example_hosts.join(", ")}</p>
          ) : null}
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
      ) : null}

      <div className="panel">
        <h3 className="panel-title">Cursor MCP (example)</h3>
        <pre className="code-block">{`{
  "mcpServers": {
    "openfdd": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm", "--network", "host",
        "--entrypoint", "openfdd-mcp",
        "-e", "OPENFDD_API_BASE=http://127.0.0.1:8080",
        "-e", "OPENFDD_MCP_TOKEN",
        "ghcr.io/bbartling/openfdd-edge-rust:latest"
      ],
      "env": { "OPENFDD_MCP_TOKEN": "<integrator JWT>" }
    }
  }
}`}</pre>
        <p className="muted">Never commit tokens. MCP uses stdio — not an HTTP port.</p>
      </div>
    </div>
  );
}
