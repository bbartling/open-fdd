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
// FAULT TIMELINE (5.0.3). fault_pct is a rolling number (one value per run over the trailing window): a fault that
// cleared an hour ago still shows a percentage, and it says nothing about WHEN. So every fault rule whose pack entry has
// a timeline_sql (68 of 77; see scripts/nf/build_sql_pack.py) also publishes a per-timestamp series on a SECOND result
// point per (equip, rule): markers point,his,fault_timeline (deliberately NOT `fdd`/`fault`, so the FDD results table
// and the old fault_pct lookups never see it), uuid = nameUuid("<resultKey>:<rule id>:timeline"), same ruleRef /
// equipRef / siteRef (+ equipUuid) attributes. Each sample is the rule's own confirmed flag at that history timestamp:
//   1 = confirmed fault, 0 = assessed and ok, NOT WRITTEN = not assessed (last sample, a gap longer than MAX_GAP_HOURS,
//   or a REQUIRED input of the rule missing at that timestamp). Unknown is never written as 0.
// Append-only: a run writes only samples newer than the point's attribute fddTimelineThrough (ISO, the newest sample
// written so far; advanced only after the AddData call that carried them succeeded), so nothing is written twice and
// NF is never asked to overwrite. The first run writes the whole trailing window. A rule without a timeline_sql
// (ratio / count / window-statistic rules) keeps only its per-run status sample.
// The fault_pct point, its uuid and its meaning are unchanged (FDD table, BACnet export, 5.0.1/5.0.2 readers).
//
// OCCUPANCY (5.0.3). A runnable rule that lists occ_mode as OPTIONAL (VAV-1, ...) and has no bound occ_mode point gets
// occ_mode synthesized onto its history rows before the SQL runs, from the site's NF schedule (read only,
// static/schedule.js: a schedule that targets the site's occupancy point, holidays included) else the 4.x default
// calendar (Mon-Fri 07:00-17:00), in the site timezone: 1 = occupied, 0 = unoccupied (the SQL treats <= 0.05 as
// unoccupied). The source lands in the result attributes as fddOccSource = point | schedule | default (rules with
// occ_mode REQUIRED, e.g. VAV-2, are untouched: no point, no run). Not available on the timescale engine (its wide
// history is built in SQL), where the rule keeps its old behaviour (no occ_mode = occupied limits).
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
//   LOUD FAILURE (5.0.5, #1550). A run that had eligible equips (results published before, or rules runnable now) but
//   freshly assessed none of them (ok + fault = 0) also throws, never STATE_SUCCESS with nothing written. Each equip
//   that produced nothing says why, and stale results carry the same reason: "required roles missing" | "unit unusable" |
//   "no input data in window (newest sample at <ISO>)" | "rule error: ...". The log always has the engine, the data
//   window, the newest input sample (engine source and NF latest value) and eligible / evaluated / written / skipped /
//   stale counts (summary.eligible, .skipped, .stale_reasons, .source_freshness, .window, .failure).
//
// Nothing site-specific: sites, equips, points and units all come from NF.
// config (hook settings, all optional). NF stores these as app OPTIONS and passes them as ctx.config (scalars only:
// see lib/settings.js; a string value such as "24" or a JSON string for timescale is converted):
//   engine        "auto" | "sqlite" | "pglite" | "timescale"   (auto: timescale when configured, else pglite when NF reports ≥ 3.5 GiB RAM)
//   timescale     the NF Timescale connection: JSON {"host","port","database","user","password"} or a postgres:// URL
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
const { queryPoints } = require('./lib/paging.js');
const settings = require('./lib/settings.js');
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

// Every point/query goes through the shared pager (lib/paging.js): NF pages by pageOffset + totalCount, not only by a
// next-page token (#1550). It throws a PagingError rather than ever returning a truncated list.
const queryAll = (http, body) => queryPoints(http, body);

async function loadModel(http, shared) {
  const recs = await queryAll(http, { layer: 'model' });
  const of = (t) => recs.filter((r) => r.pointType === t);
  const model = { sites: of('SITE'), equips: of('EQUIPMENT'), devices: of('DEVICE'), points: [], results: new Map(), timelines: new Map(),
    read: { records: recs.length, total: /** @type {any} */ (recs).totalCount, sitePointQueries: 0 } };
  // result points published by earlier runs (model-layer records), by uuid; used to mark them stale
  for (const r of recs) {
    const a = r.attrs || {};
    if (r.uuid && a.ruleRef && /(^|,)fdd(,|$)/.test(String(a.markers || ''))) model.results.set(r.uuid, r);
    if (r.uuid && a.ruleRef && /(^|,)fault_timeline(,|$)/.test(String(a.markers || ''))) model.timelines.set(r.uuid, r);
  }
  for (const s of model.sites) {
    const pts = await queryAll(http, { layer: 'default', structuredQuery: { field: { property: 'siteRef', text: shared.idOf(s) } } });
    model.read.sitePointQueries++;
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

// ---- input freshness (#1550) ------------------------------------------------------------
const tsMs = (ts) => { const t = Date.parse(String(ts).replace(/(\.\d{3})\d+/, '$1')); return Number.isFinite(t) ? t : null; };
const isoOrNull = (ms) => (ms == null ? null : new Date(ms).toISOString());
const maxOrNull = (list) => list.reduce((a, b) => (b == null ? a : a == null || b > a ? b : a), null);

/** Newest `latest.ts` (ms) over toPoint() records (NF's own latest value of each point); null when none has one. */
function newestLatest(points) {
  return maxOrNull((points || []).map((p) => (p && p.latest && p.latest.ts ? tsMs(p.latest.ts) : null)));
}

/** Newest bucket (ms) over the {uuid: Map(bucketMs -> value)} that fetchHistory returned; null when empty. */
function newestOfHistory(hist) {
  return maxOrNull(Object.values(hist).map((m) => maxOrNull([...m.keys()])));
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

/** Sweep series are physical sensors; command/status/setpoint inputs only prove operation. */
function isSweepSensorRole(role, catalog) {
  const def = (catalog && catalog.roles && catalog.roles[role]) || {};
  const name = String(def.name || role).toLowerCase();
  const key = String(role).toLowerCase();
  if (/(^|[-_])(cmd|command|status|sp|setpoint|request|count|occupied|occupancy)([-_]|$)/.test(key)
      || /request|count|setpoint|status|command/.test(name)) return false;
  const scale = roleScale(role, catalog);
  if (scale === 'fraction' || scale === 'boolean' || scale === 'text') return false;
  return !!roleQuantity(role, catalog) || scale === 'percent_rh' || (typeof scale === 'string' && scale.startsWith('si:'));
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
function buildInput({ equipId, siteId, roles, hist, grid, pack, si, occ }) {
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
    if (any) {                           // a timestamp with no data at all is a gap, not zeros
      if (occ) row.occ_mode = occ(ts) ? 1 : 0;   // synthesized from the schedule (occ is only passed when no occ_mode point is bound)
      history.push(row);
    }
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

/** Long-form sweep input. Each physical point keeps its own identity and SI conversion. */
function buildSensorInput({ equipId, sensors, hist, grid, catalog, log, warned }) {
  const sensorSeries = [];
  const sensorHistory = [];
  const skipped = {};
  for (const sensor of sensors) {
    const role = sensor.role;
    const point = sensor.point;
    const si = siPlan({ [role]: point }, catalog, log, warned);
    if (si.skipped.has(role)) { skipped[role] = (skipped[role] || 0) + 1; continue; }
    const unit = si.unit[role] != null ? si.unit[role] : point.units || '';
    sensorSeries.push({ uuid: point.uuid, role, unit });
    const samples = hist[point.uuid];
    if (!samples) continue;
    for (const ts of grid) {
      const raw = samples.get(ts);
      if (raw == null) continue;
      const value = si.convert[role] ? si.convert[role](raw) : raw;
      if (value == null || !Number.isFinite(value)) continue;
      sensorHistory.push({ equipment_id: equipId, series_id: point.uuid, sensor_role: role, unit, ts, value });
    }
  }
  return { sensorSeries, sensorHistory, skipped };
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
const sensorResultUuid = (key, ruleId, seriesId) => nameUuid(`${key}:${ruleId}:${seriesId}`);

// NF merges attrs in UpdatePoints, so every Open-FDD-owned key is written on every update.
const OFDD_RESULT_ATTRS = Object.freeze([
  'fddStatus', 'fddOutput', 'unit', 'fddLastRun', 'fddCoverageHours', 'fddSensorFaultHours',
  'fddOccSource', 'fddReason', 'fddWindowHours', 'equipUuid', 'sensorRef', 'roleRef', 'fddSummary',
  'fddOutputSince',
]);

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

/** Equipment summary is the max per-series hours; retain rows for per-series result records. */
function equipmentResult(packRule, rows, equipId, sensorNames = {}) {
  if (!packRule.output_columns?.includes('sensor_role')) {
    return rows.find((row) => row.equipment_id === equipId) || rows[0];
  }
  const scores = rows.filter((row) => row.equipment_id === equipId && typeof row.series_id === 'string'
    && typeof row.sensor_role === 'string');
  if (!scores.length) return undefined;
  const sensorValues = scores.map((row) => ({ row, out: resultValue(packRule, row) }));
  const assessed = sensorValues.filter(({ out }) => out.status !== 'not-assessed');
  return {
    equipment_id: equipId,
    fault_hours: assessed.length ? Math.max(...assessed.map(({ out }) => out.value)) : null,
    covered_hours: Math.max(...sensorValues.map(({ out }) => Number(out.coverage) || 0)),
    sensor_rows: scores,
    sensor_fault_hours: Object.fromEntries(sensorValues.map(({ row, out }) => [row.series_id, {
      role: row.sensor_role, name: sensorNames[row.series_id] || row.series_id,
      hours: out.status === 'not-assessed' ? null : out.value, status: out.status,
    }])),
  };
}

const siteEquipLabel = (siteId, equipId) => (siteId ? `${siteId}/${equipId}` : equipId);

function resultRecords({ equipRec, siteId, rule, out, shared, windowHours, key, runIso, occSource = undefined,
  sensorFaultHours = undefined, sensor = null, previous = null, outputSince = runIso }) {
  const equipId = shared.idOf(equipRec);
  const uuid = sensor ? sensorResultUuid(key, rule.id, sensor.series_id) : resultUuid(key, rule.id);
  const dis = `${(equipRec.attrs || {}).dis || equipRec.name} ${rule.id}`;
  const name = `${siteEquipLabel(siteId, equipId)}/${rule.id}${sensor ? `/${sensor.name || sensor.series_id}` : ''}`;
  const markers = ['point', 'his', out.kind === 'fault' ? 'fault' : 'metric', 'fdd'];
  const oldAttrs = previous && previous.attrs || {};
  const boundary = oldAttrs.fddOutput === out.column && oldAttrs.fddOutputSince
    ? oldAttrs.fddOutputSince : outputSince;
  const attrs = Object.fromEntries(OFDD_RESULT_ATTRS.map((k) => [k, '']));
  Object.assign(attrs, {
    dis, markers: markers.join(','), kind: 'Number', unit: out.unit,
    siteRef: siteId, equipRef: equipId, ruleRef: rule.id,
    fddWindowHours: String(windowHours), fddOutput: out.column,
    fddStatus: out.status, fddReason: out.reason || '', fddLastRun: runIso, fddOutputSince: boundary,
    fddCoverageHours: out.coverage == null ? '' : String(out.coverage),
    fddSensorFaultHours: sensorFaultHours ? JSON.stringify(sensorFaultHours) : '',
    fddOccSource: occSource || '', equipUuid: equipRec.uuid || '',
    sensorRef: sensor ? sensor.series_id : '', roleRef: sensor ? sensor.sensor_role : '',
    fddSummary: sensor ? 'sensor' : 'equip',
  });
  return [
    { uuid, name, layer: 'automation', pointType: 'POINT', attrs: {
      application_id: APP_ID, type: 'fdd-result', label: rule.id, group_key: siteEquipLabel(siteId, equipId),
      description: rule.description || rule.id, units: out.unit } },
    { uuid, name, layer: 'model', attrs },
  ];
}

// ---- fault timeline (see the header) ---------------------------------------------------------
const timelineUuid = (key, ruleId, seriesId = '') => nameUuid(`${key}:${ruleId}${seriesId ? `:${seriesId}` : ''}:timeline`);

/**
 * Timeline rows (engine.timeline) -> the samples to publish: [{ ms, value: 1 | 0 }], oldest first.
 * Skipped (= not assessed, nothing written): held_seconds 0 (last sample, gap over MAX_GAP_HOURS), a null flag,
 * a timestamp for which assessed(ms) is false (a required input missing), and anything at or before `after` (already written).
 * Sensor sweeps use SQL's assessed intervals, including silence, and combine their overlap on the pack grid.
 * @param {any[]} rows @param {{ assessed?: ((ms: number) => boolean) | null, after?: number, equipId?: string, stepSec?: number, seriesId?: string | null }} [o]
 */
function timelineSamples(rows, { assessed, after = -Infinity, equipId, stepSec = 300, seriesId = null } = {}) {
  if (rows?.some((row) => typeof row.sensor_role === 'string')) {
    return sweepTimelineSamples(rows, equipId, after, stepSec, seriesId);
  }
  const out = [];
  for (const r of rows || []) {
    if (equipId != null && r.equipment_id !== equipId) continue;
    const ms = Math.round(Number(r.ts_epoch) * 1000);
    if (!Number.isFinite(ms) || ms <= after) continue;
    if (!(Number(r.held_seconds) > 0) || r.confirmed == null) continue;
    if (assessed && !assessed(ms)) continue;
    out.push({ ms, value: Number(r.confirmed) === 1 ? 1 : 0 });
  }
  return out.sort((a, b) => a.ms - b.ms);
}

/** Collapse overlapping sensor intervals into one equipment lane on the pack grid. */
function sweepTimelineSamples(rows, equipId, after, stepSec, seriesId = null) {
  const events = new Map();
  const add = (ms, assessed, faults) => {
    const event = events.get(ms) || { assessed: 0, faults: 0 };
    event.assessed += assessed;
    event.faults += faults;
    events.set(ms, event);
  };
  for (const row of rows) {
    if ((equipId != null && row.equipment_id !== equipId) || (seriesId != null && row.series_id !== seriesId)) continue;
    const start = Math.round(Number(row.ts_epoch) * 1000);
    const end = start + Math.round(Number(row.held_seconds) * 1000);
    if (!Number.isFinite(end) || end <= start || end <= after || row.confirmed == null) continue;
    const fault = Number(row.confirmed) === 1 ? 1 : 0;
    add(start, 1, fault);
    add(end, -1, -fault);
  }
  const step = Math.max(1, Math.round(stepSec * 1000));
  const times = [...events.keys()].sort((a, b) => a - b);
  const samples = [];
  let assessed = 0, faults = 0;
  for (let i = 0; i + 1 < times.length; i++) {
    const start = times[i], next = times[i + 1];
    const event = events.get(start);
    assessed += event.assessed;
    faults += event.faults;
    if (assessed <= 0) continue;
    const value = faults > 0 ? 1 : 0;
    if (start > after) samples.push({ ms: start, value });
    for (let ms = Math.floor(Math.max(start, after) / step) * step + step; ms < next; ms += step) {
      samples.push({ ms, value });
    }
  }
  return samples;
}

/** The two records (automation + model) of an equip + rule's timeline point; `through` (ms) = newest sample written so far. */
function timelineRecords({ equipRec, siteId, rule, shared, windowHours, key, runIso, through, sensor = null }) {
  const equipId = shared.idOf(equipRec);
  const uuid = timelineUuid(key, rule.id, sensor && sensor.series_id);
  const dis = `${(equipRec.attrs || {}).dis || equipRec.name} ${rule.id} fault timeline`;
  const name = `${siteEquipLabel(siteId, equipId)}/${rule.id}${sensor ? `/${sensor.name || sensor.series_id}` : ''}/timeline`;
  const attrs = { dis, markers: ['point', 'his', 'fault_timeline'].join(','), kind: 'Number', unit: '',
    siteRef: siteId, equipRef: equipId, ruleRef: rule.id, fddKind: 'fault-timeline', fddTimelineOf: sensor
      ? sensorResultUuid(key, rule.id, sensor.series_id) : resultUuid(key, rule.id),
    fddWindowHours: String(windowHours), fddLastRun: runIso };
  if (equipRec.uuid) attrs.equipUuid = equipRec.uuid;
  if (sensor) { attrs.sensorRef = sensor.series_id; attrs.roleRef = sensor.sensor_role; }
  if (Number.isFinite(through)) attrs.fddTimelineThrough = new Date(through).toISOString();
  return [
    { uuid, name, layer: 'automation', pointType: 'POINT', attrs: {
      application_id: APP_ID, type: 'fdd-fault-timeline', label: `${rule.id} timeline`, group_key: siteEquipLabel(siteId, equipId),
      description: `${rule.id} confirmed fault per assessed timestamp: 1 fault, 0 ok, no sample = not assessed`, units: '' } },
    { uuid, name, layer: 'model', attrs },
  ];
}

// ---- occupancy for rules whose occ_mode is optional and unbound -------------------------------------
const scheduleLib = require('../static/schedule.js');
const hostTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch (e) { return 'UTC'; } };

/**
 * { source: 'schedule' | 'default', label, tz, at(ms) -> occupied } for a site. NF schedules are read once per run
 * (cache.schedules) and never written. Timezone: the site record's tz / timezone, else the host's.
 */
async function siteOccupancy({ http, model, shared, siteId, cache }) {
  if (!cache.schedules) cache.schedules = scheduleLib.loadSchedules(async (p) => { const r = await http.get(p); return r && r.data; });
  const schedules = await cache.schedules;
  const site = model.sites.find((x) => shared.idOf(x) === siteId);
  const sa = (site && site.attrs) || {};
  const tz = sa.tz || sa.timezone || hostTz();
  const picked = scheduleLib.pickSiteSchedule(schedules, { sites: model.sites, points: model.points }, siteId);
  const sched = picked || scheduleLib.defaultSchedule(tz);
  return { source: picked ? 'schedule' : 'default', label: sched.label, tz, at: (ms) => scheduleLib.occupied(sched, ms, tz) };
}

/** Model record of a previously published result, flagged stale: nothing else about it changes. */
function staleRecord(rec, reason, runIso) {
  const attrs = { ...Object.fromEntries(OFDD_RESULT_ATTRS.map((k) => [k, ''])), ...(rec.attrs || {}) };
  attrs.fddCoverageHours = '';
  attrs.fddSensorFaultHours = '';
  attrs.fddStatus = 'stale'; attrs.fddReason = reason; attrs.fddLastRun = runIso;
  return { uuid: rec.uuid, name: rec.name, layer: 'model', attrs };
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
  // fault timelines: one entry per point with all its new samples, in the same batched AddData calls
  const seriesByUuid = new Map((queue.series || []).filter((s) => !failedMeta.has(s.uuid)).map((s) => [s.uuid, s]));
  for (const s of seriesByUuid.values()) pending.push({ uuid: s.uuid, values: s.values });
  const wrote = new Set();            // timeline uuids whose samples reached NF
  for (const chunk of chunkBySize(pending)) {
    try {
      const res = await postRetry(http, '/api/v1/points/data', { points: chunk }, counters.data, baseMs); const data = res && res.data;
      if (data && data.success === false) throw new Error('AddData success=false');
      for (const x of chunk) { if (seriesByUuid.has(x.uuid)) wrote.add(x.uuid); else summary.written++; }
    } catch (e) {
      failedData += chunk.length;
      log(`result values: ${chunk.length} points failed: ${errText(e)}`);
    }
  }
  // advance each timeline's fddTimelineThrough only now that its samples are in NF (a failed AddData is retried next run)
  const advance = [...seriesByUuid.values()].filter((s) => wrote.has(s.uuid));
  for (const chunk of chunkBySize(advance.map((s) => s.record))) {
    try { await postRetry(http, '/api/v1/point/points', { points: chunk }, counters.metadata, baseMs); }
    catch (e) { failedData += chunk.length; log(`timeline watermark: ${chunk.length} records failed (those samples are written again next run): ${errText(e)}`); }
  }
  summary.timeline = { points: advance.length, samples: advance.reduce((a, s) => a + s.values.length, 0) };
  summary.errors += failedMeta.size + failedData;
  summary.requests = { metadata: counters.metadata.n, data: counters.data.n };
}

// ---- run ----------------------------------------------------------------------------
/** True when the npm package @electric-sql/pglite is installed for this app (searched up from the hooks dir). */
function pgliteInstalled() {
  for (let d = __dirname, prev = ''; d !== prev; prev = d, d = path.dirname(d)) {
    if (fs.existsSync(path.join(d, 'node_modules', '@electric-sql', 'pglite', 'package.json'))) return true;
  }
  return false;
}

/**
 * Which engine to run. An engine the config names (sqlite | pglite | timescale) is used as is, never swapped.
 * Only when none was configured ("auto"/unset) is the choice ours: timescale if configured, else pglite on big
 * boxes, but sqlite (vendored, no npm install) when pglite is not installed. Returns {kind, note}.
 */
async function pickEngine(http, wanted, timescaleConfig, hasPglite = pgliteInstalled) {
  // FULL edition: config.timescale set -> run the pack inside NF's TimescaleDB (engine "timescale", or "auto")
  if (wanted === 'timescale' || ((!wanted || wanted === 'auto') && timescaleConfig)) return { kind: 'timescale', note: '' };
  if (wanted === 'sqlite' || wanted === 'pglite') return { kind: wanted, note: '' };
  let kind = 'sqlite';
  try {
    const { data } = await http.get('/api/v1/platform/info');
    const total = Math.max(0, ...((data && data.resources) || []).map((r) => Number((r.memory || {}).totalBytes) || 0));
    if (total >= PGLITE_MIN_BYTES) kind = 'pglite';
  } catch (e) {
    kind = 'sqlite';
  }
  if (kind === 'pglite' && !hasPglite()) {
    return { kind: 'sqlite', note: 'engine auto: pglite is not installed (install the app dependencies to use it); using sqlite' };
  }
  return { kind, note: '' };
}

/**
 * @typedef {{ engine?: string, windowHours?: number, equips?: string[], dryRun?: boolean,
 *   bacnet?: { enabled?: boolean, firstInstance?: number }, timescale?: object, writeRetryMs?: number }} FddConfig
 * @param {{ sdk: any, config?: FddConfig, createEngine?: Function, pack?: any, now?: number, hasPglite?: () => boolean }} args
 */
async function runFdd({ sdk, config: rawConfig = {}, createEngine, pack: packIn, now = Date.now(), hasPglite }) {
  createEngine = createEngine || require('./lib/engines.js').createEngine;
  // NF hands the app options over as ctx.config: strings for numbers and JSON (lib/settings.js converts them)
  const config = /** @type {FddConfig} */ (settings.normalizeConfig(rawConfig));
  const http = sdk.http;
  const log = (m) => (sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const shared = loadShared();
  const { kind, note: engineNote } = await pickEngine(http, config.engine, config.timescale, hasPglite);
  if (engineNote) log(engineNote);
  const pack = packIn || loadPack(kind);
  const step = pack.poll_seconds;
  const windowHours = Number(config.windowHours) > 0 ? Number(config.windowHours) : 24;
  const to = Math.floor(now / (step * 1e3)) * step * 1e3;
  const from = to - windowHours * 3600e3;
  const grid = [];
  for (let t = from; t < to; t += step * 1e3) grid.push(t);

  const model = await loadModel(http, shared);
  const modelProblem = modelProblemOf(model);
  const only = Array.isArray(config.equips) && config.equips.length ? new Set(config.equips) : null;
  const runIso = new Date(now).toISOString();
  const summary = { engine: kind, engine_configured: config.engine || 'auto', engine_note: engineNote, equips: 0, rules: 0, errors: 0, written: 0, results: [],
    sensor_results: { total: 0, ok: 0, fault: 0, 'not-assessed': 0, stale: 0 },
    status: { ok: 0, fault: 0, 'not-assessed': 0, stale: 0 }, requests: { metadata: 0, data: 0 },
    // loud-failure bookkeeping (#1550): what was eligible, what was skipped and why, how fresh the input was
    eligible: 0, skipped: [], stale_reasons: {}, failure: null, roles_skipped_by_unit: {},
    window: { from: new Date(from).toISOString(), to: new Date(to).toISOString(), hours: windowHours },
    source_freshness: { engine: kind, newest_sample: null, age_minutes: null, nf_latest: isoOrNull(newestLatest(model.points)), nf_latest_age_minutes: null } };
  let sourceNewest = null;                               // newest input sample the engine could see (ms)
  const seenUuids = new Set();                           // every input point of the run (timescale: one freshness query at the end)
  const queue = { meta: [], values: [], series: [] };    // writes, flushed in batches after all equips ran
  const occCache = { logged: new Set() };    // NF schedules (read once per run) and which sites were logged
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
      let defaultReason = 'rule was not run for this equip (not applicable, or required roles missing)';
      let eligible = false;       // had results published before, or has a runnable rule now
      // Why this equip produced nothing: one of the three stale reasons, never a catch-all (#1550).
      const skip = (kind, detail) => {
        defaultReason = detail;
        if (eligible) summary.skipped.push({ site: siteId, equip: equipId, kind, detail });
      };
      try {
        const bound = shared.equipRules(equipRec, model, shared.catalog).filter((r) => pack.rules[r.rule.id]);
        for (const r of bound) {
          if (!r.runnable) reasons.set(r.rule.id, `required roles missing (${r.missing.length ? r.missing.join(', ') : 'no input role is bound'})`);
        }
        let runnable = bound.filter((r) => r.runnable);
        const hadResults = Object.keys(pack.rules).some((id) => model.results.has(resultUuid(key, id)));
        eligible = hadResults || runnable.length > 0;
        if (eligible) summary.eligible++;
        if (!runnable.length) {
          if (!model.points.length) skip('model-incomplete', 'model incomplete: no points were loaded for any site (not a missing role)');
          else skip('roles-missing', 'required roles missing (no rule has all its required roles bound to points of this equip)');
          continue;
        }
        let roles = roleInputs(runnable);
        const si = siPlan(roles, shared.catalog, log, warnedUnits);
        const sweepSensors = [];
        for (const r of runnable) {
          if (!pack.rules[r.rule.id].output_columns?.includes('series_id')) continue;
          for (const [role, points] of Object.entries(r.bound || {})) {
            if (!isSweepSensorRole(role, shared.catalog)) continue;
            for (const point of points || []) {
              let sensor = sweepSensors.find((s) => s.point.uuid === point.uuid);
              if (!sensor) { sensor = { role, point, ruleIds: new Set() }; sweepSensors.push(sensor); }
              sensor.ruleIds.add(r.rule.id);
            }
          }
        }
        if (si.skipped.size) {
          const bad = [...si.skipped].sort().join(', ');
          for (const role of si.skipped) if (!sweepSensors.some((sensor) => sensor.role === role))
            summary.roles_skipped_by_unit[role] = (summary.roles_skipped_by_unit[role] || 0) + 1;
          for (const r of runnable) {
            const hit = r.required.filter((x) => si.skipped.has(x));
            if (hit.length) reasons.set(r.rule.id, `unit unusable (role ${hit.join(', ')}: unknown or missing unit on the point)`);
          }
          runnable = runnable.filter((r) => !r.required.some((x) => si.skipped.has(x)));
          roles = roleInputs(runnable);
          for (const x of si.skipped) delete roles[x];
          if (!runnable.length) {
            skip('unit-unusable', `unit unusable (role ${bad}: unknown or missing unit on the point)`);
            continue;
          }
        }
        const uuids = [...new Set([...Object.values(roles).map((p) => p.uuid), ...sweepSensors.map((s) => s.point.uuid)])];
        uuids.forEach((u) => seenUuids.add(u));
        let newestHere = null;        // newest sample of this equip's inputs (ms): from the engine's own source
        let loadedRows;
        let histByTs = null;          // ms -> history row (which required inputs exist at a timestamp); not on timescale
        let occ = null;               // synthesized occupancy: a runnable rule has occ_mode optional and no point is bound
        if (kind !== 'timescale' && !roles.occ_mode && runnable.some((r) => r.optional.includes('occ_mode'))) {
          try {
            occ = await siteOccupancy({ http, model, shared, siteId, cache: occCache });
            if (!occCache.logged.has(siteId)) {
              occCache.logged.add(siteId);
              log(`${siteId || 'site'}: occ_mode synthesized from ${occ.source} (${occ.label}, ${occ.tz})`);
            }
          } catch (e) { log(`${equipId}: occupancy schedule unavailable (${errText(e)}); occ_mode not synthesized`); }
        }
        if (kind === 'timescale') {   // SQL builds the wide and per-series sweep inputs from stored SI data
          const roleToUuid = Object.fromEntries(Object.entries(roles).map(([r, p]) => [r, p.uuid]));
          const unitsByUuid = Object.fromEntries([...Object.values(roles), ...sweepSensors.map((s) => s.point)].map((p) => [p.uuid, p.units || '']));
          const sensorPlan = buildSensorInput({ equipId, sensors: sweepSensors, hist: {}, grid: [], catalog: shared.catalog, log, warned: warnedUnits });
          for (const [role, count] of Object.entries(sensorPlan.skipped)) summary.roles_skipped_by_unit[role] = (summary.roles_skipped_by_unit[role] || 0) + count;
          loadedRows = await engine.load({ equipId, siteId, roleToUuid, unitsByUuid,
            sensorSeries: sensorPlan.sensorSeries, fractionRoles: [...si.scaled], booleanRoles: [...si.bool], from, to, stepSec: step });
          if (!loadedRows && engine.newestSample) {   // empty window: when did these points last have a sample at all?
            try { newestHere = await engine.newestSample(uuids); } catch (e) { log(`${equipId}: newest-sample lookup failed: ${errText(e)}`); }
          }
        } else {
          const hist = await fetchHistory(http, uuids, from, to, step);
          newestHere = newestOfHistory(hist);
          const input = buildInput({ equipId, siteId, roles, hist, grid, pack, si, occ: occ && occ.at });
          const long = buildSensorInput({ equipId, sensors: sweepSensors, hist, grid, catalog: shared.catalog, log, warned: warnedUnits });
          for (const [role, count] of Object.entries(long.skipped)) summary.roles_skipped_by_unit[role] = (summary.roles_skipped_by_unit[role] || 0) + count;
          input.sensorSeries = long.sensorSeries;
          input.sensorHistory = long.sensorHistory;
          loadedRows = input.history.length + input.sensorHistory.length;
          histByTs = new Map(input.history.map((row) => [row.ts, row]));
          if (loadedRows) await engine.load(input);
        }
        if (newestHere != null) sourceNewest = Math.max(sourceNewest == null ? -Infinity : sourceNewest, newestHere);
        if (!loadedRows) {
          if (newestHere == null) newestHere = newestLatest(Object.values(roles));   // history sources gave nothing: NF's latest values
          const detail = `no input data in window (newest sample at ${newestHere != null ? new Date(newestHere).toISOString() : 'unknown: none found'})`;
          skip('no-data', detail);
          log(`${equipId}: ${detail}, skipped (window ${summary.window.from} .. ${summary.window.to}, engine ${kind})`);
          continue;
        }
        defaultReason = 'rule was not run for this equip (not applicable, or required roles missing)';
        summary.equips++;
        const records = [];
        const values = [];
        const timelines = [];         // { records, series } per fault rule with a timeline_sql
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
          const packRule = pack.rules[r.rule.id];
          const ruleSensors = packRule.output_columns?.includes('series_id') ? sweepSensors : [];
          const ruleRows = [...(rows || [])];
          for (const sensor of ruleSensors) if (!ruleRows.some((x) => x.equipment_id === equipId && x.series_id === sensor.point.uuid)) {
            ruleRows.push({ equipment_id: equipId, series_id: sensor.point.uuid, sensor_role: sensor.role, fault_hours: null, covered_hours: 0 });
          }
          const row = equipmentResult(packRule, ruleRows, equipId,
            Object.fromEntries(ruleSensors.map((sensor) => [sensor.point.uuid, sensor.point.dis || sensor.point.name || sensor.point.uuid])));
          const out = resultValue(packRule, row);
          const sensorFaultHours = row && row.sensor_fault_hours;
          const perSensor = row && row.sensor_rows || [];
          const sensorById = new Map(ruleSensors.map((sensor) => [sensor.point.uuid, {
            series_id: sensor.point.uuid, sensor_role: sensor.role, name: sensor.point.dis || sensor.point.name,
          }]));
          if (engine.resultRow && perSensor.length) {
            for (const sensorRow of perSensor) dbRows.push(engine.resultRow({ runTs: to, equip: equipId, site: siteId,
              ruleId: r.rule.id, row: sensorRow, windowStart: from, windowEnd: to }));
            if (row) dbRows.push(engine.resultRow({ runTs: to, equip: equipId, site: siteId, ruleId: r.rule.id,
              row, windowStart: from, windowEnd: to }));
          }
          if (perSensor.length) {
            for (const sensorRow of perSensor) {
              const sensor = sensorById.get(sensorRow.series_id) || { series_id: sensorRow.series_id, sensor_role: sensorRow.sensor_role, name: sensorRow.series_id };
              const sensorOut = resultValue(packRule, sensorRow);
              summary.sensor_results.total++;
              summary.sensor_results[sensorOut.status]++;
              const sensorUuid = sensorResultUuid(key, r.rule.id, sensor.series_id);
              touched.add(sensorUuid);
              const prevSensor = model.results.get(sensorUuid);
              records.push(...resultRecords({ equipRec, siteId, rule: r.rule, out: sensorOut, shared, windowHours, key, runIso,
                sensor, previous: prevSensor, outputSince: new Date(to).toISOString() }));
              if (sensorOut.status !== 'not-assessed') values.push({ uuid: sensorUuid, value: sensorOut.value });
            }
          }
          summary.status[out.status]++;
          if (out.status !== 'not-assessed') {
            summary.results.push({ site: siteId, equip: equipId, rule: r.rule.id, value: out.value, unit: out.unit, fault: out.fault, status: out.status,
              ...(sensorFaultHours ? { sensor_fault_hours: sensorFaultHours } : {}) });
            if (engine.resultRow && !perSensor.length) dbRows.push(engine.resultRow({ runTs: to, equip: equipId, site: siteId, ruleId: r.rule.id, row, windowStart: from, windowEnd: to }));
          }
          const uuid = resultUuid(key, r.rule.id);
          touched.add(uuid);
          const usesOcc = r.required.includes('occ_mode') || r.optional.includes('occ_mode');
          const occSource = usesOcc ? (roles.occ_mode ? 'point' : occ ? occ.source : undefined) : undefined;
          records.push(...resultRecords({ equipRec, siteId, rule: r.rule, out, shared, windowHours, key, runIso, occSource,
            sensorFaultHours, previous: model.results.get(uuid), outputSince: new Date(to).toISOString() }));
          if (out.status !== 'not-assessed') values.push({ uuid, value: out.value });
          if (out.kind === 'fault' && !config.dryRun && engine.timeline && pack.rules[r.rule.id].timeline_sql) {
            try {
              const timelineRows = await engine.timeline(r.rule.id);
              const sensorTimelineRows = timelineRows?.some((x) => x.series_id) ? timelineRows : null;
              if (sensorTimelineRows) {
                const timelineBySeries = new Map();
                for (const event of sensorTimelineRows) {
                  if (!event.series_id) continue;
                  if (!timelineBySeries.has(event.series_id)) timelineBySeries.set(event.series_id, []);
                  timelineBySeries.get(event.series_id).push(event);
                }
                for (const sensorRow of perSensor) {
                  const sensor = sensorById.get(sensorRow.series_id) || { series_id: sensorRow.series_id, sensor_role: sensorRow.sensor_role, name: sensorRow.series_id };
                  const tuuid = timelineUuid(key, r.rule.id, sensor.series_id);
                  const prev = model.timelines.get(tuuid);
                  const prevThrough = prev ? Date.parse((prev.attrs || {}).fddTimelineThrough || '') : NaN;
                  const samples = timelineSamples(timelineBySeries.get(sensor.series_id) || [], { equipId, seriesId: sensor.series_id,
                    after: Number.isFinite(prevThrough) ? prevThrough : -Infinity, stepSec: pack.poll_seconds });
                  const [auto, model2] = timelineRecords({ equipRec, siteId, rule: r.rule, shared, windowHours, key, runIso,
                    through: prevThrough, sensor });
                  const t = { records: [auto, model2], series: null };
                  if (samples.length) {
                    const through = samples[samples.length - 1].ms;
                    t.series = { uuid: tuuid, values: samples.map((x) => ({ ts: new Date(x.ms).toISOString(), real: x.value })),
                      record: { ...model2, attrs: { ...model2.attrs, fddTimelineThrough: new Date(through).toISOString() } } };
                  }
                  timelines.push(t);
                }
                // Keep the documented equipment timeline as "any sensor faulting" for older readers.
                const equipTimelineUuid = timelineUuid(key, r.rule.id);
                const equipPrev = model.timelines.get(equipTimelineUuid);
                const equipThrough = equipPrev ? Date.parse((equipPrev.attrs || {}).fddTimelineThrough || '') : NaN;
                const equipSamples = timelineSamples(sensorTimelineRows, { equipId,
                  after: Number.isFinite(equipThrough) ? equipThrough : -Infinity, stepSec: pack.poll_seconds });
                const [equipAuto, equipModel] = timelineRecords({ equipRec, siteId, rule: r.rule, shared, windowHours, key,
                  runIso, through: equipThrough });
                const equipT = { records: [equipAuto, equipModel], series: null };
                if (equipSamples.length) {
                  const through = equipSamples[equipSamples.length - 1].ms;
                  equipT.series = { uuid: equipTimelineUuid, values: equipSamples.map((x) => ({ ts: new Date(x.ms).toISOString(), real: x.value })),
                    record: { ...equipModel, attrs: { ...equipModel.attrs, fddTimelineThrough: new Date(through).toISOString() } } };
                }
                timelines.push(equipT);
              } else {
              const tuuid = timelineUuid(key, r.rule.id);
              const prev = model.timelines.get(tuuid);
              const prevThrough = prev ? Date.parse((prev.attrs || {}).fddTimelineThrough || '') : NaN;
              // a timestamp is assessed only when every REQUIRED input of the rule has a value there (unknown is not ok)
              const assessed = histByTs ? (ms) => { const row = histByTs.get(ms); return !!row && r.required.every((role) => row[role] != null); } : null;
              const samples = timelineSamples(timelineRows,
                { assessed, equipId, after: Number.isFinite(prevThrough) ? prevThrough : -Infinity, stepSec: pack.poll_seconds });
              const [auto, model2] = timelineRecords({ equipRec, siteId, rule: r.rule, shared, windowHours, key, runIso, through: prevThrough });
              const t = { records: [auto, model2], series: null };
              if (samples.length) {
                const through = samples[samples.length - 1].ms;
                t.series = { uuid: tuuid, values: samples.map((x) => ({ ts: new Date(x.ms).toISOString(), real: x.value })),
                  record: { ...model2, attrs: { ...model2.attrs, fddTimelineThrough: new Date(through).toISOString() } } };
              }
              timelines.push(t);
              }
            } catch (e) {
              summary.errors++;
              log(`${equipId} ${r.rule.id} timeline: ${errText(e)}`);
            }
          }
        }
        if (config.dryRun) continue;
        if (dbRows.length) await engine.writeResults(dbRows);   // timescale: also keep results in the database
        if (!records.length) continue;
        queue.meta.push(...records);
        for (const t of timelines) { queue.meta.push(...t.records); if (t.series) queue.series.push(t.series); }
        const ts = new Date(to).toISOString();
        for (const v of values) queue.values.push({ uuid: v.uuid, ts, value: v.value });
      } catch (e) {
        summary.errors++;
        defaultReason = `run error: ${errText(e)}`;
        log(`${equipId}: ${errText(e)}`);
      } finally {
        // previously published results this run did not refresh: flag, never overwrite with a number
        const stale = [];
        for (const [uuid, prev] of model.results) {
          const attrs = prev.attrs || {};
          const ruleId = attrs.ruleRef;
          if (!pack.rules[ruleId] || touched.has(uuid)) continue;
          const expectedUuid = attrs.sensorRef
            ? sensorResultUuid(key, ruleId, attrs.sensorRef)
            : resultUuid(key, ruleId);
          if (uuid !== expectedUuid) continue;
          const why = reasons.get(ruleId) || defaultReason;
          stale.push(staleRecord(prev, why, runIso));
          if (attrs.sensorRef) {
            summary.sensor_results.total++;
            summary.sensor_results.stale++;
            const timeline = model.timelines.get(timelineUuid(key, ruleId, attrs.sensorRef));
            if (timeline) stale.push(staleRecord(timeline, why, runIso));
          } else {
            summary.status.stale++;
            const bucket = why.replace(/\s*\(.*$/s, '').slice(0, 60);   // group by the reason, not its details
            summary.stale_reasons[bucket] = (summary.stale_reasons[bucket] || 0) + 1;
          }
        }
        if (stale.length && !config.dryRun) queue.meta.push(...stale);
      }
    }
    if (!config.dryRun) {
      const retryMs = Number(config.writeRetryMs) >= 0 && config.writeRetryMs != null ? Number(config.writeRetryMs) : RETRY_BASE_MS;
      await flushWrites(http, queue, summary, log, retryMs);
    }
    if (kind === 'timescale' && engine.newestSample && seenUuids.size) {   // freshness of the source the engine reads
      try { sourceNewest = maxOrNull([sourceNewest, await engine.newestSample([...seenUuids])]); } catch (e) { log(`newest-sample lookup failed: ${errText(e)}`); }
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
  const skippedRoles = Object.entries(summary.roles_skipped_by_unit).filter(([, n]) => n > 0).sort(([a], [b]) => a.localeCompare(b));
  const skippedRoleCount = skippedRoles.reduce((n, [, count]) => n + count, 0);
  const unitSkipText = `roles skipped by unit: ${skippedRoleCount} (${skippedRoles.length ? skippedRoles.map(([role, count]) => `${role} ${count}`).join(', ') : 'none'})`;
  summary.roles_skipped_by_unit_total = skippedRoleCount;
  const fresh = summary.source_freshness;
  fresh.newest_sample = isoOrNull(sourceNewest);
  fresh.age_minutes = sourceNewest == null ? null : Math.round((now - sourceNewest) / 60e3);
  fresh.nf_latest_age_minutes = fresh.nf_latest ? Math.round((now - Date.parse(fresh.nf_latest)) / 60e3) : null;
  // eligible equips (had results, or have runnable rules) but not one output freshly assessed: this run did nothing useful
  if (!config.dryRun && summary.eligible > 0 && st.ok + st.fault === 0) {
    summary.failure = `no fresh results were written for any of ${summary.eligible} eligible equips`;
  }
  // An empty / incomplete MODEL is its own failure with its own reason: never "required roles missing" (#1550)
  if (modelProblem) summary.failure = modelProblem;
  for (const line of runReport(summary, windowHours)) log(line);
  log(`open-fdd ${kind}: ${summary.equips} equips, ${summary.rules} rule runs, ${summary.errors} errors, `
    + `${faults.length} with fault time, ${summary.written} values written (window ${windowHours} h); `
    + `ok ${st.ok}, fault ${st.fault}, not-assessed ${st['not-assessed']}, stale ${st.stale}; `
    + `requests: ${summary.requests.metadata} metadata, ${summary.requests.data} data; ${unitSkipText}`);
  return summary;
}

/**
 * Why the model cannot be evaluated at all, or null when it can. "0 equipment" is NOT "required roles missing": it
 * means the model layer was not read completely (paging, #1550), was emptied, or was never built. The text says how
 * many records were read of how many NF reported, and whether results published earlier prove equipment existed.
 * @param {{ sites: any[], equips: any[], points: any[], results: Map<any, any>, read?: { records: number, total: any } }} model
 */
function modelProblemOf(model) {
  const r = model.read || { records: 0, total: null };
  const read = `${r.records} model records read${r.total != null ? ` of totalCount ${r.total}` : ''}`;
  const counts = `${model.sites.length} sites, ${model.equips.length} equipment, ${model.points.length} points`;
  if (!model.equips.length) {
    const had = model.results.size;
    return had
      ? `model incomplete: 0 equipment resolved from the model layer (${counts}; ${read}) although ${had} published results exist; `
        + 'the model layer was not read completely or its equipment records are gone'
      : `model empty: 0 equipment resolved from the model layer (${counts}; ${read}); model the site's equipment in NF (Haystack) first`;
  }
  if (!model.points.length) {
    return `model incomplete: ${model.equips.length} equipment but 0 points loaded (${counts}; ${read}); `
      + `${model.sites.length ? 'the per-site point query returned nothing' : 'no SITE record was found, so no points were queried'}`;
  }
  return null;
}

/** Always-logged run report: engine and window, input freshness, evaluated / written / skipped / stale with reasons. */
function runReport(s, windowHours) {
  const tally = (items, f) => Object.entries(items.reduce((a, x) => ({ ...a, [f(x)]: (a[f(x)] || 0) + 1 }), {}))
    .map(([k, n]) => `${k} x${n}`).join('; ') || 'none';
  const fr = s.source_freshness;
  const age = (m) => (m == null ? '' : ` (${m} min ago)`);
  const lines = [
    `open-fdd run: engine ${s.engine}, data window ${s.window.from} .. ${s.window.to} (${windowHours} h); `
    + `newest input sample in the ${s.engine} source ${fr.newest_sample || 'not read'}${age(fr.age_minutes)}, `
    + `NF latest value ${fr.nf_latest || 'none'}${age(fr.nf_latest_age_minutes)}`,
    `open-fdd counts: eligible ${s.eligible}, evaluated ${s.equips}, written ${s.written}, skipped ${s.skipped.length}, stale ${s.status.stale}; `
    + `skipped by reason: ${tally(s.skipped, (x) => x.kind)}; stale by reason: ${Object.entries(s.stale_reasons).map(([k, n]) => `${k} x${n}`).join('; ') || 'none'}`,
  ];
  for (const x of s.skipped.slice(0, 20)) lines.push(`open-fdd skipped ${x.site ? `${x.site}/` : ''}${x.equip}: ${x.detail}`);
  if (s.skipped.length > 20) lines.push(`open-fdd skipped: ${s.skipped.length - 20} more equips (same format)`);
  if (s.failure) lines.push(`open-fdd FAILED: ${s.failure}`);
  return lines;
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
    if (r.value > 0 && !byEquip.get(k).rules.includes(r.rule)) byEquip.get(k).rules.push(r.rule);
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
  const st = summary.status;
  if (summary.errors || summary.failure) {
    const fr = summary.source_freshness;
    const why = Object.entries(summary.stale_reasons).map(([k, n]) => `${k} x${n}`).join('; ');
    const skipped = Object.entries(summary.skipped.reduce((a, x) => ({ ...a, [x.kind]: (a[x.kind] || 0) + 1 }), {})).map(([k, n]) => `${k} x${n}`).join('; ');
    const err = new Error((summary.errors ? `open-fdd: ${summary.errors} error${summary.errors === 1 ? '' : 's'} during the run (see the log); ` : 'open-fdd: ')
      + (summary.failure ? `${summary.failure}; ` : '')
      + `ok ${st.ok}, fault ${st.fault}, not-assessed ${st['not-assessed']}, stale ${st.stale}; `
      + `eligible ${summary.eligible}, evaluated ${summary.equips}, written ${summary.written}, skipped ${summary.skipped.length}${skipped ? ` (${skipped})` : ''}`
      + `${why ? `; stale reasons: ${why}` : ''}; engine ${summary.engine}, window ${summary.window.from} .. ${summary.window.to}; `
      + `newest input sample ${fr.newest_sample || 'not read'}, NF latest value ${fr.nf_latest || 'none'}`);
    /** @type {any} */ (err).summary = summary;
    throw err;
  }
  return summary;
}
module.exports = Object.assign(hook, { runFdd, modelProblemOf, loadModel, pickEngine, pgliteInstalled, nameUuid, resultKey, resultUuid, sensorResultUuid, timelineUuid, timelineSamples, buildInput, buildSensorInput, siPlan, resultValue, equipmentResult, resultRecords, OFDD_RESULT_ATTRS, bacnetPlan, chunkBySize });
