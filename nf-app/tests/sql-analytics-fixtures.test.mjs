// #1649 / #1744: the shared hook fixtures (tests/fixtures/sql_analytics_cases.json, generated from pandas by
// scripts/nf/build_sql_analytics_fixtures.py) answered by the NF app's SQL adapters (hooks/lib/sql-analytics.js), the
// same functions the dashboard and the analytics hook call. Python checks the same cases against its SQL twins.
// The cooling case needs the heat-pump mode gate of the full ladder, which the dashboard's one-tier adapter does not
// take; tests/test_sql_mech_cooling.py covers it.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const SA = require("../hooks/lib/sql-analytics.js");
const FIX = JSON.parse(readFileSync(new URL("../../tests/fixtures/sql_analytics_cases.json", import.meta.url), "utf8"));
const CASES = Object.fromEntries(FIX.cases.map((c) => [c.id, c]));
const close = (a, b, label) => assert.ok((a == null && b == null) || Math.abs(a - b) < 1e-9, `${label}: ${a} != ${b}`);

/** One grid over the union of the given [[colName, [[ts, value]]]] series. */
function gridOf(series) {
  const t = [...new Set(series.flatMap(([, pts]) => pts.map(([x]) => x)))].sort((a, b) => a - b);
  const at = new Map(t.map((x, j) => [x, j]));
  const cols = {};
  for (const [k, pts] of series) {
    cols[k] = new Array(t.length).fill(null);
    for (const [x, v] of pts) cols[k][at.get(x)] = v;
  }
  return { t, cols };
}
const col = (frame, name) => frame.rows.filter((r) => r[name] != null).map((r) => [r.ts_ms, r[name]]);

test("fixture: runtime across a DST week, a data gap and a percent command", async () => {
  const c = CASES["runtime-dst-week-gap-percent-command"], o = c.options;
  const e1 = c.frames["equipment-1"], e2 = c.frames["equipment-2"];
  const g = gridOf([["f1", col(e1, "supply_fan_operating_status")], ["o1", col(e1, "outdoor_air_intake_temperature")], ["p2", col(e2, "hw-pump-cmd")]]);
  const plain = { weeks: o.week_starts, occupied: o.occupied_intervals };
  const got = await SA.runtimeFromGrid("duckdb", g, [{ key: "equipment-1", motor: "f1", oat: "o1", ...plain },
    { key: "equipment-2", motor: "p2", oat: null, ...plain }]);
  assert.equal(c.expected.rows.length, 2);
  for (const w of c.expected.rows) {
    const r = got.get(w.equipment_id).get(w.week_start);
    assert.ok(r, `${w.equipment_id} ${w.week_label}`);
    close(r.hours, w.hours, `${w.equipment_id} hours`);
    close(r.inHours, w.in_hours, `${w.equipment_id} in_hours`);
    close(r.afterHours, w.after_hours, `${w.equipment_id} after_hours`);
    close(r.oat, w.avg_oat_c, `${w.equipment_id} avg_oat_c`);
    assert.equal(r.partial, w.partial_week);
  }
  assert.equal([...got.values()].reduce((n, m) => n + m.size, 0), c.expected.rows.length, "no extra week rows");
});

test("fixture: economizer with a percent damper and MAT holes", async () => {
  const c = CASES["economizer-percent-damper-mixed_air_temperature-holes"], f = c.frames["equipment-1"];
  const g = gridOf([["fan", col(f, "supply_fan_operating_status")], ["outdoor_air_intake_temperature", col(f, "outdoor_air_intake_temperature")], ["return_air_temperature", col(f, "return_air_temperature")],
    ["mixed_air_temperature", col(f, "mixed_air_temperature")], ["damper", col(f, "outdoor_air_intake_damper_position_command")]]);
  const { summary } = await SA.econFromGrid("duckdb", g);
  const w = c.expected.metrics.rows[0];
  assert.equal(summary.n, w.n_fan_on_samples);
  assert.equal(summary.nIdent, w.n_identifiable);
  close(summary.medianResid, w.median_mat_resid_f, "median residual (SI, despite the legacy _f name)");
  close(summary.maeResid, w.mat_resid_mae_f, "MAE");
  close(SA.ECON_DIAG_DT_MIN_C, w.dt_min_f, "identifiable delta");
});

for (const id of ["web-weather-outage", "web-weather-empty"]) {
  test(`fixture: BAS vs web OAT, ${id}`, async () => {
    const c = CASES[id], f = c.frames["equipment-1"];
    const g = gridOf([["bas", col(f, "outdoor_air_intake_temperature")], ["web", c.web_weather.map((r) => [r.ts_ms, r.value_c])]]);
    const { stats } = await SA.basFromGrid("duckdb", g, { maxAgeMs: c.options.max_age_seconds * 1000 });
    const w = c.expected["equipment-1"];
    assert.equal(stats.n, w.n);
    close(stats.bias, w.bias, "bias");
    close(stats.mae, w.mae, "mae");
    close(stats.maxAbs, w.max_abs, "max_abs");
    close(stats.withinBand, w.within_band, "within_band");
  });
}
