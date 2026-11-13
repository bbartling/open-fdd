"use strict";
/**
 * Open-FDD on NF's TimescaleDB northbound database (FULL edition). CommonJS, npm package `pg`.
 *
 *   const ts = require("./lib/timescale");
 *   const client = await ts.connect(config.timescale);   // { connectionString | host,port,database,user, passwordEnv }
 *   await ts.install(client);                            // core.sql + adapter_nf.sql + install.sql (idempotent)
 *   await ts.syncPoints(client, { siteId, equipId, rows: ts.pointRows({ pack, siteId, equipId, roleToUuid, unitsByUuid }) });
 *   const h = await ts.loadHistory(client, { pack, siteId, equipId, roleToUuid, unitsByUuid, from, to, stepSec: pack.poll_seconds });
 *   const { results, errors } = await ts.runRules(client, pack, ruleIds);
 *   await ts.writeResults(client, rows);
 *   await ts.maybeEnforceCap(client);
 *   await client.end();
 *
 * NF's own tables are only touched through the views openfdd.nf_samples and fdd.input_sample (timescale/adapter_nf.sql);
 * the Open-FDD tables are fdd.point (a mirror of the bound points, synced here), fdd.rule_result and fdd.rule_config
 * (timescale/core.sql, the shared core schema). The rules run in the SAME session: loadHistory creates TEMP tables history / weather / ... with the
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

/** schema_version of install.sql this release needs (4 = shared core schema: fdd.point / fdd.rule_result / fdd.rule_config). */
const SCHEMA_VERSION = 4;

/** Installed openfdd schema_version, 0 when the schema / config table / key is absent (pre-scoped release = 0). */
async function schemaVersion(client) {
  const have = await client.query("SELECT to_regclass('openfdd.config') AS r");
  if (!have.rows[0].r) return 0;
  const { rows } = await client.query("SELECT value FROM openfdd.config WHERE key = 'schema_version'");
  return rows.length ? Number(rows[0].value) || 0 : 0;
}

/** Install order: the core tables first (the adapter's view joins fdd.point), then the NF adapter, then policy + migration. */
const SQL_FILES = ["core.sql", "adapter_nf.sql", "install.sql"];

/**
 * Runs core.sql, adapter_nf.sql then install.sql (run it as the INSTALLER role; an older install is upgraded in place:
 * scoped retention functions + the existing daily job altered; v3 results are copied into fdd.rule_result and the old
 * tables dropped). Returns { jobRegistered, maxBytes, schemaVersion }.
 */
async function install(client) {
  for (const f of SQL_FILES) {
    await client.query(fs.readFileSync(path.join(SQL_DIR, f), "utf8"));
  }
  const { rows } = await client.query("SELECT key, value FROM openfdd.config WHERE key IN ('job_registered', 'max_bytes', 'schema_version')");
  const cfg = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  return { jobRegistered: cfg.job_registered === true || cfg.job_registered === "true", maxBytes: Number(cfg.max_bytes), schemaVersion: Number(cfg.schema_version) };
}

/** True when the core tables and the input view exist (read-only; the schema probe reports it as core_ok). */
async function coreOk(client) {
  const { rows } = await client.query(
    "SELECT to_regclass('fdd.point') IS NOT NULL AND to_regclass('fdd.rule_result') IS NOT NULL AND to_regclass('fdd.rule_config') IS NOT NULL AND to_regclass('fdd.input_sample') IS NOT NULL AS ok");
  return rows[0].ok === true;
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

/** Scale decision for one bound role: {a, b, unit, bool?}, v_si = a + b * v. siPlan (hooks/fdd.js) made the decisions. */
function roleFactors(role, uuid, { unitsByUuid = {}, fractionRoles = [], booleanRoles = [] }) {
  const unit = unitsByUuid[uuid];
  if (booleanRoles.includes(role)) return { a: 0, b: fractionRoles.includes(role) ? 0.01 : 1, unit: "bool", bool: true };
  if (fractionRoles.includes(role)) return { a: 0, b: 0.01, unit: "fraction" };
  return siFactors(unit);
}

/**
 * The fdd.point rows (one per bound point, shape of core.sql) for one equipment, from the same arguments as loadHistory.
 *   roleToUuid  {role: pointUuid}   unitsByUuid {pointUuid: nfUnit}   fractionRoles / booleanRoles = siPlan's decisions
 *   sensorSeries [{uuid, role, unit}] sweep sensors (unit = canonical SI unit); pointMeta {uuid: {name, dis, kind, haystackId}}
 * A point bound to a role AND swept appears once, with the role's scale. Text roles (occ_mode) keep their values (scale 1).
 * @returns {Array<Record<string, any>>}
 */
function pointRows({ pack, siteId = "", equipId, roleToUuid = {}, unitsByUuid = {}, fractionRoles = [], booleanRoles = [], sensorSeries = [], pointMeta = {} }) {
  const histCols = new Map(pack.contract.history.map((c) => [c.name, c]));
  const plan = { unitsByUuid, fractionRoles, booleanRoles };
  const rows = new Map();
  const add = (uuid, role, f, unit, kind) => {
    if (rows.has(uuid)) return;
    const meta = pointMeta[uuid] || {};
    const native = unitsByUuid[uuid];
    rows.set(uuid, {
      site_id: siteId, point_key: uuid, equipment_id: equipId, role, role_source: "nf-model", kind,
      unit: unit || null, source_unit: native || null, si_scale: f.b, si_offset: f.a, haystack_id: meta.haystackId || null,
      attrs: Object.fromEntries(Object.entries({ name: meta.name, dis: meta.dis, nf_kind: meta.kind }).filter(([, v]) => v != null && v !== "")),
    });
  };
  for (const [role, uuid] of Object.entries(roleToUuid)) {
    const col = histCols.get(role);
    if (!col || role === "equipment_id" || role === "timestamp_utc") continue;
    if (col.type === "text") { add(uuid, role, { a: 0, b: 1 }, unitsByUuid[uuid], "text"); continue; }
    const f = roleFactors(role, uuid, plan);
    add(uuid, role, f, f.unit, f.bool ? "bool" : "numeric");
  }
  for (const { uuid, role, unit } of sensorSeries) {
    const f = siFactors(unitsByUuid[uuid]);
    add(uuid, role, f, unit || f.unit, "numeric");
  }
  return [...rows.values()];
}

/**
 * Mirrors the bound points of ONE equipment into fdd.point (upsert), and removes this equipment's rows that are no
 * longer bound. fdd.point is keyed (site_id, point_key): a point shared by several equipments carries the binding of
 * the equipment synced last, which is the one about to be loaded. Returns { upserted, removed }.
 */
async function syncPoints(client, { siteId = "", equipId, rows }) {
  const ids = rows.map((r) => r.point_key);
  await client.query("BEGIN");
  try {
    const up = await client.query(
      `INSERT INTO fdd.point (site_id, point_key, equipment_id, role, role_source, kind, unit, source_unit, si_scale, si_offset, haystack_id, attrs, updated_at)
       SELECT site_id, point_key, equipment_id, role, role_source, coalesce(kind, 'numeric'), unit, source_unit,
              coalesce(si_scale, 1), coalesce(si_offset, 0), haystack_id, coalesce(attrs, '{}'::jsonb), now()
       FROM jsonb_populate_recordset(null::fdd.point, $1::jsonb)
       ON CONFLICT (site_id, point_key) DO UPDATE SET
         equipment_id = EXCLUDED.equipment_id, role = EXCLUDED.role, role_source = EXCLUDED.role_source, kind = EXCLUDED.kind,
         unit = EXCLUDED.unit, source_unit = EXCLUDED.source_unit, si_scale = EXCLUDED.si_scale, si_offset = EXCLUDED.si_offset,
         haystack_id = EXCLUDED.haystack_id, attrs = EXCLUDED.attrs, updated_at = now()`,
      [JSON.stringify(rows)]);
    const del = await client.query(
      "DELETE FROM fdd.point WHERE site_id = $1::text AND equipment_id = $2::text AND point_key <> ALL($3::text[])",
      [siteId, equipId, ids]);
    await client.query("COMMIT");
    return { upserted: up.rowCount, removed: del.rowCount };
  } catch (e) {
    try { await client.query("ROLLBACK"); } catch (_) { /* connection may be gone */ }
    throw e;
  }
}

/**
 * Builds the pack's wide `history` (+ weather, sensor_history) as TEMP tables in this session (the tables of pack.contract)
 * from fdd.input_sample (SI values: the view applies fdd.point.si_scale / si_offset, see timescale/adapter_nf.sql).
 * The points must be synced first (syncPoints; the engine's load() does both).
 *   roleToUuid  {role: pointUuid}   roles must be history columns of pack.contract
 *   unitsByUuid {pointUuid: nfUnit} only reported back (the conversion lives in fdd.point)
 *   fractionRoles [role]  roles divided by 100 (siPlan().scaled)        -> the reported unit is "fraction"
 *   booleanRoles  [role]  roles whose bucket average must lie in [0, 1], else NULL (rejected): siPlan().bool
 * The scale decisions (fraction / boolean / unitless-skipped) are made ONLY by siPlan; this function applies the boolean
 * clamp and does not look at role names or units to guess one. Roles siPlan skipped are not passed in.
 * sensorSeries is the validated sweep binding list with a canonical SI unit per UUID.
 * Returns counts of wide history rows and long sensor rows, plus wide roles and SI units.
 */
async function loadHistory(client, { pack, equipId, siteId = "", roleToUuid, unitsByUuid = {}, fractionRoles = [], booleanRoles = [],
  sensorSeries = [], from, to, stepSec }) {
  if (!pack || !pack.contract) throw new Error("loadHistory: pack is required");
  const step = Number(stepSec || pack.poll_seconds);
  if (!(step > 0)) throw new Error("loadHistory: stepSec must be > 0");
  const histCols = new Map(pack.contract.history.map((c) => [c.name, c]));
  const roles = Object.entries(roleToUuid || {}).filter(([r]) => histCols.has(r) && r !== "equipment_id" && r !== "timestamp_utc");
  await createTempTables(client, pack);
  const bools = new Set(booleanRoles);

  const params = [step, iso(from), iso(to), [...new Set(roles.map(([, u]) => u))], equipId, String(siteId ?? "")];
  const exprs = roles.map(([role, uuid]) => {
    params.push(uuid);
    const u = `$${params.length}`;
    if (histCols.get(role).type === "text") {
      return `max(value) FILTER (WHERE point_key = ${u})::text AS ${quoteId(role)}`;
    }
    const v = `avg(value) FILTER (WHERE point_key = ${u})`;
    // boolean roles: an on-fraction in [0, 1] (clamped for float noise); anything else is rejected (NULL), see siPlan
    return bools.has(role) ? `(CASE WHEN ${v} BETWEEN -1e-9 AND 1 + 1e-9 THEN least(1, greatest(0, ${v})) END) AS ${quoteId(role)}` : `${v} AS ${quoteId(role)}`;
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
         FROM fdd.input_sample
         WHERE site_id = $6::text AND point_key = ANY($4::text[]) AND ts >= $2::timestamptz AND ts < $3::timestamptz
         GROUP BY 2
       ) t
       WHERE ${names.map((n) => `t.${n} IS NOT NULL`).join(" OR ")}
       ORDER BY timestamp_utc`,
      params,
    );
    rows = res.rowCount;
  }
  await client.query("CREATE INDEX history_eq_ts ON pg_temp.history (equipment_id, timestamp_utc)");

  let sensorRows = 0;
  if (sensorSeries.length && pack.contract.sensor_history) {
    const bindings = sensorSeries.map(({ uuid, role, unit }) => ({ uuid, role, unit }));
    const res = await client.query(
      `INSERT INTO pg_temp.sensor_history (equipment_id, series_id, sensor_role, unit, timestamp_utc, value)
       WITH samples AS (
         SELECT point_key,
                time_bucket(make_interval(secs => $1::double precision), ts, timestamptz '1970-01-01 00:00:00+00') AS bucket,
                avg(value) AS value
         FROM fdd.input_sample
         WHERE site_id = $7::text AND point_key = ANY($4::text[]) AND ts >= $2::timestamptz AND ts < $3::timestamptz
         GROUP BY 1, 2
       )
       SELECT $5::text, b.uuid, b.role, b.unit, s.bucket, s.value
       FROM samples s
       JOIN jsonb_to_recordset($6::jsonb) AS b(uuid text, role text, unit text) ON b.uuid = s.point_key
       WHERE s.value IS NOT NULL`,
      [step, iso(from), iso(to), [...new Set(bindings.map(({ uuid }) => uuid))], equipId, JSON.stringify(bindings), String(siteId ?? "")],
    );
    sensorRows = res.rowCount;
  }

  // weather = the outdoor-air roles of the same grid (same as fdd.js buildInput)
  const wcols = pack.contract.weather.map((c) => c.name).filter((n) => n !== "timestamp_utc" && histCols.has(n));
  if (wcols.length) {
    await client.query(
      `INSERT INTO pg_temp.weather (timestamp_utc, ${wcols.map(quoteId).join(", ")})
       SELECT timestamp_utc, ${wcols.map(quoteId).join(", ")} FROM pg_temp.history
       WHERE ${wcols.map((n) => `${quoteId(n)} IS NOT NULL`).join(" OR ")}`);
  }
  const si = {};
  for (const [role, uuid] of roles) si[role] = roleFactors(role, uuid, { unitsByUuid, fractionRoles, booleanRoles }).unit;
  return { rows, sensorRows, roles: roles.map(([r]) => r), si };
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

const RESULT_KEY = ["site_id", "equipment_id", "rule_id", "subject_key", "window_start", "window_end", "rule_hash", "config_hash"];

/**
 * One fdd.rule_result row (core.sql) from a rule's output row: fault_pct / fault_hours / covered_hours when present;
 * other numeric outputs and the sweep's per-role hours go to metrics, text outputs to diagnostics.outputs. status: fault_hours > 0 FAULT, = 0 PASS, not
 * assessable (NULL) INCONCLUSIVE. subject_key = the swept sensor's point uuid ('' = equipment level). Both window ends
 * are required (window_end > window_start); rule_hash / config_hash '' when the caller has none.
 */
function toResultRow({ runTs, equip, site = "", ruleId, row, engine = "timescale", windowStart, windowEnd, pollSeconds = 300,
  ruleHash = "", configHash = "", configRevision = null, parameters = {} }) {
  if (windowStart == null || windowEnd == null) throw new Error("toResultRow: windowStart and windowEnd are required");
  const known = new Set(["equipment_id", "series_id", "sensor_role", "fault_pct", "fault_hours", "covered_hours"]);
  const metrics = {};
  const outputs = {};   // text outputs of the rule (e.g. a status column) survive the round trip in diagnostics.outputs
  for (const [k, v] of Object.entries(row)) {
    if (known.has(k)) continue;
    if (typeof v === "number" && Number.isFinite(v)) metrics[k] = v;
    else if (typeof v === "string") outputs[k] = v;
  }
  if (row.sensor_fault_hours) metrics.sensor_fault_hours = row.sensor_fault_hours;
  const num = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
  const sensorNotAssessed = typeof row.series_id === "string" && !(num(row.covered_hours) > 0);
  const faultHours = sensorNotAssessed ? null : num(row.fault_hours);
  return {
    site_id: site || "", equipment_id: equip, rule_id: ruleId, subject_key: row.series_id || "",
    window_start: iso(windowStart), window_end: iso(windowEnd), rule_hash: ruleHash, config_hash: configHash, config_revision: configRevision,
    effective_parameters: parameters, poll_seconds: pollSeconds,
    status: faultHours == null ? "INCONCLUSIVE" : faultHours > 0 ? "FAULT" : "PASS",
    reason: faultHours != null ? null : sensorNotAssessed ? "sensor not assessed (no covered time)" : "rule reports no fault_hours",
    fault_hours: faultHours, covered_hours: num(row.covered_hours), fault_pct: num(row.fault_pct), role: row.sensor_role || null,
    engine, metrics, diagnostics: Object.keys(outputs).length ? { outputs } : {}, created_at: iso(runTs),
  };
}

/** Upsert rows (shape of toResultRow) into fdd.rule_result on its primary key (a re-run of a window updates in place). Returns the row count. */
async function writeResults(client, rows) {
  const byKey = new Map();
  for (const r of rows) byKey.set(RESULT_KEY.map((k) => String(r[k] ?? "")).join("\u0001"), r);   // last wins inside one batch
  const unique = [...byKey.values()];
  let n = 0;
  for (let i = 0; i < unique.length; i += 500) {
    const res = await client.query(
      `INSERT INTO fdd.rule_result (site_id, equipment_id, rule_id, subject_key, window_start, window_end, rule_hash, config_hash,
         config_revision, effective_parameters, poll_seconds, status, reason, fault_hours, covered_hours, fault_pct, role, engine,
         metrics, diagnostics, source_watermark, created_at)
       SELECT site_id, equipment_id, rule_id, coalesce(subject_key, ''), window_start, window_end, coalesce(rule_hash, ''), coalesce(config_hash, ''),
         config_revision, coalesce(effective_parameters, '{}'::jsonb), coalesce(poll_seconds, 300), status, reason, fault_hours, covered_hours,
         fault_pct, role, engine, coalesce(metrics, '{}'::jsonb), coalesce(diagnostics, '{}'::jsonb), source_watermark, coalesce(created_at, now())
       FROM jsonb_populate_recordset(null::fdd.rule_result, $1::jsonb)
       ON CONFLICT (site_id, equipment_id, rule_id, subject_key, window_start, window_end, rule_hash, config_hash) DO UPDATE SET
         config_revision = EXCLUDED.config_revision, effective_parameters = EXCLUDED.effective_parameters,
         poll_seconds = EXCLUDED.poll_seconds, status = EXCLUDED.status, reason = EXCLUDED.reason,
         fault_hours = EXCLUDED.fault_hours, covered_hours = EXCLUDED.covered_hours, fault_pct = EXCLUDED.fault_pct,
         role = EXCLUDED.role, engine = EXCLUDED.engine, metrics = EXCLUDED.metrics, diagnostics = EXCLUDED.diagnostics,
         source_watermark = EXCLUDED.source_watermark, created_at = EXCLUDED.created_at`,
      [JSON.stringify(unique.slice(i, i + 500))],
    );
    n += res.rowCount;
  }
  return n;
}

// ---------------------------------------------------------------- size cap (scoped retention)

const DAY_MS = 24 * 3600e3;

/**
 * Once a day (unless the TimescaleDB job exists): openfdd.enforce_size_cap(config max_bytes). Scope = schemas openfdd and fdd (fdd.rule_result)
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

// ---------------------------------------------------------------- persisted rule tuning (#1589 & 5.0.17, fdd.rule_config)

const LIMITS_RULE_ID = "SV-LIMITS";

/** Active revisions in fdd.rule_config, filtered by optional ruleId / siteId: [{ site_id, rule_id, scope_key, revision, parameters }].
 * @param {any} client
 * @param {{ siteId?: string | null, ruleId?: string | null }} [opts]
 */
async function activeRuleConfigs(client, { siteId = null, ruleId = null } = {}) {
  const args = [];
  const conds = ["active"];
  if (ruleId != null) { args.push(ruleId); conds.push(`rule_id = $${args.length}`); }
  if (siteId != null) { args.push(siteId); conds.push(`site_id = $${args.length}`); }
  const { rows } = await client.query(
    `SELECT site_id, rule_id, scope_key, revision, parameters FROM fdd.rule_config WHERE ${conds.join(" AND ")} ORDER BY site_id, rule_id, scope_key`,
    args,
  );
  return rows.map((r) => ({ site_id: r.site_id, rule_id: r.rule_id, scope_key: r.scope_key, revision: Number(r.revision), parameters: r.parameters }));
}

/** Revision history (newest first) of one (siteId, ruleId, scopeKey): [{ revision, active, created_at, created_by, parameters }]. */
async function ruleConfigHistory(client, siteId, ruleId, scopeKey, limit = 50) {
  const { rows } = await client.query(
    `SELECT revision, active, created_at, created_by, parameters FROM fdd.rule_config
      WHERE site_id = $1 AND rule_id = $2 AND scope_key = $3 ORDER BY revision DESC LIMIT $4`,
    [siteId, ruleId, scopeKey, Math.max(1, Math.min(500, Number(limit) || 50))],
  );
  return rows.map((r) => ({ revision: Number(r.revision), active: r.active, created_at: iso(r.created_at), created_by: r.created_by, parameters: r.parameters }));
}

/**
 * Append a new ACTIVE revision for (siteId, ruleId, scopeKey) inside an advisory-locked transaction.
 * When expectedRevision is provided (0 for none active yet, >= 1 for the current active revision),
 * rejects concurrent overwrites with err.code = "revision_conflict".
 */
async function appendRuleConfigRevision(client, { siteId, ruleId, scopeKey, parameters, createdBy, expectedRevision = null }) {
  if (!ruleId || typeof ruleId !== "string") throw new Error("ruleId is required");
  if (!scopeKey || (scopeKey !== "site" && !scopeKey.startsWith("equip:"))) throw new Error('scope must be "site" or "equip:<equipment id>"');
  await client.query("BEGIN");
  try {
    await client.query("SELECT pg_advisory_xact_lock(hashtext($1))", [`${siteId}|${ruleId}|${scopeKey}`]);
    const activeRes = await client.query(
      "SELECT revision FROM fdd.rule_config WHERE site_id = $1 AND rule_id = $2 AND scope_key = $3 AND active ORDER BY revision DESC LIMIT 1",
      [siteId, ruleId, scopeKey],
    );
    const currentActive = activeRes.rows.length ? Number(activeRes.rows[0].revision) : 0;
    if (expectedRevision !== null && expectedRevision !== undefined) {
      const exp = Number(expectedRevision);
      if (!Number.isInteger(exp) || exp < 0) throw new Error("expected_revision must be a non-negative integer");
      if (exp !== currentActive) {
        const err = /** @type {any} */ (new Error(`revision conflict on ${ruleId} (${scopeKey}): active revision is ${currentActive}, expected ${exp}; reload and retry`));
        err.code = "revision_conflict";
        err.activeRevision = currentActive;
        throw err;
      }
    }
    const { rows } = await client.query(
      "SELECT coalesce(max(revision), 0) + 1 AS rev FROM fdd.rule_config WHERE site_id = $1 AND rule_id = $2 AND scope_key = $3",
      [siteId, ruleId, scopeKey],
    );
    const rev = Number(rows[0].rev);
    await client.query("UPDATE fdd.rule_config SET active = false WHERE site_id = $1 AND rule_id = $2 AND scope_key = $3 AND active",
      [siteId, ruleId, scopeKey]);
    await client.query(
      "INSERT INTO fdd.rule_config (site_id, rule_id, scope_key, revision, parameters, active, created_by) VALUES ($1, $2, $3, $4, $5::jsonb, true, $6)",
      [siteId, ruleId, scopeKey, rev, JSON.stringify(parameters), String(createdBy || "open-fdd")]);
    await client.query("COMMIT");
    return rev;
  } catch (e) {
    await client.query("ROLLBACK");
    throw e;
  }
}

/** The parameters of one stored revision (null when it does not exist). */
async function ruleConfigRevision(client, siteId, ruleId, scopeKey, revision) {
  const { rows } = await client.query(
    "SELECT parameters FROM fdd.rule_config WHERE site_id = $1 AND rule_id = $2 AND scope_key = $3 AND revision = $4",
    [siteId, ruleId, scopeKey, Number(revision)],
  );
  return rows.length ? rows[0].parameters : null;
}

const activeRoleLimitOverrides = (client, siteId) => activeRuleConfigs(client, { siteId, ruleId: LIMITS_RULE_ID });
const roleLimitHistory = (client, siteId, scopeKey, limit = 50) => ruleConfigHistory(client, siteId, LIMITS_RULE_ID, scopeKey, limit);
const appendRoleLimitRevision = (client, { siteId, scopeKey, parameters, createdBy, expectedRevision = null }) =>
  appendRuleConfigRevision(client, { siteId, ruleId: LIMITS_RULE_ID, scopeKey, parameters, createdBy, expectedRevision });
const roleLimitRevision = (client, siteId, scopeKey, revision) => ruleConfigRevision(client, siteId, LIMITS_RULE_ID, scopeKey, revision);

module.exports = {
  connect, install, coreOk, schemaVersion, requireConfig, SCHEMA_VERSION, SQL_FILES, pointRows, syncPoints, loadHistory, runRules, toResultRow, writeResults,
  maybeEnforceCap, retentionPreview, historyRoute, siFactors, newestSample,
  LIMITS_RULE_ID, activeRuleConfigs, ruleConfigHistory, appendRuleConfigRevision, ruleConfigRevision,
  activeRoleLimitOverrides, roleLimitHistory, appendRoleLimitRevision, roleLimitRevision,
};
