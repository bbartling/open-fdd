import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, getBridgeBase } from "../lib/api";
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
import OperationalContextPanel from "./buildingInsight/OperationalContextPanel";

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
const ANALYTICS_POLL_MS = 15 * 60 * 1000;

/** Main dashboard — live faults (15s) + AI building insight + analytics (15 min). */
export default function BuildingInsightDashboard() {
  const { snapshot, error: streamError, live } = useDashboardStream();
  const [insight, setInsight] = useState<InsightResponse | null>(null);
  const [buildingMeta, setBuildingMeta] = useState<BuildingStatusResponse | null>(null);
  const [insightError, setInsightError] = useState("");
  const [insightLoading, setInsightLoading] = useState(false);
  const [selectedFault, setSelectedFault] = useState<DisplayFault | null>(null);
  const [edgeVersion, setEdgeVersion] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${getBridgeBase()}/api/health`)
      .then((r) => r.json())
      .then((h: { version?: string; image_tag?: string }) =>
        setEdgeVersion(h.version || h.image_tag || null),
      )
      .catch(() => setEdgeVersion(null));
  }, []);

  const loadInsight = useCallback(async (force = false) => {
    setInsightLoading(true);
    try {
      const qs = force ? "?force=true" : "";
      const res = await apiFetch<InsightResponse>(`/openfdd-agent/building-insight${qs}`);
      setInsight(res);
      setInsightError("");
    } catch (e) {
      setInsight(null);
      setInsightError(force ? formatApiError(e) : "");
    } finally {
      setInsightLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadInsight(false);
  }, [loadInsight]);

  useEffect(() => {
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
  const needsModelSetup = !faults?.model_configured && (faults?.alert_count ?? 0) === 0;

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

  const pillClass =
    healthIndex.overallTraffic === "red"
      ? "bis-pill-critical"
      : healthIndex.overallTraffic === "yellow"
        ? "bis-pill-warning"
        : "bis-pill-ok";

  return (
    <div className="bis-dashboard">
      {needsModelSetup ? (
        <div className="bis-card bis-setup-banner">
          <h3>Get started</h3>
          <p className="muted">
            No Haystack model loaded yet — stack health and gauges below reflect the live edge only.
            Sign in and import a model under{" "}
            <Link to="/model">Model &amp; assignments</Link> to enable fault detection
            and comfort analytics.
          </p>
        </div>
      ) : null}

      <BuildingStrip
        siteName="Active site"
        siteDetail={`${days}-day analytics · Open FDD`}
        edgeVersion={edgeVersion}
        equipmentCount={equipmentCount}
        pointCount={pointCount}
        activeFaults={sevCounts.total}
        faultBreakdown={faultBreakdown}
        live={live}
        lastSyncLabel="HTTP poll · 15s"
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
          {insight?.sentence ? (
            <p className="bis-insight-one-liner">{insight.sentence}</p>
          ) : insightLoading ? (
            <p className="muted bis-insight-one-liner">Loading AI building insight…</p>
          ) : null}
          {insight?.refresh_interval_s ? (
            <p className="muted bis-insight-meta">
              Insight refresh every {Math.round(insight.refresh_interval_s / 60)} min
              {insight.source === "ollama" ? " · Ollama" : insight.source === "rules" ? " · live model" : ""}
              {insight.cached ? " · cached" : ""}
            </p>
          ) : null}
        </div>

        <ComfortZonePanel
          zoneSentence={insight?.zone_sentence}
          deviceSentence={insight?.device_sentence}
          worstZones={insight?.worst_zones}
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
              {insightLoading ? "Loading…" : insight ? "Refresh insight" : "Load insight"}
            </button>
          </div>
          {displayFaults.length ? (
            <div className="bis-fault-list">
              {displayFaults.slice(0, 12).map((f) => (
                <FaultCard key={f.id} fault={f} onSelect={setSelectedFault} />
              ))}
            </div>
          ) : (
            <p className="bis-lead bis-ok-text">
              All clear — no open faults or model warnings.
              {!insight ? (
                <span className="muted"> Use Load insight for comfort analytics when the agent is enabled.</span>
              ) : null}
            </p>
          )}
        </div>

        <OperationalContextPanel
          refreshKey={snapshot?.faults.alert_count}
          analyticsPollMs={ANALYTICS_POLL_MS}
          insight={insight}
          insightError={insightError}
          buildingMeta={buildingMeta}
        />
      </div>

      <FaultDetailModal
        fault={selectedFault}
        onClose={() => setSelectedFault(null)}
        onCleared={() => window.dispatchEvent(new CustomEvent("ofdd-dashboard-refresh"))}
      />
    </div>
  );
}
