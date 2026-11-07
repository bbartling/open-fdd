// Open-FDD rule runner (ADR-014 slice 3). Scheduled NF hook, no point bindings.
//
// Each run, for every Haystack equip in NF's model layer:
//   1. bind rule roles to the equip's points (static/fdd.js — the exact code the FDD tab runs)
//   2. read the bound points' history from NF, resampled server side to the pack's grid
//      (GET /api/v1/point/data …&window=300s&method=AVERAGE) for the trailing window
//      (values are brought to the role's declared scale first: SI by unit, fraction 0-1, boolean 0/1; see siPlan)
//   3. run every runnable rule of the SQL pack (sql/fdd → rules/pack-*.json) in an
//      embedded engine: SQLite-WASM on small edges, PGlite (real Postgres) on big ones
//   4. write one result point per (site, equip, rule): automation layer (history) + model layer (all queued, then
//      flushed in batches at the end of the run: one UpdatePoints + one AddData call per chunk, see flushWrites)
//      (Haystack tags fault/ruleRef/equipRef/siteRef), value = fault % of covered time
//      (metric rules: their first declared output), trended every run.
//
// Result identity (site scoped): the uuid is derived from resultKey(equip) + rule id, where the key is the equip
// record's own NF uuid when it has one (stable across renames of the equip id or the site, and unique across sites),
// else "site:<siteRef>:<equip id>". Equip ids alone are NOT unique across sites. MIGRATION (5.0.0 -> 5.0.1): 5.0.0
// derived the uuid from "<equip id>:<rule id>" only, so those old result points are not reused and not touched; new
// points appear next to them. The operator can delete the old ones (application_id open-fdd, no siteRef-scoped name,
// no fddStatus attribute) once the new ones are trending. Nothing is deleted automatically.
//
// Result contract (typed, unknown is never healthy):
//   fault rule   = pack output_columns contain fault_pct or fault_hours. Published value = fault_pct (unit %) else
//                  fault_hours (unit h). covered_hours null/0 -> fddStatus "not-assessed", NO numeric value written.
//                  Otherwise fddStatus "ok" (0) or "fault" (> 0) and fddCoverageHours. Always keeps the fault marker.
//   metric rule  = every other rule. Publishes its first declared output column (0 is a valid value), unit "".
//   stale        = a previously published result point whose rule could not be refreshed this run (no history,
//                  roles missing, rule error): its record gets fddStatus "stale" + fddReason, no new value.
//   Every model record also carries fddLastRun (ISO). Any rule error makes the hook throw at the very end, after
//   everything else was written, so NF records the run as failed.
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
  const model = { sites: of('SITE'), equips: of('EQUIPMENT'), devices: of('DEVICE'), points: [], results: new Map() };
  // result points published by earlier runs (model-layer records), by uuid; used to mark them stale
  for (const r of recs) {
    const a = r.attrs || {};
    if (r.uuid && a.ruleRef && /(^|,)fdd(,|$)/.test(String(a.markers || ''))) model.results.set(r.uuid, r);
  }
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

/** Units that already mean "a fraction 0-1" (not a percent). */
const FRACTION_UNIT = /^(ratio|fraction|frac|0-1|0\.\.1|0 to 1|unitless ratio)$/i;
const isBoolKind = (kind) => /^bool/i.test(String(kind || ''));

/**
 * Role scale (issue #1541) from the catalog (sql/fdd/role_scales.json -> fdd-catalog.json roles.<role>.scale):
 *   fraction | boolean | percent_rh | text | si:<unit>. null = the catalog does not declare one (legacy / tests).
 */
function roleScale(role, catalog) {
  const s = ((catalog && catalog.roles && catalog.roles[role]) || {}).scale;
  return typeof s === 'string' ? s : null;
}

/**
 * Per bound role: how to bring the point's values to the role's declared scale and which unit to declare.
 *   convert[role](v) -> value (null = reject this value); unit[role] -> unit string;
 *   skipped = roles that cannot be brought to their scale; scaled = roles divided by 100; bool = 0/1 roles.
 * The scales (sql/fdd/README.md, "Input contract"): the SQL rules never guess a scale by magnitude, so this is the
 * ONE place that decides, from the point's DECLARED unit and kind. hooks/lib/timescale.js applies exactly these
 * decisions (plan.scaled / plan.bool) in SQL.
 *   fraction  unit "%"/"percent" -> v/100; unit ratio/fraction/0-1 -> as is; kind Bool -> as is (0/1 is a valid
 *             fraction); NO unit (or any other unit) -> SKIPPED and logged, never guessed (a unitless 0-100
 *             command cannot be told from a 0-1 one).
 *   boolean   kind Bool -> as is; Number/Enum: a "%" unit is /100 first; the value must then lie in [0, 1]
 *             (a resampled 0/1 status is an on-fraction of the bucket) - anything outside is REJECTED (null), not
 *             thresholded and not rescaled: a 0-100 analog or an enum 1/2/3 is not 0/1 data.
 *   percent_rh / text / si:<unit>  physical quantity (humidity stays 0-100) or categorical: the SI conversion below.
 * A known unit is converted (degF -> degC, inH2O -> Pa, cfm -> L/s ...). An unknown or empty unit leaves the value
 * as it is (humidity, ppm, counts), except for temperature/pressure/flow roles: those are skipped, logged once per
 * point, never guessed.
 */
function siPlan(roles, catalog, log, warned) {
  const plan = { convert: {}, unit: {}, skipped: new Set(), scaled: new Set(), bool: new Set() };
  const skip = (role, p, why) => {
    plan.skipped.add(role);
    if (log && warned && !warned.has(p.uuid)) { warned.add(p.uuid); log(`${p.name || p.uuid}: role ${role} ${why}, role skipped`); }
  };
  for (const [role, p] of Object.entries(roles)) {
    const unit = p.units || '';
    const probe = ofddUnits.toSI(1, unit);
    const scale = roleScale(role, catalog);
    if (scale === 'fraction' || scale === 'boolean') {
      const pct = !!probe && probe.quantity === 'percent' && !/rh/i.test(unit);
      const bool = isBoolKind(p.kind);
      if (scale === 'fraction') {
        if (bool || FRACTION_UNIT.test(unit)) { plan.convert[role] = (v) => v; }
        else if (pct) { plan.convert[role] = (v) => v / 100; plan.scaled.add(role); }
        else { skip(role, p, unit ? `is a fraction 0-1 but unit "${unit}" is not a percent or fraction` : 'is a fraction 0-1 but its point has no unit (0-100 or 0-1 cannot be told apart)'); continue; }
        plan.unit[role] = 'fraction';
      } else {
        if (probe && !pct && !FRACTION_UNIT.test(unit)) { skip(role, p, `is a 0/1 status but unit "${unit}" is a ${probe.quantity}`); continue; }
        const div = !bool && pct;
        if (div) plan.scaled.add(role);
        plan.bool.add(role);
        plan.convert[role] = (v) => { const x = div ? v / 100 : v; return x >= -1e-9 && x <= 1 + 1e-9 ? Math.min(1, Math.max(0, x)) : null; };
        plan.unit[role] = 'bool';
      }
      continue;
    }
    const want = roleQuantity(role, catalog);
    if (probe) {
      if (want && probe.quantity !== want) { // e.g. a temperature role whose point says kPa: wrong binding, not ours to fix
        skip(role, p, `is a ${want} but unit "${unit}" is a ${probe.quantity}`);
        continue;
      }
      plan.convert[role] = (v) => { const r = ofddUnits.toSI(v, unit); return r ? r.value : v; };
      plan.unit[role] = probe.unit;
    } else if (want && STRICT_QUANTITY.includes(want)) {
      skip(role, p, `(${want}) has ${unit ? `unknown unit "${unit}"` : 'no unit'}`);
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
      const x = v != null ? conv(role, v) : null;
      if (x != null) { row[role] = x; any = true; }
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
      const x = v != null ? conv(role, v) : null;
      if (x != null) { w[role] = x; any = true; }
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

/** Site-scoped identity of an equip's results: its NF uuid when it has one, else "site:<siteRef>:<equip id>". */
function resultKey(equipRec, siteId, equipId) {
  return equipRec && equipRec.uuid ? `equip:${equipRec.uuid}` : `site:${siteId || ''}:${equipId}`;
}
const resultUuid = (key, ruleId) => nameUuid(`${key}:${ruleId}`);

const FAULT_COLS = ['fault_pct', 'fault_hours'];


/**
 * What one rule run publishes.
 * @returns {{ kind: string, status: 'ok'|'fault'|'not-assessed', value: any, unit: string,
 *   fault: boolean, column: string, coverage: any, reason: string }}
 */
function resultValue(packRule, row) {
  const cols = (packRule && packRule.output_columns) || Object.keys(row || {});
  const num = (v) => (v != null && Number.isFinite(Number(v)) ? Number(v) : null);
  if (cols.some((c) => FAULT_COLS.includes(c))) {
    const column = cols.includes('fault_pct') ? 'fault_pct' : 'fault_hours';
    const unit = column === 'fault_pct' ? '%' : 'h';
    const base = { kind: 'fault', unit, fault: true, column, value: null, coverage: null };
    if (!row) return { ...base, status: 'not-assessed', reason: 'rule returned no row (no usable input)' };
    const coverage = cols.includes('covered_hours') ? num(row.covered_hours) : null;
    if (cols.includes('covered_hours') && !(coverage > 0)) {
      return { ...base, coverage: coverage || 0, status: 'not-assessed', reason: 'no covered time in the window (covered_hours 0)' };
    }
    const value = num(row[column]);
    if (value == null) return { ...base, coverage, status: 'not-assessed', reason: `${column} is null` };
    return { ...base, value, coverage, status: value > 0 ? 'fault' : 'ok', reason: '' };
  }
  const column = cols.find((c) => c !== 'equipment_id') || '';
  const base = { kind: 'metric', unit: '', fault: false, column, value: null, coverage: null };
  if (!row) return { ...base, status: 'not-assessed', reason: 'rule returned no row (no usable input)' };
  const value = num(row[column]);
  if (value == null) return { ...base, status: 'not-assessed', reason: `${column} is null` };
  return { ...base, value, status: 'ok', reason: '' };
}

const siteEquipLabel = (siteId, equipId) => (siteId ? `${siteId}/${equipId}` : equipId);

function resultRecords({ equipRec, siteId, rule, out, shared, windowHours, key, runIso }) {
  const equipId = shared.idOf(equipRec);
  const uuid = resultUuid(key, rule.id);
  const dis = `${(equipRec.attrs || {}).dis || equipRec.name} ${rule.id}`;
  const name = `${siteEquipLabel(siteId, equipId)}/${rule.id}`;
  const markers = ['point', 'his', out.kind === 'fault' ? 'fault' : 'metric', 'fdd'];
  const attrs = {
    dis, markers: markers.join(','), kind: 'Number', unit: out.unit,
    siteRef: siteId, equipRef: equipId, ruleRef: rule.id,
    fddWindowHours: String(windowHours), fddOutput: out.column,
    fddStatus: out.status, fddReason: out.reason || '', fddLastRun: runIso };
  if (out.coverage != null) attrs.fddCoverageHours = String(out.coverage);
  return [
    { uuid, name, layer: 'automation', pointType: 'POINT', attrs: {
      application_id: APP_ID, type: 'fdd-result', label: rule.id, group_key: siteEquipLabel(siteId, equipId),
      description: rule.description || rule.id, units: out.unit } },
    { uuid, name, layer: 'model', attrs },
  ];
}

/** Model record of a previously published result, flagged stale: nothing else about it changes. */
function staleRecord(rec, reason, runIso) {
  return { uuid: rec.uuid, name: rec.name, layer: 'model',
    attrs: { ...(rec.attrs || {}), fddStatus: 'stale', fddReason: reason, fddLastRun: runIso } };
}

// ---- NF writes (batched) ------------------------------------------------------------------
// Everything a run publishes is queued while the equips are processed and flushed once at the end:
//   metadata  POST /api/v1/point/points   { points: [record, ...] }              (UpdatePoints, many records per call)
//   values    POST /api/v1/points/data    { points: [{ uuid, values: [{ ts, real }] }, ...] }   (AddData, batched)
// https://docs.normal.dev/api/html/api.html : AddData "carries any number of (uuid, values, errors) tuples in one
// request"; its reply is only { success, taskUuid }, so a failed call cannot say which point failed.
const WRITE_MAX_RECORDS = 500;          // records (metadata) or points (values) per call
const WRITE_MAX_BYTES = 512 * 1024;     // JSON payload cap per call
const RETRY_ATTEMPTS = 3;               // 429/503 only
const RETRY_BASE_MS = 500;
const httpStatus = (e) => Number((e && ((e.response && e.response.status) || e.status || e.statusCode)) || 0);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Split items into chunks of at most maxCount items and about maxBytes of JSON (a single big item stands alone). */
function chunkBySize(items, maxCount = WRITE_MAX_RECORDS, maxBytes = WRITE_MAX_BYTES) {
  const chunks = [];
  let cur = [];
  let bytes = 0;
  for (const it of items) {
    const n = JSON.stringify(it).length + 1;
    if (cur.length && (cur.length >= maxCount || bytes + n > maxBytes)) { chunks.push(cur); cur = []; bytes = 0; }
    cur.push(it);
    bytes += n;
  }
  if (cur.length) chunks.push(cur);
  return chunks;
}

/**
 * One POST with retry: only 429/503 are retried (at most RETRY_ATTEMPTS attempts, exponential backoff);
 * any other error (400, 500, network) fails at once. counter.n counts every request actually sent.
 */
async function postRetry(http, url, body, counter, baseMs) {
  for (let attempt = 1; ; attempt++) {
    counter.n++;
    try {
      return await http.post(url, body);
    } catch (e) {
      const st = httpStatus(e);
      if ((st !== 429 && st !== 503) || attempt >= RETRY_ATTEMPTS) throw e;
      await sleep(baseMs * 2 ** (attempt - 1));
    }
  }
}

/** Flush the queued metadata + values; fills summary.written / errors / requests. Never throws. */
async function flushWrites(http, queue, summary, log, baseMs) {
  const counters = { metadata: { n: 0 }, data: { n: 0 } };
  const failedMeta = new Set();     // uuids whose metadata could not be written
  for (const chunk of chunkBySize(queue.meta)) {
    try {
      const res = await postRetry(http, '/api/v1/point/points', { points: chunk }, counters.metadata, baseMs); const data = res && res.data;
      for (const r of (data && data.results) || []) if (r && r.success === false && r.uuid) failedMeta.add(r.uuid);
    } catch (e) {
      for (const r of chunk) failedMeta.add(r.uuid);
      log(`result metadata: ${chunk.length} records failed: ${errText(e)}`);
    }
  }
  if (failedMeta.size) log(`result metadata: ${failedMeta.size} points not written`);
  let failedData = 0;
  // a point whose metadata failed is not written to (it may not exist); it is already counted as an error
  const pending = queue.values.filter((v) => !failedMeta.has(v.uuid))
    .map((v) => ({ uuid: v.uuid, values: [{ ts: v.ts, real: v.value }] }));
  for (const chunk of chunkBySize(pending)) {
    try {
      const res = await postRetry(http, '/api/v1/points/data', { points: chunk }, counters.data, baseMs); const data = res && res.data;
      if (data && data.success === false) throw new Error('AddData success=false');
      summary.written += chunk.length;
    } catch (e) {
      failedData += chunk.length;
      log(`result values: ${chunk.length} points failed: ${errText(e)}`);
    }
  }
  summary.errors += failedMeta.size + failedData;
  summary.requests = { metadata: counters.metadata.n, data: counters.data.n };
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
 *   bacnet?: { enabled?: boolean, firstInstance?: number }, timescale?: object, writeRetryMs?: number }} FddConfig
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
  const runIso = new Date(now).toISOString();
  const summary = { engine: kind, equips: 0, rules: 0, errors: 0, written: 0, results: [],
    status: { ok: 0, fault: 0, 'not-assessed': 0, stale: 0 }, requests: { metadata: 0, data: 0 } };
  const queue = { meta: [], values: [] };    // writes, flushed in batches after all equips ran
  const warnedUnits = new Set();
  const engine = await createEngine({ kind, pack, config: config.timescale });
  try {
    for (const equipRec of model.equips) {
      const equipId = shared.idOf(equipRec);
      if (only && !only.has(equipId)) continue;
      const siteId = (equipRec.attrs || {}).siteRef || '';
      const key = resultKey(equipRec, siteId, equipId);
      // results of this equip written (or deliberately flagged) this run; every other previously published
      // result of the equip goes stale with the reason below (per rule) or the equip-level default.
      const touched = new Set();
      const reasons = new Map();
      let defaultReason = 'required input roles are missing or have no usable unit';
      try {
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
          loadedRows = await engine.load({ equipId, siteId, roleToUuid, unitsByUuid, fractionRoles: [...si.scaled], booleanRoles: [...si.bool], from, to, stepSec: step });
        } else {
          const hist = await fetchHistory(http, uuids, from, to, step);
          const input = buildInput({ equipId, siteId, roles, hist, grid, pack, si });
          loadedRows = input.history.length;
          if (loadedRows) await engine.load(input);
        }
        if (!loadedRows) {
          defaultReason = `no history in the last ${windowHours} h`;
          log(`${equipId}: no history in the last ${windowHours} h, skipped`);
          continue;
        }
        defaultReason = 'rule was not run (required input roles are missing)';
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
            reasons.set(r.rule.id, `rule error: ${errText(e)}`);
            log(`${equipId} ${r.rule.id}: ${errText(e)}`);
            continue;
          }
          summary.rules++;
          const row = rows.find((x) => x.equipment_id === equipId) || rows[0];
          const out = resultValue(pack.rules[r.rule.id], row);
          summary.status[out.status]++;
          if (out.status !== 'not-assessed') {
            summary.results.push({ site: siteId, equip: equipId, rule: r.rule.id, value: out.value, unit: out.unit, fault: out.fault, status: out.status });
            if (engine.resultRow) dbRows.push(engine.resultRow({ runTs: to, equip: equipId, site: siteId, ruleId: r.rule.id, row, windowStart: from, windowEnd: to }));
          }
          const uuid = resultUuid(key, r.rule.id);
          touched.add(uuid);
          records.push(...resultRecords({ equipRec, siteId, rule: r.rule, out, shared, windowHours, key, runIso }));
          if (out.status !== 'not-assessed') values.push({ uuid, value: out.value });
        }
        if (config.dryRun) continue;
        if (dbRows.length) await engine.writeResults(dbRows);   // timescale: also keep results in the database
        if (!records.length) continue;
        queue.meta.push(...records);
        const ts = new Date(to).toISOString();
        for (const v of values) queue.values.push({ uuid: v.uuid, ts, value: v.value });
      } catch (e) {
        summary.errors++;
        defaultReason = `run error: ${errText(e)}`;
        log(`${equipId}: ${errText(e)}`);
      } finally {
        // previously published results this run did not refresh: flag, never overwrite with a number
        const stale = [];
        for (const ruleId of Object.keys(pack.rules)) {
          const uuid = resultUuid(key, ruleId);
          const prev = model.results.get(uuid);
          if (!prev || touched.has(uuid)) continue;
          stale.push(staleRecord(prev, reasons.get(ruleId) || defaultReason, runIso));
        }
        summary.status.stale += stale.length;
        if (stale.length && !config.dryRun) queue.meta.push(...stale);
      }
    }
    if (!config.dryRun) {
      const retryMs = Number(config.writeRetryMs) >= 0 && config.writeRetryMs != null ? Number(config.writeRetryMs) : RETRY_BASE_MS;
      await flushWrites(http, queue, summary, log, retryMs);
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
  const st = summary.status;
  log(`open-fdd ${kind}: ${summary.equips} equips, ${summary.rules} rule runs, ${summary.errors} errors, `
    + `${faults.length} with fault time, ${summary.written} values written (window ${windowHours} h); `
    + `ok ${st.ok}, fault ${st.fault}, not-assessed ${st['not-assessed']}, stale ${st.stale}; `
    + `requests: ${summary.requests.metadata} metadata, ${summary.requests.data} data`);
  return summary;
}

// ---- optional: fault counts on NF's own BACnet server ----------------------------------
// config.bacnet = { enabled: true, firstInstance: 1000 }  (off unless enabled)
// One analog value per (site, equip), "OFDD <site>/<equip> faults" = how many rules had fault time in the
// last window; PROP_DESCRIPTION lists them. Objects are found by name, so instances stay
// put across runs; new equips take the next free instance ≥ firstInstance. Only creates /
// updates NF's own local objects (CreateLocalObject never gets a point uuid).
// BACnet object names are capped at 64 chars; a longer name keeps its head and ends in a short hash of the full name,
// so two long names that share a prefix stay distinct. Without a site (old results) the name is "OFDD <equip> faults".
const BACNET_NAME = (siteId, equipId) => {
  const full = `OFDD ${siteEquipLabel(siteId, equipId)} faults`;
  return full.length <= 64 ? full : `${full.slice(0, 54)}~${crypto.createHash('sha1').update(full).digest('hex').slice(0, 9)}`;
};

function bacnetPlan(results, existing, firstInstance) {
  const byEquip = new Map();   // "site\0equip" -> { site, equip, rules }
  for (const r of results) {
    if (!r.fault) continue;
    const k = `${r.site || ''}\0${r.equip}`;
    if (!byEquip.has(k)) byEquip.set(k, { site: r.site || '', equip: r.equip, rules: [] });
    if (r.value > 0) byEquip.get(k).rules.push(r.rule);
  }
  const used = new Set(existing.map((o) => o.instance));
  const byName = new Map(existing.map((o) => [o.name, o.instance]));
  let next = firstInstance;
  const plan = [];
  for (const { site, equip, rules } of [...byEquip.values()].sort((a, b) => siteEquipLabel(a.site, a.equip).localeCompare(siteEquipLabel(b.site, b.equip)))) {
    const name = BACNET_NAME(site, equip);
    let instance = byName.get(name);
    const create = instance == null;
    if (create) {
      while (used.has(next)) next++;
      instance = next;
      used.add(next);
    }
    const description = rules.length ? `Open-FDD faults: ${rules.sort().join(', ')}` : 'Open-FDD: no faults';
    plan.push({ site, equip, name, instance, create, count: rules.length, description: description.slice(0, 250) });
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

/**
 * NF hook entry point; helpers are exported for tests. Extra arguments (pack, createEngine, now) pass through to
 * runFdd. A rule error does not stop the run (everything else is still written), but it must not look like a
 * success to NF: after the last write the hook throws with the per-status summary.
 */
async function hook({ sdk, config, ...rest }) {
  const summary = await runFdd({ sdk, config: config || {}, ...rest });
  if (summary.errors) {
    const st = summary.status;
    throw new Error(`open-fdd: ${summary.errors} error${summary.errors === 1 ? '' : 's'} during the run (see the log); `
      + `ok ${st.ok}, fault ${st.fault}, not-assessed ${st['not-assessed']}, stale ${st.stale}`);
  }
  return summary;
}
module.exports = Object.assign(hook, { runFdd, nameUuid, resultKey, resultUuid, buildInput, siPlan, resultValue, bacnetPlan, chunkBySize });
