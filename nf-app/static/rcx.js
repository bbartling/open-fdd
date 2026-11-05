// RCx views registry for the Open-FDD NF app.
//
// Every chart module (rcx-*.js, fdd-plots.js, energy.js) registers views with rcxView().
// A view declares the rule roles it needs (same role names as sql/fdd + fdd-catalog.json);
// the RCx tab binds them on the equips in scope with fdd.js (NF class or Haystack markers),
// shows the views that can draw, and lists the rest with what they are missing.
// No site-specific code: equips, points, units and history all come from NF.
//
// Needs nf.js, model.js, theme.js, charts.js (fetchSeries, parseTs), fdd.js (bindRoles,
// equipPool, equipKinds, loadCatalog). Loaded before the rcx-*.js view modules and app.js.

const RCX_VIEWS = [];

/**
 * Register a view.
 * def = {
 *   id: "economizer-delta",                  unique, used in the URL (#rcx/<id>)
 *   group: "Air handlers",                    section heading on the RCx tab
 *   title: "Economizer: OAT − MAT",           card title
 *   kinds: ["ahu"],                           equipment kinds (fdd-catalog equipment_kinds); [] = any
 *   roles: { required: ["oa_t", "mat"], optional: ["rat"] },
 *   scope: "equip" | "site",                  equip: one card per bound equip; site: one card, all bound equips
 *   minEquips: 1,                             site views: how many bound equips it needs
 *   hours: 168,                               default history span (the tab's range picker overrides)
 *   render: async (el, ctx) => {…}            draw into el; return a short text note or nothing
 * }
 */
function rcxView(def) {
  if (RCX_VIEWS.some((v) => v.id === def.id)) throw new Error(`rcxView: duplicate id ${def.id}`);
  RCX_VIEWS.push({ kinds: [], roles: { required: [], optional: [] }, scope: "equip", minEquips: 1, hours: 168, ...def });
}

const equipLabel = (e) => (e.attrs || {}).dis || e.name;

/**
 * Which equips can feed a view: [{ rec, id, name, kinds, bound: {role: [points]} }].
 * An equip qualifies when its kinds match and every required role has at least one point.
 */
function rcxBind(view, equips, model, catalog) {
  const out = [];
  for (const rec of equips) {
    const kinds = equipKinds(rec, catalog);
    if (view.kinds.length && !view.kinds.some((k) => kinds.includes(k))) continue;
    const bound = bindRoles([...view.roles.required, ...view.roles.optional], equipPool(rec, model), catalog);
    if (view.roles.required.every((r) => bound[r] && bound[r].length)) {
      out.push({ rec, id: idOf(rec), name: equipLabel(rec), kinds, bound });
    }
  }
  return out;
}

/** Roles a view still needs on the scoped equips (for the "not available" list). */
function rcxMissing(view, equips, model, catalog) {
  const missing = new Set();
  for (const rec of equips) {
    const kinds = equipKinds(rec, catalog);
    if (view.kinds.length && !view.kinds.some((k) => kinds.includes(k))) continue;
    const bound = bindRoles(view.roles.required, equipPool(rec, model), catalog);
    for (const r of view.roles.required) if (!bound[r].length) missing.add(r);
  }
  return [...missing];
}

/**
 * The context a view's render() gets.
 *   ctx.equips          bound equips (one for scope "equip", all for scope "site")
 *   ctx.hours           history span in hours
 *   ctx.first(eq, role) best point for a role on an equip (or null)
 *   ctx.series(pts, o)  Map(uuid -> [[ms, v], …]) from NF, resampled server side
 *                       o = { hours, windowSec, method: "AVERAGE"|"MIN"|"MAX"|… }
 *   ctx.aligned(cols,o) one time grid for several points: { t: [ms…], cols: {key: [v|null…]} }
 *                       cols = { key: point } — the shape most RCx math wants
 *   ctx.chart(el)       themed ECharts instance (theme.js ofddChart)
 *   ctx.unit(p)         display unit of a point
 *   ctx.weather         site weather points (tagged `weather`)
 *   ctx.model, ctx.catalog, ctx.view
 */
function rcxContext(view, equips, hours, model, catalog) {
  const first = (eq, role) => (eq.bound[role] && eq.bound[role][0]) || null;
  const series = (pts, o = {}) => fetchSeries(pts.filter(Boolean), o.hours || hours,
    { method: o.method || "AVERAGE", ...(o.windowSec ? { windowSec: o.windowSec } : {}) });
  const aligned = async (cols, o = {}) => {
    const entries = Object.entries(cols).filter(([, p]) => p);
    const windowSec = o.windowSec || pickWindow(o.hours || hours);
    const data = await series(entries.map(([, p]) => p), { ...o, windowSec });
    const step = windowSec * 1e3;
    const ts = new Set();
    const byKey = {};
    for (const [key, p] of entries) {
      const m = new Map((data.get(p.uuid) || []).map(([t, v]) => [Math.floor(t / step) * step, v]));
      byKey[key] = m;
      for (const t of m.keys()) ts.add(t);
    }
    const t = [...ts].sort((a, b) => a - b);
    const out = {};
    for (const key of Object.keys(cols)) out[key] = t.map((x) => (byKey[key] ? byKey[key].get(x) ?? null : null));
    return { t, cols: out };
  };
  const site = equips[0] && (equips[0].rec.attrs || {}).siteRef;
  return {
    view, equips, hours, model, catalog, first, series, aligned,
    chart: (el) => ofddChart(el),
    unit: (p) => (p && p.units) || "",
    weather: model.points.filter((p) => has(p, "weather") && has(p, "point") && p.siteRef === site),
  };
}

/** Views for the equips in scope: { ready: [{view, equips}], missing: [{view, roles}] }. */
function rcxPlan(equips, model, catalog) {
  const ready = [];
  const missing = [];
  for (const view of RCX_VIEWS) {
    const bound = rcxBind(view, equips, model, catalog);
    if (bound.length >= (view.scope === "site" ? view.minEquips : 1)) ready.push({ view, equips: bound });
    else missing.push({ view, roles: rcxMissing(view, equips, model, catalog) });
  }
  return { ready, missing };
}

// ---- fault lane: the ONE way every plot shows faults ---------------------------------
// Same as central's FDD plots: a stand-alone 0/1 "confirmed_fault" step lane in its own
// grid at the bottom of the chart, x axis linked to the signal grids, FAULT_LANE colors.
// Fault data = the FDD hook's result point for (equip, rule): fault % per run (hourly);
// any value > 0 counts as "in fault" for that hour.

/** The FDD hook's result point for an equip + rule (markers fdd + fault, ruleRef, equipRef), or null. */
function rcxResultPoint(model, equipId, ruleId) {
  return model.points.find((p) => has(p, "fdd") && has(p, "fault") && p.equipRef === equipId
    && ((p.rec.attrs || {}).ruleRef || "") === ruleId) || null;
}

/** [[ms, 0|1], …] fault lane for an equip + rule over `hours` (hourly; [] if the rule never ran). */
async function rcxFaultData(model, equipId, ruleId, hours) {
  const p = rcxResultPoint(model, equipId, ruleId);
  if (!p) return [];
  const data = await fetchSeries([p], hours, { method: "MAX", windowSec: 3600 });
  return (data.get(p.uuid) || []).map(([t, v]) => [t, v > 0 ? 1 : 0]);
}

/**
 * Append the bottom fault lane to an ECharts option built for one or more stacked grids.
 * Works with `grid`/`xAxis`/`yAxis` given as objects or arrays; signal grids are squeezed
 * to leave LANE_PX at the bottom, every x axis is linked (tooltip, zoom).
 *   lanes = [{ name: "ECON-1", data: [[ms, 0|1], …] }, …]   (several rules → several lanes)
 */
function rcxWithFaultLane(option, lanes) {
  lanes = (lanes || []).filter((l) => l && l.data && l.data.length);
  if (!lanes.length) return option;
  const LANE_PX = 26, GAP = 8, BOTTOM = 34;
  const arr = (x) => (x == null ? [] : Array.isArray(x) ? x : [x]);
  const grids = arr(option.grid).length ? arr(option.grid) : [{}];
  const xAxes = arr(option.xAxis).length ? arr(option.xAxis) : [{ type: "time" }];
  const yAxes = arr(option.yAxis);
  const reserve = BOTTOM + lanes.length * (LANE_PX + GAP);
  // Push existing grids up: bottom offsets are relative to the chart's bottom edge.
  for (const g of grids) g.bottom = (typeof g.bottom === "number" ? g.bottom : 40) + reserve;
  for (const x of xAxes) { x.axisLabel = { ...(x.axisLabel || {}), show: false }; }
  // Lane names sit left of their lane: make the left margin wide enough for the longest one,
  // on every grid, so all the time axes stay aligned.
  const nameRoom = 16 + 7 * Math.max(...lanes.map((l) => String(l.name).length));
  const left = Math.max(typeof grids[0].left === "number" ? grids[0].left : 60, nameRoom);
  const right = grids[0].right ?? 20;
  for (const g of grids) g.left = left;
  const series = arr(option.series);
  lanes.forEach((lane, i) => {
    const gi = grids.length;
    grids.push({ left, right, height: LANE_PX, bottom: BOTTOM + (lanes.length - 1 - i) * (LANE_PX + GAP) });
    xAxes.push({ type: "time", gridIndex: gi, axisLabel: { show: i === lanes.length - 1 }, splitLine: { show: false } });
    yAxes.push({ type: "value", gridIndex: gi, min: 0, max: 1, interval: 1, name: lane.name, nameLocation: "middle",
      nameRotate: 0, nameGap: 8, nameTextStyle: { align: "right" }, axisLabel: { show: false }, splitLine: { show: false } });
    series.push({ name: lane.name, type: "line", step: "end", showSymbol: false, connectNulls: false,
      xAxisIndex: xAxes.length - 1, yAxisIndex: yAxes.length - 1,
      lineStyle: FAULT_LANE.lineStyle, areaStyle: FAULT_LANE.areaStyle, data: lane.data });
  });
  const allX = xAxes.map((_, i) => i);
  return {
    ...option, grid: grids, xAxis: xAxes, yAxis: yAxes, series,
    tooltip: { trigger: "axis", ...(option.tooltip || {}), axisPointer: { link: [{ xAxisIndex: "all" }] } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    dataZoom: [{ type: "inside", xAxisIndex: allX }],
  };
}

// ---- small shared math for the view modules ------------------------------------------
const rcxStats = {
  mean: (xs) => { const v = xs.filter((x) => x != null && Number.isFinite(x)); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; },
  quantile: (xs, q) => {
    const v = xs.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
    if (!v.length) return null;
    const i = (v.length - 1) * q, lo = Math.floor(i), hi = Math.ceil(i);
    return v[lo] + (v[hi] - v[lo]) * (i - lo);
  },
  /** [min, q1, median, q3, max] for an ECharts boxplot. */
  box: (xs) => [0, 0.25, 0.5, 0.75, 1].map((q) => rcxStats.quantile(xs, q)),
  /** Least-squares line through [[x, y]…] → { slope, intercept, r2 } (null if < 2 points). */
  fit: (pairs) => {
    const p = pairs.filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
    if (p.length < 2) return null;
    const n = p.length, mx = p.reduce((a, [x]) => a + x, 0) / n, my = p.reduce((a, [, y]) => a + y, 0) / n;
    let sxy = 0, sxx = 0, syy = 0;
    for (const [x, y] of p) { sxy += (x - mx) * (y - my); sxx += (x - mx) ** 2; syy += (y - my) ** 2; }
    if (!sxx) return null;
    const slope = sxy / sxx;
    return { slope, intercept: my - slope * mx, r2: syy ? (sxy * sxy) / (sxx * syy) : 1 };
  },
  /** Commands/status as 0–1 fractions (percent inputs > 1 are scaled, like the SQL pack). */
  frac: (v) => (v == null ? null : v > 1 ? v / 100 : v),
};
