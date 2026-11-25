// #1783 FILTER-LOAD on the SQL engines (PGlite, SQLite): the filter DP path (threshold edges, fan off, run proof,
// low-airflow and implausible samples), the fan-effort advisory path, and NOT ASSESSED (never a silent pass) without a
// filter DP or the fan power + airflow pair, or with too thin a baseline. The same cases run on pandas, DuckDB and
// PostgreSQL in tests/test_filter_load.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const PACKS = {
  pglite: JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8")),
  sqlite: JSON.parse(readFileSync(new URL("../rules/pack-sqlite.json", import.meta.url), "utf8")),
};
const CASES = JSON.parse(readFileSync(new URL("../../tests/fixtures/filter_load_cases.json", import.meta.url), "utf8")).cases;
const START = Date.UTC(2026, 0, 1);

function input(c) {
  const n = c.n || 97;
  const cols = [...new Set([...Object.keys(c.row), ...Object.keys(c.second_half || {})])];
  const history = [];
  for (let i = 0; i < n; i++) {
    const vals = i >= Math.floor(n / 2) ? { ...c.row, ...(c.second_half || {}) } : c.row;
    history.push({ equipment_id: "ahu-1", ts: START + i * 300_000, ...vals });
  }
  return { historyColumns: cols.map((name) => ({ name, type: "double" })), history, weather: [], sensorHistory: [] };
}

for (const kind of ["pglite", "sqlite"]) {
  for (const c of CASES) {
    test(`${kind} FILTER-LOAD ${c.id}`, async () => {
      const eng = await createEngine({ kind, pack: PACKS[kind] });
      try {
        await eng.load(input(c));
        const [row] = await eng.query("FILTER-LOAD");
        if (typeof c.expect === "string") {
          assert.equal(row.assessment, c.expect);
          assert.equal(row.fault_hours, null);
          assert.equal(row.covered_hours, 0);
        } else {
          assert.equal(row.assessment, "assessed");
          assert.equal(row.filter_path, c.path);
          assert.ok(Math.abs(row.fault_hours - c.expect) < 1e-5, `fault_hours ${row.fault_hours}, want ${c.expect}`);
        }
      } finally {
        await eng.close();
      }
    });
  }
}
