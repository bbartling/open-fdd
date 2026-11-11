// node --test nf-app/tests — logic tests for the Open-FDD NF app (no NF, no browser).
// The page scripts are classic browser scripts, so they run in a vm context like the page does.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import { multiSensorEquip } from "./fixtures/multi_sensor_equip.mjs";

const dir = new URL("../static/", import.meta.url);
const load = (...files) => {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of files) vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  // Top-level const/let live in the script scope, not on the global object: read them by name.
  ctx.get = (name) => vm.runInContext(name, ctx);
  return ctx;
};

// A small Haystack model in NF's point/query shape: one site, one equip, one device, points.
const rec = (name, pointType, attrs, latest) => ({ uuid: `u-${name}`, name, pointType, attrs, latestValue: latest });
const FIXTURE = {
  sites: [rec("Site A", "SITE", { id: "site-a" })],
  equips: [rec("AHU-1", "EQUIPMENT", { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu,rooftop" })],
  devices: [rec("CTRL-1", "DEVICE", { id: "CTRL-1", siteRef: "site-a", equipRef: "AHU-1", markers: "device,bacnet,controller" })],
  points: [
    rec("SAT", "POINT", { siteRef: "site-a", equipRef: "AHU-1", deviceRef: "CTRL-1", markers: "point,sensor,discharge,air,temp,his,cur", kind: "Number", unit: "°F", dis: "Supply \"air\" temp", class: "discharge-air-temp-sensor" }),
    rec("OAT", "POINT", { siteRef: "site-a", equipRef: "AHU-1", markers: "point,sensor,outside,air,temp,his,cur", kind: "Number", unit: "°F", class: "outside-air-temp-sensor" }),
    rec("OAH", "POINT", { siteRef: "site-a", equipRef: "AHU-1", markers: "point,sensor,outside,air,humidity,his,cur", kind: "Number", unit: "%RH" }),
    rec("FAN-C", "POINT", { siteRef: "site-a", equipRef: "AHU-1", markers: "point,cmd,discharge,fan,run,writable,his,cur", kind: "Bool" }),
    rec("SPARE", "POINT", { siteRef: "site-a", equipRef: "AHU-1", markers: "point,cmd,spare,his,cur", kind: "Number" }),
    rec("WX", "POINT", { siteRef: "site-a", weatherStationRef: "wx-1", markers: "point,sensor,weather,outside,air,temp,his", kind: "Number", unit: "°F" }),
    rec("INTERNAL", "POINT", { siteRef: "site-a", deviceRef: "CTRL-1" }),
  ],
};

function modelFor(ctx) {
  return { sites: FIXTURE.sites, equips: FIXTURE.equips, devices: FIXTURE.devices, points: FIXTURE.points.map(ctx.toPoint) };
}

test("toPoint reads tags, refs, units and labels from NF attrs", () => {
  const ctx = load("nf.js", "model.js");
  const p = ctx.toPoint(FIXTURE.points[0]);
  assert.deepEqual([...p.tags], ["point", "sensor", "discharge", "air", "temp", "his", "cur"]);
  assert.equal(p.equipRef, "AHU-1");
  assert.equal(p.units, "°F");
  assert.equal(p.name, "discharge air temp");
  assert.equal(ctx.toPoint(FIXTURE.points[6]).tags.length, 0);
});

test("Turtle export: every ref target and every non-standard tag is defined (no orphans)", () => {
  const ctx = load("nf.js", "model.js");
  const { turtle, nonStandard } = ctx.modelToTurtle(modelFor(ctx), "urn:test:");
  assert.deepEqual([...nonStandard], ["rooftop", "spare"]);
  const defined = new Set([...turtle.matchAll(/^local:(\S+)\n\s+a /gm)].map((m) => m[1]));
  const refs = [...turtle.matchAll(/(?:siteRef|equipRef|deviceRef|weatherStationRef) local:(\S+?)(?= ;| \.)/g)].map((m) => m[1]);
  assert.ok(refs.length >= 8);
  for (const r of refs) assert.ok(defined.has(r), `ref to undefined ${r}`);
  for (const t of nonStandard) assert.ok(defined.has(t), `tag ${t} not defined`);
  assert.match(turtle, /rdfs:label "Supply \\"air\\" temp"/);          // quotes escaped
  assert.ok(!/local:u-INTERNAL/.test(turtle), "untagged objects stay out of the graph");
});

test("pointSets picks cards, status and weather by tags only", () => {
  const ctx = load("nf.js", "model.js", "charts.js");
  const sets = ctx.pointSets(modelFor(ctx), "site-a", "");
  assert.deepEqual(Array.from(sets.cards, (p) => p.uuid), ["u-SAT", "u-OAT", "u-OAH"]);   // temps first, then by label
  assert.deepEqual(Array.from(sets.status, (p) => p.uuid), ["u-FAN-C"]);
  assert.deepEqual(Array.from(sets.weather, (p) => p.uuid), ["u-WX"]);
  assert.deepEqual(Array.from(ctx.rhPair(sets.cards), (p) => p.uuid), ["u-OAT", "u-OAH"]);
});

test("pickWindow keeps every chart request to ~360 values per series", () => {
  const ctx = load("nf.js", "model.js", "charts.js");
  for (const [hours, win] of [[6, 60], [24, 300], [72, 900], [168, 1800], [720, 7200]]) {
    assert.equal(ctx.get("pickWindow")(hours), win, `${hours} h`);
    assert.ok((hours * 3600) / win <= 360);
  }
});

test("fetchDisplay chunks 161 and 709 point history reads below the request limit", async () => {
  const ctx = load("nf.js", "model.js", "charts.js");
  const requests = [];
  ctx.fetch = async (url) => {
    requests.push(String(url));
    const params = new URL(String(url), "http://mock").searchParams;
    return { ok: true, status: 200, json: async () => ({ data: [...params.getAll("uuids")].map((uuid) => ({
      uuid, values: [{ ts: "2026-01-01T00:00:00Z", double: 1 }],
    })) }) };
  };
  for (const count of [161, 709]) {
    const points = Array.from({ length: count }, (_, i) => ({ uuid: `synthetic-${count}-${i.toString().padStart(4, "0")}`, units: "" }));
    const before = requests.length;
    const result = await ctx.fetchDisplay(points, 24, { windowSec: 3600 });
    const used = requests.slice(before);
    assert.ok(used.length > 1, `${count} uuids use multiple requests`);
    assert.ok(used.every((url) => Buffer.byteLength(url) < 8192), "each request stays below the mock front-door limit");
    assert.ok(used.every((url) => new URL(url, "http://mock").searchParams.getAll("uuids").length <= 40));
    assert.equal(result.size, count);
    assert.ok(points.every((p) => result.get(p.uuid)?.length === 1), "all chunk responses are merged");
  }
});

test("live update stream caps oversized lists and leaves the complete set to polling", () => {
  const ctx = load("nf.js");
  let state, requests = 0;
  ctx.fetch = async () => { requests++; throw new Error("should use polling"); };
  const stop = ctx.streamUpdates(Array.from({ length: 161 }, (_, i) =>
    `00000000-0000-4000-8000-${i.toString(16).padStart(12, "0")}`), () => {}, (up, err) => { state = { up, err }; });
  assert.equal(requests, 0);
  assert.equal(state.up, false);
  assert.match(state.err.message, /safe request limit/);
  assert.equal(typeof stop, "function");
});

test("byDay groups samples by local calendar day, in time order", () => {
  const ctx = load("nf.js", "model.js", "charts.js");
  const t0 = new Date(2026, 10, 1, 23, 30).getTime();
  const days = ctx.byDay([[t0, 1], [t0 + 3600e3, 2], [t0 + 7200e3, 3]]);
  assert.equal(days.size, 2);
  assert.deepEqual(Array.from(days.values(), (v) => v.length), [1, 2]);
  const beforeMidnight = Date.UTC(2026, 0, 2, 5, 30);
  const afterMidnight = Date.UTC(2026, 0, 2, 6, 30);
  const samples = [[beforeMidnight, 1], [afterMidnight, 2]];
  assert.equal(ctx.byDay(samples, "UTC").size, 1);
  assert.equal(ctx.byDay(samples, "America/Chicago").size, 2);
  const localHour = ctx.hourOfDayFormatter("America/Chicago");
  assert.equal(localHour(beforeMidnight), 23.5);
  assert.equal(localHour(afterMidnight), 0.5);
  const chart = ctx.chartOptionSiteTime({ xAxis: { type: "time" }, tooltip: { trigger: "axis" } }, "America/Chicago");
  assert.match(chart.xAxis.axisLabel.formatter(beforeMidnight), /11:30/);
  assert.match(chart.xAxis.axisPointer.label.formatter({ value: beforeMidnight }), /11:30/);
  assert.match(chart.tooltip.formatter([{ axisValue: beforeMidnight, value: [beforeMidnight, 1], seriesName: "series" }]), /11:30/);
});

test("weather hook: site comes from NF, never hard-coded", () => {
  const require = createRequire(import.meta.url);
  const hook = require("../hooks/weather.js");
  const sites = [{ id: "a", latitude: 43.07, longitude: -89.4 }, { id: "b", latitude: 0, longitude: 0 }];
  assert.equal(hook.pickSite(sites).id, "a");
  assert.throws(() => hook.pickSite(sites, "b"), /no latitude\/longitude/);
  assert.throws(() => hook.pickSite([sites[0], { id: "c", latitude: 1, longitude: 2 }]), /set the app config value "site"/);
  assert.throws(() => hook.pickSite([]), /no NF site has latitude/);
  assert.match(hook.openMeteoUrl(1.5, -2.5), /latitude=1\.5&longitude=-2\.5/);
  const dew = hook.magnusDewpointF(70, 50);
  assert.ok(dew > 49 && dew < 52, `dewpoint ${dew}`);
});

test("FDD binding: kinds from equip markers, inputs by NF class or markers", () => {
  const ctx = load("nf.js", "model.js", "fdd.js");
  const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
  const model = modelFor(ctx);
  assert.ok(Array.from(ctx.equipKinds(FIXTURE.equips[0], catalog)).includes("ahu"));
  const rows = ctx.equipRules(FIXTURE.equips[0], model, catalog);
  const byId = Object.fromEntries(Array.from(rows, (r) => [r.rule.id, r]));
  // FAN-RUNTIME-HOURS needs only fan_cmd: FAN-C carries fan,run,cmd (no class) -> runnable by markers
  assert.equal(byId["FAN-RUNTIME-HOURS"].runnable, true);
  assert.equal(byId["FAN-RUNTIME-HOURS"].bound.fan_cmd[0].uuid, "u-FAN-C");
  // sat is filled by class (discharge-air-temp-sensor), oa_t by class outside-air-temp-sensor
  const satRule = rows.find((r) => r.rule.required_roles.includes("sat"));
  assert.equal(satRule.bound.sat[0].uuid, "u-SAT");
  // a rule needing a role nobody has is listed with what is missing
  const econ = byId["ECON-1"];
  assert.ok(econ && !econ.runnable && Array.from(econ.missing).includes("oa_damper_pct"));
  // weather-service points fill web_* roles only; equipment sensors win oa_t
  const web = rows.find((r) => r.rule.required_roles.includes("web_oa_t"));
  if (web) assert.equal(web.bound.web_oa_t[0].uuid, "u-WX");
  const oat = rows.find((r) => r.rule.required_roles.includes("oa_t"));
  assert.deepEqual(Array.from(oat.bound.oa_t, (p) => p.uuid), ["u-OAT"]);
  // rules with no point roles read other data and are not "runnable"
  for (const r of rows) if (!r.pointInputs) assert.equal(r.runnable, false);
  // duplicate required/optional roles are listed once
  for (const r of rows) assert.equal(new Set([...r.required, ...r.optional]).size, r.required.length + r.optional.length);
  // runnable rules sort first
  assert.ok(rows[0].runnable);
});

test("FDD catalog covers every registry rule and only names NF classes", () => {
  const catalog = JSON.parse(readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
  const nf = new Set(JSON.parse(readFileSync(new URL("../rules/nf_classes.json", dir), "utf8")).classes);
  assert.ok(catalog.rules.length >= 70);
  for (const r of catalog.rules) {
    assert.deepEqual(r.unmapped_roles, [], `${r.id} has unmapped roles`);
    for (const role of [...r.required_roles, ...r.optional_roles]) assert.ok(catalog.roles[role], `${r.id}: role ${role}`);
  }
  for (const [role, def] of Object.entries(catalog.roles)) {
    for (const c of def.classes) assert.ok(nf.has(c), `${role}: ${c} is not an NF class`);
    assert.ok(def.classes.length || def.markers.length, `${role} cannot match anything`);
  }
});

test("Faults panel expands per-sensor sweep rows and heatmap scales hours separately from percent", async () => {
  const els = new Map();
  const el = (id) => { if (!els.has(id)) els.set(id, { hidden: false, checked: false, style: {}, innerHTML: "", textContent: "", attrs: {}, classes: new Set(),
    setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }, classList: { add: (x) => el(id).classes.add(x), remove: (x) => el(id).classes.delete(x), contains: (x) => el(id).classes.has(x) } }); return els.get(id); };
  let chartOption = null, disposedCharts = 0, rangeControl, lastRange;
  let chosenRange = { preset: "all" };
  const readRange = async (points, state, opts) => {
    lastRange = { state, opts };
    return { series: new Map(points.map((p) => [p.uuid, p.history || []])), windowSec: 3600 };
  };
  const ctx = vm.createContext({
    console,
    document: { getElementById: (id) => el(id) },
    location: { pathname: "/apps/static/open-fdd/" },
    has: (p, tag) => p.tags.includes(tag),
    idOf: (e) => e.id,
    latestOf: (p) => p.value,
    esc: (s) => String(s ?? "").replace(/[&<>\"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]),
    fmt: (v) => String(v ?? "–"), dispVal: (_p, v) => v,
    dispUnit: (p) => p.rec.attrs.unit,
    parseTs: (v) => Date.parse(v),
    rcxCurrentOutputSeries: (_p, samples, windowSec = 0) => {
      const boundary = Date.parse(_p.rec.attrs.fddOutputSince || "");
      if (!Number.isFinite(boundary)) return Array.from(samples || []);
      const width = windowSec * 1e3, first = width ? Math.ceil(boundary / width) * width : boundary;
      return Array.from(samples || []).filter(([t]) => t >= first);
    },
    FAULT_LANE: { lineStyle: { color: "#e11d48" } },
    fddCatalog: { sensor_sweep_roles: { "SV-STALE": ["sat", "mat", "oa_t", "rat"] } },
    echarts: { getInstanceByDom: () => ({ dispose: () => { disposedCharts++; } }) },
    chartTimeZone: (tz) => tz || "UTC",
    getChartRangeState: () => chosenRange,
    renderRangeControl: (_el, options) => { rangeControl = options; },
    fetchRange: readRange,
    ofddChart: () => ({ setOption: (o) => { chartOption = o; } }),
  });
  vm.runInContext(readFileSync(new URL("../static/app.js", import.meta.url), "utf8"), ctx, { filename: "app.js" });
  const h = 3600e3;
  const point = (uuid, name, equipRef, tags, attrs = {}, value = 0, history = []) => ({ uuid, name, dis: name, equipRef, siteRef: attrs.siteRef || "site-fixture", tags, value,
    latest: { ts: "2026-01-01T00:00:00Z" }, history, rec: { attrs: { ...attrs } } });
  const mixedHistory = multiSensorEquip.unitBoundarySeries();
  const mixedBoundary = new Date(mixedHistory[multiSensorEquip.unitBoundaryIndex].ts).toISOString();
  const sensorRoles = {
    "sensor-sat-1": "sat", "sensor-sat-2": "sat", "sensor-mat-1": "mat", "sensor-oa-1": "oa_t",
    "sensor-rat-1": "rat", "sensor-static-1": "duct_static",
  };
  const inputs = multiSensorEquip.points.filter((p) => p.attrs.equipRef === "AHU-A").map((p) => point(
    p.uuid, p.attrs.dis, p.attrs.equipRef, p.attrs.markers.split(","), p.attrs, multiSensorEquip.historyValue(p.uuid, 1),
  ));
  const rules = ["SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE", "SV-RATE"];
  const faultRole = { "SV-RANGE": "rat", "SV-FLATLINE": "sensor-sat-2", "SV-SPIKE": "mat", "SV-RATE": "mat" };
  const results = [];
  for (const rule of rules) {
    const values = inputs.map((input) => {
      const role = sensorRoles[input.uuid];
      let status = faultRole[rule] === input.uuid || faultRole[rule] === role ? "fault" : "ok";
      if (rule === "SV-STALE" && input.uuid === "sensor-sat-1") status = "stale";
      if (rule === "SV-STALE" && role === "duct_static") status = "not-assessed";
      if (rule === "SV-RATE" && input.uuid === "sensor-rat-1") status = "not-assessed";
      const value = status === "fault" ? 2 : status === "ok" ? 0 : null;
      return point(`${rule}-${input.uuid}`, `${input.name} ${rule}`, "AHU-A", ["fdd", "fault"], {
        ruleRef: rule, fddSummary: "sensor", sensorRef: input.uuid, roleRef: role,
        unit: "h", fddOutput: "fault_hours", fddOutputSince: new Date(90 * 60e3).toISOString(),
        fddStatus: status, fddWindowHours: "24", fddCoverageHours: status === "ok" ? "23.916666666666668" : "24",
      }, value, [[0, 95], [h, 80], [2 * h, value]]);
    });
    results.push(point(`${rule}-summary`, `AHU-A ${rule}`, "AHU-A", ["fdd", "fault"], {
      ruleRef: rule, fddSummary: "equip", unit: "h", fddOutput: "fault_hours", fddStatus: "fault", fddWindowHours: "24", fddCoverageHours: "24",
    }, 2, [[2 * h, 2]]), ...values);
  }
  const percentResult = point("legacy-pct", "FC1 output", "AHU-A", ["fdd", "fault"], { ruleRef: "FC1", unit: "%", fddOutput: "fault_pct" }, 30, [[h, 30]]);
  const mixedResult = point(multiSensorEquip.unitBoundaryPoint.uuid, "legacy sweep output", "AHU-A", ["fdd", "fault"], {
    ruleRef: "SV-LEGACY", fddSummary: "equip", unit: "h", fddOutput: "fault_hours", fddOutputSince: mixedBoundary,
    fddStatus: "fault", fddWindowHours: "24",
  }, 2.25, mixedHistory.map((x) => [Date.parse(x.ts), x.value]));
  const otherSiteResult = point("other-site-result", "other site", "AHU-A", ["fdd", "fault"], {
    ruleRef: "SV-RANGE", fddSummary: "sensor", sensorRef: "other-sensor", roleRef: "rat", siteRef: "site-other", unit: "h", fddOutput: "fault_hours", fddStatus: "fault",
  }, 99);
  const vavResult = point("vav-result", "VAV-only result", "VAV-A", ["fdd", "fault"], {
    ruleRef: "FC1", siteRef: "site-fixture", unit: "%", fddOutput: "fault_pct", fddStatus: "fault",
  }, 5);
  ctx.testModel = { sites: [{ id: "site-fixture", attrs: { tz: "America/Chicago" } }], equips: [
    { id: "AHU-A", name: "AHU-A", attrs: { siteRef: "site-fixture" } },
    { id: "VAV-A", name: "VAV-A", attrs: { siteRef: "site-fixture" } },
    { id: "AHU-A", name: "Other AHU-A", attrs: { siteRef: "site-other" } },
  ], points: [...results, percentResult, mixedResult, otherSiteResult, vavResult, ...inputs] };
  vm.runInContext("model = testModel", ctx);
  vm.runInContext('scope.site = "site-fixture"', ctx);
  const initial = vm.runInContext("renderScopedFddResults()", ctx);
  assert.match(el("fddRangeStatus").textContent, /Loading fault history/);
  assert.equal(el("fddLanes").attrs["aria-busy"], "true");
  await initial;
  assert.equal(el("fddRangeStatus").textContent, "");
  assert.equal(el("fddLanes").attrs["aria-busy"], undefined);
  assert.equal(rangeControl.key, "faults");
  assert.equal(lastRange.state.preset, "all");
  assert.equal(lastRange.opts.siteTz, "America/Chicago");
  chosenRange = { preset: "custom", fromMs: 0, toMs: 3 * h };
  await rangeControl.onChange();
  assert.deepEqual(lastRange.state, chosenRange, "range control refreshes the Faults request");
  chosenRange = { preset: "all" };
  let html = el("fddResultRows").innerHTML;
  assert.match(html, /equipment summary/);
  assert.match(html, /data-expand=/);
  assert.match(html, /not-assessed/);
  assert.match(html, /stale/);
  assert.match(html, /23\.92 h covered/);
  assert.doesNotMatch(html, /23\.916666666666668/);
  assert.equal(vm.runInContext("formatFaultNumber(23.916666666666668)", ctx), "23.92");
  assert.equal(vm.runInContext("formatFaultNumber(0)", ctx), "0");
  assert.equal(vm.runInContext("formatFaultNumber(null)", ctx), "–");
  assert.equal(vm.runInContext("formatFaultNumber('')", ctx), "–");
  assert.doesNotMatch(html, /other-sensor/);
  assert.match(html, /sensor-1/);
  assert.match(html, /sensor-2/);
  assert.equal((html.match(/class="clickable fdd-sensor-row"/g) || []).length, 30, "six rows for each of five SV rules");
  assert.match(html, /fdd-sensor-row[^>]* hidden/);
  assert.equal(chartOption.visualMap.find((x) => x.max === 24).text[0], "24 h");
  assert.equal(chartOption.visualMap.find((x) => x.max === 100).text[0], "100 %");
  const hSeries = chartOption.series.find((s) => s.name === "h");
  const hCells = Array.from(hSeries.data, (x) => Array.from(x));
  assert.ok(hCells.some((x) => x[2] === 2.25), "current h value remains from the shared mixed-history fixture");
  assert.ok(hCells.some((x) => x[2] === 0), "assessed-zero cells remain visible");
  assert.ok(hCells.every((x) => x[2] != null), "missing samples are not displayed as zeros");
  assert.ok(!chartOption.yAxis.data.some((x) => x.includes("SV-STALE") && x.endsWith("sensor-1")), "empty stale sensor lane is collapsed");
  assert.ok(!chartOption.yAxis.data.some((x) => x.includes("SV-STALE") && x.includes("duct_static")), "empty excluded-role lane is collapsed");
  assert.ok(chartOption.yAxis.data.some((x) => x.includes("SV-STALE") && x.endsWith("sensor-2")), "assessed-zero peer stays visible");
  assert.ok(hCells.every((x) => x[2] !== 18 && x[2] !== 95 && x[2] !== 80), "pre-boundary % history is excluded");
  const hRow = chartOption.yAxis.data.findIndex((x) => x.includes("SV-RANGE") && x.includes("sensor-5"));
  assert.match(chartOption.tooltip.formatter({ value: [1, hRow, 2] }), /2 h/);
  const percentRow = chartOption.yAxis.data.findIndex((x) => x.startsWith("FC1"));
  assert.match(chartOption.tooltip.formatter({ value: [0, percentRow, 30] }), /30 %/);

  el("fddFaultedOnly").checked = true;
  await vm.runInContext("renderFddResults(model.equips)", ctx);
  html = el("fddResultRows").innerHTML;
  assert.doesNotMatch(html, /data-rule="SV-RANGE" data-equip="AHU-A" data-sensor="sensor-sat-1"/);
  assert.doesNotMatch(html, /stale|not-assessed/);
  el("fddFaultedOnly").checked = false;
  await vm.runInContext("renderFddResults(model.equips)", ctx);
  html = el("fddResultRows").innerHTML;
  assert.match(html, /stale/);
  assert.match(html, /not-assessed/);
  vm.runInContext('scope.equip = "VAV-A"', ctx);
  await vm.runInContext("renderScopedFddResults()", ctx);
  assert.match(el("fddResultRows").innerHTML, /data-equip="VAV-A"/);
  assert.doesNotMatch(el("fddResultRows").innerHTML, /SV-RANGE/);
  vm.runInContext('scope.equip = "AHU-A"', ctx);
  await vm.runInContext("renderScopedFddResults()", ctx);
  assert.match(el("fddResultRows").innerHTML, /SV-RANGE/);
  el("fddLanes").textContent = "echarts canvas marker";
  await vm.runInContext("renderFddResults(model.equips)", ctx);
  assert.equal(el("fddLanes").textContent, "echarts canvas marker", "normal rerenders preserve chart DOM");
  assert.equal(disposedCharts, 0, "normal rerenders reuse the live chart instance");
  ctx.fetchRange = async () => { throw new Error("history unavailable"); };
  await vm.runInContext("renderFddResults(model.equips)", ctx);
  assert.equal(el("fddLanes").hidden, false);
  assert.equal(el("fddLanes").attrs.role, "alert");
  assert.match(el("fddLanes").textContent, /history unavailable/);
  assert.equal(disposedCharts, 1, "replace chart DOM only after disposing its instance");
  ctx.fetchRange = readRange;
  await vm.runInContext("renderFddResults(model.equips)", ctx);
  assert.equal(el("fddLanes").textContent, "", "successful recovery clears only the prior error text");
  assert.equal(el("fddLanes").attrs.role, undefined);
  assert.equal(el("fddLanes").classes.has("history-error"), false);
});

test("161 fault lanes render an option using the real chunked All history path", async () => {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, { hidden: false, checked: false, style: {}, innerHTML: "", textContent: "", attrs: {}, classes: new Set(),
      setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; },
      classList: { add: (x) => el(id).classes.add(x), remove: (x) => el(id).classes.delete(x), contains: (x) => el(id).classes.has(x) } });
    return elements.get(id);
  };
  const requests = [];
  let option = null;
  const ctx = vm.createContext({
    console, URL, URLSearchParams, TextDecoder,
    document: { getElementById: el }, location: { pathname: "/apps/static/open-fdd/" },
    has: (p, tag) => p.tags.includes(tag), idOf: (e) => e.id,
    latestOf: (p) => p.latest?.double, esc: (s) => String(s ?? "").replace(/[&<>\"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]),
    fmt: (v) => String(v ?? "–"), dispVal: (_p, v) => v, dispUnit: (p) => p.units || "",
    rcxCurrentOutputSeries: (_p, samples) => samples,
    FAULT_LANE: { lineStyle: { color: "#e11d48" } },
    echarts: { getInstanceByDom: () => null },
    fetch: async (url) => {
      requests.push(url);
      assert.ok(Buffer.byteLength(url) < 6500, "mock front door allows each chunk");
      const params = new URLSearchParams(url.split("?")[1]);
      const ids = params.getAll("uuids");
      assert.ok(ids.length <= 40);
      return { ok: true, json: async () => ({ data: ids.map((uuid) => ({ uuid, values: [{ ts: "2026-01-01T00:00:00Z", double: 1 }] })) }) };
    },
    ofddChart: () => ({ setOption: (built) => { option = built; } }),
  });
  for (const file of ["nf.js", "model.js", "charts.js", "app.js"]) {
    vm.runInContext(readFileSync(new URL(`../static/${file}`, import.meta.url), "utf8"), ctx, { filename: file });
  }
  ctx.renderRangeControl = () => {};
  ctx.getChartRangeState = () => ({ preset: "all" });
  const points = Array.from({ length: 161 }, (_, i) => {
    const uuid = `00000000-0000-4000-8000-${i.toString(16).padStart(12, "0")}`;
    return { uuid, name: `sensor-${i}`, dis: `sensor-${i}`, units: "h", equipRef: "equip-1", siteRef: "site-1", tags: ["fdd", "fault"], latest: { double: 1, ts: "2026-01-01T00:00:00Z" },
      rec: { attrs: { ruleRef: "SV-RANGE", sensorRef: uuid, roleRef: "sat", fddSummary: "sensor", fddOutput: "fault_hours", fddStatus: "fault" } } };
  });
  ctx.testModel = { equips: [{ id: "equip-1", name: "equip-1", attrs: { siteRef: "site-1" } }], points };
  vm.runInContext('model = testModel; scope.site = "site-1"', ctx);
  await vm.runInContext("renderFddResults(model.equips)", ctx);
  assert.ok(requests.length > 1, "the rendered lanes read history in multiple bounded requests");
  assert.equal(option.yAxis.data.length, 161);
  assert.equal(option.series.length, 1);
  assert.ok(option.series[0].data.length > 0, "the chart option has plotted lane data");
  assert.equal(el("fddLanes").hidden, false);
});

test("point history honors the same mixed-output boundary as FDD plots", async () => {
  const elements = new Map();
  const element = (id) => { if (!elements.has(id)) elements.set(id, { textContent: "" }); return elements.get(id); };
  let plotted = null, requestedWindow = null;
  const ctx = vm.createContext({
    console, document: { getElementById: element }, location: { pathname: "/apps/static/open-fdd/" },
    GENERIC: new Set(), tooltip: {}, unitLabel: (u) => u, dispUnit: (p) => p.rec.attrs.unit, dispSeries: (_p, arr) => arr,
    pickWindow: () => 3600,
    getChartRangeState: () => ({ preset: "24h" }), renderRangeControl: () => {}, chartTimeZone: (tz) => tz || "UTC",
    chartOptionSiteTime: (option) => option,
    resolveChartSelection: async (_points, state) => ({ ...state, resolvedBounds: { fromMs: 0, toMs: 24 * 3600e3 } }),
    fetchRange: async (points, _state, options) => {
      requestedWindow = options.windowSec;
      return { windowSec: options.windowSec, fromMs: 0, toMs: 24 * 3600e3,
        series: new Map(points.map((p) => [p.uuid, [[0, 95], [3600e3, 80], [7200e3, 2], [10800e3, 0]]])) };
    },
    rcxCurrentOutputSeries: (_p, samples, width) => {
      const boundary = Date.parse(_p.rec.attrs.fddOutputSince || ""), first = Math.ceil(boundary / (width * 1e3)) * width * 1e3;
      return samples.filter(([t]) => t >= first);
    },
    ofddChart: () => ({}), ofddRender: (_chart, option) => { plotted = option.series[0].data; },
  });
  vm.runInContext(readFileSync(new URL("../static/app.js", import.meta.url), "utf8"), ctx, { filename: "app.js" });
  const current = { uuid: "legacy", dis: "legacy output", name: "legacy output", kind: "Number", tags: [], rec: { attrs: {
    unit: "h", fddOutput: "fault_hours", fddOutputSince: new Date(90 * 60e3).toISOString(),
  } } };
  ctx.testModel = { points: [current] };
  vm.runInContext('model = testModel; selectedPoint = "legacy"; histHours = 24', ctx);
  await vm.runInContext("renderPointHistory()", ctx);
  assert.equal(requestedWindow, 3600, "filter cutoff uses the same bucket width as the NF request");
  assert.deepEqual(Array.from(plotted, (x) => Array.from(x)), [[7200e3, 2], [10800e3, 0]], "older % buckets are not shown under current h units");
});

test("RCx ignores superseded range resolutions and failures", async () => {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { textContent: "", innerHTML: "", classList: { add() {}, remove() {}, toggle() {} } });
    return elements.get(id);
  };
  const pending = [];
  const ctx = vm.createContext({
    console, document: { getElementById: element }, location: { pathname: "/apps/static/open-fdd/" },
    idOf: (r) => (r.attrs || {}).id || r.name,
    has: (p, marker) => (p.tags || []).includes(marker),
    chartTimeZone: (tz) => tz || "UTC", getChartRangeState: () => ({ preset: "24h" }),
    renderRangeControl: () => {}, loadCatalog: async () => ({}),
    rcxPlan: () => ({ ready: [], missing: [] }),
    resolveChartSelection: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
  });
  vm.runInContext(readFileSync(new URL("../static/app.js", import.meta.url), "utf8"), ctx, { filename: "app.js" });
  ctx.testModel = { sites: [{ name: "Site", attrs: { id: "site-a" } }], equips: [], points: [] };
  vm.runInContext('model = testModel; scope.site = "site-a"', ctx);

  const older = vm.runInContext("renderRcx()", ctx);
  await new Promise(setImmediate);
  const newer = vm.runInContext("renderRcx()", ctx);
  await new Promise(setImmediate);
  element("rcxRangeStatus").textContent = "new range is loading";
  pending[0].reject(new Error("obsolete failure"));
  await assert.rejects(older, /obsolete failure/);
  assert.equal(element("rcxRangeStatus").textContent, "new range is loading");
  pending[1].resolve({ resolvedBounds: { fromMs: 0, toMs: 3600e3 } });
  await newer;
  assert.equal(element("rcxRangeStatus").textContent, "");
});

test("rule plot panel is visible while resolving a range and exposes lookup errors", async () => {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, { textContent: "", hidden: true, classList: { add() {}, remove() {} }, scrollIntoView() {} });
    return elements.get(id);
  };
  let rejectRange;
  const ctx = vm.createContext({
    console, document: { getElementById: element }, location: { pathname: "/apps/static/open-fdd/" },
    idOf: (r) => (r.attrs || {}).id || r.name, has: (p, marker) => (p.tags || []).includes(marker),
    equipLabel: (e) => e.name, chartTimeZone: () => "UTC", getChartRangeState: () => ({ preset: "custom" }),
    renderRangeControl: () => {}, loadCatalog: async () => ({}), equipRules: () => [{ rule: { id: "SV-RANGE", description: "sensor bounds" }, bound: {} }],
    resolveChartSelection: () => new Promise((_resolve, reject) => { rejectRange = reject; }),
  });
  vm.runInContext(readFileSync(new URL("../static/app.js", import.meta.url), "utf8"), ctx, { filename: "app.js" });
  ctx.testModel = { equips: [{ name: "AHU-1", attrs: { id: "AHU-1", siteRef: "site-a" } }],
    points: [{ name: "SAT", equipRef: "AHU-1", siteRef: "site-a", tags: ["his"] }] };
  vm.runInContext('model = testModel; scope.site = "site-a"', ctx);

  const plot = vm.runInContext('showRulePlot("SV-RANGE", "AHU-1").catch((e) => { $("fddPlotNote").textContent = `could not draw: ${e.message}`; })', ctx);
  await new Promise(setImmediate);
  assert.equal(element("fddPlotPanel").hidden, false);
  assert.equal(element("fddPlotRangeStatus").textContent, "Resolving range…");
  rejectRange(new Error("range lookup failed"));
  await plot;
  assert.equal(element("fddPlotNote").textContent, "could not draw: range lookup failed");
});
