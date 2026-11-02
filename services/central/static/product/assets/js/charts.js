import * as echarts from "../vendor/echarts.esm.min.js";
import { fetchBasVsWeb, fetchInspectSeries } from "./analytics.js";
import { displayName, has, isTemp, roleOf, unitLabel } from "./tags.js";

export const PALETTE = [
  "#4cc9f0",
  "#f8961e",
  "#f94144",
  "#90be6d",
  "#b5179e",
  "#f9c74f",
  "#43aa8b",
  "#577590",
];

const axisStyle = {
  axisLine: { lineStyle: { color: "#2b3858" } },
  axisLabel: { color: "#8a96b3" },
  splitLine: { lineStyle: { color: "#1c2640" } },
};
const tooltip = {
  trigger: "axis",
  backgroundColor: "#0f1730ee",
  borderColor: "#2b3858",
  textStyle: { color: "#e6ebf5" },
};

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
  if (!rows.length) {
    chart.clear();
    return;
  }
  const bas = [];
  const web = [];
  for (const row of rows) {
    const t = parseTs(row.ts);
    if (t == null) continue;
    if (row.bas_oa_t != null) bas.push([t, row.bas_oa_t]);
    if (row.web_oa_t != null) web.push([t, row.web_oa_t]);
  }
  chart.setOption({
    color: ["#f8961e", "#4cc9f0"],
    tooltip,
    legend: { top: 0, textStyle: { color: "#c9d2e8" } },
    grid: { left: 50, right: 50, top: 36, bottom: 60 },
    xAxis: { type: "time", ...axisStyle },
    yAxis: {
      type: "value",
      scale: true,
      name: "°C",
      nameTextStyle: { color: "#8a96b3" },
      ...axisStyle,
    },
    dataZoom: [
      { type: "inside" },
      {
        type: "slider",
        height: 18,
        bottom: 8,
        borderColor: "#2b3858",
        fillerColor: "#4cc9f022",
        textStyle: { color: "#8a96b3" },
      },
    ],
    series: [
      { name: "BAS OAT", type: "line", showSymbol: false, smooth: true, data: bas },
      { name: "Web OAT", type: "line", showSymbol: false, smooth: true, data: web },
    ],
  });
}

export function renderTempTrend(points, history, rangeHours) {
  const temps = tempRoles(points);
  const chart = chartEl("tempChart");
  if (!chart) return;
  const bucket = rangeHours > 24 ? 5 * 60_000 : 60_000;
  chart.setOption(
    {
      color: PALETTE,
      tooltip,
      legend: { top: 0, textStyle: { color: "#c9d2e8" } },
      grid: { left: 50, right: 20, top: 36, bottom: 70 },
      xAxis: { type: "time", ...axisStyle },
      yAxis: {
        type: "value",
        scale: true,
        name: unitLabel(temps[0]) || "°C",
        nameTextStyle: { color: "#8a96b3" },
        ...axisStyle,
      },
      dataZoom: [
        { type: "inside" },
        {
          type: "slider",
          height: 22,
          bottom: 12,
          borderColor: "#2b3858",
          fillerColor: "#4cc9f022",
          textStyle: { color: "#8a96b3" },
        },
      ],
      series: temps.map((p) => ({
        name: displayName(p),
        type: "line",
        showSymbol: false,
        smooth: 0.2,
        sampling: "lttb",
        lineStyle: { width: 1.6 },
        data: downsample(since(history.get(roleOf(p)) || [], rangeHours), bucket),
      })),
    },
    { replaceMerge: ["series"] },
  );
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
      tooltip: {
        position: "top",
        backgroundColor: "#0f1730ee",
        borderColor: "#2b3858",
        textStyle: { color: "#e6ebf5" },
      },
      grid: { left: 80, right: 20, top: 10, bottom: 80 },
      xAxis: {
        type: "category",
        data: [...Array(24).keys()].map(String),
        ...axisStyle,
        splitArea: { show: false },
      },
      yAxis: { type: "category", data: days, ...axisStyle },
      visualMap: {
        min: Math.min(...vals, 0),
        max: Math.max(...vals, 1),
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemHeight: 220,
        textStyle: { color: "#8a96b3" },
        inRange: {
          color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#f94144"],
        },
      },
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: { borderColor: "#121a30", borderWidth: 2, borderRadius: 3 },
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
      tooltip: {
        backgroundColor: "#0f1730ee",
        borderColor: "#2b3858",
        textStyle: { color: "#e6ebf5" },
      },
      grid: { left: 50, right: 70, top: 20, bottom: 40 },
      xAxis: {
        type: "value",
        scale: true,
        name: unitLabel(oat) || "°C",
        nameLocation: "center",
        nameGap: 26,
        nameTextStyle: { color: "#8a96b3" },
        ...axisStyle,
      },
      yAxis: {
        type: "value",
        scale: true,
        name: "%RH",
        nameTextStyle: { color: "#8a96b3" },
        ...axisStyle,
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
        textStyle: { color: "#8a96b3" },
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
      tooltip,
      grid: { left: 50, right: 20, top: 20, bottom: 50 },
      xAxis: { type: "time", ...axisStyle },
      yAxis: {
        type: "value",
        scale: true,
        name: point.kind === "Bool" ? "on / off" : unitLabel(point) || role,
        nameTextStyle: { color: "#8a96b3" },
        ...axisStyle,
      },
      dataZoom: [
        { type: "inside" },
        {
          type: "slider",
          height: 18,
          bottom: 6,
          borderColor: "#2b3858",
          fillerColor: "#4cc9f022",
          textStyle: { color: "#8a96b3" },
        },
      ],
      series: [
        {
          name: displayName(point),
          type: "line",
          showSymbol: false,
          sampling: "lttb",
          step: point.kind === "Bool" ? "end" : false,
          lineStyle: { width: 1.6, color: "#4cc9f0" },
          areaStyle: { opacity: 0.08, color: "#4cc9f0" },
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
}
