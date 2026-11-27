// #1631: the sensor sweeps take the run proof of a sample from the latest proof row at or before it, held for at most
// MAX_GAP_HOURS. Proof that is absent or older is UNKNOWN and cannot create a fault (it used to count as energized).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const pgPack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const START = Date.UTC(2026, 0, 1);
const MIN = 60_000;
const GATED = ["SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-RATE"];
const near = (a, b) => a != null && Math.abs(a - b) <= 1e-6;

/** One day; proof rows every 5 min at :00/:05 (proof(minute) -> operating_status, undefined = no row); SAT out of range and
 *  stuck, sampled at `offset` seconds past each 5-minute grid point. */
function input({ proof, offset = 60, days = 1, value = () => 90 }) {
  const history = [], sensorHistory = [];
  for (let m = 0; m < days * 1440; m += 5) {
    const p = proof(m);
    if (p !== undefined) history.push({ equipment_id: "eq-1", ts: START + m * MIN, operating_status: p });
    sensorHistory.push({ equipment_id: "eq-1", series_id: "discharge_air_temperature-1", sensor_role: "discharge_air_temperature", unit: "°C",
      ts: START + m * MIN + offset * 1000, value: value(m) });
  }
  return { historyColumns: [{ name: "operating_status", type: "double" }], history, weather: [], sensorHistory };
}

async function run(inp, rules = ["SV-RANGE"]) {
  const out = {};
  for (const [kind, pack] of [["duckdb", pgPack]]) {
    const eng = await createEngine({ kind, pack });
    try {
      await eng.load(inp);
      out[kind] = {};
      for (const r of rules) {
        const row = (await eng.query(r)).find((x) => x.series_id === "discharge_air_temperature-1");
        const tl = (await eng.timeline(r)).filter((x) => x.series_id === "discharge_air_temperature-1" && x.confirmed === 1);
        out[kind][r] = { ...row, confirmed_rows: tl.length, timeline_hours: tl.reduce((s, x) => s + x.held_seconds, 0) / 3600 };
      }
    } finally {
      await eng.close();
    }
  }
  return out.duckdb;
}

test("the #1631 repro: proof OFF all day, sensor 60 s off the proof grid -> no fault (was 23.9 h)", async () => {
  const r = (await run(input({ proof: () => 0 }), GATED));
  for (const rule of GATED) {
    assert.equal(r[rule].fault_hours, 0, `${rule}: ${r[rule].fault_hours}`);
    assert.equal(r[rule].confirmed_rows, 0, `${rule}: timeline`);
  }
  assert.ok(r["SV-RANGE"].covered_hours > 23.9, "sensor-data coverage is unchanged");
});

test("proof ON with the same offset still faults: the latest proof at or before the sample holds", async () => {
  const r = await run(input({ proof: () => 1 }));
  assert.ok(r["SV-RANGE"].fault_hours > 23.8, `${r["SV-RANGE"].fault_hours}`);
  assert.ok(near(r["SV-RANGE"].fault_hours, r["SV-RANGE"].timeline_hours), "summary and timeline agree");
});

test("proof older than MAX_GAP_HOURS is unknown and cannot fault; fresh proof resumes", async () => {
  // proof ON for 0..6 h, no proof rows 6..12 h, proof ON again 12..24 h
  const r = await run(input({ proof: (m) => (m >= 360 && m < 720 ? undefined : 1) }));
  // 6 h of ON + the 1 h hold of the last proof row + 12 h of ON (each minus the confirm delay at the start of a streak)
  assert.ok(r["SV-RANGE"].fault_hours < 24 - 4.9, `unknown proof must not fault: ${r["SV-RANGE"].fault_hours}`);
  assert.ok(r["SV-RANGE"].fault_hours > 18, `${r["SV-RANGE"].fault_hours}`);
});

test("a NULL proof row is unknown, not ON", async () => {
  const r = await run(input({ proof: () => null }));
  assert.equal(r["SV-RANGE"].fault_hours, null, "all proof NULL -> no_run_proof, SKIPPED");
});

test("sensor history but no history rows: no proof (SKIPPED with the gate on, assessed with it off)", async () => {
  const inp = input({ proof: () => undefined });
  const r = await run(inp);
  assert.equal(r["SV-RANGE"].fault_hours, null);
  assert.equal(r["SV-RANGE"].covered_hours, 0);
});
