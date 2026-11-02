import { postAnalytics } from "./analytics.js";
import { analyticsWindowFromSampling } from "./window-policy.js";
import { displayTempC, tempAxisLabel } from "./role-units.js";

export const ECONOMIZER_DT_MIN_C = 50 / 9;

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

function econEmptyMessage() {
  return `No qualified economizer samples. Fan-on proof, |OAT−RAT| ≥ ${ECONOMIZER_DT_MIN_C.toFixed(1)} °C, and a measured MAT are required.`;
}

function analyticsBody(buildingId, window, refresh) {
  return {
    building_id: buildingId,
    max_points: 4000,
    dt_min_c: ECONOMIZER_DT_MIN_C,
    ...window,
    ...(refresh ? { refresh: true } : {}),
  };
}

export async function loadOverviewRcxPreset(buildingId, presetId, mapping, refresh) {
  const window = analyticsWindowFromSampling(mapping?.equipment ?? []);
  const body = analyticsBody(buildingId, window, refresh);
  const unitSystem = "metric";

  if (presetId in PLANT_FOR) {
    const env = await postAnalytics("/api/analytics/runtime", body);
    const chart = weeklyMotorChart(env?.rows ?? [], PLANT_FOR[presetId]);
    return {
      chart,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env?.warnings?.[0] ?? "No motor weekly series for this plant.",
      env,
    };
  }
  if (presetId === "mech_cooling_oat_bins") {
    const env = await postAnalytics("/api/analytics/mechanical-cooling", body);
    const chart = mechCoolingChart(env?.rows ?? []);
    return {
      chart,
      lineSeries: chart?.lineSeries ?? [],
      error: chart
        ? undefined
        : env?.warnings?.[0] ?? "No mechanical-cooling outdoor-air bins.",
      env,
    };
  }
  if (
    presetId === "economizer_delta" ||
    presetId === "economizer_mat_resid" ||
    presetId === "economizer_temps_overlay"
  ) {
    const env = await postAnalytics("/api/analytics/economizer", body);
    const points = env?.points ?? env?.rows ?? [];
    if (presetId === "economizer_delta") {
      const chart = economizerDeltaChart(points, unitSystem);
      return {
        chart,
        lineSeries: [],
        error: chart ? undefined : env?.warnings?.[0] ?? econEmptyMessage(),
        env,
      };
    }
    if (presetId === "economizer_mat_resid") {
      const chart = economizerMatResidChart(points, unitSystem);
      return {
        chart,
        lineSeries: chart?.lineSeries ?? [],
        error: chart ? undefined : env?.warnings?.[0] ?? econEmptyMessage(),
        env,
      };
    }
    const chart = economizerTempsOverlayChart(points, unitSystem);
    return {
      chart,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env?.warnings?.[0] ?? econEmptyMessage(),
      env,
    };
  }
  if (presetId === "bas_vs_web_oat") {
    const env = await postAnalytics("/api/analytics/bas-vs-web-oat", body);
    const chart = basVsWebChart(env?.rows ?? [], unitSystem);
    const companion = basVsWebHistChart(env?.rows ?? [], unitSystem);
    return {
      chart,
      companion,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env?.warnings?.[0] ?? "No BAS vs web OAT overlay.",
      env,
    };
  }
  return { chart: null, lineSeries: [], error: "Unknown preset.", env: null };
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function ts(row) {
  return row.timestamp_utc || row.ts || row.time;
}

function weeklyMotorChart(rows, plantGroup) {
  const filtered = rows.filter((r) => {
    const pg = String(r.plant_group || r.kind || "").toLowerCase();
    return pg === plantGroup || pg === "ahu" && plantGroup === "air";
  });
  const byEquip = new Map();
  for (const r of filtered) {
    const id = r.equipment_id || r.label;
    const week = r.week_label || r.week;
    const hours = num(r.run_hours ?? r.runtime_hours);
    if (!id || !week || hours == null) continue;
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
    .map((r) => ({
      label: r.oat_bin || r.bin_label,
      hours: num(r.run_hours ?? r.hours),
    }))
    .filter((b) => b.label && b.hours != null)
    .sort((a, b) => String(a.label).localeCompare(String(b.label)));
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

function pickPoint(row, ...keys) {
  for (const k of keys) {
    const v = num(row[k]);
    if (v != null) return v;
  }
  return null;
}

function economizerDeltaChart(points, unitSystem) {
  const data = [];
  for (const p of points) {
    const oat = pickPoint(p, "oa_t", "oat", "bas_oat_c");
    const rat = pickPoint(p, "rat", "return_air_t");
    const mat = pickPoint(p, "mat", "mixed_air_t");
    if (oat == null || rat == null || mat == null) continue;
    if (Math.abs(oat - rat) < ECONOMIZER_DT_MIN_C) continue;
    data.push([displayTempC(oat - rat, unitSystem), displayTempC(mat - rat, unitSystem)]);
  }
  if (!data.length) return null;
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
  const lineSeries = [];
  const xs = [];
  const ys = [];
  for (const p of points) {
    const t = ts(p);
    const mat = pickPoint(p, "mat", "mixed_air_t");
    const resid = pickPoint(p, "mat_residual", "mat_resid");
    if (!t || resid == null) continue;
    xs.push(t);
    ys.push(displayTempC(resid, unitSystem));
  }
  if (!xs.length) return null;
  lineSeries.push({ name: "MAT residual", data: xs.map((x, i) => [x, ys[i]]) });
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      xAxis: { type: "time", axisLabel: { color: "#8899bb" } },
      yAxis: { name: tempAxisLabel(unitSystem), axisLabel: { color: "#8899bb" } },
      series: [{ name: "MAT residual", type: "line", showSymbol: false, data: lineSeries[0].data }],
    },
    lineSeries,
  };
}

function economizerTempsOverlayChart(points, unitSystem) {
  const roles = [
    ["OAT", "oa_t"],
    ["RAT", "rat"],
    ["MAT", "mat"],
    ["SAT", "sat"],
    ["OA damper %", "oa_damper_pct"],
  ];
  const lineSeries = [];
  const series = [];
  for (const [label, key] of roles) {
    const data = [];
    for (const p of points) {
      const t = ts(p);
      let v = pickPoint(p, key);
      if (v == null) continue;
      if (key !== "oa_damper_pct") v = displayTempC(v, unitSystem);
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

function basVsWebChart(rows, unitSystem) {
  const lineSeries = [];
  const bas = [];
  const web = [];
  for (const r of rows) {
    const t = ts(r);
    const b = pickPoint(r, "bas_oat_c", "bas_oa_t", "oa_t");
    const w = pickPoint(r, "web_oat_c", "web_oa_t", "web-outside-air-temp");
    if (!t) continue;
    if (b != null) bas.push([t, displayTempC(b, unitSystem)]);
    if (w != null) web.push([t, displayTempC(w, unitSystem)]);
  }
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
  const deltas = [];
  for (const r of rows) {
    const b = pickPoint(r, "bas_oat_c", "bas_oa_t", "oa_t");
    const w = pickPoint(r, "web_oat_c", "web_oa_t");
    if (b == null || w == null) continue;
    deltas.push(displayTempC(b - w, unitSystem));
  }
  if (!deltas.length) return null;
  const buckets = new Map();
  const step = unitSystem === "imperial" ? 2 : 1;
  for (const d of deltas) {
    const k = Math.round(d / step) * step;
    buckets.set(k, (buckets.get(k) || 0) + 1);
  }
  const keys = [...buckets.keys()].sort((a, b) => a - b);
  return {
    option: {
      backgroundColor: "transparent",
      title: { text: "BAS − web deviation", textStyle: { color: "#c9d2e8", fontSize: 12 } },
      xAxis: { type: "category", data: keys.map(String), axisLabel: { color: "#8899bb" } },
      yAxis: { type: "value", name: "count", axisLabel: { color: "#8899bb" } },
      series: [{ type: "bar", data: keys.map((k) => buckets.get(k)), itemStyle: { color: "#f8961e" } }],
    },
    lineSeries: [],
  };
}

export { basVsWebHistChart };
