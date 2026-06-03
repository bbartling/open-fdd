/**
 * Read-only building summary on the home page (one sentence, fixed refresh).
 *
 * SECURITY: Do NOT add chat inputs, message history, or POST /openfdd-agent/chat here.
 * Interactive LLM chat belongs on the Agent tab (/agent) only.
 */
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";

type InsightResponse = {
  ok: boolean;
  sentence: string;
  zone_sentence?: string;
  zone_temps?: {
    topology_mode?: string;
    zone_sensor_count?: number;
    struggling_zones?: { label?: string; ahu_name?: string; reason?: string }[];
    refresh_interval_s?: number;
  };
  source?: string;
  generated_at?: number;
  next_refresh_at?: number;
  refresh_interval_s?: number;
  cached?: boolean;
  error?: string;
  ollama_ok?: boolean;
};

const DEFAULT_POLL_MS = 15 * 60 * 1000;

export default function HomeBuildingInsight() {
  const [insight, setInsight] = useState<InsightResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const qs = force ? "?force=true" : "";
      const res = await apiFetch<InsightResponse>(`/openfdd-agent/building-insight${qs}`);
      setInsight(res);
      setError("");
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    const intervalMs = DEFAULT_POLL_MS;
    const timer = window.setInterval(() => void load(false), intervalMs);
    return () => window.clearInterval(timer);
  }, [load]);

  const updatedLabel =
    insight?.generated_at != null
      ? new Date(insight.generated_at * 1000).toLocaleString()
      : null;
  const nextLabel =
    insight?.next_refresh_at != null
      ? new Date(insight.next_refresh_at * 1000).toLocaleTimeString()
      : null;

  return (
    <section className="panel home-insight-panel">
      <div className="home-insight-head">
        <h3 className="panel-title">Building insight</h3>
        <button type="button" className="secondary-btn" disabled={loading} onClick={() => void load(true)}>
          {loading ? "Refreshing…" : "Refresh now"}
        </button>
      </div>
      <p className="home-insight-sentence">{insight?.sentence || "Loading building summary…"}</p>
      {insight?.zone_sentence ? (
        <p className="home-insight-zone">{insight.zone_sentence}</p>
      ) : null}
      {insight?.zone_temps?.struggling_zones?.length ? (
        <p className="muted home-insight-meta">
          Slow recovery zones:{" "}
          {insight.zone_temps.struggling_zones
            .map((z) => `${z.label || "?"} (${z.ahu_name || "AHU"})`)
            .join(", ")}
        </p>
      ) : null}
      <p className="muted home-insight-meta">
        {insight?.source === "ollama" ? "AI summary" : "Rule-based summary"}
        {updatedLabel ? ` · updated ${updatedLabel}` : ""}
        {nextLabel ? ` · next refresh ${nextLabel}` : ""}
        {insight?.refresh_interval_s
          ? ` · every ${Math.round(insight.refresh_interval_s / 60)} min`
          : ""}
      </p>
      {insight?.error && !insight.ollama_ok ? (
        <p className="muted home-insight-meta">Ollama offline — showing deterministic summary. Use Agent tab for chat.</p>
      ) : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
