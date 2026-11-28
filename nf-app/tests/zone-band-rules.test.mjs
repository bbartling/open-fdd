// node --test nf-app/tests/zone-band-rules.test.mjs - the occupied zone temperature range reaches the zone comfort FDD rules
// (VAV-1 ZONE_T_LO / ZONE_T_HI, SCHED-1 comfort_low / comfort_high) through the hook's tuning layer, and a RUN on the DuckDB
// engine uses it. (The same run on the Timescale engine is nf-app/timescale/test/timescale.test.mjs.) Explicit per-rule tuning wins.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const fdd = require("../hooks/fdd.js");
const { createEngine, releaseDuckDb } = require("../hooks/lib/engines.js");
const pack = require("../rules/pack-postgres.json");
const Z = require("../hooks/lib/zone-band.js");
const F2C = (f) => (f - 32) * 5 / 9;
const near = (a, b, e = 1e-9) => assert.ok(Math.abs(a - b) < e, `${a} != ${b}`);
after(async () => { await releaseDuckDb(); });

const calendarRow = (zb, revision = 3, site = "S") => ({ site_id: site, rule_id: "OCC-CALENDAR", scope_key: "site", revision, parameters: { version: 1, calendar: { timezone: "America/Chicago", days: {}, ...(zb === undefined ? {} : { zone_band: zb }) } } });
const ruleRow = (ruleId, scope, params, revision = 7, site = "S") => ({ site_id: site, rule_id: ruleId, scope_key: scope, revision, parameters: { version: 1, params } });
const tuningOf = (rows) => fdd.loadRoleLimitOverrides({ engine: { ruleConfigOverrides: async () => rows }, pack, log: () => {} });
const sqlBand = (sql) => { const m = /zone_air_temperature < ([-0-9.e+]+) OR zone_air_temperature > ([-0-9.e+]+)/.exec(sql); return m ? [Number(m[1]), Number(m[2])] : null; };

test("VAV-1: the saved band becomes ZONE_T_LO / ZONE_T_HI in the rendered SQL, recorded in the run's parameters", async () => {
  const t = await tuningOf([calendarRow({ lo_c: 20, hi_c: 25 })]);
  const r = t.forRule("S", "VAV-A", "VAV-1");
  assert.deepEqual(sqlBand(r.sql), [20, 25]);
  assert.deepEqual(sqlBand(r.timeline_sql), [20, 25], "the timeline renders the same band");
  const zb = r.parameters.zone_band;
  assert.deepEqual([zb.source, zb.rule_id, zb.revision, zb.lo_c, zb.hi_c], ["occupancy_calendar", "OCC-CALENDAR", 3, 20, 25]);
  assert.deepEqual(zb.applied, { zone_t_lo: 20, zone_t_hi: 25 });
  assert.equal(zb.effective.zone_t_lo, 20); assert.equal(zb.effective.zone_t_hi, 25);
  assert.equal(r.configRevision, 3, "recorded against the calendar revision that carried the band");
  console.log(`ZONE-BAND-PROOF VAV-1 run params: ${JSON.stringify(zb.applied)} sql band ${JSON.stringify(sqlBand(r.sql))} (calendar rev ${zb.revision})`);
});

test("SCHED-1: comfort_low / comfort_high follow the band too", async () => {
  const t = await tuningOf([calendarRow({ lo_c: F2C(68), hi_c: F2C(78) })]);
  const r = t.forRule("S", "AHU-A", "SCHED-1");
  const zb = r.parameters.zone_band;
  assert.deepEqual(Object.keys(zb.applied).sort(), ["comfort_high", "comfort_low"]);
  near(zb.applied.comfort_low, F2C(68)); near(zb.applied.comfort_high, F2C(78));
  const shipped = pack.rules["SCHED-1"].sql;
  assert.notEqual(r.sql, shipped);
  assert.match(r.sql, new RegExp(String(F2C(68)).slice(0, 8)));
  console.log(`ZONE-BAND-PROOF SCHED-1 run params: ${JSON.stringify(zb.applied)}`);
});

test("no saved band (or none usable) leaves the shipped 70-75 F rules alone", async () => {
  for (const rows of [[], [calendarRow(undefined)], [calendarRow({ lo_c: 25, hi_c: 20 })], [calendarRow({ lo_c: "x", hi_c: 24 })], [calendarRow(null)], [calendarRow({ lo_c: NaN, hi_c: 24 })]]) {
    const t = await tuningOf(rows);
    assert.equal(t.forRule("S", "VAV-A", "VAV-1"), null, JSON.stringify(rows.map((r) => r.parameters.calendar && r.parameters.calendar.zone_band)));
    assert.equal(t.forRule("S", "AHU-A", "SCHED-1"), null);
  }
  const shipped = sqlBand(pack.rules["VAV-1"].sql); near(shipped[0], Z.DEFAULT_LO_C, 1e-6); near(shipped[1], Z.DEFAULT_HI_C, 1e-6);
});

test("an out-of-range or too-narrow stored band is clamped / widened before it reaches a rule", async () => {
  const wide = (await tuningOf([calendarRow({ lo_c: -5, hi_c: 99 })])).forRule("S", "V", "VAV-1");
  assert.deepEqual(sqlBand(wide.sql).map((x) => +x.toFixed(6)), [+Z.LIMIT_LO_C.toFixed(6), +Z.LIMIT_HI_C.toFixed(6)]);
  const narrow = (await tuningOf([calendarRow({ lo_c: F2C(79), hi_c: F2C(80) })])).forRule("S", "V", "VAV-1");
  const [lo, hi] = sqlBand(narrow.sql);
  near(lo, F2C(78), 1e-6); near(hi, F2C(80), 1e-6);
  assert.ok(hi - lo >= Z.MIN_DEADBAND_K - 1e-6);
});

test("precedence: shipped < site band < site rule tuning < equipment rule tuning (an explicit per-rule value always wins)", async () => {
  const band = calendarRow({ lo_c: 20, hi_c: 25 });
  // site rule tuning of ONE key: that key wins, the band supplies the other
  const site = (await tuningOf([band, ruleRow("VAV-1", "site", { zone_t_hi: 26.5 })])).forRule("S", "VAV-A", "VAV-1");
  assert.deepEqual(sqlBand(site.sql), [20, 26.5]);
  assert.deepEqual(site.parameters.zone_band.applied, { zone_t_lo: 20 });
  assert.equal(site.parameters.rule_params.overrides.site.zone_t_hi, 26.5);
  // both keys tuned on the rule: the band is ignored for this rule, and the run says so
  const both = (await tuningOf([band, ruleRow("VAV-1", "site", { zone_t_lo: 19, zone_t_hi: 27 })])).forRule("S", "VAV-A", "VAV-1");
  assert.deepEqual(sqlBand(both.sql), [19, 27]);
  assert.deepEqual(both.parameters.zone_band.applied, {}); assert.equal(both.parameters.zone_band.skipped.length, 1);
  // equipment tuning beats the site tuning and the band; another equipment still follows the band
  const rows = [band, ruleRow("VAV-1", "site", { zone_t_lo: 19, zone_t_hi: 27 }), ruleRow("VAV-1", "equip:VAV-B", { zone_t_hi: 24.5 }, 9)];
  const t = await tuningOf(rows);
  assert.deepEqual(sqlBand(t.forRule("S", "VAV-B", "VAV-1").sql), [19, 24.5]);
  assert.deepEqual(sqlBand(t.forRule("S", "VAV-A", "VAV-1").sql), [19, 27]);
  // SCHED-1 keys are comfort_low / comfort_high
  const sch = (await tuningOf([band, ruleRow("SCHED-1", "site", { comfort_high: 26 })])).forRule("S", "AHU-A", "SCHED-1");
  assert.equal(sch.parameters.zone_band.applied.comfort_low, 20); assert.equal(sch.parameters.rule_params.effective.comfort_high, 26);
  // another site's band never leaks
  const other = await tuningOf([calendarRow({ lo_c: 20, hi_c: 25 }, 3, "OTHER")]);
  assert.equal(other.forRule("S", "VAV-A", "VAV-1"), null);
  assert.deepEqual(sqlBand(other.forRule("OTHER", "VAV-A", "VAV-1").sql), [20, 25]);
  // an explicit rule override that is not about the band is untouched by it
  const conf = (await tuningOf([band, ruleRow("VAV-1", "site", { confirm_min: 30 })])).forRule("S", "VAV-A", "VAV-1");
  assert.deepEqual(sqlBand(conf.sql), [20, 25]);
});

test("changing the band changes the rule hash and config hash (the next run is recorded against the new band)", async () => {
  const a = (await tuningOf([calendarRow({ lo_c: 20, hi_c: 25 }, 3)])).forRule("S", "V", "VAV-1");
  const b = (await tuningOf([calendarRow({ lo_c: 19, hi_c: 26 }, 4)])).forRule("S", "V", "VAV-1");
  assert.notEqual(a.ruleHash, b.ruleHash); assert.notEqual(a.configHash, b.configHash);
  assert.deepEqual([a.configRevision, b.configRevision], [3, 4]);
});

// ---- a real run on the DuckDB engine ------------------------------------------------------------------------------
const grid = Array.from({ length: 288 }, (_, i) => Date.parse("2026-11-05T00:00:00Z") + i * 300e3);
const historyColumns = pack.contract.history.filter((c) => c.name !== "equipment_id" && c.name !== "timestamp_utc").map((c) => ({ name: c.name, type: c.type }));
// the zone ramps 16 -> 30 C over the day (14 K), 5 min samples
const rows = (occupancy) => grid.map((ts, i) => ({ equipment_id: "Z", ts, zone_air_temperature: 16 + (14 * i) / 287, occupancy_status: occupancy, supply_fan_command: 1, supply_fan_operating_status: 1 }));
async function run(ruleId, occupancy, tuned) {
  const e = await createEngine({ kind: "duckdb", pack });
  try {
    await e.load({ historyColumns, history: rows(occupancy), weather: [] });
    return (await e.query(ruleId, tuned ? { sql: tuned.sql, timeline_sql: tuned.timeline_sql } : undefined))[0];
  } finally { await e.close(); }
}

test("DuckDB run, VAV-1: widening the saved band to 18-26 C cuts the fault share; it equals tuning the rule by hand", async () => {
  const def = await run("VAV-1", 1, null);
  const t = await tuningOf([calendarRow({ lo_c: 18.5, hi_c: 26 })]);
  const banded = await run("VAV-1", 1, t.forRule("S", "Z", "VAV-1"));
  const manual = await run("VAV-1", 1, (await tuningOf([ruleRow("VAV-1", "site", { zone_t_lo: 18.5, zone_t_hi: 26 })])).forRule("S", "Z", "VAV-1"));
  console.log(`ZONE-BAND-PROOF DuckDB VAV-1 fault_pct: default 21.1-23.9 C = ${def.fault_pct.toFixed(2)} %, saved band 18.5-26 C = ${banded.fault_pct.toFixed(2)} % (same as manual tuning ${manual.fault_pct.toFixed(2)} %)`);
  assert.ok(banded.fault_pct < def.fault_pct - 20, "a wider band means fewer faults");
  assert.equal(banded.fault_pct, manual.fault_pct); assert.equal(banded.fault_hours, manual.fault_hours);
  // expected: samples below 18.5 or above 26 of the 16..30 ramp = (2.5 + 4) / 14 of the day, less the 15 min confirm window
  assert.ok(Math.abs(banded.fault_pct - (6.5 / 14) * 100) < 3, `expected ~${((6.5 / 14) * 100).toFixed(1)}, got ${banded.fault_pct}`);
  const narrow = await run("VAV-1", 1, (await tuningOf([calendarRow({ lo_c: 21.5, hi_c: 22.7 })])).forRule("S", "Z", "VAV-1"));
  assert.ok(narrow.fault_pct > def.fault_pct, "a narrower band means more faults");
});

test("DuckDB run, SCHED-1 (unoccupied fan run with the zone already comfortable): the saved band decides what 'comfortable' is", async () => {
  const def = await run("SCHED-1", 0, null);
  const wide = await run("SCHED-1", 0, (await tuningOf([calendarRow({ lo_c: 18.5, hi_c: 26 })])).forRule("S", "Z", "SCHED-1"));
  console.log(`ZONE-BAND-PROOF DuckDB SCHED-1 fault_pct: default 21.1-23.9 C = ${def.fault_pct.toFixed(2)} %, saved band 18.5-26 C = ${wide.fault_pct.toFixed(2)} %`);
  assert.ok(wide.fault_pct > def.fault_pct + 15, "more of the day counts as comfortable with the wider band");
});