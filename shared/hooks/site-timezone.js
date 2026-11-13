'use strict';
/**
 * The site time zone for a hook, resolved in the SAME order as the dashboard (static/charts.js resolveSiteTimeZone,
 * #1584 / #1587):
 *
 *   1. model site `tz`, then `timezone`           (Haystack SITE record attrs)
 *   2. the app option `timezone`                  (ctx.config.timezone: NF console > app settings)
 *   3. NF Sites `timezone`                        (GET /api/v1/sites: the site by id / name, or the only one)
 *   4. the host zone, when it is not UTC          (a container is usually Etc/UTC: that tells nothing)
 *   5. "UTC", source "none"                       (a fallback, reported as such)
 *
 * The dashboard is a browser global script (no module system), so this file cannot be the one copy for both; the
 * order and the source names are pinned by nf-app/tests/site-timezone-hook.test.mjs, which runs charts.js and this
 * module over the same cases. A zone that is not an IANA name is skipped (and named in `ignored`), never used.
 *
 * Source names (shown in run summaries and logs): "model site" | "app option" | "NF Sites API" | "host" | "none".
 */
const { listAll } = require('./paging.js');

/** @param {any} z @returns {string | null} the zone when Intl knows it, else null */
function knownZone(z) {
  const s = String(z === undefined || z === null ? '' : z).trim();
  if (!s) return null;
  try { new Intl.DateTimeFormat('en-US', { timeZone: s }); return s; } catch (_) { return null; }
}

const isUtcZone = (z) => /^(utc|etc\/utc|etc\/gmt|gmt|z)$/i.test(String(z === undefined || z === null ? '' : z).trim());

/** The zone of the machine running the hook (null when unknown or UTC). */
function hostZone() {
  try {
    const z = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return isUtcZone(z) ? null : knownZone(z);
  } catch (_) { return null; }
}

/** The app option `timezone` from ctx.config (typed values already unwrapped by settings.normalizeConfig), raw. */
const optionOf = (config) => {
  const c = config || {};
  const v = c.timezone !== undefined ? c.timezone : c.timeZone;
  return v === undefined || v === null || String(v).trim() === '' ? null : String(v).trim();
};

/** The NF Sites entry for a model site: matched by id / name / dis, else the only site that has a zone. */
function nfSiteFor(sites, siteRec) {
  const list = (Array.isArray(sites) ? sites : []).filter((s) => s && knownZone(s.timezone));
  const a = (siteRec && siteRec.attrs) || {};
  const names = [a.id, a.name, a.dis, siteRec && siteRec.name].filter(Boolean).map(String);
  return list.find((s) => [s.id, s.name].filter(Boolean).map(String).some((n) => names.includes(n)))
    || (list.length === 1 ? list[0] : null);
}

/**
 * @param {any} siteRec model SITE record (attrs.tz / attrs.timezone), may be null
 * @param {{ config?: any, sites?: any[], host?: string | null }} [inputs]
 *   host: override the host zone (tests); undefined = the real one
 * @returns {{ zone: string, source: string, fallback: boolean, label: string, ignored?: string }}
 */
function resolveSiteTimeZone(siteRec, inputs = {}) {
  const a = (siteRec && siteRec.attrs) || {};
  const opt = optionOf(inputs.config);
  const optZone = knownZone(opt);
  const nfSite = nfSiteFor(inputs.sites, siteRec);
  const host = inputs.host !== undefined ? knownZone(inputs.host) : hostZone();
  const hit = [[knownZone(a.tz), 'model site', false], [knownZone(a.timezone), 'model site', false],
    [optZone, 'app option', false], [nfSite && knownZone(nfSite.timezone), 'NF Sites API', false],
    [isUtcZone(host) ? null : host, 'host', true]].find((c) => c[0]) || ['UTC', 'none', true];
  const [zone, source, fallback] = hit;
  const out = { zone: /** @type {string} */ (zone), source: /** @type {string} */ (source), fallback: !!fallback,
    label: fallback ? `${zone} (${source === 'host' ? 'host fallback' : 'fallback'})` : /** @type {string} */ (zone) };
  if (opt && !optZone) out.ignored = `app option "timezone" is "${opt}", not an IANA zone name (e.g. America/Chicago): ignored`;
  return out;
}

/**
 * NF Sites with a usable zone, one read per run; a failure leaves the source empty (the chain falls through) and
 * is returned so the caller can log it.
 * @param {any} http sdk.http
 * @returns {Promise<{ sites: any[], error: string | null }>}
 */
async function loadNfSites(http) {
  try {
    const sites = await listAll(http, '/api/v1/sites', 'sites');
    return { sites: sites.filter((s) => s && knownZone(s.timezone)), error: null };
  } catch (e) {
    return { sites: [], error: String((e && e.message) || e) };
  }
}

module.exports = { resolveSiteTimeZone, loadNfSites, nfSiteFor, knownZone, isUtcZone, hostZone, optionOf };
