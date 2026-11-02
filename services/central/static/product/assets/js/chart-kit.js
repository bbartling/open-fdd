import * as echarts from "../vendor/echarts.esm.min.js";

const charts = new Map();

export function mountChart(host, option) {
  if (!host) return null;
  let chart = charts.get(host);
  if (!chart) {
    chart = echarts.init(host, null, { renderer: "canvas" });
    charts.set(host, chart);
  }
  chart.setOption(option, true);
  return chart;
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

/** Inspect stacked domains — title matches charts.contract.json. */
export function inspectChartOption(equipmentId, rows, roles, unitSystem = "metric") {
  const title = `Inspection — ${equipmentId}`;
  const series = [];
  const lineSeries = [];
  let gridTop = 40;
  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const rowH = 140;
  const maxH = 2400;
  const n = Math.min(roles.length, Math.floor(maxH / rowH));
  const usedRoles = roles.slice(0, n);
  for (let i = 0; i < usedRoles.length; i++) {
    const top = gridTop + i * rowH;
    grids.push({ left: 60, right: 20, top, height: rowH - 24 });
    xAxes.push({
      type: "time",
      gridIndex: i,
      axisLabel: { show: i === usedRoles.length - 1, color: "#8899bb" },
    });
    yAxes.push({
      type: "value",
      gridIndex: i,
      name: usedRoles[i],
      nameTextStyle: { color: "#c9d2e8", fontSize: 11 },
      axisLabel: { color: "#8899bb", fontSize: 10 },
    });
    const data = [];
    for (const r of rows) {
      const t = r.timestamp_utc || r.ts;
      const v = r[usedRoles[i]];
      if (t == null || v == null) continue;
      data.push([t, Number(v)]);
    }
    lineSeries.push({ name: usedRoles[i], data });
    series.push({
      name: usedRoles[i],
      type: "line",
      xAxisIndex: i,
      yAxisIndex: i,
      showSymbol: false,
      data,
    });
  }
  const totalHeight = Math.max(320, gridTop + usedRoles.length * rowH);
  return {
    option: {
      backgroundColor: "transparent",
      title: { text: title, textStyle: { color: "#c9d2e8", fontSize: 14 } },
      tooltip: { trigger: "axis" },
      grid: grids,
      xAxis: xAxes,
      yAxis: yAxes,
      series,
    },
    lineSeries,
    heightPx: Math.min(totalHeight, maxH),
  };
}

/** FDD rule chart: roles on y, confirmed_fault on secondary axis. */
export function fddPlotOption(rows, roles, hasConfirmedFault) {
  const timestamps = rows.map((r) => r.timestamp_utc || r.ts).filter(Boolean);
  const series = [];
  const lineSeries = [];
  for (const role of roles) {
    const data = rows
      .map((r) => {
        const t = r.timestamp_utc || r.ts;
        const v = r[role];
        if (t == null || v == null) return null;
        return [t, Number(v)];
      })
      .filter(Boolean);
    if (!data.length) continue;
    lineSeries.push({ name: role, data });
    series.push({ name: role, type: "line", showSymbol: false, data });
  }
  if (hasConfirmedFault) {
    const faultData = rows
      .map((r) => {
        const t = r.timestamp_utc || r.ts;
        const v = r.confirmed_fault ?? r.fault;
        if (t == null || v == null) return null;
        return [t, Number(v) > 0 ? 1 : 0];
      })
      .filter(Boolean);
    if (faultData.length) {
      lineSeries.push({ name: "confirmed_fault", data: faultData });
      series.push({
        name: "confirmed_fault",
        type: "line",
        yAxisIndex: 1,
        step: "end",
        showSymbol: false,
        lineStyle: { color: "#f94144" },
        data: faultData,
      });
    }
  }
  return {
    option: {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: "#c9d2e8" } },
      xAxis: { type: "time", axisLabel: { color: "#8899bb" } },
      yAxis: [
        { type: "value", axisLabel: { color: "#8899bb" } },
        { type: "value", min: 0, max: 1, name: "fault", axisLabel: { color: "#8899bb" } },
      ],
      series,
    },
    lineSeries,
  };
}
