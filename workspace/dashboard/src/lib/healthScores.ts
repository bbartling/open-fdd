import type { Traffic } from "../components/TrafficLight";
import type { FaultAlert } from "./dashboardStream";

export type PillarKey = "comfort" | "efficiency" | "reliability" | "maintenance";

export type PillarScore = {
  key: PillarKey;
  label: string;
  score: number;
  deltaLabel?: string;
  color: string;
};

export type BuildingHealthIndex = {
  pillars: PillarScore[];
  overall: number;
  overallTraffic: Traffic;
  overallLabel: string;
  summaryLine: string;
};

const PILLAR_META: Record<PillarKey, { label: string; order: number }> = {
  comfort: { label: "Comfort", order: 0 },
  efficiency: { label: "Efficiency", order: 1 },
  reliability: { label: "Reliability", order: 2 },
  maintenance: { label: "Data model", order: 3 },
};

function scoreColor(score: number): string {
  if (score >= 80) return "var(--bis-green, #2a9d4e)";
  if (score >= 65) return "var(--bis-yellow, #e6a500)";
  return "var(--bis-red, #d94545)";
}

function trafficFromScore(score: number): Traffic {
  if (score >= 80) return "green";
  if (score >= 60) return "yellow";
  return "red";
}

function clamp(n: number): number {
  return Math.max(0, Math.min(100, Math.round(n)));
}

export type InsightScoreInput = {
  struggling_zone_count?: number;
  worst_zone_count?: number;
  zone_sensor_count?: number;
  opportunity_count?: number;
  healthy_device_ratio?: number;
  historian_lag_count?: number;
  offline_device_count?: number;
  flaky_device_count?: number;
  model_score?: number | null;
  fdd_critical?: number;
  fdd_warning?: number;
};

function countFaultsByKind(alerts: FaultAlert[]) {
  let fddCritical = 0;
  let fddWarning = 0;
  let historianLag = 0;
  let offlinePoll = 0;
  let flakyPoll = 0;
  let modelWarn = 0;
  let comfortish = 0;
  let efficiencyish = 0;

  for (const a of alerts) {
    const src = String(a.source || "");
    const sev = String(a.severity || "warning");
    const code = String(a.code || "").toUpperCase();
    const title = String(a.title || "").toLowerCase();

    if (src === "poll_health") {
      if (title.includes("historian")) historianLag += 1;
      else if (title.includes("offline") || title.includes("no recent")) offlinePoll += 1;
      else if (title.includes("flaky")) flakyPoll += 1;
      continue;
    }
    if (src === "model_health") {
      modelWarn += 1;
      continue;
    }
    if (sev === "critical") fddCritical += 1;
    else fddWarning += 1;

    if (
      code.includes("SENSOR") ||
      title.includes("sensor") ||
      title.includes("zone") ||
      title.includes("temperature")
    ) {
      comfortish += 1;
    }
    if (
      code.includes("SIMULT") ||
      title.includes("heat") ||
      title.includes("cool") ||
      title.includes("economizer") ||
      title.includes("setback") ||
      title.includes("schedule") ||
      title.includes("after hours")
    ) {
      efficiencyish += 1;
    }
  }

  return {
    fddCritical,
    fddWarning,
    historianLag,
    offlinePoll,
    flakyPoll,
    modelWarn,
    comfortish,
    efficiencyish,
  };
}

export function computeBuildingHealthIndex(
  alerts: FaultAlert[],
  insight?: InsightScoreInput | null,
): BuildingHealthIndex {
  const counts = countFaultsByKind(alerts);
  const ins = insight || {};

  let comfort = 92;
  comfort -= Math.min(24, (ins.struggling_zone_count ?? 0) * 6);
  comfort -= Math.min(12, (ins.worst_zone_count ?? 0) * 2);
  comfort -= Math.min(20, counts.comfortish * 8);
  comfort -= Math.min(15, counts.fddCritical * 5);

  let efficiency = 88;
  efficiency -= Math.min(20, (ins.opportunity_count ?? 0) * 5);
  efficiency -= Math.min(30, counts.efficiencyish * 10);
  efficiency -= Math.min(20, counts.fddWarning * 3);

  let reliability = 90;
  const totalDevices = Math.max(
    1,
    (ins.historian_lag_count ?? 0) +
      (ins.offline_device_count ?? 0) +
      (ins.flaky_device_count ?? 0) +
      (ins.healthy_device_ratio != null ? 1 : 0),
  );
  if (ins.healthy_device_ratio != null) {
    reliability = 40 + ins.healthy_device_ratio * 60;
  }
  reliability -= Math.min(35, counts.historianLag * 3);
  reliability -= Math.min(40, counts.offlinePoll * 12);
  reliability -= Math.min(16, counts.flakyPoll * 8);
  reliability -= Math.min(25, counts.fddCritical * 8);

  let maintenance = ins.model_score != null ? ins.model_score : 85;
  maintenance -= Math.min(15, counts.modelWarn * 2);

  const pillars: PillarScore[] = (Object.keys(PILLAR_META) as PillarKey[])
    .sort((a, b) => PILLAR_META[a].order - PILLAR_META[b].order)
    .map((key) => {
      const raw =
        key === "comfort"
          ? comfort
          : key === "efficiency"
            ? efficiency
            : key === "reliability"
              ? reliability
              : maintenance;
      const score = clamp(raw);
      return {
        key,
        label: PILLAR_META[key].label,
        score,
        color: scoreColor(score),
        deltaLabel:
          key === "reliability" && ins.healthy_device_ratio != null
            ? `${Math.round(ins.healthy_device_ratio * 100)}% devices healthy`
            : undefined,
      };
    });

  const overall = clamp(
    pillars[0].score * 0.35 +
      pillars[1].score * 0.25 +
      pillars[2].score * 0.25 +
      pillars[3].score * 0.15,
  );
  const overallTraffic = trafficFromScore(overall);
  const issueCount = alerts.length;
  const overallLabel =
    overallTraffic === "green"
      ? "Green"
      : overallTraffic === "yellow"
        ? "Yellow"
        : "Red";

  let summaryLine = "Telemetry and model look healthy.";
  if (issueCount > 0) {
    const parts: string[] = [];
    if (counts.historianLag) parts.push(`${counts.historianLag} historian lag`);
    if (counts.offlinePoll) parts.push(`${counts.offlinePoll} offline`);
    if (counts.fddCritical + counts.fddWarning)
      parts.push(`${counts.fddCritical + counts.fddWarning} FDD`);
    if (counts.modelWarn) parts.push("model gaps");
    summaryLine =
      parts.length > 0
        ? `${issueCount} active item${issueCount === 1 ? "" : "s"} — ${parts.join(", ")}.`
        : `${issueCount} item${issueCount === 1 ? "" : "s"} need attention.`;
  }

  return { pillars, overall, overallTraffic, overallLabel, summaryLine };
}
