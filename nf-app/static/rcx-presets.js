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
// Units: ctx.series hands over canonical SI (degC, Pa, L/s, kW, kWh, %), so every threshold and
// calculation below is SI. Values are mapped to the user's display system (ctx.disp /
// ctx.dispDelta) only when an option or note is built. A least-squares line commutes with that
// affine map, so scatters are fitted on the display values (same R2, same decision).
//
// Conventions (same physical defaults as the old central UI, expressed in SI):
//   comfort band      21.111-23.889 C (70-75 F) unless the zone has a setpoint: then
//                     sp +/- 1.3889 delta C (2.5 delta F), or heating_sp..cooling_sp when both exist.
//   degree days       daily mean outdoor-air temperature, base 18.333 C (65 F): CDD = max(0, mean-base),
//                     HDD = max(0, base-mean), in C-days, summed per calendar month (UTC days; NF's
//                     daily resample buckets). Shown in F-days (x1.8) in the imperial display system.
//                     Outdoor air = NF weather points (web_oa_t) first, else the equip's own oa_t.
(function () {
  "use strict";

  const TEMP = "°C";                                // SI temperature unit
  const DEGREE_DAY_BASE_C = (65 - 32) * 5 / 9;  // 65 F = 18.333 C
  const COMFORT_LO_C = (70 - 32) * 5 / 9, COMFORT_HI_C = (75 - 32) * 5 / 9;   // 21.111 / 23.889 C
  const COMFORT_SP_HALF_C = 2.5 * 5 / 9;           // setpoint +/- 2.5 delta F = 1.3889 delta C
  const OUTLIER_RED = "#dc2626";

  const finite = (v) => v != null && Number.isFinite(v);
  const num = (v) => { if (v == null || v === "") return null; const n = typeof v === "number" ? v : Number(v); return Number.isFinite(n) ? n : null; };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const round = (v, d = 1) => (finite(v) ? Math.round(v * 10 ** d) / 10 ** d : null);
  const tsOf = (v) => (typeof v === "number" ? v : Date.parse(String(v ?? "")));

  // ---- pure math ----------------------------------------------------------------------
  /** Default comfort band [lo, hi] in degC (70-75 F). */
  const defaultBand = () => [COMFORT_LO_C, COMFORT_HI_C];
  /** Half-width of the band around a single zone setpoint, in delta degC (2.5 delta F). */
  const spHalfWidth = () => COMFORT_SP_HALF_C;

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

  /** Map(UTC day -> mean) from [[ms, v]] (SI values in, SI mean out). */
  function dailyMeans(arr) {
    const acc = new Map();
    for (const [t, x] of arr) {
      if (!finite(x)) continue;
      const k = dayKey(t), a = acc.get(k) || [0, 0];
      a[0] += x; a[1]++; acc.set(k, a);
    }
    return new Map([...acc].map(([k, [s, n]]) => [k, s / n]));
  }

  /** Degree days (C-days) of one day's mean temperature (degC): kind "cdd" or "hdd". */
  const degreeDay = (meanC, kind, base = DEGREE_DAY_BASE_C) =>
    (!finite(meanC) ? null : kind === "hdd" ? Math.max(0, base - meanC) : Math.max(0, meanC - base));

  /** Map(month -> { dd, days }) in C-days from Map(day -> mean degC). */
  function monthlyDegreeDays(dayMeans, kind, base = DEGREE_DAY_BASE_C) {
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

  // ---- fleet analytics: rogue VAVs and the zone-temperature percentile band --------------------
  // Every threshold of these two analyses lives in this one block.
  const ROGUE_OPEN_PCT = 95;         // a damper / reheat valve at or above this position counts as "open"
  const ROGUE_CLOSED_PCT = 5;        // ... at or below this as "closed"
  const ROGUE_SHARE = 0.9;           // "always" = in that state for at least 90 % of the assessed samples
  const ROGUE_MIN_SAMPLES = 12;      // fewer assessed samples than this: no verdict
  const ZONE_P_LO = 0.1, ZONE_P_HI = 0.9;   // zone temperature band: 10th / 90th percentile across the zones, per time step
  const ZONE_BAND_MIN_ZONES = 5;     // percentiles across fewer zones mean nothing: plain lines, nothing highlighted
  const ZONE_ROGUE_TOP = 3;          // highlight at most this many rogue zones above p90, and as many below p10
  const ZONE_ROGUE_MIN_SHARE = 0.25; // a zone is rogue when it sits outside the band on the same side for >= 25 % of its samples
  const ZONE_ROGUE_MIN_EXCESS_C = 0.5; // ... and "outside" means beyond the band edge by at least this many delta degC (~1 delta F): a zone that is only
                                       // always the warmest of a tight fleet is not rogue
  const ROGUE_ABOVE_COLOR = "#dc2626", ROGUE_BELOW_COLOR = "#2563eb", MUTED_COLOR = "#94a3b8", HEALTHY_COLOR = "#16a34a";

  /** Damper / valve position in percent (0-1 fractions and 0-100 values both work, like the SQL pack). */
  const posPct = (v) => (finite(v) ? rcxStats.frac(v) * 100 : null);

  /** { n, open, closed, openShare, closedShare } over the finite samples of a position series. */
  function stuckStats(values) {
    let n = 0, open = 0, closed = 0;
    for (const v of values) {
      const p = posPct(v);
      if (p == null) continue;
      n++;
      if (p >= ROGUE_OPEN_PCT) open++; else if (p <= ROGUE_CLOSED_PCT) closed++;
    }
    return { n, open, closed, openShare: n ? open / n : null, closedShare: n ? closed / n : null };
  }

  /** "Always open" / "always closed" verdict of a position series: { state, share, n } or null (not stuck / too few samples). */
  function stuckVerdict(values) {
    const s = stuckStats(values);
    if (s.n < ROGUE_MIN_SAMPLES) return null;
    if (s.openShare >= ROGUE_SHARE) return { state: "open", share: s.openShare, n: s.n };
    if (s.closedShare >= ROGUE_SHARE) return { state: "closed", share: s.closedShare, n: s.n };
    return null;
  }

  /**
   * Rogue VAV findings, ranked (largest share first). devices = [{ id, label, damper: number[], reheat?: number[] }];
   * a damper and a reheat valve are judged separately -> rows [{ id, label, part: "Damper"|"Reheat valve", state, share, n }].
   */
  function rogueVavRows(devices) {
    const rows = [];
    for (const d of devices) {
      for (const [part, vals] of [["Damper", d.damper], ["Reheat valve", d.reheat]]) {
        if (!vals || !vals.length) continue;
        const v = stuckVerdict(vals);
        if (v) rows.push({ id: d.id, label: d.label, part, state: v.state, share: v.share, n: v.n });
      }
    }
    return rows.sort((a, b) => b.share - a.share || a.label.localeCompare(b.label) || a.part.localeCompare(b.part));
  }

  /** Verdict text of one device for the summary donut: its worst finding ("Damper always open") or "Healthy". */
  const vavVerdictLabel = (rows, id) => { const r = rows.find((x) => x.id === id); return r ? `${r.part} always ${r.state}` : "Healthy"; };

  /**
   * 10th / 90th percentile band across zones, per time step. cols = one number[] per zone on a shared grid (null = no
   * sample). A step with fewer than ZONE_BAND_MIN_ZONES zones reporting has no band (null).
   */
  function zoneBand(cols, pLo = ZONE_P_LO, pHi = ZONE_P_HI) {
    const len = Math.max(0, ...cols.map((c) => c.length));
    const lo = [], hi = [];
    for (let i = 0; i < len; i++) {
      const xs = cols.map((c) => c[i]).filter(finite);
      if (xs.length < ZONE_BAND_MIN_ZONES) { lo.push(null); hi.push(null); continue; }
      lo.push(rcxStats.quantile(xs, pLo)); hi.push(rcxStats.quantile(xs, pHi));
    }
    return { lo, hi };
  }

  /**
   * Rogue zones against the band: the worst above p90 and the worst below p10.
   * zones = [{ id, label, v: number[] }] on the band's grid. -> { above: [{ id, label, share, n }], below: [...], stats }
   * (share = fraction of the zone's assessed samples above p90 / below p10; both lists capped at ZONE_ROGUE_TOP, worst first).
   */
  function pickRogueZones(zones, band) {
    const stats = zones.map((z) => {
      let n = 0, a = 0, b = 0;
      z.v.forEach((x, i) => {
        if (!finite(x) || band.lo[i] == null) return;
        n++;
        if (x > band.hi[i] + ZONE_ROGUE_MIN_EXCESS_C) a++; else if (x < band.lo[i] - ZONE_ROGUE_MIN_EXCESS_C) b++;
      });
      return { id: z.id, label: z.label, n, above: n ? a / n : 0, below: n ? b / n : 0 };
    });
    const top = (key) => stats.filter((s) => s.n >= ROGUE_MIN_SAMPLES && s[key] >= ZONE_ROGUE_MIN_SHARE)
      .sort((x, y) => y[key] - x[key] || x.label.localeCompare(y.label)).slice(0, ZONE_ROGUE_TOP)
      .map((s) => ({ id: s.id, label: s.label, share: s[key], n: s.n }));
    const above = top("above"), aboveIds = new Set(above.map((s) => s.id));
    return { above, below: top("below").filter((s) => !aboveIds.has(s.id)), stats };
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
    /** @type {any[]} */
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
      legend: { bottom: 0, type: "scroll" }, dataZoom: false,
      // radius and centre are percentages of the container (never a fixed size) and the labels are just "{d}%", so the ring and
      // its labels always fit the frame; names are in the legend.
      series: [{
        type: "pie", radius: ["34%", "56%"], center: ["50%", "46%"], label: { formatter: "{d}%" }, labelLine: { length: 8, length2: 6 },
        data: points.map((p, i) => ({ name: String(p.label ?? p.equipment_id ?? `slice ${i}`), value: num(p.value) ?? 0, ...(p.color ? { itemStyle: { color: p.color } } : {}) })),
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
    // The parent grows to hold every frame: a fixed card height used to clip the second chart (the "cut-off pie").
    if (el.style) el.style.height = `${Array.from({ length: n }, (_, i) => heights[i] || 340).reduce((a, b) => a + b, 0)}px`;
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

  /** Zone temperatures with the p10-p90 band; rogue zones in two colours, everything else muted. SI in, display units out. */
  function zoneBandOption({ title, yTitle, t, zones, band, rogue, toDisp }) {
    const above = new Map(rogue.above.map((r) => [r.id, r])), below = new Map(rogue.below.map((r) => [r.id, r]));
    const disp = (vals) => toDisp(t.map((x, i) => [x, vals[i]])).map(([x, v]) => [x, v == null ? null : +v.toFixed(2)]);
    const series = [];
    const loD = disp(band.lo), hiD = disp(band.hi);
    const bandName = `${ZONE_P_LO * 100}th-${ZONE_P_HI * 100}th percentile of all zones`;
    series.push({ name: "band base", type: "line", stack: "band", symbol: "none", silent: true, lineStyle: { opacity: 0 }, data: loD });
    series.push({ name: bandName, type: "line", stack: "band", symbol: "none", silent: true, lineStyle: { opacity: 0 }, areaStyle: { opacity: 0.2 },
      data: loD.map(([x, lo], i) => [x, lo == null || hiD[i][1] == null ? null : +(hiD[i][1] - lo).toFixed(2)]) });
    const legend = [bandName];
    for (const z of [...zones].sort((a, b) => a.label.localeCompare(b.label))) {
      const a = above.get(z.id), b = below.get(z.id);
      const hot = a || b, color = a ? ROGUE_ABOVE_COLOR : b ? ROGUE_BELOW_COLOR : MUTED_COLOR;
      const name = a ? `${z.label} (above p90 ${Math.round(a.share * 100)} %)` : b ? `${z.label} (below p10 ${Math.round(b.share * 100)} %)` : z.label;
      if (hot) legend.push(name);
      series.push({ name, type: "line", showSymbol: false, connectNulls: false, z: hot ? 5 : 1,
        lineStyle: { width: hot ? 2.2 : 1, color, opacity: hot ? 1 : 0.45 }, itemStyle: { color }, data: disp(z.v) });
    }
    return {
      backgroundColor: "transparent", title: { text: title },
      tooltip: { trigger: "axis", valueFormatter: (v) => (finite(v) ? String(+v.toFixed(2)) : "") },
      legend: { type: "scroll", top: 28, data: legend },
      grid: { left: 56, right: 24, top: 72, bottom: 56 },
      xAxis: { type: "time" }, yAxis: { type: "value", name: yTitle || "", scale: true }, series,
    };
  }

  /** Ranked bars of the rogue VAV findings (worst first): one row per damper / reheat valve, coloured by open vs closed. */
  function rogueBarsOption(rows, opts = {}) {
    if (!rows.length) return null;
    return {
      backgroundColor: "transparent", title: { text: opts.title ?? "Rogue VAVs" }, dataZoom: false,
      tooltip: pointTip((p) => `${esc(p.name)}: ${round(p.value, 0)} % of assessed samples`),
      grid: { left: 190, right: 32, top: 56, bottom: 36 },
      xAxis: { type: "value", name: opts.xTitle ?? "% of assessed samples", min: 0, max: 100 },
      yAxis: { type: "category", inverse: true, data: rows.map((r) => `${r.label} · ${r.part} always ${r.state}`) },
      series: [{ type: "bar", data: rows.map((r) => ({ value: +(r.share * 100).toFixed(1), itemStyle: { color: r.state === "open" ? ROGUE_ABOVE_COLOR : ROGUE_BELOW_COLOR } })) }],
    };
  }

  /**
   * "AHU on" filter for one card: keep(eq, samples) drops the samples taken while the feeding AHU's fan is off (when the
   * tab's filter is on and the VAV's AHU and its fan signal are known), and counts what it could and could not filter.
   */
  function ahuFilter(ctx, windowSec) {
    const seen = new Map();                                    // equip id -> { filtered, assumed }
    return {
      async keep(eq, samples) {
        if (!ctx.ahuOn) return samples;
        const m = await ctx.ahuMask(eq, windowSec);
        seen.set(eq.id, m ? { filtered: true, assumed: m.assumed, ahu: m.ahu.name, role: m.role } : { filtered: false, assumed: false });
        return m ? rcxKeepAhuOn(samples, m.on, windowSec * 1e3) : samples;
      },
      /** Sentence for the card note ("" when the filter is off). */
      note() {
        if (!ctx.ahuOn) return "";
        const all = [...seen.values()], done = all.filter((x) => x.filtered), assumed = done.filter((x) => x.assumed).length;
        const roles = [...new Set(done.map((x) => x.role === "fan_status" ? "status" : "command"))].join("/");
        return ` · AHU on only: ${done.length} of ${all.length} filtered by the feeding AHU's fan ${roles || "signal"}`
          + (assumed ? `; AHU assumed for ${assumed} (the site has one AHU and no airRef)` : "")
          + (all.length - done.length ? `; ${all.length - done.length} without a known AHU fan signal left unfiltered` : "");
      },
    };
  }

  // One timeseries preset: role (+ optional overlay / return) per equip, all equips on one chart.
  /** @param {{id: string, group: string, title: string, kinds: any, role: string, overlay?: string, ret?: string, extra?: string[], rules?: string[]}} o */
  function timeseriesPreset({ id, group, title, kinds, role, overlay, ret, extra = [], rules = [] }) {
    rcxView({
      id, group, title, kinds, scope: "site", minEquips: 1, hours: 168,
      roles: { required: [role], optional: [overlay, ret, ...extra].filter(Boolean) },
      render: async (el, ctx) => {
        const want = ctx.equips.map((eq) => ({
          eq, y: ctx.first(eq, role), sp: overlay ? ctx.first(eq, overlay) : null, rt: ret ? ctx.first(eq, ret) : null,
        }));
        const { data } = await load(ctx, want.flatMap((w) => [w.y, w.sp, w.rt]).filter(Boolean));
        // data is SI; the last step maps each series to display units (delta T: a difference, no offset)
        const toDisp = (arr, pt) => ctx.dispSeries(arr, ctx.siUnit(pt));
        const rows = [];
        for (const w of want) {
          const name = labelOf(w.eq), base = { equipment_id: name };
          const ySI = data.get(w.y.uuid) || [];
          for (const [t, v] of toDisp(ySI, w.y)) rows.push({ ...base, series: "primary", ts: t, value: v });
          if (w.sp) for (const [t, v] of toDisp(data.get(w.sp.uuid) || [], w.sp)) rows.push({ ...base, series: "overlay", ts: t, value: v });
          if (w.rt) {
            const rt = data.get(w.rt.uuid) || [];
            for (const [t, v] of toDisp(rt, w.rt)) rows.push({ ...base, series: "return", ts: t, value: v });
            const supply = new Map(ySI.map(([t, v]) => [t, v]));
            const dT = rt.filter(([t]) => supply.has(t)).map(([t, v]) => [t, v - supply.get(t)]);
            for (const [t, v] of ctx.dispSeries(dT, ctx.siUnit(w.y), true)) rows.push({ ...base, series: "delta T", ts: t, value: v });
          }
        }
        const unit = unitsOf(ctx, want.map((w) => w.y));
        let option = multiEquipmentTimeseriesOption(rows, { title, yTitle: unit });
        if (option && rules.length) {
          // bottom 0/1 lanes of the related FDD rules, one per equip/rule that has results (max 6)
          const lanes = [];
          for (const w of want) for (const rule of rules) {
            if (lanes.length >= MAX_LANES) break;
            const data = await rcxFaultData(ctx.model, w.eq, rule, ctx.hours);
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
          // pair on the SI series, then map both axes to display units (the fit commutes with that)
          const xSI = ctx.siUnit(w.x), ySI = ctx.siUnit(w.y);
          for (const [x, y] of pairSeries(data.get(w.x.uuid) || [], data.get(w.y.uuid) || [], step)) {
            pts.push({ equipment_id: labelOf(w.eq), oat: ctx.disp(x, xSI).value, value: ctx.disp(y, ySI).value });
          }
        }
        const fit = resetFit(pts.map((p) => [p.oat, p.value]));
        const unit = unitsOf(ctx, usable.map((w) => w.y)), xUnit = ctx.dispUnit(TEMP);
        const ok = draw(el, ctx, oatScatterOption(pts, { title, xTitle: `${xLabel} (${xUnit})`, yTitle: `${role}${unit ? ` (${unit})` : ""}`, fit }), `rcx_${id}`);
        return ok ? `${pts.length} samples · ${fit ? `slope ${round(fit.slope, 2)} ${unit ? unit + " " : ""}/ ${xUnit}, R² ${round(fit.r2, 2)}` : "no fit"}` : noData(role);
      },
    });
  }

  // ---- the 18 presets -------------------------------------------------------------------
  /** Per-sample comfort band (degC) for zone_t series `arr`: heating..cooling sp, else sp +/- 1.3889 delta C, else 21.111-23.889 C. */
  function bandsFor(arr, data, step, w) {
    const [dl, dh] = defaultBand(), half = spHalfWidth();       // degC; data is SI
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

  // Zones. Fleet analytics (pies, rankings, the all-zones band) draw only in the all-devices view.
  rcxView({
    id: "zone_comfort_rank", group: "Zones", title: "Zones — comfort ranking (% time in band)",
    kinds: ZONES, scope: "site", minEquips: 1, hours: 168, fleet: true, headline: true,
    roles: { required: ["zone_t"], optional: ["zone_air_temp_sp", "cooling_sp", "heating_sp"] },
    render: async (el, ctx) => {
      const want = ctx.equips.map((eq) => ({ eq, t: ctx.first(eq, "zone_t"), sp: ctx.first(eq, "zone_air_temp_sp"), c: ctx.first(eq, "cooling_sp"), h: ctx.first(eq, "heating_sp") }));
      const { data, step, windowSec } = await load(ctx, want.flatMap((w) => [w.t, w.sp, w.c, w.h]).filter(Boolean));
      const filt = ahuFilter(ctx, windowSec);
      const rows = [];
      const tot = { inBand: 0, below: 0, above: 0 };
      for (const w of want) {
        const arr = await filt.keep(w.eq, data.get(w.t.uuid) || []);
        const { lo, hi } = bandsFor(arr, data, step, w);
        const s = comfortStats(arr.map(([, v]) => v), lo, hi);
        if (s.pct != null) rows.push({ equipment_id: labelOf(w.eq), label: labelOf(w.eq), value: s.pct });
        tot.inBand += s.inBand; tot.below += s.below; tot.above += s.above;
      }
      const [a, b] = frames(el, 2, [Math.max(260, 40 * rows.length + 100), 320]);
      const okA = draw(a, ctx, rankingBarsOption(rankComfort(rows), { title: "Comfort — % of time in band (worst first)", worstFirst: true, suffix: " %", xTitle: "% in band" }), "rcx_zone_comfort_rank");
      draw(b, ctx, comfortDonutOption([
        { label: "In band", value: tot.inBand }, { label: "Too warm", value: tot.above }, { label: "Too cool", value: tot.below },
      ], { title: "All zones — samples by comfort" }), "rcx_zone_comfort_donut");
      const n = tot.inBand + tot.below + tot.above;
      if (n) ctx.kpi({ id: "zones-in-band", label: "Zones in comfort band", value: `${round((tot.inBand / n) * 100, 0)} %`, sub: `${rows.length} zones${ctx.ahuOn ? " · while AHU on" : ""}`, order: 10, tone: tot.inBand / n < 0.8 ? "warn" : "ok" });
      return okA ? `${rows.length} zone(s) · band = setpoint ±${round(ctx.dispDelta(COMFORT_SP_HALF_C, TEMP).value, 1)} ${ctx.dispDelta(0, TEMP).unit}, heating..cooling sp, else ${round(ctx.disp(COMFORT_LO_C, TEMP).value, 0)}–${round(ctx.disp(COMFORT_HI_C, TEMP).value, 0)} ${ctx.dispUnit(TEMP)}${filt.note()}` : noData("zone temperature");
    },
  });

  // All zone temperatures on one chart with the 10th / 90th percentile band across zones; the worst zones above p90 and
  // below p10 are drawn in their own colours, every other zone is muted. One zone (single-device view): just its line.
  rcxView({
    id: "zone_temps", group: "Zones", title: "Zones — all space temps (10th–90th percentile band)",
    kinds: ZONES, scope: "site", minEquips: 1, hours: 168, headline: true, wide: true,
    roles: { required: ["zone_t"], optional: [] },
    render: async (el, ctx) => {
      const want = ctx.equips.map((eq) => ({ eq, y: ctx.first(eq, "zone_t") }));
      const { data, step, windowSec } = await load(ctx, want.map((w) => w.y));
      const filt = ahuFilter(ctx, windowSec);
      const zones = [];
      for (const w of want) zones.push({ id: w.eq.id, label: labelOf(w.eq), w, arr: await filt.keep(w.eq, data.get(w.y.uuid) || []) });
      const t = [...new Set(zones.flatMap((z) => z.arr.map(([x]) => Math.floor(x / step) * step)))].sort((a, b) => a - b);
      if (!t.length) return noData("zone temperature");
      const idx = new Map(t.map((x, i) => [x, i]));
      for (const z of zones) { z.v = t.map(() => null); for (const [x, v] of z.arr) z.v[idx.get(Math.floor(x / step) * step)] = v; }
      const unit = unitsOf(ctx, want.map((w) => w.y)), toDisp = (arr) => ctx.dispSeries(arr, ctx.siUnit(want[0].y));
      if (zones.length < ZONE_BAND_MIN_ZONES) {
        const rows = zones.flatMap((z) => toDisp(z.arr).map(([x, v]) => ({ equipment_id: z.label, series: "primary", ts: x, value: v })));
        const ok = draw(el, ctx, multiEquipmentTimeseriesOption(rows, { title: "Zones — space temps", yTitle: unit }), "rcx_zone_temps");
        return ok ? `${zones.length} zone(s) · the percentile band needs at least ${ZONE_BAND_MIN_ZONES} zones${filt.note()}` : noData("zone temperature");
      }
      const band = zoneBand(zones.map((z) => z.v));
      const rogue = pickRogueZones(zones, band);
      const ok = draw(el, ctx, zoneBandOption({ title: "Zones — all space temps, 10th–90th percentile band", yTitle: unit, t, zones, band, rogue, toDisp }), "rcx_zone_temps_band");
      if (ok) ctx.kpi({ id: "rogue-zones", label: "Rogue zones", value: String(rogue.above.length + rogue.below.length), sub: `${rogue.above.length} above p90 · ${rogue.below.length} below p10${ctx.ahuOn ? " · while AHU on" : ""}`, order: 30, tone: rogue.above.length + rogue.below.length ? "warn" : "ok" });
      return ok ? `${zones.length} zones · band = ${ZONE_P_LO * 100}th–${ZONE_P_HI * 100}th percentile across zones per time step · rogue = beyond the band by >= ${round(ctx.dispDelta(ZONE_ROGUE_MIN_EXCESS_C, TEMP).value, 1)} ${ctx.dispDelta(0, TEMP).unit} on the same side for >= ${ZONE_ROGUE_MIN_SHARE * 100} % of samples (worst ${ZONE_ROGUE_TOP} per side): `
        + `${rogue.above.length ? `above: ${rogue.above.map((r) => r.label).join(", ")}` : "none above"}; ${rogue.below.length ? `below: ${rogue.below.map((r) => r.label).join(", ")}` : "none below"}${filt.note()}` : noData("zone temperature");
    },
  });

  // VAV health = rogue VAVs: a damper or reheat valve that sits ~fully open or ~fully closed for (nearly) the whole range.
  // Comfort lives under Zones only; there is no comfort or airflow verdict here.
  rcxView({
    id: "vav_health", group: "VAV", title: "VAV — health (rogue dampers and reheat valves)",
    kinds: ZONES, scope: "site", minEquips: 1, hours: 168, fleet: true, headline: true,
    roles: { required: [], anyOf: ["damper_pct", "damper_cmd", "reheat_valve_pct"], optional: [] },
    render: async (el, ctx) => {
      const want = ctx.equips.map((eq) => ({ eq, dm: firstOf(ctx, eq, ["damper_pct", "damper_cmd"]), rh: ctx.first(eq, "reheat_valve_pct") }))
        .filter((w) => w.dm || w.rh);
      if (!want.length) return noData("VAV damper or reheat valve");
      const { data, windowSec } = await load(ctx, want.flatMap((w) => [w.dm, w.rh]).filter(Boolean));
      const filt = ahuFilter(ctx, windowSec);
      const devices = [];
      for (const w of want) {
        const vals = async (p) => (p ? (await filt.keep(w.eq, data.get(p.uuid) || [])).map(([, v]) => v) : null);
        devices.push({ id: w.eq.id, label: labelOf(w.eq), damper: await vals(w.dm), reheat: await vals(w.rh) });
      }
      const rows = rogueVavRows(devices);
      const tally = new Map();
      for (const d of devices) { const k = vavVerdictLabel(rows, d.id); tally.set(k, (tally.get(k) || 0) + 1); }
      const kinds = ["Healthy", ...new Set(rows.map((r) => `${r.part} always ${r.state}`))];
      const rogueIds = new Set(rows.map((r) => r.id));
      ctx.kpi({ id: "rogue-vavs", label: "Rogue VAVs", value: `${rogueIds.size} of ${devices.length}`, sub: `damper / reheat valve stuck${ctx.ahuOn ? " · while AHU on" : ""}`, order: 20, tone: rogueIds.size ? "warn" : "ok" });
      const [a, b] = rows.length ? frames(el, 2, [Math.max(260, 34 * rows.length + 110), 320]) : frames(el, 1, [320]);
      const kindColor = (k) => (k === "Healthy" ? HEALTHY_COLOR : /open$/.test(k) ? ROGUE_ABOVE_COLOR : ROGUE_BELOW_COLOR);
      const donut = comfortDonutOption(kinds.map((k) => ({ label: k, value: tally.get(k) || 0, color: kindColor(k) })), { title: "VAV health" });
      let ok;
      if (rows.length) {
        ok = draw(a, ctx, rogueBarsOption(rows, { title: `Rogue VAVs — position ${ROGUE_OPEN_PCT} % or more / ${ROGUE_CLOSED_PCT} % or less` }), "rcx_vav_rogue");
        draw(b, ctx, donut, "rcx_vav_health_donut");
      } else ok = draw(a, ctx, donut, "rcx_vav_health_donut");
      return `${devices.length} VAV(s) · rogue = damper or reheat valve at >= ${ROGUE_OPEN_PCT} % (open) or <= ${ROGUE_CLOSED_PCT} % (closed) for >= ${ROGUE_SHARE * 100} % of assessed samples (at least ${ROGUE_MIN_SAMPLES})`
        + `${rows.length ? "" : " · none found"}${filt.note()}`;
    },
  });

  // Single-VAV (and all-VAV) charts: positions and reheat discharge temperatures. No zone-airflow timeseries.
  rcxView({
    id: "vav_positions", group: "VAV", title: "VAV — damper and reheat valve position (timeseries)",
    kinds: ZONES, scope: "site", minEquips: 1, hours: 168,
    roles: { required: [], anyOf: ["damper_pct", "damper_cmd", "reheat_valve_pct"], optional: [] },
    render: async (el, ctx) => {
      const want = ctx.equips.map((eq) => ({ eq, dm: firstOf(ctx, eq, ["damper_pct", "damper_cmd"]), rh: ctx.first(eq, "reheat_valve_pct") })).filter((w) => w.dm || w.rh);
      if (!want.length) return noData("VAV damper or reheat valve");
      const { data } = await load(ctx, want.flatMap((w) => [w.dm, w.rh]).filter(Boolean));
      const rows = [];
      for (const w of want) {
        for (const [part, p] of [["damper", w.dm], ["reheat valve", w.rh]]) {
          if (!p) continue;
          for (const [t, v] of data.get(p.uuid) || []) if (finite(v)) rows.push({ equipment_id: labelOf(w.eq), series: part, ts: t, value: +(rcxStats.frac(v) * 100).toFixed(1) });
        }
      }
      const ok = draw(el, ctx, multiEquipmentTimeseriesOption(rows, { title: "Damper and reheat valve position", yTitle: "% open" }), "rcx_vav_positions");
      return ok ? `${want.length} VAV(s) · % open` : noData("VAV damper or reheat valve");
    },
  });

  // Reheat (discharge) temperatures: only VAVs that have a reheat valve are drawn.
  rcxView({
    id: "vav_reheat_dats", group: "VAV", title: "VAV — reheat discharge temps (timeseries)",
    kinds: ZONES, scope: "site", minEquips: 1, hours: 168,
    roles: { required: ["vav_discharge_t"], optional: ["reheat_valve_pct"] },
    render: async (el, ctx) => {
      const want = ctx.equips.filter((eq) => ctx.first(eq, "reheat_valve_pct")).map((eq) => ({ eq, y: ctx.first(eq, "vav_discharge_t") }));
      if (!want.length) return "No VAV with a reheat valve and a discharge temperature here.";
      const { data } = await load(ctx, want.map((w) => w.y));
      const rows = want.flatMap((w) => ctx.dispSeries(data.get(w.y.uuid) || [], ctx.siUnit(w.y)).map(([t, v]) => ({ equipment_id: labelOf(w.eq), series: "primary", ts: t, value: v })));
      const unit = unitsOf(ctx, want.map((w) => w.y));
      const ok = draw(el, ctx, multiEquipmentTimeseriesOption(rows, { title: "Reheat discharge air temperature", yTitle: unit }), "rcx_vav_reheat_dats");
      return ok ? `${want.length} VAV(s) with reheat${unit ? ` · ${unit}` : ""}` : noData("reheat discharge temperature");
    },
  });

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
          rows.push({ equipment_id: labelOf(w.eq), value: ctx.disp(v, ctx.siUnit(w.y)).value });   // Pa -> display
        }
      }
      const unit = unitsOf(ctx, want.map((w) => w.y));
      const ok = draw(el, ctx, multiEquipmentBoxOption(rows, { title: "Duct static pressure — fan on", yTitle: unit }), "rcx_duct_static_box");
      return ok ? `${rows.length} samples · fan-on filter on ${filtered}/${want.length} equip(s)` : noData("duct static (fan on)");
    },
  });

  resetPreset({ id: "ahu_sat_reset_scatter", group: "Scatter plots", title: "AHU — SAT vs web dry-bulb (scatter)", kinds: AIR, role: "sat", xRoles: ["web_oa_t", "oa_t"], xLabel: "OAT" });

  // Plant
  // Scatter plots draw wherever their roles exist (no equipment-kind restriction): outdoor-air temperature vs the hot-water
  // supply temperature (HW reset), and vs the chilled-water supply temperature when a chilled-water system exists.
  resetPreset({ id: "hw_reset_scatter", group: "Scatter plots", title: "Hot water — HWS vs web dry-bulb (scatter)", kinds: [], role: "hw_supply_t", xRoles: ["web_oa_t", "oa_t"], xLabel: "OAT" });
  resetPreset({ id: "chw_reset_scatter", group: "Scatter plots", title: "Chilled water — CHWS vs web dry-bulb (scatter)", kinds: [], role: "chw_supply_t", xRoles: ["web_oa_t", "oa_t"], xLabel: "OAT" });
  resetPreset({ id: "cw_reset_scatter", group: "Scatter plots", title: "Tower / CW — leave temp vs wet-bulb (dry-bulb fallback)", kinds: [...CHW, "cooling_tower"], role: "cw_supply_t", xRoles: ["web_wb_t", "web_oa_t", "oa_t"], xLabel: "OA wet-bulb / dry-bulb" });
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
    // degree days are C-days (SI); the last step shows them in the display system (F-days = x1.8)
    const ddK = ctx.dispDelta(1, TEMP).value, ddUnit = ddK === 1 ? "°C·day" : "°F·day";
    const baseDisp = round(ctx.disp(DEGREE_DAY_BASE_C, TEMP).value, ddK === 1 ? 1 : 0);
    const siRows = meterRows(monthlySum(energy), monthlyDegreeDays(dailyMeans(data.get(oat.uuid) || []), dd));
    const rows = siRows.map((r) => ({ ...r, dd: r.dd * ddK }));
    const fit = resetFit(rows.map((r) => [r.dd, r.energy]));
    const unit = gas ? unitsOf(ctx, sources.map((s) => s.p)) : "kWh";
    const ok = draw(el, ctx, meteringChartsOption(rows, {
      title: `${gas ? "Gas per month vs HDD" : "Electric kWh per month vs CDD"} (base ${baseDisp} ${ctx.dispUnit(TEMP)})`,
      ddLabel: `${dd.toUpperCase()} (${ddUnit}, base ${baseDisp})`, energyYTitle: `${gas ? "gas" : "electric"}${unit ? ` (${unit}${sources.some((s) => s.rate) && gas ? "/day" : ""})` : ""}`, fit,
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
    DEGREE_DAY_BASE_C, COMFORT_LO_C, COMFORT_HI_C, COMFORT_SP_HALF_C, defaultBand, spHalfWidth, comfortStats, rankComfort, resetFit, pairSeries, bucketMap,
    vavHealthStats, vavVerdict, stuckStats, stuckVerdict, rogueVavRows, vavVerdictLabel, zoneBand, pickRogueZones, ahuFilter,
    ROGUE: { OPEN_PCT: ROGUE_OPEN_PCT, CLOSED_PCT: ROGUE_CLOSED_PCT, SHARE: ROGUE_SHARE, MIN_SAMPLES: ROGUE_MIN_SAMPLES },
    ZONE_BAND: { P_LO: ZONE_P_LO, P_HI: ZONE_P_HI, MIN_ZONES: ZONE_BAND_MIN_ZONES, ROGUE_TOP: ZONE_ROGUE_TOP, ROGUE_MIN_SHARE: ZONE_ROGUE_MIN_SHARE, ROGUE_MIN_EXCESS_C: ZONE_ROGUE_MIN_EXCESS_C },
    dailyMeans, degreeDay, monthlyDegreeDays, isCumulative, dailyEnergy, monthlySum, meterRows, outlierEquipmentIds,
    options: {
      multiEquipmentTimeseriesOption, oatScatterOption, multiEquipmentBoxOption, rankingBarsOption, comfortDonutOption,
      meteringChartsOption, vavHealthWorstBarsOption, vavHealthDonutOption, zoneBandOption, rogueBarsOption,
    },
  };
})();
