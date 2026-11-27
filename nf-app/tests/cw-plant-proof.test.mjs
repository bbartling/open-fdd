// #1631: CW-FAN-1 / CW-OPT-1 / CW-APR-1 kept a legacy plant-proof CASE (pump / chiller status, CHW flow, CHW pump command) whose
// ELSE branch was 0, so a resolved operating_status that was ON could never unlock them when none of those points is bound.
// Same contract as TRIM-3 / TRIM-4 (#1710): an unbound legacy point is unknown and the operating_status gate decides; a bound
// legacy point that reads OFF still blocks the fault.
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

// Six hours at five minutes. Wet bulb 20 C. CW-OPT-1 faults when the condenser supply is below wb + approach - slack
// (cw 21 C); CW-FAN-1 when the tower fan is at least 95 % and the supply is above wb + approach + excess (cw 30 C).
const CASES = { "CW-OPT-1": { supply_condenser_water_temperature: 21 }, "CW-FAN-1": { supply_condenser_water_temperature: 30, cooling_tower_fan_command: 1 },
  "CW-APR-1": { supply_condenser_water_temperature: 30, cooling_tower_fan_command: 1 } };   // CW-APR-1 (Grok, #1710): approach 10 K at full fan

function input(ruleId, { runProof, pumpStatus }) {
  const extra = CASES[ruleId];
  const cols = ["operating_status", "weather_service_air_wet_bulb_temperature", ...Object.keys(extra)];
  if (pumpStatus !== undefined) cols.push("pump_operating_status");
  const history = [];
  for (let minute = 0; minute <= 360; minute += 5) {
    const row = { equipment_id: "plant-1", ts: START + minute * 60_000, operating_status: runProof, weather_service_air_wet_bulb_temperature: 20, ...extra };
    if (pumpStatus !== undefined) row.pump_operating_status = pumpStatus;
    history.push(row);
  }
  return { historyColumns: cols.map((name) => ({ name, type: "double" })), history, weather: [], sensorHistory: [] };
}

async function faultHours(kind, ruleId, opts) {
  const eng = await createEngine({ kind, pack: PACKS[kind] });
  try {
    await eng.load(input(ruleId, opts));
    const rows = await eng.query(ruleId);
    assert.equal(rows.length, 1);
    return Number(rows[0].fault_hours);
  } finally {
    await eng.close();
  }
}

for (const kind of ["duckdb"]) {
  for (const ruleId of Object.keys(CASES)) {
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
