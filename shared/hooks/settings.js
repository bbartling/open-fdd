'use strict';
/**
 * Hook settings, the way NF 3.10.x actually stores them (5.0.6, #1550).
 *
 * NF does NOT persist a hook-definition `config` (UpdateHook has no such field: the stored hook shows
 * `config: null`), and a hook process gets no app environment. What persists is the app's OPTIONS (Settings of the
 * app in the NF console, or PATCH /api/v1/apps/<id> with updateMask ["options"] + ["configuration"]). The hook
 * runtime hands the option values to the hook as `ctx.config`, one flat map of scalars:
 *
 *   engine       string  "auto" | "sqlite" | "pglite" | "timescale"
 *   windowHours  number  (a string such as "24" is accepted)
 *   timescale    string  (secret) the connection as JSON {"host","port","database","user","password"} or a postgres:// URL
 *   latitude     number  weather: site latitude when neither NF Sites nor the model has one
 *   longitude    number
 *   site         string  weather: which NF site when several have coordinates
 *   weather      bool    weather: false = OFF: no outbound HTTP at all, the hook returns {skipped, reason: "weather disabled"}
 *                        (alias weatherEnabled; default on; see weatherEnabled() below)
 *   exporters    string  weather: where the values go besides the hook variables: "bacnet-av" (default when NF's BACnet
 *                        server is present), a comma list or a JSON array, "none" = variables only
 *   timezone     string  IANA zone for the site when the model site has none (fdd occupancy schedule, charts; #1587)
 *
 * Options cannot hold nested objects, so `timescale` arrives as a STRING; this module turns the scalar form into
 * the object form the code wants. An object (a test, or a future NF that does store hook config) passes through.
 * Nothing here logs or returns a secret: errors name the option and never echo its value.
 */

/** Options whose value is an object/array in the code but arrives as a JSON string in NF options. */
const JSON_OPTIONS = ['timescale', 'history', 'bacnet', 'equips'];
const NUMBER_OPTIONS = ['windowHours', 'latitude', 'longitude', 'writeRetryMs'];
const BOOLEAN_OPTIONS = ['dryRun', 'bacnetMirror', 'bacnet_mirror', 'weather', 'weatherEnabled'];

/** NF typed values, e.g. { string: "x" } / { signed: 24 } / { boolean: true } (as GetApplications shows an option). */
const TYPED_KEYS = ['string', 'signed', 'unsigned', 'double', 'real', 'boolean'];

/** @param {any} v */
function unwrapTyped(v) {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    const keys = Object.keys(v);
    if (keys.length === 1 && TYPED_KEYS.includes(keys[0])) return v[keys[0]];
  }
  return v;
}

/** @param {any} v */
const blank = (v) => v === undefined || v === null || (typeof v === 'string' && v.trim() === '');

/**
 * Where the missing-settings messages point to. Kept in one place so fdd, history and doctor say the same thing.
 */
const TIMESCALE_WHERE = 'set the app option "timescale" (NF console > app settings: a JSON string '
  + '{"host","port","database","user","password"} or a postgres:// URL; docs/install.md) '
  + 'or the hook config "timescale" (an object) on a NF that stores hook config';

/**
 * The Timescale connection as an object, from a string option or an object. Returns null when absent/blank.
 * Throws a clear Error (naming the option, never its value) when it is present but unusable.
 * @param {any} value
 * @returns {Record<string, any> | null}
 */
function parseTimescale(value) {
  const v = unwrapTyped(value);
  if (blank(v)) return null;
  if (typeof v === 'object') return v;
  const text = String(v).trim();
  if (/^postgres(ql)?:\/\//i.test(text)) return { connectionString: text };
  if (text.startsWith('{')) {
    try {
      const o = JSON.parse(text);
      if (o && typeof o === 'object' && !Array.isArray(o)) return o;
    } catch (_) { /* fall through: the parse error text can quote the secret, so it is not shown */ }
  }
  throw new Error('app option "timescale" is set but is not valid JSON (an object with host or connectionString) '
    + 'or a postgres:// URL; its value is not shown because it holds a password. Fix it: ' + TIMESCALE_WHERE);
}

/**
 * Same as parseTimescale, but the engine "timescale" needs one: throws the single clear "not found" message.
 * @param {any} value
 * @returns {Record<string, any>}
 */
function requireTimescale(value) {
  const o = parseTimescale(value);
  if (!o || !(o.connectionString || o.host)) {
    throw new Error('Timescale connection settings not found' + (o ? ' (the setting has no host or connectionString)' : '')
      + ': ' + TIMESCALE_WHERE);
  }
  return o;
}

/** @param {any} v @returns {any} */
function toBool(v) {
  if (typeof v === 'boolean') return v;
  const s = String(v).trim().toLowerCase();
  if (['true', '1', 'yes', 'on'].includes(s)) return true;
  if (['false', '0', 'no', 'off'].includes(s)) return false;
  return v;
}

/**
 * ctx.config as the code wants it: typed values unwrapped, blank options dropped (an empty option is "not set",
 * it must not beat a default), numbers / booleans / JSON options converted from their string form. A JSON option
 * that does not parse is kept as is (the consumer reports it; `timescale` is reported by requireTimescale).
 * Returns a copy; the input is untouched.
 * @param {any} raw
 * @returns {Record<string, any>}
 */
function normalizeConfig(raw) {
  /** @type {Record<string, any>} */
  const out = {};
  for (const [k, v0] of Object.entries(raw && typeof raw === 'object' ? raw : {})) {
    const v = unwrapTyped(v0);
    if (blank(v)) continue;
    if (NUMBER_OPTIONS.includes(k) && typeof v === 'string' && Number.isFinite(Number(v))) out[k] = Number(v);
    else if (BOOLEAN_OPTIONS.includes(k)) out[k] = toBool(v);
    else if (JSON_OPTIONS.includes(k) && typeof v === 'string') {
      if (k === 'timescale') {
        try { out[k] = parseTimescale(v); } catch (_) { out[k] = v; }   // bad value: kept, requireTimescale explains
      } else {
        try { out[k] = JSON.parse(v); } catch (_) { out[k] = v; }
      }
    } else out[k] = v;
  }
  return out;
}

/**
 * Is the web weather fetch ON? Default yes. The app option `weather` (alias `weatherEnabled`) set to false turns it off
 * (a normalized config: booleans already converted). Either one saying false wins. Used by the weather hook (no HTTP
 * when off), the fdd hook (stale weather points are not bound; local OAT fallback) and kept in step with `doctor`
 * (scripts/nf/hooks/nf_app_sync.py weather_enabled).
 * @param {any} config
 * @returns {boolean}
 */
function weatherEnabled(config) {
  const c = config || {};
  return !(toBool(c.weather) === false || toBool(c.weatherEnabled) === false);
}

/**
 * `text` with the connection's secrets removed (password, password inside a URL), for logs and error messages.
 * @param {any} text
 * @param {any} [conn] the timescale settings object, when known
 * @returns {string}
 */
function redact(text, conn) {
  let s = String(text);
  // Replace the known connection string BEFORE userinfo masking, otherwise masking
  // changes the string and leaves query credentials such as ?password=secret exposed.
  if (conn && typeof conn === 'object' && conn.connectionString) {
    s = s.split(String(conn.connectionString)).join('postgres://***');
  }
  s = s.replace(/(postgres(?:ql)?:\/\/[^:/@\s]*:)[^@\s]*@/gi, '$1***@');
  // Query passwords independently of a full connectionString match (partial URL fragments
  // in error text can still carry ?password=secret after userinfo masking).
  s = s.replace(/([?&]password=)[^&\s]*/gi, '$1***');
  const pw = conn && typeof conn === 'object' ? conn.password : null;
  if (pw != null && String(pw).length > 0) {
    const secret = String(pw);
    // A short bare secret cannot be reliably distinguished from ordinary text.
    // Omit the driver diagnostic when the redacted message still contains it.
    if (secret.length < 3 && s.includes(secret)) return 'Timescale connection failed (driver detail redacted)';
    s = s.split(secret).join('***');
  }
  return s;
}

module.exports = { weatherEnabled, normalizeConfig, parseTimescale, requireTimescale, redact, unwrapTyped, TIMESCALE_WHERE };
