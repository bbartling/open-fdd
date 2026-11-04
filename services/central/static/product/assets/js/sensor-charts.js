import { rainbowColor, toolboxSaveAsImage, faultLaneStyle } from "./chart-theme.js";

export function sensorHealthHeatmapOption(rows, opts = {}) {
  if (!rows.length) return null;
  const eqs = [...new Set(rows.map((r) => String(r.equipment_id ?? "")))].sort();
  const roles = [...new Set(rows.map((r) => String(r.role ?? "")))].sort();
  if (!eqs.length || !roles.length) return null;
  const data = [];
  for (let yi = 0; yi < eqs.length; yi++) {
    for (let xi = 0; xi < roles.length; xi++) {
      const hit = rows.find(
        (r) => String(r.equipment_id) === eqs[yi] && String(r.role) === roles[xi],
      );
      const cov = hit ? Number(hit.coverage_pct) : null;
      if (cov != null && Number.isFinite(cov)) data.push([xi, yi, cov]);
    }
  }
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? "Sensor health — coverage %" },
    toolbox: toolboxSaveAsImage(opts.pngStem ?? "sensor_health"),
    grid: { left: 80, top: 56, right: 48, bottom: 80 },
    xAxis: { type: "category", data: roles, axisLabel: { rotate: 30 } },
    yAxis: { type: "category", data: eqs },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: { color: ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"] },
    },
    series: [{ type: "heatmap", data, label: { show: false } }],
  };
}

export function deriveSensorFaultMasks(values, opts = {}) {
  const win = opts.flatlineWindow ?? 12;
  const spikeZ = opts.spikeZ ?? 4;
  const rangeZ = opts.rangeZ ?? 3;
  const finite = values.filter((v) => v != null && Number.isFinite(v));
  const mean = finite.length ? finite.reduce((a, b) => a + b, 0) / finite.length : 0;
  const variance =
    finite.length > 1
      ? finite.reduce((a, v) => a + (v - mean) ** 2, 0) / finite.length
      : 0;
  const std = Math.sqrt(variance);
  const flatline = values.map(() => 0);
  const spike = values.map(() => 0);
  const range = values.map(() => 0);
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || !Number.isFinite(v)) continue;
    if (std > 0 && Math.abs(v - mean) > rangeZ * std) range[i] = 1;
    if (std > 0 && Math.abs(v - mean) > spikeZ * std) spike[i] = 1;
    if (i + 1 >= win) {
      const slice = values.slice(i + 1 - win, i + 1).filter((x) => x != null && Number.isFinite(x));
      if (slice.length >= Math.max(5, Math.floor(win * 0.6))) {
        const m = slice.reduce((a, b) => a + b, 0) / slice.length;
        const s = Math.sqrt(slice.reduce((a, x) => a + (x - m) ** 2, 0) / slice.length);
        if (s <= 1e-9) {
          for (let j = i + 1 - win; j <= i; j++) flatline[j] = 1;
        }
      }
    }
  }
  return { "SV-FLATLINE": flatline, "SV-SPIKE": spike, "SV-RANGE": range };
}

export function sensorFaultChartOption(points, opts) {
  if (!points.length) return null;
  const key = opts.valueKey ?? "value_f";
  const x = points.map((p) => {
    const ms = Date.parse(String(p.timestamp_utc ?? p.timestamp ?? ""));
    return Number.isFinite(ms) ? ms : null;
  });
  const y = points.map((p) => {
    const v = p[key] ?? p.value ?? p.value_f;
    if (v == null || v === "") return null;
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  });
  if (!y.some((v) => v != null)) return null;
  const masks =
    opts.ruleMasks && Object.keys(opts.ruleMasks).length
      ? opts.ruleMasks
      : deriveSensorFaultMasks(y);
  const series = [
    {
      name: opts.sensorName ?? "sensor",
      type: "line",
      xAxisIndex: 0,
      yAxisIndex: 0,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 1.4, color: rainbowColor(0) },
      data: x.map((t, i) => [t, y[i]]),
    },
  ];
  const laneNames = Object.keys(masks);
  const gridCount = 1 + laneNames.length;
  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const rowH = 80;
  for (let i = 0; i < gridCount; i++) {
    grids.push({ left: 64, right: 24, top: 48 + i * rowH, height: rowH - 16 });
    xAxes.push({ type: "time", gridIndex: i, show: i === gridCount - 1 });
    yAxes.push({
      type: "value",
      gridIndex: i,
      name: i === 0 ? opts.yTitle ?? "value" : laneNames[i - 1],
      min: i === 0 ? undefined : 0,
      max: i === 0 ? undefined : 1,
    });
  }
  laneNames.forEach((lane, idx) => {
    const fl = faultLaneStyle();
    series.push({
      name: lane,
      type: "line",
      xAxisIndex: idx + 1,
      yAxisIndex: idx + 1,
      step: "end",
      showSymbol: false,
      connectNulls: false,
      lineStyle: fl.line,
      areaStyle: fl.area,
      data: x.map((t, i) => [t, masks[lane][i] ? 1 : 0]),
    });
  });
  return {
    backgroundColor: "transparent",
    title: { text: opts.title ?? `Sensor fault — ${opts.sensorName ?? ""}` },
    toolbox: toolboxSaveAsImage(opts.pngStem ?? "sensor_fault"),
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    series,
  };
}
