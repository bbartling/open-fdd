// Open-FDD sweep tuning (#1589): persisted SI role-limit overrides for the five sensor sweeps (Full edition only).
//
// On-request hook (StartHook args, a string map). It reads and writes ONLY fdd.rule_config rows with rule_id "SV-LIMITS"
// in NF's TimescaleDB (app option "timescale"); it never touches NF points, BACnet or the model. The fdd hook applies
// the active revisions on its next scheduled run (shipped < site < equipment) and records config_revision /
// config_hash / effective_parameters on every sweep row of fdd.rule_result.
//
//   action   "get" (default) | "preview" | "save" | "reset" | "rollback" | "history"
//   site     NF site id (the equip's siteRef, as the fdd hook uses it)
//   scope    "site" (default) | "equip:<equipment id>"
//   overrides  JSON { "version": 1, "roles": { "<role>": { "lo": 12.0, ... } } } in SI (preview / save)
//   revision   rollback: the revision whose parameters become the new active revision
//   note       optional text stored with the revision
//   by         who saved (stored as created_by; default "open-fdd-ui")
//
// Every answer is one JSON object (also logged as the run's last event, which the editor reads):
//   { ok, action, site, scope, active, effective: { roles: {role: {field: value}}, sources: {role: {field: layer}} },
//     history: [...], revision?, error? }
'use strict';
const settings = require('./lib/settings.js');
const startArgs = require('./lib/start-hook-args.js');
const roleLimits = require('./lib/role-limits.js');
const fs = require('fs');
const path = require('path');

const ACTIONS = ['get', 'preview', 'save', 'reset', 'rollback', 'history'];
const errText = (e) => (e && e.message) || String(e);

/** shipped limits + allowlists: the pack's copy (the same bytes the fdd hook merges onto). */
function loadTemplates() {
  const pack = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'rules', 'pack-postgres.json'), 'utf8'));
  return pack.role_limit_templates;
}

/** @param {any} args */
function parseArgs(args) {
  const a = startArgs.normalizeStartHookArgs(args, { jsonFields: ['overrides'], numberFields: ['revision'] });
  const action = String(a.action || 'get');
  if (!ACTIONS.includes(action)) throw new Error(`action must be one of ${ACTIONS.join(', ')}`);
  const site = typeof a.site === 'string' ? a.site : '';
  const scope = String(a.scope || roleLimits.SITE_SCOPE);
  if (scope !== roleLimits.SITE_SCOPE && !(scope.startsWith(roleLimits.EQUIP_SCOPE_PREFIX) && scope.length > roleLimits.EQUIP_SCOPE_PREFIX.length)) {
    throw new Error('scope must be "site" or "equip:<equipment id>"');
  }
  if (scope.length > 300 || site.length > 300) throw new Error('site / scope too long');
  const by = String(a.by || 'open-fdd-ui').replace(/[^\w.@ -]/g, '').slice(0, 80) || 'open-fdd-ui';
  const note = a.note == null ? undefined : String(a.note).slice(0, 500);
  return { action, site, scope, overrides: a.overrides, revision: a.revision, by, note };
}

/** Effective limits of a scope: {roles: {role: {field: SI}}, sources: {role: {field: layer}}}. Throws when invalid. */
function effectiveOf(tpl, siteParams, equipParams) {
  const { doc, sources } = roleLimits.merge(tpl.shipped, siteParams, equipParams);
  roleLimits.validateRoleLimits(doc, tpl.allowlists);
  const roles = {};
  for (const e of doc.roles) {
    roles[e.role] = { quantity: e.quantity, lo: e.lo, hi: e.hi, spike_delta: e.spike_delta, flat_tol: e.flat_tol, stale_tol: e.stale_tol, rate_per_h: e.rate_per_h };
  }
  return { roles, sources };
}

/**
 * @param {{ sdk: any, args?: any, config?: any, connect?: (cfg: any) => Promise<any>, templates?: any }} o
 */
async function handle({ sdk, args = {}, config = {}, connect, templates }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  let result;
  let client = null;
  let owned = false;
  try {
    const a = parseArgs(args);
    const tpl = templates || loadTemplates();
    const cfg = settings.normalizeConfig(config);
    const ts = require('./lib/timescale.js');
    if (connect) client = await connect(cfg);
    else {
      ts.requireConfig(cfg.timescale);
      client = await ts.connect(cfg.timescale);
      owned = true;
    }
    if (!(await ts.coreOk(client))) throw new Error('core schema missing (fdd.rule_config): run the schema hook or timescale/install.sql first');
    const activeRows = await ts.activeRoleLimitOverrides(client, a.site);
    const active = Object.fromEntries(activeRows.map((r) => [r.scope_key, { revision: r.revision, parameters: r.parameters }]));
    const siteActive = active[roleLimits.SITE_SCOPE];
    const isEquip = a.scope !== roleLimits.SITE_SCOPE;
    // The layers for this scope: the site override alone, or the site override under this equipment's
    const layers = (own) => isEquip ? [siteActive && siteActive.parameters, own] : [own, undefined];

    let revision;
    let candidate = active[a.scope] && active[a.scope].parameters;
    if (a.action === 'preview' || a.action === 'save') {
      candidate = roleLimits.normalizeOverride(a.overrides, tpl.shipped);
      if (a.note) candidate.note = a.note;
    } else if (a.action === 'reset') {
      candidate = { version: 1, roles: {}, reset: true, ...(a.note ? { note: a.note } : {}) };
    } else if (a.action === 'rollback') {
      if (!Number.isInteger(a.revision) || a.revision < 1) throw new Error('rollback needs revision (a positive integer)');
      const old = await ts.roleLimitRevision(client, a.site, a.scope, a.revision);
      if (!old) throw new Error(`no revision ${a.revision} for ${a.scope}`);
      const { reset: _r, rollback_of: _b, ...rest } = old;
      candidate = { ...roleLimits.normalizeOverride({ ...rest, version: rest.version }, tpl.shipped), rollback_of: a.revision };
    }
    const [siteLayer, equipLayer] = layers(candidate);
    const effective = effectiveOf(tpl, siteLayer, equipLayer);     // throws: an invalid override is never stored
    if (['save', 'reset', 'rollback'].includes(a.action)) {
      revision = await ts.appendRoleLimitRevision(client, { siteId: a.site, scopeKey: a.scope, parameters: candidate, createdBy: a.by });
      log(`tuning: ${a.action} ${a.scope} on site ${a.site || '(none)'} -> revision ${revision} (applies from the next fdd run)`);
    }
    const history = await ts.roleLimitHistory(client, a.site, a.scope, 20);
    const after = Object.fromEntries((await ts.activeRoleLimitOverrides(client, a.site)).map((r) => [r.scope_key, { revision: r.revision, parameters: r.parameters }]));
    result = { ok: true, action: a.action, site: a.site, scope: a.scope, written: revision != null, ...(revision != null ? { revision } : {}),
      active: after, effective, history, consumers: roleLimits.FIELD_RULES };
  } catch (e) {
    result = { ok: false, action: (args && args.action) || 'get', error: errText(e) };
  } finally {
    if (client && owned) { try { await client.end(); } catch (_) { /* closing */ } }
  }
  const text = JSON.stringify(result);
  log(text);
  return result;
}

module.exports = Object.assign(
  async (ctx) => handle({ sdk: ctx.sdk, args: startArgs.startHookArgs(ctx, { configFallback: false }), config: ctx.config }),
  { handle, parseArgs, effectiveOf },
);
