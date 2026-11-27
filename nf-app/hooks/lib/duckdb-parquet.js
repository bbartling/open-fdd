"use strict";
/**
 * Parquet history for the NF plugin's Node DuckDB engine (@duckdb/node-api).
 *
 * Open-FDD does not run a Python DuckDB process. This module is the on-disk store the hook
 * reads and writes through the warm in-process connection. Layout (openfdd.parquet.v1):
 *
 *   <root>/samples/point_id=<id>/date=<YYYY-MM-DD>/part-<batch>.parquet
 *   <root>/checkpoint.json    per raw point id: min_ms, max_ms (written after the file rename)
 *   <root>/layout.json        { format, layout_version }
 *   <root>/tmp/               DuckDB spill, capped (not the history)
 *
 * Hive columns are point_id and date (UTC). File columns: ts_ms, value, value_text, site_id,
 * equipment_id, role, kind (history|sensor|weather), unit, batch_id. A point id that is not a
 * safe path segment is stored as p-<sha256 32 hex>. Dedupe key is (kind, point_id, ts_ms);
 * the greatest batch_id wins. Rules see TEMP views over read_parquet for the window only.
 * retentionDays 0 keeps every date; the default is 90.
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const FORMAT = "openfdd.parquet.v1";
const LAYOUT_VERSION = 1;
const PARQUET_TABLES = new Set(["history", "weather", "sensor_history"]);

function sqlStr(value) {
  return "'" + String(value).replace(/'/g, "''") + "'";
}

function sqlDouble(value) {
  if (value == null || Number.isNaN(value)) return "NULL";
  if (value === Infinity) return "CAST('Infinity' AS DOUBLE)";
  if (value === -Infinity) return "CAST('-Infinity' AS DOUBLE)";
  if (!Number.isFinite(value)) return "NULL";
  return String(value);
}

function pointIdFor(pointId) {
  const text = String(pointId);
  if (/^[A-Za-z0-9._:~-]{1,200}$/.test(text)) return text;
  return "p-" + crypto.createHash("sha256").update(text).digest("hex").slice(0, 32);
}

function utcDate(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function retentionOf(cfg) {
  if (cfg.retentionDays == null || cfg.retentionDays === "") return 90;
  const days = Number(cfg.retentionDays);
  if (!Number.isFinite(days) || days < 0) throw new Error("parquetRetentionDays must be a number >= 0 (0 keeps every date)");
  return days;
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) { return null; }
}

function writeJson(file, value) {
  const tmp = file + ".partial";
  fs.writeFileSync(tmp, JSON.stringify(value));
  fs.renameSync(tmp, file);
}

function checkpointPath(root) { return path.join(root, "checkpoint.json"); }

function loadCheckpoint(root) {
  const doc = readJson(checkpointPath(root));
  return doc && doc.points ? doc : { points: {} };
}

function saveCheckpoint(root, doc) { writeJson(checkpointPath(root), doc); }

function ensureLayout(root) {
  fs.mkdirSync(root, { recursive: true });
  const file = path.join(root, "layout.json");
  if (!fs.existsSync(file)) writeJson(file, { format: FORMAT, layout_version: LAYOUT_VERSION });
}

function parquetFiles(root) {
  const out = [];
  const samples = path.join(root, "samples");
  if (!fs.existsSync(samples)) return out;
  for (const point of fs.readdirSync(samples)) {
    const pointDir = path.join(samples, point);
    if (!point.startsWith("point_id=") || !fs.statSync(pointDir).isDirectory()) continue;
    for (const date of fs.readdirSync(pointDir)) {
      const dateDir = path.join(pointDir, date);
      if (!date.startsWith("date=") || !fs.statSync(dateDir).isDirectory()) continue;
      for (const name of fs.readdirSync(dateDir)) {
        if (name.endsWith(".parquet")) out.push(path.join(dateDir, name));
      }
    }
  }
  return out;
}

function enforceRetention(root, days) {
  if (!(days > 0)) return 0;
  const cutoff = new Date();
  cutoff.setUTCHours(0, 0, 0, 0);
  cutoff.setUTCDate(cutoff.getUTCDate() - days);
  const cutoffDay = cutoff.toISOString().slice(0, 10);
  const samples = path.join(root, "samples");
  if (!fs.existsSync(samples)) return 0;
  let removed = 0;
  for (const point of fs.readdirSync(samples)) {
    const pointDir = path.join(samples, point);
    if (!point.startsWith("point_id=") || !fs.statSync(pointDir).isDirectory()) continue;
    for (const date of fs.readdirSync(pointDir)) {
      const dateDir = path.join(pointDir, date);
      if (!date.startsWith("date=") || !fs.statSync(dateDir).isDirectory()) continue;
      if (date.slice(5) < cutoffDay) {
        fs.rmSync(dateDir, { recursive: true, force: true });
        removed++;
      }
    }
    if (fs.existsSync(pointDir) && fs.readdirSync(pointDir).length === 0) fs.rmdirSync(pointDir);
  }
  if (removed) {
    const doc = loadCheckpoint(root);
    for (const id of Object.keys(doc.points)) {
      const hive = "point_id=" + pointIdFor(id);
      const dir = path.join(samples, hive);
      if (!fs.existsSync(dir)) delete doc.points[id];
    }
    saveCheckpoint(root, doc);
  }
  return removed;
}

function pushSample(out, rawId, ts, raw, siteId, equipmentId, role, kind, unit) {
  if (raw === undefined || raw === null || (typeof raw === "number" && Number.isNaN(raw))) return;
  const tsMs = Number(ts);
  if (!Number.isFinite(tsMs)) return;
  const text = typeof raw === "string";
  out.push({
    raw_id: String(rawId),
    point_id: pointIdFor(rawId),
    date: utcDate(tsMs),
    ts_ms: tsMs,
    value: text ? null : Number(raw),
    value_text: text ? raw : null,
    site_id: siteId || "",
    equipment_id: equipmentId || "",
    role: String(role),
    kind,
    unit: unit || "",
  });
}

function samplesFromInput(input) {
  const out = [];
  const ids = input.pointIds || {};
  const site = input.siteId || "";
  for (const row of input.history || []) {
    const equipmentId = row.equipment_id || input.equipId || "";
    for (const [role, raw] of Object.entries(row)) {
      if (role === "equipment_id" || role === "ts" || role === "timestamp_utc") continue;
      pushSample(out, ids[role] || `${equipmentId}~${role}`, row.ts, raw, site, equipmentId, role, "history", "");
    }
  }
  for (const row of input.weather || []) {
    for (const [role, raw] of Object.entries(row)) {
      if (role === "ts" || role === "timestamp_utc") continue;
      pushSample(out, ids[role] || `weather~${role}`, row.ts, raw, site, "", role, "weather", "");
    }
  }
  for (const row of input.sensorHistory || []) {
    if (!row.series_id) continue;
    pushSample(out, row.series_id, row.ts, row.value, site, row.equipment_id || input.equipId || "", row.sensor_role || "", "sensor", row.unit || "");
  }
  return out;
}

let writeChain = Promise.resolve();
function locked(fn) {
  const run = writeChain.then(fn, fn);
  writeChain = run.then(() => {}, () => {});
  return run;
}

async function insertBatch(conn, rows, batchId) {
  await conn.run(`CREATE OR REPLACE TEMP TABLE openfdd_batch (
    point_id VARCHAR, date VARCHAR, ts_ms DOUBLE, value DOUBLE, value_text VARCHAR,
    site_id VARCHAR, equipment_id VARCHAR, role VARCHAR, kind VARCHAR, unit VARCHAR, batch_id VARCHAR)`);
  for (let i = 0; i < rows.length; i += 80) {
    const values = rows.slice(i, i + 80).map((r) => `(${[
      sqlStr(r.point_id), sqlStr(r.date), sqlDouble(r.ts_ms), sqlDouble(r.value),
      r.value_text == null ? "NULL" : sqlStr(r.value_text), sqlStr(r.site_id), sqlStr(r.equipment_id),
      sqlStr(r.role), sqlStr(r.kind), sqlStr(r.unit), sqlStr(batchId),
    ].join(", ")})`).join(", ");
    await conn.run(`INSERT INTO openfdd_batch VALUES ${values}`);
  }
}

async function flushSamples(conn, root, rows) {
  if (!rows.length) return 0;
  const batchId = `${Date.now().toString(36)}-${crypto.randomBytes(4).toString("hex")}`;
  await insertBatch(conn, rows, batchId);
  const seen = new Set();
  for (const row of rows) seen.add(row.point_id + "\0" + row.date);
  for (const key of seen) {
    const [pointId, date] = key.split("\0");
    const dir = path.join(root, "samples", `point_id=${pointId}`, `date=${date}`);
    fs.mkdirSync(dir, { recursive: true });
    const finalPath = path.join(dir, `part-${batchId}.parquet`);
    const partial = finalPath + ".partial";
    await conn.run(`COPY (
      SELECT CAST(ts_ms AS BIGINT) AS ts_ms, value, value_text, site_id, equipment_id, role, kind, unit, batch_id
      FROM openfdd_batch
      WHERE point_id = ${sqlStr(pointId)} AND date = ${sqlStr(date)}
    ) TO ${sqlStr(partial)} (FORMAT parquet, COMPRESSION zstd)`);
    fs.renameSync(partial, finalPath);
  }
  const doc = loadCheckpoint(root);
  for (const row of rows) {
    const rec = doc.points[row.raw_id] || { min_ms: row.ts_ms, max_ms: row.ts_ms };
    rec.min_ms = Math.min(rec.min_ms, row.ts_ms);
    rec.max_ms = Math.max(rec.max_ms, row.ts_ms);
    doc.points[row.raw_id] = rec;
  }
  saveCheckpoint(root, doc);
  return rows.length;
}

async function viewWindow(conn, root, fromMs, toMs) {
  const files = parquetFiles(root);
  if (!files.length) {
    await conn.run(`CREATE OR REPLACE TEMP VIEW openfdd_window AS
      SELECT * FROM (SELECT
        NULL::VARCHAR AS point_id, NULL::VARCHAR AS date, NULL::BIGINT AS ts_ms,
        NULL::DOUBLE AS value, NULL::VARCHAR AS value_text, NULL::VARCHAR AS site_id,
        NULL::VARCHAR AS equipment_id, NULL::VARCHAR AS role, NULL::VARCHAR AS kind,
        NULL::VARCHAR AS unit, NULL::VARCHAR AS batch_id) WHERE false`);
    return;
  }
  const d0 = utcDate(fromMs);
  const d1 = utcDate(toMs > fromMs ? toMs - 1 : fromMs);
  const glob = path.join(root, "samples", "**", "*.parquet");
  await conn.run(`CREATE OR REPLACE TEMP VIEW openfdd_window AS
    SELECT point_id, date, ts_ms, value, value_text, site_id, equipment_id, role, kind, unit, batch_id
    FROM (
      SELECT *, row_number() OVER (PARTITION BY kind, point_id, ts_ms ORDER BY batch_id DESC) AS rn
      FROM read_parquet(${sqlStr(glob)}, hive_partitioning = true, union_by_name = true)
      WHERE CAST(date AS VARCHAR) >= ${sqlStr(d0)} AND CAST(date AS VARCHAR) <= ${sqlStr(d1)}
    ) q
    WHERE rn = 1 AND ts_ms >= ${Math.trunc(fromMs)} AND ts_ms < ${Math.trunc(toMs)}`);
}

async function viewHistory(conn, columns, equipmentIds, quoteId) {
  const roles = columns.filter((c) => c.name !== "equipment_id" && c.name !== "timestamp_utc");
  const aggs = roles.map((col) => {
    const src = col.type === "text" ? "value_text" : "value";
    return `max(CASE WHEN role = ${sqlStr(col.name)} THEN ${src} END) AS ${quoteId(col.name)}`;
  });
  const where = equipmentIds.length
    ? `kind = 'history' AND equipment_id IN (${equipmentIds.map(sqlStr).join(", ")})`
    : "kind = 'history' AND false";
  await conn.run(`CREATE OR REPLACE TEMP VIEW history AS
    SELECT equipment_id, CAST(to_timestamp(ts_ms / 1000.0) AS TIMESTAMPTZ) AS timestamp_utc${aggs.length ? ",\n" + aggs.join(",\n") : ""}
    FROM openfdd_window WHERE ${where}
    GROUP BY equipment_id, ts_ms`);
}

async function viewWeather(conn, columns, quoteId) {
  const roles = columns.filter((c) => c.name !== "timestamp_utc").map((c) => c.name);
  const names = roles.length ? roles : ["oa_t", "web_oa_t", "web_oa_dp"];
  const aggs = names.map((name) => `max(CASE WHEN role = ${sqlStr(name)} THEN value END) AS ${quoteId(name)}`);
  await conn.run(`CREATE OR REPLACE TEMP VIEW weather AS
    SELECT CAST(to_timestamp(ts_ms / 1000.0) AS TIMESTAMPTZ) AS timestamp_utc, ${aggs.join(", ")}
    FROM openfdd_window WHERE kind = 'weather'
    GROUP BY ts_ms`);
}

async function viewSensor(conn, equipmentIds) {
  const where = equipmentIds.length
    ? `kind = 'sensor' AND equipment_id IN (${equipmentIds.map(sqlStr).join(", ")})`
    : "kind = 'sensor' AND false";
  await conn.run(`CREATE OR REPLACE TEMP VIEW sensor_history AS
    SELECT equipment_id, point_id AS series_id, role AS sensor_role, unit,
           CAST(to_timestamp(ts_ms / 1000.0) AS TIMESTAMPTZ) AS timestamp_utc, value
    FROM openfdd_window WHERE ${where}`);
}

async function scratch(conn, api, name, spec, rows, helpers) {
  const { quoteId, cellValue, DUCK_TYPE } = helpers;
  await conn.run(`CREATE OR REPLACE TEMP TABLE ${quoteId(name)} (${spec.map((c) => `${quoteId(c.name)} ${DUCK_TYPE[c.type]}`).join(", ")})`);
  if (!rows.length) return;
  const app = await conn.createAppender(name, "main", "temp");
  try {
    for (const row of rows) {
      for (const col of spec) {
        const value = cellValue(row, col);
        if (value === null) app.appendNull();
        else if (col.type === "timestamp") app.appendTimestampTZ(new api.DuckDBTimestampTZValue(BigInt(Math.round(Number(value) * 1000))));
        else if (col.type === "text") app.appendVarchar(value);
        else app.appendDouble(value);
      }
      app.endRow();
    }
    app.flushSync();
  } finally { app.closeSync(); }
}

async function scalar(conn, sql) {
  const rows = (await conn.runAndReadAll(sql)).getRowObjectsJS();
  const value = rows[0] && Object.values(rows[0])[0];
  return typeof value === "bigint" ? Number(value) : Number(value || 0);
}

/**
 * Append this run's samples, then build the window views and the small scratch tables.
 * Returns history rows plus sensor rows visible in the window (0 when both are empty).
 */
async function loadWindow(conn, api, pack, input, cfg, helpers) {
  const root = String(cfg.parquetDir);
  const days = retentionOf(cfg);
  const samples = samplesFromInput(input);
  await locked(async () => {
    ensureLayout(root);
    enforceRetention(root, days);
    await flushSamples(conn, root, samples);
  });
  const fromMs = Number(input.window && input.window.from);
  const toMs = Number(input.window && input.window.to);
  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs)) throw new Error("duckdb parquet load needs input.window {from, to} epoch ms");
  await viewWindow(conn, root, fromMs, toMs);
  const cols = helpers.tableColumns(pack, input);
  const equipmentIds = [];
  const seenEquip = new Set();
  for (const row of input.history || []) {
    const id = row.equipment_id || input.equipId;
    if (id && !seenEquip.has(id)) { seenEquip.add(id); equipmentIds.push(String(id)); }
  }
  if (!equipmentIds.length && input.equipId) equipmentIds.push(String(input.equipId));
  await viewHistory(conn, cols.history || [], equipmentIds, helpers.quoteId);
  await viewWeather(conn, cols.weather || [], helpers.quoteId);
  await viewSensor(conn, equipmentIds);
  for (const [table, spec] of Object.entries(cols)) {
    if (PARQUET_TABLES.has(table)) continue;
    await scratch(conn, api, table, spec, input[helpers.TABLE_INPUT_KEY[table]] || [], helpers);
  }
  const historyRows = await scalar(conn, "SELECT count(*) FROM history");
  const sensorRows = await scalar(conn, "SELECT count(*) FROM sensor_history");
  return historyRows + sensorRows;
}

function coverage(root, pointIds) {
  const points = loadCheckpoint(root).points;
  const out = {};
  for (const id of pointIds || []) {
    const rec = points[String(id)];
    out[String(id)] = rec ? { min_ms: Number(rec.min_ms), max_ms: Number(rec.max_ms) } : null;
  }
  return out;
}

function epochMs(value) {
  if (value == null) return null;
  if (value instanceof Date) return value.getTime();
  if (typeof value === "number") return value > 1e12 ? value : value * 1000;
  if (typeof value === "bigint") return Number(value) / 1000;
  if (typeof value === "object" && value.micros != null) return Number(value.micros) / 1000;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

async function windowHistory(conn, equipmentId, duckRows) {
  const rows = duckRows(await conn.runAndReadAll(`SELECT * FROM history WHERE equipment_id = ${sqlStr(equipmentId)}`));
  return rows.map((row) => ({ ...row, ts: epochMs(row.timestamp_utc) }));
}

async function explain(conn, sql) {
  const reader = await conn.runAndReadAll("EXPLAIN " + (sql || "SELECT count(*) FROM history"));
  return reader.getRowObjectsJS().map((row) => Object.values(row).join(" ")).join("\n");
}

module.exports = { loadWindow, coverage, windowHistory, explain, FORMAT, pointIdFor, parquetFiles };
