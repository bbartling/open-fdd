// Regression contract for per-sensor SV scoring and elapsed-time windows.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const pgPack = JSON.parse(readFileSync(new URL("../rules/pack-postgres.json", import.meta.url), "utf8"));
const catalog = JSON.parse(readFileSync(new URL("../static/fdd-catalog.json", import.meta.url), "utf8"));
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
      discharge_air_temperature: minute <= 35 ? 12.0 : null,
      return_air_temperature: 20 + minute / 100,
      supply_fan_operating_status: 0,
    });
  }
  if (history.at(-1).ts !== START + 240 * 60_000) {
    history.push({ equipment_id: "eq-1", ts: START + 240 * 60_000, discharge_air_temperature: null, return_air_temperature: 22.4, supply_fan_operating_status: 0 });
  }
  return {
    history,
    authorizedSeries: ["discharge_air_temperature", "return_air_temperature"].map((role) => ({ site_id: "site-1", equipment_id: "eq-1", role, unit: "°C" })),
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  };
}

function inputWithRatSpike() {
  const history = [];
  for (let minute = 0; minute <= 120; minute += 7) {
    history.push({
      equipment_id: "eq-1", ts: START + minute * 60_000,
      discharge_air_temperature: 12 + minute / 100,
      return_air_temperature: minute < 70 ? 21 : 30,
      supply_fan_operating_status: 1,
    });
  }
  return {
    history,
    authorizedSeries: ["discharge_air_temperature", "return_air_temperature"].map((role) => ({ site_id: "site-1", equipment_id: "eq-1", role, unit: "°C" })),
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  };
}

function inputWithFlatSat() {
  const history = [];
  // Just over two elapsed hours: SAT is stuck while the peer RAT continues changing.
  for (let minute = 0; minute <= 133; minute += 7) {
    history.push({
      equipment_id: "eq-1", ts: START + minute * 60_000,
      discharge_air_temperature: 12.0,
      return_air_temperature: 20 + minute / 100,
      supply_fan_operating_status: 1,
    });
  }
  return {
    history,
    authorizedSeries: ["discharge_air_temperature", "return_air_temperature"].map((role) => ({ site_id: "site-1", equipment_id: "eq-1", role, unit: "°C" })),
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
  { series_id: "series-discharge_air_temperature-1", role: "discharge_air_temperature", unit: "°C" },
  { series_id: "series-return_air_temperature-1", role: "return_air_temperature", unit: "°C" },
];
const sweepScore = (out, rule, series_id) => Number(out[rule].find((row) => row.series_id === series_id)?.fault_hours ?? 0);
const sweepCovered = (out, rule, series_id) => Number(out[rule].find((row) => row.series_id === series_id)?.covered_hours ?? 0);

/** The resolved run proof (#1608) of these fixtures is their own fan status (tier 1), as the hook would bind it. */
const withRunProof = (input) => ({ ...input, history: input.history.map((row) => ("operating_status" in row ? row : { ...row, operating_status: row.supply_fan_operating_status ?? null })) });

async function queryBoth(input, ruleIds) {
  input = withRunProof(input);
  const pg = await createEngine({ kind: "duckdb", pack: pgPack });
  try {
    await pg.load(input);
    const out = {};
    for (const id of ruleIds) out[id] = await pg.query(id);
    return out;
  } finally {
    await pg.close();
  }
}

test("#1673: trailing silence is SV-STALE only, per sensor, including while de-energized", async () => {
  const out = await queryBoth(withSensorHistory(inputWithGap(), twoRoleSensors), SILENCE_SWEEPS);
  // Last SAT observation is minute 35, equipment history ends at minute 240; stale_after_hours is 0.5 h.
  const expectedSilenceHours = (240 - 35) / 60 - 0.5;
  assert.ok(around(sweepScore(out, "SV-STALE", "series-discharge_air_temperature-1"), expectedSilenceHours), `SV-STALE/discharge_air_temperature=${sweepScore(out, "SV-STALE", "series-discharge_air_temperature-1")}`);
  for (const rule of SILENCE_SWEEPS) {
    if (rule !== "SV-STALE") assert.ok(around(sweepScore(out, rule, "series-discharge_air_temperature-1"), 0), `${rule}/discharge_air_temperature must not score the gap: ${sweepScore(out, rule, "series-discharge_air_temperature-1")}`);
    assert.ok(around(sweepScore(out, rule, "series-return_air_temperature-1"), 0), `${rule}/return_air_temperature=${sweepScore(out, rule, "series-return_air_temperature-1")}`);
  }
});

test("trailing silence uses equipment end even when the last sensor timestamp has no wide row", async () => {
  const history = [];
  for (let minute = 0; minute <= 70; minute += 7) {
    history.push({ equipment_id: "eq-1", ts: START + minute * 60_000, discharge_air_temperature: null, supply_fan_operating_status: 0 });
  }
  const sensorHistory = [0, 10].map((minute) => ({
    equipment_id: "eq-1", series_id: "series-discharge_air_temperature", sensor_role: "discharge_air_temperature", unit: "°C",
    ts: START + minute * 60_000, value: 12,
  }));
  const out = await queryBoth({ history, sensorHistory }, SILENCE_SWEEPS);
  // The t=10 sensor row has no exact-time wide proof row; the equipment still ends at t=70 (gap 60 min - 30 min).
  assert.ok(around(sweepScore(out, "SV-STALE", "series-discharge_air_temperature"), 0.5), "SV-STALE: trailing silence should reach the independent equipment end");
  for (const rule of SILENCE_SWEEPS.filter((r) => r !== "SV-STALE")) {
    assert.ok(around(sweepScore(out, rule, "series-discharge_air_temperature"), 0), `${rule}: the gap is not this rule's fault (#1673)`);
  }
});

test("SV-SPIKE preserves the role that jumped", async () => {
  const out = await queryBoth(withSensorHistory(inputWithRatSpike(), twoRoleSensors), ["SV-SPIKE"]);
  assert.ok(sweepScore(out, "SV-SPIKE", "series-return_air_temperature-1") > 0, "return_air_temperature spike should be reported");
  assert.ok(around(sweepScore(out, "SV-SPIKE", "series-discharge_air_temperature-1"), 0), "normal discharge_air_temperature must stay clear");
});

test("#1673: a stuck sensor that is still polled is SV-FLATLINE only; a changing peer does not mask it", async () => {
  const out = await queryBoth(withSensorHistory(inputWithFlatSat(), twoRoleSensors), ["SV-STALE", "SV-FLATLINE", "SV-RANGE", "SV-SPIKE"]);
  assert.ok(sweepScore(out, "SV-FLATLINE", "series-discharge_air_temperature-1") > 0, "SV-FLATLINE/discharge_air_temperature should be faulted");
  assert.ok(around(sweepScore(out, "SV-FLATLINE", "series-return_air_temperature-1"), 0), "SV-FLATLINE/return_air_temperature should remain clear");
  for (const rule of ["SV-STALE", "SV-RANGE", "SV-SPIKE"]) {
    assert.ok(around(sweepScore(out, rule, "series-discharge_air_temperature-1"), 0), `${rule}: a polled stuck value is not ${rule}`);
    assert.ok(sweepCovered(out, rule, "series-discharge_air_temperature-1") > 0, `${rule}: the stuck sensor is still assessed`);
  }
});

test("SV-RANGE resets confirmation after a gap and does not count the gap as fault time (#1673)", async () => {
  const input = withSensorHistory({
    history: [[0, 12], [7, 75], [60, 12], [62, 75], [64, 12]].map(([minute, discharge_air_temperature]) => ({
      equipment_id: "eq-1", ts: START + minute * 60_000, discharge_air_temperature, supply_fan_operating_status: 1,
    })),
    authorizedSeries: [{ site_id: "site-1", equipment_id: "eq-1", role: "discharge_air_temperature", unit: "°C" }],
    equipment: [{ building_id: "site-1", equipment_id: "eq-1" }],
  }, [{ series_id: "series-discharge_air_temperature-1", role: "discharge_air_temperature", unit: "°C" }]);
  const out = await queryBoth(input, ["SV-RANGE"]);
  // Count the first fault's 30-minute hold only: the 23 minutes of silence beyond it are unknown here, not a range
  // fault (SV-STALE scores gaps). The two-minute fault after the gap has not met five-minute confirmation.
  assert.ok(around(sweepScore(out, "SV-RANGE", "series-discharge_air_temperature-1"), 30 / 60), `discharge_air_temperature=${sweepScore(out, "SV-RANGE", "series-discharge_air_temperature-1")}`);
});

test("all five sweeps return separate rows and timelines for same-role sensors", async () => {
  const history = [0, 5, 10, 15].map((minute) => ({
    equipment_id: "eq-1", ts: START + minute * 60_000, discharge_air_temperature: 20, supply_fan_operating_status: 1,
  }));
  const sensorHistory = [];
  for (const [series_id, values] of [["series-healthy", [20, 20, 20, 20]], ["series-fault", [20, 75, 75, 75]]]) {
    history.forEach((row, index) => sensorHistory.push({
      equipment_id: row.equipment_id, series_id, sensor_role: "discharge_air_temperature", unit: "°C", ts: row.ts, value: values[index],
    }));
  }
  const input = withRunProof({ history, sensorHistory, equipment: [{ building_id: "site-1", equipment_id: "eq-1" }] });
  const pg = await createEngine({ kind: "duckdb", pack: pgPack });
  try {
    await pg.load(input);
    for (const rule of ALL_SWEEPS) {
      const a = await pg.query(rule);
      assert.equal(a.length, 2, `${rule} returns both series`);
      assert.deepEqual(new Set(a.map((row) => row.sensor_role)), new Set(["discharge_air_temperature"]), `${rule} keeps role descriptive`);
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
  }
});

test("sweeps emit only their canonical assessable roles", async () => {
  const history = [0, 5, 10].map((minute) => ({
    equipment_id: "eq-1", ts: START + minute * 60_000, discharge_air_temperature: 20, discharge_air_static_pressure: 250, discharge_air_volume_flow_rate: 50, supply_fan_operating_status: 1,
  }));
  const sensorHistory = [];
  for (const [series_id, sensor_role, unit, value] of [
    ["discharge_air_temperature-id", "discharge_air_temperature", "°C", 20],
    ["static-id", "discharge_air_static_pressure", "Pa", 250],
    ["flow-id", "discharge_air_volume_flow_rate", "L/s", 50],
  ]) {
    for (const row of history) sensorHistory.push({
      equipment_id: row.equipment_id, series_id, sensor_role, unit, ts: row.ts, value,
    });
  }
  const out = await queryBoth({ history, sensorHistory }, ALL_SWEEPS);
  for (const rule of ALL_SWEEPS) {
    const expected = new Set(catalog.sensor_sweep_roles[rule]);
    const actual = new Set(out[rule].map((row) => row.sensor_role));
    assert.deepEqual(actual, new Set([...actual].filter((role) => expected.has(role))), `${rule} rows stay in its allowlist`);
    assert.equal(actual.has("discharge_air_volume_flow_rate"), ["SV-RANGE", "SV-STALE"].includes(rule), `${rule} zone airflow inclusion`);
    assert.equal(actual.has("discharge_air_static_pressure"), ["SV-RANGE", "SV-SPIKE", "SV-STALE"].includes(rule), `${rule} duct static inclusion`);
    assert.ok(out[rule].every((row) => row.fault_hours != null || Number(row.covered_hours) === 0), `${rule} null hours mean no coverage`);
  }
});

test("a never-covered assessable sensor returns NULL fault hours, not zero", async () => {
  const history = [{ equipment_id: "eq-1", ts: START, discharge_air_temperature: 20, supply_fan_operating_status: 1 }];
  const sensorHistory = [{
    equipment_id: "eq-1", series_id: "discharge_air_temperature-never-covered", sensor_role: "discharge_air_temperature", unit: "°C", ts: START, value: 20,
  }];
  const out = await queryBoth({ history, sensorHistory }, ALL_SWEEPS);
  for (const rule of ALL_SWEEPS) {
    assert.equal(out[rule].length, 1, `${rule} may report the assessable sensor as not-assessed`);
    assert.equal(out[rule][0].covered_hours, 0, `${rule} has no interval to assess`);
    assert.equal(out[rule][0].fault_hours, null, `${rule} must preserve not-assessed as NULL`);
  }
});

test("a non-SI sample starts a fresh per-sensor confirmation segment", async () => {
  const samples = [[0, 75, "°C"], [2, 75, "°C"], [4, 75, "°C"], [6, 75, "°F"],
    [8, 75, "°C"], [10, 75, "°C"], [12, 20, "°C"]];
  const history = samples.map(([minute, discharge_air_temperature]) => ({
    equipment_id: "eq-1", ts: START + minute * 60_000, discharge_air_temperature, supply_fan_operating_status: 1,
  }));
  const sensorHistory = samples.map(([minute, value, unit]) => ({
    equipment_id: "eq-1", series_id: "series-discharge_air_temperature", sensor_role: "discharge_air_temperature", unit,
    ts: START + minute * 60_000, value,
  }));
  const out = await queryBoth({ history, sensorHistory }, ["SV-RANGE"]);
  // The first segment contributes only its confirmed final two-minute hold. The two-minute
  // second-segment fault stays below confirm_min even though it has the same role and series.
  assert.ok(around(sweepScore(out, "SV-RANGE", "series-discharge_air_temperature"), 2 / 60),
    `unit boundary must reset the streak: ${sweepScore(out, "SV-RANGE", "series-discharge_air_temperature")} h`);
});

test("three same-role SI sensors isolate fault, healthy zero, insufficient history, operating gate, and row order", async () => {
  // Two temperature sensors on role 'discharge_air_temperature' (one faulted, one healthy), plus a third sensor with only 1 sample at window end (insufficient history).
  // Equipment is off (supply_fan_operating_status = 0) for minutes 0..30 and on (supply_fan_operating_status = 1) for minutes 35..180.
  const history = [];
  for (let minute = 0; minute <= 180; minute += 5) {
    history.push({
      equipment_id: "eq-1",
      ts: START + minute * 60_000,
      discharge_air_temperature: 22.0,
      supply_fan_operating_status: minute >= 35 ? 1 : 0,
    });
  }
  const sensorHistory = [];
  for (let i = 0; i < history.length; i++) {
    const row = history[i];
    const minute = i * 5;
    sensorHistory.push({
      equipment_id: "eq-1",
      series_id: "discharge_air_temperature-healthy",
      sensor_role: "discharge_air_temperature",
      unit: "°C",
      ts: row.ts,
      value: 22.0 + (i % 3) * 0.25,
    });
    // Out of range during supply_fan_operating_status = 0 (minutes 0..30) must NOT score when gated,
    // while minutes 60..150 (supply_fan_operating_status = 1) trigger SV-RANGE, SV-FLATLINE, SV-SPIKE, and SV-RATE.
    let faultVal = 22.0 + (i % 3) * 0.25;
    if (minute <= 30) faultVal = 75.0;
    else if (minute === 50 || minute === 60) faultVal = 75.0;
    else if (minute === 55) faultVal = 20.0;
    else if (minute >= 65 && minute <= 150) faultVal = 75.0;
    sensorHistory.push({
      equipment_id: "eq-1",
      series_id: "discharge_air_temperature-fault",
      sensor_role: "discharge_air_temperature",
      unit: "°C",
      ts: row.ts,
      value: faultVal,
    });
  }
  sensorHistory.push({
    equipment_id: "eq-1",
    series_id: "discharge_air_temperature-short",
    sensor_role: "discharge_air_temperature",
    unit: "°C",
    ts: START + 180 * 60_000,
    value: 75.0,
  });

  const ordered = { history, sensorHistory, equipment: [{ building_id: "site-1", equipment_id: "eq-1" }] };
  const reversed = {
    history: [...history].reverse(),
    sensorHistory: [...sensorHistory].reverse(),
    equipment: ordered.equipment,
  };
  const outA = await queryBoth(ordered, ALL_SWEEPS);
  const outB = await queryBoth(reversed, ALL_SWEEPS);

  const bySeries = (rows) => Object.fromEntries(rows.map((r) => [r.series_id, r]));
  for (const rule of ALL_SWEEPS) {
    assert.deepEqual(
      [...outA[rule]].sort((a, b) => a.series_id.localeCompare(b.series_id)),
      [...outB[rule]].sort((a, b) => a.series_id.localeCompare(b.series_id)),
      `${rule}: reordered input rows must produce identical per-sensor output`
    );
    const rows = bySeries(outA[rule]);
    assert.deepEqual(Object.keys(rows).sort(), ["discharge_air_temperature-fault", "discharge_air_temperature-healthy", "discharge_air_temperature-short"], rule);
    assert.equal(rows["discharge_air_temperature-healthy"].fault_hours, 0, `${rule}: healthy peer must preserve explicit 0`);
    assert.ok(Number(rows["discharge_air_temperature-healthy"].covered_hours) > 0, `${rule}: healthy peer must be covered`);
    if (rule === "SV-STALE") {
      // #1673: a single sample at the window end leaves 180 min of missing data before it: 3 h covered, 2.5 h stale
      assert.ok(around(rows["discharge_air_temperature-short"].covered_hours, 3) && around(rows["discharge_air_temperature-short"].fault_hours, 2.5), `SV-STALE discharge_air_temperature-short ${JSON.stringify(rows["discharge_air_temperature-short"])}`);
      assert.equal(rows["discharge_air_temperature-fault"].fault_hours, 0, "SV-STALE: a polled sensor is never stale, whatever its values");
      continue;
    }
    assert.equal(rows["discharge_air_temperature-short"].covered_hours, 0, `${rule}: single-sample sensor has 0 coverage`);
    assert.equal(rows["discharge_air_temperature-short"].fault_hours, null, `${rule}: insufficient history stays NULL (not 0)`);
  }
  const rangeFault = bySeries(outA["SV-RANGE"])["discharge_air_temperature-fault"].fault_hours;
  assert.ok(around(rangeFault, 100 / 60), `SV-RANGE must respect supply_fan_operating_status gate (got ${rangeFault} h)`);
  assert.ok(bySeries(outA["SV-SPIKE"])["discharge_air_temperature-fault"].fault_hours > 0, "SV-SPIKE faults on discharge_air_temperature-fault");
  assert.ok(bySeries(outA["SV-FLATLINE"])["discharge_air_temperature-fault"].fault_hours > 0, "SV-FLATLINE faults on discharge_air_temperature-fault");
  assert.ok(bySeries(outA["SV-RATE"])["discharge_air_temperature-fault"].fault_hours > 0, "SV-RATE faults on discharge_air_temperature-fault");
  assert.equal(bySeries(outA["SV-STALE"])["discharge_air_temperature-fault"].fault_hours, 0, "SV-STALE stays 0 when value changes at min 60 and min 155");
});
