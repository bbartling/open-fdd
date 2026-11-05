// node --test nf-app/tests — logic tests for the Open-FDD NF app (no NF, no browser).
// The page scripts are classic browser scripts, so they run in a vm context like the page does.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

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

test("byDay groups samples by local calendar day, in time order", () => {
  const ctx = load("nf.js", "model.js", "charts.js");
  const t0 = new Date(2026, 10, 1, 23, 30).getTime();
  const days = ctx.byDay([[t0, 1], [t0 + 3600e3, 2], [t0 + 7200e3, 3]]);
  assert.equal(days.size, 2);
  assert.deepEqual(Array.from(days.values(), (v) => v.length), [1, 2]);
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
