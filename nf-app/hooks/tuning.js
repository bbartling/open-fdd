// Open-FDD tuning hook (#1589 & 5.0.17): persisted SI overrides in fdd.rule_config (Full edition only).
//
// On-request hook (StartHook args, a string map). Reads and writes fdd.rule_config rows in NF's TimescaleDB
// (app option "timescale"); never touches NF points, BACnet or the model. Supports both sensor-sweep role limits
// (rule_id "SV-LIMITS", default) and per-rule SQL parameters (any rule_id in pack.rule_tuning_templates.rules).
//
//   action             "get" (default) | "preview" | "save" | "reset" | "rollback" | "history"
//   site               NF site id
//   scope              "site" (default) | "equip:<equipment id>"
//   rule_id            "SV-LIMITS" (default) | any rule id in pack.rule_tuning_templates.rules
//   overrides          JSON { version: 1, roles: {...} } (SV-LIMITS) or { version: 1, params: {...} } (per-rule) in SI
//   revision           rollback: positive integer revision to restore
//   expected_revision  optional optimistic-concurrency check (0 = none active yet, >= 1 = current active revision)
//   note               optional text stored with the revision
//   by                 who saved (stored as created_by; default "open-fdd-ui")
'use strict';
const settings = require('./lib/settings.js');
const startArgs = require('./lib/start-hook-args.js');
const roleLimits = require('./lib/role-limits.js');
const ruleTuning = require('./lib/rule-tuning.js');
const fs = require('fs');
const path = require('path');

const ACTIONS = ['get', 'preview', 'save', 'reset', 'rollback', 'history'];
const errText = (e) => (e && e.message) || String(e);

function loadPack() {
  return JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'rules', 'pack-postgres.json'), 'utf8'));
}

function loadTemplates() {
  return loadPack().role_limit_templates;
}

/** @param {any} args */
function parseArgs(args) {
  const a = startArgs.normalizeStartHookArgs(args, { jsonFields: ['overrides'], numberFields: ['revision', 'expected_revision'] });
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
  const out = { action, site, scope, overrides: a.overrides, revision: a.revision, by, note };
  if (a.rule_id != null && String(a.rule_id).trim() !== '') {
    const rid = String(a.rule_id).trim();
    if (rid.length > 100) throw new Error('rule_id too long');
    out.rule_id = rid;
  }
  if (a.expected_revision !== undefined && a.expected_revision !== null) {
    if (!Number.isInteger(a.expected_revision) || a.expected_revision < 0) {
      throw new Error('expected_revision must be a non-negative integer');
    }
    out.expected_revision = a.expected_revision;
  }
  return out;
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

async function handleRoleLimits({ ts, client, a, tpl, log }) {
  const activeRows = await ts.activeRuleConfigs(client, { siteId: a.site, ruleId: roleLimits.LIMITS_RULE_ID });
  const active = Object.fromEntries(activeRows.map((r) => [r.scope_key, { revision: r.revision, parameters: r.parameters }]));
  const siteActive = active[roleLimits.SITE_SCOPE];
  const isEquip = a.scope !== roleLimits.SITE_SCOPE;
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
    const old = await ts.ruleConfigRevision(client, a.site, roleLimits.LIMITS_RULE_ID, a.scope, a.revision);
    if (!old) throw new Error(`no revision ${a.revision} for ${a.scope}`);
    const { reset: _r, rollback_of: _b, ...rest } = old;
    candidate = { ...roleLimits.normalizeOverride({ ...rest, version: rest.version }, tpl.shipped), rollback_of: a.revision };
  }
  const [siteLayer, equipLayer] = layers(candidate);
  const effective = effectiveOf(tpl, siteLayer, equipLayer);
  if (['save', 'reset', 'rollback'].includes(a.action)) {
    revision = await ts.appendRuleConfigRevision(client, {
      siteId: a.site, ruleId: roleLimits.LIMITS_RULE_ID, scopeKey: a.scope, parameters: candidate, createdBy: a.by, expectedRevision: a.expected_revision,
    });
    log(`tuning: ${a.action} ${roleLimits.LIMITS_RULE_ID} ${a.scope} on site ${a.site || '(none)'} -> revision ${revision} (applies from the next fdd run)`);
  }
  const history = await ts.ruleConfigHistory(client, a.site, roleLimits.LIMITS_RULE_ID, a.scope, 20);
  const after = Object.fromEntries((await ts.activeRuleConfigs(client, { siteId: a.site, ruleId: roleLimits.LIMITS_RULE_ID })).map((r) => [r.scope_key, { revision: r.revision, parameters: r.parameters }]));
  return {
    ok: true, action: a.action, site: a.site, scope: a.scope, rule_id: roleLimits.LIMITS_RULE_ID,
    written: revision != null, ...(revision != null ? { revision } : {}),
    active: after, effective, history, consumers: roleLimits.FIELD_RULES,
  };
}

async function handleRuleParams({ ts, client, a, pack, log }) {
  const ruleTplRoot = pack.rule_tuning_templates;
  const ruleTpl = ruleTplRoot && ruleTplRoot.rules && ruleTplRoot.rules[a.rule_id];
  if (!ruleTpl) throw new Error(`unknown tunable rule ${a.rule_id}`);
  const activeRows = await ts.activeRuleConfigs(client, { siteId: a.site, ruleId: a.rule_id });
  const active = Object.fromEntries(activeRows.map((r) => [r.scope_key, { revision: r.revision, parameters: r.parameters }]));
  const siteActive = active[ruleTuning.SITE_SCOPE];
  const isEquip = a.scope !== ruleTuning.SITE_SCOPE;
  const layers = (own) => isEquip ? [siteActive && siteActive.parameters, own] : [own, undefined];

  let revision;
  let candidate = active[a.scope] && active[a.scope].parameters;
  if (a.action === 'preview' || a.action === 'save') {
    candidate = ruleTuning.normalizeRuleOverride(a.overrides, ruleTpl.controls, a.rule_id);
    if (a.note) candidate.note = a.note;
  } else if (a.action === 'reset') {
    candidate = { version: 1, params: {}, reset: true, ...(a.note ? { note: a.note } : {}) };
  } else if (a.action === 'rollback') {
    if (!Number.isInteger(a.revision) || a.revision < 1) throw new Error('rollback needs revision (a positive integer)');
    const old = await ts.ruleConfigRevision(client, a.site, a.rule_id, a.scope, a.revision);
    if (!old) throw new Error(`no revision ${a.revision} for ${a.rule_id} ${a.scope}`);
    const { reset: _r, rollback_of: _b, ...rest } = old;
    candidate = { ...ruleTuning.normalizeRuleOverride({ ...rest, version: rest.version }, ruleTpl.controls, a.rule_id), rollback_of: a.revision };
  }
  const [siteLayer, equipLayer] = layers(candidate);
  const merged = ruleTuning.mergeRuleParams(ruleTpl.controls, siteLayer, equipLayer, a.rule_id);
  const values = ruleTuning.resolvePlaceholders(ruleTplRoot.runtime_defaults, ruleTpl.controls, merged.effective, merged.overrideKeys, pack.poll_seconds);

  // Verify full SQL rendering (including active SV-LIMITS if this is a sweep rule) before saving
  let roleLimitsOpt = null;
  let roleLimitsSummary = null;
  if (roleLimits.SWEEP_RULES.includes(a.rule_id) && pack.role_limit_templates) {
    const svRows = await ts.activeRuleConfigs(client, { siteId: a.site, ruleId: roleLimits.LIMITS_RULE_ID });
    const svActive = Object.fromEntries(svRows.map((r) => [r.scope_key, { revision: r.revision, parameters: r.parameters }]));
    const svSite = svActive[roleLimits.SITE_SCOPE];
    const svEquip = isEquip ? svActive[a.scope] : undefined;
    const effLimits = roleLimits.effectiveRoleLimits(
      pack.role_limit_templates.shipped, pack.role_limit_templates.allowlists,
      svSite && svSite.parameters, svEquip && svEquip.parameters,
    );
    roleLimitsOpt = {
      roleTemplate: pack.role_limit_templates.rules[a.rule_id],
      limits: effLimits,
      fillTemplate: roleLimits.fillTemplate,
    };
    if (a.action === 'get') {
      const svEff = effectiveOf(pack.role_limit_templates, svSite && svSite.parameters, svEquip && svEquip.parameters);
      const svHistory = await ts.ruleConfigHistory(client, a.site, roleLimits.LIMITS_RULE_ID, a.scope, 20);
      roleLimitsSummary = { active: svActive, effective: svEff, history: svHistory, consumers: roleLimits.FIELD_RULES };
    }
  }
  ruleTuning.renderRuleSql(ruleTpl.sql, values, a.rule_id, roleLimitsOpt);
  if (ruleTpl.timeline_sql) ruleTuning.renderRuleSql(ruleTpl.timeline_sql, values, a.rule_id, roleLimitsOpt);

  if (['save', 'reset', 'rollback'].includes(a.action)) {
    revision = await ts.appendRuleConfigRevision(client, {
      siteId: a.site, ruleId: a.rule_id, scopeKey: a.scope, parameters: candidate, createdBy: a.by, expectedRevision: a.expected_revision,
    });
    log(`tuning: ${a.action} ${a.rule_id} ${a.scope} on site ${a.site || '(none)'} -> revision ${revision} (applies from the next fdd run)`);
  }
  const history = await ts.ruleConfigHistory(client, a.site, a.rule_id, a.scope, 20);
  const after = Object.fromEntries((await ts.activeRuleConfigs(client, { siteId: a.site, ruleId: a.rule_id })).map((r) => [r.scope_key, { revision: r.revision, parameters: r.parameters }]));
  return {
    ok: true, action: a.action, site: a.site, scope: a.scope, rule_id: a.rule_id,
    written: revision != null, ...(revision != null ? { revision } : {}),
    active: after, effective: { params: merged.effective, sources: merged.sources },
    controls: ruleTpl.controls, history,
    ...(roleLimitsSummary ? { role_limits: roleLimitsSummary } : {}),
  };
}

/**
 * @param {{ sdk: any, args?: any, config?: any, connect?: (cfg: any) => Promise<any>, templates?: any, pack?: any }} o
 */
async function handle({ sdk, args = {}, config = {}, connect, templates, pack: packIn }) {
  const log = (m) => (sdk && sdk.logEvent ? sdk.logEvent(m) : console.log(m));
  let result;
  let client = null;
  let owned = false;
  try {
    const a = parseArgs(args);
    const pack = packIn || (!templates ? loadPack() : null);
    const tpl = templates || (pack && pack.role_limit_templates) || loadTemplates();
    const cfg = settings.normalizeConfig(config);
    const ts = require('./lib/timescale.js');
    if (connect) client = await connect(cfg);
    else {
      ts.requireConfig(cfg.timescale);
      client = await ts.connect(cfg.timescale);
      owned = true;
    }
    if (!(await ts.coreOk(client))) throw new Error('core schema missing (fdd.rule_config): run the schema hook or timescale/install.sql first');
    const ruleId = a.rule_id || roleLimits.LIMITS_RULE_ID;
    if (ruleId === roleLimits.LIMITS_RULE_ID) {
      result = await handleRoleLimits({ ts, client, a, tpl, log });
    } else {
      result = await handleRuleParams({ ts, client, a, pack: pack || loadPack(), log });
    }
  } catch (e) {
    result = { ok: false, action: (args && args.action) || 'get', error: errText(e), ...(e && e.code ? { code: e.code } : {}), ...(e && e.activeRevision != null ? { active_revision: e.activeRevision } : {}) };
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
