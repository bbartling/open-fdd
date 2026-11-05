/**
 * Overview RCx preset charts (archived centralOverview.ts parity, ECharts).
 */
import { rainbowColor, toolboxSaveAsImage } from "./chart-theme.js";
import { displayTempC, displayDeltaC, tempAxisLabel } from "./role-units.js";
import { ECONOMIZER_DT_MIN_C, isIdentifiablePoint } from "./tip-analytics-normalize.js";

function parseTs(iso) {
  const ms = Date.parse(String(iso ?? ""));
  return Number.isFinite(ms) ? ms : null;
}

export function weeklyMotorOption(rows, plantGroup, pngStem) {
  const filtered = rows.filter(
    (r) =>
      String(r.kind) === "weekly_equipment" &&
      String(r.plant_group || "").toLowerCase() === plantGroup,
  );
  const weeks = [...new Set(filtered.map((r) => String(r.week_label ?? r.week ?? "")))].sort();
  const byEquip = new Map();
  for (const r of filtered) {
    const id = String(r.label ?? r.equipment_id ?? "");
    const week = String(r.week_label ?? r.week ?? "");
    const hours = Number(r.run_hours ?? r.runtime_hours);
    if (!id || !week || !Number.isFinite(hours)) continue;
    if (!byEquip.has(id)) byEquip.set(id, new Map());
    byEquip.get(id).set(week, hours);
  }
  if (!byEquip.size) return null;

  const series = [];
  let ci = 0;
  for (const [name, weekMap] of [...byEquip.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    series.push({
      name,
      type: "bar",
      data: weeks.map((w) => weekMap.get(w) ?? null),
      itemStyle: { color: rainbowColor(ci) },
    });
    ci += 1;
  }

  const oatByWeek = new Map();
  for (const r of filtered) {
    const w = String(r.week_label ?? r.week ?? "");
    const o = Number(r.avg_oa_t ?? r.avg_oat_f);
    if (!w || !Number.isFinite(o)) continue;
    const e = oatByWeek.get(w) ?? { sum: 0, n: 0 };
    e.sum += o;
    e.n += 1;
    oatByWeek.set(w, e);
  }
  const oat = weeks.map((w) => {
    const e = oatByWeek.get(w);
    return e && e.n > 0 ? e.sum / e.n : null;
  });
  const hasOat = oat.some((v) => v != null);
  if (hasOat) {
    series.push({
      name: `Avg OAT ${tempAxisLabel("metric")} (while on)`,
      type: "line",
      yAxisIndex: 1,
      data: oat,
      lineStyle: { width: 2, color: "#333333", type: "dotted" },
      symbol: "circle",
      symbolSize: 7,
      itemStyle: { color: "#333333" },
    });
  }

  const titles = {
    air: "Air side — supply fans",
    boiler: "Boiler plant — HW pumps",
    chiller: "Chiller plant — chillers, CHW/CW pumps, towers",
  };

  return {
    option: {
      backgroundColor: "transparent",
      title: { text: titles[plantGroup] ?? plantGroup },
      tooltip: { trigger: "axis" },
      legend: { top: 28 },
      toolbox: toolboxSaveAsImage(pngStem),
      grid: { left: 56, right: hasOat ? 56 : 24, top: 72, bottom: 64 },
      xAxis: { type: "category", data: weeks, axisLabel: { rotate: -45 } },
      yAxis: [
        { type: "value", name: "Run hours" },
        ...(hasOat
          ? [{ type: "value", name: tempAxisLabel("metric"), position: "right", scale: true }]
          : []),
      ],
      series,
    },
    lineSeries: [],
  };
}

export function mechCoolingOption(rows, pngStem) {
  const individuals = rows.filter(
    (r) =>
      String(r.kind) === "oat_bin" &&
      (!r.series_kind || r.series_kind === "individual_device"),
  );
  const bins = individuals.length ? individuals : rows.filter((r) => String(r.kind) === "oat_bin");
  if (!bins.length) return null;

  const byBin = new Map();
  for (const r of bins) {
    const label = String(r.oat_bin ?? r.bin_label ?? "");
    if (!label) continue;
    const eq = String(r.equipment_id ?? r.label ?? "plant");
    const hours = Number(r.run_hours ?? r.hours);
    if (!Number.isFinite(hours)) continue;
    if (!byBin.has(label)) byBin.set(label, new Map());
    byBin.get(label).set(eq, (byBin.get(label).get(eq) ?? 0) + hours);
  }
  const labels = [...byBin.keys()].sort();
  const eqs = [...new Set(bins.map((r) => String(r.equipment_id ?? r.label ?? "plant")))].sort();
  const series = eqs.map((eq, i) => ({
    name: eq,
    type: "bar",
    stack: "hours",
    data: labels.map((lb) => byBin.get(lb)?.get(eq) ?? null),
    itemStyle: { color: rainbowColor(i) },
  }));

  return {
    option: {
      backgroundColor: "transparent",
      title: { text: "Mechanical cooling — outdoor-air bins" },
      tooltip: { trigger: "axis" },
      legend: { top: 28 },
      toolbox: toolboxSaveAsImage(pngStem),
      grid: { left: 56, right: 24, top: 72, bottom: 64 },
      xAxis: { type: "category", data: labels, name: "OAT bin °C" },
      yAxis: { type: "value", name: "hours" },
      series,
    },
    lineSeries: [],
  };
}

export function economizerDeltaOption(points, unitSystem, dtMinC = ECONOMIZER_DT_MIN_C, pngStem) {
  const usable = points.filter(
    (p) => isIdentifiablePoint(p) && p.delta_or_c != null && p.delta_mr_c != null,
  );
  if (usable.length < 5) return null;

  const scatterData = usable.map((p) => [
    displayDeltaC(p.delta_or_c, unitSystem),
    displayDeltaC(p.delta_mr_c, unitSystem),
    p.damper_fb_pct,
  ]);

  const hasDamper = usable.some((p) => p.damper_fb_pct != null);
  const series = [
    {
      type: "scatter",
      name: "samples",
      data: scatterData,
      symbolSize: 7,
      ...(hasDamper
        ? {
            visualMap: true,
          }
        : { itemStyle: { color: rainbowColor(0), opacity: 0.75 } }),
    },
  ];

  const title = `Economizer free-cooling delta scatter (fan on, |OAT−RAT|≥${displayDeltaC(dtMinC, unitSystem)?.toFixed(1) ?? dtMinC} ${tempAxisLabel(unitSystem).replace("°", "Δ°")})`;

  const option = {
    backgroundColor: "transparent",
    title: { text: title },
    tooltip: { trigger: "item" },
    toolbox: toolboxSaveAsImage(pngStem),
    grid: { left: 56, right: hasDamper ? 72 : 24, top: 56, bottom: 48 },
    xAxis: { type: "value", name: "OAT − RAT", scale: true },
    yAxis: { type: "value", name: "MAT − RAT", scale: true },
    series,
  };

  if (hasDamper) {
    option.visualMap = {
      show: true,
      dimension: 2,
      min: 0,
      max: 100,
      calculable: true,
      orient: "vertical",
      right: 0,
      top: "center",
      text: ["OA damper %", ""],
      inRange: { color: ["#440154", "#31688e", "#35b779", "#fde725"] },
    };
  }

  return { option, lineSeries: [] };
}

export function economizerMatResidOption(points, unitSystem, pngStem) {
  const usable = points.filter((p) => isIdentifiablePoint(p) && p.mat_resid_c != null);
  if (usable.length < 5) return null;
  const byEq = new Map();
  for (const p of usable) {
    const eq = String(p.equipment_id || "AHU");
    if (!byEq.has(eq)) byEq.set(eq, []);
    byEq.get(eq).push(p);
  }
  const lineSeries = [];
  const series = [];
  let ci = 0;
  for (const [eq, rows] of byEq) {
    const data = rows
      .map((r) => [parseTs(r.timestamp_utc), displayDeltaC(r.mat_resid_c, unitSystem)])
      .filter((d) => d[0] != null);
    lineSeries.push({ name: eq, data });
    series.push({
      name: eq,
      type: "line",
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 1.4, color: rainbowColor(ci) },
      data,
    });
    ci += 1;
  }
  return {
    option: {
      backgroundColor: "transparent",
      title: {
        text: "MAT residual (meas − mixing model from OA damper) — fan on, identifiable",
      },
      tooltip: { trigger: "axis" },
      legend: { top: 28 },
      toolbox: toolboxSaveAsImage(pngStem),
      grid: { left: 56, right: 24, top: 72, bottom: 48 },
      xAxis: { type: "time", name: "time" },
      yAxis: { type: "value", name: `MAT residual (${tempAxisLabel(unitSystem)})` },
      series,
    },
    lineSeries,
  };
}

export function economizerTempsOverlayOption(points, unitSystem, equipmentId, pngStem) {
  const eq =
    equipmentId && points.some((p) => String(p.equipment_id) === equipmentId)
      ? equipmentId
      : String(points[0]?.equipment_id ?? "");
  const rows = points.filter((p) => String(p.equipment_id) === eq);
  if (rows.length < 3) return null;

  const tempRoles = [
    ["OAT", "oa_t"],
    ["RAT", "rat"],
    ["MAT", "mat"],
    ["SAT", "sat"],
  ];
  const lineSeries = [];
  const series = [];
  let ci = 0;
  for (const [label, key] of tempRoles) {
    const data = rows
      .map((r) => [parseTs(r.timestamp_utc), displayTempC(r[key], unitSystem)])
      .filter((d) => d[0] != null && d[1] != null);
    if (!data.length) continue;
    lineSeries.push({ name: label, data });
    series.push({
      name: label,
      type: "line",
      yAxisIndex: 0,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 1.5, color: rainbowColor(ci) },
      data,
    });
    ci += 1;
  }
  const damperData = rows
    .map((r) => [parseTs(r.timestamp_utc), Number(r.damper_fb_pct)])
    .filter((d) => d[0] != null && Number.isFinite(d[1]));
  if (damperData.length) {
    lineSeries.push({ name: "OA damper %", data: damperData });
    series.push({
      name: "OA damper %",
      type: "line",
      yAxisIndex: 1,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 1.2, color: rainbowColor(1), type: "dashed" },
      data: damperData,
    });
  }
  if (!series.length) return null;

  return {
    option: {
      backgroundColor: "transparent",
      title: { text: `Economizer temps — ${eq}` },
      tooltip: { trigger: "axis" },
      legend: { top: 28 },
      toolbox: toolboxSaveAsImage(pngStem),
      grid: { left: 56, right: 56, top: 72, bottom: 48 },
      xAxis: { type: "time" },
      yAxis: [
        { type: "value", name: tempAxisLabel(unitSystem), scale: true },
        { type: "value", name: "OA damper %", min: 0, max: 100, position: "right" },
      ],
      series,
    },
    lineSeries,
  };
}

export function basOverlayOption(points, unitSystem, oatErr = 2, pngStem) {
  if (!points.length) return null;
  const lineSeries = [];
  const bas = points
    .filter((p) => p.bas_oat_c != null)
    .map((p) => [parseTs(p.timestamp_utc), displayTempC(p.bas_oat_c, unitSystem)]);
  const web = points
    .filter((p) => p.web_oat_c != null)
    .map((p) => [parseTs(p.timestamp_utc), displayTempC(p.web_oat_c, unitSystem)]);
  if (!bas.length && !web.length) return null;

  const err = displayDeltaC(oatErr, unitSystem) ?? oatErr;
  const bandHi = points
    .filter((p) => p.web_oat_c != null)
    .map((p) => [parseTs(p.timestamp_utc), displayTempC(Number(p.web_oat_c) + oatErr, unitSystem)]);
  const bandLo = points
    .filter((p) => p.web_oat_c != null)
    .map((p) => [parseTs(p.timestamp_utc), displayTempC(Number(p.web_oat_c) - oatErr, unitSystem)]);

  const series = [];
  if (bandHi.length && bandLo.length) {
    series.push(
      { name: "band top", type: "line", data: bandHi, lineStyle: { opacity: 0 }, stack: "band", symbol: "none" },
      {
        name: `±${err} band`,
        type: "line",
        data: bandLo,
        lineStyle: { opacity: 0 },
        areaStyle: { color: "rgba(234,179,8,0.18)" },
        stack: "band",
        symbol: "none",
      },
    );
  }
  if (web.length) {
    lineSeries.push({ name: "Web OAT", data: web });
    series.push({
      name: "Web OAT",
      type: "line",
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 1.4, color: rainbowColor(3) },
      data: web,
    });
  }
  if (bas.length) {
    lineSeries.push({ name: "BAS oa_t", data: bas });
    series.push({
      name: "BAS oa_t",
      type: "line",
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 1.4, color: rainbowColor(0) },
      data: bas,
    });
  }

  return {
    option: {
      backgroundColor: "transparent",
      title: { text: `BAS vs web outdoor-air temperature (±${err} band)` },
      tooltip: { trigger: "axis" },
      legend: { top: 28 },
      toolbox: toolboxSaveAsImage(pngStem ?? "bas_vs_web_oat"),
      grid: { left: 56, right: 24, top: 72, bottom: 48 },
      xAxis: { type: "time", name: "time" },
      yAxis: { type: "value", name: tempAxisLabel(unitSystem), scale: true },
      series,
    },
    lineSeries,
  };
}

export function basHistOption(rows, unitSystem, pngStem) {
  const histRows = rows.filter((r) => String(r.kind) === "delta_hist" || r.count != null);
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
      title: { text: "BAS vs web outdoor-air temperature deviation" },
      toolbox: toolboxSaveAsImage(pngStem ?? "bas_web_oat_deviation_hist"),
      grid: { left: 56, right: 24, top: 56, bottom: 48 },
      xAxis: { type: "category", data: labels },
      yAxis: { type: "value", name: "count" },
      series: [{ type: "bar", data: counts, itemStyle: { color: "#f8961e" } }],
    },
    lineSeries: [],
  };
}
