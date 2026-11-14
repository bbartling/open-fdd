'use strict';
// The site model as Turtle: on-request hook (both editions; source shared/hooks/rdf.js).
//
//   POST /api/v1/apps/<app>/hooks/rdf                    {"offset": "0", "limit": "150000"}   (flat string map)
//   GET  /api/v1/apps/<app>/hooks/rdf/runs?include_results=true&include_logs=true   -> the answer (one JSON event line)
//
// Answer: {ok, base, snapshot, total_chars, offset, next_offset | null, points, turtle}. Offsets count UTF-16 characters;
// `limit` is UTF-8 bytes. Pass the first answer's `snapshot` on later pages: a changed model answers model_changed. The slice is of the same Turtle the Model & RDF tab builds (static/model.js modelToTurtle); page with
// next_offset until it is null. Lite has no SPARQL engine (1 GB boxes): a client runs the SPARQL itself on this
// Turtle (open_fdd.nf.sparql_data, rdflib) and reads history through NF's /api/v1/point/data. Full also has the
// `sparql` and `sparql-data` hooks. Read-only: it only reads NF's point records. Nothing site-specific here.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');
const { queryPoints } = require('./lib/paging.js');
const startArgs = require('./lib/start-hook-args.js');

const STATIC = path.join(__dirname, '..', 'static');
const DEFAULT_LIMIT = 150000;   // UTF-8 bytes of Turtle per answer (NF keeps the answer as one event line)
const MAX_LIMIT = 190000;

/** static/model.js in a sandbox: toPoint, idOf, ENTITY_TYPES, modelToTurtle (the UI's own code). */
function loadShared() {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  vm.runInContext(fs.readFileSync(path.join(STATIC, 'model.js'), 'utf8'), ctx, { filename: 'model.js' });
  const get = (n) => vm.runInContext(n, ctx);
  return { toPoint: get('toPoint'), idOf: get('idOf'), ENTITY_TYPES: get('ENTITY_TYPES'), modelToTurtle: get('modelToTurtle') };
}

/** Model-layer entities plus every point of each site (default layer), as the UI loads them. */
async function loadModel(http, shared) {
  const recs = await queryPoints(http, { layer: 'model' });
  const of = (t) => recs.filter((r) => r.pointType === t);
  const model = { sites: of('SITE'), equips: of('EQUIPMENT'), devices: of('DEVICE'), points: [] };
  for (const s of model.sites) {
    const pts = await queryPoints(http, { layer: 'default', structuredQuery: { field: { property: 'siteRef', text: shared.idOf(s) } } });
    model.points.push(...pts.filter((r) => !shared.ENTITY_TYPES.includes(r.pointType)).map(shared.toPoint));
  }
  return model;
}

/** Base IRI: same scheme as the UI (urn:nf:<host>:); args.base wins. */
function baseOf(sdk, args = {}) {
  if (args.base) return String(args.base);
  const host = (sdk && sdk.http && sdk.http.defaults && sdk.http.defaults.baseURL) || 'nf';
  return `urn:nf:${String(host).replace(/^https?:\/\//, '').replace(/\/$/, '')}:`;
}

/** {model, turtle, base, shared} for the NF this hook runs on. */
async function buildTurtle(sdk, args = {}) {
  const shared = loadShared();
  const model = await loadModel(sdk.http, shared);
  const base = baseOf(sdk, args);
  const { turtle } = shared.modelToTurtle(model, base, { nfBase: args.nfBase || '' });
  return { model, turtle, base, shared };
}

const intArg = (v, dflt, name, max = Infinity) => {
  if (v == null || v === '') return dflt;
  const n = Number(v);
  if (!Number.isInteger(n) || n < 0) throw new Error(`args.${name} must be a non-negative integer`);
  return Math.min(n, max);
};

/** The longest slice from `offset` (UTF-16 index) whose UTF-8 size is at most `limit` bytes; never splits a pair. */
function sliceBytes(text, offset, limit) {
  let used = 0, i = offset;
  while (i < text.length) {
    const code = text.codePointAt(i);
    const width = code > 0xffff ? 2 : 1;
    const size = code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
    if (used + size > limit) break;
    used += size; i += width;
  }
  if (i === offset && offset < text.length) throw new Error('args.limit is smaller than one character');
  return text.slice(offset, i);
}

/** @param {{sdk: any, args?: any, now?: () => number}} o */
async function handle({ sdk, args = {}, now = () => Date.now() }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const t0 = now();
  let result;
  try {
    const offset = intArg(args.offset, 0, 'offset');
    const limit = Math.max(1, intArg(args.limit, DEFAULT_LIMIT, 'limit', MAX_LIMIT));
    const { model, turtle, base } = await buildTurtle(sdk, args);
    const snapshot = crypto.createHash('sha256').update(turtle).digest('hex');
    if (args.snapshot && args.snapshot !== snapshot) throw Object.assign(new Error('the model changed while paging; start again from offset 0'), { code: 'model_changed' });
    if (offset > turtle.length) throw new Error('args.offset is past the end of the Turtle');
    // `limit` bounds the logged JSON line, not just the Turtle: JSON escaping (quotes, newlines) adds bytes
    let budget = limit;
    for (;;) {
      const chunk = sliceBytes(turtle, offset, Math.max(1, budget));
      const end = offset + chunk.length;
      result = { ok: true, ms: now() - t0, base, snapshot, total_chars: turtle.length, offset,
        next_offset: end < turtle.length ? end : null, points: model.points.length, turtle: chunk };
      const over = Buffer.byteLength(JSON.stringify(result), 'utf8') - limit;
      if (over <= 0) break;
      if (budget <= 1) throw new Error('args.limit is too small for one character of Turtle plus the answer');
      budget = Math.max(1, budget - over - 16);
    }
  } catch (e) {
    result = { ok: false, ms: now() - t0, error: String((e && e.message) || e), ...(e && e.code ? { error_code: String(e.code) } : {}) };
  }
  log(JSON.stringify(result));
  return result;
}

const argsOf = (ctx) => startArgs.startHookArgs(ctx);
module.exports = Object.assign(
  async (ctx) => handle({ sdk: ctx.sdk, args: argsOf(ctx) }),
  { handle, argsOf, buildTurtle, loadShared, loadModel, baseOf, sliceBytes },
);
