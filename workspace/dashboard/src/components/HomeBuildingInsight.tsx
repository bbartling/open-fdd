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
  device_sentence?: string;
  lookback_days?: number;
  methodology?: {
    lookback_days?: number;
    zone_temperatures?: string;
    recovery_rates?: string;
    device_poll_health?: string;
  };
  fault_sentences?: string[];
  worst_zones?: { label?: string; day_avg_f?: number; night_avg_f?: number; recovery_f_per_min?: number }[];
  zone_temps?: {
    topology_mode?: string;
    zone_sensor_count?: number;
    struggling_zones?: { label?: string; ahu_name?: string; reason?: string }[];
    refresh_interval_s?: number;
  };
  device_poll_health?: {
    healthy_count?: number;
    offline_equipment?: { equipment_name?: string; points_stale?: number; points_polled?: number }[];
    flaky_equipment?: { equipment_name?: string; max_flips_per_day?: number }[];
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
  const days = insight?.lookback_days ?? 14;

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
      {insight?.device_sentence ? (
        <p className="home-insight-zone">{insight.device_sentence}</p>
      ) : null}
      {insight?.worst_zones?.length ? (
        <p className="muted home-insight-meta">
          Worst zones ({days}d):{" "}
          {insight.worst_zones
            .map((z) => {
              const parts = [z.label || "?"];
              if (z.night_avg_f != null && z.day_avg_f != null) {
                parts.push(`night ${z.night_avg_f}°F / day ${z.day_avg_f}°F`);
              }
              if (z.recovery_f_per_min != null) {
                parts.push(`recovery ${z.recovery_f_per_min}°F/min`);
              }
              return parts.join(" — ");
            })
            .join("; ")}
        </p>
      ) : null}
      {insight?.device_poll_health?.offline_equipment?.length ? (
        <p className="muted home-insight-meta">
          Offline devices:{" "}
          {insight.device_poll_health.offline_equipment.map((e) => e.equipment_name || "?").join(", ")}
        </p>
      ) : null}
      {insight?.device_poll_health?.flaky_equipment?.length ? (
        <p className="muted home-insight-meta">
          Flaky poll:{" "}
          {insight.device_poll_health.flaky_equipment
            .map((e) => `${e.equipment_name} (${e.max_flips_per_day ?? "?"} flips/d)`)
            .join(", ")}
        </p>
      ) : null}
      {insight?.fault_sentences?.length ? (
        <ul className="home-insight-faults muted">
          {insight.fault_sentences.slice(0, 8).map((line) => (
            <li key={line.slice(0, 80)}>{line}</li>
          ))}
        </ul>
      ) : null}
      {insight?.zone_temps?.struggling_zones?.length ? (
        <p className="muted home-insight-meta">
          Slow recovery:{" "}
          {insight.zone_temps.struggling_zones
            .map((z) => `${z.label || "?"} (${z.ahu_name || "AHU"})`)
            .join(", ")}
        </p>
      ) : null}
      <p className="muted home-insight-meta">
        {insight?.source === "ollama" ? "AI summary" : "Rule-based summary"}
        {` · ${days}-day historian window`}
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
