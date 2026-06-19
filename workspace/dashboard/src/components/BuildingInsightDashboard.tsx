import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, hasToken } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import { useDashboardStream } from "../lib/dashboardStream";
import { buildDisplayFaults, countBySeverity, faultAlertIds, type DisplayFault } from "../lib/displayFaults";
import { computeBuildingHealthIndex } from "../lib/healthScores";
import BuildingStrip from "./buildingInsight/BuildingStrip";
import ComfortZonePanel from "./buildingInsight/ComfortZonePanel";
import FaultCard from "./buildingInsight/FaultCard";
import FddRulesInServicePanel from "./buildingInsight/FddRulesInServicePanel";
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
  const [canClearAlarms, setCanClearAlarms] = useState(false);
  const [clearingId, setClearingId] = useState<string | null>(null);
  const [clearError, setClearError] = useState("");

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

  useEffect(() => {
    if (!hasToken()) {
      setCanClearAlarms(false);
      return;
    }
    apiFetch<{ role?: string }>("/api/auth/me")
      .then((me) => {
        const role = String(me.role || "").toLowerCase();
        setCanClearAlarms(role === "operator" || role === "integrator" || role === "agent");
      })
      .catch(() => setCanClearAlarms(false));
  }, [snapshot?.faults.alert_count]);

  const clearFault = useCallback(async (fault: DisplayFault) => {
    setClearError("");
    setClearingId(fault.id);
    try {
      await apiFetch("/api/faults/clear", {
        method: "POST",
        body: JSON.stringify({ alert_ids: faultAlertIds(fault) }),
      });
      if (selectedFault?.id === fault.id) setSelectedFault(null);
    } catch (e) {
      setClearError(formatApiError(e));
    } finally {
      setClearingId(null);
    }
  }, [selectedFault?.id]);

  const faults = snapshot?.faults;
  const displayFaults = useMemo(() => buildDisplayFaults(faults?.families || []), [faults?.families]);
  const operatorOverrideCount = useMemo(
    () => displayFaults.find((f) => f.id === "group-bacnet-overrides")?.underlying.length ?? 0,
    [displayFaults],
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
        siteDetail={`${days}-day analytics`}
        equipmentCount={equipmentCount}
        pointCount={pointCount}
        activeFaults={sevCounts.total}
        faultBreakdown={faultBreakdown}
        operatorOverrideCount={operatorOverrideCount}
        live={live}
        lastSyncLabel={live ? "Live" : "Polling"}
      />

      <div className="bis-row bis-row-2">
        <div className="bis-card bis-health-card">
          <h3>Building health</h3>
          <p className="bis-card-sub bis-card-sub-compact">
            Comfort · efficiency · reliability
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
                <FaultCard
                  key={f.id}
                  fault={f}
                  onSelect={setSelectedFault}
                  canClear={canClearAlarms}
                  clearing={clearingId === f.id}
                  onClear={(fault) => void clearFault(fault)}
                />
              ))}
            </div>
          ) : (
            <p className="bis-lead bis-ok-text">All clear — no open faults or model warnings.</p>
          )}
          {clearError ? <p className="error">{clearError}</p> : null}
          {insightError ? <p className="error">{insightError}</p> : null}
        </div>

        <FddRulesInServicePanel />
      </div>

      <FaultDetailModal
        fault={selectedFault}
        onClose={() => setSelectedFault(null)}
        canClear={canClearAlarms}
        clearing={selectedFault ? clearingId === selectedFault.id : false}
        onClear={(fault) => void clearFault(fault)}
      />
    </div>
  );
}
