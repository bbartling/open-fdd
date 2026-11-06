// PGURL=postgres://postgres:example@localhost:55432/postgres node --test nf-app/timescale/test/timescale.test.mjs
// Needs the Docker TimescaleDB from docker-compose.yml (see ../README.md). Skips when PGURL is unset or unreachable.
// Checks: install idempotency, SI conversion in loadHistory, rule results == the pglite engine on the same
// history, writeResults, history_buckets / historyRoute, and the size cap.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("../../hooks/lib/timescale.js");
const { createEngine } = require("../../hooks/lib/engines.js");
const ofddUnits = require("../../static/units.js");
const pack = JSON.parse(readFileSync(new URL("../../rules/pack-postgres.json", import.meta.url), "utf8"));
const seedSql = readFileSync(fileURLToPath(new URL("./seed_nf_like.sql", import.meta.url)), "utf8");

const PGURL = process.env.PGURL;
let client = null;
let skip = false;
if (!PGURL) skip = "PGURL is not set (docker compose -f nf-app/timescale/test/docker-compose.yml up -d; PGURL=postgres://postgres:example@localhost:55432/postgres)";
else {
  try {
    client = await ts.connect({ connectionString: PGURL });
  } catch (e) {
    skip = `TimescaleDB not reachable at PGURL (${e.message})`;
  }
}
if (skip) console.log(`# SKIPPED: ${skip}`);

const EQUIP = "AHU-1";
const FROM = "2026-09-20T00:00:00Z";
const TO = "2026-10-14T00:00:00Z";
const STEP = pack.poll_seconds;
// Rules that run on this AHU's roles (a mix of fault, sensor-validation and metric rules).
const RULES = ["FC1", "FC2", "FC3", "FC4", "FC5", "FC6", "FC7", "FC8", "FC9", "FC10", "FC11", "FC12", "ECON-1", "ECON-2",
  "AHU-SATDEV", "AHU-DUCTHI", "AHU-SIMUL", "SV-RANGE", "SV-FLATLINE", "SV-SPIKE", "SV-STALE", "SV-RATE", "OAT-METEO",
  "FAN-RUNTIME-HOURS", "FAULT-ELAPSED-HOURS", "AVG-ZONE-TEMP"].filter((r) => pack.rules[r]);

let roleToUuid, unitsByUuid, loaded, ruleRun;

before(async () => {
  if (skip) return;
  await client.query(seedSql);
  await ts.install(client);
  const { rows } = await client.query("SELECT id::text AS id, name, units FROM public.points");
  roleToUuid = {};
  unitsByUuid = {};
  for (const r of rows) {
    roleToUuid[r.name.replace(/^AHU-1\//, "")] = r.id;
    unitsByUuid[r.id] = r.units;
  }
});

after(async () => {
  if (skip) return;
  // leave a fresh, installed DB behind for poking (the cap test deletes chunks)
  await client.query(seedSql);
  await ts.install(client);
  await client.end();
});

const close = (a, b) => {
  if (a == null || b == null) return (a ?? null) === (b ?? null);
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-9 + 1e-6 * Math.max(Math.abs(a), Math.abs(b));
  return String(a) === String(b);
};
const diffRows = (a, b) => {
  const key = (r) => String(r.equipment_id);
  const x = [...a].sort((p, q) => key(p).localeCompare(key(q)));
  const y = [...b].sort((p, q) => key(p).localeCompare(key(q)));
  if (x.length !== y.length) return [`row count ${x.length} vs ${y.length}`];
  const out = [];
  x.forEach((ra, i) => {
    for (const k of new Set([...Object.keys(ra), ...Object.keys(y[i])])) if (!close(ra[k], y[i][k])) out.push(`${k}: ${ra[k]} vs ${y[i][k]}`);
  });
  return out;
};

test("install is idempotent and registers the size-cap job", { skip }, async () => {
  const a = await ts.install(client);
  const b = await ts.install(client);
  assert.equal(b.maxBytes, 107374182400, "default cap is 100 GB");
  assert.deepEqual(a, b);
  const { rows } = await client.query("SELECT count(*)::int AS n FROM timescaledb_information.jobs WHERE proc_name = 'size_cap_job'");
  assert.equal(rows[0].n, 1, "exactly one job after two installs");
  const ht = await client.query("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_schema = 'openfdd'");
  assert.deepEqual(ht.rows.map((r) => r.hypertable_name), ["fdd_results"]);
  console.log(`# add_job registered: ${a.jobRegistered}`);
  assert.equal(a.jobRegistered, true);
  const s = await client.query("SELECT count(*)::int AS n FROM openfdd.nf_samples");
  assert.ok(s.rows[0].n > 200000, `adapter view sees the seeded NF data (${s.rows[0].n} rows)`);
});

test("loadHistory builds the wide history in SI", { skip }, async () => {
  loaded = await ts.loadHistory(client, { pack, equipId: EQUIP, siteId: "site-1", roleToUuid, unitsByUuid, from: FROM, to: TO, stepSec: STEP });
  const days = (Date.parse(TO) - Date.parse(FROM)) / 864e5;
  assert.equal(loaded.rows, days * 288, "one row per 5-minute bucket");
  assert.equal(loaded.si.sat, "°C");
  assert.equal(loaded.si.duct_static, "Pa");
  const t = "2026-10-05T10:00:00Z";
  const raw = (await client.query(
    `SELECT avg(d.value) FILTER (WHERE p.name = 'AHU-1/sat') AS sat, avg(d.value) FILTER (WHERE p.name = 'AHU-1/duct_static') AS ds,
            avg(d.value) FILTER (WHERE p.name = 'AHU-1/fan_status') AS fs
     FROM public.data d JOIN public.points p ON p.id = d.point_id WHERE d."time" >= $1 AND d."time" < $1::timestamptz + interval '5 minutes'`, [t])).rows[0];
  const h = (await client.query("SELECT sat, duct_static, fan_status, zone_t FROM pg_temp.history WHERE timestamp_utc = $1", [t])).rows[0];
  assert.ok(raw.sat > 40 && raw.sat < 100, `raw sat is in degF (${raw.sat})`);
  assert.ok(Math.abs(h.sat - (raw.sat - 32) * 5 / 9) < 1e-9, `sat ${raw.sat} degF -> ${h.sat} degC`);
  assert.ok(h.sat > 5 && h.sat < 40, "sat is plausible degC");
  assert.ok(Math.abs(h.duct_static - raw.ds * ofddUnits.toSI(1, "inH2O").value) < 1e-9, "duct static inH2O -> Pa");
  assert.equal(h.fan_status, raw.fs, "unitless status passes through");
  const w = (await client.query("SELECT count(*)::int AS n FROM pg_temp.weather")).rows[0].n;
  assert.equal(w, loaded.rows, "weather mirrors the oa_t grid");
});

test("rules in Timescale == the pglite engine on the same history", { skip, timeout: 280000 }, async () => {
  const t0 = Date.now();
  ruleRun = await ts.runRules(client, pack, RULES);
  const tsMs = Date.now() - t0;
  // same rows -> pglite
  const q = async (sql) => (await client.query(sql)).rows;
  const hist = (await q("SELECT * FROM pg_temp.history ORDER BY timestamp_utc")).map(({ timestamp_utc, ...r }) => ({ ...r, ts: timestamp_utc.getTime() }));
  const weather = (await q("SELECT * FROM pg_temp.weather ORDER BY timestamp_utc")).map(({ timestamp_utc, ...r }) => ({ ...r, ts: timestamp_utc.getTime() }));
  const input = {
    historyColumns: pack.contract.history.map((c) => ({ name: c.name, type: c.type })),
    history: hist, weather, authorizedSeries: await q("SELECT * FROM pg_temp.authorized_series"),
    equipment: await q("SELECT * FROM pg_temp.equipment"),
  };
  const eng = await createEngine({ kind: "pglite", pack });
  let matched = 0, bothError = 0, withFault = 0;
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
    }
  } finally { await eng.close(); }
  console.log(`# rules compared: ${RULES.length}, matched: ${matched}, both-error: ${bothError}, with fault>0: ${withFault}, timescale run ${tsMs} ms`);
  assert.deepEqual(problems, []);
  assert.ok(matched >= 15, `at least 15 rules must run and match (got ${matched})`);
  assert.ok(withFault >= 1, "the seeded faults are detected");
  const fc1 = ruleRun.results.FC1[0];
  assert.equal(fc1.equipment_id, EQUIP);
  assert.equal(typeof fc1.fault_pct, "number", "numbers are coerced");
});

test("writeResults upserts into openfdd.fdd_results", { skip }, async () => {
  assert.ok(ruleRun, "needs the rules test");
  const runTs = "2026-10-14T00:00:00Z";
  const rows = [];
  for (const [id, res] of Object.entries(ruleRun.results)) {
    const row = res.find((r) => r.equipment_id === EQUIP);
    if (row) rows.push(ts.toResultRow({ runTs, equip: EQUIP, site: "site-1", ruleId: id, row, windowStart: FROM, windowEnd: TO }));
  }
  assert.ok(rows.length >= 15);
  assert.equal(await ts.writeResults(client, rows), rows.length);
  assert.equal(await ts.writeResults(client, rows), rows.length, "second write upserts");
  const n = (await client.query("SELECT count(*)::int AS n FROM openfdd.fdd_results WHERE run_ts = $1", [runTs])).rows[0].n;
  assert.equal(n, rows.length, "no duplicates");
  const back = (await client.query("SELECT fault_pct, fault_hours, covered_hours, engine, window_start FROM openfdd.fdd_results WHERE rule_id = 'FC1'")).rows[0];
  assert.ok(close(back.fault_pct, ruleRun.results.FC1[0].fault_pct));
  assert.equal(back.engine, "timescale");
  assert.equal(back.window_start.toISOString(), "2026-09-20T00:00:00.000Z");
});

test("history_buckets and historyRoute", { skip }, async () => {
  const sat = roleToUuid.sat;
  const { rows } = await client.query(
    "SELECT * FROM openfdd.history_buckets($1::text[], '2026-09-15Z', '2026-10-15Z', interval '1 day')", [[sat]]);
  assert.equal(rows.length, 30);
  const day = rows.find((r) => r.bucket.toISOString() === "2026-10-05T00:00:00.000Z");
  const raw = (await client.query(
    "SELECT avg(value) AS a, min(value) AS mn, max(value) AS mx, count(*)::int AS n FROM public.data WHERE point_id = $1::uuid AND \"time\" >= '2026-10-05Z' AND \"time\" < '2026-10-06Z'", [sat])).rows[0];
  assert.ok(close(day.avg, raw.a) && close(day.min, raw.mn) && close(day.max, raw.mx));
  assert.equal(Number(day.n), raw.n);
  const gapDay = rows.find((r) => r.bucket.toISOString() === "2026-09-21T00:00:00.000Z");
  assert.equal(Number(gapDay.n), 288 - 37, "the 3 h SAT outage leaves 251 samples");
  assert.ok(Number(gapDay.n) < 288);

  const r = await ts.historyRoute(client, { uuids: [sat, roleToUuid.oa_t], from: "2026-09-15T00:00:00Z", to: "2026-10-15T00:00:00Z", bucket: "1 day" });
  assert.equal(r.rows.length, 60);
  assert.equal(r.truncated, false);
  const auto = await ts.historyRoute(client, { uuids: [sat], from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z" });
  assert.equal(auto.bucket, "6 hours", "59 days / ~1000 buckets");
  const big = await ts.historyRoute(client, { uuids: Object.values(roleToUuid), from: "2026-09-01T00:00:00Z", to: "2026-10-30T00:00:00Z", bucket: "5 minutes" });
  assert.equal(big.truncated, true);
  assert.ok(JSON.stringify(big).length <= 200000 + 400, `capped JSON (${JSON.stringify(big).length} bytes)`);
  await assert.rejects(ts.historyRoute(client, { uuids: [sat], from: "2026-09-01Z", to: "2026-10-01Z", bucket: "1 day; drop table x" }));
});

test("size cap drops the oldest chunks, keeps the newest, and reports it", { skip }, async () => {
  // fdd_results needs several 30-day chunks too
  for (const m of ["2026-05-15", "2026-06-15", "2026-07-15", "2026-08-15", "2026-09-15"]) {
    await client.query(
      "INSERT INTO openfdd.fdd_results (run_ts, equip, rule_id, fault_pct) VALUES ($1::timestamptz, 'AHU-1', 'FC1', 1.0) ON CONFLICT DO NOTHING", [m]);
  }
  const chunks = async () => (await client.query(
    `SELECT hypertable_name AS h, chunk_name, range_start, range_end FROM timescaledb_information.chunks
     WHERE hypertable_schema IN ('public', 'openfdd') ORDER BY range_end`)).rows;
  const total = async () => Number((await client.query("SELECT openfdd.hypertables_bytes() AS b")).rows[0].b);
  const before = await chunks();
  const dataBefore = before.filter((c) => c.h === "data");
  const resBefore = before.filter((c) => c.h === "fdd_results");
  assert.ok(dataBefore.length >= 55 && resBefore.length >= 5, `${dataBefore.length} data chunks, ${resBefore.length} result chunks`);
  const size0 = await total();

  // 1) cap at 60% of the current size
  const cap = Math.floor(size0 * 0.6);
  const s1 = (await client.query("SELECT openfdd.enforce_size_cap($1::bigint) AS r", [cap])).rows[0].r;
  const after1 = await chunks();
  const size1 = await total();
  console.log(`# cap test 1: before ${size0} B, cap ${cap} B, after ${size1} B, dropped ${s1.chunks_dropped} chunks (of ${before.length}), reached_cap=${s1.reached_cap}`);
  assert.equal(s1.before_bytes, size0);
  assert.equal(s1.after_bytes, size1);
  assert.ok(size1 <= cap && s1.reached_cap === true);
  assert.ok(s1.chunks_dropped > 0);
  assert.equal(s1.dropped.length, s1.chunks_dropped);
  assert.equal(after1.length, before.length - s1.chunks_dropped, "chunk count matches the summary");
  assert.ok(s1.dropped.every((d) => d.bytes > 0));
  // oldest first: every dropped data chunk ends before every surviving data chunk starts
  const droppedData = s1.dropped.filter((d) => d.hypertable === "public.data");
  const keptData = after1.filter((c) => c.h === "data");
  assert.ok(droppedData.length > 0);
  const maxDroppedEnd = Math.max(...droppedData.map((d) => Date.parse(d.range_end)));
  assert.ok(keptData.every((c) => c.range_start.getTime() >= maxDroppedEnd - 1), "only the oldest data chunks were dropped");
  assert.equal(keptData.at(-1).chunk_name, dataBefore.at(-1).chunk_name, "newest data chunk kept");
  assert.equal(after1.filter((c) => c.h === "fdd_results").at(-1).chunk_name, resBefore.at(-1).chunk_name, "newest results chunk kept");
  // data actually gone
  const oldest = (await client.query("SELECT min(\"time\") AS t FROM public.data")).rows[0].t;
  assert.ok(oldest.getTime() >= maxDroppedEnd - 1);

  // 2) already under the cap -> no-op
  const s2 = (await client.query("SELECT openfdd.enforce_size_cap($1::bigint) AS r", [cap])).rows[0].r;
  assert.equal(s2.chunks_dropped, 0);
  assert.equal(s2.reached_cap, true);

  // 3) impossible cap (1 byte): everything but the newest chunk of each hypertable goes
  const s3 = (await client.query("SELECT openfdd.enforce_size_cap(1) AS r")).rows[0].r;
  const after3 = await chunks();
  console.log(`# cap test 3: cap 1 B, dropped ${s3.chunks_dropped}, left ${after3.length} chunks, reached_cap=${s3.reached_cap}`);
  assert.equal(s3.reached_cap, false);
  assert.deepEqual(after3.map((c) => c.h).sort(), ["data", "fdd_results"], "exactly one (newest) chunk per hypertable remains");
  assert.equal(after3.find((c) => c.h === "data").chunk_name, dataBefore.at(-1).chunk_name);
  assert.equal(s3.chunks_dropped, after1.length - 2);

  // config + hook-driven cap
  await client.query("UPDATE openfdd.config SET value = to_jsonb(12345::bigint) WHERE key = 'max_bytes'");
  assert.equal(Number((await client.query("SELECT openfdd.max_bytes() AS m")).rows[0].m), 12345);
  await client.query("UPDATE openfdd.config SET value = to_jsonb(107374182400::bigint) WHERE key = 'max_bytes'");
  const m = await ts.maybeEnforceCap(client);
  assert.deepEqual(m, { skipped: "job" }, "with the TimescaleDB job registered the hook does not enforce");
});

test("maybeEnforceCap runs once a day when no job exists", { skip }, async () => {
  await client.query("SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE proc_name = 'size_cap_job'");
  await client.query("DELETE FROM openfdd.config WHERE key = 'last_cap_run'");
  const first = await ts.maybeEnforceCap(client, { now: Date.parse("2026-11-01T00:00:00Z") });
  assert.equal(first.chunks_dropped, 0);
  assert.equal(first.reached_cap, true);
  assert.deepEqual(await ts.maybeEnforceCap(client, { now: Date.parse("2026-11-01T12:00:00Z") }), { skipped: "ran < 24 h ago" });
  const next = await ts.maybeEnforceCap(client, { now: Date.parse("2026-11-02T00:00:01Z") });
  assert.equal(next.reached_cap, true);
});
