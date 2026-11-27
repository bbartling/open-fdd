// #1670: SCHED-247 tells proven OFF from unknown proof, reports its durations and needs enough known proof.
// Shared scenarios: tests/fixtures/sched247_cases.json (DuckDB and pandas run the same file in
// tests/parity/test_sched247_proof.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const pgPack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const fixture = JSON.parse(readFileSync(new URL("../../tests/fixtures/sched247_cases.json", import.meta.url), "utf8"));
const TOL = fixture.tolerance_hours;

function input() {
  const history = [];
  for (const c of fixture.cases) for (const r of c.rows) history.push({ equipment_id: c.equipment_id, ...r });
  return {
    historyColumns: [{ name: "fan_status", type: "double" }, { name: "fan_cmd", type: "double" }],
    history, weather: [],
  };
}

function checkRow(kind, c, row) {
  assert.ok(row, `${kind}/${c.equipment_id}: no row`);
  for (const [key, want] of Object.entries(c.expected)) {
    if (want === undefined) continue;
    const got = row[key];
    if (want === null) {
      if (key === "window_hours") continue;
      assert.equal(got, null, `${kind}/${c.equipment_id}.${key}: ${got}`);
    } else if (typeof want === "number") {
      assert.ok(typeof got === "number" && Math.abs(got - want) <= TOL, `${kind}/${c.equipment_id}.${key}: got ${got}, want ${want}`);
    } else {
      assert.equal(got, want, `${kind}/${c.equipment_id}.${key}`);
    }
  }
  // invariants on every row
  const sum = row.proven_on_hours + row.proven_off_hours + row.unknown_hours;
  assert.ok(Math.abs(sum - row.window_hours) <= TOL, `${kind}/${c.equipment_id}: on+off+unknown ${sum} != window ${row.window_hours}`);
  assert.ok(Math.abs(row.covered_hours - row.proven_on_hours - row.proven_off_hours) <= TOL, `${kind}/${c.equipment_id}: covered`);
  if (row.assessment === "assessed") assert.ok(row.fault_hours !== null && row.fault_pct !== null);
  else assert.ok(row.fault_hours === null && row.fault_pct === null, `${kind}/${c.equipment_id}: unassessed row has hours`);
}

const results = {};
for (const [kind, pack] of [["duckdb", pgPack]]) {
  test(`${kind}: SCHED-247 proof states, durations and completeness`, async () => {
    const eng = await createEngine({ kind, pack });
    try {
      await eng.load(input());
      const rows = await eng.query("SCHED-247");
      results[kind] = rows;
      for (const c of fixture.cases) checkRow(kind, c, rows.find((r) => r.equipment_id === c.equipment_id));
      const tl = await eng.timeline("SCHED-247");
      // the timeline sums to the fault hours of every assessed equipment
      for (const r of rows) {
        const conf = tl.filter((t) => t.equipment_id === r.equipment_id && t.confirmed === 1)
          .reduce((s, t) => s + t.held_seconds, 0) / 3600;
        assert.ok(Math.abs(conf - (r.fault_hours ?? 0)) <= TOL, `${kind}/${r.equipment_id}: timeline ${conf} vs ${r.fault_hours}`);
      }
    } finally {
      await eng.close();
    }
  });
}

test("DuckDB returns a SCHED-247 row for every fixture case", () => {
  const ids = new Set((results.duckdb || []).map((r) => r.equipment_id));
  for (const c of fixture.cases) assert.ok(ids.has(c.equipment_id), c.equipment_id);
});
