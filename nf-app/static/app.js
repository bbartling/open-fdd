// Open-FDD on Normal Framework: dashboard tabs (Open-FDD 4.x light/dark theme). Everything renders from `model` (model.js: Haystack SITE /
// EQUIPMENT / DEVICE records + point markers and refs), narrowed by the site and
// equip pickers. Point sets are chosen by markers, never by name, so the same page
// works on any NF whose points are tagged. The BACnet tab reads NF's own server.
// Charts come from the catalog in charts.js: one on screen at a time, fetched resampled.

const LIVE_MS = 15000;            // polling while the push stream is down
const RESYNC_MS = 5 * 60e3;       // full refresh while it is up (untagged points, BACnet tab)
const SPARK_HOURS = 6;            // Overview sparklines: 6 h of 5-min averages
const CHART_REFRESH_MS = 5 * 60e3;

/** @param {string} id @returns {AnyEl} */
const $ = (id) => /** @type {AnyEl} */ (document.getElementById(id));
const fmtPoint = (p) => {
  const v = latestOf(p);
  if (v == null) return "–";
  return p.kind === "Bool" ? (v ? "on" : "off") : `${fmt(dispVal(p, v), 2)} ${unitLabel(dispUnit(p))}`.trim();
};

let model = null;                        // loadModel() result
const scope = { site: "", equip: "" };   // equip "" = every equip on the site
let points = [];          // numeric sensor/sp points on the scoped equips (cards + charts)
let variables = [];       // `weather` points on the site, charted against the equip's outside air
let statusPts = [];       // kind Bool points on the scoped equips (status chips)
let sparkHist = new Map();  // uuid -> [[ms, value], ...] for the sparklines (+ live samples)
let histHours = 24;
const chartSel = { id: "", hours: 0, point: "" };  // Charts tab: the one chart on screen
let selectedPoint = null; // Points tab
let activeTab = "overview";
const fddExpandedGroups = new Set();
// Chart instances live in theme.js (one per element, rebuilt on a theme switch).
const mk = (id) => ofddChart($(id));

// ---- scope: which points each tab shows, decided by tags --------------------------
const siteEquipIds = () => model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site).map(idOf);
const taggedOnSite = () => model.points.filter((p) => p.siteRef === scope.site && has(p, "point"));
const scopedSets = () => pointSets(model, scope.site, scope.equip);

function fillPickers() {
  $("sitePick").innerHTML = model.sites.map((s) => `<option value="${esc(idOf(s))}">${esc(s.name)}</option>`).join("");
  $("sitePick").value = scope.site;
  const equips = model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site);
  $("equipPick").innerHTML = `<option value="">all equips (${equips.length})</option>`
    + equips.map((e) => `<option value="${esc(idOf(e))}">${esc((e.attrs || {}).dis || e.name)}</option>`).join("");
  $("equipPick").value = scope.equip;
}

async function applyScope() {
  ({ cards: points, weather: variables, status: statusPts } = scopedSets());
  rdf = modelToTurtle(model, `urn:nf:${location.host}:`);
  const tagged = taggedOnSite();
  const site = model.sites.find((s) => idOf(s) === scope.site);
  const equips = model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site);
  const devices = model.devices.filter((d) => (d.attrs || {}).siteRef === scope.site);
  const names = (recs) => recs.map((r) => (r.attrs || {}).dis || r.name).join(", ") || "–";
  $("sub").textContent = `${site?.name ?? scope.site} · ${names(equips)} · ${names(devices)} · ${tagged.length} tagged points · ${location.host}`;
  $("nPoints").textContent = tagged.length;
  renderSummary();
  renderCards();
  renderChips();
  renderTab(activeTab);
  // Only the sparklines need history up front: one small resampled request.
  startStream();
  setLive(true, "loading sparklines…");
  await loadSparks();
  if (activeTab === "overview") points.forEach((p, i) => updateCard(i, false));
  setLive(true, `live · ${new Date().toLocaleTimeString()}`);
}

// ---- sparkline history ---------------------------------------------------------------
async function loadSparks() {
  sparkHist = await fetchSeries(points, SPARK_HOURS, { windowSec: 300 });
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
  $("cards").innerHTML = points.map((p, i) => `
    <div class="card" id="card-${i}" title="${esc(p.tags.join(" "))}">
      <div class="name">${esc(p.name)}</div>
      <div class="desc">${esc(p.dis)}</div>
      <div class="val"><span id="val-${i}">–</span><small>${esc(unitLabel(dispUnit(p)))}</small></div>
      <div class="delta" id="delta-${i}">&nbsp;</div>
      <div class="spark" id="spark-${i}"></div>
    </div>`).join("");
  points.forEach((p, i) => updateCard(i, false));
}

function updateCard(i, flash) {
  const p = points[i];
  const v = dispVal(p, latestOf(p));
  const shown = dispSeries(p, sparkHist.get(p.uuid) || []);   // history is kept as NF stores it
  $(`val-${i}`).textContent = fmt(v, isRH(p) || isTemp(p) ? 1 : 2);
  const hour = since(shown, 1);
  if (hour.length > 1 && v != null) {
    const d = v - hour[0][1];
    const arrow = Math.abs(d) < 0.05 ? "→" : d > 0 ? "▲" : "▼";
    $(`delta-${i}`).textContent = `${arrow} ${d >= 0 ? "+" : ""}${fmt(d, 2)} in the last hour`;
  }
  const pal = palette();
  const color = pal[i % pal.length];
  mk(`spark-${i}`).setOption({
    animation: false, backgroundColor: "transparent",
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: "time", show: false }, yAxis: { type: "value", show: false, scale: true },
    series: [{
      type: "line", data: since(shown, 6), showSymbol: false, smooth: true,
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
  }).join("") : `<span class="sub">No Bool points tagged on an equip.</span>`;
}

// ---- Charts tab -----------------------------------------------------------------------
// A gallery of the catalog (charts.js) and ONE chart below it. Picking a chart fetches
// just that chart's points, resampled by NF; "open in new window" = chart.html.
const chartCtx = () => ({ cards: points, status: statusPts, weather: variables });
const PREF_KEY = "benchviz.chart";

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
  const defs = renderGallery();
  const def = defs.find((d) => d.id === chartSel.id);
  if (!def) return;
  const ctx = chartCtx();
  if (!def.ranges.includes(chartSel.hours)) chartSel.hours = def.range;
  const opts = def.pick ? def.pick(ctx) : [];
  if (def.pick && !opts.some((p) => p.uuid === chartSel.point)) chartSel.point = def.defaultPick(ctx);
  $("chartTitle").textContent = def.title;
  $("chartPick").style.display = def.pick ? "" : "none";
  $("chartPick").innerHTML = opts.map((p) => `<option value="${p.uuid}">${esc(p.name)}</option>`).join("");
  $("chartPick").value = chartSel.point || "";
  $("chartRange").innerHTML = def.ranges.map((h) =>
    `<button data-h="${h}" class="${h === chartSel.hours ? "on" : ""}">${rangeLabel(h)}</button>`).join("");
  $("chartOpen").href = chartUrl(def);
  saveChartPref();
  const hint = await drawChart(mk("chartHost"), def, ctx, chartSel.hours, { point: chartSel.point });
  if (hint != null) $("chartHint").textContent = hint;
}

// ---- FDD tab --------------------------------------------------------------------------
// Which rules from the catalog each equip in scope can run (fdd.js binds inputs by tags).
const fddEquipsInScope = () => model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site && (!scope.equip || idOf(e) === scope.equip));
const renderScopedFddResults = () => renderFddResults(fddEquipsInScope());
async function renderFdd() {
  const catalog = await loadCatalog();
  const equips = fddEquipsInScope();
  const rows = equips.flatMap((e) => equipRules(e, model, catalog).map((r) => ({ ...r, equip: e })));
  const runnable = rows.filter((r) => r.runnable);
  $("nRules").textContent = runnable.length;
  const stat = (n, label) => `<div class="stat"><b>${n}</b><span>${label}</span></div>`;
  $("fddStats").innerHTML = [
    stat(catalog.rules.length, "rules in catalog"), stat(rows.length, "rules for these equip kinds"),
    stat(runnable.length, "can run now"), stat(rows.filter((r) => r.pointInputs && !r.runnable).length, "missing inputs"),
    stat(rows.filter((r) => !r.pointInputs).length, "use other data"), stat(equips.length, "equips"),
  ].join("");
  const only = $("fddRunnableOnly").checked;
  const chip = (role, pts, optional) => {
    const cls = pts.length ? "got" : optional ? "opt" : "miss";
    const title = pts.length ? pts.map((p) => p.dis).join(" · ") : optional ? "optional, not found" : "required, not found";
    const label = pts.length ? `${role} → ${pts[0].name}${pts.length > 1 ? ` (+${pts.length - 1})` : ""}` : role;
    return `<span class="tag ${cls} ${optional ? "opt" : ""}" title="${esc(title)}">${esc(label)}</span>`;
  };
  $("fddRows").innerHTML = rows.filter((r) => !only || r.runnable).map((r) => `<tr class="clickable" data-rule="${esc(r.rule.id)}" data-equip="${esc(idOf(r.equip))}" title="plot this rule">
      <td><span class="rule-id">${esc(r.rule.id)}</span><div class="sub">${esc(r.rule.description)}</div></td>
      <td class="sub">${esc((r.equip.attrs || {}).dis || r.equip.name)}</td>
      <td><div class="tags">${r.required.map((x) => chip(x, r.bound[x], false)).join("")}${r.optional.map((x) => chip(x, r.bound[x], true)).join("")}</div></td>
      <td>${r.runnable ? `<span class="ok">✓ can run</span>`
        : !r.pointInputs ? `<span class="sub">uses utility/meter data, not points</span>`
        : `<span class="warn">needs ${esc(r.missing.join(", "))}</span>`}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="sub">No rules apply to the equips in scope.</td></tr>`;
  await renderScopedFddResults();
}

// "Run FDD now": start the hook through NF (StartHook = on-request run), wait for it, reload.
// The app id is the static path segment (/api/v1/apps/static/<app>/), never hard-coded.
const APP_ID = (location.pathname.match(/\/apps\/static\/([^/]+)\//) || [])[1] || "open-fdd";
async function runFddNow() {
  const state = $("fddRunState");
  $("fddRunNow").disabled = true;
  try {
    state.textContent = "starting…";
    const { pid } = await api(`/api/v1/apps/${APP_ID}/hooks/fdd`, {});
    for (let i = 0; i < 60; i++) {
      await new Promise((ok) => setTimeout(ok, 2000));
      const runs = (await api(`/api/v1/apps/${APP_ID}/hooks/fdd/runs?page_size=5&include_results=true`)).runs || [];
      const run = runs.find((r) => r.pid === pid);
      if (!run || ["STATE_RUNNING", "STATE_ENQUEUED", "STATE_SCHEDULED"].includes(run.state)) { state.textContent = `running… ${2 * (i + 1)} s`; continue; }
      const events = Object.values(run.results || {}).flatMap((g) => g.events || []);
      state.textContent = run.state === "STATE_SUCCESS" ? (events.at(-1)?.message || "done") : `run ended: ${run.state}`;
      model.points = await loadPoints(model);
      await renderFdd();
      return;
    }
    state.textContent = "still running; reload later";
  } finally {
    $("fddRunNow").disabled = false;
  }
}

async function showRulePlot(ruleId, equipId) {
  const catalog = await loadCatalog();
  const equipRec = model.equips.find((e) => idOf(e) === equipId && (e.attrs || {}).siteRef === scope.site)
    || model.equips.find((e) => idOf(e) === equipId);
  const row = equipRec && equipRules(equipRec, model, catalog).find((r) => r.rule.id === ruleId);
  if (!row) return;
  $("fddPlotPanel").hidden = false;
  $("fddPlotTitle").textContent = `${ruleId} · ${equipLabel(equipRec)}`;
  $("fddPlotNote").textContent = row.rule.description || "";
  $("fddPlotPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  const note = await fddRulePlot($("fddPlot"), { rule: row.rule, equipRec, bound: row.bound,
    resultPoint: rcxResultPoint(model, equipRec, ruleId), model, hours: 168 });
  $("fddPlot").classList.add("rendered");
  if (note) $("fddPlotNote").textContent = note;
}

// Result points the FDD hook writes: markers fdd + fault|metric, ruleRef, equipRef.
const ruleRefOf = (p) => (p.rec.attrs || {}).ruleRef || "";
const fddResults = (equipIds) => model.points
  .filter((p) => has(p, "fdd") && ruleRefOf(p) && equipIds.includes(p.equipRef)
    && (!scope.site || p.siteRef === scope.site || (!p.siteRef && model.equips.filter((e) => idOf(e) === p.equipRef).length === 1)))
  .sort((a, b) => (latestOf(b) ?? 0) - (latestOf(a) ?? 0) || ruleRefOf(a).localeCompare(ruleRefOf(b)));

/** Faults panel: latest value per rule/equip + a lane per fault rule (hourly max, 7 days). */
async function renderFddResults(equips) {
  const results = fddResults(equips.map(idOf));
  $("fddResultsPanel").hidden = !results.length;
  if (!results.length) return;
  const equipName = (id) => {
    const e = model.equips.find((x) => idOf(x) === id && (x.attrs || {}).siteRef === scope.site)
      || model.equips.find((x) => idOf(x) === id);
    return (e && ((e.attrs || {}).dis || e.name)) || id;
  };
  const attrsOf = (p) => p.rec.attrs || {};
  const when = (p) => {
    const ts = attrsOf(p).fddLastRun || (p.latest && p.latest.ts);
    return ts ? new Date(parseTs(ts)).toLocaleString() : "–";
  };
  const sensorNameOf = (p) => {
    const ref = attrsOf(p).sensorRef;
    const input = ref && model.points.find((x) => x.uuid === ref && has(x, "point"));
    return input ? (input.dis || input.name) : (p.name || p.dis);
  };
  const statusOf = (p) => attrsOf(p).fddStatus || (latestOf(p) == null ? "not-assessed" : has(p, "fault") && latestOf(p) > 0 ? "fault" : "ok");
  const faulted = (p) => statusOf(p) === "fault" || (statusOf(p) !== "not-assessed" && statusOf(p) !== "stale" && has(p, "fault") && latestOf(p) > 0);
  const sweeps = new Set(results.filter((p) => /^SV-/.test(ruleRefOf(p))).map(ruleRefOf));
  const rows = [];
  for (const ruleId of sweeps) {
    const ruleRows = results.filter((p) => ruleRefOf(p) === ruleId);
    const byGroup = new Map();
    for (const p of ruleRows) {
      const key = p.equipRef;
      if (!byGroup.has(key)) byGroup.set(key, []);
      byGroup.get(key).push(p);
    }
    for (const [equipId, group] of byGroup) {
      const sensors = group.filter((p) => attrsOf(p).fddSummary === "sensor" || attrsOf(p).sensorRef);
      const summary = group.find((p) => attrsOf(p).fddSummary === "equip") || group.find((p) => !sensors.includes(p));
      if (summary) {
        const groupId = `${ruleId}|${equipId}`;
        const v = latestOf(summary), status = statusOf(summary), hot = faulted(summary);
        rows.push(`<tr class="clickable fdd-summary-row" data-rule="${esc(ruleId)}" data-equip="${esc(equipId)}">
          <td>${sensors.length ? `<button class="fdd-expand" type="button" data-expand="${esc(groupId)}" aria-expanded="${fddExpandedGroups.has(groupId)}" title="Show sensor results">${fddExpandedGroups.has(groupId) ? "▾" : "▸"}</button> ` : ""}<span class="rule-id">${esc(ruleId)}</span><div class="sub">equipment summary</div></td>
          <td class="sub">${esc(equipName(equipId))}</td><td class="${hot ? "warn" : status === "ok" ? "ok" : "sub"}">${esc(status)} · ${v == null ? `– ${esc(dispUnit(summary))}` : `${fmt(dispVal(summary, v))} ${esc(dispUnit(summary))}`}</td>
          <td class="sub">${esc(when(summary))}${attrsOf(summary).fddCoverageHours !== "" && attrsOf(summary).fddCoverageHours != null ? ` · ${esc(attrsOf(summary).fddCoverageHours)} h covered` : ""}</td></tr>`);
      }
      const faultedOnly = $("fddFaultedOnly")?.checked;
      for (const p of sensors.sort((a, b) => Number(faulted(b)) - Number(faulted(a)) || String(attrsOf(a).roleRef || "").localeCompare(String(attrsOf(b).roleRef || "")))) {
        const v = latestOf(p), status = statusOf(p), hot = faulted(p), groupId = `${ruleId}|${equipId}`;
        if (faultedOnly && !hot) continue;
        const role = attrsOf(p).roleRef || "sensor";
        const hidden = !fddExpandedGroups.has(groupId);
        rows.push(`<tr class="clickable fdd-sensor-row" data-rule="${esc(ruleId)}" data-equip="${esc(equipId)}" data-sensor="${esc(attrsOf(p).sensorRef || "")}"${hidden ? " hidden" : ""}>
          <td><span class="rule-id">${esc(ruleId)}</span><div class="sub">${esc(role)}</div></td><td class="sub">${esc(sensorNameOf(p))}<div class="sub">${esc(equipName(equipId))}</div></td>
          <td class="${hot ? "warn" : status === "ok" ? "ok" : "sub"}">${esc(status)} · ${v == null ? `– ${esc(dispUnit(p))}` : `${fmt(dispVal(p, v))} ${esc(dispUnit(p))}`}</td>
          <td class="sub">${esc(when(p))}${attrsOf(p).fddCoverageHours !== "" && attrsOf(p).fddCoverageHours != null ? ` · ${esc(attrsOf(p).fddCoverageHours)} h covered` : ""}</td></tr>`);
      }
    }
  }
  for (const p of results.filter((x) => !sweeps.has(ruleRefOf(x)))) {
    const v = latestOf(p);
    const hot = has(p, "fault") && v > 0;
    rows.push(`<tr class="clickable" data-rule="${esc(ruleRefOf(p))}" data-equip="${esc(p.equipRef)}" title="plot this rule"><td><span class="rule-id">${esc(ruleRefOf(p))}</span></td><td class="sub">${esc(equipName(p.equipRef))}</td>
      <td class="${hot ? "warn" : "ok"}">${fmt(dispVal(p, v))} ${esc(dispUnit(p))}</td><td class="sub">${esc(when(p))}</td></tr>`);
  }
  $("fddResultRows").innerHTML = rows.join("");
  const sweepSensorPoints = results.filter((p) => /^SV-/.test(ruleRefOf(p)) && (attrsOf(p).fddSummary === "sensor" || attrsOf(p).sensorRef));
  const heatmapRows = results.filter((p) => has(p, "fault") && !sweepSensorPoints.some((s) => s.equipRef === p.equipRef && ruleRefOf(s) === ruleRefOf(p) && (attrsOf(p).fddSummary === "equip" || !attrsOf(p).fddSummary)));
  const faults = heatmapRows;
  const el = $("fddLanes");
  el.hidden = !faults.length;
  if (!faults.length) return;
  const series = await fetchDisplay(faults, 24 * 7, { method: "MAX", windowSec: 3600 });
  const label = (p) => `${ruleRefOf(p)} · ${attrsOf(p).roleRef ? `${attrsOf(p).roleRef} · ${sensorNameOf(p)}` : equipName(p.equipRef)}`;
  el.style.height = `${Math.max(160, 26 * faults.length + 70)}px`;
  // Heatmaps need category axes: one column per hour.
  const units = (p) => dispUnit(p) || (attrsOf(p).fddOutput === "fault_hours" ? "h" : "%");
  const filtered = new Map(faults.map((p) => [p.uuid, rcxCurrentOutputSeries(p, series.get(p.uuid) || [], 3600)]));
  const hours = [...new Set(faults.flatMap((p) => (filtered.get(p.uuid) || []).map(([t]) => Math.floor(t / 3600e3) * 3600e3)))].sort((a, b) => a - b);
  const col = new Map(hours.map((t, i) => [t, i]));
  const hourLabel = (t) => new Date(t).toLocaleString(undefined, { weekday: "short", hour: "numeric" });
  const unitGroups = new Map();
  for (const p of faults) {
    const unit = units(p);
    if (!unitGroups.has(unit)) unitGroups.set(unit, []);
    unitGroups.get(unit).push(p);
  }
  const unitEntries = [...unitGroups];
  const heatSeries = unitEntries.map(([unit, points]) => ({ type: "heatmap", name: unit, data: points.flatMap((p) =>
    (filtered.get(p.uuid) || []).map(([t, v]) => [col.get(Math.floor(t / 3600e3) * 3600e3), faults.indexOf(p), v])) }));
  const visualMaps = unitEntries.map(([unit, points], seriesIndex) => {
    const max = unit === "h" ? Math.max(1, ...points.map((p) => Number(attrsOf(p).fddWindowHours) || 24)) : 100;
    return { min: 0, max, seriesIndex, dimension: 2, orient: "horizontal", left: `${Math.round((seriesIndex + 1) * 100 / (unitEntries.length + 1))}%`, bottom: 0, itemHeight: 100,
      text: [`${max} ${unit}`, `0 ${unit}`], inRange: { color: ["rgba(239,68,68,0.05)", FAULT_LANE.lineStyle.color] } };
  });
  ofddChart(el).setOption({
    tooltip: { formatter: (x) => { const p = faults[x.value[1]], unit = units(p); return `${esc(label(p))}<br>${esc(hourLabel(hours[x.value[0]]))}: ${fmt(x.value[2])} ${esc(unit)}`; } },
    grid: { left: 200, right: 20, top: 10, bottom: 70 },
    xAxis: { type: "category", data: hours.map(hourLabel), splitArea: { show: false } },
    yAxis: { type: "category", data: faults.map(label), inverse: true },
    visualMap: visualMaps,
    series: heatSeries,
  }, true);
}

// ---- Points tab -----------------------------------------------------------------------
function pointRows() {
  const showUntagged = $("showUntagged").checked;
  const tokens = $("pointFilter").value.toLowerCase().split(/[\s,]+/).filter(Boolean);
  return model.points
    .filter((p) => p.siteRef === scope.site && (showUntagged || has(p, "point")))
    .filter((p) => !scope.equip || p.equipRef === scope.equip || p.weatherStationRef || !has(p, "point"))
    .filter((p) => tokens.every((t) => p.tags.some((m) => m.toLowerCase() === t) || p.dis.toLowerCase().includes(t)))
    .sort((a, b) => (Number(has(b, "point")) - Number(has(a, "point"))) || (a.equipRef || a.weatherStationRef).localeCompare(b.equipRef || b.weatherStationRef)
      || rank(a) - rank(b) || a.name.localeCompare(b.name));
}

function renderPoints() {
  const rows = pointRows();
  $("pointHint").textContent = `${rows.length} shown`;
  $("pointRows").innerHTML = rows.map((p) => {
    const tags = p.tags.filter((t) => !GENERIC.has(t)).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
    const ref = p.equipRef ? `equip @${p.equipRef}` : p.weatherStationRef ? `weatherStation @${p.weatherStationRef}` : "–";
    const binding = [p.objectId && `${p.objectId}${p.deviceRef ? ` · ${p.deviceRef}` : ""}`, p.bacnet && `serves BACnet ${p.bacnet}`]
      .filter(Boolean).join("<br>") || "–";
    const ts = p.latest?.ts ? new Date(parseTs(p.latest.ts)).toLocaleTimeString() : "–";
    return `<tr class="pick ${selectedPoint === p.uuid ? "sel" : ""}" data-uuid="${p.uuid}">
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
  const p = model.points.find((x) => x.uuid === selectedPoint);
  if (!p) return;
  $("histHint").textContent = `${p.dis} · ${p.tags.filter((t) => !GENERIC.has(t)).join(" ")}`;
  const windowSec = pickWindow(histHours);
  const history = (await fetchDisplay([p], histHours, { windowSec })).get(p.uuid) || [];
  const data = rcxCurrentOutputSeries(p, history, windowSec);
  ofddRender(mk("histChart"), {
    tooltip, grid: { left: 50, right: 20, top: 30, bottom: 50 },
    xAxis: { type: "time" },
    yAxis: { type: "value", scale: true, name: p.kind === "Bool" ? "on / off" : unitLabel(dispUnit(p)) },
    series: [{
      name: p.name, type: "line", showSymbol: false, step: p.kind === "Bool" ? "end" : false,
      lineStyle: { width: 1.6 }, areaStyle: { opacity: 0.08 },
      data,
    }],
  }, p.name);
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
    const eqPts = onSite.filter((p) => p.equipRef === eid);
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
  // A group level for stations keeps every point leaf at the same depth as the
  // equip → device → point branch, so the tidy layout doesn't stack labels.
  const groups = stations.length
    ? [{ name: "weather stations", kind: "weather", children: stations, itemStyle: { color: TREE_COLORS.weather },
        symbolSize: 10, rec: { name: "weather stations", attrs: { note: `${stations.length} station(s)` } } }]
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
    <div class="check"><span class="${ok ? "ok" : "warn"}">${ok ? "✓" : "!"}</span> ${esc(label)}
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

// ---- RCx tab ----------------------------------------------------------------------------
// Views come from rcx-*.js modules (rcxView registry in rcx.js). One card per bound equip
// (scope "equip") or one per site (scope "site"); each card renders on its own so one
// failing view never blanks the tab.
let rcxRun = 0;
let rcxRangeChosen = false;          // set once the user touches #rcxRange
async function renderRcx() {
  const run = ++rcxRun;
  const catalog = await loadCatalog();
  const equips = model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site && (!scope.equip || idOf(e) === scope.equip));
  const hours = Number($("rcxRange").value) || 168;
  // Weekly views want a month of history; until the user picks a range themselves they get their own 672 h.
  const hoursFor = (view) => (!rcxRangeChosen && /^weekly-/.test(view.id) ? view.hours || hours : hours);
  const { ready, missing } = rcxPlan(equips, model, catalog);
  const cards = ready.flatMap(({ view, equips: eqs }) => (view.scope === "site" ? [{ view, eqs }] : eqs.map((eq) => ({ view, eqs: [eq] }))));
  $("nRcx").textContent = String(cards.length);
  $("nRcxMissing").textContent = String(missing.length);
  $("rcxMissing").innerHTML = missing.map(({ view, roles }) => `<tr><td>${esc(view.title)}<div class="sub">${esc(view.group)}</div></td>
    <td class="sub">${roles.length ? esc(roles.join(", ")) : `equipment kind: ${esc(view.kinds.join(" / "))}`}</td></tr>`).join("");
  const groups = [...new Set(cards.map((c) => c.view.group))];
  $("rcxBody").innerHTML = groups.map((g, gi) => `<section class="panel"><h2>${esc(g)}</h2><div class="rcx-grid">${
    cards.map((c, i) => [c, i]).filter(([c]) => c.view.group === g).map(([c, i]) => `<div class="rcx-card">
      <h3>${esc(c.view.title)}${c.view.scope === "equip" ? ` <span class="sub">· ${esc(c.eqs[0].name)}</span>` : ""}</h3>
      <div class="chart" id="rcx-${i}"></div><div class="sub note" id="rcx-note-${i}"></div></div>`).join("")}</div></section>`).join("")
    || `<section class="panel"><p class="sub">No RCx view has its inputs on the equips in scope yet — see "Not available here".</p></section>`;
  for (const [i, c] of cards.entries()) {
    if (run !== rcxRun) return;                      // a newer render (range/scope change) took over
    const el = $(`rcx-${i}`);
    try {
      const note = await c.view.render(el, rcxContext(c.view, c.eqs, hoursFor(c.view), model, catalog));
      el.classList.add("rendered");
      if (note) $(`rcx-note-${i}`).textContent = note;
      // Fault lanes (rcxWithFaultLane) add grids under the signals: give each lane its own room
      // instead of squeezing the signal plot.
      const inst = window.echarts && echarts.getInstanceByDom(el);
      const lanes = inst ? (inst.getOption().series || []).filter((s) => s.lineStyle && s.lineStyle.color === FAULT_LANE.lineStyle.color && s.step).length : 0;
      if (lanes) { el.style.height = `${el.clientHeight + 34 * lanes}px`; inst.resize(); }
      // Drew nothing (inputs present but no usable data / not enough equips): list it with the
      // other unavailable views instead of leaving an empty box on the page.
      if (!el.querySelector("canvas, svg")) {
        /** @type {HTMLElement} */ (el.closest(".rcx-card")).hidden = true;
        const who = c.view.scope === "equip" ? ` · ${c.eqs[0].name}` : "";
        $("rcxMissing").insertAdjacentHTML("beforeend", `<tr><td>${esc(c.view.title + who)}<div class="sub">${esc(c.view.group)}</div></td>
          <td class="sub">${esc(note || "no data in this range")}</td></tr>`);
        $("nRcxMissing").textContent = String($("rcxMissing").rows.length);
        $("nRcx").textContent = String(Number($("nRcx").textContent) - 1);
      }
    } catch (e) {
      $(`rcx-note-${i}`).textContent = `could not draw: ${e.message}`;
    }
  }
}

// ---- display units: imperial | si (units.js, localStorage "openfdd-units") -------------------
function syncUnitsToggle() {
  const si = unitSystem() === "si";
  $("unitsToggle").textContent = si ? "°C · SI" : "°F · imperial";
  $("unitsToggle").title = `Showing ${si ? "SI (°C, Pa, L/s)" : "imperial (°F, inH₂O, cfm)"} · click for ${si ? "imperial" : "SI"}. Calculations are always SI.`;
}

function setUnits(sys) {
  try { localStorage.setItem("openfdd-units", sys); } catch { /* storage blocked: stays imperial */ }
  syncUnitsToggle();
  renderCards();                 // unit labels sit in the card markup
  renderTab(activeTab);
}

// ---- tabs + live loop -----------------------------------------------------------------

function renderTab(name) {
  const errs = (e) => setLive(false, e.message);
  if (name === "overview") points.forEach((p, i) => updateCard(i, false));
  if (name === "charts") renderCharts().catch(errs);
  if (name === "fdd") renderFdd().catch(errs);
  if (name === "rcx") renderRcx().catch(errs);
  if (name === "points") { renderPoints(); if (selectedPoint) renderPointHistory().catch(errs); }
  if (name === "bacnet") renderBacnet().catch((e) => ($("bacHint").textContent = `BACnet server: ${e.message}`));
  if (name === "export") ofddExport.render({ model, scope });
  if (name === "model") renderModel();
  // Charts created while their tab was hidden have zero size until resized.
  requestAnimationFrame(ofddResizeAll);
}

function showTab(name) {
  if (!$(`tab-${name}`)) name = "overview";
  activeTab = name;
  document.querySelectorAll("#tabs button").forEach((/** @type {HTMLElement} */ b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${name}`));
  // Keep the tab in the URL hash so a link opens straight on it.
  if (location.hash !== `#${name}`) window.history.replaceState(null, "", `#${name}`);
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
    if (!sparkHist.has(u.uuid)) sparkHist.set(u.uuid, []);
    sparkHist.get(u.uuid).push([parseTs(v.ts), num]);
  }
  // NF pushes one batch per poll; coalesce the redraw.
  clearTimeout(uiTimer);
  uiTimer = setTimeout(() => {
    if (activeTab === "overview") changed.forEach((k) => updateCard(k, true));
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
      if (!sparkHist.has(p.uuid)) sparkHist.set(p.uuid, []);
      sparkHist.get(p.uuid).push([parseTs(f.latest.ts), v]);
      const i = points.indexOf(p);
      if (i >= 0) updateCard(i, activeTab === "overview");
    }
    statusPts = scopedSets().status;
    renderChips();
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
  $("sitePick").onchange = () => { scope.site = $("sitePick").value; scope.equip = ""; fillPickers(); applyScope().catch(showErr); };
  $("equipPick").onchange = () => { scope.equip = $("equipPick").value; applyScope().catch(showErr); };
  const chartErr = (e) => ($("chartHint").textContent = `could not load: ${e.message}`);
  $("gallery").onclick = (ev) => {
    const b = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("[data-chart]"));
    if (!b || b.dataset.chart === chartSel.id) return;
    chartSel.id = b.dataset.chart;
    chartSel.hours = 0;
    renderCharts().catch(chartErr);
  };
  $("chartRange").onclick = (ev) => {
    const h = Number(/** @type {HTMLElement} */ (ev.target).dataset.h);
    if (!h || h === chartSel.hours) return;
    chartSel.hours = h;
    renderCharts().catch(chartErr);
  };
  $("chartPick").onchange = () => { chartSel.point = $("chartPick").value; renderCharts().catch(chartErr); };
  $("histRange").onclick = (ev) => {
    const h = Number(/** @type {HTMLElement} */ (ev.target).dataset.h);
    if (!h) return;
    histHours = h;
    document.querySelectorAll("#histRange button").forEach((b) => b.classList.toggle("on", b === ev.target));
    renderPointHistory().catch((e) => setLive(false, e.message));
  };
  $("fddRunnableOnly").onchange = () => renderFdd().catch((e) => setLive(false, e.message));
  $("fddFaultedOnly").onchange = () => renderFdd().catch((e) => setLive(false, e.message));
  $("rcxRange").onchange = () => { rcxRangeChosen = true; renderRcx().catch((e) => setLive(false, e.message)); };

  // Click a rule (Faults or Rule inputs) → stacked signal plot + bottom fault lane (fdd-plots.js).
  const plotErr = (e) => ($("fddPlotNote").textContent = `could not draw: ${e.message}`);
  for (const id of ["fddRows", "fddResultRows"]) {
    $(id).onclick = (ev) => {
      const toggle = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("[data-expand]"));
      if (toggle) {
        const groupId = toggle.dataset.expand;
        fddExpandedGroups.has(groupId) ? fddExpandedGroups.delete(groupId) : fddExpandedGroups.add(groupId);
        renderScopedFddResults().catch(showErr);
        ev.stopPropagation(); return;
      }
      const tr = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("tr[data-rule]"));
      if (tr) showRulePlot(tr.dataset.rule, tr.dataset.equip).catch(plotErr);
    };
  }
  $("fddPlotClose").onclick = () => { $("fddPlotPanel").hidden = true; };
  $("fddRunNow").onclick = () => runFddNow().catch((e) => ($("fddRunState").textContent = `could not start: ${e.message}`));
  $("pointFilter").oninput = renderPoints;
  $("showUntagged").onchange = renderPoints;
  $("pointRows").onclick = (ev) => {
    const tr = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("tr[data-uuid]"));
    if (!tr) return;
    selectedPoint = tr.dataset.uuid;
    renderPoints();
    renderPointHistory().catch((e) => setLive(false, e.message));
  };
  $("unitsToggle").onclick = () => setUnits(unitSystem() === "si" ? "imperial" : "si");
  syncUnitsToggle();
  $("dlTtl").onclick = () => download(`${scope.site || "nf"}-haystack.ttl`, rdf.turtle, "text/turtle");
  $("dlJson").onclick = () => download(`${scope.site || "nf"}-haystack.json`, JSON.stringify({
    sites: model.sites, equips: model.equips, devices: model.devices,
    points: model.points.filter((p) => p.tags.length).map((p) => p.rec),
  }, null, 2), "application/json");
  // Theme switch: theme.js disposed every chart; draw the visible ones again.
  onThemeChange(() => { points.forEach((p, i) => updateCard(i, false)); renderTab(activeTab); });
}

async function main() {
  setInterval(() => ($("clock").textContent = new Date().toLocaleString()), 1000);
  wireControls();
  loadChartPref();
  await initAuth();
  model = await loadModel();
  scope.site = idOf(model.sites[0]);
  fillPickers();
  activeTab = (location.hash || "#overview").slice(1);
  if (!$(`tab-${activeTab}`)) activeTab = "overview";
  document.querySelectorAll("#tabs button").forEach((/** @type {HTMLElement} */ b) => b.classList.toggle("on", b.dataset.tab === activeTab));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === `tab-${activeTab}`));
  await applyScope();
  api("/api/v1/bacnet/local").then((l) => ($("nBacnet").textContent = (l.objects || []).length)).catch(() => {});
  setTimeout(liveLoop, LIVE_MS);
  // Re-sync sparklines every 10 min; redraw the open chart every 5 (both small requests).
  setInterval(async () => {
    await loadSparks().catch(() => {});
    if (activeTab === "overview") points.forEach((p, i) => updateCard(i, false));
  }, 10 * 60e3);
  setInterval(() => { if (activeTab === "charts" && !document.hidden) renderCharts().catch(() => {}); }, CHART_REFRESH_MS);
}

if (typeof document !== "undefined" && document.documentElement) main().catch(showErr);
