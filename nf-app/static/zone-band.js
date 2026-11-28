// GENERATED COPY of shared/zone-band.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
'use strict';
/**
 * Occupied zone temperature range (5.0.22): the site's comfort band, one low / high pair that both the zone comfort
 * analytics (the RCx comfort ranking, sql/analytics/zone_comfort.sql {lo}/{hi}) and the zone comfort FDD rules
 * (VAV-1 zone_t_lo / zone_t_hi = {{ZONE_T_LO}} / {{ZONE_T_HI}}, SCHED-1 comfort_low / comfort_high) read.
 * One file, two runtimes: the fdd / tuning hooks (CommonJS, hooks/lib/zone-band.js) and the Overview slider
 * (browser global `ofddZoneBand`, static/zone-band.js). Python twin: open_fdd/analytics/zone_band.py.
 *
 * SI is the storage unit and the default display: the band is { lo_c, hi_c } in degC, saved inside the site's weekly
 * occupancy calendar document (OCC-CALENDAR, fdd.rule_config) as `calendar.zone_band`, so it persists per site next to
 * the occupied hours. Imperial is display only (degF in, degF out; nothing imperial is ever stored).
 *
 * Limits (Ben, 5.0.22): 65 .. 80 degF = 18.3333 .. 26.6667 degC. Default 70 .. 75 degF = 21.1111 .. 23.8889 degC.
 * Minimum deadband between the handles: 2 degF = 10/9 K = 1.1111 K. A band is always inside the limits, never
 * negative, and hi - lo >= MIN_DEADBAND_K.
 *
 * Two entry points, one rule set:
 *   validateBand(raw)  STRICT, for a save / API call: throws on a missing, non-numeric, NaN or inverted (lo > hi) band;
 *                      clamps an out-of-range value into the limits; widens a band narrower than the deadband.
 *   resolveBand(raw)   LENIENT, for reading a stored value: the validated band, else the 70-75 degF default.
 *
 * Precedence into the FDD rules (applyToEffective): shipped default < the site band < an explicit per-rule tuning
 * override (site, then equipment). A parameter the operator tuned on the rule itself always wins over the band.
 */
(function (root) {
  const f2c = (f) => (f - 32) * 5 / 9;
  const c2f = (c) => c * 9 / 5 + 32;
  const LIMIT_LO_C = f2c(65);          // 18.3333 degC
  const LIMIT_HI_C = f2c(80);          // 26.6667 degC
  const DEFAULT_LO_C = f2c(70);        // 21.1111 degC
  const DEFAULT_HI_C = f2c(75);        // 23.8889 degC
  const MIN_DEADBAND_K = 10 / 9;       // 2 degF = 1.1111 K, hi - lo may never be smaller
  const EPS = 1e-9;
  /** Rule parameter pairs that carry the zone comfort band (catalog keys; SI degC). */
  const RULE_PAIRS = [{ lo: 'zone_t_lo', hi: 'zone_t_hi' }, { lo: 'comfort_low', hi: 'comfort_high' }];

  const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
  /** A finite number from a number or a numeric string; anything else (boolean, '', null, NaN, Infinity) is null. */
  function toNumber(v) {
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (typeof v === 'string' && v.trim() !== '') { const n = Number(v); return Number.isFinite(n) ? n : null; }
    return null;
  }
  const defaultBand = () => ({ lo_c: DEFAULT_LO_C, hi_c: DEFAULT_HI_C });
  const isDefault = (b) => !!b && Math.abs(b.lo_c - DEFAULT_LO_C) < EPS && Math.abs(b.hi_c - DEFAULT_HI_C) < EPS;

  /** Widen lo..hi (already inside the limits, lo <= hi) to the minimum deadband, keeping lo where possible. */
  function enforceDeadband(lo, hi) {
    if (hi - lo >= MIN_DEADBAND_K - EPS) return { lo_c: lo, hi_c: hi };
    if (lo + MIN_DEADBAND_K <= LIMIT_HI_C + EPS) return { lo_c: lo, hi_c: Math.min(LIMIT_HI_C, lo + MIN_DEADBAND_K) };
    return { lo_c: LIMIT_HI_C - MIN_DEADBAND_K, hi_c: LIMIT_HI_C };
  }

  /**
   * The canonical band for a save. Throws (Error with a plain message) when raw is missing, not { lo_c, hi_c },
   * non-numeric / NaN, or inverted (lo > hi). Out-of-range and negative values are clamped into [18.3333, 26.6667];
   * a band narrower than MIN_DEADBAND_K is widened (the high handle moves up, or the low one down at the top limit).
   * @param {any} raw @returns {{ lo_c: number, hi_c: number }}
   */
  function validateBand(raw) {
    if (raw == null) throw new Error('zone_band is missing (expected { lo_c, hi_c } in degC)');
    if (typeof raw !== 'object' || Array.isArray(raw)) throw new Error('zone_band must be { lo_c, hi_c } in degC');
    const lo = toNumber(raw.lo_c), hi = toNumber(raw.hi_c);
    if (lo == null || hi == null) throw new Error('zone_band lo_c and hi_c must both be finite numbers (degC)');
    if (lo > hi) throw new Error(`zone_band is inverted: lo_c (${lo}) is above hi_c (${hi})`);
    return enforceDeadband(clamp(lo, LIMIT_LO_C, LIMIT_HI_C), clamp(hi, LIMIT_LO_C, LIMIT_HI_C));
  }

  /**
   * The band to use when READING a stored value (never throws): the validated band, else the 70-75 degF default.
   * `source` is "saved" or "default"; `reason` says why a stored value was not used.
   * @param {any} raw @returns {{ lo_c: number, hi_c: number, source: 'saved' | 'default', reason?: string }}
   */
  function resolveBand(raw) {
    if (raw == null) return { ...defaultBand(), source: 'default', reason: 'no saved band' };
    try { return { ...validateBand(raw), source: 'saved' }; } catch (e) {
      return { ...defaultBand(), source: 'default', reason: /** @type {Error} */ (e).message };
    }
  }

  /**
   * Move one slider handle. `which` is "lo" or "hi", valueC the wanted degC. The handle is clamped to the limits and
   * stops MIN_DEADBAND_K short of the other handle (lo never above hi - deadband, hi never below lo + deadband).
   * A non-finite wanted value changes nothing.
   * @param {{ lo_c: number, hi_c: number }} band @param {'lo' | 'hi'} which @param {number} valueC
   */
  function moveHandle(band, which, valueC) {
    const v = toNumber(valueC);
    const cur = validateBand(band);
    if (v == null) return cur;
    if (which === 'lo') return { lo_c: clamp(v, LIMIT_LO_C, cur.hi_c - MIN_DEADBAND_K), hi_c: cur.hi_c };
    if (which === 'hi') return { lo_c: cur.lo_c, hi_c: clamp(v, cur.lo_c + MIN_DEADBAND_K, LIMIT_HI_C) };
    throw new Error('which must be "lo" or "hi"');
  }

  // ---- display (imperial is display only) -----------------------------------------------------------------------
  const isImperial = (system) => /^(imperial|ip|degf|f)$/i.test(String(system || ''));
  /** degC -> the display system's number ("si" default, "imperial" = degF). */
  const toDisplay = (c, system) => (isImperial(system) ? c2f(c) : c);
  /** The display system's number -> degC. */
  const fromDisplay = (v, system) => (isImperial(system) ? f2c(Number(v)) : Number(v));
  const unitLabel = (system) => (isImperial(system) ? '°F' : '°C');
  /** The slider contract in display units: bounds, step, minimum gap (a temperature DIFFERENCE: K in SI, degF delta). */
  function sliderSpec(system) {
    if (isImperial(system)) return { unit: '°F', min: 65, max: 80, step: 1, decimals: 0, minGap: 2, gapLabel: '2 °F' };
    return { unit: '°C', min: Math.floor(LIMIT_LO_C * 10) / 10, max: Math.ceil(LIMIT_HI_C * 10) / 10, step: 0.1, decimals: 1, minGap: MIN_DEADBAND_K, gapLabel: `${MIN_DEADBAND_K.toFixed(2)} K` };
  }
  /** "21.1–23.9 °C" / "70–75 °F". */
  function describe(band, system) {
    const s = sliderSpec(system), d = s.decimals;
    return `${toDisplay(band.lo_c, system).toFixed(d)}–${toDisplay(band.hi_c, system).toFixed(d)} ${s.unit}`;
  }

  // ---- the FDD rule parameters ----------------------------------------------------------------------------------
  /** The { lo, hi } parameter-key pairs a rule's controls carry (VAV-1: zone_t_lo/hi, SCHED-1: comfort_low/high). */
  const rulePairs = (controls) => RULE_PAIRS.filter((p) => controls && Object.prototype.hasOwnProperty.call(controls, p.lo) && Object.prototype.hasOwnProperty.call(controls, p.hi));

  /**
   * Put the site band under the explicit tuning: for every comfort pair of the rule, a key that was NOT overridden on
   * the rule (not in overrideKeys) takes the band value. An explicit per-rule override always wins. If only one key
   * of a pair is explicit, the band's other value is used only when it keeps hi - lo >= the deadband (else the shipped
   * default stays). Returns a new effective map plus { applied, sources, skipped } for the rule's recorded parameters.
   * @param {any} controls rule controls @param {Record<string, any>} effective @param {Set<string>} overrideKeys
   * @param {{ lo_c: number, hi_c: number } | null} band a validated band (null = nothing to apply)
   */
  function applyToEffective(controls, effective, overrideKeys, band) {
    const out = { ...effective };
    const applied = /** @type {Record<string, number>} */ ({});
    const skipped = /** @type {string[]} */ ([]);
    if (!band) return { effective: out, applied, skipped, pairs: [] };
    const pairs = rulePairs(controls);
    for (const p of pairs) {
      const loSet = overrideKeys.has(p.lo), hiSet = overrideKeys.has(p.hi);
      if (loSet && hiSet) { skipped.push(`${p.lo}/${p.hi}: explicit rule tuning wins`); continue; }
      if (!loSet && !hiSet) { out[p.lo] = band.lo_c; out[p.hi] = band.hi_c; applied[p.lo] = band.lo_c; applied[p.hi] = band.hi_c; continue; }
      if (loSet) {
        if (band.hi_c - out[p.lo] >= MIN_DEADBAND_K - EPS) { out[p.hi] = band.hi_c; applied[p.hi] = band.hi_c; } else skipped.push(`${p.hi}: band high is within the deadband of the tuned ${p.lo}`);
      } else if (out[p.hi] - band.lo_c >= MIN_DEADBAND_K - EPS) { out[p.lo] = band.lo_c; applied[p.lo] = band.lo_c; } else skipped.push(`${p.lo}: band low is within the deadband of the tuned ${p.hi}`);
    }
    return { effective: out, applied, skipped, pairs: pairs.map((p) => `${p.lo}/${p.hi}`) };
  }

  const api = {
    LIMIT_LO_C, LIMIT_HI_C, DEFAULT_LO_C, DEFAULT_HI_C, MIN_DEADBAND_K, RULE_PAIRS,
    defaultBand, isDefault, toNumber, validateBand, resolveBand, moveHandle, enforceDeadband,
    toDisplay, fromDisplay, unitLabel, sliderSpec, describe, rulePairs, applyToEffective,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ofddZoneBand = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);