import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import BrickNetworkGraph, { downloadBrickNetworkPng } from "./BrickNetworkGraph";
import type { BrickNetworkInput } from "../lib/brickNetworkGraph";

type ModelGraph = BrickNetworkInput & {
  site_id: string;
  query_engine?: string;
};

type Props = {
  siteId?: string;
  onStatus?: (msg: string) => void;
  refreshKey?: number;
  onModelChange?: () => void;
};

export default function ModelGraphExplorer({ siteId, onStatus, refreshKey = 0 }: Props) {
  const [graph, setGraph] = useState<ModelGraph | null>(null);
  const [error, setError] = useState("");
  const networkChartRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    const q = siteId ? `?site_id=${encodeURIComponent(siteId)}` : "";
    const data = await apiFetch<ModelGraph>(`/api/model/graph${q}`);
    setGraph(data);
    setError("");
  }, [siteId]);

  useEffect(() => {
    load().catch((e) => setError(formatApiError(e)));
  }, [load, refreshKey]);

  async function handleDownloadPng() {
    const el = networkChartRef.current?.querySelector(".dm-network-chart") as HTMLDivElement | null;
    try {
      await downloadBrickNetworkPng(el);
      onStatus?.("Downloaded BRICK network graph PNG");
    } catch (e) {
      setError(formatApiError(e));
    }
  }

  return (
    <div className="dm-explorer dm-explorer-single">
      <section className="dm-network-section panel">
        <div className="dm-network-head">
          <div>
            <h3 className="panel-title">BRICK network</h3>
            <p className="muted dm-network-sub">
              Equipment <strong>feeds</strong> relationships and BACnet points on the model. Pin FDD rules per device on{" "}
              <a href="/fdd-assignments">FDD assignments</a>.
            </p>
          </div>
          <div className="dm-network-actions">
            <button
              type="button"
              className="secondary"
              disabled={!graph?.equipment?.length}
              onClick={() => void handleDownloadPng()}
            >
              Download PNG
            </button>
          </div>
        </div>

        {graph?.feeds?.length ? (
          <ul className="dm-feeds-chips" aria-label="Feeds relationships">
            {graph.feeds.map((f) => (
              <li key={`${f.from_equipment_id}-${f.to_equipment_id}`} className="dm-feed-chip">
                <span>{f.from_label || f.from_equipment_id}</span>
                <span className="dm-feed-chip-arrow">feeds →</span>
                <span>{f.to_label || f.to_equipment_id}</span>
              </li>
            ))}
          </ul>
        ) : null}

        <div ref={networkChartRef} className="dm-network-wrap">
          <BrickNetworkGraph graph={graph} height={480} />
        </div>
      </section>

      {error ? <p className="error">{error}</p> : null}
    </div>
  );
}
