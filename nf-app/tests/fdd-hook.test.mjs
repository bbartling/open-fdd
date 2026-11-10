// FDD hook (nf-app/hooks/fdd.js) without NF: fake HTTP + stub engine.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");
import { multiSensorEquip } from "./fixtures/multi_sensor_equip.mjs";

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
  pt("u-FANC", "FAN-C", ["discharge", "fan", "run", "cmd"], { equipRef: "AHU-1", class: "discharge-run-cmd", unit: "%" }),
  pt("u-FANS", "FAN-S", ["discharge", "fan", "run", "sensor"], { equipRef: "AHU-1", class: "discharge-run-status" }),
  pt("u-OAT", "OAT", ["outside", "air", "temp", "sensor"], { equipRef: "AHU-1", class: "outside-air-temp-sensor", unit: "°F" }),
];

/** Fake NF: model + default layer queries, resampled history, records writes. */
function fakeHttp(extraPoints = [], fns = {}, opts = {}) {
  const model = opts.model || MODEL, points = opts.points || POINTS;
  const writes = { points: [], data: [], calls: { points: 0, data: 0 } };
  const fail = opts.fail || {};   // { points|data: (attempt, body) => HTTP status or 0 }, simulates NF errors
  const attempts = { points: 0, data: 0 };
  const maybeFail = (kind, body) => {
    attempts[kind]++;
    const st = fail[kind] ? fail[kind](attempts[kind], body) : 0;
    if (st) { const e = new Error("HTTP " + st); e.response = { status: st }; throw e; }
  };
  const series = (uuid, fn) => {
    const values = [];
    for (let t = NOW - 24 * 3600e3; t < NOW; t += STEP * 1e3) values.push({ ts: new Date(t).toISOString(), double: fn(t) });
    return { uuid, values };
  };
  return {
    writes,
    async post(p, body) {
      if (p === "/api/v1/point/query") {
        if (body.layer === "model") return { data: { points: model } };
        const site = body.structuredQuery && body.structuredQuery.field && body.structuredQuery.field.text;
        return { data: { points: [...points, ...extraPoints].filter((x) => !site || x.attrs.siteRef === site) } };
      }
      if (p === "/api/v1/point/points") { writes.calls.points++; maybeFail("points", body); writes.points.push(...body.points); return { data: {} }; }
      if (p === "/api/v1/points/data") {   // AddData (batched): flattened into one {uuid, values} entry per point
        writes.calls.data++; maybeFail("data", body);
        for (const x of body.points) writes.data.push({ uuid: x.uuid, values: x.values });
        return { data: { success: true } };
      }
      if (p === "/api/v1/point/data") throw new Error("per-point data write is no longer used");
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      if (p.startsWith("/api/v1/platform/info")) return { data: { resources: [{ memory: { totalBytes: String(1024 ** 3) } }] } };
      if (p.startsWith("/api/v1/point/data?")) {
        assert.match(p, /window=300s&method=AVERAGE/);
        const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
        const f = { "u-FANC": () => 1, "u-FANS": (t) => ((t / 3600e3) % 2 < 1 ? 1 : 0), "u-OAT": () => 55, ...fns };
        if (opts.noHistory) return { data: { data: uuids.map((u) => ({ uuid: u, values: [] })) } };
        return { data: { data: uuids.map((u) => series(u, f[u] || (() => 1))) } };
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
  const cmd = http.writes.points.filter((r) => r.uuid === hook.resultUuid(hook.resultKey(MODEL[1], "site-a", "AHU-1"), "CMD-1"));
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
  assert.match(logs.at(-1), /1 equips, 2 rule runs, 0 errors, 1 with fault time, 2 values written.*requests: 1 metadata, 1 data/s);
  assert.deepEqual(summary.requests, { metadata: 1, data: 1 });
  assert.deepEqual(summary.status, { ok: 1, fault: 1, "not-assessed": 0, stale: 0 });
  assert.equal(tags.fddStatus, "fault");
  assert.equal(tags.fddCoverageHours, "24");
  assert.equal(tags.fddLastRun, new Date(NOW).toISOString());
});

test("fdd hook: dryRun writes nothing; uuids are stable v5-style", async () => {
  const http = fakeHttp();
  await hook.runFdd({ sdk: { http, logEvent() {} }, config: { dryRun: true }, pack: PACK, createEngine: stubEngine({ queries: [] }), now: NOW });
  assert.equal(http.writes.points.length + http.writes.data.length, 0);
  const k = hook.resultKey(MODEL[1], "site-a", "AHU-1");
  assert.equal(hook.resultUuid(k, "CMD-1"), hook.resultUuid(k, "CMD-1"));
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

// ---- review P1 #1: results are site scoped --------------------------------------------------
const TWO_SITES = [
  { uuid: "sa", name: "site-a", pointType: "SITE", attrs: { id: "site-a", markers: "site" } },
  { uuid: "sb", name: "site-b", pointType: "SITE", attrs: { id: "site-b", markers: "site" } },
  { uuid: "ea", name: "AHU-1", pointType: "EQUIPMENT", attrs: { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu" } },
  { uuid: "eb", name: "AHU-1", pointType: "EQUIPMENT", attrs: { id: "AHU-1", siteRef: "site-b", markers: "equip,ahu" } },
];
const inSite = (site, p) => ({ ...p, uuid: `${p.uuid}-${site}`, attrs: { ...p.attrs, siteRef: site } });

test("fdd results: two sites with the same equip id publish distinct uuids and keep their own siteRef", async () => {
  const pts = [...POINTS.slice(0, 2).map((p) => inSite("site-a", p)), ...POINTS.slice(0, 2).map((p) => inSite("site-b", p))];
  const http = fakeHttp([], {}, { model: TWO_SITES, points: pts });
  const summary = await hook.runFdd({ sdk: { http, logEvent() {} }, pack: PACK, createEngine: stubEngine({ queries: [] }), now: NOW });
  const model = http.writes.points.filter((r) => r.layer === "model");
  const cmd = model.filter((r) => r.attrs.ruleRef === "CMD-1");
  assert.equal(cmd.length, 2);
  assert.equal(new Set(cmd.map((r) => r.uuid)).size, 2, "one result uuid per site");
  assert.deepEqual(cmd.map((r) => r.attrs.siteRef).sort(), ["site-a", "site-b"]);
  assert.equal(new Set(http.writes.points.map((r) => r.name)).size, 2 * 2, "names are site scoped too (2 rules x 2 sites)");
  assert.deepEqual(summary.results.map((r) => r.site).sort(), ["site-a", "site-a", "site-b", "site-b"]);
  // the equip's NF uuid wins when present, and survives a rename of the equip id
  const renamed = hook.resultKey({ ...TWO_SITES[2], attrs: { ...TWO_SITES[2].attrs, id: "AHU-1-renamed" } }, "site-a", "AHU-1-renamed");
  assert.equal(renamed, hook.resultKey(TWO_SITES[2], "site-a", "AHU-1"));
  // without an equip uuid the key falls back to site + equip id, still distinct per site
  const bare = (site) => hook.resultKey({ attrs: { id: "AHU-1" } }, site, "AHU-1");
  assert.notEqual(bare("site-a"), bare("site-b"));
  assert.notEqual(hook.resultUuid(bare("site-a"), "CMD-1"), hook.resultUuid(bare("site-b"), "CMD-1"));
});

test("fdd BACnet plan: one AV per site + equip, name capped at 64 chars", () => {
  const results = [
    { site: "site-a", equip: "AHU-1", rule: "FC1", fault: true, value: 5 },
    { site: "site-b", equip: "AHU-1", rule: "FC2", fault: true, value: 3 },
    { site: "S".repeat(40), equip: "E".repeat(30), rule: "FC1", fault: true, value: 1 },
    { site: "S".repeat(40), equip: "E".repeat(29) + "F", rule: "FC1", fault: true, value: 1 },
  ];
  const plan = hook.bacnetPlan(results, [], 1000);
  const names = plan.map((p) => p.name);
  assert.ok(names.includes("OFDD site-a/AHU-1 faults") && names.includes("OFDD site-b/AHU-1 faults"));
  assert.ok(names.every((n) => n.length <= 64), names.join("|"));
  assert.equal(new Set(names).size, 4, "capped names stay unique");
  assert.equal(new Set(plan.map((p) => p.instance)).size, 4);
});

// ---- review P1 #2: unknown is not healthy ---------------------------------------------------
const F_COLS = ["equipment_id", "fault_hours", "covered_hours", "fault_pct"];
const statusPack = { ...PACK, rules: {
  "CMD-1": { sql: "-", output_columns: F_COLS },
  "FAN-RUNTIME-HOURS": { sql: "-", output_columns: ["equipment_id", "fan_runtime_hours", "total_hours"] },
} };
const resultRec = (ruleId, extra = {}) => ({
  uuid: hook.resultUuid(hook.resultKey(MODEL[1], "site-a", "AHU-1"), ruleId), name: `site-a/AHU-1/${ruleId}`, layer: "model",
  attrs: { dis: `AHU-1 ${ruleId}`, markers: "point,his,fault,fdd", kind: "Number", unit: "%", siteRef: "site-a", equipRef: "AHU-1", ruleRef: ruleId, fddStatus: "fault", ...extra },
});
/** engine whose rule results are scripted: Error = throw, array = rows. */
const scripted = (byRule) => async ({ kind }) => ({ kind, async load() {}, async close() {},
  async query(id) { const v = byRule[id]; if (v instanceof Error) throw v; return v; } });
const FAN_OK = [{ equipment_id: "AHU-1", fan_runtime_hours: 24, total_hours: 24 }];

async function runScripted(byRule, { existing = [], noHistory = false, points, config } = {}) {
  const http = fakeHttp([], {}, { model: [...MODEL, ...existing], noHistory, points });
  const logs = [];
  const summary = await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config, pack: statusPack, createEngine: scripted(byRule), now: NOW });
  const model = (rule) => http.writes.points.filter((r) => r.layer === "model" && r.attrs.ruleRef === rule).at(-1);
  const dataFor = (rule) => http.writes.data.filter((d) => d.uuid === model(rule)?.uuid);
  return { http, summary, logs, model, dataFor };
}

test("fdd status: fault rule with zero coverage is not-assessed, never a healthy 0 or a metric", async () => {
  for (const row of [
    { equipment_id: "AHU-1", fault_pct: null, fault_hours: null, covered_hours: 0 },
    { equipment_id: "AHU-1", fault_pct: null, fault_hours: 0, covered_hours: 0 },
    { equipment_id: "AHU-1", fault_pct: null, fault_hours: 0, covered_hours: null },
  ]) {
    const r = await runScripted({ "CMD-1": [row], "FAN-RUNTIME-HOURS": FAN_OK });
    const a = r.model("CMD-1").attrs;
    assert.equal(a.fddStatus, "not-assessed", JSON.stringify(row));
    assert.match(a.fddReason, /covered|coverage/);
    assert.equal(a.fddLastRun, new Date(NOW).toISOString());
    assert.match(a.markers, /\bfault\b/);
    assert.doesNotMatch(a.markers, /\bmetric\b/);
    assert.equal(a.unit, "%", "still the fault point's unit, not covered_hours' empty unit");
    assert.equal(r.dataFor("CMD-1").length, 0, "no numeric value written");
    assert.equal(r.summary.status["not-assessed"], 1);
  }
});

test("stale cleanup only matches results derived from the current site's equipment key", async () => {
  const siteBEquip = { uuid: "e-site-b", name: "AHU-1", pointType: "EQUIPMENT",
    attrs: { id: "AHU-1", siteRef: "site-b", markers: "equip,ahu" } };
  const siteBKey = hook.resultKey(siteBEquip, "site-b", "AHU-1");
  const siteBResult = { uuid: hook.resultUuid(siteBKey, "CMD-1"), name: "site-b/AHU-1/CMD-1", layer: "model",
    attrs: { markers: "point,his,fault,fdd", siteRef: "site-b", equipRef: "AHU-1", ruleRef: "CMD-1", fddStatus: "fault" } };
  const retiredSensor = { uuid: hook.sensorResultUuid(hook.resultKey(MODEL[1], "site-a", "AHU-1"), "CMD-1", "fixture-retired"),
    name: "fixture-retired result", layer: "model",
    attrs: { ...siteBResult.attrs, siteRef: "site-a", sensorRef: "fixture-retired" } };
  // The foreign result is present in the model layer, but the current run resolves only site-a equipment.
  const http = fakeHttp([], {}, { model: [...MODEL, siteBResult, retiredSensor] });
  const summary = await hook.runFdd({ sdk: { http }, pack: statusPack, createEngine: stubEngine({ queries: [] }), now: NOW });
  assert.equal(http.writes.points.some((point) => point.uuid === siteBResult.uuid), false,
    "matching equipRef alone must not stale another site's result");
  assert.equal(http.writes.data.some((point) => point.uuid === siteBResult.uuid), false);
  assert.equal(http.writes.points.find((point) => point.uuid === retiredSensor.uuid)?.attrs.fddStatus, "stale");
  assert.equal(summary.sensor_results.stale, 1);
  assert.equal(summary.status.stale, 0, "sensor results do not count as equipment summaries");
});

test("fdd status: covered fault rule is ok at 0 and fault above 0, with coverage hours", async () => {
  const ok = await runScripted({ "CMD-1": [{ equipment_id: "AHU-1", fault_pct: 0, fault_hours: 0, covered_hours: 23.5 }], "FAN-RUNTIME-HOURS": FAN_OK });
  assert.equal(ok.model("CMD-1").attrs.fddStatus, "ok");
  assert.equal(ok.model("CMD-1").attrs.fddCoverageHours, "23.5");
  assert.deepEqual(ok.dataFor("CMD-1").map((d) => d.values[0].real), [0], "a covered healthy 0 is published");
  const bad = await runScripted({ "CMD-1": [{ equipment_id: "AHU-1", fault_pct: 12.5, fault_hours: 3, covered_hours: 24 }], "FAN-RUNTIME-HOURS": FAN_OK });
  assert.equal(bad.model("CMD-1").attrs.fddStatus, "fault");
  assert.deepEqual(bad.dataFor("CMD-1").map((d) => d.values[0].real), [12.5]);
});

test("fdd status: metric rules publish their first declared metric column, zero included", async () => {
  const r = await runScripted({ "CMD-1": [{ equipment_id: "AHU-1", fault_pct: 0, fault_hours: 0, covered_hours: 24 }],
    "FAN-RUNTIME-HOURS": [{ equipment_id: "AHU-1", fan_runtime_hours: 0, total_hours: 24 }] });
  const m = r.model("FAN-RUNTIME-HOURS").attrs;
  assert.equal(m.fddStatus, "ok");
  assert.equal(m.fddOutput, "fan_runtime_hours");
  assert.match(m.markers, /\bmetric\b/);
  assert.deepEqual(r.dataFor("FAN-RUNTIME-HOURS").map((d) => d.values[0].real), [0], "not total_hours, and 0 is fine");
});

test("fdd status: query error marks the existing point stale, still writes the rest, then the hook throws", async () => {
  const existing = [resultRec("CMD-1")];
  const http = fakeHttp([], {}, { model: [...MODEL, ...existing] });
  const boom = () => scripted({ "CMD-1": new Error("boom"), "FAN-RUNTIME-HOURS": FAN_OK });
  // runFdd returns the summary...
  const summary = await hook.runFdd({ sdk: { http, logEvent() {} }, pack: statusPack, createEngine: boom(), now: NOW });
  assert.equal(summary.errors, 1);
  assert.deepEqual(summary.status, { ok: 1, fault: 0, "not-assessed": 0, stale: 1 });
  const stale = http.writes.points.find((r) => r.attrs.ruleRef === "CMD-1");
  assert.equal(stale.attrs.fddStatus, "stale");
  assert.match(stale.attrs.fddReason, /boom/);
  assert.equal(stale.attrs.equipRef, "AHU-1", "rest of the record kept");
  assert.match(stale.attrs.markers, /\bfault\b/);
  assert.equal(http.writes.data.some((d) => d.uuid === stale.uuid), false, "no fresh value for a stale point");
  assert.equal(http.writes.data.length, 1, "the healthy rule was still written");
  // ...and the hook entry point fails the run so NF does not mark it successful
  const http2 = fakeHttp([], {}, { model: [...MODEL, ...existing] });
  await assert.rejects(hook({ sdk: { http: http2, logEvent() {} }, config: {}, pack: statusPack, createEngine: boom(), now: NOW }),
    /1 error.*ok 1.*stale 1/s);
  assert.equal(http2.writes.data.length, 1, "everything it could was written before throwing");
});

test("fdd status: missing roles and no history mark existing results stale (and write no values)", async () => {
  const existing = [resultRec("CMD-1"), resultRec("FAN-RUNTIME-HOURS", { markers: "point,his,metric,fdd", unit: "", fddStatus: "ok" })];
  const none = { "CMD-1": [], "FAN-RUNTIME-HOURS": [] };
  // roles gone: the fan points no longer exist on the equip
  const miss = await runScripted(none, { existing, points: [POINTS[2]] });
  assert.deepEqual(miss.summary.status, { ok: 0, fault: 0, "not-assessed": 0, stale: 2 });
  assert.ok(miss.http.writes.points.every((r) => r.attrs.fddStatus === "stale" && /missing|bound|input/i.test(r.attrs.fddReason)));
  assert.equal(miss.http.writes.data.length, 0);
  assert.equal(miss.summary.errors, 0);
  // history gone
  const nh = await runScripted(none, { existing, noHistory: true });
  assert.deepEqual(nh.summary.status, { ok: 0, fault: 0, "not-assessed": 0, stale: 2 });
  assert.ok(nh.http.writes.points.every((r) => r.attrs.fddStatus === "stale" && /no input data in window/.test(r.attrs.fddReason)));
  assert.equal(nh.http.writes.data.length, 0);
  // a point never published before is not invented as stale
  const fresh = await runScripted(none, { noHistory: true });
  assert.equal(fresh.http.writes.points.length, 0);
  // dryRun writes nothing, stale included
  const dry = await runScripted(none, { existing, noHistory: true, config: { dryRun: true } });
  assert.equal(dry.http.writes.points.length, 0);
});

test("fdd status: a rule returning no row is not-assessed", async () => {
  const r = await runScripted({ "CMD-1": [], "FAN-RUNTIME-HOURS": FAN_OK });
  assert.equal(r.model("CMD-1").attrs.fddStatus, "not-assessed");
  assert.equal(r.dataFor("CMD-1").length, 0);
});

test("sweep result keeps per-series rows and summarizes by maximum hours", () => {
  const rule = { output_columns: ["equipment_id", "series_id", "sensor_role", "fault_hours", "covered_hours"] };
  const rows = [
    { equipment_id: "fixture", series_id: "sat-a", sensor_role: "sat", fault_hours: 2, covered_hours: 22 },
    { equipment_id: "fixture", series_id: "rat-a", sensor_role: "rat", fault_hours: 3, covered_hours: 20 },
    { equipment_id: "other", series_id: "sat-x", sensor_role: "sat", fault_hours: 4, covered_hours: 24 },
    { equipment_id: "fixture", series_id: "mat-a", sensor_role: "mat", fault_hours: 0, covered_hours: 23 },
  ];
  const summary = hook.equipmentResult(rule, rows, "fixture");
  assert.equal(summary.fault_hours, 3);
  assert.equal(summary.covered_hours, 23);
  assert.deepEqual(summary.sensor_fault_hours, {
    "sat-a": { role: "sat", name: "sat-a", hours: 2, status: "fault" },
    "rat-a": { role: "rat", name: "rat-a", hours: 3, status: "fault" },
    "mat-a": { role: "mat", name: "mat-a", hours: 0, status: "ok" },
  });
  assert.equal(hook.equipmentResult(rule, rows, "missing"), undefined);
});

test("the FDD hook writes stable per-sensor results, timelines identity attrs, and the equipment max summary", async () => {
  const http = fakeHttp([], {}, { model: [...multiSensorEquip.sites, ...multiSensorEquip.equips], points: multiSensorEquip.points });
  const pack = {
    ...PACK,
    rules: { "SV-STALE": { sql: "-", timeline_sql: "-", output_columns: ["equipment_id", "series_id", "sensor_role", "fault_hours", "covered_hours"] } },
  };
  let missingSeries;
  const createEngine = async ({ kind }) => ({
    kind,
    async load(input) { assert.ok(input.sensorSeries.length >= 5); assert.ok(input.sensorHistory.length > 0); missingSeries = input.sensorSeries[0].uuid; },
    async query() {
      return [
        ...multiSensorEquip.points.filter((p) => p.attrs.equipRef === "AHU-A").map((p, i) => ({
          equipment_id: "AHU-A", series_id: p.uuid,
          sensor_role: p.attrs.class === "discharge-air-temp-sensor" ? "sat" : p.attrs.class === "mixed-air-temp-sensor" ? "mat" : p.attrs.class === "outside-air-temp-sensor" ? "oa_t" : p.attrs.class === "return-air-temp-sensor" ? "rat" : "duct_static",
          fault_hours: i === 1 ? 2 : 0, covered_hours: 24,
        })).filter((row) => row.series_id !== missingSeries),
      ];
    },
    async timeline() { return multiSensorEquip.points.filter((p) => p.attrs.equipRef === "AHU-A").map((p, i) => ({
      equipment_id: "AHU-A", series_id: p.uuid, sensor_role: i < 2 ? "sat" : "mat", ts_epoch: NOW / 1000,
      confirmed: i === 1 ? 1 : 0, held_seconds: 300,
    })); },
    async close() {},
  });
  const summary = await hook.runFdd({ sdk: { http }, pack, createEngine, now: NOW });
  assert.equal(summary.results.length, 1, "NF run summary retains one equipment result per rule");
  assert.equal(summary.sensor_results.total, 5, "only stale-assessable sensors get result points");
  assert.deepEqual(summary.status, { ok: 0, fault: 1, "not-assessed": 0, stale: 0 });
  const equipKey = hook.resultKey(multiSensorEquip.equips[0], "site-fixture", "AHU-A");
  const uuid = hook.resultUuid(equipKey, "SV-STALE");
  const summaryPoint = http.writes.points.find((row) => row.uuid === uuid && row.layer === "model");
  const mapping = JSON.parse(summaryPoint.attrs.fddSensorFaultHours);
  assert.deepEqual(Object.keys(mapping).sort(), multiSensorEquip.points.slice(0, 5).map((p) => p.uuid).sort());
  assert.equal(summaryPoint.attrs.fddSummary, "equip");
  assert.equal(summaryPoint.attrs.fddOutputSince, new Date(Math.floor(NOW / (STEP * 1000)) * STEP * 1000).toISOString());
  assert.equal(http.writes.data.find((row) => row.uuid === uuid).values[0].real, 2);
  const sensorPoints = http.writes.points.filter((row) => row.layer === "model" && row.attrs.ruleRef === "SV-STALE" && row.attrs.fddSummary === "sensor");
  assert.equal(sensorPoints.length, 5);
  assert.ok(sensorPoints.every((p) => p.attrs.roleRef !== "duct_static" && p.attrs.roleRef !== "zone_flow"));
  assert.ok(sensorPoints.every((p) => p.attrs.sensorRef && p.attrs.roleRef
    && p.attrs.fddCoverageHours === (p.attrs.fddStatus === "not-assessed" ? "0" : "24")));
  assert.ok(sensorPoints.every((p) => hook.OFDD_RESULT_ATTRS.every((key) => Object.hasOwn(p.attrs, key))));
  assert.equal(summary.roles_skipped_by_unit_total, 0);
  assert.ok(JSON.parse(summaryPoint.attrs.fddSensorFaultHours)["sensor-sat-1"].name);
  assert.ok(http.writes.data.some((row) => sensorPoints.some((p) => p.uuid === row.uuid)));
  const timelines = http.writes.points.filter((p) => p.layer === "model" && /(^|,)fault_timeline(,|$)/.test(p.attrs.markers));
  const timelinesByUuid = new Map(timelines.map((p) => [p.uuid, p]));
  assert.equal([...timelinesByUuid.values()].filter((p) => p.attrs.sensorRef).length, 5);
  assert.equal([...timelinesByUuid.values()].filter((p) => !p.attrs.sensorRef).length, 1, "equipment timeline remains the any-sensor summary");
  assert.ok([...timelinesByUuid.values()].filter((p) => p.attrs.sensorRef).every((p) => p.attrs.fddTimelineOf === sensorPoints.find((s) => s.attrs.sensorRef === p.attrs.sensorRef).uuid));
  const missing = sensorPoints.find((p) => p.attrs.sensorRef === missingSeries);
  assert.equal(missing.attrs.fddStatus, "not-assessed");
  assert.equal(missing.attrs.fddCoverageHours, "0");
  assert.equal(http.writes.data.some((row) => row.uuid === missing.uuid), false);
  const nextHttp = fakeHttp([], {}, { model: [...multiSensorEquip.sites, ...multiSensorEquip.equips, ...http.writes.points.filter((p) => p.layer === "model")], points: multiSensorEquip.points });
  await hook.runFdd({ sdk: { http: nextHttp }, pack, createEngine, now: NOW + STEP * 1000 });
  const nextUuids = nextHttp.writes.points.filter((p) => p.layer === "model" && p.attrs.fddSummary === "sensor").map((p) => p.uuid).sort();
  assert.deepEqual(nextUuids, sensorPoints.map((p) => p.uuid).sort());
});

test("every sweep publishes only its canonical assessable sensor roles", async () => {
  const http = fakeHttp([], {}, { model: [...multiSensorEquip.sites, multiSensorEquip.equips[0]],
    points: multiSensorEquip.points.filter((p) => p.attrs.equipRef === "AHU-A") });
  const sweepIds = ["SV-RATE", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE"];
  const pack = { ...PACK, rules: Object.fromEntries(sweepIds.map((id) => [id, {
    sql: "-", output_columns: ["equipment_id", "series_id", "sensor_role", "fault_hours", "covered_hours"],
  }])) };
  const role = (p) => ({
    "discharge-air-temp-sensor": "sat", "mixed-air-temp-sensor": "mat", "outside-air-temp-sensor": "oa_t",
    "return-air-temp-sensor": "rat", "discharge-air-pressure-sensor": "duct_static",
  })[p.attrs.class];
  const createEngine = async () => ({
    kind: "sqlite", async load(input) { assert.equal(input.sensorSeries.length, 6); }, async close() {},
    async query(ruleId) {
      const all = multiSensorEquip.points.filter((p) => p.attrs.equipRef === "AHU-A");
      const supported = ruleId === "SV-RANGE" ? all : all.filter((p) => p.attrs.class !== "discharge-air-pressure-sensor");
      return supported.map((p) => ({ equipment_id: "AHU-A", series_id: p.uuid, sensor_role: role(p), fault_hours: 0, covered_hours: 24 }));
    },
  });
  const summary = await hook.runFdd({ sdk: { http }, pack, createEngine, now: NOW });
  assert.equal(summary.results.length, 5);
  assert.equal(summary.sensor_results.total, 27);
  assert.deepEqual(summary.status, { ok: 5, fault: 0, "not-assessed": 0, stale: 0 });
  for (const ruleId of sweepIds) {
    const rows = http.writes.points.filter((p) => p.layer === "model" && p.attrs.ruleRef === ruleId && p.attrs.fddSummary === "sensor");
    const ductExpected = ruleId === "SV-RANGE" || ruleId === "SV-SPIKE";
    assert.equal(rows.length, ductExpected ? 6 : 5, `${ruleId} should include its assessable sensor points`);
    const duct = rows.find((p) => p.attrs.sensorRef === "sensor-static-1");
    assert.equal(Boolean(duct), ductExpected);
    assert.ok(rows.every((p) => p.attrs.roleRef !== "zone_flow"));
  }
});

test("result attrs always clear inapplicable coverage and keep or reset the mixed-unit boundary", async () => {
  const key = hook.resultKey(MODEL[1], "site-a", "AHU-1");
  const sameOutput = resultRec("CMD-1", { fddOutput: "fault_pct", fddOutputSince: "2026-11-04T12:00:00.000Z", fddCoverageHours: "24" });
  const kept = await runScripted({ "CMD-1": [{ equipment_id: "AHU-1", fault_pct: null, fault_hours: null, covered_hours: 0 }], "FAN-RUNTIME-HOURS": FAN_OK }, { existing: [sameOutput] });
  const record = kept.model("CMD-1");
  assert.equal(record.attrs.fddCoverageHours, "0");
  assert.equal(record.attrs.fddOutputSince, "2026-11-04T12:00:00.000Z");
  assert.ok(hook.OFDD_RESULT_ATTRS.every((name) => Object.hasOwn(record.attrs, name)));
  assert.equal(record.attrs.sensorRef, "");
  assert.equal(record.attrs.fddSensorFaultHours, "");
  assert.equal(hook.resultUuid(key, "CMD-1"), record.uuid);
  const metricOld = resultRec("FAN-RUNTIME-HOURS", { markers: "point,his,metric,fdd", unit: "", fddOutput: "fan_runtime_hours",
    fddCoverageHours: "24", fddSensorFaultHours: "{\"obsolete\":1}" });
  const metricRun = await runScripted({ "CMD-1": FAN_OK, "FAN-RUNTIME-HOURS": FAN_OK }, { existing: [metricOld] });
  const metric = metricRun.model("FAN-RUNTIME-HOURS");
  assert.equal(metric.attrs.fddCoverageHours, "");
  assert.equal(metric.attrs.fddSensorFaultHours, "");
  assert.ok(hook.OFDD_RESULT_ATTRS.every((name) => Object.hasOwn(metric.attrs, name)));
});

test("fdd status: resultValue contract", () => {
  const f = { output_columns: F_COLS };
  assert.equal(hook.resultValue(f, { fault_pct: null, fault_hours: null, covered_hours: 0 }).status, "not-assessed");
  assert.equal(hook.resultValue(f, { fault_pct: 0, fault_hours: 0, covered_hours: 0 }).status, "not-assessed");
  assert.equal(hook.resultValue(f, { fault_pct: 0, fault_hours: 0, covered_hours: 2 }).status, "ok");
  assert.equal(hook.resultValue(f, { fault_pct: 1, fault_hours: 1, covered_hours: 2 }).status, "fault");
  assert.equal(hook.resultValue({ output_columns: ["equipment_id", "fault_hours", "covered_hours"] }, { fault_hours: 2, covered_hours: 4 }).unit, "h");
  const m = hook.resultValue({ output_columns: ["equipment_id", "x", "y"] }, { x: 0, y: 5 });
  assert.deepEqual([m.status, m.value, m.fault, m.column], ["ok", 0, false, "x"]);
});

// ---- issue #1541: one declared scale per column --------------------------------------------------------
test("fdd hook: a declared-% command reaches the engine as a fraction (1 % -> 0.01), a status stays 0/1", async () => {
  const http = fakeHttp();
  const seen = { queries: [] };
  await hook.runFdd({ sdk: { http, logEvent() {} }, config: { dryRun: true }, pack: PACK, createEngine: stubEngine(seen), now: NOW });
  assert.equal(seen.input.history[0].fan_cmd, 0.01, "u-FANC is 1 and declares %");
  assert.ok(seen.input.history.every((r) => r.fan_status === 0 || r.fan_status === 1));
  const unit = Object.fromEntries(seen.input.authorizedSeries.map((a) => [a.role, a.unit]));
  assert.deepEqual([unit.fan_cmd, unit.fan_status], ["fraction", "bool"]);
});

test("fdd hook: a UNITLESS command point is skipped and logged; rules that need it are not assessed", async () => {
  const points = POINTS.map((p) => (p.uuid === "u-FANC" ? { ...p, attrs: { ...p.attrs, unit: "" } } : p));
  const http = fakeHttp([], {}, { points });
  const seen = { queries: [] };
  const logs = [];
  const summary = await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config: { dryRun: true }, pack: PACK, createEngine: stubEngine(seen), now: NOW });
  assert.ok(logs.some((l) => /fan_cmd.*no unit/.test(l)), logs.join(" / "));
  assert.deepEqual(summary.roles_skipped_by_unit, { fan_cmd: 1 });
  assert.ok(logs.some((l) => /roles skipped by unit: 1 \(fan_cmd 1\)/.test(l)), logs.join(" / "));
  assert.deepEqual(seen.queries, [], "CMD-1 and FAN-RUNTIME-HOURS require fan_cmd: not run, so not assessed (no result written)");
  assert.ok(!seen.input || !seen.input.history.some((r) => "fan_cmd" in r), "no fan_cmd value reaches the engine");
});

test("fdd hook: a status outside 0..1 (enum, 0-100 analog) is rejected, not thresholded", async () => {
  const http = fakeHttp([], { "u-FANS": () => 3 });
  const seen = { queries: [] };
  await hook.runFdd({ sdk: { http, logEvent() {} }, config: { dryRun: true }, pack: PACK, createEngine: stubEngine(seen), now: NOW });
  assert.ok(!seen.input.history.some((r) => "fan_status" in r), "value 3 never reaches the engine as a status");
});

// ---- review F09: batched writes -------------------------------------------------------------------------
// N equips, each with the two pack rules (CMD-1, FAN-RUNTIME-HOURS); writeRetryMs 0 keeps retries instant.
const bigModel = (n) => [MODEL[0], ...Array.from({ length: n }, (_, i) => ({ uuid: `e${i}`, name: `AHU-${i}`,
  pointType: "EQUIPMENT", attrs: { id: `AHU-${i}`, siteRef: "site-a", markers: "equip,ahu" } }))];
const inEquip = (p, i) => ({ ...p, uuid: `${p.uuid}-${i}`, attrs: { ...p.attrs, equipRef: `AHU-${i}` } });
const bigPoints = (n) => Array.from({ length: n }, (_, i) => POINTS.slice(0, 2).map((p) => inEquip(p, i))).flat();
const BIG_ENGINE = () => scripted({ "CMD-1": [{ equipment_id: "AHU-0", fault_pct: 5, fault_hours: 1, covered_hours: 24 }], "FAN-RUNTIME-HOURS": FAN_OK });
async function runBig(n, opts = {}) {
  const http = fakeHttp([], {}, { model: bigModel(n), points: bigPoints(n), ...opts });
  const logs = [];
  const summary = await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config: { writeRetryMs: 0, ...(opts.config || {}) },
    pack: statusPack, createEngine: BIG_ENGINE(), now: NOW });
  return { http, summary, logs };
}

test("fdd writes: metadata for all equips is ONE UpdatePoints call, values ONE AddData call", async () => {
  const { http, summary } = await runBig(10);
  assert.equal(summary.equips, 10);
  assert.equal(http.writes.calls.points, 1, "one metadata call for 10 equips");
  assert.equal(http.writes.points.length, 10 * 2 * 2, "10 equips x 2 rules x (automation + model)");
  assert.equal(http.writes.calls.data, 1);
  assert.equal(http.writes.data.length, 20);
  assert.equal(summary.written, 20);
  assert.deepEqual(summary.requests, { metadata: 1, data: 1 });
  assert.equal(summary.errors, 0);
});

test("fdd writes: chunked by record count (500 per UpdatePoints call, 500 points per AddData call)", async () => {
  const { http, summary } = await runBig(150);   // 150 x 2 rules x 2 records = 600 records, 300 values
  assert.equal(http.writes.points.length, 600);
  assert.equal(http.writes.calls.points, 2, "600 records -> 500 + 100");
  assert.equal(http.writes.calls.data, 1, "300 points fit one AddData call");
  assert.deepEqual(summary.requests, { metadata: 2, data: 1 });
  assert.equal(summary.written, 300);
  // and by payload size
  const big = Array.from({ length: 10 }, (_, i) => ({ i, pad: "x".repeat(100) }));
  assert.equal(hook.chunkBySize(big, 500, 450).length, 4, "3 items of ~117 bytes per 450-byte chunk");
  assert.deepEqual(hook.chunkBySize([1, 2, 3], 2, 1e6).map((c) => c.length), [2, 1]);
});

test("fdd writes: 429 and 503 are retried (max 3 attempts), 400 is not", async () => {
  const flaky = await runBig(2, { fail: { points: (n) => (n < 3 ? 429 : 0), data: (n) => (n === 1 ? 503 : 0) } });
  assert.equal(flaky.summary.errors, 0);
  assert.deepEqual(flaky.summary.requests, { metadata: 3, data: 2 }, "every attempt is counted");
  assert.equal(flaky.http.writes.points.length, 8);
  assert.equal(flaky.summary.written, 4);

  const never = await runBig(2, { fail: { points: () => 503 } });
  assert.equal(never.summary.requests.metadata, 3, "gives up after 3 attempts");
  assert.equal(never.summary.errors, 4, "one error per point of the failed call (2 equips x 2 rules)");
  assert.equal(never.http.writes.points.length, 0);
  assert.equal(never.summary.written, 0, "no values for points whose metadata failed");
  assert.equal(never.summary.requests.data, 0);

  const bad = await runBig(2, { fail: { points: () => 400 } });
  assert.equal(bad.summary.requests.metadata, 1, "400 is not retried");
  assert.equal(bad.summary.errors, 4);
  const bad2 = await runBig(2, { fail: { data: () => 400 } });
  assert.equal(bad2.summary.requests.data, 1, "400 is not retried");
  assert.equal(bad2.summary.errors, 4, "4 value points failed");
  assert.equal(bad2.http.writes.points.length, 8, "metadata was still written");
});

test("fdd writes: a partial failure counts per point, keeps going, and the hook still throws at the end", async () => {
  // 150 equips -> 2 metadata chunks (500 + 100 records); the second one fails with 400 = 50 points
  const opts = { fail: { points: (n) => (n === 2 ? 400 : 0) } };
  const { http, summary, logs } = await runBig(150, opts);
  assert.equal(http.writes.points.length, 500);
  assert.equal(summary.errors, 50, "one error per point whose metadata failed");
  assert.equal(summary.written, 300 - 50, "values of the failed points are skipped, the rest are written");
  assert.ok(logs.some((l) => /50 points not written/.test(l)));
  const http2 = fakeHttp([], {}, { model: bigModel(150), points: bigPoints(150), ...opts });
  await assert.rejects(hook({ sdk: { http: http2, logEvent() {} }, config: { writeRetryMs: 0 }, pack: statusPack,
    createEngine: BIG_ENGINE(), now: NOW }), /50 errors/);
  assert.equal(http2.writes.data.length, 250, "everything it could was written before throwing");
});

test("fdd writes: stale flags ride in the same metadata batch", async () => {
  const http = fakeHttp([], {}, { model: [...MODEL, resultRec("CMD-1")] });
  const boom = scripted({ "CMD-1": new Error("boom"), "FAN-RUNTIME-HOURS": FAN_OK });
  const summary = await hook.runFdd({ sdk: { http, logEvent() {} }, pack: statusPack, createEngine: boom, now: NOW });
  assert.equal(http.writes.calls.points, 1, "stale + fresh records in one call");
  assert.deepEqual(summary.requests, { metadata: 1, data: 1 });
});

test("fdd writes: dryRun sends no write requests", async () => {
  const { http, summary } = await runBig(3, { config: { dryRun: true } });
  assert.deepEqual(summary.requests, { metadata: 0, data: 0 });
  assert.equal(http.writes.calls.points + http.writes.calls.data, 0);
});
