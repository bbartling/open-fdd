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
const { buildDataset } = require("../hooks/lib/synthetic_dataset.js");

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

const sortRows = (rows) => [...rows].sort((x, y) => String(x.equipment_id).localeCompare(String(y.equipment_id)));

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
const results = { pg: {}, lite: {}, errors: {} };

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
    ["authorized_series", "equipment", "history", "utility_interval", "utility_monthly", "weather"]);
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

test("output columns match the pack's declared output_columns", () => {
  for (const [rid, rule] of Object.entries(litePack.rules)) {
    const rows = results.lite[rid] || [];
    if (rows.length) assert.deepEqual(Object.keys(rows[0]).sort(), [...rule.output_columns].sort(), rid);
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
