// node --test nf-app/tests/rcx-finegrid.test.mjs
// Phase 2a: runtime hours, after-hours split and cooling bins integrate on the FINE grid (ctx.alignedFine,
// 300 s window), the weekly runtime chart carries a schedule reference, and everything is compared with the
// two-site fixture's TRUTH (fixtures/two_site.mjs, computed on the native grid with the 4.x convention).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { twoSite as fx, TRUTH, fetchSeriesStub, fakeSdkHttp, pickWindow, resample, seriesOf } from "./fixtures/two_site.mjs";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
const A = fx.sites["site-a"], B = fx.sites["site-b"];
const arr = (x, f) => Array.from(x, f);
const near = (a, b, msg, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${msg}: ${a} vs ${b}`);

/** A browser-like vm context with the app's classic scripts; NF history + schedules come from the fixture. */
function load({ units = "si" } = {}) {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa, Intl, localStorage: { getItem: () => units } });
  ctx.pickWindow = pickWindow;
  ctx.FAULT_LANE = { lineStyle: { color: "red" }, areaStyle: { color: "red" } };
  ctx.ofddChart = (el) => ({ el });
  ctx.rendered = [];
  ctx.ofddRender = (chart, option, name) => ctx.rendered.push({ option, name });
  ctx.requests = [];                                           // every fetchSeries call: { n, hours, windowSec, endMs }
  const nowFor = (hours) => hours;                              // (unused: stub is anchored per call below)
  ctx.anchorMs = Math.max(A.endMs, B.endMs);
  ctx.fetchSeries = async (list, hours, o = {}) => {
    const windowSec = o.windowSec || pickWindow(hours);
    ctx.requests.push({ n: list.length, hours, windowSec, method: o.method || "AVERAGE", endMs: o.endMs ?? null });
    const end = o.endMs ?? ctx.anchorMs;
    const out = new Map(list.map((p) => [p.uuid, []]));
    const to = Math.ceil(end / (windowSec * 1000)) * windowSec * 1000;
    for (const p of list) out.set(p.uuid, resample(seriesOf(fx, p.uuid) || [], to - hours * 3600e3, to, windowSec, o.method || "AVERAGE"));
    return out;
  };
  const http = fakeSdkHttp(fx);
  ctx.api = async (p) => (await http.get(p)).data;              // nf.js api() stand-in (GET, parsed JSON)
  void nowFor;
  for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "schedule.js", "rcx.js", "rcx-overview.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  ctx.api = async (p) => (await http.get(p)).data;              // nf.js redefines api(); put the stand-in back
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
}

const view = (ctx, id) => arr(ctx.get("RCX_VIEWS")).find((v) => v.id === id);
const siteEquips = (siteRef) => fx.model.equips.filter((e) => e.attrs.siteRef === siteRef);
const HOURS = 700;                                              // > the 28 d the fixture holds, still one fine request (<= 750 h)

async function render(ctx, id, equips, hours = HOURS) {
  const v = view(ctx, id);
  const bound = ctx.rcxBind(v, equips, fx.model, catalog);
  assert.equal(bound.length, equips.length, `${id}: every equip binds`);
  const before = ctx.rendered.length;
  const note = await v.render({}, ctx.rcxContext(v, bound, hours, fx.model, catalog));
  assert.equal(ctx.rendered.length, before + 1);
  return { note, option: ctx.rendered[ctx.rendered.length - 1].option, bound };
}
const bySuffix = (option, suffix) => option.series.filter((s) => s.type === "bar" && s.name.endsWith(suffix));
const dataAt = (s, ms) => { const d = s.data.find(([k]) => k === ms); return d ? d[1] : 0; };

// ---- fine-grid weekly runtime vs TRUTH ----------------------------------------------------------------
for (const [siteRef, S] of [["site-a", A], ["site-b", B]]) {
  test(`weekly-fan ${siteRef}: run hours per ISO week, in-schedule and after-hours equal the fixture TRUTH (fine grid)`, async () => {
    const ctx = load();
    ctx.anchorMs = S.endMs;
    const { option, note } = await render(ctx, "weekly-fan", siteEquips(siteRef));
    const [inS] = bySuffix(option, " · in schedule"), [after] = bySuffix(option, " · after hours");
    assert.ok(inS && after, "one solid in-schedule and one after-hours stack per equip");
    assert.ok(after.itemStyle.decal, "after-hours is hatched");
    assert.equal(inS.stack, after.stack, "same stack = a split of the total");
    TRUTH[siteRef].weeks.forEach((w, k) => {
      const ms = S.weekStarts[k];
      assert.ok(inS.data.some(([x]) => x === ms), `${siteRef} week ${k}: bar is placed at the local Monday`);
      near(dataAt(inS, ms) + dataAt(after, ms), w.runHours, `${siteRef} week ${k} run hours`);
      near(dataAt(inS, ms), w.inScheduleHours, `${siteRef} week ${k} in-schedule`);
      near(dataAt(after, ms), w.afterHoursHours, `${siteRef} week ${k} after-hours`);
    });
    assert.match(note, /hatched = after-hours/);
    // every integration request used the fine window, none the ~360-point display window
    const fine = ctx.requests.filter((r) => r.hours >= HOURS - 1);
    assert.ok(fine.length >= 1 && fine.every((r) => r.windowSec === 300), JSON.stringify(ctx.requests));
    assert.ok(300 < pickWindow(HOURS), "the display grid would have been coarser");
  });
}

test("site-a: the planted pulse is 70/60 h after hours in week 1, the holiday adds 10 h after hours in week 2", async () => {
  const ctx = load();
  const { option } = await render(ctx, "weekly-fan", siteEquips("site-a"));
  const [after] = bySuffix(option, " · after hours");
  near(dataAt(after, A.weekStarts[0]), 70 / 60, "week 1 after-hours (14 samples x 5 min)");
  near(dataAt(after, A.weekStarts[1]), 10, "week 2 after-hours = the holiday");
  near(dataAt(after, A.weekStarts[2]), 0, "week 3");
  near(dataAt(after, A.weekStarts[3]), 0, "week 4");
  // site-b: none
  ctx.anchorMs = B.endMs;
  const b = await render(ctx, "weekly-fan", siteEquips("site-b"));
  for (const ms of B.weekStarts) near(dataAt(bySuffix(b.option, " · after hours")[0], ms), 0, "site-b after hours");
});

// ---- schedule reference line ---------------------------------------------------------------------------
test("schedule reference: stepped hours per ISO week (holiday week 40 h, DST week still 50 h); label says (default) for site-b", async () => {
  const ctx = load();
  const a = await render(ctx, "weekly-fan", siteEquips("site-a"));
  const refA = a.option.series.find((s) => /^schedule /.test(s.name));
  assert.equal(refA.step, "end");
  assert.match(refA.name, /^schedule 50 h\/week \(America\/Chicago, NF schedule "site-a occupancy"\)$/);
  assert.deepEqual(arr(refA.data.slice(0, 4), (d) => arr(d)), A.weekStarts.map((ms, k) => [ms, TRUTH["site-a"].weeks[k].scheduleHours]));
  assert.deepEqual(arr(TRUTH["site-a"].weeks, (w) => w.scheduleHours), [50, 40, 50, 50]);
  assert.equal(refA.data[4][1], 50, "closing point holds the last week to the end of the axis");

  ctx.anchorMs = B.endMs;
  const b = await render(ctx, "weekly-fan", siteEquips("site-b"));
  const refB = b.option.series.find((s) => /^schedule /.test(s.name));
  assert.equal(refB.name, "schedule 50 h/week (default)");
  assert.deepEqual(arr(refB.data.slice(0, 4), (d) => arr(d)), B.weekStarts.map((ms) => [ms, 50]));   // week 3 spans the Nov 1 DST end: still 50 h
  assert.match(b.note, /schedule 50 h\/week \(default\)/);
  // xAxis range covers the line's closing point
  assert.ok([].concat(b.option.xAxis)[0].max >= refB.data[4][0]);
});

test("the schedule is read-only: the only schedule calls are GETs, and nothing is written", async () => {
  const ctx = load();
  const calls = [];
  const http = fakeSdkHttp(fx);
  ctx.api = async (p, opts) => { calls.push([p, opts]); return (await http.get(p)).data; };
  await render(ctx, "weekly-fan", siteEquips("site-a"));
  assert.ok(calls.length >= 1 && calls.every(([p, o]) => /^\/api\/v1\/schedules/.test(p) && !o), JSON.stringify(calls));
  assert.equal(http.writes.points.length + http.writes.data.length, 0);
});

test("two sites with the same AHU-1 in one chart get separate stacks, legend names and schedule lines", async () => {
  const ctx = load();
  const { option } = await render(ctx, "weekly-fan", fx.model.equips);
  const names = arr(option.series, (s) => s.name);
  assert.deepEqual(names.filter((n) => /AHU-1/.test(n)).sort(), [
    "AHU-1 · site-a · after hours", "AHU-1 · site-a · in schedule", "AHU-1 · site-b · after hours", "AHU-1 · site-b · in schedule"]);
  assert.equal(new Set(names).size, names.length, "no two series share a legend name");
  assert.deepEqual(names.filter((n) => /^schedule /.test(n)).sort(), [
    "schedule 50 h/week (America/Chicago, NF schedule \"site-a occupancy\") · site-a", "schedule 50 h/week (default) · site-b"]);
  const sa = option.series.find((s) => s.name === "AHU-1 · site-a · after hours"), sb = option.series.find((s) => s.name === "AHU-1 · site-b · after hours");
  near(dataAt(sa, A.weekStarts[1]), 10, "site-a holiday");
  near(dataAt(sb, B.weekStarts[1]), 0, "site-b has none");
});

// ---- nulls ---------------------------------------------------------------------------------------------
test("null fan_status gap: not 'off' (no after-hours), not covered (the long interval counts for nothing)", async () => {
  const ctx = load();
  const { option } = await render(ctx, "weekly-fan", siteEquips("site-a"));
  const [inS] = bySuffix(option, " · in schedule"), [after] = bySuffix(option, " · after hours");
  const w = TRUTH["site-a"].weeks[2], gap = TRUTH["site-a"].planted.fanStatusGap;
  assert.equal(gap.samples, 36);
  near(dataAt(inS, A.weekStarts[2]) + dataAt(after, A.weekStarts[2]), w.runHours, "week 3 run hours");
  // a full week of 07:00-17:00 Mon-Fri is 50 h. The 36 null samples (3 h) are gone AND so is the 09:55 -> 13:00 interval
  // (3 h 05 min > 3600 s = a gap): 50 - 3 - 5/60.
  near(w.runHours, 50 - 3 - 5 / 60, "TRUTH week 3");
  near(dataAt(after, A.weekStarts[2]), 0, "a null stretch is never after-hours/off time");
  // the union-grid shortcut (another series ticking inside the hole) would give the 5 min back: the math must not
  const M = ctx.get("rcxOverviewMath");
  const t = [0, 300e3, 600e3, 900e3, 1200e3, 1500e3], fan = [1, 1, null, null, null, 1], oat = [5, 5, 5, 5, 5, 5];
  near(M.weeklyRuntime(t, fan, { duty: true }).get(M.weekStart(0)).hours, 1500 / 3600, "a null hole UNDER the 3600 s cap is bridged by the last real sample (4.x LEAD), not counted as off");
  const long = [0, 300e3, 600e3, 7200e3 + 600e3];
  assert.equal(M.weeklyRuntime(long, [1, 1, null, 1], { duty: true }).get(M.weekStart(0)).hours, 300 / 3600, "hole over the cap: only the first interval counts");
  assert.equal(M.mechBins(long, [1, 1, 1, 1], [5, 5, null, 5], { duty: true }).hours[0], 300 / 3600, "bins: no OAT row = no interval, and a gap is not stretched");
  void oat;
});

// ---- cooling bins -------------------------------------------------------------------------------------
test("short cooling event: 1/3 h lands in the <10 bin on the fine grid; a coarse-grid run loses it; the view uses the fine grid", async () => {
  const ctx = load();
  const cols = (eq, role) => ctx.rcxBind(view(ctx, "mech-cooling-compressor-status"), [eq], fx.model, catalog)[0].bound[role][0];
  const eq = siteEquips("site-a")[0], M = ctx.get("rcxOverviewMath");
  const pts = { a: cols(eq, "compressor_status"), o: cols(eq, "oa_t") };
  const rc = ctx.rcxContext(view(ctx, "mech-cooling-compressor-status"), ctx.rcxBind(view(ctx, "mech-cooling-compressor-status"), [eq], fx.model, catalog), 672, fx.model, catalog);
  const fine = await rc.alignedFine(pts, { hours: 672 }), coarse = await rc.aligned(pts, { hours: 672 });
  assert.equal(fine.windowSec, 300);
  assert.equal(coarse.t[1] - coarse.t[0] > 300e3, true, `display grid is coarse (${pickWindow(672)} s)`);
  const f = M.mechBins(fine.t, fine.cols.a, fine.cols.o, { duty: true }), c = M.mechBins(coarse.t, coarse.cols.a, coarse.cols.o, { duty: true });
  near(f.hours[0], 1 / 3, "fine <10 bin");
  near(f.hours[0], TRUTH["site-a"].cooling.belowTenHours, "fine <10 bin == TRUTH");
  assert.ok(Math.abs(c.hours[0] - 1 / 3) > 0.1, `coarse grid distorts the event (${c.hours[0]} h vs 1/3 h)`);
  // the view itself (what the user sees) bins on the fine grid, for both sites, all six bins
  for (const [siteRef, S] of [["site-a", A], ["site-b", B]]) {
    const cx = load();
    cx.anchorMs = S.endMs;
    const { option, note } = await render(cx, "mech-cooling-compressor-status", siteEquips(siteRef), 672);
    const series = option.series[0], want = TRUTH[siteRef].cooling.binHours;
    want.forEach((h, i) => near(series.data[i] ?? 0, h, `${siteRef} bin ${i}`));
    assert.ok(cx.requests.length >= 1 && cx.requests.every((r) => r.windowSec === 300), `${siteRef}: ${JSON.stringify(cx.requests)}`);
    assert.deepEqual(arr(option.xAxis.data), ["<10", "10-16", "16-21", "21-27", "27-32", ">=32"]);
    assert.match(note, /outdoor-air temperature/);
  }
  // SI bins, imperial labels only
  const imp = load({ units: "imperial" });
  imp.anchorMs = A.endMs;
  const { option } = await render(imp, "mech-cooling-compressor-status", siteEquips("site-a"), 672);
  assert.deepEqual(arr(option.xAxis.data), ["<50", "50-60", "60-70", "70-80", "80-90", ">=90"]);
  near(option.series[0].data[0], 1 / 3, "same hours in the same SI bin, imperial labels");
});

// ---- ctx.alignedFine ---------------------------------------------------------------------------------
test("alignedFine: a long span is fetched in <= 9000-sample chunks walked back from now and merged without duplicates", async () => {
  const ctx = load();
  const eq = siteEquips("site-a")[0];
  const v = view(ctx, "weekly-fan"), bound = ctx.rcxBind(v, [eq], fx.model, catalog);
  const rc = ctx.rcxContext(v, bound, 1500, fx.model, catalog);
  const fan = bound[0].bound.fan_status[0];
  const g = await rc.alignedFine({ f: fan }, { hours: 1500 });
  const chunks = ctx.requests.filter((r) => r.windowSec === 300);
  assert.equal(chunks.length, 2, JSON.stringify(ctx.requests));                  // 1500 h = 2 x 750 h at 300 s (9000 samples)
  assert.ok(chunks.every((r) => r.hours <= 750 && r.endMs != null));
  assert.equal(chunks[0].endMs - chunks[1].endMs, 750 * 3600e3);
  assert.ok(g.t.every((x, i) => i === 0 || x > g.t[i - 1]), "sorted, no duplicate timestamps");
  // the chunks end at "now" (real Date); compare with the non-null native samples inside the span they cover
  const hi = chunks[0].endMs, lo = hi - 1500 * 3600e3;
  const want = seriesOf(fx, fan.uuid).filter(([ms, val]) => val != null && ms >= lo && ms < hi).length;
  assert.equal(g.t.length, want, "every native 5 min sample of the span, once");
  assert.equal(g.t.length, new Set(g.t).size);
});
