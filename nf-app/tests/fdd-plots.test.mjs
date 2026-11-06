// node --test nf-app/tests/fdd-plots.test.mjs — FDD + sensor plots (fdd-plots.js).
// Sensor limits/masks/health run in SI; NF history arrives in each point's own unit (fetchSeries
// stub) and charts show the display system (ctx.units = "imperial" | "si").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
const H = 3600e3;

// Fake NF history: seriesData[uuid] = [[ms, v], ...]; calls are recorded.
function load(seriesData = {}) {
  const calls = [];
  const ctx = vm.createContext({
    console, URLSearchParams, localStorage: { getItem: () => ctx.units },
    FAULT_LANE: { lineStyle: { color: "red", width: 1 }, areaStyle: { color: "pink" } },
    palette: () => ["c0", "c1", "c2", "c3", "c4", "c5"],
    pickWindow: () => 300,
    fetchSeries: async (list, hours, o = {}) => {
      calls.push({ uuids: list.map((p) => p.uuid), hours, o });
      return new Map(list.map((p) => [p.uuid, seriesData[p.uuid] || []]));
    },
    ofddChart: (el) => ({ setOption() {}, resize() {}, el }),
    ofddRender: (chart, option, name) => { chart.rendered = { option, name }; ctx.last = chart; },
  });
  ctx.units = "imperial";
  for (const f of ["units.js", "model.js", "fdd.js", "rcx.js", "fdd-plots.js"]) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  ctx.calls = calls;
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
}
const plain = (x) => JSON.parse(JSON.stringify(x));
const F2C = (f) => (f - 32) * 5 / 9;
const near = (a, b, e = 1e-6) => assert.ok(Math.abs(a - b) < e, `${a} != ${b}`);
const pt = (uuid, name, extra = {}) => ({ uuid, name, dis: name, tags: ["point"], units: "°F", kind: "Number", equipRef: "AHU-1", siteRef: "s", rec: { attrs: {} }, ...extra });

test("views register in the right groups with roles that exist in fdd-catalog", () => {
  const ctx = load();
  const views = ctx.get("RCX_VIEWS");
  const by = Object.fromEntries(views.map((v) => [v.id, v]));
  assert.equal(by["fdd-oat-meteo"].group, "Weather");
  assert.deepEqual(Array.from(by["fdd-oat-meteo"].roles.required), ["oa_t", "web_oa_t"]);
  assert.equal(by["fdd-sensor-health"].group, "Sensors");
  assert.equal(by["fdd-sensor-fault"].group, "Sensors");
  for (const v of views) for (const r of [...v.roles.required, ...v.roles.optional]) assert.ok(catalog.roles[r], `${v.id}: role ${r} not in catalog`);
  assert.ok(catalog.roles.oa_damper_pct);
});

test("role expansion: ECON rules gain the OA damper when it is bound", () => {
  const ctx = load();
  const bound = { oa_damper_pct: [pt("d", "damper")] };
  assert.deepEqual(Array.from(ctx.fddPlotExpandRoles("ECON-3", ["oa_t"], bound)), ["oa_t", "oa_damper_pct"]);
  assert.deepEqual(Array.from(ctx.fddPlotExpandRoles("ECON-3", ["oa_t", "oa_damper_pct"], bound)), ["oa_t", "oa_damper_pct"]);
  assert.deepEqual(Array.from(ctx.fddPlotExpandRoles("ECON-3", ["oa_t"], {})), ["oa_t"]);
  assert.deepEqual(Array.from(ctx.fddPlotExpandRoles("SV-RANGE", ["oa_t"], bound)), ["oa_t"]);
});

test("sensor masks: flatline, spike and range (z and physical bounds)", () => {
  const ctx = load();
  const v = [...Array(10).fill(70), 70.5, 69.5, 70, 70.2, 69.8, 200, 70, 70];
  const m = plain(ctx.fddPlotSensorMasks(v, { flatlineWindow: 6, minSlice: 5, rangeZ: 3, spikeZ: 3 }));
  assert.deepEqual(m["SV-FLATLINE"].slice(0, 10), Array(10).fill(1));
  assert.equal(m["SV-FLATLINE"][12], 0);
  assert.equal(m["SV-SPIKE"][15], 1);
  assert.equal(m["SV-RANGE"][15], 1);
  const b = plain(ctx.fddPlotSensorMasks([60, 70, 160, null, -50], { bounds: { min: -40, max: 150 } }));
  assert.deepEqual(b["SV-RANGE"], [0, 0, 1, 0, 1]);
});

test("hourly health: ok / flatline / out of range / stale, with gaps handled", () => {
  const ctx = load();
  const grid = Array.from({ length: 10 }, (_, i) => i * H);
  const m = (pairs) => new Map(pairs);
  // SI inputs (degC): 21 C ~ 70 F; 93 C is out of range (limit 65.556 C = 150 F)
  const avg = m([[0, 21], [1 * H, 21], [2 * H, 21], [3 * H, 93], [4 * H, 21.5], /* 5 gap (short) */ [6 * H, 21.5]]);
  const min = m([[0, 15.5], [1 * H, 21], [2 * H, 21], [3 * H, 93], [4 * H, 21], [6 * H, 21]]);
  const max = m([[0, 26.7], [1 * H, 21.01], [2 * H, 21], [3 * H, 93], [4 * H, 22.2], [6 * H, 22.2]]);
  const count = m([[0, 12], [1 * H, 12], [2 * H, 2], [3 * H, 12], [4 * H, 12], [6 * H, 12]]);
  const s = plain(ctx.fddPlotHealthStates(grid, { avg, min, max, count }, { family: "temp" }));
  // hours 7-9 have no data: a 3 h trailing run >= staleHours(2) -> stale; hour 5 is a 1 h gap -> null.
  assert.deepEqual(s, [0, 2, 0, 3, 0, null, 0, 1, 1, 1]);
  // leading hours before first sample stay null; the limit is SI (65.556 C): 80 C is out of range, 21 C is fine
  const one = (v) => ({ avg: m([[2 * H, v]]), min: m([[2 * H, v]]), max: m([[2 * H, v]]), count: m([[2 * H, 1]]) });
  assert.deepEqual(plain(ctx.fddPlotHealthStates([0, H, 2 * H], one(80), { family: "temp" })), [null, null, 3]);
  assert.deepEqual(plain(ctx.fddPlotHealthStates([0, H, 2 * H], one(65), { family: "temp" })), [null, null, 0]);
  // pressure limits are Pa (-5..15 inH2O = -1245..3736 Pa); percent -2..102
  assert.deepEqual(plain(ctx.fddPlotHealthStates([0], { avg: m([[0, 3700]]), min: m([[0, 3700]]), max: m([[0, 3700]]) }, { family: "pressure" })), [0]);
  assert.deepEqual(plain(ctx.fddPlotHealthStates([0], { avg: m([[0, 3800]]), min: m([[0, 3800]]), max: m([[0, 3800]]) }, { family: "pressure" })), [3]);
  assert.equal(ctx.fddPlotCanon, undefined, "no per-unit canon helper any more");
  assert.deepEqual(plain(ctx.fddPlotLimits.temp), { min: -40, max: 65.556 });
});

test("unit families group by quantity (any temperature unit -> temp, any pressure unit -> pressure)", () => {
  const ctx = load();
  const fam = (units, extra) => ctx.fddPlotUnitFamily(pt("x", "x", { units, ...extra }));
  assert.equal(fam("°F"), "temp"); assert.equal(fam("°C"), "temp"); assert.equal(fam("K"), "temp");
  assert.equal(fam("inH₂O"), "pressure"); assert.equal(fam("kPa"), "pressure");
  assert.equal(fam("cfm"), "flow"); assert.equal(fam("L/s"), "flow");
  assert.equal(fam("kW"), "power"); assert.equal(fam("%"), "pct");
  assert.equal(fam("", { kind: "Bool" }), "bool");
});

test("heatmap option: categorical states, one row per sensor, no data cells for null", () => {
  const ctx = load();
  const o = ctx.fddPlotHealthOption({ title: "t", hours: [0, H], rows: [{ label: "a", states: [0, null] }, { label: "b", states: [3, 1] }] });
  assert.deepEqual(plain(o.series[0].data), [[0, 0, 0], [0, 1, 3], [1, 1, 1]]);
  assert.equal(o.visualMap.pieces.length, 4);
  assert.equal(o.visualMap.pieces[3].color, "red");
});

test("rule plot: unit-family grids, fault lane is the LAST grid (via rcxWithFaultLane)", async () => {
  const sat = pt("sat", "sat"), oat = pt("oat", "oat", { units: "°F" }), damper = pt("dmp", "damper", { units: "%" });
  const res = pt("res", "res", { tags: ["fdd", "fault"], rec: { attrs: { ruleRef: "ECON-1" } } });
  const ctx = load({
    sat: [[0, 55], [300e3, 56]], oat: [[0, 40], [300e3, 41]], dmp: [[0, 10]],
    res: [[0, 0], [H, 12], [2 * H, 0]],
  });
  const rule = { id: "ECON-1", required_roles: ["sat", "oa_t"], optional_roles: [] };
  const el = { style: {} };
  const note = await ctx.fddRulePlot(el, {
    rule, equipRec: { name: "AHU-1", attrs: {} }, resultPoint: res, hours: 24,
    bound: { sat: [sat], oa_t: [oat], oa_damper_pct: [damper] },
  });
  const o = plain(ctx.last.rendered.option);
  assert.equal(o.grid.length, 3, "temp grid, pct grid, fault lane");
  assert.equal(o.series.length, 4);
  const lane = o.series[o.series.length - 1];
  assert.equal(lane.name, "ECON-1");
  assert.equal(lane.xAxisIndex, 2);
  assert.equal(lane.step, "end");
  assert.deepEqual(lane.lineStyle, { color: "red", width: 1 });
  assert.deepEqual(lane.data, [[0, 0], [H, 1], [2 * H, 0]]);
  assert.deepEqual(o.series.slice(0, 3).map((s) => s.yAxisIndex), [0, 0, 1]);
  assert.match(note, /fault in 1 of 3/);
  assert.ok(parseInt(el.style.height) > 400);
  // The fault lane is fetched hourly with MAX.
  assert.ok(ctx.calls.some((c) => c.uuids[0] === "res" && c.o.method === "MAX" && c.o.windowSec === 3600));
  // imperial display: the degF history is plotted as-is, axis named in degF
  assert.equal(o.yAxis[0].name, "°F");
  near(o.series[0].data[0][1], 55, 1e-9);
});

test("rule plot: signals are plotted in the display system (SI display shows degC, same history)", async () => {
  const sat = pt("sat", "sat"), oatC = pt("oat", "oat", { units: "°C" }), dmp = pt("dmp", "damper", { units: "%" });
  const hist = { sat: [[0, 55], [300e3, 56]], oat: [[0, F2C(40)], [300e3, F2C(41)]], dmp: [[0, 10]] };
  const run = async (units) => {
    const ctx = load(hist);
    ctx.units = units;
    await ctx.fddRulePlot({ style: {} }, { rule: { id: "ECON-1", required_roles: ["sat", "oa_t"], optional_roles: [] },
      equipRec: { name: "AHU-1", attrs: {} }, hours: 24, bound: { sat: [sat], oa_t: [oatC], oa_damper_pct: [dmp] } });
    return plain(ctx.last.rendered.option);
  };
  const imp = await run("imperial"), si = await run("si");
  // one temp family even though the two points have different native units (°F vs °C)
  assert.equal(imp.grid.length, 2); assert.equal(si.grid.length, 2);
  assert.equal(imp.yAxis[0].name, "°F"); assert.equal(si.yAxis[0].name, "°C");
  near(imp.series[0].data[0][1], 55, 1e-9); near(si.series[0].data[0][1], F2C(55), 1e-9);   // sat: native F
  near(imp.series[1].data[0][1], 40, 1e-9); near(si.series[1].data[0][1], F2C(40), 1e-9);   // oat: native C
  assert.match(imp.series[0].name, /sat \(°F\)/); assert.match(si.series[1].name, /oa_t \(°C\)/);
  assert.equal(imp.series[2].data[0][1], 10);                                            // percent never converted
});

test("rule plot without a result point draws signals only; without bound inputs it says so", async () => {
  const ctx = load({ a: [[0, 1], [300e3, 2]] });
  const rule = { id: "SV-X", required_roles: ["sat"], optional_roles: [] };
  const note = await ctx.fddRulePlot({ style: {} }, { rule, equipRec: { name: "E", attrs: {} }, bound: { sat: [pt("a", "a")] }, resultPoint: null });
  assert.match(note, /no result point/);
  assert.equal(plain(ctx.last.rendered.option).grid.length, 1);
  assert.match(await ctx.fddRulePlot({ style: {} }, { rule, equipRec: { name: "E", attrs: {} }, bound: {} }), /No bound input/);
});

test("OAT-METEO view: lane from rcxFaultData is the last grid; omitted when no result point", async () => {
  const bas = pt("bas", "bas"), web = pt("web", "web", { tags: ["weather"] });
  const res = pt("res", "res", { tags: ["fdd", "fault"], rec: { attrs: { ruleRef: "OAT-METEO" } } });
  const ctx = load({ bas: [[0, 50]], web: [[0, 51]], res: [[0, 5], [H, 0]] });
  const view = ctx.get("RCX_VIEWS").find((v) => v.id === "fdd-oat-meteo");
  const mk = (points) => ctx.rcxContext(view, [{ id: "AHU-1", name: "AHU-1", bound: { oa_t: [bas], web_oa_t: [web] } }], 24, { points }, catalog);
  const note = await view.render({ style: {} }, mk([bas, web, res]));
  const o = plain(ctx.last.rendered.option);
  assert.equal(o.yAxis[0].name, "°F"); near(o.series[0].data[0][1], 50, 1e-9);
  assert.equal(o.grid.length, 2);
  assert.equal(o.series[o.series.length - 1].xAxisIndex, 1);
  assert.deepEqual(o.series[o.series.length - 1].data, [[0, 1], [H, 0]]);
  assert.match(note, /fault in 1 of 2/);
  await view.render({ style: {} }, mk([bas, web]));
  assert.equal(plain(ctx.last.rendered.option).grid.length, 1);
});

test("sensor fault view: worst sensor, mask lanes are the trailing grids", async () => {
  const a = pt("a", "good"), b = pt("b", "bad");
  const good = Array.from({ length: 8 }, (_, i) => [i * H, 70 + i]);
  const bad = Array.from({ length: 8 }, (_, i) => [i * H, i === 4 ? 300 : 70 + (i % 2)]);
  const ctx = load({ a: good, b: bad });
  const view = ctx.get("RCX_VIEWS").find((v) => v.id === "fdd-sensor-fault");
  const eq = { id: "AHU-1", name: "AHU-1", bound: { sat: [a], oa_t: [b] } };
  const note = await view.render({ style: {} }, ctx.rcxContext(view, [eq], 24, { points: [] }, catalog));
  const o = plain(ctx.last.rendered.option);
  assert.equal(o.yAxis[0].name, "°F");                       // flagged in SI (300 F = 149 C > 65.6 C), shown in display units
  near(o.series[0].data.find(([, v]) => v > 200)[1], 300, 1e-9);
  assert.equal(o.grid.length, 4, "signal + SV-FLATLINE + SV-SPIKE + SV-RANGE");
  assert.deepEqual(o.series.slice(1).map((s) => s.name), ["SV-FLATLINE", "SV-SPIKE", "SV-RANGE"]);
  assert.deepEqual(o.series.slice(1).map((s) => s.xAxisIndex), [1, 2, 3]);
  assert.match(o.title.text, /oa_t/);
  assert.match(note, /oa_t/);
});

test("health view tells you when no sensor role is bound", async () => {
  const ctx = load();
  const view = ctx.get("RCX_VIEWS").find((v) => v.id === "fdd-sensor-health");
  const note = await view.render({ style: {} }, { equips: [{ id: "x", name: "x", bound: {} }], hours: 24, first: () => null });
  assert.match(note, /No temperature/);
});
