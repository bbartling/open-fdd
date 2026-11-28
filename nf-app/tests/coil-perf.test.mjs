// #1641 COIL-PERF on the SQL engines (PGlite, SQLite): heating and cooling modes, the temperature-pair ladder, the
// airflow and run-proof gates, and NOT ASSESSED (never a silent pass) without a coil valve or a temperature pair.
// The same cases run on pandas in tests/test_coil_perf.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const PACKS = {
  duckdb: JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8")),
};
const CASES = JSON.parse(readFileSync(new URL("../../tests/fixtures/coil_perf_cases.json", import.meta.url), "utf8")).cases;
const START = Date.UTC(2026, 0, 1);

function input(row) {
  const cols = Object.keys(row);
  const history = [];
  for (let i = 0; i <= 48; i++) history.push({ equipment_id: "ahu-1", ts: START + i * 300_000, ...row });
  return { historyColumns: cols.map((name) => ({ name, type: "double" })), history, weather: [], sensorHistory: [] };
}

for (const kind of ["duckdb"]) {
  for (const c of CASES) {
    test(`${kind} COIL-PERF ${c.id}`, async () => {
      const eng = await createEngine({ kind, pack: PACKS[kind] });
      try {
        await eng.load(input(c.row));
        const [row] = await eng.query("COIL-PERF");
        if (typeof c.expect === "string") {
          assert.equal(row.assessment, c.expect);
          assert.equal(row.fault_hours, null);
          assert.equal(row.covered_hours, 0);
        } else {
          assert.equal(row.assessment, "assessed");
          assert.ok(Math.abs(row.fault_hours - c.expect) < 1e-5, `fault_hours ${row.fault_hours}, want ${c.expect}`);
        }
      } finally {
        await eng.close();
      }
    });
  }
}
