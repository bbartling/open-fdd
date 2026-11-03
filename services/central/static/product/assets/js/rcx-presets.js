import { postAnalytics } from "./analytics.js";
import { analyticsWindowFromSampling } from "./window-policy.js";
import { displayTempC, displayDeltaC, tempAxisLabel } from "./role-units.js";
import {
  ECONOMIZER_DT_MIN_C,
  normalizeTipOverviewEnvelope,
  isIdentifiablePoint,
  tipOatBinLo,
} from "./tip-analytics-normalize.js";

export { ECONOMIZER_DT_MIN_C };

export const OVERVIEW_RCX_PRESET_IDS = [
  "ahu_motor_weekly",
  "economizer_delta",
  "economizer_mat_resid",
  "economizer_temps_overlay",
  "boiler_motor_weekly",
  "chiller_motor_weekly",
  "mech_cooling_oat_bins",
  "bas_vs_web_oat",
];

const PLANT_FOR = {
  ahu_motor_weekly: "air",
  boiler_motor_weekly: "boiler",
  chiller_motor_weekly: "chiller",
};

function analyticsPostBody(buildingId, window, refresh) {
  return {
    building_id: buildingId,
    max_points: 4000,
    dt_min_c: ECONOMIZER_DT_MIN_C,
    ...window,
    ...(refresh ? { refresh: true } : {}),
  };
}

function econEmptyMessage() {
  return `No qualified economizer samples. Fan-on proof, |OAT−RAT| ≥ ${ECONOMIZER_DT_MIN_C.toFixed(1)} °C, and a measured MAT are required.`;
}

export async function loadOverviewRcxPreset(buildingId, presetId, mapping, refresh) {
  const window = analyticsWindowFromSampling(mapping?.equipment ?? []);
  const body = analyticsPostBody(buildingId, window, refresh);
  const unitSystem = "metric";

  if (presetId in PLANT_FOR) {
    const env = normalizeTipOverviewEnvelope(
      "runtime",
      await postAnalytics("/api/analytics/runtime", body),
    );
    const chart = weeklyMotorChart(env.rows ?? [], PLANT_FOR[presetId]);
    return {
      chart,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env.warnings?.[0] ?? "No motor weekly series for this plant.",
      env,
    };
  }
  if (presetId === "mech_cooling_oat_bins") {
    const env = normalizeTipOverviewEnvelope(
      "mechanical-cooling",
      await postAnalytics("/api/analytics/mechanical-cooling", body),
    );
    const chart = mechCoolingChart(env.rows ?? []);
    return {
      chart,
      lineSeries: [],
      error: chart
        ? undefined
        : env.warnings?.[0] ??
          "No mechanical-cooling outdoor-air bins. Compressor or chiller status with outdoor air is required.",
      env,
    };
  }
  if (
    presetId === "economizer_delta" ||
    presetId === "economizer_mat_resid" ||
    presetId === "economizer_temps_overlay"
  ) {
    const env = normalizeTipOverviewEnvelope(
      "economizer",
      await postAnalytics("/api/analytics/economizer", body),
      { dtMinC: body.dt_min_c },
    );
    const points = env.points ?? [];
    if (presetId === "economizer_delta") {
      const chart = economizerDeltaChart(points, unitSystem);
      return {
        chart,
        lineSeries: [],
        error: chart ? undefined : env.warnings?.[0] ?? econEmptyMessage(),
        env,
      };
    }
    if (presetId === "economizer_mat_resid") {
      const chart = economizerMatResidChart(points, unitSystem);
      return {
        chart,
        lineSeries: chart?.lineSeries ?? [],
        error: chart ? undefined : env.warnings?.[0] ?? econEmptyMessage(),
        env,
      };
    }
    const chart = economizerTempsOverlayChart(points, unitSystem);
    return {
      chart,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env.warnings?.[0] ?? econEmptyMessage(),
      env,
    };
  }
  if (presetId === "bas_vs_web_oat") {
    const raw = await postAnalytics("/api/analytics/bas-vs-web-oat", body);
    const env = normalizeTipOverviewEnvelope("bas-vs-web-oat", raw);
    const chart = basVsWebChart(env.points ?? [], unitSystem);
    const companion = basVsWebHistChart(raw.rows ?? [], unitSystem);
    return {
      chart,
      companion,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env.warnings?.[0] ?? "No coincident BAS and web outdoor-air samples for this site and window.",
      env,
    };
  }
  return { chart: null, lineSeries: [], error: "Unknown preset.", env: null };
}

function weeklyMotorChart(rows, plantGroup) {
  const filtered = rows.filter(
    (r) =>
      String(r.kind) === "weekly_equipment" &&
      String(r.plant_group || "").toLowerCase() === plantGroup,
  );
  const byEquip = new Map();
  for (const r of filtered) {
    const id = r.equipment_id || r.label;
    const week = r.week_label || r.week;
    const hours = Number(r.run_hours ?? r.runtime_hours);
    if (!id || !week || !Number.isFinite(hours)) continue;
    if (!byEquip.has(id)) byEquip.set(id, []);
    byEquip.get(id).push([week, hours]);
  }
  if (!byEquip.size) return null;
  const series = [...byEquip.entries()].map(([name, data]) => ({
    name,
    type: "bar",
    data: data.sort((a, b) => String(a[0]).localeCompare(String(b[0]))),
  }));
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c9d2e8" } },
      xAxis: { type: "category", axisLabel: { color: "#8899bb" } },
      yAxis: { type: "value", name: "run hours", axisLabel: { color: "#8899bb" } },
      series,
    },
    lineSeries: [],
  };
}

function mechCoolingChart(rows) {
  const bins = rows
    .filter((r) => String(r.kind) === "oat_bin")
    .map((r) => ({
      label: r.oat_bin || r.bin_label,
      hours: Number(r.run_hours ?? r.hours),
      sort: tipOatBinLo(String(r.oat_bin || r.bin_label || "")),
    }))
    .filter((b) => b.label && Number.isFinite(b.hours))
    .sort((a, b) => a.sort - b.sort);
  if (!bins.length) return null;
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: bins.map((b) => b.label), axisLabel: { color: "#8899bb" } },
      yAxis: { type: "value", name: "hours", axisLabel: { color: "#8899bb" } },
      series: [{ type: "bar", data: bins.map((b) => b.hours), itemStyle: { color: "#4361ee" } }],
    },
    lineSeries: [],
  };
}

function economizerDeltaChart(points, unitSystem) {
  const usable = points.filter(
    (p) =>
      isIdentifiablePoint(p) &&
      p.delta_or_c != null &&
      p.delta_mr_c != null,
  );
  if (usable.length < 5) return null;
  const data = usable.map((p) => [
    displayDeltaC(p.delta_or_c, unitSystem),
    displayDeltaC(p.delta_mr_c, unitSystem),
  ]);
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "item" },
      xAxis: { name: "OAT−RAT", axisLabel: { color: "#8899bb" } },
      yAxis: { name: "MAT−RAT", axisLabel: { color: "#8899bb" } },
      series: [{ type: "scatter", data, symbolSize: 6, itemStyle: { color: "#43aa8b" } }],
    },
    lineSeries: [],
  };
}

function economizerMatResidChart(points, unitSystem) {
  const usable = points.filter((p) => isIdentifiablePoint(p) && p.mat_resid_c != null);
  if (usable.length < 5) return null;
  const lineSeries = [];
  const byEq = new Map();
  for (const p of usable) {
    const eq = p.equipment_id || "AHU";
    if (!byEq.has(eq)) byEq.set(eq, []);
    byEq.get(eq).push(p);
  }
  const series = [];
  for (const [eq, rows] of byEq) {
    const data = rows
      .map((r) => [r.timestamp_utc, displayDeltaC(r.mat_resid_c, unitSystem)])
      .filter((d) => d[0]);
    lineSeries.push({ name: eq, data });
    series.push({ name: eq, type: "line", showSymbol: false, data });
  }
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      xAxis: { type: "time", axisLabel: { color: "#8899bb" } },
      yAxis: { name: tempAxisLabel(unitSystem), axisLabel: { color: "#8899bb" } },
      legend: { textStyle: { color: "#c9d2e8" } },
      series,
    },
    lineSeries,
  };
}

function economizerTempsOverlayChart(points, unitSystem) {
  const usable = points.filter((p) => isIdentifiablePoint(p));
  const roles = [
    ["OAT", "oa_t"],
    ["RAT", "rat"],
    ["MAT", "mat"],
    ["SAT", "sat"],
    ["OA damper %", "damper_fb_pct"],
  ];
  const lineSeries = [];
  const series = [];
  for (const [label, key] of roles) {
    const data = [];
    for (const p of usable) {
      const t = p.timestamp_utc;
      let v = p[key];
      if (t == null || v == null) continue;
      if (key !== "damper_fb_pct") v = displayTempC(v, unitSystem);
      data.push([t, v]);
    }
    if (!data.length) continue;
    lineSeries.push({ name: label, data });
    series.push({ name: label, type: "line", showSymbol: false, data });
  }
  if (!series.length) return null;
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c9d2e8" } },
      xAxis: { type: "time", axisLabel: { color: "#8899bb" } },
      yAxis: { name: tempAxisLabel(unitSystem), axisLabel: { color: "#8899bb" } },
      series,
    },
    lineSeries,
  };
}

function basVsWebChart(points, unitSystem) {
  const lineSeries = [];
  const bas = points
    .filter((p) => p.bas_oat_c != null)
    .map((p) => [p.timestamp_utc, displayTempC(p.bas_oat_c, unitSystem)]);
  const web = points
    .filter((p) => p.web_oat_c != null)
    .map((p) => [p.timestamp_utc, displayTempC(p.web_oat_c, unitSystem)]);
  if (!bas.length && !web.length) return null;
  const series = [];
  if (bas.length) {
    lineSeries.push({ name: "BAS OAT", data: bas });
    series.push({ name: "BAS OAT", type: "line", showSymbol: false, data: bas });
  }
  if (web.length) {
    lineSeries.push({ name: "Web OAT", data: web });
    series.push({ name: "Web OAT", type: "line", showSymbol: false, data: web });
  }
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c9d2e8" } },
      xAxis: { type: "time", axisLabel: { color: "#8899bb" } },
      yAxis: { name: tempAxisLabel(unitSystem), axisLabel: { color: "#8899bb" } },
      series,
    },
    lineSeries,
  };
}

function basVsWebHistChart(rows, unitSystem) {
  const histRows = rows.filter(
    (r) => String(r.kind) === "delta_hist" || r.count != null,
  );
  if (!histRows.length) return null;
  const sorted = [...histRows].sort(
    (a, b) => (Number(a.bin_lo_f) || 0) - (Number(b.bin_lo_f) || 0),
  );
  const labels = sorted.map((r) => {
    const lo = Number(r.bin_lo_f);
    return Number.isFinite(lo) ? String(displayDeltaC(lo, unitSystem)) : String(r.bin_label || "");
  });
  const counts = sorted.map((r) => Number(r.count)).filter(Number.isFinite);
  if (!counts.length) return null;
  return {
    option: {
      backgroundColor: "transparent",
      title: {
        text: "BAS vs web outdoor-air temperature deviation",
        textStyle: { color: "#c9d2e8", fontSize: 12 },
      },
      xAxis: { type: "category", data: labels, axisLabel: { color: "#8899bb" } },
      yAxis: { type: "value", name: "count", axisLabel: { color: "#8899bb" } },
      series: [{ type: "bar", data: counts, itemStyle: { color: "#f8961e" } }],
    },
    lineSeries: [],
  };
}
