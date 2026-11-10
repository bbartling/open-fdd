// node --test nf-app/tests/fault-timeline.test.mjs
// 5.0.3: the fault lane is a per-timestamp confirmed-fault TIMELINE (1 confirmed / 0 ok / gap = not assessed), not the
// rolling fault_pct. Two-site fixture (tests/fixtures/two_site.mjs): the real FDD hook (sqlite engine, real pack) runs on
// fake NF HTTP, rcx.js reads what it wrote, VAV-1 gets a synthesized occ_mode from the site schedule.
import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import { twoSite as fx, TRUTH, wall, confirmedLane, resample, fakeSdkHttp } from "./fixtures/two_site.mjs";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");
const S = require("../static/schedule.js");
const catalog = JSON.parse(readFileSync(new URL("../static/fdd-catalog.json", import.meta.url), "utf8"));

const A = fx.sites["site-a"], B = fx.sites["site-b"];
const STEP = 300e3;
const NOW_A = Math.round(TRUTH["site-a"].fault.nowMs);   // Fri 2026-11-06 20:00 America/Chicago (the truth number carries float dust)
const key = (site) => hook.resultKey(site.equipRec, site.id, "AHU-1");

// ---- running the hook on the fixture ------------------------------------------------------------------------
/** An http that also serves `overlay()` model-layer records (what the previous run wrote), like NF would. */
function overlayHttp(base, overlay) {
  return {
    writes: base.writes,
    async post(p, body) {
      const r = await base.post(p, body);
      if (p === "/api/v1/point/query" && body.layer === "model") return { data: { points: [...r.data.points, ...overlay()] } };
      return r;
    },
    get: (p) => base.get(p),
  };
}
async function runHook(nowMs, { http, config = {} } = {}) {
  http = http || fakeSdkHttp(fx, { nowMs });
  const logs = [];
  const summary = await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config: { engine: "sqlite", ...config }, now: nowMs });
  return { http, logs, summary };
}
/** What a run wrote: model records by uuid (last wins) and the [[ms, value]] samples per uuid. */
function written(http) {
  const models = new Map(), data = new Map();
  for (const r of http.writes.points) if (r.layer === "model") models.set(r.uuid, r);
  for (const d of http.writes.data) data.set(d.uuid, [...(data.get(d.uuid) || []), ...d.values.map((v) => [Date.parse(v.ts), v.real])]);
  return { models, data };
}
const timelineRec = (w, site, rule, equipId = "AHU-1") =>
  [...w.models.values()].find((r) => /fault_timeline/.test(r.attrs.markers) && r.attrs.ruleRef === rule && r.attrs.siteRef === site && r.attrs.equipRef === equipId);
const resultRec = (w, site, rule, equipId = "AHU-1") =>
  [...w.models.values()].find((r) => /(^|,)fdd(,|$)/.test(r.attrs.markers) && r.attrs.ruleRef === rule && r.attrs.siteRef === site && r.attrs.equipRef === equipId);

let run1, w1;
before(async () => {
  run1 = await runHook(NOW_A);
  w1 = written(run1.http);
}, { timeout: 120000 });

/** Fixture lane (confirmedLane over the window the hook read), without the last window sample (no forward interval, not assessed). */
function expectedLane(site, nowMs, hours = 24) {
  const to = Math.floor(nowMs / STEP) * STEP, from = to - hours * 3600e3;
  const rows = site.rows.filter((r) => r.ts >= from && r.ts < to);
  return confirmedLane(rows).slice(0, -1);
}

// ---- 1. cleared fault ----------------------------------------------------------------------------------------
test("the hook runs clean and writes a timeline point per (equip, rule) next to the fault_pct point", () => {
  assert.equal(run1.summary.errors, 0, run1.logs.join("\n"));
  const rec = timelineRec(w1, "site-a", "CMD-1");
  assert.ok(rec, "CMD-1 timeline point");
  assert.equal(rec.attrs.markers, "point,his,fault_timeline", "no fdd / fault marker: the FDD table and fault_pct lookups never see it");
  assert.equal(rec.uuid, hook.timelineUuid(key(A), "CMD-1"));
  assert.notEqual(rec.uuid, hook.resultUuid(key(A), "CMD-1"));
  assert.equal(rec.attrs.equipUuid, A.equipUuid);
  assert.equal(rec.attrs.fddTimelineOf, hook.resultUuid(key(A), "CMD-1"));
  const auto = run1.http.writes.points.find((r) => r.uuid === rec.uuid && r.layer === "automation");
  assert.ok(auto, "automation record too, like the fault_pct point");
  assert.equal(auto.attrs.application_id, "open-fdd");
  // fault_pct point still there, unchanged contract
  const res = resultRec(w1, "site-a", "CMD-1");
  assert.equal(res.attrs.fddOutput, "fault_pct");
  assert.equal(res.attrs.equipUuid, A.equipUuid);
});

test("cleared fault: the timeline is confirmedLane (1 confirmed, 0 ok), 0 after the clear while rolling fault_pct is still > 0", () => {
  const T = TRUTH["site-a"].fault;
  const rec = timelineRec(w1, "site-a", "CMD-1");
  const got = w1.data.get(rec.uuid);
  const want = expectedLane(A, NOW_A).filter(([, v]) => v != null);
  assert.deepEqual(got, want, "per-timestamp samples == fixture lane (assessed timestamps only)");
  assert.ok(got.some(([, v]) => v === 1) && got.some(([, v]) => v === 0));
  // confirms at 14:05, reads ok from 15:30 on, all the way to the end of the window
  const at = (h, m) => got.find(([t]) => t === wall(2026, 11, 6, h, m, "America/Chicago"));
  assert.equal(at(14, 0)[1], 0, "raw fault but not yet confirmed (10 min)");
  assert.equal(at(14, 5)[1], 1);
  assert.equal(at(15, 25)[1], 1);
  assert.equal(at(15, 30)[1], 0);
  assert.ok(got.filter(([t]) => t >= T.clearedMs).every(([, v]) => v === 0), "no 1 after the clear");
  assert.equal(got.filter(([, v]) => v === 1).length, 17, "14:05 .. 15:25");
  // ...while the rolling number the same run published is still above 0
  const pct = w1.data.get(resultRec(w1, "site-a", "CMD-1").uuid);
  assert.equal(pct.length, 1);
  assert.ok(Math.abs(pct[0][1] - T.rollingFaultPctAtNow) < 1e-6, `fault_pct ${pct[0][1]}`);
  assert.ok(pct[0][1] > 5);
  // and the last assessed lane value (now) is 0
  assert.equal(got.at(-1)[1], 0);
});

// ---- 2. null telemetry ---------------------------------------------------------------------------------------
test("null telemetry is a gap in the timeline, never a 0: fan_status null 10:00-13:00 writes no sample", async () => {
  const now = wall(2026, 10, 27, 20, 0, "America/Chicago");
  const { http, summary, logs } = await runHook(now);
  assert.equal(summary.errors, 0, logs.join("\n"));
  const w = written(http);
  const got = w.data.get(timelineRec(w, "site-a", "CMD-1").uuid);
  const g0 = wall(2026, 10, 27, 10, 0, "America/Chicago"), g1 = wall(2026, 10, 27, 13, 0, "America/Chicago");
  assert.equal(got.filter(([t]) => t >= g0 && t < g1).length, 0, "nothing written for the 36 gap samples");
  assert.ok(got.some(([t]) => t < g0) && got.some(([t]) => t >= g1), "samples on both sides");
  assert.ok(got.every(([, v]) => v === 0 || v === 1));
  // the fixture says the same: those timestamps are null, everything else assessed
  const want = expectedLane(A, now);
  assert.equal(want.filter(([t, v]) => t >= g0 && t < g1 && v != null).length, 0);
  assert.deepEqual(got, want.filter(([, v]) => v != null));
  assert.equal(want.filter(([, v]) => v == null).length, TRUTH["site-a"].planted.fanStatusGap.samples);
});

// ---- 3. two sites, AHU-1 both ----------------------------------------------------------------------------------
test("two sites with AHU-1: distinct timeline uuids, each keeps its own siteRef and its own samples", () => {
  const a = timelineRec(w1, "site-a", "CMD-1"), b = timelineRec(w1, "site-b", "CMD-1");
  assert.ok(a && b);
  assert.notEqual(a.uuid, b.uuid);
  assert.equal(b.uuid, hook.timelineUuid(key(B), "CMD-1"));
  assert.equal(b.attrs.equipUuid, B.equipUuid);
  assert.notEqual(resultRec(w1, "site-a", "CMD-1").uuid, resultRec(w1, "site-b", "CMD-1").uuid);
  // site-b never has a fault: all zeros; site-a has the confirmed run
  assert.ok(w1.data.get(b.uuid).length > 200 && w1.data.get(b.uuid).every(([, v]) => v === 0));
  assert.ok(w1.data.get(a.uuid).some(([, v]) => v === 1));
});

// ---- rcx.js: rcxFaultData / rcxResultPoint -----------------------------------------------------------------------
/** rcx.js in a vm, fetchSeries served from what the hook wrote (resampled like NF), model = fixture points + written points. */
function rcx(w, nowMs, { onlyResult = false } = {}) {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa, localStorage: { getItem: () => "si" } });
  ctx.pickWindow = () => 3600;
  ctx.FAULT_LANE = { lineStyle: { color: "red", width: 1 }, areaStyle: { color: "pink" } };
  ctx.ofddChart = (el) => ({ el });
  ctx.fetchSeries = async (list, hours, { method = "AVERAGE", windowSec = 3600 } = {}) => {
    const end = (Math.floor(nowMs / (windowSec * 1e3)) + 1) * windowSec * 1e3;      // the window containing now, so a sample stamped exactly now is in
    return new Map(list.map((p) => [p.uuid, resample(w.data.get(p.uuid) || [], end - windowSec * 1e3 - hours * 3600e3, end, windowSec, method)]));
  };
  for (const f of ["units.js", "nf.js", "model.js", "fdd.js", "schedule.js", "rcx.js"]) {
    vm.runInContext(readFileSync(new URL(`../static/${f}`, import.meta.url), "utf8"), ctx, { filename: f });
  }
  const toPoint = vm.runInContext("toPoint", ctx);
  const recs = [...w.models.values()].filter((r) => !onlyResult || !/fault_timeline/.test(r.attrs.markers));
  const model = { sites: fx.model.sites, equips: fx.model.equips, devices: [], points: [...fx.model.points, ...recs.map(toPoint)] };
  return { ctx, model, get: (n) => vm.runInContext(n, ctx) };
}
const lanePlain = (lane) => Array.from(lane, (x) => Array.from(x));

test("rcxFaultData reads the timeline: cleared fault reads 0 after the clear; unknown stays null (gap), never 0", async () => {
  const { ctx, model } = rcx(w1, NOW_A);
  const lane = lanePlain(await ctx.rcxFaultData(model, A.equipRec, "CMD-1", 24));
  assert.equal(ctx.rcxFaultData.length >= 4, true);
  const T = TRUTH["site-a"].fault;
  assert.ok(lane.filter(([t]) => t >= T.clearedMs).every(([, v]) => v === 0), "cleared reads 0");
  assert.equal(lane.filter(([, v]) => v === 1).length, 17);
  assert.deepEqual(lane, expectedLane(A, NOW_A).filter(([, v]) => v != null), "no gaps inside this window: native samples");
  // ...and the fan_status gap (other window) shows up as a null, not a 0
  const now2 = wall(2026, 10, 27, 20, 0, "America/Chicago");
  const run2 = await runHook(now2);
  const r2 = rcx(written(run2.http), now2);
  const lane2 = lanePlain(await r2.ctx.rcxFaultData(r2.model, A.equipRec, "CMD-1", 24));
  const g0 = wall(2026, 10, 27, 10, 0, "America/Chicago"), g1 = wall(2026, 10, 27, 13, 0, "America/Chicago");
  const nulls = lane2.filter(([, v]) => v == null);
  assert.ok(nulls.length >= 1, "a null marks the gap");
  assert.ok(nulls.every(([t]) => t >= g0 - STEP && t <= g1), "the null sits at the gap");
  assert.ok(!lane2.some(([t, v]) => t >= g0 && t < g1 && v === 0), "no 0 inside the gap");
  assert.equal(lane2.filter(([, v]) => v === 0).length, expectedLane(A, now2).filter(([, v]) => v === 0).length);
  const src = r2.ctx.rcxFaultData && (await r2.ctx.rcxFaultData(r2.model, A.equipRec, "CMD-1", 24));
  assert.equal(src.source, "timeline");
  assert.equal(src.approximate, false);
});

test("rcxResultPoint / rcxFaultData: two sites with AHU-1 never share a point or a lane", async () => {
  const { ctx, model } = rcx(w1, NOW_A);
  const pa = ctx.rcxResultPoint(model, A.equipRec, "CMD-1"), pb = ctx.rcxResultPoint(model, B.equipRec, "CMD-1");
  assert.equal(pa.uuid, hook.resultUuid(key(A), "CMD-1"));
  assert.equal(pb.uuid, hook.resultUuid(key(B), "CMD-1"));
  assert.notEqual(pa.uuid, pb.uuid);
  const ta = ctx.rcxTimelinePoint(model, A.equipRec, "CMD-1"), tb = ctx.rcxTimelinePoint(model, B.equipRec, "CMD-1");
  assert.equal(ta.uuid, hook.timelineUuid(key(A), "CMD-1"));
  assert.equal(tb.uuid, hook.timelineUuid(key(B), "CMD-1"));
  // an OfddEquip ({ rec, id }) works the same as the record
  assert.equal(ctx.rcxResultPoint(model, { rec: B.equipRec, id: "AHU-1" }, "CMD-1").uuid, pb.uuid);
  const la = lanePlain(await ctx.rcxFaultData(model, A.equipRec, "CMD-1", 24)), lb = lanePlain(await ctx.rcxFaultData(model, B.equipRec, "CMD-1", 24));
  assert.ok(la.some(([, v]) => v === 1), "site-a lane has its fault");
  assert.ok(lb.length > 200 && lb.every(([, v]) => v === 0), "site-b lane is its own: all ok, none of site-a's fault");
  // 5.0.1-style points (no equipUuid attribute) are still told apart by siteRef
  const stripped = { ...model, points: model.points.map((p) => (p.rec.attrs.equipUuid ? { ...p, rec: { ...p.rec, attrs: { ...p.rec.attrs, equipUuid: undefined } } } : p)) };
  assert.equal(ctx.rcxResultPoint(stripped, A.equipRec, "CMD-1").uuid, pa.uuid);
  assert.equal(ctx.rcxResultPoint(stripped, B.equipRec, "CMD-1").uuid, pb.uuid);
  // a point of ANOTHER equip uuid with the same ids is not matched
  const alien = { uuid: "zzz", attrs: { id: "AHU-1", siteRef: "site-a" } };
  assert.equal(ctx.rcxResultPoint(model, alien, "CMD-1"), null, "an unknown equip uuid with a different equipUuid on every point: no match");
});

test("rcxFaultData falls back to fault_pct (approximate, nulls kept) only when no timeline point exists; the lane draws nulls as gaps", async () => {
  const { ctx, model } = rcx(w1, NOW_A, { onlyResult: true });
  const lane = await ctx.rcxFaultData(model, A.equipRec, "CMD-1", 24);
  assert.equal(lane.source, "fault_pct");
  assert.equal(lane.approximate, true);
  assert.ok(lane.length >= 1 && Array.from(lane).every(([, v]) => v === 0 || v === 1));
  assert.equal(ctx.rcxTimelinePoint(model, A.equipRec, "CMD-1"), null);
  assert.equal((await ctx.rcxFaultData(model, A.equipRec, "NOPE", 24)).source, "none");
  // rcxWithFaultLane keeps null as a gap (connectNulls false) and marks the fallback
  const data = [[1, 0], [2, 1], [3, null], [4, 0]];
  const opt = ctx.rcxWithFaultLane({ grid: [{}], xAxis: [{ type: "time" }], yAxis: [{ type: "value" }], series: [] }, [{ name: "CMD-1", data }]);
  const s = opt.series.at(-1);
  assert.equal(s.connectNulls, false);
  assert.deepEqual(Array.from(s.data, (x) => Array.from(x)), [[1, 0], [2, 1], [3, null], [4, 0]]);
  assert.equal(s.approximate, undefined, "a plain lane is not flagged");
  const opt2 = ctx.rcxWithFaultLane({ grid: [{}], xAxis: [{ type: "time" }], yAxis: [{ type: "value" }], series: [] }, [{ name: "CMD-1", data: lane }]);
  assert.equal(opt2.series.at(-1).approximate, true);
  assert.equal(opt2.series.at(-1).lineStyle.type, "dashed");
  // legacy call with a bare equip id still resolves (but only by equipRef: ambiguous across sites)
  assert.ok(ctx.rcxResultPoint(model, "AHU-1", "CMD-1"));
});

test("a missing fault_pct sample is null in the fallback lane, not 0", async () => {
  const { ctx, model } = rcx(w1, NOW_A, { onlyResult: true });
  const p = ctx.rcxResultPoint(model, A.equipRec, "CMD-1");
  p.rec.attrs.fddOutputSince = "";
  ctx.fetchSeries = async () => new Map([[p.uuid, [[0, 0], [3600e3, null], [7200e3, 12]]]]);
  const lane = lanePlain(await ctx.rcxFaultData(model, A.equipRec, "CMD-1", 24));
  assert.deepEqual(lane, [[0, 0], [3600e3, null], [7200e3, 1]]);
});

test("mixed % to h result history starts at the first full bucket after fddOutputSince", async () => {
  const { ctx, model } = rcx(w1, NOW_A, { onlyResult: true });
  const p = ctx.rcxResultPoint(model, A.equipRec, "CMD-1");
  p.rec.attrs.fddOutput = "fault_hours";
  p.rec.attrs.unit = "h";
  p.rec.attrs.fddOutputSince = new Date(90 * 60e3).toISOString();
  ctx.fetchSeries = async () => new Map([[p.uuid, [[0, 15], [3600e3, 8], [7200e3, 2], [10800e3, 0]]]]);
  const lane = lanePlain(await ctx.rcxFaultData(model, A.equipRec, "CMD-1", 24));
  assert.deepEqual(lane, [[7200e3, 1], [10800e3, 0]], "old percent buckets and the bucket containing the switch are dropped");
  assert.deepEqual(lanePlain(ctx.rcxCurrentOutputSeries(p, [[0, 15], [3600e3, 8], [7200e3, 2]], 3600)), [[7200e3, 2]]);
});

// ---- 4. hook writes: batching, no 0 for unknown, append-only ---------------------------------------------------------
test("hook writes: timeline samples ride the batched AddData calls, one entry per point, values only 0/1", () => {
  const { http, summary } = run1;
  const timelineUuids = [...w1.models.values()].filter((r) => /fault_timeline/.test(r.attrs.markers)).map((r) => r.uuid);
  assert.ok(timelineUuids.length >= 40, `${timelineUuids.length} timeline points over two equips`);
  const entries = http.writes.data.filter((d) => timelineUuids.includes(d.uuid));
  assert.equal(new Set(entries.map((e) => e.uuid)).size, entries.length, "one AddData entry per timeline point");
  assert.ok(entries.some((e) => e.values.length > 200), "a whole window of samples in ONE entry, not one request per sample");
  for (const e of entries) for (const v of e.values) {
    assert.ok(v.real === 0 || v.real === 1, `timeline value ${v.real}`);
    assert.match(v.ts, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
  }
  // a handful of requests for everything: metadata, data and the watermark update
  assert.ok(summary.requests.data <= 4, `${summary.requests.data} AddData calls`);
  assert.ok(summary.requests.metadata <= 3, `${summary.requests.metadata} UpdatePoints calls`);
  assert.equal(summary.timeline.points, entries.length);
  assert.equal(summary.timeline.samples, entries.reduce((a, e) => a + e.values.length, 0));
  // a rule that has no timeline_sql gets only its per-run status sample and no timeline point
  assert.equal(timelineRec(w1, "site-a", "FAULT-ELAPSED-HOURS"), undefined);
  assert.equal(timelineRec(w1, "site-a", "FCU-DEADBAND"), undefined);
});

test("append-only: the next run writes only samples after fddTimelineThrough, no duplicates, nothing for unknown", async () => {
  const rec1 = timelineRec(w1, "site-a", "CMD-1");
  const last1 = w1.data.get(rec1.uuid).at(-1)[0];
  // the watermark advanced with the AddData that carried the samples (second UpdatePoints call)
  const wm = run1.http.writes.points.filter((r) => r.uuid === rec1.uuid && r.layer === "model");
  assert.equal(wm.at(-1).attrs.fddTimelineThrough, new Date(last1).toISOString());
  assert.equal(wm[0].attrs.fddTimelineThrough, undefined, "first metadata pass does not claim samples that are not written yet");
  assert.equal(last1, Math.floor(NOW_A / STEP) * STEP - 2 * STEP, "last window sample has no forward interval: not assessed yet");
  // second run, an hour later, sees the first run's records
  const now2 = NOW_A + 3600e3;
  const prev = () => [...w1.models.values()];
  const http2 = overlayHttp(fakeSdkHttp(fx, { nowMs: now2 }), prev);
  const { summary, logs } = await runHook(now2, { http: http2 });
  assert.equal(summary.errors, 0, logs.join("\n"));
  const w2 = written(http2);
  const got = w2.data.get(rec1.uuid);
  assert.equal(got[0][0], last1 + STEP, "continues right after the watermark");
  assert.equal(got.length, 12, "one hour of new samples");
  assert.ok(got.every(([t]) => t > last1), "nothing at or before the watermark is written again");
  assert.deepEqual(got, expectedLane(A, now2).filter(([t, v]) => t > last1 && v != null));
  const all = [...w1.data.get(rec1.uuid), ...got];
  assert.equal(new Set(all.map(([t]) => t)).size, all.length, "union has no duplicate timestamp");
  // the whole-run totals line up: still only a few requests
  assert.ok(summary.requests.data <= 3);
});

test("timelineSamples: held 0, a missing required input and already-written timestamps are skipped; unknown is never 0", () => {
  const rows = [
    { equipment_id: "E", ts_epoch: 10, confirmed: 0, held_seconds: 300 },
    { equipment_id: "E", ts_epoch: 20, confirmed: 1, held_seconds: 300 },
    { equipment_id: "E", ts_epoch: 30, confirmed: 0, held_seconds: 0 },          // last sample / gap: not assessed
    { equipment_id: "E", ts_epoch: 40, confirmed: 0, held_seconds: 300 },        // input missing at 40
    { equipment_id: "E", ts_epoch: 50, confirmed: null, held_seconds: 300 },
    { equipment_id: "X", ts_epoch: 60, confirmed: 1, held_seconds: 300 },        // another equip
    { equipment_id: "E", ts_epoch: 70, confirmed: 1, held_seconds: 300 },
  ];
  const assessed = (ms) => ms !== 40000;
  assert.deepEqual(hook.timelineSamples(rows, { assessed, equipId: "E" }), [{ ms: 10000, value: 0 }, { ms: 20000, value: 1 }, { ms: 70000, value: 1 }]);
  assert.deepEqual(hook.timelineSamples(rows, { assessed, equipId: "E", after: 20000 }), [{ ms: 70000, value: 1 }]);
  assert.deepEqual(hook.timelineSamples([], {}), []);
});

test("sensor sweep timeline preserves a silence interval while another role reports healthy samples", () => {
  const rows = [
    { equipment_id: "fixture", sensor_role: "sat", ts_epoch: 300, held_seconds: 900, confirmed: 1 },
    { equipment_id: "fixture", sensor_role: "rat", ts_epoch: 0, held_seconds: 600, confirmed: 0 },
    { equipment_id: "fixture", sensor_role: "rat", ts_epoch: 900, held_seconds: 600, confirmed: 0 },
  ];
  assert.deepEqual(hook.timelineSamples(rows, { equipId: "fixture", after: 300000, assessed: () => false }), [
    { ms: 600000, value: 1 }, { ms: 900000, value: 1 }, { ms: 1200000, value: 0 },
  ]);
});

// ---- 5. VAV-1 occupancy ---------------------------------------------------------------------------------------------
/** A VAV with one zone temperature point at a constant 25 degC (above the 23.9 occupied band) on `site`; optional occupancy point. */
function vavSetup(site, { occPoint = false, nowMs }) {
  const base = fakeSdkHttp(fx, { nowMs });
  const equip = { uuid: `vav-${site.id}`, name: "VAV-9", layer: "model", pointType: "EQUIPMENT", attrs: { id: "VAV-9", dis: "VAV-9", markers: "equip,vav", siteRef: site.id } };
  const pt = (id, role, extra = {}) => ({ uuid: `${id}-${site.id}`, name: id, layer: "default", pointType: "POINT", attrs: {
    dis: id, markers: ["point", "his", ...catalog.roles[role].markers].join(","), class: catalog.roles[role].classes[0], equipRef: "VAV-9", siteRef: site.id, ...extra } });
  const points = [pt("zt", "zone_t", { unit: "°C", kind: "Number" })];
  if (occPoint) points.push(pt("occ", "occ_mode", { unit: "", kind: "Bool" }));
  const flat = new Set(points.map((p) => p.uuid));
  return {
    equip,
    http: {
      writes: base.writes,
      async post(p, body) {
        const r = await base.post(p, body);
        if (p !== "/api/v1/point/query") return r;
        if (body.layer === "model") return { data: { points: [...r.data.points, equip] } };
        const s = body.structuredQuery && body.structuredQuery.field && body.structuredQuery.field.text;
        return { data: { points: [...r.data.points, ...(s === site.id ? points : [])] } };
      },
      async get(p) {
        if (!p.startsWith("/api/v1/point/data?")) return base.get(p);
        const q = new URLSearchParams(p.split("?")[1]);
        const from = Date.parse(q.get("from")), to = Math.min(nowMs, Date.parse(q.get("to"))), win = parseInt(q.get("window"), 10) * 1000;
        const data = q.getAll("uuids").map((uuid) => {
          if (!flat.has(uuid)) return null;
          const values = [];
          for (let t = Math.ceil(from / win) * win; t < to; t += win) values.push({ ts: new Date(t).toISOString(), double: uuid.startsWith("occ") ? 1 : 25 });
          return { uuid, values };
        }).filter(Boolean);
        return { data: { data } };
      },
    },
  };
}
const flagsAt = (site, ms) => site.flags[site.t.indexOf(ms)];

test("VAV-1 without an occ_mode point: occupied limits only while the schedule says occupied, holidays are unoccupied, source = schedule", async () => {
  // Wed 2026-10-21 .. Fri 2026-10-23 20:00: Thu 10-22 is site-a's NF holiday
  const now = wall(2026, 10, 23, 20, 0, "America/Chicago");
  const { http } = vavSetup(A, { nowMs: now });
  const { summary, logs } = await runHook(now, { http, config: { windowHours: 72, equips: ["VAV-9"] } });
  assert.equal(summary.errors, 0, logs.join("\n"));
  assert.ok(logs.some((l) => /occ_mode synthesized from schedule/.test(l)), logs.join("\n"));
  const w = written(http);
  assert.equal(resultRec(w, "site-a", "VAV-1", "VAV-9").attrs.fddOccSource, "schedule");
  const samples = w.data.get(timelineRec(w, "site-a", "VAV-1", "VAV-9").uuid);
  assert.ok(samples.length > 800, `${samples.length} samples`);
  const ymd = (ms) => new Date(ms).toLocaleDateString("en-CA", { timeZone: "America/Chicago" });
  const cell = (h, m, d) => samples.find(([t]) => t === wall(2026, 10, d, h, m, "America/Chicago"));
  // normal occupied day (Wed 21): confirmed from 15 min after 07:00, unoccupied limits (no fault) before 07:00 and from 17:00
  assert.equal(cell(12, 0, 21)[1], 1);
  assert.equal(cell(7, 5, 21)[1], 0, "inside the 15 min confirmation");
  assert.equal(cell(7, 15, 21)[1], 1);
  assert.equal(cell(3, 0, 21)[1], 0, "after hours: unoccupied limits, 25 degC is not a fault");
  assert.equal(cell(17, 0, 21)[1], 0);
  assert.equal(cell(22, 30, 22)[1], 0);
  // the holiday is unoccupied all day, although it is a Thursday 07:00-17:00
  const holiday = samples.filter(([t]) => ymd(t) === "2026-10-22");
  assert.ok(holiday.length > 250 && holiday.every(([, v]) => v === 0), "holiday: never in fault");
  assert.ok(A.flags.filter((f) => f.holiday).length > 100, "the fixture really has an unoccupied weekday");
  // every confirmed sample is an occupied timestamp of the fixture's own calendar
  for (const [t, v] of samples) if (v === 1) assert.equal(flagsAt(A, t).occ, true, new Date(t).toISOString());
  assert.ok(samples.filter(([, v]) => v === 1).length > 100);
});

test("VAV-1 on a site with no NF schedule: the 4.x default calendar in the site timezone, source = default", async () => {
  const now = wall(2026, 10, 21, 20, 0, "America/New_York");
  const { http } = vavSetup(B, { nowMs: now });
  const { summary, logs } = await runHook(now, { http, config: { windowHours: 48, equips: ["VAV-9"] } });
  assert.equal(summary.errors, 0, logs.join("\n"));
  assert.ok(logs.some((l) => /occ_mode synthesized from default/.test(l) && /America\/New_York/.test(l)), logs.join("\n"));
  const w = written(http);
  assert.equal(resultRec(w, "site-b", "VAV-1", "VAV-9").attrs.fddOccSource, "default");
  const samples = w.data.get(timelineRec(w, "site-b", "VAV-1", "VAV-9").uuid);
  const cell = (h, m, d) => samples.find(([t]) => t === wall(2026, 10, d, h, m, "America/New_York"));
  assert.equal(cell(11, 0, 21)[1], 1);
  assert.equal(cell(6, 55, 21)[1], 0);
  assert.equal(cell(17, 5, 20)[1], 0);
  for (const [t, v] of samples) if (v === 1) assert.equal(flagsAt(B, t).occ, true);
});

test("VAV-1 with an occ_mode point: the point wins, nothing is synthesized, source = point", async () => {
  const now = wall(2026, 10, 21, 20, 0, "America/Chicago");
  const { http } = vavSetup(A, { occPoint: true, nowMs: now });
  const { summary, logs } = await runHook(now, { http, config: { windowHours: 24, equips: ["VAV-9"] } });
  assert.equal(summary.errors, 0, logs.join("\n"));
  assert.ok(!logs.some((l) => /occ_mode synthesized/.test(l)));
  const w = written(http);
  assert.equal(resultRec(w, "site-a", "VAV-1", "VAV-9").attrs.fddOccSource, "point");
  const samples = w.data.get(timelineRec(w, "site-a", "VAV-1", "VAV-9").uuid);
  // the point says occupied around the clock (1), so 03:00 is in fault: the schedule is not applied over a real signal
  const t3 = wall(2026, 10, 21, 3, 0, "America/Chicago");
  assert.equal(samples.find(([t]) => t === t3)[1], 1);
});

test("VAV-2 keeps its required occ_mode: no point, not run (nothing synthesized for it)", async () => {
  const now = wall(2026, 10, 21, 20, 0, "America/Chicago");
  const { http } = vavSetup(A, { nowMs: now });
  await runHook(now, { http, config: { windowHours: 24, equips: ["VAV-9"] } });
  const w = written(http);
  assert.equal(resultRec(w, "site-a", "VAV-2", "VAV-9"), undefined);
  assert.equal(timelineRec(w, "site-a", "VAV-2", "VAV-9"), undefined);
});
