// SPARQL data: on-request hook (FULL edition). Query the site model, get the matched points' trend data back.
//
//   POST /api/v1/apps/open-fdd/hooks/sparql-data   flat string map (NF StartHook), e.g.
//        {"query": "SELECT ?uuid WHERE { ... }", "from": "2026-11-01T00:00:00Z", "to": "2026-11-02T00:00:00Z",
//         "bucket": "5 minutes"}
//   GET  /api/v1/apps/open-fdd/hooks/sparql-data/runs?include_results=true&include_logs=true   -> the answer (JSON event line)
//
// The query runs on the same Turtle as the Model & RDF tab and the `sparql` hook (static/model.js modelToTurtle, Oxigraph).
// Read-only: SELECT and ASK only (no CONSTRUCT / DESCRIBE, no updates, no SERVICE). PREFIXes the model declares are
// added when the query leaves them out. The time-series ids are taken from one result column: args.uuidVar, else the
// first of uuid / tsId / timeseriesId / point / p whose values name model points (a uuid literal or a point IRI), else
// any column that does. Values that are not points of this model are never fetched.
//
// Args: query; from / to (ISO, `to` exclusive) or windowHours (default 24); bucket "raw" | "<n> minutes|hours|days"
// (default "5 minutes"); source auto | nf | timescale (auto = Timescale when configured and not raw, else NF
// point/data); pointOffset / pointLimit (<= 200); includeRows (default true); uuidVar; maxBytes / maxRows (lower only).
//
// Answer: {ok, kind, vars, rows: [{var: text}], rows_total, rows_truncated, uuid_var, points_total, point_offset,
//   next_point_offset | null, points: {uuid: {dis, unit, kind, cls, tags, equip, site, weather, role}},
//   equips: [{site, id, dis, tags}], source, bucket,
//   window_sec, from, to, complete, next_from | null, series: {uuid: [[epoch_ms, value], ...]}, samples,
//   operating_status: [{site, equip, uuid | null, source, tier, via, unit}], run_proof_series: {uuid: [[epoch_ms, value], ...]}}.
// operating_status (#1635) is the run proof the FDD hook resolves for each returned equipment (own status, own command, or
// the feeding equipment's; static/run-proof.js); uuid null = none bound, so client rules gated on it are SKIPPED
// no_run_proof like the hook and SQL. Proof points that are not on this page come back in run_proof_series, cut on the
// same timestamp as series.
// Values are in each point's stored unit (convert to SI on the client: open_fdd.nf.sparql_data). When the answer would
// pass maxBytes it is cut on a timestamp: every point is complete before next_from, page on from there. More points
// than pointLimit page with pointOffset; nothing is dropped silently. Errors are {ok: false, error, error_code?}.
// Nothing site-specific here.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const rdf = require('./rdf.js');
const { Worker } = require('worker_threads');
const crypto = require('crypto');
const startArgs = require('./lib/start-hook-args.js');
const settings = require('./lib/settings.js');

const sparqlLib = () => require('../static/sparql.js');
const oxigraph = () => {
  try { return require(/** @type {string} */ ('oxigraph')); }
  catch (e) { throw new Error(`oxigraph is not installed (${e && e.message}). Install the app dependencies.`); }
};

const LIMITS = {
  pointLimit: 200,          // points per answer (same as the history hook's uuid cap)
  maxBytes: 190000,         // answer text (NF keeps it as one event line)
  maxRows: 5000,            // SPARQL rows returned
  nfSpanDays: 31,           // NF point/data per answer
  timescaleSpanDays: 366,
  nfRequests: 400,          // point/data calls per run
  nfSampleCap: 10000,       // NF returns at most this many samples per series and call
  maxTriples: 500000,
  maxRssGrowthMb: 256,      // process RSS growth while the query worker runs (WebAssembly is outside the V8 heap)
};
const UUID_VARS = ['uuid', 'tsId', 'timeseriesId', 'point', 'p'];
const NF_BATCH = 20;
const CHUNK_MS = 7 * 86400e3;
const UNIT_SECS = { minute: 60, hour: 3600, day: 86400 };
const BUCKET_RE = /^\s*(\d+)\s*(minute|hour|day)s?\s*$/i;

const argsOf = (ctx) => startArgs.startHookArgs(ctx, {
  numberFields: ['windowHours', 'pointOffset', 'pointLimit', 'maxBytes', 'maxRows', 'nfSampleCap'],
  // windowHours stays a window length: validateArgs turns it into a bucket-aligned window (expanding it here to
  // unaligned ISO bounds made every windowHours-only bucketed request fail as "unaligned").
  booleanFields: ['includeRows'],
});

const lower = (v, cap) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Math.min(Math.floor(Number(v)), cap) : cap);
const time = (v, name) => {
  const ms = typeof v === 'number' ? v : Date.parse(String(v || ''));
  if (!Number.isFinite(ms) || ms <= 0) throw new Error(`args.${name} must be an ISO time`);
  return ms;
};

/** Run in a disposable worker: hard wall-clock limit, bounded V8 heap, and an RSS watchdog (Oxigraph's WebAssembly
 * memory, store plus ORDER BY / GROUP BY / DISTINCT buffers, is outside the V8 heap limit but shows in the process RSS).
 * A worker failure never falls back to synchronous evaluation in NF's application thread. SELECT gets an engine-side cap
 * in sparql-worker.js. */
function evaluate(turtle, query, { timeoutMs = 15000, cap = LIMITS.maxRows, maxGrowthMb = LIMITS.maxRssGrowthMb,
  rss = () => process.memoryUsage().rss, everyMs = 50 } = {}) {
  return new Promise((resolve, reject) => {
    const base = rss();
    const worker = new Worker(path.join(__dirname, 'lib', 'sparql-worker.js'), {
      workerData: { ofddSparqlWorker: true }, resourceLimits: { maxOldGenerationSizeMb: 128, maxYoungGenerationSizeMb: 16 },
    });
    let done = false;
    const finish = (error, value) => {
      if (done) return; done = true; clearTimeout(timer); clearInterval(watch); worker.terminate();
      if (error) reject(error); else resolve(value);
    };
    const timer = setTimeout(() => finish(new Error('SPARQL query exceeded wall-clock limit')), Math.min(15000, timeoutMs));
    const watch = setInterval(() => {
      if (rss() - base > maxGrowthMb * 1048576) {
        finish(Object.assign(new Error(`SPARQL query exceeded the memory limit (${maxGrowthMb} MB); narrow it (ORDER BY / GROUP BY / DISTINCT over a large join buffer every solution)`), { code: 'too_large' }));
      }
    }, everyMs);
    worker.on('error', e => finish(e));
    worker.on('exit', code => { if (!done) finish(new Error('SPARQL worker exited before answering: ' + code)); });
    worker.on('message', msg => finish(msg.ok ? null : new Error(msg.error), msg.r));
    worker.postMessage({ turtle, query, cap, maxTriples: LIMITS.maxTriples });
  });
}
const bytes = value => Buffer.byteLength(JSON.stringify(value), 'utf8');

/** Checked, defaulted arguments (throws Error naming the bad one). */
function validateArgs(args = {}, { now = Date.now() } = {}) {
  const query = args.query;
  const { form } = sparqlLib().sparqlCheckQuery(query);   // read-only policy, size cap
  if (form !== 'SELECT' && form !== 'ASK') throw new Error(`only SELECT and ASK are allowed here (got ${form}); use the sparql hook for graphs`);
  let from = args.from, to = args.to;
  if ((from == null || from === '') && (to == null || to === '')) {
    const h = Number(args.windowHours) > 0 ? Number(args.windowHours) : 24;
    to = now; from = now - h * 3600e3;
  }
  const defaulted = (args.from == null || args.from === '') && (args.to == null || args.to === '');
  let f = time(from, 'from'), t = time(to, 'to');
  if (t <= f) throw new Error('args.from must be before args.to');
  const bucketText = args.bucket == null || args.bucket === '' ? '5 minutes' : String(args.bucket).trim();
  let windowSec = 0;
  if (bucketText.toLowerCase() !== 'raw') {
    const m = BUCKET_RE.exec(bucketText);
    if (!m || Number(m[1]) < 1) throw new Error('args.bucket must be "raw" or like "5 minutes", "1 hour", "1 day"');
    windowSec = Number(m[1]) * UNIT_SECS[m[2].toLowerCase()];
    // Buckets are aligned to the Unix epoch. A window edge inside a bucket would answer a partial bucket under the
    // full bucket's timestamp, and the next page would answer the rest under the same timestamp (5.0.20): so a
    // bucketed window must start and end on bucket boundaries. The defaulted window is widened to them.
    const w = windowSec * 1000;
    if (defaulted) { f = Math.floor(f / w) * w; t = Math.ceil(t / w) * w; }
    else if (f % w || t % w) {
      throw Object.assign(new Error(`args.from and args.to must be multiples of the bucket (${bucketText}, aligned to the Unix epoch)`), { code: 'unaligned' });
    }
  }
  const source = String(args.source || 'auto').toLowerCase();
  if (!['auto', 'nf', 'timescale'].includes(source)) throw new Error('args.source must be auto, nf or timescale');
  if (source === 'timescale' && !windowSec) throw new Error('bucket "raw" needs source nf (Timescale answers buckets)');
  const spanDays = (t - f) / 86400e3;
  const capDays = source === 'timescale' ? LIMITS.timescaleSpanDays : LIMITS.nfSpanDays;
  if (spanDays > capDays) throw new Error(`time span is longer than ${capDays} days for source ${source}; page the range`);
  const pointOffset = args.pointOffset == null || args.pointOffset === '' ? 0 : Number(args.pointOffset);
  if (!Number.isInteger(pointOffset) || pointOffset < 0) throw new Error('args.pointOffset must be a non-negative integer');
  return {
    query, form, from: new Date(f).toISOString(), to: new Date(t).toISOString(), fromMs: f, toMs: t,
    bucket: windowSec ? bucketText : 'raw', windowSec, source,
    pointOffset, pointLimit: lower(args.pointLimit, LIMITS.pointLimit),
    maxBytes: lower(args.maxBytes, LIMITS.maxBytes), maxRows: lower(args.maxRows, LIMITS.maxRows),
    nfSampleCap: lower(args.nfSampleCap, LIMITS.nfSampleCap),
    includeRows: args.includeRows !== false && args.includeRows !== 'false',
    uuidVar: args.uuidVar ? String(args.uuidVar).replace(/^[?$]/, '') : '',
  };
}

/** The query with the model's PREFIX lines put in front of those it does not declare itself. */
function withPrefixes(query, turtle) {
  const declared = new Set([...String(query).matchAll(/PREFIX\s+([A-Za-z0-9_-]*):/gi)].map((m) => m[1]));
  const missing = sparqlLib().sparqlPrefixes(turtle).split('\n').filter((l) => {
    const m = /^PREFIX\s+([A-Za-z0-9_-]*):/.exec(l);
    return m && !declared.has(m[1]);
  });
  return missing.length ? missing.join('\n') + '\n' + query : query;
}

/** NF sample -> number | string | null (same reading as the fdd hook, plus text). */
function sampleValue(v) {
  if (!v) return null;
  for (const k of ['double', 'real', 'unsigned', 'signed', 'enumerated']) if (v[k] != null) return Number(v[k]);
  if (v.boolean != null) return v.boolean === true || v.boolean === 'true' ? 1 : 0;
  if (v.string != null) return String(v.string);
  return null;
}
const tsMs = (ts) => Date.parse(String(ts).replace(/(\.\d{3})\d+/, '$1'));

/** {uuid: [[ms, value]]} from NF point/data: <= 20 uuids and <= 7 days a call; a series at NF's sample cap is split. */
async function nfSeries(http, uuids, a) {
  const out = Object.fromEntries(uuids.map((u) => [u, []]));
  let requests = 0;
  const call = async (ids, f, t, depth) => {
    if (++requests > LIMITS.nfRequests) throw Object.assign(new Error(`more than ${LIMITS.nfRequests} NF history calls; use fewer points, a shorter range or a larger bucket`), { code: 'too_large' });
    const qs = ids.map((u) => 'uuids=' + encodeURIComponent(u)).join('&')
      + `&from=${new Date(f).toISOString()}&to=${new Date(t).toISOString()}`
      + (a.windowSec ? `&window=${a.windowSec}s&method=AVERAGE` : '');
    const { data } = await http.get('/api/v1/point/data?' + qs);
    const got = new Map(((data && data.data) || []).map((s) => [s.uuid, s.values || []]));
    const full = ids.filter((u) => (got.get(u) || []).length >= a.nfSampleCap);
    if (full.length && t - f > 1000 && depth < 20) {
      const mid = f + Math.floor((t - f) / 2);
      const rest = ids.filter((u) => !full.includes(u));
      for (const u of rest) push(u, got.get(u));
      await call(full, f, mid, depth + 1);
      await call(full, mid, t, depth + 1);
      return;
    }
    if (full.length) throw Object.assign(new Error('NF history still hits its sample cap at the minimum split; shorten the range'), { code: 'too_large' });
    for (const u of ids) push(u, got.get(u));
  };
  const push = (u, values) => {
    for (const s of values || []) {
      const t = tsMs(s.ts), v = sampleValue(s);
      if (Number.isFinite(t) && v != null && (typeof v === 'string' || Number.isFinite(v))) out[u].push([t, v]);
    }
  };
  for (let f = a.fromMs; f < a.toMs; f += CHUNK_MS) {
    const t = Math.min(f + CHUNK_MS, a.toMs);
    for (let i = 0; i < uuids.length; i += NF_BATCH) await call(uuids.slice(i, i + NF_BATCH), f, t, 0);
  }
  for (const u of uuids) out[u].sort((x, y) => x[0] - y[0]);
  return out;
}

/** {uuid: [[ms, avg]]} from the Timescale history route (bucketed); a truncated answer is an error, never a partial one. */
async function timescaleSeries(ts, conn, uuids, a, limits) {
  const client = await ts.connect(conn);
  try {
    const r = await ts.historyRoute(client, { uuids, from: a.from, to: a.to, bucket: a.bucket, coarsen: false }, limits || {});
    if (r.truncated) throw Object.assign(new Error('Timescale answer was truncated; use a shorter range, fewer points or a larger bucket'), { code: 'too_large' });
    const out = Object.fromEntries(uuids.map((u) => [u, []]));
    for (const row of r.rows || []) {
      const t = Date.parse(row.bucket);
      if (out[row.point_uuid] && Number.isFinite(t) && row.avg != null) out[row.point_uuid].push([t, Number(row.avg)]);
    }
    for (const u of uuids) out[u].sort((x, y) => x[0] - y[0]);
    return out;
  } finally {
    await client.end();
  }
}

/**
 * Model points named by the result. `points` are toPoint() records. Returns {uuidVar, uuids (sorted, distinct)}.
 * A value names a point when it is its uuid or its IRI (base + uuid), or an older IRI of a model point:
 * `urn:nf:<host>:<uuid>` or `urn:nf:site:<site>:<uuid>` (before #1773 settled on `urn:nf:<uuid>`).
 */
function pickPoints(vars, rows, points, base, uuidVar = '') {
  const byKey = new Map();
  for (const p of points) if (p.uuid) { byKey.set(p.uuid, p.uuid); byKey.set(base + p.uuid, p.uuid); }
  const legacy = (v) => (typeof v === 'string' && v.startsWith('urn:nf:') ? byKey.get(v.slice(v.lastIndexOf(':') + 1)) : undefined);
  const hits = (i) => rows.map((r) => byKey.get(r[i]) || legacy(r[i])).filter(Boolean);
  let order;
  if (uuidVar) {
    if (!vars.includes(uuidVar)) throw new Error(`args.uuidVar "${uuidVar}" is not a column of the result (${vars.join(', ')})`);
    order = [uuidVar];
  } else {
    order = [...UUID_VARS.filter((v) => vars.includes(v)), ...vars.filter((v) => !UUID_VARS.includes(v))];
  }
  for (const v of order) {
    const ids = hits(vars.indexOf(v));
    if (ids.length) return { uuidVar: v, uuids: [...new Set(ids)].sort() };
  }
  throw new Error('the result names no point of the model: select a uuid (ref:hasTimeseriesId) or a point IRI');
}

const meta = (p) => {
  const a = (p.rec && p.rec.attrs) || {};
  return { dis: p.dis, unit: p.units || '', kind: p.kind || 'Number', cls: p.cls || '', tags: [...(p.tags || [])],
    equip: p.equipRef || '', site: p.siteRef || '', weather: p.weatherStationRef || '', role: a.ofddRole || '' };
};

/** model.js + fdd.js + run-proof.js in a sandbox (the FDD hook's own resolver, #1635), loaded once. */
let proofShared = null;
function runProofShared() {
  if (proofShared) return proofShared;
  const STATIC = path.join(__dirname, '..', 'static');
  const ctx = vm.createContext({ console });
  for (const f of ['model.js', 'fdd.js', 'run-proof.js']) {
    vm.runInContext(fs.readFileSync(path.join(STATIC, f), 'utf8'), ctx, { filename: f });
  }
  proofShared = {
    resolveRunProof: vm.runInContext('resolveRunProof', ctx),
    idOf: vm.runInContext('idOf', ctx),
    catalog: JSON.parse(fs.readFileSync(path.join(STATIC, 'fdd-catalog.json'), 'utf8')),
  };
  return proofShared;
}

/**
 * The resolved run proof of each returned equipment (#1635): [{site, equip, uuid | null, source, tier, via, unit}].
 * The same resolution as the FDD hook (own status, own command, then the feeding equipment's).
 */
function runProofOf(model, equips) {
  const { resolveRunProof, idOf, catalog } = runProofShared();
  const own = catalog.operating_status.own;
  const pinned = (e, role) => model.points.find((p) => p.uuid && p.equipRef === e.id && (p.siteRef || '') === e.site
    && (((p.rec || {}).attrs || {}).ofddRole) === role);
  return equips.map((e) => {
    // 1. a point the model binds outright as operating_status (NF attr ofddRole, the client's explicit binding) is the proof
    const explicit = pinned(e, 'operating_status');
    if (explicit) return { site: e.site, equip: e.id, uuid: explicit.uuid, source: 'operating_status', tier: 'own', via: 'self', unit: explicit.units || '' };
    // 2. the FDD hook's resolution (own status, own command, then the feeding equipment's), by class / markers
    const rec = model.equips.find((r) => idOf(r) === e.id && (((r.attrs || {}).siteRef) || '') === e.site);
    const proof = rec ? resolveRunProof(rec, model, catalog) : { found: false };
    if (proof.found && proof.point && proof.point.uuid) {
      return { site: e.site, equip: e.id, uuid: proof.point.uuid, source: proof.source, tier: proof.tier, via: proof.via, unit: proof.point.units || '' };
    }
    // 3. an own status / command the model pins by ofddRole (the roles the client binds), in contract order
    for (const source of ['status', 'command']) {
      for (const role of own[source]) {
        const pt = pinned(e, role);
        if (pt) return { site: e.site, equip: e.id, uuid: pt.uuid, source, tier: 'own', via: 'self', unit: pt.units || '' };
      }
    }
    return { site: e.site, equip: e.id, uuid: null, source: null, tier: null, via: null, unit: null };
  });
}

/** The equipment records the page's points belong to: [{site, id, dis, tags}] (for role binding by equipment kind). */
function equipsOf(model, points, idOf) {
  const want = new Set(points.filter((p) => p.equipRef).map((p) => `${p.siteRef}\u0000${p.equipRef}`));
  const out = [];
  for (const e of model.equips) {
    const a = e.attrs || {};
    const id = idOf(e);
    if (!want.has(`${a.siteRef || ''}\u0000${id}`)) continue;
    out.push({ site: a.siteRef || '', id, dis: a.dis || e.name || id, tags: String(a.markers || '').split(',').filter(Boolean) });
  }
  return out;
}

/** Cut the series on a timestamp so the answer fits: [{series, complete, nextFrom, samples}]. */
function fitSeries(series, budget) {
  const all = [];
  for (const [u, s] of Object.entries(series)) for (const x of s) all.push([x[0], u, x]);
  all.sort((p, q) => p[0] - q[0]);
  let size = 0, cut = null;
  for (let i = 0; i < all.length; i++) {
    size += bytes(all[i][2]) + 1;
    if (size > budget) { cut = all[i][0]; break; }
  }
  if (cut == null) return { series, complete: true, nextFrom: null, samples: all.length };
  const out = Object.fromEntries(Object.keys(series).map((u) => [u, series[u].filter(([t]) => t < cut)]));
  return { series: out, complete: false, nextFrom: cut, samples: Object.values(out).reduce((n, s) => n + s.length, 0) };
}

/** @param {{sdk: any, args?: any, config?: any, now?: () => number, deps?: {ts?: any}}} o */
async function handle({ sdk, args = {}, config: rawConfig = {}, now = () => Date.now(), deps = {} }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const t0 = now();
  let result;
  try {
    const a = validateArgs(args, { now: now() });
    const { model, turtle, base, shared } = await rdf.buildTurtle(sdk, args);
    if (Buffer.byteLength(turtle, 'utf8') > 8 * 1024 * 1024) throw new Error('model Turtle exceeds 8 MiB');
    const q = withPrefixes(a.query, turtle);
    const evaluated = await evaluate(turtle, q);
    if (evaluated.truncated) throw new Error('SPARQL result exceeds 5000 rows; narrow the query or add LIMIT');
    const snapshot = crypto.createHash('sha256').update(turtle).update(q).update(JSON.stringify(evaluated)).digest('hex');
    if (args.snapshot && args.snapshot !== snapshot) throw new Error('model/query changed during paging; restart the request');
    if (a.form === 'ASK') {
      result = { ok: true, ms: 0, base, kind: 'ask', value: evaluated.value };
    } else {
      const r = evaluated;
      if (r.total > 200000) throw new Error(`query returned ${r.total} rows; add LIMIT or narrow it`);
      const { uuidVar, uuids } = pickPoints(r.vars, r.rows, model.points, base, a.uuidVar);
      const page = uuids.slice(a.pointOffset, a.pointOffset + a.pointLimit);
      const byUuid = new Map(model.points.map((p) => [p.uuid, p]));
      let source = a.source;
      const conn = settings.parseTimescale(settings.normalizeConfig(rawConfig).timescale);
      if (source === 'auto') source = conn && a.windowSec ? 'timescale' : 'nf';
      if (source === 'timescale' && !conn) throw new Error('source timescale: Timescale connection settings not found (full edition only): ' + settings.TIMESCALE_WHERE);
      const equips = equipsOf(model, page.map((u) => byUuid.get(u)), shared.idOf);
      const runProof = runProofOf(model, equips);
      // proof points that are not on this page are fetched with it and returned in run_proof_series (#1635)
      const onPage = new Set(page);
      const proofOnly = [...new Set(runProof.map((r) => r.uuid).filter((u) => u && !onPage.has(u)))].sort();
      const fetchIds = [...page, ...proofOnly];
      const fetched = !fetchIds.length ? {} : source === 'timescale'
        ? await timescaleSeries(deps.ts || require('./lib/timescale.js'), conn, fetchIds, a, settings.normalizeConfig(rawConfig).history)
        : await nfSeries(sdk.http, fetchIds, a);
      result = {
        ok: true, ms: 0, base, snapshot, kind: 'select', vars: r.vars,
        ...(a.includeRows ? { rows: r.rows.slice(0, a.maxRows).map((row) => Object.fromEntries(r.vars.map((v, i) => [v, row[i]]))) } : {}),
        rows_total: r.total, rows_truncated: a.includeRows && r.total > a.maxRows,
        uuid_var: uuidVar, points_total: uuids.length, point_offset: a.pointOffset, point_limit: a.pointLimit,
        next_point_offset: a.pointOffset + a.pointLimit < uuids.length ? a.pointOffset + a.pointLimit : null,
        points: Object.fromEntries(page.map((u) => [u, meta(byUuid.get(u))])),
        equips, operating_status: runProof,
        source, bucket: a.bucket, window_sec: a.windowSec, from: a.from, to: a.to,
      };
      const fixed = bytes(result) + 300 + page.reduce((n,u)=>n+bytes(u)+4,0);
      if (fixed >= a.maxBytes) throw Object.assign(new Error('answer without data is already over maxBytes; use fewer points (pointLimit) or includeRows=false'), { code: 'too_large' });
      const fit = fitSeries(fetched, a.maxBytes - fixed);
      if (!fit.complete && fit.nextFrom <= a.fromMs) throw Object.assign(new Error('one timestamp of data is over maxBytes; use fewer points (pointLimit)'), { code: 'too_large' });
      const series = {}, runProofSeries = {};
      for (const [u, s] of Object.entries(fit.series)) (onPage.has(u) ? series : runProofSeries)[u] = s;
      Object.assign(result, { complete: fit.complete, next_from: fit.nextFrom == null ? null : new Date(fit.nextFrom).toISOString(),
        samples: fit.samples, series, run_proof_series: runProofSeries });
    }
    result.ms = now() - t0;
    if (bytes(result) > a.maxBytes) throw Object.assign(new Error('answer exceeds UTF-8 byte limit; lower pointLimit or includeRows=false'), { code: 'too_large' });
  } catch (e) {
    result = { ok: false, ms: now() - t0, error: String((e && e.message) || e), ...(e && e.code ? { error_code: String(e.code) } : {}) };
  }
  log(JSON.stringify(result));
  return result;
}

module.exports = Object.assign(
  async (ctx) => handle({ sdk: ctx.sdk, args: argsOf(ctx), config: ctx.config || {} }),
  { handle, argsOf, validateArgs, withPrefixes, pickPoints, sampleValue, fitSeries, nfSeries, evaluate, runProofOf, LIMITS },
);
