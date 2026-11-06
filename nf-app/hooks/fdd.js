// Open-FDD rule runner (ADR-014 slice 3). Scheduled NF hook, no point bindings.
//
// Each run, for every Haystack equip in NF's model layer:
//   1. bind rule roles to the equip's points (static/fdd.js — the exact code the FDD tab runs)
//   2. read the bound points' history from NF, resampled server side to the pack's grid
//      (GET /api/v1/point/data …&window=300s&method=AVERAGE) for the trailing window
//      (values are converted to SI by each point's unit first: units.js toSI; see siPlan)
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
//   bacnet        { enabled: true, firstInstance: 1000 } → fault count per equip as an AV on
//                 NF's BACnet server (off by default; see exportToBacnet)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');
// Units: FDD math is SI only. Every NF history value goes through toSI() before the rules see it.
const ofddUnits = require('../static/units.js');

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
const PACK_FILE = { sqlite: 'pack-sqlite.json', pglite: 'pack-postgres.json', timescale: 'pack-postgres.json' };
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

// ---- SI conversion --------------------------------------------------------------------
// Quantities whose unit must be known: guessing °F vs °C (or inH2O vs Pa) would silently change the physics.
const STRICT_QUANTITY = ['temperature', 'pressure', 'flow'];

/** Quantity a role carries, from its Haystack-style name (fdd-catalog roles). null = unitless/other. */
function roleQuantity(role, catalog) {
  const name = String(((catalog && catalog.roles && catalog.roles[role]) || {}).name || role);
  if (/request|count/.test(name)) return null;
  if (/temp|dewpoint|wetbulb/.test(name)) return 'temperature';
  if (/pressure/.test(name)) return 'pressure';
  if (/airflow|(^|-)flow($|-)/.test(name)) return 'flow';
  return null;
}

/**
 * Per bound role: how to bring the point's values to SI and which SI unit to declare.
 *   convert[role](v) -> SI value; unit[role] -> SI unit string; skipped = roles with no usable unit.
 * A known unit is converted (°F -> °C, inH2O -> Pa, cfm -> L/s ...). An unknown or empty unit leaves the
 * value as it is (statuses, commands, percent), except for temperature/pressure/flow roles: those are
 * skipped, logged once per point, never guessed.
 */
function siPlan(roles, catalog, log, warned) {
  const plan = { convert: {}, unit: {}, skipped: new Set() };
  for (const [role, p] of Object.entries(roles)) {
    const unit = p.units || '';
    const probe = ofddUnits.toSI(1, unit);
    const want = roleQuantity(role, catalog);
    if (probe) {
      if (want && probe.quantity !== want) { // e.g. a temperature role whose point says kPa: wrong binding, not ours to fix
        plan.skipped.add(role);
        if (log && warned && !warned.has(p.uuid)) { warned.add(p.uuid); log(`${p.name || p.uuid}: role ${role} is a ${want} but unit "${unit}" is a ${probe.quantity}, role skipped`); }
        continue;
      }
      plan.convert[role] = (v) => { const r = ofddUnits.toSI(v, unit); return r ? r.value : v; };
      plan.unit[role] = probe.unit;
    } else if (want && STRICT_QUANTITY.includes(want)) {
      plan.skipped.add(role);
      if (log && warned && !warned.has(p.uuid)) { warned.add(p.uuid); log(`${p.name || p.uuid}: role ${role} (${want}) has ${unit ? `unknown unit "${unit}"` : 'no unit'}, role skipped`); }
    } else {
      plan.unit[role] = unit;
    }
  }
  return plan;
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
function buildInput({ equipId, siteId, roles, hist, grid, pack, si }) {
  si = si || siPlan(roles, null);
  const conv = (role, v) => (si.convert[role] ? si.convert[role](v) : v);
  const contract = pack.contract.history.filter((c) => c.name !== 'equipment_id' && c.name !== 'timestamp_utc');
  const history = [];
  for (const ts of grid) {
    const row = { equipment_id: equipId, ts };
    let any = false;
    for (const [role, p] of Object.entries(roles)) {
      const v = hist[p.uuid].get(ts);
      if (v != null) { row[role] = conv(role, v); any = true; }
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
      if (v != null) { w[role] = conv(role, v); any = true; }
    }
    if (any) weather.push(w);
  }
  return {
    historyColumns: contract.map((c) => ({ name: c.name, type: c.type })),
    history,
    weather,
    authorizedSeries: Object.entries(roles).map(([role, p]) => ({ site_id: siteId, equipment_id: equipId, role, unit: si.unit[role] != null ? si.unit[role] : (p.units || '') })),
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
async function pickEngine(http, wanted, timescaleConfig) {
  // FULL edition: config.timescale set -> run the pack inside NF's TimescaleDB (engine "timescale", or "auto")
  if (wanted === 'timescale' || ((!wanted || wanted === 'auto') && timescaleConfig)) return 'timescale';
  if (wanted === 'sqlite' || wanted === 'pglite') return wanted;
  try {
    const { data } = await http.get('/api/v1/platform/info');
    const total = Math.max(0, ...((data && data.resources) || []).map((r) => Number((r.memory || {}).totalBytes) || 0));
    return total >= PGLITE_MIN_BYTES ? 'pglite' : 'sqlite';
  } catch (e) {
    return 'sqlite';
  }
}

/**
 * @typedef {{ engine?: string, windowHours?: number, equips?: string[], dryRun?: boolean,
 *   bacnet?: { enabled?: boolean, firstInstance?: number }, timescale?: object }} FddConfig
 * @param {{ sdk: any, config?: FddConfig, createEngine?: Function, pack?: any, now?: number }} args
 */
async function runFdd({ sdk, config = {}, createEngine, pack: packIn, now = Date.now() }) {
  createEngine = createEngine || require('./lib/engines.js').createEngine;
  const http = sdk.http;
  const log = (m) => (sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const shared = loadShared();
  const kind = await pickEngine(http, config.engine, config.timescale);
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
  const warnedUnits = new Set();
  const engine = await createEngine({ kind, pack, config: config.timescale });
  try {
    for (const equipRec of model.equips) {
      const equipId = shared.idOf(equipRec);
      if (only && !only.has(equipId)) continue;
      const siteId = (equipRec.attrs || {}).siteRef || '';
      let runnable = shared.equipRules(equipRec, model, shared.catalog)
        .filter((r) => r.runnable && pack.rules[r.rule.id]);
      if (!runnable.length) continue;
      let roles = roleInputs(runnable);
      const si = siPlan(roles, shared.catalog, log, warnedUnits);
      if (si.skipped.size) {
        runnable = runnable.filter((r) => !r.required.some((x) => si.skipped.has(x)));
        roles = roleInputs(runnable);
        for (const x of si.skipped) delete roles[x];
        if (!runnable.length) continue;
      }
      const uuids = [...new Set(Object.values(roles).map((p) => p.uuid))];
      let loadedRows;
      if (kind === 'timescale') {   // history stays in the database: SQL builds the wide table (SI conversion included)
        const roleToUuid = Object.fromEntries(Object.entries(roles).map(([r, p]) => [r, p.uuid]));
        const unitsByUuid = Object.fromEntries(Object.values(roles).map((p) => [p.uuid, p.units || '']));
        loadedRows = await engine.load({ equipId, siteId, roleToUuid, unitsByUuid, from, to, stepSec: step });
      } else {
        const hist = await fetchHistory(http, uuids, from, to, step);
        const input = buildInput({ equipId, siteId, roles, hist, grid, pack, si });
        loadedRows = input.history.length;
        if (loadedRows) await engine.load(input);
      }
      if (!loadedRows) { log(`${equipId}: no history in the last ${windowHours} h, skipped`); continue; }
      summary.equips++;
      const records = [];
      const values = [];
      const dbRows = [];            // timescale: rows for openfdd.fdd_results
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
        if (engine.resultRow) dbRows.push(engine.resultRow({ runTs: to, equip: equipId, site: siteId, ruleId: r.rule.id, row, windowStart: from, windowEnd: to }));
        records.push(...resultRecords({ equipRec, siteId, rule: r.rule, out, shared, windowHours }));
        values.push({ uuid: nameUuid(`${equipId}:${r.rule.id}`), value: out.value });
      }
      if (config.dryRun) continue;
      if (dbRows.length) await engine.writeResults(dbRows);   // timescale: also keep results in the database
      if (!records.length) continue;
      await http.post('/api/v1/point/points', { points: records });
      const ts = new Date(to).toISOString();
      for (const v of values) {
        await http.post('/api/v1/point/data', { uuid: v.uuid, values: [{ ts, real: v.value }] });
        summary.written++;
      }
    }
    if (engine.maybeEnforceCap && !config.dryRun) {   // retention cap (a no-op when the TimescaleDB job exists)
      try { summary.cap = await engine.maybeEnforceCap(); } catch (e) { summary.errors++; log(`size cap: ${errText(e)}`); }
    }
  } finally {
    await engine.close();
    // Small edges: hand freed engine memory back now rather than at the next GC.
    if (typeof global.gc === 'function') global.gc();
  }
  const faults = summary.results.filter((r) => r.fault && r.value > 0);
  if (config.bacnet && config.bacnet.enabled && !config.dryRun) {
    try {
      summary.bacnet = await exportToBacnet(http, summary.results, config.bacnet, log);
    } catch (e) {
      summary.errors++;
      log(`BACnet export: ${errText(e)}`);
    }
  }
  log(`open-fdd ${kind}: ${summary.equips} equips, ${summary.rules} rule runs, ${summary.errors} errors, `
    + `${faults.length} with fault time, ${summary.written} values written (window ${windowHours} h)`);
  return summary;
}

// ---- optional: fault counts on NF's own BACnet server ----------------------------------
// config.bacnet = { enabled: true, firstInstance: 1000 }  (off unless enabled)
// One analog value per equip, "OFDD <equip> faults" = how many rules had fault time in the
// last window; PROP_DESCRIPTION lists them. Objects are found by name, so instances stay
// put across runs; new equips take the next free instance ≥ firstInstance. Only creates /
// updates NF's own local objects (CreateLocalObject never gets a point uuid).
const BACNET_NAME = (equipId) => `OFDD ${equipId} faults`.slice(0, 64);

function bacnetPlan(results, existing, firstInstance) {
  const byEquip = new Map();
  for (const r of results) {
    if (!r.fault) continue;
    if (!byEquip.has(r.equip)) byEquip.set(r.equip, []);
    if (r.value > 0) byEquip.get(r.equip).push(r.rule);
  }
  const used = new Set(existing.map((o) => o.instance));
  const byName = new Map(existing.map((o) => [o.name, o.instance]));
  let next = firstInstance;
  const plan = [];
  for (const [equip, rules] of [...byEquip.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const name = BACNET_NAME(equip);
    let instance = byName.get(name);
    const create = instance == null;
    if (create) {
      while (used.has(next)) next++;
      instance = next;
      used.add(next);
    }
    const description = rules.length ? `Open-FDD faults: ${rules.sort().join(', ')}` : 'Open-FDD: no faults';
    plan.push({ equip, name, instance, create, count: rules.length, description: description.slice(0, 250) });
  }
  return plan;
}

async function exportToBacnet(http, results, cfg, log) {
  const first = Number.isInteger(cfg.firstInstance) && cfg.firstInstance > 0 ? cfg.firstInstance : 1000;
  const { data } = await http.get('/api/v1/bacnet/local');
  const prop = (o, p) => {
    const v = ((o.props || []).find((x) => x.property === p) || {}).value || {};
    return v.characterString;
  };
  const existing = ((data && data.objects) || [])
    .filter((o) => o.objectId && o.objectId.objectType === 'OBJECT_ANALOG_VALUE')
    .map((o) => ({ instance: o.objectId.instance, name: prop(o, 'PROP_OBJECT_NAME') || '' }));
  const plan = bacnetPlan(results, existing, first);
  for (const p of plan) {
    const objectId = { objectType: 'OBJECT_ANALOG_VALUE', instance: p.instance };
    const pv = { property: 'PROP_PRESENT_VALUE', value: { real: p.count } };
    const desc = { property: 'PROP_DESCRIPTION', value: { characterString: p.description } };
    if (p.create) {
      await http.post('/api/v1/bacnet/local', { objectId, props: [
        { property: 'PROP_OBJECT_NAME', value: { characterString: p.name } },
        { property: 'PROP_UNITS', value: { enumerated: 95 } },            // no-units
        desc, pv] });
      log(`created BACnet av.${p.instance} ${p.name}`);
    } else {
      await http.patch('/api/v1/bacnet/local', { objectId, props: [pv, desc] });
    }
  }
  return plan.map((p) => ({ object: `av.${p.instance}`, name: p.name, faults: p.count }));
}

/** NF hook entry point; helpers are exported for tests. */
async function hook({ sdk, config }) {
  await runFdd({ sdk, config: config || {} });
}
module.exports = Object.assign(hook, { runFdd, nameUuid, buildInput, siPlan, resultValue, bacnetPlan });
