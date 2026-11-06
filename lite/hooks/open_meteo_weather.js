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

/** The NF site to fetch weather for: config `site` (id) if set, else the only site with coordinates. */
function pickSite(sites, wanted) {
  if (wanted) {
    const s = sites.find((x) => x.id === wanted);
    if (!s) throw new Error(`config site "${wanted}" is not an NF site (have: ${sites.map((x) => x.id).join(', ') || 'none'})`);
    if (!hasCoords(s)) throw new Error(`NF site "${wanted}" has no latitude/longitude; set them in NF (Sites)`);
    return s;
  }
  const located = sites.filter(hasCoords);
  if (located.length === 1) return located[0];
  if (!located.length) throw new Error('no NF site has latitude/longitude; set them in NF (Sites)');
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
const RUN_DEADLINE_MS = 60000; // whole-run cap so a hung run fails instead of blocking the schedule

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
    getJson.lastReq = req;
  });
}

async function getJsonWithRetry(url, log) {
  let lastErr;
  for (let attempt = 0; attempt <= HTTP_RETRIES; attempt += 1) {
    try {
      return await withDeadline(getJson(url), HTTP_TIMEOUT_MS, 'Open-Meteo request', () => {
        if (getJson.lastReq) getJson.lastReq.destroy(new Error('Open-Meteo hard deadline'));
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
  const sitesRes = await nf(sdk.http.get('/api/v1/sites?pageSize=500'), 'GetSites');
  const site = pickSite((sitesRes && sitesRes.sites) || [], config && config.site);
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
    dewpoint_open_meteo_f: Number.isFinite(apiDewF) ? round2(apiDewF) : null,
    dewpoint_magnus_f: Number.isFinite(calcDewF) ? round2(calcDewF) : null,
    bacnet,
  };
  log(`open-meteo weather ${JSON.stringify(summary)}`);
  return summary;
}

module.exports = async (ctx) => withDeadline(runOnce(ctx), RUN_DEADLINE_MS, 'open-meteo weather hook run');

module.exports.magnusDewpointF = magnusDewpointF;
module.exports.openMeteoUrl = openMeteoUrl;
module.exports.pickSite = pickSite;
module.exports.avInstances = avInstances;
module.exports.bacnetObjects = bacnetObjects;
module.exports.withDeadline = withDeadline;
