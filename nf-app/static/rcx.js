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

/** RCx tab state (the device filter is the shell's per-tab equip picker): ahuOn = the "AHU on" filter (null = automatic: on when the feeding AHU is known). */
const rcxUi = { ahuOn: null };

/**
 * Register a view.
 * def = {
 *   id: "economizer-delta",                  unique, used in the URL (#rcx/<id>)
 *   group: "Air handlers",                    section heading on the RCx tab
 *   title: "Economizer: OAT − MAT",           card title
 *   kinds: ["ahu"],                           equipment kinds (fdd-catalog equipment_kinds); [] = any
 *   roles: { required: ["oa_t", "mat"], optional: ["rat"] },     anyOf: [..] = at least one of these roles must bind (e.g. fan status OR command)
 *   scope: "equip" | "site",                  equip: one card per bound equip; site: one card, all bound equips
 *   minEquips: 1,                             site views: how many bound equips it needs
 *   hours: 168,                               default history span (the tab's range picker overrides)
 *   tab: "rcx" | "fdd",                       which tab draws it (default "rcx"; fault-lane charts live on "fdd")
 *   fleet: true,                              fleet analytics (pies, rankings, all-zones): only in the all-devices view
 *   headline: true,                           drawn in the headline row at the top of the tab
 *   tabHidden: true,                          registered (agent analytics, parity) but not drawn on any tab
 *   render: async (el, ctx) => {…}            draw into el; return a short text note or nothing
 * }
 */
/** @param {RcxViewDef} def */
function rcxView(def) {
  if (RCX_VIEWS.some((v) => v.id === def.id)) throw new Error(`rcxView: duplicate id ${def.id}`);
  RCX_VIEWS.push({ kinds: [], roles: { required: [], optional: [] }, scope: "equip", minEquips: 1, hours: 168, tab: "rcx", ...def });
}

const equipLabel = (e) => (e.attrs || {}).dis || e.name;

/**
 * Which equips can feed a view: [{ rec, id, name, kinds, bound: {role: [points]} }].
 * An equip qualifies when its kinds match and every required role has at least one point.
 */
/** @param {RcxViewDef} view @param {NfRecord[]} equips @param {OfddModel} model @param {FddCatalog} catalog @returns {OfddEquip[]} */
function rcxBind(view, equips, model, catalog) {
  const out = [];
  for (const rec of equips) {
    const kinds = equipKinds(rec, catalog);
    if (view.kinds.length && !view.kinds.some((k) => kinds.includes(k))) continue;
    const bound = bindRoles([...view.roles.required, ...(view.roles.anyOf || []), ...view.roles.optional], equipPool(rec, model), catalog);
    const any = !view.roles.anyOf || !view.roles.anyOf.length || view.roles.anyOf.some((r) => bound[r] && bound[r].length);
    if (any && view.roles.required.every((r) => bound[r] && bound[r].length)) {
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
    const bound = bindRoles([...view.roles.required, ...(view.roles.anyOf || [])], equipPool(rec, model), catalog);
    for (const r of view.roles.required) if (!bound[r].length) missing.add(r);
    const any = view.roles.anyOf || [];
    if (any.length && !any.some((r) => bound[r].length)) missing.add(any.join(" or "));
  }
  return [...missing];
}

// ---- units: calc in SI, display in the user's system -----------------------------------
// NF points arrive in whatever unit the site uses. Everything a view computes runs on SI
// values (units.js: °C, Pa, L/s, kW, kWh, %); only the last step before a chart/label maps
// them to the display system (ofddUnits.displaySystem(): "imperial" | "si"). Unitless and
// unknown units pass through unchanged. Without units.js (bare test contexts) everything
// passes through.
const rcxUnits = () => globalThis.ofddUnits || null;

/** SI unit of a point (its own unit when unknown/unitless). */
function rcxSiUnit(p) {
  const U = rcxUnits(), u = (p && p.units) || "";
  const r = U && u ? U.toSI(0, u) : null;
  return r ? r.unit : u;
}

/** [[ms, v], …] in the point's own unit -> canonical SI. */
function rcxToSI(arr, p) {
  const U = rcxUnits();
  if (!U || !p || !p.units || !U.toSI(0, p.units)) return arr;
  return arr.map(([t, v]) => { const r = v == null ? null : U.toSI(v, p.units); return [t, r ? r.value : v]; });
}

/** SI value -> { value, unit } in the display system. */
function rcxDisp(v, siUnit) {
  const U = rcxUnits();
  return U ? U.fromSI(v, siUnit, U.displaySystem()) : { value: v == null ? null : Number(v), unit: siUnit || "" };
}
/** SI difference (e.g. delta degC) -> { value, unit } in the display system (no 32 offset). */
function rcxDispDelta(d, siUnit) {
  const U = rcxUnits();
  return U ? U.deltaFromSI(d, siUnit, U.displaySystem()) : { value: d == null ? null : Number(d), unit: siUnit || "" };
}
/** [[ms, v], …] SI -> display values (delta = true for differences). */
function rcxDispSeries(arr, siUnit, delta = false) {
  const U = rcxUnits();
  if (!U) return arr;
  const sys = U.displaySystem(), f = delta ? U.deltaFromSI : U.fromSI;
  return arr.map(([t, v]) => [t, v == null ? null : f(v, siUnit, sys).value]);
}

/**
 * The context a view's render() gets.
 *   ctx.equips          bound equips (one for scope "equip", all for scope "site")
 *   ctx.hours           history span in hours
 *   ctx.first(eq, role) best point for a role on an equip (or null)
 *   ctx.series(pts, o)  Map(uuid -> [[ms, v], …]) from NF, resampled server side, values in SI
 *                       o = { hours, windowSec, method: "AVERAGE"|"MIN"|"MAX"|… }
 *   ctx.aligned(cols,o) one time grid for several points, values in SI: { t: [ms…], cols: {key: [v|null…]} }
 *                       cols = { key: point } — the shape most RCx math wants
 *   ctx.alignedFine(cols,o) same shape, but on the FINE grid (300 s window, long spans fetched in chunks):
 *                       the one to use for run hours, after-hours split and cooling bins. Charts may
 *                       still draw from aligned() (~360 points); never integrate on that grid.
 *   ctx.chart(el)       themed ECharts instance (theme.js ofddChart)
 *   ctx.siUnit(p)       SI unit of a point (own unit when unknown)
 *   ctx.disp(v, si)     SI value -> { value, unit } in the display system
 *   ctx.dispDelta(d, si)  same for differences (Δ°C -> Δ°F ×1.8, no offset)
 *   ctx.dispUnit(si)    display unit text for an SI unit
 *   ctx.dispSystem()    "imperial" | "si"
 *   ctx.dispSeries(arr, si, delta)  [[ms, SI]] -> [[ms, display]]
 *   ctx.unit(p)         display unit of a point
 *   ctx.weather         site weather points (tagged `weather`)
 *   ctx.ahuOn           true when the tab's "AHU on" filter is active
 *   ctx.feedingAhu(eq)  { ahu, assumed } the AHU that feeds a VAV (airRef; the site's only AHU = assumed), or null
 *   ctx.ahuMask(eq, windowSec)  async: { on: Map(bucket ms -> bool), ahu, assumed, role } or null (no fan signal)
 *   ctx.kpi(tile)       publish a summary tile { id, label, value, sub?, tone?, order? } for the tab's KPI row
 *   ctx.model, ctx.catalog, ctx.view
 */
const RCX_FINE_SEC = 300;              // NF resample window for integration (ctx.alignedFine)
const RCX_FINE_MAX_SAMPLES = 9000;     // per series per request (NF caps at ~10000)
const rcxChartConfig = new WeakMap();
const rcxChartOriginalSetOption = new WeakMap();

/**
 * Shared look of every card chart: x labels never overlap (hideOverlap), and `dropTitle` removes the ECharts title when
 * the card already has a heading with the same text (a subtext, if any, stays). A title-less legend/grid moves up by the
 * title's room so the chart does not keep an empty band.
 */
function rcxTidyOption(option, dropTitle) {
  if (!option || typeof option !== "object") return option;
  const out = { ...option };
  const arr = (x) => (x == null ? [] : Array.isArray(x) ? x : [x]);
  if (out.xAxis) out.xAxis = (Array.isArray(out.xAxis) ? out.xAxis : [out.xAxis]).map((a) => ({ ...a, axisLabel: { hideOverlap: true, ...(a.axisLabel || {}) } }));
  if (Array.isArray(option.xAxis) === false && option.xAxis) out.xAxis = out.xAxis[0];
  if (dropTitle && out.title && !Array.isArray(out.title) && out.title.text) {
    const { text, ...rest } = out.title;
    out.title = rest.subtext ? rest : undefined;
    if (!rest.subtext) {
      const up = (v) => (typeof v === "number" && v >= 24 ? v - 24 : v);
      if (out.legend && !Array.isArray(out.legend)) out.legend = { ...out.legend, top: up(out.legend.top) };
      if (out.grid) out.grid = Array.isArray(out.grid) ? out.grid.map((g) => ({ ...g, top: up(g.top) })) : { ...out.grid, top: up(out.grid.top) };
    }
  }
  return out;
}

function rcxSiteChart(el, siteTz, range, dropTitle = false) {
  const chart = ofddChart(el);
  if (!chart || typeof chart.setOption !== "function") return chart;
  rcxChartConfig.set(chart, { siteTz: chartTimeZone(siteTz), range, dropTitle });
  if (!rcxChartOriginalSetOption.has(chart)) {
    const original = chart.setOption.bind(chart);
    rcxChartOriginalSetOption.set(chart, original);
    chart.setOption = (option, ...args) => {
      const cfg = rcxChartConfig.get(chart);
      const tidy = rcxTidyOption(option, cfg.dropTitle);
      const styled = typeof chartOptionSiteTime === "function"
        ? chartOptionSiteTime(tidy, cfg.siteTz) : tidy;
      // Keep explicit view extents (for example a week bucket whose start precedes a short
      // selected interval). The input series itself is already fetched for cfg.range.
      const bounds = cfg.range?.resolvedBounds;
      if (bounds && Number.isFinite(bounds.fromMs) && Number.isFinite(bounds.toMs)) {
        for (const axis of (Array.isArray(styled?.xAxis) ? styled.xAxis : [styled?.xAxis])) {
          if (axis?.type !== "time") continue;
          if (axis.min == null) axis.min = bounds.fromMs;
          if (axis.max == null) axis.max = bounds.toMs;
        }
      }
      return original(styled, ...args);
    };
  }
  return chart;
}

/** @param {RcxViewDef} view @param {OfddEquip[]} equips @param {number} hours @param {OfddModel} model @param {FddCatalog} catalog @returns {RcxContext} */
function rcxContext(view, equips, hours, model, catalog, range = null, siteTz = "UTC", extra = {}) {
  const first = (eq, role) => (eq.bound[role] && eq.bound[role][0]) || null;
  const series = async (pts, o = {}) => {
    const list = pts.filter(Boolean);
    const opts = { method: o.method || "AVERAGE", ...(o.windowSec ? { windowSec: o.windowSec, minWindowSec: o.windowSec } : {}),
      ...(o.endMs != null ? { endMs: o.endMs } : {}), siteTz, preserveWindow: true };
    const data = range ? (await fetchRange(list, range, opts)).series : await fetchSeries(list, o.hours || hours, opts);
    return new Map(list.map((p) => [p.uuid, rcxToSI(data.get(p.uuid) || [], p)]));
  };
  // Fine-grid history for integration (run hours, bins): a 300 s window instead of the ~360-point
  // display grid. NF caps a series at ~10000 samples per request, so a long span is walked back in
  // chunks of at most RCX_FINE_MAX_SAMPLES (750 h at 300 s) and the chunks are merged by timestamp.
  const fineSeries = async (pts, o = {}) => {
    const list = pts.filter(Boolean), span = o.hours || hours, windowSec = o.windowSec || RCX_FINE_SEC;
    if (range) return series(list, { ...o, hours: span, windowSec });
    const perChunk = Math.max(1, Math.floor((RCX_FINE_MAX_SAMPLES * windowSec) / 3600));
    if (span <= perChunk) return series(list, { ...o, hours: span, windowSec });
    const end = Math.ceil(Date.now() / (windowSec * 1e3)) * windowSec * 1e3;
    const jobs = [];
    for (let done = 0; done < span; done += perChunk) {
      jobs.push(series(list, { ...o, hours: Math.min(perChunk, span - done), windowSec, endMs: end - done * 3600e3 }));
    }
    const parts = await Promise.all(jobs);
    return new Map(list.map((p) => {
      const m = new Map();
      for (const part of parts) for (const [t, v] of part.get(p.uuid) || []) m.set(t, v);
      return [p.uuid, [...m].sort((a, b) => a[0] - b[0])];
    }));
  };
  const gridOf = (cols, data, windowSec) => {
    const entries = Object.entries(cols).filter(([, p]) => p);
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
  const aligned = async (cols, o = {}) => {
    const windowSec = o.windowSec || pickWindow(o.hours || hours);
    const data = await series(Object.values(cols).filter(Boolean), { ...o, windowSec });
    return gridOf(cols, data, windowSec);
  };
  // Same shape as aligned(), but on the fine grid; use it for anything that integrates over time.
  const alignedFine = async (cols, o = {}) => {
    const windowSec = o.windowSec || RCX_FINE_SEC;
    const data = await fineSeries(Object.values(cols).filter(Boolean), { ...o, windowSec });
    return { ...gridOf(cols, data, windowSec), windowSec, fine: true };
  };
  const site = equips[0] && equips[0].rec && (equips[0].rec.attrs || {}).siteRef;
  const feeds = () => rcxAirFeeds(model, site, catalog);
  const feedingAhu = (eq) => feeds().get(eq.id) || null;
  const fanOf = (ahu) => {
    const bound = bindRoles(["fan_status", "fan_cmd"], equipPool(ahu.rec, model), catalog);
    const role = bound.fan_status.length ? "fan_status" : bound.fan_cmd.length ? "fan_cmd" : null;
    return role ? { role, p: bound[role][0] } : null;
  };
  const maskCache = extra.maskCache || new Map();    // AHU fan point + window -> pending mask (VAVs share their AHU; the tab shares it across cards)
  const ahuMask = async (eq, windowSec = RCX_FINE_SEC) => {
    const f = feedingAhu(eq);
    const fan = f && f.ahu ? fanOf(f.ahu) : null;
    if (!fan) return null;
    const key = `${fan.p.uuid}|${windowSec}`;
    if (!maskCache.has(key)) {
      maskCache.set(key, series([fan.p], { windowSec }).then((data) => rcxAhuOnBuckets(data.get(fan.p.uuid) || [], windowSec * 1e3)));
    }
    return { on: await maskCache.get(key), ahu: f.ahu, assumed: f.assumed, role: fan.role };
  };
  return {
    view, equips, hours, model, catalog, first, series, aligned, alignedFine, range, siteTz,
    ahuOn: !!extra.ahuOn, feedingAhu, ahuMask, kpi: (tile) => { if (extra.kpis) extra.kpis.push(tile); },
    chart: (el) => rcxSiteChart(el, siteTz, range, !!extra.dropTitle),
    siUnit: rcxSiUnit,
    disp: rcxDisp,
    dispDelta: rcxDispDelta,
    dispUnit: (si) => rcxDisp(0, si).unit,
    dispSystem: () => (rcxUnits() ? rcxUnits().displaySystem() : "si"),
    dispSeries: rcxDispSeries,
    unit: (p) => rcxDisp(0, rcxSiUnit(p)).unit,
    weather: model.points.filter((p) => has(p, "weather") && has(p, "point") && p.siteRef === site),
  };
}

// ---- AHU -> VAV feed + the "AHU on" filter ------------------------------------------------
/** Ref value -> bare id ("@AHU-1" and "AHU-1" are the same). */
const rcxRefId = (v) => String(v ?? "").trim().replace(/^@/, "");

/**
 * Which AHU feeds each VAV: Map(vav id -> { ahu: OfddEquip-like { rec, id, name }, assumed }).
 *   1. the VAV's Haystack `airRef` names an AHU of the same site (by id, name or NF uuid): assumed = false;
 *   2. no airRef at all and the site has exactly ONE AHU: that AHU, assumed = true (the UI says "assumed");
 *   3. otherwise no entry (an airRef that points nowhere is not guessed around).
 * `equips` = NF equip records of the site, `kindsOf(rec)` = equipment kinds of a record (fdd.js equipKinds).
 */
function rcxAirFeedMap(equips, kindsOf) {
  const ahus = equips.filter((e) => kindsOf(e).includes("ahu"));
  const out = new Map();
  for (const e of equips) {
    if (!kindsOf(e).includes("vav")) continue;
    const ref = rcxRefId((e.attrs || {}).airRef);
    const mk = (rec, assumed) => ({ ahu: { rec, id: idOf(rec), name: equipLabel(rec) }, assumed });
    if (ref) {
      const hit = ahus.find((a) => [idOf(a), a.name, a.uuid, (a.attrs || {}).dis].some((x) => x && rcxRefId(x) === ref));
      if (hit) out.set(idOf(e), mk(hit, false));
    } else if (ahus.length === 1) out.set(idOf(e), mk(ahus[0], true));
  }
  return out;
}

/** Feed map for one site of the model. */
function rcxAirFeeds(model, site, catalog) {
  const equips = model.equips.filter((e) => !site || (e.attrs || {}).siteRef === site);
  return rcxAirFeedMap(equips, (e) => equipKinds(e, catalog));
}

/** [[ms, v], ...] fan status/cmd -> Map(bucket start ms -> on?) (on = fraction above 0.05, like the runtime views). */
function rcxAhuOnBuckets(samples, stepMs) {
  const m = new Map();
  for (const [t, v] of samples) {
    if (v == null || !Number.isFinite(v)) continue;
    m.set(Math.floor(t / stepMs) * stepMs, rcxStats.frac(v) > 0.05);
  }
  return m;
}

/** Keep only the samples whose bucket has the AHU running. mask = rcxAhuOnBuckets(...); null mask = keep all. */
function rcxKeepAhuOn(samples, mask, stepMs) {
  if (!mask) return samples;
  return samples.filter(([t]) => mask.get(Math.floor(t / stepMs) * stepMs) === true);
}

/** HTML for the KPI tile row: tiles = [{ id, label, value, sub?, tone? ("warn"|"ok") , order? }]. */
function rcxKpiHtml(tiles) {
  const e = (x) => String(x ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  return [...tiles].sort((a, b) => (a.order ?? 50) - (b.order ?? 50) || String(a.id).localeCompare(String(b.id)))
    .map((t) => `<div class="kpi${t.tone ? ` kpi-${e(t.tone)}` : ""}" data-kpi="${e(t.id)}"><span class="kpi-label">${e(t.label)}</span>`
      + `<b class="kpi-value">${e(t.value)}</b>${t.sub ? `<span class="kpi-sub">${e(t.sub)}</span>` : ""}</div>`).join("");
}

/**
 * Views for the equips in scope: { ready: [{view, equips}], missing: [{view, roles}] }.
 * opts.tab ("rcx" | "fdd"): only that tab's views (default: all, which the agent analytics hook relies on);
 * opts.single: one device is selected, so fleet analytics (view.fleet) and tabHidden views are left out.
 */
function rcxPlan(equips, model, catalog, opts = {}) {
  const ready = [];
  const missing = [];
  for (const view of RCX_VIEWS) {
    if (opts.tab && view.tab !== opts.tab) continue;
    if (opts.tab && view.tabHidden) continue;
    if (opts.single && view.fleet) continue;
    const bound = rcxBind(view, equips, model, catalog);
    if (bound.length >= (view.scope === "site" ? view.minEquips : 1)) ready.push({ view, equips: bound });
    else missing.push({ view, roles: rcxMissing(view, equips, model, catalog) });
  }
  return { ready, missing };
}

// ---- fault lane: the ONE way every plot shows faults ---------------------------------
// Same as central's FDD plots: a stand-alone 0/1 "confirmed_fault" step lane in its own
// grid at the bottom of the chart, x axis linked to the signal grids, FAULT_LANE colors.
// Fault data (5.0.3) = the FDD hook's per-timestamp TIMELINE point for (equip, rule): one sample per assessed
// history timestamp, 1 = confirmed fault, 0 = ok, and NO sample where the rule could not assess (gap = null in the
// lane, never 0). Only when no timeline point exists (hook older than 5.0.3, or a rule without a per-row confirmed
// flag) the lane falls back to the rolling fault_pct result point, hourly MAX, and is marked approximate.

/**
 * Who an equip is, for matching the hook's result points: { id (Haystack id), site (siteRef), uuid (NF equip uuid) }.
 * `equip` = an OfddEquip ({ rec, id }), an NF equip record, or (legacy) a bare equip id string, which carries no
 * site and matches on equipRef only, so two sites that both have "AHU-1" are indistinguishable: pass the equip.
 */
function rcxEquipIdentity(equip) {
  if (typeof equip === "string") return { id: equip, site: "", uuid: "" };
  const rec = (equip && equip.rec) || equip || {};
  const a = rec.attrs || {};
  return { id: (equip && equip.id) || idOf(rec), site: a.siteRef || "", uuid: rec.uuid || "" };
}

/** How well result point p belongs to the equip: 0 no, 1 equipRef only (legacy), 2 equipRef + siteRef, 3 equip uuid. */
function rcxMatchRank(p, who, model) {
  if (p.equipRef !== who.id) return 0;
  const a = p.rec.attrs || {};
  if (who.uuid && a.equipUuid) return a.equipUuid === who.uuid ? 3 : 0;
  if (!who.site) return 1;
  if (p.siteRef) return p.siteRef === who.site ? 2 : 0;
  // a 5.0.0 point without any siteRef: only when no other equip in the model shares the id
  return ((model.equips || []).filter((e) => idOf(e) === who.id).length <= 1) ? 1 : 0;
}

function rcxBestPoint(model, equip, ruleId, markers, sensorRef = null) {
  const who = rcxEquipIdentity(equip);
  let best = null, bestRank = 0;
  for (const p of model.points) {
    if (!markers.every((m) => has(p, m)) || ((p.rec.attrs || {}).ruleRef || "") !== ruleId) continue;
    if (sensorRef != null && String((p.rec.attrs || {}).sensorRef || "") !== String(sensorRef)) continue;
    if (sensorRef == null && (p.rec.attrs || {}).sensorRef) continue;
    const r = rcxMatchRank(p, who, model);
    if (r > bestRank) { best = p; bestRank = r; }
  }
  return best;
}

/** The FDD hook's fault_pct result point (markers fdd + fault, ruleRef) of an equip + rule, site scoped, or null. */
function rcxResultPoint(model, equip, ruleId, sensorRef = null) {
  return rcxBestPoint(model, equip, ruleId, ["fdd", "fault"], sensorRef);
}

/** The hook's per-timestamp confirmed-fault point (marker fault_timeline, ruleRef) of an equip + rule, site scoped, or null. */
function rcxTimelinePoint(model, equip, ruleId, sensorRef = null) {
  return rcxBestPoint(model, equip, ruleId, ["fault_timeline"], sensorRef);
}

/** Result points for each sensor series in a per-sensor sweep. */
function rcxSensorResultPoints(model, equip, ruleId) {
  const who = rcxEquipIdentity(equip);
  return (model.points || []).filter((p) => has(p, "fdd") && has(p, "fault")
    && ((p.rec.attrs || {}).ruleRef || "") === ruleId
    && ((p.rec.attrs || {}).fddSummary === "sensor" || (p.rec.attrs || {}).sensorRef)
    && rcxMatchRank(p, who, model) > 0);
}

/**
 * Raw timeline samples -> lane: [[ms, 1|0|null]]. Values > 0 are 1, other numbers 0, null stays null; where two
 * neighbouring samples are further apart than 1.5 windows a [ms, null] is inserted so the lane shows a gap.
 */
function rcxTimelineLane(samples, windowSec) {
  const out = [];
  const arr = [...(samples || [])].sort((a, b) => a[0] - b[0]);
  const step = (windowSec || 300) * 1e3;
  for (const [t, v] of arr) {
    const prev = out.length ? out[out.length - 1] : null;
    if (prev && prev[1] != null && t - prev[0] > 1.5 * step) out.push([prev[0] + step, null]);
    out.push([t, v == null ? null : v > 0 ? 1 : 0]);
  }
  return out;
}

const rcxTagLane = (lane, source, approximate) =>
  Object.defineProperties(lane, { source: { value: source }, approximate: { value: approximate } });

/**
 * Keep a result history in the unit/output currently declared by its attrs.
 * NF stores one unit attribute per point, not per sample. `fddOutputSince` is
 * the durable boundary written when the output changes; skip the partial
 * resample bucket containing that boundary so old and new values are never
 * averaged/maxed together. Legacy points without the boundary retain history.
 */
function rcxCurrentOutputSeries(point, samples, windowSec = 0) {
  const attrs = (point && point.rec && point.rec.attrs) || {};
  if (!["fault_pct", "fault_hours"].includes(attrs.fddOutput)) return Array.from(samples || []);
  const boundary = Date.parse(attrs.fddOutputSince || "");
  if (!Number.isFinite(boundary)) return Array.from(samples || []);
  const width = Math.max(0, Number(windowSec) || 0) * 1e3;
  const firstAllowed = width > 0 ? Math.ceil(boundary / width) * width : boundary;
  return Array.from(samples || []).filter(([t]) => Number(t) >= firstAllowed);
}

/**
 * Fault lane [[ms, 1 | 0 | null]] for an equip + rule over `hours` ([] when the rule never ran).
 *   1 confirmed fault, 0 assessed and ok, null not assessed (a gap: the hook wrote nothing there). Never 0 for unknown.
 *   equip = OfddEquip / NF equip record (matches by NF equip uuid, else siteRef + equipRef) or a legacy id string.
 *   opts.windowSec: bucket (default: 300 s = the hook's grid up to 48 h, else 3600 s; MAX per bucket).
 * The array carries non-enumerable `source` ("timeline" | "fault_pct" | "none") and `approximate` (true for the
 * fault_pct fallback, whose 1 means "this hour had a run with fault time", not a confirmed timestamp).
 */
async function rcxFaultData(model, equip, ruleId, hours, opts = {}) {
  const sensorRef = opts.sensorRef == null ? null : opts.sensorRef;
  const tp = rcxTimelinePoint(model, equip, ruleId, sensorRef);
  if (tp) {
    const windowSec = opts.windowSec || (hours <= 48 ? 300 : 3600);
    const data = opts.range ? (await fetchRange([tp], opts.range, { method: "MAX", windowSec, minWindowSec: windowSec,
      siteTz: opts.siteTz || "UTC", preserveWindow: true })).series : await fetchSeries([tp], hours, { method: "MAX", windowSec });
    return rcxTagLane(rcxTimelineLane(data.get(tp.uuid) || [], windowSec), "timeline", false);
  }
  const p = sensorRef == null ? rcxResultPoint(model, equip, ruleId) : rcxResultPoint(model, equip, ruleId, sensorRef);
  if (!p) return rcxTagLane([], "none", false);
  const data = opts.range ? (await fetchRange([p], opts.range, { method: "MAX", windowSec: 3600, minWindowSec: 3600,
    siteTz: opts.siteTz || "UTC", preserveWindow: true })).series : await fetchSeries([p], hours, { method: "MAX", windowSec: 3600 });
  const samples = rcxCurrentOutputSeries(p, data.get(p.uuid) || [], 3600);
  return rcxTagLane(samples.map(([t, v]) => [t, v == null ? null : v > 0 ? 1 : 0]), "fault_pct", true);
}

/**
 * Append the bottom fault lane to an ECharts option built for one or more stacked grids.
 * Works with `grid`/`xAxis`/`yAxis` given as objects or arrays; signal grids are squeezed
 * to leave LANE_PX at the bottom, every x axis is linked (tooltip, zoom).
 *   lanes = [{ name: "ECON-1", data: [[ms, 0|1], …] }, …]   (several rules → several lanes)
 */
function rcxWithFaultLane(option, lanes) {
  // null samples (rcxFaultData: not assessed) stay gaps (connectNulls false); the fault_pct fallback
  // (data.approximate) is drawn dashed and the series is flagged `approximate`, so it never passes for a confirmed lane
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
    const approx = !!lane.data.approximate;
    series.push({ name: lane.name, type: "line", step: "end", showSymbol: false, connectNulls: false,
      xAxisIndex: xAxes.length - 1, yAxisIndex: yAxes.length - 1,
      lineStyle: approx ? { ...FAULT_LANE.lineStyle, type: "dashed" } : FAULT_LANE.lineStyle, areaStyle: FAULT_LANE.areaStyle,
      ...(approx ? { approximate: true } : {}), data: lane.data });
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
