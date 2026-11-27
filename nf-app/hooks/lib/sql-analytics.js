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
const TS_MS = { sqlite: "s.ts", postgres: "CAST(EXTRACT(EPOCH FROM s.ts) * 1000 AS BIGINT)", duckdb: "CAST(EXTRACT(EPOCH FROM s.ts) * 1000 AS BIGINT)" };
/** pglite is the Postgres test engine. duckdb runs the same SQL text. */
const dialectOf = (engine) => (engine === "pglite" || engine === "duckdb" ? "postgres" : engine);
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

/** sql_economizer.render_economizer_points_sql (same roles and checks as the metrics query, no gap limit). */
function renderEconomizerPoints(engine, roles, { siteId = "local", dtMinC = ECON_DIAG_DT_MIN_C, startMs = null, endMs = null } = {}) {
  checkEngine(engine);
  for (const [, role] of roles) if (!["fan", "oat", "rat", "mat", "damper"].includes(role)) throw new Error(`unknown economizer role ${role}`);
  const dt = Number(dtMinC);
  if (!Number.isFinite(dt) || dt < 0) throw new Error("dt_min_c must be a non-negative number");
  return render("economizer_points", {
    roles: inline([["equipment_id", "TEXT"], ["role", "TEXT"], ["point_key", "TEXT"]], roles),
    ts_ms: TS_MS[engine],
    site_id: quote(siteId),
    window_filter: windowFilter(startMs, endMs),
    dt_min: pyRepr(dt),
  });
}

/** sql_bas_web.render_bas_web_sql (pairs = [[equipment_id, bas_key, web_key, max_age_ms]]). */
function renderBasWeb(engine, pairs, opts = {}) {
  return renderBasWebTemplate("bas_vs_web_oat", engine, pairs, opts);
}

/** sql_bas_web.render_bas_web_points_sql: the paired samples bas_vs_web_oat.sql aggregates (same arguments). */
function renderBasWebPoints(engine, pairs, opts = {}) {
  return renderBasWebTemplate("bas_vs_web_points", engine, pairs, opts);
}

function renderBasWebTemplate(name, engine, pairs, { siteId = "local", bandC = BAS_WEB_BAND_C, startMs = null, endMs = null } = {}) {
  checkEngine(engine);
  for (const p of pairs) if (!(Number(p[3]) >= 0)) throw new Error("max_age_ms must be >= 0");
  const band = Number(bandC);
  if (!Number.isFinite(band) || band < 0) throw new Error("band_c must be a non-negative number");
  if (startMs != null && endMs != null && Number(endMs) <= Number(startMs)) throw new Error("end_ms must be after start_ms");
  let wf = "", wwf = "";
  if (startMs != null) { wf += ` AND t >= ${intOf(startMs)}`; wwf += ` AND w.t >= ${intOf(startMs)} - w.max_age_ms`; }
  if (endMs != null) { wf += ` AND t < ${intOf(endMs)}`; wwf += ` AND w.t < ${intOf(endMs)}`; }
  return render(name, {
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
async function openDuckCore(points, samples, siteId) {
  let api;
  try { api = await import("@duckdb/node-api"); }
  catch (e) {
    const err = new Error(`DuckDB engine failed to load: ${e && e.message ? e.message : e}. Reinstall the DuckDB build or switch to the Timescale build.`);
    /** @type {any} */ (err).code = "OPENFDD_DUCKDB_UNAVAILABLE";
    throw err;
  }
  const instance = await api.DuckDBInstance.create(":memory:", {
    autoinstall_known_extensions: "false", autoload_known_extensions: "false", temp_directory: "",
  });
  const conn = await instance.connect();
  const num = (v) => (typeof v === "bigint" ? Number(v) : typeof v === "object" && v && typeof v.toDouble === "function" ? v.toDouble() : v);
  await conn.run("SET TimeZone = 'UTC'");
  await conn.run("SET threads = 1");   // one thread: AVG stays the same number on every run
  await conn.run("CREATE SCHEMA fdd");
  await conn.run("CREATE TABLE fdd.point (site_id VARCHAR NOT NULL, point_key VARCHAR NOT NULL, equipment_id VARCHAR, role VARCHAR, PRIMARY KEY (site_id, point_key))");
  await conn.run("CREATE TABLE fdd.sample_store (site_id VARCHAR NOT NULL, point_key VARCHAR NOT NULL, ts TIMESTAMPTZ NOT NULL, value DOUBLE)");
  await conn.run("CREATE VIEW fdd.input_sample AS SELECT site_id, point_key, ts, value FROM fdd.sample_store WHERE value IS NOT NULL");
  for (let i = 0; i < points.length; i += 200) {
    const vals = points.slice(i, i + 200).map((p) => `(${quote(siteId)}, ${quote(p.point_key)}, ${p.equipment_id == null ? "NULL" : quote(p.equipment_id)}, ${p.role ? quote(p.role) : "NULL"})`);
    await conn.run(`INSERT INTO fdd.point VALUES ${vals.join(", ")}`);
  }
  for (let i = 0; i < samples.length; i += 500) {
    const vals = samples.slice(i, i + 500).map(([k, t, v]) =>
      `(${quote(siteId)}, ${quote(k)}, to_timestamp(${Math.trunc(t)} / 1000.0), ${v == null ? "NULL" : pyRepr(v)})`);
    await conn.run(`INSERT INTO fdd.sample_store VALUES ${vals.join(", ")}`);
  }
  return {
    engine: "duckdb",
    async query(sql) {
      const rows = (await conn.runAndReadAll(sql)).getRowObjectsJS();
      return rows.map((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, num(v)])));
    },
    close() { conn.closeSync(); instance.closeSync(); },
  };
}

async function openCore(engine, points, samples, { siteId = "local" } = {}) {
  checkEngine(dialectOf(engine));
  if (engine === "duckdb") return openDuckCore(points, samples, siteId);
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

// ---------------------------------------------------------------- grid adapters (the RCx data entry points)

/**
 * Weekly motor run hours for the RCx weekly view and the analytics hook, from an aligned grid g = { t: [ms], cols }.
 * specs: [{ key, motor: colName, oat: colName|null, weekOf: (ms) -> weekStartMs|null, occ: (ms) -> bool|null }].
 * Returns Map(key -> Map(weekStartMs -> { hours, inHours, afterHours, oat, n, partial })), the shape the views read.
 * The weeks are the site's own (weekOf, e.g. local Mondays): every distinct weekOf(t) of the grid is a boundary. The
 * occupancy is evaluated at each sample time (the SQL books an interval by the state at its start). A week with no
 * running time has no entry (the SQL, like pandas, emits weeks with ON time only).
 */
async function runtimeFromGrid(engine, g, specs) {
  const points = [], samples = [], oats = [], weeks = [], occupied = [];
  const t = g.t;
  specs = require("../../static/sql-analytics-client.js").plainRuntimeSpecs(t, specs);
  specs.forEach((s, i) => {
    const eq = `e${i}`;
    const motor = g.cols[s.motor] || [];
    points.push({ point_key: `${eq}/m`, equipment_id: eq, role: "fan_status" });
    for (let j = 0; j < t.length; j++) if (motor[j] != null && Number.isFinite(Number(motor[j]))) samples.push([`${eq}/m`, t[j], Number(motor[j])]);
    if (s.oat && g.cols[s.oat]) {
      points.push({ point_key: `${eq}/o`, equipment_id: eq, role: "outside_air_temp" });
      const o = g.cols[s.oat];
      for (let j = 0; j < t.length; j++) if (o[j] != null && Number.isFinite(Number(o[j]))) samples.push([`${eq}/o`, t[j], Number(o[j])]);
      oats.push([eq, `${eq}/o`]);
    }
    if (s.weeks) for (const k of s.weeks) weeks.push([eq, k]);
    if (s.occupied) for (const [a, b] of s.occupied) occupied.push([eq, a, b]);
  });
  const anyOcc = specs.some((s) => s.occupied);
  const db = await openCore(engine, points, samples);
  try {
    const rows = await db.query(renderRuntime(dialectOf(engine),
      { oats, weeks, occupied: anyOcc ? occupied : null }));
    const out = new Map(specs.map((s) => [s.key, new Map()]));
    for (const r of rows) {
      const spec = specs[Number(String(r.equipment_id).slice(1))];
      const hours = Number(r.run_hours), inH = r.in_hours == null ? null : Number(r.in_hours);
      out.get(spec.key).set(Number(r.week_start_ms), {
        hours, inHours: spec.occupied ? inH : null, afterHours: spec.occupied ? hours - inH : null,
        oat: r.avg_oat_c == null ? null : Number(r.avg_oat_c), n: Number(r.n_samples), partial: !!Number(r.partial_week),
      });
    }
    return out;
  } finally {
    await db.close();
  }
}

/**
 * Mechanical-cooling hours per SI OAT bin from an aligned grid, one proof column per equip (a one-tier ladder).
 * specs: [{ key, proof: colName, oat: colName }] -> Map(key -> [hours per bin, MECH_OAT_BIN_LABELS order]).
 */
async function mechFromGrid(engine, g, specs) {
  const points = [], samples = [], plan = { candidates: [], gates: [], oats: [] };
  const t = g.t;
  specs.forEach((s, i) => {
    const eq = `e${i}`, proof = g.cols[s.proof] || [], oat = g.cols[s.oat] || [];
    points.push({ point_key: `${eq}/p`, equipment_id: eq, role: "proof" }, { point_key: `${eq}/o`, equipment_id: eq, role: "oat" });
    for (let j = 0; j < t.length; j++) {
      if (proof[j] != null && Number.isFinite(Number(proof[j]))) samples.push([`${eq}/p`, t[j], Number(proof[j])]);
      if (oat[j] != null && Number.isFinite(Number(oat[j]))) samples.push([`${eq}/o`, t[j], Number(oat[j])]);
    }
    plan.candidates.push([eq, 1, 0, `${eq}/p`, "on", null]);
    plan.oats.push([eq, `${eq}/o`]);
  });
  const db = await openCore(engine, points, samples);
  try {
    const rows = await db.query(renderMechBins(dialectOf(engine), plan));
    const out = new Map(specs.map((s) => [s.key, MECH_OAT_BIN_LABELS.map(() => 0)]));
    for (const r of rows) out.get(specs[Number(String(r.equipment_id).slice(1))].key)[Number(r.bin)] = Number(r.on_ms) / 3600000;
    return out;
  } finally {
    await db.close();
  }
}

/**
 * Economizer rows (the chart points) and the per-equip metrics from one equip's aligned grid
 * g = { t, cols: { oa_t, rat, mat, fan, sat, damper } }. Every value is computed by economizer_points.sql /
 * economizer_metrics.sql; sat only passes through for display. Rows keep the view's shape.
 */
async function econFromGrid(engine, g) {
  const t = g.t, roleOf = { fan: "fan", oa_t: "oat", rat: "rat", mat: "mat", damper: "damper" };
  const points = [], samples = [], roles = [];
  for (const [col, role] of Object.entries(roleOf)) {
    const v = g.cols[col];
    if (!v) continue;
    points.push({ point_key: col, equipment_id: "E", role });
    roles.push(["E", role, col]);
    for (let j = 0; j < t.length; j++) if (v[j] != null && Number.isFinite(Number(v[j]))) samples.push([col, t[j], Number(v[j])]);
  }
  if (!roles.some((r) => r[1] === "fan") || !roles.some((r) => r[1] === "oat") || !roles.some((r) => r[1] === "rat")) {
    return { rows: [], summary: { n: 0, nIdent: 0, medianResid: null, maeResid: null } };
  }
  const eng = dialectOf(engine);
  const db = await openCore(engine, points, samples);
  try {
    const sat = new Map((g.cols.sat || []).map((v, j) => [t[j], v]));
    const pts = await db.query(renderEconomizerPoints(eng, roles));
    const rows = pts.filter((r) => r.mat != null).map((r) => {
      const ts = Number(r.t), resid = r.mat_resid == null ? null : Number(r.mat_resid);
      return { t: ts, oa: Number(r.oat), rat: Number(r.rat), mat: Number(r.mat), sat: sat.get(ts) ?? null,
        damperPct: r.damper_pct == null ? null : Number(r.damper_pct), dOR: Number(r.d_or), dMR: Number(r.d_mr),
        ident: !!Number(r.identifiable), oaFrac: r.oa_frac_pct == null ? null : Number(r.oa_frac_pct),
        matPred: resid == null ? null : Number(r.mat) - resid, matResid: resid };
    });
    const m = (await db.query(renderEconomizer(eng, roles)))[0];
    const summary = m ? { n: Number(m.n_fan_on), nIdent: Number(m.n_identifiable),
      medianResid: m.median_resid == null ? null : Number(m.median_resid), maeResid: m.mae_resid == null ? null : Number(m.mae_resid) }
      : { n: 0, nIdent: 0, medianResid: null, maeResid: null };
    return { rows, summary };
  } finally {
    await db.close();
  }
}

/**
 * As-of age limit for the web reading, ms: max(1.5 x median web interval, 2 x median BAS interval), each over its
 * non-null samples (weather_resolver.default_web_max_age_seconds).
 */
function webMaxAgeMs(t, bas, web) {
  const medianStep = (v) => {
    const ts = t.filter((_, j) => v[j] != null && Number.isFinite(Number(v[j])));
    if (ts.length < 2) return 0;
    const d = ts.slice(1).map((x, j) => x - ts[j]).sort((a, b) => a - b), m = d.length >> 1;
    return d.length % 2 ? d[m] : (d[m - 1] + d[m]) / 2;
  };
  return Math.max(1.5 * medianStep(web), 2 * medianStep(bas));
}

/**
 * BAS vs web outdoor air from one aligned grid g = { t, cols: { bas, web } } (degC): the paired samples
 * (bas_vs_web_points.sql) and their statistics (bas_vs_web_oat.sql). Returns { rows: [{t, bas, web, d}], band,
 * stats: { n, bias, mae, maxAbs, withinBand } }. maxAgeMs overrides the as-of limit (default webMaxAgeMs).
 */
async function basFromGrid(engine, g, { bandC = BAS_WEB_BAND_C, maxAgeMs = null } = {}) {
  const t = g.t, empty = { rows: [], band: bandC, stats: { n: 0, bias: null, mae: null, maxAbs: null, withinBand: null } };
  const bas = g.cols.bas || [], web = g.cols.web || [];
  const samples = [];
  for (const [key, v] of [["bas", bas], ["web", web]]) {
    for (let j = 0; j < t.length; j++) if (v[j] != null && Number.isFinite(Number(v[j]))) samples.push([key, t[j], Number(v[j])]);
  }
  if (!samples.some((s) => s[0] === "bas") || !samples.some((s) => s[0] === "web")) return empty;
  const eng = dialectOf(engine);
  const pairs = [["E", "bas", "web", Math.floor(maxAgeMs == null ? webMaxAgeMs(t, bas, web) : maxAgeMs)]];
  const db = await openCore(engine, [{ point_key: "bas", equipment_id: "E", role: "oa_t" },
    { point_key: "web", equipment_id: null, role: "web_oa_t" }], samples);
  try {
    const rows = (await db.query(renderBasWebPoints(eng, pairs))).map((r) =>
      ({ t: Number(r.t), bas: Number(r.bas), web: Number(r.web), d: Number(r.d) }));
    const s = (await db.query(renderBasWeb(eng, pairs, { bandC })))[0];
    if (!s) return { ...empty, rows };
    const n = Number(s.n);
    return { rows, band: bandC, stats: { n, bias: Number(s.bias), mae: Number(s.mae), maxAbs: Number(s.max_abs),
      withinBand: Number(s.n_within) / n } };
  } finally {
    await db.close();
  }
}

module.exports = {
  runtimeFromGrid, mechFromGrid, econFromGrid, basFromGrid, webMaxAgeMs, renderBasWebPoints,
  TS_MS, MECH_OAT_BIN_EDGES_C, MECH_OAT_BIN_LABELS, ELAPSED_MAX_GAP_SECONDS, ECON_DIAG_DT_MIN_C, BAS_WEB_BAND_C,
  pyRepr, inline, render, renderRuntime, renderMechBins, renderEconomizer, renderEconomizerPoints, renderBasWeb, openCore,
};
