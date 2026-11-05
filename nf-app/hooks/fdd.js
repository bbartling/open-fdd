// Open-FDD rule runner (ADR-014 slice 3). Scheduled NF hook, no point bindings.
//
// Each run, for every Haystack equip in NF's model layer:
//   1. bind rule roles to the equip's points (static/fdd.js — the exact code the FDD tab runs)
//   2. read the bound points' history from NF, resampled server side to the pack's grid
//      (GET /api/v1/point/data …&window=300s&method=AVERAGE) for the trailing window
//   3. run every runnable rule of the SQL pack (sql/fdd → rules/pack-*.json) in an
//      embedded engine: SQLite-WASM on small edges, PGlite (real Postgres) on big ones
//   4. write one result point per (equip, rule): automation layer (history) + model layer
//      (Haystack tags fault/ruleRef/equipRef/siteRef), value = fault % of covered time
//      (metric rules: their first output), trended every run.
//
// Nothing site-specific: sites, equips, points and units all come from NF.
// config (hook settings, all optional):
//   engine        "auto" | "sqlite" | "pglite"   (auto: pglite when NF reports ≥ 3.5 GiB RAM)
//   windowHours   trailing window per run (default 24)
//   equips        list of equip ids to limit a run to (default: every equip)
//   dryRun        true → compute and log, write nothing
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

const APP_ID = 'open-fdd';
const STATIC = path.join(__dirname, '..', 'static');
const RULES = path.join(__dirname, '..', 'rules');
const PAGE = 500;
const PGLITE_MIN_BYTES = 3.5 * 1024 ** 3;

// ---- shared code with the UI ------------------------------------------------------
/** model.js + fdd.js run unchanged in a sandbox: one binding implementation for UI and hook. */
function loadShared() {
  const ctx = vm.createContext({ console });
  for (const f of ['model.js', 'fdd.js']) {
    vm.runInContext(fs.readFileSync(path.join(STATIC, f), 'utf8'), ctx, { filename: f });
  }
  const get = (n) => vm.runInContext(n, ctx);
  return {
    toPoint: get('toPoint'), idOf: get('idOf'), has: get('has'), equipRules: get('equipRules'),
    ENTITY_TYPES: get('ENTITY_TYPES'),
    catalog: JSON.parse(fs.readFileSync(path.join(STATIC, 'fdd-catalog.json'), 'utf8')),
  };
}

// pglite runs the Postgres pack as written; sqlite runs the translated one.
const PACK_FILE = { sqlite: 'pack-sqlite.json', pglite: 'pack-postgres.json' };
const loadPack = (kind) => JSON.parse(fs.readFileSync(path.join(RULES, PACK_FILE[kind]), 'utf8'));

// ---- NF reads -----------------------------------------------------------------------
const errText = (e) => (e && (e.message || (e.response && JSON.stringify(e.response.data)))) || String(e);

async function queryAll(http, body) {
  const out = [];
  let pageToken = '';
  do {
    const { data } = await http.post('/api/v1/point/query', { pageSize: PAGE, ...body, ...(pageToken && { pageToken }) });
    out.push(...((data && data.points) || []));
    pageToken = (data && data.nextPageToken) || '';
  } while (pageToken);
  return out;
}

async function loadModel(http, shared) {
  const recs = await queryAll(http, { layer: 'model' });
  const of = (t) => recs.filter((r) => r.pointType === t);
  const model = { sites: of('SITE'), equips: of('EQUIPMENT'), devices: of('DEVICE'), points: [] };
  for (const s of model.sites) {
    const pts = await queryAll(http, { layer: 'default', structuredQuery: { field: { property: 'siteRef', text: shared.idOf(s) } } });
    model.points.push(...pts.filter((r) => !shared.ENTITY_TYPES.includes(r.pointType)).map(shared.toPoint));
  }
  return model;
}

const scalar = (v) => {
  if (!v) return null;
  for (const k of ['double', 'real', 'unsigned', 'signed', 'enumerated']) if (v[k] != null) return Number(v[k]);
  if (v.boolean != null) return v.boolean === true || v.boolean === 'true' ? 1 : 0;
  return null;
};

/** {uuid: Map(bucketMs -> value)} on the pack grid, NF resamples (AVERAGE per window). */
async function fetchHistory(http, uuids, fromMs, toMs, stepSec) {
  const out = Object.fromEntries(uuids.map((u) => [u, new Map()]));
  for (let i = 0; i < uuids.length; i += 20) {
    const chunk = uuids.slice(i, i + 20);
    const qs = chunk.map((u) => 'uuids=' + encodeURIComponent(u)).join('&')
      + `&from=${new Date(fromMs).toISOString()}&to=${new Date(toMs).toISOString()}&window=${stepSec}s&method=AVERAGE`;
    const { data } = await http.get('/api/v1/point/data?' + qs);
    for (const series of (data && data.data) || []) {
      const m = out[series.uuid];
      if (!m) continue;
      for (const s of series.values || []) {
        const v = scalar(s);
        if (v == null || !Number.isFinite(v) || !s.ts) continue;
        const t = Date.parse(String(s.ts).replace(/(\.\d{3})\d+/, '$1'));
        m.set(Math.floor(t / (stepSec * 1e3)) * stepSec * 1e3, v);
      }
    }
  }
  return out;
}

// ---- rule inputs ----------------------------------------------------------------------
/** The point that feeds each bound role of the runnable rules (best match = first). */
function roleInputs(rows) {
  const roles = {};
  for (const r of rows) for (const role of [...r.required, ...r.optional]) {
    const p = r.bound[role] && r.bound[role][0];
    if (p && !roles[role]) roles[role] = p;
  }
  return roles;
}

/** Engine input for one equip: history on the grid, weather, unit catalog for the SV rules. */
function buildInput({ equipId, siteId, roles, hist, grid, pack }) {
  const contract = pack.contract.history.filter((c) => c.name !== 'equipment_id' && c.name !== 'timestamp_utc');
  const history = [];
  for (const ts of grid) {
    const row = { equipment_id: equipId, ts };
    let any = false;
    for (const [role, p] of Object.entries(roles)) {
      const v = hist[p.uuid].get(ts);
      if (v != null) { row[role] = v; any = true; }
    }
    if (any) history.push(row);          // a timestamp with no data at all is a gap, not zeros
  }
  const weather = [];
  for (const ts of grid) {
    const w = { ts };
    let any = false;
    for (const role of ['oa_t', 'web_oa_t', 'web_oa_dp']) {
      const p = roles[role];
      const v = p && hist[p.uuid].get(ts);
      if (v != null) { w[role] = v; any = true; }
    }
    if (any) weather.push(w);
  }
  return {
    historyColumns: contract.map((c) => ({ name: c.name, type: c.type })),
    history,
    weather,
    authorizedSeries: Object.entries(roles).map(([role, p]) => ({ site_id: siteId, equipment_id: equipId, role, unit: p.units || '' })),
    equipment: [{ building_id: siteId, equipment_id: equipId }],
  };
}

// ---- outputs ------------------------------------------------------------------------
/** Deterministic RFC 4122 v5-style uuid from a name (stable across runs and restarts). */
function nameUuid(name) {
  const h = crypto.createHash('sha1').update(`${APP_ID}:${name}`).digest();
  h[6] = (h[6] & 0x0f) | 0x50;
  h[8] = (h[8] & 0x3f) | 0x80;
  const x = h.subarray(0, 16).toString('hex');
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20)}`;
}

const FAULT_COLS = ['fault_pct', 'fault_hours'];

/** The number a result point trends: fault % of covered time, else the rule's first metric. */
function resultValue(packRule, row) {
  if (row.fault_pct != null) return { value: Number(row.fault_pct), unit: '%', fault: true };
  if (row.fault_hours != null) return { value: Number(row.fault_hours), unit: 'h', fault: true };
  const col = ((packRule && packRule.output_columns) || Object.keys(row)).find((c) => c !== 'equipment_id' && typeof row[c] === 'number');
  return col ? { value: row[col], unit: '', fault: false, column: col } : null;
}

function resultRecords({ equipRec, siteId, rule, out, shared, windowHours }) {
  const equipId = shared.idOf(equipRec);
  const uuid = nameUuid(`${equipId}:${rule.id}`);
  const dis = `${(equipRec.attrs || {}).dis || equipRec.name} ${rule.id}`;
  const markers = ['point', 'his', out.fault ? 'fault' : 'metric', 'fdd'];
  return [
    { uuid, name: `${equipId}/${rule.id}`, layer: 'automation', pointType: 'POINT', attrs: {
      application_id: APP_ID, type: 'fdd-result', label: rule.id, group_key: equipId,
      description: rule.description || rule.id, units: out.unit } },
    { uuid, name: `${equipId}/${rule.id}`, layer: 'model', attrs: {
      dis, markers: markers.join(','), kind: 'Number', unit: out.unit,
      siteRef: siteId, equipRef: equipId, ruleRef: rule.id,
      fddWindowHours: String(windowHours), fddOutput: out.column || (out.unit === '%' ? 'fault_pct' : 'fault_hours') } },
  ];
}

// ---- run ----------------------------------------------------------------------------
async function pickEngine(http, wanted) {
  if (wanted === 'sqlite' || wanted === 'pglite') return wanted;
  try {
    const { data } = await http.get('/api/v1/platform/info');
    const total = Math.max(0, ...((data && data.resources) || []).map((r) => Number((r.memory || {}).totalBytes) || 0));
    return total >= PGLITE_MIN_BYTES ? 'pglite' : 'sqlite';
  } catch (e) {
    return 'sqlite';
  }
}

async function runFdd({ sdk, config = {}, createEngine, pack: packIn, now = Date.now() }) {
  createEngine = createEngine || require('./lib/engines.js').createEngine;
  const http = sdk.http;
  const log = (m) => (sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const shared = loadShared();
  const kind = await pickEngine(http, config.engine);
  const pack = packIn || loadPack(kind);
  const step = pack.poll_seconds;
  const windowHours = Number(config.windowHours) > 0 ? Number(config.windowHours) : 24;
  const to = Math.floor(now / (step * 1e3)) * step * 1e3;
  const from = to - windowHours * 3600e3;
  const grid = [];
  for (let t = from; t < to; t += step * 1e3) grid.push(t);

  const model = await loadModel(http, shared);
  const only = Array.isArray(config.equips) && config.equips.length ? new Set(config.equips) : null;
  const summary = { engine: kind, equips: 0, rules: 0, errors: 0, written: 0, results: [] };
  const engine = await createEngine({ kind, pack });
  try {
    for (const equipRec of model.equips) {
      const equipId = shared.idOf(equipRec);
      if (only && !only.has(equipId)) continue;
      const siteId = (equipRec.attrs || {}).siteRef || '';
      const runnable = shared.equipRules(equipRec, model, shared.catalog)
        .filter((r) => r.runnable && pack.rules[r.rule.id]);
      if (!runnable.length) continue;
      const roles = roleInputs(runnable);
      const uuids = [...new Set(Object.values(roles).map((p) => p.uuid))];
      const hist = await fetchHistory(http, uuids, from, to, step);
      const input = buildInput({ equipId, siteId, roles, hist, grid, pack });
      if (!input.history.length) { log(`${equipId}: no history in the last ${windowHours} h, skipped`); continue; }
      await engine.load(input);
      summary.equips++;
      const records = [];
      const values = [];
      for (const r of runnable) {
        let rows;
        try {
          rows = await engine.query(r.rule.id);
        } catch (e) {
          summary.errors++;
          log(`${equipId} ${r.rule.id}: ${errText(e)}`);
          continue;
        }
        summary.rules++;
        const row = rows.find((x) => x.equipment_id === equipId) || rows[0];
        const out = row && resultValue(pack.rules[r.rule.id], row);
        if (!out || !Number.isFinite(out.value)) continue;
        summary.results.push({ equip: equipId, rule: r.rule.id, ...out });
        records.push(...resultRecords({ equipRec, siteId, rule: r.rule, out, shared, windowHours }));
        values.push({ uuid: nameUuid(`${equipId}:${r.rule.id}`), value: out.value });
      }
      if (config.dryRun || !records.length) continue;
      await http.post('/api/v1/point/points', { points: records });
      const ts = new Date(to).toISOString();
      for (const v of values) {
        await http.post('/api/v1/point/data', { uuid: v.uuid, values: [{ ts, real: v.value }] });
        summary.written++;
      }
    }
  } finally {
    await engine.close();
    // Small edges: hand freed engine memory back now rather than at the next GC.
    if (typeof global.gc === 'function') global.gc();
  }
  const faults = summary.results.filter((r) => r.fault && r.value > 0);
  log(`open-fdd ${kind}: ${summary.equips} equips, ${summary.rules} rule runs, ${summary.errors} errors, `
    + `${faults.length} with fault time, ${summary.written} values written (window ${windowHours} h)`);
  return summary;
}

module.exports = async ({ sdk, config }) => {
  await runFdd({ sdk, config: config || {} });
};
module.exports.runFdd = runFdd;
module.exports.nameUuid = nameUuid;
module.exports.buildInput = buildInput;
module.exports.resultValue = resultValue;
