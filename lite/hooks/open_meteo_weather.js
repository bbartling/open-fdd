/**
 * Open-FDD Lite: Open-Meteo outdoor-air weather hook, mirrored to NF's BACnet server.
 *
 * Same fetch / retry / deadline / AddPointsData pattern as the full edition's
 * nf-app/hooks/weather.js. Every 20 minutes it:
 *
 *   1. reads the site location from NF itself (GET /api/v1/sites: latitude,
 *      longitude, name). Nothing site-specific lives in this file. With one
 *      site that has coordinates it is used; with several, set the hook config
 *      value `site` to the site id,
 *   2. fetches current conditions from Open-Meteo (no API key),
 *   3. writes three hook global variables (NF points with history),
 *   4. creates (once) and updates three analog-value objects on NF's own BACnet
 *      server so any BACnet client can read the same numbers. The AV instance
 *      numbers come from the hook config value `avInstances` (default [1, 2, 3],
 *      in the order oa_dry_bulb_web, oa_rh_web, oa_dewpoint_web). Set
 *      `bacnetMirror` to false to skip the BACnet part.
 *
 *        label              default object  name        units
 *        oa_dry_bulb_web    av.1            WEB OA-T    degF  (64)
 *        oa_rh_web          av.2            WEB OA-H    %RH   (29)
 *        oa_dewpoint_web    av.3            WEB OA-DP   degF  (64)
 *
 * Local objects are created WITHOUT a uuid. Passing an existing point uuid to
 * CreateLocalObject overwrites that point (NF 3.10.9), so let NF assign one.
 * Node's built-in https only: no npm dependencies.
 */
const https = require('https');

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
 * The Lite edition's one pager (the full edition shares nf-app/hooks/lib/paging.js; Lite is a single-file app, so this
 * is the same algorithm inline, #1550). NF pages by pageOffset + totalCount, not only by a next-page token:
 * a nextPageToken is followed when present, else pageOffset advances until totalCount (or an empty / short page when
 * there is no totalCount). A page that repeats, a short read and a hard cap are errors (err.paging), never a
 * silently truncated list.
 * @param {(p: { pageSize: number, pageOffset?: number, pageToken?: string }) => Promise<any>} fetchPage
 * @param {{ key: string, what: string, pageSize?: number, maxRecords?: number, maxPages?: number }} o
 */
async function pageAll(fetchPage, o) {
  const pageSize = o.pageSize || 500;
  const maxRecords = o.maxRecords || 200000;
  const maxPages = o.maxPages || 1000;
  const fail = (m) => Object.assign(new Error(`${o.what}: ${m}`), { paging: true });
  const out = [];
  const seen = new Set();
  const tokens = new Set();
  let token = '';
  let offset = 0;
  let total = null;
  for (let pages = 0; ; pages += 1) {
    if (pages >= maxPages || offset >= maxRecords) {
      throw fail(`paging cap reached after ${offset} records in ${pages} pages (totalCount ${total === null ? 'unknown' : total}); refusing to continue with a partial result`);
    }
    const params = { pageSize };
    if (token) params.pageToken = token;
    else if (offset > 0) params.pageOffset = offset;
    const page = (await fetchPage(params)) || {};
    const recs = Array.isArray(page[o.key]) ? page[o.key] : [];
    const t = page.totalCount === undefined || page.totalCount === null || page.totalCount === '' ? NaN : Number(page.totalCount);
    if (Number.isFinite(t) && t >= 0) total = t;
    let added = 0;
    for (const r of recs) {
      const id = (r && (r.uuid || r.id)) || JSON.stringify(r);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(r);
      added += 1;
    }
    if (recs.length && !added) throw fail(`page ${pages + 1} repeated records already read (the server ignored the paging parameters); refusing to loop`);
    offset += recs.length;
    if (page.nextPageToken) {
      if (tokens.has(page.nextPageToken)) throw fail('nextPageToken repeated; refusing to loop');
      tokens.add(page.nextPageToken);
      token = page.nextPageToken;
      continue;
    }
    token = '';
    if (!recs.length) break;
    if (total !== null) {
      if (offset >= total) break;
    } else if (recs.length < pageSize) break;
  }
  if (total !== null && offset < total) throw fail(`read ${offset} of totalCount ${total} records, then the server returned an empty page; refusing to continue with a partial result`);
  return out;
}

/** All pages of POST /api/v1/point/query for one layer; a layer that does not exist (HTTP error) is just empty. */
async function queryLayer(http, layer) {
  // First-request failure (missing/unreadable layer) -> []; a later-page failure must propagate
  // so a truncated model is never mistaken for "no site found" (#1553 CodeRabbit).
  let pages = 0;
  try {
    return await pageAll(async (p) => {
      const data = (await http.post('/api/v1/point/query', { layer, ...p })).data;
      pages += 1;
      return data;
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
const WRITE_TIMEOUT_MS = 10000; // per NF API call
const MODEL_LOOKUP_TIMEOUT_MS = 45000; // paginated model/site lookup (many sequential pages)
const RUN_DEADLINE_MS = 120000; // whole-run: model lookup (45s) + Open-Meteo fetch + point writes must fit

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
      { headers: { 'User-Agent': 'open-fdd-lite-weather-hook/1.0', Accept: 'application/json' } },
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
    req.setTimeout(HTTP_TIMEOUT_MS, () => req.destroy(new Error(`Open-Meteo idle timeout after ${HTTP_TIMEOUT_MS} ms`)));
    req.on('error', reject);
    /** @type {any} */ (getJson).lastReq = req;
  });
}

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
  const have = new Set(
    (listing.objects || [])
      .filter((o) => o.objectId && o.objectId.objectType === 'OBJECT_ANALOG_VALUE')
      .map((o) => o.objectId.instance),
  );
  const mirrored = {};
  for (const obj of objects) {
    const value = values[obj.label];
    if (!Number.isFinite(value)) continue;
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

async function runOnce({ globalVariables, sdk, config }) {
  const log = (msg) => {
    console.log(msg);
    try {
      sdk.logEvent(msg);
    } catch (_) {
      /* logEvent is best effort */
    }
  };

  const instances = avInstances(config); // validate config before any network call
  const sites = await pageAll(async (p) => nf(sdk.http.get(`/api/v1/sites?pageSize=${p.pageSize}${p.pageOffset ? `&pageOffset=${p.pageOffset}` : ''}${p.pageToken ? `&pageToken=${encodeURIComponent(p.pageToken)}` : ''}`), 'GetSites'),
    { key: 'sites', what: 'sites' });
  const wanted = config && config.site;
  let site;
  try {
    site = pickSite(sites, wanted);
    site.source = 'nf sites api';
  } catch (e) {
    if (!e || !e.noCoords) throw e;
    // NF's Sites collection has no usable coordinates: try the modeled Haystack SITE (never invent any)
    site = await withDeadline(siteFromModel(sdk.http, wanted), MODEL_LOOKUP_TIMEOUT_MS, 'model site lookup');
    if (!site) throw e;
    log(`weather location from the ${site.source} (site ${site.id}); NF Sites had none`);
  }
  const siteName = site.name || site.id;
  const wx = await getJsonWithRetry(openMeteoUrl(site.latitude, site.longitude), log);
  const cur = wx && wx.current;
  if (!cur) throw new Error('Open-Meteo response has no "current" block');

  const tempF = Number(cur.temperature_2m);
  const rh = Number(cur.relative_humidity_2m);
  const apiDewF = cur.dew_point_2m === null || cur.dew_point_2m === undefined ? NaN : Number(cur.dew_point_2m);
  const calcDewF = magnusDewpointF(tempF, rh);
  const dewF = Number.isFinite(apiDewF) ? apiDewF : calcDewF;
  if (!Number.isFinite(tempF) || !Number.isFinite(rh)) {
    throw new Error(`Open-Meteo returned non-numeric values: ${JSON.stringify(cur)}`);
  }
  const values = { oa_dry_bulb_web: tempF, oa_rh_web: rh, oa_dewpoint_web: dewF };

  // Await each write so a failure fails the run (variable.write() does not).
  const ts = new Date().toISOString();
  for (const [label, value] of Object.entries(values)) {
    const v = globalVariables.byLabel(label);
    if (!v) throw new Error(`global variable "${label}" not found; check the hook's globalVariables`);
    if (!Number.isFinite(value)) continue;
    const res = await nf(
      sdk.http.post('/api/v1/point/data', { uuid: v.uuid, values: [{ ts, real: round2(value) }] }),
      `AddPointsData ${label}`,
    );
    if (!res || res.success !== true) throw new Error(`AddPointsData ${label} (${v.uuid}): ${JSON.stringify(res)}`);
  }

  const mirror = !(config && (config.bacnetMirror === false || config.bacnetMirror === 'false'));
  const bacnet = mirror ? await mirrorToBacnet(sdk, bacnetObjects(siteName, instances), values, cur.time, log) : null;

  const summary = {
    site: site.id,
    siteName,
    location: `${site.latitude},${site.longitude}`,
    observed: cur.time,
    oa_dry_bulb_f: round2(tempF),
    oa_rh_pct: round2(rh),
    coords_source: site.source,
    dewpoint_open_meteo_f: Number.isFinite(apiDewF) ? round2(apiDewF) : null,
    dewpoint_magnus_f: Number.isFinite(calcDewF) ? round2(calcDewF) : null,
    bacnet,
  };
  log(`open-meteo weather ${JSON.stringify(summary)}`);
  return summary;
}

// The hook is the function; the helpers hang off it for offline tests.
module.exports = Object.assign(
  async (ctx) => withDeadline(runOnce(ctx), RUN_DEADLINE_MS, 'open-meteo weather hook run'),
  { magnusDewpointF, openMeteoUrl, pickSite, siteFromModel, coordsFromAttrs, avInstances, bacnetObjects, withDeadline, pageAll },
);
