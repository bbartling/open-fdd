/**
 * Generic RCx preset charts (archived vibeCharts.ts → ECharts).
 */
import { rainbowColor, toolboxSaveAsImage } from "./chart-theme.js";
import { displayTempC, tempAxisLabel } from "./role-units.js";

export const OUTLIER_RED = "#dc2626";

export function outlierEquipmentIds(points, opts = {}) {
  const zCut = opts.outlierZ ?? 2.5;
  const valueKey = opts.valueKey ?? "value_f";
  const primaryOnly = opts.primaryOnly ?? true;
  const means = new Map();
  for (const p of points) {
    if (primaryOnly && String(p.series ?? "primary") !== "primary") continue;
    const eq = String(p.equipment_id ?? "");
    if (!eq) continue;
    const raw = p[valueKey] ?? p.fail_pct;
    const n = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isFinite(n)) continue;
    const cur = means.get(eq) ?? { sum: 0, n: 0 };
    cur.sum += n;
    cur.n += 1;
    means.set(eq, cur);
  }
  const vals = [...means.entries()].map(([eq, { sum, n }]) => ({ eq, mean: sum / n }));
  if (vals.length < 3) return new Set();
  const mu = vals.reduce((a, v) => a + v.mean, 0) / vals.length;
  const sd = Math.sqrt(vals.reduce((a, v) => a + (v.mean - mu) ** 2, 0) / vals.length);
  if (!(sd > 0)) return new Set();
  const out = new Set();
  for (const v of vals) {
    if (Math.abs(v.mean - mu) / sd >= zCut) out.add(v.eq);
  }
  return out;
}

/** True when an RCx ECharts option accidentally includes a fault lane. */
export function rcxOptionHasFaultLane(option) {
  if (!option) return false;
  if ((option.series || []).some((s) => String(s.name) === "confirmed_fault")) return true;
  const ya = option.yAxis;
  const axes = Array.isArray(ya) ? ya : ya ? [ya] : [];
  if (axes.some((y) => y?.name === "fault")) return true;
  return false;
}

function parseTs(iso) {
  const ms = Date.parse(String(iso ?? ""));
  return Number.isFinite(ms) ? ms : null;
}

function num(v) {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export function multiEquipmentTimeseriesOption(points, opts) {
  if (!points.length) return null;
  const outliers = outlierEquipmentIds(points);
  const byKey = new Map();
  for (const p of points) {
    const eq = String(p.equipment_id ?? "eq");
    const series = String(p.series ?? "primary");
    const name =
      series === "primary"
        ? eq
        : series === "overlay"
          ? `${eq} · setpoint`
          : `${eq} · ${series}`;
    const list = byKey.get(name) ?? [];
    list.push(p);
    byKey.set(name, list);
  }
  const series = [];
  let colorI = 0;
  for (const [name, rows] of [...byKey.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const eq = name.split(" · ")[0];
    const isOut = outliers.has(eq);
    const data = rows.map((r) => [parseTs(r.timestamp_utc), num(r.value_f)]);
    series.push({
      name: isOut ? `${name} ★` : name,
      type: "line",
      showSymbol: false,
      connectNulls: false,
      lineStyle: {
        width: isOut ? 2.4 : 1.4,
        color: isOut ? OUTLIER_RED : rainbowColor(colorI),
        type: isOut ? "dashed" : "solid",
      },
      data,
    });
    if (!isOut) colorI += 1;
  }
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "Timeseries" },
    tooltip: { trigger: "axis" },
    toolbox: toolboxSaveAsImage(opts.pngStem),
    legend: { top: 28 },
    grid: { left: 56, right: 24, top: 72, bottom: 48 },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: opts.yTitle ?? "", scale: true },
    series,
  };
}

export function oatScatterOption(points, opts) {
  if (!points.length) return null;
  const data = points
    .map((p) => [num(p.oat_f ?? p.oa_t), num(p.value_f ?? p.y)])
    .filter((d) => d[0] != null && d[1] != null);
  if (!data.length) return null;
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "OAT scatter" },
    tooltip: { trigger: "item" },
    toolbox: toolboxSaveAsImage(opts.pngStem),
    grid: { left: 56, right: 24, top: 56, bottom: 48 },
    xAxis: { type: "value", name: "OAT", scale: true },
    yAxis: { type: "value", name: opts.yTitle ?? "value", scale: true },
    series: [{ type: "scatter", data, symbolSize: 8, itemStyle: { opacity: 0.75 } }],
  };
}

export function multiEquipmentBoxOption(points, opts) {
  if (!points.length) return null;
  const byEq = new Map();
  for (const p of points) {
    const eq = String(p.equipment_id ?? "eq");
    const v = num(p.value_f ?? p.y);
    if (v == null) continue;
    if (!byEq.has(eq)) byEq.set(eq, []);
    byEq.get(eq).push(v);
  }
  const categories = [...byEq.keys()].sort();
  const seriesData = categories.map((eq) => byEq.get(eq));
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "Box plot" },
    tooltip: { trigger: "item" },
    toolbox: toolboxSaveAsImage(opts.pngStem),
    grid: { left: 56, right: 24, top: 56, bottom: 48 },
    xAxis: { type: "category", data: categories },
    yAxis: { type: "value", name: opts.yTitle ?? "" },
    series: [{ type: "boxplot", data: seriesData.map((arr) => boxStats(arr)) }],
  };
}

function boxStats(arr) {
  const s = [...arr].sort((a, b) => a - b);
  const q = (p) => s[Math.floor(p * (s.length - 1))] ?? s[0];
  return [s[0], q(0.25), q(0.5), q(0.75), s[s.length - 1]];
}

export function rankingBarsOption(points, opts) {
  const sorted = [...points].sort((a, b) => num(b.value_f) - num(a.value_f));
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "Ranking" },
    toolbox: toolboxSaveAsImage(opts.pngStem),
    grid: { left: 120, right: 24, top: 56, bottom: 48 },
    xAxis: { type: "value" },
    yAxis: {
      type: "category",
      data: sorted.map((p) => String(p.equipment_id ?? p.label ?? "")),
      inverse: true,
    },
    series: [
      {
        type: "bar",
        data: sorted.map((p) => num(p.value_f)),
        itemStyle: { color: rainbowColor(2) },
      },
    ],
  };
}

export function comfortDonutOption(points, opts) {
  const total = points.reduce((a, p) => a + (num(p.value_f) ?? 0), 0);
  if (!total) return null;
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "Comfort" },
    toolbox: toolboxSaveAsImage(opts.pngStem),
    series: [
      {
        type: "pie",
        radius: ["45%", "70%"],
        data: points.map((p, i) => ({
          name: String(p.label ?? p.equipment_id ?? `slice ${i}`),
          value: num(p.value_f) ?? 0,
        })),
      },
    ],
  };
}

export function vavHealthWorstBarsOption(points, opts) {
  return rankingBarsOption(points, { ...opts, title: opts.title ?? "Worst zones" });
}

export function vavHealthDonutOption(points, opts) {
  return comfortDonutOption(points, { ...opts, title: opts.title ?? "VAV health" });
}

export function meteringChartsOption(points, opts) {
  const months = [...new Set(points.map((p) => String(p.month ?? p.x)))].sort();
  const energy = months.map((m) => {
    const hit = points.find((p) => String(p.month ?? p.x) === m);
    return num(hit?.energy ?? hit?.y);
  });
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "Metering" },
    toolbox: toolboxSaveAsImage(opts.pngStem),
    grid: [{ left: "8%", width: "38%", top: 56, bottom: 48 }, { left: "55%", width: "38%", top: 56, bottom: 48 }],
    xAxis: [
      { type: "category", data: months, gridIndex: 0 },
      { type: "value", gridIndex: 1, name: opts.ddLabel ?? "degree-days" },
    ],
    yAxis: [{ type: "value", gridIndex: 0, name: opts.energyYTitle ?? "energy" }, { type: "value", gridIndex: 1 }],
    series: [
      { type: "bar", xAxisIndex: 0, yAxisIndex: 0, data: energy },
      {
        type: "scatter",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: points.map((p) => [num(p.dd ?? p.x2), num(p.energy ?? p.y)]),
      },
    ],
  };
}

/** Dispatch generic RCx coverage.chart_kind → ECharts option. */
export function rcxPresetOption(coverage, points, opts = {}) {
  const kind = String(coverage?.chart_kind ?? "timeseries");
  const stem = opts.pngStem ?? `rcx_${coverage?.family ?? "generic"}_${coverage?.preset ?? "plot"}`;
  const base = { title: coverage?.title ?? stem, pngStem: stem, ...opts };
  switch (kind) {
    case "scatter_oat":
      return oatScatterOption(points, base);
    case "box":
      return multiEquipmentBoxOption(points, base);
    case "ranking":
      return rankingBarsOption(points, base);
    case "metering":
      return meteringChartsOption(points, base);
    case "vav_health":
      return coverage?.companion === "donut"
        ? vavHealthDonutOption(points, base)
        : vavHealthWorstBarsOption(points, base);
    default:
      return multiEquipmentTimeseriesOption(points, {
        ...base,
        yTitle: coverage?.y_title ?? tempAxisLabel("metric"),
      });
  }
}
