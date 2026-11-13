// node --test nf-app/tests/rcx-presets.test.mjs — RCx presets: math, registration, roles, fault lane.
// Math is SI (degC, Pa, C-days); fixtures give NF history in the point's own unit and the display
// system (ctx.units = "imperial" | "si") only changes what the charts show.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));

const F2C = (f) => (f - 32) * 5 / 9;
const near = (a, b, e = 1e-6) => assert.ok(Math.abs(a - b) < e, `${a} != ${b}`);

function load(fetchData = new Map()) {
  const rendered = [];
  const ctx = vm.createContext({
    localStorage: { getItem: () => ctx.units },
    console, URLSearchParams, TextDecoder, atob, btoa,
    echarts: { registerTheme() {} },
    FAULT_LANE: { lineStyle: { color: "red" }, areaStyle: { color: "red" } },
    pickWindow: () => 3600,
    fetchSeries: async (list) => new Map(list.map((p) => [p.uuid, fetchData.get(p.uuid) || []])),
    ofddChart: (el) => ({ el }),
    ofddRender: (chart, option, name) => rendered.push({ chart, option, name }),
  });
  ctx.units = "imperial";
  for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "rcx.js", "rcx-presets.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  ctx.get = (name) => vm.runInContext(name, ctx);
  ctx.rendered = rendered;
  return ctx;
}

// vav_flows (zone airflow timeseries) was removed on purpose; vav_positions and vav_reheat_dats take its place in the VAV group.
const IDS = ["zone_comfort_rank", "zone_temps", "ahu_dats", "ahu_mats", "ahu_rats", "ahu_dampers", "duct_static_box",
  "duct_static_ts", "ahu_sat_reset_scatter", "hw_reset_scatter", "chw_reset_scatter", "cw_reset_scatter",
  "vav_positions", "vav_reheat_dats", "vav_health", "fan_speeds", "meter_elec_cdd", "meter_gas_hdd", "chw_temps_ts", "cw_temps_ts"];

test("all preset ids are registered once, in a known group, with real catalog roles", () => {
  const ctx = load();
  const views = Array.from(ctx.get("RCX_VIEWS"));
  for (const id of IDS) assert.equal(views.filter((v) => v.id === id).length, 1, id);
  assert.equal(views.length, IDS.length);
  const groups = new Set(["Zones", "Air handlers", "Plant", "VAV", "Metering", "Scatter plots"]);
  const kinds = new Set(Object.keys(catalog.equipment_kinds));
  for (const v of views) {
    assert.ok(groups.has(v.group), `${v.id} group ${v.group}`);
    assert.equal(v.scope, "site");
    for (const k of v.kinds) assert.ok(kinds.has(k), `${v.id} kind ${k}`);
    for (const r of [...v.roles.required, ...v.roles.optional]) assert.ok(catalog.roles[r], `${v.id}: role ${r} not in fdd-catalog.json`);
  }
});

test("fault-lane rule ids exist in fdd-catalog.json", () => {
  const ids = new Set(catalog.rules.map((r) => r.id));
  for (const id of ["FC1", "AHU-DUCTHI", "AHU-SATDEV", "ZONE-COMFORT-PCT", "CHW-1"]) assert.ok(ids.has(id), id);
});

test("comfort %, ranking and per-sample bands", () => {
  const m = load().get("rcxPresetMath");
  const s = m.comfortStats([68, 72, 74, 76, null], 70, 75);
  assert.deepEqual([s.n, s.inBand, s.below, s.above, s.pct], [4, 2, 1, 1, 50]);
  assert.equal(m.comfortStats([70, 80], [60, 60], [75, null]).n, 1);     // unknown band -> skipped
  assert.equal(m.comfortStats([], 70, 75).pct, null);
  // SI thresholds: 70-75 F = 21.111-23.889 C; setpoint +/- 2.5 delta F = 1.3889 delta C
  const [lo, hi] = m.defaultBand();
  near(lo, 21.1111, 1e-4); near(hi, 23.8889, 1e-4);
  near(m.spHalfWidth(), 2.5 / 1.8, 1e-12);
  near(m.DEGREE_DAY_BASE_C, 18.3333, 1e-4);
  assert.equal(m.toF, undefined, "no per-unit F conversion helpers any more");
  const ranked = m.rankComfort([{ label: "b", value: 90 }, { label: "a", value: 40 }, { label: "c", value: null }]);
  assert.deepEqual(Array.from(ranked, (r) => r.label), ["a", "b"]);
});

test("reset fit and pairing on a shared time grid", () => {
  const m = load().get("rcxPresetMath");
  const f = m.resetFit([[0, 100], [10, 80], [20, 60], [null, 5]]);
  assert.ok(Math.abs(f.slope + 2) < 1e-9 && Math.abs(f.intercept - 100) < 1e-9 && Math.abs(f.r2 - 1) < 1e-9);
  assert.deepEqual([f.n, f.x0, f.x1], [3, 0, 20]);
  assert.equal(m.resetFit([[1, 1]]), null);
  const pairs = m.pairSeries([[0, 50], [3600e3, 60]], [[10, 1], [3600e3 + 5, 2], [7200e3, 3]], 3600e3);
  assert.deepEqual(Array.from(pairs, (p) => Array.from(p)), [[50, 1], [60, 2]]);
});

test("degree days (base 18.333 C = 65 F, in C-days), daily energy and monthly join", () => {
  const m = load().get("rcxPresetMath");
  near(m.degreeDay(F2C(75), "cdd"), 10 / 1.8);
  assert.equal(m.degreeDay(F2C(75), "hdd"), 0);
  near(m.degreeDay(F2C(40), "hdd"), 25 / 1.8);
  const d = (day, h = 0) => Date.UTC(2026, 6, day, h);
  const oat = [[d(1), F2C(75)], [d(2), F2C(65)], [d(3), F2C(85)]];                // SI in
  const dd = m.monthlyDegreeDays(m.dailyMeans(oat), "cdd");
  near(dd.get("2026-07").dd, 30 / 1.8, 1e-9); assert.equal(dd.get("2026-07").days, 3);
  near(m.monthlyDegreeDays(m.dailyMeans([[d(1), 0]]), "hdd").get("2026-07").dd, 18.3333, 1e-4);   // 0 C is 18.3 C-days below base
  // kW -> kWh (x24), interval kWh, cumulative register (differences)
  assert.equal(m.dailyEnergy([[d(1), 2]], "rate").get("2026-07-01"), 48);
  assert.equal(m.dailyEnergy([[d(1), 5], [d(1, 1), 7]], "interval").get("2026-07-01"), 12);
  const reg = [[d(1), 100], [d(2), 130], [d(3), 150], [d(5), 400]];                  // 2-day gap skipped
  assert.ok(m.isCumulative(reg));
  assert.ok(!m.isCumulative([[1, 5], [2, 1], [3, 7], [4, 2]]));
  const e = m.dailyEnergy(reg, "cumulative");
  assert.deepEqual([e.get("2026-07-02"), e.get("2026-07-03"), e.has("2026-07-05")], [30, 20, false]);
  const rows = m.meterRows(m.monthlySum(e), dd);
  assert.deepEqual(Array.from(rows, (r) => [r.month, r.energy]), [["2026-07", 50]]);
  near(rows[0].dd, 30 / 1.8, 1e-9);
});

test("ported renderers return options (or null when empty)", () => {
  const o = load().get("rcxPresetMath").options;
  const rows = [1, 2, 3].map((i) => ({ equipment_id: `A${i}`, series: "primary", ts: i * 1000, value: i }));
  assert.equal(o.multiEquipmentTimeseriesOption(rows).series.length, 3);
  assert.equal(o.multiEquipmentTimeseriesOption([]), null);
  const sc = o.oatScatterOption([{ equipment_id: "A", oat: 1, value: 2 }], { fit: { slope: 1, intercept: 0, r2: 1, n: 5, x0: 0, x1: 2 } });
  assert.deepEqual(Array.from(sc.series, (s) => s.type), ["scatter", "line"]);
  assert.equal(o.oatScatterOption([{ oat: null, value: 1 }]), null);
  assert.equal(o.multiEquipmentBoxOption(rows).series[0].data.length, 3);
  assert.equal(o.rankingBarsOption([{ label: "a", value: 1 }, { label: "b", value: 5 }]).yAxis.data[0], "b");
  assert.equal(o.rankingBarsOption([{ label: "a", value: 1 }, { label: "b", value: 5 }], { worstFirst: true }).yAxis.data[0], "a");
  assert.equal(o.comfortDonutOption([{ label: "x", value: 0 }]), null);
  assert.equal(o.vavHealthDonutOption([{ label: "x", value: 3 }]).title.text, "VAV health");
  // the donut is sized in percent of its container (never a fixed size) with short labels, so it cannot be cut off
  const pie = o.comfortDonutOption([{ label: "x", value: 3 }, { label: "y", value: 1 }]).series[0];
  assert.ok(pie.radius.every((r) => /^\d+%$/.test(r) && parseInt(r, 10) <= 60), "radius is a percentage of the frame");
  assert.ok(pie.center.every((c) => /%$/.test(c)));
  assert.equal(pie.label.formatter, "{d}%");
  assert.equal(o.vavHealthWorstBarsOption([{ label: "x", value: 3 }]).title.text, "Worst zones");
  assert.equal(o.meteringChartsOption([{ month: "2026-07", energy: 5, dd: 3 }]).series.length, 2);
});

// One AHU with duct static + setpoint and a fault-result point for rule FC1.
const rec = (name, pointType, attrs) => ({ uuid: `u-${name}`, name, pointType, attrs });
const MODEL = {
  sites: [rec("S", "SITE", { id: "s" })],
  equips: [rec("AHU-1", "EQUIPMENT", { id: "AHU-1", siteRef: "s", markers: "equip,ahu" })],
  devices: [],
  points: [
    rec("DSP", "POINT", { siteRef: "s", equipRef: "AHU-1", markers: "point,sensor,discharge,air,pressure,his", kind: "Number", unit: "inH₂O" }),
    rec("DSP-SP", "POINT", { siteRef: "s", equipRef: "AHU-1", markers: "point,sp,discharge,air,pressure,his", kind: "Number", unit: "inH₂O" }),
    rec("FC1-RES", "POINT", { siteRef: "s", equipRef: "AHU-1", markers: "point,fdd,fault,his", kind: "Number", ruleRef: "FC1" }),
  ],
};

function mount(ctx, id, data) {
  const model = { ...MODEL, points: MODEL.points.map(ctx.toPoint) };
  const view = Array.from(ctx.get("RCX_VIEWS")).find((v) => v.id === id);
  const equips = ctx.rcxBind(view, MODEL.equips, model, catalog);
  assert.equal(equips.length, 1, "AHU binds");
  const c = ctx.rcxContext(view, equips, 24, model, catalog);
  const el = { style: {}, clientHeight: 300 };
  return view.render(el, c);
}

test("duct_static_ts: FC1 fault lane is the last grid when its result point has data", async () => {
  const t = Date.parse("2026-07-01T00:00:00Z");
  const data = new Map([
    ["u-DSP", [[t, 1.1], [t + 3600e3, 1.2]]], ["u-DSP-SP", [[t, 1.0], [t + 3600e3, 1.0]]],
    ["u-FC1-RES", [[t, 0], [t + 3600e3, 2]]],
  ]);
  const ctx = load(data);
  await mount(ctx, "duct_static_ts");
  const { option } = ctx.rendered.at(-1);
  assert.equal(option.grid.length, 2);
  const last = option.series.at(-1);
  assert.equal(last.xAxisIndex, option.grid.length - 1);
  assert.equal(option.yAxis.at(-1).name, "FC1");
  assert.deepEqual(Array.from(last.data, (d) => Array.from(d)), [[t, 0], [t + 3600e3, 1]]);
  assert.ok(option.series.slice(0, -1).every((s) => s.xAxisIndex === undefined));   // signals on grid 0
  // history is inH2O; math is Pa; the chart shows the display system (here imperial = inH2O)
  assert.equal(option.yAxis[0].name, "inH₂O");
  near(option.series[0].data[0][1], 1.1, 1e-9);
});

test("duct static: the SI display system shows Pa (display conversion is the last step)", async () => {
  const t = Date.parse("2026-07-01T00:00:00Z");
  const data = new Map([["u-DSP", [[t, 1.1]]], ["u-DSP-SP", [[t, 1.0]]]]);
  const ctx = load(data);
  ctx.units = "si";
  await mount(ctx, "duct_static_ts");
  const { option } = ctx.rendered.at(-1);
  assert.equal([].concat(option.yAxis)[0].name, "Pa");
  near(option.series[0].data[0][1], 1.1 * 249.0889, 1e-6);
  const box = await mount(ctx, "duct_static_box");
  assert.equal(ctx.rendered.at(-1).option.yAxis.name, "Pa");
  assert.match(box, /samples|No duct/);
});

test("no result point data -> no lane; scatter/box presets never get one", async () => {
  const t = Date.parse("2026-07-01T00:00:00Z");
  const data = new Map([["u-DSP", [[t, 1.1]]], ["u-DSP-SP", [[t, 1.0]]]]);
  const ctx = load(data);
  await mount(ctx, "duct_static_ts");
  assert.ok(!Array.isArray(ctx.rendered.at(-1).option.grid));
  const note = await mount(ctx, "duct_static_box");
  const box = ctx.rendered.at(-1).option;
  assert.equal(box.series[0].type, "boxplot");
  assert.ok(!Array.isArray(box.grid) || box.grid.length === 1);
  assert.match(note, /samples/);
});

test("VAV health math: comfort, rogue damper (>=20 h), broken flow, verdict", () => {
  const m = load().get("rcxPresetMath");
  const fill = (v) => Array(24).fill(v);                    // 24 hourly buckets
  const healthy = m.vavHealthStats({ temp: fill(72), lo: 70, hi: 75, damper: fill(0.4), flow: fill(100), flowSp: fill(100) }, 3600);
  assert.deepEqual([healthy.poor, healthy.rogue, healthy.broken, healthy.anyPct], [false, false, false, 0]);
  assert.equal(m.vavVerdict(healthy), "Healthy");
  const rogue = m.vavHealthStats({ temp: fill(72), lo: 70, hi: 75, damper: fill(100) }, 3600);   // percent units
  assert.equal(rogue.rogue, true);
  assert.equal(m.vavVerdict(rogue), "Rogue damper");
  assert.equal(m.vavHealthStats({ temp: fill(72), lo: 70, hi: 75, damper: fill(1) }, 1800).rogue, null);   // 12 h < 20 h
  const broken = m.vavHealthStats({ temp: fill(80), lo: 70, hi: 75, flow: fill(50), flowSp: fill(100) }, 3600);
  assert.deepEqual([broken.broken, broken.poor, broken.flowErrPct, broken.comfortPct], [true, true, 100, 100]);
  assert.equal(m.vavVerdict(broken), "Broken box");
  assert.equal(m.vavHealthStats({ temp: fill(72), lo: 70, hi: 75 }, 3600).broken, null);          // no flow data
});

// ---- rogue VAVs, zone percentile band, AHU on, single vs all devices ----------------------------
const rep = (v, n) => Array.from({ length: n }, () => v);

test("stuck verdict: always open / always closed over >= 90 % of assessed samples, nothing on too few samples", () => {
  const m = load().get("rcxPresetMath");
  const plain = (x) => JSON.parse(JSON.stringify(x));
  assert.deepEqual(plain(m.stuckVerdict(rep(100, 20))), { state: "open", share: 1, n: 20 });
  assert.equal(m.stuckVerdict(rep(0, 20)).state, "closed");
  assert.equal(m.stuckVerdict(rep(1, 20)).state, "open", "0-1 fractions work like percent (1 = 100 %)");
  assert.equal(m.stuckVerdict(rep(96, 18).concat(rep(40, 2))).state, "open", "18 of 20 = 90 % is enough");
  assert.equal(m.stuckVerdict(rep(96, 17).concat(rep(40, 3))), null, "17 of 20 = 85 % is not");
  assert.equal(m.stuckVerdict(rep(94, 20)), null, "94 % open is below the 95 % open threshold");
  assert.equal(m.stuckVerdict(rep(5, 20)).state, "closed", "5 % or less counts as closed");
  assert.equal(m.stuckVerdict(rep(100, 11)), null, "fewer than 12 assessed samples: no verdict");
  assert.equal(m.stuckVerdict([...rep(100, 12), ...rep(null, 50)]).state, "open", "missing samples are not assessed samples");
  const rows = m.rogueVavRows([
    { id: "a", label: "VAV-A", damper: rep(100, 20), reheat: rep(50, 20) },
    { id: "b", label: "VAV-B", damper: rep(50, 20), reheat: rep(0, 20) },
    { id: "c", label: "VAV-C", damper: rep(100, 19).concat([50]), reheat: null },
    { id: "d", label: "VAV-D", damper: rep(50, 20) },
  ]);
  assert.deepEqual(Array.from(rows, (r) => `${r.label}|${r.part}|${r.state}`), ["VAV-A|Damper|open", "VAV-B|Reheat valve|closed", "VAV-C|Damper|open"], "ranked by share, worst first; healthy VAVs absent");
  assert.equal(m.vavVerdictLabel(rows, "b"), "Reheat valve always closed");
  assert.equal(m.vavVerdictLabel(rows, "d"), "Healthy");
});

test("zone band + rogue selection: p10/p90 across zones, worst above p90 and below p10, one list each", () => {
  const m = load().get("rcxPresetMath");
  const N = 40, zones = Array.from({ length: 10 }, (_, z) => ({ id: `z${z}`, label: `Zone ${z}`,
    v: Array.from({ length: N }, (_, i) => 70 + (z % 3) * 0.4 + Math.sin(i / 5 + z) * 0.5) }));
  zones[3].v = zones[3].v.map((x) => x + 8);            // always much warmer than everybody
  zones[7].v = zones[7].v.map((x) => x - 8);           // always much colder
  const band = m.zoneBand(zones.map((z) => z.v));
  assert.equal(band.lo.length, N);
  assert.ok(band.lo.every((x, i) => x < band.hi[i]));
  const rogue = m.pickRogueZones(zones, band);
  assert.deepEqual(Array.from(rogue.above, (r) => r.id), ["z3"]);
  assert.deepEqual(Array.from(rogue.below, (r) => r.id), ["z7"]);
  assert.ok(rogue.above[0].share >= 0.9 && rogue.below[0].share >= 0.9);
  // fewer than 5 zones: no band at all, nothing highlighted
  const few = m.zoneBand(zones.slice(0, 4).map((z) => z.v));
  assert.ok(few.lo.every((x) => x === null) && few.hi.every((x) => x === null));
  assert.deepEqual(Array.from(m.pickRogueZones(zones.slice(0, 4), few).above), []);
  // a normal fleet has no rogue zone
  const calm = Array.from({ length: 10 }, (_, z) => ({ id: `c${z}`, label: `C${z}`, v: Array.from({ length: N }, (_, i) => 70 + Math.sin(i / 3) * 0.2 + z * 0.01) }));
  const calmRogue = m.pickRogueZones(calm, m.zoneBand(calm.map((z) => z.v)));
  assert.equal(calmRogue.above.length + calmRogue.below.length, 0);
});

const vavSite = (n, { airRef = true, ahus = ["AHU-1"] } = {}) => ({
  sites: [rec("S", "SITE", { id: "s" })],
  equips: [
    ...ahus.map((a) => rec(a, "EQUIPMENT", { id: a, siteRef: "s", markers: "equip,ahu" })),
    ...Array.from({ length: n }, (_, i) => rec(`VAV-${i + 1}`, "EQUIPMENT", { id: `VAV-${i + 1}`, siteRef: "s", markers: "equip,vav", ...(airRef ? { airRef: ahus[i % ahus.length] } : {}) })),
  ],
  devices: [],
  points: [
    ...ahus.map((a) => rec(`${a}-FAN`, "POINT", { siteRef: "s", equipRef: a, markers: "point,sensor,fan,run,his", kind: "Bool" })),
    ...Array.from({ length: n }, (_, i) => [
      rec(`V${i + 1}-ZT`, "POINT", { siteRef: "s", equipRef: `VAV-${i + 1}`, markers: "point,sensor,zone,air,temp,his", kind: "Number", unit: "°F" }),
      rec(`V${i + 1}-DM`, "POINT", { siteRef: "s", equipRef: `VAV-${i + 1}`, markers: "point,sensor,damper,his", kind: "Number", unit: "%" }),
      rec(`V${i + 1}-RH`, "POINT", { siteRef: "s", equipRef: `VAV-${i + 1}`, class: "reheat-cmd", markers: "point,cmd,reheat,his", kind: "Number", unit: "%" }),
      rec(`V${i + 1}-DT`, "POINT", { siteRef: "s", equipRef: `VAV-${i + 1}`, markers: "point,sensor,discharge,air,temp,his", class: "discharge-air-temp-sensor", kind: "Number", unit: "°F" }),
    ]).flat(),
  ],
});
const vavFrame = () => { const kids = []; return { kids, el: { ownerDocument: { createElement: () => ({ style: {} }) }, appendChild: (c) => kids.push(c), style: {}, clientHeight: 300 } }; };
async function renderVav(id, model, data, extra = {}, hours = 48) {
  const ctx = load(data);
  const m = { ...model, points: model.points.map(ctx.toPoint) };
  const view = Array.from(ctx.get("RCX_VIEWS")).find((v) => v.id === id);
  const equips = ctx.rcxBind(view, model.equips.filter((e) => /VAV/.test(e.name)), m, catalog);
  const kpis = [], { kids, el } = vavFrame();
  const note = await view.render(el, ctx.rcxContext(view, equips, hours, m, catalog, null, "UTC", { kpis, ...extra }));
  return { ctx, note, kpis, kids, el, rendered: ctx.rendered };
}
const hourly = (vals, t0 = T0) => vals.map((v, i) => [t0 + i * 3600e3, v]);

test("vav_health: rogue VAVs ranked, two frames that hold their charts (no cut-off), KPI published", async () => {
  const model = vavSite(3);
  const data = new Map();
  data.set("u-V1-DM", hourly(rep(100, 48))); data.set("u-V1-RH", hourly(rep(0, 48)));          // damper always open, reheat always closed
  data.set("u-V2-DM", hourly(Array.from({ length: 48 }, (_, i) => 20 + (i % 5) * 15))); data.set("u-V2-RH", hourly(rep(100, 48)));   // reheat always open
  data.set("u-V3-DM", hourly(Array.from({ length: 48 }, (_, i) => 20 + (i % 5) * 15))); data.set("u-V3-RH", hourly(Array.from({ length: 48 }, (_, i) => (i % 2) * 60)));
  const r = await renderVav("vav_health", model, data);
  assert.equal(r.kids.length, 2);
  assert.deepEqual(Array.from(r.rendered, (x) => x.name), ["rcx_vav_rogue", "rcx_vav_health_donut"]);
  const bars = r.rendered[0].option;
  assert.deepEqual(Array.from(bars.yAxis.data), ["VAV-1 · Damper always open", "VAV-1 · Reheat valve always closed", "VAV-2 · Reheat valve always open"]);
  assert.equal(bars.series[0].data[0].value, 100);
  const donut = r.rendered[1].option.series[0].data;
  assert.equal(donut.find((d) => d.name === "Healthy").value, 1);
  assert.equal(donut.find((d) => d.name === "Reheat valve always open").value, 1);
  assert.ok(parseInt(r.el.style.height, 10) >= 260 + 320, "the parent grows to hold both frames");
  assert.equal(r.kpis[0].id, "rogue-vavs");
  assert.equal(r.kpis[0].value, "2 of 3");
  assert.doesNotMatch(r.note, /comfort/i, "comfort lives under Zones only");
});

test("vav_health with no rogue VAV draws the healthy donut alone and says none found", async () => {
  const data = new Map([["u-V1-DM", hourly(Array.from({ length: 48 }, (_, i) => 20 + (i % 5) * 15))]]);
  const r = await renderVav("vav_health", vavSite(1), data);
  assert.equal(r.kids.length, 1);
  assert.match(r.note, /none found/);
});

test("AHU on filter: a damper that is closed whenever the AHU is off is rogue only when judged over all samples", async () => {
  const model = vavSite(1, { airRef: true });
  const fan = hourly(Array.from({ length: 48 }, (_, i) => (i < 24 ? 1 : 0)));                 // AHU on first 24 h
  const damper = hourly(Array.from({ length: 48 }, (_, i) => (i < 24 ? 100 : 0)));             // open while on, closed while off
  const data = new Map([["u-AHU-1-FAN", fan], ["u-V1-DM", damper]]);
  const all = await renderVav("vav_health", model, data, { ahuOn: false });
  assert.equal(all.kpis[0].value, "0 of 1", "50 % open / 50 % closed over every sample: not stuck");
  const on = await renderVav("vav_health", model, data, { ahuOn: true });
  assert.equal(on.kpis[0].value, "1 of 1", "only while the AHU runs the damper never leaves 100 %");
  assert.match(on.note, /AHU on only: 1 of 1 filtered/);
  assert.doesNotMatch(on.note, /assumed/, "linked by airRef, not assumed");
});

test("AHU on filter without airRef: the site's only AHU is assumed and the note says so; several AHUs and no airRef = unfiltered", async () => {
  const fan = hourly(Array.from({ length: 48 }, (_, i) => (i < 24 ? 1 : 0))), damper = hourly(Array.from({ length: 48 }, (_, i) => (i < 24 ? 100 : 0)));
  const one = await renderVav("vav_health", vavSite(1, { airRef: false }), new Map([["u-AHU-1-FAN", fan], ["u-V1-DM", damper]]), { ahuOn: true });
  assert.equal(one.kpis[0].value, "1 of 1");
  assert.match(one.note, /AHU assumed for 1 \(the site has one AHU and no airRef\)/);
  const two = await renderVav("vav_health", vavSite(1, { airRef: false, ahus: ["AHU-1", "AHU-2"] }), new Map([["u-AHU-1-FAN", fan], ["u-V1-DM", damper]]), { ahuOn: true });
  assert.equal(two.kpis[0].value, "0 of 1", "no airRef and two AHUs: the feed is unknown, so nothing is filtered");
  assert.match(two.note, /1 without a known AHU fan signal left unfiltered/);
});

test("feed map: airRef (with or without @) wins; a dangling airRef is not guessed around", () => {
  const ctx = load();
  const kinds = (e) => ((e.attrs || {}).markers || "").split(",").includes("ahu") ? ["ahu"] : ["vav"];
  const eq = (name, attrs) => rec(name, "EQUIPMENT", { id: name, siteRef: "s", ...attrs });
  const m = ctx.rcxAirFeedMap([eq("A1", { markers: "equip,ahu" }), eq("A2", { markers: "equip,ahu" }),
    eq("V1", { airRef: "@A2" }), eq("V2", { airRef: "A1" }), eq("V3", {}), eq("V4", { airRef: "nowhere" })], kinds);
  assert.equal(m.get("V1").ahu.id, "A2"); assert.equal(m.get("V1").assumed, false);
  assert.equal(m.get("V2").ahu.id, "A1");
  assert.equal(m.has("V3"), false, "two AHUs and no airRef: unknown");
  assert.equal(m.has("V4"), false, "an airRef that points nowhere is not guessed");
  const single = ctx.rcxAirFeedMap([eq("A1", { markers: "equip,ahu" }), eq("V3", {}), eq("V4", { airRef: "nowhere" })], kinds);
  assert.deepEqual([single.get("V3").ahu.id, single.get("V3").assumed], ["A1", true]);
  assert.equal(single.has("V4"), false);
});

test("zone_temps draws the percentile band with rogue zones coloured and the rest muted; one zone = plain line", async () => {
  const model = vavSite(10);
  const data = new Map();
  for (let z = 0; z < 10; z++) data.set(`u-V${z + 1}-ZT`, hourly(Array.from({ length: 48 }, (_, i) => 70 + (z % 3) * 0.3 + Math.sin(i / 4 + z) * 0.4 + (z === 3 ? 7 : 0) - (z === 6 ? 7 : 0))));
  const r = await renderVav("zone_temps", model, data);
  const o = r.rendered[0].option;
  assert.equal(r.rendered[0].name, "rcx_zone_temps_band");
  const names = Array.from(o.series, (s) => s.name);
  assert.ok(names.includes("10th-90th percentile of all zones"));
  const hot = o.series.find((s) => /^VAV-4 \(above p90/.test(s.name)), cold = o.series.find((s) => /^VAV-7 \(below p10/.test(s.name));
  assert.ok(hot && cold, "rogue zones are named with their side");
  assert.notEqual(hot.lineStyle.color, cold.lineStyle.color, "above and below get distinct colours");
  const muted = o.series.find((s) => s.name === "VAV-1");
  assert.ok(muted.lineStyle.opacity < 1 && muted.lineStyle.width <= 1, "the others are muted");
  assert.equal(o.legend.data.length, 3, "the legend lists the band and the two rogue zones only");
  assert.equal(r.kpis.find((k) => k.id === "rogue-zones").value, "2");
  const one = await renderVav("zone_temps", vavSite(1), new Map([["u-V1-ZT", hourly(rep(70, 10))]]));
  assert.equal(one.rendered[0].name, "rcx_zone_temps");
  assert.match(one.note, /needs at least 5 zones/);
});

test("single device vs all devices: fleet analytics only in the all-devices plan", () => {
  const ctx = load();
  const model = vavSite(6);
  const m = { ...model, points: model.points.map(ctx.toPoint) };
  const ids = (plan) => Array.from(plan.ready, (r) => r.view.id);
  const all = ctx.rcxPlan(model.equips, m, catalog, { tab: "rcx" });
  const single = ctx.rcxPlan(model.equips.filter((e) => e.name === "VAV-2"), m, catalog, { tab: "rcx", single: true });
  for (const id of ["zone_comfort_rank", "vav_health"]) {
    assert.ok(ids(all).includes(id), `${id} in the all-devices view`);
    assert.ok(!ids(single).includes(id), `${id} not on a single device`);
  }
  for (const id of ["zone_temps", "vav_positions", "vav_reheat_dats"]) assert.ok(ids(single).includes(id), `${id} is the device's own chart`);
  assert.ok(!ids(all).includes("vav_flows") && !ids(single).includes("vav_flows"), "zone airflow timeseries is gone");
  const fleet = Array.from(ctx.get("RCX_VIEWS")).filter((v) => v.fleet).map((v) => v.id).sort();
  assert.deepEqual(fleet, ["vav_health", "zone_comfort_rank"]);
});

test("reheat discharge temps only for VAVs that have a reheat valve; positions view carries damper and reheat", async () => {
  const model = vavSite(2);
  model.points = model.points.filter((p) => p.name !== "V2-RH");                    // VAV-2 has no reheat valve
  const data = new Map([["u-V1-DT", hourly(rep(90, 10))], ["u-V2-DT", hourly(rep(60, 10))], ["u-V1-DM", hourly(rep(40, 10))], ["u-V1-RH", hourly(rep(30, 10))]]);
  const r = await renderVav("vav_reheat_dats", model, data);
  assert.deepEqual(Array.from(r.rendered[0].option.series, (s) => s.name), ["VAV-1"], "VAV-2 has no reheat: not drawn");
  const p = await renderVav("vav_positions", model, data);
  assert.deepEqual(Array.from(p.rendered[0].option.series, (s) => s.name).sort(), ["VAV-1 · damper", "VAV-1 · reheat valve"]);
});

test("scatter plots: a hot-water / chilled-water scatter binds only where its role exists", () => {
  const ctx = load();
  const site = (extra) => ({ sites: [rec("S", "SITE", { id: "s" })], devices: [], equips: [rec("PLANT", "EQUIPMENT", { id: "PLANT", siteRef: "s", markers: "equip" })],
    points: [rec("OAT", "POINT", { siteRef: "s", equipRef: "PLANT", markers: "point,sensor,outside,air,temp,his", class: "outside-air-temp-sensor", kind: "Number", unit: "°F" }), ...extra] });
  const hw = rec("HWS", "POINT", { siteRef: "s", equipRef: "PLANT", markers: "point,sensor,hot,water,leaving,temp,his", kind: "Number", unit: "°F" });
  const chw = rec("CHWS", "POINT", { siteRef: "s", equipRef: "PLANT", markers: "point,sensor,chilled,water,leaving,temp,his", kind: "Number", unit: "°F" });
  const ready = (model) => { const m = { ...model, points: model.points.map(ctx.toPoint) }; return Array.from(ctx.rcxPlan(model.equips, m, catalog, { tab: "rcx" }).ready, (r) => r.view.id); };
  const none = ready(site([])), onlyHw = ready(site([hw])), both = ready(site([hw, chw]));
  assert.ok(!none.includes("hw_reset_scatter") && !none.includes("chw_reset_scatter"));
  assert.ok(onlyHw.includes("hw_reset_scatter") && !onlyHw.includes("chw_reset_scatter"), "no chilled-water system, no CHW scatter");
  assert.ok(both.includes("hw_reset_scatter") && both.includes("chw_reset_scatter"));
  const v = Array.from(ctx.get("RCX_VIEWS"));
  for (const id of ["hw_reset_scatter", "chw_reset_scatter"]) assert.equal(v.find((x) => x.id === id).group, "Scatter plots");
});

// ---- same physical data from a degF point and a degC point: same SI decisions ------------------
const T0 = Date.parse("2026-07-01T00:00:00Z");
const fixture = (extra, unit) => ({
  sites: [rec("S", "SITE", { id: "s" })],
  equips: extra.equips,
  devices: [],
  points: extra.points(unit),
});
async function renderPreset(id, model, data, units = "imperial") {
  const ctx = load(data);
  ctx.units = units;
  const m = { ...model, points: model.points.map(ctx.toPoint) };
  const view = Array.from(ctx.get("RCX_VIEWS")).find((v) => v.id === id);
  const equips = ctx.rcxBind(view, model.equips, m, catalog);
  assert.ok(equips.length, `${id} binds`);
  const el = { ownerDocument: { createElement: () => ({ style: {} }) }, appendChild() {}, style: {}, clientHeight: 300 };
  const note = await view.render(el, ctx.rcxContext(view, equips, 24, m, catalog));
  return { ctx, note, rendered: ctx.rendered };
}

const zoneModel = (unit, withSp) => fixture({
  equips: [rec("V-1", "EQUIPMENT", { id: "V-1", siteRef: "s", markers: "equip,vav" })],
  points: (u) => [
    rec("ZT", "POINT", { siteRef: "s", equipRef: "V-1", markers: "point,sensor,zone,air,temp,his", kind: "Number", unit: u }),
    ...(withSp ? [rec("ZSP", "POINT", { siteRef: "s", equipRef: "V-1", markers: "point,sp,zone,air,temp,his", kind: "Number", unit: u })] : []),
  ],
}, unit);
const hours = (vals, conv) => vals.map((v, i) => [T0 + i * 3600e3, conv(v)]);

test("zone comfort %: a degF zone and a degC zone with the same physical temperatures agree (70-75 F default band)", async () => {
  const temps = [69, 72, 74, 76];                                   // 2 of 4 inside 21.11-23.89 C
  const f = await renderPreset("zone_comfort_rank", zoneModel("°F"), new Map([["u-ZT", hours(temps, (x) => x)]]));
  const c = await renderPreset("zone_comfort_rank", zoneModel("°C"), new Map([["u-ZT", hours(temps, F2C)]]));
  assert.equal(f.rendered[0].option.series[0].data[0], 50);
  assert.equal(c.rendered[0].option.series[0].data[0], 50);
  assert.deepEqual(JSON.parse(JSON.stringify(f.rendered[1].option.series)), JSON.parse(JSON.stringify(c.rendered[1].option.series)));   // donut
  assert.match(f.note, /±2\.5 Δ°F.*else 70–75 °F/);                // thresholds read back in the display system
  const si = await renderPreset("zone_comfort_rank", zoneModel("°F"), new Map([["u-ZT", hours(temps, (x) => x)]]), "si");
  assert.equal(si.rendered[0].option.series[0].data[0], 50);        // same decision in the SI display system
  assert.match(si.note, /±1\.4 Δ°C.*else 21–24 °C/);
});

test("zone comfort with a setpoint: sp +/- 1.3889 delta C (2.5 delta F) in either point unit", async () => {
  const temps = [69, 71, 73, 74.8];                                  // sp 72 F: band 69.5-74.5 F -> one below, two in, one above
  const sp = [72, 72, 72, 72];
  const mk = (conv, unit) => renderPreset("zone_comfort_rank", zoneModel(unit, true),
    new Map([["u-ZT", hours(temps, conv)], ["u-ZSP", hours(sp, conv)]]));
  const f = await mk((x) => x, "°F"), c = await mk(F2C, "°C");
  assert.equal(f.rendered[0].option.series[0].data[0], c.rendered[0].option.series[0].data[0]);
  assert.equal(f.rendered[0].option.series[0].data[0], 50);          // 71 and 73 in
});

const ahuModel = (unit) => fixture({
  equips: [rec("AHU-1", "EQUIPMENT", { id: "AHU-1", siteRef: "s", markers: "equip,ahu" })],
  points: (u) => [
    rec("SAT", "POINT", { siteRef: "s", equipRef: "AHU-1", markers: "point,sensor,discharge,air,temp,his", class: "discharge-air-temp-sensor", kind: "Number", unit: u }),
    rec("OAT", "POINT", { siteRef: "s", equipRef: "AHU-1", markers: "point,sensor,outside,air,temp,his", class: "outside-air-temp-sensor", kind: "Number", unit: u }),
  ],
}, unit);

test("SAT reset scatter: points and fit in the display system; same fit whichever unit the NF point has", async () => {
  const oat = [40, 50, 60], sat = [60, 57, 54];                      // -0.3 F per F
  const run = (conv, unit, sys) => renderPreset("ahu_sat_reset_scatter", ahuModel(unit),
    new Map([["u-OAT", hours(oat, conv)], ["u-SAT", hours(sat, conv)]]), sys);
  const f = await run((x) => x, "°F", "imperial"), c = await run(F2C, "°C", "imperial"), si = await run(F2C, "°C", "si");
  const dataOf = (r) => r.rendered[0].option.series[0].data;
  dataOf(f).forEach(([x, y], i) => { near(x, dataOf(c)[i][0], 1e-9); near(y, dataOf(c)[i][1], 1e-9); });
  near(dataOf(f)[0][0], 40, 1e-9); near(dataOf(f)[0][1], 60, 1e-9);                  // degF shown
  near(dataOf(si)[0][0], F2C(40), 1e-9); near(dataOf(si)[0][1], F2C(60), 1e-9);       // degC shown
  assert.match(f.note, /slope -0\.3 °F \/ °F, R² 1/);
  assert.match(si.note, /slope -0\.3 °C \/ °C, R² 1/);                               // slope is dimensionless here
  assert.equal(f.rendered[0].option.xAxis.name, "OAT (°F)"); assert.equal(si.rendered[0].option.xAxis.name, "OAT (°C)");
});

const meterModel = (unit) => fixture({
  equips: [rec("M-1", "EQUIPMENT", { id: "M-1", siteRef: "s", markers: "equip,elec,meter" })],
  points: (u) => [
    rec("KW", "POINT", { siteRef: "s", equipRef: "M-1", markers: "point,elec,power,sensor,his", kind: "Number", unit: "kW" }),
    rec("OAT", "POINT", { siteRef: "s", equipRef: "M-1", markers: "point,sensor,outside,air,temp,his", class: "outside-air-temp-sensor", kind: "Number", unit: u }),
  ],
}, unit);

test("metering: degree days are C-days (base 18.333 C) inside, F-days (x1.8, base 65) in the imperial display", async () => {
  const day = (i) => T0 + i * 86400e3;
  const oatF = [80, 85, 90];                                         // CDD 15 + 20 + 25 = 60 F-days = 33.33 C-days
  const mk = (conv, unit, sys) => renderPreset("meter_elec_cdd", meterModel(unit), new Map([
    ["u-OAT", oatF.map((v, i) => [day(i), conv(v)])], ["u-KW", oatF.map((v, i) => [day(i), 2])]]), sys);
  const f = await mk((x) => x, "°F", "imperial"), c = await mk(F2C, "°C", "imperial"), si = await mk(F2C, "°C", "si");
  const dd = (r) => r.rendered[0].option.series[1].data[0][0];
  near(dd(f), 60, 1e-9); near(dd(c), 60, 1e-9);                      // same physical data -> same CDD
  near(dd(si), 60 / 1.8, 1e-9);                                      // SI display: C-days
  assert.match(f.rendered[0].option.xAxis[1].name, /CDD \(°F·day, base 65\)/);
  assert.match(si.rendered[0].option.xAxis[1].name, /CDD \(°C·day, base 18\.3\)/);
  assert.equal(f.rendered[0].option.series[1].data[0][1], si.rendered[0].option.series[1].data[0][1]);   // kWh untouched
});
