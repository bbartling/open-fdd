// #1631: a COMMAND point is the run proof only when its scale is known: a boolean point, a percent or 0-1 fraction
// unit, or a start/stop (run / enable) command, which is 0/1 even when the model leaves `kind` unset (Grok, #1718). A
// numeric ANALOG command (speed, VFD, position ...) with no unit could be 0-100 or 0-1 and is skipped. The check runs
// inside the resolver's candidate loop, so the next candidate (another own command, then a feeder) still wins.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");
const dir = new URL("../static/", import.meta.url);
const catalog = JSON.parse(fs.readFileSync(new URL("fdd-catalog.json", dir), "utf8"));
const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
for (const f of ["paging.js", "nf.js", "model.js", "fdd.js", "run-proof.js"]) vm.runInContext(fs.readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
const problem = (p) => vm.runInContext("runProofCommandProblem", ctx)(p);

test("runProofCommandProblem: bool, percent, fraction and start/stop commands are usable; an analog number is not", () => {
  assert.equal(problem({ kind: "Bool", units: "", tags: [] }), "");
  assert.equal(problem({ kind: "Number", units: "%", tags: ["speed", "cmd"] }), "");
  assert.equal(problem({ kind: "Number", units: "fraction", tags: [] }), "");
  assert.equal(problem({ kind: "Number", units: "", cls: "discharge-run-cmd", tags: ["discharge", "fan", "run", "cmd"] }), "",
    "an untagged start/stop command (model.js defaults kind to Number) stays usable");
  assert.equal(problem({ kind: "Number", units: "", tags: ["fan", "enable", "cmd"] }), "");
  assert.match(problem({ kind: "Number", units: "", cls: "discharge-fan-speed-cmd", tags: ["fan", "speed", "cmd"] }), /no unit/);
  assert.match(problem({ kind: "Number", units: "", tags: ["fan", "run", "speed", "cmd"] }), /no unit/, "speed wins over run");
  assert.match(problem({ kind: "Number", units: "kW", tags: ["fan", "cmd"] }), /not a percent or 0-1 fraction/);
});

// ---- the resolver: a refused command falls through to the next candidate -----------------------------------------
const rec = (uuid, type, attrs) => ({ uuid, name: attrs.id || uuid, pointType: type, layer: type === "POINT" ? "default" : "model", attrs });
function resolve(records, equipId) {
  ctx.records = records;
  ctx.catalog = catalog;
  ctx.equipId = equipId;
  return JSON.parse(JSON.stringify(vm.runInContext(`(() => {
    const of = (t) => records.filter((x) => x.pointType === t);
    const model = { sites: of("SITE"), equips: of("EQUIPMENT"), devices: [], points: of("POINT").map(toPoint) };
    const r = resolveRunProof(model.equips.find((e) => idOf(e) === equipId), model, catalog);
    return { ...r, point: r.point && r.point.name };
  })()`, ctx)));
}
const SITE = rec("s", "SITE", { id: "site-a", markers: "site" });
const AHU = rec("e1", "EQUIPMENT", { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu" });
const VAV = rec("e2", "EQUIPMENT", { id: "VAV-1", siteRef: "site-a", markers: "equip,vav", airRef: "@AHU-1" });
const pt = (uuid, name, equip, markers, extra = {}) => rec(uuid, "POINT", { siteRef: "site-a", equipRef: equip, dis: name, markers: ["point", "his", ...markers].join(","), ...extra });

test("an untagged start/stop command is the own proof (as on release)", () => {
  const r = resolve([SITE, AHU, pt("c1", "AHU-1 start-stop", "AHU-1", ["discharge", "fan", "run", "cmd"], { class: "discharge-run-cmd" })], "AHU-1");
  assert.equal(r.found, true);
  assert.equal(r.source, "command");
  assert.deepEqual(r.refused, []);
});

test("an analog own command with no unit is skipped and the feeder's status wins", () => {
  const r = resolve([SITE, AHU, VAV,
    pt("s1", "AHU-1 fan status", "AHU-1", ["discharge", "fan", "run", "sensor"], { class: "discharge-run-sensor" }),
    pt("c2", "VAV-1 fan speed", "VAV-1", ["fan", "speed", "cmd"], { class: "run-cmd" })], "VAV-1");
  assert.equal(r.found, true, JSON.stringify(r));
  assert.equal(r.tier, "feeder");
  assert.equal(r.equip, "AHU-1");
  assert.equal(r.refused.length, 1);
  assert.match(r.refused[0].reason, /no unit/);
});

test("with no other candidate, the analog command leaves no proof and says why", () => {
  const r = resolve([SITE, AHU, pt("c3", "AHU-1 fan speed", "AHU-1", ["fan", "speed", "cmd"], { class: "run-cmd" })], "AHU-1");
  assert.equal(r.found, false);
  assert.match(r.refused[0].reason, /analog output with no unit/);
});

test("hook: the skip reason and the log carry the refusal", async () => {
  const STEP = 300, NOW = Date.parse("2026-11-09T15:02:00Z");
  const points = [
    pt("u-SAT", "SAT", "AHU-1", ["discharge", "air", "temp", "sensor"], { class: "discharge-air-temp-sensor", unit: "°C" }),
    pt("u-SATSP", "SAT-SP", "AHU-1", ["discharge", "air", "temp", "sp"], { class: "discharge-air-temp-sp", unit: "°C" }),
    pt("u-FAN", "FAN-SPEED", "AHU-1", ["fan", "speed", "cmd"], { class: "run-cmd" }),
  ];
  const http = {
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? [SITE, AHU] : points } };
      return { data: { success: true } };
    },
    async get(p) {
      const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
      const values = [];
      for (let t = NOW - 24 * 3600e3; t < NOW; t += STEP * 1e3) values.push({ ts: new Date(t).toISOString(), double: 50 });
      return { data: { data: uuids.map((uuid) => ({ uuid, values })) } };
    },
  };
  const engine = () => async () => ({
    kind: "duckdb",
    async load(input) { return input.history.length; },
    async query() { return [{ equipment_id: "AHU-1", fault_hours: null, covered_hours: 0, fault_pct: null }]; },
    async close() {},
  });
  const logs = [];
  const pack = { poll_seconds: STEP, contract: { history: ["equipment_id", "timestamp_utc", "sat", "sat_sp", "fan_cmd", "run_proof"]
    .map((name) => ({ name, type: name === "equipment_id" ? "text" : name === "timestamp_utc" ? "timestamp" : "double" })) },
    rules: { "AHU-SATDEV": { sql: "-", output_columns: ["equipment_id", "fault_hours", "covered_hours", "fault_pct"] } } };
  const summary = await hook.runFdd({ sdk: { http, logEvent: (m) => logs.push(m) }, config: {}, pack, createEngine: engine(), now: NOW });
  assert.equal(summary.no_run_proof, 1, logs.join("\n"));
  assert.ok(logs.some((l) => /run proof candidate AHU-1\/.* \(fan_cmd\) not used: .*analog output with no unit/.test(l)), logs.join("\n"));
});
