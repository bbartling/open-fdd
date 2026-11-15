// node --test nf-app/tests/overview-dashboard.test.mjs - the Overview RCx dashboard (5.0.20): no device picker, every
// modeled device at once, and a panel only when the model has that equipment (hidden otherwise). Synthetic model:
// tests/fixtures/dashboard_model.mjs. Also the FDD plot shading helpers (fault spans red, equipment-off spans grey).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dashboardModel } from "./fixtures/dashboard_model.mjs";

const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
function load() {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa, localStorage: { getItem: () => "si" } });
  ctx.FAULT_LANE = { lineStyle: { color: "red" }, areaStyle: { color: "red" } };
  ctx.pickWindow = () => 3600; ctx.ofddChart = () => ({}); ctx.ofddRender = () => {};
  for (const f of ["units.js", "paging.js", "nf.js", "model.js", "fdd.js", "schedule.js", "charts.js", "rcx.js", "plot-spec-data.js", "fdd-plots.js", "rcx-overview.js", "rcx-presets.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  ctx.get = (n) => vm.runInContext(n, ctx);
  return ctx;
}
/** The dashboard's panels (view ids) for a model, the way renderViewTab("rcx") plans them: every device, fleet views on. */
function panels(plant) {
  const ctx = load(), { records, points } = dashboardModel({ plant });
  const model = { sites: records.filter((r) => r.pointType === "SITE"), equips: records.filter((r) => r.pointType === "EQUIPMENT"), devices: [], points: points.map(ctx.toPoint) };
  const { ready } = ctx.rcxPlan(model.equips, model, catalog, { tab: "rcx", single: false });
  return new Map(Array.from(ready, (x) => [x.view.id, Array.from(x.equips, (e) => e.name)]));
}

const PLANT_PANELS = {
  "mech-cooling-hours": "DX / compressor / chiller cooling hours binned by outdoor air (#1598)",
  hw_reset_scatter: "hot-water reset scatter", chw_reset_scatter: "chilled-water reset scatter",
  zone_temps: "zone temperatures", zone_comfort_rank: "zone comfort ranking", "weekly-chiller": "chiller weekly run hours",
};

test("AHU-only model: AHU run hours and air-side panels show; chiller, hot-water, DX cooling and zone panels are hidden", () => {
  const p = panels("ahu");
  for (const id of ["weekly-fan", "ahu_dats", "economizer-delta"]) assert.ok(p.has(id), `${id} shows`);
  for (const [id, what] of Object.entries(PLANT_PANELS)) assert.ok(!p.has(id), `${what} (${id}) is hidden without that equipment`);
});

test("full model: every plant panel shows, each with ALL its devices on one panel (no picker)", () => {
  const p = panels("full");
  for (const [id, what] of Object.entries(PLANT_PANELS)) assert.ok(p.has(id), `${what} (${id}) shows`);
  assert.deepEqual(p.get("weekly-fan").sort(), ["AHU-1", "AHU-2"], "both AHUs' run hours together");
  assert.deepEqual(p.get("mech-cooling-hours").sort(), ["AHU-2", "CH-1"], "DX unit and chiller binned together; AHU-1 has no cooling proof");
  assert.deepEqual(p.get("zone_temps").sort(), ["VAV-1", "VAV-2", "VAV-3"], "all zones together");
  for (const id of p.keys()) {
    const v = load().get("RCX_VIEWS").find((x) => x.id === id);
    assert.equal(v.tab || "rcx", "rcx");
  }
});

test("Overview hides the dashboard until a panel draws, and drops empty cards and groups", () => {
  const app = readFileSync(new URL("app.js", dir), "utf8");
  assert.match(app, /if \(fleet && \$\("overviewRcx"\)\) \$\("overviewRcx"\)\.hidden = !cards\.length/);
  assert.match(app, /an empty group goes too/);
  assert.match(app, /ofddTabs\.overview = async \(\) => \{/);
  assert.match(app, /ofddOccupancyEditor\.render/);
  assert.match(app, /const fleet = tab === "rcx"; +\/\/ the RCx dashboard: every device, never one picked/);
});

test("FDD plot shading: fault spans and equipment-off spans become mark areas on every signal grid", () => {
  const ctx = load();
  const spans = ctx.fddPlotSpans([[0, 0], [1, 1], [2, 1], [3, 0], [4, 1]], (v) => v === 1);
  assert.deepEqual(Array.from(spans, (s) => Array.from(s)), [[1, 3], [4, 5]]);
  const option = { series: [{ type: "line", xAxisIndex: 0 }, { type: "line", xAxisIndex: 0 }, { type: "line", xAxisIndex: 1 }] };
  ctx.fddPlotShade(option, 2, [[1, 3]], [[10, 20]]);
  assert.equal(option.series[0].markArea.data.length, 2, "one off span + one fault span");
  assert.ok(!option.series[1].markArea, "once per grid");
  assert.equal(option.series[2].markArea.data.length, 2);
  const built = ctx.fddPlotRuleOption({ title: "t", groups: [{ family: "temp", unit: "°C", series: [{ name: "sat (°C)", data: [[0, 1]] }] }] });
  assert.equal(built.option.legend.show, false, "no legend");
  assert.equal(built.option.series[0].endLabel.show, true, "lines are labelled directly");
});