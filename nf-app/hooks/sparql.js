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
// The Turtle is built by static/model.js (modelToTurtle) from the model NF holds right now, exactly
// as the UI builds it, then loaded into Oxigraph (Node build, vendored in static/vendor/oxigraph).
// Nothing site-specific here: sites, equips, points and tags all come from NF.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const STATIC = path.join(__dirname, '..', 'static');
const PAGE = 500;
const MAX_QUERY_CHARS = 20000;
const MAX_RESULT_CHARS = 200000;      // cap on the returned/logged answer text
const FORMATS = ['json', 'csv', 'turtle'];

const sparqlLib = () => require('../static/sparql.js');
// The module names are cast to `string` so tsc does not follow them into the vendored build (never type-checked).
const oxigraph = () => {
  try { return require(/** @type {string} */ ('oxigraph')); } catch (e) { return require(/** @type {string} */ ('../static/vendor/oxigraph/node.js')); }
};

/** Pure: Turtle + query -> answer. Throws Error on a bad format, parse error or evaluation error. */
function runSparql(turtle, query, format = 'json', opts = {}) {
  format = String(format || 'json').toLowerCase();
  if (!FORMATS.includes(format)) throw new Error(`format must be one of ${FORMATS.join(', ')}`);
  if (typeof query !== 'string' || !query.trim()) throw new Error('args.query is required');
  if (query.length > MAX_QUERY_CHARS) throw new Error(`query longer than ${MAX_QUERY_CHARS} characters`);
  const lib = sparqlLib();
  const ox = opts.ox || oxigraph();
  const store = new ox.Store();
  store.load(turtle, { format: 'text/turtle' });
  const r = lib.sparqlExec(store, query, opts.cap || lib.SPARQL_ROW_CAP);
  if (format === 'turtle') {
    if (r.kind !== 'graph') throw new Error('format "turtle" needs a CONSTRUCT or DESCRIBE query');
    return { format, kind: r.kind, total: r.total, truncated: r.truncated, body: r.turtle };
  }
  if (format === 'csv') return { format, kind: r.kind, total: r.total ?? null, truncated: !!r.truncated, body: lib.sparqlToCsv(r) };
  const { triples, ...rest } = r;
  return { format, ...rest };
}

// ---- NF model (same loader as hooks/fdd.js) -------------------------------------------
function loadShared() {
  const ctx = vm.createContext({ console, URLSearchParams, TextDecoder, atob, btoa });
  for (const f of ['model.js']) vm.runInContext(fs.readFileSync(path.join(STATIC, f), 'utf8'), ctx, { filename: f });
  const get = (n) => vm.runInContext(n, ctx);
  return { toPoint: get('toPoint'), idOf: get('idOf'), ENTITY_TYPES: get('ENTITY_TYPES'), modelToTurtle: get('modelToTurtle') };
}

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

const errText = (e) => (e && (e.message || (e.response && JSON.stringify(e.response.data)))) || String(e);

/** Hook arguments: NF passes the StartHook "args" object; accept the common spots. */
const argsOf = (ctx) => {
  const a = (ctx && (ctx.args || ctx.params || (ctx.sdk && ctx.sdk.args) || ctx.config)) || {};
  return typeof a === 'string' ? JSON.parse(a) : a;
};

/** @param {{sdk: any, args?: any, nfBase?: string, now?: () => number}} o */
async function handle({ sdk, args = {}, nfBase, now = () => Date.now() }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const t0 = now();
  let result;
  try {
    const shared = loadShared();
    const model = await loadModel(sdk.http, shared);
    // Base IRIs: same scheme as the UI (urn:nf:<host>:); the hook has no browser host, so default to
    // the NF host the SDK talks to. Pass args.base to match the UI's IRIs, args.nfBase to get the
    // rdfs:seeAlso history URLs (without it only ref:hasTimeseriesId is exported).
    const host = args.base || nfBase || (sdk.http && sdk.http.defaults && sdk.http.defaults.baseURL) || 'nf';
    const base = String(args.base || `urn:nf:${String(host).replace(/^https?:\/\//, '').replace(/\/$/, '')}:`);
    const { turtle } = shared.modelToTurtle(model, base, { nfBase: args.nfBase || '' });
    const r = runSparql(turtle, args.query, args.format);
    result = { ok: true, ms: now() - t0, base, ...r };
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
  { runSparql, handle, argsOf, loadShared },
);
