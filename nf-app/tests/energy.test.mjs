// node --test nf-app/tests/energy.test.mjs — energy views: math, registry, role names.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));

const load = () => {
  const ctx = vm.createContext({
    console, URLSearchParams, TextDecoder, atob, btoa,
    ofddChart: () => ({}), ofddRender: () => {}, fetchSeries: async () => new Map(), pickWindow: () => 3600,
    FAULT_LANE: { lineStyle: {}, areaStyle: {} },
  });
  for (const f of ["nf.js", "model.js", "fdd.js", "rcx.js", "energy.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  ctx.get = (n) => vm.runInContext(n, ctx);
  return ctx;
};
const ctx = load();
const M = ctx.energyMath;
const at = (day, h = 0) => new Date(`${day}T${String(h).padStart(2, "0")}:00:00`).getTime();   // local time
const near = (a, b, e = 1e-6) => assert.ok(Math.abs(a - b) < e, `${a} != ${b}`);

test("kW -> kWh (average kW x window hours) and register deltas, with resets and unit scaling", () => {
  const kw = [[0, 10], [3600e3, 20], [7200e3, null]];
  assert.deepEqual(Array.from(M.intervalKwh(kw, "kw", 3600), (p) => p[1]), [10, 20]);
  assert.deepEqual(Array.from(M.intervalKwh([[0, 10]], "kw", 900), (p) => p[1]), [2.5]);
  const reg = [[0, 100], [1, 110], [2, 125], [3, 5], [4, 12]];   // reset between 2 and 3
  assert.deepEqual(Array.from(M.intervalKwh(reg, "kwh", 3600), (p) => p[1]), [10, 15, 7]);
  assert.deepEqual(Array.from(M.intervalKw(reg, "kwh", 1800), (p) => p[1]), [20, 30, 14]);
  assert.equal(M.energyScale("W", "power"), 0.001);
  assert.equal(M.energyScale("MWh", "energy"), 1000);
  assert.equal(M.energyScale("", "power"), 1);
  near(M.toF(100, "°C"), 212);
  assert.equal(M.toF(70, "°F"), 70);
});

test("degree days use base 65 F", () => {
  assert.deepEqual({ ...M.degreeDays(80) }, { hdd: 0, cdd: 15 });
  assert.deepEqual({ ...M.degreeDays(50) }, { hdd: 15, cdd: 0 });
  assert.deepEqual({ ...M.degreeDays(null) }, { hdd: null, cdd: null });
});

// Hourly synthetic data: day d has mean T = 60 + 4 d, kWh/day = 100 + 5 x CDD (CDD = T - 65 when above).
const days = Array.from({ length: 12 }, (_, i) => `2026-07-${String(i + 1).padStart(2, "0")}`);
const tOf = (i) => 60 + 4 * i;
function synth(shift = 0, partialLast = false) {
  const kwh = [], kw = [], oat = [];
  days.forEach((d, i) => {
    const cdd = Math.max(0, tOf(i) - 65);
    const daily = 100 + 5 * cdd - (i >= 8 ? shift : 0);
    const n = partialLast && i === days.length - 1 ? 6 : 24;
    for (let h = 0; h < n; h++) {
      kwh.push([at(d, h), daily / 24]);
      kw.push([at(d, h), daily / 24 + (h === 15 ? 3 : 0)]);
      oat.push([at(d, h), tOf(i)]);
    }
  });
  return { kwh, kw, oat };
}

test("dailyTable / monthlyTable aggregate, flag partial days and carry degree days", () => {
  const s = synth(0, true);
  const daily = M.dailyTable(s.kwh, s.kw, s.oat, 3600);
  assert.equal(daily.length, 12);
  near(daily[0].kwh, 100); near(daily[0].peakKw, 100 / 24 + 3); near(daily[0].hdd, 5); assert.equal(daily[0].cdd, 0);
  near(daily[11].cdd, tOf(11) - 65);
  assert.equal(daily[0].complete, true);
  assert.equal(daily[11].complete, false);
  const monthly = M.monthlyTable(daily);
  assert.equal(monthly.length, 1);
  assert.equal(monthly[0].month, "2026-07");
  near(monthly[0].kwh, daily.reduce((a, d) => a + d.kwh, 0));
  near(monthly[0].days, 11.25);
  near(monthly[0].peakKw, Math.max(...daily.map((d) => d.peakKw)));
});

test("baselineFit recovers the line, picks CDD over HDD, and falls back flat with no variation", () => {
  const daily = M.dailyTable(synth().kwh, [], synth().oat, 3600);
  const fit = M.baselineFit(daily);
  assert.equal(fit.xKey, "cdd");
  near(fit.slope, 5, 1e-6); near(fit.intercept, 100, 1e-6); near(fit.r2, 1, 1e-9);
  near(M.predict(fit, 10), 150);
  const res = M.residuals(daily, fit);
  assert.ok(res.every((r) => Math.abs(r.residual) < 1e-6));
  const flat = M.baselineFit(daily.slice(0, 2), "cdd");       // cooler days only: CDD all zero
  assert.equal(flat.slope, 0); near(flat.intercept, 100);
  assert.equal(M.baselineFit(daily.slice(0, 1)), null);
});

test("mvSavings: reporting days 20 kWh below the baseline model save 20 kWh/day", () => {
  const s = synth(20);
  const daily = M.dailyTable(s.kwh, s.kw, s.oat, 3600);
  const r = M.mvSavings(daily, { from: days[0], to: days[7] }, { from: days[8], to: days[11] }, "cdd");
  assert.equal(r.baseDays, 8); assert.equal(r.repDays, 4);
  near(r.fit.slope, 5, 1e-6);
  near(r.savings, 80, 1e-6);
  near(r.actual + r.savings, r.predicted);
  near(r.pct, 80 / r.predicted);
  near(r.cvrmse, 0, 1e-9);
  assert.equal(M.mvSavings(daily, { from: days[0], to: days[1] }, { from: days[8], to: days[11] }), null);   // < 3 baseline days
  assert.equal(M.mvSavings(daily, { from: days[0], to: days[7] }, { from: "2030-01-01", to: "2030-01-02" }), null);
});

test("EUI, rolling 12 months, season peaks and the hour x weekday grid", () => {
  near(M.eui(1000, 30, 10000), 1000 * 3.412 / 10000 * 365 / 30);
  assert.equal(M.eui(1000, 30, 0), null);
  assert.equal(M.eui(1000, 30, null), null);
  const monthly = Array.from({ length: 14 }, (_, i) => ({ month: `m${i}`, kwh: 10, days: 30 }));
  const roll = M.rolling12(monthly);
  assert.equal(roll[0].kwh, 10); assert.equal(roll[11].kwh, 120); assert.equal(roll[13].kwh, 120); assert.equal(roll[13].days, 360);
  const daily = M.dailyTable(synth().kwh, synth().kw, synth().oat, 3600);
  const seasons = Array.from(M.seasonPeaks(daily), (s) => ({ ...s }));
  assert.equal(seasons[0].season, "Cooling days"); assert.equal(seasons[0].days, 10);   // T > 65 from day 3 on
  assert.equal(seasons[1].days, 2);
  const grid = M.heatmapGrid([[at("2026-07-06", 14), 10], [at("2026-07-13", 14), 30]]);   // two Mondays at 14:00
  assert.equal(grid.data.length, 1);
  assert.deepEqual(Array.from(grid.data[0]), [14, 1, 20]);
  assert.equal(grid.max, 20);
});

test("siteMetric: EUI only when every site has an area", () => {
  assert.equal(M.siteMetric([{ area: 1000 }, { area: 5 }]).allArea, true);
  const m = M.siteMetric([{ area: 1000 }, { area: null }]);
  assert.equal(m.allArea, false);
  assert.equal(m.value(300, 30, null), 10);
  assert.match(m.label, /kWh\/day/);
});

test("chart options are theme-free and well formed", () => {
  const s = synth(), daily = M.dailyTable(s.kwh, s.kw, s.oat, 3600), monthly = M.monthlyTable(daily);
  const fit = M.baselineFit(daily), res = M.residuals(daily, fit);
  const C = M.charts;
  const all = [
    C.demandHeatmapOption(M.heatmapGrid(s.kw)), C.intervalDemandOption(s.kw), C.monthlyLinesOption(monthly),
    C.weatherOption(daily, fit, res), C.peakDualOption(monthly), C.peakSeasonOption(M.seasonPeaks(daily)),
    C.mvOption(M.mvSavings(daily, { from: days[0], to: days[7] }, { from: days[8], to: days[11] })),
  ];
  const sites = [{ name: "A", area: 100, monthly, rolling: M.rolling12(monthly), kwh: 100, days: 10 }, { name: "B", area: 200, monthly, rolling: M.rolling12(monthly), kwh: 300, days: 10 }];
  const metric = M.siteMetric(sites);
  const rows = sites.map((x) => ({ ...x, value: metric.value(x.kwh, x.days, x.area) }));
  all.push(C.peerBarsOption(rows, metric), C.peerBulletOption(rows[0], rows, metric), C.rankedOption(rows, metric),
    C.rollingOption(sites, metric), C.intensityOption(sites, metric), C.stackedOption(sites));
  for (const o of all) {
    assert.ok(o.series.length && o.xAxis && o.yAxis);
    assert.ok(!/#[0-9a-f]{3,6}\b|rgb/i.test(JSON.stringify(o)), "no theme colors in options");
  }
  assert.equal(C.rankedOption(rows, metric).yAxis.data[0], "B");     // 300 kWh over 200 ft2 beats 100 over 100 per day covered... both 10 d
});

test("views register under Energy with real catalog roles and meter kind", () => {
  const views = Array.from(ctx.get("RCX_VIEWS")).filter((v) => v.group === "Energy");
  assert.ok(views.length >= 20, `got ${views.length}`);
  const ids = views.map((v) => v.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ["energy-demand-heatmap", "energy-interval-demand", "energy-monthly", "energy-weather-scatter", "energy-demand-peak",
    "energy-peak-cooling", "energy-mv", "energy-mv-kwh", "energy-peer-bullet", "energy-peer-bars", "energy-ranked-eui",
    "energy-rolling12", "energy-intensity-heatmap", "energy-stacked-meters"]) assert.ok(ids.includes(id), id);
  for (const v of views) {
    for (const role of [...v.roles.required, ...v.roles.optional]) assert.ok(catalog.roles[role], `${v.id}: role ${role}`);
    assert.deepEqual(Array.from(v.kinds), ["meter"]);
    assert.ok(Object.keys(catalog.equipment_kinds).includes("meter"));
    assert.equal(typeof v.render, "function");
  }
  for (const v of views.filter((x) => x.scope === "site")) assert.equal(v.roles.required.length, 0);
  // fault lanes only for the rules that relate to energy
  for (const r of ["UTIL-INTERVAL", "UTIL-MONTHLY"]) assert.ok(catalog.rules.some((x) => x.id === r), r);
});

test("a meter equip with a kW point binds the kW views; a register-only meter binds the kWh twins", () => {
  const rec = (name, attrs) => ({ uuid: `u-${name}`, name, pointType: "POINT", attrs });
  const eq = (id) => ({ uuid: `e-${id}`, name: id, pointType: "EQUIPMENT", attrs: { id, siteRef: "s", markers: "equip,elec,meter" } });
  const model = {
    sites: [], equips: [eq("M1"), eq("M2")], devices: [],
    points: [
      rec("kw", { siteRef: "s", equipRef: "M1", markers: "point,elec,power,sensor,his", unit: "kW" }),
      rec("kwh", { siteRef: "s", equipRef: "M2", markers: "point,elec,energy,sensor,his", unit: "kWh" }),
    ].map(ctx.toPoint),
  };
  const plan = ctx.rcxPlan(model.equips, model, catalog);
  const ready = (id) => Array.from(plan.ready.find((r) => r.view.id === id)?.equips || [], (e) => e.name);
  assert.deepEqual(ready("energy-monthly"), ["M1"]);
  assert.deepEqual(ready("energy-monthly-kwh"), ["M2"]);
});
