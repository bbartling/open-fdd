// SQL analytics for the NF app (#1649): the portable queries in sql/analytics (copied to nf-app/rules/analytics by
// scripts/nf/sync_shared.py) rendered and run in-process on SQLite (the vendored sql.js) or PGlite.
//
// The renderers mirror the Python ones byte for byte (open_fdd/analytics/sql_runtime.py, sql_mech_cooling.py,
// sql_economizer.py, sql_bas_web.py): comment lines dropped, {placeholders} replaced by checked literals (quoted strings,
// integers, Python-repr floats), inline tables as SELECT ... UNION ALL. pandas is the reference; the parity tests compare
// the answers. There is no JS analytics math: these queries are the math.
"use strict";

const fs = require("fs");
const path = require("path");

const TEMPLATE_DIR = path.join(__dirname, "..", "..", "rules", "analytics");
const TS_MS = { sqlite: "s.ts", postgres: "CAST(EXTRACT(EPOCH FROM s.ts) * 1000 AS BIGINT)" };
/** open_fdd.analytics.si_thresholds.MECH_OAT_BIN_EDGES_C and MECH_OAT_BIN_LABELS. */
const MECH_OAT_BIN_EDGES_C = [10.0, 15.555555555555556, 21.11111111111111, 26.666666666666668, 32.22222222222222];
const MECH_OAT_BIN_LABELS = ["<10", "10-16", "16-21", "21-27", "27-32", ">=32"];
const ELAPSED_MAX_GAP_SECONDS = 3600.0;
const ECON_DIAG_DT_MIN_C = 10.0 * 5.0 / 9.0;
const BAS_WEB_BAND_C = 2.0;

const templates = {};
function template(name) {
  if (!templates[name]) templates[name] = fs.readFileSync(path.join(TEMPLATE_DIR, `${name}.sql`), "utf8").replace(/\r\n/g, "\n");
  return templates[name];
}

/** Python repr() of a float (the renderers' literal for a double): 5.0, 0.638888889, 1e-05. */
function pyRepr(v) {
  const x = Number(v);
  if (!Number.isFinite(x)) throw new Error("numbers rendered into SQL must be finite");
  if (Object.is(x, -0)) return "-0.0";
  const ax = Math.abs(x);
  if (x !== 0 && (ax < 1e-4 || ax >= 1e16)) {
    const [m, e] = x.toExponential().split("e");
    const exp = Number(e);
    return `${m}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  return Number.isInteger(x) ? `${x}.0` : String(x);
}

const quote = (s) => "'" + String(s).replace(/'/g, "''") + "'";

function intOf(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(`not an integer: ${v}`);
  return String(Math.trunc(n));
}

/** A typed inline table (open_fdd.analytics.sql_runtime._inline). columns: [[name, "TEXT"|"INTEGER"|"DOUBLE PRECISION"]]. */
function inline(columns, rows) {
  const lit = (v, t) => {
    if (v === null || v === undefined) return `CAST(NULL AS ${t})`;
    if (t === "TEXT") return quote(v);
    if (t === "INTEGER") return intOf(v);
    return `CAST(${pyRepr(v)} AS DOUBLE PRECISION)`;
  };
  if (!rows.length) return "  SELECT " + columns.map(([c, t]) => `${lit(null, t)} AS ${c}`).join(", ") + " WHERE 1 = 0";
  return rows.map((row) => "  SELECT " + columns.map(([c, t], i) => `${lit(row[i], t)} AS ${c}`).join(", ")).join("\n  UNION ALL\n");
}

/** Drop comment lines and fill {placeholders}; every placeholder must be supplied. */
function render(name, values) {
  const lines = template(name).split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();   // Python str.splitlines() drops the final newline
  const body = lines.filter((ln) => !ln.trimStart().startsWith("--")).join("\n");
  return body.replace(/\{(\w+)\}/g, (m, k) => {
    if (!(k in values)) throw new Error(`${name}: no value for {${k}}`);
    return values[k];
  });
}

function windowFilter(startMs, endMs, col = "t") {
  if (startMs != null && endMs != null && Number(endMs) <= Number(startMs)) throw new Error("end_ms must be after start_ms");
  let f = "";
  if (startMs != null) f += ` AND ${col} >= ${intOf(startMs)}`;
  if (endMs != null) f += ` AND ${col} < ${intOf(endMs)}`;
  return f;
}

function checkEngine(engine) {
  if (!(engine in TS_MS)) throw new Error(`unknown engine ${engine}`);
}

function gapMs(seconds = ELAPSED_MAX_GAP_SECONDS) {
  const g = Number(seconds);
  if (!Number.isFinite(g) || g <= 0) throw new Error("max_gap_seconds must be a positive number");
  return String(Math.round(g * 1000));
}

// ---------------------------------------------------------------- renderers (twins of the Python ones)

/** sql_runtime.render_runtime_sql. */
function renderRuntime(engine, { siteId = "local", equipmentIds = null, startMs = null, endMs = null,
  maxGapSeconds = ELAPSED_MAX_GAP_SECONDS, oats = [], weeks = [], occupied = null } = {}) {
  checkEngine(engine);
  const g = gapMs(maxGapSeconds);
  const eqs = equipmentIds || [];
  return render("motor_weekly_runtime", {
    site_id: quote(siteId),
    equipment_filter: eqs.length ? "\n    AND p.equipment_id IN (" + eqs.map(quote).join(", ") + ")" : "",
    window_filter: windowFilter(startMs, endMs),
    ts_ms: TS_MS[engine],
    max_gap_ms: g,
    oats: inline([["equipment_id", "TEXT"], ["point_key", "TEXT"]], oats),
    weeks: inline([["equipment_id", "TEXT"], ["week_ms", "INTEGER"]], weeks),
    occ: inline([["equipment_id", "TEXT"], ["start_ms", "INTEGER"], ["end_ms", "INTEGER"]], occupied || []),
    use_occ: occupied == null ? "0" : "1",
  });
}

/** sql_mech_cooling.render_mech_bins_sql (plan = { candidates, gates, oats }). */
function renderMechBins(engine, plan, { siteId = "local", startMs = null, endMs = null, maxGapSeconds = ELAPSED_MAX_GAP_SECONDS } = {}) {
  checkEngine(engine);
  const g = gapMs(maxGapSeconds);
  for (const row of plan.candidates) if (row[4] !== "on" && row[4] !== "above") throw new Error(`unknown proof kind ${row[4]}`);
  let cases = MECH_OAT_BIN_EDGES_C.map((e, i) => `WHEN oat < ${pyRepr(e)} THEN ${i}`).join(" ");
  cases += ` ELSE ${MECH_OAT_BIN_EDGES_C.length}`;
  return render("mech_cooling_oat_bins", {
    candidates: inline([["equipment_id", "TEXT"], ["tier", "INTEGER"], ["alt", "INTEGER"], ["point_key", "TEXT"],
      ["kind", "TEXT"], ["thr", "DOUBLE PRECISION"]], plan.candidates),
    gates: inline([["equipment_id", "TEXT"], ["point_key", "TEXT"]], plan.gates),
    oats: inline([["equipment_id", "TEXT"], ["point_key", "TEXT"]], plan.oats),
    ts_ms: TS_MS[engine],
    site_id: quote(siteId),
    window_filter: windowFilter(startMs, endMs),
    max_gap_ms: g,
    bin_cases: cases,
  });
}

/** sql_economizer.render_economizer_sql (roles = [[equipment_id, role, point_key]]). */
function renderEconomizer(engine, roles, { siteId = "local", dtMinC = ECON_DIAG_DT_MIN_C, startMs = null, endMs = null,
  maxGapSeconds = ELAPSED_MAX_GAP_SECONDS } = {}) {
  checkEngine(engine);
  for (const [, role] of roles) if (!["fan", "oat", "rat", "mat", "damper"].includes(role)) throw new Error(`unknown economizer role ${role}`);
  const dt = Number(dtMinC);
  if (!Number.isFinite(dt) || dt < 0) throw new Error("dt_min_c must be a non-negative number");
  return render("economizer_metrics", {
    roles: inline([["equipment_id", "TEXT"], ["role", "TEXT"], ["point_key", "TEXT"]], roles),
    ts_ms: TS_MS[engine],
    site_id: quote(siteId),
    window_filter: windowFilter(startMs, endMs),
    max_gap_ms: gapMs(maxGapSeconds),
    dt_min: pyRepr(dt),
  });
}

/** sql_bas_web.render_bas_web_sql (pairs = [[equipment_id, bas_key, web_key, max_age_ms]]). */
function renderBasWeb(engine, pairs, { siteId = "local", bandC = BAS_WEB_BAND_C, startMs = null, endMs = null } = {}) {
  checkEngine(engine);
  for (const p of pairs) if (!(Number(p[3]) >= 0)) throw new Error("max_age_ms must be >= 0");
  const band = Number(bandC);
  if (!Number.isFinite(band) || band < 0) throw new Error("band_c must be a non-negative number");
  if (startMs != null && endMs != null && Number(endMs) <= Number(startMs)) throw new Error("end_ms must be after start_ms");
  let wf = "", wwf = "";
  if (startMs != null) { wf += ` AND t >= ${intOf(startMs)}`; wwf += ` AND w.t >= ${intOf(startMs)} - w.max_age_ms`; }
  if (endMs != null) { wf += ` AND t < ${intOf(endMs)}`; wwf += ` AND w.t < ${intOf(endMs)}`; }
  return render("bas_vs_web_oat", {
    pairs: inline([["equipment_id", "TEXT"], ["bas_key", "TEXT"], ["web_key", "TEXT"], ["max_age_ms", "INTEGER"]], pairs),
    ts_ms: TS_MS[engine],
    site_id: quote(siteId),
    window_filter: wf,
    web_window_filter: wwf,
    band: pyRepr(band),
  });
}

// ---------------------------------------------------------------- the core tables, in-process

/**
 * An in-process database with fdd.point + fdd.input_sample (a view over fdd.sample_store). samples: [[pointKey, tsMs,
 * value]] (SI, UTC ms). Returns { engine, query(sql) -> rows, close() }. SQLite stores integer ms; PGlite timestamptz.
 */
async function openCore(engine, points, samples, { siteId = "local" } = {}) {
  checkEngine(engine === "pglite" ? "postgres" : engine);
  if (engine === "sqlite") {
    const { loadSqlJs } = require("./engines.js");
    const SQL = await loadSqlJs();
    const db = new SQL.Database();
    db.run("ATTACH DATABASE ':memory:' AS fdd");
    db.run("CREATE TABLE fdd.point (site_id TEXT NOT NULL, point_key TEXT NOT NULL, equipment_id TEXT, role TEXT, PRIMARY KEY (site_id, point_key))");
    db.run("CREATE TABLE fdd.sample_store (site_id TEXT NOT NULL, point_key TEXT NOT NULL, ts INTEGER NOT NULL, value REAL)");
    db.run("CREATE VIEW fdd.input_sample AS SELECT site_id, point_key, ts, value FROM sample_store WHERE value IS NOT NULL");
    db.run("BEGIN");
    const ps = db.prepare("INSERT INTO fdd.point VALUES (?, ?, ?, ?)");
    for (const p of points) ps.run([siteId, p.point_key, p.equipment_id == null ? null : String(p.equipment_id), p.role || null]);
    ps.free();
    const ss = db.prepare("INSERT INTO fdd.sample_store VALUES (?, ?, ?, ?)");
    for (const [k, t, v] of samples) ss.run([siteId, k, Math.trunc(t), v]);
    ss.free();
    db.run("COMMIT");
    return {
      engine: "sqlite",
      query(sql) {
        const res = db.exec(sql);
        if (!res.length) return [];
        const { columns, values } = res[0];
        return values.map((v) => Object.fromEntries(columns.map((c, i) => [c, v[i]])));
      },
      close() { db.close(); },
    };
  }
  const { PGlite } = await import("@electric-sql/pglite");
  const db = new PGlite();
  await db.waitReady;
  await db.exec("SET TIME ZONE 'UTC'; CREATE SCHEMA fdd;"
    + " CREATE TABLE fdd.point (site_id text NOT NULL, point_key text NOT NULL, equipment_id text, role text, PRIMARY KEY (site_id, point_key));"
    + " CREATE TABLE fdd.sample_store (site_id text NOT NULL, point_key text NOT NULL, ts timestamptz NOT NULL, value double precision);"
    + " CREATE VIEW fdd.input_sample AS SELECT site_id, point_key, ts, value FROM fdd.sample_store WHERE value IS NOT NULL;");
  for (let i = 0; i < points.length; i += 200) {
    const vals = points.slice(i, i + 200).map((p) => `(${quote(siteId)}, ${quote(p.point_key)}, ${p.equipment_id == null ? "NULL" : quote(p.equipment_id)}, ${p.role ? quote(p.role) : "NULL"})`);
    await db.exec(`INSERT INTO fdd.point VALUES ${vals.join(", ")}`);
  }
  for (let i = 0; i < samples.length; i += 500) {
    const vals = samples.slice(i, i + 500).map(([k, t, v]) =>
      `(${quote(siteId)}, ${quote(k)}, to_timestamp(${Math.trunc(t)} / 1000.0), ${v == null ? "NULL" : pyRepr(v)})`);
    await db.exec(`INSERT INTO fdd.sample_store VALUES ${vals.join(", ")}`);
  }
  await db.exec("ANALYZE fdd.sample_store; ANALYZE fdd.point;");
  return {
    engine: "postgres",
    async query(sql) {
      const res = await db.query(sql);
      return res.rows.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, typeof v === "bigint" ? Number(v)
        : typeof v === "string" && /^-?\d+(\.\d+)?(e[+-]?\d+)?$/i.test(v) && k !== "equipment_id" && k !== "signal" && k !== "motor_family" ? Number(v) : v])));
    },
    async close() { await db.close(); },
  };
}

module.exports = {
  TS_MS, MECH_OAT_BIN_EDGES_C, MECH_OAT_BIN_LABELS, ELAPSED_MAX_GAP_SECONDS, ECON_DIAG_DT_MIN_C, BAS_WEB_BAND_C,
  pyRepr, inline, render, renderRuntime, renderMechBins, renderEconomizer, renderBasWeb, openCore,
};
