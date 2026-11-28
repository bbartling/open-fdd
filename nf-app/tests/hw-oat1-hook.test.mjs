// node --test nf-app/tests/hw-oat1-hook.test.mjs
// #1782 HW-OAT-1 through the FDD hook, the way MECH-OAT-1 runs: weather_service_air_temperature is required, and the site's weather point (the
// sidecar the Open-Meteo hook writes, tagged `weather` in NF) fills it for a boiler with no outside-air sensor of its own.
// The engine gets it both as the history column and as the weather table the SQL joins as-of.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");

const STEP = 300;
const NOW = Date.parse("2026-07-05T12:02:00Z");
const pt = (uuid, name, markers, extra = {}) => ({
  uuid, name, layer: "default", pointType: "POINT",
  attrs: { siteRef: "site-a", markers: ["point", "his", ...markers].join(","), dis: name, ...extra },
});
const MODEL = [
  { uuid: "s", name: "site-a", pointType: "SITE", attrs: { id: "site-a", markers: "site", tz: "America/Chicago" } },
  { uuid: "e", name: "BLR-1", pointType: "EQUIPMENT", attrs: { id: "BLR-1", siteRef: "site-a", markers: "equip,boiler" } },
];
const PUMP = pt("u-PUMP", "HW-PUMP-S", ["pump", "run", "sensor"], { equipRef: "BLR-1", unit: "" });
const WEB = pt("u-WEB", "oa_dry_bulb_web", ["weather", "outside", "air", "temp", "sensor"], { unit: "degF" });
const LOCAL = pt("u-OAT", "OAT-LOCAL", ["outside", "air", "temp", "sensor"], { equipRef: "BLR-1", class: "outside-air-temp-sensor", unit: "degF" });

function http(points) {
  return {
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? MODEL : points } };
      if (p === "/api/v1/point/points" || p === "/api/v1/points/data") return { data: { success: true } };
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (p.startsWith("/api/v1/platform/info")) return { data: { resources: [{ memory: { totalBytes: String(1024 ** 3) } }] } };
      if (p.startsWith("/api/v1/point/data?")) {
        const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
        const val = { "u-PUMP": 1, "u-WEB": 77, "u-OAT": 50 };
        return { data: { data: uuids.map((uuid) => ({ uuid, values: Array.from({ length: 288 }, (_, i) => ({ ts: new Date(NOW - 24 * 3600e3 + i * STEP * 1e3).toISOString(), double: val[uuid] })) })) } };
      }
      throw new Error("unexpected GET " + p);
    },
  };
}
const PACK = {
  poll_seconds: STEP,
  contract: { history: [{ name: "equipment_id", type: "text" }, { name: "timestamp_utc", type: "timestamp" },
    { name: "weather_service_air_temperature", type: "double" }, { name: "pump_operating_status", type: "double" }, { name: "supply_hot_water_temperature", type: "double" }, { name: "outdoor_air_intake_temperature", type: "double" }] },
  rules: { "HW-OAT-1": { sql: "-", output_columns: ["equipment_id", "fault_hours", "covered_hours", "fault_pct", "assessment"] } },
};
async function run(points, config = {}) {
  const seen = { input: {}, queries: [] };
  const logs = [];
  const engine = async ({ kind }) => ({
    kind,
    async load(input) { seen.input = input; },
    async query(id) { seen.queries.push(id); return [{ equipment_id: "BLR-1", fault_hours: 23.5, covered_hours: 24, fault_pct: 97.9, assessment: "assessed" }]; },
    async close() {},
  });
  const summary = await hook.runFdd({ sdk: { http: http(points), logEvent: (m) => logs.push(m) }, config: { engine: "duckdb", ...config }, pack: PACK, createEngine: engine, now: NOW });
  return { summary, seen, logs };
}
const vals = (rows, name) => [...new Set((rows || []).map((r) => r[name]).filter((x) => x != null))];
const near = (a, b) => Math.abs(a - b) < 0.01;

test("weather sidecar only (no outside-air sensor on the boiler): HW-OAT-1 is assessed on the web dry bulb", async () => {
  const { summary, seen } = await run([PUMP, WEB]);
  assert.equal(summary.oat.web, 1);
  assert.equal(summary.oat.local, 0);
  assert.ok(seen.queries.includes("HW-OAT-1"), "HW-OAT-1 runs with only the site weather point");
  const web = vals(seen.input.history, "weather_service_air_temperature");
  assert.ok(web.length === 1 && near(web[0], 25), `history weather_service_air_temperature is the weather point in SI: ${web}`);
  const wx = vals(seen.input.weather, "weather_service_air_temperature");
  assert.ok(wx.length === 1 && near(wx[0], 25), `the weather table carries it for the as-of join: ${wx}`);
  assert.ok(summary.results.some((r) => r.rule === "HW-OAT-1" && r.equip === "BLR-1"), JSON.stringify(summary.results));
});

test("weather off and no outside-air sensor: HW-OAT-1 skips with the reason, as MECH-OAT-1 does", async () => {
  const { seen, logs } = await run([PUMP, WEB], { weather: false });
  assert.ok(!seen.queries.includes("HW-OAT-1"));
  assert.ok(logs.some((l) => /HW-OAT-1 skipped: no outside-air temperature \(weather disabled\)/.test(l)), logs.join("\n"));
});

test("no weather point but a local outside-air sensor: it fills weather_service_air_temperature (the local fallback)", async () => {
  const { summary, seen } = await run([PUMP, LOCAL]);
  assert.equal(summary.oat.local, 1);
  assert.ok(seen.queries.includes("HW-OAT-1"));
  const web = vals(seen.input.history, "weather_service_air_temperature");
  assert.ok(web.length === 1 && near(web[0], 10), `weather_service_air_temperature is the local sensor (50 degF): ${web}`);
});

// ---- the real pack on the DuckDB engine: what the FDD tab draws -------------------------------------------------------
function recordingHttp(points) {
  const base = http(points);
  const writes = { points: [], data: [] };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/points") { writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/points/data") { for (const x of body.points) writes.data.push({ uuid: x.uuid, values: x.values }); return { data: { success: true } }; }
      return base.post(p, body);
    },
    get: (p) => base.get(p),
  };
}
async function realRun(points) {
  const h = recordingHttp(points);
  const logs = [];
  const summary = await hook.runFdd({ sdk: { http: h, logEvent: (m) => logs.push(m) }, config: { engine: "duckdb" }, now: NOW });
  const rec = (marker) => h.writes.points.find((r) => r.layer === "model" && new RegExp(marker).test(r.attrs.markers) && r.attrs.ruleRef === "HW-OAT-1");
  const timeline = rec("fault_timeline");
  const lane = timeline ? h.writes.data.filter((d) => d.uuid === timeline.uuid).flatMap((d) => d.values) : [];
  return { summary, logs, result: rec("(^|,)fdd(,|$)"), lane };
}

test("real engine: weather only, no pump status and no HW supply -> not assessed and no fault-lane samples", async () => {
  const { summary, result, lane } = await realRun([WEB]);
  assert.ok(!summary.results.some((r) => r.rule === "HW-OAT-1"), "no assessed HW-OAT-1 result");
  assert.ok(result, "the not-assessed result record is written");
  assert.equal(lane.length, 0, `an unassessed plant is never drawn as a clean no-fault lane: ${JSON.stringify(lane.slice(0, 3))}`);
});

test("real engine: HW pump proven on at 25 C -> fault, and the lane shows it", async () => {
  const { summary, lane } = await realRun([PUMP, WEB]);
  const r = summary.results.find((x) => x.rule === "HW-OAT-1");
  assert.ok(r && r.fault, JSON.stringify(summary.results));
  assert.ok(lane.some((v) => v.real === 1), "confirmed fault samples on the lane");
});
