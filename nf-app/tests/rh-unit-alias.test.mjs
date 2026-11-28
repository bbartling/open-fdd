// #1669: the canonical relative-humidity unit token percent_0_100 (0-100 %RH) is assessable in the long-form sweeps.
// A 0-1 fraction is not relative humidity in percent and stays unassessed (never rescaled inside a rule).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine, HELPERS } = require("../hooks/lib/engines.js");
const pgPack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const START = Date.UTC(2026, 0, 1);

// Six hours, five-minute samples. Two humidity series on one AHU: oa_h in percent_0_100 reads 120 %RH for the
// last three hours (out of the 0-100 band), zone_rh declared as a 0-1 fraction reads 0.5.
function input(oaUnit) {
  const history = [];
  const sensorHistory = [];
  for (let minute = 0; minute <= 360; minute += 5) {
    const ts = START + minute * 60_000;
    const oa = minute >= 180 ? 120 : 45;
    history.push({ equipment_id: "ahu-1", ts, fan_status: 1, run_proof: 1, oa_h: oa, zone_rh: 0.5 });
    sensorHistory.push({ equipment_id: "ahu-1", series_id: "s-oa-h", sensor_role: "oa_h", unit: oaUnit, ts, value: oa });
    sensorHistory.push({ equipment_id: "ahu-1", series_id: "s-zone-rh", sensor_role: "zone_rh", unit: "fraction", ts, value: 0.5 });
  }
  return {
    historyColumns: [{ name: "fan_status", type: "double" }, { name: "run_proof", type: "double" }, { name: "oa_h", type: "double" }, { name: "zone_rh", type: "double" }],
    history, weather: [], sensorHistory,
  };
}

test("helper: percent_0_100 declares relative humidity; fraction does not", () => {
  assert.equal(HELPERS.fdd_unit_declares_quantity("percent_0_100", "relative_humidity"), 1);
  assert.equal(HELPERS.fdd_mask_sweep_val("oa_h", "percent_0_100", 55), 55);
  assert.equal(HELPERS.fdd_mask_sweep_val("oa_h", "%RH", 55), 55);
  for (const unit of ["fraction", "percent_0_1", "0-1", ""]) {
    assert.equal(HELPERS.fdd_mask_sweep_val("zone_rh", unit, 0.5), null, unit);
  }
});

for (const [kind, pack] of [["duckdb", pgPack]]) {
  test(`${kind}: SV-RANGE assesses a percent_0_100 humidity series from long-form history`, async () => {
    const eng = await createEngine({ kind, pack });
    try {
      await eng.load(input("percent_0_100"));
      const rows = await eng.query("SV-RANGE");
      const oa = rows.find((r) => r.series_id === "s-oa-h");
      assert.ok(oa, `oa_h series missing from SV-RANGE: ${JSON.stringify(rows)}`);
      assert.ok(oa.covered_hours > 5.9, `covered ${oa.covered_hours}`);
      assert.ok(Math.abs(oa.fault_hours - 3) < 0.01, `fault ${oa.fault_hours}`);
      const zone = rows.find((r) => r.series_id === "s-zone-rh");
      assert.ok(!zone || !(zone.covered_hours > 0), `fraction zone_rh must not be assessed: ${JSON.stringify(zone)}`);
    } finally {
      await eng.close();
    }
  });

  test(`${kind}: the same series with '%' gives the same SV-RANGE result as percent_0_100`, async () => {
    const results = [];
    for (const unit of ["%", "percent_0_100"]) {
      const eng = await createEngine({ kind, pack });
      try {
        await eng.load(input(unit));
        const oa = (await eng.query("SV-RANGE")).find((r) => r.series_id === "s-oa-h");
        results.push([oa.fault_hours, oa.covered_hours]);
      } finally {
        await eng.close();
      }
    }
    assert.ok(results[0][1] > 5.9, `% series not assessed: ${results[0]}`);
    assert.deepEqual(results[1], results[0]);
  });
}
