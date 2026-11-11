// node --test nf-app/tests/rcx-overview.test.mjs — overview RCx views (rcx-overview.js).
// Classic browser scripts run in a vm context, like app.test.mjs. NF history, ECharts and the
// theme are stubbed: fetchSeries serves fixtures (in the point's own unit), ofddRender captures the
// option it is given. The math runs in SI (ctx.series converts through units.js); charts and notes
// show the display system (ctx.units = "imperial" | "si").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));

const HOUR = 3600e3;
const T0 = Date.UTC(2026, 9, 26);            // a Monday 00:00 UTC (ISO week 2026-W44)

function load() {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa,
    localStorage: { getItem: () => ctx.units } });          // ofddUnits.displaySystem()
  ctx.units = "imperial";
  ctx.pickWindow = () => 3600;                // one value per hour
  ctx.FAULT_LANE = { lineStyle: { color: "red" }, areaStyle: { color: "red" } };
  ctx.ofddChart = (el) => ({ el, setOption(option) { this.option = option; } });
  ctx.rendered = [];
  ctx.ofddRender = (chart, option, name) => { chart.setOption?.(option); ctx.rendered.push({ option: chart.option || option, name }); };
  ctx.series = new Map();                      // uuid -> [[ms, v]] served by the fetchSeries stub
  ctx.fetchSeries = async (list) => new Map(list.map((p) => [p.uuid, ctx.series.get(p.uuid) || []]));
  for (const f of ["units.js", "nf.js", "model.js", "fdd.js", "schedule.js", "charts.js", "rcx.js", "rcx-overview.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  ctx.fetchSeries = async (list) => new Map(list.map((p) => [p.uuid, ctx.series.get(p.uuid) || []]));
  ctx.pickWindow = () => 3600;
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
}
const arr = (x, f) => Array.from(x, f);
const near = (a, b, e = 1e-6) => assert.ok(Math.abs(a - b) < e, `${a} != ${b}`);
const F2C = (f) => (f - 32) * 5 / 9;

// ---- fixture model: one AHU with every role, a chiller, weather, an ECON-1 result point ------
const rec = (name, pointType, attrs) => ({ uuid: `u-${name}`, name, pointType, attrs });
const pt = (name, markers, extra = {}) => rec(name, "POINT", { siteRef: "s", equipRef: "AHU-1", markers: `point,his,${markers}`, kind: "Number", unit: "°F", ...extra });
const AHU = rec("AHU-1", "EQUIPMENT", { id: "AHU-1", siteRef: "s", markers: "equip,ahu" });
const POINTS = [
  pt("OAT", "sensor,outside,air,temp", { class: "outside-air-temp-sensor" }),
  pt("RAT", "sensor,return,air,temp", { class: "return-air-temp-sensor" }),
  pt("MAT", "sensor,mixed,air,temp", { class: "mixed-air-temp-sensor" }),
  pt("SAT", "sensor,discharge,air,temp", { class: "discharge-air-temp-sensor" }),
  pt("FAN-S", "sensor,discharge,fan,run", { class: "discharge-run-sensor", kind: "Bool", unit: "" }),
  pt("FAN-C", "cmd,discharge,fan,run", { class: "discharge-run-cmd", kind: "Bool", unit: "" }),
  pt("DMP", "sensor,outside,damper", { class: "outside-damper-sensor", unit: "%" }),
  pt("ECON1", "fdd,fault", { ruleRef: "ECON-1", unit: "" }),
  rec("WX", "POINT", { siteRef: "s", weatherStationRef: "w", markers: "point,weather,outside,air,temp,his", kind: "Number", unit: "°F" }),
];
function setup(points = POINTS) {
  const ctx = load();
  const model = { sites: [], equips: [AHU], devices: [], points: points.map(ctx.toPoint) };
  const byName = (n) => model.points.find((p) => p.rec.name === n);
  return { ctx, model, byName };
}
const views = (ctx) => arr(ctx.get("RCX_VIEWS"));
const view = (ctx, id) => views(ctx).find((v) => v.id === id);
const hourly = (n, f) => Array.from({ length: n }, (_, i) => [T0 + i * HOUR, f(i)]);
/** Render a view against the fixture the way app.js does. */
async function renderView(ctx, model, id, hours = 48) {
  const v = view(ctx, id);
  const bound = ctx.rcxBind(v, model.equips, model, catalog);
  assert.ok(bound.length, `${id}: nothing bound`);
  const eqs = v.scope === "site" ? bound : [bound[0]];
  const note = await v.render({}, ctx.rcxContext(v, eqs, hours, model, catalog));
  return { note, out: ctx.rendered[ctx.rendered.length - 1] };
}

// ---- registration ----------------------------------------------------------------------------
test("every view uses real catalog roles and kinds, unique ids, valid scope/group", () => {
  const { ctx } = setup();
  const vs = views(ctx);
  assert.ok(vs.length >= 12);
  assert.equal(new Set(vs.map((v) => v.id)).size, vs.length);
  for (const v of vs) {
    for (const r of [...v.roles.required, ...v.roles.optional]) assert.ok(catalog.roles[r], `${v.id}: role ${r}`);
    for (const k of v.kinds) assert.ok(catalog.equipment_kinds[k], `${v.id}: kind ${k}`);
    assert.ok(["equip", "site"].includes(v.scope));
    assert.ok(["Air handlers", "Weather", "Plant"].includes(v.group), `${v.id}: group ${v.group}`);
    assert.ok(v.roles.required.length, `${v.id} needs a required role`);
  }
  for (const id of ["weekly-fan", "weekly-fan-cmd", "weekly-pump", "weekly-compressor", "mech-cooling-chiller-status",
    "economizer-delta", "economizer-mat-residual", "economizer-temps", "bas-vs-web-oat", "bas-vs-web-oat-hist"]) {
    assert.ok(view(ctx, id), id);
  }
  assert.deepEqual(Object.keys(ctx).filter((k) => /^rcxOverview/.test(k)), ["rcxOverviewMath"]);
});

// ---- pure math ------------------------------------------------------------------------------
test("ISO weeks: Monday start (UTC), week labels, year boundary", () => {
  const { rcxOverviewMath: m } = setup().ctx;
  assert.equal(m.weekStart(Date.UTC(2026, 10, 5, 13)), Date.UTC(2026, 10, 2));
  assert.equal(m.weekStart(Date.UTC(2026, 10, 8, 23, 59)), Date.UTC(2026, 10, 2));   // Sunday stays in the week
  assert.equal(m.isoWeekLabel(Date.UTC(2026, 10, 5)), "2026-W45");
  assert.equal(m.isoWeekLabel(Date.UTC(2027, 0, 1)), "2026-W53");
  assert.equal(m.isoWeekLabel(Date.UTC(2025, 11, 29)), "2026-W01");
});

test("weeklyRuntime: duty vs threshold, 0.05 on-limit, gap cap, week split, OAT while on", () => {
  const { rcxOverviewMath: m } = setup().ctx;
  // Sunday 22:00 .. Monday 04:00 (UTC): 6 hourly samples ending in week 2026-W45's Monday.
  const sun = Date.UTC(2026, 10, 1, 22);
  const t = Array.from({ length: 7 }, (_, i) => sun + i * HOUR);
  const on = new Array(7).fill(1);
  const w = m.weeklyRuntime(t, on, { duty: true });
  assert.deepEqual(arr(w.keys()), [Date.UTC(2026, 9, 26), Date.UTC(2026, 10, 2)]);
  assert.equal(w.get(Date.UTC(2026, 9, 26)).hours, 2);          // 22:00, 23:00 intervals
  assert.equal(w.get(Date.UTC(2026, 10, 2)).hours, 4);          // 00:00..03:00 intervals (last sample has no interval)
  assert.equal(w.get(Date.UTC(2026, 10, 2)).partial, true);     // under 6 days observed
  // duty mode weights by the resampled on-fraction; <= 0.05 is off
  assert.equal(m.weeklyRuntime(t, [0.5, 0.5, 0.05, 0.04, 1, 1, 1], { duty: true }).get(Date.UTC(2026, 9, 26)).hours, 1);
  // analog command: any > 5% counts the whole interval; percent inputs are normalized (50 -> 0.5)
  assert.equal(m.weeklyRuntime(t, [0.3, 50, 0.04, 0, 0, 0, 0], { duty: false }).get(Date.UTC(2026, 9, 26)).hours, 2);
  // a gap longer than the cap is not counted
  const gap = [T0, T0 + HOUR, T0 + 6 * HOUR, T0 + 7 * HOUR];
  assert.equal(m.weeklyRuntime(gap, [1, 1, 1, 1], { duty: true }).get(Date.UTC(2026, 9, 26)).hours, 2);
  assert.equal(m.weeklyRuntime(gap, [1, 1, 1, 1], { duty: true, gapMaxSec: 6 * 3600 }).get(Date.UTC(2026, 9, 26)).hours, 7);
  // average OAT is taken while running only
  const o = m.weeklyRuntime(t, [1, 0, 1, 0, 0, 0, 0], { duty: true, oat: [40, 99, 60, 99, 99, 99, 99] });
  assert.equal(o.get(Date.UTC(2026, 9, 26)).oat, 40);
  assert.equal(o.get(Date.UTC(2026, 10, 2)).oat, 60);
});

test("mechBins: bins are fixed in degC (50..90 degF); labels follow the display system", () => {
  const { rcxOverviewMath: m } = setup().ctx;
  assert.deepEqual(arr(m.oatBinLabels()), ["<10", "10-16", "16-21", "21-27", "27-32", ">=32"]);
  assert.deepEqual(arr(m.oatBinLabels((c) => c * 1.8 + 32)), ["<50", "50-60", "60-70", "70-80", "80-90", ">=90"]);
  const t = Array.from({ length: 6 }, (_, i) => T0 + i * HOUR);
  // the same physical temperatures (given in degC) land in the same bins whichever labels are shown
  const oat = [45, 55, 55, 75, 95, 95].map(F2C);
  const r = m.mechBins(t, [1, 1, 0, 1, 1, 1], oat, { duty: true });
  assert.deepEqual(arr(r.hours), [1, 1, 0, 1, 0, 1]);           // last sample has no interval
  assert.deepEqual(arr(r.labels), ["<10", "10-16", "16-21", "21-27", "27-32", ">=32"]);
  assert.deepEqual(arr(m.mechBins(t, [1, 1, 0, 1, 1, 1], oat, { duty: true, toDisp: (c) => c * 1.8 + 32 }).hours), arr(r.hours));
  const c = m.mechBins(t, [1, 1, 1, 1, 1, 1], [5, 5, 12, 33, 33, 33]);
  assert.deepEqual(arr(c.hours), [2, 1, 0, 0, 0, 2]);
});

test("economizerRows: SI default identifiable delta is 5.5556 delta degC (= 10 delta degF)", () => {
  const { rcxOverviewMath: m } = setup().ctx;
  near(m.ECON_DT_MIN_C, 50 / 9, 1e-12);
  const g = { t: [1, 2, 3], rat: [21, 21, 21], mat: [18, 18, 18], fan: [1, 1, 1], oa_t: [21 - 5.5, 21 - 5.6, 21 + 5.6] };
  assert.deepEqual(arr(m.economizerRows(g), (r) => r.ident), [false, true, true]);   // |OAT-RAT| >= 5.5556
});

test("economizerRows: fan gate, identifiable delta, OA fraction, damper mixing residual", () => {
  const { rcxOverviewMath: m } = setup().ctx;
  const g = {
    t: [1, 2, 3, 4, 5],
    oa_t: [50, 50, 50, 50, 50], rat: [70, 70, 70, 70, 70], mat: [60, 65, 60, 70, 60],
    fan: [1, 1, 0, 1, 1], sat: [55, 55, 55, 55, 55], damper: [50, 50, 50, 50, null],
  };
  const rows = m.economizerRows(g, { dtMin: 10 });
  assert.deepEqual(arr(rows, (r) => r.t), [1, 2, 4, 5]);        // fan off (t=3) dropped
  assert.equal(rows[0].dOR, -20);
  assert.equal(rows[0].dMR, -10);
  assert.equal(rows[0].oaFrac, 50);
  assert.equal(rows[0].matPred, 60);                            // 70 + 0.5 * -20
  assert.equal(rows[0].matResid, 0);
  assert.equal(rows[1].matResid, 5);
  assert.equal(rows[2].oaFrac + 0, 0);
  assert.equal(rows[3].matResid, null);                         // no damper reading
  assert.equal(rows[3].damperPct, null);
  // not identifiable below the minimum delta: no OA fraction
  const lo = m.economizerRows({ ...g, oa_t: [66, 66, 66, 66, 66] }, { dtMin: 10 });
  assert.ok(lo.every((r) => !r.ident && r.oaFrac === null));
  const s = m.economizerSummary(rows);
  assert.deepEqual([s.n, s.nIdent, s.medianResid, s.maeResid], [4, 4, 5, 5]);
});

test("basVsWeb: web joined as-of within its cadence, delta, band stats, histogram", () => {
  const { rcxOverviewMath: m } = setup().ctx;
  const t = Array.from({ length: 8 }, (_, i) => T0 + i * HOUR);
  const bas = [50, 51, 52, 53, 54, 55, 56, 57];
  const web = [50, null, null, 50, null, null, 50, null];       // 3 h cadence
  assert.equal(m.webMaxAgeMs(t, web), 4.5 * HOUR);
  const r = m.basVsWeb(t, bas, web);
  assert.deepEqual(arr(r.rows, (x) => x.d), [0, 1, 2, 3, 4, 5, 6, 7]);
  assert.equal(r.band, 2);                                      // delta degC (= 3.6 delta degF)
  assert.equal(r.stats.n, 8);
  assert.equal(r.stats.bias, 3.5);
  assert.equal(r.stats.maxAbs, 7);
  assert.equal(r.stats.withinBand, 3 / 8);                      // |d| <= 2 degC: 0, 1, 2
  // stale web (older than the bound) is not joined
  const stale = m.asOfFill(t, [10, null, null, null, null, null, null, null], 2 * HOUR);
  assert.deepEqual(arr(stale), [10, 10, 10, null, null, null, null, null]);
  // histogram: contiguous bins, ends clamped
  const h = m.deltaHist([0.2, 0.4, 1.6, -0.7, 100], 1);
  assert.deepEqual(arr(h.labels).slice(0, 3), ["-1", "0", "1"]);
  assert.deepEqual(arr(h.counts).slice(0, 3), [1, 2, 1]);
  assert.equal(h.counts[h.counts.length - 1], 1);
  assert.equal(h.labels[h.labels.length - 1], "20");
});

test("mergeFaultLanes ORs equips into one time-ordered lane", () => {
  const { rcxOverviewMath: m } = setup().ctx;
  assert.deepEqual(arr(m.mergeFaultLanes([[[2, 0], [1, 1]], [[2, 1], [3, 0]], null]), (x) => arr(x)), [[1, 1], [2, 1], [3, 0]]);
});

// ---- views end to end (stubbed NF history) ----------------------------------------------------
test("weekly-fan view: runtime bars per equip, fault lane last when the SCHED-247 result point exists", async () => {
  const withResult = [...POINTS, pt("SCHED", "fdd,fault", { ruleRef: "SCHED-247", unit: "" })];
  const { ctx, model, byName } = setup(withResult);
  ctx.series.set(byName("FAN-S").uuid, hourly(48, (i) => (i < 24 ? 1 : 0)));
  ctx.series.set(byName("OAT").uuid, hourly(48, () => 40));
  ctx.series.set(byName("SCHED").uuid, hourly(48, (i) => (i > 30 ? 1 : 0)));
  const { note, out } = await renderView(ctx, model, "weekly-fan", 48);
  const o = out.option;
  // one stack per equip: in-schedule + after-hours bars add up to the 24 hourly intervals while on
  const bars = o.series.filter((s) => s.type === "bar");
  assert.deepEqual(arr(bars, (b) => b.name), ["AHU-1 · in schedule", "AHU-1 · after hours"]);
  const sum = (b) => b.data.reduce((a, [, h]) => a + h, 0);
  assert.equal(sum(bars[0]) + sum(bars[1]), 24);
  assert.equal(sum(bars[0]), 10);                                // no NF schedule, no site tz: default Mon-Fri 07-17 (UTC) = 10 h of Monday
  // the schedule reference is a step line labelled as the default calendar
  const ref = o.series.find((s) => /^schedule /.test(s.name));
  assert.equal(ref.name, "schedule 50 h/week (default)");
  assert.equal(ref.step, "end");
  assert.deepEqual(arr(ref.data[0]), [T0, 50]);
  assert.ok(o.series.some((s) => /Avg OAT/.test(s.name)));
  // lane = last grid / x axis / y axis / series
  assert.equal(o.series[o.series.length - 1].name, "SCHED-247");
  assert.equal(o.grid.length, 2);
  assert.equal(o.grid[o.grid.length - 1].height, 26);
  assert.equal(o.series[o.series.length - 1].xAxisIndex, o.xAxis.length - 1);
  assert.ok(o.xAxis.every((x) => x.min === o.xAxis[0].min));
  assert.match(note, /ISO weeks/);
  // fan_cmd view yields to fan_status: this equip has a status point, so nothing to draw
  ctx.series.set(byName("FAN-C").uuid, hourly(48, () => 1));
  const cmd = await view(ctx, "weekly-fan-cmd").render({}, ctx.rcxContext(view(ctx, "weekly-fan-cmd"),
    ctx.rcxBind(view(ctx, "weekly-fan-cmd"), model.equips, model, catalog), 48, model, catalog));
  assert.match(cmd, /counted by the fan_status view/);
});

test("weekly runtime keeps week buckets visible for a one-hour historical range and bounds fault lanes to it", async () => {
  const result = pt("SCHED", "fdd,fault", { ruleRef: "SCHED-247", unit: "" });
  const { ctx, model, byName } = setup([...POINTS, result]);
  const fromMs = T0 + 2 * 86400e3 + 12 * HOUR, toMs = fromMs + HOUR;
  const range = { preset: "custom", resolvedBounds: { fromMs, toMs } };
  const calls = [];
  ctx.fetchRange = async (points, selected, options) => {
    calls.push({ selected, options });
    return { series: new Map(points.map((p) => [p.uuid, p.rec.name === "SCHED" ? [[fromMs, 1]]
      : p.rec.name === "FAN-S" ? [[fromMs, 1], [fromMs + 5 * 60e3, 1]] : p.rec.name === "OAT" ? [[fromMs, 10]] : []])) };
  };
  const v = view(ctx, "weekly-fan"), bound = ctx.rcxBind(v, model.equips, model, catalog);
  const note = await v.render({}, ctx.rcxContext(v, bound, 1, model, catalog, range, "UTC"));
  assert.ok(ctx.rendered.length, `weekly chart should render: ${note}`);
  const option = ctx.rendered.at(-1).option;
  const lane = option.series.at(-1);
  assert.ok(calls.some((c) => c.selected === range && c.options.method === "MAX"), "fault result history uses the selected interval");
  assert.deepEqual(arr(lane.data, (x) => arr(x)), [[fromMs, 1]]);
  assert.ok(option.xAxis[0].min <= fromMs && option.xAxis[0].max > toMs, "weekly aggregate axis still spans its whole week");

  const chart = ctx.rcxContext(v, bound, 1, model, catalog, range, "UTC").chart({});
  chart.setOption({ xAxis: { type: "time" }, series: [] });
  assert.equal(chart.option.xAxis.min, fromMs, "ordinary time axes retain the selected lower bound");
  assert.equal(chart.option.xAxis.max, toMs, "ordinary time axes retain the selected upper bound");
  assert.equal(typeof chart.option.xAxis.axisLabel.formatter, "function", "site-time formatting remains installed");
});

test("no result point -> no fault lane", async () => {
  const { ctx, model, byName } = setup(POINTS.filter((p) => p.name !== "ECON1"));
  for (const n of ["OAT", "RAT", "MAT", "FAN-S", "DMP"]) ctx.series.set(byName(n).uuid, hourly(24, () => 1));
  ctx.series.get(byName("OAT").uuid).forEach((s) => (s[1] = 50));
  ctx.series.get(byName("RAT").uuid).forEach((s) => (s[1] = 70));
  ctx.series.get(byName("MAT").uuid).forEach((s) => (s[1] = 60));
  ctx.series.get(byName("DMP").uuid).forEach((s) => (s[1] = 50));
  const { out } = await renderView(ctx, model, "economizer-mat-residual", 24);
  assert.ok(!Array.isArray(out.option.grid), "grid stays a single object without a lane");
  assert.equal(out.option.series.length, 1);
});

test("economizer views: lane is the last grid when ECON-1 result exists; delta scatter has none", async () => {
  const { ctx, model, byName } = setup();
  const set = (n, f) => ctx.series.set(byName(n).uuid, hourly(24, f));
  set("OAT", () => 50); set("RAT", () => 70); set("MAT", (i) => 60 + (i % 3)); set("SAT", () => 55);
  set("FAN-S", () => 1); set("DMP", () => 50); set("ECON1", (i) => (i > 12 ? 1 : 0));
  for (const id of ["economizer-mat-residual", "economizer-temps"]) {
    const { out } = await renderView(ctx, model, id, 24);
    const o = out.option;
    assert.equal(o.series[o.series.length - 1].name, "ECON-1", id);
    assert.equal(o.grid[o.grid.length - 1].height, 26, id);
    assert.equal(o.yAxis[o.yAxis.length - 1].gridIndex, o.grid.length - 1, id);
    assert.ok(o.series[o.series.length - 1].areaStyle === ctx.FAULT_LANE.areaStyle);
  }
  const resid = ctx.rendered.find((r) => r.name === "economizer_mat_residual").option.series[0].data;
  assert.deepEqual(arr(resid, (d) => d[1]).slice(0, 3), [0, 1, 2]);   // MAT 60..62 vs mixing model 60
  const scatter = await renderView(ctx, model, "economizer-delta", 24);
  assert.ok(scatter.out.option.series.every((s) => s.type === "scatter"));
  assert.ok(!Array.isArray(scatter.out.option.grid));
});

test("bas-vs-web views: overlay with OAT-METEO lane, band uses theme colors, histogram has no lane", async () => {
  const meteo = [...POINTS, pt("OATM", "fdd,fault", { ruleRef: "OAT-METEO", unit: "" })];
  const { ctx, model, byName } = setup(meteo);
  ctx.series.set(byName("OAT").uuid, hourly(24, (i) => 50 + (i % 2)));
  ctx.series.set(byName("WX").uuid, hourly(24, () => 50));
  ctx.series.set(byName("OATM").uuid, hourly(24, (i) => (i > 20 ? 1 : 0)));
  const { note, out } = await renderView(ctx, model, "bas-vs-web-oat", 24);
  const o = out.option;
  assert.equal(o.series[o.series.length - 1].name, "OAT-METEO");
  assert.deepEqual(arr(o.series.slice(0, 2), (s) => s.name), ["Web OAT", "BAS oa_t"]);
  assert.equal(o.series[3].areaStyle.color, undefined);         // color comes from the theme palette
  near(o.series[3].data[0][1], 7.2, 1e-9);                      // 2 x 3.6 delta degF band (2 degC in SI math)
  assert.match(note, /bias 0\.50 Δ°F/);
  const h = await renderView(ctx, model, "bas-vs-web-oat-hist", 24);
  assert.ok(!Array.isArray(h.out.option.grid));
  assert.deepEqual(arr(h.out.option.series[0].data), [12, 12]);
});

test("mech-cooling view bins on-hours by web OAT", async () => {
  const { ctx, model } = setup([
    rec("CH-1", "POINT", { siteRef: "s", equipRef: "AHU-1", markers: "point,his,compressor,run,sensor", kind: "Bool" }),
    POINTS[8],
  ]);
  const byName = (n) => model.points.find((p) => p.rec.name === n);
  ctx.series.set(byName("CH-1").uuid, hourly(10, (i) => (i < 5 ? 1 : 0)));
  ctx.series.set(byName("WX").uuid, hourly(10, () => 85));
  const { out } = await renderView(ctx, model, "mech-cooling-compressor-status", 10);
  const bar = out.option.series[0];
  assert.equal(bar.name, "AHU-1");
  assert.deepEqual(arr(out.option.xAxis.data), ["<50", "50-60", "60-70", "70-80", "80-90", ">=90"]);
  assert.deepEqual(arr(bar.data), [null, null, null, null, 5, null]);
});

// ---- the same physical data in degF and degC points: same SI decisions, display switches last ----
function unitSetup(unit) {
  const conv = unit === "°F" ? (f) => f : F2C;                  // fixtures are written in degF
  const pts = POINTS.map((p) => (p.attrs.unit === "°F" ? { ...p, attrs: { ...p.attrs, unit } } : p));
  const s = setup(pts.concat([pt("OATM", "fdd,fault", { ruleRef: "OAT-METEO", unit: "" })]));
  const set = (n, f) => s.ctx.series.set(s.byName(n).uuid, hourly(48, (i) => conv(f(i))));
  set("OAT", (i) => 50 + (i % 2)); set("WX", () => 50); set("RAT", () => 70); set("MAT", (i) => 60 + (i % 3));
  set("SAT", () => 55);
  s.ctx.series.set(s.byName("DMP").uuid, hourly(48, () => 50));   // percent: not a temperature, never converted
  s.ctx.series.set(s.byName("FAN-S").uuid, hourly(48, () => 1));
  return s;
}

test("BAS vs web OAT: a degF point and a degC point give the same decision (within band %, bias)", async () => {
  const f = unitSetup("°F"), c = unitSetup("°C");
  const rf = await renderView(f.ctx, f.model, "bas-vs-web-oat", 48), rc = await renderView(c.ctx, c.model, "bas-vs-web-oat", 48);
  assert.equal(rf.note, rc.note);                               // 24 + 24 samples, bias 0.50 delta degF, 100 % in band
  assert.match(rf.note, /within band 100%/);
  const a = rf.out.option.series[1].data, b = rc.out.option.series[1].data;
  a.forEach(([, v], i) => near(v, b[i][1], 1e-9));
});

test("display system switches last: SI shows degC / delta degC, imperial degF / delta degF, same math", async () => {
  const s = unitSetup("°F");
  s.ctx.units = "imperial";
  const imp = await renderView(s.ctx, s.model, "bas-vs-web-oat", 48);
  s.ctx.units = "si";
  const si = await renderView(s.ctx, s.model, "bas-vs-web-oat", 48);
  assert.equal(imp.out.option.yAxis.name, "°F"); assert.equal(si.out.option.yAxis.name, "°C");
  near(imp.out.option.series[1].data[0][1], 50, 1e-9);          // BAS 50 degF ...
  near(si.out.option.series[1].data[0][1], 10, 1e-9);           // ... = 10 degC
  assert.match(si.note, /bias 0\.28 Δ°C/);                      // 0.5 delta degF = 0.278 delta degC
  near(si.out.option.series[3].data[0][1], 4, 1e-9);            // band = 2 x 2 delta degC (imperial: 7.2)
  // economizer scatter: the identifiable-delta note shows 10 delta degF or 5.6 delta degC
  const eImp = (s.ctx.units = "imperial", await renderView(s.ctx, s.model, "economizer-delta", 48));
  const eSi = (s.ctx.units = "si", await renderView(s.ctx, s.model, "economizer-delta", 48));
  assert.match(eImp.note, />= 10\.0 Δ°F/); assert.match(eSi.note, />= 5\.6 Δ°C/);
  const x = (o) => o.series.flatMap((q) => q.data.map((d) => d[0]));
  x(eImp.out.option).forEach((v, i) => near(v, x(eSi.out.option)[i] * 1.8, 0.02));
});

test("economizer residual / mech-cooling: degF and degC points give identical SI decisions", async () => {
  const f = unitSetup("°F"), c = unitSetup("°C");
  const rf = await renderView(f.ctx, f.model, "economizer-mat-residual", 48), rc = await renderView(c.ctx, c.model, "economizer-mat-residual", 48);
  assert.equal(rf.note, rc.note);
  assert.deepEqual(arr(rf.out.option.series[0].data, (d) => d[1]), arr(rc.out.option.series[0].data, (d) => d[1]));
});
