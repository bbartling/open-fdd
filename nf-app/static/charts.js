// GENERATED COPY of shared/static/charts.js by scripts/nf/sync_shared.py: edit the source, then re-run the script.
// Chart catalog for the Open-FDD pages (both editions; source: shared/static/charts.js). Each chart says which points it needs (by tags), which
// ranges it offers and how NF should resample them, so only one small request goes
// out per chart and nothing is fetched for charts that aren't on screen.
//
// NF resamples server side: /api/v1/point/data?...&window=<s>s&method=AVERAGE|MIN|MAX
// returns one value per window (7 days of one sensor: 916 KB raw vs 14 KB hourly).
// Used by the Charts tab (app-core.js) and the standalone chart.html. Needs nf.js, model.js and
// theme.js: options here are theme-free (colors come from the registered ECharts themes). units.js is optional
// (Full only): without it the display helpers show values and units as NF stores them.

const unitLabel = (u) => u || "";

// ---- display units (units.js: calculations are SI, the UI shows the user's system) -------
// Raw series from fetchSeries() stay in the unit NF stores; these helpers convert for display only.
const unitSystem = () => (typeof ofddUnits !== "undefined" ? ofddUnits.displaySystem() : "imperial");
/** One value of point `p` in the display system. */
const dispVal = (p, v) => (typeof ofddUnits === "undefined" || v == null ? v : ofddUnits.display(v, p.units, unitSystem()).value);
/** Unit label of point `p` in the display system. */
const dispUnit = (p) => (typeof ofddUnits === "undefined" ? p.units || "" : ofddUnits.display(0, p.units, unitSystem()).unit);
/** [[ms, value], ...] of point `p` converted to the display system. */
const dispSeries = (p, arr) => (typeof ofddUnits === "undefined" || !arr ? arr : arr.map(([t, v]) => [t, dispVal(p, v)]));
const parseTs = (ts) => Date.parse(ts.replace(/(\.\d{3})\d+/, "$1"));
const fmt = (v, d = 1) => (v == null || isNaN(v) ? "–" : v.toFixed(d));
const latestOf = (p) => p.latest?.double ?? p.latest?.real;

const axisStyle = {};            // axis colors come from the theme
const tooltip = { trigger: "axis" };
const legend = { top: 0 };

// ---- which points, by tags (shared with app.js) ------------------------------------
// Sensors first, temps first, then setpoints; ties by label.
const rank = (p) => (has(p, "sensor") ? 0 : 2) + (isTemp(p) ? 0 : 1);

/** Equip scope value that selects the weather points instead of an equipment (A8: weather is its own category). */
const WEATHER_SCOPE = "__weather__";
const WEATHER_LABEL = "Weather";
/** A weather-service point (marker `weather` or a `weatherStationRef`): never one of an equip's own sensors. */
/** An FDD hook result point (markers fdd / fault, or a ruleRef): an output, never a signal; same test the FDD tab uses. */
const isFddResult = (p) => has(p, "fdd") || has(p, "fault") || !!((p.rec && p.rec.attrs) || {}).ruleRef;
const isWeatherPoint = (p) => has(p, "weather") || !!p.weatherStationRef;

/**
 * Point sets for a site (and optionally one equip, or WEATHER_SCOPE): cards/charts (numeric sensors + setpoints),
 * numeric (every numeric trended point, commands included), status (Bool), weather, and equipNames (id -> label).
 */
function pointSets(model, site, equip) {
  const equips = model.equips.filter((e) => (e.attrs || {}).siteRef === site);
  const equipIds = equips.map(idOf);
  const tagged = model.points.filter((p) => p.siteRef === site && has(p, "point"));
  const weather = tagged.filter(isWeatherPoint).sort((a, b) => a.name.localeCompare(b.name));
  const inScope = (p) => !isWeatherPoint(p) && p.equipRef && (equip ? p.equipRef === equip : equipIds.includes(p.equipRef));
  const equipPts = equip === WEATHER_SCOPE ? weather : tagged.filter(inScope);
  const trended = (p) => p.kind === "Number" && has(p, "his") && !has(p, "spare") && !isFddResult(p);
  return {
    // weather points are cards whether or not the station tagged them `sensor`
    cards: equipPts.filter((p) => trended(p) && (equip === WEATHER_SCOPE || has(p, "sensor") || has(p, "sp")))
      .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)),
    numeric: equipPts.filter(trended).sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)),
    status: equipPts.filter((p) => p.kind === "Bool" && !has(p, "spare") && !isFddResult(p))
      .sort((a, b) => (a.equipRef || "").localeCompare(b.equipRef || "") || a.name.localeCompare(b.name)),
    weather,
    scopeEquip: equip || "",
    equipNames: Object.fromEntries(equips.map((e) => [idOf(e), (e.attrs || {}).dis || e.name])),
  };
}

/** Where a point sits, for labels: its equip's name, "Weather" for weather points. */
function pointOwner(p, c) {
  if (isWeatherPoint(p)) return WEATHER_LABEL;
  return (c && c.equipNames && c.equipNames[p.equipRef]) || p.equipRef || "";
}
/** Series / option label from the model (dis, else the marker name), prefixed with the equip when `points` span several. */
function pointLabel(p, c, points) {
  const base = p.dis || p.name || "";
  if (!base) return "";
  const owners = new Set((points || []).map((x) => pointOwner(x, c)));
  const owner = pointOwner(p, c);
  return owners.size > 1 && owner && !base.startsWith(owner) ? `${owner} · ${base}` : base;
}
/** Dropdown options of a catalog chart picker: label = dis + unit, from the model (A5). */
function pickOptions(def, c) {
  const pts = def.pick ? def.pick(c) : [];
  return pts.map((p) => ({ value: p.uuid, label: `${pointLabel(p, c, pts)}${dispUnit(p) ? ` (${dispUnit(p)})` : ""}` }))
    .filter((o) => o.label);
}

// Outside air temp + humidity sensors on one equip, found by markers.
function rhPair(points) {
  const t = points.find((p) => has(p, "outside", "air", "temp", "sensor"));
  const rh = points.find((p) => has(p, "outside", "air", "humidity", "sensor") && p.equipRef === t?.equipRef);
  return t && rh ? [t, rh] : null;
}

function dewPointC(tC, rh) {
  const a = 17.62, b = 243.12;
  const g = Math.log(rh / 100) + (a * tC) / (b + tC);
  return (b * g) / (a - g);
}
function dewPointF(tF, rh) {
  return dewPointC((tF - 32) / 1.8, rh) * 1.8 + 32;
}

// ---- history: resampled by NF, cached briefly ---------------------------------------
const WINDOWS = [60, 300, 600, 900, 1800, 3600, 7200, 14400, 86400];

/** @typedef {Map<any, any> & {windowSec: number}} HistorySeriesMap */

/** Smallest window giving at most ~`target` values per series over `hours`. */
const pickWindow = (hours, target = 360) => WINDOWS.find((w) => (hours * 3600) / w <= target) || 86400;
const windowLabel = (seconds) => seconds >= 3600 ? `${+(seconds / 3600).toFixed(1)} h` : `${+(seconds / 60).toFixed(1)} min`;

const seriesCache = new Map();  // url -> { at, promise }
const CACHE_MS = 60e3;
// Leave room for fixed query parameters and request headers under NF's ~8 KB front-door limit.
const HISTORY_URL_BUDGET = 6000;
const HISTORY_UUID_BATCH = 40;

// A chart range is stored as absolute instants in the page URL. Date-time inputs are
// formatted and parsed in the site's IANA timezone, not the browser's local timezone.
const RANGE_PRESETS = Object.freeze({ "1h": 1, "24h": 24, "1w": 168 });
// The ONE default range for every history view (Overview, Charts, Points, FDD, RCx, chart.html, export): the last 7 days.
// "All" and the other presets stay selectable; anything without a range in the page URL starts here.
const DEFAULT_RANGE_PRESET = "1w";
const DEFAULT_RANGE_HOURS = RANGE_PRESETS[DEFAULT_RANGE_PRESET];
/** A fresh state for the default range. @returns {{preset: string, fromMs?: number, toMs?: number}} */
const defaultChartRange = () => ({ preset: DEFAULT_RANGE_PRESET });
const validChartTimeZone = (tz) => {
  try { new Intl.DateTimeFormat("en-US", { timeZone: tz || "UTC" }); return tz || "UTC"; }
  catch { return "UTC"; }
};
function chartTimeZone(siteTz) { return validChartTimeZone(siteTz); }

// ---- site timezone (#1584) -------------------------------------------------------------------
// Real NF often has no site `tz`, an empty /api/v1/sites and a container zone of Etc/UTC. Resolution order:
// model site `tz`/`timezone` -> app option `timezone` -> NF Sites API `timezone` -> browser-local -> UTC.
// Nothing is retagged; the resolved source is shown next to the zone when it is a fallback.
// modelSites: SITE records in the loaded model (null until loadModel ran); a lone Sites API record is only
// borrowed for an unmatched site when the model is not known to hold several sites.
const SITE_TZ_SOURCES = { appOption: null, sites: [], weatherOff: false, modelSites: null };
/** Called by loadModel with the number of modeled sites. */
function noteModelSiteCount(n) { SITE_TZ_SOURCES.modelSites = Number.isFinite(n) ? n : null; }
/** The optional zone reads must not hold the page: give up after `ms` and use the remaining fallbacks. */
const TZ_READ_TIMEOUT_MS = 5000;
function boundedRead(p, ms = TZ_READ_TIMEOUT_MS) {
  if (typeof setTimeout !== "function") return p;
  let t;
  return Promise.race([p, new Promise((_, rej) => { t = setTimeout(() => rej(new Error("timed out")), ms); })])
    .finally(() => clearTimeout(t));
}
const chartTzLabels = new Map();            // zone -> label shown next to the range pickers
const knownZone = (z) => {
  const s = String(z ?? "").trim();
  if (!s) return null;
  try { new Intl.DateTimeFormat("en-US", { timeZone: s }); return s; } catch { return null; }
};
const isUtcZone = (z) => /^(utc|etc\/utc|etc\/gmt|gmt|z)$/i.test(String(z ?? "").trim());
/** @param {{appOption?: string|null, sites?: any[], weatherOff?: boolean}} s */
function setSiteTimeZoneSources(s = {}) {
  SITE_TZ_SOURCES.appOption = knownZone(s.appOption);
  SITE_TZ_SOURCES.sites = Array.isArray(s.sites) ? s.sites : [];
  SITE_TZ_SOURCES.weatherOff = !!s.weatherOff;
}
/** The raw value of an app option (typed or scalar) from a GET /api/v1/apps listing entry, or undefined. */
function appOptionRaw(app, name) {
  for (const o of (app && app.options) || []) {
    if (o && o.name === name) return o.value && typeof o.value === "object" ? Object.values(o.value)[0] : o.value;
  }
  return undefined;
}
/** The app option `timezone` from a GET /api/v1/apps listing entry, or null. */
function appTimeZoneOption(app) { return knownZone(appOptionRaw(app, "timezone")); }
/** True when the app option `weather` (alias `weatherEnabled`) is switched OFF (#1552): no web weather is fetched, so stale weather points are not used. */
function appWeatherOff(app) {
  return ["weather", "weatherEnabled"].some((n) => ["false", "0", "no", "off"].includes(String(appOptionRaw(app, n) ?? "").trim().toLowerCase()));
}
/** Is the web weather switched off in the app options? (set by loadSiteTimeZoneSources / the analytics hook) */
const weatherDisabled = () => SITE_TZ_SOURCES.weatherOff;
/** Best-effort read of the non-model zone sources + the weather switch; a failure just leaves that source empty. */
async function loadSiteTimeZoneSources() {
  const loc = typeof location === "undefined" ? null : location;
  const appId = loc && (String(loc.pathname || "").match(/\/apps\/static\/([^/]+)\//) || [])[1];
  let appOption = null, weatherOff = false, sites = [];
  // both reads run together, each bounded; a failure or a timeout just leaves that source empty
  const [appsR, sitesR] = await Promise.allSettled([
    appId ? boundedRead(api("/api/v1/apps")) : Promise.resolve(null),
    boundedRead(api("/api/v1/sites?pageSize=100")),
  ]);
  try {
    const app = appsR.status === "fulfilled" && appsR.value ? (appsR.value.applications || []).find((a) => a.id === appId) : null;
    appOption = appTimeZoneOption(app); weatherOff = appWeatherOff(app);
  } catch { /* malformed: leave empty */ }
  try { sites = sitesR.status === "fulfilled" ? ((sitesR.value || {}).sites || []).filter((s) => s && knownZone(s.timezone)) : []; } catch { sites = []; }
  setSiteTimeZoneSources({ appOption, sites, weatherOff });
}
/**
 * The zone to show and parse for a model site record.
 * @param {any} siteRec model SITE record (attrs.tz / attrs.timezone), may be null
 * @param {{browser?: boolean, register?: boolean}} [opts] browser:false skips the browser zone (hooks)
 * @returns {{zone: string, source: string, fallback: boolean, label: string}}
 */
function resolveSiteTimeZone(siteRec, opts = {}) {
  const a = (siteRec && siteRec.attrs) || {};
  const names = [a.id, a.name, a.dis, siteRec && siteRec.name].filter(Boolean).map(String);
  const fromApi = (SITE_TZ_SOURCES.sites.find((s) => [s.id, s.name].filter(Boolean).map(String).some((n) => names.includes(n)))
    || (SITE_TZ_SOURCES.sites.length === 1 && !(SITE_TZ_SOURCES.modelSites > 1) ? SITE_TZ_SOURCES.sites[0] : null) || {}).timezone;
  let browser = null;
  if (opts.browser !== false) {
    try { browser = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { browser = null; }
    browser = isUtcZone(browser) ? null : knownZone(browser);
  }
  const hit = [[knownZone(a.tz), "model site", false], [knownZone(a.timezone), "model site", false],
    [SITE_TZ_SOURCES.appOption, "app option", false], [knownZone(fromApi), "NF Sites API", false], [browser, "browser", true]]
    .find((c) => c[0]) || ["UTC", "none", true];
  const [zone, source, fallback] = hit;
  const label = !fallback ? zone : source === "browser" ? `${zone} (browser fallback)` : `${zone} (fallback)`;
  if (opts.register !== false) chartTzLabels.set(zone, label);
  return { zone, source, fallback, label };
}
const scheduleApi = () => /** @type {any} */ (globalThis).ofddSchedule;
/** @returns {{preset: string, fromMs?: number, toMs?: number}} */
function getChartRangeState(key) {
  const q = new URLSearchParams(typeof location === "undefined" ? "" : location.search);
  const preset = q.get(`range.${key}`) || DEFAULT_RANGE_PRESET;
  if (preset === "custom") {
    const fromRaw = q.get(`from.${key}`), toRaw = q.get(`to.${key}`), fromMs = Number(fromRaw), toMs = Number(toRaw);
    if (fromRaw && toRaw && Number.isSafeInteger(fromMs) && Number.isSafeInteger(toMs)
      && Number.isFinite(new Date(fromMs).getTime()) && Number.isFinite(new Date(toMs).getTime()) && fromMs < toMs)
      return { preset, fromMs, toMs };
    return defaultChartRange();
  }
  return { preset: Object.hasOwn(RANGE_PRESETS, preset) || preset === "all" ? preset : DEFAULT_RANGE_PRESET };
}
function setChartRangeState(key, state, { push = true } = {}) {
  const url = new URL(location.href), q = url.searchParams;
  q.set(`range.${key}`, state.preset);
  q.delete(`from.${key}`); q.delete(`to.${key}`);
  if (state.preset === "custom") {
    q.set(`from.${key}`, String(state.fromMs)); q.set(`to.${key}`, String(state.toMs));
  }
  history[push ? "pushState" : "replaceState"]({}, "", url);
  return state;
}
function resolveChartRange(state, { nowMs = Date.now(), oldestMs = null } = {}) {
  if (state?.preset === "custom" && Number.isFinite(state.fromMs) && Number.isFinite(state.toMs) && state.fromMs < state.toMs)
    return { fromMs: state.fromMs, toMs: state.toMs };
  if (state?.preset === "all") return { fromMs: Number.isFinite(oldestMs) ? oldestMs : nowMs, toMs: nowMs };
  const hours = RANGE_PRESETS[state?.preset] || DEFAULT_RANGE_HOURS;
  return { fromMs: nowMs - hours * 3600e3, toMs: nowMs };
}

const dateTimeInputValue = (ms, siteTz) => {
  const tz = chartTimeZone(siteTz);
  const schedule = scheduleApi();
  const p = schedule ? schedule.localParts(ms, tz) : (() => {
    const vals = {};
    for (const x of new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(new Date(ms)))
      if (x.type !== "literal") vals[x.type] = Number(x.value);
    return { y: vals.year, m: vals.month, d: vals.day, h: vals.hour % 24, mi: vals.minute };
  })();
  return `${String(p.y).padStart(4, "0")}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")}T${String(p.h).padStart(2, "0")}:${String(p.mi).padStart(2, "0")}`;
};
const dateTimeInputMs = (value, siteTz) => {
  const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)$/.exec(value || "");
  if (!m) return NaN;
  const tz = chartTimeZone(siteTz), [y, mo, d, h, mi] = m.slice(1).map(Number);
  const schedule = scheduleApi();
  if (schedule) {
    const ms = schedule.localToMs(y, mo, d, h, mi, tz), p = schedule.localParts(ms, tz);
    return p.y === y && p.m === mo && p.d === d && p.h === h && p.mi === mi ? ms : NaN;
  }
  const wall = Date.UTC(y, mo - 1, d, h, mi), fields = (t) => {
    const x = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(new Date(t));
    const o = {}; for (const a of x) if (a.type !== "literal") o[a.type] = Number(a.value);
    return Date.UTC(o.year, o.month - 1, o.day, o.hour % 24, o.minute);
  };
  let t = wall; t = wall - (fields(t) - t); t = wall - (fields(t) - t);
  return fields(t) === wall ? t : NaN;
};

/** Mount shared range buttons and site-timezone custom fields.
 * @param {HTMLElement} container
 * @param {{key?:string,state?:any,siteTz?:string,onChange?:(state:any)=>void}} options
 */
function renderRangeControl(container, { key = "default", state = getChartRangeState(key), siteTz = "UTC", onChange } = {}) {
  const tz = chartTimeZone(siteTz), now = Date.now();
  container.classList.add("chart-range-control");
  const bounds = state.preset === "custom" ? state : resolveChartRange(state, { nowMs: now, oldestMs: now - 24 * 3600e3 });
  container.innerHTML = `<div class="seg chart-range-presets">${[["1h", "1 h"], ["24h", "24 h"], ["1w", "1 week"], ["all", "All"]].map(([v, label]) =>
    `<button type="button" data-range="${v}" class="${state.preset === v ? "on" : ""}">${label}</button>`).join("")}</div>
    <label>From <input type="datetime-local" data-range-from step="60" value="${dateTimeInputValue(bounds.fromMs, tz)}"></label>
    <label>To <input type="datetime-local" data-range-to step="60" value="${dateTimeInputValue(bounds.toMs, tz)}"></label>
    <span class="sub">${esc(chartTzLabels.get(tz) || tz)}</span><button type="button" data-range-apply>Apply</button>`;
  const applyState = (next, push = true) => {
    setChartRangeState(key, next, { push });
    onChange?.(next);
  };
  container.onclick = (event) => {
    const target = /** @type {HTMLElement | null} */ (/** @type {HTMLElement} */ (event.target).closest("[data-range]"));
    if (target) applyState({ preset: target.dataset.range });
    else if ((/** @type {HTMLElement} */ (event.target)).closest("[data-range-apply]")) {
      const fromMs = dateTimeInputMs(/** @type {HTMLInputElement} */ (container.querySelector("[data-range-from]")).value, tz);
      const toMs = dateTimeInputMs(/** @type {HTMLInputElement} */ (container.querySelector("[data-range-to]")).value, tz);
      if (Number.isFinite(fromMs) && fromMs < toMs) applyState({ preset: "custom", fromMs, toMs });
      else {
        const end = /** @type {HTMLInputElement} */ (container.querySelector("[data-range-to]"));
        end.setCustomValidity("Enter valid site-local times with end after start"); end.reportValidity();
      }
    }
  };
  container.oninput = (event) => /** @type {HTMLInputElement} */ (event.target).setCustomValidity("");
  return state;
}

function historyUrl(points, from, to, windowSec, method) {
  const ids = points.map((p) => "uuids=" + encodeURIComponent(p.uuid)).join("&");
  return `/api/v1/point/data?${ids}&from=${from}&to=${to}&window=${windowSec}s&method=${method}&count=10000&reverse=false`;
}

function historyChunks(list, from, to, windowSec, method) {
  const chunks = [];
  let chunk = [];
  for (const point of list) {
    const candidate = [...chunk, point];
    if (chunk.length && (candidate.length > HISTORY_UUID_BATCH
      || historyUrl(candidate, from, to, windowSec, method).length > HISTORY_URL_BUDGET)) {
      chunks.push(chunk);
      chunk = [point];
    } else chunk = candidate;
    if (historyUrl(chunk, from, to, windowSec, method).length > HISTORY_URL_BUDGET) {
      throw new Error("point history request exceeds the safe URL limit");
    }
  }
  if (chunk.length) chunks.push(chunk);
  return chunks;
}

/**
 * uuid -> [[ms, value], ...] for `list` over the last `hours`, one value per window.
 * UUIDs are grouped into bounded requests; repeat calls within a minute reuse each chunk answer.
 */
async function fetchSeries(list, hours, { method = "AVERAGE", windowSec = pickWindow(hours), endMs = null, fromMs = null } = {}) {
  const out = /** @type {HistorySeriesMap} */ (new Map(list.map((p) => [p.uuid, []])));
  out.windowSec = windowSec;
  if (!list.length) return out;
  // Round the end to the window so repeat views share a cache entry. endMs (window-aligned) lets a
  // caller walk a long span back in chunks (rcx.js alignedFine).
  const end = endMs != null ? endMs : Math.ceil(Date.now() / (windowSec * 1e3)) * windowSec * 1e3;
  const from = new Date(fromMs == null ? end - hours * 3600e3 : fromMs).toISOString(), to = new Date(end).toISOString();
  const chunks = historyChunks(list, from, to, windowSec, method);
  // A small fixed concurrency bounds load while keeping 709-sensor views practical.
  for (let base = 0; base < chunks.length; base += 4) {
    const responses = await Promise.all(chunks.slice(base, base + 4).map((chunk) => {
      const url = historyUrl(chunk, from, to, windowSec, method);
      let hit = seriesCache.get(url);
      if (!hit || Date.now() - hit.at > CACHE_MS) {
        hit = { at: Date.now(), promise: api(url) };
        seriesCache.set(url, hit);
        hit.promise.catch(() => seriesCache.delete(url));
        for (const [k, v] of seriesCache) if (Date.now() - v.at > CACHE_MS) seriesCache.delete(k);
      }
      return hit.promise;
    }));
    for (const response of responses) for (const series of response.data || []) {
      const arr = out.get(series.uuid);
      if (!arr) continue;
      for (const s of series.values || []) {
        const v = s.double ?? s.real;
        if (v != null && s.ts) arr.push([parseTs(s.ts), v]);
      }
    }
  }
  for (const arr of out.values()) arr.sort((a, b) => a[0] - b[0]);
  return out;
}

const oldestCache = new Map();
function oldestUrl(points) {
  const ids = points.map((p) => `uuids=${encodeURIComponent(p.uuid)}`).join("&");
  return `/api/v1/point/data?${ids}&count=1&reverse=false`;
}
function oldestChunks(list) {
  const chunks = []; let chunk = [];
  for (const point of list) {
    const candidate = [...chunk, point];
    if (chunk.length && (candidate.length > HISTORY_UUID_BATCH || oldestUrl(candidate).length > HISTORY_URL_BUDGET)) {
      chunks.push(chunk); chunk = [point];
    } else chunk = candidate;
    if (oldestUrl(chunk).length > HISTORY_URL_BUDGET) throw new Error("point history request exceeds the safe URL limit");
  }
  if (chunk.length) chunks.push(chunk);
  return chunks;
}
async function oldestSamples(list) {
  const now = Date.now(), missing = list.filter((p) => {
    const hit = oldestCache.get(p.uuid), ttl = Number.isFinite(hit?.value) ? 10 * 60e3 : 30e3;
    return !hit || now - hit.at >= ttl;
  });
  const chunks = oldestChunks(missing);
  for (let base = 0; base < chunks.length; base += 4) {
    const batch = chunks.slice(base, base + 4);
    const results = await Promise.all(batch.map(async (chunk) => {
      try { return { body: await api(oldestUrl(chunk)) }; }
      catch (error) { return { error }; }
    }));
    let failure;
    for (let i = 0; i < results.length; i++) {
      const result = results[i];
      if (result.error) { failure ||= result.error; continue; }
      const body = result.body, chunk = batch[i];
      const rows = Array.isArray(body.data) ? body.data : body.data?.data || [];
      for (const row of rows) {
        const ts = row?.values?.[0]?.ts;
        oldestCache.set(row.uuid, { at: now, value: ts ? parseTs(ts) : null });
      }
      for (const p of chunk) if (oldestCache.get(p.uuid)?.at !== now) oldestCache.set(p.uuid, { at: now, value: null });
    }
    if (failure) throw failure;
  }
  return list.map((p) => oldestCache.get(p.uuid)?.value ?? null);
}

async function resolveChartSelection(list, state, { siteTz = "UTC", nowMs = Date.now() } = {}) {
  let oldestMs = null;
  if (state?.preset === "all" && list.length) {
    const found = (await oldestSamples(list)).filter(Number.isFinite);
    if (found.length) oldestMs = Math.min(...found);
  }
  return { ...state, resolvedBounds: resolveChartRange(state, { nowMs, oldestMs }), timeZone: chartTimeZone(siteTz) };
}

/**
 * Fetch a preset or custom interval. The effective window expands for long intervals so the
 * Normal GetData 10,000 sample limit cannot silently truncate the oldest part of the range.
 * Returns bucket series with exact requested bounds for consumers that need axis clipping.
 */
async function fetchRange(list, state, { method = "AVERAGE", windowSec = null, minWindowSec = 60,
  siteTz = "UTC", endMs = null, nowMs = Date.now(), preserveWindow = false, target = 360 } = {}) {
  nowMs = endMs ?? nowMs;
  const resolved = state?.resolvedBounds ? state : await resolveChartSelection(list, state, { siteTz, nowMs });
  const bounds = resolved.resolvedBounds;
  const spanHours = Math.max(0, (bounds.toMs - bounds.fromMs) / 3600e3);
  const automatic = windowSec || Math.max(pickWindow(spanHours || 1, target), Math.ceil((bounds.toMs - bounds.fromMs) / (target * 1000)));
  const wanted = Math.max(minWindowSec, automatic);
  const capWindow = Math.ceil((bounds.toMs - bounds.fromMs) / 9999e3);
  const effectiveWindowSec = preserveWindow ? wanted : Math.max(wanted, capWindow, 1);
  const series = new Map(list.map((p) => [p.uuid, []]));
  const chunkMs = 9999 * effectiveWindowSec * 1000;
  const chunks = [{ fromMs: bounds.fromMs, toMs: bounds.toMs }];
  if (preserveWindow && bounds.toMs - bounds.fromMs > chunkMs) {
    chunks.length = 0;
    let cursor = bounds.fromMs;
    while (cursor < bounds.toMs) {
      const alignedCap = (Math.floor(cursor / (effectiveWindowSec * 1000)) + 9999) * effectiveWindowSec * 1000;
      const end = Math.min(bounds.toMs, alignedCap > cursor ? alignedCap : cursor + chunkMs);
      chunks.push({ fromMs: cursor, toMs: end }); cursor = end;
    }
  }
  for (const chunk of chunks) {
    const got = await fetchSeries(list, (chunk.toMs - chunk.fromMs) / 3600e3, { method, windowSec: effectiveWindowSec,
      endMs: chunk.toMs, fromMs: chunk.fromMs });
    for (const p of list) series.get(p.uuid).push(...(got.get(p.uuid) || []));
  }
  for (const [uuid, values] of series) {
    const byTimestamp = new Map();
    for (const [timestamp, value] of values) byTimestamp.set(timestamp, value);
    series.set(uuid, [...byTimestamp].sort((a, b) => a[0] - b[0]));
  }
  // Resampling buckets are aligned to the Unix epoch. NF applies `from`/`to` to input samples;
  // clamp display coordinates so partial edge buckets remain visible inside the chosen interval.
  if (state?.preset === "custom") for (const [uuid, values] of series) {
    series.set(uuid, values.filter(([t]) => t < bounds.toMs).map(([t, v]) => [Math.max(t, bounds.fromMs), v]));
  }
  return { series, windowSec: effectiveWindowSec, fromMs: bounds.fromMs, toMs: bounds.toMs,
    timeZone: chartTimeZone(siteTz) };
}

/** Catalog chart fetcher: retain fetchSeries' Map shape while honoring the active range. */
async function fetchChartSeries(ctx, list, hours, opts = {}) {
  if (ctx?.range) {
    const result = await fetchRange(list, ctx.range, { ...opts, siteTz: ctx.siteTz || "UTC" });
    const series = /** @type {HistorySeriesMap} */ (result.series);
    series.windowSec = result.windowSec;
    return series;
  }
  return fetchSeries(list, hours, opts);
}
async function fetchChartDisplay(ctx, list, hours, opts = {}) {
  const out = await fetchChartSeries(ctx, list, hours, opts);
  for (const p of list) out.set(p.uuid, dispSeries(p, out.get(p.uuid)));
  return out;
}

/** fetchSeries() with every series converted to the display system (per point unit). */
async function fetchDisplay(list, hours, opts) {
  const out = await fetchSeries(list, hours, opts);
  for (const p of list) out.set(p.uuid, dispSeries(p, out.get(p.uuid)));
  return out;
}

const dayFormatter = (siteTz) => new Intl.DateTimeFormat(undefined, {
  weekday: "short", month: "numeric", day: "numeric",
  ...(siteTz ? { timeZone: chartTimeZone(siteTz), year: "numeric" } : {}),
});

function hourOfDayFormatter(siteTz) {
  const clock = new Intl.DateTimeFormat("en-US", {
    ...(siteTz ? { timeZone: chartTimeZone(siteTz) } : {}), hourCycle: "h23", hour: "numeric", minute: "numeric",
  });
  return (ms) => {
    const parts = clock.formatToParts(ms);
    const hour = Number(parts.find((p) => p.type === "hour").value);
    const minute = Number(parts.find((p) => p.type === "minute").value);
    return hour + minute / 60;
  };
}

/** Group [[ms, v]] by local calendar day -> Map(day -> values[]), days in time order. */
function byDay(arr, siteTz) {
  const m = new Map();
  const day = dayFormatter(siteTz);
  for (const [t, v] of arr) {
    const k = day.format(t);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(v);
  }
  return m;
}

const lineSeries = (p, data, extra = {}) => ({
  name: p.name, type: "line", showSymbol: false, smooth: 0.2, lineStyle: { width: 1.6 },
  emphasis: { focus: "series" }, data, ...extra,
});

// ---- the catalog --------------------------------------------------------------------
// ctx = { cards, numeric, status, weather, equipNames } from pointSets(). Each entry:
//   applies(ctx)      chart makes sense for these points (else hidden)
//   ranges / range    offered + default hours
//   pick(ctx)         optional: points for a picker; build gets opt.point
//   build(ctx, hours, opt) -> { option, hint }   (fetches only what it draws)
const CHARTS = [
  {
    id: "temps", title: "Temperatures", desc: "Every temperature sensor and setpoint on the equip",
    ranges: [6, 24, 72, 168], range: 24,
    applies: (c) => c.cards.some(isTemp),
    async build(c, hours) {
      const temps = c.cards.filter(isTemp);
      const s = await fetchChartDisplay(c, temps, hours);
      return {
        hint: `${temps.length} points · ${windowLabel(s.windowSec)} averages`,
        option: {
          tooltip, legend, grid: { left: 50, right: 20, top: 36, bottom: 60 },
          xAxis: { type: "time", ...axisStyle },
          yAxis: { type: "value", scale: true, name: temps[0] ? dispUnit(temps[0]) : "", ...axisStyle },
          series: temps.map((p) => lineSeries(p, s.get(p.uuid))),
        },
      };
    },
  },
  {
    id: "heatmap", title: "Hour-of-day heatmap", desc: "One sensor's hourly average, day by day (pick the sensor)",
    ranges: [72, 168], range: 168,
    applies: (c) => c.cards.length > 0,
    pick: (c) => c.cards,
    defaultPick: (c) => (c.cards.find((p) => has(p, "discharge", "air", "temp")) || c.cards[0])?.uuid,
    async build(c, hours, opt) {
      const p = c.cards.find((x) => x.uuid === opt.point) || c.cards[0];
      const arr = (await fetchChartDisplay(c, [p], hours, { windowSec: 3600, preserveWindow: true })).get(p.uuid);
      const days = [];
      const dayLabel = dayFormatter(c.siteTz), hour = hourOfDayFormatter(c.siteTz);
      const data = arr.map(([t, v]) => {
        const day = dayLabel.format(t);
        if (!days.includes(day)) days.push(day);
        return [Math.floor(hour(t)), days.indexOf(day), +v.toFixed(2)];
      });
      const vals = data.map((d) => d[2]);
      return {
        hint: `${p.dis} · hourly averages, site time`,
        option: {
          tooltip: { position: "top", formatter: (x) => `${days[x.value[1]]} ${x.value[0]}:00<br><b>${x.value[2]} ${dispUnit(p)}</b>` },
          grid: { left: 90, right: 20, top: 10, bottom: 80 },
          xAxis: { type: "category", data: [...Array(24).keys()].map(String), ...axisStyle },
          yAxis: { type: "category", data: days, ...axisStyle },
          visualMap: {
            min: vals.length ? Math.min(...vals) : 0, max: vals.length ? Math.max(...vals) : 1,
            calculable: true, orient: "horizontal", left: "center", bottom: 0,
            itemHeight: 220,
            inRange: { color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#f94144"] },
          },
          dataZoom: false,
          series: [{ type: "heatmap", data, itemStyle: { borderColor: themeName() === "dark" ? "#121a30" : "#ffffff", borderWidth: 2, borderRadius: 3 } }],
        },
      };
    },
  },
  {
    id: "daily", title: "Daily min / mean / max", desc: "Each temperature's range per day",
    ranges: [72, 168], range: 168,
    applies: (c) => c.cards.some(isTemp),
    async build(c, hours) {
      const temps = c.cards.filter(isTemp);
      // Hourly MIN / MAX / AVERAGE from NF, folded into local days here (NF's daily
      // windows are UTC-aligned). 3 small requests instead of every raw sample.
      const [lo, hi, avg] = await Promise.all(["MIN", "MAX", "AVERAGE"].map((method) =>
        fetchChartDisplay(c, temps, hours, { method, windowSec: 3600, preserveWindow: true })));
      const days = [...byDay(avg.get(temps[0].uuid) || [], c.siteTz).keys()];
      return {
        hint: "hourly MIN / MAX / AVERAGE from NF, grouped by site day",
        option: {
          legend,
          tooltip: { trigger: "item", formatter: (x) => `${x.seriesName} · ${x.name}<br>min ${fmt(x.value[3])} · mean ${fmt((x.value[1] + x.value[2]) / 2)} · max ${fmt(x.value[4])}` },
          grid: { left: 50, right: 20, top: 36, bottom: 56 },
          xAxis: { type: "category", data: days, ...axisStyle },
          yAxis: { type: "value", scale: true, name: temps[0] ? dispUnit(temps[0]) : "", ...axisStyle },
          // Candlestick as a range bar: open/close = mean (thin), low/high = min/max.
          series: temps.map((p, i) => {
            const L = byDay(lo.get(p.uuid), c.siteTz), H = byDay(hi.get(p.uuid), c.siteTz), A = byDay(avg.get(p.uuid), c.siteTz);
            const col = palette()[i % palette().length];
            return {
              name: p.name, type: "candlestick", barMaxWidth: 10,
              itemStyle: { color: col, color0: col, borderColor: col, borderColor0: col },
              data: days.map((d) => {
                if (!A.has(d)) return ["-", "-", "-", "-"];
                const a = A.get(d), m = a.reduce((x, y) => x + y, 0) / a.length;
                return [m - 0.15, m + 0.15, Math.min(...(L.get(d) || a)), Math.max(...(H.get(d) || a))];
              }),
            };
          }),
        },
      };
    },
  },
  {
    id: "runtime", title: "Equipment runtime", desc: "Hours on per day for each on/off point (fan, heat, …)",
    ranges: [72, 168], range: 168,
    applies: (c) => c.status.length > 0,
    async build(c, hours) {
      // Hourly AVERAGE of a 0/1 point = fraction of that hour it was on.
      const s = await fetchChartSeries(c, c.status, hours, { windowSec: 3600, preserveWindow: true });
      const days = [...byDay(s.get(c.status[0].uuid) || [], c.siteTz).keys()];
      return {
        hint: "from hourly averages of each Bool point",
        option: {
          legend, tooltip: { trigger: "axis", suffix: " h" },
          grid: { left: 50, right: 20, top: 36, bottom: 56 },
          xAxis: { type: "category", data: days, ...axisStyle },
          yAxis: { type: "value", name: "hours on", max: 24, ...axisStyle },
          series: c.status.map((p) => {
            const D = byDay(s.get(p.uuid), c.siteTz);
            return { name: p.name, type: "bar", barMaxWidth: 18,
              data: days.map((d) => +(D.get(d) || []).reduce((a, b) => a + b, 0).toFixed(2)) };
          }),
        },
      };
    },
  },
  {
    id: "psy", title: "Outdoor air: temp vs humidity", desc: "Outside air temp against humidity, colored by time of day",
    ranges: [24, 168], range: 168,
    applies: (c) => !!rhPair(c.cards),
    async build(c, hours) {
      const [t, rh] = rhPair(c.cards);
      const s = await fetchChartDisplay(c, [t, rh], hours, { windowSec: 900 });
      const rhAt = new Map(s.get(rh.uuid));
      const hour = hourOfDayFormatter(c.siteTz);
      const stamp = new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium", timeStyle: "short", ...(c.siteTz ? { timeZone: chartTimeZone(c.siteTz) } : {}),
      });
      const pts = s.get(t.uuid).filter(([k]) => rhAt.has(k))
        .map(([k, tv]) => [tv, rhAt.get(k), hour(k), k]);
      const lastT = dispVal(t, latestOf(t)), lastRH = dispVal(rh, latestOf(rh));
      const tU = dispUnit(t);
      return {
        hint: `${t.name} × ${rh.name} · ${windowLabel(s.windowSec)} averages · ringed dot = now`,
        option: {
          tooltip: { formatter: (x) => `${stamp.format(x.value[3] ?? Date.now())}<br>${fmt(x.value[0])} ${tU} · ${fmt(x.value[1])} %RH`
              + (/F$/.test(tU) ? `<br>dew point ${fmt(dewPointF(x.value[0], x.value[1]))} °F`
                : /C$/.test(tU) ? `<br>dew point ${fmt(dewPointC(x.value[0], x.value[1]))} °C` : "") },
          grid: { left: 50, right: 70, top: 20, bottom: 40 },
          xAxis: { type: "value", scale: true, name: tU, nameLocation: "center", nameGap: 26, ...axisStyle },
          yAxis: { type: "value", scale: true, name: "%RH", ...axisStyle },
          visualMap: { dimension: 2, min: 0, max: 24, right: 0, top: "middle", itemHeight: 180, calculable: false,
            text: ["24h", "0h"],
            inRange: { color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#3a0ca3"] }, seriesIndex: 0 },
          series: [
            { type: "scatter", data: pts, symbolSize: 6, itemStyle: { opacity: 0.75 } },
            { type: "scatter", data: lastT != null && lastRH != null ? [[lastT, lastRH]] : [], symbolSize: 14,
              itemStyle: { color: cssVar("--text"), borderColor: cssVar("--accent"), borderWidth: 3 }, z: 10 },
          ],
        },
      };
    },
  },
  {
    id: "other", title: "All signals", desc: "All numeric data of the selected equip, one y-axis per unit; on/off points in a lane below",
    ranges: [6, 24, 72, 168], range: 24,
    applies: (c) => signalSets(c).lines.length > 0,
    async build(c, hours) {
      const { lines, lanes, shown, narrowed } = signalSets(c);
      const [s, sb] = await Promise.all([
        fetchChartDisplay(c, lines, hours),
        lanes.length ? fetchChartSeries(c, lanes, hours, { method: "MAX" }) : new Map(),
      ]);
      const data = (p) => (s.get(p.uuid) || sb.get(p.uuid) || []);
      const labelOf = (p) => signalLabel(p, c, [...lines, ...lanes]);
      return {
        hint: `${narrowed ? `showing ${shown}, pick an equip above · ` : ""}${lines.length} numeric signal${lines.length === 1 ? "" : "s"} on ${signalAxes(lines).length} axis(es)`
          + `${lanes.length ? ` · ${lanes.length} on/off in the lane below` : ""} · ${windowLabel(s.windowSec)} averages`,
        option: signalsOption(signalAxes(lines), lanes, data, labelOf),
      };
    },
  },
];

/** Series label of the signals chart: the same human label as the Temperatures chart (p.name), equip-prefixed only across several equips. */
function signalLabel(p, c, points) {
  const base = p.name || p.dis || "";
  if (!base) return "";
  const owners = new Set((points || []).map((x) => pointOwner(x, c)));
  const owner = pointOwner(p, c);
  const twin = (points || []).some((x) => x !== p && (x.name || x.dis) === base && pointOwner(x, c) === owner);
  const named = twin && p.dis && p.dis !== base ? `${base} (${p.dis})` : base;      // equal marker names on one equip: add the point's own name
  return owners.size > 1 && owner ? `${owner} · ${named}` : named;
}
/**
 * The numeric lines and on/off lanes of `c`. A point without any model label is omitted, never named "Sensor N".
 * With no single equip selected the chart shows the first equip (sorted by name) that has signals: `narrowed`, `shown`.
 */
function signalSets(c) {
  const labelled = (p) => !!(p.name || p.dis);
  let lines = (c.numeric || c.cards || []).filter(labelled), lanes = (c.status || []).filter(labelled);
  let shown = "", narrowed = false;
  const owners = new Set([...lines, ...lanes].map((p) => p.equipRef || ""));
  if (!c.scopeEquip && owners.size > 1) {
    const nameOf = (id) => pointOwner({ equipRef: id, tags: [] }, c);
    const first = [...owners].sort((x, y) => nameOf(x).localeCompare(nameOf(y)))[0];
    lines = lines.filter((p) => (p.equipRef || "") === first); lanes = lanes.filter((p) => (p.equipRef || "") === first);
    shown = nameOf(first); narrowed = true;
  }
  return { lines, lanes, shown, narrowed };
}
/** Group points by display unit, in first-seen order: [{ unit, points }] (one y-axis each). */
function signalAxes(points) {
  const by = new Map();
  for (const p of points) {
    const unit = dispUnit(p) || "";
    if (!by.has(unit)) by.set(unit, []);
    by.get(unit).push(p);
  }
  return [...by].map(([unit, pts]) => ({ unit, points: pts }));
}
/**
 * The "Other signals" option: one value axis per unit (axis name = unit; left / right alternating, extra ones offset),
 * and, when there are on/off points, a bottom grid with one step lane per point. `data(p)` -> [[ms, v], ...].
 */
function signalsOption(axes, lanes, data, labelOf) {
  const nLeft = Math.ceil(axes.length / 2), nRight = Math.floor(axes.length / 2), W = 70;
  const laneH = lanes.length ? Math.min(160, 16 * lanes.length + 10) : 0;
  const left = (lanes.length ? 110 : 50) + W * Math.max(0, nLeft - 1), right = 20 + W * nRight;
  const bottom = 56 + (laneH ? laneH + 22 : 0);
  const series = [];
  axes.forEach((ax, i) => ax.points.forEach((p) => series.push({
    name: labelOf(p), type: "line", yAxisIndex: i, showSymbol: false, smooth: false, lineStyle: { width: 1.4 },
    emphasis: { focus: "series" }, data: data(p) })));
  lanes.forEach((p, i) => series.push({
    name: labelOf(p), type: "line", xAxisIndex: 1, yAxisIndex: axes.length, showSymbol: false, step: "end",
    lineStyle: { width: 1.2 }, areaStyle: { opacity: 0.25, origin: i },
    // [t, lane position, raw 0/1]: the tooltip shows the last dimension
    data: data(p).map(([t, v]) => [t, i + (v > 0.5 ? 0.8 : 0), v > 0.5 ? 1 : 0]) }));
  return {
    tooltip, legend: { type: "scroll", top: 0 }, axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [{ left, right, top: 56, bottom }, ...(laneH ? [{ left, right, height: laneH, bottom: 44 }] : [])],
    xAxis: [{ type: "time", gridIndex: 0, ...axisStyle, axisLabel: { show: !laneH } },
      ...(laneH ? [{ type: "time", gridIndex: 1, ...axisStyle }] : [])],
    yAxis: [...axes.map((ax, i) => ({
      type: "value", scale: true, name: ax.unit || "unitless", gridIndex: 0, position: i % 2 ? "right" : "left",
      offset: W * Math.floor(i / 2), ...axisStyle, splitLine: { show: i === 0 },
    })), ...(laneH ? [{
      type: "value", gridIndex: 1, min: 0, max: lanes.length, interval: 1, splitLine: { show: false }, axisTick: { show: false },
      axisLabel: { width: 90, overflow: "truncate", fontSize: 10, formatter: (v) => (lanes[v] ? labelOf(lanes[v]) : "") },
    }] : [])],
    series,
  };
}

const chartDef = (id) => CHARTS.find((c) => c.id === id);
const rangeLabel = (h) => (h < 48 ? `${h}h` : `${h / 24}d`);

/** Format time axes and ordinary axis tooltips in the selected site's timezone. */
function chartOptionSiteTime(option, siteTz, bounds = null) {
  const axes = (Array.isArray(option?.xAxis) ? option.xAxis : [option?.xAxis]).filter((axis) => axis?.type === "time");
  if (!axes.length) return option;
  const timeZone = chartTimeZone(siteTz);
  const tick = new Intl.DateTimeFormat(undefined, { timeZone, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const detail = new Intl.DateTimeFormat(undefined, { timeZone, year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  const stamp = (value, format) => {
    const ms = typeof value === "number" ? value : Date.parse(value);
    return Number.isFinite(ms) ? format.format(ms) : String(value ?? "");
  };
  const pointerLabel = (params) => stamp(params.value, detail);
  for (const axis of axes) {
    axis.axisLabel = { ...axis.axisLabel, formatter: (value) => stamp(value, tick) };
    axis.axisPointer = { ...axis.axisPointer, label: { ...axis.axisPointer?.label, formatter: pointerLabel } };
    if (bounds) { axis.min = bounds.fromMs; axis.max = bounds.toMs; }
  }
  if (option.axisPointer) option.axisPointer = { ...option.axisPointer, label: { ...option.axisPointer.label, formatter: pointerLabel } };
  if (option.tooltip?.trigger === "axis" && option.tooltip.formatter == null) {
    option.tooltip = { ...option.tooltip, formatter: (items) => {
      const rows = Array.isArray(items) ? items : [items], first = rows[0] || {};
      const time = first.axisValue ?? first.value?.[0];
      return [esc(stamp(time, detail)), ...rows.map((row) => {
        const value = Array.isArray(row.value) ? row.value[1] : row.value;
        return `${esc(row.seriesName)}: ${typeof value === "number" ? fmt(value, 2) : esc(value)}`;
      })].join("<br>");
    } };
  }
  return option;
}

/**
 * Draw one catalog chart into `chart` (an echarts instance). Returns the hint text.
 * Late answers from an earlier call on the same instance are dropped.
 */
async function drawChart(chart, def, ctx, hours, opt = {}) {
  const ticket = (chart.__ticket = (chart.__ticket || 0) + 1);
  chart.showLoading({ text: "", color: cssVar("--accent"), maskColor: "rgba(127,127,127,0.12)" });
  try {
    const { option, hint } = await def.build(ctx, hours, opt);
    if (chart.__ticket !== ticket) return null;
    const styled = chartOptionSiteTime(option, ctx.siteTz, opt.range?.resolvedBounds);
    ofddRender(chart, { animationDuration: 300, ...styled }, def.title);
    return hint;
  } finally {
    if (chart.__ticket === ticket) chart.hideLoading();
  }
}
