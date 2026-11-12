// Read-only agent analytics tools for Open-FDD: one on-request hook, dispatched on args.tool.
//
//   POST /api/v1/apps/open-fdd/hooks/analytics   {"args": {"tool": "analyze_ahu_weekly_runtime", "site": "...", "days": 28}}
//   GET  /api/v1/apps/open-fdd/hooks/analytics/runs?include_results=true     -> the answer
//
// Tools (every row is keyed by equipUuid, with siteRef + equipRef next to it, so two sites that both have an "AHU-1"
// never share a row):
//   analyze_ahu_weekly_runtime  {site?, equip?, days=28}     per (siteRef, equipUuid) ISO week: run_hours, schedule_hours,
//                                                            in_schedule_hours, after_hours, partial_week, mean_oat_on_c,
//                                                            schedule_source / schedule_label (fine 300 s grid, chunked)
//   analyze_mechanical_cooling  {site?, equip?, days=28}     per equip hours in the six fixed SI OAT bins (fine grid)
//   analyze_economizer          {site?, equip?, days=7}      n, n_identifiable, median_residual_k, mae_k
//   get_fdd_fault_timeline      {site?, equip, rule, days=1, dense?}  confirmed | ok | unknown per assessed timestamp,
//                                                            from the FDD hook's timeline point (never fault_pct)
//   resolve_equipment_roles     {equipUuid} | {siteRef, equipRef}     the roles fdd.js binds for one equip
//   explain_missing_rcx_view    {viewId, site?, equip?}      why an RCx view is not available here
// `site` / `siteRef` and `equip` / `equipRef` / `equipUuid` are synonyms (equip matches an NF uuid first, then a Haystack
// id or name). A single-equip tool whose equip matches several sites is an ERROR listing the candidates, never a guess;
// the list tools simply return every matching equip, each under its own equipUuid.
//
// The math is the dashboard's: static/rcx.js + rcx-overview.js (+ schedule.js, fdd.js, model.js) run unchanged in a vm
// sandbox, the same way hooks/fdd.js shares model.js / fdd.js (browser fetchSeries -> sdk.http GET /api/v1/point/data).
// Numbers integrate on the fine grid (ctx.alignedFine), never on the ~360-point display grid.
//
// READ ONLY, enforced: every call goes through readOnlyHttp(), a proxy that lets GET and the read POSTs
// (/api/v1/point/query, /api/v1/auth/token) through and throws on every other method or route. The hook never writes
// points, schedules or BACnet values. The answer is the hook's return value and one sdk.logEvent line (JSON, capped).
//
// Nothing site-specific: sites, equips, points, schedules and units all come from NF.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const STATIC = path.join(__dirname, '..', 'static');
const { queryPoints } = require('./lib/paging.js');
const MAX_RESULT_CHARS = 200000;
const FINE_SEC = 300;                   // the pack grid: native cadence of the FDD timeline points
const FINE_MAX_SAMPLES = 9000;          // per series per request (NF caps at ~10000)
const MAX_DAYS = 366;
const SCRIPTS = ['units.js', 'model.js', 'fdd.js', 'schedule.js', 'charts.js', 'rcx.js', 'rcx-overview.js', 'rcx-presets.js', 'fdd-plots.js', 'energy.js'];
const READ_POSTS = new Set(['/api/v1/point/query', '/api/v1/auth/token']);
const COOLING_ROLES = ['compressor_status', 'chiller_status', 'chiller_cmd'];

/** A tool failure that is the caller's to fix (bad args, ambiguous equip): returned as { ok: false, error, ... }. */
class ToolError extends Error {
  /** @param {string} message @param {any} [extra] */
  constructor(message, extra) { super(message); this.extra = extra || {}; }
}

// ---- read-only HTTP ---------------------------------------------------------------------------------------------
const routeOf = (p) => String(p || '').split('?')[0].replace(/\/+$/, '');

/**
 * sdk.http restricted to reads: get() on /api/... routes, post() on the read routes only, everything else throws
 * (put / patch / delete / request / ... and any other POST). Returns a Proxy so a method added to sdk.http later is
 * blocked by default (allow-list, not deny-list).
 */
function readOnlyHttp(http) {
  const blocked = (what) => new ToolError(`read-only: ${what} is blocked in the analytics hook (GET and ${[...READ_POSTS].join(', ')} only)`);
  const allowed = {
    get: async (/** @type {any} */ p, /** @type {any[]} */ ...rest) => {
      if (!/^\/api\//.test(String(p))) throw blocked(`GET ${String(p).slice(0, 80)}`);
      return http.get(p, ...rest);
    },
    post: async (/** @type {any} */ p, /** @type {any[]} */ ...rest) => {
      if (!READ_POSTS.has(routeOf(p))) throw blocked(`POST ${routeOf(p)}`);
      return http.post(p, ...rest);
    },
  };
  return new Proxy(http, {
    get(target, prop) {
      if (prop === 'get' || prop === 'post') return allowed[prop];
      const v = target[prop];
      if (typeof v === 'function') return async () => { throw blocked(`sdk.http.${String(prop)}`); };
      return v;                                    // defaults / baseURL / plain data
    },
    set() { return false; },
  });
}

// ---- NF reads (same loader as hooks/sparql.js) ------------------------------------------------------------------------
// the shared pager (lib/paging.js): pageOffset + totalCount or a token, loud on a cap or short read (#1550)
const queryAll = (http, body) => queryPoints(http, body);

async function loadModel(http, g) {
  const recs = await queryAll(http, { layer: 'model' });
  const of = (t) => recs.filter((r) => r.pointType === t);
  const model = { sites: of('SITE'), equips: of('EQUIPMENT'), devices: of('DEVICE'), points: [] };
  for (const s of model.sites) {
    const pts = await queryAll(http, { layer: 'default', structuredQuery: { field: { property: 'siteRef', text: g('idOf')(s) } } });
    model.points.push(...pts.filter((r) => !g('ENTITY_TYPES').includes(r.pointType)).map(g('toPoint')));
  }
  return model;
}

// ---- the dashboard code in a sandbox ------------------------------------------------------------------------------------
/**
 * model.js, fdd.js, schedule.js, charts.js, rcx*.js ... in one vm context. `Date` is pinned to `nowMs` (the window end
 * is "now" for the browser code too, and the tests need a fixed clock); `api` is the browser's api() on the read-only http.
 */
function loadSandbox(http, nowMs, tzSources) {
  class PinnedDate extends Date {
    /** @param {any[]} a */
    constructor(...a) { super(.../** @type {[any]} */ (a.length ? a : [nowMs])); }
    static now() { return nowMs; }
  }
  const ctx = vm.createContext({
    console, URLSearchParams, TextDecoder, atob, btoa, Intl, Date: PinnedDate,
    localStorage: { getItem: () => 'si' },                  // calculations are SI whatever the display system
    api: async (p) => (await http.get(p)).data,
  });
  for (const f of SCRIPTS) vm.runInContext(fs.readFileSync(path.join(STATIC, f), 'utf8'), ctx, { filename: f });
  const g = (n) => vm.runInContext(n, ctx);
  // the dashboard's site-zone sources (#1587): the app option `timezone` and NF Sites, so weekly runtime evaluates the
  // schedule in the same zone the UI shows (model site tz still wins, inside resolveSiteTimeZone)
  if (tzSources) g('setSiteTimeZoneSources')(tzSources);
  g.catalog = JSON.parse(fs.readFileSync(path.join(STATIC, 'fdd-catalog.json'), 'utf8'));
  return g;
}

// ---- identity + scope -------------------------------------------------------------------------------------------------
const attrsOf = (r) => (r && r.attrs) || {};
const siteOfEquip = (r) => attrsOf(r).siteRef || '';

/** Who a row is about. `key` is the FDD hook's resultKey (equip:<uuid> | site:<siteRef>:<id>). */
function identity(g, rec) {
  const equipRef = g('idOf')(rec), siteRef = siteOfEquip(rec);
  return { siteRef, equipRef, equipUuid: rec.uuid || null, equipName: attrsOf(rec).dis || rec.name || equipRef,
    key: rec.uuid ? `equip:${rec.uuid}` : `site:${siteRef}:${equipRef}` };
}

/** Args: site / siteRef and equip / equipRef / equipUuid, normalized. */
function scopeOf(args) {
  const str = (v) => (v == null || v === '' ? '' : String(v));
  return { site: str(args.site ?? args.siteRef), equip: str(args.equipUuid || args.equip || args.equipRef), uuidOnly: !!args.equipUuid };
}

/** Site id a user-given site name / id stands for ('' = any). Throws on an unknown site. */
function siteId(g, model, site) {
  if (!site) return '';
  const hit = model.sites.find((s) => g('idOf')(s) === site || s.uuid === site || s.name === site || attrsOf(s).dis === site);
  if (!hit) throw new ToolError(`unknown site "${site}"`, { sites: model.sites.map((s) => g('idOf')(s)) });
  return g('idOf')(hit);
}

/** Equips matching the scope, each under its own uuid: [rec]. Throws on an unknown site; an empty list when nothing matches. */
function equipsInScope(g, model, scope) {
  const site = siteId(g, model, scope.site);
  const idOf = g('idOf');
  return model.equips.filter((e) => {
    if (site && siteOfEquip(e) !== site) return false;
    if (!scope.equip) return true;
    if (e.uuid === scope.equip) return true;
    if (scope.uuidOnly) return false;
    return idOf(e) === scope.equip || e.name === scope.equip || attrsOf(e).dis === scope.equip;
  });
}

/** Exactly one equip, or a ToolError (unknown, or several candidates: never a guess). */
function resolveOne(g, model, scope) {
  if (!scope.equip) throw new ToolError('equip is required (an NF uuid, or a Haystack id with site)');
  const hits = equipsInScope(g, model, scope);
  if (hits.length === 1) return hits[0];
  if (!hits.length) throw new ToolError(`no equip matches "${scope.equip}"${scope.site ? ` in site "${scope.site}"` : ''}`);
  throw new ToolError(`"${scope.equip}" matches ${hits.length} equips; pass equipUuid, or site + equip`, { candidates: hits.map((e) => identity(g, e)) });
}

const round = (v, d = 4) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v * 10 ** d) / 10 ** d : v);
const iso = (ms) => new Date(ms).toISOString();
const bySite = (recs) => { const m = new Map(); for (const r of recs) { const k = siteOfEquip(r); m.set(k, [...(m.get(k) || []), r]); } return m; };

function daysOf(args, dflt) {
  const d = args.days == null || args.days === '' ? dflt : Number(args.days);
  if (!(d > 0) || d > MAX_DAYS) throw new ToolError(`days must be a number in (0, ${MAX_DAYS}]`);
  return d;
}
const viewOf = (g, pred) => Array.from(g('RCX_VIEWS')).find(pred);

/** Local-Monday label "YYYY-Www" for a week start (the week key of weeklyRuntime). */
function weekLabel(g, startMs, tz) {
  const S = g('ofddSchedule'), M = g('rcxOverviewMath');
  const p = tz ? S.localParts(startMs + 6 * 3600e3, tz) : null;           // noon-ish: the civil date of that Monday
  return M.isoWeekLabel(p ? Date.UTC(p.y, p.m - 1, p.d, 12) : startMs);
}

// ---- tools ----------------------------------------------------------------------------------------------------------
const ctxFor = (g, view, bound, hours, model) => g('rcxContext')(view, bound, hours, model, g.catalog);

async function analyze_ahu_weekly_runtime(sb, args) {
  const { g, model, now } = sb;
  const days = daysOf(args, 28), hours = days * 24;
  const equips = equipsInScope(g, model, scopeOf(args));
  const status = viewOf(g, (v) => v.id === 'weekly-fan'), cmd = viewOf(g, (v) => v.id === 'weekly-fan-cmd');
  const D = g('rcxOverviewMath').data, S = g('ofddSchedule');
  const rows = [];
  for (const [, list] of bySite(equips)) {
    const withStatus = g('rcxBind')(status, list, model, g.catalog);
    const seen = new Set(withStatus.map((e) => e.rec.uuid || e.id));
    // an equip with a fan status is counted by it; the command only counts equips that lack one (no equip twice)
    const withCmd = g('rcxBind')(cmd, list, model, g.catalog).filter((e) => !seen.has(e.rec.uuid || e.id));
    for (const [view, bound, role] of [[status, withStatus, 'fan_status'], [cmd, withCmd, 'fan_cmd']]) {
      if (!bound.length) continue;
      const { perEq } = await D.weeklyData(ctxFor(g, view, bound, hours, model), bound, role);
      for (const p of perEq) {
        for (const [k, w] of p.weeks) {
          const info = p.site ? S.weeklyScheduleInfo(p.site.schedule, k, p.site.tz) : null;
          rows.push({
            ...identity(g, p.eq.rec), signal_role: role, tz: (p.site && p.site.tz) || 'UTC',
            week_start: iso(k), week: weekLabel(g, k, p.site && p.site.tz),
            run_hours: round(w.hours), schedule_hours: info ? info.hours : null,
            in_schedule_hours: round(w.inHours), after_hours: round(w.afterHours),
            partial_week: !!w.partial, mean_oat_on_c: round(w.oat, 2), samples: w.n,
            schedule_source: info ? info.source : null, schedule_label: info ? info.label : null,
          });
        }
      }
    }
  }
  rows.sort((a, b) => a.siteRef.localeCompare(b.siteRef) || a.equipRef.localeCompare(b.equipRef) || String(a.equipUuid).localeCompare(String(b.equipUuid)) || a.week_start.localeCompare(b.week_start));
  return { days, grid_s: FINE_SEC, to: iso(Math.ceil(now / (FINE_SEC * 1e3)) * FINE_SEC * 1e3), rows };
}

async function analyze_mechanical_cooling(sb, args) {
  const { g, model, now } = sb;
  const days = daysOf(args, 28), hours = days * 24;
  const equips = equipsInScope(g, model, scopeOf(args));
  const M = g('rcxOverviewMath'), D = M.data;
  const edges = M.oatEdges();
  const rows = [];
  for (const role of COOLING_ROLES) {
    const view = viewOf(g, (v) => v.id.startsWith('mech-cooling') && v.roles.required[0] === role);
    if (!view) continue;
    for (const [, list] of bySite(equips)) {
      const bound = g('rcxBind')(view, list, model, g.catalog);
      if (!bound.length) continue;
      const res = await D.mechData(ctxFor(g, view, bound, hours, model), role);
      for (const p of res.per) {
        const h = p.bins.hours;
        rows.push({
          ...identity(g, p.eq.rec), signal_role: role, oat_source: res.wx ? 'weather' : 'equip',
          bins: p.bins.labels.map((label, i) => ({ label, from_c: i ? round(edges[i - 1], 3) : null, to_c: i < edges.length ? round(edges[i], 3) : null, hours: round(h[i]) })),
          total_hours: round(h.reduce((a, b) => a + b, 0)),
        });
      }
      if (res.error && !res.per.length) rows.push(...bound.map((e) => ({ ...identity(g, e.rec), signal_role: role, error: res.error })));
    }
  }
  rows.sort((a, b) => a.siteRef.localeCompare(b.siteRef) || a.equipRef.localeCompare(b.equipRef) || String(a.equipUuid).localeCompare(String(b.equipUuid)) || a.signal_role.localeCompare(b.signal_role));
  return { days, grid_s: FINE_SEC, edges_c: edges.map((e) => round(e, 3)), to: iso(Math.ceil(now / (FINE_SEC * 1e3)) * FINE_SEC * 1e3), rows };
}

async function analyze_economizer(sb, args) {
  const { g, model, now } = sb;
  const days = daysOf(args, 7), hours = days * 24;
  const equips = equipsInScope(g, model, scopeOf(args));
  const view = viewOf(g, (v) => v.id === 'economizer-delta');
  const M = g('rcxOverviewMath'), D = M.data;
  const rows = [];
  for (const [, list] of bySite(equips)) {
    const bound = g('rcxBind')(view, list, model, g.catalog);
    if (!bound.length) continue;
    const ctx = ctxFor(g, view, bound, hours, model);
    for (const eq of bound) {
      const { rows: samples } = await D.econGrid(ctx, eq, true);      // fine grid
      const s = M.economizerSummary(samples);
      rows.push({ ...identity(g, eq.rec), n: s.n, n_identifiable: s.nIdent, median_residual_k: round(s.medianResid), mae_k: round(s.maeResid),
        has_damper: !!ctx.first(eq, 'oa_damper_pct'), min_delta_k: round(M.ECON_DT_MIN_C, 4) });
    }
  }
  rows.sort((a, b) => a.siteRef.localeCompare(b.siteRef) || a.equipRef.localeCompare(b.equipRef) || String(a.equipUuid).localeCompare(String(b.equipUuid)));
  return { days, grid_s: FINE_SEC, to: iso(Math.ceil(now / (FINE_SEC * 1e3)) * FINE_SEC * 1e3), rows };
}

const STATE = { 1: 'confirmed', 0: 'ok' };

async function get_fdd_fault_timeline(sb, args) {
  const { g, model, now } = sb;
  const rule = String(args.rule || '').trim();
  if (!rule) throw new ToolError('rule is required (an Open-FDD rule id, e.g. "ECON-1")');
  const days = daysOf(args, 1), hours = days * 24;
  const rec = resolveOne(g, model, scopeOf(args));
  const tp = g('rcxTimelinePoint')(model, rec, rule);
  let lane, source, approximate;
  if (tp) {
    // 5-minute MAX windows (the hook's grid), long spans walked back in chunks like ctx.alignedFine
    const perChunk = Math.max(1, Math.floor((FINE_MAX_SAMPLES * FINE_SEC) / 3600));
    const end = Math.ceil(now / (FINE_SEC * 1e3)) * FINE_SEC * 1e3, fetchSeries = g('fetchSeries');
    const merged = new Map();
    for (let done = 0; done < hours; done += perChunk) {
      const part = await fetchSeries([tp], Math.min(perChunk, hours - done), { method: 'MAX', windowSec: FINE_SEC, endMs: end - done * 3600e3 });
      for (const [t, v] of part.get(tp.uuid) || []) merged.set(t, v);
    }
    lane = Array.from(g('rcxTimelineLane')([...merged].sort((a, b) => a[0] - b[0]), FINE_SEC), (x) => [x[0], x[1]]);
    source = 'timeline'; approximate = false;
  } else {
    const r = await g('rcxFaultData')(model, rec, rule, hours);        // fault_pct fallback: approximate, hourly
    lane = Array.from(r, (x) => [x[0], x[1]]);
    source = r.source; approximate = !!r.approximate;
  }
  const states = lane.map(([t, v]) => ({ ts: iso(t), state: v == null ? 'unknown' : STATE[v] }));
  const count = (s) => states.filter((x) => x.state === s).length;
  const confirmed = states.filter((x) => x.state === 'confirmed');
  // default: state changes only (an entry holds until the next one); dense: every sample, unknown markers included
  const timeline = args.dense ? states : states.filter((x, i) => i === 0 || x.state !== states[i - 1].state);
  return {
    ...identity(g, rec), rule, source, approximate, days, step_s: source === 'timeline' ? FINE_SEC : 3600, dense: !!args.dense,
    to: iso(Math.ceil(now / (FINE_SEC * 1e3)) * FINE_SEC * 1e3),
    summary: { samples: states.length, confirmed: count('confirmed'), ok: count('ok'), unknown: count('unknown'),
      first_confirmed: confirmed.length ? confirmed[0].ts : null, last_confirmed: confirmed.length ? confirmed[confirmed.length - 1].ts : null,
      last_state: states.length ? states[states.length - 1].state : null },
    timeline,
  };
}

async function resolve_equipment_roles(sb, args) {
  const { g, model } = sb;
  const rec = resolveOne(g, model, scopeOf(args));
  const catalog = g.catalog;
  const bound = g('bindRoles')(Object.keys(catalog.roles), g('equipPool')(rec, model), catalog);
  const roles = {};
  for (const [role, pts] of Object.entries(bound)) {
    if (!pts || !pts.length) continue;
    roles[role] = pts.map((p) => ({ uuid: p.uuid, dis: p.dis, units: p.units, kind: p.kind, class: p.cls, equipRef: p.equipRef, siteRef: p.siteRef }));
  }
  const rules = g('equipRules')(rec, model, catalog);
  return { ...identity(g, rec), kinds: g('equipKinds')(rec, catalog), roles, roles_bound: Object.keys(roles).length,
    runnable_rules: rules.filter((r) => r.runnable).map((r) => r.rule.id), not_runnable_rules: rules.filter((r) => !r.runnable).length };
}

async function explain_missing_rcx_view(sb, args) {
  const { g, model } = sb;
  const viewId = String(args.viewId || args.view || '').trim();
  const views = Array.from(g('RCX_VIEWS'));
  if (!viewId) throw new ToolError('viewId is required', { views: views.map((v) => v.id) });
  const view = views.find((v) => v.id === viewId);
  if (!view) throw new ToolError(`unknown view "${viewId}"`, { views: views.map((v) => v.id) });
  const equips = equipsInScope(g, model, scopeOf(args));
  const catalog = g.catalog, req = view.roles.required, opt = view.roles.optional;
  const per = equips.map((rec) => {
    const kinds = g('equipKinds')(rec, catalog);
    const bound = g('bindRoles')([...req, ...opt], g('equipPool')(rec, model), catalog);
    const kindOk = !view.kinds.length || view.kinds.some((k) => kinds.includes(k));
    const missing = req.filter((r) => !(bound[r] && bound[r].length));
    return { rec, kinds, bound, kindOk, missing, status: !kindOk ? 'kind_mismatch' : missing.length ? 'missing_roles' : 'ready', noData: /** @type {string[]} */ ([]) };
  });
  // "no data": the roles are bound but the required points have no history in the view's span
  const ready = per.filter((p) => p.status === 'ready');
  if (ready.length && args.checkData !== false) {
    const pts = [...new Map(ready.flatMap((p) => req.map((r) => p.bound[r][0])).map((p) => [p.uuid, p])).values()];
    const hours = view.hours || 168;
    const data = await g('fetchSeries')(pts, hours, { method: 'AVERAGE', windowSec: Math.max(3600, g('pickWindow')(hours)) });
    for (const p of ready) {
      p.noData = req.filter((r) => !(data.get(p.bound[r][0].uuid) || []).length);
      if (p.noData.length) p.status = 'no_data';
    }
  }
  const plan = g('rcxPlan')(equips, model, catalog);
  const missingEntry = plan.missing.find((m) => m.view.id === view.id);
  const readyCount = per.filter((p) => p.status === 'ready').length, need = view.scope === 'site' ? view.minEquips : 1;
  const available = readyCount >= need;
  const reasons = [];
  if (!equips.length) reasons.push('no equip in scope');
  const n = (s) => per.filter((p) => p.status === s).length;
  if (n('kind_mismatch')) reasons.push(`${n('kind_mismatch')} equip(s) are not of kind ${view.kinds.join('/')}`);
  if (n('missing_roles')) reasons.push(`${n('missing_roles')} equip(s) lack required role(s): ${[...new Set(per.filter((p) => p.status === 'missing_roles').flatMap((p) => p.missing))].join(', ')}`);
  if (n('no_data')) reasons.push(`${n('no_data')} equip(s) have the roles bound but no history in the last ${view.hours || 168} h`);
  if (equips.length && !available && !reasons.length) reasons.push(`needs at least ${need} ready equip(s), found ${readyCount}`);
  if (equips.length && !available && readyCount && readyCount < need) reasons.push(`this site-scope view needs at least ${need} ready equips, found ${readyCount}`);
  return {
    view: { id: view.id, title: view.title, group: view.group, scope: view.scope, kinds: view.kinds, roles: { required: req, optional: opt }, minEquips: view.minEquips, hours: view.hours },
    available, missing_roles: missingEntry ? missingEntry.roles : [], reasons,
    equips: per.map((p) => ({ ...identity(g, p.rec), status: p.status, kinds: p.kinds, missing_roles: p.missing, no_data_roles: p.noData,
      bound_roles: Object.keys(p.bound).filter((r) => p.bound[r] && p.bound[r].length) })),
  };
}

const TOOLS = { analyze_ahu_weekly_runtime, analyze_mechanical_cooling, analyze_economizer, get_fdd_fault_timeline, resolve_equipment_roles, explain_missing_rcx_view };

// ---- hook ------------------------------------------------------------------------------------------------------------
const errText = (e) => (e && (e.message || (e.response && JSON.stringify(e.response.data)))) || String(e);
const startArgs = require('./lib/start-hook-args.js');
const settings = require('./lib/settings.js');
const siteTz = require('./lib/site-timezone.js');

/** Hook arguments: NF passes the StartHook "args" object; accept the common spots (same as sparql.js). */
const argsOf = (ctx) => {
  return startArgs.startHookArgs(ctx, { configFallback: true, numberFields: ['days'], booleanFields: ['dense', 'checkData'] });
};

/** Keep the answer under the cap: shorten the longest list (rows / timeline / equips) and say so. */
function capResult(result) {
  let text = JSON.stringify(result);
  if (text.length <= MAX_RESULT_CHARS) return { result, text };
  const key = ['rows', 'timeline', 'equips'].filter((k) => Array.isArray(result[k])).sort((a, b) => result[b].length - result[a].length)[0];
  if (!key) return { result: { ok: result.ok, tool: result.tool, truncated: true, note: `answer larger than ${MAX_RESULT_CHARS} characters` }, text: '' };
  const total = result[key].length;
  // a timeline keeps its NEWEST entries (what happened lately); lists keep their head
  const cut = (n) => ({ ...result, [key]: key === 'timeline' ? result[key].slice(-n) : result[key].slice(0, n), truncated: true, [`${key}_total`]: total });
  let keep = total, out = result;
  while (keep > 1 && text.length > MAX_RESULT_CHARS) {
    keep = Math.floor(keep / 2);
    out = cut(keep);
    text = JSON.stringify(out);
  }
  return { result: out, text };
}

/** @param {{sdk: any, args?: any, config?: any, now?: () => number}} o */
async function handle({ sdk, args = {}, config = {}, now = () => Date.now() }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const t0 = now();
  const tool = String((args && args.tool) || '');
  let result;
  try {
    if (!Object.prototype.hasOwnProperty.call(TOOLS, tool)) throw new ToolError(`args.tool must be one of ${Object.keys(TOOLS).join(', ')}`);
    const http = readOnlyHttp(sdk.http);
    const nowMs = now();
    const cfg = settings.normalizeConfig(config);
    const nfSites = (await siteTz.loadNfSites(http)).sites;
    const g = loadSandbox(http, nowMs, { appOption: siteTz.knownZone(siteTz.optionOf(cfg)), sites: nfSites, weatherOff: !settings.weatherEnabled(cfg) });
    const model = await loadModel(http, g);
    const out = await TOOLS[tool]({ g, model, http, now: nowMs }, args);
    result = { ok: true, tool, ms: now() - t0, ...out };
  } catch (e) {
    result = { ok: false, tool, ms: now() - t0, error: errText(e), ...(e instanceof ToolError ? e.extra : {}) };
  }
  const capped = capResult(result);
  const text = capped.text || JSON.stringify(capped.result);
  log(text);
  return JSON.parse(text);          // plain host-realm JSON (the sandbox's arrays / objects are normalized away)
}

// The hook is the function; the helpers hang off it for the tests (assigned in one go so tsc sees the shape).
module.exports = Object.assign(
  async (ctx) => handle({ sdk: ctx.sdk, args: argsOf(ctx), config: ctx.config }),
  { handle, readOnlyHttp, argsOf, TOOLS, ToolError, loadSandbox, loadModel, resolveOne, equipsInScope },
);
