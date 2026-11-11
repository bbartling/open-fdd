// Overview RCx views for the Open-FDD NF app (port of archive central-v4 overview-rcx-charts.js).
//
// Central computed these server side (runtime, mechanical-cooling, economizer, bas-vs-web-oat).
// Here the same math runs in the browser on NF history: ctx.aligned() gives one time grid for
// several roles, resampled by NF. Pure math lives on globalThis.rcxOverviewMath (tests use it);
// only rcxView() registrations leave this file. Nothing site-specific: equips, roles and
// units all come from NF + fdd-catalog.json.
//
// Thresholds kept from the SQL pack (sql/analytics/postgres/queries):
//   * ON threshold: command/status fraction > 0.05 (rcxStats.frac normalizes percent to 0-1),
//     as in motor_weekly_runtime.sql / mechanical_cooling_oat_bins.sql / economizer_deltas.sql.
//   * Gap cap: a sample interval only counts when it is <= 3600 s. Hours (weekly runtime, after-hours
//     split, cooling bins) integrate on the FINE grid (ctx.alignedFine, 300 s window), never on the
//     ~360-point display grid (ctx.aligned): a coarse AVERAGE bucket smears a short pulse or hides a
//     short cooling event. Intervals run to the signal's own next non-null sample (4.x LEAD()), so a
//     null stretch is uncovered, not "off".
//   * Economizer: fan_status > 0.05 gate, |OAT-RAT| >= 50/9 delta degC (= 10 delta degF) to be identifiable.
//   * BAS vs web OAT: band +-2 delta degC (= 3.6 delta degF); web value is carried as-of (last value)
//     for at most ~1.5 x its own cadence.
// Units: ctx.series/aligned hand over canonical SI (degC, Pa, L/s, ...), so all the math and every
// threshold here is SI. Values are mapped to the user's display system (ctx.disp / ctx.dispDelta)
// only when a chart or note is built.
// Needs rcx.js (rcxView, rcxStats, rcxFaultData, rcxWithFaultLane), model.js (has),
// charts.js (pickWindow), theme.js (ofddRender).
(function () {
  "use strict";

  const ON = 0.05;                      // on-threshold on a 0-1 command/status fraction
  const GAP_MAX_SEC = 3600;             // longest interval a sample may stand for
  const ECON_DT_MIN_C = 50 / 9;         // |OAT-RAT| (delta degC) for an identifiable economizer sample
  const BAS_BAND_C = 2;                 // BAS vs web OAT band (delta degC)
  const OAT_EDGES_C = [10, 15.555555555555556, 21.11111111111111, 26.666666666666668, 32.22222222222222];
  const WEEK_MS = 7 * 86400e3;
  const isNum = (x) => x != null && Number.isFinite(x);
  const median = (xs) => rcxStats.quantile(xs, 0.5);
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

  /**
   * Weight of one sample interval: how much of it the motor counts as running.
   *   duty = true  (Bool status/command): the resampled average IS the on-fraction -> weight = frac.
   *   duty = false (analog command): on at all (> 0.05) -> whole interval, as the SQL pack does.
   * Fractions <= 0.05 count as off.
   */
  function onWeight(v, duty) {
    if (!isNum(v)) return 0;
    const f = rcxStats.frac(v);
    if (!(f > ON)) return 0;
    return duty ? Math.min(f, 1) : 1;
  }

  /**
   * Run hours per ISO week from one signal on a time grid.
   * t = [ms], v = [value|null], oat = [value|null] (optional, average OAT while running).
   * Interval i is [t[i], t[i+1]) and belongs to the week of t[i]; intervals longer than
   * gapMaxSec are skipped (data gap). Returns Map(weekStartMs -> { hours, oat, n, partial })
   * partial = the observed span inside that week is under 6 days (central's partial_week).
   */
  function weeklyRuntime(t, v, { duty = false, gapMaxSec = GAP_MAX_SEC, oat = null, weekOf = weekStart, occ = null } = {}) {
    const weeks = new Map();
    const get = (k) => {
      if (!weeks.has(k)) weeks.set(k, { hours: 0, inH: 0, afterH: 0, oatSum: 0, oatN: 0, n: 0, first: Infinity, last: -Infinity });
      return weeks.get(k);
    };
    // 4.x LEAD() runs over the signal's own rows: a null sample is not a row, so a null stretch is neither
    // "off" nor covered. The interval from the last real sample before it to the next real one is simply
    // long, and the gap cap drops it (a short null hole under the cap is bridged, as in the SQL).
    const rows = [];
    for (let i = 0; i < t.length; i++) if (isNum(v[i])) rows.push(i);
    for (let j = 0; j < rows.length; j++) {
      const i = rows[j];
      const w = get(weekOf(t[i]));
      w.n++; w.first = Math.min(w.first, t[i]); w.last = Math.max(w.last, t[i]);
      if (j + 1 >= rows.length) continue;
      const dt = (t[rows[j + 1]] - t[i]) / 1000;
      if (!(dt > 0 && dt <= gapMaxSec)) continue;
      const wt = onWeight(v[i], duty);
      if (!wt) continue;
      const h = (wt * dt) / 3600;
      w.hours += h;
      if (occ) { if (occ(t[i])) w.inH += h; else w.afterH += h; }   // an interval belongs to the occupancy at its start
      if (oat && isNum(oat[i])) { w.oatSum += oat[i]; w.oatN++; }
    }
    const out = new Map();
    for (const [k, w] of [...weeks].sort((a, b) => a[0] - b[0])) {
      out.set(k, { hours: w.hours, inHours: occ ? w.inH : null, afterHours: occ ? w.afterH : null,
        oat: w.oatN ? w.oatSum / w.oatN : null, n: w.n, partial: w.last - w.first < 6 * 86400e3 });
    }
    return out;
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
  const oatBinIndex = (oat, edges) => { const i = edges.findIndex((e) => oat < e); return i < 0 ? edges.length : i; };

  /**
   * Hours the cooling device was on, per OAT bin (mechanical_cooling_oat_bins.sql). oat in degC;
   * toDisp only relabels the bins for the display system.
   * Only intervals where the device is on (weight > 0) and OAT is known count.
   * Returns { labels, hours: [h per label] }.
   */
  /** @param {any} t @param {any} active @param {any} oat @param {{toDisp?: (c: number) => number, duty?: boolean, gapMaxSec?: number}} [o] */
  function mechBins(t, active, oat, { toDisp, duty = false, gapMaxSec = GAP_MAX_SEC } = {}) {
    const edges = oatEdges(), labels = oatBinLabels(toDisp), hours = labels.map(() => 0);
    // Like the SQL: only rows where the device signal AND the OAT both exist (joined), and the interval runs
    // to the next joined row, so a null stretch is uncovered (gap cap), never "off".
    const rows = [];
    for (let i = 0; i < t.length; i++) if (isNum(active[i]) && isNum(oat[i])) rows.push(i);
    for (let j = 0; j + 1 < rows.length; j++) {
      const i = rows[j], dt = (t[rows[j + 1]] - t[i]) / 1000;
      if (!(dt > 0 && dt <= gapMaxSec)) continue;
      const w = onWeight(active[i], duty);
      if (w) hours[oatBinIndex(oat[i], edges)] += (w * dt) / 3600;
    }
    return { labels, hours };
  }

  /**
   * Economizer samples (economizer_deltas.sql + economizer.rs). Row inputs are parallel arrays on
   * one grid: oa_t, rat, mat, sat?, fan (fan_status), damper? (oa_damper_pct, 0-1 or 0-100).
   * Kept: fan on (> 0.05) and oa_t/rat/mat present. Per sample (temps in degC, deltas in delta degC):
   *   dOR = OAT - RAT, dMR = MAT - RAT, identifiable = |dOR| >= dtMin,
   *   oaFrac% = 100 dMR / dOR (identifiable, clamped -20..120),
   *   matPred = RAT + damperFrac * dOR, matResid = MAT - matPred (needs a damper).
   */
  function economizerRows(g, { dtMin = ECON_DT_MIN_C } = {}) {
    const rows = [];
    for (let i = 0; i < g.t.length; i++) {
      const [oa, rat, mat, fan] = [g.oa_t[i], g.rat[i], g.mat[i], g.fan[i]];
      if (!isNum(oa) || !isNum(rat) || !isNum(mat) || !isNum(fan) || !(rcxStats.frac(fan) > ON)) continue;
      const dOR = oa - rat, dMR = mat - rat, ident = Math.abs(dOR) >= dtMin;
      const dmp = g.damper && isNum(g.damper[i]) ? rcxStats.frac(g.damper[i]) : null;
      const matPred = dmp == null ? null : rat + dmp * dOR;
      rows.push({
        t: g.t[i], oa, rat, mat, sat: g.sat && isNum(g.sat[i]) ? g.sat[i] : null,
        damperPct: dmp == null ? null : dmp * 100, dOR, dMR, ident,
        oaFrac: ident ? Math.max(-20, Math.min(120, (100 * dMR) / dOR)) : null,
        matPred, matResid: matPred == null ? null : mat - matPred,
      });
    }
    return rows;
  }

  function economizerSummary(rows) {
    const ident = rows.filter((r) => r.ident), resid = ident.map((r) => r.matResid).filter(isNum);
    return { n: rows.length, nIdent: ident.length, medianResid: median(resid),
      maeResid: resid.length ? resid.reduce((a, b) => a + Math.abs(b), 0) / resid.length : null };
  }

  /** Last non-null value at or before each t, no older than maxAgeMs (as-of join). */
  function asOfFill(t, v, maxAgeMs) {
    const out = new Array(t.length).fill(null);
    let last = null, lastT = -Infinity;
    for (let i = 0; i < t.length; i++) {
      if (isNum(v[i])) { last = v[i]; lastT = t[i]; }
      if (last != null && t[i] - lastT <= maxAgeMs) out[i] = last;
    }
    return out;
  }

  /** As-of bound for a slow series: 1.5 x its own cadence, at least two grid steps. */
  function webMaxAgeMs(t, v) {
    const seen = t.filter((_, i) => isNum(v[i]));
    const gaps = seen.slice(1).map((x, i) => x - seen[i]);
    const step = median(t.slice(1).map((x, i) => x - t[i]));
    return Math.max(1.5 * (median(gaps) || 0), 2 * (step || 0));
  }

  /**
   * BAS vs web outdoor-air temperature (bas_vs_web_oat.sql): web is joined as-of to each BAS
   * sample; delta = BAS - web. All temperatures in degC, bandC in delta degC.
   * Returns { rows: [{t, bas, web, d}], stats: { n, bias, mae, maxAbs, withinBand } }.
   */
  function basVsWeb(t, bas, web, { bandC = BAS_BAND_C } = {}) {
    const webAs = asOfFill(t, web, webMaxAgeMs(t, web)), band = bandC;
    const rows = [];
    for (let i = 0; i < t.length; i++) {
      if (isNum(bas[i]) && webAs[i] != null) rows.push({ t: t[i], bas: bas[i], web: webAs[i], d: bas[i] - webAs[i] });
    }
    const ds = rows.map((r) => r.d), n = ds.length;
    return { rows, band, stats: {
      n, bias: rcxStats.mean(ds), mae: n ? ds.reduce((a, b) => a + Math.abs(b), 0) / n : null,
      maxAbs: n ? Math.max(...ds.map(Math.abs)) : null,
      withinBand: n ? ds.filter((d) => Math.abs(d) <= band).length / n : null,
    } };
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
    weekStart, isoWeekLabel, onWeight, weeklyRuntime, oatEdges, oatBinLabels, mechBins,
    economizerRows, economizerSummary, asOfFill, webMaxAgeMs, basVsWeb, deltaHist, mergeFaultLanes,
    ECON_DT_MIN_C, BAS_BAND_C, ON,
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
    { id: "fan", title: "Supply fans", group: "Air handlers", kinds: ["ahu"], signals: ["fan_status", "fan_cmd"], faults: ["SCHED-247"] },
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
    for (const ref of new Set(eqs.map(siteOf))) {
      const rec = ((ctx.model && ctx.model.sites) || []).find((r) => ((r.attrs && r.attrs.id) || r.name) === ref);
      const tz = siteZone(rec);
      const schedule = S.pickSiteSchedule(schedules, ctx.model, ref) || S.defaultSchedule(tz);
      const zone = schedule.tz || tz || null;
      out.set(ref, { siteRef: ref, schedule, tz: zone, weekOf: weekIndexer(zone), occ: (ms) => S.occupied(schedule, ms, zone) });
    }
    return out;
  }

  /**
   * Weekly runtime per equip on the FINE grid (shared by the chart and the agent analytics hook): { perEq, sites }.
   * perEq = [{ eq, site, role, weeks: Map(weekStartMs -> weeklyRuntime row) }], sites = Map(siteRef -> schedule info).
   * Hours integrate on the fine grid (alignedFine), schedules are read once per call (read only).
   */
  async function weeklyData(ctx, eqs, role) {
    const wx = weatherOat(ctx);
    const cols = {};
    eqs.forEach((eq, i) => { cols[`m${i}`] = ctx.first(eq, role); cols[`o${i}`] = ctx.first(eq, "oa_t") || wx; });
    const [g, sites] = await Promise.all([ctx.alignedFine(cols, { hours: ctx.hours }), siteSchedules(ctx, eqs)]);
    const perEq = eqs.map((eq, i) => {
      const site = sites.get(siteOf(eq));
      return { eq, site, role, weeks: M.weeklyRuntime(g.t, g.cols[`m${i}`], { duty: cols[`m${i}`].kind === "Bool", gapMaxSec: GAP_MAX_SEC,
        oat: g.cols[`o${i}`], weekOf: site && site.weekOf, occ: site && site.occ }) };
    });
    return { perEq, sites };
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
        { name: `${name} · in schedule`, type: "bar", stack: `eq${i}`, itemStyle: color, data: bars((w) => w.inHours) },
        { name: `${name} · after hours`, type: "bar", stack: `eq${i}`, itemStyle: { ...color, decal: AFTER_HOURS_DECAL }, data: bars((w) => w.afterHours) },
      ];
    });
    // Schedule reference: hours per ISO week as a step line (holiday weeks step down), one per site.
    const S = sched(), refs = [];
    if (S) {
      for (const site of new Set(perEq.map((p) => p.site).filter(Boolean))) {
        const ks = [...new Set(perEq.filter((p) => p.site === site).flatMap((p) => [...p.weeks.keys()]))].sort((a, b) => a - b);
        if (!ks.length) continue;
        const infos = ks.map((k) => S.weeklyScheduleInfo(site.schedule, k, site.tz));
        const end = site.tz ? S.localWeekStartMs(ks[ks.length - 1] + 8 * 86400e3, site.tz) : ks[ks.length - 1] + WEEK_MS;
        const label = infos[0].label + (sites.size > 1 ? ` · ${site.siteRef}` : "");
        refs.push({ site, label, end });
        series.push({ id: `schedule-ref:${site.siteRef}`, name: label, type: "line", step: "end", showSymbol: false, z: 5,
          lineStyle: { width: 2, type: "dashed" }, data: [...ks.map((k, i) => [k, infos[i].hours]), [end, infos[infos.length - 1].hours]] });
      }
    }
    // mean OAT while on: averaged in degC, shown in the display system
    const oatMeans = ctx.dispSeries(starts.map((k) => [k, rcxStats.mean(perEq.map((p) => p.weeks.get(k)?.oat))]).filter(([, v]) => v != null), TEMP)
      .map(([k, v]) => [k, +v.toFixed(1)]);
    const oatUnit = ctx.dispUnit(TEMP);
    if (oatMeans.length) {
      series.push(lineS(`Avg OAT ${oatUnit} (while on)`, oatMeans, { yAxisIndex: 1, showSymbol: true, symbolSize: 7,
        lineStyle: { width: 2, type: "dotted" } }));
    }
    const xMin = starts[0], xMax = Math.max(starts[starts.length - 1] + WEEK_MS, ...refs.map((r) => r.end));
    const tzs = [...new Set([...sites.values()].map((s) => s.tz || "UTC"))], tzLabel = tzs.length <= 1 ? tzs[0] || "UTC" : "site local";
    const option = {
      tooltip: { trigger: "axis", valueFormatter: (v) => (isNum(v) ? String(+v.toFixed(2)) : "") }, legend: { top: 0 },
      grid: baseGrid({ right: oatMeans.length ? 56 : 24 }),
      xAxis: { type: "time", min: xMin, max: xMax, name: `week of (${tzLabel})` },
      yAxis: [{ type: "value", name: "Run hours" },
        ...(oatMeans.length ? [{ type: "value", name: oatUnit, position: "right", scale: true, splitLine: { show: false } }] : [])],
      series,
    };
    const lanes = motor.faults ? await faultLanes(ctx, motor.faults, eqs) : [];
    let out = lanes.length ? rcxWithFaultLane(option, lanes) : option;
    out = { ...out, xAxis: [].concat(out.xAxis).map((x) => ({ ...x, min: xMin, max: xMax })) };   // bars and lane share one range
    ofddRender(ctx.chart(el), out, `${motor.id}_weekly_runtime`);
    return `ISO weeks (${tzLabel}), ${starts.length} shown; ${partial.size ? `${partial.size} partial (under 6 days of data); ` : ""}`
      + `on = signal > ${ON * 100}%${role.endsWith("_status") ? " (status)" : " (command)"}`
      + (refs.length ? `; hatched = after-hours run time; line = ${refs.map((r) => r.label).join(", ")}` : "");
  }

  for (const motor of MOTORS) {
    motor.signals.forEach((role, i) => {
      rcxView({
        id: `weekly-${motor.id}${i ? "-" + role.split("_").pop() : ""}`,
        group: motor.group,
        title: `Weekly runtime: ${motor.title}${motor.signals.length > 1 ? ` (${role.endsWith("_status") ? "status" : "command"})` : ""}`,
        kinds: motor.kinds, scope: "site", hours: 672,
        roles: { required: [role], optional: ["oa_t", ...motor.signals.filter((r) => r !== role)] },
        render: (el, ctx) => renderWeekly(el, ctx, motor, role),
      });
    });
  }

  // ================= mechanical cooling x OAT bins =====================================

  /**
   * Cooling hours per OAT bin per equip on the FINE grid (shared by the chart and the agent analytics hook).
   * toDisp only relabels the bins. -> { per: [{ eq, bins: { labels, hours } }], wx } or { error } (no OAT point at all).
   */
  async function mechData(ctx, role, toDisp) {
    const wx = weatherOat(ctx);
    const cols = {};
    ctx.equips.forEach((eq, i) => { cols[`a${i}`] = ctx.first(eq, role); cols[`o${i}`] = wx || ctx.first(eq, "oa_t"); });
    if (!Object.keys(cols).some((k) => k[0] === "o" && cols[k])) return { error: "needs an outdoor-air temperature (weather point or oa_t)", per: [], wx };
    const g = await ctx.alignedFine(cols, { hours: ctx.hours });   // fine grid: a short low-OAT event must not vanish
    const per = ctx.equips.map((eq, i) => {
      const op = cols[`o${i}`];
      // a slow weather series (20 min) is carried as-of onto the 5 min device rows, bounded by its own cadence
      const oat = op ? M.asOfFill(g.t, g.cols[`o${i}`], Math.max(M.webMaxAgeMs(g.t, g.cols[`o${i}`]), g.windowSec * 1e3)) : null;
      return oat ? { eq, bins: M.mechBins(g.t, g.cols[`a${i}`], oat,
        { toDisp, duty: cols[`a${i}`].kind === "Bool", gapMaxSec: GAP_MAX_SEC }) } : null;
    }).filter(Boolean);
    return { per, wx };
  }

  for (const role of ["compressor_status", "chiller_status", "chiller_cmd"]) {
    rcxView({
      id: `mech-cooling-${role.split("_").slice(0, -1).join("-")}-${role.split("_").pop()}`,
      group: "Plant",
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

  // ================= economizer ========================================================

  const ECON_RULES = ["ECON-1", "ECON-2", "DMP-1"];
  const ECON_ROLES = { required: ["oa_t", "rat", "mat", "fan_status"], optional: ["sat", "oa_damper_pct"] };

  /** Economizer samples of one equip. `fine` = the fine grid (agent numbers); the charts keep the display grid. */
  async function econGrid(ctx, eq, fine = false) {
    const col = (r) => ctx.first(eq, r);
    const g = await (fine ? ctx.alignedFine : ctx.aligned)({ oa_t: col("oa_t"), rat: col("rat"), mat: col("mat"), fan: col("fan_status"),
      sat: col("sat"), damper: col("oa_damper_pct") }, { hours: ctx.hours });
    return { eq, rows: M.economizerRows({ t: g.t, ...g.cols }) };
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
      const s = M.economizerSummary(rows);
      return `fan on, |OAT-RAT| >= ${dmin.value.toFixed(1)} ${unit} · ${s.nIdent} samples`;
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
      const med = M.economizerSummary(per.flatMap((p) => p.rows.filter((r) => r.ident)));
      return `MAT - (RAT + damper% x (OAT - RAT)), fan on, identifiable · median ${med.medianResid == null ? "n/a" : ctx.dispDelta(med.medianResid, TEMP).value.toFixed(2)} ${unit}`;
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
    return { eq, ...M.basVsWeb(g.t, g.cols.bas, g.cols.web), g, web };
  }
  const BAS_ROLES = { required: ["oa_t", "web_oa_t"], optional: [] };

  rcxView({
    id: "bas-vs-web-oat", group: "Weather", title: "BAS vs web outdoor-air temperature",
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
      draw(ctx, el, { tooltip: { trigger: "axis" }, legend: { top: 0, data: ["Web OAT", "BAS oa_t", `+-${+half.toFixed(1)} band`] },
        grid: baseGrid({ bottom: 56 }), xAxis: { type: "time" },
        yAxis: { type: "value", name: unit, scale: true }, series }, lanes, "bas_vs_web_oat");
      const s = d.stats;
      return `${eqName(d.eq)} vs web · ${s.n} samples · bias ${ctx.dispDelta(s.bias, TEMP).value.toFixed(2)} ${ctx.dispDelta(0, TEMP).unit} · within band ${(s.withinBand * 100).toFixed(0)}%`;
    },
  });

  rcxView({
    id: "bas-vs-web-oat-hist", group: "Weather", title: "BAS vs web outdoor-air deviation",
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
