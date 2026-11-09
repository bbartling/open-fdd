// Regression contract for per-sensor SV scoring and elapsed-time windows.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const pgPack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const litePack = JSON.parse(readFileSync(new URL("../rules/pack-sqlite.json", import.meta.url), "utf8"));
const SWEEPS = ["SV-STALE", "SV-FLATLINE", "SV-RANGE", "SV-SPIKE"];
const START = Date.UTC(2026, 0, 1);
const around = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;

function inputWithGap() {
  const history = [];
  // Seven-minute observations exercise elapsed windows off the five-minute grid.
  // SAT goes silent after minute 35 while RAT continues through the equipment end at minute 240.
  for (let minute = 0; minute <= 240; minute += 7) {
    history.push({
      equipment_id: "eq-1", ts: START + minute * 60_000,
      sat: minute <= 35 ? 12.0 : null,
      rat: 20 + minute / 100,
      fan_status: 0,
    });
  }
  if (history.at(-1).ts !== START + 240 * 60_000) {
    history.push({ equipment_id: "eq-1", ts: START + 240 * 60_000, sat: null, rat: 22.4, fan_status: 0 });
  }
  return {
    history,
    authorizedSeries: ["sat", "rat"].map((role) => ({ site_id: "site-1", equipment_id: "eq-1", role, unit: "°C" })),
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  };
}

function inputWithRatSpike() {
  const history = [];
  for (let minute = 0; minute <= 120; minute += 7) {
    history.push({
      equipment_id: "eq-1", ts: START + minute * 60_000,
      sat: 12 + minute / 100,
      rat: minute < 70 ? 21 : 30,
      fan_status: 1,
    });
  }
  return {
    history,
    authorizedSeries: ["sat", "rat"].map((role) => ({ site_id: "site-1", equipment_id: "eq-1", role, unit: "°C" })),
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  };
}

function inputWithFlatSat() {
  const history = [];
  // Just over two elapsed hours: SAT is stuck while the peer RAT continues changing.
  for (let minute = 0; minute <= 133; minute += 7) {
    history.push({
      equipment_id: "eq-1", ts: START + minute * 60_000,
      sat: 12.0,
      rat: 20 + minute / 100,
      fan_status: 1,
    });
  }
  return {
    history,
    authorizedSeries: ["sat", "rat"].map((role) => ({ site_id: "site-1", equipment_id: "eq-1", role, unit: "°C" })),
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  };
}

async function queryBoth(input, ruleIds) {
  const pg = await createEngine({ kind: "pglite", pack: pgPack });
  const lite = await createEngine({ kind: "sqlite", pack: litePack });
  try {
    await pg.load(input);
    await lite.load(input);
    const out = {};
    for (const id of ruleIds) {
      const [a, b] = await Promise.all([pg.query(id), lite.query(id)]);
      const sort = (rows) => [...rows].sort((x, y) => String(x.sensor_role).localeCompare(String(y.sensor_role)));
      assert.deepEqual(sort(a), sort(b), `${id}: Postgres and SQLite differ`);
      out[id] = Object.fromEntries(a.map((row) => [row.sensor_role, Number(row.fault_hours)]));
    }
    return out;
  } finally {
    await pg.close();
    await lite.close();
  }
}

test("SV sweeps attribute trailing silence per sensor, including while de-energized", async () => {
  const out = await queryBoth(inputWithGap(), SWEEPS);
  // Last SAT observation is minute 35, equipment history ends at minute 240; threshold is 0.5 h.
  const expectedSilenceHours = (240 - 35) / 60 - 0.5;
  for (const rule of SWEEPS) {
    assert.ok(around(out[rule].sat, expectedSilenceHours), `${rule}/sat=${out[rule].sat}`);
    assert.ok(around(out[rule].rat, 0), `${rule}/rat=${out[rule].rat}`);
  }
});

test("SV-SPIKE preserves the role that jumped", async () => {
  const out = await queryBoth(inputWithRatSpike(), ["SV-SPIKE"]);
  assert.ok(out["SV-SPIKE"].rat > 0, "rat spike should be reported");
  assert.ok(around(out["SV-SPIKE"].sat, 0), "normal sat must stay clear");
});

test("SV-STALE and SV-FLATLINE do not let a changing peer mask a stuck sensor", async () => {
  const out = await queryBoth(inputWithFlatSat(), ["SV-STALE", "SV-FLATLINE"]);
  for (const rule of ["SV-STALE", "SV-FLATLINE"]) {
    assert.ok(out[rule].sat > 0, `${rule}/sat should be faulted`);
    assert.ok(around(out[rule].rat, 0), `${rule}/rat should remain clear`);
  }
});

test("SV-RANGE resets confirmation after a gap without losing its silent fault time", async () => {
  const input = {
    history: [[0, 12], [7, 75], [60, 12], [62, 75], [64, 12]].map(([minute, sat]) => ({
      equipment_id: "eq-1", ts: START + minute * 60_000, sat, fan_status: 1,
    })),
    authorizedSeries: [{ site_id: "site-1", equipment_id: "eq-1", role: "sat", unit: "°C" }],
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  };
  const out = await queryBoth(input, ["SV-RANGE"]);
  // Count the first fault's 30-minute hold and 23-minute silence. The
  // independent two-minute fault after the gap has not met five-minute confirmation.
  assert.ok(around(out["SV-RANGE"].sat, 53 / 60), `sat=${out["SV-RANGE"].sat}`);
});
