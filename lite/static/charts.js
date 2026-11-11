// Chart catalog for Open-FDD Lite. Each chart says which points it needs (by tags), which
// ranges it offers and how NF should resample them, so only one small request goes
// out per chart and nothing is fetched for charts that aren't on screen.
//
// NF resamples server side: /api/v1/point/data?...&window=<s>s&method=AVERAGE|MIN|MAX
// returns one value per window (7 days of one sensor: 916 KB raw vs 14 KB hourly).
// Used by the Charts tab (app.js) and the standalone chart.html. Needs nf.js + model.js.

const PALETTE = LT.palette;
const unitLabel = (u) => u || "";
const parseTs = (ts) => Date.parse(ts.replace(/(\.\d{3})\d+/, "$1"));
const fmt = (v, d = 1) => (v == null || isNaN(v) ? "–" : v.toFixed(d));
const latestOf = (p) => p.latest?.double ?? p.latest?.real;

const axisStyle = {
  axisLine: { lineStyle: { color: LT.axisLine } },
  axisLabel: { color: LT.label },
  splitLine: { lineStyle: { color: LT.split } },
};
const tooltip = { trigger: "axis", backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText } };
function chartTimeLabel(value, siteTz) {
  const ms = Number.isFinite(Number(value)) ? Number(value) : Date.parse(value);
  return Number.isFinite(ms) ? new Intl.DateTimeFormat(undefined, { timeZone: chartTimeZone(siteTz), dateStyle: "medium", timeStyle: "short" }).format(new Date(ms)) : String(value ?? "");
}
const timeAxis = (siteTz) => ({ type: "time", ...axisStyle, axisLabel: { formatter: (value) => chartTimeLabel(value, siteTz) } });
const rangeTooltip = (siteTz) => ({ ...tooltip, formatter: (items) => {
  const rows = Array.isArray(items) ? items : [items], first = rows[0] || {};
  const value = first.value, time = first.axisValue ?? (Array.isArray(value) ? value[0] : "");
  return `${chartTimeLabel(time, siteTz)}<br>${rows.map((row) => {
    const v = Array.isArray(row.value) ? row.value[1] : row.value;
    return `${esc(row.seriesName)}: ${typeof v === "number" ? fmt(v, 2) : esc(v)}`;
  }).join("<br>")}`;
} });
const zoom = (bottom = 8) => [{ type: "inside" }, { type: "slider", height: 18, bottom, borderColor: LT.axisLine,
  fillerColor: LT.filler, textStyle: { color: LT.label } }];
const legend = { top: 0, textStyle: { color: LT.legend } };

// ---- which points, by tags (shared with app.js) ------------------------------------
// Sensors first, temps first, then setpoints; ties by label.
const rank = (p) => (has(p, "sensor") ? 0 : 2) + (isTemp(p) ? 0 : 1);

/** Point sets for a site (and optionally one equip): cards/charts, status, weather. */
function pointSets(model, site, equip) {
  const equipIds = model.equips.filter((e) => (e.attrs || {}).siteRef === site).map(idOf);
  const inScope = (p) => p.equipRef && (equip ? p.equipRef === equip : equipIds.includes(p.equipRef));
  const tagged = model.points.filter((p) => p.siteRef === site && has(p, "point"));
  const equipPts = tagged.filter(inScope);
  return {
    cards: equipPts
      .filter((p) => p.kind === "Number" && has(p, "his") && !has(p, "spare") && (has(p, "sensor") || has(p, "sp")))
      .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)),
    status: equipPts.filter((p) => p.kind === "Bool" && !has(p, "spare"))
      .sort((a, b) => a.equipRef.localeCompare(b.equipRef) || a.name.localeCompare(b.name)),
    weather: tagged.filter((p) => has(p, "weather")).sort((a, b) => a.name.localeCompare(b.name)),
  };
}

// Outside air temp + humidity sensors on one equip, found by markers.
function rhPair(points) {
  const t = points.find((p) => has(p, "outside", "air", "temp", "sensor"));
  const rh = points.find((p) => has(p, "outside", "air", "humidity", "sensor") && p.equipRef === t?.equipRef);
  return t && rh ? [t, rh] : null;
}

function dewPointF(tF, rh) {
  const tC = (tF - 32) / 1.8, a = 17.62, b = 243.12;
  const g = Math.log(rh / 100) + (a * tC) / (b + tC);
  return ((b * g) / (a - g)) * 1.8 + 32;
}

// ---- history: resampled by NF, cached briefly ---------------------------------------
const WINDOWS = [60, 300, 600, 900, 1800, 3600, 7200, 14400, 86400];

/** Smallest window giving at most ~`target` values per series over `hours`. */
const rangeHours = (range) => typeof range === "number" ? range
  : range?.preset === "1h" ? 1 : range?.preset === "24h" ? 24 : range?.preset === "1w" ? 168
    : range?.preset === "custom" ? Math.max(1, (range.toMs - range.fromMs) / 3600e3) : 168;
const pickWindow = (hours, target = 360) => WINDOWS.find((w) => (rangeHours(hours) * 3600) / w <= target) || 86400;
const windowLabel = (seconds) => seconds >= 3600 ? `${+(seconds / 3600).toFixed(1)} h` : `${+(seconds / 60).toFixed(1)} min`;

const seriesCache = new Map();  // url -> { at, promise }
const CACHE_MS = 60e3;
// Leave room for fixed query parameters and request headers under NF's ~8 KB front-door limit.
const HISTORY_URL_BUDGET = 6000;
const HISTORY_UUID_BATCH = 40;
/** @typedef {Map<any, any> & {windowSec: number}} HistorySeriesMap */

// A chart range is stored as absolute instants in the page URL. Date-time inputs are
// formatted and parsed in the site's IANA timezone, not the browser's local timezone.
const RANGE_PRESETS = Object.freeze({ "1h": 1, "24h": 24, "1w": 168 });
const validChartTimeZone = (tz) => {
  try { new Intl.DateTimeFormat("en-US", { timeZone: tz || "UTC" }); return tz || "UTC"; }
  catch { return "UTC"; }
};
function chartTimeZone(siteTz) { return validChartTimeZone(siteTz); }
function getChartRangeState(key) {
  const q = new URLSearchParams(typeof location === "undefined" ? "" : location.search);
  const preset = q.get(`range.${key}`) || "all";
  if (preset === "custom") {
    const fromRaw = q.get(`from.${key}`), toRaw = q.get(`to.${key}`), fromMs = Number(fromRaw), toMs = Number(toRaw);
    if (fromRaw && toRaw && Number.isSafeInteger(fromMs) && Number.isSafeInteger(toMs)
      && Number.isFinite(new Date(fromMs).getTime()) && Number.isFinite(new Date(toMs).getTime()) && fromMs < toMs)
      return { preset, fromMs, toMs };
    return { preset: "all" };
  }
  return { preset: Object.hasOwn(RANGE_PRESETS, preset) || preset === "all" ? preset : "all" };
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
  const hours = RANGE_PRESETS[state?.preset] || 24;
  return { fromMs: nowMs - hours * 3600e3, toMs: nowMs };
}

const dateTimeInputValue = (ms, siteTz) => {
  const tz = chartTimeZone(siteTz);
  const vals = {};
  for (const x of new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(new Date(ms)))
    if (x.type !== "literal") vals[x.type] = Number(x.value);
  const p = { y: vals.year, m: vals.month, d: vals.day, h: vals.hour % 24, mi: vals.minute };
  return `${String(p.y).padStart(4, "0")}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")}T${String(p.h).padStart(2, "0")}:${String(p.mi).padStart(2, "0")}`;
};
const dateTimeInputMs = (value, siteTz) => {
  const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)$/.exec(value || "");
  if (!m) return NaN;
  const tz = chartTimeZone(siteTz), [y, mo, d, h, mi] = m.slice(1).map(Number);
  const wall = Date.UTC(y, mo - 1, d, h, mi), fields = (t) => {
    const x = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(new Date(t));
    const o = {}; for (const a of x) if (a.type !== "literal") o[a.type] = Number(a.value);
    return Date.UTC(o.year, o.month - 1, o.day, o.hour % 24, o.minute);
  };
  let t = wall; t = wall - (fields(t) - t); t = wall - (fields(t) - t);
  return fields(t) === wall ? t : NaN;
};

/** Mount shared range buttons and site-timezone custom fields. */
/** @param {AnyEl} container @param {{key?: string, state?: any, siteTz?: string, onChange?: (state: any) => void}} opts */
function renderRangeControl(container, opts = {}) {
  const { key = "", state = getChartRangeState(key), siteTz = "UTC", onChange } = opts;
  const tz = chartTimeZone(siteTz), now = Date.now();
  const validCustom = state.preset === "custom" && Number.isFinite(state.fromMs) && Number.isFinite(state.toMs) && state.fromMs < state.toMs;
  const bounds = validCustom ? state : resolveChartRange(state, { nowMs: now, oldestMs: now - 24 * 3600e3 });
  container.innerHTML = `<div class="chart-range"><div class="seg chart-range-presets">${[["1h", "1 h"], ["24h", "24 h"], ["1w", "1 week"], ["all", "All"]].map(([v, label]) =>
    `<button type="button" data-range="${v}" class="${state.preset === v ? "on" : ""}">${label}</button>`).join("")}</div>
    <label>From <input type="datetime-local" data-range-from step="60" value="${dateTimeInputValue(bounds.fromMs, tz)}"></label>
    <label>To <input type="datetime-local" data-range-to step="60" value="${dateTimeInputValue(bounds.toMs, tz)}"></label>
    <span class="sub">${esc(tz)}</span><button type="button" data-range-apply>Apply</button></div>`;
  const applyState = (next, push = true) => {
    setChartRangeState(key, next, { push });
    onChange?.(next);
  };
  container.onclick = (/** @type {MouseEvent} */ event) => {
    const eventTarget = /** @type {HTMLElement} */ (event.target);
    const target = /** @type {HTMLElement | null} */ (eventTarget.closest("[data-range]"));
    if (target) applyState({ preset: target.dataset.range });
    else if (eventTarget.closest("[data-range-apply]")) {
      const fromMs = dateTimeInputMs(/** @type {HTMLInputElement} */ (container.querySelector("[data-range-from]")).value, tz);
      const toInput = /** @type {HTMLInputElement} */ (container.querySelector("[data-range-to]"));
      const toMs = dateTimeInputMs(toInput.value, tz);
      if (Number.isFinite(fromMs) && fromMs < toMs) applyState({ preset: "custom", fromMs, toMs });
      else { toInput.setCustomValidity("Enter valid site-local times with end after start"); toInput.reportValidity(); }
    }
  };
  container.oninput = (/** @type {Event} */ event) => /** @type {HTMLInputElement} */ (event.target).setCustomValidity?.("");
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
/** @returns {Promise<HistorySeriesMap>} */
async function fetchSeries(list, hours, opts = {}) {
  const method = opts.method || "AVERAGE";
  const windowSec = opts.windowSec ?? (typeof hours === "number" ? pickWindow(hours) : null);
  if (typeof hours === "object" && hours) {
    const result = await fetchRange(list, hours, { ...opts, method, ...(windowSec == null ? {} : { windowSec }) });
    const series = /** @type {HistorySeriesMap} */ (result.series);
    series.windowSec = result.windowSec;
    return series;
  }
  const endMs = opts.endMs ?? null, fromMs = opts.fromMs ?? null;
  const effectiveWindowSec = windowSec || pickWindow(hours);
  const out = /** @type {HistorySeriesMap} */ (new Map(list.map((p) => [p.uuid, []])));
  out.windowSec = effectiveWindowSec;
  if (!list.length) return out;
  // Round the end to the window so repeat views share a cache entry. endMs (window-aligned) lets a
  // caller walk a long span back in chunks (rcx.js alignedFine).
  const end = endMs != null ? endMs : Math.ceil(Date.now() / (effectiveWindowSec * 1e3)) * effectiveWindowSec * 1e3;
  const from = new Date(fromMs == null ? end - hours * 3600e3 : fromMs).toISOString(), to = new Date(end).toISOString();
  const chunks = historyChunks(list, from, to, effectiveWindowSec, method);
  // A small fixed concurrency bounds load while keeping 709-sensor views practical.
  for (let base = 0; base < chunks.length; base += 4) {
    const responses = await Promise.all(chunks.slice(base, base + 4).map((chunk) => {
      const url = historyUrl(chunk, from, to, effectiveWindowSec, method);
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
    for (const p of chunks.slice(base, base + 4).flat()) oldestCache.set(p.uuid, { at: now, value: null });
    const bodies = await Promise.all(chunks.slice(base, base + 4).map((c) => api(oldestUrl(c))));
    for (const body of bodies) {
      const rows = Array.isArray(body.data) ? body.data : body.data?.data || [];
      for (const row of rows) {
        const ts = row?.values?.[0]?.ts;
        oldestCache.set(row.uuid, { at: now, value: ts ? parseTs(ts) : null });
      }
    }
    for (const p of chunks.slice(base, base + 4).flat()) if (!oldestCache.has(p.uuid)) oldestCache.set(p.uuid, { at: now, value: null });
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
  siteTz = "UTC", endMs = null, preserveWindow = false, target = 360 } = {}) {
  const nowMs = endMs ?? Date.now();
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
  // Resampling buckets are aligned to the Unix epoch. NF applies `from`/`to` to input samples;
  // clamp display coordinates so partial edge buckets remain visible inside the chosen interval.
  if (state?.preset === "custom") for (const [uuid, values] of series) {
    series.set(uuid, values.filter(([t]) => t < bounds.toMs).map(([t, v]) => [Math.max(t, bounds.fromMs), v]));
  }
  return { series, windowSec: effectiveWindowSec, fromMs: bounds.fromMs, toMs: bounds.toMs,
    timeZone: chartTimeZone(siteTz) };
}

function chartTimeParts(t, siteTz) {
  if (!siteTz) {
    const d = new Date(t);
    return { y: d.getFullYear(), m: d.getMonth() + 1, d: d.getDate(), h: d.getHours(), mi: d.getMinutes() };
  }
  const vals = {};
  for (const x of new Intl.DateTimeFormat("en-US", { timeZone: chartTimeZone(siteTz), hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(new Date(t)))
    if (x.type !== "literal") vals[x.type] = Number(x.value);
  return { y: vals.year, m: vals.month, d: vals.day, h: vals.hour % 24, mi: vals.minute };
}
const localDay = (t, siteTz) => {
  if (!siteTz) return new Date(t).toLocaleDateString(undefined, { weekday: "short", month: "numeric", day: "numeric" });
  return new Intl.DateTimeFormat(undefined, { timeZone: chartTimeZone(siteTz), weekday: "short", month: "numeric", day: "numeric" }).format(new Date(t));
};

/** Group [[ms, v]] by local calendar day -> Map(day -> values[]), days in time order. */
function byDay(arr, siteTz) {
  const m = new Map();
  for (const [t, v] of arr) {
    const k = localDay(t, siteTz);
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
// ctx = { cards, status, weather } from pointSets(). Each entry:
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
      const s = await fetchSeries(temps, hours);
      return {
        hint: `${temps.length} points · ${windowLabel(s.windowSec)} averages`,
        option: {
          color: PALETTE, tooltip: rangeTooltip(c.siteTz), legend, grid: { left: 50, right: 20, top: 36, bottom: 60 },
          xAxis: timeAxis(c.siteTz),
          yAxis: { type: "value", scale: true, name: unitLabel(temps[0]?.units), nameTextStyle: { color: LT.label }, ...axisStyle },
          dataZoom: zoom(),
          series: temps.map((p) => lineSeries(p, s.get(p.uuid))),
        },
      };
    },
  },
  {
    id: "weather", title: "Weather vs outside air", desc: "Weather-service values next to the equip's outside air sensors",
    ranges: [24, 48, 168], range: 48,
    applies: (c) => c.weather.length > 0,
    async build(c, hours) {
      const pair = rhPair(c.cards) || [];
      const s = await fetchSeries([...pair, ...c.weather], hours);
      const line = (p, axis, dashed) => ({
        name: p.name, type: "line", yAxisIndex: axis, data: s.get(p.uuid), showSymbol: dashed, symbolSize: 4,
        step: dashed ? "end" : false, smooth: !dashed, lineStyle: { width: dashed ? 2 : 1.4, type: dashed ? "dashed" : "solid" },
      });
      return {
        hint: "dashed = weather service, solid = equipment sensors",
        option: {
          color: [PALETTE[1], PALETTE[6], PALETTE[2], PALETTE[0], PALETTE[3], PALETTE[4]], tooltip: rangeTooltip(c.siteTz), legend,
          grid: { left: 50, right: 50, top: 36, bottom: 60 },
          xAxis: timeAxis(c.siteTz),
          yAxis: [
            { type: "value", scale: true, name: "°F", nameTextStyle: { color: LT.label }, ...axisStyle },
            { type: "value", scale: true, name: "%RH", position: "right", nameTextStyle: { color: LT.label }, ...axisStyle, splitLine: { show: false } },
          ],
          dataZoom: zoom(),
          series: [...pair.map((p) => line(p, isRH(p) ? 1 : 0, false)), ...c.weather.map((p) => line(p, isRH(p) ? 1 : 0, true))],
        },
      };
    },
  },
  {
    id: "heatmap", title: "Hour-of-day heatmap", desc: "One sensor's hourly average, day by day",
    ranges: [72, 168], range: 168,
    applies: (c) => c.cards.length > 0,
    pick: (c) => c.cards,
    defaultPick: (c) => (c.cards.find((p) => has(p, "discharge", "air", "temp")) || c.cards[0])?.uuid,
    async build(c, hours, opt) {
      const p = c.cards.find((x) => x.uuid === opt.point) || c.cards[0];
      const history = await fetchSeries([p], hours, { windowSec: 3600, preserveWindow: true });
      const arr = history.get(p.uuid);
      const days = [];
      const data = arr.map(([t, v]) => {
        const day = localDay(t, c.siteTz);
        if (!days.includes(day)) days.push(day);
        return [chartTimeParts(t, c.siteTz).h, days.indexOf(day), +v.toFixed(2)];
      });
      const vals = data.map((d) => d[2]);
      return {
        hint: `${p.dis} · ${windowLabel(history.windowSec)} averages, site time`,
        option: {
          tooltip: { position: "top", backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText },
            formatter: (x) => `${days[x.value[1]]} ${x.value[0]}:00<br><b>${x.value[2]} ${unitLabel(p.units)}</b>` },
          grid: { left: 90, right: 20, top: 10, bottom: 80 },
          xAxis: { type: "category", data: [...Array(24).keys()].map(String), ...axisStyle },
          yAxis: { type: "category", data: days, ...axisStyle },
          visualMap: {
            min: Math.min(...vals), max: Math.max(...vals), calculable: true, orient: "horizontal", left: "center", bottom: 0,
            itemHeight: 220, textStyle: { color: LT.label },
            inRange: { color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#f94144"] },
          },
          series: [{ type: "heatmap", data, itemStyle: { borderColor: LT.panel, borderWidth: 2, borderRadius: 3 } }],
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
        fetchSeries(temps, hours, { method, windowSec: 3600, preserveWindow: true })));
      const days = [...byDay(avg.get(temps[0].uuid) || [], c.siteTz).keys()];
      return {
        hint: `${windowLabel(avg.windowSec)} MIN / MAX / AVERAGE from NF, grouped by site day`,
        option: {
          color: PALETTE, legend,
          tooltip: { trigger: "item", backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText },
            formatter: (x) => `${x.seriesName} · ${x.name}<br>min ${fmt(x.value[3])} · mean ${fmt((x.value[1] + x.value[2]) / 2)} · max ${fmt(x.value[4])}` },
          grid: { left: 50, right: 20, top: 36, bottom: 30 },
          xAxis: { type: "category", data: days, ...axisStyle },
          yAxis: { type: "value", scale: true, name: unitLabel(temps[0]?.units), nameTextStyle: { color: LT.label }, ...axisStyle },
          // Candlestick as a range bar: open/close = mean (thin), low/high = min/max.
          series: temps.map((p, i) => {
            const L = byDay(lo.get(p.uuid), c.siteTz), H = byDay(hi.get(p.uuid), c.siteTz), A = byDay(avg.get(p.uuid), c.siteTz);
            const col = PALETTE[i % PALETTE.length];
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
      const s = await fetchSeries(c.status, hours, { windowSec: 3600, preserveWindow: true });
      const days = [...byDay(s.get(c.status[0].uuid) || [], c.siteTz).keys()];
      return {
        hint: `from ${windowLabel(s.windowSec)} averages of each Bool point`,
        option: {
          color: PALETTE, legend, tooltip: { ...tooltip, valueFormatter: (v) => `${fmt(v)} h` },
          grid: { left: 50, right: 20, top: 36, bottom: 30 },
          xAxis: { type: "category", data: days, ...axisStyle },
          yAxis: { type: "value", name: "hours on", max: 24, nameTextStyle: { color: LT.label }, ...axisStyle },
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
      const s = await fetchSeries([t, rh], hours, { windowSec: 900 });
      const rhAt = new Map(s.get(rh.uuid));
      const pts = s.get(t.uuid).filter(([k]) => rhAt.has(k))
        .map(([k, tv]) => { const parts = chartTimeParts(k, c.siteTz); return [tv, rhAt.get(k), parts.h + parts.mi / 60, k]; });
      const lastT = latestOf(t), lastRH = latestOf(rh);
      return {
        hint: `${t.name} × ${rh.name} · ${windowLabel(s.windowSec)} averages · white = now`,
        option: {
          tooltip: { backgroundColor: LT.tipBg, borderColor: LT.axisLine, textStyle: { color: LT.tipText },
            formatter: (x) => `${new Date(x.value[3] ?? Date.now()).toLocaleString(undefined, c.siteTz ? { timeZone: chartTimeZone(c.siteTz) } : {})}<br>${fmt(x.value[0])} ${unitLabel(t.units)} · ${fmt(x.value[1])} %RH`
              + (/F$/.test(t.units) ? `<br>dew point ${fmt(dewPointF(x.value[0], x.value[1]))} °F` : "") },
          grid: { left: 50, right: 70, top: 20, bottom: 40 },
          xAxis: { type: "value", scale: true, name: unitLabel(t.units), nameLocation: "center", nameGap: 26, nameTextStyle: { color: LT.label }, ...axisStyle },
          yAxis: { type: "value", scale: true, name: "%RH", nameTextStyle: { color: LT.label }, ...axisStyle },
          visualMap: { dimension: 2, min: 0, max: 24, right: 0, top: "middle", itemHeight: 180, calculable: false,
            text: ["24h", "0h"], textStyle: { color: LT.label },
            inRange: { color: ["#3a0ca3", "#4361ee", "#4cc9f0", "#f9c74f", "#f8961e", "#3a0ca3"] }, seriesIndex: 0 },
          series: [
            { type: "scatter", data: pts, symbolSize: 6, itemStyle: { opacity: 0.75 } },
            { type: "scatter", data: lastT != null && lastRH != null ? [[lastT, lastRH]] : [], symbolSize: 14,
              itemStyle: { color: "#ffffff", borderColor: "#4cc9f0", borderWidth: 3 }, z: 10 },
          ],
        },
      };
    },
  },
  {
    id: "other", title: "Other signals", desc: "Non-temperature, non-humidity sensors (pressure, position, …)",
    ranges: [6, 24, 72, 168], range: 24,
    applies: (c) => c.cards.some((p) => !isTemp(p) && !isRH(p)),
    async build(c, hours) {
      const others = c.cards.filter((p) => !isTemp(p) && !isRH(p)).slice(0, 2);
      const s = await fetchSeries(others, hours);
      return {
        hint: `${windowLabel(s.windowSec)} averages`,
        option: {
          color: PALETTE.slice(3), tooltip: rangeTooltip(c.siteTz), legend, grid: { left: 50, right: 50, top: 36, bottom: 60 },
          xAxis: timeAxis(c.siteTz),
          yAxis: others.map((p, i) => ({
            type: "value", scale: true, name: unitLabel(p.units), position: i ? "right" : "left",
            nameTextStyle: { color: LT.label }, ...axisStyle, splitLine: { show: !i, lineStyle: { color: LT.split } },
          })),
          dataZoom: zoom(),
          series: others.map((p, i) => lineSeries(p, s.get(p.uuid), { yAxisIndex: i, smooth: false, areaStyle: { opacity: 0.08 } })),
        },
      };
    },
  },
];

const chartDef = (id) => CHARTS.find((c) => c.id === id);
const rangeLabel = (h) => (h < 48 ? `${h}h` : `${h / 24}d`);

/**
 * Draw one catalog chart into `chart` (an echarts instance). Returns the hint text.
 * Late answers from an earlier call on the same instance are dropped.
 */
async function drawChart(chart, def, ctx, hours, opt = {}) {
  const ticket = (chart.__ticket = (chart.__ticket || 0) + 1);
  chart.showLoading({ text: "", color: LT.palette[0], maskColor: LT.dark ? "rgba(11,16,32,0.35)" : "rgba(255,255,255,0.5)" });
  try {
    const { option, hint } = await def.build(ctx, hours, opt);
    if (chart.__ticket !== ticket) return null;
    chart.setOption({ animationDuration: 300, ...option }, true);
    return hint;
  } finally {
    if (chart.__ticket === ticket) chart.hideLoading();
  }
}
