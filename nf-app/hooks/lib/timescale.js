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
const settings = require("./settings");

const NUMERIC_OIDS = new Set([20, 21, 23, 700, 701, 1700]);
const IDENT = /^[a-z_][a-z0-9_]*$/;
const quoteId = (s) => '"' + String(s).replace(/"/g, '""') + '"';
const iso = (t) => (t instanceof Date ? t : new Date(t)).toISOString();

// ---------------------------------------------------------------- connect / install

/** Connected pg Client. config: { connectionString } or { host, port, database, user, passwordEnv|password, ssl }. */
async function connect(config = {}) {
  let Client;
  try {
    ({ Client } = require("pg"));
  } catch (e) {
    if (e && e.code === "MODULE_NOT_FOUND") {
      throw new Error('pg not installed: install the app dependencies (nf_app_sync.py install, or PATCH /api/v1/apps/<app-id>/dependencies then restart); engine "timescale" needs the pg package');
    }
    throw e;
  }
  config = requireConfig(config);   // a JSON string option (how NF stores it) or an object; one message when absent
  const opts = {};
  if (config.connectionString) opts.connectionString = config.connectionString;
  else {
    Object.assign(opts, { host: config.host, port: config.port || 5432, database: config.database || "postgres", user: config.user });
  }
  const pw = config.passwordEnv ? process.env[config.passwordEnv] : config.password;
  if (pw) opts.password = pw;
  if (config.ssl) opts.ssl = config.ssl;
  opts.application_name = "open-fdd";
  const client = new Client(opts);
  try {
    await client.connect();
  } catch (e) {
    // never let the password (or a URL with credentials) reach a log or a run record
    const err = new Error(settings.redact(e && e.message, { ...config, password: pw }));
    /** @type {any} */ (err).code = e && e.code;
    throw err;
  }
  return client;
}

/** schema_version of install.sql this release needs (scoped retention = 2). */
const SCHEMA_VERSION = 2;

/** Installed openfdd schema_version, 0 when the schema / config table / key is absent (pre-scoped release = 0). */
async function schemaVersion(client) {
  const have = await client.query("SELECT to_regclass('openfdd.config') AS r");
  if (!have.rows[0].r) return 0;
  const { rows } = await client.query("SELECT value FROM openfdd.config WHERE key = 'schema_version'");
  return rows.length ? Number(rows[0].value) || 0 : 0;
}

/**
 * Runs adapter_nf.sql then install.sql (run it as the INSTALLER role; an older install is upgraded in place:
 * scoped retention functions + the existing daily job altered). Returns { jobRegistered, maxBytes, schemaVersion }.
 */
async function install(client) {
  for (const f of ["adapter_nf.sql", "install.sql"]) {
    await client.query(fs.readFileSync(path.join(SQL_DIR, f), "utf8"));
  }
  const { rows } = await client.query("SELECT key, value FROM openfdd.config WHERE key IN ('job_registered', 'max_bytes', 'schema_version')");
  const cfg = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  return { jobRegistered: cfg.job_registered === true || cfg.job_registered === "true", maxBytes: Number(cfg.max_bytes), schemaVersion: Number(cfg.schema_version) };
}

/**
 * The connection settings as an object, or a clear error naming where they are expected (never a silent fallback).
 * Accepts the object form and the string form NF stores (app option "timescale": JSON text or a postgres:// URL).
 */
function requireConfig(config) {
  return settings.requireTimescale(config);
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
 *   fractionRoles [role]  roles to divide by 100 (declared-% fraction/boolean roles): siPlan().scaled from hooks/fdd.js
 *   booleanRoles  [role]  roles whose bucket average must lie in [0, 1], else NULL (rejected): siPlan().bool
 * The scale decisions (fraction / boolean / unitless-skipped) are made ONLY by siPlan; this function applies them and
 * does not look at role names or units to guess one. Roles siPlan skipped are not passed in. Without the two arrays
 * the roles are plain SI conversions by unit.
 * Returns { rows, roles, si: {role: unit}, bytes: 0 }. rows = history rows written (0 = no data in the window).
 */
async function loadHistory(client, { pack, equipId, siteId = "", roleToUuid, unitsByUuid = {}, fractionRoles = [], booleanRoles = [], from, to, stepSec }) {
  if (!pack || !pack.contract) throw new Error("loadHistory: pack is required");
  const step = Number(stepSec || pack.poll_seconds);
  if (!(step > 0)) throw new Error("loadHistory: stepSec must be > 0");
  const histCols = new Map(pack.contract.history.map((c) => [c.name, c]));
  const roles = Object.entries(roleToUuid || {}).filter(([r]) => histCols.has(r) && r !== "equipment_id" && r !== "timestamp_utc");
  await createTempTables(client, pack);
  const frac = new Set(fractionRoles);
  const bools = new Set(booleanRoles);
  const factorsFor = (role, uuid) => {
    const unit = unitsByUuid[uuid];
    if (bools.has(role)) return { a: 0, b: frac.has(role) ? 0.01 : 1, unit: "bool", bool: true };
    if (frac.has(role)) return { a: 0, b: 0.01, unit: "fraction" };
    return siFactors(unit);
  };

  const params = [step, iso(from), iso(to), [...new Set(roles.map(([, u]) => u))], equipId];
  const exprs = roles.map(([role, uuid]) => {
    params.push(uuid);
    const u = `$${params.length}`;
    if (histCols.get(role).type === "text") {
      return `max(value) FILTER (WHERE point_uuid = ${u})::text AS ${quoteId(role)}`;
    }
    const f = factorsFor(role, uuid);
    params.push(f.a, f.b);
    const v = `(avg(value) FILTER (WHERE point_uuid = ${u})) * $${params.length}::double precision + $${params.length - 1}::double precision`;
    // boolean roles: an on-fraction in [0, 1] (clamped for float noise); anything else is rejected (NULL), see siPlan
    return f.bool ? `(CASE WHEN ${v} BETWEEN -1e-9 AND 1 + 1e-9 THEN least(1, greatest(0, ${v})) END) AS ${quoteId(role)}` : `${v} AS ${quoteId(role)}`;
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
  for (const [role, uuid] of roles) si[role] = factorsFor(role, uuid).unit;
  for (const [role, unit] of Object.entries(si)) {
    await client.query("INSERT INTO pg_temp.authorized_series (site_id, equipment_id, role, unit) VALUES ($1, $2, $3, $4)", [siteId, equipId, role, unit]);
  }
  await client.query("INSERT INTO pg_temp.equipment (building_id, equipment_id) VALUES ($1, $2)", [siteId, equipId]);
  return { rows, roles: roles.map(([r]) => r), si };
}

/**
 * Newest sample (epoch ms, null = none at all) of the given point uuids in openfdd.nf_samples, whatever the window.
 * Read-only. Tells "the source stopped receiving rows" from "the window was empty".
 */
async function newestSample(client, uuids) {
  const ids = [...new Set((uuids || []).filter((u) => typeof u === "string" && u))];
  if (!ids.length) return null;
  const { rows } = await client.query("SELECT max(ts) AS t FROM openfdd.nf_samples WHERE point_uuid = ANY($1::text[])", [ids]);
  const t = rows[0] && rows[0].t;
  return t ? new Date(t).getTime() : null;
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

// ---------------------------------------------------------------- size cap (scoped retention)

const DAY_MS = 24 * 3600e3;

/**
 * Once a day (unless the TimescaleDB job exists): openfdd.enforce_size_cap(config max_bytes). Scope = schema openfdd
 * + config retention_allowlist ONLY (never NF's own tables unless listed). Returns the function's JSON result
 * (always has status). Throws when the installed schema is the old global-retention release: re-run install.sql
 * as the installer role (the old job is then altered in place).
 */
async function maybeEnforceCap(client, { now = Date.now() } = {}) {
  if ((await schemaVersion(client)) < SCHEMA_VERSION) {
    throw new Error("openfdd schema is older than this release (global retention): run timescale/install.sql as the installer role to upgrade; retention skipped");
  }
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

/** Dry run: what enforce_size_cap(maxBytes) would drop (default = config max_bytes). Drops nothing. */
async function retentionPreview(client, maxBytes) {
  const { rows } = maxBytes == null
    ? await client.query("SELECT openfdd.retention_preview() AS r")
    : await client.query("SELECT openfdd.retention_preview($1::bigint) AS r", [String(maxBytes)]);
  return rows[0].r;
}

// ---------------------------------------------------------------- long-range history (on-request hook)

const BUCKET_RE = /^\s*(\d{1,6})\s*(second|minute|hour|day|week|month)s?\s*$/i;
const UNIT_SECS = { second: 1, minute: 60, hour: 3600, day: 86400, week: 604800, month: 2592000 };
const MAX_UUIDS = 200;
const MAX_BYTES = 200000;
const TARGET_BUCKETS = 1000;
/** Server-side defaults; override with hook config `history` (never from the request args). */
const HISTORY_LIMITS = { maxPoints: 200000, maxSpanDays: 3660, minBucketSec: 60, statementTimeoutMs: 20000, maxBytes: MAX_BYTES, maxUuids: MAX_UUIDS };
/** @type {[string, number][]} */
const NICE = [["1 minute", 60], ["5 minutes", 300], ["15 minutes", 900], ["1 hour", 3600], ["6 hours", 21600], ["1 day", 86400], ["1 week", 604800]];
/** @type {[string, number][]} */
const COARSE = [...NICE, ["1 month", 2592000]];

/** A positive, finite time (ISO string, epoch ms number or Date). */
function parseTime(v, name) {
  let ms = NaN;
  if (v instanceof Date) ms = v.getTime();
  else if (typeof v === "number") ms = v;
  else if (typeof v === "string" && v.trim()) ms = Date.parse(v);
  if (!Number.isFinite(ms) || ms <= 0 || ms > 253402300799999) throw new Error(`args.${name} must be a positive, finite time (ISO string or epoch ms)`);
  return new Date(ms);
}

const posNum = (v, d) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : d);

/**
 * history_buckets rows with hard bounds. args (request): { uuids, from, to, bucket?, coarsen? (default true) }.
 * limits (server config, NOT the request): { maxPoints 200000, maxSpanDays 3660, minBucketSec 60,
 * statementTimeoutMs 20000, maxBytes 200000, maxUuids 200 }. Before querying: times positive/finite with from < to,
 * span <= maxSpanDays, bucket >= minBucketSec, and (buckets per series) x (uuids) <= maxPoints; otherwise the bucket is
 * coarsened (coarsened = true, requested_bucket kept) or the request is rejected (coarsen: false / nothing fits).
 * The query runs in a transaction with SET LOCAL statement_timeout and LIMIT maxPoints + 1. Result:
 * { bucket, requested_bucket, coarsened, from, to, total, truncated, max_points, coverage, rows }.
 */
async function historyRoute(client, args = {}, limits = {}) {
  const L = {};
  for (const k of Object.keys(HISTORY_LIMITS)) L[k] = posNum(limits[k], HISTORY_LIMITS[k]);
  const { uuids, from, to, bucket } = args;
  if (!Array.isArray(uuids) || !uuids.length) throw new Error("args.uuids (array) is required");
  const ids = [...new Set(uuids.map((u) => (typeof u === "string" ? u.trim() : "")))];
  if (ids.some((u) => !u || u.length > 128)) throw new Error("args.uuids must be non-empty strings (point uuids)");
  if (ids.length > L.maxUuids) throw new Error(`at most ${L.maxUuids} uuids`);
  const f = parseTime(from, "from"), t = parseTime(to, "to");
  if (t <= f) throw new Error("args.from must be before args.to");
  const spanSec = (t.getTime() - f.getTime()) / 1000;
  if (spanSec > L.maxSpanDays * 86400) throw new Error(`time span is longer than ${L.maxSpanDays} days; query a shorter range`);

  let requested = null;
  let secs;
  let width;
  if (bucket !== undefined && bucket !== null && bucket !== "") {
    const m = BUCKET_RE.exec(String(bucket));
    if (!m || Number(m[1]) < 1) throw new Error('args.bucket like "15 minutes", "1 hour", "1 day" (a positive count)');
    width = `${Number(m[1])} ${m[2].toLowerCase()}s`;
    secs = Number(m[1]) * UNIT_SECS[m[2].toLowerCase()];
    if (secs < L.minBucketSec) throw new Error(`args.bucket must be at least ${L.minBucketSec} seconds (got ${width})`);
    requested = String(bucket).trim();
  } else {
    const want = Math.max(spanSec / TARGET_BUCKETS, L.minBucketSec);
    [width, secs] = NICE.find(([, s]) => s >= want) || NICE[NICE.length - 1];
  }
  // upper bound of output rows: buckets per series (+2 for epoch alignment at both ends) x series
  const points = (s) => (Math.floor(spanSec / s) + 2) * ids.length;
  let coarsened = false;
  if (points(secs) > L.maxPoints) {
    if (args.coarsen === false) throw new Error(`request would return about ${points(secs)} points (max ${L.maxPoints}); use a larger bucket, fewer uuids or a shorter range`);
    const next = COARSE.find(([, s]) => s >= secs && points(s) <= L.maxPoints);
    if (!next) throw new Error(`request would return about ${points(secs)} points (max ${L.maxPoints}) even with the coarsest bucket; use fewer uuids or a shorter range`);
    [width, secs] = next;
    coarsened = true;
  }

  let res;
  try {
    await client.query("BEGIN");
    await client.query("SELECT set_config('statement_timeout', $1::text, true)", [`${Math.floor(L.statementTimeoutMs)}ms`]);
    res = await client.query(
      "SELECT point_uuid, bucket, avg, min, max, n FROM openfdd.history_buckets($1::text[], $2::timestamptz, $3::timestamptz, $4::interval) LIMIT $5::int",
      [ids, f.toISOString(), t.toISOString(), width, L.maxPoints + 1]);
    await client.query("COMMIT");
  } catch (e) {
    try { await client.query("ROLLBACK"); } catch (_) { /* connection may be gone */ }
    if (e && e.code === "57014") {
      const err = /** @type {any} */ (new Error(`history query exceeded ${L.statementTimeoutMs} ms and was cancelled; use fewer uuids, a shorter range or a larger bucket`));
      err.code = "history_timeout";
      throw err;
    }
    throw e;
  }

  let truncated = res.rows.length > L.maxPoints;
  const rows = [];
  const per = new Map();
  let size = 400;
  for (const r of res.rows.slice(0, L.maxPoints)) {
    const o = { point_uuid: r.point_uuid, bucket: r.bucket.toISOString(), avg: r.avg, min: r.min, max: r.max, n: Number(r.n) };
    size += JSON.stringify(o).length + 1;
    if (size > L.maxBytes) { truncated = true; break; }
    rows.push(o);
    const c = per.get(o.point_uuid) || { buckets: 0, samples: 0, first: o.bucket, last: o.bucket };
    c.buckets++; c.samples += o.n; c.last = o.bucket;
    per.set(o.point_uuid, c);
  }
  const coverage = {
    requested: ids.length, with_data: per.size, without_data: ids.filter((u) => !per.has(u)),
    complete: !truncated, points: Object.fromEntries(per),
  };
  return {
    bucket: width, requested_bucket: requested, coarsened, from: f.toISOString(), to: t.toISOString(),
    total: res.rows.length, truncated, max_points: L.maxPoints, coverage, rows,
  };
}

module.exports = {
  connect, install, schemaVersion, requireConfig, SCHEMA_VERSION, loadHistory, runRules, toResultRow, writeResults,
  maybeEnforceCap, retentionPreview, historyRoute, siFactors, newestSample,
};
