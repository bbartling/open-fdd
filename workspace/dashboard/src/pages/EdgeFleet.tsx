import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/api";
import PageHeader from "../components/PageHeader";

type EdgeRow = {
  edge_id: string;
  has_telemetry?: boolean;
};

type EdgesResponse = {
  ok?: boolean;
  edges?: EdgeRow[];
  error?: string;
};

type IngestStats = {
  ok?: boolean;
  ingest_ok?: number;
  ingest_dup?: number;
  ingest_reject?: number;
  dead_letters?: number;
};

type HealthInfo = {
  ok?: boolean;
  service?: string;
  version?: string;
  edges?: number;
  ingest_ok?: number;
  ingest_dup?: number;
  ingest_reject?: number;
};

const POLL_MS = 15_000;

function StatCard({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return (
    <div className="metric-card">
      <div className="metric-head">
        <span className="status-kv-label">{label}</span>
        <strong>{value}</strong>
      </div>
      {detail ? <p className="muted metric-detail">{detail}</p> : null}
    </div>
  );
}

export default function EdgeFleetPage() {
  const [edges, setEdges] = useState<EdgeRow[]>([]);
  const [ingest, setIngest] = useState<IngestStats | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [edgeRes, ingestRes, healthRes] = await Promise.all([
        apiFetch<EdgesResponse>("/api/edges"),
        apiFetch<IngestStats>("/api/ingest/stats"),
        apiFetch<HealthInfo>("/api/health"),
      ]);
      setEdges(edgeRes.edges ?? []);
      setIngest(ingestRes);
      setHealth(healthRes);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      pollRef.current = window.setTimeout(load, POLL_MS);
    }
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (pollRef.current != null) window.clearTimeout(pollRef.current);
    };
  }, [load]);

  const onlineCount = edges.filter((e) => e.has_telemetry).length;

  return (
    <div>
      <PageHeader
        title="Edge fleet"
        subtitle="Remote fieldbus edges connected to Open-FDD Central over MQTTS. BACnet/Modbus/Haystack commissioning stays on the edge; this view shows central shadow and ingest health."
        meta={
          <span className="muted">
            {busy ? "Refreshing…" : `Auto-refresh ${POLL_MS / 1000}s`}
            {health?.service ? ` · ${health.service}` : null}
            {health?.version ? ` v${health.version}` : null}
          </span>
        }
      />

      {error ? <p className="error">{error}</p> : null}

      <section className="panel">
        <h3 className="panel-title">Central health</h3>
        <div className="metric-grid">
          <StatCard
            label="Service"
            value={health?.ok ? "ok" : health ? "degraded" : "—"}
            detail={health?.service ?? "Waiting for /api/health"}
          />
          <StatCard label="Registered edges" value={health?.edges ?? edges.length} />
          <StatCard label="Telemetry active" value={`${onlineCount} / ${edges.length}`} />
        </div>
      </section>

      <section className="panel">
        <h3 className="panel-title">Ingest pipeline</h3>
        <div className="metric-grid">
          <StatCard label="Accepted" value={ingest?.ingest_ok ?? health?.ingest_ok ?? 0} />
          <StatCard label="Duplicates" value={ingest?.ingest_dup ?? health?.ingest_dup ?? 0} />
          <StatCard label="Rejected" value={ingest?.ingest_reject ?? health?.ingest_reject ?? 0} />
          <StatCard label="Dead letters" value={ingest?.dead_letters ?? 0} />
        </div>
      </section>

      <section className="panel">
        <h3 className="panel-title">Edges</h3>
        {edges.length === 0 ? (
          <p className="muted">
            No edges registered yet. Provision an edge kit and start <code>openfdd-fieldbus</code> with MQTTS
            enabled; telemetry will appear here after the first envelope.
          </p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Edge ID</th>
                <th>Telemetry</th>
              </tr>
            </thead>
            <tbody>
              {edges.map((edge) => (
                <tr key={edge.edge_id}>
                  <td>
                    <code>{edge.edge_id}</code>
                  </td>
                  <td>
                    <span className={`status-pill ${edge.has_telemetry ? "status-green" : "status-gray"}`}>
                      <span className="status-dot" />
                      {edge.has_telemetry ? "receiving" : "idle"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
