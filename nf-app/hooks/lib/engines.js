"use strict";
/**
 * SQL engines for the Open-FDD rule pack (CommonJS, NF hook runtime).
 *
 *   const { createEngine } = require("./lib/engines");
 *   const eng = await createEngine({ kind: "sqlite" | "pglite", pack });  // pack = parsed pack-<dialect>.json
 *   await eng.load(input);
 *   const rows = await eng.query("FC1");   // [{ equipment_id, fault_hours, ... }]
 *   await eng.close();
 *
 * kind "pglite": @electric-sql/pglite (exact Postgres, ~300 MB RSS) runs rules/pack-postgres.json.
 * kind "sqlite": sql.js (SQLite WASM, a few MB) runs rules/pack-sqlite.json; the fdd.* helper functions are
 *                JS functions registered with create_function; timestamps are REAL epoch seconds.
 *
 * input = {
 *   historyColumns: [{ name, type: "double" | "text" }],      // columns present in `history` rows
 *   history:   [{ equipment_id, ts /* epoch ms *\/, <col>: number | string | null }],
 *   weather:   [{ ts, oa_t, web_oa_t, web_oa_dp }],
 *   sensorHistory?: [{ equipment_id, series_id, sensor_role, unit, ts, value }],   // long-form sweep input (SI values)
 *   sweepSeries?: [{ equipment_id, series_id, sensor_role, unit, window_start, window_end }], // epoch ms; bound series fetched OK (#1673)
 *   utilityInterval?: [{ ts, kwh }], utilityMonthly?: [{ billing_period, kwh }]   // optional
 * }
 * Contract columns (pack.contract) that are not listed exist as typed NULL columns.
 * Rows come back as plain objects with numbers as JS numbers (NaN/NULL -> null).
 *
 * eng.timeline(ruleId) -> [{ equipment_id, sensor_role?, ts_epoch (s), confirmed 0|1, held_seconds }]: the rule's per-timestamp
 * confirmed flag (pack rule.timeline_sql; [] when the rule has none). held_seconds 0 = not assessed (last sample /
 * gap longer than MAX_GAP_HOURS).
 */
const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------- fdd.* helpers (twins of sql/fdd/postgres/postgres_helpers.sql; SI units only)

const normUnit = (v) => (v == null ? "" : String(v).replace(/[^a-zA-Z0-9]/g, "").toLowerCase());

const QUANTITY = {
  ahu_sat: "absolute_temperature", chw_return_t: "absolute_temperature", chw_supply_sp: "absolute_temperature",
  chw_supply_t: "absolute_temperature", cooling_coil_entering_temp: "absolute_temperature",
  cooling_coil_leaving_temp: "absolute_temperature", cooling_sp: "absolute_temperature", cw_return_t: "absolute_temperature",
  cw_supply_t: "absolute_temperature", heating_coil_entering_temp: "absolute_temperature",
  heating_coil_leaving_temp: "absolute_temperature", heating_sp: "absolute_temperature", hw_return_t: "absolute_temperature",
  hw_supply_t: "absolute_temperature", mat: "absolute_temperature", oa_t: "absolute_temperature",
  preheat_leave_t: "absolute_temperature", rat: "absolute_temperature", sat: "absolute_temperature",
  sat_sp: "absolute_temperature", vav_discharge_t: "absolute_temperature", vav_inlet_t: "absolute_temperature",
  web_oa_dp: "absolute_temperature", web_oa_t: "absolute_temperature", web_wb_t: "absolute_temperature",
  zone_air_temp_sp: "absolute_temperature", zone_t: "absolute_temperature",
  ma_h: "relative_humidity", oa_h: "relative_humidity", ra_h: "relative_humidity", sa_h: "relative_humidity",
  web_oa_h: "relative_humidity", zone_rh: "relative_humidity",
  chw_dp: "air_pressure", chw_dp_sp: "air_pressure", duct_static: "air_pressure", duct_static_sp: "air_pressure",
  chw_flow: "volume_flow", min_flow_sp: "volume_flow", vav_total_flow: "volume_flow", zone_airflow_sp: "volume_flow", zone_flow: "volume_flow",
  chiller_power: "power", electric_kw: "power", electric_kwh: "energy", kwh: "energy",
  chiller_amps: "electric_current", chiller_current: "electric_current", zone_co2: "concentration",
  chw_reset_request_sum: "count", hw_reset_request_sum: "count", static_reset_request: "count",
};
const quantityForRole = (role) => (role == null ? null : QUANTITY[String(role).trim()] || null);

const unitDeclaresQuantity = (unit, quantity) => {
  if (unit == null || String(unit).trim() === "") return 0;
  const n = normUnit(unit);
  if (quantity === "absolute_temperature") return ["c", "degc", "celsius"].includes(n) ? 1 : 0;
  if (quantity === "relative_humidity") {
    return ["pct", "percent", "percent0100", "rh", "percentrelativehumidity"].includes(n) || String(unit).includes("%") ? 1 : 0;
  }
  if (quantity === "air_pressure") {
    return ["pa", "pascal"].includes(n) ? 1 : 0;
  }
  if (quantity === "volume_flow") return n === "ls" ? 1 : 0;
  if (quantity === "power") return n === "kw" ? 1 : 0;
  if (quantity === "energy") return n === "kwh" ? 1 : 0;
  if (quantity === "electric_current") return n === "a" ? 1 : 0;
  if (quantity === "concentration") return n === "ppm" ? 1 : 0;
  if (quantity === "count") return n === "count" ? 1 : 0;
  return 0;
};

const isExpectedConstantRole = (role) => {
  if (role == null || String(role).trim() === "") return 0;
  const n = normUnit(role);
  return n.endsWith("sp") || n.includes("setpoint") || n.includes("status") || n.endsWith("cmd") ||
    n.includes("command") || n === "occmode" || n.includes("occupied") || n.includes("occupancy") ||
    n === "loopenabled" ? 1 : 0;
};

const sweepAssessable = (role, unit) =>
  isExpectedConstantRole(role) ? 0 : unitDeclaresQuantity(unit, quantityForRole(role));

// Postgres `trim(v)::double precision`, NULL when invalid or out of range.
const tryDouble = (v) => {
  if (v == null) return null;
  const s = String(v).trim();
  if (/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) {
    const x = Number(s);
    return Number.isFinite(x) ? x : null;
  }
  if (/^[+-]?(inf|infinity)$/i.test(s)) return s.startsWith("-") ? -Infinity : Infinity;
  return null; // 'nan' cannot live in SQLite either (it would be NULL)
};

const maskSweepVal = (role, unit, val) => (sweepAssessable(role, unit) ? (val === undefined ? null : val) : null);

const HELPERS = {
  fdd_try_double: tryDouble,
  fdd_norm_unit: normUnit,
  fdd_quantity_for_sql_role: quantityForRole,
  fdd_unit_declares_quantity: unitDeclaresQuantity,
  fdd_is_expected_constant_sql_role: isExpectedConstantRole,
  fdd_sweep_assessable_sql_role: sweepAssessable,
  fdd_mask_sweep_val: maskSweepVal,
};

// ---------------------------------------------------------------- input -> table specs (shared by both engines)

const TABLE_INPUT_KEY = {
  history: "history", weather: "weather", utility_interval: "utilityInterval",
  utility_monthly: "utilityMonthly",
  sensor_history: "sensorHistory",
  sweep_series: "sweepSeries",   // #1673: expected sweep series + requested window (SV-STALE)
};
// Which input key feeds a contract column (timestamp_utc is fed from `ts`, epoch ms).
const inputKey = (col) => (col === "timestamp_utc" ? "ts" : col);

/** Columns of each table: the contract's, plus any extra history columns the input declares. */
const tableColumns = (pack, input) => {
  const out = {};
  for (const [table, cols] of Object.entries(pack.contract)) out[table] = cols.map((c) => ({ ...c }));
  const have = new Set(out.history.map((c) => c.name));
  for (const c of input.historyColumns || []) {
    if (!have.has(c.name)) { out.history.push({ name: c.name, type: c.type === "text" ? "text" : "double" }); have.add(c.name); }
  }
  return out;
};

const cellValue = (row, col) => {
  const raw = row[inputKey(col.name)];
  if (raw === undefined || raw === null) return null;
  if (col.type === "timestamp") return Number(raw); // epoch ms
  if (col.type === "text") return String(raw);
  const x = typeof raw === "number" ? raw : Number(raw);
  return Number.isNaN(x) && typeof raw !== "number" ? null : x;
};

const numberOrNull = (v) => (typeof v === "bigint" ? Number(v) : typeof v === "number" ? (Number.isFinite(v) ? v : v) : v);

// ---------------------------------------------------------------- sqlite (sql.js)

let sqlJsPromise = null;
const loadSqlJs = () => {
  if (!sqlJsPromise) {
    // Prefer the copy vendored next to the hook (hooks/vendor/sql.js, same files as the pinned
    // npm version) so small edges need no `npm install`; fall back to node_modules.
    const vendored = path.join(__dirname, "..", "vendor", "sql.js");
    const dir = fs.existsSync(path.join(vendored, "sql-wasm.wasm")) ? vendored : path.dirname(require.resolve("sql.js"));
    const initSqlJs = require(path.join(dir, "sql-wasm.js"));
    const wasmBinary = fs.readFileSync(path.join(dir, "sql-wasm.wasm"));
    sqlJsPromise = initSqlJs({ wasmBinary });
  }
  return sqlJsPromise;
};

const quoteId = (s) => '"' + String(s).replace(/"/g, '""') + '"';

const rowsOf = (res) => {
  if (!res.length) return [];
  const { columns, values } = res[0];
  return values.map((v) => {
    const o = {};
    columns.forEach((c, i) => { o[c] = v[i]; });
    return o;
  });
};

async function createSqlite(pack) {
  const SQL = await loadSqlJs();
  const db = new SQL.Database();
  for (const name of pack.helper_functions || Object.keys(HELPERS)) {
    const fn = HELPERS[name];
    if (!fn) throw new Error(`pack needs helper ${name}, engines.js does not implement it`);
    // sql.js derives the SQL arity from the JS function's .length, so wrap with a fixed arity.
    const nul = (r) => (r === undefined ? null : r);
    const wrapped = [() => nul(fn()), (a) => nul(fn(a)), (a, b) => nul(fn(a, b)), (a, b, c) => nul(fn(a, b, c))][fn.length];
    db.create_function(name, wrapped);
  }
  let loaded = false;
  return {
    kind: "sqlite",
    async load(input) {
      const cols = tableColumns(pack, input);
      db.run("BEGIN");
      try {
        for (const [table, spec] of Object.entries(cols)) {
          db.run(`DROP TABLE IF EXISTS ${table}`);
          db.run(`CREATE TABLE ${table} (${spec.map((c) => `${quoteId(c.name)} ${c.type === "text" ? "TEXT" : "REAL"}`).join(", ")})`);
          const rows = input[TABLE_INPUT_KEY[table]] || [];
          if (!rows.length) continue;
          const stmt = db.prepare(`INSERT INTO ${table} VALUES (${spec.map(() => "?").join(",")})`);
          try {
            for (const row of rows) {
              stmt.run(spec.map((c) => {
                const v = cellValue(row, c);
                if (v === null) return null;
                if (c.type === "timestamp") return Number(v) / 1000;
                return typeof v === "number" && Number.isNaN(v) ? null : v; // SQLite stores NaN as NULL anyway
              }));
            }
          } finally { stmt.free(); }
        }
        db.run("CREATE INDEX IF NOT EXISTS history_eq_ts ON history(equipment_id, timestamp_utc)");
        db.run("COMMIT");
      } catch (e) { db.run("ROLLBACK"); throw e; }
      loaded = true;
    },
    async query(ruleId) {
      if (!loaded) throw new Error("engine: call load(input) before query()");
      const rule = pack.rules[ruleId];
      if (!rule) {
        const why = pack.skipped && pack.skipped[ruleId];
        throw new Error(why ? `rule ${ruleId} is skipped on sqlite: ${why}` : `unknown rule ${ruleId}`);
      }
      return rowsOf(db.exec(rule.sql));
    },
    /** Per-timestamp confirmed flags. Sensor sweeps also return sensor_role. Empty when the rule has no timeline. */
    async timeline(ruleId) {
      if (!loaded) throw new Error("engine: call load(input) before timeline()");
      const rule = pack.rules[ruleId];
      if (!rule || !rule.timeline_sql) return [];
      return rowsOf(db.exec(rule.timeline_sql));
    },
    // Also drop the cached sql.js module so its WASM memory can be collected between hourly
    // runs: on a 1 GB edge the runtime otherwise keeps ~40 MB resident for nothing.
    async close() { db.close(); sqlJsPromise = null; },
  };
}

// ---------------------------------------------------------------- pglite

const PG_TYPE = { double: "DOUBLE PRECISION", text: "VARCHAR", timestamp: "timestamptz" };
const NUMERIC_OIDS = new Set([20, 21, 23, 700, 701, 1700]);

const pgLiteral = (c, v) => {
  if (v === null) return "NULL";
  if (c.type === "timestamp") return `'${new Date(v).toISOString()}'`;
  if (c.type === "text") return `'${String(v).replace(/'/g, "''")}'`;
  if (Number.isNaN(v)) return "'NaN'::float8";
  if (!Number.isFinite(v)) return v > 0 ? "'Infinity'::float8" : "'-Infinity'::float8";
  return String(v);
};

const pgRows = (res) => {
  const numeric = new Set(res.fields.filter((f) => NUMERIC_OIDS.has(f.dataTypeID)).map((f) => f.name));
  return res.rows.map((r) => {
    const o = {};
    for (const [k, v] of Object.entries(r)) {
      o[k] = numeric.has(k) && v !== null && v !== undefined ? numberOrNull(typeof v === "string" ? Number(v) : v) : v;
    }
    return o;
  });
};

async function createPglite(pack) {
  let PGlite;
  try {
    ({ PGlite } = await import("@electric-sql/pglite"));
  } catch (e) {
    if (e && (e.code === "ERR_MODULE_NOT_FOUND" || /Cannot find (package|module)/.test(String(e.message)))) {
      throw new Error("pglite is not installed. It is a parity-test engine only (nf-app devDependency), not a runtime engine. Use duckdb or timescale.");
    }
    throw e;
  }
  const db = new PGlite();
  await db.waitReady;
  await db.exec(pack.helpers_sql);
  let loaded = false;
  return {
    kind: "pglite",
    async load(input) {
      const cols = tableColumns(pack, input);
      for (const [table, spec] of Object.entries(cols)) {
        await db.exec(`DROP TABLE IF EXISTS ${table}`);
        await db.exec(`CREATE TABLE ${table} (${spec.map((c) => `${quoteId(c.name)} ${PG_TYPE[c.type]}`).join(", ")})`);
        const rows = input[TABLE_INPUT_KEY[table]] || [];
        const names = spec.map((c) => quoteId(c.name)).join(", ");
        for (let i = 0; i < rows.length; i += 200) {
          const values = rows.slice(i, i + 200)
            .map((row) => "(" + spec.map((c) => pgLiteral(c, cellValue(row, c))).join(", ") + ")").join(",\n");
          await db.exec(`INSERT INTO ${table} (${names}) VALUES\n${values}`);
        }
      }
      await db.exec("CREATE INDEX history_eq_ts ON history(equipment_id, timestamp_utc)");
      // Planner statistics for the window / as-of joins (#1631): without them PGlite guesses row counts and the sweep
      // rules' joins degrade to nested loops (seconds -> tens of seconds on a week of 5-min data).
      for (const table of Object.keys(cols)) await db.exec(`ANALYZE ${table}`);
      loaded = true;
    },
    async query(ruleId) {
      if (!loaded) throw new Error("engine: call load(input) before query()");
      const rule = pack.rules[ruleId];
      if (!rule) throw new Error(`unknown rule ${ruleId}`);
      return pgRows(await db.query(rule.sql));
    },
    async timeline(ruleId) {
      if (!loaded) throw new Error("engine: call load(input) before timeline()");
      const rule = pack.rules[ruleId];
      if (!rule || !rule.timeline_sql) return [];
      return pgRows(await db.query(rule.timeline_sql));
    },
    async close() { await db.close(); },
  };
}

/** sha256 (hex) of a rule's SQL text: the rule_hash provenance of fdd.rule_result rows. */
const ruleHashes = new WeakMap();
/** #1707: a statistic rule outputs no fault_hours (AVG-ZONE-TEMP, ZONE-COMFORT-PCT, FAN-RUNTIME-HOURS); it is written as METRIC. */
function isMetricRule(pack, ruleId) {
  const r = pack && pack.rules && pack.rules[ruleId];
  return !!(r && Array.isArray(r.output_columns) && !r.output_columns.includes("fault_hours"));
}

function ruleHash(pack, ruleId) {
  let byRule = ruleHashes.get(pack);
  if (!byRule) ruleHashes.set(pack, (byRule = new Map()));
  if (!byRule.has(ruleId)) {
    const rule = pack.rules[ruleId];
    byRule.set(ruleId, rule ? require("crypto").createHash("sha256").update(String(rule.sql)).digest("hex") : "");
  }
  return byRule.get(ruleId);
}

// ---------------------------------------------------------------- timescale (FULL edition: rules run inside NF's TimescaleDB)

/**
 * Not fed with prebuilt rows: load() takes { equipId, siteId, roleToUuid, unitsByUuid, pointMeta, fractionRoles, booleanRoles,
 * sensorSeries, from, to, stepSec } (the two role arrays are siPlan's scale decisions, #1541), mirrors the bound points into
 * fdd.point (their SI scale / offset), and builds the pack's wide `history` in SQL from fdd.input_sample (see
 * timescale/adapter_nf.sql); returns the row count.
 * opts.client = an already connected pg client (tests); otherwise opts.config (hook config.timescale) is used.
 */
async function createTimescale(pack, opts = {}) {
  const ts = require("./timescale");
  if (!opts.client) ts.requireConfig(opts.config);   // engine "timescale" without config.timescale fails visibly, never falls back
  const client = opts.client || (await ts.connect(opts.config));
  const owned = !opts.client;
  try {
    // The v4 core tables (fdd.point / fdd.rule_result) must exist before any sync or result write.
    const ver = await ts.schemaVersion(client);
    if (ver < ts.SCHEMA_VERSION) {
      try { await ts.install(client); } catch (e) {
        throw new Error(`openfdd schema upgrade not applied (${e.message}); run timescale/install.sql as the installer role`);
      }
    }
  } catch (e) { if (owned) await client.end(); throw e; }
  return {
    kind: "timescale",
    client,
    warnings: [],
    async load(args) {
      await ts.syncPoints(client, { siteId: args.siteId || "", equipId: args.equipId, rows: ts.pointRows({ pack, ...args }) });
      const { rows, sensorRows } = await ts.loadHistory(client, { pack, ...args });
      return rows || sensorRows;
    },
    /**
     * #1636: write a synthesized occ_mode (1 occupied / 0 not, from at(ms)) onto this equipment's session history rows,
     * after load(). Only called when no occ_mode point is bound. Returns the number of rows updated.
     */
    async occupancy(equipId, at) {
      const res = await client.query("SELECT DISTINCT timestamp_utc FROM pg_temp.history WHERE equipment_id = $1", [equipId]);
      if (!res.rows.length) return 0;
      const ts = res.rows.map((r) => new Date(r.timestamp_utc));
      const upd = await client.query(
        `UPDATE pg_temp.history h SET occ_mode = v.occ
         FROM unnest($2::timestamptz[], $3::float8[]) AS v(ts, occ)
         WHERE h.equipment_id = $1 AND h.timestamp_utc = v.ts`,
        [equipId, ts.map((d) => d.toISOString()), ts.map((d) => (at(d.getTime()) ? 1 : 0))]);
      return upd.rowCount;
    },
    /** Mirror the bound points of one equipment into fdd.point (load() does this itself). */
    syncPoints: (args) => ts.syncPoints(client, { siteId: args.siteId || "", equipId: args.equipId, rows: ts.pointRows({ pack, ...args }) }),
    /** sql: optional { sql, timeline_sql } of this rule re-rendered with role-limit overrides (#1589); default the pack's. */
    async query(ruleId, sql) {
      const runPack = sql && pack.rules[ruleId] ? { ...pack, rules: { ...pack.rules, [ruleId]: { ...pack.rules[ruleId], ...sql } } } : pack;
      const { results, errors } = await ts.runRules(client, runPack, [ruleId]);
      if (errors[ruleId]) throw new Error(errors[ruleId]);
      return results[ruleId];
    },
    /** Same contract as the other engines; call it after query() of the rule (the helper SQL is installed there). */
    async timeline(ruleId, sql) {
      const rule = sql && pack.rules[ruleId] ? { ...pack.rules[ruleId], ...sql } : pack.rules[ruleId];
      if (!rule || !rule.timeline_sql) return [];
      const res = await client.query(rule.timeline_sql);
      const numeric = new Set(res.fields.filter((f) => NUMERIC_OIDS.has(f.dataTypeID)).map((f) => f.name));
      return res.rows.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, numeric.has(k) && v != null ? Number(v) : v])));
    },
    /** Newest sample (epoch ms | null) of these points in the source table, any age (read-only). */
    newestSample: (uuids) => ts.newestSample(client, uuids),
    resultRow: (a) => ts.toResultRow({ engine: "timescale", pollSeconds: pack.poll_seconds, ruleHash: ruleHash(pack, a.ruleId),
      metric: isMetricRule(pack, a.ruleId), ...a }),
    /** Active role-limit override revisions (fdd.rule_config SV-LIMITS) of every site (#1589). */
    roleLimitOverrides: () => ts.activeRoleLimitOverrides(client),
    ruleConfigOverrides: () => ts.activeRuleConfigs(client),
    writeResults: (rows) => ts.writeResults(client, rows),
    maybeEnforceCap: () => ts.maybeEnforceCap(client),
    async close() { if (owned) await client.end(); },
  };
}

// ---------------------------------------------------------------- duckdb (#1645: native DuckDB, warm in-memory instance)

/**
 * Native DuckDB (@duckdb/node-api, pinned in package.json dependencies) runs the Postgres pack as written; the
 * fdd.* helpers are the SQL macros of pack.duckdb_helpers_sql (sql/fdd/duckdb/duckdb_helpers.sql).
 *
 * Lifetime: ONE in-memory DuckDB instance per hook process, created on first use and kept warm between runs (no
 * re-initialisation, macros installed once). Each createEngine() opens its own connection and loads the inputs into
 * TEMP tables of that connection, so overlapping runs never see each other's rows; close() disconnects, which drops
 * them. releaseDuckDb() closes the instance itself (tests, shutdown). Incremental append and Parquet history are later
 * slices of #1645: today every run reloads its window, as the other in-process engines do.
 *
 * Offline and disk-free by construction (DUCKDB_SAFETY): extension autoinstall and autoload are OFF, so DuckDB never
 * downloads anything (an edge box may have no internet); everything the pack needs (core functions, ICU time zones,
 * Parquet, JSON) is statically linked in the 2.0.1 build. TimeZone is set with SET GLOBAL after creation: passing it as
 * a create option makes DuckDB try to autoinstall ICU from the network first. temp_directory is '' (DuckDB's default for
 * an in-memory database is '.tmp' with up to 90 % of the free disk), so nothing is ever spilled to the SD card.
 *
 * Memory (1 GB edges): the instance is capped by DuckDB's memory_limit (default DUCKDB_DEFAULTS.memoryLimit) and
 * threads. With spilling off, a query over the cap fails with an out-of-memory error (the rule is reported as a rule
 * error). If the instance cannot be created at all, createEngine throws and the run fails loudly (no silent engine
 * swap). A package that does not load fails the same way in pickEngine and does not switch engines. Settings: app options duckdbMemoryLimit
 * ("256MB") and duckdbThreads (2), passed here as opts.config { memoryLimit, threads }; env OPENFDD_DUCKDB_MEMORY_LIMIT /
 * OPENFDD_DUCKDB_THREADS when unset.
 * The settings of the first engine of a process win until releaseDuckDb().
 */
const DUCKDB_PACKAGE = "@duckdb/node-api";
const DUCKDB_DEFAULTS = Object.freeze({ memoryLimit: "256MB", threads: 2 });
const DUCK_TYPE = { double: "DOUBLE", text: "VARCHAR", timestamp: "TIMESTAMPTZ" };
/** Fixed settings of every instance: no network, no disk (see above). */
const DUCKDB_SAFETY = Object.freeze({ autoinstall_known_extensions: "false", autoload_known_extensions: "false", temp_directory: "" });
/** Extra settings a caller may add (tests: point the extension repository at an unreachable host to prove offline use). */
const DUCKDB_EXTRA_KEYS = ["custom_extension_repository", "extension_directory"];
let duck = null;   // { api, instance, options, ready: Promise } of this process

/** Validated DuckDB options: memory_limit like "256MB" / "1GB", threads 1..64. Throws on anything else. */
function duckDbOptions(cfg = {}) {
  const env = (typeof process !== "undefined" && process.env) || {};
  const mem = String(cfg.memoryLimit ?? env.OPENFDD_DUCKDB_MEMORY_LIMIT ?? DUCKDB_DEFAULTS.memoryLimit).trim();
  if (!/^\d+(\.\d+)?\s*(KB|MB|GB|KiB|MiB|GiB)$/i.test(mem)) throw new Error(`duckdb memoryLimit ${JSON.stringify(mem)}: use e.g. "256MB" or "1GB"`);
  const threads = Number(cfg.threads ?? env.OPENFDD_DUCKDB_THREADS ?? DUCKDB_DEFAULTS.threads);
  if (!Number.isInteger(threads) || threads < 1 || threads > 64) throw new Error(`duckdb threads ${JSON.stringify(cfg.threads)}: use an integer 1..64`);
  const extra = {};
  for (const [k, v] of Object.entries(cfg.extraSettings || {})) {
    if (!DUCKDB_EXTRA_KEYS.includes(k)) throw new Error(`duckdb setting ${JSON.stringify(k)} is not allowed`);
    extra[k] = String(v);
  }
  return { memory_limit: mem.replace(/\s+/g, ""), threads: String(threads), ...extra, ...DUCKDB_SAFETY };
}

async function loadDuckDbApi() {
  try {
    return await import(DUCKDB_PACKAGE);
  } catch (e) {
    const err = new Error(`duckdb not installed or not loadable on this platform (${e && e.message}): install the app dependencies `
      + `(nf_app_sync.py install, or PATCH /api/v1/apps/<app-id>/dependencies then restart); ${DUCKDB_PACKAGE} ships `
      + "native builds for linux x64/arm64 (glibc, musl), win32 x64/arm64 and darwin only");
    /** @type {any} */ (err).code = "OPENFDD_DUCKDB_UNAVAILABLE";
    throw err;
  }
}

/** The warm process instance, created on first use; macros installed once. */
async function warmDuckDb(pack, cfg) {
  if (!pack.duckdb_helpers_sql) throw new Error("duckdb engine needs pack-postgres.json with duckdb_helpers_sql (rebuild: scripts/nf/build_sql_pack.py)");
  if (!duck) {
    const options = duckDbOptions(cfg);
    const state = { api: null, instance: null, options, helpers: pack.duckdb_helpers_sql, ready: null };
    state.ready = (async () => {
      state.api = await loadDuckDbApi();
      state.instance = await state.api.DuckDBInstance.create(":memory:", options);
      const conn = await state.instance.connect();
      try {
        await conn.run("SET GLOBAL TimeZone = 'UTC'");   // built-in ICU; never a create option (that autoinstalls)
        await conn.run(pack.duckdb_helpers_sql);
      } finally { conn.closeSync(); }
    })();
    duck = state;
    try { await state.ready; } catch (e) {
      if (duck === state) duck = null;
      try { if (state.instance) state.instance.closeSync(); } catch { /* keep the original error */ }
      throw e;
    }
  } else {
    await duck.ready;
    if (duck.helpers !== pack.duckdb_helpers_sql) {   // a newer pack in the same process: refresh the macros
      const conn = await duck.instance.connect();
      try { await conn.run(pack.duckdb_helpers_sql); duck.helpers = pack.duckdb_helpers_sql; } finally { conn.closeSync(); }
    }
  }
  return duck;
}

/** Close the warm instance (frees its memory). The next duckdb engine creates a new one. */
async function releaseDuckDb() {
  const state = duck;
  duck = null;
  if (!state) return;
  try { await state.ready; } catch { return; }
  state.instance.closeSync();
}

/** DuckDB JS values -> the plain values the other engines return (BIGINT/HUGEINT/DECIMAL -> number). */
const duckValue = (v) => {
  if (v === null || v === undefined) return null;
  if (typeof v === "bigint") return Number(v);
  if (typeof v === "number" || typeof v === "string" || typeof v === "boolean" || v instanceof Date) return v;
  if (typeof v.toDouble === "function") return v.toDouble();   // DuckDBDecimalValue and friends
  return v;
};
const duckRows = (reader) => reader.getRowObjectsJS().map((r) => {
  const o = {};
  for (const [k, v] of Object.entries(r)) o[k] = duckValue(v);
  return o;
});

async function createDuckDb(pack, opts = {}) {
  const state = await warmDuckDb(pack, opts.config);
  const { api } = state;
  const conn = await state.instance.connect();
  let loaded = false;
  let closed = false;
  const runSql = async (ruleId, sql, which) => {
    if (!loaded) throw new Error(`engine: call load(input) before ${which}()`);
    return duckRows(await conn.runAndReadAll(sql));
  };
  const ruleOf = (ruleId, sql) => {
    const rule = pack.rules[ruleId];
    if (!rule) throw new Error(`unknown rule ${ruleId}`);
    return sql ? { ...rule, ...sql } : rule;
  };
  // Saved tuning (#1589/#1636): the store is fdd.rule_config in the app's Timescale database. When the app has one
  // (option timescale, or opts.tuningClient in tests), this engine reads the same active revisions as the timescale
  // engine, and the hook renders the tuned Postgres SQL (DuckDB runs it as is) into query(ruleId, sql) / timeline().
  const tuningSource = opts.tuningClient || (opts.config && opts.config.timescale) || null;
  const tuning = tuningSource ? {
    async ruleConfigOverrides() {
      const ts = require("./timescale");
      if (opts.tuningClient) return ts.activeRuleConfigs(opts.tuningClient);
      const client = await ts.connect(opts.config.timescale);
      try { return await ts.activeRuleConfigs(client); } finally { await client.end(); }
    },
  } : {};
  return {
    kind: "duckdb",
    ...tuning,
    /** The settings that keep the engine offline and off the disk, as this connection sees them (doctor, tests). */
    async settings() {
      return (await conn.runAndReadAll(`SELECT current_setting('TimeZone') AS time_zone, current_setting('temp_directory') AS temp_directory,
        current_setting('autoinstall_known_extensions') AS autoinstall, current_setting('autoload_known_extensions') AS autoload,
        current_setting('memory_limit') AS memory_limit, current_setting('threads') AS threads`)).getRowObjectsJS().map((r) => {
        const o = {}; for (const [k, v] of Object.entries(r)) o[k] = duckValue(v); return o;
      })[0];
    },
    /** DuckDB version string of the warm instance (e.g. "v2.0.1"). */
    async version() { return (await conn.runAndReadAll("SELECT version() AS v")).getRowObjectsJS()[0].v; },
    async load(input) {
      const cols = tableColumns(pack, input);
      for (const [table, spec] of Object.entries(cols)) {
        await conn.run(`CREATE OR REPLACE TEMP TABLE ${table} (${spec.map((c) => `${quoteId(c.name)} ${DUCK_TYPE[c.type]}`).join(", ")})`);
        const rows = input[TABLE_INPUT_KEY[table]] || [];
        if (!rows.length) continue;
        const app = await conn.createAppender(table, "main", "temp");
        try {
          for (const row of rows) {
            for (const c of spec) {
              const v = cellValue(row, c);
              if (v === null) app.appendNull();
              else if (c.type === "timestamp") app.appendTimestampTZ(new api.DuckDBTimestampTZValue(BigInt(Math.round(Number(v) * 1000))));
              else if (c.type === "text") app.appendVarchar(v);
              else app.appendDouble(v);   // NaN / +-Infinity kept, as in Postgres
            }
            app.endRow();
          }
          app.flushSync();
        } finally { app.closeSync(); }
      }
      loaded = true;
    },
    /** sql: optional { sql, timeline_sql } re-rendered with tuning overrides (#1589); default the pack's. */
    async query(ruleId, sql) { return runSql(ruleId, ruleOf(ruleId, sql).sql, "query"); },
    async timeline(ruleId, sql) {
      const rule = pack.rules[ruleId] ? ruleOf(ruleId, sql) : null;
      if (!rule || !rule.timeline_sql) return [];
      return runSql(ruleId, rule.timeline_sql, "timeline");
    },
    /** Disconnects (drops this run's TEMP tables); the warm instance stays for the next run. */
    async close() { if (!closed) { closed = true; conn.closeSync(); } },
  };
}

// ---------------------------------------------------------------- public

async function createEngine({ kind, pack, ...opts }) {
  if (!pack || !pack.rules || !pack.contract) throw new Error("createEngine: pack (parsed pack-*.json) is required");
  if (kind === "sqlite") return createSqlite(pack);
  if (kind === "pglite") return createPglite(pack);
  if (kind === "timescale") return createTimescale(pack, opts);
  if (kind === "duckdb") return createDuckDb(pack, opts);
  throw new Error(`unknown engine kind ${JSON.stringify(kind)} (runtime engines are "duckdb" and "timescale"; "sqlite" and "pglite" are parity-test engines)`);
}

module.exports = { createEngine, HELPERS, loadSqlJs, releaseDuckDb, duckDbOptions, DUCKDB_DEFAULTS, DUCKDB_SAFETY };
