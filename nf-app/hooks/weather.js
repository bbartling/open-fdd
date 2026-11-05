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
 * Site location comes from NF itself (GET /api/v1/sites: latitude/longitude),
 * so nothing site-specific lives in this file. With one site that has
 * coordinates it is used; with several, set the app config value `site` to the
 * site id. Otherwise the run fails with a clear message.
 *
 * Uses Node's built-in https module only (no npm dependencies), so the app can
 * be created through the console API without a git repository or npm install.
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

const HTTP_TIMEOUT_MS = 20000; // per-attempt deadline for the Open-Meteo request
const HTTP_RETRIES = 1; // one retry on network error/timeout/5xx
const WRITE_TIMEOUT_MS = 10000; // per-point AddPointsData deadline
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
    getJson.lastReq = req;
  });
}

/** Open-Meteo fetch with a hard per-attempt deadline (covers DNS stalls and slow-drip bodies) and one retry. */
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

async function runOnce({ globalVariables, sdk, config }) {
  const log = (msg) => {
    console.log(msg);
    try {
      sdk.logEvent(msg);
    } catch (_) {
      /* logEvent is best effort */
    }
  };

  const sitesRes = await withDeadline(sdk.http.get('/api/v1/sites?pageSize=500'), WRITE_TIMEOUT_MS, 'GetSites');
  const site = pickSite((sitesRes && sitesRes.data && sitesRes.data.sites) || [], config && config.site);
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

  const summary = {
    site: site.id,
    location: `${site.latitude},${site.longitude}`,
    observed: cur.time,
    oa_dry_bulb_f: round2(tempF),
    oa_rh_pct: round2(rh),
    dewpoint_open_meteo_f: Number.isFinite(apiDewF) ? round2(apiDewF) : null,
    dewpoint_magnus_f: Number.isFinite(calcDewF) ? round2(calcDewF) : null,
    dewpoint_delta_f: Number.isFinite(apiDewF) && Number.isFinite(calcDewF) ? round2(calcDewF - apiDewF) : null,
    dewpoint_written_f: round2(dewF),
    dewpoint_source: dewSource,
    write_path: writePath,
  };
  log(`open-meteo weather ${JSON.stringify(summary)}`);
  return summary;
}

module.exports = async (ctx) => withDeadline(runOnce(ctx), RUN_DEADLINE_MS, 'open-meteo weather hook run');

// Exported for offline tests (node -e "require('./open_meteo_weather.js').magnusDewpointF(70,50)").
module.exports.magnusDewpointF = magnusDewpointF;
module.exports.openMeteoUrl = openMeteoUrl;
module.exports.pickSite = pickSite;
module.exports.withDeadline = withDeadline;
