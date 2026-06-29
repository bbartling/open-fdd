import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";
import FddRuleWiresheet from "../wiresheet/FddRuleWiresheet";
import { graphToFlow } from "../wiresheet/graphAdapter";
import { fetchWiresheetGraph } from "../wiresheet/wiresheetApi";

const GRAPH_ID = "graph:live-fdd-validation";

type Props = {
  onStatus?: (message: string) => void;
};

/** Model page FDD wiresheet — live canvas + AI propose; syncs when assignments change. */
export default function FddWiresheetSummary({ onStatus }: Props) {
  const siteId = useActiveSiteId();
  const [nodeCount, setNodeCount] = useState(0);
  const [reviewStatus, setReviewStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const loadMeta = useCallback(async () => {
    if (!siteId) return;
    try {
      const graph = await fetchWiresheetGraph(GRAPH_ID, siteId);
      const flow = graphToFlow(graph);
      setNodeCount(flow.nodes.length);
      setReviewStatus(graph.review_status ?? "draft");
    } catch {
      setNodeCount(0);
    }
  }, [siteId]);

  useEffect(() => {
    void loadMeta();
  }, [loadMeta, refreshKey]);

  useEffect(() => {
    const onChange = () => {
      setRefreshKey((k) => k + 1);
    };
    window.addEventListener("ofdd-assignments-changed", onChange);
    return () => window.removeEventListener("ofdd-assignments-changed", onChange);
  }, []);

  async function proposeFromAi() {
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<{
        review_status?: string;
        proposed?: unknown[];
        proposals?: unknown[];
        wiresheet_sync?: { node_count?: number };
      }>("/api/fdd-wires/propose-assignments", {
        method: "POST",
        body: JSON.stringify({ site_id: siteId || undefined, equipment_type: "ahu" }),
      });
      const n = out.proposed?.length ?? out.proposals?.length ?? 0;
      const nodes = out.wiresheet_sync?.node_count;
      const msg = `AI proposed ${n} bindings (${out.review_status ?? "needs_review"})${
        nodes != null ? ` — wiresheet now has ${nodes} nodes` : ""
      }.`;
      onStatus?.(msg);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  async function syncFromAssignments() {
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<{ node_count?: number; review_status?: string }>(
        "/api/fdd-wires/sync-from-assignments",
        {
          method: "POST",
          body: JSON.stringify({ site_id: siteId || undefined, graph_id: GRAPH_ID }),
        },
      );
      onStatus?.(`Wiresheet synced — ${out.node_count ?? 0} nodes (${out.review_status ?? "draft"}).`);
      setRefreshKey((k) => k + 1);
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel fdd-wiresheet-summary">
      <div className="fdd-wiresheet-summary__header">
        <div>
          <h3 className="panel-title">FDD rule mapping wiresheet</h3>
          <p className="muted">
            Haystack points → FDD inputs → SQL rules → faults. When AI saves model assignments or you import
            commissioning JSON, use <strong>Sync from assignments</strong> or save via MCP — the graph below updates
            for review before activate.
          </p>
        </div>
        <div className="action-bar">
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void proposeFromAi()}>
            {busy ? "Working…" : "AI propose assignments"}
          </button>
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void syncFromAssignments()}>
            Sync from assignments
          </button>
          <Link className="primary-btn" to="/wiresheet">
            Open Wiresheet Studio
          </Link>
        </div>
      </div>
      {error ? <p className="error-banner">{error}</p> : null}
      <dl className="detail-grid compact">
        <div>
          <dt>Graph</dt>
          <dd>
            <code>{GRAPH_ID}</code>
          </dd>
        </div>
        <div>
          <dt>Nodes</dt>
          <dd>{nodeCount}</dd>
        </div>
        <div>
          <dt>Review</dt>
          <dd>{reviewStatus || "—"}</dd>
        </div>
        <div>
          <dt>Site</dt>
          <dd>{siteId || "loading…"}</dd>
        </div>
      </dl>
      <FddRuleWiresheet key={refreshKey} compact />
    </section>
  );
}
