// FDD hook (nf-app/hooks/fdd.js) without NF: fake HTTP + stub engine.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");

const STEP = 300;
const NOW = Date.parse("2026-11-05T12:02:00Z");
const pt = (uuid, name, markers, extra = {}) => ({
  uuid, name, layer: "default", pointType: "POINT",
  attrs: { siteRef: "site-a", markers: ["point", "his", ...markers].join(","), dis: name, ...extra },
});
const MODEL = [
  { uuid: "s", name: "site-a", pointType: "SITE", attrs: { id: "site-a", markers: "site" } },
  { uuid: "e", name: "AHU-1", pointType: "EQUIPMENT", attrs: { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu" } },
];
const POINTS = [
  pt("u-FANC", "FAN-C", ["discharge", "fan", "run", "cmd"], { equipRef: "AHU-1", class: "discharge-run-cmd" }),
  pt("u-FANS", "FAN-S", ["discharge", "fan", "run", "sensor"], { equipRef: "AHU-1", class: "discharge-run-status" }),
  pt("u-OAT", "OAT", ["outside", "air", "temp", "sensor"], { equipRef: "AHU-1", class: "outside-air-temp-sensor", unit: "°F" }),
];

/** Fake NF: model + default layer queries, resampled history, records writes. */
function fakeHttp() {
  const writes = { points: [], data: [] };
  const series = (uuid, fn) => {
    const values = [];
    for (let t = NOW - 24 * 3600e3; t < NOW; t += STEP * 1e3) values.push({ ts: new Date(t).toISOString(), double: fn(t) });
    return { uuid, values };
  };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? MODEL : POINTS } };
      if (p === "/api/v1/point/points") { writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/point/data") { writes.data.push(body); return { data: {} }; }
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (p.startsWith("/api/v1/platform/info")) return { data: { resources: [{ memory: { totalBytes: String(1024 ** 3) } }] } };
      if (p.startsWith("/api/v1/point/data?")) {
        assert.match(p, /window=300s&method=AVERAGE/);
        const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
        const fns = { "u-FANC": () => 1, "u-FANS": (t) => ((t / 3600e3) % 2 < 1 ? 1 : 0), "u-OAT": () => 55 };
        return { data: { data: uuids.map((u) => series(u, fns[u])) } };
      }
      throw new Error("unexpected GET " + p);
    },
  };
}

const PACK = {
  poll_seconds: STEP,
  contract: { history: [{ name: "equipment_id", type: "text" }, { name: "timestamp_utc", type: "timestamp" },
    { name: "fan_cmd", type: "double" }, { name: "fan_status", type: "double" }, { name: "oa_t", type: "double" }] },
  rules: { "CMD-1": { sql: "-", output_columns: ["equipment_id", "fault_hours", "covered_hours", "fault_pct"] },
    "FAN-RUNTIME-HOURS": { sql: "-", output_columns: ["equipment_id", "fan_runtime_hours", "total_hours"] } },
};

function stubEngine(seen) {
  return async ({ kind }) => ({
    kind,
    async load(input) { seen.input = input; },
    async query(id) {
      seen.queries.push(id);
      return id === "CMD-1"
        ? [{ equipment_id: "AHU-1", fault_hours: 12, covered_hours: 24, fault_pct: 50 }]
        : [{ equipment_id: "AHU-1", fan_runtime_hours: 24, total_hours: 24 }];
    },
    async close() { seen.closed = true; },
  });
}

test("fdd hook: binds, reads the 5-min grid, runs runnable pack rules, writes result points", async () => {
  const http = fakeHttp();
  const seen = { queries: [] };
  const logs = [];
  const summary = await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, pack: PACK, createEngine: stubEngine(seen), now: NOW });
  assert.equal(summary.engine, "sqlite", "1 GiB box → sqlite");
  assert.deepEqual(seen.queries.sort(), ["CMD-1", "FAN-RUNTIME-HOURS"], "only rules in the pack that are runnable");
  assert.equal(seen.input.history.length, 288, "24 h on the 5-min grid");
  // only the roles the runnable rules use are read (OAT is bound but no rule here needs it)
  assert.deepEqual(Object.keys(seen.input.history[0]).sort(), ["equipment_id", "fan_cmd", "fan_status", "ts"]);
  assert.equal(seen.input.history[0].ts % (STEP * 1e3), 0);
  assert.deepEqual(seen.input.authorizedSeries.map((a) => a.role).sort(), ["fan_cmd", "fan_status"]);
  assert.ok(seen.closed);
  // two records (automation + model) per result, same deterministic uuid
  const cmd = http.writes.points.filter((r) => r.uuid === hook.nameUuid("AHU-1:CMD-1"));
  assert.deepEqual(cmd.map((r) => r.layer).sort(), ["automation", "model"]);
  const tags = cmd.find((r) => r.layer === "model").attrs;
  assert.equal(tags.ruleRef, "CMD-1");
  assert.equal(tags.equipRef, "AHU-1");
  assert.equal(tags.siteRef, "site-a");
  assert.match(tags.markers, /\bfault\b/);
  assert.equal(tags.unit, "%");
  const metric = http.writes.points.find((r) => r.layer === "model" && r.attrs.ruleRef === "FAN-RUNTIME-HOURS").attrs;
  assert.match(metric.markers, /\bmetric\b/);
  assert.equal(metric.fddOutput, "fan_runtime_hours");
  assert.deepEqual(http.writes.data.map((d) => d.values[0].real).sort(), [24, 50]);
  assert.equal(http.writes.data[0].values[0].ts, new Date(Math.floor(NOW / 3e5) * 3e5).toISOString());
  assert.match(logs.at(-1), /1 equips, 2 rule runs, 0 errors, 1 with fault time, 2 values written/);
});

test("fdd hook: dryRun writes nothing; uuids are stable v5-style", async () => {
  const http = fakeHttp();
  await hook.runFdd({ sdk: { http, logEvent() {} }, config: { dryRun: true }, pack: PACK, createEngine: stubEngine({ queries: [] }), now: NOW });
  assert.equal(http.writes.points.length + http.writes.data.length, 0);
  assert.equal(hook.nameUuid("AHU-1:CMD-1"), hook.nameUuid("AHU-1:CMD-1"));
  assert.match(hook.nameUuid("x"), /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});
