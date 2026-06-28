import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { apiFetch, hasToken } from "../lib/api";
import { useEffect, useState } from "react";

export default function AgentPage() {
  const [toolCount, setToolCount] = useState<number | null>(null);

  useEffect(() => {
    if (!hasToken()) return;
    apiFetch<{ tools?: unknown[] }>("/api/agent/tools")
      .then((j) => setToolCount(j.tools?.length ?? 0))
      .catch(() => setToolCount(null));
  }, []);

  return (
    <div className="page page-wide">
      <PageHeader
        title="MCP / Agent"
        subtitle="Connect Cursor or Codex to the Rust edge via the openfdd-mcp sidecar (read-first tools)."
      />

      <section className="panel">
        <h3 className="panel-title">Model Context Protocol (MCP)</h3>
        <p>
          MCP exposes JWT-authenticated bridge APIs as tools for external agents. Use it for Haystack SPARQL, driver
          status, BACnet reads, and CSV/model workflows — not for unsupervised field-bus writes.
        </p>
        <ul>
          <li>
            <code>openfdd_model_sparql</code> — query the Haystack RDF model
          </li>
          <li>
            <code>openfdd_model_coverage</code> — mapped vs unmapped points
          </li>
          <li>
            <code>openfdd_haystack_read</code> · <code>openfdd_bacnet_read</code> — live OT reads
          </li>
        </ul>
        <p className="muted">
          Setup: repository <code>mcp/README.md</code> · contract{" "}
          <code>docs/agent/openfdd-mcp-tool-contract.md</code>
        </p>
        {toolCount != null ? (
          <p className="ok">
            Bridge reports <strong>{toolCount}</strong> REST tools via <code>/api/agent/tools</code>.
          </p>
        ) : null}
      </section>

      <section className="panel">
        <h3 className="panel-title">CSV data assistant (external agent)</h3>
        <p className="muted">
          For Lake Geneva–style UT3 merges, ask your agent to: profile uploads via{" "}
          <code>POST /api/csv/import/preview</code>, run <code>POST /api/csv/import/plan</code>, validate row counts,
          then save. On the CSV tab, prefer <strong>Append</strong> for four school-year kW files (
          <code>Date</code> + <code>kW</code>).
        </p>
        <p>
          <Link to="/csv">Open CSV Fusion / UT3 Import</Link>
        </p>
      </section>

      <section className="panel">
        <h3 className="panel-title">In-app chat (deferred)</h3>
        <p className="muted">
          Built-in Ollama operator chat is not enabled in 3.2.x. Use MCP + Cursor on the bench, or{" "}
          <Link to="/sql-fdd">SQL FDD Rules</Link> and <Link to="/live-fdd-validation">Validation runs</Link> for
          bench proof.
        </p>
      </section>
    </div>
  );
}
