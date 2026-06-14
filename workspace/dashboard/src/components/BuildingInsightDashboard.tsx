import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { useDashboardStream } from "../lib/dashboardStream";
import { buildDisplayFaults, countBySeverity, type DisplayFault } from "../lib/displayFaults";
import { computeBuildingHealthIndex } from "../lib/healthScores";
import BuildingStrip from "./buildingInsight/BuildingStrip";
import ComfortZonePanel from "./buildingInsight/ComfortZonePanel";
import FaultCard from "./buildingInsight/FaultCard";
import FaultDetailModal from "./buildingInsight/FaultDetailModal";
import HealthGauge from "./buildingInsight/HealthGauge";
import type { InsightResponse } from "../lib/insightTypes";

type BuildingStatusResponse = {
  ok?: boolean;
  model_score?: number | null;
  model_counts?: {
    equipment?: number;
    points?: number;
  };
  alert_count?: number;
};

const INSIGHT_POLL_MS = 15 * 60 * 1000;

export default function BuildingInsightDashboard() {
  const { snapshot, error: streamError, live } = useDashboardStream();
  const [insight, setInsight] = useState<InsightResponse | null>(null);
  const [buildingMeta, setBuildingMeta] = useState<BuildingStatusResponse | null>(null);
  const [insightError, setInsightError] = useState("");
  const [insightLoading, setInsightLoading] = useState(false);
  const [selectedFault, setSelectedFault] = useState<DisplayFault | null>(null);

  const loadInsight = useCallback(async (force = false) => {
    setInsightLoading(true);
    try {
      const qs = force ? "?force=true" : "";
      const res = await apiFetch<InsightResponse>(`/openfdd-agent/building-insight${qs}`);
      setInsight(res);
      setInsightError("");
    } catch (e) {
      setInsightError(formatApiError(e));
    } finally {
      setInsightLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadInsight(false);
    const t = window.setInterval(() => void loadInsight(false), INSIGHT_POLL_MS);
    return () => window.clearInterval(t);
  }, [loadInsight]);

  useEffect(() => {
    apiFetch<BuildingStatusResponse>("/api/building/status")
      .then(setBuildingMeta)
      .catch(() => setBuildingMeta(null));
  }, [snapshot?.faults.alert_count]);

  const faults = snapshot?.faults;
  const displayFaults = useMemo(
    () => buildDisplayFaults(faults?.families || []),
    [faults?.families],
  );
  const sevCounts = useMemo(() => countBySeverity(displayFaults), [displayFaults]);

  const poll = insight?.device_poll_health;
  const deviceSentenceMatch = insight?.device_sentence?.match(/(\d+)\/(\d+)/);
  const parsedTotal = deviceSentenceMatch ? Number(deviceSentenceMatch[2]) : NaN;
  const totalDevices =
    Number.isFinite(parsedTotal) && parsedTotal > 0
      ? parsedTotal
      : (poll?.healthy_count ?? 0) + (poll?.offline_equipment?.length ?? 0) + (poll?.flaky_equipment?.length ?? 0);
  const healthyRatio =
    totalDevices > 0 && poll?.healthy_count != null ? poll.healthy_count / totalDevices : undefined;

  const healthIndex = useMemo(
    () =>
      computeBuildingHealthIndex(
        displayFaults.flatMap((d) => d.underlying),
        {
          struggling_zone_count: insight?.zone_temps?.struggling_zones?.length,
          worst_zone_count: insight?.worst_zones?.length,
          zone_sensor_count: insight?.zone_temps?.zone_sensor_count,
          opportunity_count: insight?.zone_temps?.research?.opportunities?.length,
          healthy_device_ratio: healthyRatio,
          historian_lag_count: displayFaults.find((d) => d.id === "group-historian-lag")?.underlying
            .length,
          offline_device_count: poll?.offline_equipment?.length,
          flaky_device_count: poll?.flaky_equipment?.length,
          model_score: buildingMeta?.model_score ?? undefined,
        },
      ),
    [displayFaults, insight, poll, healthyRatio, buildingMeta?.model_score],
  );

  const equipmentCount =
    buildingMeta?.model_counts?.equipment ?? insight?.brick_model?.equipment_count;
  const pointCount = buildingMeta?.model_counts?.points;

  const faultBreakdown =
    sevCounts.total === 0
      ? "all clear"
      : [
          sevCounts.critical ? `${sevCounts.critical} critical` : "",
          sevCounts.high ? `${sevCounts.high} high` : "",
          sevCounts.medium ? `${sevCounts.medium} medium` : "",
        ]
          .filter(Boolean)
          .join(" · ");

  const days = insight?.lookback_days ?? 14;
  const updatedLabel =
    insight?.generated_at != null
      ? new Date(insight.generated_at * 1000).toLocaleString()
      : null;

  if (streamError && !snapshot) {
    return (
      <div className="bis-dashboard">
        <div className="bis-card">
          <p className="error">Could not load building status: {streamError}</p>
        </div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="bis-dashboard">
        <div className="bis-card">
          <p className="muted">Loading building dashboard…</p>
        </div>
      </div>
    );
  }

  if (!faults?.model_configured && faults.alert_count === 0) {
    return (
      <div className="bis-dashboard">
        <div className="bis-card">
          <h2>Building insight</h2>
          <p className="muted">No building model configured yet.</p>
          <p className="muted">
            Import a BRICK model under <Link to="/model">Model & assignments</Link> to enable fault
            detection and comfort analytics.
          </p>
        </div>
      </div>
    );
  }

  const pillClass =
    healthIndex.overallTraffic === "red"
      ? "bis-pill-critical"
      : healthIndex.overallTraffic === "yellow"
        ? "bis-pill-warning"
        : "bis-pill-ok";

  return (
    <div className="bis-dashboard">
      <BuildingStrip
        siteName="Active site"
        siteDetail={`${days}-day analytics · Open FDD`}
        equipmentCount={equipmentCount}
        pointCount={pointCount}
        activeFaults={sevCounts.total}
        faultBreakdown={faultBreakdown}
        live={live}
        lastSyncLabel={live ? "WebSocket" : "HTTP poll"}
      />

      <div className="bis-row bis-row-2">
        <div className="bis-card bis-health-card">
          <h3>Building health index</h3>
          <h2>Comfort · Efficiency · Reliability</h2>
          <p className="bis-card-sub">
            Ordered for operators: comfort first, then efficiency, then reliability and data model
            completeness.
          </p>
          <div className={`bis-overall-pill ${pillClass}`}>
            <span className="bis-pill-dot" />
            <div className="bis-pill-txt">
              <strong>Overall: {healthIndex.overallLabel}</strong> — {healthIndex.summaryLine}
            </div>
            <div className="bis-pill-grade">{healthIndex.overall}</div>
          </div>
          <div className="bis-gauge-grid">
            {healthIndex.pillars.map((p) => (
              <HealthGauge
                key={p.key}
                label={p.label}
                score={p.score}
                color={p.color}
                deltaLabel={p.deltaLabel}
              />
            ))}
          </div>
          {insight?.sentence ? <p className="bis-insight-one-liner">{insight.sentence}</p> : null}
        </div>

        <ComfortZonePanel
          zoneSentence={insight?.zone_sentence}
          deviceSentence={insight?.device_sentence}
          worstZones={insight?.worst_zones}
          zoneSystems={insight?.zone_systems}
          opportunities={insight?.zone_temps?.research?.opportunities}
          lookbackDays={days}
        />
      </div>

      <div className="bis-row bis-row-2 bis-row-mt">
        <div className="bis-card">
          <div className="bis-card-head-row">
            <div>
              <h3>Prioritized issues</h3>
              <h2>
                Plain-language alerts{" "}
                <span className="bis-hint">click for detail</span>
              </h2>
            </div>
            <button
              type="button"
              className="bis-btn bis-btn-secondary"
              disabled={insightLoading}
              onClick={() => void loadInsight(true)}
            >
              {insightLoading ? "Refreshing…" : "Refresh insight"}
            </button>
          </div>
          {displayFaults.length ? (
            <div className="bis-fault-list">
              {displayFaults.slice(0, 12).map((f) => (
                <FaultCard key={f.id} fault={f} onSelect={setSelectedFault} />
              ))}
            </div>
          ) : (
            <p className="bis-lead bis-ok-text">All clear — no open faults or model warnings.</p>
          )}
        </div>

        <div className="bis-card">
          <h3>Devices with issues</h3>
          {insight?.faults_linked?.length ? (
            <ul className="bis-device-faults">
              {insight.faults_linked.slice(0, 8).map((f, i) => (
                <li key={`${f.equipment_id || f.equipment_name}-${f.symptom}-${i}`}>
                  <div className="bis-device-fault-head">
                    <strong className="bis-device-name">{f.equipment_name || "Unknown device"}</strong>
                    {f.data_source ? <span className="bis-source-badge">{f.data_source}</span> : null}
                  </div>
                  <div className="bis-device-symptom">{f.short_description || f.symptom || f.rule_name}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No active FDD faults on modeled devices.</p>
          )}
          {insight?.brick_model?.feeds_chains?.length ? (
            <p className="bis-muted-line bis-foot-feeds">
              <strong>BRICK feeds:</strong> {insight.brick_model.feeds_chains.slice(0, 4).join("; ")}
              {(insight.brick_model.feeds_chains.length ?? 0) > 4 ? " …" : ""}
            </p>
          ) : null}
          {insight?.zone_temps?.struggling_zones?.length ? (
            <p className="bis-muted-line">
              <strong>Slow recovery:</strong>{" "}
              {insight.zone_temps.struggling_zones
                .slice(0, 4)
                .map((z) => `${z.label || "?"} (${z.ahu_name || "AHU"})`)
                .join(", ")}
            </p>
          ) : null}
          <p className="bis-foot-meta">
            {insight?.source === "ollama" ? "AI summary" : "Rule-based summary"}
            {updatedLabel ? ` · updated ${updatedLabel}` : ""}
            {insight?.refresh_interval_s
              ? ` · every ${Math.round(insight.refresh_interval_s / 60)} min`
              : ""}
          </p>
          {insightError ? <p className="error">{insightError}</p> : null}
        </div>
      </div>

      <FaultDetailModal fault={selectedFault} onClose={() => setSelectedFault(null)} />
    </div>
  );
}
