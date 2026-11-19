// #1673: SV-STALE is missing data (gaps, expected series with no sample), independent of the motor; SV-FLATLINE is a
// stuck value among present samples; SV-RANGE / SV-SPIKE / SV-FLATLINE no longer score gaps. Both engines, same rows.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const pgPack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const litePack = JSON.parse(readFileSync(new URL("../rules/pack-sqlite.json", import.meta.url), "utf8"));
const START = Date.UTC(2026, 0, 1);
const MIN = 60_000;
const near = (a, b) => a != null && Math.abs(a - b) <= 1e-6;
const SWEEPS = ["SV-STALE", "SV-FLATLINE", "SV-RANGE", "SV-SPIKE"];

async function both(input, rules = SWEEPS) {
  const out = {};
  for (const [kind, pack] of [["pglite", pgPack], ["sqlite", litePack]]) {
    const eng = await createEngine({ kind, pack });
    try {
      await eng.load(input);
      out[kind] = {};
      for (const r of rules) out[kind][r] = Object.fromEntries((await eng.query(r)).map((row) => [row.series_id, row]));
    } finally {
      await eng.close();
    }
  }
  for (const r of rules) {
    for (const id of new Set([...Object.keys(out.pglite[r]), ...Object.keys(out.sqlite[r])])) {
      const a = out.pglite[r][id], b = out.sqlite[r][id];
      assert.ok(a && b, `${r}/${id}: missing on one engine`);
      for (const k of ["fault_hours", "covered_hours"]) {
        assert.ok(a[k] === b[k] || near(a[k], b[k]), `${r}/${id}.${k}: pglite ${a[k]} vs sqlite ${b[k]}`);
      }
    }
  }
  return out.pglite;
}

/** Equipment rows every 5 min over [0, minutes]; proof(minute) gives run_proof (undefined = column absent). */
function history(minutes, proof) {
  const rows = [];
  for (let m = 0; m <= minutes; m += 5) {
    const row = { equipment_id: "eq-1", ts: START + m * MIN };
    const p = proof ? proof(m) : undefined;
    if (p !== undefined) row.run_proof = p;
    rows.push(row);
  }
  return rows;
}
const cols = (withProof) => (withProof ? [{ name: "run_proof", type: "double" }] : []);
function samples(series, minutes, value, skip = () => false) {
  const out = [];
  for (let m = 0; m <= minutes; m += 5) {
    if (skip(m)) continue;
    out.push({ equipment_id: "eq-1", series_id: series, sensor_role: "sat", unit: "°C", ts: START + m * MIN, value: value(m) });
  }
  return out;
}
const declared = (series, fromMin, toMin) => ({ equipment_id: "eq-1", series_id: series, sensor_role: "sat", unit: "°C",
  window_start: START + fromMin * MIN, window_end: START + toMin * MIN });

test("a 3-hour gap is SV-STALE only; the gap adds no FLATLINE / RANGE / SPIKE fault and keeps other value faults", async () => {
  // 6 h; SAT samples missing for minutes 125..295 (a 3 h gap from 120 to 300); out of range (about 90 degC, above the
  // 65.6 degC band, still moving) for minutes 0..60. After the gap the value jumps by about 27 degC (13 -> 40).
  const wiggle = (m) => (m % 15) / 10;
  const value = (jump) => (m) => (m <= 60 ? 90 + wiggle(m) : m >= 300 && jump ? 40 + wiggle(m) : 13 + wiggle(m));
  const run = (jump) => both({
    historyColumns: cols(true), history: history(360, () => 1), weather: [],
    sensorHistory: samples("sat-a", 360, value(jump), (m) => m > 120 && m < 300),
  });
  const out = await run(true);
  const control = await run(false);
  assert.ok(near(out["SV-STALE"]["sat-a"].fault_hours, 3.0 - 0.5), `stale ${out["SV-STALE"]["sat-a"].fault_hours}`);
  assert.ok(near(out["SV-STALE"]["sat-a"].covered_hours, 6.0));
  assert.ok(out["SV-RANGE"]["sat-a"].fault_hours > 0.9, "the independent range fault at other times is kept");
  assert.ok(out["SV-RANGE"]["sat-a"].fault_hours <= 65 / 60 + 1e-9, "no range fault inside the gap");
  assert.equal(out["SV-FLATLINE"]["sat-a"].fault_hours, 0, "moving values are never a flatline");
  // the genuine 90 -> 13 step at minute 65 is a spike; the 13 -> 40 jump across the gap must add nothing
  assert.ok(out["SV-SPIKE"]["sat-a"].fault_hours > 0, "the genuine step is kept");
  assert.ok(near(out["SV-SPIKE"]["sat-a"].fault_hours, control["SV-SPIKE"]["sat-a"].fault_hours), "the jump across the gap is not a spike");
});

test("an expected series with no sample faults for the whole window; a series that failed to fetch is not assessed", async () => {
  const input = {
    historyColumns: cols(true), history: history(240, () => 1), weather: [],
    sensorHistory: samples("sat-live", 240, (m) => 13 + (m % 15) / 10),
    // sat-dead was fetched successfully and returned nothing; sat-failed is not declared (its history request failed)
    sweepSeries: [declared("sat-live", 0, 240), declared("sat-dead", 0, 240)],
  };
  const out = await both(input, ["SV-STALE", "SV-FLATLINE"]);
  assert.ok(near(out["SV-STALE"]["sat-dead"].fault_hours, 4.0 - 0.5) && near(out["SV-STALE"]["sat-dead"].covered_hours, 4.0));
  assert.equal(out["SV-STALE"]["sat-live"].fault_hours, 0);
  assert.equal(out["SV-STALE"]["sat-failed"], undefined, "a failed fetch is not an observed empty series");
  assert.equal(out["SV-FLATLINE"]["sat-dead"], undefined, "flatline needs present samples");
});

test("an equipment with no history rows still assesses its declared series over the requested window", async () => {
  const out = await both({ historyColumns: [], history: [], weather: [], sensorHistory: [], sweepSeries: [declared("sat-x", 0, 120)] }, ["SV-STALE"]);
  assert.ok(near(out["SV-STALE"]["sat-x"].fault_hours, 1.5) && near(out["SV-STALE"]["sat-x"].covered_hours, 2.0));
});

test("SV-STALE is independent of run proof: ON, OFF, unknown and unbound give the same gap fault", async () => {
  const gap = (m) => m > 60 && m < 180;   // 2 h gap (60 -> 180)
  const results = [];
  for (const [name, proof] of [["on", () => 1], ["off", () => 0], ["unknown", () => null], ["unbound", undefined]]) {
    const input = { historyColumns: cols(proof !== undefined), history: history(240, proof), weather: [],
      sensorHistory: samples("sat-g", 240, (m) => 13 + (m % 15) / 10, gap) };
    const row = (await both(input, ["SV-STALE"]))["SV-STALE"]["sat-g"];
    assert.ok(near(row.fault_hours, 1.5), `${name}: ${row.fault_hours}`);
    results.push(row.fault_hours);
  }
  assert.ok(results.every((r) => near(r, results[0])));
});

test("SV-FLATLINE gating: ON assesses, OFF is ineligible, unbound proof is SKIPPED (no_run_proof)", async () => {
  const stuck = () => 12.0;   // last value held with fresh timestamps
  const run = async (proof) => (await both({ historyColumns: cols(proof !== undefined), history: history(240, proof), weather: [],
    sensorHistory: samples("sat-s", 240, stuck) }, ["SV-FLATLINE", "SV-STALE"]));
  const on = await run(() => 1);
  assert.ok(on["SV-FLATLINE"]["sat-s"].fault_hours > 2, "ON: a held last value is a flatline");
  assert.equal(on["SV-STALE"]["sat-s"].fault_hours, 0, "ON: fresh timestamps are not stale");
  const off = await run(() => 0);
  assert.equal(off["SV-FLATLINE"]["sat-s"].fault_hours, 0, "OFF: ineligible, no flatline fault");
  const unbound = await run(undefined);
  assert.equal(unbound["SV-FLATLINE"]["sat-s"].fault_hours, null, "unbound proof: SKIPPED, not an assessed zero");
  assert.equal(unbound["SV-FLATLINE"]["sat-s"].covered_hours, 0);
  assert.equal(unbound["SV-STALE"]["sat-s"].fault_hours, 0, "stale still assesses without proof");
});

test("two sensors on one role are two series: only the silent one is stale", async () => {
  const input = { historyColumns: cols(true), history: history(240, () => 1), weather: [],
    sensorHistory: [...samples("sat-1", 240, (m) => 13 + (m % 15) / 10), ...samples("sat-2", 240, () => 14, (m) => m > 30)] };
  const out = await both(input, ["SV-STALE"]);
  assert.equal(out["SV-STALE"]["sat-1"].fault_hours, 0);
  assert.ok(near(out["SV-STALE"]["sat-2"].fault_hours, (240 - 30) / 60 - 0.5));
});
