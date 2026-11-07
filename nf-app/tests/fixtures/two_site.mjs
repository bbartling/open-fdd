// Synthetic two-site acceptance dataset for the 5.0.3 RCx / FDD semantic-parity work.
// Test-only (ESM). Names are `site-a` / `site-b` only; nothing here is a real building.
//
//   import { twoSite, TRUTH, fetchSeriesStub, fakeSdkHttp } from "./fixtures/two_site.mjs";
//
// The dataset (28 days, 5-minute native cadence, local-Monday aligned per site):
//   site-a  America/Chicago   SI-declared points (degC, %)   NF schedule bound through an occ point
//   site-b  America/New_York  imperial-declared points (degF, %)   no bound schedule -> 4.x default 50 h/week
//   Both have an air handler with Haystack id `AHU-1` (distinct NF uuids, distinct siteRef).
//
// What is planted (site-a unless said otherwise); every time is site-local wall clock:
//   pulse     Wed 2026-10-14 22:00-23:10  fan runs after hours, 70 min = 14 samples. A 2 h AVERAGE bucket stretches
//             it to 2 h, a 30 min bucket to ~1.5 h.
//   holiday   Thu 2026-10-22  NF special event, so unoccupied. The BAS did not know: the fan runs its normal 07:00-17:00
//             (10 h counted as after-hours).
//   cooling   Wed 2026-10-28 08:00-08:20  compressor on at OAT < 10 degC (20 min = 4 samples). That morning OAT is 12 degC
//             except a dip to 8 degC for 08:00-08:30, so a 2 h bucket (28 d view, 07:00-09:00 local) averages ~11 degC
//             and moves the event out of the `<10` bin into `10-16`; a 30 min bucket (7 d view) keeps it in `<10`
//             but is wider than the event (20 min on in 30 min).
//   gaps      fan_status null Tue 2026-10-27 10:00-13:00 (36 samples); mat null Wed 2026-11-04 10:00-12:00 (24).
//             A gap longer than 3600 s contributes nothing (4.x / SQL held_seconds rule), nulls are not "off".
//   fault     Fri 2026-11-06 14:00-15:30 fan_cmd = 100 % but fan_status = 0 (CMD-1 raw fault). With the 10 min confirm
//             it is confirmed from the 14:05 row to the 15:25 row and reads ok from 15:30. At `fault.nowMs`
//             (Fri 20:00) the rolling 24 h fault_pct is still ~5.9 % although the fault cleared 4.5 h earlier.
//   site-b    runs exactly 07:00-17:00 Mon-Fri: zero after-hours, no holiday, no low-OAT cooling, no fault.
//
// Truth numbers are computed on the FINE native grid with the 4.x convention (interval i = [t[i], t[i+1]) belongs to
// the week and to the occupancy of t[i]; an interval longer than 3600 s is a gap and counts for nothing; on = signal
// > 0.05). Later tests assert the app / hook / tools against TRUTH; schedule.test.mjs cross-checks schedule.js against
// them (the fixture's own occupancy is hand-rolled below, it does not import schedule.js).
import { readFileSync } from "node:fs";
import crypto from "node:crypto";

const catalog = JSON.parse(readFileSync(new URL("../../static/fdd-catalog.json", import.meta.url), "utf8"));

export const STEP_SEC = 300;
export const STEP_MS = STEP_SEC * 1000;
export const GAP_MAX_SEC = 3600;
export const ON = 0.05;
export const OAT_EDGES_C = [10, 15.555555555555556, 21.11111111111111, 26.666666666666668, 32.22222222222222];
export const ECON_DT_MIN_C = 50 / 9;
const HOLIDAY = "2026-10-22";
const PULSE_DAY = "2026-10-14", COOL_DAY = "2026-10-28", FAN_GAP_DAY = "2026-10-27", MAT_GAP_DAY = "2026-11-04", FAULT_DAY = "2026-11-06";

// ---- wall clock (hand-rolled, Intl only) ---------------------------------------------------------
const fmts = new Map();
function parts(ms, tz) {
  let f = fmts.get(tz);
  if (!f) { f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" }); fmts.set(tz, f); }
  const o = {};
  for (const p of f.formatToParts(new Date(ms))) if (p.type !== "literal") o[p.type] = Number(p.value);
  const dow = (new Date(Date.UTC(o.year, o.month - 1, o.day)).getUTCDay() + 6) % 7;
  return { ymd: `${o.year}-${String(o.month).padStart(2, "0")}-${String(o.day).padStart(2, "0")}`, dow, minute: (o.hour % 24) * 60 + o.minute };
}
/** Instant at which wall clocks in tz read y-m-d h:mi. */
export function wall(y, m, d, h, mi, tz) {
  const w = Date.UTC(y, m - 1, d, h, mi);
  const off = (t) => { const p = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric", second: "numeric" }).formatToParts(new Date(t)); const o = {}; for (const q of p) if (q.type !== "literal") o[q.type] = Number(q.value); return Date.UTC(o.year, o.month - 1, o.day, o.hour % 24, o.minute, o.second) - t; };
  let t = w - off(w);
  t = w - off(t);
  return t;
}

const uuidOf = (name) => {
  const h = crypto.createHash("sha1").update(`two-site:${name}`).digest("hex");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-5${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
};
const median = (xs) => { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b), n = s.length; return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2; };
const F = (c) => (c * 9) / 5 + 32;
const edgeIndex = (oat) => { const i = OAT_EDGES_C.findIndex((e) => oat < e); return i < 0 ? OAT_EDGES_C.length : i; };

// ---- roles ---------------------------------------------------------------------------------------
// role -> [kind, declared unit in SI sites, declared unit in imperial sites]
const ROLES = {
  fan_status: ["Bool", "", ""], fan_cmd: ["Number", "%", "%"], oa_t: ["Number", "°C", "°F"], rat: ["Number", "°C", "°F"],
  mat: ["Number", "°C", "°F"], sat: ["Number", "°C", "°F"], sat_sp: ["Number", "°C", "°F"], oa_damper_pct: ["Number", "%", "%"],
  compressor_status: ["Bool", "", ""],
};
const TEMP_ROLES = new Set(["oa_t", "rat", "mat", "sat", "sat_sp"]);

/** Build the dataset. Deterministic; takes ~100 ms. */
export function buildTwoSite() {
  const defs = [
    { id: "site-a", tz: "America/Chicago", imperial: false, holiday: true, planted: true, oatMean: 13, oatAmp: 6 },
    { id: "site-b", tz: "America/New_York", imperial: true, holiday: false, planted: false, oatMean: 17, oatAmp: 5 },
  ];
  const sites = {}, modelRecs = [], pointRecs = [], schedules = [];
  for (const def of defs) {
    const startMs = wall(2026, 10, 12, 0, 0, def.tz), endMs = wall(2026, 11, 9, 0, 0, def.tz);
    const weekStarts = [0, 7, 14, 21].map((k) => wall(2026, 10, 12 + k, 0, 0, def.tz));
    const siteUuid = uuidOf(`${def.id}/site`), equipUuid = uuidOf(`${def.id}/AHU-1`);
    const siteRec = { uuid: siteUuid, name: def.id, layer: "model", pointType: "SITE", attrs: { id: def.id, dis: def.id, markers: "site", tz: def.tz } };
    const equipRec = { uuid: equipUuid, name: "AHU-1", layer: "model", pointType: "EQUIPMENT", attrs: { id: "AHU-1", dis: "AHU-1", markers: "equip,ahu", siteRef: def.id } };
    modelRecs.push(siteRec, equipRec);

    // ---- simulate (SI) -------------------------------------------------------------------------
    const t = [], si = {}, flags = [];
    for (const r of Object.keys(ROLES)) si[r] = [];
    si.occ = [];
    for (let ms = startMs; ms < endMs; ms += STEP_MS) {
      const p = parts(ms, def.tz), m = p.minute, weekday = p.dow < 5, block = m >= 420 && m < 1020;
      const holiday = def.holiday && p.ymd === HOLIDAY;
      const occ = weekday && block && !holiday;
      const plan = weekday && block;
      const pulse = def.planted && p.ymd === PULSE_DAY && m >= 1320 && m < 1390;
      const fault = def.planted && p.ymd === FAULT_DAY && m >= 840 && m < 930;
      const lowEvent = def.planted && p.ymd === COOL_DAY && m >= 480 && m < 500;
      const fanPlan = plan || pulse;
      let oat = def.oatMean + def.oatAmp * Math.sin((2 * Math.PI * (m - 540)) / 1440);
      if (def.planted && p.ymd === COOL_DAY && m >= 360 && m < 720) oat = m >= 480 && m < 510 ? 8 : 12;
      const status = fanPlan && !fault ? 1 : 0, cmd = fanPlan ? 1 : 0;
      const damper = fanPlan ? 0.3 : 0;
      const rat = 22 + 0.5 * Math.sin((2 * Math.PI * m) / 1440);
      const saw = ((Math.floor((ms - startMs) / STEP_MS) % 5) - 2) / 2;
      const mat = rat + damper * (oat - rat) + 0.5 + 0.2 * saw;
      const comp = (fanPlan && !fault && oat >= OAT_EDGES_C[1]) || lowEvent ? 1 : 0;
      t.push(ms); flags.push({ occ, holiday, pulse, fault });
      si.fan_status.push(def.planted && p.ymd === FAN_GAP_DAY && m >= 600 && m < 780 ? null : status);
      si.fan_cmd.push(cmd);
      si.oa_t.push(oat); si.rat.push(rat);
      si.mat.push(def.planted && p.ymd === MAT_GAP_DAY && m >= 600 && m < 720 ? null : mat);
      si.sat.push(fanPlan ? 13 : 20); si.sat_sp.push(13);
      si.oa_damper_pct.push(damper * 100);   // % (0-100); fan_cmd above is a 0-1 fraction in `si`, declared % in `series`
      si.compressor_status.push(comp);
      si.occ.push(occ ? 1 : 0);
    }

    // ---- NF records ------------------------------------------------------------------------------
    const points = {}, series = {};
    const mk = (role, def2) => {
      const uuid = uuidOf(`${def.id}/AHU-1/${role}`);
      const cat = catalog.roles[role];
      const [kind, uSi, uImp] = def2;
      const rec = { uuid, name: `${def.id} AHU-1 ${role}`, layer: "default", pointType: "POINT", attrs: {
        dis: `AHU-1 ${cat.name}`, markers: ["point", "his", ...cat.markers].join(","), class: cat.classes[0] || "", equipRef: "AHU-1", siteRef: def.id,
        unit: def.imperial ? uImp : uSi, kind } };
      points[role] = rec; pointRecs.push(rec);
      // declared-unit history: imperial sites store degF; fan_cmd is declared "%" (0-100)
      series[role] = t.map((ms, i) => {
        let v = si[role][i];
        if (v == null) return [ms, null];
        if (role === "fan_cmd") v *= 100;
        if (def.imperial && TEMP_ROLES.has(role)) v = F(v);
        return [ms, v];
      });
    };
    for (const [role, d] of Object.entries(ROLES)) mk(role, d);
    // site-level occupancy point (what an NF schedule targets) and, on site-b, a lighting point (not occupancy)
    const occRec = { uuid: uuidOf(`${def.id}/occ`), name: `${def.id} occupancy`, layer: "default", pointType: "POINT", attrs: {
      dis: `${def.id} occupancy`, markers: "point,his,occ,cmd", class: "occupied-cmd", siteRef: def.id, unit: "", kind: "Bool" } };
    if (def.planted) { points.occ = occRec; pointRecs.push(occRec); series.occ = t.map((ms, i) => [ms, si.occ[i]]); }
    let lightRec = null;
    if (!def.planted) {
      lightRec = { uuid: uuidOf(`${def.id}/lighting`), name: `${def.id} lighting`, layer: "default", pointType: "POINT", attrs: {
        dis: `${def.id} lighting`, markers: "point,his,lighting,cmd", class: "lighting-cmd", siteRef: def.id, unit: "", kind: "Bool" } };
      pointRecs.push(lightRec);
    }
    // history rows in SI (what the SQL pack sees); fan_cmd as a 0-1 fraction
    const rows = t.map((ms, i) => ({ ts: ms, fan_status: si.fan_status[i], fan_cmd: si.fan_cmd[i], oa_t: si.oa_t[i], rat: si.rat[i], mat: si.mat[i],
      sat: si.sat[i], sat_sp: si.sat_sp[i], oa_damper_pct: si.oa_damper_pct[i] / 100, compressor_status: si.compressor_status[i] }));
    sites[def.id] = { ...def, startMs, endMs, weekStarts, siteUuid, equipUuid, siteRec, equipRec, points, lightRec, t, si, series, rows, flags };
  }

  // ---- NF schedules ----------------------------------------------------------------------------
  const wd = { timeValues: [{ time: { hour: 7 }, value: { boolean: true } }, { time: { hour: 17 }, value: { boolean: false } }] };
  schedules.push({
    uuid: uuidOf("schedule/site-a"), name: "site-a occupancy", layer: "local", outOfService: false, defaultValue: { boolean: false },
    weeklySchedule: { days: [wd, wd, wd, wd, wd, {}, {}] },
    specialEvents: [{ name: "Test Holiday", date: { year: 2026, month: 10, day: 22 }, priority: 1, timeValues: [{ time: {}, value: { boolean: false } }] }],
    targets: [{ pointUuid: sites["site-a"].points.occ.uuid, layer: "default" }],
  });
  const every = { timeValues: [{ time: { hour: 6 }, value: { boolean: true } }, { time: { hour: 22 }, value: { boolean: false } }] };
  schedules.push({   // decoy: site-b's only schedule drives a lighting point, so it must NOT bind as site-b occupancy
    uuid: uuidOf("schedule/site-b-lighting"), name: "site-b lighting", layer: "local", outOfService: false, defaultValue: { boolean: false },
    weeklySchedule: { days: [every, every, every, every, every, every, every] },
    targets: [{ pointUuid: sites["site-b"].lightRec.uuid, layer: "default" }],
  });

  // ---- model.js shapes (loadModel() result) ----------------------------------------------------
  const GENERIC = new Set(["point", "his", "cur", "writable"]);
  const toPoint = (r) => {
    const a = r.attrs, tags = a.markers.split(",").filter(Boolean);
    return { uuid: r.uuid, tags, dis: a.dis, units: a.unit || "", kind: a.kind || "Number", name: tags.filter((x) => !GENERIC.has(x) && x !== "sensor").join(" ") || r.name,
      equipRef: a.equipRef || "", weatherStationRef: "", siteRef: a.siteRef || "", deviceRef: "", objectId: "", bacnet: "", cls: a.class || "", latest: undefined, rec: r };
  };
  const model = { sites: Object.values(sites).map((s) => s.siteRec), equips: Object.values(sites).map((s) => s.equipRec), devices: [], points: pointRecs.map(toPoint) };

  const fixture = { STEP_SEC, sites, model, records: { model: modelRecs, points: pointRecs }, schedules };
  fixture.truth = computeTruth(sites);
  return fixture;
}

// ---- truth (fine native grid, 4.x convention) -----------------------------------------------------

/** Hours a [ms, value|null] series was on (value > ON); null samples are dropped first, an interval over capSec is a gap. */
export function hoursOn(series, { capSec = GAP_MAX_SEC, on = (v) => v > ON, where = () => true } = {}) {
  const s = series.filter(([, v]) => v != null);
  let h = 0;
  for (let i = 0; i + 1 < s.length; i++) {
    const dt = (s[i + 1][0] - s[i][0]) / 1000;
    if (dt > 0 && dt <= capSec && on(s[i][1]) && where(s[i][0])) h += dt / 3600;
  }
  return h;
}

/** Seconds covered (sum of non-gap intervals) of a series, in hours. */
export function coveredHours(series, { capSec = GAP_MAX_SEC } = {}) { return hoursOn(series, { capSec, on: () => true }); }

/** Hours per OAT bin (six SI bins) the `active` series was on; oat in degC at the same timestamps (mechanical_cooling_oat_bins.sql). */
export function coolingBins(t, active, oat, { capSec = GAP_MAX_SEC } = {}) {
  const bins = new Array(OAT_EDGES_C.length + 1).fill(0);
  for (let i = 0; i + 1 < t.length; i++) {
    const dt = (t[i + 1] - t[i]) / 1000;
    if (!(dt > 0 && dt <= capSec) || oat[i] == null || active[i] == null || !(active[i] > ON)) continue;
    bins[edgeIndex(oat[i])] += dt / 3600;
  }
  return bins;
}

/**
 * CMD-1 on SI history rows (cmd1_fan_mismatch.sql): raw = (fan_cmd >= 0.05) <> (fan_status > 0.5), null input = not assessed;
 * confirmed once the raw-fault streak has held >= confirmSec (held = the row's interval, 0 over a gap > capSec).
 * Returns per row { ts, assessed, raw, held, confirmed } .
 */
export function cmd1(rows, { confirmSec = 600, capSec = GAP_MAX_SEC } = {}) {
  const out = [];
  let prevRaw = null, prevGap = 0, elapsed = 0;
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i], assessed = r.fan_cmd != null && r.fan_status != null;
    const raw = assessed && (r.fan_cmd >= 0.05) !== (r.fan_status > 0.5) ? 1 : 0;
    const dt = i + 1 < rows.length ? (rows[i + 1].ts - r.ts) / 1000 : null;
    const held = dt != null && dt > 0 && dt <= capSec ? dt : 0, gap = dt != null && dt > capSec ? 1 : 0;
    elapsed = raw === prevRaw && !prevGap ? elapsed + held : held;
    prevRaw = raw; prevGap = gap;
    out.push({ ts: r.ts, assessed, raw, held, confirmed: raw === 1 && elapsed >= confirmSec ? 1 : 0 });
  }
  return out;
}

/** The lane a fault chart should draw: [ms, 1 confirmed | 0 ok | null not assessed]. Never `fault_pct > 0`. */
export const confirmedLane = (rows, opts) => cmd1(rows, opts).map((c) => [c.ts, c.assessed ? c.confirmed : null]);

/** Rolling fault_pct the hook publishes at `atMs`: confirmed seconds / covered seconds over the trailing window, in percent. */
export function rollingFaultPct(rows, atMs, windowHours = 24, opts) {
  const win = rows.filter((r) => r.ts >= atMs - windowHours * 3600e3 && r.ts < atMs);
  const c = cmd1(win, opts);
  const covered = c.reduce((a, x) => a + x.held, 0), conf = c.reduce((a, x) => a + (x.confirmed ? x.held : 0), 0);
  return covered ? (100 * conf) / covered : 0;
}

/** Economizer samples: fan on (> 0.05), oa_t / rat / mat present; identifiable = |oat - rat| >= 50/9 K; resid = mat - (rat + damper * (oat - rat)). */
export function economizer(rows) {
  const kept = rows.filter((r) => r.oa_t != null && r.rat != null && r.mat != null && r.fan_status != null && r.fan_status > ON);
  const ident = kept.filter((r) => Math.abs(r.oa_t - r.rat) >= ECON_DT_MIN_C);
  const resid = ident.map((r) => r.mat - (r.rat + r.oa_damper_pct * (r.oa_t - r.rat)));
  return { n: kept.length, nIdent: ident.length, medianResidK: median(resid), maeResidK: resid.length ? resid.reduce((a, b) => a + Math.abs(b), 0) / resid.length : null };
}

/** Round float dust (1e-9) out of the truth numbers so tests can use strict equality on hours. */
const round9 = (v) => (typeof v === "number" ? Math.round(v * 1e9) / 1e9 : Array.isArray(v) ? v.map(round9) : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, round9(x)])) : v);

function computeTruth(sites) {
  const truth = {};
  for (const [id, s] of Object.entries(sites)) {
    const occAt = new Map(s.t.map((ms, i) => [ms, s.flags[i].occ]));
    const wk = (ms) => { let k = 0; for (let i = 0; i < s.weekStarts.length; i++) if (ms >= s.weekStarts[i]) k = i; return k; };
    const fan = s.series.fan_status;
    const weeks = s.weekStarts.map((startMs, k) => {
      const inWeek = (ms) => wk(ms) === k;
      const run = hoursOn(fan, { where: inWeek }), inSched = hoursOn(fan, { where: (ms) => inWeek(ms) && occAt.get(ms) }), after = hoursOn(fan, { where: (ms) => inWeek(ms) && !occAt.get(ms) });
      const sched = s.t.reduce((a, ms, i) => a + (inWeek(ms) && occAt.get(ms) ? STEP_SEC / 3600 : 0), 0);
      return { startMs, scheduleHours: Math.round(sched * 1000) / 1000, runHours: run, inScheduleHours: inSched, afterHoursHours: after,
        coveredHours: coveredHours(fan.filter(([ms]) => inWeek(ms))) };
    });
    const bins = coolingBins(s.t, s.si.compressor_status, s.si.oa_t);
    // the low-OAT event alone (the only compressor run below 10 degC)
    const lowIdx = s.t.map((ms, i) => i).filter((i) => s.si.compressor_status[i] === 1 && s.si.oa_t[i] < OAT_EDGES_C[0]);
    const out = { weeks, afterHoursFanHours: weeks.reduce((a, w) => a + w.afterHoursHours, 0),
      cooling: { edgesC: OAT_EDGES_C.slice(), binHours: bins, belowTenHours: bins[0], eventSamples: lowIdx.length, eventStartMs: lowIdx.length ? s.t[lowIdx[0]] : null,
        eventHours: lowIdx.length * STEP_SEC / 3600 },
      economizer: economizer(s.rows), startMs: s.startMs, endMs: s.endMs, stepSec: STEP_SEC, fault: null, planted: null };
    if (s.planted) {
      const lane = confirmedLane(s.rows), c = cmd1(s.rows);
      const first = c.find((x) => x.confirmed), firstRaw = c.find((x) => x.raw), cleared = c.find((x) => x.ts > first.ts && !x.confirmed);
      const nowMs = wall(2026, 11, 6, 20, 0, s.tz);
      const pct = rollingFaultPct(s.rows, nowMs);
      out.fault = { rule: "CMD-1", confirmSec: 600, rawStartMs: firstRaw.ts, confirmedFromMs: first.ts, clearedMs: cleared.ts,
        confirmedHours: c.filter((x) => x.confirmed).reduce((a, x) => a + x.held, 0) / 3600, nowMs, windowHours: 24,
        rollingFaultPctAtNow: pct, laneAtNow: lane.filter(([ms]) => ms < nowMs).at(-1)[1] };
      out.planted = {
        pulse: { startMs: s.t[s.flags.findIndex((f) => f.pulse)], samples: s.flags.filter((f) => f.pulse).length, hours: s.flags.filter((f) => f.pulse).length * STEP_SEC / 3600 },
        holiday: { ymd: HOLIDAY, fanHours: s.flags.reduce((a, f, i) => a + (f.holiday && s.si.fan_status[i] === 1 ? STEP_SEC / 3600 : 0), 0) },
        fanStatusGap: { startMs: s.t[s.si.fan_status.findIndex((v) => v == null)], samples: s.si.fan_status.filter((v) => v == null).length },
        matGap: { samples: s.si.mat.filter((v) => v == null).length },
      };
    }
    truth[id] = round9(out);
  }
  return truth;
}

// ---- accessors ------------------------------------------------------------------------------------

/** charts.js WINDOWS / pickWindow(hours, target = 360): the coarse NF resample window the app picks for a view. */
export const WINDOWS = [60, 300, 600, 900, 1800, 3600, 7200, 14400, 86400];
export const pickWindow = (hours, target = 360) => WINDOWS.find((w) => (hours * 3600) / w <= target) || 86400;

const AGG = { AVERAGE: (x) => x.reduce((a, b) => a + b, 0) / x.length, MIN: (x) => Math.min(...x), MAX: (x) => Math.max(...x), SUM: (x) => x.reduce((a, b) => a + b, 0),
  FIRST: (x) => x[0], LAST: (x) => x[x.length - 1], COUNT: (x) => x.length };

/** Raw declared-unit series of one point uuid (nulls kept), or undefined. */
export function seriesOf(fx, uuid) {
  for (const s of Object.values(fx.sites)) for (const [role, rec] of Object.entries(s.points)) if (rec.uuid === uuid) return s.series[role];
  return undefined;
}

/** What NF's point/data does: [[bucketMs, value]] resampled to windowSec with `method`, nulls skipped, over [fromMs, toMs). windowSec = null -> native samples. */
export function resample(series, fromMs, toMs, windowSec, method = "AVERAGE") {
  const agg = AGG[method] || AGG.AVERAGE, win = windowSec ? windowSec * 1000 : 0, out = [];
  if (!win) return series.filter(([ms, v]) => v != null && ms >= fromMs && ms < toMs);
  let b = null, xs = [];
  const flush = () => { if (b != null && xs.length) out.push([b, agg(xs)]); xs = []; };
  for (const [ms, v] of series) {
    if (v == null || ms < fromMs || ms >= toMs) continue;
    const k = Math.floor(ms / win) * win;
    if (k !== b) { flush(); b = k; }
    xs.push(v);
  }
  flush();
  return out;
}

/**
 * A `fetchSeries(list, hours, { method, windowSec })` stand-in for UI tests: Map(uuid -> [[ms, value]]) in each point's
 * declared unit, nulls dropped (like the real one), resampled like NF. `nowMs` anchors the window end (default: the
 * later site end). windowSec defaults to pickWindow(hours), the coarse grid that distorts short events.
 */
export function fetchSeriesStub(fx, { nowMs } = {}) {
  const end = nowMs ?? Math.max(...Object.values(fx.sites).map((s) => s.endMs));
  return async (list, hours, { method = "AVERAGE", windowSec = pickWindow(hours) } = {}) => {
    const out = new Map(list.map((p) => [p.uuid, []]));
    const to = Math.ceil(end / (windowSec * 1000)) * windowSec * 1000;
    for (const p of list) out.set(p.uuid, resample(seriesOf(fx, p.uuid) || [], to - hours * 3600e3, to, windowSec, method));
    return out;
  };
}

/**
 * Fake `sdk.http` for hook tests (axios-like: post/get return { data }): model + default layer queries (default layer
 * filtered by the siteRef structuredQuery like hooks/fdd.js sends it), point/data resampled from the fixture with
 * window / method / from / to honoured, GET /api/v1/schedules, and recording of point / data writes.
 * `nowMs` bounds the history (nothing at or after it).
 */
export function fakeSdkHttp(fx, { nowMs } = {}) {
  const writes = { points: [], data: [] };
  const cut = nowMs ?? Infinity;
  const clean = (r) => { const { ...c } = r; return c; };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/query") {
        if (body.layer === "model") return { data: { points: fx.records.model.map(clean) } };
        const site = body.structuredQuery && body.structuredQuery.field && body.structuredQuery.field.text;
        return { data: { points: fx.records.points.filter((x) => !site || x.attrs.siteRef === site).map(clean) } };
      }
      if (p === "/api/v1/point/points") { writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/points/data") { for (const x of body.points) writes.data.push({ uuid: x.uuid, values: x.values }); return { data: { success: true } }; }
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (p.startsWith("/api/v1/platform/info")) return { data: { resources: [{ memory: { totalBytes: String(4 * 1024 ** 3) } }] } };
      if (p.startsWith("/api/v1/schedules/")) { const u = decodeURIComponent(p.slice("/api/v1/schedules/".length).split("?")[0]); return { data: { schedule: fx.schedules.find((s) => s.uuid === u) } }; }
      if (p.startsWith("/api/v1/schedules")) return { data: { schedules: fx.schedules, totalCount: String(fx.schedules.length) } };
      if (p.startsWith("/api/v1/point/data?")) {
        const q = new URLSearchParams(p.split("?")[1]);
        const win = parseInt(q.get("window") || "0", 10) || null, from = Date.parse(q.get("from") || "1970-01-01T00:00:00Z"), to = Math.min(cut, Date.parse(q.get("to") || "2100-01-01T00:00:00Z"));
        const data = q.getAll("uuids").map((uuid) => ({ uuid, values: resample(seriesOf(fx, uuid) || [], from, to, win, q.get("method") || "AVERAGE").map(([ms, v]) => ({ ts: new Date(ms).toISOString(), double: v })) }));
        return { data: { data } };
      }
      throw new Error("unexpected GET " + p);
    },
  };
}

export const twoSite = buildTwoSite();
export const TRUTH = twoSite.truth;
export default twoSite;
