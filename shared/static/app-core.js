// Open-FDD dashboard shell, shared by both editions (source: shared/static/app-core.js, copied into nf-app/ and lite/ by
// scripts/nf/sync_shared.py). It owns what Full and Lite have in common: the top bar (site picker, live pill, theme), the
// per-tab equip pickers, the tab router, Overview, Charts, Points, BACnet Server and Model & RDF, and the live loop.
// Everything renders from `model` (model.js: Haystack SITE / EQUIPMENT / DEVICE records + point markers and refs), so the
// same page works on any NF whose points are tagged. The edition's own app.js loads after this file, registers the tabs
// only that edition has (Full: FDD, RCx, Export, ...) through the ofdd* registries below, then calls main().
//
// Needs (classic scripts, in this order): nf.js, model.js, theme.js, charts.js, then this file, then app.js.

const LIVE_MS = 15000;            // polling while the push stream is down
const RESYNC_MS = 5 * 60e3;       // full refresh while it is up (untagged points, BACnet tab)
const CHART_REFRESH_MS = 5 * 60e3;

// ---- edition hooks: the edition's app.js fills these before it calls main() ---------------------
/** Tabs only one edition has: tab name -> render function (may return a promise). */
const ofddTabs = /** @type {Record<string, () => any>} */ ({});
/** Tabs that get an equip picker at the top (the top bar has only the site). Editions add their own. */
const ofddEquipScoped = new Set(["overview", "charts", "points"]);
/** Functions run once by wireControls() (the edition's own buttons and inputs). */
const ofddWire = /** @type {Array<() => void>} */ ([]);
/** Functions run after a theme switch, once the shared tabs have redrawn. */
const ofddOnTheme = /** @type {Array<() => void>} */ ([]);

/** @param {string} id @returns {AnyEl} */
const $ = (id) => /** @type {AnyEl} */ (document.getElementById(id));
const fmtPoint = (p) => {
  const v = latestOf(p);
  if (v == null) return "–";
  return p.kind === "Bool" ? (v ? "on" : "off") : `${fmt(dispVal(p, v), 2)} ${unitLabel(dispUnit(p))}`.trim();
};

let model = null;                        // loadModel() result
const scope = { site: "", equip: "" };   // equip "" = every equip on the site; WEATHER_SCOPE = the weather points
let points = [];          // numeric sensor/sp points on the scoped equips (cards + charts)
let variables = [];       // `weather` points on the site
let statusPts = [];       // kind Bool points on the scoped equips (status chips)
let sparkHist = new Map();  // uuid -> [[ms, value], ...] for the sparklines (+ live samples)
let sparkRangeRead = 0;
let sparkCustomEnd = Infinity;
const chartSel = { id: "", hours: 0, point: "" };  // Charts tab: the one chart on screen
let selectedPoint = null; // Points tab
let pointHistoryRead = 0;
let activeTab = "overview";
// Chart instances live in theme.js (one per element, rebuilt on a theme switch).
const mk = (id) => ofddChart($(id));

// ---- scope: which points each tab shows, decided by tags --------------------------
const OVERVIEW_EQUIP_KEY = "openfdd.overview.equip";
let overviewSelection = { site: "", equipId: "", mode: "auto", reason: "" };
const deliberateAllTabs = new Set();

function loadOverviewEquipMap() {
  try {
    if (typeof localStorage === "undefined") return {};
    const raw = JSON.parse(localStorage.getItem(OVERVIEW_EQUIP_KEY) || "{}");
    return raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  } catch { return {}; }
}
function saveOverviewEquipForSite(site, equipId) {
  try {
    if (typeof localStorage === "undefined" || !site) return;
    const map = loadOverviewEquipMap();
    if (equipId) map[site] = equipId;
    else delete map[site];
    localStorage.setItem(OVERVIEW_EQUIP_KEY, JSON.stringify(map));
  } catch { /* private mode */ }
}

const siteEquips = () => model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site);
const siteEquipIds = () => siteEquips().map(idOf);
const taggedOnSite = () => model.points.filter((p) => p.siteRef === scope.site && has(p, "point"));
const equipLabelOf = (e) => (e.attrs || {}).dis || e.name;
const eligibleSingleEquips = (m, site) => sortOverviewEquips((m?.equips || []).filter((e) => (e.attrs || {}).siteRef === site && isOverviewEligibleEquip(e)));

/** @param {any} m @param {string} site @param {{ forceAuto?: boolean, nowMs?: number }} [opts] */
function resolveOverviewSelection(m, site, { forceAuto = false, nowMs } = {}) {
  const equips = eligibleSingleEquips(m, site);
  if (!equips.length) {
    return { site, equipId: "", mode: "empty", reason: "No eligible equipment modeled on this site." };
  }
  const validIds = new Set(equips.map(idOf));
  if (!forceAuto) {
    const saved = loadOverviewEquipMap()[site];
    if (saved && validIds.has(saved)) {
      return { site, equipId: saved, mode: "manual", reason: "Manual selection (saved for this site)." };
    }
    if (overviewSelection.site === site && overviewSelection.equipId && validIds.has(overviewSelection.equipId)) {
      return overviewSelection;
    }
  }
  const auto = autoSelectOverviewEquip(m, site, nowMs === undefined ? {} : { nowMs });
  return { site, equipId: auto.equipId, mode: "auto", reason: auto.reason };
}

const overviewEquipId = () => (overviewSelection.site === scope.site ? overviewSelection.equipId : "");
const exportEquipId = () => {
  const singleIds = new Set(eligibleSingleEquips(model, scope.site).map(idOf));
  if (scope.equip && scope.equip !== WEATHER_SCOPE && singleIds.has(scope.equip)) return scope.equip;
  return overviewEquipId();
};
const activeEquipScope = () => {
  if (activeTab === "overview") return overviewEquipId();
  if (activeTab === "export") return exportEquipId();
  return scope.equip;
};
const scopedSets = () => pointSets(model, scope.site, activeEquipScope());

/**
 * Entries of the equip pickers for one site: every equip, plus "Weather" as its own entry when the site has weather
 * points (weather is a category of its own, never an equip's sensors).
 * @returns {{value: string, label: string}[]}
 */
function equipChoices(m, site) {
  const equips = m.equips.filter((e) => (e.attrs || {}).siteRef === site);
  const weather = m.points.some((p) => p.siteRef === site && has(p, "point") && isWeatherPoint(p));
  return [{ value: "", label: `all equips (${equips.length})` },
    ...equips.map((e) => ({ value: idOf(e), label: equipLabelOf(e) })),
    ...(weather ? [{ value: WEATHER_SCOPE, label: WEATHER_LABEL }] : [])];
}

/** One equip picker at the top of every tab that needs one (the top bar only has the site). */
function ensureScopeBars() {
  for (const name of ofddEquipScoped) {
    const tab = document.getElementById(`tab-${name}`);
    if (!tab || tab.querySelector(".scopebar")) continue;
    const bar = document.createElement("div"), label = document.createElement("label"), pick = document.createElement("select");
    bar.className = "scopebar"; label.className = "scope"; pick.className = "equip-pick";
    pick.setAttribute("aria-label", "equip");
    label.append("equip ", pick); bar.append(label);
    if (name === "overview") {
      const autoBtn = document.createElement("button");
      autoBtn.type = "button";
      autoBtn.className = "btn overview-auto-btn";
      autoBtn.id = "overviewAutoBtn";
      autoBtn.textContent = "Auto";
      autoBtn.title = "Return to automatic temperature-based equipment selection";
      const reason = document.createElement("span");
      reason.className = "overview-scope-reason";
      reason.id = "overviewScopeReason";
      bar.append(autoBtn, reason);
    }
    tab.prepend(bar);
  }
}

function fillPickers(opts = {}) {
  $("sitePick").innerHTML = model.sites.map((s) => `<option value="${esc(idOf(s))}">${esc(s.name)}</option>`).join("");
  $("sitePick").value = scope.site;
  ensureScopeBars();
  overviewSelection = resolveOverviewSelection(model, scope.site, opts);
  const choices = equipChoices(model, scope.site);
  if (!choices.some((c) => c.value === scope.equip)) scope.equip = "";
  const singleEquips = eligibleSingleEquips(model, scope.site);
  const singleHtml = singleEquips.length
    ? singleEquips.map((e) => `<option value="${esc(idOf(e))}">${esc(equipLabelOf(e))}</option>`).join("")
    : `<option value="">no equipment</option>`;
  const multiHtml = choices.map((c) => `<option value="${esc(c.value)}">${esc(c.label)}</option>`).join("");
  document.querySelectorAll(".equip-pick").forEach((/** @type {AnyEl} */ sel) => {
    const tabId = sel.closest(".tab")?.id?.replace(/^tab-/, "") || "";
    if (tabId === "overview") {
      sel.innerHTML = singleHtml;
      sel.value = overviewSelection.equipId || "";
    } else if (tabId === "export") {
      sel.innerHTML = singleHtml;
      sel.value = exportEquipId() || "";
    } else {
      sel.innerHTML = multiHtml;
      sel.value = scope.equip;
    }
  });
  const autoBtn = $("overviewAutoBtn");
  if (autoBtn) autoBtn.disabled = overviewSelection.mode !== "manual";
  const reasonEl = $("overviewScopeReason");
  if (reasonEl) reasonEl.textContent = overviewSelection.reason || "";
}

async function applyScope() {
  ({ cards: points, weather: variables, status: statusPts } = scopedSets());
  rdf = modelToTurtle(model, `urn:nf:${location.host}:`);
  const tagged = taggedOnSite();
  const site = model.sites.find((s) => idOf(s) === scope.site);
  $("sub").textContent = `${site?.name ?? scope.site} · ${siteEquipIds().length} equips · ${tagged.length} tagged points · ${location.host}`;
  $("nPoints").textContent = tagged.length;
  renderSummary();
  renderCards();
  renderChips();
  renderOverviewIo();
  renderTab(activeTab);
  startStream();
  setLive(true, `live · ${new Date().toLocaleTimeString()}`);
}

// ---- sparkline history ---------------------------------------------------------------
const siteTimeZone = () => {
  const site = model?.sites?.find((s) => idOf(s) === scope.site) || (model?.sites?.length === 1 ? model.sites[0] : null);
  return resolveSiteTimeZone(site).zone;
};

async function refreshOverviewSparks() {
  const read = ++sparkRangeRead;
  const state = getChartRangeState("overview");
  const siteTz = siteTimeZone();
  const status = $("overviewRangeStatus");
  renderRangeControl($("overviewRangeControl"), { key: "overview", state, siteTz, onChange: refreshOverviewSparks });
  status.textContent = "Loading overview history…";
  try {
    const { series, toMs } = await fetchRange(points, state, { target: 72, minWindowSec: 300, siteTz });
    if (read !== sparkRangeRead) return;
    sparkHist = series;
    sparkCustomEnd = state.preset === "custom" ? toMs : Infinity;
    status.textContent = "";
    if (activeTab === "overview") points.forEach((_p, i) => updateCard(i, false));
  } catch (e) {
    if (read === sparkRangeRead) status.textContent = `Overview history unavailable: ${e.message}`;
  }
}

/** A live sample onto a sparkline (the array is capped: a long-lived tab must not grow without bound). */
function pushSpark(uuid, ms, value) {
  if (!sparkHist.has(uuid)) sparkHist.set(uuid, []);
  const arr = sparkHist.get(uuid);
  arr.push([ms, value]);
  if (arr.length > 2000) arr.splice(0, arr.length - 2000);
}

const since = (arr, hours) => {
  const cut = Date.now() - hours * 3600e3;
  return arr.filter(([t]) => t >= cut);
};

// ---- Overview tab ---------------------------------------------------------------------
function renderSummary() {
  const tagged = taggedOnSite();
  const onSite = model.points.filter((p) => p.siteRef === scope.site);
  const stat = (n, label) => `<div class="stat"><b>${n}</b><span>${label}</span></div>`;
  $("summary").innerHTML = [
    stat(siteEquipIds().length, "equips"),
    stat(model.devices.filter((d) => (d.attrs || {}).siteRef === scope.site).length, "devices"),
    stat(tagged.length, "tagged points"),
    stat(onSite.length - tagged.length, "untagged objects"),
    stat(points.length, "charted sensors / sp"),
    stat(new Set(variables.map((p) => p.weatherStationRef)).size, "weather stations"),
  ].join("");
}

function renderCards() {
  const sets = scopedSets();
  const ctx = { equipNames: sets.equipNames };
  const eq = activeEquipScope();
  $("cards").innerHTML = points.map((p, i) => `
    <div class="card" id="card-${i}" title="${esc(p.tags.join(" "))}">
      <div class="name">${esc(p.name)}</div>
      <div class="desc">${esc(eq ? p.dis : `${pointOwner(p, ctx)} · ${p.dis}`)}</div>
      <div class="val"><span id="val-${i}">–</span><small>${esc(unitLabel(dispUnit(p)))}</small></div>
      <div class="delta" id="delta-${i}">&nbsp;</div>
      <div class="spark" id="spark-${i}"></div>
    </div>`).join("");
  points.forEach((p, i) => updateCard(i, false));
}

function updateCard(i, flash) {
  const p = points[i];
  const v = dispVal(p, latestOf(p));
  const shown = dispSeries(p, (sparkHist.get(p.uuid) || []).filter(([t]) => t <= sparkCustomEnd));
  $(`val-${i}`).textContent = fmt(v, isRH(p) || isTemp(p) ? 1 : 2);
  const hour = since(shown, 1);
  if (hour.length > 1 && v != null) {
    const d = v - hour[0][1];
    const arrow = Math.abs(d) < 0.05 ? "→" : d > 0 ? "▲" : "▼";
    $(`delta-${i}`).textContent = `${arrow} ${d >= 0 ? "+" : ""}${fmt(d, 2)} in the last hour`;
  } else {
    $(`delta-${i}`).textContent = "";
  }
  const pal = palette();
  const color = pal[i % pal.length];
  mk(`spark-${i}`).setOption({
    animation: false, backgroundColor: "transparent",
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: "time", show: false }, yAxis: { type: "value", show: false, scale: true },
    series: [{
      type: "line", data: shown, showSymbol: false, smooth: true,
      lineStyle: { width: 1.5, color },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: color + "66" }, { offset: 1, color: color + "00" }]) },
    }],
  });
  if (flash) {
    const el = $(`card-${i}`);
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  }
}

function renderChips() {
  $("chips").innerHTML = statusPts.length ? statusPts.map((p) => {
    const on = !!latestOf(p);
    return `<span class="chip ${on ? "on" : ""}" title="${esc(p.dis)}&#10;${esc(p.tags.join(" "))}">
      <span class="led"></span>${esc(p.name)}<span class="state">${on ? "on" : "off"}</span></span>`;
  }).join("") : `<span class="sub">No Bool points tagged on this equipment.</span>`;
}

function renderOverviewIo() {
  const tbody = $("overviewIoRows");
  const hint = $("overviewIoHint");
  if (!tbody) return;
  const eqId = overviewEquipId();
  if (!eqId) {
    if (hint) hint.textContent = "no equipment modeled on this site";
    tbody.innerHTML = `<tr><td colspan="7" class="sub">No modeled equipment is available on this site.</td></tr>`;
    return;
  }
  const inv = scopedEquipmentInventory(model, scope.site, eqId);
  const siteTz = siteTimeZone();
  const fmtTs = (ts) => {
    if (!ts) return "–";
    const ms = parseTs(ts);
    return Number.isFinite(ms) ? new Date(ms).toLocaleString(undefined, { timeZone: siteTz }) : ts;
  };
  const label = inv.equip ? equipLabelOf(inv.equip) : eqId;
  if (hint) {
    const gapNote = inv.gaps.length ? ` · ${inv.gaps.length} point${inv.gaps.length === 1 ? "" : "s"} skipped (missing siteRef)` : "";
    hint.textContent = `${label} · ${inv.ioPoints.length} I/O point${inv.ioPoints.length === 1 ? "" : "s"}${inv.fddPoints.length ? ` · ${inv.fddPoints.length} FDD output${inv.fddPoints.length === 1 ? "" : "s"} excluded` : ""}${gapNote}`;
  }
  tbody.innerHTML = inv.ioPoints.length ? inv.ioPoints.map((row) => `<tr>
    <td>${esc(row.label)}<div class="sub mono">${esc(row.uuid)}</div></td>
    <td>${esc(row.roleLabel)}</td>
    <td class="num">${esc(row.formattedValue)}</td>
    <td>${esc(row.unit || "–")}</td>
    <td class="sub">${esc(fmtTs(row.updatedTs))}</td>
    <td class="sub">${row.historyAvailable ? "trended" : "current-only"}</td>
    <td><span class="io-badge ${esc(row.status)}">${esc(row.status)}</span></td>
  </tr>`).join("") : `<tr><td colspan="7" class="sub">No modeled I/O points belong to ${esc(label)}.</td></tr>`;
}

// ---- Charts tab -----------------------------------------------------------------------
// A gallery of the catalog (charts.js) and ONE chart below it. Picking a chart fetches
// just that chart's points, resampled by NF; "open in new window" = chart.html.
const chartCtx = () => scopedSets();
const PREF_KEY = "openfdd.chart";
let chartRangeRead = 0;

function loadChartPref() {
  try { Object.assign(chartSel, JSON.parse(localStorage.getItem(PREF_KEY) || "{}")); } catch { /* private mode */ }
}
function saveChartPref() {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(chartSel)); } catch { /* private mode */ }
}

function chartUrl(def) {
  const q = new URLSearchParams({ c: def.id, site: scope.site, h: String(chartSel.hours) });
  if (scope.equip) q.set("equip", scope.equip);
  if (def.pick && chartSel.point) q.set("point", chartSel.point);
  const range = getChartRangeState("charts");
  q.set("range.charts", range.preset);
  if (range.preset === "custom") { q.set("from.charts", String(range.fromMs)); q.set("to.charts", String(range.toMs)); }
  return `chart.html?${q}`;
}

function renderGallery() {
  const ctx = chartCtx();
  const defs = CHARTS.filter((d) => d.applies(ctx));
  if (!defs.some((d) => d.id === chartSel.id)) chartSel.id = defs[0]?.id || "";
  $("gallery").innerHTML = defs.map((d) => `
    <button class="gcard ${d.id === chartSel.id ? "on" : ""}" data-chart="${d.id}">
      <b>${esc(d.title)}</b><span>${esc(d.desc)}</span></button>`).join("")
    || `<span class="sub">No charts apply to the tagged points on this equip.</span>`;
  return defs;
}

async function renderCharts() {
  const read = ++chartRangeRead;
  const defs = renderGallery();
  const def = defs.find((d) => d.id === chartSel.id);
  if (!def) return;
  const baseCtx = chartCtx();
  const opts = def.pick ? def.pick(baseCtx) : [];
  if (def.pick && !opts.some((p) => p.uuid === chartSel.point)) chartSel.point = def.defaultPick(baseCtx);
  const rangeState = getChartRangeState("charts"), siteTz = siteTimeZone();
  renderRangeControl($("chartRangeControl"), { key: "charts", state: rangeState, siteTz,
    onChange: () => renderCharts().catch((e) => ($("chartRangeStatus").textContent = `Could not load this range: ${e.message}`)) });
  $("chartRangeStatus").textContent = "Resolving available history…";
  const candidates = (def.pick ? opts : [...baseCtx.numeric, ...baseCtx.cards, ...baseCtx.status, ...baseCtx.weather]).filter((p) => p && p.uuid);
  let range;
  try { range = await resolveChartSelection(candidates, rangeState, { siteTz }); }
  catch (e) { $("chartRangeStatus").textContent = `Could not load this range: ${e.message}`; throw e; }
  if (read !== chartRangeRead) return;
  const ctx = { ...baseCtx, range, siteTz };
  const hours = Math.max(1, (range.resolvedBounds.toMs - range.resolvedBounds.fromMs) / 3600e3);
  chartSel.hours = hours;
  $("chartTitle").textContent = def.title;
  $("chartPick").hidden = !def.pick;
  $("chartPick").innerHTML = pickOptions(def, baseCtx).map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  $("chartPick").value = chartSel.point || "";
  $("chartOpen").href = chartUrl(def);
  saveChartPref();
  $("chartRangeStatus").textContent = "Loading history…";
  let hint;
  try { hint = await drawChart(mk("chartHost"), def, ctx, hours, { point: chartSel.point, range, siteTz }); }
  catch (e) { $("chartRangeStatus").textContent = `Could not load this range: ${e.message}`; throw e; }
  $("chartRangeStatus").textContent = "";
  if (hint != null) $("chartHint").textContent = hint;
}

// ---- Points tab -----------------------------------------------------------------------
/** Sort group of a point: its equip's id, weather points last (A8: weather is a category of its own). */
const pointGroup = (p) => (isWeatherPoint(p) ? "￿" : p.equipRef || "");

function pointRows() {
  const showUntagged = $("showUntagged").checked;
  const tokens = $("pointFilter").value.toLowerCase().split(/[\s,]+/).filter(Boolean);
  const inScope = (p) => !scope.equip ? true
    : scope.equip === WEATHER_SCOPE ? isWeatherPoint(p)
    : (!isWeatherPoint(p) && p.equipRef === scope.equip) || !has(p, "point");
  return model.points
    .filter((p) => p.siteRef === scope.site && (showUntagged || has(p, "point")))
    .filter(inScope)
    .filter((p) => tokens.every((t) => p.tags.some((m) => m.toLowerCase() === t) || p.dis.toLowerCase().includes(t)))
    .sort((a, b) => (Number(has(b, "point")) - Number(has(a, "point"))) || pointGroup(a).localeCompare(pointGroup(b))
      || rank(a) - rank(b) || a.name.localeCompare(b.name));
}

function renderPoints() {
  const rows = pointRows();
  const names = scopedSets().equipNames;
  $("pointHint").textContent = `${rows.length} shown`;
  let group = null;
  $("pointRows").innerHTML = rows.map((p) => {
    const tags = p.tags.filter((t) => !GENERIC.has(t)).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
    const weather = isWeatherPoint(p);
    const ref = weather ? `${WEATHER_LABEL}${p.weatherStationRef ? ` · station @${p.weatherStationRef}` : ""}`
      : p.equipRef ? `equip @${p.equipRef}` : "–";
    const binding = [p.objectId && `${p.objectId}${p.deviceRef ? ` · ${p.deviceRef}` : ""}`, p.bacnet && `serves BACnet ${p.bacnet}`]
      .filter(Boolean).join("<br>") || "–";
    const ts = p.latest?.ts ? new Date(parseTs(p.latest.ts)).toLocaleTimeString() : "–";
    const g = has(p, "point") ? pointGroup(p) : "\u0000untagged";
    const head = g !== group && !scope.equip
      ? `<tr class="grouprow"><td colspan="6">${esc(!has(p, "point") ? "Untagged objects" : weather ? WEATHER_LABEL : names[p.equipRef] || p.equipRef || "Site")}</td></tr>` : "";
    group = g;
    return `${head}<tr class="pick ${selectedPoint === p.uuid ? "sel" : ""}" data-uuid="${p.uuid}">
      <td>${esc(p.dis)}<div class="sub">${esc(p.cls || p.name)}</div></td>
      <td><div class="tags">${tags || `<span class="sub">untagged</span>`}</div></td>
      <td class="num">${esc(fmtPoint(p))}</td>
      <td class="sub">${esc(ref)}</td>
      <td class="sub mono">${binding}</td>
      <td class="sub">${ts}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="6" class="sub">No points match.</td></tr>`;
}

async function renderPointHistory() {
  const read = ++pointHistoryRead;
  const p = model.points.find((x) => x.uuid === selectedPoint);
  const state = getChartRangeState("points"), siteTz = siteTimeZone();
  renderRangeControl($("histRangeControl"), { key: "points", state, siteTz,
    onChange: () => renderPointHistory().catch(() => {}) });
  if (!p) { $("histRangeStatus").textContent = "Select a point to load its history."; return; }
  $("histHint").textContent = `${p.dis} · ${p.tags.filter((t) => !GENERIC.has(t)).join(" ")}`;
  $("histRangeStatus").textContent = "Loading history…";
  let range;
  try { range = await resolveChartSelection([p], state, { siteTz }); }
  catch (e) { if (read === pointHistoryRead) $("histRangeStatus").textContent = `Could not load this range: ${e.message}`; throw e; }
  if (read !== pointHistoryRead) return;
  const spanHours = Math.max(1, (range.resolvedBounds.toMs - range.resolvedBounds.fromMs) / 3600e3);
  const windowSec = pickWindow(spanHours);
  let fetched;
  try { fetched = await fetchRange([p], range, { windowSec, minWindowSec: windowSec, preserveWindow: true, siteTz }); }
  catch (e) { if (read === pointHistoryRead) $("histRangeStatus").textContent = `Could not load this range: ${e.message}`; throw e; }
  if (read !== pointHistoryRead) return;
  const effectiveWindowSec = fetched.windowSec;
  const history = dispSeries(p, fetched.series.get(p.uuid) || []);
  // Full only: drop buckets recorded under an older output unit (rcx.js); Lite shows the history as is.
  const data = typeof rcxCurrentOutputSeries === "function" ? rcxCurrentOutputSeries(p, history, effectiveWindowSec) : history;
  ofddRender(mk("histChart"), chartOptionSiteTime({
    tooltip, grid: { left: 50, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "time", min: fetched.fromMs, max: fetched.toMs },
    yAxis: { type: "value", scale: true, name: p.kind === "Bool" ? "on / off" : unitLabel(dispUnit(p)) },
    series: [{
      name: p.name, type: "line", showSymbol: false, step: p.kind === "Bool" ? "end" : false,
      lineStyle: { width: 1.6 }, areaStyle: { opacity: 0.08 },
      data,
    }],
  }, siteTz), p.name);
  $("histRangeStatus").textContent = data.length ? "" : "No history in this range.";
}

// ---- BACnet Server tab --------------------------------------------------------------
async function renderBacnet() {
  const [cfg, local, ports] = await Promise.all([
    api("/api/v1/bacnet/configuration"), api("/api/v1/bacnet/local"), api("/api/v1/bacnet/ports"),
  ]);
  const addr = selfAddress(ports);
  const dev = cfg.deviceInstance;
  const objs = local.objects || [];
  $("nBacnet").textContent = objs.length;
  const read = (oid, prop) => readProp(dev, addr, oid, prop).catch(() => undefined);
  const devId = { objectType: "OBJECT_DEVICE", instance: dev };
  const [name, vendor, modelName, fw] = await Promise.all(
    ["PROP_OBJECT_NAME", "PROP_VENDOR_NAME", "PROP_MODEL_NAME", "PROP_FIRMWARE_REVISION"].map((p) => read(devId, p)));
  $("devcard").innerHTML = `
    <span class="k">device</span><span class="mono">d.${dev} · ${esc(name ?? cfg.deviceName)}</span>
    <span class="k">vendor / model</span><span>${esc(vendor ?? "–")} · ${esc(modelName ?? "–")}</span>
    <span class="k">firmware</span><span>${esc(fw ?? "–")}</span>
    <span class="k">BACnet/IP</span><span>${esc(addr?.label ?? "–")} · ${(ports.ports || []).length} port(s)</span>
    <span class="k">local objects</span><span>${objs.length} · values read back with ReadProperty</span>`;
  $("bacHint").textContent = `device ${dev} "${cfg.deviceName}"${addr ? ` at ${addr.label}` : ""}`
    + ` · ${objs.length} local object${objs.length === 1 ? "" : "s"} · from /api/v1/bacnet/local + ReadProperty`;
  if (!objs.length) {
    $("bacRows").innerHTML = `<tr><td colspan="7" class="sub">No local objects on this NF yet.</td></tr>`;
    $("objCards").innerHTML = `<div class="sub">NF serves only its device object.</div>`;
    return;
  }
  const same = (a, b) => typeof a === "number" && typeof b === "number" && Math.abs(a - b) < 0.01;
  const linked = (id) => model.points.find((p) => p.bacnet === id);
  const reads = await Promise.all(objs.map(async (o) => {
    try { return { wire: await readProp(dev, addr, o.objectId) }; } catch (e) { return { err: e.message }; }
  }));
  $("bacRows").innerHTML = objs.map((o, i) => {
    const id = objId(o.objectId);
    const { wire, err } = reads[i];
    const cfgPv = propOf(o, "PROP_PRESENT_VALUE");
    const hv = linked(id);
    const hookVal = hv ? latestOf(hv) : undefined;
    const ok = same(cfgPv, wire) && (!hv || same(wire, hookVal));
    const units = propOf(o, "PROP_UNITS");
    return `<tr>
      <td class="mono">${esc(id)}<div class="sub">dev ${dev}</div></td>
      <td>${esc(propOf(o, "PROP_OBJECT_NAME"))}<div class="sub">${esc(propOf(o, "PROP_DESCRIPTION"))}</div></td>
      <td>${esc(BAC_UNITS[units] ?? units ?? "")}<div class="sub">${units ?? ""}</div></td>
      <td class="num">${fmt(cfgPv, 2)}</td>
      <td class="num">${err ? `<span class="bad" title="${esc(err)}">read failed</span>` : fmt(wire, 2)}</td>
      <td class="num">${hv ? `${fmt(hookVal, 2)}<div class="sub">${esc(hv.name)} · ${hv.latest?.ts ? new Date(parseTs(hv.latest.ts)).toLocaleTimeString() : ""}</div>` : `<span class="sub">–</span>`}</td>
      <td>${ok ? `<span class="ok">✓ same</span>` : `<span class="bad">✗ differs</span>`}</td>
    </tr>`;
  }).join("");
  $("objCards").innerHTML = objs.map((o, i) => {
    const id = objId(o.objectId);
    const hv = linked(id);
    const units = propOf(o, "PROP_UNITS");
    const rows = (o.props || []).map((p) => {
      const v = p.value || {};
      const shown = v.bitString ? `bits ${v.bitString.length} set [${(v.bitString.setBits || []).join(",")}]` : scalar(v);
      return `<tr><td>${esc(p.property.replace(/^PROP_/, "").toLowerCase())}</td><td>${esc(shown)}</td></tr>`;
    }).join("");
    return `<div class="obj">
      <div class="top"><span class="id">${esc(id)}</span><b>${esc(propOf(o, "PROP_OBJECT_NAME"))}</b>
        <span class="pv">${typeof reads[i].wire === "number" ? reads[i].wire.toFixed(2) : "–"} <small>${esc(BAC_UNITS[units] ?? "")}</small></span></div>
      ${hv ? `<div class="tags mt6">${tagChips(hv)}</div>` : `<div class="sub">no Haystack point references ${esc(id)}</div>`}
      <table class="props">${rows}</table>
    </div>`;
  }).join("");
}

// ---- Model & RDF tab ------------------------------------------------------------------
const TREE_COLORS = {
  site: "#b5179e", equip: "#f8961e", device: "#4361ee", sensor: "#43aa8b", sp: "#f9c74f",
  cmd: "#f94144", weather: "#4cc9f0", other: "#577590",
};
const REF_KEYS = ["siteRef", "equipRef", "deviceRef", "weatherStationRef"];
let rdf = { turtle: "", nonStandard: [] };

function tagChips(p) {
  const refs = REF_KEYS.map((k) => [k, k === "siteRef" ? p.siteRef : p[k]]).filter(([, v]) => v);
  return p.tags.map((m) => `<span class="tag ${rdf.nonStandard.includes(m) ? "odd" : ""}">${esc(m)}</span>`).join("")
    + refs.map(([k, v]) => `<span class="tag ref">${k}:@${esc(v)}</span>`).join("");
}

function pointNode(p) {
  const kind = has(p, "weather") ? "weather" : has(p, "cmd") ? "cmd" : has(p, "sp") ? "sp" : has(p, "sensor") ? "sensor" : "other";
  const label = p.tags.filter((t) => !GENERIC.has(t) && !["sensor", "weather"].includes(t)).join(" ") || p.dis;
  const val = fmtPoint(p);
  const av = p.bacnet ? `  ↔ BACnet ${p.bacnet}` : "";
  return { name: `${label}  ${val === "–" ? "" : val}${av}`.trim(), kind, point: p, itemStyle: { color: TREE_COLORS[kind] }, symbolSize: 8 };
}

function entityNode(rec, kind, children, label) {
  const a = rec.attrs || {};
  return {
    name: `${label || a.dis || rec.name}${children.length ? `  (${children.length})` : ""}`, kind, rec,
    itemStyle: { color: TREE_COLORS[kind] }, symbolSize: kind === "site" ? 18 : 13, children,
  };
}

function buildTree() {
  const site = model.sites.find((s) => idOf(s) === scope.site);
  const onSite = model.points.filter((p) => p.siteRef === scope.site);
  const equipNodes = model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site).map((equip) => {
    const eid = idOf(equip);
    const eqPts = onSite.filter((p) => p.equipRef === eid && !isWeatherPoint(p));
    const devs = model.devices.filter((d) => (d.attrs || {}).equipRef === eid);
    const devNodes = devs.map((d) => {
      const did = idOf(d);
      const kids = eqPts.filter((p) => p.deviceRef === did).map(pointNode);
      const internals = onSite.filter((p) => p.deviceRef === did && !p.equipRef);
      if (internals.length) {
        kids.push({
          name: `untagged objects (${internals.length})`, kind: "other", collapsed: true,
          itemStyle: { color: TREE_COLORS.other }, symbolSize: 9,
          rec: { name: "untagged objects", attrs: { note: "deviceRef + siteRef only (internal logic, files, priorities)" } },
          children: internals.map((p) => ({ name: `${p.objectId} ${p.dis}`.trim(), kind: "other", point: p,
            itemStyle: { color: TREE_COLORS.other }, symbolSize: 5 })),
        });
      }
      return entityNode(d, "device", kids, did);
    });
    const loose = eqPts.filter((p) => !devs.some((d) => p.deviceRef === idOf(d))).map(pointNode);
    return entityNode(equip, "equip", [...devNodes, ...loose]);
  });
  const stations = [...new Set(onSite.map((p) => p.weatherStationRef).filter(Boolean))].map((ws) =>
    entityNode({ name: ws, attrs: { id: ws, markers: "weatherStation" } }, "weather",
      onSite.filter((p) => p.weatherStationRef === ws).map(pointNode)));
  // The weather stations sit under their own "Weather" category next to the equips; a group level keeps every point leaf
  // at the same depth as the equip → device → point branch, so the tidy layout doesn't stack labels.
  const groups = stations.length
    ? [{ name: WEATHER_LABEL, kind: "weather", children: stations, itemStyle: { color: TREE_COLORS.weather },
        symbolSize: 10, rec: { name: WEATHER_LABEL, attrs: { note: `${stations.length} station(s)` } } }]
    : [];
  return entityNode(site, "site", [...equipNodes, ...groups]);
}

function showDetail(node) {
  const p = node.point;
  const r = p ? p.rec : node.rec || {};
  const a = r.attrs || {};
  const rows = [
    ["kind", node.kind], ["name", r.name], ["uuid", r.uuid], ["pointType", r.pointType],
    ...(p?.latest ? [["latest", `${fmtPoint(p)} @ ${p.latest.ts}`]] : []),
    ...Object.entries(a).filter(([k]) => k !== "markers").sort(([x], [y]) => x.localeCompare(y)),
  ].filter(([, v]) => v !== undefined && v !== "");
  const chips = p ? tagChips(p) : markersOf(r).map((m) => `<span class="tag">${esc(m)}</span>`).join("");
  $("detail").innerHTML = `<div class="tags">${chips}</div>
    <table>${rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("")}</table>`;
}

function renderModelChecks() {
  const onSite = model.points.filter((p) => p.siteRef === scope.site);
  const tagged = onSite.filter((p) => has(p, "point"));
  const equipIds = new Set(model.equips.map(idOf));
  const deviceIds = new Set(model.devices.map(idOf));
  const stale = tagged.filter((p) => has(p, "his") && (!p.latest?.ts || Date.now() - parseTs(p.latest.ts) > 30 * 60e3));
  const checks = [
    [rdf.nonStandard.length === 0, "tags outside the Haystack libs", rdf.nonStandard],
    [tagged.every((p) => p.cls || has(p, "weather") || has(p, "spare")), "tagged points without a class",
      tagged.filter((p) => !p.cls && !has(p, "weather") && !has(p, "spare")).map((p) => p.dis)],
    [tagged.every((p) => p.kind !== "Number" || p.units), "Number points without a unit",
      tagged.filter((p) => p.kind === "Number" && !p.units).map((p) => p.dis)],
    [onSite.every((p) => !p.equipRef || equipIds.has(p.equipRef)), "equipRef pointing at no equip",
      onSite.filter((p) => p.equipRef && !equipIds.has(p.equipRef)).map((p) => p.dis)],
    [onSite.every((p) => !p.deviceRef || deviceIds.has(p.deviceRef)), "deviceRef pointing at no device",
      onSite.filter((p) => p.deviceRef && !deviceIds.has(p.deviceRef)).map((p) => p.dis)],
    [stale.length === 0, "trended points with no sample in 30 min", stale.map((p) => p.dis)],
  ];
  $("checks").innerHTML = checks.map(([ok, label, items]) => `
    <div class="check check-row"><span class="${ok ? "ok" : "warn"}">${ok ? "✓" : "!"}</span> ${esc(label)}
      ${items.length ? `<div class="tags check-items">${items.map((x) => `<span class="tag odd">${esc(x)}</span>`).join("")}</div>` : ""}
    </div>`).join("");
  const tagSet = new Set(tagged.flatMap((p) => p.tags));
  const stat = (n, label) => `<div class="stat"><b>${n}</b><span>${label}</span></div>`;
  $("modelStats").innerHTML = [
    stat(model.sites.length, "sites"), stat(model.equips.length, "equips"), stat(model.devices.length, "devices"),
    stat(tagged.length, "tagged points"), stat(onSite.length - tagged.length, "untagged objects"),
    stat(tagSet.size, "distinct markers"), stat(rdf.turtle.split("\n").filter((l) => l.startsWith("local:")).length, "RDF subjects"),
  ].join("");
}

function renderModel() {
  $("ttl").textContent = rdf.turtle;
  // Legend dots are colored through the CSSOM (style attributes are blocked by the CSP).
  $("legend").replaceChildren(...Object.entries(TREE_COLORS).map(([k, c]) => {
    const item = document.createElement("span"), dot = document.createElement("i");
    dot.style.background = c;
    item.append(dot, k);
    return item;
  }));
  renderModelChecks();
  const root = buildTree();
  const leaves = (n, depth) => (!n.children?.length || n.collapsed || depth >= 4 ? 1
    : n.children.reduce((s, c) => s + leaves(c, depth + 1), 0));
  $("tree").style.height = `${Math.max(520, leaves(root, 0) * 24 + 60)}px`;
  const chart = mk("tree");
  chart.resize();
  ofddRender(chart, {
    tooltip: { trigger: "item",
      formatter: (x) => esc(x.data.point?.dis || x.data.rec?.attrs?.dis || x.name) },
    series: [{
      type: "tree", data: [root], top: 30, bottom: 20, left: 90, right: 300,
      orient: "LR", initialTreeDepth: 4, roam: true, expandAndCollapse: true, animationDuration: 400,
      symbol: "circle", lineStyle: { color: cssVar("--line"), width: 1.4, curveness: 0.5 },
      label: { position: "top", distance: 6, align: "center", color: cssVar("--text"), fontSize: 12 },
      leaves: { label: { position: "right", verticalAlign: "middle", align: "left", distance: 6 } },
      emphasis: { focus: "descendant" },
    }],
  }, "haystack-tree");
  chart.off("click");
  chart.on("click", (x) => showDetail(x.data));
  showDetail(root);
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---- tabs + live loop -----------------------------------------------------------------
function renderTab(name) {
  const errs = (e) => setLive(false, e.message);
  if (name === "overview") refreshOverviewSparks();
  if (name === "charts") renderCharts().catch(errs);
  if (name === "points") { renderPoints(); if (selectedPoint) renderPointHistory().catch(errs); }
  if (name === "bacnet") renderBacnet().catch((e) => ($("bacHint").textContent = `BACnet server: ${e.message}`));
  if (name === "model") renderModel();
  if (ofddTabs[name]) {                      // a tab only this edition has
    try { const r = ofddTabs[name](); if (r && r.catch) r.catch(errs); } catch (e) { errs(e); }
  }
  // Charts created while their tab was hidden have zero size until resized.
  requestAnimationFrame(ofddResizeAll);
}

function showTab(name) {
  if (name === "tuning") name = "fdd";
  if (name === "tuning") name = "fdd";
  if (!$(`tab-${name}`)) name = "overview";
  activeTab = name;
  document.querySelectorAll("#tabs button").forEach((/** @type {HTMLElement} */ b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${name}`));
  // Keep the tab in the URL hash so a link opens straight on it.
  if (location.hash !== `#${name}`) window.history.replaceState(null, "", `#${name}`);
  ({ cards: points, weather: variables, status: statusPts } = scopedSets());
  if (name === "overview") { renderCards(); renderChips(); renderOverviewIo(); }
  renderTab(name);
}

// ---- live values: NF push stream, polling as fallback ------------------------------------
let stopStream = null;
let streamUp = false;
let uiTimer = null;
const changed = new Set();  // card indexes updated since the last redraw

function startStream() {
  stopStream?.();
  const uuids = taggedOnSite().map((p) => p.uuid);
  if (!uuids.length) return;
  stopStream = streamUpdates(uuids, onUpdate, (up, err) => {
    streamUp = up;
    setLive(true, up ? `live (push) · ${new Date().toLocaleTimeString()}` : `polling · stream ${err?.message || "down"}`);
  });
}

/** One pushed value: update every copy of that point, then redraw what shows it. */
function onUpdate(u) {
  const v = u.value || {};
  const num = v.double ?? v.real ?? (typeof v.boolean === "boolean" ? +v.boolean : v.enumerated ?? v.unsigned);
  if (!u.uuid || !v.ts || num == null) return;
  const latest = { ts: v.ts, double: num };
  for (const p of [...model.points, ...points, ...variables, ...statusPts]) if (p.uuid === u.uuid) p.latest = latest;
  const i = points.findIndex((p) => p.uuid === u.uuid);
  if (i >= 0) {
    changed.add(i);
    pushSpark(u.uuid, parseTs(v.ts), num);
  }
  // NF pushes one batch per poll; coalesce the redraw.
  clearTimeout(uiTimer);
  uiTimer = setTimeout(() => {
    if (activeTab === "overview") {
      changed.forEach((k) => updateCard(k, true));
      renderOverviewIo();
    }
    changed.clear();
    renderChips();
    if (activeTab === "points") renderPoints();
    setLive(true, `live (push) · ${new Date().toLocaleTimeString()}`);
  }, 250);
}

// One refresh at a time; after failures wait longer (15 s → 30 s → … 5 min) so a box
// that is rebooting or overloaded isn't hammered.
let liveFails = 0;
async function liveLoop() {
  liveFails = (await refreshLive()) ? 0 : liveFails + 1;
  const wait = liveFails ? Math.min(LIVE_MS * 2 ** liveFails, RESYNC_MS) : streamUp ? RESYNC_MS : LIVE_MS;
  setTimeout(liveLoop, wait);
}

async function refreshLive() {
  try {
    const before = new Map(model.points.map((p) => [p.uuid, p.latest?.ts]));
    model.points = await loadPoints(model);
    const byId = new Map(model.points.map((p) => [p.uuid, p]));
    for (const p of [...points, ...variables]) {
      const f = byId.get(p.uuid);
      if (!f?.latest?.ts || f.latest.ts === before.get(p.uuid)) continue;
      p.latest = f.latest;
      const v = latestOf(f);
      if (v == null) continue;
      pushSpark(p.uuid, parseTs(f.latest.ts), v);
      const i = points.indexOf(p);
      if (i >= 0) updateCard(i, activeTab === "overview");
    }
    statusPts = scopedSets().status;
    renderChips();
    if (activeTab === "overview") renderOverviewIo();
    if (activeTab === "points") renderPoints();
    if (activeTab === "bacnet") renderBacnet().catch((e) => ($("bacHint").textContent = `BACnet server: ${e.message}`));
    setLive(true, `${streamUp ? "live (push)" : "polling"} · ${new Date().toLocaleTimeString()}`);
    return true;
  } catch (e) {
    setLive(false, `${e.message} · retrying`);
    return false;
  }
}

function setLive(ok, txt) {
  $("liveDot").classList.toggle("bad", !ok);
  $("liveTxt").textContent = txt;
}

function showErr(e) {
  $("err").style.display = "block";
  $("err").textContent = `Could not load NF data: ${e.message}. Open this page on the NF host (LAN or Normal Online) after signing in to the console there.`;
  setLive(false, "error");
}

function wireControls() {
  $("tabs").onclick = (ev) => { const b = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("button")); if (b) showTab(b.dataset.tab); };
  $("sitePick").onchange = () => {
    scope.site = $("sitePick").value;
    scope.equip = "";
    deliberateAllTabs.clear();
    overviewSelection = { site: "", equipId: "", mode: "auto", reason: "" };
    fillPickers();
    applyScope().catch(showErr);
  };
  // Overview Auto button: drop the site's saved override and re-run temperature-based auto-selection.
  document.addEventListener("click", (ev) => {
    const btn = /** @type {HTMLElement} */ (ev.target).closest?.("#overviewAutoBtn");
    if (!btn) return;
    saveOverviewEquipForSite(scope.site, "");
    fillPickers({ forceAuto: true });
    if (!deliberateAllTabs.size && overviewSelection.equipId) scope.equip = overviewSelection.equipId;
    applyScope().catch(showErr);
  });
  // The equip pickers sit inside their tabs: Overview persists its own single-equip pick per site and never wipes deliberate All on FDD/RCx.
  document.addEventListener("change", (ev) => {
    const sel = /** @type {HTMLElement} */ (ev.target).closest?.(".equip-pick");
    if (!sel) return;
    const val = /** @type {AnyEl} */ (sel).value;
    const tabId = sel.closest(".tab")?.id?.replace(/^tab-/, "") || "";
    if (tabId === "overview") {
      if (val) {
        saveOverviewEquipForSite(scope.site, val);
        overviewSelection = { site: scope.site, equipId: val, mode: "manual", reason: "Manual selection (saved for this site)." };
        if (!deliberateAllTabs.has("fdd") && !deliberateAllTabs.has("rcx")) scope.equip = val;
      }
    } else {
      if (val === "") deliberateAllTabs.add(tabId);
      else deliberateAllTabs.delete(tabId);
      scope.equip = val;
    }
    fillPickers();
    applyScope().catch(showErr);
  });
  const chartErr = (e) => ($("chartHint").textContent = `could not load: ${e.message}`);
  $("gallery").onclick = (ev) => {
    const b = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("[data-chart]"));
    if (!b || b.dataset.chart === chartSel.id) return;
    chartSel.id = b.dataset.chart;
    chartSel.hours = 0;
    renderCharts().catch(chartErr);
  };
  $("chartPick").onchange = () => { chartSel.point = $("chartPick").value; renderCharts().catch(chartErr); };
  $("pointFilter").oninput = renderPoints;
  $("showUntagged").onchange = renderPoints;
  $("pointRows").onclick = (ev) => {
    const tr = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("tr[data-uuid]"));
    if (!tr) return;
    selectedPoint = tr.dataset.uuid;
    renderPoints();
    renderPointHistory().catch((e) => setLive(false, e.message));
  };
  $("dlTtl").onclick = () => download(`${scope.site || "nf"}-haystack.ttl`, rdf.turtle, "text/turtle");
  $("dlJson").onclick = () => download(`${scope.site || "nf"}-haystack.json`, JSON.stringify({
    sites: model.sites, equips: model.equips, devices: model.devices,
    points: model.points.filter((p) => p.tags.length).map((p) => p.rec),
  }, null, 2), "application/json");
  window.addEventListener("popstate", () => {
    const restoredTab = (location.hash || `#${activeTab}`).slice(1);
    showTab(restoredTab);
  });
  // Theme switch: theme.js disposed every chart; draw the visible ones again.
  onThemeChange(() => { points.forEach((p, i) => updateCard(i, false)); renderTab(activeTab); ofddOnTheme.forEach((fn) => fn()); });
  ofddWire.forEach((fn) => fn());
}

async function main() {
  setInterval(() => ($("clock").textContent = new Date().toLocaleString()), 1000);
  wireControls();
  loadChartPref();
  await initAuth();
  await loadSiteTimeZoneSources();
  model = await loadModel();
  scope.site = idOf(model.sites[0]);
  fillPickers();
  activeTab = (location.hash || "#overview").slice(1);
  if (activeTab === "tuning") activeTab = "fdd";
  if (!$(`tab-${activeTab}`)) activeTab = "overview";
  document.querySelectorAll("#tabs button").forEach((/** @type {HTMLElement} */ b) => b.classList.toggle("on", b.dataset.tab === activeTab));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${activeTab}`));
  await applyScope();
  api("/api/v1/bacnet/local").then((l) => ($("nBacnet").textContent = (l.objects || []).length)).catch(() => {});
  setTimeout(liveLoop, LIVE_MS);
  // Re-sync the visible sparklines every 10 min and redraw the open chart every 5.
  setInterval(() => { if (activeTab === "overview" && !document.hidden) refreshOverviewSparks(); }, 10 * 60e3);
  setInterval(() => { if (activeTab === "charts" && !document.hidden) renderCharts().catch(() => {}); }, CHART_REFRESH_MS);
}
