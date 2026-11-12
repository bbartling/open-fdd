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
    return ["pct", "percent", "rh", "percentrelativehumidity"].includes(n) || String(unit).includes("%") ? 1 : 0;
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
      throw new Error('pglite not installed: install the app dependencies (nf_app_sync.py install, or PATCH /api/v1/apps/<app-id>/dependencies then restart), or set the hook config engine to "sqlite"');
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

// ---------------------------------------------------------------- timescale (FULL edition: rules run inside NF's TimescaleDB)

/**
 * Not fed with prebuilt rows: load() takes { equipId, siteId, roleToUuid, unitsByUuid, fractionRoles, booleanRoles, from,
 * to, stepSec } (the last two arrays are siPlan's scale decisions, #1541) and builds
 * the pack's wide `history` in SQL from openfdd.nf_samples (see timescale/adapter_nf.sql); returns the row count.
 * opts.client = an already connected pg client (tests); otherwise opts.config (hook config.timescale) is used.
 */
async function createTimescale(pack, opts = {}) {
  const ts = require("./timescale");
  if (!opts.client) ts.requireConfig(opts.config);   // engine "timescale" without config.timescale fails visibly, never falls back
  const client = opts.client || (await ts.connect(opts.config));
  const owned = !opts.client;
  try {
    // The v3 result upsert requires the migrated key before any result writes.
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
      const { rows, sensorRows } = await ts.loadHistory(client, { pack, ...args });
      return rows || sensorRows;
    },
    async query(ruleId) {
      const { results, errors } = await ts.runRules(client, pack, [ruleId]);
      if (errors[ruleId]) throw new Error(errors[ruleId]);
      return results[ruleId];
    },
    /** Same contract as the other engines; call it after query() of the rule (the helper SQL is installed there). */
    async timeline(ruleId) {
      const rule = pack.rules[ruleId];
      if (!rule || !rule.timeline_sql) return [];
      const res = await client.query(rule.timeline_sql);
      const numeric = new Set(res.fields.filter((f) => NUMERIC_OIDS.has(f.dataTypeID)).map((f) => f.name));
      return res.rows.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, numeric.has(k) && v != null ? Number(v) : v])));
    },
    /** Newest sample (epoch ms | null) of these points in the source table, any age (read-only). */
    newestSample: (uuids) => ts.newestSample(client, uuids),
    resultRow: (a) => ts.toResultRow({ engine: "timescale", ...a }),
    writeResults: (rows) => ts.writeResults(client, rows),
    maybeEnforceCap: () => ts.maybeEnforceCap(client),
    async close() { if (owned) await client.end(); },
  };
}

// ---------------------------------------------------------------- public

async function createEngine({ kind, pack, ...opts }) {
  if (!pack || !pack.rules || !pack.contract) throw new Error("createEngine: pack (parsed pack-*.json) is required");
  if (kind === "sqlite") return createSqlite(pack);
  if (kind === "pglite") return createPglite(pack);
  if (kind === "timescale") return createTimescale(pack, opts);
  throw new Error(`unknown engine kind ${JSON.stringify(kind)} (use "sqlite", "pglite" or "timescale")`);
}

module.exports = { createEngine, HELPERS };
