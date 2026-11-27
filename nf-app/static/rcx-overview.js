// Overview RCx views for the Open-FDD NF app (port of archive central-v4 overview-rcx-charts.js).
//
// #1649: the analytics are SQL, never JS math. Weekly / daily run hours, mechanical-cooling OAT bins, the economizer
// points and metrics and BAS vs web outdoor air are sql/analytics/*.sql (parity-tested against pandas on SQLite,
// DuckDB and PostgreSQL), reached through ctx.sqlAnalytics: in the analytics hook it runs in-process (sql.js), in the
// browser static/sql-analytics-client.js sends the aligned grid to that hook. This file builds the grids, draws the
// charts and maps SI to the display system (ctx.disp / ctx.dispDelta) only for charts and notes.
// Hours integrate on the FINE grid (ctx.alignedFine, 300 s window), never on the ~360-point display grid: a coarse
// AVERAGE bucket smears a short pulse or hides a short cooling event. Nothing site-specific: equips, roles and units
// all come from NF + fdd-catalog.json. Display constants kept for captions: ON (0.05) and ECON_DT_MIN_C (50/9 delta
// degC), the same values the SQL uses.
// Needs rcx.js (rcxView, rcxStats, rcxFaultData, rcxWithFaultLane), model.js (has),
// charts.js (pickWindow), theme.js (ofddRender).
(function () {
  "use strict";

  const ON = 0.05;                      // on-threshold on a 0-1 command/status fraction
  const ECON_DT_MIN_C = 50 / 9;         // |OAT-RAT| (delta degC) for an identifiable economizer sample
  const OAT_EDGES_C = [10, 15.555555555555556, 21.11111111111111, 26.666666666666668, 32.22222222222222];
  const WEEK_MS = 7 * 86400e3;
  const isNum = (x) => x != null && Number.isFinite(x);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ================= pure math (globalThis.rcxOverviewMath) =============================

  /** Monday 00:00 UTC of the ISO week containing ms (central's date_trunc('week')). */
  function weekStart(ms) {
    const d = new Date(ms);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  }

  /** "2026-W45" for the ISO week containing ms (central's to_char IYYY-"W"IW). */
  function isoWeekLabel(ms) {
    const thu = new Date(weekStart(ms) + 3 * 86400e3);
    const y = thu.getUTCFullYear();
    const wk = Math.floor((thu.getTime() - Date.UTC(y, 0, 1)) / 86400e3 / 7) + 1;
    return `${y}-W${String(wk).padStart(2, "0")}`;
  }

  /** Bin edges in degC (50/60/70/80/90 degF). */
  const oatEdges = () => OAT_EDGES_C.slice();
  /**
   * Bin labels, lowest to highest, edges shown through `toDisp` (degC -> display number; default
   * identity = degC): "<10", "10-16", ... ">=32" in degC, "<50", "50-60", ... in degF.
   */
  function oatBinLabels(toDisp = (c) => c) {
    const e = oatEdges().map((x) => Math.round(toDisp(x)));
    return [`<${e[0]}`, ...e.slice(1).map((x, i) => `${e[i]}-${x}`), `>=${e[e.length - 1]}`];
  }

  /** Histogram of deltas, contiguous bins of `width`, ends clamped at +-maxBins bins. */
  function deltaHist(ds, width, maxBins = 20) {
    const idx = ds.filter(isNum).map((d) => Math.max(-maxBins, Math.min(maxBins, Math.floor(d / width))));
    if (!idx.length) return { labels: [], counts: [] };
    const lo = Math.min(...idx), hi = Math.max(...idx), counts = new Array(hi - lo + 1).fill(0);
    for (const i of idx) counts[i - lo]++;
    const dec = width < 1 ? 1 : 0;
    return { labels: counts.map((_, k) => ((lo + k) * width).toFixed(dec)), counts };
  }

  /**
   * OR several equips' fault lanes into one: [[ms, 1|0|null]]. 1 if any equip is 1, else 0 if any is 0, else null
   * (not assessed stays a gap, it is never turned into ok). The result is approximate when any input lane was.
   */
  function mergeFaultLanes(arrays) {
    const m = new Map();
    for (const a of arrays) for (const [t, v] of a || []) {
      const cur = m.has(t) ? m.get(t) : null;
      m.set(t, v == null ? cur : cur == null ? v : Math.max(cur, v));
    }
    const out = [...m].sort((a, b) => a[0] - b[0]);
    return arrays.some((a) => a && a.approximate) ? Object.defineProperty(out, "approximate", { value: true }) : out;
  }

  globalThis.rcxOverviewMath = {
    weekStart, isoWeekLabel, oatEdges, oatBinLabels, deltaHist, mergeFaultLanes, ECON_DT_MIN_C, ON,
  };
  const M = globalThis.rcxOverviewMath;
  // Data entry points (no drawing) for the agent analytics hook (hooks/analytics.js); the views above use the same ones.
  M.data = { weeklyData, mechData, econGrid, siteSchedules, weekIndexer, weatherOat };

  // ================= view helpers ======================================================

  const TEMP = "°C";                    // SI unit of every temperature in this file
  const eqName = (eq) => eq.name;
  const nan = (x) => (isNum(x) ? x : null);

  /** Site weather outdoor-air temperature point (unique one, like the SQL), else null. */
  function weatherOat(ctx) {
    const w = ctx.weather.filter((p) => has(p, "temp") && has(p, "outside"));
    return w.length === 1 ? w[0] : null;
  }

  /** Fault lanes for rules: one lane per rule, any equip in fault; none when no result point exists. */
  async function faultLanes(ctx, rules, eqs) {
    const lanes = [];
    for (const rule of rules) {
      const arrays = await Promise.all(eqs.map((eq) => rcxFaultData(ctx.model, eq, rule, ctx.hours,
        { range: ctx.range, siteTz: ctx.siteTz })));
      const data = M.mergeFaultLanes(arrays);
      if (data.length) lanes.push({ name: rule, data });
    }
    return lanes;
  }

  const baseGrid = (extra = {}) => ({ left: 56, right: 24, top: 36, bottom: 48, ...extra });
  const draw = (ctx, el, option, lanes, name) => {
    const chart = ctx.chart(el);
    ofddRender(chart, lanes && lanes.length ? rcxWithFaultLane(option, lanes) : option, name);
  };
  const lineS = (name, data, extra = {}) => ({ name, type: "line", showSymbol: false, connectNulls: false,
    lineStyle: { width: 1.4 }, data, ...extra });
  const plainItemTip = (fmt) => ({ trigger: "item", formatter: (p) => esc(fmt(p)) });

  // ================= weekly motor runtime ==============================================

  // One entry per motor family. `signals` = roles by preference (status wins over command, as in
  // motor_weekly_runtime.sql). A view requires one signal; the later-signal view only draws
  // equips that lack the preferred one, so no equip is counted twice.
  const MOTORS = [
    { id: "fan", title: "AHU supply fans", group: "Air handlers", kinds: ["ahu"], signals: ["fan_status", "fan_cmd"], faults: ["SCHED-247"] },
    { id: "pump", title: "Pumps", group: "Plant", kinds: ["boiler", "chwPlant", "chiller"], signals: ["pump_status"] },
    { id: "chw-pump", title: "Chilled-water pumps", group: "Plant", kinds: ["chiller", "chwPlant"], signals: ["chw_pump_status", "chw_pump_cmd"] },
    { id: "cw-pump", title: "Condenser-water pumps", group: "Plant", kinds: ["chiller", "chwPlant", "cooling_tower"], signals: ["cw_pump_cmd"] },
    { id: "compressor", title: "Compressors", group: "Plant", kinds: [], signals: ["compressor_status"] },
    { id: "chiller", title: "Chillers", group: "Plant", kinds: ["chiller", "chwPlant"], signals: ["chiller_status", "chiller_cmd"] },
    { id: "tower-fan", title: "Cooling-tower fans", group: "Plant", kinds: ["cooling_tower", "chiller", "chwPlant"], signals: ["tower_fan_cmd"] },
  ];

  // ---- schedules for the weekly views (read only; schedule.js = ofddSchedule) ----------------
  const sched = () => globalThis.ofddSchedule || null;
  const siteOf = (eq) => (eq.rec && eq.rec.attrs && eq.rec.attrs.siteRef) || "";
  const AFTER_HOURS_DECAL = { symbol: "rect", dashArrayX: [1, 0], dashArrayY: [2, 3], rotation: Math.PI / 4, color: "rgba(127,127,127,0.65)" };

  /** ISO-week start function: Monday 00:00 in `tz` (cached per week, so 8000 samples cost a handful of Intl calls); UTC Monday without a tz. */
  function weekIndexer(tz) {
    const S = sched();
    if (!tz || !S) return weekStart;
    let lo = Infinity, hi = -Infinity, cur = 0;
    return (ms) => {
      if (ms >= lo && ms < hi) return cur;
      cur = S.localWeekStartMs(ms, tz);
      lo = cur; hi = S.localWeekStartMs(cur + 8 * 86400e3, tz);   // next local Monday (a DST week is 167 or 169 h)
      return cur;
    };
  }

  /** The site's zone: model tz, else the app option / NF Sites zone when the page loaded them (#1584), else null. */
  function siteZone(rec) {
    const own = (rec && rec.attrs && (rec.attrs.tz || rec.attrs.timezone)) || null;
    if (own || typeof resolveSiteTimeZone !== "function") return own;
    const r = resolveSiteTimeZone(rec, { browser: false, register: false });
    return r.source === "none" ? null : r.zone;
  }

  /**
   * Per siteRef of the given equips: { siteRef, schedule, tz, weekOf, occ } with the schedule NF binds to
   * the site's occupancy point (else the 4.x default 50 h/week calendar), loaded once. Empty Map when
   * schedule.js is not loaded (the view then draws no schedule split).
   */
  async function siteSchedules(ctx, eqs) {
    const S = sched(), out = new Map();
    if (!S) return out;
    let schedules = [];
    try { if (typeof api === "function") schedules = await S.loadSchedules(api); } catch (e) { schedules = []; }
    const O = occ();
    for (const ref of new Set(eqs.map(siteOf))) {
      const rec = ((ctx.model && ctx.model.sites) || []).find((r) => ((r.attrs && r.attrs.id) || r.name) === ref);
      const tz = siteZone(rec);
      // 5.0.20: the site's occupancy calendar (saved on the Overview, or the draft being edited) comes first; without
      // one, unchanged: an NF schedule bound to the site, else the 4.x default (the FDD hook's occ_mode uses the same).
      const cal = O && occCalendarOf(ref);
      const schedule = cal ? O.calendarSchedule(cal) : S.pickSiteSchedule(schedules, ctx.model, ref) || S.defaultSchedule(tz);
      const zone = schedule.tz || tz || null;
      out.set(ref, { siteRef: ref, schedule, tz: zone, weekOf: weekIndexer(zone), occ: (ms) => S.occupied(schedule, ms, zone) });
    }
    return out;
  }

  /**
   * Weekly runtime per equip on the FINE grid (shared by the chart and the agent analytics hook): { perEq, sites }.
   * perEq = [{ eq, site, role, weeks: Map(weekStartMs -> SQL runtime row: hours, inHours, afterHours, oat, n, partial) }], sites = Map(siteRef -> schedule info).
   * Hours integrate on the fine grid (alignedFine), schedules are read once per call (read only).
   */
  async function weeklyData(ctx, eqs, role) {
    const wx = weatherOat(ctx);
    const cols = {};
    eqs.forEach((eq, i) => { cols[`m${i}`] = ctx.first(eq, role); cols[`o${i}`] = wx || ctx.first(eq, "oa_t"); });   // one OAT policy: weather first, else the equip oa_t
    const [g, sites] = await Promise.all([ctx.alignedFine(cols, { hours: ctx.hours }), siteSchedules(ctx, eqs)]);
    // #1649: the run hours are the SQL analytic (sql/analytics/motor_weekly_runtime.sql), not JS math
    if (!ctx.sqlAnalytics) throw new Error("SQL analytics engine unavailable (ctx.sqlAnalytics)");
    const specs = eqs.map((eq, i) => {
      const site = sites.get(siteOf(eq));
      return { key: i, motor: `m${i}`, oat: `o${i}`, weekOf: site && site.weekOf, occ: site && site.occ };
    });
    const byEq = await ctx.sqlAnalytics.runtime(g, specs);
    const perEq = eqs.map((eq, i) => ({ eq, site: sites.get(siteOf(eq)), role, weeks: byEq.get(i) || new Map() }));
    return { perEq, sites };
  }

  // ---- occupancy calendar (static/occupancy.js = ofddOccupancy) -------------------------------------------------------
  const occ = () => globalThis.ofddOccupancy || null;
  /** The calendar the page (or the analytics hook) set for a site: globalThis.ofddOccCalendars[siteRef], else null. */
  function occCalendarOf(siteRef) {
    const all = globalThis.ofddOccCalendars;
    const c = all && (all instanceof Map ? all.get(siteRef) : all[siteRef]);
    return c && typeof c === "object" ? c : null;
  }
  /** Bare-minimum occupied hours per week of a site entry: its schedule's nominal week (calendar, NF schedule or default). */
  const bareMinOf = (site) => (site && site.schedule && Number.isFinite(site.schedule.hoursPerWeek) ? site.schedule.hoursPerWeek : null);
  M.bareMinOf = bareMinOf;
  M.occCalendarOf = occCalendarOf;

  // The reference line is the occupancy calendar's bare-minimum hours (edited on the Overview, saved per site); the old
  // per-browser min-run override box is gone (5.0.20): one setter, shared by every chart, export and the analytics hook.
  const DEFAULT_MIN_RUN_HOURS = 50;                 // the 4.x default schedule (no calendar saved, no NF schedule)

  /** The reference hours for week k: the first site's schedule week (calendar = bare-min), else the default. */
  function refAt(refs, k, def) {
    for (const r of refs) if (r.weeks && r.weeks.has(k)) return r.weeks.get(k);
    return def;
  }

  async function renderWeekly(el, ctx, motor, role) {
    const preferred = motor.signals.slice(0, motor.signals.indexOf(role));
    const eqs = ctx.equips.filter((eq) => !preferred.some((r) => ctx.first(eq, r)));
    if (!eqs.length) return `every equip here is counted by the ${preferred.join("/")} view`;
    const { perEq, sites } = await weeklyData(ctx, eqs, role);
    const starts = [...new Set(perEq.flatMap((p) => [...p.weeks.keys()]))].sort((a, b) => a - b);
    if (!starts.length || !perEq.some((p) => [...p.weeks.values()].some((w) => w.hours > 0))) return "no running time in this window";
    const partial = new Set(starts.filter((k) => perEq.every((p) => !p.weeks.has(k) || p.weeks.get(k).partial)));
    // One stack per equip: solid = in-schedule run hours, hatched = after-hours run hours (total = both).
    const pal = typeof palette === "function" ? palette() : null;
    const series = perEq.flatMap((p, i) => {
      const color = pal ? { color: pal[i % pal.length] } : {};
      // hours are kept unrounded (agents / exports read the option); the tooltip formats them
      const bars = (pick) => starts.filter((k) => p.weeks.has(k)).map((k) => [k, pick(p.weeks.get(k))]);
      // two sites can both have an "AHU-1": the legend must tell them apart
      const name = sites.size > 1 ? `${eqName(p.eq)} · ${siteOf(p.eq)}` : eqName(p.eq);
      if (!p.site) return [{ name, type: "bar", data: bars((w) => w.hours) }];
      return [
        { name, type: "bar", stack: `eq${i}`, itemStyle: color, data: bars((w) => w.inHours) },
        { name: `${name} (after hours)`, type: "bar", stack: `eq${i}`, itemStyle: { ...color, decal: AFTER_HOURS_DECAL }, data: bars((w) => w.afterHours) },
      ];
    });
    // Schedule reference: hours per ISO week as a step line (holiday weeks step down), one per site. This is the default
    // min-run-hours (bare-minimum occupied hours per week): the site schedule's hours, else the 50 h/week calendar.
    const S = sched(), refs = [];
    let defaultMin = DEFAULT_MIN_RUN_HOURS;
    if (S) {
      for (const site of new Set(perEq.map((p) => p.site).filter(Boolean))) {
        const ks = [...new Set(perEq.filter((p) => p.site === site).flatMap((p) => [...p.weeks.keys()]))].sort((a, b) => a - b);
        if (!ks.length) continue;
        const infos = ks.map((k) => S.weeklyScheduleInfo(site.schedule, k, site.tz));
        const end = site.tz ? S.localWeekStartMs(ks[ks.length - 1] + 8 * 86400e3, site.tz) : ks[ks.length - 1] + WEEK_MS;
        const label = infos[0].label + (sites.size > 1 ? ` · ${site.siteRef}` : "");
        if (!refs.length) defaultMin = infos[0].hours;
        refs.push({ site, label, end, weeks: new Map(ks.map((k, i) => [k, infos[i].hours])) });
        series.push({ id: `schedule-ref:${site.siteRef}`, name: label, type: "line", step: "end", showSymbol: false, z: 5,
          lineStyle: { width: 2, type: "dashed" }, data: [...ks.map((k, i) => [k, infos[i].hours]), [end, infos[infos.length - 1].hours]] });
      }
    }
    const xEnd = Math.max(starts[starts.length - 1] + WEEK_MS, ...refs.map((r) => r.end));
    const bareMin = bareMinOf(perEq[0].site);
    if (motor.id === "fan" && ctx.kpi) {
      const full = perEq.flatMap((p) => [...p.weeks.values()].filter((w) => !w.partial).map((w) => w.hours));
      if (full.length) ctx.kpi({ id: "ahu-run-hours-week", label: "AHU run hours / week", value: `${(full.reduce((x, y) => x + y, 0) / full.length).toFixed(1)} h`,
        sub: `bare-min occupied ${+defaultMin.toFixed(1)} h/week`, order: 40 });
    }
    // mean OAT while on: averaged in degC, shown in the display system
    const oatMeans = ctx.dispSeries(starts.map((k) => [k, rcxStats.mean(perEq.map((p) => p.weeks.get(k)?.oat))]).filter(([, v]) => v != null), TEMP)
      .map(([k, v]) => [k, +v.toFixed(1)]);
    const oatUnit = ctx.dispUnit(TEMP);
    if (oatMeans.length) {
      series.push(lineS(`Avg OAT ${oatUnit}`, oatMeans, { yAxisIndex: 1, showSymbol: true, symbolSize: 7,
        lineStyle: { width: 2, type: "dotted" } }));
    }
    const xMin = starts[0], xMax = xEnd;
    const tzs = [...new Set([...sites.values()].map((s) => s.tz || "UTC"))], tzLabel = tzs.length <= 1 ? tzs[0] || "UTC" : "site local";
    const option = {
      title: { text: `${motor.title}: weekly runtime`, left: 8, top: 0 },
      tooltip: { trigger: "axis", valueFormatter: (v) => (isNum(v) ? String(+v.toFixed(2)) : "") }, legend: { top: 24, type: "scroll", formatter: (n) => (n.length > 30 ? `${n.slice(0, 28)}…` : n) },
      grid: baseGrid({ top: 80, bottom: 44, right: oatMeans.length ? 56 : 24 }),
      xAxis: { type: "time", min: xMin, max: xMax, name: `week of (${tzLabel})`, nameLocation: "middle", nameGap: 28 },
      yAxis: [{ type: "value", name: "Run hours" },
        ...(oatMeans.length ? [{ type: "value", name: oatUnit, position: "right", scale: true, splitLine: { show: false } }] : [])],
      series,
    };
    // Weeks where an equip ran fewer hours than the bare-minimum occupied hours (the reference line) are shaded amber.
    const below = [];
    for (const k of starts) {
      const ref = refAt(refs, k, defaultMin);
      if (perEq.some((p) => p.weeks.has(k) && !p.weeks.get(k).partial && p.weeks.get(k).hours < ref - 1e-9)) below.push(k);
    }
    if (below.length && series.length) {
      series[0] = { ...series[0], markArea: { silent: true, itemStyle: { color: "rgba(245,158,11,0.14)" },
        data: below.map((k) => [{ xAxis: k, name: "below min" }, { xAxis: k + WEEK_MS }]) } };
    }
    option.belowWeeks = below;
    option.bareMinOccHoursPerWeek = bareMin != null ? bareMin : defaultMin;
    const lanes = motor.faults ? await faultLanes(ctx, motor.faults, eqs) : [];
    let out = lanes.length ? rcxWithFaultLane(option, lanes) : option;
    out = { ...out, xAxis: [].concat(out.xAxis).map((x) => ({ ...x, min: xMin, max: xMax })) };   // bars and lane share one range
    ofddRender(ctx.chart(el), out, `${motor.id}_weekly_runtime`);
    return `ISO weeks (${tzLabel}), ${starts.length} shown; ${partial.size ? `${partial.size} partial (under 6 days of data); ` : ""}`
      + `on = signal > ${ON * 100}%${role.endsWith("_status") ? " (status)" : " (command)"}`
      + (perEq.some((p) => p.site) ? "; hatched = after-hours run time" : "")
      + `; dashed line = bare-minimum occupied hours/week (occupancy calendar or NF schedule); dotted = average outdoor-air temperature while on`
      + (refs.length ? `; ${refs.map((r) => r.label).join(", ")}` : "")
      + (option.belowWeeks.length ? `; amber = ${option.belowWeeks.length} week${option.belowWeeks.length === 1 ? "" : "s"} below the line` : "");
  }

  for (const motor of MOTORS) {
    motor.signals.forEach((role, i) => {
      rcxView({
        id: `weekly-${motor.id}${i ? "-" + role.split("_").pop() : ""}`,
        group: motor.group,
        title: `Weekly runtime: ${motor.title}${motor.signals.length > 1 ? ` (${role.endsWith("_status") ? "status" : "command"})` : ""}`,
        kinds: motor.kinds, scope: "site", hours: 672, fine: true,
        roles: { required: [role], optional: ["oa_t", ...motor.signals.filter((r) => r !== role)] },
        render: (el, ctx) => renderWeekly(el, ctx, motor, role),
      });
    });
  }

  // ================= AHU run hours per day ==============================================
  // Replaces the weekly "Supply fans (command)" bars in the RCx tab: one bar per AHU per calendar day (site time zone),
  // hours the fan was running, from the fan STATUS when the AHU has one and its COMMAND otherwise (the series name says which).

  /** ms -> Date-only label key (UTC midnight ms of the calendar date in `tz`; UTC when no tz). Cached per quarter hour. */
  function dayKeyer(tz) {
    let fmt = null;
    if (tz) { try { fmt = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }); } catch (e) { fmt = null; } }
    const cache = new Map();
    return (ms) => {
      const q = Math.floor(ms / 900e3);                          // every UTC offset is a multiple of 15 minutes
      let k = cache.get(q);
      if (k === undefined) { k = Date.parse(`${fmt ? fmt.format(ms) : new Date(ms).toISOString().slice(0, 10)}T00:00:00Z`); cache.set(q, k); }
      return k;
    };
  }

  /**
   * Run hours per calendar day (site zone) for grid columns `keys`, from the SQL weekly-runtime analytic
   * (motor_weekly_runtime.sql) bucketed by day: each distinct day of the grid is a bucket boundary. Same definition as
   * the weekly hours: an interval [t[i], t[i+1]) belongs to the day of t[i], on = value > 5 %, intervals over the gap
   * cap are dropped. Every day with samples gets a row (hours 0 when the SQL has no running time that day).
   * -> per key: [{ day: "YYYY-MM-DD", dayMs, hours }] oldest first.
   */
  async function dailyRuntimes(sa, g, keys, { tz = null } = {}) {
    if (!sa) throw new Error("SQL analytics engine unavailable (ctx.sqlAnalytics)");
    // dayKeyer labels a local date as that date's UTC midnight, which is not an instant in the site zone; the SQL needs
    // real bucket starts. The first grid time of each local day is one: every sample of that day is at or after it.
    const dayOf = dayKeyer(tz), firstOf = new Map();
    for (const x of g.t) { const d = dayOf(x); if (!firstOf.has(d)) firstOf.set(d, x); }
    const byKey = await sa.runtime(g, keys.map((k) => ({ key: k, motor: k, oat: null, weekOf: (ms) => firstOf.get(dayOf(ms)) })));
    return keys.map((k) => {
      const v = g.cols[k] || [], days = new Set(), hours = byKey.get(k) || new Map();
      g.t.forEach((x, j) => { if (isNum(v[j])) days.add(dayOf(x)); });
      return [...days].sort((a, b) => a - b).map((dayMs) => {
        const w = hours.get(firstOf.get(dayMs));
        return { day: new Date(dayMs).toISOString().slice(0, 10), dayMs, hours: w ? w.hours : 0 };
      });
    });
  }

  /** Signal a motor's run hours are computed from: the first of motor.signals that binds (status before command). */
  const runSignalOf = (ctx, eq, motor) => {
    for (const role of motor.signals) {
      const p = ctx.first(eq, role);
      if (p) return { p, role, label: role.endsWith("_status") ? "status" : "command" };
    }
    return null;
  };

  /**
   * One daily run-hours chart for a motor family: grouped bars, one series per equip, "<equip> (status|command)"
   * (status wins; the command is used for equips that have no status point). Plant motors get one chart per family.
   */
  function dailyRuntimeView(motor, id, extra = {}) {
    rcxView({
      id, group: motor.group, title: `${motor.title}: run hours per day`,
      kinds: motor.kinds, scope: "site", hours: 168, fine: true, ...extra,
      roles: { required: [], anyOf: motor.signals, optional: [] },
      render: async (el, ctx) => {
        const list = ctx.equips.map((eq) => ({ eq, sig: runSignalOf(ctx, eq, motor) })).filter((x) => x.sig);
        if (!list.length) return `no equipment here has ${motor.signals.join(" or ")}`;
        const cols = {};
        list.forEach((x, i) => { cols[`m${i}`] = x.sig.p; });
        const g = await ctx.alignedFine(cols, { hours: ctx.hours });
        const daily = await dailyRuntimes(ctx.sqlAnalytics, g, list.map((_, i) => `m${i}`), { tz: ctx.siteTz });
        const per = list.map((x, i) => ({ ...x, days: daily[i] }));
        const days = [...new Map(per.flatMap((p) => p.days.map((d) => [d.dayMs, d.day]))).entries()].sort((a, b) => a[0] - b[0]);
        if (!days.length || !per.some((p) => p.days.some((d) => d.hours > 0))) return "no running time in this window";
        const series = per.map((p) => {
          const by = new Map(p.days.map((d) => [d.dayMs, d.hours]));
          return { name: `${eqName(p.eq)} (${p.sig.label})`, type: "bar", data: days.map(([k]) => (by.has(k) ? +by.get(k).toFixed(2) : null)) };
        });
        draw(ctx, el, {
          title: { text: `${motor.title}: run hours per day`, left: 8, top: 0 },
          tooltip: { trigger: "axis", valueFormatter: (x) => (isNum(x) ? `${+x.toFixed(1)} h` : "") }, legend: { top: 24, type: "scroll" }, dataZoom: false,
          grid: baseGrid({ top: 64, bottom: 44 }),
          xAxis: { type: "category", data: days.map(([, d]) => d), name: `day (${ctx.siteTz || "UTC"})`, nameLocation: "middle", nameGap: 28 },
          yAxis: { type: "value", name: "run hours / day", min: 0, max: 24 }, series,
        }, null, `${motor.id.replace(/-/g, "_")}_runtime_daily`);
        if (motor.id === "fan") {
          const all = per.flatMap((p) => p.days.map((d) => d.hours));
          ctx.kpi({ id: "ahu-run-hours", label: "AHU run hours / day", value: `${(all.reduce((a, b) => a + b, 0) / all.length).toFixed(1)} h`, sub: `average of ${per.length} AHU${per.length === 1 ? "" : "s"}`, order: 40 });
        }
        const usedCmd = per.filter((p) => p.sig.label === "command").length;
        return `on = signal > ${ON * 100}% · integrated on the 5-minute grid · ${per.length - usedCmd} from status`
          + `${usedCmd ? `, ${usedCmd} from command (no status point)` : ""} · first and last day may be partial`;
      },
    });
  }

  // 5.0.20: the Overview draws WEEKLY run hours against the occupancy calendar; the daily view stays registered only.
  dailyRuntimeView(MOTORS[0], "ahu-runtime-daily", { headline: true, tabHidden: true });
  // Plant motors are drawn by their weekly charts (same clean style, min-run line); the daily versions stay registered only.
  for (const motor of MOTORS.slice(1)) dailyRuntimeView(motor, `runtime-daily-${motor.id}`, { tabHidden: true });

  M.dailyRuntimes = dailyRuntimes;
  M.dayKeyer = dayKeyer;

  // ================= mechanical cooling x OAT bins =====================================

  /**
   * Cooling hours per OAT bin per equip on the FINE grid (shared by the chart and the agent analytics hook).
   * toDisp only relabels the bins. -> { per: [{ eq, bins: { labels, hours } }], wx } or { error } (no OAT point at all).
   */
  async function mechData(ctx, role, toDisp, pick = null) {
    const wx = weatherOat(ctx);
    const cols = {};
    ctx.equips.forEach((eq, i) => { cols[`a${i}`] = pick ? pick(eq) : ctx.first(eq, role); cols[`o${i}`] = wx || ctx.first(eq, "oa_t"); });
    if (!Object.keys(cols).some((k) => k[0] === "o" && cols[k])) return { error: "needs an outdoor-air temperature (weather point or oa_t)", per: [], wx };
    const g = await ctx.alignedFine(cols, { hours: ctx.hours });   // fine grid: a short low-OAT event must not vanish
    // #1649: the hours per bin are the SQL analytic (sql/analytics/mech_cooling_oat_bins.sql, OAT joined as-of)
    if (!ctx.sqlAnalytics) throw new Error("SQL analytics engine unavailable (ctx.sqlAnalytics)");
    const idx = ctx.equips.map((eq, i) => i).filter((i) => cols[`a${i}`] && cols[`o${i}`]);
    const hoursBy = await ctx.sqlAnalytics.mech(g, idx.map((i) => ({ key: i, proof: `a${i}`, oat: `o${i}` })));
    const labels = M.oatBinLabels(toDisp);
    const per = idx.map((i) => ({ eq: ctx.equips[i], col: cols[`a${i}`], bins: { labels, hours: hoursBy.get(i) } }));
    return { per, wx };
  }

  for (const role of ["compressor_status", "chiller_status", "chiller_cmd"]) {
    rcxView({
      id: `mech-cooling-${role.split("_").slice(0, -1).join("-")}-${role.split("_").pop()}`,
      group: "Plant", tabHidden: true,          // superseded on the tab by "mech-cooling-hours" (one chart, one series per equip)
      title: `Mechanical cooling hours by outdoor air (${role.replace("_", " ")})`,
      kinds: [], scope: "site", hours: 720,
      roles: { required: [role], optional: ["oa_t"] },
      render: async (el, ctx) => {
        const res = await mechData(ctx, role, (c) => ctx.disp(c, TEMP).value);
        if (res.error) return res.error;
        const { per, wx } = res;
        if (!per.length) return "no outdoor-air data";
        const unit = ctx.dispUnit(TEMP), labels = M.oatBinLabels((c) => ctx.disp(c, TEMP).value);
        const series = per.map((p) => ({ name: eqName(p.eq), type: "bar", stack: "hours",
          data: p.bins.hours.map((h) => (h > 0 ? h : null)) }));   // unrounded; the tooltip formats
        if (!per.some((p) => p.bins.hours.some((h) => h > 0))) return "cooling never ran in this window";
        draw(ctx, el, {
          tooltip: { trigger: "axis", valueFormatter: (v) => (isNum(v) ? String(+v.toFixed(2)) : "") }, legend: { top: 0 }, dataZoom: false,
          grid: baseGrid({ bottom: 40 }),
          xAxis: { type: "category", data: labels, name: `OAT bin ${unit}`, nameLocation: "middle", nameGap: 26 },
          yAxis: { type: "value", name: "hours" }, series,
        }, null, `mech_cooling_${role}`);
        return `${wx ? "web" : "equip"} outdoor-air temperature · on = ${role.endsWith("_cmd") ? "command" : "status"} > ${ON * 100}%`;
      },
    });
  }

  // One chart per equip (hours per fixed SI outdoor-air bin). The proof is type-dispatched per equip: a status first (chiller
  // status, compressor status, DX cooling status), else a command (chiller, compressor, DX cooling command), and the chart
  // says which. AHU / RTU DX run roles bind too; a chilled-water valve is never proof (its hours belong to the plant).
  const MECH_STATUS = ["chiller_status", "compressor_status", "dx_cooling"];
  const MECH_CMD = ["chiller_cmd", "compressor_cmd", "dx_cool_cmd"];
  rcxView({
    id: "mech-cooling-hours", group: "Plant", title: "Mechanical cooling hours by outdoor air",
    kinds: [], scope: "site", hours: 720, fine: true,
    roles: { required: [], anyOf: [...MECH_STATUS, ...MECH_CMD], optional: ["oa_t"] },
    render: async (el, ctx) => {
      const roleOf = new Map();
      const pick = (eq) => { for (const r of [...MECH_STATUS, ...MECH_CMD]) { const p = ctx.first(eq, r); if (p) { roleOf.set(p.uuid, r); return p; } } return null; };
      const res = await mechData(ctx, null, (c) => ctx.disp(c, TEMP).value, pick);
      if (res.error) return res.error;
      const { per, wx } = res;
      if (!per.length) return "no outdoor-air data";
      const unit = ctx.dispUnit(TEMP), labels = M.oatBinLabels((c) => ctx.disp(c, TEMP).value);
      const proof = (p) => `${eqName(p.eq)}: ${roleOf.get(p.col.uuid).replace(/_/g, " ")}`;
      if (!per.some((p) => p.bins.hours.some((h) => h > 0))) return "cooling never ran in this window";
      draw(ctx, el, {
        title: { text: "Mechanical cooling hours by outdoor air", left: 8, top: 0 },
        tooltip: { trigger: "axis", valueFormatter: (v) => (isNum(v) ? `${+v.toFixed(1)} h` : "") }, legend: { top: 24 }, dataZoom: false,
        grid: baseGrid({ top: 64, bottom: 44 }),
        xAxis: { type: "category", data: labels, name: `OAT bin ${unit}`, nameLocation: "middle", nameGap: 28 },
        yAxis: { type: "value", name: "hours" }, series: per.map((p) => ({ name: eqName(p.eq), type: "bar", data: p.bins.hours.map((h) => (h > 0 ? h : null)) })),
      }, null, "mech_cooling_hours");
      return `${wx ? "web" : "equip"} outdoor-air temperature · proof > ${ON * 100}% (${per.map(proof).join("; ")}) · fixed SI bins (shown in ${unit})`;
    },
  });

  // ================= economizer ========================================================

  const ECON_RULES = ["ECON-1", "ECON-2", "DMP-1"];
  const ECON_ROLES = { required: ["oa_t", "rat", "mat", "fan_status"], optional: ["sat", "oa_damper_pct"] };

  /** Economizer samples of one equip. `fine` = the fine grid (agent numbers); the charts keep the display grid. */
  async function econGrid(ctx, eq, fine = false) {
    const col = (r) => ctx.first(eq, r);
    const g = await (fine ? ctx.alignedFine : ctx.aligned)({ oa_t: col("oa_t"), rat: col("rat"), mat: col("mat"), fan: col("fan_status"),
      sat: col("sat"), damper: col("oa_damper_pct") }, { hours: ctx.hours });
    // #1649: rows and summary are the SQL analytics (economizer_points.sql / economizer_metrics.sql)
    if (!ctx.sqlAnalytics) throw new Error("SQL analytics engine unavailable (ctx.sqlAnalytics)");
    const { rows, summary } = await ctx.sqlAnalytics.econ(g);
    return { eq, rows, summary };
  }

  rcxView({
    id: "economizer-delta", group: "Air handlers", title: "Economizer: free-cooling delta scatter",
    kinds: ["ahu"], scope: "site", hours: 168, roles: ECON_ROLES,
    // No fault lane: a scatter of delta vs delta has no time axis to link a lane to.
    render: async (el, ctx) => {
      const per = await Promise.all(ctx.equips.map((eq) => econGrid(ctx, eq)));
      const rows = per.flatMap((p) => p.rows.filter((r) => r.ident));
      if (rows.length < 5) return "fewer than 5 identifiable fan-on samples (needs |OAT-RAT| above the minimum delta)";
      const dmin = ctx.dispDelta(ECON_DT_MIN_C, TEMP), unit = dmin.unit;   // deltas: no 32 offset
      // Damper position bands stand in for central's visual map (theme palette colors only).
      /** @type {[string, (r: any) => boolean][]} */
      const bands = [["damper n/a", (r) => r.damperPct == null], ["damper 0-33%", (r) => r.damperPct != null && r.damperPct < 33.34],
        ["damper 33-67%", (r) => r.damperPct >= 33.34 && r.damperPct < 66.67], ["damper 67-100%", (r) => r.damperPct >= 66.67]];
      const series = bands.map(([name, test]) => ({ name, type: "scatter", symbolSize: 7,
        data: rows.filter(test).map((r) => [+ctx.dispDelta(r.dOR, TEMP).value.toFixed(2), +ctx.dispDelta(r.dMR, TEMP).value.toFixed(2), r.damperPct]) })).filter((s) => s.data.length);
      draw(ctx, el, {
        tooltip: plainItemTip((p) => `${p.seriesName}: OAT-RAT ${p.value[0]}, MAT-RAT ${p.value[1]}`), legend: { top: 0 }, dataZoom: false,
        grid: baseGrid({ bottom: 44 }),
        xAxis: { type: "value", name: `OAT - RAT (${unit})`, scale: true, nameLocation: "middle", nameGap: 26 },
        yAxis: { type: "value", name: `MAT - RAT (${unit})`, scale: true }, series,
      }, null, "economizer_free_cooling_delta");
      return `fan on, |OAT-RAT| >= ${dmin.value.toFixed(1)} ${unit} · ${rows.filter((r) => r.ident).length} samples`;
    },
  });

  rcxView({
    id: "economizer-mat-residual", group: "Air handlers", title: "Economizer: MAT residual (measured - mixing model)",
    kinds: ["ahu"], scope: "site", hours: 168, roles: { required: [...ECON_ROLES.required, "oa_damper_pct"], optional: ["sat"] },
    render: async (el, ctx) => {
      const per = await Promise.all(ctx.equips.map((eq) => econGrid(ctx, eq)));
      const series = per.map((p) => lineS(eqName(p.eq),
        ctx.dispSeries(p.rows.filter((r) => r.ident && r.matResid != null).map((r) => [r.t, r.matResid]), TEMP, true)
          .map(([t, v]) => [t, +v.toFixed(2)])))
        .filter((s) => s.data.length);
      if (!series.length) return "no identifiable fan-on samples with a damper position";
      const unit = ctx.dispDelta(0, TEMP).unit;
      const lanes = await faultLanes(ctx, ECON_RULES, ctx.equips);
      draw(ctx, el, { tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: baseGrid({ bottom: 56 }),
        xAxis: { type: "time" }, yAxis: { type: "value", name: `residual (${unit})`, scale: true }, series }, lanes, "economizer_mat_residual");
      // per equip, from economizer_metrics.sql (the SQL summary, never recomputed here)
      const meds = per.map((p) => `${eqName(p.eq)} ${p.summary.medianResid == null ? "n/a" : ctx.dispDelta(p.summary.medianResid, TEMP).value.toFixed(2)}`);
      return `MAT - (RAT + damper% x (OAT - RAT)), fan on, identifiable · median residual ${meds.join(", ")} ${unit}`;
    },
  });

  rcxView({
    id: "economizer-temps", group: "Air handlers", title: "Economizer: temperatures and OA damper",
    kinds: ["ahu"], scope: "equip", hours: 168, roles: ECON_ROLES,
    render: async (el, ctx) => {
      const eq = ctx.equips[0], col = (r) => ctx.first(eq, r);
      const cols = { OAT: col("oa_t"), RAT: col("rat"), MAT: col("mat"), SAT: col("sat"), "OA damper %": col("oa_damper_pct") };
      const g = await ctx.aligned(cols, { hours: ctx.hours });
      const pairs = (k) => g.t.map((t, i) => [t, g.cols[k][i]]).filter((d) => isNum(d[1]));
      const tempPairs = (k) => ctx.dispSeries(pairs(k), TEMP);
      const series = ["OAT", "RAT", "MAT", "SAT"].map((k) => [k, tempPairs(k)]).filter(([, d]) => d.length).map(([k, d]) => lineS(k, d));
      const dmp = pairs("OA damper %").map(([t, v]) => [t, +(rcxStats.frac(v) * 100).toFixed(1)]);
      if (dmp.length) series.push(lineS("OA damper %", dmp, { yAxisIndex: 1, lineStyle: { width: 1.2, type: "dashed" } }));
      if (series.length < 3) return "not enough temperature data";
      const lanes = await faultLanes(ctx, ECON_RULES, [eq]);
      draw(ctx, el, { tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: baseGrid({ right: 56, bottom: 56 }),
        xAxis: { type: "time" },
        yAxis: [{ type: "value", name: ctx.dispUnit(TEMP), scale: true },
          { type: "value", name: "OA damper %", min: 0, max: 100, position: "right", splitLine: { show: false } }], series }, lanes, "economizer_temps_oa_damper");
    },
  });

  // ================= BAS vs web outdoor-air temperature ================================

  async function basData(ctx) {
    const eq = ctx.equips[0];                      // primary reference: first bound equip's oa_t
    const bas = ctx.first(eq, "oa_t"), web = ctx.first(eq, "web_oa_t");
    const g = await ctx.aligned({ bas, web }, { hours: ctx.hours });
    return { eq, ...(await ctx.sqlAnalytics.bas(g)), g, web };   // bas_vs_web_points.sql + bas_vs_web_oat.sql
  }
  const BAS_ROLES = { required: ["oa_t", "web_oa_t"], optional: [] };

  // The deviation sits under "Weather" (or the boiler / hot-water plant when that is where the hard-wired outdoor-air
  // sensor is modelled), never with the air handlers. It is an FDD chart: signals on top, OAT-METEO fault lane at the bottom.
  const basGroup = (eqs) => (((eqs && eqs[0] && eqs[0].kinds) || []).some((k) => ["boiler", "chwPlant", "chiller"].includes(k)) ? "Boiler / hot-water plant" : "Weather");
  rcxView({
    id: "bas-vs-web-oat", group: "Weather", groupOf: basGroup, tab: "fdd", title: "BAS vs web outdoor-air temperature",
    kinds: [], scope: "site", hours: 168, roles: BAS_ROLES,
    render: async (el, ctx) => {
      const d = await basData(ctx);
      if (!d.rows.length) return "no coincident BAS and web outdoor-air samples in this window";
      // math above is degC; the chart gets display values (band base = web - band, width = 2 x band)
      const T = (c) => ctx.disp(c, TEMP).value, half = ctx.dispDelta(d.band, TEMP).value, unit = ctx.dispUnit(TEMP);
      const series = [
        lineS("Web OAT", d.rows.map((r) => [r.t, T(r.web)])),
        lineS("BAS oa_t", d.rows.map((r) => [r.t, T(r.bas)])),
        // Band = transparent base (web - band) + stacked 2 x band wide area; theme palette colors.
        { name: "band base", type: "line", stack: "band", symbol: "none", silent: true, lineStyle: { opacity: 0 },
          data: d.rows.map((r) => [r.t, +(T(r.web) - half).toFixed(2)]) },
        { name: `+-${+half.toFixed(1)} band`, type: "line", stack: "band", symbol: "none", silent: true,
          lineStyle: { opacity: 0 }, areaStyle: { opacity: 0.18 }, data: d.rows.map((r) => [r.t, +(2 * half).toFixed(2)]) },
      ];
      const lanes = await faultLanes(ctx, ["OAT-METEO"], ctx.equips);
      draw(ctx, el, { title: { text: fddRuleRich("BAS vs web outdoor-air temperature", "OAT-METEO", eqName(d.eq)), left: 8, top: 0, textStyle: { rich: FDD_RULE_RICH } },
        tooltip: { trigger: "axis" }, legend: { top: 24, data: ["Web OAT", "BAS oa_t", `+-${+half.toFixed(1)} band`] },
        grid: baseGrid({ top: 64, bottom: 56 }), xAxis: { type: "time" },
        yAxis: { type: "value", name: unit, scale: true }, series }, lanes, "bas_vs_web_oat");
      const s = d.stats, lane = lanes[0] && lanes[0].data;
      const fault = lane && lane.length
        ? ` · ${lane.approximate ? "approximate: fault" : "confirmed fault"} in ${lane.filter(([, f]) => f === 1).length} of ${lane.filter(([, f]) => f != null).length} ${lane.approximate ? "hourly results" : "assessed samples"}`
        : " · no OAT-METEO result point yet (lane omitted)";
      return `${eqName(d.eq)} vs web · ${s.n} samples · bias ${ctx.dispDelta(s.bias, TEMP).value.toFixed(2)} ${ctx.dispDelta(0, TEMP).unit} · within band ${(s.withinBand * 100).toFixed(0)}%${fault}`;
    },
  });

  rcxView({
    // Registered for the agent analytics; not drawn on a tab (the FDD chart above carries bias and in-band share).
    id: "bas-vs-web-oat-hist", group: "Weather", groupOf: basGroup, tab: "fdd", tabHidden: true, title: "BAS vs web outdoor-air deviation",
    kinds: [], scope: "site", hours: 168, roles: BAS_ROLES,
    // No fault lane: a histogram has no time axis.
    render: async (el, ctx) => {
      const d = await basData(ctx);
      if (!d.rows.length) return "no coincident BAS and web outdoor-air samples in this window";
      // bin the deltas in display units (1 degF / 0.5 degC wide) so the labels are round numbers
      const dd = ctx.dispDelta(1, TEMP), du = dd.unit;
      const h = M.deltaHist(d.rows.map((r) => +ctx.dispDelta(r.d, TEMP).value.toFixed(6)), dd.value > 1 ? 1 : 0.5);
      draw(ctx, el, { tooltip: { trigger: "axis" }, dataZoom: false, grid: baseGrid({ top: 20, bottom: 44 }),
        xAxis: { type: "category", data: h.labels, name: `BAS - web (${du})`, nameLocation: "middle", nameGap: 26 },
        yAxis: { type: "value", name: "count" }, series: [{ name: "samples", type: "bar", data: h.counts }] }, null, "bas_web_oat_deviation_hist");
      return `bin = lower edge · mean ${ctx.dispDelta(d.stats.bias, TEMP).value.toFixed(2)} ${du}, max |delta| ${ctx.dispDelta(d.stats.maxAbs, TEMP).value.toFixed(1)} ${du}`;
    },
  });
})();
