// node --test nf-app/tests/rcx-presets.test.mjs — RCx presets: math, registration, roles, fault lane.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));

function load(fetchData = new Map()) {
  const rendered = [];
  const ctx = vm.createContext({
    console, URLSearchParams, TextDecoder, atob, btoa,
    echarts: { registerTheme() {} },
    FAULT_LANE: { lineStyle: { color: "red" }, areaStyle: { color: "red" } },
    pickWindow: () => 3600,
    fetchSeries: async (list) => new Map(list.map((p) => [p.uuid, fetchData.get(p.uuid) || []])),
    ofddChart: (el) => ({ el }),
    ofddRender: (chart, option, name) => rendered.push({ chart, option, name }),
  });
  for (const f of ["nf.js", "model.js", "fdd.js", "rcx.js", "rcx-presets.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  ctx.get = (name) => vm.runInContext(name, ctx);
  ctx.rendered = rendered;
  return ctx;
}

const IDS = ["zone_comfort_rank", "zone_temps", "ahu_dats", "ahu_mats", "ahu_rats", "ahu_dampers", "duct_static_box",
  "duct_static_ts", "ahu_sat_reset_scatter", "hw_reset_scatter", "chw_reset_scatter", "cw_reset_scatter",
  "vav_flows", "vav_health", "fan_speeds", "meter_elec_cdd", "meter_gas_hdd", "chw_temps_ts", "cw_temps_ts"];

test("all 18 preset ids are registered once, in a known group, with real catalog roles", () => {
  const ctx = load();
  const views = Array.from(ctx.get("RCX_VIEWS"));
  for (const id of IDS) assert.equal(views.filter((v) => v.id === id).length, 1, id);
  assert.equal(views.length, IDS.length);
  const groups = new Set(["Zones", "Air handlers", "Plant", "VAV", "Metering"]);
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
  const [lo, hi] = m.defaultBand("°C");
  assert.ok(Math.abs(lo - 21.111) < 1e-3 && Math.abs(hi - 23.889) < 1e-3);
  assert.deepEqual(Array.from(m.defaultBand("°F")), [70, 75]);
  const ranked = m.rankComfort([{ label: "b", value: 90 }, { label: "a", value: 40 }, { label: "c", value: null }]);
  assert.deepEqual(Array.from(ranked, (r) => r.label), ["a", "b"]);
  assert.equal(m.toF(0, "°C"), 32);
  assert.equal(m.toF(50, "°F"), 50);
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

test("degree days (base 65 F), daily energy and monthly join", () => {
  const m = load().get("rcxPresetMath");
  assert.equal(m.degreeDay(75, "cdd"), 10);
  assert.equal(m.degreeDay(75, "hdd"), 0);
  assert.equal(m.degreeDay(40, "hdd"), 25);
  const d = (day, h = 0) => Date.UTC(2026, 6, day, h);
  const oat = [[d(1), 75], [d(2), 65], [d(3), 85]];
  const dd = m.monthlyDegreeDays(m.dailyMeans(oat, "°F"), "cdd");
  assert.deepEqual([dd.get("2026-07").dd, dd.get("2026-07").days], [30, 3]);
  assert.equal(m.monthlyDegreeDays(m.dailyMeans([[d(1), 0]], "°C"), "hdd").get("2026-07").dd, 33);   // 0 C = 32 F
  // kW -> kWh (x24), interval kWh, cumulative register (differences)
  assert.equal(m.dailyEnergy([[d(1), 2]], "rate").get("2026-07-01"), 48);
  assert.equal(m.dailyEnergy([[d(1), 5], [d(1, 1), 7]], "interval").get("2026-07-01"), 12);
  const reg = [[d(1), 100], [d(2), 130], [d(3), 150], [d(5), 400]];                  // 2-day gap skipped
  assert.ok(m.isCumulative(reg));
  assert.ok(!m.isCumulative([[1, 5], [2, 1], [3, 7], [4, 2]]));
  const e = m.dailyEnergy(reg, "cumulative");
  assert.deepEqual([e.get("2026-07-02"), e.get("2026-07-03"), e.has("2026-07-05")], [30, 20, false]);
  const rows = m.meterRows(m.monthlySum(e), dd);
  assert.deepEqual(Array.from(rows, (r) => [r.month, r.energy, r.dd]), [["2026-07", 50, 30]]);
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

test("vav_health renders bars + donut into two frames", async () => {
  const MODEL2 = {
    sites: [rec("S", "SITE", { id: "s" })],
    equips: [rec("V-1", "EQUIPMENT", { id: "V-1", siteRef: "s", markers: "equip,vav" })],
    devices: [],
    points: [
      rec("ZT", "POINT", { siteRef: "s", equipRef: "V-1", markers: "point,sensor,zone,air,temp,his", kind: "Number", unit: "°F" }),
      rec("DM", "POINT", { siteRef: "s", equipRef: "V-1", markers: "point,sensor,damper,his", kind: "Number", unit: "%" }),
    ],
  };
  const t = Date.parse("2026-07-01T00:00:00Z");
  const data = new Map([["u-ZT", [[t, 80], [t + 3600e3, 81]]], ["u-DM", [[t, 50], [t + 3600e3, 50]]]]);
  const ctx = load(data);
  const model = { ...MODEL2, points: MODEL2.points.map(ctx.toPoint) };
  const view = Array.from(ctx.get("RCX_VIEWS")).find((v) => v.id === "vav_health");
  assert.equal(view.group, "VAV");
  const equips = ctx.rcxBind(view, MODEL2.equips, model, catalog);
  assert.equal(equips.length, 1);
  const kids = [];
  const el = { ownerDocument: { createElement: () => ({ style: {} }) }, appendChild: (c) => kids.push(c), style: {}, clientHeight: 300 };
  await view.render(el, ctx.rcxContext(view, equips, 24, model, catalog));
  assert.equal(kids.length, 2);
  assert.deepEqual(Array.from(ctx.rendered, (r) => r.name), ["rcx_vav_health_worst", "rcx_vav_health_donut"]);
  assert.equal(ctx.rendered[0].option.series[0].data[0], 100);
  assert.equal(ctx.rendered[1].option.series[0].data.find((d) => d.name === "Poor comfort").value, 1);
});
