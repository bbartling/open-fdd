// Long-range history from NF's TimescaleDB: on-request hook (FULL edition only).
//
//   POST /api/v1/apps/open-fdd/hooks/history
//        {"args": {"uuids": ["<point uuid>", ...], "from": "2026-06-01T00:00:00Z", "to": "2026-11-01T00:00:00Z", "bucket": "1 day"}}
//   GET  /api/v1/apps/open-fdd/hooks/history/runs?include_results=true     -> the answer
//
// Returns {bucket, from, to, total, truncated, rows: [{point_uuid, bucket, avg, min, max, n}]}, capped at
// about 200 KB (truncated = true when more rows existed). bucket is optional ("15 minutes", "1 hour",
// "1 day", ...); without it one is picked so each series has about 1000 buckets.
// Bounds (server side, hook config `history`: maxPoints 200000, maxSpanDays 3660, minBucketSec 60,
// statementTimeoutMs 20000): too-fine requests are coarsened (coarsened = true) or rejected; the answer also has
// coverage / truncated / max_points. Needs hook config `timescale` (same as the fdd hook): the NF database that holds the history and
// has timescale/install.sql applied. Nothing site-specific here.
const ts = require('./lib/timescale.js');

/** Hook arguments: NF passes the StartHook "args" object; accept the common spots (same as sparql.js). */
const argsOf = (ctx) => {
  const a = (ctx && (ctx.args || ctx.params || (ctx.sdk && ctx.sdk.args))) || {};
  return typeof a === 'string' ? JSON.parse(a) : a;
};

/**
 * @param {{ sdk: any, args?: { uuids?: string[], from?: string, to?: string, bucket?: string }, config?: { timescale?: object, history?: object } }} p
 */
async function handle({ sdk, args = {}, config = {} }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  if (!config.timescale) throw new Error('history hook: config.timescale is not set (full edition only)');
  const client = await ts.connect(config.timescale);
  try {
    const result = await ts.historyRoute(client, /** @type {any} */ (args), /** @type {any} */ (config.history || {}));
    const text = JSON.stringify(result);
    log(text.length > 200000 ? text.slice(0, 200000) : text);
    return result;
  } finally {
    await client.end();
  }
}

/** NF hook entry point; helpers exported for tests. */
const hook = async (ctx) => handle({ sdk: ctx.sdk, args: argsOf(ctx), config: ctx.config || {} });
module.exports = Object.assign(hook, { handle, argsOf });
