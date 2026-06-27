import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { useActiveSiteId } from "../lib/useActiveSiteId";
import { graphToFlow } from "../wiresheet/graphAdapter";
import type { WiresheetGraph } from "../wiresheet/types";

const GRAPH_ID = "graph:live-fdd-validation";

type Props = {
  onStatus?: (message: string) => void;
};

/** Compact FDD wiresheet summary for Model page — AI propose + link to full studio. */
export default function FddWiresheetSummary({ onStatus }: Props) {
  const siteId = useActiveSiteId();
  const [nodeCount, setNodeCount] = useState(0);
  const [reviewStatus, setReviewStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadGraph = useCallback(async () => {
    if (!siteId) return;
    try {
      const qs = `?site_id=${encodeURIComponent(siteId)}`;
      const graph = await apiFetch<WiresheetGraph>(
        `/api/fdd-wires/graphs/${encodeURIComponent(GRAPH_ID)}${qs}`,
      );
      const flow = graphToFlow(graph);
      setNodeCount(flow.nodes.length);
      setReviewStatus(graph.review_status ?? "draft");
    } catch {
      setNodeCount(0);
    }
  }, [siteId]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  async function proposeFromAi() {
    setBusy(true);
    setError("");
    try {
      const out = await apiFetch<{ review_status?: string; proposed?: unknown[] }>(
        "/api/fdd-wires/propose-assignments",
        {
          method: "POST",
          body: JSON.stringify({ site_id: siteId || undefined, equipment_type: "ahu" }),
        },
      );
      const msg = `AI proposed ${out.proposed?.length ?? 0} bindings (${out.review_status ?? "needs_review"}) — open Wiresheet Studio to review.`;
      onStatus?.(msg);
      await loadGraph();
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
            Visual map from Haystack points → FDD inputs → SQL rules → faults. Populated by AI proposals or manual
            editing; review before activate.
          </p>
        </div>
        <div className="action-bar">
          <button type="button" className="secondary-btn" disabled={busy} onClick={() => void proposeFromAi()}>
            {busy ? "Proposing…" : "AI propose assignments"}
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
    </section>
  );
}
