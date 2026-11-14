// Weekly occupancy calendar for Open-FDD (5.0.20): the site's occupied hours, edited on the Overview and saved per site
// with the tuning settings (fdd.rule_config, rule_id OCC-CALENDAR, scope "site"). Classic script (browser global
// `ofddOccupancy`) and CommonJS from one file, like schedule.js. No dependencies.
//
// Document (SI-free, wall clock in the site zone):
//   { timezone: "America/Chicago", days: { mon: { occupied: true, start: "06:00", end: "18:00" }, ..., sun: {...} } }
// Defaults: Mon-Fri occupied 06:00-18:00, Sat/Sun unoccupied = 60 h/week (open_fdd.analytics.occupancy.OccupancySchedule).
//
// Bare-minimum occupied hours per week = sum over occupied days of (end - start); end <= start wraps past midnight:
// (24 h - start) + end. Same arithmetic as open_fdd.analytics.occupancy.occupied_hours_per_week (Python), so the
// Overview line, the API payload and the pandas side agree. The weekly runtime charts draw it as the reference line.
(function (root) {
  "use strict";

  const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const DAY_LABELS = { mon: "Monday", tue: "Tuesday", wed: "Wednesday", thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday" };
  const RULE_ID = "OCC-CALENDAR";
  const DEFAULT_TZ = "America/Chicago";
  const HHMM = /^([01]?\d|2[0-3]):([0-5]\d)$/;

  /** "HH:MM" -> minutes after midnight; null when not a valid 24 h time. */
  function minutesOf(text) {
    const m = HHMM.exec(String(text == null ? "" : text).trim());
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }
  const hhmm = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
  const validTz = (tz) => { try { new Intl.DateTimeFormat("en-US", { timeZone: tz }); return true; } catch (e) { return false; } };

  /** The default calendar (a fresh object): Mon-Fri 06:00-18:00 occupied, Sat/Sun not. */
  function defaultCalendar(tz) {
    const days = {};
    for (const d of DAYS) days[d] = { occupied: d !== "sat" && d !== "sun", start: "06:00", end: "18:00" };
    return { timezone: tz && validTz(tz) ? tz : DEFAULT_TZ, days };
  }

  /**
   * A stored / posted calendar -> the canonical document. Missing days or fields take the defaults (like the Python
   * from_dict); a bad time or zone is an error (never silently replaced), so a Save cannot store garbage.
   * @param {any} raw @param {{ tz?: string }} [opts]
   */
  function normalizeCalendar(raw, opts = {}) {
    const def = defaultCalendar(opts.tz);
    if (raw == null) return def;
    if (typeof raw !== "object" || Array.isArray(raw)) throw new Error("occupancy calendar must be an object");
    const tz = raw.timezone == null || raw.timezone === "" ? def.timezone : String(raw.timezone);
    if (!validTz(tz)) throw new Error(`unknown timezone ${tz}`);
    const rawDays = raw.days || {};
    if (typeof rawDays !== "object" || Array.isArray(rawDays)) throw new Error("days must be an object keyed mon..sun");
    for (const k of Object.keys(rawDays)) if (!DAYS.includes(k)) throw new Error(`unknown day ${k} (mon..sun)`);
    const days = {};
    for (const d of DAYS) {
      const r = rawDays[d] || {}, base = def.days[d];
      const occupied = r.occupied == null ? base.occupied : r.occupied === true || r.occupied === "true";
      const out = {};
      for (const f of ["start", "end"]) {
        const v = r[f] == null || r[f] === "" ? base[f] : r[f];
        const min = minutesOf(v);
        if (min == null) throw new Error(`${d}.${f} must be HH:MM (24 h), got ${JSON.stringify(v)}`);
        out[f] = hhmm(min);
      }
      days[d] = { occupied, start: out.start, end: out.end };
    }
    return { timezone: tz, days };
  }

  /** Occupied hours of one day row (0 when unoccupied); end <= start wraps past midnight. */
  function dayHours(row) {
    if (!row || !row.occupied) return 0;
    const s = minutesOf(row.start), e = minutesOf(row.end);
    if (s == null || e == null) return 0;
    return (e <= s ? 24 * 60 - s + e : e - s) / 60;
  }

  /** Bare-minimum occupied hours per week (the Python occupied_hours_per_week). */
  function occupiedHoursPerWeek(cal) {
    const c = cal || defaultCalendar();
    let total = 0;
    for (const d of DAYS) total += dayHours(c.days && c.days[d]);
    return Math.round(total * 100) / 100;
  }

  /**
   * The calendar as a schedule.js schedule (source "calendar"), so occupied(), weeklyScheduleInfo() and the after-hours
   * split work unchanged. A wrapping day spills into the next day's early hours (Sunday into Monday). hoursPerWeek and
   * every week's hours are the bare-minimum figure above (the calendar has no holidays).
   */
  function calendarSchedule(cal) {
    const c = normalizeCalendar(cal);
    const masks = DAYS.map(() => new Uint8Array(1440));
    DAYS.forEach((d, i) => {
      const r = c.days[d];
      if (!r.occupied) return;
      const s = minutesOf(r.start), e = minutesOf(r.end);
      if (e > s) { masks[i].fill(1, s, e); return; }
      masks[i].fill(1, s, 1440);
      masks[(i + 1) % 7].fill(1, 0, e);
    });
    const weekly = masks.map((m) => {
      const steps = [];
      let prev = 0;
      for (let min = 0; min < 1440; min++) if (m[min] !== prev) { steps.push({ min, occ: m[min] === 1 }); prev = m[min]; }
      return steps;
    });
    const hours = occupiedHoursPerWeek(c);
    return { uuid: "", name: "occupancy calendar", layer: "", source: "calendar", tz: c.timezone, defaultOcc: false, weekly,
      events: [], targets: [], outOfService: false, hoursPerWeek: hours, calendar: c,
      label: `occupancy calendar ${+hours.toFixed(2)} h/week (${c.timezone})` };
  }

  /** Validate an OCC-CALENDAR override document { version: 1, calendar } for the tuning hook. */
  function normalizeCalendarOverride(doc) {
    if (!doc || typeof doc !== "object" || Array.isArray(doc)) throw new Error("overrides must be { version: 1, calendar: {...} }");
    if (doc.version !== 1) throw new Error("overrides.version must be 1");
    return { version: 1, calendar: normalizeCalendar(doc.calendar) };
  }

  const api = { DAYS, DAY_LABELS, RULE_ID, DEFAULT_TZ, minutesOf, defaultCalendar, normalizeCalendar, dayHours, occupiedHoursPerWeek,
    calendarSchedule, normalizeCalendarOverride };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.ofddOccupancy = api;
})(typeof globalThis !== "undefined" ? globalThis : this);