import * as echarts from "../vendor/echarts.esm.min.js";
import { fetchBasVsWeb, fetchInspectSeries } from "./analytics.js";
import { displayName, has, isTemp, roleOf, unitLabel } from "./tags.js";
import { rainbowColor, toolboxSaveAsImage } from "./chart-theme.js";
import { basOverlayOption } from "./overview-rcx-charts.js";

export const PALETTE = [
  "#2563eb",
  "#ea580c",
  "#dc2626",
  "#16a34a",
  "#7c3aed",
  "#ca8a04",
  "#0d9488",
  "#577590",
];

const charts = new Map();

export function chartEl(id) {
  const node = document.getElementById(id);
  if (!node) return null;
  node.classList.add("chart-ready");
  if (!charts.has(id)) {
    charts.set(id, echarts.init(node, null, { renderer: "canvas" }));
  }
  return charts.get(id);
}

export function disposeSparklines() {
  for (const [id, inst] of charts) {
    if (id.startsWith("spark-")) {
      inst.dispose();
      charts.delete(id);
    }
  }
}

export function resizeCharts() {
  for (const inst of charts.values()) {
    inst.resize();
  }
}

function parseTs(iso) {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
}

function seriesFromInspect(rows, role) {
  const out = [];
  for (const row of rows) {
    const t = parseTs(row.timestamp_utc);
    const v = row[role];
    if (t == null || v == null) continue;
    out.push([t, Number(v)]);
  }
  return out;
}

function downsample(arr, bucketMs) {
  if (bucketMs <= 60_000) return arr;
  const out = [];
  let key = null;
  let sum = 0;
  let n = 0;
  for (const [t, v] of arr) {
    const k = Math.floor(t / bucketMs) * bucketMs;
    if (k !== key && n) {
      out.push([key + bucketMs / 2, sum / n]);
      sum = 0;
      n = 0;
    }
    key = k;
    sum += v;
    n += 1;
  }
  if (n) out.push([key + bucketMs / 2, sum / n]);
  return out;
}

function since(arr, hours) {
  const cut = Date.now() - hours * 3600 * 1000;
  return arr.filter(([t]) => t >= cut);
}

function tempRoles(points) {
  return points.filter(isTemp);
}

function findRole(points, role) {
  return points.find((p) => roleOf(p) === role);
}

export async function loadScopeHistory(buildingId, equipId, cardPoints, weatherPoints, hours) {
  const roles = new Set();
  for (const p of [...cardPoints, ...weatherPoints]) {
    if (roleOf(p)) roles.add(roleOf(p));
  }
  const rows = await fetchInspectSeries(buildingId, equipId, hours, [...roles]);
  const history = new Map();
  for (const role of roles) {
    history.set(role, seriesFromInspect(rows, role));
  }
  return { rows, history };
}

export function renderOverviewSpark(i, point, history) {
  const role = roleOf(point);
  const color = PALETTE[i % PALETTE.length];
  const data = since(history.get(role) || [], 6);
  chartEl(`spark-${i}`)?.setOption({
    animation: false,
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: "time", show: false },
    yAxis: { type: "value", show: false, scale: true },
    series: [
      {
        type: "line",
        data,
        showSymbol: false,
        smooth: true,
        lineStyle: { width: 1.5, color },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `${color}66` },
            { offset: 1, color: `${color}00` },
          ]),
        },
      },
    ],
  });
}

export function renderBasVsWeb(rows) {
  const chart = chartEl("wxChart");
  if (!chart) return;
  const points = rows.map((row) => ({
    timestamp_utc: row.ts ?? row.timestamp_utc,
    bas_oat_c: row.bas_oa_t ?? row.bas_oat_c,
    web_oat_c: row.web_oa_t ?? row.web_oat_c,
  }));
  const built = basOverlayOption(points, "metric", 2, "charts_weather_vs_oat");
  if (!built?.option) {
    chart.clear();
    return;
  }
  chart.setOption(built.option, true);
}

export function renderTempTrend(points, history, rangeHours) {
  const temps = tempRoles(points);
  const chart = chartEl("tempChart");
  if (!chart) return;
  const bucket = rangeHours > 24 ? 5 * 60_000 : 60_000;
  chart.setOption(
    {
      backgroundColor: "transparent",
      color: PALETTE,
      tooltip: { trigger: "axis" },
      legend: { top: 0 },
      toolbox: toolboxSaveAsImage("charts_temps"),
      grid: { left: 50, right: 20, top: 36, bottom: 70 },
      xAxis: { type: "time" },
      yAxis: {
        type: "value",
        scale: true,
        name: unitLabel(temps[0]) || "°C",
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 22, bottom: 12 }],
      series: temps.map((p, i) => ({
        name: displayName(p),
        type: "line",
        showSymbol: false,
        smooth: 0.2,
        sampling: "lttb",
        lineStyle: { width: 1.6, color: rainbowColor(i) },
        data: downsample(since(history.get(roleOf(p)) || [], rangeHours), bucket),
      })),
    },
    { replaceMerge: ["series"] },
  );
}

function dailyStats(history, role, rangeHours) {
  const byDay = new Map();
  for (const [t, v] of since(history.get(role) || [], rangeHours)) {
    const day = new Date(t).toISOString().slice(0, 10);
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(v);
  }
  const days = [...byDay.keys()].sort();
  const min = [];
  const mean = [];
  const max = [];
  for (const d of days) {
    const vals = byDay.get(d);
    min.push([d, Math.min(...vals)]);
    max.push([d, Math.max(...vals)]);
    mean.push([d, vals.reduce((a, b) => a + b, 0) / vals.length]);
  }
  return { days, min, mean, max };
}

export function renderDailyMinMax(points, history, rangeHours) {
  const chart = chartEl("dailyChart");
  if (!chart) return;
  const p = points.find(isTemp) || points[0];
  if (!p) {
    chart.clear();
    return;
  }
  const { days, min, mean, max } = dailyStats(history, roleOf(p), rangeHours);
  chart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    toolbox: toolboxSaveAsImage("charts_daily_min_mean_max"),
    legend: { top: 0 },
    grid: { left: 50, right: 20, top: 36, bottom: 48 },
    xAxis: { type: "category", data: days },
    yAxis: { type: "value", scale: true, name: unitLabel(p) || "°C" },
    series: [
      { name: "min", type: "line", data: min.map(([, v]) => v), showSymbol: false },
      { name: "mean", type: "line", data: mean.map(([, v]) => v), showSymbol: false },
      { name: "max", type: "line", data: max.map(([, v]) => v), showSymbol: false },
    ],
  });
}

export function renderRuntimeBool(points, history, rangeHours) {
  const chart = chartEl("runtimeChart");
  if (!chart) return;
  const status = points.find((p) => roleOf(p).includes("status") || roleOf(p).includes("cmd"));
  if (!status) {
    chart.clear();
    return;
  }
  const role = roleOf(status);
  const byDay = new Map();
  for (const [t, v] of since(history.get(role) || [], rangeHours)) {
    const day = new Date(t).toISOString().slice(0, 10);
    const on = Number(v) > 0.5 ? 1 : 0;
    const e = byDay.get(day) ?? { on: 0, n: 0 };
    e.on += on;
    e.n += 1;
    byDay.set(day, e);
  }
  const days = [...byDay.keys()].sort();
  const hours = days.map((d) => {
    const e = byDay.get(d);
    const frac = e.n ? e.on / e.n : 0;
    return +(frac * 24).toFixed(2);
  });
  chart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    toolbox: toolboxSaveAsImage("charts_runtime"),
    grid: { left: 50, right: 20, top: 24, bottom: 48 },
    xAxis: { type: "category", data: days },
    yAxis: { type: "value", name: "run hours (est.)" },
    series: [{ type: "bar", data: hours, itemStyle: { color: rainbowColor(2) } }],
  });
}

export function renderHeatmap(points, history, heatRole) {
  const chart = chartEl("heatChart");
  if (!chart) return;
  const p = points.find((x) => roleOf(x) === heatRole) || points.find(isTemp);
  if (!p) {
    chart.clear();
    return;
  }
  const cells = new Map();
  const days = [];
  for (const [t, v] of since(history.get(roleOf(p)) || [], 168)) {
    const d = new Date(t);
    const day = d.toLocaleDateString(undefined, { weekday: "short", month: "numeric", day: "numeric" });
    if (!days.includes(day)) days.push(day);
    const key = `${day}|${d.getHours()}`;
    const c = cells.get(key) || [0, 0];
    c[0] += v;
    c[1] += 1;
    cells.set(key, c);
  }
  const data = [...cells.entries()].map(([k, [s, n]]) => {
    const [day, h] = k.split("|");
    return [Number(h), days.indexOf(day), +(s / n).toFixed(3)];
  });
  const vals = data.map((d) => d[2]);
  chart.setOption(
    {
      backgroundColor: "transparent",
      tooltip: { position: "top" },
      toolbox: toolboxSaveAsImage("charts_hour_heatmap"),
      grid: { left: 80, right: 20, top: 10, bottom: 80 },
      xAxis: {
        type: "category",
        data: [...Array(24).keys()].map(String),
        splitArea: { show: false },
      },
      yAxis: { type: "category", data: days },
      visualMap: {
        min: Math.min(...vals, 0),
        max: Math.max(...vals, 1),
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemHeight: 220,
        inRange: {
          color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#f94144"],
        },
      },
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: { borderWidth: 2, borderRadius: 3 },
        },
      ],
    },
    true,
  );
}

export function renderPsychrometric(points, history, hintEl) {
  const chart = chartEl("psyChart");
  if (!chart || !hintEl) return;
  const oat = findRole(points, "oa_t") || points.find((p) => has(p, "outside", "air", "temp"));
  const rhPoint =
    points.find((p) => roleOf(p).includes("humidity")) ||
    points.find((p) => has(p, "outside", "air", "humidity"));
  if (!oat || !rhPoint) {
    hintEl.textContent = "need oa_t + humidity roles on equipment";
    chart.clear();
    return;
  }
  hintEl.textContent = `${displayName(oat)} × ${displayName(rhPoint)}`;
  const rhSeries = downsample(since(history.get(roleOf(rhPoint)) || [], 168), 15 * 60_000);
  const rhAt = new Map(rhSeries.map(([k, v]) => [k, v]));
  const pts = downsample(since(history.get(roleOf(oat)) || [], 168), 15 * 60_000)
    .filter(([k]) => rhAt.has(k))
    .map(([k, tv]) => [tv, rhAt.get(k), new Date(k).getHours() + new Date(k).getMinutes() / 60, k]);
  chart.setOption(
    {
      backgroundColor: "transparent",
      tooltip: { trigger: "item" },
      toolbox: toolboxSaveAsImage("charts_temp_rh"),
      grid: { left: 50, right: 70, top: 20, bottom: 40 },
      xAxis: {
        type: "value",
        scale: true,
        name: unitLabel(oat) || "°C",
        nameLocation: "center",
        nameGap: 26,
      },
      yAxis: {
        type: "value",
        scale: true,
        name: "%RH",
      },
      visualMap: {
        dimension: 2,
        min: 0,
        max: 24,
        right: 0,
        top: "middle",
        itemHeight: 180,
        calculable: false,
        text: ["24h", "0h"],
        inRange: {
          color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#3a0ca3"],
        },
        seriesIndex: 0,
      },
      series: [{ type: "scatter", data: pts, symbolSize: 6, itemStyle: { opacity: 0.75 } }],
    },
    true,
  );
}

export function renderPointHistory(point, rows, hours) {
  const chart = chartEl("histChart");
  if (!chart || !point) return;
  const role = roleOf(point);
  const data = downsample(seriesFromInspect(rows, role), hours > 24 ? 5 * 60_000 : 60_000);
  chart.setOption(
    {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      toolbox: toolboxSaveAsImage(`${String(point.equipRef || "point").replace(/[^\w.-]+/g, "_")}_history`),
      grid: { left: 50, right: 20, top: 20, bottom: 50 },
      xAxis: { type: "time" },
      yAxis: {
        type: "value",
        scale: true,
        name: point.kind === "Bool" ? "on / off" : unitLabel(point) || role,
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 6 }],
      series: [
        {
          name: displayName(point),
          type: "line",
          showSymbol: false,
          sampling: "lttb",
          step: point.kind === "Bool" ? "end" : false,
          lineStyle: { width: 1.6, color: rainbowColor(0) },
          areaStyle: { opacity: 0.08 },
          data,
        },
      ],
    },
    true,
  );
}

export async function refreshChartsTab(state) {
  const { buildingId, equipId, cardPoints, history, rangeHours, heatRole } = state;
  if (!equipId) return;
  const basRows = await fetchBasVsWeb(buildingId, [equipId], Math.max(rangeHours, 48));
  renderBasVsWeb(basRows);
  renderTempTrend(cardPoints, history, rangeHours);
  renderHeatmap(cardPoints, history, heatRole);
  renderPsychrometric(cardPoints, history, document.getElementById("psyHint"));
  renderDailyMinMax(cardPoints, history, rangeHours);
  renderRuntimeBool(cardPoints, history, rangeHours);
}
