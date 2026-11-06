"use strict";
/**
 * Open-FDD on NF's TimescaleDB northbound database (FULL edition). CommonJS, npm package `pg`.
 *
 *   const ts = require("./lib/timescale");
 *   const client = await ts.connect(config.timescale);   // { connectionString | host,port,database,user, passwordEnv }
 *   await ts.install(client);                            // adapter_nf.sql + install.sql (idempotent)
 *   const h = await ts.loadHistory(client, { equipId, roleToUuid, unitsByUuid, from, to, stepSec: pack.poll_seconds });
 *   const { results, errors } = await ts.runRules(client, pack, ruleIds);
 *   await ts.writeResults(client, rows);
 *   await ts.maybeEnforceCap(client);
 *   await client.end();
 *
 * NF's own tables are only touched through the view openfdd.nf_samples (timescale/adapter_nf.sql).
 * The rules run in the SAME session: loadHistory creates TEMP tables history / weather / ... with the
 * pack contract's columns, which shadow nothing in NF's schema (pg_temp is searched first).
 * Secrets: password comes from the env var named by config.passwordEnv (or config.password, an NF hook
 * setting), never from the repo.
 */
const fs = require("fs");
const path = require("path");

const SQL_DIR = path.join(__dirname, "..", "..", "timescale");
const ofddUnits = require("../../static/units.js");

const NUMERIC_OIDS = new Set([20, 21, 23, 700, 701, 1700]);
const IDENT = /^[a-z_][a-z0-9_]*$/;
const quoteId = (s) => '"' + String(s).replace(/"/g, '""') + '"';
const iso = (t) => (t instanceof Date ? t : new Date(t)).toISOString();

// ---------------------------------------------------------------- connect / install

/** Connected pg Client. config: { connectionString } or { host, port, database, user, passwordEnv|password, ssl }. */
async function connect(config = {}) {
  const { Client } = require("pg");
  const opts = {};
  if (config.connectionString) opts.connectionString = config.connectionString;
  else {
    if (!config.host) throw new Error("timescale config needs connectionString or host");
    Object.assign(opts, { host: config.host, port: config.port || 5432, database: config.database || "postgres", user: config.user });
  }
  const pw = config.passwordEnv ? process.env[config.passwordEnv] : config.password;
  if (pw) opts.password = pw;
  if (config.ssl) opts.ssl = config.ssl;
  opts.application_name = "open-fdd";
  const client = new Client(opts);
  await client.connect();
  return client;
}

/** Runs adapter_nf.sql then install.sql. Returns { jobRegistered, maxBytes }. */
async function install(client) {
  for (const f of ["adapter_nf.sql", "install.sql"]) {
    await client.query(fs.readFileSync(path.join(SQL_DIR, f), "utf8"));
  }
  const { rows } = await client.query("SELECT key, value FROM openfdd.config WHERE key IN ('job_registered', 'max_bytes')");
  const cfg = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  return { jobRegistered: cfg.job_registered === true || cfg.job_registered === "true", maxBytes: Number(cfg.max_bytes) };
}

// ---------------------------------------------------------------- history -> session TEMP tables

const TYPE = { double: "double precision", text: "text", timestamp: "timestamptz" };

/** Affine factors v_si = a + b * v for a unit (toSI is linear/affine); unknown unit = identity. */
function siFactors(unit) {
  const r0 = ofddUnits.toSI(0, unit);
  const r1 = ofddUnits.toSI(1, unit);
  if (!r0 || !r1) return { a: 0, b: 1, unit: unit || "" };
  return { a: r0.value, b: r1.value - r0.value, unit: r0.unit };
}

async function createTempTables(client, pack) {
  for (const [table, cols] of Object.entries(pack.contract)) {
    if (!IDENT.test(table)) throw new Error(`bad table name ${table}`);
    await client.query(`DROP TABLE IF EXISTS pg_temp.${table}`);
    await client.query(`CREATE TEMP TABLE ${table} (${cols.map((c) => `${quoteId(c.name)} ${TYPE[c.type]}`).join(", ")})`);
  }
}

/**
 * Builds the pack's wide `history` (+ weather, authorized_series, equipment) as TEMP tables in this session.
 *   roleToUuid  {role: pointUuid}   roles must be history columns of pack.contract
 *   unitsByUuid {pointUuid: nfUnit} values are converted to SI in SQL (a + b*avg): one avg per role per bucket
 * Returns { rows, roles, si: {role: unit}, bytes: 0 }. rows = history rows written (0 = no data in the window).
 */
async function loadHistory(client, { pack, equipId, siteId = "", roleToUuid, unitsByUuid = {}, from, to, stepSec }) {
  if (!pack || !pack.contract) throw new Error("loadHistory: pack is required");
  const step = Number(stepSec || pack.poll_seconds);
  if (!(step > 0)) throw new Error("loadHistory: stepSec must be > 0");
  const histCols = new Map(pack.contract.history.map((c) => [c.name, c]));
  const roles = Object.entries(roleToUuid || {}).filter(([r]) => histCols.has(r) && r !== "equipment_id" && r !== "timestamp_utc");
  await createTempTables(client, pack);

  const params = [step, iso(from), iso(to), [...new Set(roles.map(([, u]) => u))], equipId];
  const exprs = roles.map(([role, uuid]) => {
    params.push(uuid);
    const u = `$${params.length}`;
    if (histCols.get(role).type === "text") {
      return `max(value) FILTER (WHERE point_uuid = ${u})::text AS ${quoteId(role)}`;
    }
    const f = siFactors(unitsByUuid[uuid]);
    params.push(f.a, f.b);
    return `(avg(value) FILTER (WHERE point_uuid = ${u})) * $${params.length}::double precision + $${params.length - 1}::double precision AS ${quoteId(role)}`;
  });
  let rows = 0;
  if (roles.length) {
    const names = roles.map(([r]) => quoteId(r));
    const res = await client.query(
      `INSERT INTO pg_temp.history (equipment_id, timestamp_utc, ${names.join(", ")})
       SELECT * FROM (
         SELECT $5::text AS equipment_id,
                time_bucket(make_interval(secs => $1::double precision), ts, timestamptz '1970-01-01 00:00:00+00') AS timestamp_utc,
                ${exprs.join(",\n                ")}
         FROM openfdd.nf_samples
         WHERE point_uuid = ANY($4::text[]) AND ts >= $2::timestamptz AND ts < $3::timestamptz
         GROUP BY 2
       ) t
       WHERE ${names.map((n) => `t.${n} IS NOT NULL`).join(" OR ")}
       ORDER BY timestamp_utc`,
      params,
    );
    rows = res.rowCount;
  }
  await client.query("CREATE INDEX history_eq_ts ON pg_temp.history (equipment_id, timestamp_utc)");

  // weather = the outdoor-air roles of the same grid (same as fdd.js buildInput)
  const wcols = pack.contract.weather.map((c) => c.name).filter((n) => n !== "timestamp_utc" && histCols.has(n));
  if (wcols.length) {
    await client.query(
      `INSERT INTO pg_temp.weather (timestamp_utc, ${wcols.map(quoteId).join(", ")})
       SELECT timestamp_utc, ${wcols.map(quoteId).join(", ")} FROM pg_temp.history
       WHERE ${wcols.map((n) => `${quoteId(n)} IS NOT NULL`).join(" OR ")}`);
  }
  const si = {};
  for (const [role, uuid] of roles) si[role] = siFactors(unitsByUuid[uuid]).unit;
  for (const [role, unit] of Object.entries(si)) {
    await client.query("INSERT INTO pg_temp.authorized_series (site_id, equipment_id, role, unit) VALUES ($1, $2, $3, $4)", [siteId, equipId, role, unit]);
  }
  await client.query("INSERT INTO pg_temp.equipment (building_id, equipment_id) VALUES ($1, $2)", [siteId, equipId]);
  return { rows, roles: roles.map(([r]) => r), si };
}

// ---------------------------------------------------------------- rules

const helpersDone = new WeakSet();

const coerce = (res) => {
  const numeric = new Set(res.fields.filter((f) => NUMERIC_OIDS.has(f.dataTypeID)).map((f) => f.name));
  return res.rows.map((r) => {
    const o = {};
    for (const [k, v] of Object.entries(r)) o[k] = numeric.has(k) && v !== null && v !== undefined ? Number(v) : v;
    return o;
  });
};

/**
 * Runs pack rules on the session's TEMP tables. The pack's helper SQL (schema fdd) is installed once per
 * connection. Returns { results: {ruleId: rows}, errors: {ruleId: message} }; a failing rule never stops the others.
 */
async function runRules(client, pack, ruleIds) {
  if (!helpersDone.has(client)) {
    await client.query(pack.helpers_sql);
    helpersDone.add(client);
  }
  const results = {};
  const errors = {};
  for (const id of ruleIds || Object.keys(pack.rules)) {
    const rule = pack.rules[id];
    if (!rule) { errors[id] = "unknown rule"; continue; }
    try {
      results[id] = coerce(await client.query(rule.sql));
    } catch (e) {
      errors[id] = e.message;
    }
  }
  return { results, errors };
}

// ---------------------------------------------------------------- results

/**
 * One fdd_results row from a rule's output row: fault_pct / fault_hours / covered_hours when present,
 * every other numeric output column goes to metric.
 */
function toResultRow({ runTs, equip, site = "", ruleId, row, engine = "timescale", windowStart, windowEnd }) {
  const known = new Set(["equipment_id", "fault_pct", "fault_hours", "covered_hours"]);
  const metric = {};
  for (const [k, v] of Object.entries(row)) if (!known.has(k) && typeof v === "number" && Number.isFinite(v)) metric[k] = v;
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  return {
    run_ts: iso(runTs), equip, site, rule_id: ruleId,
    fault_pct: num(row.fault_pct), fault_hours: num(row.fault_hours), covered_hours: num(row.covered_hours),
    metric: Object.keys(metric).length ? metric : null, engine,
    window_start: windowStart == null ? null : iso(windowStart), window_end: windowEnd == null ? null : iso(windowEnd),
  };
}

/** Upsert rows (shape of toResultRow) into openfdd.fdd_results. Returns the row count. */
async function writeResults(client, rows) {
  let n = 0;
  for (let i = 0; i < rows.length; i += 500) {
    const part = rows.slice(i, i + 500).map((r) => ({ ...r, run_ts: iso(r.run_ts) }));
    const res = await client.query(
      `INSERT INTO openfdd.fdd_results
         SELECT * FROM jsonb_populate_recordset(null::openfdd.fdd_results, $1::jsonb)
       ON CONFLICT (run_ts, equip, rule_id) DO UPDATE SET
         site = EXCLUDED.site, fault_pct = EXCLUDED.fault_pct, fault_hours = EXCLUDED.fault_hours,
         covered_hours = EXCLUDED.covered_hours, metric = EXCLUDED.metric, engine = EXCLUDED.engine,
         window_start = EXCLUDED.window_start, window_end = EXCLUDED.window_end`,
      [JSON.stringify(part)],
    );
    n += res.rowCount;
  }
  return n;
}

// ---------------------------------------------------------------- size cap

const DAY_MS = 24 * 3600e3;

/** Once a day (unless the TimescaleDB job exists): openfdd.enforce_size_cap(config max_bytes). */
async function maybeEnforceCap(client, { now = Date.now() } = {}) {
  const cfg = Object.fromEntries((await client.query("SELECT key, value FROM openfdd.config")).rows.map((r) => [r.key, r.value]));
  const job = await client.query("SELECT 1 FROM timescaledb_information.jobs WHERE proc_schema = 'openfdd' AND proc_name = 'size_cap_job'");
  if (job.rowCount) return { skipped: "job" };
  const last = cfg.last_cap_run ? Date.parse(cfg.last_cap_run) : 0;
  if (now - last < DAY_MS) return { skipped: "ran < 24 h ago" };
  const { rows } = await client.query("SELECT openfdd.enforce_size_cap(openfdd.max_bytes()) AS r");
  await client.query(
    "INSERT INTO openfdd.config (key, value) VALUES ('last_cap_run', to_jsonb($1::text)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
    [new Date(now).toISOString()]);
  return rows[0].r;
}

// ---------------------------------------------------------------- long-range history (on-request hook)

const BUCKET_RE = /^\s*(\d+)\s*(second|minute|hour|day|week|month)s?\s*$/i;
const MAX_UUIDS = 200;
const MAX_BYTES = 200000;
const TARGET_BUCKETS = 1000;
/** @type {[string, number][]} */
const NICE = [["1 minute", 60], ["5 minutes", 300], ["15 minutes", 900], ["1 hour", 3600], ["6 hours", 21600], ["1 day", 86400], ["1 week", 604800]];

/** history_buckets rows, JSON capped at ~200 KB. bucket optional: picked so each series has ~1000 buckets. */
async function historyRoute(client, { uuids, from, to, bucket, maxBytes = MAX_BYTES }) {
  if (!Array.isArray(uuids) || !uuids.length) throw new Error("args.uuids (array) is required");
  if (uuids.length > MAX_UUIDS) throw new Error(`at most ${MAX_UUIDS} uuids`);
  const f = new Date(from), t = new Date(to);
  if (Number.isNaN(+f) || Number.isNaN(+t) || t <= f) throw new Error("args.from / args.to must be ISO times with from < to");
  let width = bucket;
  if (width) {
    const m = BUCKET_RE.exec(String(width));
    if (!m) throw new Error('args.bucket like "15 minutes", "1 hour", "1 day"');
    width = `${m[1]} ${m[2].toLowerCase()}s`;
  } else {
    const secs = (t.getTime() - f.getTime()) / 1000 / TARGET_BUCKETS;
    width = (NICE.find(([, s]) => s >= secs) || NICE[NICE.length - 1])[0];
  }
  const res = await client.query(
    "SELECT point_uuid, bucket, avg, min, max, n FROM openfdd.history_buckets($1::text[], $2::timestamptz, $3::timestamptz, $4::interval)",
    [uuids.map(String), f.toISOString(), t.toISOString(), width]);
  const rows = [];
  let size = 200;
  let truncated = false;
  for (const r of res.rows) {
    const o = { point_uuid: r.point_uuid, bucket: r.bucket.toISOString(), avg: r.avg, min: r.min, max: r.max, n: Number(r.n) };
    size += JSON.stringify(o).length + 1;
    if (size > maxBytes) { truncated = true; break; }
    rows.push(o);
  }
  return { bucket: width, from: f.toISOString(), to: t.toISOString(), total: res.rowCount, truncated, rows };
}

module.exports = { connect, install, loadHistory, runRules, toResultRow, writeResults, maybeEnforceCap, historyRoute, siFactors };
