// Occupancy schedules for Open-FDD (read-only). One place decides "is this site occupied at time t",
// shared by the weekly-runtime schedule line, the after-hours split, synthesized `occ_mode` for
// rules, and the agent tools. Classic script (browser global `ofddSchedule`) and CommonJS, from one file
// (same pattern as units.js). No dependencies.
//
// Source of schedules: NF ScheduleManager, read only (never create / update / write back).
//   GET /api/v1/schedules?pageOffset=&pageSize=&hideEmpty=   -> { schedules: [Schedule], totalCount }
//   GET /api/v1/schedules/{uuid}                             -> { schedule: Schedule }
// Schedule (normalgw.hpl.v1.Schedule, REST JSON is camelCase; snake_case is accepted too):
//   uuid, name, layer, outOfService, defaultValue: Value,
//   weeklySchedule: { days: [DailySchedule x7] }     index 0 = Monday ... 6 = Sunday (BACnet order)
//   DailySchedule:  { timeValues: [{ time: {hour, minute, second}, value: Value }] }
//   specialEvents:  [{ name, priority, date: {year, month, day} | dateRange: {startDate, endDate}, timeValues }]
//   targets:        [{ pointUuid, layer }]            points the schedule writes (analytics only reads them)
//   Value: { boolean | unsigned | signed | real | double | null } - occupied = true or a number > 0.
// A schedule has no timezone: the site record carries `tz` / `timezone` and that is what we evaluate in.
//
// Normalized shape (everything below returns / accepts this; plain JSON, safe to cache):
//   { uuid, name, layer, source: "schedule" | "default", label, tz, defaultOcc: boolean,
//     weekly: [ [ {min, occ} ] x7 ],          steps per weekday (Mon=0), min = minutes after local midnight, sorted
//     events: [ { name, priority, date: [y,m,d] | null, range: [[y,m,d],[y,m,d]] | null, steps: [{min, occ}] } ],
//     targets: [ { pointUuid, layer } ], outOfService, hoursPerWeek }
// `source` is "schedule" (read from NF), "default" (the 4.x calendar) or "point" (a caller that used a
// real occupancy point's history instead; never produced here, see SOURCES).
//
// Semantics match the 4.x occupancySchedule.ts: occupied intervals are WALL-CLOCK blocks in the site
// timezone, so a DST change never resizes a 07:00-17:00 block (the elapsed week gets 1 h longer or
// shorter, the occupied hours stay 50). A step list is evaluated as "value of the last step at or before
// this time of day"; before the first step the schedule's default value applies (unoccupied if none).
// A special event whose date matches replaces the weekly day entirely (lowest `priority` number wins,
// missing priority = 16); an event with no steps is a closed (unoccupied) day.
(function (root) {
  "use strict";

  const SOURCES = ["schedule", "point", "default"];
  const DEFAULT_START_MIN = 7 * 60, DEFAULT_END_MIN = 17 * 60;
  const DEFAULT_LABEL = "schedule 50 h/week (default)";

  // ---- timezone helpers (Intl only; same code in Node and the browser) ----------------------
  const fmtCache = new Map();
  function fmt(tz) {
    let f = fmtCache.get(tz);
    if (!f) {
      f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
        hour: "numeric", minute: "numeric", second: "numeric" });
      fmtCache.set(tz, f);
    }
    return f;
  }
  const validTz = (tz) => { try { fmt(tz); return true; } catch (e) { return false; } };
  const tzOf = (tz) => (tz && validTz(tz) ? tz : "UTC");

  /** Civil date and time of an instant in `tz`: { y, m (1-12), d, h, mi, s, dow (Mon=0..Sun=6), minute (since midnight) }. */
  function localParts(ms, tz) {
    const o = {};
    for (const p of fmt(tzOf(tz)).formatToParts(new Date(ms))) if (p.type !== "literal") o[p.type] = Number(p.value);
    const dow = (new Date(Date.UTC(o.year, o.month - 1, o.day)).getUTCDay() + 6) % 7;
    return { y: o.year, m: o.month, d: o.day, h: o.hour % 24, mi: o.minute, s: o.second, dow, minute: (o.hour % 24) * 60 + o.minute + o.second / 60 };
  }

  /** The instant at which wall clocks in `tz` read y-m-d h:mi (a skipped DST hour maps to the instant after the jump). */
  function localToMs(y, m, d, h, mi, tz) {
    const zone = tzOf(tz);
    const wall = Date.UTC(y, m - 1, d, h || 0, mi || 0, 0);
    const off = (t) => { const p = localParts(t, zone); return Date.UTC(p.y, p.m - 1, p.d, p.h, p.mi, p.s) - t; };
    let t = wall - off(wall);
    t = wall - off(t);
    return t;
  }

  /** Monday 00:00 (wall clock in tz) of the civil week containing ms, as an instant. */
  function localWeekStartMs(ms, tz) {
    const p = localParts(ms, tz);
    const mon = new Date(Date.UTC(p.y, p.m - 1, p.d - p.dow));
    return localToMs(mon.getUTCFullYear(), mon.getUTCMonth() + 1, mon.getUTCDate(), 0, 0, tz);
  }

  // ---- normalization ----------------------------------------------------------------------
  const pick = (o, ...keys) => { for (const k of keys) if (o && o[k] !== undefined && o[k] !== null) return o[k]; return undefined; };

  /** NF Value -> occupied boolean (null when the value says nothing: null / missing). */
  function valueOcc(v) {
    if (v === undefined || v === null) return null;
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v > 0;
    if (typeof v === "string") { const s = v.trim().toLowerCase(); return s === "true" || s === "occupied" || s === "1" ? true : s === "false" || s === "unoccupied" || s === "0" ? false : null; }
    if (v.null) return null;
    for (const k of ["boolean", "enumerated", "unsigned", "signed", "real", "double"]) {
      if (v[k] !== undefined && v[k] !== null) return typeof v[k] === "boolean" ? v[k] : Number(v[k]) > 0;
    }
    return null;
  }

  function stepMinute(t) {
    if (!t) return null;
    if (typeof t === "string") { const m = /^(\d{1,2}):(\d{2})/.exec(t.trim()); return m ? Number(m[1]) * 60 + Number(m[2]) : null; }
    const h = Number(t.hour || 0), mi = Number(t.minute || 0), s = Number(t.second || 0);
    return h * 60 + mi + s / 60;
  }

  function normSteps(list) {
    const steps = [];
    for (const tv of list || []) {
      const min = stepMinute(tv && tv.time), occ = valueOcc(tv && tv.value);
      if (min == null || occ == null) continue;
      steps.push({ min, occ });
    }
    return steps.sort((a, b) => a.min - b.min);
  }

  function normDate(d) {
    if (!d) return null;
    if (typeof d === "string") { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d); return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null; }
    const y = Number(d.year || 0), m = Number(d.month || 0), day = Number(d.day || 0);
    if (!y && !m && !day) return null;
    return [y, m, day];       // 0 / 255 style wildcards: year 0 = every year, month 0 = every month
  }

  /** wildcard-aware compare of a civil date [y,m,d] against a pattern: -1 / 0 / 1 (pattern vs date). */
  function cmpDate(pat, y, m, d) {
    const a = [pat[0] || y, pat[1] && pat[1] <= 12 ? pat[1] : m, pat[2] && pat[2] <= 31 ? pat[2] : d], b = [y, m, d];
    for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
    return 0;
  }

  function normEvent(e) {
    const rng = pick(e, "dateRange", "date_range");
    const range = rng ? [normDate(pick(rng, "startDate", "start_date")), normDate(pick(rng, "endDate", "end_date"))] : null;
    const start = pick(e, "startDate", "start_date"), end = pick(e, "endDate", "end_date");   // flat form from the brief
    const flat = start || end ? [normDate(start), normDate(end || start)] : null;
    const r = range && range[0] && range[1] ? range : flat && flat[0] && flat[1] ? flat : null;
    const date = normDate(e.date);
    if (!date && !r) return null;
    const pr = Number(e.priority);
    return { name: e.name || "", priority: pr > 0 ? pr : 16, date, range: r, steps: normSteps(pick(e, "timeValues", "time_values")) };
  }

  const dayMinutes = (steps, defaultOcc) => {
    // occupied minutes in one civil day for a step list
    let occ = defaultOcc, prev = 0, total = 0;
    for (const s of steps) { if (occ) total += s.min - prev; occ = s.occ; prev = s.min; }
    if (occ) total += 1440 - prev;
    return total;
  };

  const hoursOfWeekly = (weekly, defaultOcc) => Math.round(weekly.reduce((a, d) => a + dayMinutes(d, defaultOcc), 0) / 6) / 10;

  /** Raw NF Schedule -> normalized (see header). Returns null for something that is not a schedule. */
  function normalizeSchedule(raw) {
    if (!raw || typeof raw !== "object") return null;
    const ws = pick(raw, "weeklySchedule", "weekly_schedule");
    const days = (ws && ws.days) || [];
    const weekly = Array.from({ length: 7 }, (_, i) => normSteps(days[i] && pick(days[i], "timeValues", "time_values")));
    const defaultOcc = valueOcc(pick(raw, "defaultValue", "default_value")) === true;
    const events = (pick(raw, "specialEvents", "special_events") || []).map(normEvent).filter(Boolean);
    const targets = (raw.targets || []).map((t) => ({ pointUuid: pick(t, "pointUuid", "point_uuid") || "", layer: t.layer || "" })).filter((t) => t.pointUuid);
    const s = { uuid: raw.uuid || "", name: raw.name || "", layer: raw.layer || "", source: "schedule", label: "", tz: null,
      defaultOcc, weekly, events, targets, outOfService: !!pick(raw, "outOfService", "out_of_service"), hoursPerWeek: hoursOfWeekly(weekly, defaultOcc) };
    s.label = labelOf(s);
    return s;
  }

  /** The 4.x default calendar: Monday-Friday 07:00-17:00 = 50 h/week. */
  function defaultSchedule(tz) {
    const day = [{ min: DEFAULT_START_MIN, occ: true }, { min: DEFAULT_END_MIN, occ: false }];
    const weekly = [day, day, day, day, day, [], []];
    return { uuid: "", name: "default", layer: "", source: "default", label: DEFAULT_LABEL, tz: tz || null, defaultOcc: false,
      weekly, events: [], targets: [], outOfService: false, hoursPerWeek: 50 };
  }

  function labelOf(s) {
    if (s.source === "default") return DEFAULT_LABEL;
    const where = [s.tz, s.name ? `NF schedule "${s.name}"` : "NF schedule"].filter(Boolean).join(", ");
    return `schedule ${s.hoursPerWeek} h/week (${where})`;
  }
  const withTz = (s, tz) => { const c = { ...s, tz: tz || s.tz || null }; c.label = labelOf(c); return c; };

  // ---- loading (read only) ----------------------------------------------------------------
  /**
   * Every NF schedule, normalized. `api(path)` is nf.js `api` (GET, parsed JSON). Pages through
   * /api/v1/schedules; a list item with no weekly rules and no events is fetched by uuid in case the
   * list omitted details. A server without ScheduleManager (HTTP error) yields [].
   * @param {(path: string) => Promise<any>} api
   * @returns {Promise<any[]>}
   */
  async function loadSchedules(api) {
    const size = 100, raw = [];
    try {
      for (let offset = 0; ; offset += size) {
        const page = await api(`/api/v1/schedules?pageOffset=${offset}&pageSize=${size}`);
        const items = (page && page.schedules) || [];
        raw.push(...items);
        const total = Number(page && page.totalCount);
        if (items.length < size || (total > 0 && raw.length >= total)) break;
      }
    } catch (e) { return []; }
    const full = await Promise.all(raw.map(async (r) => {
      const has = pick(r, "weeklySchedule", "weekly_schedule") || (pick(r, "specialEvents", "special_events") || []).length;
      if (has || !r.uuid) return r;
      try { const g = await api(`/api/v1/schedules/${encodeURIComponent(r.uuid)}`); return (g && g.schedule) || r; } catch (e) { return r; }
    }));
    return full.map(normalizeSchedule).filter(Boolean);
  }

  // ---- binding ----------------------------------------------------------------------------
  const markersOf = (a) => String((a && a.markers) || "").split(",").map((x) => x.trim()).filter(Boolean);
  const idOfRec = (r) => (r.attrs && r.attrs.id) || r.name;
  const siteTz = (rec) => (rec && rec.attrs && (rec.attrs.tz || rec.attrs.timezone)) || null;

  /** A point (model.js toPoint() or a raw NF record) that says "occupied": markers occ / occupied, or a class containing "occupied". */
  function isOccPoint(p) {
    const tags = p.tags || markersOf(p.attrs || (p.rec && p.rec.attrs));
    const cls = String(p.cls || (p.attrs && p.attrs.class) || (p.rec && p.rec.attrs && p.rec.attrs.class) || "").toLowerCase();
    return tags.includes("occ") || tags.includes("occupied") || cls.includes("occupied");
  }
  const siteOf = (p) => p.siteRef || (p.attrs && p.attrs.siteRef) || (p.rec && p.rec.attrs && p.rec.attrs.siteRef) || "";

  /**
   * The schedule for one site, or null (caller then uses defaultSchedule()).
   *   1. a schedule whose targets include an occupancy point (markers occ|occupied, class ~ occupied) of that site;
   *   2. else the schedule a site attribute names (attrs.scheduleRef | occScheduleRef | scheduleUuid, by uuid or name);
   *   3. else null.
   * Out-of-service schedules are skipped. Among several matches the one with the most targets on that site's
   * occupancy points wins, then the lowest uuid (deterministic). The result carries the site timezone.
   * @param {any[]} schedules normalized (loadSchedules) @param {{sites?: any[], points?: any[]}} model @param {string} siteRef Haystack site id
   */
  function pickSiteSchedule(schedules, model, siteRef) {
    const list = (schedules || []).filter((s) => s && !s.outOfService);
    const site = ((model && model.sites) || []).find((r) => idOfRec(r) === siteRef);
    const tz = siteTz(site);
    const occ = new Set(((model && model.points) || []).filter((p) => siteOf(p) === siteRef && isOccPoint(p)).map((p) => p.uuid));
    const score = (s) => s.targets.filter((t) => occ.has(t.pointUuid)).length;
    const bound = list.filter((s) => score(s) > 0).sort((a, b) => score(b) - score(a) || String(a.uuid).localeCompare(String(b.uuid)));
    if (bound.length) return withTz(bound[0], tz);
    const a = (site && site.attrs) || {};
    const ref = a.scheduleRef || a.occScheduleRef || a.scheduleUuid;
    if (ref) { const s = list.find((x) => x.uuid === ref) || list.find((x) => x.name === ref); if (s) return withTz(s, tz); }
    return null;
  }

  // ---- evaluation -------------------------------------------------------------------------
  function matchEvent(s, y, m, d) {
    let best = null;
    for (const e of s.events || []) {
      const hit = e.date ? cmpDate(e.date, y, m, d) === 0 : cmpDate(e.range[0], y, m, d) <= 0 && cmpDate(e.range[1], y, m, d) >= 0;
      if (hit && (!best || e.priority < best.priority)) best = e;
    }
    return best;
  }

  /** Steps in force on a civil day ([] with `closed` for a holiday-style event without steps). */
  function daySteps(s, y, m, d, dow) {
    const e = matchEvent(s, y, m, d);
    if (e) return e.steps.length ? { steps: e.steps, closed: false } : { steps: [], closed: true };
    return { steps: s.weekly[dow] || [], closed: false };
  }

  function occAt(s, minute, y, m, d, dow) {
    const { steps, closed } = daySteps(s, y, m, d, dow);
    if (closed) return false;
    let occ = s.defaultOcc;
    for (const st of steps) { if (st.min <= minute) occ = st.occ; else break; }
    return occ;
  }

  /** Occupied at instant tsMs? Wall clock in `tz` (default: the schedule's tz, else UTC). */
  function occupied(schedule, tsMs, tz) {
    const s = schedule || defaultSchedule(), p = localParts(tsMs, tz || s.tz);
    return occAt(s, p.minute, p.y, p.m, p.d, p.dow);
  }

  const meta = (arr, s, tz) => {
    Object.defineProperties(arr, { source: { value: s.source }, label: { value: s.label }, tz: { value: tzOf(tz || s.tz) } });
    return arr;
  };

  /**
   * [[ms, 0|1]] every stepSec from startMs (inclusive) to endMs (exclusive); a sample is the occupancy
   * at that instant. The array also carries non-enumerable `source`, `label`, `tz`.
   */
  function occupancySeries(schedule, startMs, endMs, stepSec, tz) {
    const s = schedule || defaultSchedule(), step = Math.max(1, stepSec || 300) * 1000, out = [];
    for (let t = startMs; t < endMs; t += step) out.push([t, occupied(s, t, tz) ? 1 : 0]);
    return meta(out, s, tz);
  }

  /**
   * Occupied hours in the ISO week that starts at isoWeekStartMs, special events (holidays) included.
   * Wall-clock: the week's seven civil days are summed, so a DST week still gives 50 for 07:00-17:00 Mon-Fri.
   * isoWeekStartMs is any instant of "Monday 00:00" (UTC or the site's zone; it snaps to the nearest civil
   * Monday within +-12 h). tz is accepted for symmetry and the result label.
   */
  function weeklyScheduleHours(schedule, isoWeekStartMs, tz) {
    return weeklyScheduleInfo(schedule, isoWeekStartMs, tz).hours;
  }

  /** weeklyScheduleHours plus provenance: { hours, source, label, tz, holidays: [civil dates [y,m,d] of closed or changed days] }. */
  function weeklyScheduleInfo(schedule, isoWeekStartMs, tz) {
    const s = schedule || defaultSchedule();
    const base = new Date(isoWeekStartMs + 12 * 3600e3);
    const monday = Date.UTC(base.getUTCFullYear(), base.getUTCMonth(), base.getUTCDate());
    let minutes = 0;
    const changed = [];
    for (let i = 0; i < 7; i++) {
      const c = new Date(monday + i * 86400e3), y = c.getUTCFullYear(), m = c.getUTCMonth() + 1, d = c.getUTCDate();
      const { steps, closed } = daySteps(s, y, m, d, i);
      if (matchEvent(s, y, m, d)) changed.push([y, m, d]);
      if (!closed) minutes += dayMinutes(steps, s.defaultOcc);
    }
    return { hours: Math.round(minutes / 6) / 10, source: s.source, label: s.label, tz: tzOf(tz || s.tz), holidays: changed };
  }

  const api = { SOURCES, DEFAULT_LABEL, loadSchedules, normalizeSchedule, pickSiteSchedule, defaultSchedule, occupied, occupancySeries,
    weeklyScheduleHours, weeklyScheduleInfo, isOccPoint, localParts, localToMs, localWeekStartMs, labelOf };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ofddSchedule = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
