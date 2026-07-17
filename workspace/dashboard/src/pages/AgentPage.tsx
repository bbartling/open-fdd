import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, getBridgeBase, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type AgentConfig = {
  ok?: boolean;
  embedded_chat?: boolean;
  external_agent_workflow?: boolean;
  mcp_binary?: string;
  tools_endpoint?: string;
  workflow?: string[];
};

type HealthInfo = { version?: string; image_tag?: string };

function benchApiBase(): string {
  if (typeof window !== "undefined" && window.location.hostname !== "localhost") {
    return `${window.location.protocol}//${window.location.hostname}:8080`;
  }
  return "http://127.0.0.1:8080";
}

function mcpConfigJson(imageTag: string, apiBase: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        openfdd: {
          command: "docker",
          args: [
            "run",
            "-i",
            "--rm",
            "--network",
            "host",
            "-e",
            `OPENFDD_API_BASE=${apiBase}`,
            "-e",
            "OPENFDD_COMMISSION_BASE=http://127.0.0.1:9091",
            "-e",
            "OPENFDD_MCP_TOKEN",
            `ghcr.io/bbartling/openfdd-mcp:${imageTag}`,
          ],
          env: { OPENFDD_MCP_TOKEN: "<integrator JWT from dashboard login — never commit>" },
        },
      },
    },
    null,
    2,
  );
}

function agentBriefing(imageTag: string, apiBase: string): string {
  return `You help a human operator on Open-FDD (edge ${imageTag}, ${apiBase}).

Start read-only: openfdd_health · openfdd_driver_status.
CSV: openfdd_csv_* for preview → plan → preflight → execute (human must approve writes).
Writes need OPENFDD_MCP_ALLOW_WRITES=1 and confirm:true. No BACnet writes without explicit human OK.
Long Niagara CSV exports must be pivoted to wide historian shape before preflight pass.`;
}

async function copyText(text: string): Promise<void> {
  await navigator.clipboard.writeText(text);
}

export default function AgentPage() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [toolCount, setToolCount] = useState<number | null>(null);
  const [imageTag, setImageTag] = useState("3.2.8");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<"" | "mcp" | "brief">("");
  const [busy, setBusy] = useState(false);

  const apiBase = useMemo(() => benchApiBase(), []);

  const refresh = useCallback(async () => {
    if (!hasToken()) return;
    setBusy(true);
    setError("");
    try {
      const base = getBridgeBase();
      const [cfg, tools, health] = await Promise.all([
        apiFetch<AgentConfig>("/api/agent/config"),
        apiFetch<{ tools?: unknown[] }>("/api/agent/tools"),
        fetch(`${base}/api/health`).then((r) => r.json() as Promise<HealthInfo>),
      ]);
      setConfig(cfg);
      setToolCount(tools.tools?.length ?? 0);
      setImageTag(health.image_tag || health.version || imageTag);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }, [imageTag]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const mcpJson = useMemo(() => mcpConfigJson(imageTag, apiBase), [imageTag, apiBase]);
  const briefing = useMemo(() => agentBriefing(imageTag, apiBase), [imageTag, apiBase]);

  async function onCopy(kind: "mcp" | "brief") {
    try {
      await copyText(kind === "mcp" ? mcpJson : briefing);
      setCopied(kind);
      window.setTimeout(() => setCopied(""), 2500);
    } catch (e) {
      setError(formatApiError(e));
    }
  }

  return (
    <div className="page page-wide">
      <PageHeader
        title="External agents"
        subtitle="Open-FDD has no embedded chatbot. Wire any MCP-capable host via stdio openfdd-mcp, then reload that host so tools register."
      />

      {error ? <p className="error">{error}</p> : null}

      <div className="panel">
        <h3 className="panel-title">What this is</h3>
        <p>
          Connect <strong>Codex, Cursor, Claude Desktop, OpenClaw</strong>, or any MCP host to this edge.
          The agent assists the human operator on your OT LAN — read-first by default; writes require explicit approval.
        </p>
      </div>

      <div className="panel">
        <h3 className="panel-title">Copy MCP host configuration</h3>
        <p className="muted">
          Paste into your external agent&apos;s MCP settings, replace the JWT placeholder, then <strong>restart or reload</strong>{" "}
          that host (tools load at session start — they do not hot-plug).
        </p>
        <p className="muted">
          Same machine as edge: use <code>{apiBase}</code> and <code>--network host</code>. Remote OT-LAN PC: set{" "}
          <code>OPENFDD_API_BASE</code> to <code>http://&lt;bench-ip&gt;:8080</code> and omit <code>--network host</code> when Docker runs remotely.
        </p>
        <pre className="code-block">{mcpJson}</pre>
        <button type="button" className="primary-btn" onClick={() => void onCopy("mcp")}>
          {copied === "mcp" ? "Copied MCP config" : "Copy MCP configuration"}
        </button>
      </div>

      <div className="panel">
        <h3 className="panel-title">Copy first message to external agent</h3>
        <p className="muted">Paste as the opening turn after MCP tools appear in the host session.</p>
        <pre className="code-block">{briefing}</pre>
        <button type="button" className="primary-btn" onClick={() => void onCopy("brief")}>
          {copied === "brief" ? "Copied briefing" : "Copy agent briefing"}
        </button>
      </div>

      {config ? (
        <div className="panel">
          <h3 className="panel-title">Edge status</h3>
          <p className="muted">
            {busy ? "Refreshing…" : null}
            Image tag <code>{imageTag}</code>
            {toolCount != null ? ` · ${toolCount} REST tools at /api/agent/tools` : null}
            {config.embedded_chat === false ? " · embedded chat disabled" : null}
          </p>
          <p className="muted">
            CSV batch import uses MCP/API only — see{" "}
            <a href="https://bbartling.github.io/open-fdd/drivers/csv-batch.html" target="_blank" rel="noreferrer">
              CSV batch driver docs
            </a>
            {" "}· MCP <code>openfdd_csv_*</code>
          </p>
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
      ) : null}
    </div>
  );
}
