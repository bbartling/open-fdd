// #1649: the NF hook's SQL analytics renderers (hooks/lib/sql-analytics.js) produce exactly the SQL the Python renderers
// (open_fdd/analytics/sql_*.py) produce, so the pandas == SQL parity proven in Python holds for the app's SQL too.
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const SA = require("../hooks/lib/sql-analytics.js");
const root = fileURLToPath(new URL("../..", import.meta.url));
const py = process.env.OPENFDD_PYTHON || "python3";

const pyRender = (code) => JSON.parse(execFileSync(py, ["-c", `import json, sys; sys.path.insert(0, ${JSON.stringify(root)})\n${code}`],
  { encoding: "utf8" }));

const oats = [["AHU-1", "AHU-1/oat"], ["o'brien", "k'1"]];
const weeks = [["AHU-1", 1772416800000], ["AHU-1", 1773018000000]];
const occupied = [["AHU-1", 1772438400000, 1772478000000]];
const plan = {
  candidates: [["CH-1", 1, 0, "CH-1/chiller-status", "on", null], ["CH-1", 3, 0, "CH-1/chiller-amps", "above", 5.0],
    ["RTU-1", 3, 0, "RTU-1/s1", "on", null]],
  gates: [["HP-1", "HP-1/mode"]],
  oats: [["CH-1", "CH-1/oat"]],
};
const roles = [["AHU-1", "fan", "AHU-1/f"], ["AHU-1", "oat", "AHU-1/o"], ["AHU-1", "damper_position", "AHU-1/d"]];
const pairs = [["AHU-1", "AHU-1/oat", "web", 5400000], ["AHU-2", "AHU-2/oat", "web", 1800000]];

test("pyRepr matches Python repr for the floats the renderers emit", () => {
  const vals = [5.0, 0.638888889, 1500.0, 15.555555555555556, 1e-05, 0.0001, 2.0, 5.555555555555555, -3.25];
  const want = pyRender(`print(json.dumps([repr(float(v)) for v in ${JSON.stringify(vals)}]))`);
  assert.deepEqual(vals.map(SA.pyRepr), want);
});

for (const engine of ["sqlite", "postgres"]) {
  test(`${engine}: runtime / mech / economizer / BAS-web render byte-identical to Python`, () => {
    const want = pyRender(`
from open_fdd.analytics.sql_runtime import render_runtime_sql
from open_fdd.analytics.sql_mech_cooling import Plan, render_mech_bins_sql
from open_fdd.analytics.sql_economizer import render_economizer_sql
from open_fdd.analytics.sql_bas_web import render_bas_web_sql
eng = ${JSON.stringify(engine)}
out = {
  "rt": render_runtime_sql(eng),
  "rt_full": render_runtime_sql(eng, site_id="s'1", equipment_ids=["AHU-1", "x'y"], start_ms=1772416800000,
      end_ms=1773021600000, oats=${JSON.stringify(oats)}, weeks=${JSON.stringify(weeks)}, occupied=${JSON.stringify(occupied)}),
  "rt_occ_empty": render_runtime_sql(eng, occupied=[]),
  "mech": render_mech_bins_sql(eng, Plan(${JSON.stringify(plan.candidates).replace(/null/g, "None")}, ${JSON.stringify(plan.gates)}, ${JSON.stringify(plan.oats)}, {})),
  "mech_empty": render_mech_bins_sql(eng, Plan([], [], [], {})),
  "econ": render_economizer_sql(eng, ${JSON.stringify(roles)}, start_ms=1, end_ms=2),
  "basweb": render_bas_web_sql(eng, ${JSON.stringify(pairs)}, band_c=1.5, start_ms=1772416800000),
  "basweb_pts": __import__("open_fdd.analytics.sql_bas_web", fromlist=["x"]).render_bas_web_points_sql(eng, ${JSON.stringify(pairs)}, start_ms=1772416800000, end_ms=1773021600000),
  "econ_pts":__import__("open_fdd.analytics.sql_economizer", fromlist=["x"]).render_economizer_points_sql(eng, ${JSON.stringify(roles)}, start_ms=1, end_ms=2),
}
print(json.dumps(out))
`);
    assert.equal(SA.renderRuntime(engine), want.rt);
    assert.equal(SA.renderRuntime(engine, { siteId: "s'1", equipmentIds: ["AHU-1", "x'y"], startMs: 1772416800000,
      endMs: 1773021600000, oats, weeks, occupied }), want.rt_full);
    assert.equal(SA.renderRuntime(engine, { occupied: [] }), want.rt_occ_empty);
    assert.equal(SA.renderMechBins(engine, plan), want.mech);
    assert.equal(SA.renderMechBins(engine, { candidates: [], gates: [], oats: [] }), want.mech_empty);
    assert.equal(SA.renderEconomizer(engine, roles, { startMs: 1, endMs: 2 }), want.econ);
    assert.equal(SA.renderBasWeb(engine, pairs, { bandC: 1.5, startMs: 1772416800000 }), want.basweb);
    assert.equal(SA.renderBasWebPoints(engine, pairs, { startMs: 1772416800000, endMs: 1773021600000 }), want.basweb_pts);
    assert.equal(SA.renderEconomizerPoints(engine, roles, { startMs: 1, endMs: 2 }), want.econ_pts);
  });
}

test("renderers refuse bad input like the Python ones", () => {
  assert.throws(() => SA.renderRuntime("oracle"), /unknown engine/);
  assert.throws(() => SA.renderRuntime("sqlite", { maxGapSeconds: 0 }), /positive/);
  assert.throws(() => SA.renderRuntime("sqlite", { startMs: 5, endMs: 5 }), /after/);
  assert.throws(() => SA.renderEconomizer("sqlite", [["A", "valve", "k"]]), /unknown economizer role/);
  assert.throws(() => SA.renderBasWeb("sqlite", [["A", "b", "w", -1]]), /max_age_ms/);
  assert.throws(() => SA.renderMechBins("sqlite", { candidates: [["A", 1, 0, "k", "maybe", null]], gates: [], oats: [] }), /proof kind/);
});
