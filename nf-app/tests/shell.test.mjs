// node --test nf-app/tests (also imported by lite/tests/shell.test.mjs) — the shared dashboard shell
// (shared/static/app-core.js + charts.js) as each edition ships it: the top bar, the equip pickers, the heat-map sensor
// dropdown, the "All signals" chart and the Weather category. Every check runs against the Full AND the Lite copies.
import { test as baseTest } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

for (const [edition, dirUrl] of [["full", new URL("../static/", import.meta.url)], ["lite", new URL("../../lite/static/", import.meta.url)]]) {
const test = (name, fn) => baseTest(`[${edition}] ${name}`, fn);
const text = (f) => readFileSync(new URL(f, dirUrl), "utf8");
function load() {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa, Intl, Date, Math });
  for (const f of ["paging.js", "nf.js", "model.js", "charts.js", "app-core.js"]) vm.runInContext(text(f), ctx, { filename: f });
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
}

const rec = (name, pointType, attrs, latest) => ({ uuid: `u-${name}`, name, pointType, attrs, latestValue: latest });
const pt = (name, attrs) => rec(name, "POINT", { siteRef: "site-a", kind: "Number", ...attrs });
const equip = (id, dis) => rec(id, "EQUIPMENT", { id, dis, siteRef: "site-a", markers: "equip,vav" });
const FIXTURE = {
  sites: [rec("Site A", "SITE", { id: "site-a" })],
  equips: [equip("VAV-A", "Zone A"), equip("VAV-B", "Zone B")],
  devices: [],
  points: [
    pt("ZN-T", { equipRef: "VAV-A", dis: "Zone temp", unit: "°F", markers: "point,sensor,zone,air,temp,his,cur" }),
    pt("SAT", { equipRef: "VAV-A", dis: "Discharge temp", unit: "°F", markers: "point,sensor,discharge,air,temp,his,cur" }),
    pt("DMPR", { equipRef: "VAV-A", dis: "Damper position", unit: "%", markers: "point,cmd,damper,his,cur" }),
    pt("FLOW", { equipRef: "VAV-A", dis: "Airflow", unit: "cfm", markers: "point,sensor,air,flow,his,cur" }),
    pt("FAN", { equipRef: "VAV-A", dis: "Fan status", kind: "Bool", markers: "point,sensor,fan,run,his,cur" }),
    pt("ZN-T2", { equipRef: "VAV-B", dis: "Zone temp", unit: "°F", markers: "point,sensor,zone,air,temp,his,cur" }),
    pt("FDD-F1", { equipRef: "VAV-A", dis: "SV-RANGE fault", unit: "h", markers: "point,fdd,fault,his,cur", ruleRef: "SV-RANGE" }),
    pt("FDD-F2", { equipRef: "VAV-A", dis: "SV-STALE fault", unit: "h", markers: "point,fdd,fault,his,cur", ruleRef: "SV-STALE" }),
    pt("FDD-B", { equipRef: "VAV-A", dis: "fault flag", kind: "Bool", markers: "point,fdd,fault,his,cur", ruleRef: "SV-RATE" }),
    pt("WX-T", { weatherStationRef: "wx-1", dis: "Web outside air temp", unit: "°F", markers: "point,sensor,weather,outside,air,temp,his" }),
    pt("WX-H", { weatherStationRef: "wx-1", dis: "Web outside air humidity", unit: "%RH", markers: "point,sensor,weather,outside,air,humidity,his" }),
  ],
};
const modelFor = (ctx) => ({ sites: FIXTURE.sites, equips: FIXTURE.equips, devices: FIXTURE.devices, points: FIXTURE.points.map(ctx.toPoint) });

test("top bar: only the site (picker), the live pill, clock, units and theme; no equip picker or chips", () => {
  const html = text("index.html");
  const header = html.slice(html.indexOf("<header>"), html.indexOf("</header>"));
  assert.match(header, /id="sitePick"/);
  assert.match(header, /id="themeToggle"/);
  assert.ok(!/equipPick|equip-pick|class="chip|data-equip/.test(header), "no per-equip controls in the top bar");
  assert.equal((header.match(/<select/g) || []).length, 1, "the site picker is the only select");
  assert.ok(!/equipPick/.test(text("app-core.js")), "no code still looks for the old top-bar equip picker");
});

test("each tab that needs an equip gets its own equip picker (the shell adds it), Full adds FDD / RCx / Export", () => {
  const core = text("app-core.js"), app = text("app.js");
  assert.match(core, /ofddEquipScoped = new Set\(\["overview", "charts", "points"\]\)/);
  assert.match(core, /className = "equip-pick"/);
  if (edition === "full") assert.match(app, /for \(const tab of \["fdd", "rcx", "export"\]\) ofddEquipScoped\.add\(tab\)/);
  else assert.ok(!/renderFdd|renderRcx|ofddTabs|ofddExport/.test(app), "Lite carries no FDD / RCx / export code");
});

test("equip choices come from the model and list Weather as its own entry", () => {
  const ctx = load(), m = modelFor(ctx);
  const choices = Array.from(ctx.get("equipChoices")(m, "site-a"), (c) => [c.value, c.label]);
  assert.deepEqual(choices, [["", "all equips (2)"], ["VAV-A", "Zone A"], ["VAV-B", "Zone B"], ["__weather__", "Weather"]]);
  const noWx = { ...m, points: m.points.filter((p) => !p.weatherStationRef) };
  assert.ok(!ctx.get("equipChoices")(noWx, "site-a").some((c) => c.label === "Weather"), "no Weather entry without weather points");
});

test("weather points are their own category: never an equip's sensors, selectable as Weather", () => {
  const ctx = load(), m = modelFor(ctx);
  const names = (set) => Array.from(set, (p) => p.dis);
  const all = ctx.pointSets(m, "site-a", "");
  assert.ok(!names(all.cards).some((n) => /Web outside/.test(n)), "not in the all-equips cards");
  assert.deepEqual(names(all.weather), ["Web outside air humidity", "Web outside air temp"]);
  const a = ctx.pointSets(m, "site-a", "VAV-A");
  assert.ok(!names(a.numeric).some((n) => /Web outside/.test(n)));
  const wx = ctx.pointSets(m, "site-a", ctx.get("WEATHER_SCOPE"));
  assert.deepEqual(names(wx.cards).sort(), ["Web outside air humidity", "Web outside air temp"]);
  assert.equal(wx.status.length, 0);
  // labels: the owner of a weather point is "Weather", of an equip point its equip name
  assert.equal(ctx.pointOwner(all.weather[0], all), "Weather");
  assert.equal(ctx.pointOwner(m.points.find((p) => p.uuid === "u-ZN-T"), all), "Zone A");
  // the Points tab: Weather scope shows only weather points; an equip scope never shows them
  assert.match(text("app-core.js"), /scope\.equip === WEATHER_SCOPE \? isWeatherPoint\(p\)/);
});

test("heat-map sensor dropdown: options come from the model, label = dis + unit, default unchanged", () => {
  const ctx = load(), m = modelFor(ctx);
  const heat = ctx.get("chartDef")("heatmap");
  const a = ctx.pointSets(m, "site-a", "VAV-A");
  const opts = ctx.pickOptions(heat, a);
  assert.deepEqual(Array.from(opts, (o) => o.label), ["Discharge temp (°F)", "Zone temp (°F)", "Airflow (cfm)"]);
  assert.deepEqual(Array.from(opts, (o) => o.value), ["u-SAT", "u-ZN-T", "u-FLOW"]);
  assert.equal(heat.defaultPick(a), "u-SAT", "default = the discharge air temp, as before");
  // all equips: the equip name disambiguates equal point names
  const labels = Array.from(ctx.pickOptions(heat, ctx.pointSets(m, "site-a", "")), (o) => o.label);
  assert.ok(labels.includes("Zone A · Zone temp (°F)") && labels.includes("Zone B · Zone temp (°F)"), labels.join(" | "));
  assert.ok(labels.every((l) => !/^(sensor|series)\s*\d/i.test(l)));
});

test("Other signals: every numeric signal grouped by unit onto its own y-axis, on/off points in a bottom lane, no placeholder names", () => {
  const ctx = load(), m = modelFor(ctx);
  const other = ctx.get("chartDef")("other");
  const a = ctx.pointSets(m, "site-a", "VAV-A");
  assert.ok(other.applies(a));
  const { lines, lanes } = ctx.signalSets(a);
  assert.deepEqual(Array.from(lines, (p) => p.dis).sort(), ["Airflow", "Damper position", "Discharge temp", "Zone temp"]);
  assert.deepEqual(Array.from(lanes, (p) => p.dis), ["Fan status"]);
  const axes = ctx.signalAxes(lines);
  assert.deepEqual(Array.from(axes, (x) => x.unit).sort(), ["%", "cfm", "°F"]);
  assert.deepEqual(Array.from(axes.find((x) => x.unit === "°F").points, (p) => p.dis).sort(), ["Discharge temp", "Zone temp"]);
  const data = () => [[1000, 1], [2000, 2]];
  const names0 = (o) => Array.from(o.series, (x) => x.name);
  const opt = ctx.signalsOption(axes, lanes, data, (p) => ctx.signalLabel(p, a, [...lines, ...lanes]));
  const valueAxes = opt.yAxis.filter((y) => y.gridIndex === 0);
  assert.equal(valueAxes.length, 3, "one y-axis per unit");
  assert.deepEqual(Array.from(valueAxes, (y) => y.name).sort(), ["%", "cfm", "°F"]);
  assert.equal(opt.grid.length, 2, "a second (bottom) grid holds the on/off lane");
  assert.equal(opt.yAxis.length, 4);
  const lineSeries = opt.series.filter((s) => s.yAxisIndex < 3);
  assert.equal(lineSeries.length, 4);
  for (const s of lineSeries) assert.equal(valueAxes[s.yAxisIndex].name, ctx.get("dispUnit")(lines.find((p) => p.name === s.name)), `${s.name} sits on its unit's axis`);
  const lane = opt.series.find((s) => s.xAxisIndex === 1);
  assert.equal(lane.name, "fan run");
  assert.ok(names0(opt).includes("discharge air temp"), "the same human label the Temperatures chart uses, no equip prefix for one equip");
  assert.equal(lane.step, "end");
  const names = Array.from(opt.series, (s) => s.name);
  assert.ok(names.every((n) => n && !/^(sensor|series|unnamed)\s*\d*$/i.test(n)), names.join(" | "));
  // no equip selected: the chart shows the first equip by name and says so
  const all = ctx.pointSets(m, "site-a", "");
  const both = ctx.signalSets(all);
  assert.equal(both.narrowed, true);
  assert.equal(both.shown, "Zone A");
  assert.ok(Array.from(both.lines, (p) => p.equipRef).every((e) => e === "VAV-A"));
  assert.equal(ctx.signalSets(a).narrowed, false);
  // axis offsets: distinct per side and at least 55 px apart
  const many = ["a", "b", "c", "d", "e"].map((u) => ({ unit: u, points: [lines[0]] }));
  const wide = ctx.signalsOption(many, [], data, (p) => p.name);
  for (const side of ["left", "right"]) {
    const offs = wide.yAxis.filter((y) => y.position === side).map((y) => y.offset).sort((x, y) => x - y);
    assert.equal(new Set(offs).size, offs.length, `${side} offsets distinct`);
    offs.forEach((o, i) => i && assert.ok(o - offs[i - 1] >= 55, `${side} offsets >= 55 apart: ${offs}`));
  }
  assert.ok(wide.grid[0].left >= 50 + 55 * 2 && wide.grid[0].right >= 20 + 55, "grid margins grow to fit the stacked axes");
  // a point with no model label is omitted rather than named
  const bare = ctx.signalSets({ scopeEquip: "VAV-A", numeric: [{ uuid: "x", dis: "", name: "", units: "" }, ...a.numeric], status: [] });
  assert.equal(bare.lines.length, a.numeric.length);
  // no bool points: no second grid
  const noLane = ctx.signalsOption(axes, [], data, (p) => p.dis);
  assert.equal(noLane.grid.length, 1);
});

test("the Weather vs outside air chart is gone from the Charts tab", () => {
  const ctx = load();
  const ids = Array.from(ctx.get("CHARTS"), (c) => c.id);
  assert.ok(!ids.includes("weather"));
  assert.deepEqual(ids, ["temps", "heatmap", "daily", "runtime", "psy", "other"]);
  assert.ok(!/Weather vs outside air/.test(text("charts.js")));
});

test("Model tab: the weather stations hang under a Weather category", () => {
  const core = text("app-core.js");
  assert.match(core, /name: WEATHER_LABEL, kind: "weather"/);
  assert.ok(!/name: "weather stations"/.test(core), "the old group label is gone");
});

test("weather mirror: this edition's copy of the hook mirrors to the BACnet server by default", async () => {
  const { createRequire } = await import("node:module");
  const hook = createRequire(import.meta.url)(edition === "full" ? "../hooks/weather.js" : "../../lite/hooks/open_meteo_weather.js");
  assert.equal(hook.OFDD_EDITION, edition);
  const src = readFileSync(new URL(edition === "full" ? "../hooks/weather.js" : "../../lite/hooks/open_meteo_weather.js", import.meta.url), "utf8");
  assert.match(src, /listed === undefined \? \[\{ id: 'bacnet-av', explicit: false \}\]/, "bacnet-av is the default exporter (when NF's BACnet server is present)");
});

test("FDD hook result points are outputs: never in All signals, the heat-map dropdown, cards or lanes; no two series share a name", () => {
  const ctx = load(), m = modelFor(ctx);
  assert.equal(m.points.filter((p) => p.tags.includes("fault")).length, 3, "the fixture has fault result points");
  const a = ctx.pointSets(m, "site-a", "VAV-A");
  const all = [...a.cards, ...a.numeric, ...a.status, ...ctx.pointSets(m, "site-a", "").numeric];
  assert.ok(all.every((p) => !p.tags.includes("fault") && !p.tags.includes("fdd")));
  assert.ok(Array.from(ctx.pickOptions(ctx.get("chartDef")("heatmap"), a), (o) => o.label).every((l) => !/fault/.test(l)));
  const { lines, lanes } = ctx.signalSets(a);
  const opt = ctx.signalsOption(ctx.signalAxes(lines), lanes, () => [[1, 1]], (p) => ctx.signalLabel(p, a, [...lines, ...lanes]));
  const names = Array.from(opt.series, (x) => x.name);
  assert.equal(new Set(names).size, names.length, names.join(" | "));
  assert.ok(names.every((n) => !/fault/i.test(n)));
});
}
