/**
 * vibe19-style multi-equipment Plotly builders for RCx / Overview / FDD.
 */
import {
  fingerprintJson,
  type PlotlyFigure,
  type PlotlyTrace,
} from "./plotDataset";
import { overviewChartLayout, rainbowColor } from "./plotlyTheme";
import { familyOrderKeys, resolveRoleUnit, unitFamily } from "./roleUnits";

/** Outlier red — vibe19 charts.py stroke for z-score outliers. */
export const OUTLIER_RED = "#dc2626";

/** Equipment ids whose primary-series mean is ≥ outlierZ σ from cohort mean. */
export function outlierEquipmentIds(
  points: Array<Record<string, unknown>>,
  opts?: { outlierZ?: number; valueKey?: string; primaryOnly?: boolean },
): Set<string> {
  const zCut = opts?.outlierZ ?? 2.5;
  const valueKey = opts?.valueKey ?? "value_f";
  const primaryOnly = opts?.primaryOnly ?? true;
  const means = new Map<string, { sum: number; n: number }>();
  for (const p of points) {
    if (primaryOnly) {
      const series = String(p.series ?? "primary");
      if (series !== "primary") continue;
    }
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
  const vals = [...means.entries()].map(([eq, { sum, n }]) => ({
    eq,
    mean: sum / n,
  }));
  if (vals.length < 3) return new Set();
  const mu = vals.reduce((a, v) => a + v.mean, 0) / vals.length;
  const sd = Math.sqrt(
    vals.reduce((a, v) => a + (v.mean - mu) ** 2, 0) / vals.length,
  );
  if (!(sd > 0)) return new Set();
  const out = new Set<string>();
  for (const v of vals) {
    if (Math.abs(v.mean - mu) / sd >= zCut) out.add(v.eq);
  }
  return out;
}

/** True when an RCx figure accidentally grew an FDD fault lane. */
export function rcxFigureHasFaultLane(fig: PlotlyFigure | null): boolean {
  if (!fig) return false;
  if (fig.data.some((t) => String(t.name) === "confirmed_fault")) return true;
  for (const [k, v] of Object.entries(fig.layout ?? {})) {
    if (!/^yaxis\d*$/.test(k) || !v || typeof v !== "object") continue;
    const title = (v as { title?: string | { text?: string } }).title;
    const text = typeof title === "string" ? title : title?.text;
    if (text === "fault") return true;
  }
  return false;
}

export function multiEquipmentTimeseries(
  points: Array<Record<string, unknown>>,
  opts: { title: string; yTitle?: string },
): PlotlyFigure | null {
  if (!points.length) return null;
  const outliers = outlierEquipmentIds(points);
  const byKey = new Map<string, Array<Record<string, unknown>>>();
  for (const p of points) {
    const eq = String(p.equipment_id ?? "eq");
    const series = String(p.series ?? "primary");
    const name =
      series === "primary"
        ? eq
        : series === "overlay"
          ? `${eq} · setpoint`
          : series === "return"
            ? `${eq} · return`
            : series === "delta_t"
              ? `${eq} · ΔT`
              : series === "motor"
                ? `${eq} · motor on`
                : `${eq} · ${series}`;
    const list = byKey.get(name) ?? [];
    list.push(p);
    byKey.set(name, list);
  }
  const data: PlotlyTrace[] = [];
  let colorI = 0;
  const colorsByEq = new Map<string, string>();
  const primaryNames = [...byKey.keys()]
    .filter((n) => !n.includes(" · "))
    .sort((a, b) => a.localeCompare(b));
  for (const name of primaryNames) {
    const eq = name;
    const isOut = outliers.has(eq);
    const color = isOut ? OUTLIER_RED : rainbowColor(colorI);
    if (!isOut) colorI += 1;
    colorsByEq.set(eq, color);
    const rows = byKey.get(name) ?? [];
    data.push({
      type: "scatter",
      mode: "lines",
      name: isOut ? `${name} ★` : name,
      x: rows.map((r) => String(r.timestamp_utc ?? "")),
      y: rows.map((r) => {
        const v = r.value_f;
        if (v == null || v === "") return null;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      line: {
        width: isOut ? 2.4 : 1.4,
        color,
        dash: isOut ? "dash" : "solid",
      },
      connectgaps: false,
    });
  }
  // Non-primary overlays (setpoint / return / ΔT) stay on primary y.
  for (const [name, rows] of [...byKey.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    if (!name.includes(" · ") || name.endsWith(" · motor on")) continue;
    const eq = name.split(" · ")[0] ?? name;
    const color = colorsByEq.get(eq) ?? rainbowColor(colorI++);
    data.push({
      type: "scatter",
      mode: "lines",
      name,
      x: rows.map((r) => String(r.timestamp_utc ?? "")),
      y: rows.map((r) => {
        const v = r.value_f;
        if (v == null || v === "") return null;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      line: { width: 1.2, color, dash: "dot" },
      connectgaps: false,
    });
  }
  let hasMotor = false;
  for (const [name, rows] of [...byKey.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    if (!name.endsWith(" · motor on")) continue;
    const eq = name.split(" · ")[0] ?? name;
    const color = colorsByEq.get(eq);
    if (!color) continue;
    hasMotor = true;
    data.push({
      type: "scatter",
      mode: "lines",
      name,
      x: rows.map((r) => String(r.timestamp_utc ?? "")),
      y: rows.map((r) => {
        const v = r.value_f;
        if (v == null || v === "") return null;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      yaxis: "y2",
      line: { width: 1.0, color, dash: "dot", shape: "hv" },
      opacity: 0.7,
      connectgaps: false,
    } as PlotlyTrace);
  }
  const extra: Record<string, unknown> = {
    title: opts.title,
    xaxis: {
      title: "timestamp",
      type: "date",
      autorange: true,
      tickangle: -30,
    },
  };
  if (hasMotor) {
    extra.yaxis2 = {
      overlaying: "y",
      side: "right",
      range: [-0.08, 1.4],
      tickvals: [0, 1],
      ticktext: ["off", "on"],
      title: { text: "motor on", font: { size: 10 } },
      showgrid: false,
      autorange: false,
    };
  }
  return {
    data,
    layout: overviewChartLayout({
      xTitle: "timestamp",
      yTitle: opts.yTitle ?? "value",
      height: Math.max(380, 40 + 14 * Math.min(byKey.size, 16)),
      tickangle: -30,
      uirevision: `rcx-ts:${fingerprintJson(points.slice(0, 50))}`,
      extra,
    }),
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/rcx/preset",
    },
  };
}

export function oatScatter(
  points: Array<Record<string, unknown>>,
  opts: { title: string; yTitle: string; xTitle?: string },
): PlotlyFigure | null {
  if (!points.length) return null;
  const byEq = new Map<string, Array<Record<string, unknown>>>();
  for (const p of points) {
    const eq = String(p.equipment_id ?? "eq");
    const list = byEq.get(eq) ?? [];
    list.push(p);
    byEq.set(eq, list);
  }
  const outliers = outlierEquipmentIds(points, {
    valueKey: "y_f",
    primaryOnly: false,
  });
  const data: PlotlyTrace[] = [];
  let i = 0;
  for (const [eq, rows] of [...byEq.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    const isOut = outliers.has(eq);
    const color = isOut ? OUTLIER_RED : rainbowColor(i);
    if (!isOut) i += 1;
    data.push({
      type: "scatter",
      mode: "markers",
      name: isOut ? `${eq} ★` : eq,
      x: rows.map((r) => {
        const v = r.oat_f;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      y: rows.map((r) => {
        const v = r.y_f;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      marker: { size: isOut ? 7 : 6, opacity: 0.65, color },
    });
  }
  const hasDry = points.some((p) => p.dry_bulb_f != null);
  if (hasDry) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: "dry-bulb ref (x)",
      x: points.map((r) => {
        const v = r.dry_bulb_f;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      y: points.map((r) => {
        const v = r.y_f;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      marker: { size: 5, opacity: 0.35, symbol: "x", color: "#64748b" },
    });
  }
  return {
    data,
    layout: overviewChartLayout({
      xTitle: opts.xTitle ?? "Web dry-bulb °F",
      yTitle: opts.yTitle,
      height: 420,
      tickangle: 0,
      uirevision: `rcx-oat:${fingerprintJson(points.slice(0, 50))}`,
      extra: { title: opts.title },
    }),
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/rcx/preset",
    },
  };
}

export function multiEquipmentBox(
  points: Array<Record<string, unknown>>,
  opts: { title: string; yTitle?: string },
): PlotlyFigure | null {
  if (!points.length) return null;
  const byEq = new Map<string, number[]>();
  for (const p of points) {
    const eq = String(p.equipment_id ?? "eq");
    const v = p.value_f;
    const n = typeof v === "number" ? v : Number(v);
    if (!Number.isFinite(n)) continue;
    const list = byEq.get(eq) ?? [];
    list.push(n);
    byEq.set(eq, list);
  }
  if (!byEq.size) return null;
  const outliers = outlierEquipmentIds(points);
  const data: PlotlyTrace[] = [];
  let i = 0;
  for (const [eq, ys] of [...byEq.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    const isOut = outliers.has(eq);
    const color = isOut ? OUTLIER_RED : rainbowColor(i);
    if (!isOut) i += 1;
    data.push({
      type: "box",
      name: isOut ? `${eq} ★` : eq,
      y: ys,
      marker: { color },
      boxpoints: "outliers",
    } as PlotlyTrace);
  }
  return {
    data,
    layout: overviewChartLayout({
      xTitle: "equipment",
      yTitle: opts.yTitle ?? "value",
      height: 420,
      tickangle: -20,
      uirevision: `rcx-box:${fingerprintJson([...byEq.keys()])}`,
      extra: { title: opts.title, boxmode: "group" },
    }),
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/rcx/preset",
    },
  };
}

/** vibe19 comfort donut — in-band vs fail samples from ranking envelope rows. */
export function comfortDonut(
  rows: Array<Record<string, unknown>>,
  opts?: { title?: string },
): PlotlyFigure | null {
  if (!rows.length) return null;
  let nFail = 0;
  let nOk = 0;
  for (const r of rows) {
    const fail = Number(r.n_fail);
    const samples = Number(r.n_samples);
    if (Number.isFinite(fail) && Number.isFinite(samples) && samples > 0) {
      nFail += fail;
      nOk += Math.max(0, samples - fail);
      continue;
    }
    const pct = Number(r.fail_pct ?? r.value_f);
    if (Number.isFinite(pct) && pct > 0) nFail += 1;
    else nOk += 1;
  }
  if (nFail + nOk <= 0) return null;
  return {
    data: [
      {
        type: "pie",
        name: "comfort",
        labels: ["in band", "outside band"],
        values: [nOk, nFail],
        marker: { colors: ["#16a34a", "#dc2626"] },
        hole: 0.45,
      } as PlotlyTrace,
    ],
    layout: {
      title: opts?.title ?? "Zone comfort (occupied hours)",
      height: 320,
      showlegend: true,
      paper_bgcolor: "white",
      plot_bgcolor: "white",
      uirevision: `comfort-donut:${nOk}:${nFail}`,
    },
    meta: { point_count: rows.length, provenance: "RCx ranking rows" },
  };
}

export function rankingBars(
  points: Array<Record<string, unknown>>,
  opts: { title: string; yTitle?: string },
): PlotlyFigure | null {
  if (!points.length) return null;
  const sorted = [...points].sort((a, b) => {
    const av = Number(a.value_f ?? a.fail_pct ?? 0);
    const bv = Number(b.value_f ?? b.fail_pct ?? 0);
    return bv - av;
  });
  const outliers = outlierEquipmentIds(sorted, { primaryOnly: false });
  return {
    data: [
      {
        type: "bar",
        name: "fail %",
        x: sorted.map((r) => String(r.equipment_id ?? "")),
        y: sorted.map((r) => {
          const v = r.value_f ?? r.fail_pct;
          const n = typeof v === "number" ? v : Number(v);
          return Number.isFinite(n) ? n : null;
        }),
        marker: {
          color: sorted.map((r, i) =>
            outliers.has(String(r.equipment_id ?? ""))
              ? OUTLIER_RED
              : rainbowColor(i),
          ),
        },
      },
    ],
    layout: overviewChartLayout({
      xTitle: "equipment",
      yTitle: opts.yTitle ?? "comfort fail %",
      height: Math.max(360, 28 * Math.min(sorted.length, 24)),
      tickangle: -35,
      uirevision: `rcx-rank:${fingerprintJson(sorted.slice(0, 20))}`,
      extra: { title: opts.title },
    }),
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/rcx/preset",
    },
  };
}

export function meteringCharts(
  points: Array<Record<string, unknown>>,
  opts: { title: string; ddLabel?: string; energyYTitle?: string },
): PlotlyFigure | null {
  if (!points.length) return null;
  const byEq = new Map<string, Array<Record<string, unknown>>>();
  for (const p of points) {
    const eq = String(p.equipment_id ?? "eq");
    const list = byEq.get(eq) ?? [];
    list.push(p);
    byEq.set(eq, list);
  }
  const barData: PlotlyTrace[] = [];
  const scatterData: PlotlyTrace[] = [];
  let i = 0;
  for (const [eq, rows] of [...byEq.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    const color = rainbowColor(i);
    barData.push({
      type: "bar",
      name: `${eq} · energy`,
      x: rows.map((r) => String(r.month ?? "")),
      y: rows.map((r) => {
        const v = r.energy ?? r.value_f;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      marker: { color },
      xaxis: "x",
      yaxis: "y",
    });
    scatterData.push({
      type: "scatter",
      mode: "markers",
      name: `${eq} · vs DD`,
      x: rows.map((r) => {
        const v = r.degree_days ?? r.oat_f;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      y: rows.map((r) => {
        const v = r.energy ?? r.y_f;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      marker: { size: 8, color, opacity: 0.75 },
      xaxis: "x2",
      yaxis: "y2",
    });
    i += 1;
  }
  const energyTitle = opts.energyYTitle ?? "energy";
  return {
    data: [...barData, ...scatterData],
    layout: {
      title: opts.title,
      grid: { rows: 1, columns: 2, pattern: "independent" },
      xaxis: { title: "month", domain: [0, 0.45] },
      yaxis: { title: energyTitle },
      xaxis2: { title: opts.ddLabel ?? "degree-days", domain: [0.55, 1] },
      yaxis2: { title: energyTitle, anchor: "x2" },
      height: 420,
      legend: { orientation: "h" },
      paper_bgcolor: "white",
      plot_bgcolor: "white",
      uirevision: `rcx-meter:${fingerprintJson(points.slice(0, 30))}`,
    },
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/rcx/preset",
    },
  };
}

/** FDD rule_result_chart — vibe19 stacked unit-family axes + fault swim lane at bottom. */
export function ruleResultChart(
  rows: Array<Record<string, unknown>>,
  opts: {
    equipmentId: string;
    ruleId: string;
    roles: string[];
    confirmedFault?: Array<boolean | number | null>;
  },
): PlotlyFigure | null {
  if (!rows.length || !opts.roles.length) return null;

  const x = rows.map((r) => {
    const raw = r.timestamp_utc ?? r.timestamp ?? "";
    const s = String(raw);
    // Reject Arrow Debug dumps that used to leak into JSON.
    if (s.includes("PrimitiveArray")) return null;
    return s || null;
  });

  type SeriesItem = { role: string; unit: string; y: Array<number | null> };
  const groups = new Map<string, SeriesItem[]>();
  for (const role of opts.roles) {
    if (role === "confirmed_fault" || role === "fault") continue;
    const unit = resolveRoleUnit(role);
    let fam = unit ? unitFamily(unit) : `other:${role}`;
    if (unit === "bool" || unit === "0/1") fam = "bool";
    const y = rows.map((r) => {
      const v = r[role];
      if (v == null || v === "") return null;
      const n = typeof v === "number" ? v : Number(v);
      return Number.isFinite(n) ? n : null;
    });
    if (!y.some((v) => v != null)) continue;
    const list = groups.get(fam) ?? [];
    list.push({ role, unit, y });
    groups.set(fam, list);
  }

  const famKeys = familyOrderKeys([...groups.keys()]);
  const fault = opts.confirmedFault;
  const hasFault = Boolean(
    fault &&
      fault.length === rows.length &&
      fault.some((v) => v != null),
  );
  const nSig = famKeys.length;
  if (nSig === 0 && !hasFault) return null;

  const faultW = hasFault ? 0.55 : 0;
  const sigW = Math.max(nSig, 1);
  const totalW = sigW + faultW;
  const usable = 0.88;
  const gap = 0.02;
  const domains: Array<[number, number]> = [];
  let top = 1.0;
  for (let i = 0; i < nSig; i++) {
    const h = usable * (1.0 / totalW);
    domains.push([Math.max(0, top - h), top]);
    top = top - h - gap;
  }
  let faultDomain: [number, number] | null = null;
  if (hasFault) {
    const h = usable * (faultW / totalW);
    faultDomain = [Math.max(0, top - h), top];
  }

  const data: PlotlyTrace[] = [];
  const layout: Record<string, unknown> = {
    title: `${opts.ruleId} · ${opts.equipmentId}`,
    legend: { orientation: "h", yanchor: "bottom", y: 1.02, x: 0, font: { size: 10 } },
    hovermode: "x unified",
    height: Math.max(320, 90 * nSig + (hasFault ? 90 : 0) + 80),
    margin: { l: 64, r: 24, t: 28, b: 64 },
    paper_bgcolor: "white",
    plot_bgcolor: "white",
    uirevision: `fdd:${opts.ruleId}:${opts.equipmentId}`,
  };

  let colorI = 0;
  let lastY = "y";
  for (let i = 0; i < famKeys.length; i++) {
    const fam = famKeys[i];
    const axisI = i + 1;
    const yname = axisI === 1 ? "y" : `y${axisI}`;
    lastY = yname;
    const items = groups.get(fam) ?? [];
    const unitsIn = [...new Set(items.map((it) => it.unit).filter(Boolean))].sort();
    const title = unitsIn.length ? unitsIn.join(", ") : fam;
    const axKey = axisI === 1 ? "yaxis" : `yaxis${axisI}`;
    layout[axKey] = {
      domain: domains[i],
      title: { text: title, font: { size: 11 } },
      showgrid: true,
      zeroline: false,
      autorange: true,
      anchor: "x",
    };
    for (const item of items) {
      const label = item.unit ? `${item.role} (${item.unit})` : item.role;
      data.push({
        type: "scatter",
        mode: "lines",
        name: label,
        x,
        y: item.y,
        yaxis: yname,
        line: { width: 1.6, color: rainbowColor(colorI) },
        connectgaps: false,
        // Signal traces: lines only — fill reserved for confirmed_fault lane.
      });
      colorI += 1;
    }
  }

  if (hasFault && faultDomain && fault) {
    const axisI = nSig + 1;
    const yname = axisI === 1 ? "y" : `y${axisI}`;
    lastY = yname;
    const axKey = axisI === 1 ? "yaxis" : `yaxis${axisI}`;
    layout[axKey] = {
      domain: faultDomain,
      title: { text: "fault", font: { size: 11 } },
      range: [-0.05, 1.15],
      tickvals: [0, 1],
      ticktext: ["ok", "fault"],
      showgrid: true,
      anchor: "x",
    };
    data.push({
      type: "scatter",
      mode: "lines",
      name: "confirmed_fault",
      x,
      y: fault.map((v) => (v === true || v === 1 ? 1 : 0)),
      yaxis: yname,
      line: { width: 0.8, color: "rgba(220,38,38,0.9)", shape: "hv" },
      fill: "tozeroy",
      fillcolor: "rgba(239,68,68,0.35)",
    });
  }

  layout.xaxis = {
    title: "timestamp",
    type: "date",
    showgrid: true,
    autorange: true,
    anchor: lastY,
  };

  return {
    data,
    layout,
    meta: {
      equipment_id: opts.equipmentId,
      rule_id: opts.ruleId,
      roles: opts.roles,
      point_count: rows.length,
      provenance: "GET /api/fdd/series",
    },
  };
}

/** Sensor health coverage matrix as a Plotly heatmap (equipment × role). */
export function sensorHealthHeatmap(
  rows: Array<Record<string, unknown>>,
  opts?: { title?: string },
): PlotlyFigure | null {
  if (!rows.length) return null;
  const eqs = [...new Set(rows.map((r) => String(r.equipment_id ?? "")))].sort();
  const roles = [...new Set(rows.map((r) => String(r.role ?? "")))].sort();
  if (!eqs.length || !roles.length) return null;
  const z = eqs.map((eq) =>
    roles.map((role) => {
      const hit = rows.find(
        (r) =>
          String(r.equipment_id ?? "") === eq && String(r.role ?? "") === role,
      );
      if (!hit) return null;
      const cov = Number(hit.coverage_pct);
      return Number.isFinite(cov) ? cov : null;
    }),
  );
  return {
    data: [
      {
        type: "heatmap",
        name: "coverage",
        x: roles,
        y: eqs,
        z,
        colorscale: "YlGnBu",
        colorbar: { title: "coverage %" },
        hoverongaps: false,
      } as PlotlyTrace,
    ],
    layout: {
      title: opts?.title ?? "Sensor health — coverage %",
      xaxis: { title: "role", tickangle: -30 },
      yaxis: { title: "equipment", autorange: "reversed" },
      height: Math.max(360, 18 * Math.min(eqs.length, 40)),
      paper_bgcolor: "white",
      plot_bgcolor: "white",
      uirevision: `sensor-health:${fingerprintJson(eqs.slice(0, 20))}`,
    },
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/sensor-health",
    },
  };
}

const FAULT_LANE_COLORS: Record<string, { line: string; fill: string }> = {
  "SV-FLATLINE": { line: "#2563eb", fill: "rgba(59,130,246,0.25)" },
  "SV-SPIKE": { line: "#ca8a04", fill: "rgba(234,179,8,0.25)" },
  "SV-RANGE": { line: "#dc2626", fill: "rgba(220,38,38,0.25)" },
  "SV-STALE": { line: "#a855f7", fill: "rgba(168,85,247,0.25)" },
  "SV-RATE": { line: "#059669", fill: "rgba(16,185,129,0.25)" },
};

function finiteNums(ys: Array<number | null>): number[] {
  return ys.filter((v): v is number => v != null && Number.isFinite(v));
}

/** Derive vibe19-style sensor fault masks from a raw numeric series. */
export function deriveSensorFaultMasks(
  values: Array<number | null>,
  opts?: { flatlineWindow?: number; spikeZ?: number; rangeZ?: number },
): Record<string, Array<0 | 1>> {
  const win = opts?.flatlineWindow ?? 12;
  const spikeZ = opts?.spikeZ ?? 4;
  const rangeZ = opts?.rangeZ ?? 3;
  const finite = finiteNums(values);
  const mean =
    finite.length > 0
      ? finite.reduce((a, b) => a + b, 0) / finite.length
      : 0;
  const variance =
    finite.length > 1
      ? finite.reduce((a, v) => a + (v - mean) ** 2, 0) / finite.length
      : 0;
  const std = Math.sqrt(variance);
  const flatline: Array<0 | 1> = values.map(() => 0);
  const spike: Array<0 | 1> = values.map(() => 0);
  const range: Array<0 | 1> = values.map(() => 0);

  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null || !Number.isFinite(v)) continue;
    if (std > 0 && Math.abs(v - mean) > rangeZ * std) range[i] = 1;
    if (std > 0 && Math.abs(v - mean) > spikeZ * std) spike[i] = 1;
    if (i + 1 >= win) {
      const slice = values.slice(i + 1 - win, i + 1);
      const nums = finiteNums(slice);
      if (nums.length >= Math.max(5, Math.floor(win * 0.6))) {
        const m = nums.reduce((a, b) => a + b, 0) / nums.length;
        const s = Math.sqrt(
          nums.reduce((a, x) => a + (x - m) ** 2, 0) / nums.length,
        );
        if (s <= 1e-9) {
          for (let j = i + 1 - win; j <= i; j++) flatline[j] = 1;
        }
      }
    }
  }
  return {
    "SV-FLATLINE": flatline,
    "SV-SPIKE": spike,
    "SV-RANGE": range,
  };
}

/**
 * vibe19 `sensor_fault_chart` — sensor timeseries + optional fault swim lanes.
 */
export function sensorFaultChart(
  points: Array<Record<string, unknown>>,
  opts: {
    sensorName: string;
    valueKey?: string;
    ruleMasks?: Record<string, Array<boolean | number | null>>;
    yTitle?: string;
  },
): PlotlyFigure | null {
  if (!points.length) return null;
  const key = opts.valueKey ?? "value_f";
  const x = points.map((p) => String(p.timestamp_utc ?? p.timestamp ?? ""));
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

  const data: PlotlyTrace[] = [
    {
      type: "scatter",
      mode: "lines",
      name: opts.sensorName,
      x,
      y,
      line: { width: 1.4, color: rainbowColor(0) },
      yaxis: "y",
    },
  ];

  let laneCount = 0;
  for (const [rid, mask] of Object.entries(masks)) {
    if (!mask || mask.length !== y.length) continue;
    const flags = mask.map((v) => (v === true || v === 1 ? 1 : 0));
    if (!flags.some((f) => f === 1)) continue;
    const colors = FAULT_LANE_COLORS[rid] ?? {
      line: "#ef4444",
      fill: "rgba(239,68,68,0.3)",
    };
    data.push({
      type: "scatter",
      mode: "lines",
      name: `${rid} fault`,
      x,
      y: flags,
      yaxis: "y2",
      line: { width: 0.8, color: colors.line, shape: "hv" },
      fill: "tozeroy",
      fillcolor: colors.fill,
    });
    laneCount += 1;
  }

  return {
    data,
    layout: {
      title: `Sensor health — ${opts.sensorName}`,
      xaxis: {
        title: "timestamp_utc",
        autorange: true,
        anchor: laneCount ? "y2" : "y",
      },
      yaxis: {
        title: opts.yTitle ?? opts.sensorName,
        autorange: true,
        domain: laneCount ? [0.28, 1] : [0, 1],
        anchor: "x",
      },
      ...(laneCount
        ? {
            yaxis2: {
              title: "fault",
              domain: [0, 0.22],
              range: [-0.05, 1.05],
              showgrid: false,
              tickvals: [0, 1],
              ticktext: ["ok", "fault"],
              side: "left",
              anchor: "x",
              // Do not overlay the sensor series — bottom swim lane only.
              overlaying: undefined,
            },
          }
        : {}),
      legend: { orientation: "h" },
      height: 420,
      paper_bgcolor: "white",
      plot_bgcolor: "white",
      uirevision: `sensor-fault:${opts.sensorName}`,
    },
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/inspect + sensor_fault_chart",
    },
  };
}
