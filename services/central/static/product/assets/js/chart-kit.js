import * as echarts from "../vendor/echarts.esm.min.js";
import { activeEchartsThemeName, ensureThemes } from "./chart-theme.js";
import { resolveRoleUnit, lookupRoleBinding } from "./role-units.js";
import { ruleResultChartOption } from "./fdd-charts.js";
import { parseTimestampMillis } from "./timestamp-adapter.js";

const charts = new Map();

export function mountChart(host, option) {
  if (!host || !option) return null;
  ensureThemes();
  let chart = charts.get(host);
  const theme = activeEchartsThemeName();
  if (chart) {
    chart.dispose();
    charts.delete(host);
  }
  chart = echarts.init(host, theme, { renderer: "canvas" });
  charts.set(host, chart);
  chart.setOption(option, true);
  return chart;
}

export function remountAllCharts() {
  for (const [host, chart] of charts) {
    const option = chart.getOption();
    chart.dispose();
    charts.delete(host);
    mountChart(host, option);
  }
}

export function disposeChart(host) {
  const chart = charts.get(host);
  if (chart) {
    chart.dispose();
    charts.delete(host);
  }
}

export function resizeCharts() {
  for (const chart of charts.values()) chart.resize();
}

/** Raw unit label for inspect stacked domains. */
export function inspectRawUnit(role, unitSystem = "metric", roleUnitIndex = null, equipmentId = "") {
  const binding = lookupRoleBinding(roleUnitIndex, equipmentId, role);
  return resolveRoleUnit(role, unitSystem, binding) || role;
}

/** Inspect stacked domains — title matches charts.contract.json. */
export function inspectChartOption(equipmentId, rows, roles, unitSystem = "metric", roleUnitIndex = null) {
  const title = `Inspection — ${equipmentId}`;
  const series = [];
  const lineSeries = [];
  const gridTop = 40;
  const rowH = 140;
  const maxH = 2400;
  const n = Math.min(roles.length, Math.floor(maxH / rowH));
  const usedRoles = roles.slice(0, n);
  const grids = [];
  const xAxes = [];
  const yAxes = [];
  for (let i = 0; i < usedRoles.length; i++) {
    const top = gridTop + i * rowH;
    grids.push({ left: 60, right: 20, top, height: rowH - 24 });
    xAxes.push({
      type: "time",
      gridIndex: i,
      axisLabel: { show: i === usedRoles.length - 1 },
    });
    yAxes.push({
      type: "value",
      gridIndex: i,
      name: `${usedRoles[i]} (${inspectRawUnit(usedRoles[i], unitSystem, roleUnitIndex, equipmentId)})`,
      nameTextStyle: { fontSize: 11 },
      scale: true,
    });
    const data = [];
    for (const r of rows) {
      const raw = r.timestamp_utc ?? r.ts;
      const ms = parseTimestampMillis(raw);
      const v = r[usedRoles[i]];
      const y = v == null || v === "" ? null : Number(v);
      data.push([ms, Number.isFinite(y) ? y : null]);
    }
    lineSeries.push({ name: usedRoles[i], data: data.filter((d) => d[0] != null) });
    series.push({
      name: usedRoles[i],
      type: "line",
      xAxisIndex: i,
      yAxisIndex: i,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 1.4 },
      data,
    });
  }
  const totalHeight = Math.min(Math.max(320, gridTop + usedRoles.length * rowH), maxH);
  const pngStem = `${String(equipmentId).replace(/[^\w.-]+/g, "_")}_inspect`;
  return {
    option: {
      backgroundColor: "transparent",
      title: { text: title, left: 8, top: 4 },
      tooltip: { trigger: "axis", axisPointer: { link: [{ xAxisIndex: "all" }] } },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: grids,
      xAxis: xAxes,
      yAxis: yAxes,
      series,
    },
    lineSeries,
    heightPx: totalHeight,
    pngStem,
  };
}

/** FDD rule chart — delegates to stacked unit-family + fault lane builder. */
export function fddPlotOption(rows, roles, hasConfirmedFault, meta = {}) {
  const confirmedFault = hasConfirmedFault
    ? rows.map((r) => r.confirmed_fault ?? r.fault)
    : undefined;
  return ruleResultChartOption(rows, {
    ruleId: meta.ruleId ?? "rule",
    equipmentId: meta.equipmentId ?? "",
    roles: roles || [],
    confirmedFault,
    description: meta.description,
    pngStem: meta.pngStem,
    roleUnitIndex: meta.roleUnitIndex ?? null,
    unitSystem: meta.unitSystem ?? "metric",
  });
}
