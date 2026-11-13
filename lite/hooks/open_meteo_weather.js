// GENERATED COPY of shared/hooks/open_meteo_weather.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
/**
 * Open-FDD: Open-Meteo outdoor-air weather hook for Normal Framework (NF) 3.10.x.
 *
 * Runs as a scheduled NF Applications SDK hook (MODE_SCHEDULED, RRULE every
 * 20 minutes). Each run fetches the current conditions from Open-Meteo (free,
 * no API key) and writes three hook *global variables*. NF stores variables as
 * ordinary points (pointType VARIABLE), and each run appends one sample to
 * their history via AddPointsData, so /api/v1/point/data (console or the
 * Normal Online portal) returns them like any trended BACnet point.
 *
 *   label oa_dry_bulb_web  outdoor air dry bulb   degF
 *   label oa_rh_web        outdoor air RH         %
 *   label oa_dewpoint_web  outdoor air dewpoint   degF
 *
 * Dewpoint: Open-Meteo's dew_point_2m is used when present. It is also computed
 * here with the Magnus formula from temperature and RH and used as a
 * fallback. Both values are logged on every run.
 *
 * Site location comes from NF itself, so nothing site-specific lives in this
 * file. Order: the hook settings `latitude` + `longitude` (NF passes the app
 * options as ctx.config; set them in the NF console app settings), then the NF
 * Sites collection (GET /api/v1/sites), then the modeled Haystack SITE. With
 * one site that has coordinates it is used; with several, set the app option
 * `site` to the site id. Otherwise the run fails naming where to set them.
 * The answer's coords_source says which one was used.
 *
 * OFF SWITCH (#1552): the app option `weather` = false (alias `weatherEnabled`) turns the whole fetch off. The hook then
 * makes NO outbound HTTP request and no NF call either; it returns {skipped: true, reason: "weather disabled"} and
 * `doctor` reports "weather disabled", not a failure. Set it back to true (or clear it) to turn the fetch back on: the
 * next scheduled run resumes and the hook variables keep their history. Air-gapped / IT-restricted sites set it at install.
 *
 * EXPORTERS (#1552): the hook variables (oa_dry_bulb_web, oa_rh_web, oa_dewpoint_web, with history) are ALWAYS written.
 * Besides them the run hands the values to a list of exporters, each a small object (see EXPORTERS below):
 *
 *     { id: string,
 *       detect(sdk, config): Promise<{ available: boolean, reason?: string }>   // is this output present on this NF?
 *       export(sdk, { site, values, observed, config, log }): Promise<object>   // write; the answer goes in the summary }
 *
 * `values` = { oa_dry_bulb_web: degF, oa_rh_web: %, oa_dewpoint_web: degF }. Built in: "bacnet-av" (analog values on NF's
 * own BACnet server). Room for others (Modbus, OPC UA, ...): add an object to EXPORTERS (registerExporter) and name its
 * id in the `exporters` app option. Which exporters run:
 *
 *   `exporters` unset        -> ["bacnet-av"], and only if NF's BACnet server is present (GET /api/v1/bacnet/configuration
 *                               answers); absent = skipped with that reason, not a failure
 *   `exporters` = "none"/[]  -> hook variables only
 *   `exporters` = "bacnet-av" (or a comma list / JSON array) -> exactly those; one that is not available FAILS the run
 *                               (after the variables were written), because it was asked for by name
 *   `bacnetMirror` (alias bacnet_mirror): false removes "bacnet-av" from whatever list applies (the original off switch);
 *                               true asks for it by name
 *
 * bacnet-av creates (once) and updates three analog-value objects on NF's BACnet server so any BACnet client can read the
 * same numbers. The AV instance numbers come from the app option `avInstances` (default [1, 2, 3], in the order
 * oa_dry_bulb_web, oa_rh_web, oa_dewpoint_web).
 *
 *     label              default object  name        units
 *     oa_dry_bulb_web    av.1            WEB OA-T    degF  (64)
 *     oa_rh_web          av.2            WEB OA-H    %RH   (29)
 *     oa_dewpoint_web    av.3            WEB OA-DP   degF  (64)
 *
 * Local objects are created WITHOUT a uuid: passing an existing point uuid to CreateLocalObject overwrites that point
 * (NF 3.10.9), so NF assigns one.
 *
 * ONE source for both editions (shared/hooks/open_meteo_weather.js, copied by scripts/nf/sync_shared.py to
 * nf-app/hooks/weather.js and lite/hooks/open_meteo_weather.js). Uses Node's built-in https module plus the
 * dependency-free ./lib/paging.js and ./lib/settings.js (also shared): no npm install needed.
 */
// Written per edition by scripts/nf/sync_shared.py ('full' / 'lite'); informational: both editions mirror to NF's BACnet server by default.
const OFDD_EDITION = /** @type {string} */ ('lite');
const https = require('https');
const { pageAll, listAll } = require('./lib/paging.js');
const settings = require('./lib/settings.js');

const openMeteoUrl = (lat, lon) =>
  'https://api.open-meteo.com/v1/forecast' +
  `?latitude=${lat}&longitude=${lon}` +
  '&current=temperature_2m,relative_humidity_2m,dew_point_2m' +
  '&temperature_unit=fahrenheit&timezone=UTC';

const hasCoords = (s) => Number.isFinite(s.latitude) && Number.isFinite(s.longitude) && !(s.latitude === 0 && s.longitude === 0);

const noCoords = (msg) => Object.assign(new Error(msg), { noCoords: true });

const present = (v) => v !== undefined && v !== null && String(v).trim() !== '';

/** {latitude, longitude} from a modeled site's attrs: latitude/longitude, else geoCoord "C(lat,lon)"; null if absent/0,0. */
function coordsFromAttrs(attrs) {
  const a = attrs || {};
  let lat = present(a.latitude) ? Number(a.latitude) : NaN;
  let lon = present(a.longitude) ? Number(a.longitude) : NaN;
  if (!(Number.isFinite(lat) && Number.isFinite(lon)) && present(a.geoCoord)) {
    const m = /^\s*C?\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)\s*$/.exec(String(a.geoCoord));
    if (m) {
      lat = Number(m[1]);
      lon = Number(m[2]);
    }
  }
  const c = { latitude: lat, longitude: lon };
  return hasCoords(c) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? c : null;
}

/**
 * All pages of POST /api/v1/point/query for one layer (shared pager: pageOffset + totalCount, #1550); a layer that
 * does not exist (HTTP error) is just empty. A paging failure (cap, short read) is NOT swallowed: a truncated model
 * would hide the SITE record the same way it did for the fdd hook.
 */
async function queryLayer(http, layer) {
  // First-request failure (missing/unreadable layer) -> []; a later-page failure must propagate
  // so a truncated model is never mistaken for "no site found" (#1553 CodeRabbit).
  let pages = 0;
  try {
    return await pageAll(async (p) => {
      const res = await http.post('/api/v1/point/query', { layer, ...p });
      pages += 1;
      return res && res.data;
    }, { key: 'points', what: 'point/query' });
  } catch (e) {
    if (e && e.paging) throw e;
    if (pages > 0) throw e;
    // First request: only a missing layer (404) is empty; service failures (5xx, etc.) must propagate
    // so siteFromModel does not report "no coordinates" when the model API is down.
    // Status may live on the error object or only in the message (NF SDK / test stubs).
    const status = e && (e.status ?? e.code ?? e.statusCode);
    const msg = e ? String(e.message || e) : '';
    if (status === 404 || /\bHTTP\s*404\b/i.test(msg)) return [];
    throw e;
  }
}

const APP_OPTIONS_HINT = 'set the app options "latitude" and "longitude" (NF console > app settings: the hook reads them first)';

/**
 * Coordinates from the hook settings (NF passes the app options as ctx.config): latitude + longitude, as numbers or
 * numeric strings. Blank or 0,0 = not set (null). Set but unusable (one of the pair, not a number, out of range)
 * throws, naming the options: a typo must not silently fall through to some other site.
 * @param {any} config
 * @returns {{ id: string, name: string, latitude: number, longitude: number, source: string } | null}
 */
function coordsFromConfig(config) {
  const c = config || {};
  if (!present(c.latitude) && !present(c.longitude)) return null;
  const c2 = { latitude: present(c.latitude) ? Number(c.latitude) : NaN, longitude: present(c.longitude) ? Number(c.longitude) : NaN };
  // 0 and 0 is what an option shows when nobody filled it in (and is never a real site): unset, not an error
  if (c2.latitude === 0 && c2.longitude === 0) return null;
  if (!hasCoords(c2) || Math.abs(c2.latitude) > 90 || Math.abs(c2.longitude) > 180) {
    throw new Error('app options "latitude" and "longitude" must both be set to valid, non-zero coordinates '
      + `(got latitude=${JSON.stringify(c.latitude)}, longitude=${JSON.stringify(c.longitude)})`);
  }
  const id = present(c.site) ? String(c.site) : 'app-settings';
  return { id, name: id, ...c2, source: 'app setting (latitude/longitude)' };
}

/**
 * Fallback when NF's Sites collection has no usable coordinates: the modeled Haystack SITE record(s) on the
 * model layer (pointType SITE) and any record on the `site` layer that carries coordinates. Never invents
 * coordinates; returns null when none of them has any.
 */
async function siteFromModel(http, wanted) {
  const found = new Map(); // id -> { id, name, latitude, longitude, source }
  for (const layer of ['model', 'site']) {
    for (const r of await queryLayer(http, layer)) {
      if (layer === 'model' && r.pointType !== 'SITE') continue;
      const attrs = r.attrs || {};
      const id = String(attrs.id || r.name || '');
      const c = coordsFromAttrs(attrs);
      if (!id || !c || found.has(id)) continue;
      found.set(id, { id, name: r.name || id, ...c, source: `haystack ${layer} layer` });
    }
  }
  const list = [...found.values()];
  if (wanted) return list.find((s) => s.id === wanted || s.name === wanted) || null;
  if (list.length > 1) {
    throw new Error(`several modeled sites have coordinates (${list.map((x) => x.id).join(', ')}); set the app config value "site"`);
  }
  return list[0] || null;
}

/** The NF site to fetch weather for: config `site` (id) if set, else the only site with coordinates. */
function pickSite(sites, wanted) {
  if (wanted) {
    const s = sites.find((x) => x.id === wanted);
    if (!s) throw noCoords(`config site "${wanted}" is not an NF site (have: ${sites.map((x) => x.id).join(', ') || 'none'})`);
    if (!hasCoords(s)) throw noCoords(`NF site "${wanted}" has no latitude/longitude; set them in NF (Sites) or on the modeled Haystack site`);
    return s;
  }
  const located = sites.filter(hasCoords);
  if (located.length === 1) return located[0];
  if (!located.length) throw noCoords('no NF site has latitude/longitude; set them in NF (Sites) or on the modeled Haystack site');
  throw new Error(`several NF sites have coordinates (${located.map((x) => x.id).join(', ')}); set the app config value "site"`);
}

const DEFAULT_AV_INSTANCES = [1, 2, 3];

/** The three mirrored values: variable label, AV name and BACnet units enum (64 = degF, 29 = %RH). */
const BACNET_SPECS = [
  { label: 'oa_dry_bulb_web', name: 'WEB OA-T', units: 64, what: 'outdoor air dry bulb' },
  { label: 'oa_rh_web', name: 'WEB OA-H', units: 29, what: 'outdoor air RH' },
  { label: 'oa_dewpoint_web', name: 'WEB OA-DP', units: 64, what: 'outdoor air dewpoint' },
];

/** AV instance numbers from config.avInstances (three distinct non-negative integers), else 1, 2, 3. */
function avInstances(config) {
  const raw = config && config.avInstances;
  if (raw === undefined || raw === null || raw === '') return DEFAULT_AV_INSTANCES.slice();
  const list = (Array.isArray(raw) ? raw : String(raw).split(',')).map((x) => Number(String(x).trim()));
  const ok = list.length === BACNET_SPECS.length && list.every((n) => Number.isInteger(n) && n >= 0 && n < 4194303) && new Set(list).size === list.length;
  if (!ok) throw new Error(`config avInstances must be ${BACNET_SPECS.length} distinct instance numbers, got ${JSON.stringify(raw)}`);
  return list;
}

/** Objects to mirror for this site: BACNET_SPECS with their configured instance numbers. */
const bacnetObjects = (siteName, instances) =>
  BACNET_SPECS.map((sp, i) => ({ ...sp, instance: instances[i], description: `Open-Meteo ${sp.what}, ${siteName}` }));

const HTTP_TIMEOUT_MS = 20000; // per-attempt deadline for the Open-Meteo request
const HTTP_RETRIES = 1; // one retry on network error/timeout/5xx
const WRITE_TIMEOUT_MS = 10000; // per NF API call (point write, BACnet mirror)
const SITES_TIMEOUT_MS = 10000; // whole paginated Sites lookup
const MODEL_LOOKUP_TIMEOUT_MS = 45000; // paginated model/site lookup (many sequential pages)
const RUN_DEADLINE_MS = 180000; // Sites (10s) + model (45s) + fetch (40s) + point writes (30s) + mirror (40s)

/** Reject if `promise` doesn't settle within `ms`; calls onTimeout (e.g. abort) first. */
function withDeadline(promise, ms, what, onTimeout) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      try {
        if (onTimeout) onTimeout();
      } catch (_) {
        /* best effort */
      }
      reject(new Error(`${what} exceeded ${ms} ms`));
    }, ms);
  });
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}

function getJson(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(
      url,
      { headers: { 'User-Agent': 'openfdd-nf-weather-hook/1.0', Accept: 'application/json' } },
      (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => (body += chunk));
        res.on('end', () => {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(new Error(`Open-Meteo HTTP ${res.statusCode}: ${body.slice(0, 200)}`));
            return;
          }
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            reject(new Error(`Open-Meteo returned invalid JSON: ${e.message}`));
          }
        });
      },
    );
    // req.setTimeout only fires on an idle socket; the hard total deadline is in getJsonWithRetry.
    req.setTimeout(HTTP_TIMEOUT_MS, () => req.destroy(new Error(`Open-Meteo idle timeout after ${HTTP_TIMEOUT_MS} ms`)));
    req.on('error', reject);
    /** @type {any} */ (getJson).lastReq = req;
  });
}

/** Open-Meteo fetch with a hard per-attempt deadline (covers DNS stalls and slow-drip bodies) and one retry. */
async function getJsonWithRetry(url, log) {
  let lastErr;
  for (let attempt = 0; attempt <= HTTP_RETRIES; attempt += 1) {
    try {
      return await withDeadline(getJson(url), HTTP_TIMEOUT_MS, 'Open-Meteo request', () => {
        const lr = /** @type {any} */ (getJson).lastReq;
        if (lr) lr.destroy(new Error('Open-Meteo hard deadline'));
      });
    } catch (e) {
      lastErr = e;
      const msg = String(e && e.message);
      const retryable = !/HTTP 4\d\d/.test(msg) && !/invalid JSON/.test(msg);
      if (!retryable || attempt === HTTP_RETRIES) break;
      log(`open-meteo attempt ${attempt + 1} failed (${msg}); retrying`);
    }
  }
  throw lastErr;
}

const fToC = (f) => ((f - 32) * 5) / 9;
const cToF = (c) => (c * 9) / 5 + 32;

/** Magnus-Tetens dewpoint (Sonntag 1990 constants b=17.62, c=243.12 degC). */
function magnusDewpointF(tempF, rhPct) {
  if (!Number.isFinite(tempF) || !Number.isFinite(rhPct) || rhPct <= 0 || rhPct > 100) return NaN;
  const b = 17.62;
  const c = 243.12;
  const t = fToC(tempF);
  const gamma = Math.log(rhPct / 100) + (b * t) / (c + t);
  return cToF((c * gamma) / (b - gamma));
}

const round2 = (x) => Math.round(x * 100) / 100;

/** sdk.http (axios) rejects with a plain object; turn it into an Error that names the call. */
async function nf(promise, what) {
  try {
    return (await withDeadline(promise, WRITE_TIMEOUT_MS, what)).data;
  } catch (e) {
    const status = e && (e.status || (e.response && e.response.status));
    const detail = e && e.response && e.response.data ? JSON.stringify(e.response.data).slice(0, 200) : '';
    throw new Error(`${what} failed: ${e && e.message} status=${status} ${detail}`);
  }
}

/** Create the weather AVs on NF's BACnet server if missing, then set their present values. */
async function mirrorToBacnet(sdk, objects, values, observed, log) {
  const listing = await nf(sdk.http.get('/api/v1/bacnet/local'), 'GetLocalObjects');
  const nameOf = (o) => (((o.props || []).find((x) => x.property === 'PROP_OBJECT_NAME') || {}).value || {}).characterString || '';
  /** instance -> object name ('' when the listing carries no name) */
  const have = new Map(
    (listing.objects || [])
      .filter((o) => o.objectId && o.objectId.objectType === 'OBJECT_ANALOG_VALUE')
      .map((o) => [o.objectId.instance, nameOf(o)]),
  );
  const mirrored = {};
  for (const obj of objects) {
    const value = values[obj.label];
    if (!Number.isFinite(value)) continue;
    const current = have.get(obj.instance);
    if (current && current !== obj.name) {
      // an analog value this hook did not create sits on that instance: never overwrite it
      log(`BACnet av.${obj.instance} is "${current}", not "${obj.name}": left untouched (instance collision; `
        + 'pick free instances with the app option avInstances)');
      continue;
    }
    const objectId = { objectType: 'OBJECT_ANALOG_VALUE', instance: obj.instance };
    const pv = { property: 'PROP_PRESENT_VALUE', value: { real: round2(value) } };
    const desc = { property: 'PROP_DESCRIPTION', value: { characterString: `${obj.description} (obs ${observed})` } };
    if (!have.has(obj.instance)) {
      await nf(
        sdk.http.post('/api/v1/bacnet/local', {
          objectId,
          props: [
            { property: 'PROP_OBJECT_NAME', value: { characterString: obj.name } },
            { property: 'PROP_UNITS', value: { enumerated: obj.units } },
            desc,
            pv,
          ],
        }),
        `CreateLocalObject av.${obj.instance}`,
      );
      log(`created BACnet av.${obj.instance} ${obj.name}`);
    } else {
      await nf(sdk.http.patch('/api/v1/bacnet/local', { objectId, props: [pv, desc] }), `UpdateLocalObject av.${obj.instance}`);
    }
    mirrored[`av.${obj.instance}`] = round2(value);
  }
  return mirrored;
}

// ---- exporters (#1552) ---------------------------------------------------------------------------------------------------
/** The built-in BACnet analog-value exporter. */
const bacnetAvExporter = {
  id: 'bacnet-av',
  /** NF's BACnet server is present when its configuration endpoint answers. */
  async detect(sdk, _config) {
    try {
      await withDeadline(sdk.http.get('/api/v1/bacnet/configuration'), WRITE_TIMEOUT_MS, 'GetBacnetConfiguration');
      return { available: true };
    } catch (e) {
      const status = e && (e.status || (e.response && e.response.status));
      return { available: false, reason: `NF's BACnet server is not present (GET /api/v1/bacnet/configuration ${status ? `-> HTTP ${status}` : `failed: ${e && e.message}`})` };
    }
  },
  async export(sdk, { site, values, observed, config, log }) {
    const objects = bacnetObjects(site.name || site.id, avInstances(config));
    return mirrorToBacnet(sdk, objects, values, observed, log);
  },
};

/** id -> exporter. Add one with registerExporter (a fork, a test); name its id in the `exporters` app option. */
const EXPORTERS = { [bacnetAvExporter.id]: bacnetAvExporter };
function registerExporter(exporter) {
  if (!exporter || !exporter.id || typeof exporter.detect !== 'function' || typeof exporter.export !== 'function') {
    throw new Error('an exporter is { id, detect(sdk, config), export(sdk, ctx) }');
  }
  EXPORTERS[exporter.id] = exporter;
}

/** The `exporters` option as a list of ids: a JSON array, a comma list or one id; "none" / "[]" = []. undefined = not set. */
function parseExporters(raw) {
  if (raw === undefined || raw === null || (typeof raw === 'string' && raw.trim() === '')) return undefined;
  let list = raw;
  if (typeof raw === 'string') {
    const t = raw.trim();
    if (t.startsWith('[')) {
      try { list = JSON.parse(t); } catch (_) { throw new Error(`app option "exporters" is not valid JSON: ${t.slice(0, 80)}`); }
    } else list = t.split(',');
  }
  if (!Array.isArray(list)) throw new Error('app option "exporters" must be a list of exporter ids (or "none")');
  return list.map((x) => String(x).trim()).filter((x) => x && x.toLowerCase() !== 'none');
}

/**
 * Which exporters to run: [{ id, explicit }]. See the header for the rules. Throws on an unknown id before any network call.
 * @param {any} config normalized config
 * @returns {{id: string, explicit: boolean}[]}
 */
function exporterPlan(config) {
  const listed = parseExporters(config.exporters);
  const legacy = config.bacnetMirror !== undefined ? config.bacnetMirror : config.bacnet_mirror;
  const off = legacy === false || legacy === 'false';
  const on = legacy === true || legacy === 'true';
  /** @type {{id: string, explicit: boolean}[]} */
  let plan = listed === undefined ? [{ id: 'bacnet-av', explicit: false }] : listed.map((id) => ({ id, explicit: true }));
  if (on) plan = [...plan.filter((x) => x.id !== 'bacnet-av'), { id: 'bacnet-av', explicit: true }];
  if (off) plan = plan.filter((x) => x.id !== 'bacnet-av');
  const unknown = plan.filter((x) => !EXPORTERS[x.id]).map((x) => x.id);
  if (unknown.length) throw new Error(`unknown weather exporter(s) ${unknown.join(', ')}; known: ${Object.keys(EXPORTERS).join(', ')}, or "none"`);
  return plan;
}

/**
 * Detect, then run each planned exporter. The caller has already written the hook variables. An exporter named in the
 * config that is absent or fails is a failure (collected, thrown by the caller after all ran); an implicit default that is
 * absent is skipped with its reason.
 * @returns {Promise<{ exporters: Record<string, any>, failures: string[] }>}
 */
async function runExporters(plan, sdk, ctx) {
  /** @type {Record<string, any>} */
  const exporters = {};
  const failures = [];
  for (const { id, explicit } of plan) {
    try {
      const det = await EXPORTERS[id].detect(sdk, ctx.config);
      if (!det || !det.available) {
        const reason = (det && det.reason) || 'not available';
        exporters[id] = { status: explicit ? 'failed' : 'skipped', reason };
        if (explicit) failures.push(`${id}: ${reason}`);
        else ctx.log(`exporter ${id} skipped: ${reason}`);
        continue;
      }
      exporters[id] = { status: 'ok', result: await EXPORTERS[id].export(sdk, ctx) };
    } catch (e) {
      exporters[id] = { status: 'failed', reason: String((e && e.message) || e) };
      failures.push(`${id}: ${exporters[id].reason}`);
    }
  }
  return { exporters, failures };
}


async function runOnce({ globalVariables, sdk, config }) {
  const log = (msg) => {
    console.log(msg);
    try {
      sdk.logEvent(msg);
    } catch (_) {
      /* logEvent is best effort */
    }
  };

  // NF passes the app options as ctx.config (numbers can arrive as strings; blank options are "not set")
  config = settings.normalizeConfig(config);
  // OFF is a first-class state: nothing below runs (no Sites / model / Open-Meteo / point / BACnet call)
  if (!settings.weatherEnabled(config)) {
    log('open-meteo weather disabled by the app option "weather" (no outbound request made)');
    return { skipped: true, reason: 'weather disabled' };
  }
  const wanted = config.site;
  const plan = exporterPlan(config);
  if (plan.some((x) => x.id === 'bacnet-av')) avInstances(config); // validate before any network call
  // 1) the hook settings / app options latitude + longitude (an explicit override), 2) NF Sites, 3) the modeled SITE
  let site = coordsFromConfig(config);
  if (site) log(`weather location from the ${site.source}`);
  else {
    const sites = await withDeadline(listAll(sdk.http, '/api/v1/sites', 'sites'), SITES_TIMEOUT_MS, 'GetSites');
    try {
      site = pickSite(sites, wanted);
      site.source = 'nf sites api';
    } catch (e) {
      if (!e || !e.noCoords) throw e;
      // NF's Sites collection has no usable coordinates: try the modeled Haystack SITE (never invent any)
      site = await withDeadline(siteFromModel(sdk.http, wanted), MODEL_LOOKUP_TIMEOUT_MS, 'model site lookup');
      if (!site) throw new Error(`${e.message}; or ${APP_OPTIONS_HINT}`);
      log(`weather location from the ${site.source} (site ${site.id}); NF Sites had none`);
    }
  }
  const wx = await getJsonWithRetry(openMeteoUrl(site.latitude, site.longitude), log);
  const cur = wx && wx.current;
  if (!cur) throw new Error('Open-Meteo response has no "current" block');

  const tempF = Number(cur.temperature_2m);
  const rh = Number(cur.relative_humidity_2m);
  const apiDewF = cur.dew_point_2m === null || cur.dew_point_2m === undefined ? NaN : Number(cur.dew_point_2m);
  const calcDewF = magnusDewpointF(tempF, rh);
  const dewF = Number.isFinite(apiDewF) ? apiDewF : calcDewF;
  const dewSource = Number.isFinite(apiDewF) ? 'open-meteo' : 'magnus';

  if (!Number.isFinite(tempF) || !Number.isFinite(rh)) {
    throw new Error(`Open-Meteo returned non-numeric values: ${JSON.stringify(cur)}`);
  }

  const writes = [
    ['oa_dry_bulb_web', tempF],
    ['oa_rh_web', rh],
    ['oa_dewpoint_web', dewF],
  ];
  // NF 3.10.9 gotchas (see scripts/nf/hooks/README.md):
  //  * The app MUST have auth.apiKey scopes (normalgw.hpl.v1/v2.readwrite) or
  //    every SDK call from the runtime gets 401/UNAUTHENTICATED.
  //  * variable.write() does not await the underlying AddPointsData call, so an
  //    auth failure is swallowed and the run still reports STATE_SUCCESS.
  // So write through the NF point API (POST /api/v1/point/data) and await it,
  // which makes failures fail the run.
  const ts = new Date().toISOString();
  let writePath = 'sdk.http AddPointsData';
  for (const [label, value] of writes) {
    const v = globalVariables.byLabel(label);
    if (!v) throw new Error(`global variable "${label}" not found; check the hook's globalVariables`);
    if (!Number.isFinite(value)) continue;
    if (sdk && sdk.http && typeof sdk.http.post === 'function') {
      let res;
      try {
        res = await withDeadline(
          sdk.http.post('/api/v1/point/data', {
            uuid: v.uuid,
            values: [{ ts, real: round2(value) }],
          }),
          WRITE_TIMEOUT_MS,
          `AddPointsData ${label}`,
        );
      } catch (e) {
        // sdk.http rejects with a plain object, not an Error
        throw new Error(`AddPointsData ${label} (${v.uuid}) failed: ${e && e.message} status=${e && e.status}`);
      }
      if (!res || !res.data || res.data.success !== true) {
        throw new Error(`AddPointsData failed for ${label} (${v.uuid}): ${JSON.stringify(res && res.data)}`);
      }
    } else {
      writePath = 'variable.write';
      await withDeadline(v.write({ real: round2(value) }), WRITE_TIMEOUT_MS, `variable.write ${label}`);
    }
  }

  // exporters: the variables above are already written
  const values = { oa_dry_bulb_web: tempF, oa_rh_web: rh, oa_dewpoint_web: dewF };
  const { exporters, failures } = await runExporters(plan, sdk, { site, values, observed: cur.time, config, log });
  const bacnet = exporters['bacnet-av'] && exporters['bacnet-av'].status === 'ok' ? exporters['bacnet-av'].result : null;

  const summary = {
    site: site.id,
    siteName: site.name || site.id,
    location: `${site.latitude},${site.longitude}`,
    coords_source: site.source,
    observed: cur.time,
    oa_dry_bulb_f: round2(tempF),
    oa_rh_pct: round2(rh),
    dewpoint_open_meteo_f: Number.isFinite(apiDewF) ? round2(apiDewF) : null,
    dewpoint_magnus_f: Number.isFinite(calcDewF) ? round2(calcDewF) : null,
    dewpoint_delta_f: Number.isFinite(apiDewF) && Number.isFinite(calcDewF) ? round2(calcDewF - apiDewF) : null,
    dewpoint_written_f: round2(dewF),
    dewpoint_source: dewSource,
    write_path: writePath,
    exporters,
    bacnet,
  };
  log(`open-meteo weather ${JSON.stringify(summary)}`);
  if (failures.length) throw new Error(`weather values written, but ${failures.length} exporter(s) failed: ${failures.join('; ')}`);
  return summary;
}

// The hook is the function; the helpers hang off it for offline tests
// (load the file from the hooks folder of either edition in node and call magnusDewpointF(70, 50)).
module.exports = Object.assign(
  async (ctx) => withDeadline(runOnce(ctx), RUN_DEADLINE_MS, 'open-meteo weather hook run'),
  { OFDD_EDITION, magnusDewpointF, openMeteoUrl, pickSite, siteFromModel, coordsFromAttrs, coordsFromConfig, avInstances, bacnetObjects, mirrorToBacnet, withDeadline, pageAll,
    EXPORTERS, registerExporter, exporterPlan, parseExporters },
);
