/**
 * Fuel metering charts (archived fuelCharts.ts → ECharts).
 */
import { rainbowColor, toolboxSaveAsImage } from "./chart-theme.js";

function num(v) {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function baseGrid(title, stem) {
  return {
    backgroundColor: "transparent",
    title: { text: title },
    toolbox: toolboxSaveAsImage(stem),
    grid: { left: 56, right: 24, top: 56, bottom: 48 },
  };
}

export function summaryPeerBulletOption(rows, stem = "fuel_summary_bullet") {
  const hit = rows[0];
  if (!hit) return null;
  const val = num(hit.eui ?? hit.value);
  return {
    ...baseGrid("Site EUI vs peer median", stem),
    series: [
      {
        type: "gauge",
        min: 0,
        max: num(hit.peer_p90) ?? val * 1.5 ?? 100,
        data: [{ value: val, name: "EUI" }],
      },
    ],
  };
}

export function summaryPeerBarsOption(rows, stem = "fuel_summary_bullet") {
  return {
    ...baseGrid("Peer comparison", stem),
    xAxis: { type: "category", data: rows.map((r) => String(r.label ?? r.site ?? "")) },
    yAxis: { type: "value", name: "EUI" },
    series: [{ type: "bar", data: rows.map((r) => num(r.eui ?? r.value)), itemStyle: { color: rainbowColor(1) } }],
  };
}

export function rankedSiteEuiOption(rows, stem = "fuel_ranked_eui") {
  const sorted = [...rows].sort((a, b) => num(b.eui) - num(a.eui));
  return {
    ...baseGrid("Ranked site EUI", stem),
    xAxis: { type: "value" },
    yAxis: { type: "category", data: sorted.map((r) => String(r.site ?? r.label ?? "")), inverse: true },
    series: [{ type: "bar", data: sorted.map((r) => num(r.eui)) }],
  };
}

export function rolling12EuiOption(rows, stem = "fuel_roll12") {
  return {
    ...baseGrid("Rolling 12-month EUI", stem),
    xAxis: { type: "category", data: rows.map((r) => String(r.month ?? r.period ?? "")) },
    yAxis: { type: "value", name: "EUI" },
    series: [{ type: "line", showSymbol: false, data: rows.map((r) => num(r.eui ?? r.value)) }],
  };
}

export function intensityHeatmapForFuelOption(rows, stem = "fuel_intensity_elec") {
  return intensityHeatmapOption(rows, { title: "Fuel intensity heatmap", pngStem: stem });
}

export function intensityHeatmapOption(rows, opts = {}) {
  const months = [...new Set(rows.map((r) => String(r.month ?? "")))].sort();
  const sites = [...new Set(rows.map((r) => String(r.site ?? r.building_id ?? "")))].sort();
  const data = [];
  for (let yi = 0; yi < sites.length; yi++) {
    for (let xi = 0; xi < months.length; xi++) {
      const hit = rows.find(
        (r) => String(r.site ?? r.building_id) === sites[yi] && String(r.month) === months[xi],
      );
      const v = num(hit?.intensity ?? hit?.eui);
      if (v != null) data.push([xi, yi, v]);
    }
  }
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "Intensity heatmap" },
    toolbox: toolboxSaveAsImage(opts.pngStem ?? "fuel_intensity_gas"),
    grid: { left: 80, top: 56, right: 48, bottom: 80 },
    xAxis: { type: "category", data: months },
    yAxis: { type: "category", data: sites },
    visualMap: { min: 0, max: Math.max(...data.map((d) => d[2]), 1), calculable: true, orient: "horizontal", left: "center", bottom: 0 },
    series: [{ type: "heatmap", data }],
  };
}

export function stackedFuelOption(rows, stem = "fuel_stacked") {
  const fuels = [...new Set(rows.map((r) => String(r.fuel ?? r.series ?? "fuel")))];
  const months = [...new Set(rows.map((r) => String(r.month ?? "")))].sort();
  return {
    ...baseGrid("Stacked fuel use", stem),
    legend: { top: 28 },
    xAxis: { type: "category", data: months },
    yAxis: { type: "value", name: "energy" },
    series: fuels.map((f, i) => ({
      name: f,
      type: "bar",
      stack: "fuel",
      data: months.map((m) => {
        const hit = rows.find((r) => String(r.month) === m && String(r.fuel ?? r.series) === f);
        return num(hit?.energy ?? hit?.value);
      }),
      itemStyle: { color: rainbowColor(i) },
    })),
  };
}

export function monthlyLinesOption(rows, stem = "fuel_monthly") {
  return {
    ...baseGrid("Monthly fuel lines", stem),
    legend: { top: 28 },
    xAxis: { type: "category", data: rows.map((r) => String(r.month ?? "")) },
    yAxis: { type: "value", name: "energy" },
    series: [{ type: "line", showSymbol: false, data: rows.map((r) => num(r.energy ?? r.value)) }],
  };
}

export function demandHeatmapOption(rows, stem = "fuel_demand") {
  return intensityHeatmapOption(rows, { title: "Demand heatmap", pngStem: stem });
}

export function weatherScatterOption(rows, stem = "fuel_weather") {
  return {
    ...baseGrid("Weather vs energy", stem),
    xAxis: { type: "value", name: "degree-days", scale: true },
    yAxis: { type: "value", name: "energy", scale: true },
    series: [
      {
        type: "scatter",
        data: rows.map((r) => [num(r.dd ?? r.x), num(r.energy ?? r.y)]).filter((d) => d[0] != null && d[1] != null),
        symbolSize: 8,
      },
    ],
  };
}

export function weatherResidualBarsOption(rows, stem = "fuel_weather") {
  return {
    ...baseGrid("Weather-normalized residual", stem),
    xAxis: { type: "category", data: rows.map((r) => String(r.month ?? r.label ?? "")) },
    yAxis: { type: "value", name: "residual" },
    series: [{ type: "bar", data: rows.map((r) => num(r.residual ?? r.value)) }],
  };
}

export function demandPeakDualAxisOption(rows, stem = "fuel_demand_peak") {
  return {
    ...baseGrid("Demand peak dual axis", stem),
    legend: { top: 28 },
    xAxis: { type: "category", data: rows.map((r) => String(r.month ?? "")) },
    yAxis: [{ type: "value", name: "kW" }, { type: "value", name: "kWh", position: "right" }],
    series: [
      { type: "bar", data: rows.map((r) => num(r.peak_kw)), name: "Peak kW" },
      { type: "line", yAxisIndex: 1, showSymbol: false, data: rows.map((r) => num(r.kwh)), name: "kWh" },
    ],
  };
}

export function peakVsCoolSeasonOption(rows, stem = "fuel_peak_cool") {
  return {
    ...baseGrid("Peak vs cooling season", stem),
    xAxis: { type: "category", data: rows.map((r) => String(r.season ?? r.label ?? "")) },
    yAxis: { type: "value", name: "peak kW" },
    series: [{ type: "bar", data: rows.map((r) => num(r.peak_kw ?? r.value)) }],
  };
}
