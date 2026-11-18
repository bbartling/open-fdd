// #1631: a COMMAND point is the run proof only when its scale is known (boolean point, percent or 0-1 fraction unit). A
// numeric command with no unit could be 0-100 or 0-1, and the run proof is judged against a 0-1 threshold, so 1 % speed
// would read as running. Such a command is not used: gated rules are SKIPPED no_run_proof and the reason says why.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const hook = require("../hooks/fdd.js");

test("commandProofProblem: boolean, percent and fraction commands are usable; a unitless number is not", () => {
  assert.equal(hook.commandProofProblem({ kind: "Bool", units: "" }), "");
  assert.equal(hook.commandProofProblem({ kind: "Number", units: "%" }), "");
  assert.equal(hook.commandProofProblem({ kind: "Number", units: "fraction" }), "");
  assert.match(hook.commandProofProblem({ kind: "Number", units: "" }), /no unit/);
  assert.match(hook.commandProofProblem({ kind: "Number", units: "%RH" }), /not a percent or 0-1 fraction/);
  assert.match(hook.commandProofProblem({ kind: "Number", units: "kW" }), /not a percent or 0-1 fraction/);
});

// ---- end to end through runFdd (fake NF, engine stub that reports whether run_proof reached the rules) ----------------
const STEP = 300;
const NOW = Date.parse("2026-11-09T15:02:00Z");
const MODEL = [
  { uuid: "s", name: "site-a", pointType: "SITE", attrs: { id: "site-a", markers: "site" } },
  { uuid: "e", name: "AHU-1", pointType: "EQUIPMENT", attrs: { id: "AHU-1", siteRef: "site-a", markers: "equip,ahu" } },
];
const pt = (uuid, name, markers, extra = {}) => ({
  uuid, name, layer: "default", pointType: "POINT",
  attrs: { siteRef: "site-a", markers: ["point", "his", ...markers].join(","), dis: name, equipRef: "AHU-1", ...extra },
});
const points = (fanUnit) => [
  pt("u-SAT", "SAT", ["discharge", "air", "temp", "sensor"], { class: "discharge-air-temp-sensor", unit: "°C" }),
  pt("u-SATSP", "SAT-SP", ["discharge", "air", "temp", "sp"], { class: "discharge-air-temp-sp", unit: "°C" }),
  pt("u-FANC", "FAN-C", ["discharge", "fan", "run", "cmd"], { class: "discharge-run-cmd", ...(fanUnit ? { unit: fanUnit } : {}) }),
];
const F_COLS = ["equipment_id", "fault_hours", "covered_hours", "fault_pct"];
const PACK = {
  poll_seconds: STEP,
  contract: { history: ["equipment_id", "timestamp_utc", "sat", "sat_sp", "fan_cmd", "run_proof"].map((name) => ({
    name, type: name === "equipment_id" ? "text" : name === "timestamp_utc" ? "timestamp" : "double" })) },
  rules: { "AHU-SATDEV": { sql: "-", output_columns: F_COLS } },
};

function fakeHttp(pts) {
  return {
    async post(p, body) {
      if (p === "/api/v1/point/query") return { data: { points: body.layer === "model" ? MODEL : pts } };
      if (p === "/api/v1/point/points" || p === "/api/v1/points/data") return { data: { success: true } };
      throw new Error("unexpected POST " + p);
    },
    async get(p) {
      const uuids = [...p.matchAll(/uuids=([^&]+)/g)].map((m) => decodeURIComponent(m[1]));
      const values = [];
      for (let t = NOW - 24 * 3600e3; t < NOW; t += STEP * 1e3) values.push({ ts: new Date(t).toISOString(), double: 50 });
      return { data: { data: uuids.map((uuid) => ({ uuid, values })) } };
    },
  };
}

/** The stub answers like the SQL: no run_proof column loaded -> SKIPPED shape (covered 0, fault NULL). */
const engine = () => async () => {
  let hasProof = false;
  return {
    kind: "sqlite",
    async load(input) { hasProof = input.historyColumns.some((c) => c.name === "run_proof") && input.history.some((r) => r.run_proof != null); return input.history.length; },
    async query() {
      return [hasProof ? { equipment_id: "AHU-1", fault_hours: 0, covered_hours: 24, fault_pct: 0 }
        : { equipment_id: "AHU-1", fault_hours: null, covered_hours: 0, fault_pct: null }];
    },
    async close() {},
  };
};

async function run(fanUnit) {
  const logs = [];
  const summary = await hook.runFdd({ sdk: { http: fakeHttp(points(fanUnit)), logEvent: (m) => logs.push(m) }, config: {},
    pack: PACK, createEngine: engine(), now: NOW });
  return { logs, summary };
}

test("a unitless fan command is not the run proof: SKIPPED no_run_proof, and the log says why", async () => {
  const { logs, summary } = await run("");
  assert.equal(summary.no_run_proof, 1, logs.join("\n"));
  assert.ok(logs.some((l) => /AHU-1: run proof .* not used: the command proof has no unit/.test(l)), logs.join("\n"));
});

test("a percent fan command is the run proof: assessed", async () => {
  const { logs, summary } = await run("%");
  assert.equal(summary.no_run_proof, 0, logs.join("\n"));
  assert.ok(!logs.some((l) => /not used/.test(l)));
});
