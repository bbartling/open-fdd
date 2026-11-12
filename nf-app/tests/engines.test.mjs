// node --test nf-app/tests/engines.test.mjs
// Parity of the two SQL engines (PGlite = exact Postgres, sql.js = translated SQLite) over the whole rule pack.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { createEngine } = require("../hooks/lib/engines.js");
const { buildDataset } = require("./fixtures/synthetic_dataset.js");

const rulesDir = new URL("../rules/", import.meta.url);
const readPack = (name) => JSON.parse(readFileSync(new URL(name, rulesDir), "utf8"));
const pgPack = readPack("pack-postgres.json");
const litePack = readPack("pack-sqlite.json");

// Documented, accepted differences between the engines: rule_id -> reason. Keep empty unless justified.
const KNOWN_DIVERGENCE = {};

const REL_TOL = 1e-6;
const close = (a, b) => {
  if (a === null || b === null || a === undefined || b === undefined) return (a ?? null) === (b ?? null);
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-9 + REL_TOL * Math.max(Math.abs(a), Math.abs(b));
  return a === b;
};

const sortRows = (rows) => [...rows].sort((x, y) =>
  String(x.equipment_id).localeCompare(String(y.equipment_id)) || String(x.series_id || "").localeCompare(String(y.series_id || "")) ||
  String(x.sensor_role || "").localeCompare(String(y.sensor_role || "")));

/** Returns a list of difference strings (empty = match). */
function diffRows(pg, lite) {
  const out = [];
  const a = sortRows(pg), b = sortRows(lite);
  if (a.length !== b.length) return [`row count ${a.length} (pglite) vs ${b.length} (sqlite)`];
  a.forEach((ra, i) => {
    const rb = b[i];
    if (ra.equipment_id !== rb.equipment_id) out.push(`equipment_id ${ra.equipment_id} vs ${rb.equipment_id}`);
    const keys = new Set([...Object.keys(ra), ...Object.keys(rb)]);
    for (const k of keys) if (!close(ra[k], rb[k])) out.push(`${ra.equipment_id}.${k}: pglite=${ra[k]} sqlite=${rb[k]}`);
  });
  return out;
}

let input, pg, lite;
const results = { pg: {}, lite: {}, errors: {}, tlPg: {}, tlLite: {} };

before(async () => {
  input = buildDataset(pgPack, { equipments: 2, days: 3, stepSeconds: 300 });
  pg = await createEngine({ kind: "pglite", pack: pgPack });
  lite = await createEngine({ kind: "sqlite", pack: litePack });
  await pg.load(input);
  await lite.load(input);
  for (const rid of Object.keys(pgPack.rules)) {
    try { results.pg[rid] = await pg.query(rid); } catch (e) { results.errors[`pglite ${rid}`] = e.message; }
    if (litePack.rules[rid]) {
      try { results.lite[rid] = await lite.query(rid); } catch (e) { results.errors[`sqlite ${rid}`] = e.message; }
    }
    try { results.tlPg[rid] = await pg.timeline(rid); } catch (e) { results.errors[`pglite timeline ${rid}`] = e.message; }
    if (litePack.rules[rid]) {
      try { results.tlLite[rid] = await lite.timeline(rid); } catch (e) { results.errors[`sqlite timeline ${rid}`] = e.message; }
    }
  }
}, { timeout: 120000 });

after(async () => {
  await pg?.close();
  await lite?.close();
});

test("dataset covers every contract column (typed NULL for the rest) on both engines", () => {
  assert.equal(input.history.length, 2 * 864 - 40);
  assert.ok(Object.keys(pgPack.contract.history).length > 60);
  assert.deepEqual(Object.keys(pgPack.contract).sort(),
    ["history", "sensor_history", "utility_interval", "utility_monthly", "weather"]);
});

test("every rule runs without error on both engines", () => {
  assert.deepEqual(results.errors, {});
});

test("sqlite pack: every rule translated or skipped with a reason", () => {
  const all = Object.keys(pgPack.rules);
  for (const rid of all) assert.ok(litePack.rules[rid] || litePack.skipped[rid], `${rid} neither translated nor skipped`);
  for (const [rid, why] of Object.entries(litePack.skipped)) assert.ok(why.length > 10, `${rid} skipped without a reason`);
});

test("engines match rule by rule (rows by equipment_id, numerics within 1e-6 relative)", async (t) => {
  let matched = 0, skipped = 0, nonZero = 0, diverged = 0;
  const lines = [];
  for (const rid of Object.keys(pgPack.rules)) {
    if (!litePack.rules[rid]) { skipped++; lines.push(`skip  ${rid}: ${litePack.skipped[rid]}`); continue; }
    await t.test(rid, () => {
      const d = diffRows(results.pg[rid] || [], results.lite[rid] || []);
      if (KNOWN_DIVERGENCE[rid]) { if (d.length) diverged++; return; }
      assert.deepEqual(d, [], `${rid} differs: ${d.slice(0, 5).join("; ")}`);
    });
    const d = diffRows(results.pg[rid] || [], results.lite[rid] || []);
    if (!d.length) matched++;
    if ((results.pg[rid] || []).some((r) => Number(r.fault_hours) > 0)) nonZero++;
  }
  const total = Object.keys(pgPack.rules).length;
  console.log(`# parity: ${matched}/${total} rules match, ${skipped} skipped, ${diverged} known divergences; ` +
    `${nonZero} rules report fault_hours > 0 on the synthetic data`);
  for (const l of lines) console.log("# " + l);
  assert.ok(nonZero >= 30, `only ${nonZero} rules produced fault_hours > 0: the dataset does not exercise the pack`);
});

// ---- per-timestamp fault timeline (5.0.3): timeline_sql parity + consistency with the rule's own aggregate ----
const NO_TIMELINE = ["AVG-ZONE-TEMP", "FAN-RUNTIME-HOURS", "FAULT-ELAPSED-HOURS", "FCU-DEADBAND", "FCU-MODE-CYCLE", "FCU-SENSOR-NULL",
  "UTIL-INTERVAL", "UTIL-MONTHLY", "ZONE-COMFORT-PCT"];

test("timeline_sql: the same rules have one on both packs; the rest say why they have none", () => {
  const withTl = (pack) => Object.entries(pack.rules).filter(([, r]) => r.timeline_sql).map(([k]) => k);
  assert.deepEqual(withTl(pgPack), withTl(litePack));
  assert.equal(withTl(pgPack).length, Object.keys(pgPack.rules).length - NO_TIMELINE.length);
  for (const rid of NO_TIMELINE) {
    assert.equal(pgPack.rules[rid].timeline_sql, null, rid);
    assert.equal(litePack.rules[rid].timeline_sql, null, rid);
    assert.ok(pgPack.rules[rid].timeline_reason, `${rid} has no timeline_reason`);
  }
  for (const rid of withTl(pgPack)) assert.equal(pgPack.rules[rid].timeline_reason, "", rid);
});

test("timeline_sql: PGlite == SQLite for every rule (rows, timestamps, confirmed, held seconds)", async (t) => {
  let rules = 0, rowsTotal = 0;
  for (const rid of Object.keys(pgPack.rules)) {
    if (!pgPack.rules[rid].timeline_sql) { assert.deepEqual(results.tlPg[rid], [], rid); continue; }
    rules++;
    await t.test(rid, () => {
      const a = results.tlPg[rid], b = results.tlLite[rid];
      assert.equal(a.length, b.length, `${rid}: row count ${a.length} (pglite) vs ${b.length} (sqlite)`);
      assert.ok(a.length > 0, `${rid}: timeline is empty`);
      const perSeries = pgPack.rules[rid].output_columns.includes("series_id");
      assert.deepEqual(Object.keys(a[0]), perSeries
        ? ["equipment_id", "series_id", "sensor_role", "ts_epoch", "confirmed", "held_seconds"]
        : ["equipment_id", "ts_epoch", "confirmed", "held_seconds"]);
      const key = (r) => `${r.equipment_id}|${r.series_id || ""}|${r.sensor_role || ""}|${Number(r.ts_epoch).toFixed(3)}`;
      const by = new Map(b.map((r) => [key(r), r]));
      for (const r of a) {
        const o = by.get(key(r));
        assert.ok(o, `${rid}: ${key(r)} missing on sqlite`);
        assert.equal(Number(r.confirmed), Number(o.confirmed), `${rid} ${key(r)} confirmed`);
        assert.ok(close(Number(r.held_seconds), Number(o.held_seconds)), `${rid} ${key(r)} held ${r.held_seconds} vs ${o.held_seconds}`);
      }
      rowsTotal += a.length;
    });
  }
  console.log(`# timeline parity: ${rules} rules, ${rowsTotal} rows`);
});

test("timeline_sql: confirmed seconds add up to the rule's fault_hours (the lane and the number are the same fact)", () => {
  let checked = 0, nonZero = 0;
  for (const rid of Object.keys(litePack.rules)) {
    if (!litePack.rules[rid].timeline_sql) continue;
    for (const row of results.lite[rid] || []) {
      if (row.fault_hours == null) continue;
      const mine = results.tlLite[rid].filter((r) => r.equipment_id === row.equipment_id &&
        (row.series_id == null || r.series_id === row.series_id) && (row.sensor_role == null || r.sensor_role === row.sensor_role));
      const hours = mine.reduce((a, r) => a + (Number(r.confirmed) === 1 ? Number(r.held_seconds) : 0), 0) / 3600;
      assert.ok(close(hours, Number(row.fault_hours)), `${rid} ${row.equipment_id}${row.series_id ? `/${row.series_id}` : row.sensor_role ? `/${row.sensor_role}` : ""}: timeline ${hours} h vs fault_hours ${row.fault_hours}`);
      checked++;
      if (hours > 0) nonZero++;
    }
  }
  assert.ok(checked >= 100 && nonZero >= 20, `checked ${checked}, ${nonZero} with fault time`);
});

test("output columns match the pack's declared output_columns", () => {
  for (const [rid, rule] of Object.entries(litePack.rules)) {
    const rows = results.lite[rid] || [];
    if (rows.length) assert.deepEqual(Object.keys(rows[0]).sort(), [...rule.output_columns].sort(), rid);
  }
});

test("all five SV sweeps keep same-role points separate and return coverage per series", () => {
  const sweeps = ["SV-RATE", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE"];
  const rowsFor = (rule, equipment) => (results.lite[rule] || []).filter((r) => r.equipment_id === equipment);
  for (const rid of sweeps) {
    const rows = rowsFor(rid, "AHU-1");
    assert.ok(rows.length > 1, `${rid} has multiple per-sensor rows`);
    assert.equal(new Set(rows.map((r) => r.series_id)).size, rows.length, `${rid} keeps unique series IDs`);
    assert.ok(rows.every((r) => Object.hasOwn(r, "covered_hours")), `${rid} exposes covered hours`);
    const sat = rows.filter((r) => r.sensor_role === "sat");
    assert.equal(sat.length, 2, `${rid} retains duplicate SAT bindings as two sensor rows`);
  }
});

test("fault rules see a sick unit and a healthy unit differently", () => {
  const byEq = (rid) => Object.fromEntries((results.lite[rid] || []).map((r) => [r.equipment_id, r]));
  // fan cmd on / status off and OA-T vs web disagreement are planted on AHU-2 only
  assert.ok(Number(byEq("CMD-1")["AHU-2"]?.fault_hours ?? 0) > Number(byEq("CMD-1")["AHU-1"]?.fault_hours ?? 0));
});

test("pack-*.json are fresh (build_sql_pack.py --check)", (t) => {
  const script = fileURLToPath(new URL("../../scripts/nf/build_sql_pack.py", import.meta.url));
  for (const py of ["python3", "python"]) {
    const r = spawnSync(py, [script, "--check"], { encoding: "utf8" });
    if (r.error) continue; // interpreter not installed
    if (r.status === 9009 || /was not found|Microsoft Store/.test(r.stderr || "")) continue; // Windows launcher stub
    assert.equal(r.status, 0, `pack JSON is stale: run python scripts/nf/build_sql_pack.py\n${r.stdout}${r.stderr}`);
    return;
  }
  t.skip("python not available");
});

// ---- one declared scale per column (issue #1541) ----------------------------------------------
// sql/fdd/role_scales.json: command/position roles are FRACTIONS 0-1, statuses are 0/1, humidity %RH 0-100, the rest
// physical SI. The SQL rules no longer guess a scale by magnitude. The hook's siPlan brings each point to its role's
// scale from the DECLARED unit/kind: "%" -> /100, ratio/fraction -> as is, no unit -> role skipped (not assessed).
const hook = require("../hooks/fdd.js");
const catalog = JSON.parse(readFileSync(new URL("../static/fdd-catalog.json", import.meta.url), "utf8"));
const GRID_STEP = 300, GRID_N = 288, GRID_T0 = Date.parse("2026-11-05T00:00:00Z");
const GRID = Array.from({ length: GRID_N }, (_, i) => GRID_T0 + i * GRID_STEP * 1e3);

/** spec: {role: {value|fn(i), units, kind?}} -> { input, plan } through the hook's real siPlan + buildInput. */
function hookInput(pack, spec, logs = []) {
  const roles = {}, hist = {};
  for (const [role, s] of Object.entries(spec)) {
    roles[role] = { uuid: role, name: role, units: s.units, kind: s.kind };
    hist[role] = new Map(GRID.map((t, i) => [t, typeof s.fn === "function" ? s.fn(i) : s.value]));
  }
  const plan = hook.siPlan(roles, catalog, (m) => logs.push(m), new Set());
  for (const x of plan.skipped) delete roles[x];
  const input = hook.buildInput({ equipId: "AHU-1", siteId: "s", roles, hist, grid: GRID, pack, si: plan });
  return { input, plan, roles };
}
const ENGINES = [["pglite", () => pg, () => pgPack], ["sqlite", () => lite, () => litePack]];
async function runRule(kind, rule, spec, logs) {
  const [, getEngine, getPack] = ENGINES.find((e) => e[0] === kind);
  const { input, plan } = hookInput(getPack(), spec, logs);
  if (!input.history.length) return { row: null, plan, input };
  await getEngine().load(input);
  return { row: (await getEngine().query(rule)).find((r) => r.equipment_id === "AHU-1") || null, plan, input };
}
const fh = (r) => (r.row ? Number(r.row.fault_hours) : 0);

const FC1_BASE = { duct_static: { value: 100, units: "Pa" }, duct_static_sp: { value: 250, units: "Pa" } };   // far below setpoint
const PCT_CASES = [[0, false], [0.5, false], [1, false], [2, false], [99, true], [100, true]];
for (const [kind] of ENGINES) {
  test(`FC1 full-fan gate, declared-% fan command through the hook (${kind}): 0/0.5/1/2 % are not full fan, 99/100 % are`, async () => {
    for (const [pct, full] of PCT_CASES) {
      const r = await runRule(kind, "FC1", { ...FC1_BASE, fan_cmd: { value: pct, units: "%" } });
      assert.equal(fh(r) > 0, full, `fan ${pct} % -> fault_hours ${fh(r)}`);
    }
  });

  test(`FC1 on fraction inputs (${kind}): 0.01 is not full fan, 0.99 is, no magnitude guess`, async () => {
    for (const [frac, full] of [[0.01, false], [0.02, false], [0.5, false], [0.99, true], [1, true]]) {
      const r = await runRule(kind, "FC1", { ...FC1_BASE, fan_cmd: { value: frac, units: "ratio" } });
      assert.equal(r.plan.convert.fan_cmd(frac), frac, "a ratio unit is passed through as is");
      assert.equal(fh(r) > 0, full, `fan fraction ${frac} -> fault_hours ${fh(r)}`);
    }
  });

  test(`FC1 with a UNITLESS fan command (${kind}): the role is skipped and logged, the rule is not assessed`, async () => {
    const logs = [];
    for (const v of [1, 80, 0.8]) {
      const r = await runRule(kind, "FC1", { ...FC1_BASE, fan_cmd: { value: v, units: "" } }, logs);
      assert.ok(r.plan.skipped.has("fan_cmd"), `unitless fan_cmd=${v} is skipped`);
      assert.equal(r.input.history.some((row) => "fan_cmd" in row), false, "no fan_cmd value reaches SQL");
      // FC1 requires fan_cmd: with the role gone the hook filters the rule out (see runFdd), so no result is published
      const bound = ["duct_static", "duct_static_sp", "fan_cmd"].filter((x) => !r.plan.skipped.has(x));
      assert.deepEqual(bound, ["duct_static", "duct_static_sp"]);
    }
    assert.ok(logs.some((m) => /fan_cmd.*no unit/.test(m)), `logged: ${logs.join(" | ")}`);
  });

  // one valve (VAV-3 reheat), one damper (ECON-1 stuck closed), one pump (CHW-2 dp low at max pump speed)
  test(`valve / damper / pump rules on declared-% and fraction inputs (${kind})`, async () => {
    const reheat = (cmd) => ({ oa_t: { value: 30, units: "°C" }, zone_flow: { value: 100, units: "L/s" }, fan_status: { value: 1, units: "", kind: "Bool" }, reheat_valve_pct: cmd });
    for (const [cmd, fault] of [[{ value: 1, units: "%" }, false], [{ value: 0.01, units: "ratio" }, false], [{ value: 99, units: "%" }, true], [{ value: 0.99, units: "fraction" }, true]]) {
      assert.equal(fh(await runRule(kind, "VAV-3", reheat(cmd))) > 0, fault, `VAV-3 reheat ${JSON.stringify(cmd)}`);
    }
    const econ = (cmd) => ({ oa_t: { value: 25, units: "°C" }, fan_cmd: { value: 100, units: "%" }, oa_damper_pct: cmd });
    for (const [cmd, fault] of [[{ value: 1, units: "%" }, true], [{ value: 0.01, units: "ratio" }, true], [{ value: 99, units: "%" }, false], [{ value: 0.99, units: "ratio" }, false]]) {
      assert.equal(fh(await runRule(kind, "ECON-1", econ(cmd))) > 0, fault, `ECON-1 damper ${JSON.stringify(cmd)} (stuck closed = < 5 % open)`);
    }
    const pump = (cmd) => ({ chw_dp: { value: 1000, units: "Pa" }, chw_dp_sp: { value: 50000, units: "Pa" }, pump_status: { value: 1, units: "", kind: "Bool" }, chw_pump_cmd: cmd });
    for (const [cmd, fault] of [[{ value: 1, units: "%" }, false], [{ value: 0.01, units: "ratio" }, false], [{ value: 99, units: "%" }, true], [{ value: 0.99, units: "ratio" }, true]]) {
      assert.equal(fh(await runRule(kind, "CHW-2", pump(cmd))) > 0, fault, `CHW-2 pump ${JSON.stringify(cmd)}`);
    }
    // a unitless valve / damper / pump command is skipped, so the rule has no input for it (not assessed)
    for (const [rule, spec, role] of [["VAV-3", reheat({ value: 99, units: "" }), "reheat_valve_pct"], ["ECON-1", econ({ value: 1, units: "" }), "oa_damper_pct"], ["CHW-2", pump({ value: 99, units: "" }), "chw_pump_cmd"]]) {
      const r = await runRule(kind, rule, spec);
      assert.ok(r.plan.skipped.has(role), `${rule}: unitless ${role} skipped`);
    }
  });

  // PID-HUNT-1 compares the control output in PERCENT POINTS (span / deadband / variation parameters are points):
  // fraction x 100 happens once in the rule. Before #1541 it guessed: a stored 1 stayed 1 point, 0.99 became 99.
  test(`PID-HUNT-1 semantics (${kind}): a full-stroke flip is hunting, a 0 <-> 1 % wiggle is not`, async () => {
    const fan = { value: 1, units: "", kind: "Bool" };
    const flip = (hi, units) => ({ oa_damper_pct: { fn: (i) => (i % 2 ? hi : 0), units }, fan_status: fan });
    assert.ok(fh(await runRule(kind, "PID-HUNT-1", flip(100, "%"))) > 0, "0 <-> 100 % flips every sample: hunting");
    assert.ok(fh(await runRule(kind, "PID-HUNT-1", flip(1, "ratio"))) > 0, "0 <-> 1.0 fraction (full stroke): hunting");
    assert.equal(fh(await runRule(kind, "PID-HUNT-1", flip(1, "%"))), 0, "0 <-> 1 % (declared) is a 1 point span, below MINIMUM_SPAN_PCT: not hunting");
    assert.equal(fh(await runRule(kind, "PID-HUNT-1", flip(0.01, "ratio"))), 0, "0 <-> 0.01 fraction is the same 1 point span");
  });
}

test("siPlan: role scales decide, per declared unit and kind (fraction / boolean / humidity / physical)", () => {
  const roles = {
    fan_cmd: { uuid: "a", units: "%" }, oa_damper_pct: { uuid: "b", units: "percent" },
    chw_pump_cmd: { uuid: "c", units: "ratio" }, tower_fan_cmd: { uuid: "d", units: "", kind: "Bool" },
    htg_valve_pct: { uuid: "e", units: "" }, clg_valve_pct: { uuid: "f", units: "degC" },
    oa_h: { uuid: "g", units: "%RH" }, zone_rh: { uuid: "h", units: "%" },
    fan_status: { uuid: "i", units: "", kind: "Bool" }, pump_status: { uuid: "j", units: "%" }, chiller_status: { uuid: "k", units: "" },
    sat: { uuid: "l", units: "degF" },
  };
  const plan = hook.siPlan(roles, catalog);
  assert.equal(plan.convert.fan_cmd(50), 0.5);
  assert.equal(plan.convert.oa_damper_pct(100), 1);
  assert.equal(plan.convert.chw_pump_cmd(0.25), 0.25, "ratio unit: already a fraction");
  assert.equal(plan.convert.tower_fan_cmd(1), 1, "Bool kind: 0/1 is a valid fraction");
  assert.ok(plan.skipped.has("htg_valve_pct"), "unitless fraction role: skipped, never guessed");
  assert.ok(plan.skipped.has("clg_valve_pct"), "a fraction role bound to a temperature unit is a wrong binding");
  assert.equal(plan.convert.oa_h(55), 55, "humidity stays %RH 0-100");
  assert.equal(plan.convert.zone_rh(40), 40);
  assert.equal(plan.unit.fan_cmd, "fraction");
  assert.equal(plan.unit.oa_h, "%");
  // boolean roles: values must be 0/1 on-fractions; anything else is rejected, not thresholded or rescaled
  assert.equal(plan.convert.fan_status(1), 1);
  assert.equal(plan.convert.fan_status(0.6), 0.6, "a resampled bucket is an on-fraction");
  assert.equal(plan.convert.fan_status(2), null, "enum / analog value outside 0..1 is rejected");
  assert.equal(plan.convert.fan_status(75), null);
  assert.equal(plan.convert.chiller_status(1), 1);
  assert.equal(plan.convert.chiller_status(3), null);
  assert.equal(plan.convert.pump_status(100), 1, "a declared-% status is /100 first");
  assert.equal(plan.convert.pump_status(50), 0.5);
  assert.deepEqual([...plan.bool].sort(), ["chiller_status", "fan_status", "pump_status"]);
  assert.deepEqual([...plan.scaled].sort(), ["fan_cmd", "oa_damper_pct", "pump_status"]);
  assert.ok(Math.abs(plan.convert.sat(212) - 100) < 1e-9, "physical roles keep the SI conversion");
});

test("rejected boolean values never reach SQL (history row only keeps what passed)", () => {
  const { input } = hookInput(pgPack, { fan_status: { fn: (i) => (i % 2 ? 2 : 1), units: "" }, sat: { value: 55, units: "degF" } });
  assert.ok(input.history.every((r) => r.fan_status === undefined || r.fan_status === 1));
  assert.ok(input.history.some((r) => r.fan_status === undefined) && input.history.every((r) => r.sat !== undefined));
});

test("every history column has a declared scale and every SQL rule reads only fraction/boolean for commands", () => {
  const scales = JSON.parse(readFileSync(new URL("../../sql/fdd/role_scales.json", import.meta.url), "utf8")).roles;
  for (const c of pgPack.contract.history) if (c.name !== "equipment_id" && c.name !== "timestamp_utc") assert.ok(scales[c.name], `${c.name} has a scale`);
  for (const [role, sc] of Object.entries(catalog.roles)) assert.equal(sc.scale, scales[role], `catalog scale of ${role}`);
  for (const [id, r] of Object.entries(pgPack.rules)) assert.doesNotMatch(r.sql, />=? *1\.5\b|> *1\.0 *THEN|\/ *100\.0 *ELSE/, `${id}: magnitude guess left in the SQL`);
});

// ---- FAULT-ELAPSED-HOURS honours ZONE_T_LO / ZONE_T_HI in every output (review P1 #4) --------
test("FAULT-ELAPSED-HOURS: a non-default comfort band changes fault_samples, hours and pct together", async () => {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const render = (params) => {
    for (const py of ["python3", "python"]) {
      const r = spawnSync(py, [`${root}sql/fdd/render_rule.py`, "FAULT-ELAPSED-HOURS", "--params", JSON.stringify(params)], { encoding: "utf8" });
      if (!r.error && r.status === 0) return r.stdout;
    }
    return null;
  };
  const rendered = (params) => ({ ...pgPack, rules: { ...pgPack.rules, "FAULT-ELAPSED-HOURS": { ...pgPack.rules["FAULT-ELAPSED-HOURS"], sql: render(params) } } });
  const wide = render({ zone_t_lo: 18, zone_t_hi: 26 });
  if (!wide) return; // python not available
  assert.doesNotMatch(wide, /24\.444444|< 20\.0/, "no hard-coded band left in the rendered SQL");
  // zone_t ramps 16 -> 30 °C over the day; hourly-ish samples on the 5 min grid
  const grid = Array.from({ length: 288 }, (_, i) => Date.parse("2026-11-05T00:00:00Z") + i * 300e3);
  const run = async (params) => {
    const p = rendered(params);
    const e = await createEngine({ kind: "pglite", pack: p });
    try {
      await e.load({
        historyColumns: p.contract.history.filter((c) => c.name !== "equipment_id" && c.name !== "timestamp_utc").map((c) => ({ name: c.name, type: c.type })),
        history: grid.map((ts, i) => ({ equipment_id: "Z", ts, zone_t: 16 + (14 * i) / 287 })),
        weather: [],
      });
      return (await e.query("FAULT-ELAPSED-HOURS"))[0];
    } finally { await e.close(); }
  };
  const def = await run({}), band = await run({ zone_t_lo: 18, zone_t_hi: 26 });
  assert.ok(band.fault_samples < def.fault_samples && band.fault_hours < def.fault_hours, "a wider band means fewer faults");
  // all three outputs measure the same band: samples/hours/pct agree with each other
  for (const r of [def, band]) {
    assert.ok(Math.abs(r.fault_samples / 288 * 100 - r.fault_pct) < 1.0, `samples ${r.fault_samples} vs pct ${r.fault_pct}`);
    assert.ok(Math.abs(r.fault_hours / r.covered_hours * 100 - r.fault_pct) < 1e-6);
  }
  assert.ok(Math.abs(band.fault_samples - 288 * (2 + 4) / 14) < 3, `expected ~${288 * 6 / 14} samples outside 18-26, got ${band.fault_samples}`);
});
