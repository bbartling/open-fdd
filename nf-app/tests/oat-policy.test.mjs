// node --test nf-app/tests/oat-policy.test.mjs
// #1552: outside-air temperature for the FDD hook is "web weather first, else the equip's own sensor". With the weather
// option off the weather points are ignored (stale leftovers) and a rule with no OAT at all skips with a reason.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");
const analytics = require("../hooks/analytics.js");

const STEP = 300;
const NOW = Date.parse("2026-11-05T12:02:00Z");
const pt = (uuid, name, markers, extra = {}) => ({
  uuid, name, layer: "default", pointType: "POINT",
  attrs: { siteRef: "site-a", markers: ["point", "his", ...markers].join(","), dis: name, ...extra },
});
const MODEL = [
  { uuid: "s", name: "site-a", pointType: "SITE", attrs: { id: "site-a", markers: "site", tz: "America/Chicago" } },
  { uuid: "e", name: "AHU-1", pointType: "EQUIPMENT", attrs: { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu" } },
];
const LOCAL = pt("u-OAT", "OAT-LOCAL", ["outside", "air", "temp", "sensor"], { equipRef: "AHU-1", class: "outside-air-temp-sensor", unit: "degF" });
const WEB = pt("u-WEB", "web-oat", ["weather", "outside", "air", "temp"], { unit: "degF" });
const VALVE = pt("u-VALVE", "CLG-VLV", ["cool", "valve", "cmd"], { equipRef: "AHU-1", class: "cool-valve-cmd", unit: "%" });

function http(points) {
  return {
    async post(p, body) {
      if (p === "/api/v1/point/query") {
        if (body.layer === "model") return { data: { points: MODEL } };
        return { data: { points } };
      }
      if (p === "/api/v1/point/points" || p === "/api/v1/points/data") return { data: { success: true } };
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (p.startsWith("/api/v1/platform/info")) return { data: { resources: [{ memory: { totalBytes: String(1024 ** 3) } }] } };
      if (p.startsWith("/api/v1/point/data?")) {
        const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
        const val = { "u-OAT": 40, "u-WEB": 10, "u-VALVE": 50 };
        return { data: { data: uuids.map((uuid) => ({ uuid, values: Array.from({ length: 288 }, (_, i) => ({ ts: new Date(NOW - 24 * 3600e3 + i * STEP * 1e3).toISOString(), double: val[uuid] })) })) } };
      }
      throw new Error("unexpected GET " + p);
    },
  };
}
const PACK = {
  poll_seconds: STEP,
  contract: { history: [{ name: "equipment_id", type: "text" }, { name: "timestamp_utc", type: "timestamp" },
    { name: "web_oa_t", type: "double" }, { name: "clg_valve_pct", type: "double" }, { name: "oa_t", type: "double" }] },
  rules: {
    "MECH-OAT-1": { sql: "-", output_columns: ["equipment_id", "fault_hours"] },
    "OAT-METEO": { sql: "-", output_columns: ["equipment_id", "fault_hours", "fault_pct"] },
  },
};
async function run(points, config = {}) {
  const seen = { input: {}, queries: [] };
  const logs = [];
  const engine = async ({ kind }) => ({
    kind,
    async load(input) { seen.input = input; },
    async query(id) { seen.queries.push(id); return [{ equipment_id: "AHU-1", fault_hours: 0, covered_hours: 24, fault_pct: 0 }]; },
    async close() {},
  });
  const summary = await hook.runFdd({ sdk: { http: http(points), logEvent: (m) => logs.push(m) }, config: { engine: "sqlite", ...config }, pack: PACK, createEngine: engine, now: NOW });
  return { summary, seen, logs };
}
const col = (seen, name) => [...new Set((seen.input.history || []).map((r) => r[name]).filter((x) => x != null))];
const near = (a, b) => Math.abs(a - b) < 0.01;

test("web weather bound: it is used and the local sensor is only the OAT-METEO comparison side", async () => {
  const { summary, seen } = await run([LOCAL, WEB, VALVE]);
  assert.deepEqual(summary.oat, { weather: "on", web: 1, local: 0, none: 0, local_points: [] });
  assert.ok(seen.queries.includes("MECH-OAT-1"));
  const web = col(seen, "web_oa_t");
  assert.ok(web.length === 1 && near(web[0], (10 - 32) * 5 / 9), `web_oa_t is the weather point (10 degF): ${web}`);
});

test("no web weather but a local OA sensor: it feeds web_oa_t (local fallback), the comparison rule is not given itself", async () => {
  const { summary, seen, logs } = await run([LOCAL, VALVE]);
  assert.equal(summary.oat.local, 1);
  assert.deepEqual(summary.oat.local_points, [{ site: "site-a", equip: "AHU-1", point: "outside air temp" }]);
  assert.ok(logs.some((l) => /using the local outside-air sensor "outside air temp"/.test(l)), logs.join("\n"));
  assert.ok(seen.queries.includes("MECH-OAT-1"), "MECH-OAT-1 requires web_oa_t: runnable through the local sensor");
  const web = col(seen, "web_oa_t");
  assert.ok(web.length === 1 && near(web[0], (40 - 32) * 5 / 9), `web_oa_t is the local sensor (40 degF): ${web}`);
});

test("weather:false ignores stale weather points and uses the local sensor; OAT-METEO skips with the reason", async () => {
  const { summary, seen, logs } = await run([LOCAL, WEB, VALVE], { weather: false });
  assert.equal(summary.oat.weather, "off");
  assert.equal(summary.oat.local, 1);
  const web = col(seen, "web_oa_t");
  assert.ok(web.length === 1 && near(web[0], (40 - 32) * 5 / 9), "the stale weather point (10 degF) is not used");
  assert.ok(!seen.queries.includes("OAT-METEO"), "OAT-METEO would compare the sensor with itself");
  assert.ok(logs.some((l) => /OAT-METEO skipped: no outside-air temperature \(weather disabled\)/.test(l)), logs.join("\n"));
});

test("weather:false and no local OA sensor: rules that need web OAT skip with a clear reason, never run on nothing", async () => {
  const { summary, seen, logs } = await run([WEB, VALVE], { weather: "false" });
  assert.equal(summary.oat.none, 1);
  assert.equal(summary.equips, 0, "nothing evaluated");
  assert.ok(logs.some((l) => /MECH-OAT-1, OAT-METEO skipped: no outside-air temperature \(weather disabled\)/.test(l)), logs.join("\n"));
  assert.ok(!seen.queries.includes("MECH-OAT-1"));
  assert.ok(!seen.queries.includes("OAT-METEO"));
});

test("weather on, nothing bound and no local sensor: unchanged (no new skip reason)", async () => {
  const { summary } = await run([VALVE]);
  assert.equal(summary.oat.none, 1);
  assert.ok(!summary.skipped.some((s) => /weather is disabled/.test(s.detail)));
});

test("applyOatPolicy: the timescale engine cannot substitute (one role per point)", () => {
  const row = (id, required, optional, bound) => ({ rule: { id }, required, optional, bound, missing: required.filter((r) => !(bound[r] || []).length), pointInputs: true, runnable: true });
  const rows = [row("MECH-OAT-1", ["web_oa_t"], [], { web_oa_t: [] })];
  rows[0].runnable = false;
  const r = hook.applyOatPolicy(rows, { localOat: { name: "x" }, weatherOn: false, canSubstitute: false });
  assert.equal(r.source, "none");
  assert.match(rows[0].skipReason, /cannot be used on the timescale engine/);
  assert.equal(rows[0].runnable, false);
});

test("RCx and energy: the dashboard ignores weather points when the app option is off", () => {
  const src = (f) => readFileSync(new URL(`../static/${f}`, import.meta.url), "utf8");
  const ctx = vm.createContext({ console, Intl, URLSearchParams, Date, Math, api: async () => ({}), location: { pathname: "/", search: "", href: "https://x/" } });
  vm.runInContext(src("charts.js"), ctx);
  const get = (n) => vm.runInContext(n, ctx);
  const app = (opts) => ({ id: "open-fdd", options: opts });
  assert.equal(get("appWeatherOff")(app([{ name: "weather", value: { boolean: false } }])), true);
  assert.equal(get("appWeatherOff")(app([{ name: "weatherEnabled", value: { string: "off" } }])), true);
  assert.equal(get("appWeatherOff")(app([{ name: "weather", value: { boolean: true } }])), false);
  assert.equal(get("appWeatherOff")(app([])), false);
  get("setSiteTimeZoneSources")({ weatherOff: true });
  assert.equal(get("weatherDisabled")(), true);
  get("setSiteTimeZoneSources")({});
  assert.equal(get("weatherDisabled")(), false);
  // the analytics sandbox gets the same switch
  const g = analytics.loadSandbox({ get: async () => ({ data: {} }) }, Date.now(), { weatherOff: true });
  assert.equal(g("weatherDisabled")(), true);
  assert.match(src("rcx.js"), /weatherDisabled\(\) \? \[\]/);
  assert.match(src("energy.js"), /weatherDisabled\(\) \? null : b\.web_oa_t/);
});
