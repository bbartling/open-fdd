// node --test nf-app/tests/schedule.test.mjs: occupancy schedules (static/schedule.js) + the two-site fixture truth.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { twoSite as fx, TRUTH, wall, hoursOn, coolingBins, confirmedLane, rollingFaultPct, cmd1, resample, pickWindow, fetchSeriesStub, fakeSdkHttp, seriesOf } from "./fixtures/two_site.mjs";

const require = createRequire(import.meta.url);
const S = require("../static/schedule.js");
const U = require("../static/units.js");
const A = fx.sites["site-a"], B = fx.sites["site-b"];
const near = (a, b, msg, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${msg}: ${a} vs ${b}`);

const schedA = () => S.pickSiteSchedule(fx.schedules.map(S.normalizeSchedule), fx.model, "site-a");

// ---- default calendar ----------------------------------------------------------------------------
test("default calendar: Mon-Fri 07:00-17:00 = 50 h/week, labelled as the default", () => {
  const d = S.defaultSchedule("America/Chicago");
  assert.equal(d.source, "default");
  assert.equal(d.label, "schedule 50 h/week (default)");
  assert.equal(d.hoursPerWeek, 50);
  const mon = wall(2026, 10, 12, 0, 0, "America/Chicago");
  assert.equal(S.weeklyScheduleHours(d, mon, "America/Chicago"), 50);
  assert.equal(S.weeklyScheduleInfo(d, mon).source, "default");
  const at = (h, mi, dow = 0) => wall(2026, 10, 12 + dow, h, mi, "America/Chicago");
  assert.equal(S.occupied(d, at(6, 59), "America/Chicago"), false);
  assert.equal(S.occupied(d, at(7, 0), "America/Chicago"), true);
  assert.equal(S.occupied(d, at(16, 59), "America/Chicago"), true);
  assert.equal(S.occupied(d, at(17, 0), "America/Chicago"), false, "end is exclusive");
  assert.equal(S.occupied(d, at(10, 0, 5), "America/Chicago"), false, "Saturday");
  assert.equal(S.occupied(null, at(10, 0), "America/Chicago"), true, "no schedule = default");
});

// ---- NF shape -> normalized ----------------------------------------------------------------------
test("normalizeSchedule reads the NF ScheduleManager JSON (camelCase and snake_case)", () => {
  const s = S.normalizeSchedule(fx.schedules[0]);
  assert.equal(s.source, "schedule");
  assert.equal(s.hoursPerWeek, 50);
  assert.deepEqual(s.weekly[0], [{ min: 420, occ: true }, { min: 1020, occ: false }]);
  assert.deepEqual(s.weekly[5], []);
  assert.equal(s.events.length, 1);
  assert.deepEqual(s.events[0].date, [2026, 10, 22]);
  assert.deepEqual(s.targets, [{ pointUuid: A.points.occ.uuid, layer: "default" }]);
  const snake = S.normalizeSchedule({ uuid: "x", name: "n", default_value: { boolean: false },
    weekly_schedule: { days: [{ time_values: [{ time: { hour: 8 }, value: { boolean: true } }, { time: { hour: 12 }, value: { boolean: false } }] }] },
    special_events: [{ name: "closure", start_date: { year: 2026, month: 12, day: 24 }, end_date: { year: 2026, month: 12, day: 26 }, time_values: [] }],
    targets: [{ point_uuid: "p1", layer: "default" }] });
  assert.equal(snake.hoursPerWeek, 4);
  assert.deepEqual(snake.targets, [{ pointUuid: "p1", layer: "default" }]);
  assert.deepEqual(snake.events[0].range, [[2026, 12, 24], [2026, 12, 26]]);
  assert.equal(S.occupied(snake, wall(2026, 12, 25, 9, 0, "UTC"), "UTC"), false, "inside the date range = closed");
  assert.equal(S.occupied(snake, wall(2026, 12, 28, 9, 0, "UTC"), "UTC"), true, "Monday 28th is a normal Monday");
  assert.equal(S.normalizeSchedule(null), null);
});

test("a numeric Value > 0 is occupied; before the first step the default value applies; priority picks the event", () => {
  const raw = { uuid: "u", name: "num", defaultValue: { unsigned: 0 },
    weeklySchedule: { days: [{ timeValues: [{ time: { hour: 9 }, value: { unsigned: 1 } }, { time: { hour: 11 }, value: { unsigned: 0 } }] }] },
    specialEvents: [
      { name: "low", date: { year: 2026, month: 10, day: 12 }, priority: 10, timeValues: [{ time: { hour: 6 }, value: { boolean: true } }] },
      { name: "high", date: { year: 2026, month: 10, day: 12 }, priority: 2, timeValues: [{ time: { hour: 13 }, value: { boolean: true } }, { time: { hour: 14 }, value: { boolean: false } }] }] };
  const s = S.normalizeSchedule(raw), at = (h) => wall(2026, 10, 12, h, 0, "UTC");
  assert.equal(S.occupied(s, at(10), "UTC"), false, "event priority 2 replaces the weekly day");
  assert.equal(S.occupied(s, at(8), "UTC"), false, "before the first event step = default");
  assert.equal(S.occupied(s, at(13), "UTC"), true);
  assert.equal(S.occupied(s, wall(2026, 10, 19, 10, 0, "UTC"), "UTC"), true, "next Monday uses the weekly steps");
});

// ---- wall-clock evaluation, holiday, DST ---------------------------------------------------------
test("occupied() is wall-clock in the site timezone; the same schedule differs by zone", () => {
  const s = schedA();
  assert.equal(s.tz, "America/Chicago");
  const monCdt = Date.UTC(2026, 9, 12, 12, 0);          // 07:00 CDT
  assert.equal(S.occupied(s, monCdt), true);
  assert.equal(S.occupied(s, monCdt - 60000), false);
  assert.equal(S.occupied(s, monCdt, "America/New_York"), true, "08:00 EDT is inside 07-17 as well");
  assert.equal(S.occupied(s, Date.UTC(2026, 9, 12, 11, 30), "America/New_York"), true, "07:30 EDT");
  assert.equal(S.occupied(s, Date.UTC(2026, 9, 12, 21, 30), "America/Chicago"), true, "16:30 CDT");
  assert.equal(S.occupied(s, Date.UTC(2026, 9, 12, 22, 0), "America/Chicago"), false, "17:00 CDT");
});

test("special_events holiday is unoccupied; the weekly hours of that week drop by the block", () => {
  const s = schedA(), tz = "America/Chicago";
  assert.equal(S.occupied(s, wall(2026, 10, 22, 10, 0, tz), tz), false, "Thursday holiday");
  assert.equal(S.occupied(s, wall(2026, 10, 21, 10, 0, tz), tz), true, "Wednesday");
  assert.equal(S.occupied(s, wall(2026, 10, 23, 10, 0, tz), tz), true, "Friday");
  const wk = A.weekStarts.map((ms) => S.weeklyScheduleHours(s, ms, tz));
  assert.deepEqual(wk, [50, 40, 50, 50]);
  const info = S.weeklyScheduleInfo(s, A.weekStarts[1], tz);
  assert.deepEqual(info.holidays, [[2026, 10, 22]]);
  assert.equal(info.source, "schedule");
  assert.match(info.label, /^schedule 50 h\/week \(America\/Chicago, NF schedule "site-a occupancy"\)$/);
});

test("DST week keeps 07:00-17:00 wall clock: 50 h, not 49 or 51 (US fall-back week of 2026-10-26)", () => {
  for (const [tz, site] of [["America/Chicago", A], ["America/New_York", B]]) {
    const start = site.weekStarts[2], next = site.weekStarts[3];
    assert.equal(S.localWeekStartMs(start + 3 * 86400e3, tz), start, "week start = local Monday 00:00");
    assert.equal((next - start) / 3600e3, 169, "the elapsed week is 1 h longer, " + tz);
    const sched = S.normalizeSchedule(fx.schedules[0]);
    assert.equal(S.weeklyScheduleHours(sched, start, tz), 50);
    assert.equal(S.weeklyScheduleHours(S.defaultSchedule(tz), start, tz), 50);
    // the same answer for a UTC "Monday 00:00" and for the zone's own Monday 00:00
    assert.equal(S.weeklyScheduleHours(sched, Date.UTC(2026, 9, 26), tz), 50);
    // sample the real week: occupied sample-hours = 50 as well
    const series = S.occupancySeries(sched, start, next, 300, tz);
    near(series.reduce((a, [, o]) => a + o, 0) * 300 / 3600, 50, "sampled occupied hours " + tz);
    assert.equal(series.length, 169 * 12);
  }
  // 07:00 local is 12:00Z before the change and 13:00Z after it
  const d = S.defaultSchedule("America/Chicago");
  assert.equal(S.occupied(d, Date.UTC(2026, 9, 30, 12, 0)), true, "Fri 07:00 CDT");
  assert.equal(S.occupied(d, Date.UTC(2026, 9, 30, 11, 59)), false);
  assert.equal(S.occupied(d, Date.UTC(2026, 10, 2, 13, 0)), true, "Mon 07:00 CST");
  assert.equal(S.occupied(d, Date.UTC(2026, 10, 2, 12, 59)), false, "06:59 CST");
  // the 25 h Sunday of the change (weekend) stays unoccupied end to end
  const sunday = S.occupancySeries(d, wall(2026, 11, 1, 0, 0, "America/Chicago"), wall(2026, 11, 2, 0, 0, "America/Chicago"), 300, "America/Chicago");
  assert.equal(sunday.length, 25 * 12);
  assert.ok(sunday.every(([, o]) => o === 0));
});

test("localParts / localToMs round-trip around DST", () => {
  const tz = "America/Chicago";
  for (const [y, m, d, h, mi] of [[2026, 10, 12, 7, 0], [2026, 11, 2, 7, 0], [2026, 11, 1, 3, 30], [2026, 3, 8, 12, 0]]) {
    const ms = S.localToMs(y, m, d, h, mi, tz), p = S.localParts(ms, tz);
    assert.deepEqual([p.y, p.m, p.d, p.h, p.mi], [y, m, d, h, mi]);
  }
  assert.equal(S.localToMs(2026, 10, 12, 7, 0, "America/Chicago"), Date.UTC(2026, 9, 12, 12, 0));
  assert.equal(S.localToMs(2026, 11, 2, 7, 0, "America/Chicago"), Date.UTC(2026, 10, 2, 13, 0));
  assert.equal(S.localParts(Date.UTC(2026, 9, 12, 12, 0), "America/Chicago").dow, 0, "Monday = 0");
  assert.equal(S.localParts(Date.UTC(2026, 9, 12, 12, 0), "No/Such_Zone").h, 12, "unknown zone falls back to UTC");
});

// ---- binding --------------------------------------------------------------------------------------
test("pickSiteSchedule: occupancy-point target beats a site attribute; no target and no attribute = null (default)", () => {
  const all = fx.schedules.map(S.normalizeSchedule), [a, b] = all;
  const picked = S.pickSiteSchedule(all, fx.model, "site-a");
  assert.equal(picked.uuid, a.uuid);
  assert.equal(picked.source, "schedule");
  assert.equal(picked.tz, "America/Chicago", "site tz is attached");
  // site-b: its only schedule targets a lighting point, so nothing binds
  assert.equal(S.pickSiteSchedule(all, fx.model, "site-b"), null);
  assert.equal(S.pickSiteSchedule(all, fx.model, "no-such-site"), null);
  assert.equal(S.pickSiteSchedule([], fx.model, "site-a"), null);
  // explicit site attribute (by uuid, then by name) when no occupancy target exists
  const withAttr = (ref) => ({ ...fx.model, sites: fx.model.sites.map((s) => (s.attrs.id === "site-b" ? { ...s, attrs: { ...s.attrs, scheduleRef: ref } } : s)) });
  assert.equal(S.pickSiteSchedule(all, withAttr(b.uuid), "site-b").uuid, b.uuid);
  assert.equal(S.pickSiteSchedule(all, withAttr("site-b lighting"), "site-b").uuid, b.uuid);
  assert.equal(S.pickSiteSchedule(all, withAttr("nope"), "site-b"), null);
  // an occupancy-point binding wins over the attribute on the same site
  const attrA = { ...fx.model, sites: fx.model.sites.map((s) => (s.attrs.id === "site-a" ? { ...s, attrs: { ...s.attrs, scheduleRef: b.uuid } } : s)) };
  assert.equal(S.pickSiteSchedule(all, attrA, "site-a").uuid, a.uuid);
  // a schedule bound to another site's occupancy point does not leak across sites
  assert.equal(S.pickSiteSchedule([a], fx.model, "site-b"), null);
  // out of service is skipped
  assert.equal(S.pickSiteSchedule([{ ...a, outOfService: true }], fx.model, "site-a"), null);
  // class containing "occupied" or marker "occupied" counts as occupancy too
  const classOnly = { sites: fx.model.sites, points: [{ uuid: "pp", tags: ["point"], cls: "zone-occupied-sensor", siteRef: "site-b" }] };
  assert.equal(S.pickSiteSchedule([{ ...b, targets: [{ pointUuid: "pp", layer: "default" }] }], classOnly, "site-b").uuid, b.uuid);
  assert.equal(S.isOccPoint({ tags: ["point", "occupied"], cls: "" }), true);
  assert.equal(S.isOccPoint({ tags: ["point", "lighting"], cls: "lighting-cmd" }), false);
});

// ---- occupancySeries ------------------------------------------------------------------------------
test("occupancySeries aligns to the grid and carries source metadata", () => {
  const s = schedA();
  const series = S.occupancySeries(s, A.startMs, A.endMs, 300, "America/Chicago");
  assert.equal(series[0][0], A.startMs);
  assert.equal(series.length, A.t.length);
  assert.ok(series.every(([ms], i) => ms === A.t[i]), "same timestamps as the fixture's 5-min grid");
  assert.deepEqual(series.map(([, o]) => o), A.si.occ, "agrees with the fixture's hand-rolled occupancy, holiday included");
  assert.equal(series.source, "schedule");
  assert.match(series.label, /^schedule 50 h\/week/);
  assert.equal(series.tz, "America/Chicago");
  assert.equal(JSON.stringify(series.slice(0, 2)), JSON.stringify([[A.startMs, 0], [A.startMs + 300e3, 0]]), "plain [[ms, 0|1]] when serialized");
  const def = S.occupancySeries(null, B.startMs, B.endMs, 300, "America/New_York");
  assert.equal(def.source, "default");
  assert.equal(def.label, "schedule 50 h/week (default)");
  assert.deepEqual(def.map(([, o]) => o), B.si.occ, "site-b's fixture occupancy is the default calendar");
  // coarse step: same instants every 15 min
  const coarse = S.occupancySeries(s, A.startMs, A.startMs + 86400e3, 900, "America/Chicago");
  assert.equal(coarse.length, 96);
  assert.equal(coarse[1][0] - coarse[0][0], 900e3);
});

// ---- the fixture itself ---------------------------------------------------------------------------
test("fixture: two sites, same Haystack AHU-1, distinct uuids / siteRef / tz / declared units", () => {
  assert.equal(A.equipRec.attrs.id, "AHU-1");
  assert.equal(B.equipRec.attrs.id, "AHU-1");
  assert.notEqual(A.equipUuid, B.equipUuid);
  assert.notEqual(A.siteUuid, B.siteUuid);
  assert.deepEqual([A.equipRec.attrs.siteRef, B.equipRec.attrs.siteRef], ["site-a", "site-b"]);
  assert.deepEqual([A.siteRec.attrs.tz, B.siteRec.attrs.tz], ["America/Chicago", "America/New_York"]);
  const uuids = fx.records.points.map((r) => r.uuid);
  assert.equal(new Set(uuids).size, uuids.length, "no point uuid shared across sites");
  for (const role of ["fan_status", "oa_t", "compressor_status"]) assert.notEqual(A.points[role].uuid, B.points[role].uuid);
  assert.equal(A.points.oa_t.attrs.unit, "°C");
  assert.equal(B.points.oa_t.attrs.unit, "°F");
  assert.equal(A.points.fan_status.attrs.class, "discharge-run-sensor");
  assert.equal(A.points.fan_status.attrs.kind, "Bool");
  assert.equal(A.points.fan_cmd.attrs.unit, "%");
  assert.ok(A.points.occ.attrs.markers.split(",").includes("occ"));
  // imperial site: declared degF values convert to the SI series exactly
  for (const role of ["oa_t", "mat", "rat"]) {
    B.series[role].forEach(([, v], i) => { if (v != null) near(U.toSI(v, "°F").value, B.si[role][i], `${role} degF -> degC`, 1e-9); });
  }
  assert.ok(B.series.oa_t.some(([, v]) => v > 45), "site-b stores Fahrenheit numbers");
  assert.ok(A.series.oa_t.every(([, v]) => v < 25), "site-a stores Celsius numbers");
  // models
  assert.equal(fx.model.points.filter((p) => p.siteRef === "site-a" && p.equipRef === "AHU-1").length, 9);
});

test("fixture truth: planted events match their authored numbers", () => {
  const ta = TRUTH["site-a"], tb = TRUTH["site-b"];
  assert.deepEqual(ta.weeks.map((w) => w.scheduleHours), [50, 40, 50, 50]);
  assert.deepEqual(tb.weeks.map((w) => w.scheduleHours), [50, 50, 50, 50]);
  // after-hours: 70 min pulse (week 1) + 10 h holiday run (week 2); none in weeks 3-4; site-b none at all
  near(ta.weeks[0].afterHoursHours, 70 / 60, "pulse");
  near(ta.weeks[1].afterHoursHours, 10, "holiday run");
  assert.equal(ta.weeks[2].afterHoursHours, 0);
  assert.equal(ta.weeks[3].afterHoursHours, 0);
  near(ta.afterHoursFanHours, 70 / 60 + 10, "total after hours");
  assert.equal(tb.afterHoursFanHours, 0);
  assert.equal(ta.planted.pulse.samples, 14);
  near(ta.planted.pulse.hours, 70 / 60, "pulse hours");
  assert.equal(ta.planted.holiday.fanHours, 10);
  // fan_status gap: 36 null samples; the 185 min interval over the 3600 s cap is dropped, so 3 h 5 min of running time is lost
  assert.equal(ta.planted.fanStatusGap.samples, 36);
  near(ta.weeks[2].inScheduleHours, 50 - 185 / 60, "gap week in-schedule hours");
  assert.equal(ta.planted.matGap.samples, 24);
  // fault week: fan_status 0 for 90 min inside the schedule
  near(ta.weeks[3].inScheduleHours, 50 - 1.5, "fault week in-schedule hours");
  // site-b is exactly 07-17 Mon-Fri, no gaps
  for (const w of tb.weeks) near(w.runHours, 50, "site-b run hours");
  // cooling: only the 20 min event is below 10 degC; the six SI edges are unchanged
  assert.equal(ta.cooling.edgesC.length, 5);
  near(ta.cooling.edgesC[1], (60 - 32) * 5 / 9, "60 degF", 1e-8);
  near(ta.cooling.belowTenHours, 20 / 60, "<10 bin = the event");
  assert.equal(ta.cooling.eventSamples, 4);
  assert.equal(ta.cooling.binHours[1], 0, "10-16 bin has nothing on the fine grid");
  assert.equal(tb.cooling.belowTenHours, 0);
  assert.ok(ta.cooling.binHours.slice(2).reduce((a, b) => a + b, 0) > 100, "normal afternoon cooling");
  // fault: confirmed 14:05..15:25 rows (17 x 5 min), clears at 15:30, still > 0 % in the rolling 24 h at nowMs
  const f = ta.fault;
  assert.equal(f.confirmedFromMs - f.rawStartMs, 300e3, "10 min confirm: the 2nd raw row confirms");
  assert.equal(f.clearedMs - f.confirmedFromMs, 17 * 300e3);
  near(f.confirmedHours, 17 * 300 / 3600, "confirmed hours");
  assert.equal(f.rawStartMs, wall(2026, 11, 6, 14, 0, "America/Chicago"));
  assert.equal(f.clearedMs, wall(2026, 11, 6, 15, 30, "America/Chicago"));
  assert.ok(f.rollingFaultPctAtNow > 5 && f.rollingFaultPctAtNow < 6.5, "rolling fault_pct " + f.rollingFaultPctAtNow);
  assert.equal(f.laneAtNow, 0, "the lane reads ok after the fault cleared");
  assert.ok(f.nowMs > f.clearedMs && f.nowMs - 24 * 3600e3 < f.rawStartMs, "now is inside 24 h of the fault, after it cleared");
  assert.equal(tb.fault, null);
});

test("fixture truth: schedule.js reproduces the fixture's after-hours split on the fine grid", () => {
  for (const [id, site, sched] of [["site-a", A, schedA()], ["site-b", B, S.defaultSchedule("America/New_York")]]) {
    const occ = (ms) => S.occupied(sched, ms, site.tz);
    TRUTH[id].weeks.forEach((w, k) => {
      const inWeek = (ms) => ms >= w.startMs && ms < (site.weekStarts[k + 1] ?? site.endMs);
      near(hoursOn(site.series.fan_status, { where: (ms) => inWeek(ms) && occ(ms) }), w.inScheduleHours, `${id} in-schedule week ${k}`);
      near(hoursOn(site.series.fan_status, { where: (ms) => inWeek(ms) && !occ(ms) }), w.afterHoursHours, `${id} after-hours week ${k}`);
      near(S.weeklyScheduleHours(sched, w.startMs, site.tz), w.scheduleHours, `${id} schedule hours week ${k}`);
    });
  }
  // site-a's bound schedule and site-b's default are different sources
  assert.equal(schedA().source, "schedule");
  assert.equal(S.pickSiteSchedule(fx.schedules.map(S.normalizeSchedule), fx.model, "site-b"), null);
});

test("fixture truth: coarse display grids distort the short events, the fine grid does not", () => {
  // 2 h bucket (28 d view): the 20 min low-OAT event no longer sits in the <10 bin
  assert.equal(pickWindow(168), 1800);
  assert.equal(pickWindow(672), 7200);
  const binsAt = (hours) => {
    const win = pickWindow(hours), end = A.endMs;
    const to = Math.ceil(end / (win * 1000)) * win * 1000, from = to - hours * 3600e3;
    const rs = (role) => new Map(resample(A.series[role], from, to, win, "AVERAGE"));
    const comp = rs("compressor_status"), oat = rs("oa_t");
    const t = [...comp.keys()].sort((x, y) => x - y);
    return coolingBins(t, t.map((k) => comp.get(k)), t.map((k) => oat.get(k)), { capSec: Math.max(3600, 1.5 * win) });
  };
  near(TRUTH["site-a"].cooling.binHours[0], 1 / 3, "fine <10 bin");
  assert.ok(binsAt(672)[0] < 1e-9, "28 d display grid loses the event from the <10 bin: " + binsAt(672)[0]);
  // 2 h average of the fan pulse stretches it to a whole bucket (analog-style on-test: any average > 0.05 = on)
  const pulse = A.series.fan_status;
  const coarse = resample(pulse, A.weekStarts[0], A.weekStarts[1], 7200, "AVERAGE");
  const pulseDay = coarse.filter(([ms]) => ms >= wall(2026, 10, 14, 21, 0, "America/Chicago") && ms < wall(2026, 10, 15, 3, 0, "America/Chicago"));
  assert.ok(pulseDay.filter(([, v]) => v > 0.05).length * 2 > 70 / 60 + 0.5, "coarse buckets overstate the pulse");
});

test("fixture helpers: lane is 1 / 0 / null (never fault_pct > 0); rolling pct decays with the window", () => {
  const lane = confirmedLane(A.rows), at = (ms) => lane.find(([t]) => t === ms)[1];
  const f = TRUTH["site-a"].fault;
  assert.equal(at(f.rawStartMs), 0, "first raw row is not confirmed yet");
  assert.equal(at(f.confirmedFromMs), 1);
  assert.equal(at(f.clearedMs - 300e3), 1);
  assert.equal(at(f.clearedMs), 0);
  const gapStart = TRUTH["site-a"].planted.fanStatusGap.startMs;
  assert.equal(at(gapStart), null, "fan_status null = not assessed, not ok");
  assert.equal(at(gapStart + 35 * 300e3), null);
  assert.equal(at(gapStart + 36 * 300e3), 0);
  assert.equal(lane.filter(([, v]) => v === null).length, 36);
  assert.equal(lane.filter(([, v]) => v === 1).length, 17);
  assert.equal(confirmedLane(B.rows).filter(([, v]) => v !== 0).length, 0, "site-b never faults and has no gaps");
  const pct = (ms) => rollingFaultPct(A.rows, ms);
  assert.equal(pct(f.rawStartMs), 0);
  near(pct(f.clearedMs + 3600e3), pct(f.nowMs), "the rolling percentage stays put while the cleared fault is inside the window");
  assert.ok(pct(f.nowMs) > 0);
  assert.equal(pct(f.clearedMs + 24 * 3600e3 + 300e3), 0, "ages out of the window 24 h after the last confirmed row");
  assert.ok(pct(f.clearedMs + 24 * 3600e3 - 600e3) > 0, "still there just before that");
  assert.equal(cmd1(A.rows).filter((c) => c.assessed === false).length, 36);
});

test("fixture accessors: fetchSeries stub, fake sdk.http, schedules endpoint", async () => {
  const stub = fetchSeriesStub(fx, { nowMs: A.endMs });
  const got = await stub([A.points.fan_status, B.points.fan_status].map((r) => ({ uuid: r.uuid })), 168, { windowSec: 300 });
  assert.equal(got.get(A.points.fan_status.uuid).length, 168 * 12 - 0, "native 5 min, last 7 days; nulls dropped (gap is on 10-27, earlier)");
  assert.notDeepEqual(got.get(A.points.fan_status.uuid), got.get(B.points.fan_status.uuid));
  const coarse = await stub([{ uuid: A.points.oa_t.uuid }], 168);
  assert.equal(coarse.get(A.points.oa_t.uuid)[1][0] - coarse.get(A.points.oa_t.uuid)[0][0], 1800e3, "pickWindow(168) = 30 min");
  const http = fakeSdkHttp(fx, { nowMs: A.endMs });
  const m = await http.post("/api/v1/point/query", { layer: "model" });
  assert.equal(m.data.points.filter((r) => r.pointType === "EQUIPMENT").length, 2);
  const pa = await http.post("/api/v1/point/query", { layer: "default", structuredQuery: { field: { property: "siteRef", text: "site-a" } } });
  assert.ok(pa.data.points.every((r) => r.attrs.siteRef === "site-a"));
  const q = `uuids=${A.points.fan_status.uuid}&from=${new Date(A.endMs - 86400e3).toISOString()}&to=${new Date(A.endMs).toISOString()}&window=300s&method=AVERAGE`;
  const d = await http.get("/api/v1/point/data?" + q);
  assert.equal(d.data.data[0].values.length, 288);
  assert.equal(typeof d.data.data[0].values[0].double, "number");
  const list = await http.get("/api/v1/schedules?pageOffset=0&pageSize=100");
  assert.equal(list.data.schedules.length, 2);
  assert.equal((await http.get("/api/v1/schedules/" + A.points.occ.uuid)).data.schedule, undefined);
  assert.ok(seriesOf(fx, A.points.occ.uuid));
  await http.post("/api/v1/point/points", { points: [{ uuid: "x" }] });
  assert.equal(http.writes.points.length, 1);
});

// ---- loadSchedules (read-only NF client) ----------------------------------------------------------
test("loadSchedules pages through GET /api/v1/schedules and fetches by uuid when the list omits details", async () => {
  const calls = [];
  const many = Array.from({ length: 205 }, (_, i) => ({ uuid: `u${i}`, name: `s${i}`, weeklySchedule: { days: [] } }));
  const api = async (path) => {
    calls.push(path);
    const u = new URL(path, "http://x"), off = Number(u.searchParams.get("pageOffset") || 0), size = Number(u.searchParams.get("pageSize"));
    return { schedules: many.slice(off, off + size), totalCount: String(many.length) };
  };
  const all = await S.loadSchedules(api);
  assert.equal(all.length, 205);
  assert.equal(calls.length, 3, "100 + 100 + 5");
  assert.ok(calls.every((c) => c.startsWith("/api/v1/schedules?")), "GET only, no uuid fetch when details are present");

  const full = fx.schedules[0];
  const lean = async (path) => path.includes("?") ? { schedules: [{ uuid: full.uuid, name: full.name, targets: full.targets }], totalCount: "1" } : { schedule: full };
  const got = await S.loadSchedules(lean);
  assert.equal(got.length, 1);
  assert.equal(got[0].hoursPerWeek, 50, "details came from GET /api/v1/schedules/{uuid}");
  assert.equal(got[0].events.length, 1);

  assert.deepEqual(await S.loadSchedules(async () => { throw new Error("HTTP 404"); }), [], "no ScheduleManager = no schedules");
  assert.deepEqual(await S.loadSchedules(async () => ({})), []);
});

// ---- dev mock NF ----------------------------------------------------------------------------------
let child, base;
const MOCK = fileURLToPath(new URL("../dev/mock-nf.mjs", import.meta.url));
const freePort = () => new Promise((resolve, reject) => { const s = net.createServer(); s.once("error", reject); s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); }); });
before(async () => {
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  child = spawn(process.execPath, [MOCK, String(port)], { stdio: ["ignore", "pipe", "inherit"] });
  await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (c) => reject(new Error("mock exited " + c)));
    child.stdout.on("data", (d) => { if (String(d).includes("mock NF:")) resolve(); });
  });
});
after(() => { child.removeAllListeners("exit"); child.kill(); });

test("mock NF serves read-only schedules and the binding works end to end", async () => {
  const api = async (p, body) => (await fetch(base + p, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {})).json();
  const list = await api("/api/v1/schedules");
  assert.equal(list.schedules.length, 1);
  assert.equal(list.totalCount, "1");
  const one = await api("/api/v1/schedules/" + list.schedules[0].uuid);
  assert.equal(one.schedule.uuid, list.schedules[0].uuid);
  assert.equal((await fetch(base + "/api/v1/schedules/nope")).status, 404);
  assert.equal((await fetch(base + "/api/v1/schedules", { method: "POST", body: "{}" })).status, 404, "read-only: no create");
  assert.equal((await fetch(base + "/api/v1/schedules/" + list.schedules[0].uuid, { method: "DELETE" })).status, 404, "read-only: no delete");
  const scheds = await S.loadSchedules(api);
  assert.equal(scheds.length, 1);
  assert.equal(scheds[0].hoursPerWeek, 55, "Mon-Fri 07:00-18:00");
  const recs = (await api("/api/v1/point/query", { layer: "model" })).points;
  const pts = (await api("/api/v1/point/query", { layer: "default" })).points.map((r) => ({ uuid: r.uuid, tags: (r.attrs.markers || "").split(","), cls: r.attrs.class || "", siteRef: r.attrs.siteRef || "" }));
  const model = { sites: recs.filter((r) => r.pointType === "SITE"), points: pts };
  const north = S.pickSiteSchedule(scheds, model, "site-north");
  assert.equal(north.source, "schedule");
  assert.equal(north.tz, "America/Chicago");
  assert.equal(S.pickSiteSchedule(scheds, model, "site-south"), null, "site-south gets the default");
  const holiday = scheds[0].events[0].date, hd = wall(holiday[0], holiday[1], holiday[2], 10, 0, "America/Chicago");
  assert.equal(S.occupied(north, hd), false, "mock holiday is unoccupied");
});
