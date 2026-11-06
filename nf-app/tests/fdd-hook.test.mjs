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
function fakeHttp(extraPoints = [], fns = {}) {
  const writes = { points: [], data: [] };
  const series = (uuid, fn) => {
    const values = [];
    for (let t = NOW - 24 * 3600e3; t < NOW; t += STEP * 1e3) values.push({ ts: new Date(t).toISOString(), double: fn(t) });
    return { uuid, values };
  };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? MODEL : [...POINTS, ...extraPoints] } };
      if (p === "/api/v1/point/points") { writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/point/data") { writes.data.push(body); return { data: {} }; }
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (p.startsWith("/api/v1/platform/info")) return { data: { resources: [{ memory: { totalBytes: String(1024 ** 3) } }] } };
      if (p.startsWith("/api/v1/point/data?")) {
        assert.match(p, /window=300s&method=AVERAGE/);
        const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
        const f = { "u-FANC": () => 1, "u-FANS": (t) => ((t / 3600e3) % 2 < 1 ? 1 : 0), "u-OAT": () => 55, ...fns };
        return { data: { data: uuids.map((u) => series(u, f[u])) } };
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

test("fdd hook: BACnet export plan keeps instances by name and skips used ones", () => {
  const results = [
    { equip: "AHU-2", rule: "ECON-1", fault: true, value: 12 },
    { equip: "AHU-2", rule: "CMD-1", fault: true, value: 0 },
    { equip: "AHU-1", rule: "FC1", fault: true, value: 5 },
    { equip: "AHU-1", rule: "FAN-RUNTIME-HOURS", fault: false, value: 24 },
    { equip: "VAV-9", rule: "CMD-1", fault: true, value: 0 },
  ];
  const existing = [{ instance: 1000, name: "something else" }, { instance: 1001, name: "OFDD AHU-2 faults" }];
  const plan = hook.bacnetPlan(results, existing, 1000);
  const by = Object.fromEntries(plan.map((p) => [p.equip, p]));
  assert.deepEqual([by["AHU-1"].instance, by["AHU-1"].create, by["AHU-1"].count], [1002, true, 1]);
  assert.deepEqual([by["AHU-2"].instance, by["AHU-2"].create, by["AHU-2"].count], [1001, false, 1]);
  assert.equal(by["AHU-2"].description, "Open-FDD faults: ECON-1");
  assert.deepEqual([by["VAV-9"].instance, by["VAV-9"].count, by["VAV-9"].description], [1003, 0, "Open-FDD: no faults"]);
});

test("fdd hook: history is converted to SI by each point's unit (°F -> °C), declared SI in authorized_series", async () => {
  const extra = [
    pt("u-ZNT", "ZN-T", ["zone", "air", "temp", "sensor"], { equipRef: "AHU-1", class: "zone-air-temp-sensor" }), // no unit
    pt("u-DSP", "DSP", ["duct", "static", "pressure", "sensor"], { equipRef: "AHU-1", class: "discharge-air-pressure-sensor", unit: "inH2O" }),
  ];
  const http = fakeHttp(extra, { "u-ZNT": () => 70, "u-DSP": () => 1.5 });
  const seen = { queries: [] };
  const logs = [];
  const pack = { ...PACK, contract: { history: [...PACK.contract.history, { name: "zone_t", type: "double" }, { name: "duct_static", type: "double" }] },
    rules: { "SV-RANGE": { sql: "-", output_columns: ["equipment_id", "fault_hours"] } } };
  await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config: { dryRun: true }, pack, createEngine: stubEngine(seen), now: NOW });
  const row = seen.input.history[0];
  assert.ok(Math.abs(row.oa_t - (55 - 32) * 5 / 9) < 1e-9, `oa_t ${row.oa_t} is 55 °F = 12.778 °C`);
  assert.ok(Math.abs(row.duct_static - 1.5 * 249.0889) < 1e-6, "1.5 inH2O in Pa");
  assert.equal(row.zone_t, undefined, "temperature point without a unit is skipped, not guessed");
  const unit = Object.fromEntries(seen.input.authorizedSeries.map((a) => [a.role, a.unit]));
  assert.equal(unit.oa_t, "°C");
  assert.equal(unit.duct_static, "Pa");
  assert.equal(unit.zone_t, undefined);
  assert.equal(logs.filter((l) => /zone_t.*no unit/.test(l)).length, 1, "logged once: " + logs.join(" / "));
});

test("siPlan: known units convert, unitless roles pass through, unknown temperature/pressure/flow roles are skipped", () => {
  const roles = {
    oa_t: { uuid: "a", units: "degF" }, sat: { uuid: "b", units: "°C" }, fan_cmd: { uuid: "c", units: "" },
    oa_h: { uuid: "d", units: "%RH" }, zone_flow: { uuid: "e", units: "cfm" }, mat: { uuid: "f", units: "weird" },
  };
  const plan = hook.siPlan(roles, { roles: { oa_t: { name: "outside-air-temp" }, sat: { name: "discharge-air-temp" }, zone_flow: { name: "zone-airflow" }, mat: { name: "mixed-air-temp" } } });
  assert.ok(Math.abs(plan.convert.oa_t(32)) < 1e-12 && Math.abs(plan.convert.oa_t(212) - 100) < 1e-9);
  assert.equal(plan.convert.sat(21), 21);
  assert.ok(Math.abs(plan.convert.zone_flow(100) - 47.19474) < 1e-9);
  assert.equal(plan.convert.fan_cmd, undefined);
  assert.equal(plan.unit.fan_cmd, "");
  assert.deepEqual([...plan.skipped], ["mat"]);
  assert.deepEqual([plan.unit.oa_t, plan.unit.zone_flow, plan.unit.oa_h], ["°C", "L/s", "%"]);
});
