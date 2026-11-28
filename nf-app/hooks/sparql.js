// GENERATED COPY of shared/hooks/sparql.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
// SPARQL over the NF Haystack model: on-request hook (the API twin of the SPARQL panel in the UI).
//
//   POST /api/v1/apps/open-fdd/hooks/sparql   {"args": {"query": "SELECT ...", "format": "json"}}
//   GET  /api/v1/apps/open-fdd/hooks/sparql/runs?include_results=true     -> the answer
//
// format: "json" (default) | "csv" | "turtle".
//   json    SELECT -> {kind, vars, rows, total, truncated}; ASK -> {kind, value};
//           CONSTRUCT/DESCRIBE -> {kind, turtle, total, truncated}
//   csv     SELECT/ASK/graph -> CSV text (graph: subject,predicate,object)
//   turtle  CONSTRUCT/DESCRIBE only
// The answer is the hook's return value and one sdk.logEvent line (JSON, capped), so it shows up
// both in the run's result and in the run's logs.
//
// Read-only: SELECT / ASK / CONSTRUCT / DESCRIBE only; UPDATE operations and SERVICE are refused, and a model over
// the triple limit (default 500000) is refused before evaluation. LIMITS: the query text is capped (20000 chars),
// the answer is capped, but one evaluation runs synchronously inside the NF applications process and cannot be
// interrupted from here (no Worker/timeout in the hook); NF's hook invokeTimeout bounds how long the *run* is waited on,
// not necessarily the CPU work. Keep queries selective (LIMIT).
//
// The Turtle is built by static/model.js (modelToTurtle) from the model NF holds right now, exactly
// as the UI builds it, then loaded into Oxigraph (the oxigraph npm package, in this Node process).
// sparqlEndpoint is the SPARQL 1.1 protocol call: POST body with Content-Type application/sparql-query,
// answer application/sparql-results+json (SELECT/ASK) or text/turtle (CONSTRUCT/DESCRIBE).
// NF StartHook only accepts a string map, so the page posts {query, format} on this same route and
// handle() runs that text through sparqlEndpoint. Lite and Full share the route.
// Nothing site-specific here: sites, equips, points and tags all come from NF.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const STATIC = path.join(__dirname, '..', 'static');
const { queryPoints } = require('./lib/paging.js');
const MAX_QUERY_CHARS = 20000;
// Refuse models bigger than this before evaluating. Ceiling from env OPENFDD_SPARQL_MAX_TRIPLES (default
// 500000); a caller's args.maxTriples may only lower it.
const DEFAULT_MAX_TRIPLES = 500000;
const MAX_RESULT_CHARS = 200000;      // cap on the returned/logged answer text
const FORMATS = ['json', 'csv', 'turtle'];

const sparqlLib = () => require('../static/sparql.js');
// The module names are cast to `string` so tsc does not follow them into the vendored build (never type-checked).
const oxigraph = () => {
  try { return require(/** @type {string} */ ('oxigraph')); }
  catch (e) { throw new Error(`oxigraph is not installed (${e && e.message}). Install the app dependencies.`); }
};

/** Effective triple limit: the env ceiling, lowered (never raised) by the caller's value. */
function maxTriples(requested) {
  const env = Number(process.env.OPENFDD_SPARQL_MAX_TRIPLES);
  const ceiling = Number.isFinite(env) && env > 0 ? env : DEFAULT_MAX_TRIPLES;
  const asked = Number(requested);
  return Number.isFinite(asked) && asked > 0 ? Math.min(asked, ceiling) : ceiling;
}

/** Pure: Turtle + query -> answer. Throws Error on a bad format, parse error or evaluation error. */
function runSparql(turtle, query, format = 'json', opts = {}) {
  format = String(format || 'json').toLowerCase();
  if (!FORMATS.includes(format)) throw new Error(`format must be one of ${FORMATS.join(', ')}`);
  if (typeof query !== 'string' || !query.trim()) throw new Error('args.query is required');
  if (query.length > MAX_QUERY_CHARS) throw new Error(`query longer than ${MAX_QUERY_CHARS} characters`);
  const lib = sparqlLib();
  const ox = opts.ox || oxigraph();
  lib.sparqlCheckQuery(query);                          // read-only: SELECT/ASK/CONSTRUCT/DESCRIBE, no SERVICE
  const store = lib.sparqlLoadStore(ox, turtle, maxTriples(opts.maxTriples));   // oversize model: refused here
  const r = lib.sparqlExec(store, query, opts.cap || lib.SPARQL_ROW_CAP);
  if (format === 'turtle') {
    if (r.kind !== 'graph') throw new Error('format "turtle" needs a CONSTRUCT or DESCRIBE query');
    return { format, kind: r.kind, total: r.total, truncated: r.truncated, body: r.turtle };
  }
  if (format === 'csv') return { format, kind: r.kind, total: r.total ?? null, truncated: !!r.truncated, body: lib.sparqlToCsv(r) };
  const { triples, ...rest } = r;
  return { format, ...rest };
}

/** Exec result -> SPARQL Query Results JSON (SELECT and ASK). Graph queries stay Turtle. */
function sparqlResultsJson(r) {
  if (r.kind === 'ask') return { head: {}, boolean: r.value === true };
  if (r.kind !== 'select') return null;
  const bindings = r.rows.map((row) => {
    const b = {};
    r.vars.forEach((v, i) => {
      const text = row[i];
      if (text == null || text === '') return;
      b[v] = String(text).startsWith('_:') ? { type: 'bnode', value: String(text).slice(2) } : { type: 'literal', value: String(text) };
    });
    return b;
  });
  return { head: { vars: r.vars }, results: { bindings } };
}

/**
 * SPARQL protocol POST. `req.contentType` must be application/sparql-query; `req.body` is the query.
 * SELECT/ASK answer application/sparql-results+json. CONSTRUCT/DESCRIBE answer text/turtle.
 * @param {{method?: string, contentType?: string, headers?: Record<string, string>, body?: string}} req
 * @param {string} turtle
 * @param {{ox?: any, maxTriples?: number, cap?: number}} [opts]
 */
function sparqlEndpoint(req, turtle, opts = {}) {
  const method = String(req.method || 'POST').toUpperCase();
  const rawType = req.contentType || (req.headers && (req.headers['content-type'] || req.headers['Content-Type'])) || '';
  const contentType = String(rawType).split(';')[0].trim().toLowerCase();
  if (method !== 'POST') {
    return { status: 405, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'POST required' }) };
  }
  if (contentType !== 'application/sparql-query') {
    return { status: 415, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'Content-Type must be application/sparql-query' }) };
  }
  try {
    const r = runSparql(turtle, String(req.body || ''), 'json', opts);
    if (r.kind === 'graph') {
      const turtleOut = /** @type {{turtle?: string}} */ (r).turtle || '';
      return { status: 200, contentType: 'text/turtle', body: turtleOut, result: r };
    }
    return { status: 200, contentType: 'application/sparql-results+json', body: JSON.stringify(sparqlResultsJson(r)), result: r };
  } catch (e) {
    return { status: 400, contentType: 'application/json', body: JSON.stringify({ ok: false, error: errText(e) }) };
  }
}

// ---- NF model (same loader as hooks/fdd.js) -------------------------------------------
function loadShared() {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of ['model.js']) vm.runInContext(fs.readFileSync(path.join(STATIC, f), 'utf8'), ctx, { filename: f });
  const get = (n) => vm.runInContext(n, ctx);
  return { toPoint: get('toPoint'), idOf: get('idOf'), ENTITY_TYPES: get('ENTITY_TYPES'), modelToTurtle: get('modelToTurtle'),
    rdfBaseOf: get('rdfBaseOf') };
}

// the shared pager (lib/paging.js): pageOffset + totalCount or a token, loud on a cap or short read (#1550)
const queryAll = (http, body) => queryPoints(http, body);

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

const errText = (e) => (e && (e.message || (e.response && JSON.stringify(e.response.data)))) || String(e);
const startArgs = require('./lib/start-hook-args.js');

/** Hook arguments: NF passes the StartHook "args" object; accept the common spots. */
const argsOf = (ctx) => {
  return startArgs.startHookArgs(ctx, { configFallback: true, numberFields: ['maxTriples'] });
};

/** @param {{sdk: any, args?: any, now?: () => number}} o */
async function handle({ sdk, args = {}, now = () => Date.now() }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const t0 = now();
  let result;
  try {
    const shared = loadShared();
    const model = await loadModel(sdk.http, shared);
    // Base IRI: the UI's own rdfBaseOf (static/model.js, fixed `urn:nf:`), never the host (#1773), so the
    // subjects match the Model & RDF tab and the rdf hook. args.base overrides it; args.nfBase adds the
    // schema:url history links (without it only ref:hasTimeseriesId is exported).
    const base = String(args.base || shared.rdfBaseOf());
    const { turtle } = shared.modelToTurtle(model, base, { nfBase: args.nfBase || '' });
    const endpoint = sparqlEndpoint(
      { method: 'POST', contentType: 'application/sparql-query', body: args.query },
      turtle, { maxTriples: args.maxTriples });
    if (endpoint.status !== 200) throw new Error(JSON.parse(endpoint.body).error || 'sparql query failed');
    const wanted = String(args.format || 'json').toLowerCase();
    const r = wanted === 'json' ? endpoint.result : runSparql(turtle, args.query, wanted, { maxTriples: args.maxTriples });
    const results = endpoint.contentType === 'application/sparql-results+json' ? JSON.parse(endpoint.body) : null;
    result = { ok: true, ms: now() - t0, base, ...r, results };
    if (typeof result.body === 'string' && result.body.length > MAX_RESULT_CHARS) {
      result.body = result.body.slice(0, MAX_RESULT_CHARS);
      result.truncated = true;
    }
  } catch (e) {
    result = { ok: false, ms: now() - t0, error: errText(e) };
  }
  let text = JSON.stringify(result);
  if (text.length > MAX_RESULT_CHARS) {
    result = { ok: result.ok, ms: result.ms, kind: result.kind, total: result.total, truncated: true,
      note: `answer larger than ${MAX_RESULT_CHARS} characters, add LIMIT or select fewer columns` };
    text = JSON.stringify(result);
  }
  log(text);
  return result;
}

// The hook is the function; the helpers hang off it for the tests (assigned in one go so tsc sees the shape).
module.exports = Object.assign(
  async (ctx) => handle({ sdk: ctx.sdk, args: argsOf(ctx) }),
  { runSparql, handle, argsOf, loadShared, maxTriples, sparqlEndpoint, sparqlResultsJson },
);
