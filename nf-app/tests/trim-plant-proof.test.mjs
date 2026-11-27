// #1631: TRIM-3 / TRIM-4 kept a legacy plant-proof CASE (pump / chiller status, CHW flow, CHW pump command) whose
// ELSE branch was 0. With none of those points bound, a resolved operating_status that was ON could never unlock the rule.
// Now an unbound legacy point is unknown (NULL): the operating_status gate decides; a bound legacy point that reads OFF still
// blocks the fault.
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

// Six hours at five minutes: HWST 85 C (above the 71.1 C trim limit) and CHWST 4 C (below 7.2 C) with zero requests.
function input({ runProof, pumpStatus }) {
  const cols = ["operating_status", "supply_hot_water_temperature", "hot_water_reset_request_count", "supply_chilled_water_temperature", "chilled_water_reset_request_count"];
  if (pumpStatus !== undefined) cols.push("pump_operating_status");
  const history = [];
  for (let minute = 0; minute <= 360; minute += 5) {
    const row = { equipment_id: "plant-1", ts: START + minute * 60_000, operating_status: runProof, supply_hot_water_temperature: 85,
      hot_water_reset_request_count: 0, supply_chilled_water_temperature: 4, chilled_water_reset_request_count: 0 };
    if (pumpStatus !== undefined) row.pump_operating_status = pumpStatus;
    history.push(row);
  }
  return { historyColumns: cols.map((name) => ({ name, type: "double" })), history, weather: [], sensorHistory: [] };
}

async function faultHours(kind, ruleId, opts) {
  const eng = await createEngine({ kind, pack: PACKS[kind] });
  try {
    await eng.load(input(opts));
    const rows = await eng.query(ruleId);
    assert.equal(rows.length, 1);
    return Number(rows[0].fault_hours);
  } finally {
    await eng.close();
  }
}

for (const kind of ["duckdb"]) {
  for (const ruleId of ["TRIM-3", "TRIM-4"]) {
    test(`${kind} ${ruleId}: a bound operating_status ON unlocks the rule when no legacy plant point is bound`, async () => {
      assert.ok(await faultHours(kind, ruleId, { runProof: 1 }) > 5);
    });
    test(`${kind} ${ruleId}: operating_status OFF still blocks it`, async () => {
      assert.equal(await faultHours(kind, ruleId, { runProof: 0 }), 0);
    });
    test(`${kind} ${ruleId}: a bound legacy pump status that reads OFF still blocks it`, async () => {
      assert.equal(await faultHours(kind, ruleId, { runProof: 1, pumpStatus: 0 }), 0);
      assert.ok(await faultHours(kind, ruleId, { runProof: 1, pumpStatus: 1 }) > 5);
    });
  }
}
