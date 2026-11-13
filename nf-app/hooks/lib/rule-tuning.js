// GENERATED COPY of shared/rule-tuning.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
'use strict';
/**
 * Per-rule SQL parameter tuning (5.0.17), the JS twin of sql/fdd/render_rule.py lines 121-192.
 * One file, two runtimes: the fdd / tuning hooks (CommonJS) and the Full edition's FDD Tuners panel
 * (browser global `ofddRuleTuning`).
 *
 * SI only in storage (`fdd.rule_config`, `rule_id = "<RULE_ID>"`, `scope_key = "site" | "equip:<id>"`).
 * Override document shape: { version: 1, params: { "<key>": <finite SI number | 0 | 1> }, note?, reset?, rollback_of? }.
 * Precedence per parameter: shipped default (`controls[k].default`), then `site`, then `equip:<id>`.
 */
(function (root) {
  const SITE_SCOPE = 'site';
  const EQUIP_SCOPE_PREFIX = 'equip:';
  const PLACEHOLDER_RE = /\{\{([A-Z_0-9]+)\}\}/g;

  // Canonical unit conversion factors matching open_fdd/data/unit_factors.json.
  const FACTORS = {
    air_pressure: { si: 'Pa', units: { Pa: 1, inH2O: 249.0889, psi: 6894.757 }, ip: 'inH2O' },
    hydronic_pressure: { si: 'Pa', units: { Pa: 1, psi: 6894.757 }, ip: 'psi' },
    volumetric_flow: { si: 'L/s', units: { 'L/s': 1, cfm: 0.4719474, gpm: 0.0630902 }, ip: 'cfm' },
    interval_energy: { si: 'kWh', units: { kWh: 1, kBtu: 0.29307107 }, ip: 'kBtu' },
  };
  const FLOW_GPM_RULES = new Set(['CHW-4']);

  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

  function prettyCatalogUnit(unit) {
    if (unit === 'degC_delta') return 'degC';
    if (unit === 'degC_delta_per_h') return 'degC/h';
    if (unit === 'L_per_s') return 'L/s';
    if (unit === 'pct') return '%';
    return unit || '';
  }

  /** Available display units for a control. */
  function displayUnits(control, ruleId) {
    if (!control) return [];
    const k = control.kind;
    if (k === 'absolute_temperature' || k === 'temperature_difference') return ['degC', 'degF'];
    if (k === 'temperature_rate') return ['degC/h', 'degF/h'];
    if (FACTORS[k]) return Object.keys(FACTORS[k].units);
    if (k === 'boolean') return ['bool'];
    if (k === 'percent') return ['%'];
    return [prettyCatalogUnit(control.unit)];
  }

  /** Preferred display unit for `system` ('si' | 'ip'). */
  function preferredDisplayUnit(control, system = 'si', ruleId = '') {
    if (!control) return '';
    const k = control.kind;
    const isIp = String(system).toLowerCase() === 'ip' || String(system).toLowerCase() === 'imperial';
    if (k === 'absolute_temperature' || k === 'temperature_difference') return isIp ? 'degF' : 'degC';
    if (k === 'temperature_rate') return isIp ? 'degF/h' : 'degC/h';
    if (k === 'volumetric_flow') return isIp ? (FLOW_GPM_RULES.has(ruleId) ? 'gpm' : 'cfm') : 'L/s';
    if (FACTORS[k]) return isIp ? FACTORS[k].ip : FACTORS[k].si;
    return displayUnits(control, ruleId)[0] || '';
  }

  /** Convert an editor value in `unit` to SI (`control.unit` space). */
  function toSi(value, unit, kind) {
    if (kind === 'boolean') {
      if (value === true || value === 1) return 1;
      if (value === false || value === 0) return 0;
      throw new Error('boolean parameter must be true/false or 1/0');
    }
    if (!isNum(value)) throw new Error('value must be a finite number');
    if (kind === 'absolute_temperature') {
      if (unit === 'degC') return value;
      if (unit === 'degF') return (value - 32) * 5 / 9;
      throw new Error(`unsupported unit ${unit} for ${kind}`);
    }
    if (kind === 'temperature_difference') {
      if (unit === 'degC' || unit === 'degC_delta') return value;
      if (unit === 'degF' || unit === 'degF_delta') return value * 5 / 9;
      throw new Error(`unsupported unit ${unit} for ${kind}`);
    }
    if (kind === 'temperature_rate') {
      if (unit === 'degC/h' || unit === 'degC_delta_per_h') return value;
      if (unit === 'degF/h') return value * 5 / 9;
      throw new Error(`unsupported unit ${unit} for ${kind}`);
    }
    if (FACTORS[kind]) {
      const f = FACTORS[kind].units[unit] ?? (unit === 'L_per_s' ? FACTORS[kind].units['L/s'] : undefined);
      if (f === undefined) throw new Error(`unsupported unit ${unit} for ${kind}`);
      return value * f;
    }
    return value;
  }

  /** Convert an SI parameter value to display `unit`. */
  function fromSi(value, unit, kind) {
    if (kind === 'boolean') return Number(value) ? 1 : 0;
    if (!isNum(value)) return value;
    if (kind === 'absolute_temperature') {
      return unit === 'degF' ? value * 9 / 5 + 32 : value;
    }
    if (kind === 'temperature_difference') {
      return unit === 'degF' || unit === 'degF_delta' ? value * 9 / 5 : value;
    }
    if (kind === 'temperature_rate') {
      return unit === 'degF/h' ? value * 9 / 5 : value;
    }
    if (FACTORS[kind]) {
      const f = FACTORS[kind].units[unit] ?? (unit === 'L_per_s' ? FACTORS[kind].units['L/s'] : undefined);
      if (f === undefined) return value;
      return value / f;
    }
    return value;
  }

  /** Validate and normalize one rule-level override document: { version: 1, params: { ... } }. */
  function normalizeRuleOverride(doc, controls, ruleId = '') {
    if (!doc || typeof doc !== 'object' || Array.isArray(doc) || doc.version !== 1) {
      throw new Error(`${ruleId || 'rule'} override: version must be 1`);
    }
    if (!doc.params || typeof doc.params !== 'object' || Array.isArray(doc.params)) {
      throw new Error(`${ruleId || 'rule'} override: params must be an object`);
    }
    const out = {};
    for (const [key, raw] of Object.entries(doc.params)) {
      if (!controls || !has(controls, key)) {
        throw new Error(`${ruleId ? ruleId + '.' : ''}${key} is not a tunable SQL parameter`);
      }
      const ctrl = controls[key];
      let val = raw;
      if (ctrl.kind === 'boolean') {
        if (raw === true || raw === 1) val = 1;
        else if (raw === false || raw === 0) val = 0;
        else throw new Error(`${key} must be boolean (0/1 or true/false)`);
      } else {
        if (typeof raw === 'boolean' || !isNum(raw)) {
          throw new Error(`${key} must be a finite number`);
        }
        if (raw < ctrl.min || raw > ctrl.max) {
          throw new Error(`${key} (${raw}) outside [${ctrl.min}, ${ctrl.max}]`);
        }
      }
      out[key] = val;
    }
    const clean = { version: 1, params: out };
    for (const meta of ['note', 'reset', 'rollback_of']) {
      if (has(doc, meta) && doc[meta] !== undefined) clean[meta] = doc[meta];
    }
    return clean;
  }

  /** Merge shipped defaults < site override < equipment override for one rule. */
  function mergeRuleParams(controls, siteDoc, equipDoc, ruleId = '') {
    const effective = {};
    const sources = {};
    const overrideKeys = new Set();
    for (const [k, d] of Object.entries(controls || {})) {
      effective[k] = d.default;
      sources[k] = 'shipped';
    }
    for (const [layer, doc] of [['site', siteDoc], ['equip', equipDoc]]) {
      if (!doc) continue;
      const clean = normalizeRuleOverride(doc, controls, ruleId);
      for (const [k, v] of Object.entries(clean.params)) {
        effective[k] = v;
        sources[k] = layer;
        overrideKeys.add(k);
      }
    }
    return { effective, sources, overrideKeys };
  }

  /** Python-compatible float/int SQL literal formatting (render_rule.py::_format_value). */
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

  function formatRuleValue(value) {
    if (!isNum(value)) throw new Error(`non-finite value ${value}`);
    if (Number.isInteger(value)) return String(Object.is(value, -0) ? 0 : value);
    return pyRepr(value);
  }

  /** Exact JS twin of render_rule.py lines 121-163. */
  function resolvePlaceholders(runtimeDefaults, controls, effective, overrideKeys = new Set(), pollSeconds = 300) {
    if (!isNum(pollSeconds) || pollSeconds < 1) throw new Error('pollSeconds must be finite and >= 1');
    const values = { ...(runtimeDefaults || {}) };
    for (const [k, d] of Object.entries(controls || {})) {
      if (k !== 'confirm_min' && d.sql_placeholder) {
        values[d.sql_placeholder] = has(effective, k) ? effective[k] : d.default;
      }
    }
    // Legacy master tolerances propagate only when explicitly overridden and per-sensor eps was not overridden.
    if (overrideKeys.has('mix_tol')) {
      for (const k of ['eps_mat', 'eps_oat', 'eps_rat', 'eps_sat']) {
        if (!overrideKeys.has(k) && has(effective, 'mix_tol')) {
          values[k.toUpperCase()] = effective.mix_tol;
        }
      }
    }
    if (overrideKeys.has('supply_tol') && !overrideKeys.has('eps_sat') && has(effective, 'supply_tol')) {
      values.EPS_SAT = effective.supply_tol;
    }
    values.MODE_DELAY_MIN = Math.max(values.MODE_DELAY_MIN || 0, values.STARTUP_DELAY_MIN || 0);
    values.POLL_SECONDS = pollSeconds;
    const confirmMin = has(effective, 'confirm_min') ? effective.confirm_min : ((values.CONFIRM_SECONDS || 600) / 60);
    values.CONFIRM_SECONDS = confirmMin * 60;
    values.CONFIRM_ROWS = Math.max(1, Math.ceil(values.CONFIRM_SECONDS / pollSeconds));
    for (const [k, v] of Object.entries({ ...values })) {
      if (k.endsWith('_HOURS') && v > 0) {
        const prefix = k.slice(0, -6);
        values[prefix + '_SECONDS'] = Math.round(v * 3600);
        const rows = Math.max(prefix === 'FIXED_FLOW' ? 6 : 1, Math.ceil((v * 3600) / pollSeconds));
        values[prefix + '_ROWS'] = rows;
        values[prefix + '_ROWS_PRECEDING'] = rows - 1;
        values[prefix + '_MIN_PERIODS'] = Math.max(3, Math.floor(rows / 2));
      }
    }
    for (const prefix of ['MODE_DELAY', 'STARTUP_DELAY']) {
      const rows = Math.max(1, Math.ceil(((values[prefix + '_MIN'] || 0) * 60) / pollSeconds));
      values[prefix + '_ROWS'] = rows;
      values[prefix + '_ROWS_PRECEDING'] = rows - 1;
    }
    if (has(values, 'WEB_CADENCE_SECONDS') && has(values, 'WEB_ASOF_MARGIN_SECONDS')) {
      values.WEB_ASOF_BOUND_SECONDS = Math.round(values.WEB_CADENCE_SECONDS + values.WEB_ASOF_MARGIN_SECONDS);
    }
    return values;
  }

  /** Render one rule template (SQL or timeline_sql) using resolved `values` and optional SV role-limit filling. */
  function renderRuleSql(templateSql, values, ruleId = '', roleLimitsOpt = null) {
    if (!templateSql) return null;
    let text = templateSql;
    if (roleLimitsOpt && roleLimitsOpt.fillTemplate && roleLimitsOpt.roleTemplate && roleLimitsOpt.limits) {
      const valStrings = {};
      for (const k of Object.keys(roleLimitsOpt.roleTemplate.values || {})) {
        if (!has(values, k)) throw new Error(`Missing placeholder ${k} for ${ruleId} fragment`);
        valStrings[k] = formatRuleValue(values[k]);
      }
      text = roleLimitsOpt.fillTemplate(text, ruleId, valStrings, roleLimitsOpt.roleTemplate.sql_roles, roleLimitsOpt.limits);
    }
    return text.replace(PLACEHOLDER_RE, (_, key) => {
      if (!has(values, key)) throw new Error(`Unresolved placeholder ${key} in ${ruleId || 'rule'}`);
      return formatRuleValue(values[key]);
    });
  }

  const equipScope = (equipId) => {
    if (typeof equipId !== 'string' || !equipId) throw new Error('equipment id is required for an equipment scope');
    return EQUIP_SCOPE_PREFIX + equipId;
  };

  function canonicalJson(v) {
    if (v === null || typeof v !== 'object') return JSON.stringify(v);
    if (Array.isArray(v)) return '[' + v.map(canonicalJson).join(',') + ']';
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canonicalJson(v[k])).join(',') + '}';
  }

  const api = {
    SITE_SCOPE, EQUIP_SCOPE_PREFIX, equipScope,
    displayUnits, preferredDisplayUnit, toSi, fromSi, prettyCatalogUnit,
    normalizeRuleOverride, mergeRuleParams, formatRuleValue, resolvePlaceholders, renderRuleSql, canonicalJson,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ofddRuleTuning = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
