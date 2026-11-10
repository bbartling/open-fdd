// Regression contract for per-sensor SV scoring and elapsed-time windows.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const pgPack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const litePack = JSON.parse(readFileSync(new URL("../rules/pack-sqlite.json", import.meta.url), "utf8"));
const SILENCE_SWEEPS = ["SV-STALE", "SV-FLATLINE", "SV-RANGE", "SV-SPIKE"];
const ALL_SWEEPS = ["SV-RATE", ...SILENCE_SWEEPS];
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

function withSensorHistory(input, sensors) {
  const sensorHistory = [];
  for (const row of input.history) {
    for (const { series_id, role, unit } of sensors) {
      const value = row[role];
      if (value === null || value === undefined) continue;
      sensorHistory.push({
        equipment_id: row.equipment_id, series_id, sensor_role: role, unit, ts: row.ts, value,
      });
    }
  }
  return { ...input, sensorHistory };
}

const twoRoleSensors = [
  { series_id: "series-sat-1", role: "sat", unit: "°C" },
  { series_id: "series-rat-1", role: "rat", unit: "°C" },
];
const sweepScore = (out, rule, series_id) => Number(out[rule].find((row) => row.series_id === series_id)?.fault_hours ?? 0);
const sweepCovered = (out, rule, series_id) => Number(out[rule].find((row) => row.series_id === series_id)?.covered_hours ?? 0);

async function queryBoth(input, ruleIds) {
  const pg = await createEngine({ kind: "pglite", pack: pgPack });
  const lite = await createEngine({ kind: "sqlite", pack: litePack });
  try {
    await pg.load(input);
    await lite.load(input);
    const out = {};
    for (const id of ruleIds) {
      const [a, b] = await Promise.all([pg.query(id), lite.query(id)]);
      const sort = (rows) => [...rows].sort((x, y) => String(x.series_id).localeCompare(String(y.series_id)));
      assert.deepEqual(sort(a), sort(b), `${id}: Postgres and SQLite differ`);
      out[id] = a;
    }
    return out;
  } finally {
    await pg.close();
    await lite.close();
  }
}

test("SV sweeps attribute trailing silence per sensor, including while de-energized", async () => {
  const out = await queryBoth(withSensorHistory(inputWithGap(), twoRoleSensors), SILENCE_SWEEPS);
  // Last SAT observation is minute 35, equipment history ends at minute 240; threshold is 0.5 h.
  const expectedSilenceHours = (240 - 35) / 60 - 0.5;
  for (const rule of SILENCE_SWEEPS) {
    assert.ok(around(sweepScore(out, rule, "series-sat-1"), expectedSilenceHours), `${rule}/sat=${sweepScore(out, rule, "series-sat-1")}`);
    assert.ok(around(sweepScore(out, rule, "series-rat-1"), 0), `${rule}/rat=${sweepScore(out, rule, "series-rat-1")}`);
  }
});

test("trailing silence uses equipment end even when the last sensor timestamp has no wide row", async () => {
  const history = [];
  for (let minute = 0; minute <= 70; minute += 7) {
    history.push({ equipment_id: "eq-1", ts: START + minute * 60_000, sat: null, fan_status: 0 });
  }
  const sensorHistory = [0, 10].map((minute) => ({
    equipment_id: "eq-1", series_id: "series-sat", sensor_role: "sat", unit: "°C",
    ts: START + minute * 60_000, value: 12,
  }));
  const out = await queryBoth({ history, sensorHistory }, SILENCE_SWEEPS);
  // The t=10 sensor row has no exact-time wide proof row; the equipment still ends at t=70.
  for (const rule of SILENCE_SWEEPS) {
    assert.ok(around(sweepScore(out, rule, "series-sat"), 0.5),
      `${rule}: trailing silence should reach the independent equipment end`);
  }
});

test("SV-SPIKE preserves the role that jumped", async () => {
  const out = await queryBoth(withSensorHistory(inputWithRatSpike(), twoRoleSensors), ["SV-SPIKE"]);
  assert.ok(sweepScore(out, "SV-SPIKE", "series-rat-1") > 0, "rat spike should be reported");
  assert.ok(around(sweepScore(out, "SV-SPIKE", "series-sat-1"), 0), "normal sat must stay clear");
});

test("SV-STALE and SV-FLATLINE do not let a changing peer mask a stuck sensor", async () => {
  const out = await queryBoth(withSensorHistory(inputWithFlatSat(), twoRoleSensors), ["SV-STALE", "SV-FLATLINE"]);
  for (const rule of ["SV-STALE", "SV-FLATLINE"]) {
    assert.ok(sweepScore(out, rule, "series-sat-1") > 0, `${rule}/sat should be faulted`);
    assert.ok(around(sweepScore(out, rule, "series-rat-1"), 0), `${rule}/rat should remain clear`);
  }
});

test("SV-RANGE resets confirmation after a gap without losing its silent fault time", async () => {
  const input = withSensorHistory({
    history: [[0, 12], [7, 75], [60, 12], [62, 75], [64, 12]].map(([minute, sat]) => ({
      equipment_id: "eq-1", ts: START + minute * 60_000, sat, fan_status: 1,
    })),
    authorizedSeries: [{ site_id: "site-1", equipment_id: "eq-1", role: "sat", unit: "°C" }],
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  }, [{ series_id: "series-sat-1", role: "sat", unit: "°C" }]);
  const out = await queryBoth(input, ["SV-RANGE"]);
  // Count the first fault's 30-minute hold and 23-minute silence. The
  // independent two-minute fault after the gap has not met five-minute confirmation.
  assert.ok(around(sweepScore(out, "SV-RANGE", "series-sat-1"), 53 / 60), `sat=${sweepScore(out, "SV-RANGE", "series-sat-1")}`);
});

test("all five sweeps return separate rows and timelines for same-role sensors", async () => {
  const history = [0, 5, 10, 15].map((minute) => ({
    equipment_id: "eq-1", ts: START + minute * 60_000, sat: 20, fan_status: 1,
  }));
  const sensorHistory = [];
  for (const [series_id, values] of [["series-healthy", [20, 20, 20, 20]], ["series-fault", [20, 75, 75, 75]]]) {
    history.forEach((row, index) => sensorHistory.push({
      equipment_id: row.equipment_id, series_id, sensor_role: "sat", unit: "°C", ts: row.ts, value: values[index],
    }));
  }
  const input = { history, sensorHistory, equipment: [{ building_id: "site-1", equipment_id: "eq-1" }] };
  const pg = await createEngine({ kind: "pglite", pack: pgPack });
  const lite = await createEngine({ kind: "sqlite", pack: litePack });
  try {
    await pg.load(input);
    await lite.load(input);
    for (const rule of ALL_SWEEPS) {
      const a = await pg.query(rule), b = await lite.query(rule);
      assert.deepEqual(a.sort((x, y) => x.series_id.localeCompare(y.series_id)), b.sort((x, y) => x.series_id.localeCompare(y.series_id)), rule);
      assert.equal(a.length, 2, `${rule} returns both series`);
      assert.deepEqual(new Set(a.map((row) => row.sensor_role)), new Set(["sat"]), `${rule} keeps role descriptive`);
      assert.ok(a.every((row) => Number(row.covered_hours) > 0), `${rule} reports per-series coverage`);
      const timelines = await pg.timeline(rule);
      assert.ok(timelines.some((row) => row.series_id === "series-fault"), `${rule} timeline has fault sensor`);
      assert.ok(timelines.some((row) => row.series_id === "series-healthy"), `${rule} timeline has healthy sensor`);
      if (rule === "SV-RANGE") {
        assert.ok(sweepScore({ [rule]: a }, rule, "series-fault") > 0);
        assert.equal(sweepScore({ [rule]: a }, rule, "series-healthy"), 0);
      }
    }
  } finally {
    await pg.close();
    await lite.close();
  }
});

test("a non-SI sample starts a fresh per-sensor confirmation segment", async () => {
  const samples = [[0, 75, "°C"], [2, 75, "°C"], [4, 75, "°C"], [6, 75, "°F"],
    [8, 75, "°C"], [10, 75, "°C"], [12, 20, "°C"]];
  const history = samples.map(([minute, sat]) => ({
    equipment_id: "eq-1", ts: START + minute * 60_000, sat, fan_status: 1,
  }));
  const sensorHistory = samples.map(([minute, value, unit]) => ({
    equipment_id: "eq-1", series_id: "series-sat", sensor_role: "sat", unit,
    ts: START + minute * 60_000, value,
  }));
  const out = await queryBoth({ history, sensorHistory }, ["SV-RANGE"]);
  // The first segment contributes only its confirmed final two-minute hold. The two-minute
  // second-segment fault stays below confirm_min even though it has the same role and series.
  assert.ok(around(sweepScore(out, "SV-RANGE", "series-sat"), 2 / 60),
    `unit boundary must reset the streak: ${sweepScore(out, "SV-RANGE", "series-sat")} h`);
});
