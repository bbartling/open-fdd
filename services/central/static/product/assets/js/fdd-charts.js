/**
 * FDD rule plots — stacked unit-family grids + bottom confirmed_fault lane (Plotly parity).
 */
import { rainbowColor, toolboxSaveAsImage, linkedTimeZoom, faultLaneStyle } from "./chart-theme.js";
import { ruleLabelPlotTitle } from "./rule-labels.js";
import { familyOrderKeys, lookupRoleBinding, resolveRoleUnit, unitFamily } from "./role-units.js";
import { basOverlayOption } from "./overview-rcx-charts.js";

const FAULT_ROLE_KEYS = new Set(["confirmed_fault", "fault"]);

export function confirmedFaultPlotY(v) {
  if (v == null) return null;
  if (v === true || v === 1) return 1;
  if (v === false || v === 0) return 0;
  return null;
}

function parseTimestamp(raw) {
  const s = String(raw ?? "");
  if (!s || s.includes("PrimitiveArray")) return null;
  const ms = Date.parse(s);
  return Number.isFinite(ms) ? ms : null;
}

function rowValue(row, role) {
  const v = row[role];
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function seriesDataForRole(rows, role) {
  const out = [];
  for (const r of rows) {
    const t = parseTimestamp(r.timestamp_utc ?? r.ts ?? r.timestamp);
    const v = rowValue(r, role);
    out.push([t, v]);
  }
  return out;
}

/**
 * @returns {{ option: object, lineSeries: Array, pngStem?: string, gridCount: number, hasFaultLane: boolean }}
 */
export function ruleResultChartOption(rows, opts) {
  const roles = (opts.roles || []).filter((r) => !FAULT_ROLE_KEYS.has(r));
  if (!rows.length || !roles.length) {
    return { option: null, lineSeries: [], gridCount: 0, hasFaultLane: false };
  }

  const unitSystem = opts.unitSystem ?? "metric";
  const roleUnitIndex = opts.roleUnitIndex ?? null;
  const equipmentId = opts.equipmentId ?? "";

  const groups = new Map();
  for (const role of roles) {
    const binding = lookupRoleBinding(roleUnitIndex, equipmentId, role);
    const unit = resolveRoleUnit(role, unitSystem, binding);
    let fam = unit ? unitFamily(unit) : `other:${role}`;
    if (unit === "bool" || unit === "0/1") fam = "bool";
    const data = seriesDataForRole(rows, role);
    if (!data.some(([, v]) => v != null)) continue;
    const list = groups.get(fam) ?? [];
    list.push({ role, unit, data });
    groups.set(fam, list);
  }

  const famKeys = familyOrderKeys([...groups.keys()]);
  const faultRaw = opts.confirmedFault;
  const hasFault = Boolean(
    faultRaw &&
      faultRaw.length === rows.length &&
      faultRaw.some((v) => v != null),
  );
  const nSig = famKeys.length;
  if (nSig === 0 && !hasFault) {
    return { option: null, lineSeries: [], gridCount: 0, hasFaultLane: false };
  }

  const sigRowH = 90;
  const faultRowH = hasFault ? 90 : 0;
  const topPad = 48;
  const bottomPad = 72;
  const heightPx = Math.max(320, sigRowH * nSig + faultRowH + topPad + bottomPad);

  const grids = [];
  const xAxes = [];
  const yAxes = [];
  const series = [];
  const lineSeries = [];
  let colorI = 0;
  let yAxisIndex = 0;

  for (let i = 0; i < nSig; i++) {
    const top = topPad + i * sigRowH;
    grids.push({ left: 64, right: 24, top, height: sigRowH - 12, containLabel: false });
    xAxes.push({
      type: "time",
      gridIndex: i,
      show: false,
      axisPointer: { show: true },
    });
    const items = groups.get(famKeys[i]) ?? [];
    const unitsIn = [...new Set(items.map((it) => it.unit).filter(Boolean))].sort();
    const yName = unitsIn.length ? unitsIn.join(", ") : famKeys[i];
    yAxes.push({
      type: "value",
      gridIndex: i,
      name: yName,
      nameTextStyle: { fontSize: 11 },
      scale: true,
    });
    for (const item of items) {
      const label = item.unit ? `${item.role} (${item.unit})` : item.role;
      series.push({
        name: label,
        type: "line",
        xAxisIndex: i,
        yAxisIndex: yAxisIndex,
        showSymbol: false,
        connectNulls: false,
        lineStyle: { width: 1.6, color: rainbowColor(colorI) },
        data: item.data,
      });
      lineSeries.push({ name: label, data: item.data.filter((d) => d[0] != null) });
      colorI += 1;
    }
    yAxisIndex += 1;
  }

  let faultGridIndex = nSig;
  if (hasFault && faultRaw) {
    const top = topPad + Math.max(nSig, 0) * sigRowH;
    grids.push({ left: 64, right: 24, top, height: Math.max(60, faultRowH - 12) });
    xAxes.push({
      type: "time",
      gridIndex: faultGridIndex,
      name: "timestamp",
      nameLocation: "middle",
      nameGap: 28,
      axisPointer: { show: true },
    });
    yAxes.push({
      type: "value",
      gridIndex: faultGridIndex,
      min: -0.05,
      max: 1.15,
      interval: 1,
      name: "fault",
      axisLabel: {
        formatter: (val) => (val === 0 ? "ok" : val === 1 ? "fault" : String(val)),
      },
    });
    const faultData = rows.map((r, idx) => {
      const t = parseTimestamp(r.timestamp_utc ?? r.ts ?? r.timestamp);
      return [t, confirmedFaultPlotY(faultRaw[idx])];
    });
    const fl = faultLaneStyle();
    series.push({
      name: "confirmed_fault",
      type: "line",
      xAxisIndex: faultGridIndex,
      yAxisIndex: yAxisIndex,
      step: "end",
      showSymbol: false,
      connectNulls: false,
      lineStyle: fl.line,
      areaStyle: fl.area,
      data: faultData,
    });
    lineSeries.push({ name: "confirmed_fault", data: faultData });
    yAxisIndex += 1;
  } else if (nSig > 0) {
    xAxes[nSig - 1].show = true;
    xAxes[nSig - 1].name = "timestamp";
    xAxes[nSig - 1].nameLocation = "middle";
    xAxes[nSig - 1].nameGap = 28;
  }

  const xCount = grids.length;
  const stem = opts.pngStem ?? `fdd_${opts.ruleId}_${opts.equipmentId}`.replace(/[^\w.-]+/g, "_");

  const option = {
    backgroundColor: "transparent",
    title: {
      text: ruleLabelPlotTitle(opts.ruleId, opts.equipmentId, opts.description),
      left: 8,
      top: 4,
    },
    tooltip: { trigger: "axis", axisPointer: { type: "line", link: [{ xAxisIndex: "all" }] } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    legend: { top: 22, type: "scroll" },
    toolbox: toolboxSaveAsImage(stem),
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: linkedTimeZoom(xCount),
    series,
  };

  return {
    option,
    lineSeries,
    pngStem: stem,
    gridCount: grids.length,
    hasFaultLane: hasFault,
  };
}

export function isOatMeteoRule(ruleId) {
  const u = String(ruleId ?? "")
    .trim()
    .toUpperCase();
  return u === "OAT-METEO" || u === "WEATHER" || u === "WX-1" || u.includes("OAT-METEO");
}

export function expandFddPlotRoles(ruleId, roles, rows) {
  const out = [...(roles || [])];
  const id = String(ruleId ?? "").trim().toUpperCase();
  if (!/^ECON-[1-7]$/.test(id)) return out;
  if (out.includes("oa_damper_pct")) return out;
  const hasDamper = (rows || []).some((r) => rowValue(r, "oa_damper_pct") != null);
  if (hasDamper) out.push("oa_damper_pct");
  return out;
}

/** Weather overlay + fault lane for OAT-METEO rules. */
export function oatMeteoFddOption(points, faultX, confirmedFault, opts) {
  const overlay = basOverlayOption(points, "metric");
  if (!overlay?.option) return ruleResultChartOption([], opts);

  const fault = confirmedFault || [];
  const hasFault =
    fault.length > 0 && fault.length === (faultX || []).length && fault.some((v) => v != null);

  if (!hasFault) {
    return {
      option: {
        ...overlay.option,
        title: { text: ruleLabelPlotTitle(opts.ruleId, opts.equipmentId, opts.description) },
        toolbox: toolboxSaveAsImage(opts.pngStem ?? `fdd_${opts.ruleId}_weather`),
      },
      lineSeries: overlay.lineSeries,
      gridCount: 1,
      hasFaultLane: false,
    };
  }

  const rows = (faultX || []).map((x, i) => ({
    timestamp_utc: x,
    confirmed_fault: fault[i],
  }));
    const faultData = (faultX || []).map((x, i) => {
      const ms = Date.parse(String(x ?? ""));
      const t = Number.isFinite(ms) ? ms : null;
      return [t, confirmedFaultPlotY(fault[i])];
    });
    const fl = faultLaneStyle();
    const signalH = 280;
    const faultH = 90;
    const merged = {
      ...overlay.option,
      title: { text: ruleLabelPlotTitle(opts.ruleId, opts.equipmentId, opts.description) },
      grid: [
        { left: 64, right: 24, top: 48, height: signalH },
        { left: 64, right: 24, top: 48 + signalH + 8, height: faultH },
      ],
      xAxis: [
        { ...(overlay.option.xAxis?.[0] ?? overlay.option.xAxis), gridIndex: 0, show: false },
        {
          type: "time",
          gridIndex: 1,
          name: "timestamp",
          nameLocation: "middle",
          nameGap: 28,
        },
      ],
      yAxis: [
        { ...(overlay.option.yAxis?.[0] ?? overlay.option.yAxis), gridIndex: 0 },
        {
          type: "value",
          gridIndex: 1,
          min: -0.05,
          max: 1.15,
          interval: 1,
          name: "fault",
          axisLabel: {
            formatter: (val) => (val === 0 ? "ok" : val === 1 ? "fault" : String(val)),
          },
        },
      ],
      series: [
        ...(overlay.option.series || []).map((s) => ({ ...s, xAxisIndex: 0, yAxisIndex: 0 })),
        {
          name: "confirmed_fault",
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 1,
          step: "end",
          showSymbol: false,
          connectNulls: false,
          lineStyle: fl.line,
          areaStyle: fl.area,
          data: faultData,
        },
      ],
      dataZoom: linkedTimeZoom(2),
      toolbox: toolboxSaveAsImage(opts.pngStem ?? `fdd_${opts.ruleId}_weather`),
    };
  return {
    option: merged,
    lineSeries: [
      ...(overlay.lineSeries || []),
      { name: "confirmed_fault", data: faultData.filter((d) => d[0] != null) },
    ],
    gridCount: 2,
    hasFaultLane: true,
  };
}

/** @deprecated name — use ruleResultChartOption */
export function fddPlotOption(rows, roles, hasConfirmedFault, meta = {}) {
  const confirmedFault = hasConfirmedFault
    ? rows.map((r) => r.confirmed_fault ?? r.fault)
    : undefined;
  const expanded = expandFddPlotRoles(meta.ruleId, roles, rows);
  if (isOatMeteoRule(meta.ruleId) && meta.weatherPoints) {
    return oatMeteoFddOption(meta.weatherPoints, rows.map((r) => r.timestamp_utc ?? r.ts), confirmedFault, {
      ruleId: meta.ruleId,
      equipmentId: meta.equipmentId,
      roles: expanded,
    });
  }
  return ruleResultChartOption(rows, {
    ruleId: meta.ruleId ?? "rule",
    equipmentId: meta.equipmentId ?? "",
    roles: expanded,
    confirmedFault,
  });
}
