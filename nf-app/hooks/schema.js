'use strict';
// Read-only schema probe (5.0.13, #1585): which openfdd schema_version does the Timescale database behind the app
// option "timescale" have, and does it meet what this release needs?
//
//   POST /api/v1/apps/open-fdd/hooks/schema            (no args)
//   GET  /api/v1/apps/open-fdd/hooks/schema/runs?include_results=true     -> {ok, installed, required}
//
// Why it is a hook: the database is usually on the NF host's loopback, so the installer workstation (nf_app_sync.py
// install / doctor) can neither reach it nor needs a PostgreSQL client. The hook already runs next to the database with
// the app's own option, so the check happens there and only three fields leave NF.
//
// READ ONLY, enforced by the database: BEGIN TRANSACTION READ ONLY ... ROLLBACK. It never installs or upgrades a schema.
// It returns { ok, installed, required } (or { ok: true, skipped, reason } when Timescale is not selected) and never a
// host, user, password or connection string; a failure carries the error text with the connection redacted.
const settings = require('./lib/settings.js');
const ts = require('./lib/timescale.js');

/** @param {{ sdk?: any, config?: any, client?: any }} p  client = an already connected pg client (tests). */
async function handle({ sdk, config: rawConfig = {}, client: given }) {
  const log = (/** @type {string} */ m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  const done = (/** @type {any} */ result) => { log(JSON.stringify(result)); return result; };
  const config = settings.normalizeConfig(rawConfig);
  const engine = String(config.engine || 'auto').toLowerCase();
  let conn = null;
  try { conn = settings.parseTimescale(config.timescale); } catch (e) {
    return done({ ok: false, required: ts.SCHEMA_VERSION, error: 'the app option "timescale" is not a usable connection (value not shown)' });
  }
  if (engine === 'sqlite' || engine === 'pglite' || (!conn && engine !== 'timescale')) {
    return done({ ok: true, skipped: true, reason: 'timescale not selected', required: ts.SCHEMA_VERSION });
  }
  if (!conn && !given) return done({ ok: false, required: ts.SCHEMA_VERSION, error: 'engine "timescale" but the app option "timescale" is not set' });
  let client = given;
  try {
    if (!client) client = await ts.connect(conn);
    await client.query('BEGIN TRANSACTION READ ONLY');
    let installed;
    try { installed = await ts.schemaVersion(client); } finally { await client.query('ROLLBACK'); }
    return done({ ok: installed >= ts.SCHEMA_VERSION, installed, required: ts.SCHEMA_VERSION });
  } catch (e) {
    let text = settings.redact((e && e.message) || e, conn);
    for (const v of conn ? [conn.host, conn.user, conn.database] : []) {     // a driver error may name the endpoint
      if (v && String(v).length > 2) text = text.split(String(v)).join('***');
    }
    return done({ ok: false, required: ts.SCHEMA_VERSION, error: text });
  } finally {
    if (client && !given) { try { await client.end(); } catch (_) { /* nothing to report */ } }
  }
}

/** NF hook entry point; handle exported for tests. */
const hook = async (/** @type {any} */ ctx) => handle({ sdk: ctx.sdk, config: ctx.config || {} });
module.exports = Object.assign(hook, { handle });
