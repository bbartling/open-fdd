'use strict';
/**
 * Sensor-sweep role-limit overrides (#1589), the JS twin of open_fdd/rules/role_limit_overrides.py and of the sweep
 * fragment rendering in sql/fdd/render_rule.py. One file, two runtimes: the fdd / tuning hooks (CommonJS) and the
 * Full edition's tuning editor (browser global `ofddRoleLimits`). Full edition only (Lite has no editor).
 *
 * SI only in storage. An override is { version: 1, roles: { "<role>": { lo?, hi?, spike_delta?, flat_tol?, stale_tol?,
 * rate_per_h? } } }, one revision of fdd.rule_config (rule_id "SV-LIMITS", scope_key "site" or "equip:<equipment id>").
 * Precedence per field: shipped file (open_fdd/data/sensor_sweep_limits.json), then site, then equipment.
 * The merged document is validated exactly like validate_role_limits() before a save, and the hook re-renders the
 * five sweep rules from the pack's role_limit_templates (byte-identical to the pack SQL with the shipped limits).
 */
(function (root) {
  const LIMITS_RULE_ID = 'SV-LIMITS';
  const SITE_SCOPE = 'site';
  const EQUIP_SCOPE_PREFIX = 'equip:';
  const SWEEP_RULES = ['SV-RANGE', 'SV-SPIKE', 'SV-FLATLINE', 'SV-STALE', 'SV-RATE'];
  const FIELD_KIND = { lo: 'absolute', hi: 'absolute', spike_delta: 'difference', flat_tol: 'difference', stale_tol: 'difference', rate_per_h: 'rate' };
  const FIELD_RULES = { lo: ['SV-RANGE'], hi: ['SV-RANGE'], spike_delta: ['SV-SPIKE'], flat_tol: ['SV-FLATLINE'], stale_tol: ['SV-STALE'], rate_per_h: ['SV-RATE'] };
  const FRAGMENT_KEYS = { 'SV-RANGE': 'SV_RANGE_BANDS', 'SV-SPIKE': 'SV_SPIKE_BANDS', 'SV-FLATLINE': 'SV_FLATLINE_TOL', 'SV-STALE': 'SV_STALE_TOL', 'SV-RATE': 'SV_RATE_THRESHOLD' };
  const QUANTITIES = ['absolute_temperature', 'relative_humidity', 'air_pressure', 'volume_flow', 'power'];
  const DEFAULT_KEYS = ['flat_tol_temperature', 'stale_tol_temperature', 'rate_per_h', 'flat_s', 'stale_s'];
  const ROLE_KEYS = ['role', 'quantity', 'lo', 'hi', 'spike_delta', 'flat_tol', 'stale_tol', 'rate_per_h', 'source'];
  const SI_UNIT = { absolute_temperature: 'degC', relative_humidity: '%RH', air_pressure: 'Pa', volume_flow: 'L/s', power: 'kW' };
  // display unit -> SI factor; the numbers of open_fdd/data/unit_factors.json (tests/test_role_limit_overrides.py checks them)
  const MULTIPLY = {
    relative_humidity: { '%RH': 1, '%': 1 },
    air_pressure: { Pa: 1, inH2O: 249.0889, psi: 6894.757 },
    volume_flow: { 'L/s': 1, cfm: 0.4719474, gpm: 0.0630902 },
    power: { kW: 1, ton: 3.5168525 },
  };

  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

  // ---- units -------------------------------------------------------------------------------------------------
  function displayUnits(quantity) {
    return quantity === 'absolute_temperature' ? ['degC', 'degF'] : Object.keys(MULTIPLY[quantity] || {});
  }
  /** Editor value -> SI. Absolute temperature (F - 32) * 5/9; a temperature difference or rate F * 5/9. */
  function toSi(value, unit, quantity, field) {
    if (!isNum(value)) throw new Error(`${field}: value must be a finite number`);
    const kind = FIELD_KIND[field];
    if (!kind) throw new Error(`${field} is not an editable field`);
    if (quantity === 'absolute_temperature') {
      if (unit === 'degC') return value;
      if (unit !== 'degF') throw new Error(`${field}: unit ${unit} is not a temperature unit (degC, degF)`);
      return kind === 'absolute' ? (value - 32) * 5 / 9 : value * 5 / 9;
    }
    const f = (MULTIPLY[quantity] || {})[unit];
    if (f === undefined) throw new Error(`${field}: unit ${unit} not accepted for ${quantity} (${displayUnits(quantity).join(', ')})`);
    return value * f;
  }
  function fromSi(value, unit, quantity, field) {
    if (!isNum(value)) return value;
    const kind = FIELD_KIND[field];
    if (quantity === 'absolute_temperature') {
      if (unit === 'degC') return value;
      return kind === 'absolute' ? value * 9 / 5 + 32 : value * 9 / 5;
    }
    return value / MULTIPLY[quantity][unit];
  }

  // ---- validation (twin of sensor_sweep_catalog.validate_role_limits) --------------------------------------------
  function finite(value, what, { positive = false, allowNull = false } = {}) {
    if ((value === null || value === undefined) && allowNull) return null;
    if (!isNum(value)) throw new Error(`${what} must be a finite number, got ${JSON.stringify(value)}`);
    if (positive && value <= 0) throw new Error(`${what} must be > 0, got ${value}`);
    return value;
  }
  function validateRoleLimits(doc, allowlists) {
    if (!doc || typeof doc !== 'object' || doc.version !== 1) throw new Error('role limits: version must be 1');
    const d = doc.defaults;
    if (!d || typeof d !== 'object' || Object.keys(d).length !== DEFAULT_KEYS.length || !DEFAULT_KEYS.every((k) => has(d, k))) {
      throw new Error(`role limits: defaults must have exactly ${DEFAULT_KEYS.join(', ')}`);
    }
    const defaults = Object.fromEntries(DEFAULT_KEYS.map((k) => [k, finite(d[k], `defaults.${k}`, { positive: true })]));
    const roles = {};
    for (const entry of doc.roles || []) {
      if (!entry || typeof entry !== 'object' || Object.keys(entry).length !== ROLE_KEYS.length || !ROLE_KEYS.every((k) => has(entry, k))) {
        throw new Error(`role limits: each role needs exactly ${[...ROLE_KEYS].sort().join(', ')}`);
      }
      const role = entry.role;
      if (typeof role !== 'string' || !role.trim()) throw new Error('role limits: role must be a non-empty string');
      if (has(roles, role)) throw new Error(`role limits: duplicate role ${role}`);
      if (!QUANTITIES.includes(entry.quantity)) throw new Error(`${role}: unknown quantity ${entry.quantity}`);
      if (typeof entry.source !== 'string' || !entry.source.trim()) throw new Error(`${role}: source is required`);
      const lo = finite(entry.lo, `${role}.lo`), hi = finite(entry.hi, `${role}.hi`);
      if (lo >= hi) throw new Error(`${role}: lo (${lo}) must be < hi (${hi})`);
      roles[role] = { role, quantity: entry.quantity, lo, hi, source: entry.source,
        spike_delta: finite(entry.spike_delta, `${role}.spike_delta`, { positive: true, allowNull: true }),
        flat_tol: finite(entry.flat_tol, `${role}.flat_tol`, { positive: true, allowNull: true }),
        stale_tol: finite(entry.stale_tol, `${role}.stale_tol`, { positive: true, allowNull: true }),
        rate_per_h: finite(entry.rate_per_h, `${role}.rate_per_h`, { positive: true, allowNull: true }) };
    }
    for (const [ruleId, names] of Object.entries(allowlists || {})) {
      for (const name of names) {
        const e = roles[name];
        if (!e) throw new Error(`${ruleId}: assessed role ${name} has no limits entry`);
        if (ruleId === 'SV-SPIKE' && e.spike_delta === null) throw new Error(`${ruleId}: role ${name} needs spike_delta`);
        if (ruleId === 'SV-FLATLINE' || ruleId === 'SV-STALE') {
          if (!['absolute_temperature', 'relative_humidity'].includes(e.quantity)) throw new Error(`${ruleId}: role ${name} quantity ${e.quantity} has no declared tolerance`);
          const field = ruleId === 'SV-FLATLINE' ? 'flat_tol' : 'stale_tol';
          if (e.quantity === 'relative_humidity' && e[field] === null) throw new Error(`${ruleId}: humidity role ${name} needs ${field}`);
        }
      }
    }
    return { defaults, roles };
  }

  // ---- overrides -------------------------------------------------------------------------------------------------
  const equipScope = (equipId) => {
    if (typeof equipId !== 'string' || !equipId) throw new Error('equipment id is required for an equipment scope');
    return EQUIP_SCOPE_PREFIX + equipId;
  };
  function normalizeOverride(params, shipped) {
    if (!params || typeof params !== 'object' || params.version !== 1) throw new Error('override: version must be 1');
    const roles = params.roles;
    if (!roles || typeof roles !== 'object' || Array.isArray(roles)) throw new Error('override: roles must be an object');
    const known = new Set(shipped.roles.map((e) => e.role));
    const out = {};
    for (const [role, fields] of Object.entries(roles)) {
      if (!known.has(role)) throw new Error(`override: unknown role ${role}`);
      if (!fields || typeof fields !== 'object' || !Object.keys(fields).length) throw new Error(`override: ${role} needs at least one field`);
      out[role] = {};
      for (const [field, value] of Object.entries(fields)) {
        if (!has(FIELD_KIND, field)) throw new Error(`override: ${role}.${field} is not editable (${Object.keys(FIELD_KIND).join(', ')})`);
        if (!isNum(value)) throw new Error(`override: ${role}.${field} must be a finite SI number`);
        out[role][field] = value;
      }
    }
    const doc = { version: 1, roles: out };
    for (const k of ['note', 'reset', 'rollback_of']) if (has(params, k)) doc[k] = params[k];
    return doc;
  }
  /** { doc, sources }: shipped document with the site then the equipment override applied (not validated yet). */
  function merge(shipped, site, equipment, revisions = {}) {
    const base = JSON.parse(JSON.stringify(shipped));
    const sources = {};
    const byRole = {};
    for (const e of base.roles) { byRole[e.role] = e; sources[e.role] = Object.fromEntries(Object.keys(FIELD_KIND).map((f) => [f, 'shipped'])); }
    for (const [layer, override] of [['site', site], ['equipment', equipment]]) {
      if (!override) continue;
      const doc = normalizeOverride(override, base);
      const rev = revisions[layer];
      for (const [role, fields] of Object.entries(doc.roles)) {
        for (const [field, value] of Object.entries(fields)) { byRole[role][field] = value; sources[role][field] = layer; }
        byRole[role].source = `${layer} override` + (rev != null ? ` revision ${rev}` : '');
      }
    }
    return { doc: base, sources };
  }
  function effectiveRoleLimits(shipped, allowlists, site, equipment) {
    return validateRoleLimits(merge(shipped, site, equipment).doc, allowlists);
  }

  // ---- Python-identical number text --------------------------------------------------------------------------------
  /** Python repr(float). */
  function pyRepr(x) {
    if (!Number.isFinite(x)) throw new Error('non-finite');
    if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
    const [mant, expText] = x.toExponential().split('e');
    const exp = Number(expText);
    const neg = mant.startsWith('-');
    const digits = mant.replace('-', '').replace('.', '');
    if (exp < -4 || exp >= 16) {
      const m = digits.length > 1 ? digits[0] + '.' + digits.slice(1) : digits;
      const e = Math.abs(exp) < 10 ? '0' + Math.abs(exp) : String(Math.abs(exp));
      return (neg ? '-' : '') + m + 'e' + (exp < 0 ? '-' : '+') + e;
    }
    let s;
    if (exp < 0) s = '0.' + '0'.repeat(-exp - 1) + digits;
    else if (digits.length <= exp + 1) s = digits + '0'.repeat(exp + 1 - digits.length) + '.0';
    else s = digits.slice(0, exp + 1) + '.' + digits.slice(exp + 1);
    return (neg ? '-' : '') + s;
  }
  /** Exact decimal from text: { n: BigInt, s: scale } (value = n / 10^s). */
  function dec(text) {
    let [m, e] = String(text).toLowerCase().split('e');
    let exp = e ? Number(e) : 0;
    const neg = m.startsWith('-');
    m = m.replace('-', '');
    const [ip, fp = ''] = m.split('.');
    let n = BigInt(ip + fp || '0');
    let s = fp.length - exp;
    if (s < 0) { n *= 10n ** BigInt(-s); s = 0; }
    return { n: neg ? -n : n, s };
  }
  /** @param {{n: bigint, s: number}} a @param {{n: bigint, s: number}} b @returns {[bigint, bigint, number]} */
  const align = (a, b) => {
    const s = Math.max(a.s, b.s);
    return [a.n * 10n ** BigInt(s - a.s), b.n * 10n ** BigInt(s - b.s), s];
  };
  const decAdd = (a, b) => { const [x, y, s] = align(a, b); return { n: x + y, s }; };
  const decSub = (a, b) => { const [x, y, s] = align(a, b); return { n: x - y, s }; };
  const decHalf = (a) => ({ n: a.n * 5n, s: a.s + 1 });
  function decText({ n, s }) {
    const neg = n < 0n;
    let t = (neg ? -n : n).toString().padStart(s + 1, '0');
    if (s > 0) t = t.slice(0, -s) + '.' + t.slice(-s);
    return (neg ? '-' : '') + t;
  }
  /** Quantize to 6 decimals, ROUND_HALF_UP (away from zero on a tie), like Decimal.quantize. */
  function quantize6(d) {
    if (d.s <= 6) return d;
    const div = 10n ** BigInt(d.s - 6);
    const neg = d.n < 0n;
    const a = neg ? -d.n : d.n;
    let q = a / div;
    if ((a % div) * 2n >= div) q += 1n;
    return { n: neg ? -q : q, s: 6 };
  }
  /** render_rule._num: six-decimal SI literal (half-up), e.g. 1.666667, 20.0, 870.94. */
  const numText = (d) => pyRepr(Number(decText(quantize6(d))));
  const num = (value) => numText(dec(pyRepr(value)));

  /** Python json.dumps(obj, sort_keys=True, separators=(",", ":")) for plain JSON data (floats as Python writes them). */
  function pyJson(v) {
    if (v === null || v === undefined) return 'null';
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'number') return Number.isInteger(v) && !String(v).includes('e') ? pyRepr(v) : pyRepr(v);
    if (typeof v === 'string') return JSON.stringify(v).replace(/[\u007f-\uffff]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
    if (Array.isArray(v)) return '[' + v.map(pyJson).join(',') + ']';
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + pyJson(v[k])).join(',') + '}';
  }
  /** Layers in effect, canonical (the text configHash hashes; Python config_hash hashes the same text). */
  function configText(site, equipment) {
    const layers = {};
    if (site && site.roles && Object.keys(site.roles).length) layers.site = site.roles;
    if (equipment && equipment.roles && Object.keys(equipment.roles).length) layers.equipment = equipment.roles;
    return Object.keys(layers).length ? pyJson(layers) : '';
  }

  // ---- sweep fragments (twin of render_rule._sweep_fragments) -------------------------------------------------------
  const RANGE_SCALE = { absolute_temperature: '{{RANGE_SCALE_TEMPERATURE}}', relative_humidity: '{{RANGE_SCALE_HUMIDITY}}', air_pressure: '{{RANGE_SCALE_PRESSURE}}' };
  const SPIKE_SCALE = { absolute_temperature: '{{SPIKE_SCALE_TEMPERATURE}}', relative_humidity: '{{SPIKE_SCALE_HUMIDITY}}', air_pressure: '{{SPIKE_SCALE_PRESSURE}}' };
  function explicitRoleValue(entry, field, limits) {
    const value = entry[field];
    if (value === null || value === undefined) return null;
    const d = limits.defaults;
    if (field === 'rate_per_h') return value === d.rate_per_h ? null : value;
    if (entry.quantity === 'absolute_temperature') return value === d[`${field}_temperature`] ? null : value;
    return value;
  }
  function sweepFragment(ruleId, limits, sqlRoles) {
    const entries = Object.keys(limits.roles).filter((n) => has(sqlRoles, n)).map((n) => limits.roles[n]);
    if (ruleId === 'SV-RANGE') {
      return entries.map((e) => {
        const lo = dec(pyRepr(e.lo)), hi = dec(pyRepr(e.hi));
        const c = numText(decHalf(decAdd(lo, hi)));
        const h = numText(decHalf(decSub(hi, lo)));
        const scale = RANGE_SCALE[e.quantity];
        const hs = h + (scale ? ' * ' + scale : '');
        return `(sensor_role = '${sqlRoles[e.role]}' AND (value < (${c} - ${hs}) OR value > (${c} + ${hs})))`;
      }).join(' OR ');
    }
    if (ruleId === 'SV-SPIKE') {
      return entries.map((e) => {
        const scale = SPIKE_SCALE[e.quantity];
        const lim = num(e.spike_delta) + (scale ? ' * ' + scale : '');
        return `(sensor_role = '${sqlRoles[e.role]}' AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > ${lim})`;
      }).join(' OR ');
    }
    if (ruleId === 'SV-FLATLINE' || ruleId === 'SV-STALE') {
      const [field, tuner] = ruleId === 'SV-FLATLINE' ? ['flat_tol', '{{FLATLINE_TOL}}'] : ['stale_tol', '{{STALE_TOL}}'];
      const groups = new Map();
      for (const e of entries) {
        const v = explicitRoleValue(e, field, limits);
        if (v === null) continue;
        const k = num(v);
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(sqlRoles[e.role]);
      }
      const whens = [...groups].map(([v, roles]) => ' WHEN sensor_role IN (' + roles.map((r) => `'${r}'`).join(',') + ') THEN ' + v).join('');
      return whens ? `CASE${whens} ELSE ${tuner} END` : tuner;
    }
    if (ruleId === 'SV-RATE') {
      const base = '({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0)';
      let whens = '';
      for (const e of entries) {
        const v = explicitRoleValue(e, 'rate_per_h', limits);
        if (v !== null) whens += ` WHEN sensor_role = '${sqlRoles[e.role]}' THEN (${num(v)} * {{SENSOR_SPAN}} / 100.0)`;
      }
      return whens ? `(CASE${whens} ELSE ${base} END)` : base;
    }
    throw new Error(`${ruleId} has no role-limit fragment`);
  }
  /** A template's SQL (rule or timeline) for these limits (twin of render_rule.fill_template). */
  function fillTemplate(templateSql, ruleId, values, sqlRoles, limits) {
    const key = FRAGMENT_KEYS[ruleId];
    const text = sweepFragment(ruleId, limits, sqlRoles).replace(/\{\{([A-Z_0-9]+)\}\}/g, (_, k) => {
      if (!has(values, k)) throw new Error(`Unresolved placeholder ${k} in the ${ruleId} fragment`);
      return values[k];
    });
    return templateSql.split(`__OFDD_${key}__`).join(text);
  }
  /** {ruleId: {sql, timeline_sql}} of the five sweeps for these limits, from a postgres pack's role_limit_templates. */
  function renderSweeps(pack, limits) {
    const out = {};
    const t = pack && pack.role_limit_templates;
    if (!t) throw new Error('pack has no role_limit_templates (rebuild with scripts/nf/build_sql_pack.py)');
    for (const [ruleId, tpl] of Object.entries(t.rules)) {
      out[ruleId] = { sql: fillTemplate(tpl.sql, ruleId, tpl.values, tpl.sql_roles, limits),
        timeline_sql: tpl.timeline_sql ? fillTemplate(tpl.timeline_sql, ruleId, tpl.values, tpl.sql_roles, limits) : null };
    }
    return out;
  }

  const exported = { LIMITS_RULE_ID, SITE_SCOPE, EQUIP_SCOPE_PREFIX, SWEEP_RULES, FIELD_KIND, FIELD_RULES, FRAGMENT_KEYS, SI_UNIT, MULTIPLY,
    displayUnits, toSi, fromSi, validateRoleLimits, equipScope, normalizeOverride, merge, effectiveRoleLimits,
    pyRepr, num, pyJson, configText, explicitRoleValue, sweepFragment, fillTemplate, renderSweeps };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  root.ofddRoleLimits = exported;
})(typeof globalThis !== 'undefined' ? globalThis : this);
