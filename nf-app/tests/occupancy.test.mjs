// node --test nf-app/tests/occupancy.test.mjs - the weekly occupancy calendar (static/occupancy.js, 5.0.20): the
// bare-minimum occupied hours per week (same arithmetic as open_fdd.analytics.occupancy.occupied_hours_per_week), the
// stored document's validation, the schedule it becomes (wall clock in the site zone, DST and partial weeks), and the
// Overview: the weekly runtime chart exists only when the model has an AHU / fan.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import { dashboardModel } from "./fixtures/dashboard_model.mjs";

const require = createRequire(import.meta.url);
const O = require("../static/occupancy.js");
const S = require("../static/schedule.js");
const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));

test("hours: default Mon-Fri 06:00-18:00 = 60; all unoccupied = 0; end <= start wraps past midnight", () => {
  assert.equal(O.occupiedHoursPerWeek(O.defaultCalendar()), 60);
  const off = O.defaultCalendar();
  for (const d of O.DAYS) off.days[d].occupied = false;
  assert.equal(O.occupiedHoursPerWeek(off), 0);
  assert.equal(O.dayHours({ occupied: true, start: "22:00", end: "06:00" }), 8);
  assert.equal(O.dayHours({ occupied: true, start: "18:30", end: "18:30" }), 24, "end == start is a full day (wraps)");
  assert.equal(O.dayHours({ occupied: true, start: "07:15", end: "16:45" }), 9.5);
  const night = O.defaultCalendar();
  night.days.sun = { occupied: true, start: "22:00", end: "06:00" };
  assert.equal(O.occupiedHoursPerWeek(night), 68);
});

test("document: missing days / fields take the defaults; bad times, days and zones are errors", () => {
  const c = O.normalizeCalendar({ timezone: "Europe/Berlin", days: { sat: { occupied: true, start: "8:00", end: "12:00" } } });
  assert.equal(c.timezone, "Europe/Berlin");
  assert.deepEqual(c.days.sat, { occupied: true, start: "08:00", end: "12:00" });
  assert.deepEqual(c.days.mon, { occupied: true, start: "06:00", end: "18:00" });
  assert.deepEqual(c.days.sun, { occupied: false, start: "06:00", end: "18:00" });
  assert.throws(() => O.normalizeCalendar({ days: { mon: { start: "24:00" } } }), /mon\.start must be HH:MM/);
  assert.throws(() => O.normalizeCalendar({ days: { funday: {} } }), /unknown day funday/);
  assert.throws(() => O.normalizeCalendar({ timezone: "Mars/Olympus" }), /unknown timezone/);
  assert.throws(() => O.normalizeCalendarOverride({ version: 2, calendar: {} }), /version must be 1/);
  assert.deepEqual(O.normalizeCalendarOverride({ version: 1, calendar: c }), { version: 1, calendar: c }, "round trip");
});

test("the calendar as a schedule: wall clock in the site zone, Sunday night spills into Monday", () => {
  const cal = O.defaultCalendar("America/Chicago");
  cal.days.sun = { occupied: true, start: "22:00", end: "06:00" };
  const s = O.calendarSchedule(cal);
  assert.equal(s.source, "calendar");
  assert.equal(s.hoursPerWeek, 68);
  const at = (iso) => S.occupied(s, Date.parse(iso), "America/Chicago");
  assert.equal(at("2026-11-16T11:59:00Z"), true, "Mon 05:59 CST: Sunday's shift");
  assert.equal(at("2026-11-17T11:59:00Z"), false, "Tue 05:59 CST: closed");
  assert.equal(at("2026-11-17T12:00:00Z"), true, "Tue 06:00 CST: open");
  assert.equal(at("2026-11-18T00:00:00Z"), false, "Tue 18:00 CST: closed");
});

test("weekly bucketing in the site zone: DST weeks keep the calendar's hours; a partial week is flagged", () => {
  const tz = "America/Chicago", s = O.calendarSchedule(O.defaultCalendar(tz));
  for (const iso of ["2026-03-04T12:00:00Z", "2026-10-28T12:00:00Z", "2026-11-09T12:00:00Z"]) {       // spring-forward, fall-back, normal
    const k = S.localWeekStartMs(Date.parse(iso), tz);
    assert.equal(S.weeklyScheduleInfo(s, k, tz).hours, 60, `${iso}: 60 h (wall clock)`);
  }
  // spring-forward week is 167 elapsed hours: Monday 00:00 CDT is the bucket start
  const k = S.localWeekStartMs(Date.parse("2026-03-04T12:00:00Z"), tz), next = S.localWeekStartMs(k + 8 * 86400e3, tz);
  assert.equal((next - k) / 3600e3, 167);
  // a runtime series over 9 days starting Wednesday: the first week is partial, the second complete
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, Intl, localStorage: { getItem: () => "si" } });
  for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "schedule.js", "occupancy.js", "charts.js", "rcx.js", "rcx-overview.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  const M = vm.runInContext("rcxOverviewMath", ctx);
  const t0 = Date.parse("2026-11-04T06:00:00Z"), t = [], v = [];
  for (let i = 0; i < 12 * 24 * 12; i++) { t.push(t0 + i * 300e3); v.push(1); }
  let cur = 0, lo = Infinity, hi = -Infinity;
  const weekOf = (ms) => { if (ms >= lo && ms < hi) return cur; cur = S.localWeekStartMs(ms, tz); lo = cur; hi = S.localWeekStartMs(cur + 8 * 86400e3, tz); return cur; };
  const weeks = M.weeklyRuntime(t, v, { duty: false, gapMaxSec: 900, weekOf, occ: (ms) => S.occupied(s, ms, tz) });
  const ks = [...weeks.keys()].sort((a, b) => a - b);
  assert.equal(new Date(ks[0]).toISOString(), "2026-11-02T06:00:00.000Z", "Monday 00:00 CST");
  assert.equal(weeks.get(ks[0]).partial, true);
  assert.equal(weeks.get(ks[1]).partial, false);
  assert.ok(Math.abs(weeks.get(ks[1]).inHours - 60) < 1e-6, "a full always-on week: 60 h in schedule");
});

test("Overview: the weekly runtime chart shows with an AHU / fan and is hidden without one", () => {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, Intl, localStorage: { getItem: () => "si" } });
  ctx.FAULT_LANE = {}; ctx.pickWindow = () => 3600; ctx.ofddChart = () => ({}); ctx.ofddRender = () => {};
  for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "schedule.js", "occupancy.js", "charts.js", "rcx.js", "plot-spec-data.js", "fdd-plots.js", "rcx-overview.js", "rcx-presets.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  const plan = (filter) => {
    const { records, points } = dashboardModel({ plant: "full" });
    const keep = records.filter(filter), ids = new Set(keep.filter((r) => r.pointType === "EQUIPMENT").map((r) => r.attrs.id));
    const pts = points.filter((p) => !p.attrs.equipRef || ids.has(p.attrs.equipRef));
    const model = { sites: keep.filter((r) => r.pointType === "SITE"), equips: keep.filter((r) => r.pointType === "EQUIPMENT"), devices: [], points: pts.map(vm.runInContext("toPoint", ctx)) };
    return new Set(Array.from(vm.runInContext("rcxPlan", ctx)(model.equips, model, catalog, { tab: "rcx", single: false }).ready, (x) => x.view.id));
  };
  assert.ok(plan(() => true).has("weekly-fan"));
  const noAhu = plan((r) => !(r.pointType === "EQUIPMENT" && /^AHU/.test(r.attrs.id)));
  assert.ok(![...noAhu].some((id) => /^weekly-fan/.test(id)), "no AHU: no weekly fan chart");
});
test("a shift that wraps into the next day's shift is rejected (no double-counted hours)", () => {
  const days = { mon: { occupied: true, start: "22:00", end: "10:00" }, tue: { occupied: true, start: "06:00", end: "18:00" },
    wed: { occupied: false }, thu: { occupied: false }, fri: { occupied: false }, sat: { occupied: false }, sun: { occupied: false } };
  assert.throws(() => O.normalizeCalendar({ timezone: "America/Chicago", days }), /mon 22:00-10:00 runs into tue 06:00-18:00/);
  days.mon.end = "06:00";                                   // ends exactly when Tuesday starts: fine
  const cal = O.normalizeCalendar({ timezone: "America/Chicago", days });
  assert.equal(O.occupiedHoursPerWeek(cal), 20);
  assert.equal(O.calendarSchedule(cal).hoursPerWeek, 20);
  days.tue.occupied = false; days.mon.end = "10:00";        // nothing to collide with
  assert.equal(O.occupiedHoursPerWeek(O.normalizeCalendar({ timezone: "America/Chicago", days })), 12);
});
