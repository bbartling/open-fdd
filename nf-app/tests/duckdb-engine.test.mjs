// node --test nf-app/tests/duckdb-engine.test.mjs
// #1645 slice 1: the native DuckDB engine (kind "duckdb") runs the Postgres pack with its fdd.* macros and must give
// the same rows as PGlite (exact Postgres) and sql.js (today's small-box engine) for every rule and timeline.
// Skipped, with the reason, when @duckdb/node-api (a dependency of the DuckDB build) has no native build for this platform.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { ruleConfigClient } from "./fixtures/rule-config-client.mjs";

const require = createRequire(import.meta.url);
const engines = require("../hooks/lib/engines.js");
const { createEngine, releaseDuckDb, duckDbOptions, DUCKDB_SAFETY } = engines;
const { buildDataset } = require("./fixtures/synthetic_dataset.js");
const fdd = require("../hooks/fdd.js");

const rulesDir = new URL("../rules/", import.meta.url);
const readPack = (name) => JSON.parse(readFileSync(new URL(name, rulesDir), "utf8"));
const pgPack = readPack("pack-postgres.json");
const litePack = readPack("pack-sqlite.json");
const PINNED = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")).dependencies["@duckdb/node-api"];

let unavailable = "";
try { await import("@duckdb/node-api"); } catch (e) { unavailable = `@duckdb/node-api not loadable here: ${e.message}`; }
const opts = { skip: unavailable || false };

const REL_TOL = 1e-6;
const close = (a, b) => {
  if (a === null || b === null || a === undefined || b === undefined) return (a ?? null) === (b ?? null);
  if (typeof a === "number" && typeof b === "number") {
    if (Number.isNaN(a) || Number.isNaN(b)) return Number.isNaN(a) && Number.isNaN(b);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return a === b;   // infinities: exact, never within a tolerance
    return a === b || Math.abs(a - b) <= 1e-9 + REL_TOL * Math.max(Math.abs(a), Math.abs(b));
  }
  if (a instanceof Date || b instanceof Date) return new Date(a).getTime() === new Date(b).getTime();
  return a === b;
};
const keyOf = (r) => [r.equipment_id, r.series_id, r.sensor_role, r.billing_period, r.ts_epoch == null ? "" : Number(r.ts_epoch).toFixed(3)]
  .map((x) => String(x ?? "")).join("|");
const sortRows = (rows) => [...rows].sort((x, y) => keyOf(x).localeCompare(keyOf(y)));

/** Differences between two engines' rows of one rule (empty = equal): same keys, same columns, numbers within 1e-6. */
function diffRows(a, b, names) {
  if (a.length !== b.length) return [`row count ${a.length} (${names[0]}) vs ${b.length} (${names[1]})`];
  const out = [];
  const sa = sortRows(a), sb = sortRows(b);
  sa.forEach((ra, i) => {
    const rb = sb[i];
    const cols = new Set([...Object.keys(ra), ...Object.keys(rb)]);
    const na = Object.keys(ra).sort().join(","), nb = Object.keys(rb).sort().join(",");
    if (na !== nb) out.push(`${keyOf(ra)}: columns ${na} vs ${nb}`);
    for (const k of cols) if (!close(ra[k], rb[k])) out.push(`${keyOf(ra)}.${k}: ${names[0]}=${ra[k]} ${names[1]}=${rb[k]}`);
  });
  return out;
}

let input, duck, pg, lite;
const ms = {};
const res = { duck: {}, pg: {}, lite: {}, tlDuck: {}, tlPg: {}, tlLite: {}, errors: {} };

before(async () => {
  if (unavailable) return;
  input = buildDataset(pgPack, { equipments: 2, days: 3, stepSeconds: 300 });
  duck = await createEngine({ kind: "duckdb", pack: pgPack });
  pg = await createEngine({ kind: "pglite", pack: pgPack });
  lite = await createEngine({ kind: "sqlite", pack: litePack });
  await duck.load(input);
  await pg.load(input);
  await lite.load(input);
  for (const rid of Object.keys(pgPack.rules)) {
    for (const [name, eng, out, tl] of [["duckdb", duck, res.duck, res.tlDuck], ["pglite", pg, res.pg, res.tlPg], ["sqlite", lite, res.lite, res.tlLite]]) {
      const t0 = performance.now();
      try { out[rid] = await eng.query(rid); } catch (e) { res.errors[`${name} ${rid}`] = e.message; }
      try { tl[rid] = await eng.timeline(rid); } catch (e) { res.errors[`${name} timeline ${rid}`] = e.message; }
      ms[name] = (ms[name] || 0) + performance.now() - t0;
    }
  }
  console.log(`# rules + timelines, ms: ${Object.entries(ms).map(([k, v]) => `${k} ${Math.round(v)}`).join(", ")}`);
}, { timeout: 300000 });

after(async () => {
  await duck?.close();
  await pg?.close();
  await lite?.close();
  await releaseDuckDb();
});

test("duckdb: the pinned package reports DuckDB 2.0.1 and Node 22+ loads it", opts, async () => {
  assert.match(PINNED, /^2\.0\.1-r\.\d+$/, "pin an exact 2.0.1 revision");
  assert.equal(await duck.version(), "v2.0.1");
  assert.ok(Number(process.versions.node.split(".")[0]) >= 22);
});

test("duckdb: every rule and timeline runs without error on all three engines", opts, () => {
  assert.deepEqual(res.errors, {});
});

test("duckdb == PGlite, rule by rule (rows, columns, numerics within 1e-6 relative)", opts, async (t) => {
  let matched = 0, nonZero = 0;
  for (const rid of Object.keys(pgPack.rules)) {
    await t.test(rid, () => {
      const d = diffRows(res.duck[rid], res.pg[rid], ["duckdb", "pglite"]);
      assert.deepEqual(d, [], `${rid}: ${d.slice(0, 5).join("; ")}`);
      matched++;
      if (res.duck[rid].some((r) => Number(r.fault_hours) > 0)) nonZero++;
    });
  }
  console.log(`# duckdb parity: ${matched}/${Object.keys(pgPack.rules).length} rules match PGlite; ${nonZero} with fault_hours > 0`);
  assert.ok(nonZero >= 30, `only ${nonZero} rules had fault time: the dataset does not exercise the pack`);
});

test("duckdb == sql.js (today's small-box engine), rule by rule", opts, async (t) => {
  for (const rid of Object.keys(litePack.rules)) {
    await t.test(rid, () => {
      const d = diffRows(res.duck[rid], res.lite[rid], ["duckdb", "sqlite"]);
      assert.deepEqual(d, [], `${rid}: ${d.slice(0, 5).join("; ")}`);
    });
  }
});

test("duckdb timelines == PGlite timelines (timestamps, confirmed, held seconds)", opts, async (t) => {
  let rows = 0;
  for (const rid of Object.keys(pgPack.rules)) {
    if (!pgPack.rules[rid].timeline_sql) { assert.deepEqual(res.tlDuck[rid], [], rid); continue; }
    await t.test(rid, () => {
      assert.ok(res.tlDuck[rid].length > 0, `${rid}: empty timeline`);
      const d = diffRows(res.tlDuck[rid], res.tlPg[rid], ["duckdb", "pglite"]);
      assert.deepEqual(d, [], `${rid}: ${d.slice(0, 5).join("; ")}`);
      assert.deepEqual(Object.keys(res.tlDuck[rid][0]), Object.keys(res.tlPg[rid][0]), `${rid}: column order`);
      rows += res.tlDuck[rid].length;
    });
  }
  console.log(`# duckdb timeline parity: ${rows} rows`);
});

test("duckdb fdd.* macros == the Postgres helper functions on edge inputs", opts, async () => {
  const roles = ["sat", " sat ", "zone_rh", "duct_static", "chw_flow", "electric_kw", "kwh", "chiller_amps", "zone_co2",
    "chw_reset_request_sum", "sat_sp", "fan_status", "fan_cmd", "occ_mode", "loop_enabled", "unknown_role", ""];
  const units = ["°C", "degC", "Celsius", "%", "%RH", "percent", "Pa", "pascal", "L/s", "kW", "kWh", "A", "ppm", "count", "degF", "", null];
  const nums = ["1", " 2.5 ", "-3e2", ".5", "1.", "abc", "", "1e400", "Infinity", "-inf", "1,5"];   // not "0x10": Postgres 16+ reads hex text, sql.js and DuckDB do not
  const lit = (v) => (v === null ? "NULL" : `'${String(v).replace(/'/g, "''")}'`);
  const exprs = [];
  for (const r of roles) {
    exprs.push(`fdd.quantity_for_sql_role(${lit(r)})`, `fdd.is_expected_constant_sql_role(${lit(r)})`, `fdd.norm_unit(${lit(r)})`);
    for (const u of units) exprs.push(`fdd.sweep_assessable_sql_role(${lit(r)}, ${lit(u)})`, `fdd.mask_sweep_val(${lit(r)}, ${lit(u)}, 21.5)`);
  }
  for (const n of nums) exprs.push(`fdd.try_double(${lit(n)})`);
  // one SELECT of every helper call, run as a pseudo rule of the same pack on both engines
  const pack = { ...pgPack, rules: { __helpers: { sql: `SELECT ${exprs.map((e, i) => `${e} AS c${i}`).join(", ")}`, output_columns: [], timeline_sql: null } } };
  const row = async (kind) => {
    const eng = await createEngine({ kind, pack });
    try { await eng.load({ history: [], weather: [] }); return (await eng.query("__helpers"))[0]; } finally { await eng.close(); }
  };
  const d = await row("duckdb"), g = await row("pglite");
  exprs.forEach((e, i) => assert.ok(close(d[`c${i}`], g[`c${i}`]), `${e}: duckdb=${d[`c${i}`]} postgres=${g[`c${i}`]}`));
});

test("duckdb engine: a warm instance serves overlapping runs with isolated tables", opts, async () => {
  const a = await createEngine({ kind: "duckdb", pack: pgPack });
  const b = await createEngine({ kind: "duckdb", pack: pgPack });
  try {
    const one = { history: input.history.filter((r) => r.equipment_id === "AHU-1"), weather: input.weather, historyColumns: input.historyColumns };
    await a.load(one);
    await b.load(input);
    const fa = await a.query("FAN-RUNTIME-HOURS"), fb = await b.query("FAN-RUNTIME-HOURS");
    assert.deepEqual(fa.map((r) => r.equipment_id), ["AHU-1"], "engine a sees only its own rows");
    assert.equal(fb.length, 2, "engine b sees both equipment");
    assert.ok(close(fa[0].fan_runtime_hours, fb.find((r) => r.equipment_id === "AHU-1").fan_runtime_hours));
  } finally { await a.close(); await b.close(); }
  const c = await createEngine({ kind: "duckdb", pack: pgPack });
  try { await assert.rejects(c.query("FC1"), /load\(input\) before query/); } finally { await c.close(); }
});

/** Runs fn with OPENFDD_DUCKDB_* set to vars (undefined = unset), restoring the caller's values afterwards. */
function withDuckEnv(vars, fn) {
  const keys = ["OPENFDD_DUCKDB_MEMORY_LIMIT", "OPENFDD_DUCKDB_THREADS"];
  const saved = Object.fromEntries(keys.map((k) => [k, Object.hasOwn(process.env, k) ? process.env[k] : undefined]));
  try {
    for (const k of keys) { if (vars[k] === undefined) delete process.env[k]; else process.env[k] = vars[k]; }
    return fn();
  } finally {
    for (const k of keys) { if (saved[k] === undefined) delete process.env[k]; else process.env[k] = saved[k]; }
  }
}

test("parity guard: close() never treats an infinity as near a finite value or the other infinity", () => {
  assert.equal(close(Infinity, Infinity), true);
  assert.equal(close(-Infinity, -Infinity), true);
  assert.equal(close(1, Infinity), false);
  assert.equal(close(Infinity, 1e308), false);
  assert.equal(close(Infinity, -Infinity), false);
  assert.equal(close(NaN, NaN), true);
  assert.equal(close(NaN, 1), false);
  assert.equal(close(100, 100 + 1e-5), true, "within 1e-6 relative");
  assert.equal(close(100, 100.01), false, "outside the tolerance");
  assert.equal(close(null, undefined), true);
  assert.equal(close(null, 0), false);
});

test("parity guard: diffRows rejects a renamed column even when both values are null", () => {
  assert.deepEqual(diffRows([{ equipment_id: "A", x: null }], [{ equipment_id: "A", x: null }], ["a", "b"]), []);
  assert.equal(diffRows([{ equipment_id: "A", x: null }], [{ equipment_id: "A", y: null }], ["a", "b"]).length > 0, true);
});

test("duckdb options: memory limit and threads are validated; defaults suit a 1 GB edge; no network, no spill", () => {
  withDuckEnv({}, () => {
    assert.deepEqual(duckDbOptions({}), { memory_limit: "256MB", threads: "2",
      autoinstall_known_extensions: "false", autoload_known_extensions: "false", temp_directory: "" });
    assert.equal("TimeZone" in duckDbOptions({}), false, "TimeZone as a create option autoinstalls ICU over the network");
    assert.throws(() => duckDbOptions({ extraSettings: { temp_directory: "/tmp" } }), /not allowed/);
    assert.equal(duckDbOptions({ extraSettings: { custom_extension_repository: "http://x" } }).temp_directory, "", "safety always wins");
    const spill = duckDbOptions({ tempDirectory: "/tmp/openfdd-spill", maxTempDirectory: "1GB" });
    assert.equal(spill.temp_directory, "/tmp/openfdd-spill");
    assert.equal(spill.max_temp_directory_size, "1GB");
    assert.equal(spill.autoinstall_known_extensions, "false");
  });
  withDuckEnv({ OPENFDD_DUCKDB_MEMORY_LIMIT: "512MB", OPENFDD_DUCKDB_THREADS: "4" }, () => {
    assert.equal(duckDbOptions({}).memory_limit, "512MB", "env override");
    assert.equal(duckDbOptions({}).threads, "4", "env override");
    assert.equal(duckDbOptions({ memoryLimit: "128MB" }).memory_limit, "128MB", "the app option beats the env");
  });
  assert.equal(duckDbOptions({ memoryLimit: "1GB", threads: 4 }).memory_limit, "1GB");
  assert.throws(() => duckDbOptions({ memoryLimit: "lots" }), /memoryLimit/);
  assert.throws(() => duckDbOptions({ threads: 0 }), /threads/);
  assert.throws(() => duckDbOptions({ threads: 1.5 }), /threads/);
});

test("pickEngine: auto is duckdb; a missing package fails and does not fall back", async () => {
  const http = { get: async () => ({ data: { resources: [{ memory: { totalBytes: 8 * 1024 ** 3 } }] } }) };
  assert.deepEqual(await fdd.pickEngine(http, "duckdb", undefined, () => true), { kind: "duckdb", note: "" });
  assert.equal((await fdd.pickEngine(http, "auto", undefined, () => true)).kind, "duckdb");
  await assert.rejects(() => fdd.pickEngine(http, "duckdb", undefined, () => false), /DuckDB engine failed to load: module did not load/);
  const small = { get: async () => ({ data: { resources: [{ memory: { totalBytes: 1024 ** 3 } }] } }) };
  await assert.rejects(() => fdd.pickEngine(small, "duckdb", undefined, () => false), /DuckDB engine failed to load/);
});

// ---- saved tuning (#1589): a duckdb run with a tuning store applies the same overrides as the timescale engine ----
test("duckdb applies saved site and equipment tuning (fdd.rule_config) and equals PGlite running the same tuned SQL", opts, async () => {
  const client = ruleConfigClient();
  const SITE = "site-1";
  client.rows.push(
    { site_id: SITE, rule_id: "FC1", scope_key: "site", revision: 1, active: true, parameters: { version: 1, params: { eps_dsp: 5, confirm_min: 15 } } },
    { site_id: SITE, rule_id: "FC1", scope_key: "equip:AHU-2", revision: 1, active: true, parameters: { version: 1, params: { confirm_min: 30 } } },
    { site_id: SITE, rule_id: "FC2", scope_key: "equip:AHU-1", revision: 2, active: true, parameters: { version: 1, params: { mix_tol: 0.5, eps_mat: 0.3 } } },
  );
  const eng = await createEngine({ kind: "duckdb", pack: pgPack, tuningClient: client });
  const logs = [];
  try {
    assert.equal(typeof eng.ruleConfigOverrides, "function", "a tuning store gives the duckdb engine the overrides reader");
    const tuning = await fdd.loadRoleLimitOverrides({ engine: eng, pack: pgPack, log: (m) => logs.push(m) });
    assert.equal(tuning.summary.source, "fdd.rule_config");
    assert.equal(tuning.summary.rule_revisions, 3);
    await eng.load(input);
    let changed = 0;
    for (const [rid, equip] of [["FC1", "AHU-1"], ["FC1", "AHU-2"], ["FC2", "AHU-1"], ["FC2", "AHU-2"]]) {
      const tuned = tuning.forRule(SITE, equip, rid);
      if (rid === "FC2" && equip === "AHU-2") { assert.equal(tuned, null, "no override for FC2 on AHU-2: shipped SQL"); continue; }
      assert.ok(tuned && tuned.sql !== pgPack.rules[rid].sql, `${rid}/${equip}: tuned SQL rendered`);
      const mine = (rows) => rows.filter((r) => r.equipment_id === equip);
      const d = mine(await eng.query(rid, { sql: tuned.sql, timeline_sql: tuned.timeline_sql }));
      const dTl = mine(await eng.timeline(rid, { sql: tuned.sql, timeline_sql: tuned.timeline_sql }));
      const tunedPack = { ...pgPack, rules: { ...pgPack.rules, [rid]: { ...pgPack.rules[rid], sql: tuned.sql, timeline_sql: tuned.timeline_sql } } };
      const p = await createEngine({ kind: "pglite", pack: tunedPack });
      try {
        await p.load(input);
        const g = mine(await p.query(rid)), gTl = mine(await p.timeline(rid));
        assert.deepEqual(diffRows(d, g, ["duckdb", "pglite"]), [], `${rid}/${equip} tuned rows`);
        assert.deepEqual(diffRows(dTl, gTl, ["duckdb", "pglite"]), [], `${rid}/${equip} tuned timeline`);
      } finally { await p.close(); }
      const shipped = mine(res.duck[rid]);
      if (diffRows(d, shipped, ["tuned", "shipped"]).length) changed++;
    }
    assert.ok(changed >= 2, `the overrides change the result (${changed} of 3 tuned rule/equip pairs differ from shipped)`);
  } finally { await eng.close(); }
});

test("duckdb without a tuning store has no overrides reader (no store, nothing saved); with option timescale it reads it", opts, async () => {
  const plain = await createEngine({ kind: "duckdb", pack: pgPack });
  try { assert.equal(plain.ruleConfigOverrides, undefined); } finally { await plain.close(); }
  const withStore = await createEngine({ kind: "duckdb", pack: pgPack, config: { timescale: { host: "db.invalid", database: "x" } } });
  try { assert.equal(typeof withStore.ruleConfigOverrides, "function"); } finally { await withStore.close(); }
});

test("pickEngine: duckdb that fails to load does not switch to a configured Timescale store", async () => {
  const http = { get: async () => ({ data: { resources: [{ memory: { totalBytes: 1024 ** 3 } }] } }) };
  await assert.rejects(
    () => fdd.pickEngine(http, "duckdb", { host: "db" }, () => ({ ok: false, reason: "no native build" })),
    /DuckDB engine failed to load: no native build/,
  );
});

// ---- offline and disk-free (#1645 review): no extension download, no spill to the working directory ----
test("duckdb settings: UTC, spilling off, extension autoinstall and autoload off", opts, async () => {
  const s = await duck.settings();
  assert.deepEqual({ ...s, memory_limit: undefined, threads: undefined },
    { time_zone: "UTC", temp_directory: "", autoinstall: false, autoload: false, memory_limit: undefined, threads: undefined });
  assert.deepEqual(Object.keys(DUCKDB_SAFETY).sort(), ["autoinstall_known_extensions", "autoload_known_extensions", "temp_directory"]);
});

test("duckdb runs offline: unreachable extension repository, empty extension dir; an over-cap query fails and writes nothing", opts, () => {
  const extDir = mkdtempSync(join(tmpdir(), "ofdd-duck-ext-"));
  const cwd = mkdtempSync(join(tmpdir(), "ofdd-duck-cwd-"));
  try {
    const child = fileURLToPath(new URL("./fixtures/duckdb-offline-child.cjs", import.meta.url));
    const r = spawnSync(process.execPath, [child, extDir], { cwd, encoding: "utf8", timeout: 240000 });
    const line = (r.stdout || "").trim().split(String.fromCharCode(10)).pop().trim();
    assert.equal(r.status, 0, `child failed: ${line} ${r.stderr}`);
    const out = JSON.parse(line);
    assert.equal(out.settings.time_zone, "UTC");
    assert.equal(out.settings.temp_directory, "");
    for (const rid of ["FC1", "UTIL-MONTHLY", "SV-STALE", "OAT-METEO", "FAN-RUNTIME-HOURS"]) assert.ok(out.rules[rid] > 0, `${rid} rows offline`);
    assert.ok(out.timeline_rows > 0);
    assert.match(out.oom, /Out of Memory|memory/i, "over the cap: an out-of-memory error, not a spill");
    assert.deepEqual(readdirSync(extDir), [], "nothing downloaded into the extension directory");
    assert.deepEqual(readdirSync(cwd), [], "nothing spilled into the working directory (no .tmp)");
  } finally {
    rmSync(extDir, { recursive: true, force: true });
    rmSync(cwd, { recursive: true, force: true });
  }
});
