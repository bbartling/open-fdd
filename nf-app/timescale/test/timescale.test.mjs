// OPENFDD_TS_TEST_DISPOSABLE=1 PGURL=postgres://postgres:example@localhost:55432/postgres \
//   node --test nf-app/timescale/test/timescale.test.mjs
// Needs the Docker TimescaleDB from docker-compose.yml (see ../README.md).
// SAFETY: PGURL is only the ADMIN connection. The suite creates its OWN database openfdd_test_<random>, marks it,
// runs every destructive statement there, and drops it at the end. It skips unless OPENFDD_TS_TEST_DISPOSABLE=1
// (and PGURL) is set, and the guard (disposable.mjs) refuses any unmarked / foreign database before any DDL.
// Checks: install idempotency + upgrade of an old global-retention install and of a v3 install (results copied into
// fdd.rule_result, legacy tables dropped), the fdd.input_sample contract + index use, SI conversion in loadHistory (incl.
// percent -> fraction parity with the PGlite engine), rule results == pglite, writeResults, history bounds, and the
// SCOPED retention (Open-FDD tables only; NF-like and unrelated tables keep identical row counts and checksums).
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { assertDisposable, createDb, dbNameFor, dropDb, guarded, newToken, OPT_IN, urlForDb } from "./disposable.mjs";

const require = createRequire(import.meta.url);
const ts = require("../../hooks/lib/timescale.js");
const hook = require("../../hooks/fdd.js");
const { createEngine } = require("../../hooks/lib/engines.js");
const ofddUnits = require("../../static/units.js");
const pack = JSON.parse(readFileSync(new URL("../../rules/pack-postgres.json", import.meta.url), "utf8"));
const here = (f) => readFileSync(fileURLToPath(new URL(f, import.meta.url)), "utf8");
const seedSql = here("./seed_nf_like.sql");
const legacySql = here("./legacy_global_retention.sql");
const legacyV3Sql = here("./legacy_v3_results.sql");
const contractSources = JSON.parse(here("../../../sql/fdd/input_contract.json")).sources;

const PGURL = process.env.PGURL;
const TOKEN = newToken();
const DBNAME = dbNameFor(TOKEN);
const extraDbs = [];
let admin = null;
let raw = null;
let db = null;
let skip = false;
if (process.env[OPT_IN] !== "1") skip = `${OPT_IN}=1 is not set (this suite creates and drops its own database on the server behind PGURL)`;
else if (!PGURL) skip = "PGURL (admin connection) is not set (docker compose -f nf-app/timescale/test/docker-compose.yml up -d)";
else {
  try {
    admin = await ts.connect({ connectionString: PGURL });
    await createDb(admin, DBNAME, TOKEN);
    raw = await ts.connect({ connectionString: urlForDb(PGURL, DBNAME) });
    db = guarded(raw, TOKEN);
    console.log(`# disposable database: ${DBNAME}`);
  } catch (e) {
    skip = `TimescaleDB not reachable at PGURL (${e.code || e.message})`;
    if (admin) { try { await dropDb(admin, DBNAME); } catch (_) { /* ignore */ } await admin.end(); admin = null; }
  }
}
if (skip) console.log(`# SKIPPED: ${skip}`);

after(async () => {
  if (!admin) return;
  if (raw) await raw.end();
  for (const n of [DBNAME, ...extraDbs]) { try { await dropDb(admin, n); } catch (e) { console.log(`# could not drop ${n}: ${e.message}`); } }
  await admin.end();
});

const catalog = JSON.parse(here("../../static/fdd-catalog.json"));
/**
 * The scale decisions (issue #1541) are made by the hook's siPlan only; loadHistory applies them. This is the glue
 * fdd.js uses: roles siPlan skips are dropped, fractionRoles = plan.scaled, booleanRoles = plan.bool.
 */
function scaled(r2u, units, kinds = {}) {
  const roles = {};
  for (const [role, uuid] of Object.entries(r2u)) roles[role] = { uuid, name: role, units: units[uuid] || "", kind: kinds[uuid] };
  const plan = hook.siPlan(roles, catalog);
  const kept = Object.fromEntries(Object.entries(r2u).filter(([role]) => !plan.skipped.has(role)));
  return { plan, args: { roleToUuid: kept, unitsByUuid: units, fractionRoles: [...plan.scaled], booleanRoles: [...plan.bool] } };
}

/** The engine's load(): mirror the bound points into fdd.point, then build the TEMP history from fdd.input_sample. */
async function load(args) {
  await ts.syncPoints(db, { siteId: args.siteId || "", equipId: args.equipId, rows: ts.pointRows({ pack, ...args }) });
  return ts.loadHistory(db, { pack, ...args });
}

const EQUIP = "AHU-1";
const FROM = "2026-09-20T00:00:00Z";
const TO = "2026-10-14T00:00:00Z";
const STEP = pack.poll_seconds;
const RULES = ["FC1", "FC2", "FC3", "FC4", "FC5", "FC6", "FC7", "FC8", "FC9", "FC10", "FC11", "FC12", "ECON-1", "ECON-2",
  "AHU-SATDEV", "AHU-DUCTHI", "AHU-SIMUL", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE", "SV-RATE", "OAT-METEO",
  "FAN-RUNTIME-HOURS", "FAULT-ELAPSED-HOURS", "AVG-ZONE-TEMP"].filter((r) => pack.rules[r]);

let roleToUuid, unitsByUuid, loaded, ruleRun;
let sourceDirty = true;   // public.data needs (re)seeding

async function seed() {
  await db.query(seedSql);            // its own DO block also refuses unmarked databases before any DDL
  await ts.install(db);
  const { rows } = await db.query("SELECT id::text AS id, name, units FROM public.points");
  roleToUuid = {};
  unitsByUuid = {};
  for (const r of rows) {
    roleToUuid[r.name.replace(/^AHU-1\//, "")] = r.id;
    unitsByUuid[r.id] = r.units;
  }
  sourceDirty = false;
}

const close = (a, b) => {
  if (a == null || b == null) return (a ?? null) === (b ?? null);
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-9 + 1e-6 * Math.max(Math.abs(a), Math.abs(b));
  return String(a) === String(b);
};
const diffRows = (a, b) => {
  const key = (r) => `${r.equipment_id}|${r.series_id ?? ""}`;
  const x = [...a].sort((p, q) => key(p).localeCompare(key(q)));
  const y = [...b].sort((p, q) => key(p).localeCompare(key(q)));
  if (x.length !== y.length) return [`row count ${x.length} vs ${y.length}`];
  const out = [];
  x.forEach((ra, i) => {
    for (const k of new Set([...Object.keys(ra), ...Object.keys(y[i])])) if (!close(ra[k], y[i][k])) out.push(`${k}: ${ra[k]} vs ${y[i][k]}`);
  });
  return out;
};

const adminHadData = admin ? (await admin.query("SELECT to_regclass('public.data') AS d")).rows[0].d : null;

test("guard: unmarked / foreign / opted-out databases are refused before any DDL", { skip }, async () => {
  // the admin database is not ours
  await assert.rejects(assertDisposable(admin, TOKEN), /refused/);
  // opt-in missing
  await assert.rejects(assertDisposable(raw, TOKEN, ""), /refused: OPENFDD_TS_TEST_DISPOSABLE=1/);
  // right database, wrong token (a marker from some other run)
  await assert.rejects(assertDisposable(raw, newToken()), /does not carry this run's disposable marker/);
  // a test-created database WITHOUT a marker, and one with a FOREIGN marker: the guard and the seed's own SQL guard refuse
  for (const marker of [null, newToken()]) {
    const name = dbNameFor(newToken());
    extraDbs.push(name);
    await createDb(admin, name, marker);
    const c = await ts.connect({ connectionString: urlForDb(PGURL, name) });
    try {
      await assert.rejects(assertDisposable(c, TOKEN), /refused/);
      await assert.rejects(guarded(c, TOKEN).query(seedSql), /refused/);
      if (!marker) await assert.rejects(c.query(seedSql), /seed_nf_like.sql refused/, "the seed script refuses on its own");
      const t = await c.query("SELECT to_regclass('public.data') AS d, to_regclass('public.points') AS p");
      assert.deepEqual(t.rows[0], { d: null, p: null }, "no DDL ran");
      if (!marker) await assert.rejects(c.query(legacySql), /refused/);
    } finally { await c.end(); }
  }
  // the admin database was not touched by this suite (compare with the state before it ran)
  const a = await admin.query("SELECT to_regclass('public.data') AS d");
  assert.equal(a.rows[0].d, adminHadData, "admin database fixture state unchanged");
});

test("install is idempotent and registers the scoped size-cap job", { skip }, async () => {
  await seed();
  const a = await ts.install(db);
  const b = await ts.install(db);
  assert.equal(b.maxBytes, 107374182400, "default cap is 100 GB");
  assert.deepEqual(a, b);
  assert.equal(a.schemaVersion, ts.SCHEMA_VERSION);
  const { rows } = await db.query("SELECT count(*)::int AS n FROM timescaledb_information.jobs WHERE proc_name = 'size_cap_job'");
  assert.equal(rows[0].n, 1, "exactly one job after two installs");
  const ht = await db.query("SELECT hypertable_schema || '.' || hypertable_name AS t FROM timescaledb_information.hypertables WHERE hypertable_schema IN ('openfdd', 'fdd')");
  assert.deepEqual(ht.rows.map((r) => r.t), ["fdd.rule_result"]);
  assert.deepEqual((await db.query("SELECT to_regclass('openfdd.fdd_results') AS a, to_regclass('openfdd.retention_log') AS b")).rows[0], { a: null, b: null }, "v4 has no legacy tables");
  assert.equal(a.jobRegistered, true);
  const cfg = Object.fromEntries((await db.query("SELECT key, value FROM openfdd.config")).rows.map((r) => [r.key, r.value]));
  assert.deepEqual(cfg.retention_allowlist, [], "no source table is trimmed by default");
  assert.equal(Number(cfg.max_chunks_per_call), 100);
  const s = await db.query("SELECT count(*)::int AS n FROM openfdd.nf_samples");
  assert.ok(s.rows[0].n > 200000, `adapter view sees the seeded NF data (${s.rows[0].n} rows)`);
  assert.equal(await ts.coreOk(db), true);
});

test("fdd.input_sample has exactly the signature the input contract declares", { skip }, async () => {
  const cols = (await db.query(
    `SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type FROM pg_attribute a
     WHERE a.attrelid = 'fdd.input_sample'::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum`)).rows;
  const names = { double: "double precision", text: "text", timestamp: "timestamp with time zone" };
  assert.deepEqual(cols, Object.entries(contractSources.input_sample.columns).map(([name, c]) => ({ name, type: names[c.type] })));
});

test("fdd.input_sample applies the point's scale and uses NF's (point_id, time) index", { skip }, async () => {
  const { rows: pr } = await db.query("SELECT id::text AS id, name, units FROM public.points WHERE name = 'AHU-1/sat'");
  const id = pr[0].id;
  await ts.syncPoints(db, { siteId: "ix", equipId: "IX", rows: ts.pointRows({ pack, siteId: "ix", equipId: "IX", roleToUuid: { sat: id }, unitsByUuid: { [id]: pr[0].units } }) });
  const t = "2026-10-05T10:00:00Z";
  const raw = (await db.query("SELECT value FROM public.data WHERE point_id = $1::uuid AND \"time\" = $2", [id, t])).rows[0].value;
  const si = (await db.query("SELECT value FROM fdd.input_sample WHERE site_id = 'ix' AND point_key = $1 AND ts = $2", [id, t])).rows[0].value;
  assert.ok(Math.abs(si - (raw - 32) * 5 / 9) < 1e-9, `${raw} degF -> ${si} degC through si_scale / si_offset`);
  await db.query("BEGIN");
  try {
    await db.query("SET LOCAL enable_seqscan = off");   // tiny chunks: prove an index CAN be used, not what the planner prefers
    const plan = (await db.query(
      `EXPLAIN (FORMAT JSON) SELECT avg(value) FROM fdd.input_sample
       WHERE site_id = 'ix' AND point_key = ANY($1::text[]) AND ts >= '2026-10-05Z' AND ts < '2026-10-06Z'`, [[id]])).rows[0]["QUERY PLAN"];
    const nodes = [];
    const walk = (n) => { nodes.push(n); (n.Plans || []).forEach(walk); };
    walk(plan[0].Plan);
    const dataScans = nodes.filter((n) => /^_hyper_/.test(n["Relation Name"] || ""));
    assert.ok(dataScans.length > 0, "the data chunks are scanned");
    assert.ok(nodes.some((n) => /Index/.test(n["Node Type"])), "an index (or bitmap index) scan is used");
    assert.ok(dataScans.every((n) => !/^Seq Scan/.test(n["Node Type"])), `no sequential scan of NF's data: ${dataScans.map((n) => n["Node Type"])}`);
  } finally { await db.query("ROLLBACK"); }
  await db.query("DELETE FROM fdd.point WHERE site_id = 'ix'");
});

/** The v3 layout (openfdd.fdd_results + retention_log, schema_version 3) on top of the installed v4 database. */
async function makeV3(rows) {
  await db.query("DELETE FROM fdd.rule_result");
  await db.query("DROP TABLE IF EXISTS openfdd.fdd_results, openfdd.retention_log");
  await db.query(legacyV3Sql);
  await db.query(rows);
  await db.query("UPDATE openfdd.config SET value = '3'::jsonb WHERE key = 'schema_version'");
  await db.query("DELETE FROM openfdd.config WHERE key = 'legacy_results_copied'");
}

test("upgrade v3 -> v4: results are copied into fdd.rule_result, legacy tables dropped, re-run is a no-op", { skip }, async () => {
  await makeV3(`
    INSERT INTO openfdd.fdd_results (run_ts, equip, site, rule_id, fault_pct, fault_hours, covered_hours, metric, engine, window_start, window_end, sensor_ref, role) VALUES
      ('2026-10-12T00:00:00Z', 'fixture', 'site-1', 'FC1', 10, 2.5, 24, '{"x": 1}', 'timescale', '2026-10-11T00:00:00Z', '2026-10-12T00:00:00Z', '', NULL),
      ('2026-10-12T00:00:00Z', 'fixture', 'site-1', 'SV-RATE', 0, 0, 24, NULL, 'timescale', '2026-10-11T00:00:00Z', '2026-10-12T00:00:00Z', 'u-1', 'sat'),
      ('2026-10-12T00:00:00Z', 'fixture', 'site-1', 'SV-RATE', NULL, NULL, 0, NULL, 'timescale', '2026-10-11T00:00:00Z', '2026-10-12T00:00:00Z', 'u-2', 'sat'),
      ('2026-10-13T00:00:00Z', 'fixture', NULL, 'FC2', 5, 1, 24, NULL, 'pglite', NULL, NULL, '', NULL);
    INSERT INTO openfdd.retention_log (status, dry_run, result) VALUES ('under_cap', false, '{}');`);
  assert.equal(await ts.schemaVersion(db), 3);
  const engine = await createEngine({ kind: "timescale", pack, client: db });   // installs because 3 < 4
  await engine.close();
  assert.equal(await ts.schemaVersion(db), 4);
  const out = (await db.query(`SELECT site_id, rule_id, subject_key, status, fault_hours, role, metrics, diagnostics->'legacy'->>'window_defaulted' AS defaulted,
      window_start, window_end, created_at FROM fdd.rule_result WHERE equipment_id = 'fixture' ORDER BY created_at, rule_id, subject_key`)).rows;
  assert.equal(out.length, 4, "every legacy row copied");
  assert.deepEqual(out.map((r) => [r.rule_id, r.subject_key, r.status, r.site_id]),
    [["FC1", "", "FAULT", "site-1"], ["SV-RATE", "u-1", "PASS", "site-1"], ["SV-RATE", "u-2", "INCONCLUSIVE", "site-1"], ["FC2", "", "FAULT", ""]]);
  assert.deepEqual(out[0].metrics, { x: 1 });
  assert.equal(out[0].created_at.toISOString(), "2026-10-12T00:00:00.000Z", "run_ts kept as created_at");
  assert.equal(out[3].defaulted, "true", "a row without a window gets a flagged placeholder window");
  assert.ok(out[3].window_end > out[3].window_start);
  assert.deepEqual((await db.query("SELECT to_regclass('openfdd.fdd_results') AS a, to_regclass('openfdd.retention_log') AS b")).rows[0], { a: null, b: null });
  assert.equal((await db.query("SELECT value->>'rows' AS n FROM openfdd.config WHERE key = 'legacy_results_copied'")).rows[0].n, "4");
  const count = async () => Number((await db.query("SELECT count(*) AS n FROM fdd.rule_result")).rows[0].n);
  const n1 = await count();
  assert.equal((await ts.install(db)).schemaVersion, 4);
  assert.equal(await count(), n1, "re-running the installer changes nothing");
  await db.query("DELETE FROM fdd.rule_result WHERE equipment_id = 'fixture'");
});

test("upgrade v3 -> v4 refuses on a row-count mismatch and leaves both tables untouched", { skip }, async () => {
  await makeV3(`
    INSERT INTO openfdd.fdd_results (run_ts, equip, site, rule_id, fault_pct, fault_hours, window_start, window_end, sensor_ref) VALUES
      ('2026-10-12T00:00:00Z', 'fixture', 's', 'FC1', 1, 1, '2026-10-11T00:00:00Z', '2026-10-12T00:00:00Z', ''),
      ('2026-10-12T00:00:00Z', 'fixture', 's', 'FC2', 1, 1, '2026-10-11T00:00:00Z', '2026-10-12T00:00:00Z', '');
    INSERT INTO fdd.rule_result (site_id, equipment_id, rule_id, window_start, window_end, status)
      VALUES ('s', 'fixture', 'FC1', '2026-10-11T00:00:00Z', '2026-10-12T00:00:00Z', 'PASS');   -- same key: the copy skips it`);
  await assert.rejects(ts.install(db), /copied 1 of 2 legacy result rows/);
  assert.equal(await ts.schemaVersion(db), 3, "schema_version stays 3");
  assert.equal((await db.query("SELECT count(*)::int AS n FROM openfdd.fdd_results")).rows[0].n, 2, "legacy rows kept");
  assert.equal((await db.query("SELECT count(*)::int AS n FROM fdd.rule_result WHERE equipment_id = 'fixture'")).rows[0].n, 1, "nothing half-copied");
  assert.ok((await db.query("SELECT to_regclass('openfdd.retention_log') AS b")).rows[0].b, "retention_log kept");
  await db.query("DELETE FROM fdd.rule_result WHERE equipment_id = 'fixture'");
  assert.equal((await ts.install(db)).schemaVersion, 4, "after the conflict is cleared the upgrade completes");
  assert.equal((await db.query("DELETE FROM fdd.rule_result WHERE equipment_id = 'fixture'")).rowCount, 2, "the completed upgrade copied exactly the two legacy rows");
});

test("syncPoints mirrors the bound points and drops the equipment's unbound ones; writeResults is an idempotent upsert", { skip }, async () => {
  const ids = (await db.query("SELECT id::text AS id FROM public.points ORDER BY name LIMIT 3")).rows.map((r) => r.id);
  const rows = (keys) => keys.map((k) => ({ site_id: "sync", point_key: k, equipment_id: "SYNC", role: "sat", role_source: "t", kind: "numeric", unit: "degC", source_unit: "degF", si_scale: 5 / 9, si_offset: -160 / 9, attrs: { dis: k } }));
  assert.deepEqual(await ts.syncPoints(db, { siteId: "sync", equipId: "SYNC", rows: rows(ids) }), { upserted: 3, removed: 0 });
  assert.deepEqual(await ts.syncPoints(db, { siteId: "sync", equipId: "SYNC", rows: rows(ids.slice(0, 2)) }), { upserted: 2, removed: 1 });
  assert.equal((await db.query("SELECT count(*)::int AS n FROM fdd.point WHERE site_id = 'sync'")).rows[0].n, 2);
  await db.query("DELETE FROM fdd.point WHERE site_id = 'sync'");

  const result = (row) => ts.toResultRow({ runTs: "2026-10-13T00:00:00Z", equip: "fixture", site: "w", ruleId: "SV-RATE", row, windowStart: FROM, windowEnd: TO });
  const details = { first: { role: "sat", name: "first", hours: 1, status: "fault" } };
  const out = [
    result({ fault_hours: 1, covered_hours: 2, sensor_fault_hours: details }),
    result({ series_id: "first", sensor_role: "sat", fault_hours: 1, covered_hours: 2 }),
    result({ series_id: "second", sensor_role: "sat", fault_hours: 0, covered_hours: 2 }),
    result({ series_id: "unassessed", sensor_role: "sat", fault_hours: 0, covered_hours: 0 }),
  ];
  assert.equal(await ts.writeResults(db, out), 4);
  assert.equal(await ts.writeResults(db, out), 4);
  const saved = (await db.query(`SELECT subject_key, role, status, fault_hours, covered_hours, metrics, poll_seconds FROM fdd.rule_result
    WHERE equipment_id = 'fixture' ORDER BY subject_key`)).rows;
  assert.deepEqual(saved, [
    { subject_key: "", role: null, status: "FAULT", fault_hours: 1, covered_hours: 2, metrics: { sensor_fault_hours: details }, poll_seconds: 300 },
    { subject_key: "first", role: "sat", status: "FAULT", fault_hours: 1, covered_hours: 2, metrics: {}, poll_seconds: 300 },
    { subject_key: "second", role: "sat", status: "PASS", fault_hours: 0, covered_hours: 2, metrics: {}, poll_seconds: 300 },
    { subject_key: "unassessed", role: "sat", status: "INCONCLUSIVE", fault_hours: null, covered_hours: 0, metrics: {}, poll_seconds: 300 },
  ]);
  await db.query("DELETE FROM fdd.rule_result WHERE equipment_id = 'fixture'");
});

test("loadHistory builds the wide history in SI", { skip }, async () => {
  loaded = await load({ equipId: EQUIP, siteId: "site-1", ...scaled(roleToUuid, unitsByUuid).args, from: FROM, to: TO, stepSec: STEP });
  const days = (Date.parse(TO) - Date.parse(FROM)) / 864e5;
  assert.equal(loaded.rows, days * 288, "one row per 5-minute bucket");
  assert.equal(loaded.si.sat, "°C");
  assert.equal(loaded.si.duct_static, "Pa");
  const t = "2026-10-05T10:00:00Z";
  const rawv = (await db.query(
    `SELECT avg(d.value) FILTER (WHERE p.name = 'AHU-1/sat') AS sat, avg(d.value) FILTER (WHERE p.name = 'AHU-1/duct_static') AS ds,
            avg(d.value) FILTER (WHERE p.name = 'AHU-1/fan_status') AS fs, avg(d.value) FILTER (WHERE p.name = 'AHU-1/fan_cmd') AS fc
     FROM public.data d JOIN public.points p ON p.id = d.point_id WHERE d."time" >= $1 AND d."time" < $1::timestamptz + interval '5 minutes'`, [t])).rows[0];
  const h = (await db.query("SELECT sat, duct_static, fan_status, fan_cmd, zone_t FROM pg_temp.history WHERE timestamp_utc = $1", [t])).rows[0];
  assert.ok(rawv.sat > 40 && rawv.sat < 100, `raw sat is in degF (${rawv.sat})`);
  assert.ok(Math.abs(h.sat - (rawv.sat - 32) * 5 / 9) < 1e-9, `sat ${rawv.sat} degF -> ${h.sat} degC`);
  assert.ok(h.sat > 5 && h.sat < 40, "sat is plausible degC");
  assert.ok(Math.abs(h.duct_static - rawv.ds * ofddUnits.toSI(1, "inH2O").value) < 1e-9, "duct static inH2O -> Pa");
  assert.equal(h.fan_status, rawv.fs, "unitless status passes through");
  assert.ok(Math.abs(h.fan_cmd - rawv.fc / 100) < 1e-9, `declared-% fan command ${rawv.fc} % -> fraction ${h.fan_cmd}`);
  const w = (await db.query("SELECT count(*)::int AS n FROM pg_temp.weather")).rows[0].n;
  assert.equal(w, loaded.rows, "weather mirrors the oa_t grid");
});

test("scales: loadHistory applies exactly what siPlan decided (fraction, boolean range check, humidity, plain SI)", { skip }, async () => {
  const two = { from: "2026-09-21T00:00:00Z", to: "2026-09-23T00:00:00Z", stepSec: STEP };
  const r2u = { oa_h: roleToUuid.oa_h, fan_cmd: roleToUuid.fan_cmd, fan_status: roleToUuid.fan_status };
  // no decisions passed: plain SI conversions by unit, nothing is divided by 100 (loadHistory never guesses)
  let h = await load({ equipId: EQUIP, roleToUuid: r2u, unitsByUuid, ...two });
  let r = (await db.query("SELECT max(fan_cmd) AS fc, max(oa_h) AS oh, max(fan_status) AS fs FROM pg_temp.history")).rows[0];
  assert.ok(r.fc > 1, `no fractionRoles: fan_cmd stays 0-100 (${r.fc})`);
  assert.ok(r.oh > 30, "oa_h stays 0-100 %RH");
  // siPlan's decisions
  const { plan, args } = scaled(r2u, unitsByUuid);
  assert.deepEqual([...plan.scaled], ["fan_cmd"]);
  assert.deepEqual([...plan.bool], ["fan_status"]);
  h = await load({ equipId: EQUIP, ...args, ...two });
  r = (await db.query("SELECT max(fan_cmd) AS fc, max(oa_h) AS oh, max(fan_status) AS fs, min(fan_status) AS fm FROM pg_temp.history")).rows[0];
  assert.ok(r.fc <= 1 && r.fc > 0.5, `fan_cmd is a fraction (${r.fc})`);
  assert.ok(r.oh > 30, "oa_h stays %RH 0-100");
  assert.ok(r.fs <= 1 && r.fm >= 0, "fan_status is 0/1 on-fractions");
  assert.equal(h.si.fan_cmd, "fraction");
  assert.equal(h.si.fan_status, "bool");
  assert.equal(h.si.oa_h, "%");
  // a boolean role whose bucket average leaves [0, 1] is rejected (NULL), not rescaled or thresholded
  await db.query(`INSERT INTO public.data (point_id, "time", value) SELECT md5('bad/status')::uuid, g, 2 FROM generate_series('2026-09-21T00:00:00Z'::timestamptz, '2026-09-21T23:55:00Z', interval '5 minutes') g`);
  const bad = (await db.query("SELECT md5('bad/status')::uuid::text AS u")).rows[0].u;
  await load({ equipId: "BAD", roleToUuid: { fan_status: bad, fan_cmd: roleToUuid.fan_cmd }, unitsByUuid: { ...unitsByUuid, [bad]: "" },
    fractionRoles: ["fan_cmd"], booleanRoles: ["fan_status"], ...two });
  const n = (await db.query("SELECT count(fan_status)::int AS fs, count(fan_cmd)::int AS fc FROM pg_temp.history")).rows[0];
  assert.equal(n.fs, 0, "a status of 2 is rejected");
  assert.ok(n.fc > 0);
  sourceDirty = true;
});

test("FC1 on declared-% fan commands: Timescale == PGlite for 1 %, 2 % and 99 %", { skip, timeout: 120000 }, async () => {
  const from = "2026-10-20T00:00:00Z", to = "2026-10-21T00:00:00Z";
  const out = {};
  for (const pct of [1, 2, 99]) {
    const equip = `PCT-${pct}`;
    const ids = { fan_cmd: `md5('${equip}/fan_cmd')::uuid`, duct_static: `md5('${equip}/ds')::uuid`, duct_static_sp: `md5('${equip}/sp')::uuid` };
    await db.query(
      `INSERT INTO public.data (point_id, "time", value)
       SELECT x.id, g, x.v FROM generate_series($1::timestamptz, $2::timestamptz - interval '5 minutes', interval '5 minutes') g,
         (VALUES (${ids.fan_cmd}, ${pct}::double precision), (${ids.duct_static}, 0::double precision), (${ids.duct_static_sp}, 1.5::double precision)) AS x(id, v)`,
      [from, to]);
    const uu = {};
    for (const [role, expr] of Object.entries(ids)) uu[role] = (await db.query(`SELECT ${expr}::text AS u`)).rows[0].u;
    const units = { [uu.fan_cmd]: "%", [uu.duct_static]: "inH2O", [uu.duct_static_sp]: "inH2O" };
    const r2u = { fan_cmd: uu.fan_cmd, duct_static: uu.duct_static, duct_static_sp: uu.duct_static_sp };

    // Timescale path
    const n = await load({ equipId: equip, siteId: "s", ...scaled(r2u, units).args, from, to, stepSec: STEP });
    assert.equal(n.rows, 288);
    const tsFc1 = (await ts.runRules(db, pack, ["FC1"])).results.FC1;
    const fan = (await db.query("SELECT max(fan_cmd) AS m FROM pg_temp.history")).rows[0].m;
    assert.ok(Math.abs(fan - pct / 100) < 1e-12, `${pct} % reaches SQL as ${pct / 100} (got ${fan})`);

    // PGlite path: values converted by the hook's own siPlan (the scale rule lives there)
    const roles = {
      fan_cmd: { uuid: uu.fan_cmd, name: "fan", units: "%", kind: "Number" },
      duct_static: { uuid: uu.duct_static, name: "ds", units: "inH2O", kind: "Number" },
      duct_static_sp: { uuid: uu.duct_static_sp, name: "sp", units: "inH2O", kind: "Number" },
    };
    const plan = hook.siPlan(roles, catalog);
    const rawVals = { fan_cmd: pct, duct_static: 0, duct_static_sp: 1.5 };
    const hist = [];
    for (let t = Date.parse(from); t < Date.parse(to); t += STEP * 1000) {
      const row = { equipment_id: equip, ts: t };
      for (const role of Object.keys(roles)) row[role] = plan.convert[role](rawVals[role]);
      hist.push(row);
    }
    const eng = await createEngine({ kind: "pglite", pack });
    let liteFc1;
    try {
      await eng.load({ historyColumns: pack.contract.history.map((c) => ({ name: c.name, type: c.type })), history: hist, weather: [] });
      liteFc1 = await eng.query("FC1");
    } finally { await eng.close(); }
    assert.deepEqual(diffRows(tsFc1, liteFc1), [], `FC1 differs between engines at ${pct} %`);
    out[pct] = tsFc1[0] ? tsFc1[0].fault_pct : 0;
  }
  console.log(`# FC1 fault_pct at declared-% fan cmd: 1% -> ${out[1]}, 2% -> ${out[2]}, 99% -> ${out[99]}`);
  assert.equal(out[1], 0, "1 % fan is NOT full fan");
  assert.equal(out[2], 0);
  assert.ok(out[99] > 0, "99 % fan with low static is a fault");
  sourceDirty = true;   // the extra points live in public.data now
});

test("valve (VAV-3) and unitless command: Timescale == PGlite, unitless role is skipped and the rule not assessed", { skip, timeout: 120000 }, async () => {
  const from = "2026-10-22T00:00:00Z", to = "2026-10-23T00:00:00Z";
  const uuidOf = async (expr) => (await db.query(`SELECT ${expr}::text AS u`)).rows[0].u;
  const results = {};
  for (const [label, pct, unit] of [["1pct", 1, "%"], ["99pct", 99, "%"], ["unitless", 99, ""]]) {
    const equip = `VLV-${label}`;
    const defs = { oa_t: [30, "degC"], zone_flow: [100, "L/s"], fan_status: [1, ""], reheat_valve_pct: [pct, unit] };
    const r2u = {}, units = {}, vals = [];
    for (const [role, [v, u]] of Object.entries(defs)) {
      const id = await uuidOf(`md5('${equip}/${role}')::uuid`);
      r2u[role] = id; units[id] = u; vals.push(`(md5('${equip}/${role}')::uuid, ${v}::double precision)`);
    }
    await db.query(
      `INSERT INTO public.data (point_id, "time", value)
       SELECT x.id, g, x.v FROM generate_series($1::timestamptz, $2::timestamptz - interval '5 minutes', interval '5 minutes') g, (VALUES ${vals.join(", ")}) AS x(id, v)`, [from, to]);
    const { plan, args } = scaled(r2u, units);
    if (label === "unitless") {
      assert.ok(plan.skipped.has("reheat_valve_pct"), "unitless valve command is skipped");
      assert.ok(!("reheat_valve_pct" in args.roleToUuid), "and never reaches Timescale");
      // VAV-3 requires reheat_valve_pct: with the role gone the hook does not run it (no result = not assessed)
      const reg = catalog.rules.find((x) => x.id === "VAV-3");
      assert.ok(reg.required_roles.includes("reheat_valve_pct"));
      results[label] = null;
      continue;
    }
    const n = await load({ equipId: equip, siteId: "s", ...args, from, to, stepSec: STEP });
    assert.equal(n.rows, 288);
    const tsRes = (await ts.runRules(db, pack, ["VAV-3"])).results["VAV-3"];
    const hist = (await db.query("SELECT * FROM pg_temp.history ORDER BY timestamp_utc")).rows.map(({ timestamp_utc, ...x }) => ({ ...x, ts: timestamp_utc.getTime() }));
    const eng = await createEngine({ kind: "pglite", pack });
    let liteRes;
    try {
      await eng.load({ historyColumns: pack.contract.history.map((c) => ({ name: c.name, type: c.type })), history: hist, weather: [] });
      liteRes = await eng.query("VAV-3");
    } finally { await eng.close(); }
    assert.deepEqual(diffRows(tsRes, liteRes), [], `VAV-3 differs between engines at ${label}`);
    results[label] = tsRes[0] ? Number(tsRes[0].fault_hours) : 0;
  }
  console.log(`# VAV-3 fault_hours: declared 1 % -> ${results["1pct"]}, 99 % -> ${results["99pct"]}, unitless -> skipped`);
  assert.equal(results["1pct"], 0, "1 % reheat valve is not above 52 %");
  assert.ok(results["99pct"] > 0, "99 % reheat valve in warm weather is a fault");
  assert.equal(results.unitless, null);
  sourceDirty = true;
});

test("rules in Timescale == the pglite engine on the same history", { skip, timeout: 280000 }, async () => {
  if (sourceDirty) await seed();
  const sensorSeries = ["sat", "sat_aux", "mat", "oa_t", "rat", "duct_static"].map((name) => ({
    uuid: roleToUuid[name], role: name === "sat_aux" ? "sat" : name,
    unit: name === "duct_static" ? "Pa" : "°C",
  }));
  loaded = await load({ equipId: EQUIP, siteId: "site-1", ...scaled(roleToUuid, unitsByUuid).args,
    unitsByUuid, sensorSeries, from: FROM, to: TO, stepSec: STEP });
  const t0 = Date.now();
  ruleRun = await ts.runRules(db, pack, RULES);
  const tsMs = Date.now() - t0;
  const q = async (sql) => (await db.query(sql)).rows;
  const hist = (await q("SELECT * FROM pg_temp.history ORDER BY timestamp_utc")).map(({ timestamp_utc, ...r }) => ({ ...r, ts: timestamp_utc.getTime() }));
  const weather = (await q("SELECT * FROM pg_temp.weather ORDER BY timestamp_utc")).map(({ timestamp_utc, ...r }) => ({ ...r, ts: timestamp_utc.getTime() }));
  const sensorHistory = (await q("SELECT * FROM pg_temp.sensor_history")).map(({ timestamp_utc, ...r }) => ({ ...r, ts: timestamp_utc.getTime() }));
  assert.equal(new Set(sensorHistory.map((row) => row.series_id)).size, 6);
  assert.equal(new Set(sensorHistory.filter((row) => row.sensor_role === "sat").map((row) => row.series_id)).size, 2);
  const input = {
    historyColumns: pack.contract.history.map((c) => ({ name: c.name, type: c.type })),
    history: hist, weather, sensorHistory,
  };
  const eng = await createEngine({ kind: "pglite", pack });
  let matched = 0, bothError = 0, withFault = 0, timelines = 0;
  const problems = [];
  try {
    await eng.load(input);
    for (const id of RULES) {
      let lite, liteErr;
      try { lite = await eng.query(id); } catch (e) { liteErr = e.message; }
      const tsErr = ruleRun.errors[id];
      if (liteErr || tsErr) {
        if (liteErr && tsErr) bothError++; else problems.push(`${id}: error on one side only (timescale: ${tsErr}; pglite: ${liteErr})`);
        continue;
      }
      const d = diffRows(ruleRun.results[id], lite);
      if (d.length) problems.push(`${id}: ${d.join("; ")}`); else matched++;
      if (ruleRun.results[id].some((r) => r.fault_pct > 0)) withFault++;
      // 5.0.3 fault timeline: the same timeline_sql on the real database == pglite (per-timestamp confirmed flags).
      const tlSql = pack.rules[id] && pack.rules[id].timeline_sql;
      if (tlSql) {
        const norm = (rows) => rows.map((r) => `${r.equipment_id}|${r.series_id ?? ""}|${Number(r.ts_epoch)}|${Number(r.confirmed)}|${Number(r.held_seconds)}`).sort();
        let tsTl, tsTlErr;
        try { tsTl = await q(tlSql); } catch (e) { tsTlErr = e.message; }
        if (tsTlErr) { problems.push(`${id} timeline: timescale error ${tsTlErr}`); continue; }
        const a = norm(tsTl), b = norm(await eng.timeline(id));
        if (a.length !== b.length || a.some((x, i) => x !== b[i])) problems.push(`${id} timeline: ${a.length} rows (timescale) vs ${b.length} (pglite) or values differ`);
        else timelines++;
      }
    }
  } finally { await eng.close(); }
  console.log(`# rules compared: ${RULES.length}, matched: ${matched}, both-error: ${bothError}, with fault>0: ${withFault}, timescale run ${tsMs} ms`);
  assert.deepEqual(problems, []);
  assert.ok(matched >= 15, `at least 15 rules must run and match (got ${matched})`);
  assert.ok(withFault >= 1, "the seeded faults are detected");
  assert.ok(timelines >= 10, `fault timelines must match on at least 10 rules (got ${timelines})`);
  const fc1 = ruleRun.results.FC1[0];
  assert.equal(fc1.equipment_id, EQUIP);
  assert.equal(typeof fc1.fault_pct, "number", "numbers are coerced");
  for (const id of RULES.filter((id) => id.startsWith("SV-"))) {
    const expectedSeries = sensorSeries.filter((series) => catalog.sensor_sweep_roles[id]?.includes(series.role));
    assert.equal(ruleRun.results[id]?.length, expectedSeries.length, `${id} scores its assessable physical sensors`);
    assert.deepEqual(new Set(ruleRun.results[id].map((row) => row.series_id)), new Set(expectedSeries.map((series) => series.uuid)));
    const sat = ruleRun.results[id].filter((row) => row.sensor_role === "sat");
    assert.equal(sat.length, 2, `${id} preserves both supply-air sensors`);
    assert.ok(sat.every((row) => row.covered_hours > 0), `${id} reports real coverage`);
  }
});

test("writeResults upserts rule results into fdd.rule_result", { skip }, async () => {
  assert.ok(ruleRun, "needs the rules test");
  const runTs = "2026-10-14T00:00:00Z";
  const rows = [];
  for (const [id, res] of Object.entries(ruleRun.results)) {
    const row = hook.equipmentResult(pack.rules[id], res, EQUIP);
    if (!row) continue;
    for (const result of [row, ...(row.sensor_rows || [])]) {
      rows.push(ts.toResultRow({ runTs, equip: EQUIP, site: "site-1", ruleId: id, row: result, windowStart: FROM, windowEnd: TO }));
    }
  }
  assert.ok(rows.length >= 15);
  assert.equal(await ts.writeResults(db, rows), rows.length);
  assert.equal(await ts.writeResults(db, rows), rows.length, "second write upserts");
  const n = (await db.query("SELECT count(*)::int AS n FROM fdd.rule_result WHERE created_at = $1", [runTs])).rows[0].n;
  assert.equal(n, rows.length, "no duplicates");
  const back = (await db.query("SELECT fault_pct, fault_hours, covered_hours, engine, window_start, status FROM fdd.rule_result WHERE rule_id = 'FC1'")).rows[0];
  assert.ok(close(back.fault_pct, ruleRun.results.FC1[0].fault_pct));
  assert.equal(back.engine, "timescale");
  assert.equal(back.window_start.toISOString(), "2026-09-20T00:00:00.000Z");
  const sweep = (await db.query(`SELECT subject_key, role, fault_hours, covered_hours, metrics
    FROM fdd.rule_result WHERE rule_id = 'SV-STALE' AND created_at = $1 ORDER BY subject_key`, [runTs])).rows;
  assert.equal(sweep.length, 6, "equipment summary plus five stale-assessable sensors");
  const [summary, ...sensors] = sweep;
  assert.equal(summary.subject_key, "");
  assert.deepEqual(summary.metrics.sensor_fault_hours,
    hook.equipmentResult(pack.rules["SV-STALE"], ruleRun.results["SV-STALE"], EQUIP).sensor_fault_hours);
  assert.equal(summary.fault_hours, Math.max(...sensors.map((row) => row.fault_hours)));
  assert.equal(summary.covered_hours, Math.max(...sensors.map((row) => row.covered_hours)));
  assert.equal(sensors.filter((row) => row.role === "sat").length, 2);
});

test("sweep role-limit overrides (#1589): tuning hook preview / save / reset / rollback; the run uses and records the revision", { skip, timeout: 120000 }, async () => {
  if (sourceDirty) await seed();
  const tuning = require("../../hooks/tuning.js");
  const T = pack.role_limit_templates;
  const logs = [];
  const call = (args) => tuning.handle({ sdk: { logEvent: (m) => logs.push(m) }, args, connect: async () => db, templates: T });
  await db.query("DELETE FROM fdd.rule_config WHERE rule_id = 'SV-LIMITS'");
  const SITE = "site-1";
  const first = await call({ action: "get", site: SITE });
  assert.equal(first.ok, true, first.error);
  assert.deepEqual(first.history, [], "no revisions yet");
  assert.equal(first.effective.sources["discharge-air-temp"].hi, "shipped");

  // invalid overrides are rejected and nothing is stored
  const bad = await call({ action: "save", site: SITE, overrides: JSON.stringify({ version: 1, roles: { "discharge-air-temp": { lo: 30, hi: 20 } } }) });
  assert.equal(bad.ok, false);
  assert.match(bad.error, /lo \(30\) must be < hi \(20\)/);
  for (const roles of [{ "no-such-role": { lo: 1 } }, { "discharge-air-temp": { spike_delta: -1 } }, { "discharge-air-temp": { colour: 1 } }]) {
    const r = await call({ action: "save", site: SITE, overrides: JSON.stringify({ version: 1, roles }) });
    assert.equal(r.ok, false, JSON.stringify(roles));
  }
  assert.equal((await db.query("SELECT count(*)::int AS n FROM fdd.rule_config WHERE rule_id = 'SV-LIMITS'")).rows[0].n, 0);

  // preview validates without writing
  const siteOv = { version: 1, roles: { "discharge-air-temp": { lo: 4, hi: 16 } } };
  const pv = await call({ action: "preview", site: SITE, overrides: JSON.stringify(siteOv) });
  assert.equal(pv.ok, true, pv.error);
  assert.equal(pv.written, false);
  assert.equal(pv.effective.roles["discharge-air-temp"].hi, 16);
  assert.equal(pv.effective.sources["discharge-air-temp"].hi, "site");
  assert.equal((await db.query("SELECT count(*)::int AS n FROM fdd.rule_config WHERE rule_id = 'SV-LIMITS'")).rows[0].n, 0);

  // save: site, then equipment (precedence shipped < site < equipment)
  const s1 = await call({ action: "save", site: SITE, overrides: JSON.stringify(siteOv), note: "tighter supply band", by: "test" });
  assert.equal(s1.ok, true, s1.error);
  assert.equal(s1.revision, 1);
  const e1 = await call({ action: "save", site: SITE, scope: "equip:" + EQUIP, overrides: JSON.stringify({ version: 1, roles: { "discharge-air-temp": { hi: 13 } } }) });
  assert.equal(e1.ok, true, e1.error);
  assert.equal(e1.effective.roles["discharge-air-temp"].lo, 4, "site value inherited");
  assert.equal(e1.effective.sources["discharge-air-temp"].lo, "site");
  assert.equal(e1.effective.roles["discharge-air-temp"].hi, 13, "equipment wins");
  assert.equal(e1.effective.sources["discharge-air-temp"].hi, "equipment");
  assert.equal(e1.effective.sources["mixed-air-temp"].hi, "shipped");

  // the scheduled run: the fdd hook's loader re-renders the sweeps for this equipment and records the revision
  const engine = await createEngine({ kind: "timescale", pack, client: db });
  const tuned = await hook.loadRoleLimitOverrides({ engine, pack, log: () => {} });
  assert.equal(tuned.forEquip(SITE, "AHU-OTHER") && tuned.forEquip(SITE, "AHU-OTHER").configRevision, 1, "other equipment: site revision");
  const lim = tuned.forEquip(SITE, EQUIP);
  assert.equal(lim.configRevision, e1.revision);
  assert.equal(lim.parameters.role_limits.site_revision, 1);
  assert.notEqual(lim.sweeps["SV-RANGE"].sql, pack.rules["SV-RANGE"].sql);
  assert.equal(lim.sweeps["SV-SPIKE"].sql, pack.rules["SV-SPIKE"].sql, "rules whose limits did not change keep the pack SQL");
  assert.equal(tuned.forEquip("site-2", EQUIP), null, "another site keeps the shipped limits");
  const sensorSeries = ["sat", "mat", "oa_t"].map((name) => ({ uuid: roleToUuid[name], role: name, unit: "°C" }));
  await load({ equipId: EQUIP, siteId: SITE, ...scaled(roleToUuid, unitsByUuid).args, unitsByUuid, sensorSeries, from: FROM, to: TO, stepSec: STEP });
  const base = await engine.query("SV-RANGE");
  const over = await engine.query("SV-RANGE", lim.sweeps["SV-RANGE"]);
  const satHours = (rows) => rows.find((r) => r.sensor_role === "sat").fault_hours;
  assert.ok(satHours(over) > satHours(base), `a 4..13 degC band flags more supply-air hours (${satHours(base)} -> ${satHours(over)})`);
  const mat = (rows) => rows.find((r) => r.sensor_role === "mat").fault_hours;
  assert.equal(mat(over), mat(base), "roles without an override are unchanged");
  const row = hook.equipmentResult(pack.rules["SV-RANGE"], over, EQUIP);
  const runTs = "2026-10-14T01:00:00Z";
  const extra = { ruleHash: lim.ruleHashes["SV-RANGE"], configHash: lim.configHash, configRevision: lim.configRevision, parameters: lim.parameters };
  await ts.writeResults(db, [row, ...row.sensor_rows].map((r) => engine.resultRow({ runTs, equip: EQUIP, site: SITE, ruleId: "SV-RANGE", row: r, windowStart: FROM, windowEnd: TO, ...extra })));
  const stored = (await db.query("SELECT DISTINCT config_revision, config_hash, rule_hash, effective_parameters FROM fdd.rule_result WHERE rule_id = 'SV-RANGE' AND created_at = $1", [runTs])).rows;
  assert.equal(stored.length, 1);
  assert.equal(Number(stored[0].config_revision), e1.revision, "the run records the parameter revision");
  assert.equal(stored[0].config_hash, lim.configHash);
  assert.notEqual(stored[0].rule_hash, "");
  assert.equal(stored[0].effective_parameters.role_limits.equipment_revision, e1.revision);

  // reset (equipment back to the site) and rollback (a new revision with the old parameters; history append-only)
  const r2 = await call({ action: "reset", site: SITE, scope: "equip:" + EQUIP });
  assert.equal(r2.revision, 2);
  assert.equal(r2.effective.roles["discharge-air-temp"].hi, 16, "back to the site value");
  const rb = await call({ action: "rollback", site: SITE, scope: "equip:" + EQUIP, revision: "1" });
  assert.equal(rb.ok, true, rb.error);
  assert.equal(rb.revision, 3);
  assert.equal(rb.effective.roles["discharge-air-temp"].hi, 13);
  assert.deepEqual(rb.history.map((h) => [h.revision, h.active]), [[3, true], [2, false], [1, false]]);
  assert.equal(rb.history[0].parameters.rollback_of, 1);
  const actives = (await db.query("SELECT scope_key, revision FROM fdd.rule_config WHERE rule_id = 'SV-LIMITS' AND active ORDER BY scope_key")).rows;
  assert.deepEqual(actives.map((r) => [r.scope_key, Number(r.revision)]), [["equip:" + EQUIP, 3], ["site", 1]], "one active revision per scope");
  const site0 = await call({ action: "reset", site: SITE });
  assert.equal(site0.effective.sources["discharge-air-temp"].lo, "shipped", "site reset: shipped defaults below");
  assert.ok(logs.some((m) => m.includes("revision 1")), "saves are logged");
  await db.query("DELETE FROM fdd.rule_config WHERE rule_id = 'SV-LIMITS'");
});

test("history_buckets and historyRoute (bounds against the real database)", { skip }, async () => {
  const sat = roleToUuid.sat;
  const { rows } = await db.query(
    "SELECT * FROM openfdd.history_buckets($1::text[], '2026-09-15Z', '2026-10-15Z', interval '1 day')", [[sat]]);
  assert.equal(rows.length, 30);
  const day = rows.find((r) => r.bucket.toISOString() === "2026-10-05T00:00:00.000Z");
  const rawd = (await db.query(
    "SELECT avg(value) AS a, min(value) AS mn, max(value) AS mx, count(*)::int AS n FROM public.data WHERE point_id = $1::uuid AND \"time\" >= '2026-10-05Z' AND \"time\" < '2026-10-06Z'", [sat])).rows[0];
  assert.ok(close(day.avg, rawd.a) && close(day.min, rawd.mn) && close(day.max, rawd.mx));
  assert.equal(Number(day.n), rawd.n);
  const gapDay = rows.find((r) => r.bucket.toISOString() === "2026-09-21T00:00:00.000Z");
  assert.equal(Number(gapDay.n), 288 - 37, "the 3 h SAT outage leaves 251 samples");

  const r = await ts.historyRoute(db, { uuids: [sat, roleToUuid.oa_t], from: "2026-09-15T00:00:00Z", to: "2026-10-15T00:00:00Z", bucket: "1 day" });
  assert.equal(r.rows.length, 60);
  assert.equal(r.truncated, false);
  assert.equal(r.coarsened, false);
  assert.equal(r.coverage.with_data, 2);
  assert.equal(r.coverage.points[sat].buckets, 30);
  const auto = await ts.historyRoute(db, { uuids: [sat], from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z" });
  assert.equal(auto.bucket, "6 hours", "59 days / ~1000 buckets");
  // byte cap (200 KB) still truncates when the point budget is raised
  const big = await ts.historyRoute(db, { uuids: Object.values(roleToUuid), from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z", bucket: "5 minutes" }, { maxPoints: 5000000 });
  assert.equal(big.truncated, true);
  assert.equal(big.coverage.complete, false);
  assert.ok(JSON.stringify(big).length <= 200000 + 5000, `capped JSON (${JSON.stringify(big).length} bytes)`);
  // with the default point budget the same request is coarsened instead of read in full
  const co = await ts.historyRoute(db, { uuids: Object.values(roleToUuid), from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z", bucket: "5 minutes" });
  assert.equal(co.coarsened, true);
  assert.equal(co.requested_bucket, "5 minutes");
  assert.notEqual(co.bucket, "5 minutes");
  assert.ok(co.total <= 200000);
  await assert.rejects(ts.historyRoute(db, { uuids: [sat], from: "2026-09-01Z", to: "2026-10-01Z", bucket: "1 day; drop table x" }));
  // unknown uuids: empty answer with explicit coverage
  const unk = await ts.historyRoute(db, { uuids: ["00000000-0000-0000-0000-000000000000", sat], from: "2026-09-15T00:00:00Z", to: "2026-10-15T00:00:00Z", bucket: "1 day" });
  assert.deepEqual(unk.coverage.without_data, ["00000000-0000-0000-0000-000000000000"]);
  assert.equal(unk.coverage.with_data, 1);
  // statement timeout: the query is cancelled, the connection stays usable
  await assert.rejects(
    ts.historyRoute(db, { uuids: Object.values(roleToUuid), from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z", bucket: "1 minute" }, { statementTimeoutMs: 1, maxPoints: 5000000 }),
    (e) => e.code === "history_timeout" && /exceeded 1 ms/.test(e.message));
  assert.equal((await db.query("SELECT 1 AS ok")).rows[0].ok, 1, "rolled back, session usable");
});

// ---------------------------------------------------------------- scoped retention

/** Fixture: public.data = NF-like source (60 daily chunks), otherapp.events = unrelated app, fdd.rule_result (9 chunks). */
async function retentionFixture() {
  if (sourceDirty) await seed();
  await db.query("SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE proc_schema = 'openfdd'");
  await db.query("DROP SCHEMA IF EXISTS openfdd CASCADE");
  await db.query("DROP TABLE IF EXISTS fdd.rule_result, fdd.point, fdd.rule_config CASCADE");   // schema fdd also holds the rule helpers: keep it
  await db.query("DROP SCHEMA IF EXISTS otherapp CASCADE");
  await ts.install(db);
  await db.query(`
    CREATE SCHEMA otherapp;
    CREATE TABLE otherapp.events (ts timestamptz NOT NULL, device int NOT NULL, v double precision);
    SELECT create_hypertable('otherapp.events', 'ts', chunk_time_interval => interval '7 days');
    INSERT INTO otherapp.events
      SELECT g, d, (extract(epoch FROM g)::bigint % 997)::double precision
      FROM generate_series(timestamptz '2026-08-01', timestamptz '2026-10-30', interval '1 hour') g, generate_series(1, 3) d;
    INSERT INTO fdd.rule_result (site_id, equipment_id, rule_id, window_start, window_end, status, fault_pct, metrics, created_at)
      SELECT 's', 'AHU-' || e, 'FC' || r, g - interval '1 day', g, 'PASS', (e * r)::double precision, jsonb_build_object('pad', repeat('x', 60)), g
      FROM generate_series(timestamptz '2026-02-01', timestamptz '2026-10-20', interval '1 day') g,
           generate_series(1, 10) e, generate_series(1, 5) r;`);
}

const HT = { source: "public.data", other: "otherapp.events", ours: "fdd.rule_result" };
const fingerprint = async (tbl, where = "true") => {
  const r = (await db.query(
    `SELECT count(*)::bigint AS n, coalesce(sum(('x' || substr(md5(t::text), 1, 15))::bit(60)::bigint), 0)::text AS h FROM ${tbl} t WHERE ${where}`)).rows[0];
  return { n: Number(r.n), h: r.h };
};
const chunkNames = async (tbl) => {
  const [s, n] = tbl.split(".");
  return (await db.query("SELECT chunk_name FROM timescaledb_information.chunks WHERE hypertable_schema = $1 AND hypertable_name = $2 ORDER BY range_end", [s, n])).rows.map((r) => r.chunk_name);
};
const snapshot = async () => ({
  source: { fp: await fingerprint(HT.source), chunks: await chunkNames(HT.source) },
  other: { fp: await fingerprint(HT.other), chunks: await chunkNames(HT.other) },
  ours: { chunks: await chunkNames(HT.ours) },
});
const enforce = async (cap) => (await db.query("SELECT openfdd.enforce_size_cap($1::bigint) AS r", [String(cap)])).rows[0].r;
const preview = async (cap) => (await db.query("SELECT openfdd.retention_preview($1::bigint) AS r", [String(cap)])).rows[0].r;
const setCfg = (key, value) => db.query("INSERT INTO openfdd.config (key, value) VALUES ($1, $2::jsonb) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", [key, JSON.stringify(value)]);
const scopedBytes = async () => Number((await db.query("SELECT openfdd.hypertables_bytes() AS b")).rows[0].b);

test("retention scope defaults to the Open-FDD schemas (openfdd, fdd) only", { skip }, async () => {
  await retentionFixture();
  const snap = await snapshot();
  assert.ok(snap.source.chunks.length >= 55 && snap.other.chunks.length >= 8 && snap.ours.chunks.length >= 8,
    `chunks: source ${snap.source.chunks.length}, other ${snap.other.chunks.length}, ours ${snap.ours.chunks.length}`);
  const scope = (await db.query("SELECT schema_name || '.' || table_name AS t, reason FROM openfdd.retention_scope()")).rows;
  assert.deepEqual(scope, [{ t: HT.ours, reason: "openfdd" }]);
  const size = Number((await db.query("SELECT hypertable_size('fdd.rule_result') AS b")).rows[0].b);
  assert.equal(await scopedBytes(), size, "the cap counts Open-FDD tables only");
  assert.equal((await db.query("SELECT openfdd.retention_allowlist() AS a")).rows[0].a.length, 0);
});

test("a low cap drops ONLY Open-FDD chunks; source and unrelated tables keep identical row counts and checksums", { skip, timeout: 120000 }, async () => {
  await retentionFixture();
  const before = await snapshot();
  const size0 = await scopedBytes();
  const cap = Math.floor(size0 * 0.5);

  const pv = await preview(cap);
  assert.equal(pv.dry_run, true);
  assert.equal(pv.chunks_dropped, 0);
  assert.ok(pv.chunks_would_drop > 0);
  assert.ok(pv.would_drop.every((d) => d.hypertable === HT.ours), "preview lists Open-FDD chunks only");
  assert.deepEqual((await snapshot()).ours.chunks, before.ours.chunks, "preview dropped nothing");

  const r = await enforce(cap);
  const after = await snapshot();
  console.log(`# retention: cap ${cap} B (scoped before ${size0} B) -> status ${r.status}, dropped ${r.chunks_dropped} rule_result chunks, after ${r.after_bytes} B`);
  console.log(`# source ${HT.source}: ${before.source.fp.n} rows checksum ${before.source.fp.h} -> ${after.source.fp.n} rows checksum ${after.source.fp.h}`);
  console.log(`# other  ${HT.other}: ${before.other.fp.n} rows checksum ${before.other.fp.h} -> ${after.other.fp.n} rows checksum ${after.other.fp.h}`);
  assert.equal(r.status, "cap_reached");
  assert.equal(r.reached_cap, true);
  assert.ok(r.after_bytes <= cap);
  assert.ok(r.chunks_dropped > 0 && r.dropped.length === r.chunks_dropped);
  assert.ok(r.dropped.every((d) => d.hypertable === HT.ours), "only Open-FDD chunks were dropped");
  assert.equal(after.ours.chunks.length, before.ours.chunks.length - r.chunks_dropped);
  assert.equal(after.ours.chunks.at(-1), before.ours.chunks.at(-1), "newest results chunk kept");
  assert.equal(pv.would_drop[0].chunk, r.dropped[0].chunk, "preview and run agree on the oldest chunk");
  assert.deepEqual(after.source, before.source, "source (NF-like) untouched: chunks, row count, checksum");
  assert.deepEqual(after.other, before.other, "unrelated app untouched: chunks, row count, checksum");
  const last = (await db.query("SELECT value FROM openfdd.config WHERE key = 'retention_last'")).rows[0].value;
  assert.deepEqual({ status: last.status, dry_run: last.dry_run }, { status: "cap_reached", dry_run: false });

  // already under the cap -> explicit no-op
  assert.equal((await enforce(cap)).status, "under_cap");
});

test("unreachable cap ends with an explicit no_progress result and still spares the other tables", { skip, timeout: 120000 }, async () => {
  await retentionFixture();
  const before = await snapshot();
  const r = await enforce(1);
  const after = await snapshot();
  assert.equal(r.status, "no_progress");
  assert.equal(r.reached_cap, false);
  assert.equal(after.ours.chunks.length, 1, "only the newest Open-FDD chunk remains");
  assert.equal(r.chunks_dropped, before.ours.chunks.length - 1);
  assert.deepEqual(after.source, before.source);
  assert.deepEqual(after.other, before.other);
  assert.equal((await db.query("SELECT value->>'status' AS s FROM openfdd.config WHERE key = 'retention_last'")).rows[0].s, "no_progress");
  const again = await enforce(1);
  assert.equal(again.status, "no_progress", "second call: nothing left, still an explicit status (no loop)");
  assert.equal(again.chunks_dropped, 0);
});

test("chunk budget per call is finite and reported", { skip, timeout: 120000 }, async () => {
  await retentionFixture();
  const before = await snapshot();
  await setCfg("max_chunks_per_call", 2);
  const r = await enforce(1);
  assert.equal(r.status, "chunk_budget_exhausted");
  assert.equal(r.chunks_dropped, 2);
  assert.equal((await snapshot()).ours.chunks.length, before.ours.chunks.length - 2);
  await setCfg("max_chunks_per_call", 1000);
  assert.equal((await enforce(1)).status, "no_progress", "next call continues and finishes");
  assert.deepEqual((await snapshot()).source, before.source);
});

test("a source table is trimmed only when it is explicitly allowlisted", { skip, timeout: 180000 }, async () => {
  await retentionFixture();
  const before = await snapshot();
  const newestStart = (await db.query(
    "SELECT range_start FROM timescaledb_information.chunks WHERE hypertable_schema = 'public' AND hypertable_name = 'data' ORDER BY range_end DESC LIMIT 1")).rows[0].range_start.toISOString();
  const newestRows = await fingerprint(HT.source, `"time" >= '${newestStart}'`);

  // 1) allowlist = [otherapp.events]: it (and fdd_results) go, NF-like source does not
  await setCfg("retention_allowlist", [HT.other]);
  const scope = (await db.query("SELECT schema_name || '.' || table_name AS t FROM openfdd.retention_scope()")).rows.map((x) => x.t);
  assert.deepEqual(scope, [HT.ours, HT.other]);
  const r1 = await enforce(1);
  assert.equal(r1.status, "no_progress");
  assert.ok(r1.dropped.some((d) => d.hypertable === HT.other), "the listed unrelated table was trimmed");
  assert.ok(r1.dropped.every((d) => d.hypertable !== HT.source));
  assert.deepEqual((await snapshot()).source, before.source, "source still untouched");

  // 2) allowlist = [public.data]: now the source table is trimmed to its newest chunk
  await setCfg("retention_allowlist", [HT.source]);
  const pv = await preview(1);
  assert.ok(pv.would_drop.some((d) => d.hypertable === HT.source), "preview shows the source drop");
  assert.deepEqual((await snapshot()).source, before.source, "preview did not drop");
  const otherNow = await snapshot();
  sourceDirty = true;
  const r2 = await enforce(1);
  assert.equal(r2.status, "no_progress");
  assert.ok(r2.dropped.length > 0 && r2.dropped.every((d) => d.hypertable === HT.source), "only the listed source table was trimmed");
  const afterSource = await chunkNames(HT.source);
  assert.equal(afterSource.length, 1, "newest source chunk kept");
  assert.deepEqual(await fingerprint(HT.source, `"time" >= '${newestStart}'`), newestRows, "the newest chunk's rows are intact");
  assert.deepEqual((await snapshot()).other, otherNow.other, "unlisted app table untouched in this run");
});

test("an invalid allowlist fails closed: nothing is dropped", { skip, timeout: 120000 }, async () => {
  await retentionFixture();
  const before = await snapshot();
  const cases = [
    ["unknown table", ["public.does_not_exist"]],
    ["regular (non-hyper) table", ["public.points"]],
    ["good + unknown", [HT.source, "public.nope"]],
    ["internal schema", ["_timescaledb_catalog.chunk"]],
    ["not a string", [42]],
    ["not an array", HT.source],
    ["bare name", ["data"]],
  ];
  for (const [label, value] of cases) {
    await setCfg("retention_allowlist", value);
    const r = await enforce(1);
    assert.equal(r.status, "refused_allowlist", label);
    assert.equal(r.chunks_dropped, 0, label);
    assert.match(r.error, /retention_allowlist/, label);
    const pv = await preview(1);
    assert.equal(pv.status, "refused_allowlist", `${label} (preview)`);
    await assert.rejects(db.query("SELECT openfdd.retention_allowlist()"), /retention_allowlist/, label);
    const s = await snapshot();
    assert.deepEqual(s.source, before.source, `${label}: source untouched`);
    assert.deepEqual(s.other, before.other, `${label}: other untouched`);
    assert.deepEqual(s.ours, before.ours, `${label}: even Open-FDD chunks untouched (fail closed)`);
  }
  await setCfg("retention_allowlist", []);
  assert.equal((await enforce(1)).status, "no_progress", "valid again: works");
});

test("upgrade: an installed global-retention job becomes scoped (same job, no duplicate)", { skip, timeout: 180000 }, async () => {
  await retentionFixture();
  // recreate an OLD box: legacy global functions, a job with no scope config, a duplicate job, old config
  await db.query("SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE proc_schema = 'openfdd'");
  await db.query(legacySql);
  const old = (await db.query("SELECT add_job('openfdd.size_cap_job', interval '1 day') AS id")).rows[0].id;
  await db.query("SELECT add_job('openfdd.size_cap_job', interval '1 day')");
  await db.query("DELETE FROM openfdd.config WHERE key IN ('retention_allowlist', 'max_chunks_per_call', 'schema_version')");
  await setCfg("max_bytes", 1);
  assert.equal(await ts.schemaVersion(db), 0);
  await assert.rejects(ts.maybeEnforceCap(db), /older than this release/, "the hook refuses to run retention on the old schema");
  const before = await snapshot();

  const inst = await ts.install(db);
  assert.equal(inst.schemaVersion, ts.SCHEMA_VERSION);
  const jobs = (await db.query("SELECT job_id, config FROM timescaledb_information.jobs WHERE proc_name = 'size_cap_job'")).rows;
  assert.equal(jobs.length, 1, "duplicates removed, never a second job");
  assert.equal(jobs[0].job_id, old, "the existing job was altered in place");
  assert.equal(jobs[0].config.scope, "openfdd+fdd+allowlist", "existing job marked scoped");
  assert.deepEqual((await db.query("SELECT value FROM openfdd.config WHERE key = 'retention_allowlist'")).rows[0].value, []);
  const def = (await db.query("SELECT pg_get_functiondef('openfdd.enforce_size_cap(bigint)'::regprocedure) AS d")).rows[0].d;
  assert.match(def, /retention_run/, "enforce_size_cap body replaced");

  // the job (cap = 1 byte in config) now only trims Open-FDD tables
  await db.query(`CALL run_job(${jobs[0].job_id})`);
  const after = await snapshot();
  assert.deepEqual(after.source, before.source, "the upgraded job leaves NF-like data alone");
  assert.deepEqual(after.other, before.other, "and the unrelated app");
  assert.equal(after.ours.chunks.length, 1, "while still enforcing the cap on Open-FDD results");
  assert.equal((await db.query("SELECT value->>'status' AS s FROM openfdd.config WHERE key = 'retention_last'")).rows[0].s, "no_progress");
  assert.equal((await ts.install(db)).schemaVersion, ts.SCHEMA_VERSION);
  assert.equal((await db.query("SELECT count(*)::int AS n FROM timescaledb_information.jobs WHERE proc_name = 'size_cap_job'")).rows[0].n, 1);
});

test("maybeEnforceCap: job present -> skipped; no job -> once a day, scoped", { skip }, async () => {
  await retentionFixture();
  const before = await snapshot();
  assert.deepEqual(await ts.maybeEnforceCap(db), { skipped: "job" });
  await db.query("SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE proc_name = 'size_cap_job'");
  await db.query("DELETE FROM openfdd.config WHERE key = 'last_cap_run'");
  const first = await ts.maybeEnforceCap(db, { now: Date.parse("2026-11-01T00:00:00Z") });
  assert.equal(first.status, "under_cap");
  assert.equal(first.chunks_dropped, 0);
  assert.deepEqual(await ts.maybeEnforceCap(db, { now: Date.parse("2026-11-01T12:00:00Z") }), { skipped: "ran < 24 h ago" });
  await setCfg("max_bytes", 1);
  const next = await ts.maybeEnforceCap(db, { now: Date.parse("2026-11-02T00:00:01Z") });
  assert.equal(next.status, "no_progress");
  assert.ok(next.dropped.every((d) => d.hypertable === HT.ours));
  const s = await snapshot();
  assert.deepEqual(s.source, before.source);
  assert.deepEqual(s.other, before.other);
  const pv = await ts.retentionPreview(db, 1);
  assert.equal(pv.dry_run, true);
});

test("openfdd_rt least-privilege role can read views and write fdd tables, never public.data (#1606)", { skip }, async () => {
  await seed();
  await ts.install(db);
  const { rows: pr } = await db.query("SELECT id::text AS id FROM public.points WHERE name = 'AHU-1/sat'");
  const ptId = pr[0].id;
  await ts.syncPoints(db, { siteId: "s1", equipId: "AHU-1", rows: ts.pointRows({ pack, siteId: "s1", equipId: "AHU-1", roleToUuid: { sat: ptId }, unitsByUuid: { [ptId]: "degF" } }) });
  const dbName = (await db.query("SELECT current_database() AS d")).rows[0].d;
  const role = `openfdd_rt_${Math.random().toString(16).slice(2, 10)}`;
  await db.query(`CREATE ROLE ${role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE`);
  try {
    await db.query(`GRANT USAGE ON SCHEMA public TO ${role}`);
    await db.query(`GRANT SELECT ON public.data, public.points, public.instances TO ${role}`);
    await db.query(`GRANT USAGE ON SCHEMA openfdd TO ${role}`);
    await db.query(`GRANT SELECT ON openfdd.nf_samples TO ${role}`);
    await db.query(`GRANT SELECT, INSERT, UPDATE ON openfdd.config TO ${role}`);
    await db.query(`GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA openfdd TO ${role}`);
    await db.query(`GRANT USAGE, CREATE ON SCHEMA fdd TO ${role}`);
    await db.query(`GRANT SELECT ON fdd.input_sample TO ${role}`);
    await db.query(`GRANT SELECT, INSERT, UPDATE, DELETE ON fdd.point, fdd.rule_result, fdd.rule_config TO ${role}`);
    await db.query(`GRANT TEMP ON DATABASE "${dbName}" TO ${role}`);

    const invokerRows = (await db.query(
      `SELECT c.relname, c.reloptions FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE (n.nspname = 'openfdd' AND c.relname = 'nf_samples') OR (n.nspname = 'fdd' AND c.relname = 'input_sample')`
    )).rows;
    assert.equal(invokerRows.length, 2);
    for (const r of invokerRows) {
      assert.ok((r.reloptions || []).includes("security_invoker=true"), `${r.relname} sets security_invoker=true`);
    }

    await db.query("BEGIN");
    try {
      await db.query(`SET LOCAL ROLE ${role}`);
      const n1 = (await db.query("SELECT count(*)::int AS n FROM openfdd.nf_samples WHERE point_uuid = $1", [ptId])).rows[0].n;
      const n2 = (await db.query("SELECT count(*)::int AS n FROM fdd.input_sample WHERE site_id = 's1'")).rows[0].n;
      assert.ok(n1 > 0 && n2 > 0, "runtime role reads both adapter views");

      const deny = async (sql, params = []) => {
        await db.query("SAVEPOINT sp");
        await assert.rejects(db.query(sql, params), /permission denied|cannot (insert into|update|delete from) view/i);
        await db.query("ROLLBACK TO SAVEPOINT sp");
        await db.query("RELEASE SAVEPOINT sp");
      };
      await deny("INSERT INTO public.data (point_id, time, value) VALUES ($1::uuid, '2026-10-15T00:00:00Z', 99)", [ptId]);
      await deny("UPDATE public.data SET value = 99 WHERE point_id = $1::uuid AND time = '2026-10-05T10:00:00Z'", [ptId]);
      await deny("DELETE FROM public.data WHERE point_id = $1::uuid AND time = '2026-10-05T10:00:00Z'", [ptId]);
      await deny("INSERT INTO openfdd.nf_samples (point_uuid, ts, value) VALUES ($1, '2026-10-15T00:00:00Z', 99)", [ptId]);
      await deny("UPDATE openfdd.nf_samples SET value = 99 WHERE point_uuid = $1 AND ts = '2026-10-05T10:00:00Z'", [ptId]);
      await deny("DELETE FROM openfdd.nf_samples WHERE point_uuid = $1 AND ts = '2026-10-05T10:00:00Z'", [ptId]);
      await deny("UPDATE fdd.input_sample SET value = 20 WHERE site_id = 's1' AND point_key = $1", [ptId]);
      await deny("DELETE FROM fdd.input_sample WHERE site_id = 's1' AND point_key = $1", [ptId]);

      await db.query(
        "INSERT INTO fdd.rule_config (site_id, rule_id, scope_key, revision, parameters, active, created_by) VALUES ('s1', 'FC1', 'site', 1, '{}', true, 'test')"
      );
      await db.query("DELETE FROM fdd.rule_config WHERE site_id = 's1' AND rule_id = 'FC1'");
    } finally {
      await db.query("ROLLBACK");
    }
  } finally {
    await db.query(`REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ${role}; REVOKE ALL ON SCHEMA public FROM ${role}; REVOKE ALL ON ALL TABLES IN SCHEMA openfdd FROM ${role}; REVOKE ALL ON ALL FUNCTIONS IN SCHEMA openfdd FROM ${role}; REVOKE ALL ON SCHEMA openfdd FROM ${role}; REVOKE ALL ON ALL TABLES IN SCHEMA fdd FROM ${role}; REVOKE ALL ON SCHEMA fdd FROM ${role}; REVOKE ALL ON DATABASE "${dbName}" FROM ${role}; DROP ROLE ${role}`);
    await db.query("DELETE FROM fdd.point WHERE site_id = 's1'");
  }
});

test("upgrade v3 -> v4 rolls back cleanly on transaction abort (#1606)", { skip }, async () => {
  await makeV3(`
    INSERT INTO openfdd.fdd_results (run_ts, equip, site, rule_id, fault_pct, fault_hours, covered_hours, engine, window_start, window_end, sensor_ref) VALUES
      ('2026-10-12T00:00:00Z', 'rb-eq', 's1', 'FC1', 10, 2, 24, 'timescale', '2026-10-11T00:00:00Z', '2026-10-12T00:00:00Z', '');
    INSERT INTO openfdd.retention_log (status, dry_run, result) VALUES ('under_cap', false, '{}');`);
  await db.query("BEGIN");
  try {
    await ts.install(db);
    await db.query("SELECT 1 / 0");
    assert.fail("expected division by zero");
  } catch (e) {
    assert.match(e.message, /division by zero/);
    await db.query("ROLLBACK");
  }
  assert.equal(await ts.schemaVersion(db), 3, "rollback restores v3");
  assert.equal((await db.query("SELECT count(*)::int AS n FROM openfdd.fdd_results")).rows[0].n, 1);
  assert.ok((await db.query("SELECT to_regclass('openfdd.retention_log') AS b")).rows[0].b);
  assert.equal((await db.query("SELECT count(*)::int AS n FROM fdd.rule_result WHERE equipment_id = 'rb-eq'")).rows[0].n, 0);
  // complete the upgrade cleanly afterward so subsequent tests see v4
  assert.equal((await ts.install(db)).schemaVersion, 4);
  await db.query("DELETE FROM fdd.rule_result WHERE equipment_id = 'rb-eq'");
});
