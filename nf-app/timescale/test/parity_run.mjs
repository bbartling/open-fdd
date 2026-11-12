// Parity runner for the Timescale path (called by tests/parity/adapters.py TimescaleAdapter; never by hand in production).
//
//   OPENFDD_TS_TEST_DISPOSABLE=1 PGURL=postgres://postgres:example@localhost:55432/postgres \
//     node nf-app/timescale/test/parity_run.mjs --in input.json --out output.json
//   node nf-app/timescale/test/parity_run.mjs --plan-only --in input.json --out output.json     (no database)
//
// What it proves (the new tables, end to end):
//   1. a disposable database (disposable.mjs: opt-in + own database + marker) gets an NF-like public.points / public.data
//      seeded from the dataset in NATIVE units (to_imperial), so the affine fdd.input_sample view is exercised;
//   2. ts.install() (core.sql, adapter_nf.sql, install.sql), then per equipment: pointRows + syncPoints (fdd.point) with the
//      scale decisions of the hook's siPlan, loadHistory from fdd.input_sample;
//   3. the loaded `history` equals the SI dataset cell for cell (1e-9 relative);
//   4. every rule runs, rows go through toResultRow + writeResults into fdd.rule_result and are read BACK from it;
//   5. a second write of the same rows changes nothing (idempotent upsert), the loader query can use NF's index, and the
//      view's columns equal the input contract's `sources`.
// The weather table is a site-level input outside the core tables: the harness feeds the dataset's weather (as the PGlite
// run does) so the verdict isolates the point / sample / result path.
// Input JSON: { site_id, window: {from_ms, to_ms}, step_seconds, points, samples: {point_key: [[ts_ms], [value]]},
//               si_history: {equipment_id: [rows]}, weather: [rows], history_columns }.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createDb, dbNameFor, dropDb, guarded, newToken, OPT_IN, urlForDb, assertDisposable } from "./disposable.mjs";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..", "..");
const ts = require("../../hooks/lib/timescale.js");
const hook = require("../../hooks/fdd.js");
const pack = JSON.parse(readFileSync(path.join(root, "nf-app/rules/pack-postgres.json"), "utf8"));
const catalog = JSON.parse(readFileSync(path.join(root, "nf-app/static/fdd-catalog.json"), "utf8"));
const contract = JSON.parse(readFileSync(path.join(root, "sql/fdd/input_contract.json"), "utf8"));

const arg = (name, dflt) => { const i = process.argv.indexOf("--" + name); return i > 0 ? process.argv[i + 1] : dflt; };
const planOnly = process.argv.includes("--plan-only");
const input = JSON.parse(readFileSync(arg("in"), "utf8"));
const outFile = arg("out");
const SITE = input.site_id;
const STEP = input.step_seconds;
const FROM = new Date(input.window.from_ms);
const TO = new Date(input.window.to_ms);
const histCols = new Map(pack.contract.history.map((c) => [c.name, c]));

const uuidOf = (key) => {
  const h = createHash("md5").update(key).digest("hex");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
};
/** The unit string NF would hold for a point of the dataset (the dataset says "bool" / "%" for humidity). */
const nfUnit = (p) => (p.kind === "bool" ? "" : p.scale === "percent_rh" ? "%RH" : p.unit || "");
const close = (a, b) => Math.abs(a - b) <= 1e-9 + 1e-9 * Math.max(Math.abs(a), Math.abs(b));
const num = (v) => (v == null ? null : typeof v === "number" ? v : Number.isFinite(Number(v)) ? Number(v) : v === "Occupied" ? 1 : 0);

const equips = [...new Set(input.points.map((p) => p.equipment_id))].sort();
const keyOf = new Map(input.points.map((p) => [p.point_key, uuidOf(p.point_key)]));
const pointOfUuid = new Map(input.points.map((p) => [uuidOf(p.point_key), p]));

/** What fdd.js hands the engine for one equipment: siPlan's decisions over the bound roles + sweep sensors. */
function planFor(equip) {
  const own = input.points.filter((p) => p.equipment_id === equip);
  const unitsByUuid = Object.fromEntries(own.map((p) => [keyOf.get(p.point_key), nfUnit(p)]));
  const roleP = own.filter((p) => !p.series && histCols.has(p.role));
  const numeric = {};
  for (const p of roleP) {
    if (histCols.get(p.role).type === "text") continue;
    numeric[p.role] = { uuid: keyOf.get(p.point_key), name: p.point_key, units: nfUnit(p), kind: p.kind === "bool" ? "Bool" : "Number" };
  }
  const plan = hook.siPlan(numeric, catalog);
  const roleToUuid = {};
  for (const p of roleP) if (!plan.skipped.has(p.role)) roleToUuid[p.role] = keyOf.get(p.point_key);
  const sensorSeries = own.filter((p) => p.series).map((p) => ({ uuid: keyOf.get(p.point_key), role: p.role, unit: p.si_unit }));
  const pointMeta = Object.fromEntries(own.map((p) => [keyOf.get(p.point_key), { name: p.point_key, kind: p.kind === "bool" ? "Bool" : "Number" }]));
  return { plan, args: { siteId: SITE, equipId: equip, roleToUuid, unitsByUuid, fractionRoles: [...plan.scaled], booleanRoles: [...plan.bool], sensorSeries, pointMeta } };
}

const siByEquip = new Map();
for (const [equip, rows] of Object.entries(input.si_history)) siByEquip.set(equip, new Map(rows.map((r) => [r.ts, r])));

/** No database: the native samples times the point rows' scale / offset must equal the SI dataset. */
function factorCheck() {
  const bad = [];
  const skipped = {};
  for (const equip of equips) {
    const { plan, args } = planFor(equip);
    if (plan.skipped.size) skipped[equip] = [...plan.skipped];
    const rows = ts.pointRows({ pack, ...args });
    for (const r of rows) {
      const p = pointOfUuid.get(r.point_key);
      const [tsList, vals] = input.samples[p.point_key];
      const si = siByEquip.get(equip);
      for (let i = 0; i < tsList.length; i++) {
        const want = num(si.get(tsList[i])?.[p.role]);
        const got = vals[i] * r.si_scale + r.si_offset;
        if (want == null || !close(got, want)) { bad.push(`${p.point_key}@${tsList[i]}: ${got} vs ${want}`); break; }
      }
    }
  }
  return { factor_mismatches: bad, skipped };
}

if (planOnly) {
  writeFileSync(outFile, JSON.stringify(factorCheck()));
  process.exit(0);
}

// ------------------------------------------------------------------ database path
const PGURL = process.env.PGURL;
if (process.env[OPT_IN] !== "1" || !PGURL) {
  console.error(`parity_run.mjs refused: ${OPT_IN}=1 and PGURL (admin connection) are required; it creates and drops its own database`);
  process.exit(3);
}
const TOKEN = newToken();
const DBNAME = dbNameFor(TOKEN);
const admin = await ts.connect({ connectionString: PGURL });
let raw = null;
try {
  await createDb(admin, DBNAME, TOKEN);
  raw = await ts.connect({ connectionString: urlForDb(PGURL, DBNAME) });
  await assertDisposable(raw, TOKEN);
  const db = guarded(raw, TOKEN);
  const timing = {};
  let t0 = Date.now();

  // NF-like northbound schema (same shape as seed_nf_like.sql), seeded in native units
  await db.query(`
    CREATE EXTENSION IF NOT EXISTS timescaledb;
    CREATE TABLE public.instances (id uuid PRIMARY KEY, name text NOT NULL);
    CREATE TABLE public.points (id uuid PRIMARY KEY, instance_id uuid REFERENCES public.instances(id), name text NOT NULL, units text);
    CREATE TABLE public.data (point_id uuid NOT NULL, "time" timestamptz NOT NULL, value double precision);
    SELECT create_hypertable('public.data', 'time', chunk_time_interval => interval '1 day');
    CREATE INDEX ON public.data (point_id, "time" DESC);
    INSERT INTO public.instances VALUES (md5('instance')::uuid, 'parity');`);
  for (const p of input.points) {
    await db.query("INSERT INTO public.points VALUES ($1::uuid, md5('instance')::uuid, $2, $3)", [keyOf.get(p.point_key), p.point_key, nfUnit(p)]);
    const [tsList, vals] = input.samples[p.point_key];
    await db.query(
      `INSERT INTO public.data (point_id, "time", value) SELECT $1::uuid, to_timestamp(t / 1000.0), v FROM unnest($2::float8[], $3::float8[]) AS u(t, v)`,
      [keyOf.get(p.point_key), tsList, vals]);
  }
  await db.query("ANALYZE public.data");
  timing.seed_ms = Date.now() - t0;

  t0 = Date.now();
  const installed = await ts.install(db);
  const sig = (await db.query(
    `SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type FROM pg_attribute a
     WHERE a.attrelid = 'fdd.input_sample'::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum`)).rows;
  const typeNames = { double: "double precision", text: "text", timestamp: "timestamp with time zone" };
  const wantSig = Object.entries(contract.sources.input_sample.columns).map(([name, c]) => ({ name, type: typeNames[c.type] }));
  const signatureOk = JSON.stringify(sig) === JSON.stringify(wantSig);

  const history_mismatches = [];
  const results = {};
  const written = [];
  let indexOk = null;
  timing.install_ms = Date.now() - t0;
  t0 = Date.now();
  const ruleIds = Object.keys(pack.rules);
  const errors = {};
  const runTs = new Date(TO.getTime());
  for (const equip of equips) {
    const { plan, args } = planFor(equip);
    await ts.syncPoints(db, { siteId: SITE, equipId: equip, rows: ts.pointRows({ pack, ...args }) });
    const loaded = await ts.loadHistory(db, { pack, ...args, from: FROM, to: TO, stepSec: STEP });

    // cell-for-cell: the loaded history == the SI dataset
    const got = new Map((await db.query("SELECT * FROM pg_temp.history ORDER BY timestamp_utc")).rows.map((r) => [r.timestamp_utc.getTime(), r]));
    const want = siByEquip.get(equip);
    for (const [t, row] of want) {
      const g = got.get(t);
      for (const role of Object.keys(args.roleToUuid)) {
        const w = num(row[role]);
        const v = g ? num(g[role]) : null;
        if ((w == null) !== (v == null) || (w != null && !close(v, w))) {
          history_mismatches.push(`${equip} ${role} @${t}: ${v} vs ${w}`);
          if (history_mismatches.length > 50) break;
        }
      }
    }
    for (const t of got.keys()) if (!want.has(t)) history_mismatches.push(`${equip}: extra loaded row @${t}`);

    // site-level weather from the dataset (outside the core tables)
    await db.query("DELETE FROM pg_temp.weather");
    const wcols = pack.contract.weather.map((c) => c.name).filter((n) => n !== "timestamp_utc");
    if (input.weather.length) {
      await db.query(
        `INSERT INTO pg_temp.weather (timestamp_utc, ${wcols.map((c) => `"${c}"`).join(", ")})
         SELECT to_timestamp((r->>'ts')::float8 / 1000.0), ${wcols.map((c) => `(r->>'${c}')::double precision`).join(", ")}
         FROM jsonb_array_elements($1::jsonb) r`, [JSON.stringify(input.weather)]);
    }

    const run = await ts.runRules(db, pack, ruleIds);
    Object.assign(errors, Object.fromEntries(Object.entries(run.errors).map(([k, v]) => [`timescale ${k}`, v])));
    for (const [rid, rows] of Object.entries(run.results)) {
      for (const row of rows) {
        written.push(ts.toResultRow({ runTs, equip, site: SITE, ruleId: rid, row, windowStart: FROM, windowEnd: TO, pollSeconds: STEP }));
      }
    }
    if (indexOk === null && loaded.rows) {
      await db.query("BEGIN");
      try {
        await db.query("SET LOCAL enable_seqscan = off");
        const any = Object.values(args.roleToUuid)[0];
        const plan0 = (await db.query(
          `EXPLAIN (FORMAT JSON) SELECT avg(value) FROM fdd.input_sample WHERE site_id = $1::text AND point_key = ANY($2::text[]) AND ts >= $3::timestamptz AND ts < $4::timestamptz`,
          [SITE, [any], FROM.toISOString(), TO.toISOString()])).rows[0]["QUERY PLAN"];
        const nodes = [];
        const walk = (n) => { nodes.push(n); (n.Plans || []).forEach(walk); };
        walk(plan0[0].Plan);
        const scans = nodes.filter((n) => /^_hyper_/.test(n["Relation Name"] || ""));
        indexOk = scans.length > 0 && scans.every((n) => /Index/.test(n["Node Type"]));
      } finally { await db.query("ROLLBACK"); }
    }
  }
  timing.rules_ms = Date.now() - t0;

  // write, count, write again: an upsert on the primary key adds nothing
  const count = async () => Number((await db.query("SELECT count(*) AS n FROM fdd.rule_result")).rows[0].n);
  await ts.writeResults(db, written);
  const before = await count();
  await ts.writeResults(db, written);
  const after = await count();

  // read the results BACK from fdd.rule_result, in the row shape of the rule's output columns
  const stored = (await db.query(
    "SELECT equipment_id, rule_id, subject_key, role, fault_hours, covered_hours, fault_pct, metrics FROM fdd.rule_result WHERE site_id = $1 ORDER BY equipment_id, rule_id, subject_key", [SITE])).rows;
  for (const r of stored) {
    const cols = pack.rules[r.rule_id].output_columns || [];
    const sweep = cols.includes("series_id");
    if (sweep ? r.subject_key === "" : r.subject_key !== "") continue;
    const row = {};
    for (const c of cols) {
      if (c === "equipment_id") row[c] = r.equipment_id;
      else if (c === "series_id") row[c] = pointOfUuid.get(r.subject_key)?.point_key ?? r.subject_key;
      else if (c === "sensor_role") row[c] = r.role;
      else if (c === "fault_hours" || c === "covered_hours" || c === "fault_pct") row[c] = r[c];
      else row[c] = r.metrics[c] ?? null;
    }
    (results[r.rule_id] ||= []).push(row);
  }
  for (const rid of ruleIds) results[rid] ||= [];

  writeFileSync(outFile, JSON.stringify({
    results, errors, timing, memory: { rss_peak_mb: Math.round(process.memoryUsage().rss / 1048576) },
    history_mismatches, written: written.length, stored: { before, after }, index_ok: indexOk, signature_ok: signatureOk,
    schema_version: installed.schemaVersion, factor: factorCheck(),
  }));
  console.log(`wrote ${outFile}: ${written.length} rows, ${stored.length} stored, history mismatches ${history_mismatches.length}`);
} finally {
  if (raw) await raw.end();
  try { await dropDb(admin, DBNAME); } catch (e) { console.error(`could not drop ${DBNAME}: ${e.message}`); }
  await admin.end();
}
