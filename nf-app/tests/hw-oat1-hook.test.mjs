// node --test nf-app/tests/hw-oat1-hook.test.mjs
// #1782 HW-OAT-1 through the FDD hook, the way MECH-OAT-1 runs: web_oa_t is required, and the site's weather point (the
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
const WEB = pt("u-WEB", "oa_dry_bulb_web", ["weather", "outside", "air", "temp"], { unit: "degF" });
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
    { name: "web_oa_t", type: "double" }, { name: "pump_status", type: "double" }, { name: "hw_supply_t", type: "double" }, { name: "oa_t", type: "double" }] },
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
  const summary = await hook.runFdd({ sdk: { http: http(points), logEvent: (m) => logs.push(m) }, config: { engine: "sqlite", ...config }, pack: PACK, createEngine: engine, now: NOW });
  return { summary, seen, logs };
}
const vals = (rows, name) => [...new Set((rows || []).map((r) => r[name]).filter((x) => x != null))];
const near = (a, b) => Math.abs(a - b) < 0.01;

test("weather sidecar only (no outside-air sensor on the boiler): HW-OAT-1 is assessed on the web dry bulb", async () => {
  const { summary, seen } = await run([PUMP, WEB]);
  assert.equal(summary.oat.web, 1);
  assert.equal(summary.oat.local, 0);
  assert.ok(seen.queries.includes("HW-OAT-1"), "HW-OAT-1 runs with only the site weather point");
  const web = vals(seen.input.history, "web_oa_t");
  assert.ok(web.length === 1 && near(web[0], 25), `history web_oa_t is the weather point in SI: ${web}`);
  const wx = vals(seen.input.weather, "web_oa_t");
  assert.ok(wx.length === 1 && near(wx[0], 25), `the weather table carries it for the as-of join: ${wx}`);
  assert.ok(summary.results.some((r) => r.rule === "HW-OAT-1" && r.equip === "BLR-1"), JSON.stringify(summary.results));
});

test("weather off and no outside-air sensor: HW-OAT-1 skips with the reason, as MECH-OAT-1 does", async () => {
  const { seen, logs } = await run([PUMP, WEB], { weather: false });
  assert.ok(!seen.queries.includes("HW-OAT-1"));
  assert.ok(logs.some((l) => /HW-OAT-1 skipped: no outside-air temperature \(weather disabled\)/.test(l)), logs.join("\n"));
});

test("no weather point but a local outside-air sensor: it fills web_oa_t (the local fallback)", async () => {
  const { summary, seen } = await run([PUMP, LOCAL]);
  assert.equal(summary.oat.local, 1);
  assert.ok(seen.queries.includes("HW-OAT-1"));
  const web = vals(seen.input.history, "web_oa_t");
  assert.ok(web.length === 1 && near(web[0], 10), `web_oa_t is the local sensor (50 degF): ${web}`);
});
