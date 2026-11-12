// Runs the Open-FDD SQL pack (nf-app/rules/pack-*.json) over a deterministic SI dataset on BOTH Postgres-capable
// engines that need no server (PGlite = real Postgres, sql.js = translated SQLite) and writes everything the
// pandas side needs to a JSON file.
//
//   node tests/parity/sql_run.mjs --equips 4 --days 3 --out out.json [--engines pglite,sqlite] [--rules FC1,FC2]
//   node tests/parity/sql_run.mjs --dataset ds.json --out out.json ...   (ds.json = open_fdd.parity Dataset.to_loader_json())
//
// Output: { meta, columns, history: {equip: {ts: [...], <col>: [...]}}, weather: [...], units: {role: unit},
//           results: {pglite: {rule: [rows]}, sqlite: {...}}, errors, timing: {...}, memory: {...} }
// Timing is wall-clock per engine (load + all rules); memory is process RSS peak sampled after each stage (MB).
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const { createEngine } = require(path.join(root, "nf-app/hooks/lib/engines.js"));
const { buildDataset } = require(path.join(root, "nf-app/tests/fixtures/synthetic_dataset.js"));

const arg = (name, dflt) => {
  const i = process.argv.indexOf("--" + name);
  return i > 0 ? process.argv[i + 1] : dflt;
};
const equips = Number(arg("equips", 4));
const days = Number(arg("days", 3));
const out = arg("out", "parity_sql.json");
const engines = arg("engines", "pglite,sqlite").split(",");
const only = arg("rules", "") ? new Set(arg("rules").split(",")) : null;
const noGaps = !process.argv.includes("--gaps");
const duplicateRole = arg("duplicate-role", "false") === "true";
const plantSensors = arg("plant-sensors", "false") === "true";

const datasetFile = arg("dataset", "");
// A Python-generated dataset (open_fdd.parity): the compact loader JSON carries `sensorSeries`; sensorHistory is
// expanded here from the history rows, exactly as synthetic_dataset.js does.
function loadDataset(file) {
  const d = JSON.parse(readFileSync(file, "utf8"));
  const byEquip = new Map();
  for (const row of d.history) { if (!byEquip.has(row.equipment_id)) byEquip.set(row.equipment_id, []); byEquip.get(row.equipment_id).push(row); }
  d.sensorHistory = [];
  for (const s of d.sensorSeries) {
    for (const row of byEquip.get(s.equipment_id) || []) {
      d.sensorHistory.push({ equipment_id: s.equipment_id, series_id: s.series_id, sensor_role: s.role, unit: s.unit, ts: row.ts, value: row[s.role] ?? null });
    }
  }
  delete d.sensorSeries;
  return d;
}

const readPack = (n) => JSON.parse(readFileSync(path.join(root, "nf-app/rules", n), "utf8"));
const PACK = { pglite: readPack("pack-postgres.json"), sqlite: readPack("pack-sqlite.json") };
// --rule-sql file.json: {rule_id: sql} replaces that rule's PGlite SQL (e.g. a render with overridden role limits)
if (arg("rule-sql", "")) {
  for (const [rid, sql] of Object.entries(JSON.parse(readFileSync(arg("rule-sql"), "utf8")))) PACK.pglite.rules[rid].sql = sql;
}
const mb = () => Math.round(process.memoryUsage().rss / 1048576);
let peak = mb();
const sample = () => { peak = Math.max(peak, mb()); };

const t0 = Date.now();
const input = datasetFile ? loadDataset(datasetFile) : buildDataset(PACK.pglite, { equipments: equips, days, stepSeconds: 300, gaps: !noGaps, duplicateRole, plantSensors });
const tGen = Date.now() - t0;
sample();

const results = {}, errors = {}, timing = { generate_ms: tGen }, memory = {};
for (const kind of engines) {
  const pack = PACK[kind];
  results[kind] = {};
  const ts = Date.now();
  const eng = await createEngine({ kind, pack });
  await eng.load(input);
  timing[`${kind}_load_ms`] = Date.now() - ts;
  sample();
  const tq = Date.now();
  for (const rid of Object.keys(pack.rules)) {
    if (only && !only.has(rid)) continue;
    try { results[kind][rid] = await eng.query(rid); } catch (e) { errors[`${kind} ${rid}`] = e.message; }
  }
  timing[`${kind}_rules_ms`] = Date.now() - tq;
  timing[`${kind}_total_ms`] = Date.now() - ts;
  sample();
  memory[`${kind}_rss_mb`] = mb();
  await eng.close();
}

// columnar history for pandas
const cols = input.historyColumns.map((c) => c.name);
const history = {};
for (const row of input.history) {
  const h = (history[row.equipment_id] ||= { ts: [] });
  h.ts.push(row.ts);
  for (const c of cols) (h[c] ||= []).push(row[c] === undefined ? null : row[c]);
}
const units = {};
for (const a of input.authorizedSeries) units[a.role] = a.unit;
writeFileSync(out, JSON.stringify({
  meta: { equips: input.equipment.length, days, step_seconds: 300, rows: input.history.length, columns: cols.length },
  columns: input.historyColumns, history, weather: input.weather, units, results, errors, timing,
  memory: { ...memory, rss_peak_mb: peak },
}));
console.log(`wrote ${out}: ${input.history.length} rows, ${Object.keys(errors).length} errors, peak RSS ${peak} MB, ` +
  Object.entries(timing).map(([k, v]) => `${k}=${v}`).join(" "));
