// Long-range history from NF's TimescaleDB: on-request hook (FULL edition only).
//
//   POST /api/v1/apps/open-fdd/hooks/history
//        {"args": {"uuids": ["<point uuid>", ...], "from": "2026-06-01T00:00:00Z", "to": "2026-11-01T00:00:00Z", "bucket": "1 day"}}
//   GET  /api/v1/apps/open-fdd/hooks/history/runs?include_results=true     -> the answer
//
// Returns {bucket, from, to, total, truncated, rows: [{point_uuid, bucket, avg, min, max, n}]}, capped at
// about 200 KB (truncated = true when more rows existed). bucket is optional ("15 minutes", "1 hour",
// "1 day", ...); without it one is picked so each series has about 1000 buckets.
// The answer always has ok. An empty range is {ok: true, row_count: 0, rows: [], reason: "no rows in the requested range",
// newest_source_ts: <ISO of the newest sample of those points in the source, any age | null>}: a stale source shows up
// there. A database / connection failure is {ok: false, rows: 0, error, error_code, stage: "connect" | "query"} (5.0.5,
// #1550); a bad request (arguments) throws.
// With no config `timescale` and no args the hook returns {ok: true, skipped: true, reason: "timescale not configured"};
// with args it fails (a query must never be answered from nowhere).
// Bounds (server side, hook config `history`: maxPoints 200000, maxSpanDays 3660, minBucketSec 60,
// statementTimeoutMs 20000): too-fine requests are coarsened (coarsened = true) or rejected; the answer also has
// coverage / truncated / max_points. Needs the Timescale connection (app option `timescale`, a JSON string; same as the fdd hook; see lib/settings.js): the NF database that holds the history and
// has timescale/install.sql applied. Nothing site-specific here.
const ts = require('./lib/timescale.js');
const settings = require('./lib/settings.js');
const startArgs = require('./lib/start-hook-args.js');

/** Hook arguments: NF passes the StartHook "args" object; accept the common spots (same as sparql.js). */
const argsOf = (ctx) => startArgs.startHookArgs(ctx);

/**
 * NF StartHook args are a string→string map. Coerce JSON-encoded fields (especially `uuids`) and optional
 * `windowHours` into the shape historyRoute expects ({ uuids: string[], from, to, bucket? }).
 * @param {any} args
 */
const normalizeArgs = (args) => startArgs.normalizeStartHookArgs(args,
  { jsonFields: ['uuids'], numberFields: ['windowHours'], expandWindowHours: true });

/**
 * @param {{ sdk: any, args?: { uuids?: string[], from?: string, to?: string, bucket?: string }, config?: { timescale?: object, history?: object } }} p
 */
async function handle({ sdk, args = {}, config: rawConfig = {} }) {
  args = normalizeArgs(args);
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  // NF stores hook settings as app OPTIONS and passes them as ctx.config; `timescale` is a JSON string there.
  // An unusable value (present but not JSON / URL) throws here, naming the option, never its value.
  const config = settings.normalizeConfig(rawConfig);
  config.timescale = settings.parseTimescale(config.timescale) || undefined;
  if (!config.timescale) {
    // No Timescale configured. A bare invocation (no args: a blanket `run`, a health check) is a clean skip, not
    // an error; a real query (any args) still fails loudly, so nothing ever answers from the wrong source.
    if (!Object.keys(args || {}).length) {
      const result = { ok: true, skipped: true, reason: 'timescale not configured' };
      log(JSON.stringify(result));
      return result;
    }
    throw new Error('history hook: Timescale connection settings not found (full edition only): ' + settings.TIMESCALE_WHERE);
  }
  // A database or connection failure is ok:false with the error, never an empty answer; a bad request (arguments)
  // still throws. Database errors carry a string `code` (pg SQLSTATE, ECONNREFUSED, history_timeout ...).
  const failed = (e, stage) => {
    const result = { ok: false, rows: 0, error: String((e && e.message) || e), error_code: String(e.code), stage };
    log(JSON.stringify(result));
    return result;
  };
  const runtimeError = (e) => !!e && typeof e.code === 'string' && !!e.code;
  let client;
  try {
    client = await ts.connect(config.timescale);
  } catch (e) {
    if (runtimeError(e)) return failed(e, 'connect');
    throw e;
  }
  try {
    const result = /** @type {any} */ (await ts.historyRoute(client, /** @type {any} */ (args), /** @type {any} */ (config.history || {})));
    result.ok = true;
    result.row_count = result.rows.length;
    if (!result.rows.length) {
      // an empty answer: say so, and when the source last had a sample for these points (any age), so "nothing in
      // this range" can be told from "the source stopped receiving rows"
      result.reason = 'no rows in the requested range';
      try {
        const newest = await ts.newestSample(client, /** @type {any} */ (args).uuids);
        result.newest_source_ts = newest == null ? null : new Date(newest).toISOString();
      } catch (e) { result.newest_source_ts_error = String((e && e.message) || e); }
    }
    const text = JSON.stringify(result);
    log(text.length > 200000 ? text.slice(0, 200000) : text);
    return result;
  } catch (e) {
    if (runtimeError(e)) return failed(e, 'query');
    throw e;
  } finally {
    await client.end();
  }
}

/** NF hook entry point; helpers exported for tests. */
const hook = async (ctx) => handle({ sdk: ctx.sdk, args: argsOf(ctx), config: ctx.config || {} });
module.exports = Object.assign(hook, { handle, argsOf, normalizeArgs });
