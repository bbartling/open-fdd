import { useEffect, useState } from "react";
import BuildingCheckEngine from "../components/BuildingCheckEngine";
import { apiFetch } from "../lib/api";

type AuditEvent = Record<string, unknown>;

export default function HomePage() {
  const [auditPreview, setAuditPreview] = useState<AuditEvent[]>([]);
  const [auditError, setAuditError] = useState("");

  useEffect(() => {
    apiFetch<{ events: AuditEvent[] }>("/api/audit/events?limit=10")
      .then((r) => setAuditPreview(r.events))
      .catch((e) => setAuditError(String(e)));
  }, []);

  return (
    <div>
      <h2 className="title">Building overview</h2>
      <p className="muted">
        Default landing view — check-engine light for model gaps, stack health, and agent-reported issues.
      </p>

      <BuildingCheckEngine />

      <div className="panel">
        <h3>Stack services</h3>
        <p className="muted">
          Green = healthy · Yellow = degraded · Red = down · Gray = not configured (MCP is optional).
        </p>
      </div>

      <div className="panel">
        <h3>Security audit trail</h3>
        <p className="muted">
          Append-only JSON Lines at <code>workspace/logs/audit.jsonl</code>. Integrator role required.
        </p>
        {auditError ? (
          <p className="muted">
            {auditError.includes("403") ? "Sign in as integrator to view audit log." : auditError}
          </p>
        ) : auditPreview.length ? (
          <pre className="console audit-preview">
            {auditPreview
              .slice()
              .reverse()
              .map((ev) => JSON.stringify(ev))
              .join("\n")}
          </pre>
        ) : (
          <p className="muted">No audit events yet.</p>
        )}
      </div>
    </div>
  );
}
