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
  pt("u-FANC", "FAN-C", ["discharge", "fan", "run", "cmd"], { equipRef: "AHU-1", class: "discharge-run-cmd", unit: "%" }),
  pt("u-FANS", "FAN-S", ["discharge", "fan", "run", "sensor"], { equipRef: "AHU-1", class: "discharge-run-status" }),
  pt("u-OAT", "OAT", ["outside", "air", "temp", "sensor"], { equipRef: "AHU-1", class: "outside-air-temp-sensor", unit: "°F" }),
];

/** Fake NF: model + default layer queries, resampled history, records writes. */
function fakeHttp(extraPoints = [], fns = {}, opts = {}) {
  const model = opts.model || MODEL, points = opts.points || POINTS;
  const writes = { points: [], data: [] };
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
  assert.match(logs.at(-1), /1 equips, 2 rule runs, 0 errors, 1 with fault time, 2 values written/);
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
  assert.ok(nh.http.writes.points.every((r) => r.attrs.fddStatus === "stale" && /no history/.test(r.attrs.fddReason)));
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
  await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config: { dryRun: true }, pack: PACK, createEngine: stubEngine(seen), now: NOW });
  assert.ok(logs.some((l) => /fan_cmd.*no unit/.test(l)), logs.join(" / "));
  assert.deepEqual(seen.queries, [], "CMD-1 and FAN-RUNTIME-HOURS require fan_cmd: not run, so not assessed (no result written)");
  assert.ok(!seen.input || !seen.input.history.some((r) => "fan_cmd" in r), "no fan_cmd value reaches the engine");
});

test("fdd hook: a status outside 0..1 (enum, 0-100 analog) is rejected, not thresholded", async () => {
  const http = fakeHttp([], { "u-FANS": () => 3 });
  const seen = { queries: [] };
  await hook.runFdd({ sdk: { http, logEvent() {} }, config: { dryRun: true }, pack: PACK, createEngine: stubEngine(seen), now: NOW });
  assert.ok(!seen.input.history.some((r) => "fan_status" in r), "value 3 never reaches the engine as a status");
});
