// #1631 (design call 1, Ben: "Yes, as proposed"): run-proof gated rules report active_hours, the covered time while the
// run proof was on, and fault_pct = fault_hours / active_hours (as pandas, which divides by active time).
// covered_hours stays data coverage, so a unit that is off all day is still assessed (PASS, 0 active hours), not "not
// assessed".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const PACKS = {
  duckdb: JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8")),
};
const START = Date.UTC(2026, 0, 1);

// Six hours at five minutes; HWST 85 C with zero requests (a TRIM-3 fault throughout); the run proof is ON for the first
// three hours only (or never).
function input(proofOn) {
  const history = [];
  for (let minute = 0; minute <= 360; minute += 5) {
    history.push({ equipment_id: "plant-1", ts: START + minute * 60_000, operating_status: proofOn(minute) ? 1 : 0,
      pump_operating_status: 1, supply_hot_water_temperature: 85, hot_water_reset_request_count: 0 });
  }
  const cols = ["operating_status", "pump_operating_status", "supply_hot_water_temperature", "hot_water_reset_request_count"];
  return { historyColumns: cols.map((name) => ({ name, type: "double" })), history, weather: [], sensorHistory: [] };
}

async function run(kind, ruleId, proofOn) {
  const eng = await createEngine({ kind, pack: PACKS[kind] });
  try {
    await eng.load(input(proofOn));
    const rows = await eng.query(ruleId);
    assert.equal(rows.length, 1);
    return rows[0];
  } finally {
    await eng.close();
  }
}

test("every run-proof gated rule outputs active_hours; ungated rules do not", () => {
  const catalog = JSON.parse(readFileSync(new URL("../../sql/fdd/tuning_catalog.json", import.meta.url), "utf8")).rules;
  for (const r of catalog) {
    const cols = PACKS.duckdb.rules[r.rule_id].output_columns;
    const gatedSql = /COALESCE\(operating_status, 0\) <= 0\.05/.test(readFileSync(new URL(`../../sql/fdd/postgres/rules/${r.sql_file}`, import.meta.url), "utf8"));
    assert.equal(cols.includes("active_hours"), gatedSql, r.rule_id);
  }
});

for (const kind of ["duckdb"]) {
  test(`${kind}: covered_hours is data coverage, active_hours the proven-on part, fault_pct = fault / active`, async () => {
    const row = await run(kind, "TRIM-3", (m) => m < 180);
    assert.ok(Math.abs(row.covered_hours - 6) < 1e-9, `covered ${row.covered_hours}`);
    assert.ok(Math.abs(row.active_hours - 3) < 1e-9, `active ${row.active_hours}`);
    assert.ok(row.fault_hours > 2 && row.fault_hours <= 3, `fault ${row.fault_hours}`);
    assert.ok(Math.abs(row.fault_pct - (100 * row.fault_hours) / row.active_hours) < 1e-9, `fault_pct ${row.fault_pct}`);
  });

  test(`${kind}: a unit off all day is assessed with 0 active hours (PASS, fault_pct 0 as pandas), not skipped`, async () => {
    const row = await run(kind, "TRIM-3", () => false);
    assert.ok(Math.abs(row.covered_hours - 6) < 1e-9);
    assert.equal(row.active_hours, 0);
    assert.equal(row.fault_hours, 0);
    assert.equal(row.fault_pct, 0, "0 %, not NULL: the hook publishes fault_pct and NULL would read as not assessed");
  });
}

test("the FDD hook publishes an off-all-day gated unit as ok 0 %, not not-assessed", async () => {
  const hook = require("../hooks/fdd.js");
  const row = await run("duckdb", "TRIM-3", () => false);
  const out = hook.resultValue(PACKS.duckdb.rules["TRIM-3"], row);
  assert.equal(out.status, "ok");
  assert.equal(out.value, 0);
  assert.equal(out.column, "fault_pct");
});
