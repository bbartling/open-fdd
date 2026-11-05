// RCx presets for the Open-FDD NF app: the 18 generic "RCx Plots" presets of the archived
// central UI (archive/central-v4 .../rcx-presets.js + rcx-vibe-charts.js), rebuilt on NF data.
// Central computed these server side (POST /api/analytics/rcx/preset); here every preset reads
// its history from NF (rcxContext -> fetchSeries, resampled by NF) and does the math in JS.
//
// Classic script, no imports. Needs nf.js, model.js, theme.js (ofddRender), charts.js
// (pickWindow), fdd.js, rcx.js (rcxView, rcxStats). Options are theme-free: series colors
// come from the registered ECharts theme; only the outlier flag is a fixed red.
// Pure math is exposed on globalThis.rcxPresetMath (tests).
//
// Conventions (same as the old central defaults):
//   comfort band      70-75 F (21.11-23.89 C) unless the zone has a setpoint: then
//                     sp +/- 2.5 F, or heating_sp..cooling_sp when both exist.
//   degree days       daily mean outdoor-air temperature, base 65 F: CDD = max(0, mean-65),
//                     HDD = max(0, 65-mean), summed per calendar month (UTC days; NF's daily
//                     resample buckets). Outdoor air = NF weather points (web_oa_t) first,
//                     else the equip's own oa_t.
(function () {
  "use strict";

  const DEGREE_DAY_BASE_F = 65;
  const COMFORT_LO_F = 70, COMFORT_HI_F = 75;      // old defaults: 21.111 / 23.889 C
  const OUTLIER_RED = "#dc2626";

  const finite = (v) => v != null && Number.isFinite(v);
  const num = (v) => { if (v == null || v === "") return null; const n = typeof v === "number" ? v : Number(v); return Number.isFinite(n) ? n : null; };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const round = (v, d = 1) => (finite(v) ? Math.round(v * 10 ** d) / 10 ** d : null);
  const tsOf = (v) => (typeof v === "number" ? v : Date.parse(String(v ?? "")));

  // ---- pure math ----------------------------------------------------------------------
  const isCelsius = (unit) => /(°|deg)?\s*C\b/i.test(String(unit || "")) && !/F/i.test(String(unit || ""));
  /** Temperature in F from a value in `unit` (°F or °C; anything else passes through). */
  const toF = (v, unit) => (v == null ? null : isCelsius(unit) ? v * 1.8 + 32 : v);

  /** Comfort band [lo, hi] for a zone whose temperature is in `unit` (defaults 70-75 F). */
  function defaultBand(unit) {
    return isCelsius(unit) ? [(COMFORT_LO_F - 32) / 1.8, (COMFORT_HI_F - 32) / 1.8] : [COMFORT_LO_F, COMFORT_HI_F];
  }
  /** Half-width of the band around a single zone setpoint, in `unit` (2.5 F). */
  const spHalfWidth = (unit) => (isCelsius(unit) ? 2.5 / 1.8 : 2.5);

  /**
   * Time in band. temps = number[]; lo/hi = number or number[] (per sample, null = unknown).
   * -> { n, inBand, below, above, pct } (pct = % of valid samples inside [lo, hi], null if none).
   */
  function comfortStats(temps, lo, hi) {
    let n = 0, inBand = 0, below = 0, above = 0;
    temps.forEach((t, i) => {
      const l = Array.isArray(lo) ? lo[i] : lo, h = Array.isArray(hi) ? hi[i] : hi;
      if (!finite(t) || !finite(l) || !finite(h)) return;
      n++;
      if (t < l) below++; else if (t > h) above++; else inBand++;
    });
    return { n, inBand, below, above, pct: n ? (inBand / n) * 100 : null };
  }

  /** Rows with a numeric `value`, worst (lowest) first, ties by label. */
  const rankComfort = (rows) => rows.filter((r) => finite(r.value))
    .sort((a, b) => a.value - b.value || String(a.label ?? a.equipment_id).localeCompare(String(b.label ?? b.equipment_id)));

  /** Reset-schedule line: least squares of y on x -> { slope, intercept, r2, n, x0, x1 } or null. */
  function resetFit(pairs) {
    const p = pairs.filter(([x, y]) => finite(x) && finite(y));
    const f = rcxStats.fit(p);
    if (!f) return null;
    const xs = p.map(([x]) => x);
    return { slope: f.slope, intercept: f.intercept, r2: f.r2, n: p.length, x0: Math.min(...xs), x1: Math.max(...xs) };
  }

  /** [[x, y]] from two [[ms, v]] series that share a time grid of `stepMs` (bucket = floor(t/step)). */
  function pairSeries(xs, ys, stepMs) {
    const key = (t) => Math.floor(t / stepMs);
    const xm = new Map(xs.map(([t, v]) => [key(t), v]));
    const out = [];
    for (const [t, y] of ys) { const x = xm.get(key(t)); if (finite(x) && finite(y)) out.push([x, y]); }
    return out;
  }

  /** Map(bucket ms -> value) for a [[ms, v]] series. */
  const bucketMap = (arr, stepMs) => new Map(arr.map(([t, v]) => [Math.floor(t / stepMs) * stepMs, v]));

  const dayKey = (t) => new Date(t).toISOString().slice(0, 10);
  const monthKey = (day) => day.slice(0, 7);

  /** Map(UTC day -> mean) from [[ms, v]] (values in °F after `unit` conversion when unit given). */
  function dailyMeans(arr, unit) {
    const acc = new Map();
    for (const [t, v] of arr) {
      const x = unit === undefined ? v : toF(v, unit);
      if (!finite(x)) continue;
      const k = dayKey(t), a = acc.get(k) || [0, 0];
      a[0] += x; a[1]++; acc.set(k, a);
    }
    return new Map([...acc].map(([k, [s, n]]) => [k, s / n]));
  }

  /** Degree days of one day's mean temperature (°F): kind "cdd" or "hdd". */
  const degreeDay = (meanF, kind, base = DEGREE_DAY_BASE_F) =>
    (!finite(meanF) ? null : kind === "hdd" ? Math.max(0, base - meanF) : Math.max(0, meanF - base));

  /** Map(month -> { dd, days }) from Map(day -> mean °F). */
  function monthlyDegreeDays(dayMeans, kind, base = DEGREE_DAY_BASE_F) {
    const out = new Map();
    for (const [day, m] of dayMeans) {
      const d = degreeDay(m, kind, base);
      if (d == null) continue;
      const k = monthKey(day), a = out.get(k) || { dd: 0, days: 0 };
      a.dd += d; a.days++; out.set(k, a);
    }
    return out;
  }

  /** True when a register-style series (≥90 % of steps non-decreasing) is a cumulative meter. */
  function isCumulative(arr) {
    if (arr.length < 3) return false;
    let up = 0;
    for (let i = 1; i < arr.length; i++) if (arr[i][1] >= arr[i - 1][1]) up++;
    return up / (arr.length - 1) >= 0.9;
  }

  /**
   * Map(day -> energy) from daily buckets.  mode: "rate" (daily mean rate x 24 h, e.g. kW -> kWh),
   * "interval" (daily SUM of interval energy) or "cumulative" (daily LAST of a register; day-to-day
   * difference, gaps and roll-overs skipped).
   */
  function dailyEnergy(arr, mode) {
    const out = new Map();
    if (mode === "rate") {
      for (const [day, m] of dailyMeans(arr)) out.set(day, m * 24);
    } else if (mode === "interval") {
      for (const [t, v] of arr) if (finite(v)) out.set(dayKey(t), (out.get(dayKey(t)) || 0) + v);
    } else {
      for (let i = 1; i < arr.length; i++) {
        const gap = arr[i][0] - arr[i - 1][0], d = arr[i][1] - arr[i - 1][1];
        if (gap > 0 && gap <= 1.5 * 86400e3 && d >= 0) out.set(dayKey(arr[i][0]), d);
      }
    }
    return out;
  }

  /** Map(month -> { sum, days }) from Map(day -> value). */
  function monthlySum(dayMap) {
    const out = new Map();
    for (const [day, v] of dayMap) {
      const k = monthKey(day), a = out.get(k) || { sum: 0, days: 0 };
      a.sum += v; a.days++; out.set(k, a);
    }
    return out;
  }

  /** Rows for meteringChartsOption: months present in both maps. */
  function meterRows(energyByMonth, ddByMonth) {
    return [...energyByMonth.keys()].filter((m) => ddByMonth.has(m)).sort()
      .map((m) => ({ month: m, energy: energyByMonth.get(m).sum, dd: ddByMonth.get(m).dd, days: energyByMonth.get(m).days }));
  }

  const VAV_FULL_OPEN = 0.975, VAV_ROGUE_PCT = 95, VAV_ROGUE_MIN_H = 20, VAV_FLOW_TOL = 0.2, VAV_BROKEN_PCT = 25;

  /**
   * VAV health from bucketed samples (arrays aligned per bucket, null = missing).
   * Old central matrix: poor comfort = any time outside the band; rogue damper = >= 95 % of
   * >= 20 h at >= 97.5 % open. Broken box (central left it unknown; here from NF flow + flow sp) =
   * airflow more than 20 % off its setpoint for >= 25 % of evaluable time.
   * -> { spanH, comfortPct, openPct, flowErrPct, anyPct, poor, rogue, broken } (null = not evaluable)
   */
  function vavHealthStats({ temp = [], lo, hi, damper = [], flow = [], flowSp = [] }, stepSec) {
    const c = comfortStats(temp, lo, hi);
    const dm = damper.filter(finite);
    const open = dm.filter((v) => rcxStats.frac(v) >= VAV_FULL_OPEN).length;
    let fe = 0, fn = 0, any = 0, tot = 0;
    const len = Math.max(temp.length, damper.length, flow.length);
    for (let i = 0; i < len; i++) {
      const sp = flowSp[i], f = flow[i];
      let bad = false, seen = false;
      if (finite(f) && finite(sp) && sp > 0) { fn++; seen = true; if (Math.abs(f - sp) > VAV_FLOW_TOL * sp) { fe++; bad = true; } }
      const l = Array.isArray(lo) ? lo[i] : lo, h = Array.isArray(hi) ? hi[i] : hi;
      if (finite(temp[i]) && finite(l) && finite(h)) { seen = true; if (temp[i] < l || temp[i] > h) bad = true; }
      if (finite(damper[i])) { seen = true; if (rcxStats.frac(damper[i]) >= VAV_FULL_OPEN) bad = true; }
      if (seen) { tot++; if (bad) any++; }
    }
    const spanH = (Math.max(c.n, dm.length, fn) * stepSec) / 3600;
    const openPct = dm.length ? (open / dm.length) * 100 : null;
    const flowErrPct = fn ? (fe / fn) * 100 : null;
    return {
      spanH, comfortPct: c.n ? ((c.below + c.above) / c.n) * 100 : null, openPct, flowErrPct,
      anyPct: tot ? (any / tot) * 100 : null,
      poor: c.n ? c.below + c.above > 0 : null,
      rogue: openPct == null || spanH < VAV_ROGUE_MIN_H ? null : openPct >= VAV_ROGUE_PCT,
      broken: flowErrPct == null ? null : flowErrPct >= VAV_BROKEN_PCT,
    };
  }

  /** Worst single finding for the donut: broken > rogue > poor > healthy (unknowns count as healthy). */
  const vavVerdict = (h) => (h.broken ? "Broken box" : h.rogue ? "Rogue damper" : h.poor ? "Poor comfort" : "Healthy");

  /** z-score outliers of per-equipment mean (>= 3 equips, |z| >= zCut). */
  function outlierEquipmentIds(points, zCut = 2.5) {
    const means = new Map();
    for (const p of points) {
      if (String(p.series ?? "primary") !== "primary") continue;
      const eq = String(p.equipment_id ?? ""), v = num(p.value);
      if (!eq || v == null) continue;
      const cur = means.get(eq) || { sum: 0, n: 0 };
      cur.sum += v; cur.n++; means.set(eq, cur);
    }
    const vals = [...means].map(([eq, { sum, n }]) => ({ eq, mean: sum / n }));
    if (vals.length < 3) return new Set();
    const mu = vals.reduce((a, v) => a + v.mean, 0) / vals.length;
    const sd = Math.sqrt(vals.reduce((a, v) => a + (v.mean - mu) ** 2, 0) / vals.length);
    if (!(sd > 0)) return new Set();
    return new Set(vals.filter((v) => Math.abs(v.mean - mu) / sd >= zCut).map((v) => v.eq));
  }

  // ---- renderers (ported from rcx-vibe-charts.js; theme-free) ---------------------------
  // Input rows keep the archived shape, with `value` (ms timestamps, no value_f/timestamp_utc).
  const pointTip = (fmtFn) => ({ trigger: "item", formatter: fmtFn });

  function multiEquipmentTimeseriesOption(points, opts = {}) {
    if (!points.length) return null;
    const outliers = outlierEquipmentIds(points);
    const byKey = new Map();
    for (const p of points) {
      const eq = String(p.equipment_id ?? "eq"), series = String(p.series ?? "primary");
      const name = series === "primary" ? eq : series === "overlay" ? `${eq} · setpoint` : `${eq} · ${series}`;
      if (!byKey.has(name)) byKey.set(name, []);
      byKey.get(name).push(p);
    }
    const series = [];
    for (const [name, rows] of [...byKey].sort((a, b) => a[0].localeCompare(b[0]))) {
      const isOut = outliers.has(name.split(" · ")[0]);
      const dashed = isOut || name.includes(" · ");
      series.push({
        name: isOut ? `${name} ★` : name, type: "line", showSymbol: false, connectNulls: false,
        lineStyle: { width: isOut ? 2.4 : 1.4, type: dashed ? "dashed" : "solid", ...(isOut ? { color: OUTLIER_RED } : {}) },
        ...(isOut ? { itemStyle: { color: OUTLIER_RED } } : {}),
        data: rows.map((r) => [tsOf(r.ts), num(r.value)]),
      });
    }
    return {
      backgroundColor: "transparent", title: { text: opts.title ?? "Timeseries" },
      tooltip: { trigger: "axis" }, legend: { type: "scroll", top: 28 },
      grid: { left: 56, right: 24, top: 72, bottom: 56 },
      xAxis: { type: "time" }, yAxis: { type: "value", name: opts.yTitle ?? "", scale: true }, series,
    };
  }

  function oatScatterOption(points, opts = {}) {
    const data = points.map((p) => ({ eq: String(p.equipment_id ?? ""), d: [num(p.oat), num(p.value)] }))
      .filter((r) => r.d[0] != null && r.d[1] != null);
    if (!data.length) return null;
    const eqs = [...new Set(data.map((r) => r.eq))].sort();
    const series = eqs.map((eq) => ({
      name: eq || "points", type: "scatter", symbolSize: 7, itemStyle: { opacity: 0.7 },
      data: data.filter((r) => r.eq === eq).map((r) => r.d),
    }));
    const f = opts.fit;
    if (f) {
      series.push({
        name: `fit: y = ${round(f.slope, 3)}·x ${f.intercept < 0 ? "−" : "+"} ${Math.abs(round(f.intercept, 2))}  (R² ${round(f.r2, 2)}, n=${f.n})`,
        type: "line", showSymbol: false, silent: true, lineStyle: { width: 2, type: "dashed" },
        data: [[f.x0, f.slope * f.x0 + f.intercept], [f.x1, f.slope * f.x1 + f.intercept]],
      });
    }
    return {
      backgroundColor: "transparent", title: { text: opts.title ?? "OAT scatter" },
      tooltip: pointTip((p) => (Array.isArray(p.value) ? `${esc(p.seriesName)}<br>${esc(opts.xTitle ?? "OAT")} ${round(p.value[0], 1)} · ${esc(opts.yTitle ?? "value")} ${round(p.value[1], 2)}` : esc(p.seriesName))),
      legend: { type: "scroll", top: 28 },
      grid: { left: 56, right: 24, top: 72, bottom: 48 },
      xAxis: { type: "value", name: opts.xTitle ?? "OAT", scale: true },
      yAxis: { type: "value", name: opts.yTitle ?? "value", scale: true }, series,
    };
  }

  function boxStats(arr) {
    return rcxStats.box(arr);
  }

  function multiEquipmentBoxOption(points, opts = {}) {
    const byEq = new Map();
    for (const p of points) {
      const v = num(p.value);
      if (v == null) continue;
      const eq = String(p.equipment_id ?? "eq");
      if (!byEq.has(eq)) byEq.set(eq, []);
      byEq.get(eq).push(v);
    }
    if (!byEq.size) return null;
    const cats = [...byEq.keys()].sort();
    return {
      backgroundColor: "transparent", title: { text: opts.title ?? "Box plot" },
      tooltip: pointTip((p) => `${esc(p.name)}<br>min ${round(p.value[1], 2)} · q1 ${round(p.value[2], 2)} · median ${round(p.value[3], 2)} · q3 ${round(p.value[4], 2)} · max ${round(p.value[5], 2)}`),
      grid: { left: 56, right: 24, top: 56, bottom: 48 },
      xAxis: { type: "category", data: cats }, yAxis: { type: "value", name: opts.yTitle ?? "", scale: true },
      series: [{ type: "boxplot", data: cats.map((eq) => boxStats(byEq.get(eq))) }],
    };
  }

  function rankingBarsOption(points, opts = {}) {
    const rows = points.filter((p) => num(p.value) != null)
      .sort((a, b) => (opts.worstFirst ? num(a.value) - num(b.value) : num(b.value) - num(a.value)));
    if (!rows.length) return null;
    return {
      backgroundColor: "transparent", title: { text: opts.title ?? "Ranking" },
      tooltip: pointTip((p) => `${esc(p.name)}: ${round(p.value, 1)}${esc(opts.suffix ?? "")}`),
      grid: { left: 120, right: 32, top: 56, bottom: 32 }, dataZoom: false,
      xAxis: { type: "value", name: opts.xTitle ?? "" },
      yAxis: { type: "category", data: rows.map((p) => String(p.label ?? p.equipment_id ?? "")), inverse: true },
      series: [{ type: "bar", data: rows.map((p) => num(p.value)) }],
    };
  }

  function comfortDonutOption(points, opts = {}) {
    const total = points.reduce((a, p) => a + (num(p.value) ?? 0), 0);
    if (!total) return null;
    return {
      backgroundColor: "transparent", title: { text: opts.title ?? "Comfort" },
      tooltip: pointTip((p) => `${esc(p.name)}: ${round(p.value, 0)} (${round(p.percent, 1)}%)`),
      legend: { bottom: 0 }, dataZoom: false,
      series: [{
        type: "pie", radius: ["45%", "70%"], label: { formatter: "{b}: {d}%" },
        data: points.map((p, i) => ({ name: String(p.label ?? p.equipment_id ?? `slice ${i}`), value: num(p.value) ?? 0 })),
      }],
    };
  }

  const vavHealthWorstBarsOption = (points, opts = {}) => rankingBarsOption(points, { ...opts, title: opts.title ?? "Worst zones" });
  const vavHealthDonutOption = (points, opts = {}) => comfortDonutOption(points, { ...opts, title: opts.title ?? "VAV health" });

  function meteringChartsOption(points, opts = {}) {
    if (!points.length) return null;
    const months = [...new Set(points.map((p) => String(p.month)))].sort();
    const energy = months.map((m) => num(points.find((p) => String(p.month) === m)?.energy));
    return {
      backgroundColor: "transparent", title: { text: opts.title ?? "Metering" }, dataZoom: false,
      tooltip: pointTip((p) => (Array.isArray(p.value) ? `${esc(opts.ddLabel ?? "degree-days")} ${round(p.value[0], 0)} · ${esc(opts.energyYTitle ?? "energy")} ${round(p.value[1], 0)}` : `${esc(p.name)}: ${round(p.value, 0)}`)),
      grid: [{ left: "8%", width: "38%", top: 56, bottom: 48 }, { left: "58%", width: "36%", top: 56, bottom: 48 }],
      xAxis: [{ type: "category", data: months, gridIndex: 0 }, { type: "value", gridIndex: 1, name: opts.ddLabel ?? "degree-days", scale: true }],
      yAxis: [{ type: "value", gridIndex: 0, name: opts.energyYTitle ?? "energy" }, { type: "value", gridIndex: 1, name: opts.energyYTitle ?? "energy", scale: true }],
      series: [
        { name: opts.energyYTitle ?? "energy", type: "bar", xAxisIndex: 0, yAxisIndex: 0, data: energy },
        { name: "month", type: "scatter", xAxisIndex: 1, yAxisIndex: 1, symbolSize: 9, data: points.map((p) => [num(p.dd), num(p.energy)]) },
        ...(opts.fit ? [{
          name: "fit", type: "line", xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, silent: true, lineStyle: { type: "dashed", width: 2 },
          data: [[opts.fit.x0, opts.fit.slope * opts.fit.x0 + opts.fit.intercept], [opts.fit.x1, opts.fit.slope * opts.fit.x1 + opts.fit.intercept]],
        }] : []),
      ],
    };
  }

  // ---- view plumbing --------------------------------------------------------------------
  const AIR = ["ahu"], ZONES = ["vav", "zone_other"], CHW = ["chiller", "chwPlant"];
  const MAX_LANES = 6;
  const labelOf = (eq) => eq.name || eq.id;

  /** Draw an option into `el` (themed chart); returns false when there is nothing to draw. */
  function draw(el, ctx, option, name) {
    if (!option) return false;
    if (el.style && !el.clientHeight) el.style.height = "380px";
    ofddRender(ctx.chart(el), option, name);
    return true;
  }

  /** Split el into n stacked chart frames (class rcx-split); returns the child elements. */
  function frames(el, n, heights = []) {
    const doc = el.ownerDocument;
    if (el.replaceChildren) el.replaceChildren(); else el.textContent = "";
    return Array.from({ length: n }, (_, i) => {
      const d = doc.createElement("div");
      d.className = "rcx-split";
      d.style.height = `${heights[i] || 340}px`;
      el.appendChild(d);
      return d;
    });
  }

  async function load(ctx, points, o = {}) {
    const hours = o.hours || ctx.hours;
    const windowSec = o.windowSec || pickWindow(hours);
    const data = await ctx.series(points, { hours, windowSec, method: o.method });
    return { data, step: windowSec * 1e3, windowSec };
  }

  const firstOf = (ctx, eq, roles) => { for (const r of roles) { const p = ctx.first(eq, r); if (p) return p; } return null; };
  const unitsOf = (ctx, pts) => [...new Set(pts.filter(Boolean).map((p) => ctx.unit(p)).filter(Boolean))].join(", ");
  const noData = (what) => `No ${what} history in this window.`;

  // One timeseries preset: role (+ optional overlay / return) per equip, all equips on one chart.
  function timeseriesPreset({ id, group, title, kinds, role, overlay, ret, extra = [], rules = [] }) {
    rcxView({
      id, group, title, kinds, scope: "site", minEquips: 1, hours: 168,
      roles: { required: [role], optional: [overlay, ret, ...extra].filter(Boolean) },
      render: async (el, ctx) => {
        const want = ctx.equips.map((eq) => ({
          eq, y: ctx.first(eq, role), sp: overlay ? ctx.first(eq, overlay) : null, rt: ret ? ctx.first(eq, ret) : null,
        }));
        const { data } = await load(ctx, want.flatMap((w) => [w.y, w.sp, w.rt]).filter(Boolean));
        const rows = [];
        for (const w of want) {
          const name = labelOf(w.eq), base = { equipment_id: name };
          for (const [t, v] of data.get(w.y.uuid) || []) rows.push({ ...base, series: "primary", ts: t, value: v });
          if (w.sp) for (const [t, v] of data.get(w.sp.uuid) || []) rows.push({ ...base, series: "overlay", ts: t, value: v });
          if (w.rt) {
            const rt = data.get(w.rt.uuid) || [];
            for (const [t, v] of rt) rows.push({ ...base, series: "return", ts: t, value: v });
            const supply = new Map((data.get(w.y.uuid) || []).map(([t, v]) => [t, v]));
            for (const [t, v] of rt) if (supply.has(t)) rows.push({ ...base, series: "delta T", ts: t, value: v - supply.get(t) });
          }
        }
        const unit = unitsOf(ctx, want.map((w) => w.y));
        let option = multiEquipmentTimeseriesOption(rows, { title, yTitle: unit });
        if (option && rules.length) {
          // bottom 0/1 lanes of the related FDD rules, one per equip/rule that has results (max 6)
          const lanes = [];
          for (const w of want) for (const rule of rules) {
            if (lanes.length >= MAX_LANES) break;
            const data = await rcxFaultData(ctx.model, w.eq.id, rule, ctx.hours);
            if (data.length) lanes.push({ name: want.length > 1 ? `${labelOf(w.eq)} ${rule}` : rule, data });
          }
          option = rcxWithFaultLane(option, lanes);
        }
        const ok = draw(el, ctx, option, `rcx_${id}`);
        return ok ? `${want.length} equip(s)${unit ? ` · ${unit}` : ""}` : noData(role);
      },
    });
  }

  // Scatter of a supply/setpoint role vs outdoor-air temperature with a least-squares line.
  function resetPreset({ id, group, title, kinds, role, xRoles, xLabel }) {
    rcxView({
      id, group, title, kinds, scope: "site", minEquips: 1, hours: 720,
      roles: { required: [role], optional: xRoles },
      render: async (el, ctx) => {
        const want = ctx.equips.map((eq) => ({ eq, y: ctx.first(eq, role), x: firstOf(ctx, eq, xRoles) }));
        const usable = want.filter((w) => w.x);
        if (!usable.length) return `No outdoor-air temperature (${xRoles.join(" / ")}) is bound to these equips.`;
        const { data, step } = await load(ctx, usable.flatMap((w) => [w.y, w.x]));
        const pts = [];
        for (const w of usable) {
          const xs = (data.get(w.x.uuid) || []).map(([t, v]) => [t, toF(v, w.x.units)]);
          for (const [x, y] of pairSeries(xs, data.get(w.y.uuid) || [], step)) pts.push({ equipment_id: labelOf(w.eq), oat: x, value: y });
        }
        const fit = resetFit(pts.map((p) => [p.oat, p.value]));
        const unit = unitsOf(ctx, usable.map((w) => w.y));
        const ok = draw(el, ctx, oatScatterOption(pts, { title, xTitle: `${xLabel} (°F)`, yTitle: `${role}${unit ? ` (${unit})` : ""}`, fit }), `rcx_${id}`);
        return ok ? `${pts.length} samples · ${fit ? `slope ${round(fit.slope, 2)} / °F, R² ${round(fit.r2, 2)}` : "no fit"}` : noData(role);
      },
    });
  }

  // ---- the 18 presets -------------------------------------------------------------------
  /** Per-sample comfort band for zone_t series `arr`: heating..cooling sp, else sp +/- 2.5 F, else 70-75 F. */
  function bandsFor(arr, data, step, w) {
    const [dl, dh] = defaultBand(w.t.units), half = spHalfWidth(w.t.units);
    const sp = w.sp ? bucketMap(data.get(w.sp.uuid) || [], step) : null;
    const cl = w.c && w.h ? bucketMap(data.get(w.c.uuid) || [], step) : null;
    const ht = w.c && w.h ? bucketMap(data.get(w.h.uuid) || [], step) : null;
    const lo = [], hi = [];
    for (const [t] of arr) {
      const k = Math.floor(t / step) * step;
      if (cl && cl.has(k) && ht.has(k)) { lo.push(ht.get(k)); hi.push(cl.get(k)); }
      else if (sp && sp.has(k)) { lo.push(sp.get(k) - half); hi.push(sp.get(k) + half); }
      else { lo.push(dl); hi.push(dh); }
    }
    return { lo, hi };
  }

  // Zones
  rcxView({
    id: "zone_comfort_rank", group: "Zones", title: "Zones — comfort ranking (% time in band)",
    kinds: ZONES, scope: "site", minEquips: 1, hours: 168,
    roles: { required: ["zone_t"], optional: ["zone_air_temp_sp", "cooling_sp", "heating_sp"] },
    render: async (el, ctx) => {
      const want = ctx.equips.map((eq) => ({ eq, t: ctx.first(eq, "zone_t"), sp: ctx.first(eq, "zone_air_temp_sp"), c: ctx.first(eq, "cooling_sp"), h: ctx.first(eq, "heating_sp") }));
      const { data, step } = await load(ctx, want.flatMap((w) => [w.t, w.sp, w.c, w.h]).filter(Boolean));
      const rows = [];
      const tot = { inBand: 0, below: 0, above: 0 };
      for (const w of want) {
        const arr = data.get(w.t.uuid) || [];
        const { lo, hi } = bandsFor(arr, data, step, w);
        const s = comfortStats(arr.map(([, v]) => v), lo, hi);
        if (s.pct != null) rows.push({ equipment_id: labelOf(w.eq), label: labelOf(w.eq), value: s.pct });
        tot.inBand += s.inBand; tot.below += s.below; tot.above += s.above;
      }
      const [a, b] = frames(el, 2, [Math.max(260, 40 * rows.length + 100), 300]);
      const okA = draw(a, ctx, rankingBarsOption(rankComfort(rows), { title: "Comfort — % of time in band (worst first)", worstFirst: true, suffix: " %", xTitle: "% in band" }), "rcx_zone_comfort_rank");
      draw(b, ctx, comfortDonutOption([
        { label: "In band", value: tot.inBand }, { label: "Too warm", value: tot.above }, { label: "Too cool", value: tot.below },
      ], { title: "All zones — samples by comfort" }), "rcx_zone_comfort_donut");
      return okA ? `${rows.length} zone(s) · band = setpoint ±2.5 °F, heating..cooling sp, else 70–75 °F` : noData("zone temperature");
    },
  });
  timeseriesPreset({ id: "zone_temps", group: "Zones", title: "Zones — all space temps (timeseries)", kinds: ZONES, role: "zone_t", overlay: "zone_air_temp_sp", rules: ["ZONE-COMFORT-PCT"] });
  rcxView({
    id: "vav_health", group: "VAV", title: "VAV — health (broken / comfort / rogue)",
    kinds: ZONES, scope: "site", minEquips: 1, hours: 168,
    roles: { required: ["zone_t"], optional: ["zone_air_temp_sp", "cooling_sp", "heating_sp", "damper_pct", "damper_cmd", "zone_flow", "zone_airflow_sp"] },
    render: async (el, ctx) => {
      const want = ctx.equips.map((eq) => ({
        eq, t: ctx.first(eq, "zone_t"), sp: ctx.first(eq, "zone_air_temp_sp"), c: ctx.first(eq, "cooling_sp"), h: ctx.first(eq, "heating_sp"),
        dm: firstOf(ctx, eq, ["damper_pct", "damper_cmd"]), f: ctx.first(eq, "zone_flow"), fsp: ctx.first(eq, "zone_airflow_sp"),
      }));
      const { data, step, windowSec } = await load(ctx, want.flatMap((w) => [w.t, w.sp, w.c, w.h, w.dm, w.f, w.fsp]).filter(Boolean));
      const rows = [], tally = new Map();
      for (const w of want) {
        const arr = data.get(w.t.uuid) || [];
        const { lo, hi } = bandsFor(arr, data, step, w);
        const at = (pt) => { const m = pt ? bucketMap(data.get(pt.uuid) || [], step) : null; return arr.map(([t]) => (m ? m.get(Math.floor(t / step) * step) ?? null : null)); };
        const st = vavHealthStats({ temp: arr.map(([, v]) => v), lo, hi, damper: at(w.dm), flow: at(w.f), flowSp: at(w.fsp) }, windowSec);
        const verdict = vavVerdict(st);
        tally.set(verdict, (tally.get(verdict) || 0) + 1);
        if (st.anyPct != null) rows.push({ equipment_id: labelOf(w.eq), label: labelOf(w.eq), value: st.anyPct });
      }
      const [a, b] = frames(el, 2, [Math.max(260, 40 * rows.length + 100), 300]);
      const ok = draw(a, ctx, vavHealthWorstBarsOption(rows, { title: "Worst zones — % of time with a problem", suffix: " %", xTitle: "% of time" }), "rcx_vav_health_worst");
      draw(b, ctx, vavHealthDonutOption(["Healthy", "Poor comfort", "Rogue damper", "Broken box"].map((k) => ({ label: k, value: tally.get(k) || 0 })), { title: "VAV health" }), "rcx_vav_health_donut");
      return ok ? `${want.length} VAV(s) · problem = out of comfort band, damper >= 97.5 % open, or flow > 20 % off setpoint` : noData("VAV");
    },
  });
  timeseriesPreset({ id: "vav_flows", group: "VAV", title: "Zones — zone airflow (timeseries)", kinds: ZONES, role: "zone_flow", overlay: "zone_airflow_sp" });

  // Air handlers
  timeseriesPreset({ id: "ahu_dats", group: "Air handlers", title: "AHU — all DATs / SAT (timeseries)", kinds: AIR, role: "sat", overlay: "sat_sp", rules: ["AHU-SATDEV"] });
  timeseriesPreset({ id: "ahu_mats", group: "Air handlers", title: "AHU — all MATs (timeseries)", kinds: AIR, role: "mat" });
  timeseriesPreset({ id: "ahu_rats", group: "Air handlers", title: "AHU — all RATs (timeseries)", kinds: AIR, role: "rat" });
  timeseriesPreset({ id: "ahu_dampers", group: "Air handlers", title: "AHU — OA dampers (timeseries)", kinds: AIR, role: "oa_damper_pct" });
  timeseriesPreset({ id: "fan_speeds", group: "Air handlers", title: "AHU — fan speeds / cmds (timeseries)", kinds: AIR, role: "fan_cmd" });
  timeseriesPreset({ id: "duct_static_ts", group: "Air handlers", title: "AHU — duct static + setpoint (timeseries)", kinds: AIR, role: "duct_static", overlay: "duct_static_sp", rules: ["FC1", "AHU-DUCTHI"] });

  rcxView({
    id: "duct_static_box", group: "Air handlers", title: "AHU — duct static, fan on (box)",
    kinds: AIR, scope: "site", minEquips: 1, hours: 168,
    roles: { required: ["duct_static"], optional: ["fan_status", "fan_cmd"] },
    render: async (el, ctx) => {
      const want = ctx.equips.map((eq) => ({ eq, y: ctx.first(eq, "duct_static"), fan: firstOf(ctx, eq, ["fan_status", "fan_cmd"]) }));
      const { data, step } = await load(ctx, want.flatMap((w) => [w.y, w.fan]).filter(Boolean));
      const rows = [];
      let filtered = 0;
      for (const w of want) {
        const fan = w.fan ? bucketMap(data.get(w.fan.uuid) || [], step) : null;
        if (fan) filtered++;
        for (const [t, v] of data.get(w.y.uuid) || []) {
          // fan proof when present: status/cmd above 50 % (0/1 or 0-100 both work)
          if (fan && !((rcxStats.frac(fan.get(Math.floor(t / step) * step)) ?? 0) > 0.5)) continue;
          rows.push({ equipment_id: labelOf(w.eq), value: v });
        }
      }
      const unit = unitsOf(ctx, want.map((w) => w.y));
      const ok = draw(el, ctx, multiEquipmentBoxOption(rows, { title: "Duct static pressure — fan on", yTitle: unit }), "rcx_duct_static_box");
      return ok ? `${rows.length} samples · fan-on filter on ${filtered}/${want.length} equip(s)` : noData("duct static (fan on)");
    },
  });

  resetPreset({ id: "ahu_sat_reset_scatter", group: "Air handlers", title: "AHU — SAT vs web dry-bulb (scatter)", kinds: AIR, role: "sat", xRoles: ["web_oa_t", "oa_t"], xLabel: "OAT" });

  // Plant
  resetPreset({ id: "hw_reset_scatter", group: "Plant", title: "Boiler — HWS vs web dry-bulb (scatter)", kinds: ["boiler"], role: "hw_supply_t", xRoles: ["web_oa_t", "oa_t"], xLabel: "OAT" });
  resetPreset({ id: "chw_reset_scatter", group: "Plant", title: "Chiller — CHWS vs web dry-bulb (scatter)", kinds: CHW, role: "chw_supply_t", xRoles: ["web_oa_t", "oa_t"], xLabel: "OAT" });
  resetPreset({ id: "cw_reset_scatter", group: "Plant", title: "Tower / CW — leave temp vs wet-bulb (dry-bulb fallback)", kinds: [...CHW, "cooling_tower"], role: "cw_supply_t", xRoles: ["web_wb_t", "web_oa_t", "oa_t"], xLabel: "OA wet-bulb / dry-bulb" });
  timeseriesPreset({ id: "chw_temps_ts", group: "Plant", title: "Chiller — CHW supply / return / ΔT (timeseries)", kinds: CHW, role: "chw_supply_t", ret: "chw_return_t", rules: ["CHW-1"] });
  timeseriesPreset({ id: "cw_temps_ts", group: "Plant", title: "Tower / CW — supply / return / ΔT (timeseries)", kinds: [...CHW, "cooling_tower"], role: "cw_supply_t", ret: "cw_return_t" });

  // Metering: monthly energy vs degree days. The catalog has electric roles only; gas meters
  // are found by their Haystack markers (gas + energy/volume/flow) on the meter equip.
  async function meterRender(el, ctx, kind) {
    const gas = kind === "gas";
    const dd = gas ? "hdd" : "cdd";
    const wx = (eq) => firstOf(ctx, eq, ["web_oa_t", "oa_t"]) || ctx.weather.find((p) => p.tags.includes("temp")) || null;
    const sources = [];
    for (const eq of ctx.equips) {
      if (gas) {
        for (const p of ctx.model.points) {
          if (p.equipRef === eq.id && p.tags.includes("point") && p.tags.includes("gas") && ["energy", "volume", "flow"].some((m) => p.tags.includes(m)) && !p.tags.includes("spare"))
            sources.push({ eq, p, rate: p.tags.includes("flow") });
        }
      } else {
        const reg = firstOf(ctx, eq, ["electric_kwh", "kwh"]);
        const kw = ctx.first(eq, "electric_kw");
        if (reg) sources.push({ eq, p: reg, rate: false }); else if (kw) sources.push({ eq, p: kw, rate: true });
      }
    }
    if (!sources.length) return gas ? "No gas meter point (tags: point + gas + energy/volume/flow) on these equips." : "No kWh or kW point on these equips.";
    const oat = wx(sources[0].eq);
    if (!oat) return "No outdoor-air temperature (web_oa_t / oa_t) for degree days.";
    const windowSec = 86400;                       // daily buckets
    const { data } = await load(ctx, [...sources.map((s) => s.p), oat], { windowSec });
    // a register needs LAST (difference) and an interval-energy point needs SUM: refetch by mode
    const reg = sources.filter((s) => !s.rate);
    const last = reg.length ? (await load(ctx, reg.map((s) => s.p), { windowSec, method: "LAST" })).data : new Map();
    const sum = reg.length ? (await load(ctx, reg.map((s) => s.p), { windowSec, method: "SUM" })).data : new Map();
    const energy = new Map();
    for (const s of sources) {
      let days;
      if (s.rate) days = dailyEnergy(data.get(s.p.uuid) || [], "rate");
      else if (isCumulative(last.get(s.p.uuid) || [])) days = dailyEnergy(last.get(s.p.uuid), "cumulative");
      else days = dailyEnergy(sum.get(s.p.uuid) || [], "interval");
      for (const [d, v] of days) energy.set(d, (energy.get(d) || 0) + v);
    }
    const rows = meterRows(monthlySum(energy), monthlyDegreeDays(dailyMeans(data.get(oat.uuid) || [], oat.units), dd));
    const fit = resetFit(rows.map((r) => [r.dd, r.energy]));
    const unit = gas ? unitsOf(ctx, sources.map((s) => s.p)) : "kWh";
    const ok = draw(el, ctx, meteringChartsOption(rows, {
      title: gas ? "Gas per month vs HDD (base 65 °F)" : "Electric kWh per month vs CDD (base 65 °F)",
      ddLabel: `${dd.toUpperCase()} (°F·day, base ${DEGREE_DAY_BASE_F})`, energyYTitle: `${gas ? "gas" : "electric"}${unit ? ` (${unit}${sources.some((s) => s.rate) && gas ? "/day" : ""})` : ""}`, fit,
    }), gas ? "rcx_meter_gas_hdd" : "rcx_meter_elec_cdd");
    return ok ? `${rows.length} month(s) (partial months included) · ${sources.length} meter point(s) summed${fit ? ` · R² ${round(fit.r2, 2)}` : ""}` : "No month has both energy and outdoor-air history in this window.";
  }

  rcxView({
    id: "meter_elec_cdd", group: "Metering", title: "Metering — electric kWh/month vs CDD",
    kinds: ["meter"], scope: "site", minEquips: 1, hours: 24 * 400,
    roles: { required: [], optional: ["electric_kwh", "kwh", "electric_kw", "web_oa_t", "oa_t"] },
    render: (el, ctx) => meterRender(el, ctx, "electric"),
  });
  rcxView({
    id: "meter_gas_hdd", group: "Metering", title: "Metering — gas/month vs HDD",
    kinds: ["meter"], scope: "site", minEquips: 1, hours: 24 * 400,
    roles: { required: [], optional: ["web_oa_t", "oa_t"] },       // no gas role in fdd-catalog.json
    render: (el, ctx) => meterRender(el, ctx, "gas"),
  });

  globalThis.rcxPresetMath = {
    DEGREE_DAY_BASE_F, toF, defaultBand, spHalfWidth, comfortStats, rankComfort, resetFit, pairSeries, bucketMap,
    vavHealthStats, vavVerdict, dailyMeans, degreeDay, monthlyDegreeDays, isCumulative, dailyEnergy, monthlySum, meterRows, outlierEquipmentIds,
    options: {
      multiEquipmentTimeseriesOption, oatScatterOption, multiEquipmentBoxOption, rankingBarsOption, comfortDonutOption,
      meteringChartsOption, vavHealthWorstBarsOption, vavHealthDonutOption,
    },
  };
})();
