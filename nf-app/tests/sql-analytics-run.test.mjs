// #1649: the NF hook runs the SQL analytics in-process on Node DuckDB and gets the same answers as the Python
// runner on DuckDB (open_fdd.analytics.sql_*).
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const SA = require("../hooks/lib/sql-analytics.js");
const root = fileURLToPath(new URL("../..", import.meta.url));
const py = process.env.OPENFDD_PYTHON || "python3";
const H = 3600000;
const T0 = Date.UTC(2026, 2, 2);   // a Monday

// one AHU: fan status on 06-18 h for 9 days, hourly OAT; percent damper; RAT / MAT for the economizer; a web OAT
function core() {
  const points = [
    { point_key: "AHU-1/fan", equipment_id: "AHU-1", role: "supply_fan_operating_status" },
    { point_key: "AHU-1/oat", equipment_id: "AHU-1", role: "outside_air_temp" },
    { point_key: "AHU-1/return_air_temperature", equipment_id: "AHU-1", role: "return_air_temperature" },
    { point_key: "AHU-1/mixed_air_temperature", equipment_id: "AHU-1", role: "mixed_air_temperature" },
    { point_key: "AHU-1/dmp", equipment_id: "AHU-1", role: "oa_damper" },
    { point_key: "CH-1/st", equipment_id: "CH-1", role: "chiller_operating_status" },
    { point_key: "web", equipment_id: null, role: "weather_service_air_temperature" },
  ];
  const samples = [];
  for (let i = 0; i < 12 * 24 * 9; i++) {
    const t = T0 + i * 300000 + (i % 7) * 1000;            // jittered polls
    const h = ((t - T0) / H) % 24;
    const oat = 12 + 10 * Math.sin(((h - 9) / 24) * 2 * Math.PI);
    const on = h >= 6 && h < 18 ? 1 : 0;
    const dmp = oat < 18 ? 80 : 20;
    samples.push(["AHU-1/fan", t, on], ["AHU-1/return_air_temperature", t, 22], ["AHU-1/mixed_air_temperature", t, 22 + (dmp / 100) * (oat - 22) + 0.3],
      ["AHU-1/dmp", t, dmp], ["CH-1/st", t, oat > 18 ? 1 : 0]);
    if (i % 12 === 0) samples.push(["AHU-1/oat", t, oat], ["web", t + 120000, oat + 0.8]);
  }
  return { points, samples };
}

const cases = {
  runtime: { oats: [["AHU-1", "AHU-1/oat"]], weeks: [["AHU-1", T0 + 6 * H], ["AHU-1", T0 + 7 * 24 * H + 5 * H]],
    occupied: [["AHU-1", T0 + 7 * H, T0 + 18 * H], ["AHU-1", T0 + 31 * H, T0 + 42 * H]] },
  mech: { candidates: [["CH-1", 1, 0, "CH-1/st", "on", null]], gates: [], oats: [["CH-1", "AHU-1/oat"]] },
  econ: [["AHU-1", "fan", "AHU-1/fan"], ["AHU-1", "oat", "AHU-1/oat"], ["AHU-1", "return_air_temperature", "AHU-1/return_air_temperature"],
    ["AHU-1", "mixed_air_temperature", "AHU-1/mixed_air_temperature"], ["AHU-1", "damper_position", "AHU-1/dmp"]],
  basweb: [["AHU-1", "AHU-1/oat", "web", 5400000]],
};

function pythonAnswers({ points, samples }) {
  const code = `
import json, sys
sys.path.insert(0, ${JSON.stringify(root)})
import duckdb
from open_fdd.analytics.sql_anomaly import create_core, load_core
from open_fdd.analytics.sql_runtime import run_runtime_sql
from open_fdd.analytics.sql_mech_cooling import Plan, run_mech_bins_sql
from open_fdd.analytics.sql_economizer import run_economizer_sql
from open_fdd.analytics.sql_bas_web import run_bas_web_sql
d = json.load(sys.stdin)
conn = duckdb.connect()
create_core(conn, "duckdb")
load_core(conn, "duckdb", [dict(p, site_id="local") for p in d["points"]], [("local", k, t, v) for k, t, v in d["samples"]])
c = d["cases"]
out = {
  "runtime": run_runtime_sql(conn, "duckdb", oats=c["runtime"]["oats"], weeks=c["runtime"]["weeks"], occupied=c["runtime"]["occupied"]),
  "mech": run_mech_bins_sql(conn, "duckdb", Plan(c["mech"]["candidates"], c["mech"]["gates"], c["mech"]["oats"],
          {("CH-1", 1, 0): ("chiller_operating_status", "chiller_operating_status", "direct")})),
  "econ": run_economizer_sql(conn, "duckdb", c["econ"]),
  "basweb": run_bas_web_sql(conn, "duckdb", c["basweb"]),
}
print(json.dumps(out))
`;
  return JSON.parse(execFileSync(py, ["-c", code], { input: JSON.stringify({ points, samples, cases }), encoding: "utf8", maxBuffer: 64 << 20 }));
}

const close = (a, b) => (a == null && b == null) || (typeof a === "number" && typeof b === "number" && Math.abs(a - b) < 1e-9) || a === b;

function sameRows(got, want, label) {
  assert.equal(got.length, want.length, `${label}: row count`);
  want.forEach((w, i) => {
    for (const [k, v] of Object.entries(w)) {
      if (!(k in got[i])) continue;   // Python adds labels (bin_label, proof labels) the raw query does not return
      const g = typeof v === "boolean" ? Boolean(got[i][k]) : got[i][k];
      assert.ok(close(g, v), `${label} row ${i} ${k}: ${g} != ${v}`);
    }
  });
}

test("DuckDB core: every analytic answers exactly as the Python runner on the same samples", async () => {
  const data = core();
  const want = pythonAnswers(data);
  const db = await SA.openCore("duckdb", data.points, data.samples);
  try {
    sameRows(await db.query(SA.renderRuntime("postgres", cases.runtime)), want.runtime, "runtime");
    sameRows(await db.query(SA.renderMechBins("postgres", cases.mech)), want.mech, "mech");
    sameRows(await db.query(SA.renderEconomizer("postgres", cases.econ)), want.econ, "economizer");
    sameRows((await db.query(SA.renderBasWeb("postgres", cases.basweb))).map((r) => ({ ...r, within_band: r.n_within / r.n })), want.basweb, "bas-web");
    assert.ok(want.runtime.length >= 2 && want.mech.length >= 1 && want.econ.length === 1 && want.basweb.length === 1);
  } finally {
    db.close();
  }
});
