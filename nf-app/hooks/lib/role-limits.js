// GENERATED COPY of shared/role-limits.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
'use strict';
/**
 * Sensor-sweep role-limit overrides (#1589), the JS twin of open_fdd/rules/role_limit_overrides.py and of the sweep
 * fragment rendering in sql/fdd/render_rule.py. One file, two runtimes: the fdd / tuning hooks (CommonJS) and the
 * Full edition's tuning editor (browser global `ofddRoleLimits`). Full edition only (Lite has no editor).
 *
 * SI only in storage. An override is { version: 1, roles: { "<role>": { lo?, hi?, spike_delta?, flat_tol?, stale_tol?,
 * rate_per_h? } } }, one revision of fdd.rule_config (rule_id "SV-LIMITS", scope_key "site" or "equip:<equipment id>").
 * Precedence per field: shipped file (open_fdd/data/sensor_sweep_limits.json), then site, then equipment.
 * #1763: an override may also carry sensors: { "<series id>": { role, lo?, hi?, ... } }: that one point's own values,
 * which win over every role value (equipment over site per field) and never touch another point of the same role.
 * The merged document is validated exactly like validate_role_limits() before a save, and the hook re-renders the
 * five sweep rules from the pack's role_limit_templates (byte-identical to the pack SQL with the shipped limits).
 */
(function (root) {
  const LIMITS_RULE_ID = 'SV-LIMITS';
  const SITE_SCOPE = 'site';
  const EQUIP_SCOPE_PREFIX = 'equip:';
  // #1673: SV-STALE is a missing-data rule with no per-role value limit; stale_tol is retired (kept readable, used by no rule).
  const SWEEP_RULES = ['SV-RANGE', 'SV-SPIKE', 'SV-FLATLINE', 'SV-RATE'];
  const FIELD_KIND = { lo: 'absolute', hi: 'absolute', spike_delta: 'difference', flat_tol: 'difference', stale_tol: 'difference', rate_per_h: 'rate' };
  const FIELD_RULES = { lo: ['SV-RANGE'], hi: ['SV-RANGE'], spike_delta: ['SV-SPIKE'], flat_tol: ['SV-FLATLINE'], stale_tol: [], rate_per_h: ['SV-RATE'] };
  const FRAGMENT_KEYS = { 'SV-RANGE': 'SV_RANGE_BANDS', 'SV-SPIKE': 'SV_SPIKE_BANDS', 'SV-FLATLINE': 'SV_FLATLINE_TOL', 'SV-RATE': 'SV_RATE_THRESHOLD' };
  const QUANTITIES = ['absolute_temperature', 'relative_humidity', 'air_pressure', 'volume_flow', 'power'];
  const DEFAULT_KEYS = ['flat_tol_temperature', 'stale_tol_temperature', 'rate_per_h', 'flat_s', 'stale_s'];
  const ROLE_KEYS = ['role', 'quantity', 'lo', 'hi', 'spike_delta', 'flat_tol', 'stale_tol', 'rate_per_h', 'source'];
  const SENSOR_KEYS = [...ROLE_KEYS, 'series_id', 'fields'];
  const SENSOR_FIELDS = ['lo', 'hi', 'spike_delta', 'flat_tol', 'stale_tol', 'rate_per_h'];
  // A series id is rendered into SQL as a literal: the same characters as sensor_sweep_catalog.SERIES_ID_RE.
  const SERIES_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$/;
  const SENSOR_RULE_FIELDS = { 'SV-RANGE': ['lo', 'hi'], 'SV-SPIKE': ['spike_delta'], 'SV-FLATLINE': ['flat_tol'], 'SV-RATE': ['rate_per_h'] };
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
  const UNIT_ALIAS = {
    'l/s': 'L/s', 'l/sec': 'L/s', lpersec: 'L/s', 'l-per-sec': 'L/s',
    cfm: 'cfm', 'ft3/min': 'cfm', ft3permin: 'cfm', 'ft3-per-min': 'cfm',
    inh2o: 'inH2O', inh20: 'inH2O', 'in h2o': 'inH2O', 'in h20': 'inH2O',
    '%rh': '%RH', percentrh: '%RH', percent_rh: '%RH',
    pa: 'Pa', psi: 'psi', gpm: 'gpm',
  };
  function canonUnit(unit) {
    const fold = String(unit || '').trim().toLowerCase().replaceAll('₂', '2').replaceAll('₀', '0').replaceAll('³', '3');
    const squashed = fold.replace(/[\s_-]/g, '');
    return UNIT_ALIAS[fold] || UNIT_ALIAS[squashed] || unit;
  }

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
    const named = canonUnit(unit);
    const f = (MULTIPLY[quantity] || {})[named];
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
    return value / MULTIPLY[quantity][canonUnit(unit)];
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
    const limitEntry = (entry, what) => {
      if (!QUANTITIES.includes(entry.quantity)) throw new Error(`${what}: unknown quantity ${entry.quantity}`);
      if (typeof entry.source !== 'string' || !entry.source.trim()) throw new Error(`${what}: source is required`);
      const lo = finite(entry.lo, `${what}.lo`), hi = finite(entry.hi, `${what}.hi`);
      if (lo >= hi) throw new Error(`${what}: lo (${lo}) must be < hi (${hi})`);
      return { role: entry.role, quantity: entry.quantity, lo, hi, source: entry.source,
        spike_delta: finite(entry.spike_delta, `${what}.spike_delta`, { positive: true, allowNull: true }),
        flat_tol: finite(entry.flat_tol, `${what}.flat_tol`, { positive: true, allowNull: true }),
        stale_tol: finite(entry.stale_tol, `${what}.stale_tol`, { positive: true, allowNull: true }),
        rate_per_h: finite(entry.rate_per_h, `${what}.rate_per_h`, { positive: true, allowNull: true }) };
    };
    const exactKeys = (entry, keys) => entry && typeof entry === 'object' && Object.keys(entry).length === keys.length && keys.every((k) => has(entry, k));
    const roles = {};
    for (const entry of doc.roles || []) {
      if (!exactKeys(entry, ROLE_KEYS)) throw new Error(`role limits: each role needs exactly ${[...ROLE_KEYS].sort().join(', ')}`);
      const role = entry.role;
      if (typeof role !== 'string' || !role.trim()) throw new Error('role limits: role must be a non-empty string');
      if (has(roles, role)) throw new Error(`role limits: duplicate role ${role}`);
      roles[role] = limitEntry(entry, role);
    }
    const sensors = {};
    for (const entry of doc.sensors || []) {
      if (!exactKeys(entry, SENSOR_KEYS)) throw new Error(`sensor limits: each sensor needs exactly ${[...SENSOR_KEYS].sort().join(', ')}`);
      const sid = entry.series_id;
      if (typeof sid !== 'string' || !SERIES_ID_RE.test(sid)) throw new Error(`sensor limits: invalid series id ${JSON.stringify(sid)}`);
      if (has(sensors, sid)) throw new Error(`sensor limits: duplicate series id ${sid}`);
      const role = has(roles, entry.role) ? roles[entry.role] : null;
      if (!role) throw new Error(`sensor ${sid}: unknown role ${entry.role}`);
      const fields = entry.fields;
      if (!Array.isArray(fields) || !fields.length || fields.some((f) => !SENSOR_FIELDS.includes(f))) {
        throw new Error(`sensor ${sid}: fields must name its own limits (${SENSOR_FIELDS.join(', ')})`);
      }
      if (entry.quantity !== role.quantity) throw new Error(`sensor ${sid}: quantity ${entry.quantity} != role quantity ${role.quantity}`);
      sensors[sid] = { ...limitEntry(entry, `sensor ${sid}`), series_id: sid, fields: [...new Set(fields)].sort() };
    }
    for (const [ruleId, names] of Object.entries(allowlists || {})) {
      for (const name of names) {
        const e = roles[name];
        if (!e) throw new Error(`${ruleId}: assessed role ${name} has no limits entry`);
        if (ruleId === 'SV-SPIKE' && e.spike_delta === null) throw new Error(`${ruleId}: role ${name} needs spike_delta`);
        if (ruleId === 'SV-FLATLINE') {
          if (!['absolute_temperature', 'relative_humidity'].includes(e.quantity)) throw new Error(`${ruleId}: role ${name} quantity ${e.quantity} has no declared tolerance`);
          const field = 'flat_tol';
          if (e.quantity === 'relative_humidity' && e[field] === null) throw new Error(`${ruleId}: humidity role ${name} needs ${field}`);
        }
      }
    }
    return { defaults, roles, sensors };
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
    const sensors = params.sensors;
    if (sensors !== undefined && sensors !== null) {
      if (typeof sensors !== 'object' || Array.isArray(sensors)) throw new Error('override: sensors must be an object');
      doc.sensors = {};
      for (const [sid, fields] of Object.entries(sensors)) {
        if (!SERIES_ID_RE.test(sid)) throw new Error(`override: invalid series id ${JSON.stringify(sid)}`);
        if (!fields || typeof fields !== 'object' || !known.has(fields.role)) throw new Error(`override: sensor ${sid} needs a known role`);
        const own = Object.entries(fields).filter(([k]) => k !== 'role');
        if (!own.length) throw new Error(`override: sensor ${sid} needs at least one field`);
        const entry = { role: fields.role };
        for (const [field, value] of own) {
          if (!has(FIELD_KIND, field)) throw new Error(`override: sensor ${sid}.${field} is not editable (${Object.keys(FIELD_KIND).join(', ')})`);
          if (!isNum(value)) throw new Error(`override: sensor ${sid}.${field} must be a finite SI number`);
          entry[field] = value;
        }
        doc.sensors[sid] = entry;
      }
    }
    for (const k of ['note', 'reset', 'rollback_of']) if (has(params, k)) doc[k] = params[k];
    return doc;
  }
  /** { doc, sources }: shipped document with the site then the equipment override applied (not validated yet). */
  function merge(shipped, site, equipment, revisions = {}) {
    const base = JSON.parse(JSON.stringify(shipped));
    const sources = {};
    const byRole = {};
    for (const e of base.roles) { byRole[e.role] = e; sources[e.role] = Object.fromEntries(Object.keys(FIELD_KIND).map((f) => [f, 'shipped'])); }
    /** @type {Record<string, any>} series id -> { role, field: value, _layer: { field: layer }, _label } */
    const own = {};
    for (const [layer, override] of [['site', site], ['equipment', equipment]]) {
      if (!override) continue;
      const doc = normalizeOverride(override, base);
      const rev = revisions[layer];
      const label = `${layer} override` + (rev != null ? ` revision ${rev}` : '');
      for (const [role, fields] of Object.entries(doc.roles)) {
        for (const [field, value] of Object.entries(fields)) { byRole[role][field] = value; sources[role][field] = layer; }
        byRole[role].source = label;
      }
      for (const [sid, fields] of Object.entries(doc.sensors || {})) {
        const cur = has(own, sid) ? own[sid] : (own[sid] = { role: fields.role, _layer: {} });
        if (cur.role !== fields.role) throw new Error(`override: sensor ${sid} is ${cur.role} at one scope and ${fields.role} at another`);
        for (const [field, value] of Object.entries(fields)) if (field !== 'role') { cur[field] = value; cur._layer[field] = layer; }
        cur._label = `${label} (sensor)`;
      }
    }
    const sids = Object.keys(own).sort();
    if (sids.length) {
      // #1763: a sensor = its role's merged entry with its own fields on top (validated with the roles)
      base.sensors = sids.map((sid) => {
        const cur = own[sid];
        const fields = Object.keys(cur._layer).sort();
        sources[`sensor:${sid}`] = Object.fromEntries(Object.keys(FIELD_KIND).map((f) => [f, cur._layer[f] || 'role']));
        return { ...byRole[cur.role], ...Object.fromEntries(fields.map((f) => [f, cur[f]])), source: cur._label, series_id: sid, fields };
      });
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
    // #1763: per-sensor values under their own keys, so a config without them keeps its earlier hash
    if (site && site.sensors && Object.keys(site.sensors).length) layers.site_sensors = site.sensors;
    if (equipment && equipment.sensors && Object.keys(equipment.sensors).length) layers.equipment_sensors = equipment.sensors;
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
    // #1763: a sensor with its own value for this rule gets its own arm (series_id = '<id>'), first; its role's arm leaves it out
    const sensors = limits.sensors || {};
    const own = Object.keys(sensors).sort().map((sid) => sensors[sid])
      .filter((s) => has(sqlRoles, s.role) && (SENSOR_RULE_FIELDS[ruleId] || []).some((f) => s.fields.includes(f)));
    const sidOf = (s) => `series_id = '${s.series_id}'`;   // validated by SERIES_ID_RE: safe as a SQL literal
    const exclude = (role) => {
      const ids = own.filter((s) => s.role === role).map((s) => `'${s.series_id}'`);
      return ids.length ? ` AND series_id NOT IN (${ids.join(',')})` : '';
    };
    const heads = [...own.map((s) => [s, `${sidOf(s)} AND sensor_role = '${sqlRoles[s.role]}'`]),
      ...entries.map((e) => [e, `sensor_role = '${sqlRoles[e.role]}'${exclude(e.role)}`])];
    if (ruleId === 'SV-RANGE') {
      return heads.map(([e, head]) => {
        const lo = dec(pyRepr(e.lo)), hi = dec(pyRepr(e.hi));
        const c = numText(decHalf(decAdd(lo, hi)));
        const h = numText(decHalf(decSub(hi, lo)));
        const scale = RANGE_SCALE[e.quantity];
        const hs = h + (scale ? ' * ' + scale : '');
        return `(${head} AND (value < (${c} - ${hs}) OR value > (${c} + ${hs})))`;
      }).join(' OR ');
    }
    if (ruleId === 'SV-SPIKE') {
      return heads.map(([e, head]) => {
        const scale = SPIKE_SCALE[e.quantity];
        const lim = num(e.spike_delta) + (scale ? ' * ' + scale : '');
        return `(${head} AND previous_value IS NOT NULL AND epoch_seconds - previous_epoch <= {{MAX_SILENCE_SECONDS}} AND ABS(value - previous_value) > ${lim})`;
      }).join(' OR ');
    }
    if (ruleId === 'SV-FLATLINE') {
      const [field, tuner] = ['flat_tol', '{{FLATLINE_TOL}}'];
      const groups = new Map();
      for (const e of entries) {
        const v = explicitRoleValue(e, field, limits);
        if (v === null) continue;
        const k = num(v);
        if (!groups.has(k)) groups.set(k, []);
        groups.get(k).push(sqlRoles[e.role]);
      }
      const whens = own.map((s) => ` WHEN ${sidOf(s)} THEN ${num(s[field])}`).join('')
        + [...groups].map(([v, roles]) => ' WHEN sensor_role IN (' + roles.map((r) => `'${r}'`).join(',') + ') THEN ' + v).join('');
      return whens ? `CASE${whens} ELSE ${tuner} END` : tuner;
    }
    if (ruleId === 'SV-RATE') {
      const base = '({{STEADY_FAULT_PER_HOUR}} * {{SENSOR_SPAN}} / 100.0)';
      let whens = own.map((s) => ` WHEN ${sidOf(s)} THEN (${num(s.rate_per_h)} * {{SENSOR_SPAN}} / 100.0)`).join('');
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
