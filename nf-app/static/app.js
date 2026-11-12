// Open-FDD (Full edition) tabs on top of the shared dashboard shell. The shell (top bar, equip pickers, tab router, Overview,
// Charts, Points, BACnet Server, Model & RDF, live loop) is shared/static/app-core.js, loaded before this file; this file only
// adds what the Full edition has on top: FDD, RCx, Export, the display-units toggle and the Run FDD button.
// Everything renders from `model` (model.js), narrowed by the site picker and the equip picker inside each tab.

const fddExpandedGroups = new Set();

// ---- FDD tab --------------------------------------------------------------------------
// Which rules from the catalog each equip in the FDD tab can run (fdd.js binds inputs by tags). The tab has its own
// equipment filter (fddUi.equip, "" = all equipment); the header only picks the site.
const fddEquipsInScope = () => model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site && (!fddUi.equip || idOf(e) === fddUi.equip));
const renderScopedFddResults = () => renderFddResults(fddEquipsInScope(), fddCatalog?.sensor_sweep_roles);

/** Fill a tab's equipment picker ("" = all) from the site's equips; drops a selection that left the site. */
function fillEquipPicker(selectId, ui, allLabel) {
  const el = $(selectId);
  if (!el) return;
  const opts = fddEquipOptions(model, scope.site);
  if (ui.equip && !opts.some((o) => o.id === ui.equip)) ui.equip = "";
  el.innerHTML = `<option value="">${esc(allLabel)}</option>${opts.map((o) => `<option value="${esc(o.id)}"${o.id === ui.equip ? " selected" : ""}>${esc(o.label)}</option>`).join("")}`;
}

let viewTabsWired = false;
/** One-time wiring of the FDD / RCx tab controls (equipment filter, heat-map rows, "AHU on"). */
function wireViewTabs() {
  if (viewTabsWired) return;
  viewTabsWired = true;
  const fail = (e) => setLive(false, e.message);
  const on = (id, event, fn) => { const el = $(id); if (el) el[event] = fn; };
  on("fddEquip", "onchange", (e) => { fddUi.equip = e.target.value; renderFdd().catch(fail); });
  on("fddHeatAll", "onchange", (e) => { fddUi.heatAll = e.target.checked; renderScopedFddResults().catch(fail); });
  on("rcxEquip", "onchange", (e) => { rcxUi.equip = e.target.value; renderRcx().catch(fail); });
  on("rcxAhuOn", "onclick", (e) => { rcxUi.ahuOn = e.currentTarget.getAttribute("aria-pressed") !== "true"; renderRcx().catch(fail); });
}

async function renderFdd() {
  const catalog = await loadCatalog();
  wireViewTabs();
  fillEquipPicker("fddEquip", fddUi, "All equipment");
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
      <td>${fddRuleCellHtml(r.rule)}<div class="sub">${esc(r.rule.description)}</div></td>
      <td class="sub">${esc((r.equip.attrs || {}).dis || r.equip.name)}</td>
      <td><div class="tags">${r.required.map((x) => chip(x, r.bound[x], false)).join("")}${r.optional.map((x) => chip(x, r.bound[x], true)).join("")}</div></td>
      <td>${r.runnable ? `<span class="ok">✓ can run</span>`
        : !r.pointInputs ? `<span class="sub">uses utility/meter data, not points</span>`
        : `<span class="warn">needs ${esc(r.missing.join(", "))}</span>`}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="sub">No rules apply to the equips in scope.</td></tr>`;
  renderViewTab("fdd").catch((e) => setLive(false, e.message));      // FDD charts load in parallel with the fault table
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
  const read = ++fddPlotRead;
  const catalog = await loadCatalog();
  const equipRec = model.equips.find((e) => idOf(e) === equipId && (e.attrs || {}).siteRef === scope.site)
    || model.equips.find((e) => idOf(e) === equipId);
  const row = equipRec && equipRules(equipRec, model, catalog).find((r) => r.rule.id === ruleId);
  if (!row) return;
  const siteTz = siteTimeZone(), rangeState = getChartRangeState("rulePlot");
  const historyPoints = model.points.filter((p) => p.siteRef === scope.site && p.equipRef === equipId && has(p, "his"));
  renderRangeControl($("fddPlotRangeControl"), { key: "rulePlot", state: rangeState, siteTz,
    onChange: () => showRulePlot(ruleId, equipId).catch((e) => ($("fddPlotRangeStatus").textContent = `Could not load this range: ${e.message}`)) });
  $("fddPlotPanel").hidden = false;
  $("fddPlotTitle").innerHTML = `${fddRuleCellHtml(row.rule)} <span class="sub">· ${esc(equipLabel(equipRec))}</span>`;
  $("fddPlotNote").textContent = row.rule.description || "";
  $("fddPlotRangeStatus").textContent = "Resolving range…";
  $("fddPlotPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  let range;
  try { range = await resolveChartSelection(historyPoints, rangeState, { siteTz }); }
  catch (e) {
    if (read === fddPlotRead) $("fddPlotRangeStatus").textContent = `Could not load this range: ${e.message}`;
    throw e;
  }
  if (read !== fddPlotRead) return;
  const hours = Math.max(1, (range.resolvedBounds.toMs - range.resolvedBounds.fromMs) / 3600e3);
  $("fddPlotRangeStatus").textContent = "Loading history…";
  const note = await fddRulePlot($("fddPlot"), { rule: row.rule, equipRec, bound: row.bound,
    resultPoint: rcxResultPoint(model, equipRec, ruleId), model, hours, range, siteTz });
  if (read !== fddPlotRead) return;
  $("fddPlot").classList.add("rendered");
  $("fddPlotRangeStatus").textContent = "";
  if (note) $("fddPlotNote").textContent = note;
}

// Result points the FDD hook writes: markers fdd + fault|metric, ruleRef, equipRef.
const ruleRefOf = (p) => (p.rec.attrs || {}).ruleRef || "";
function formatFaultNumber(value) {
  const numeric = value == null || String(value).trim() === "" ? NaN : Number(value);
  return Number.isFinite(numeric) ? String(Number(numeric.toFixed(2))) : "–";
}
const fddResults = (equipIds) => model.points
  .filter((p) => has(p, "fdd") && ruleRefOf(p) && equipIds.includes(p.equipRef)
    && (!scope.site || p.siteRef === scope.site || (!p.siteRef && model.equips.filter((e) => idOf(e) === p.equipRef).length === 1)))
  .sort((a, b) => (latestOf(b) ?? 0) - (latestOf(a) ?? 0) || ruleRefOf(a).localeCompare(ruleRefOf(b)));

let faultHistoryRead = 0;
let fddPlotRead = 0;

/** Faults panel: latest result rows and the selected range of each fault lane. */
async function renderFddResults(equips, sweepRoles = {}) {
  const read = ++faultHistoryRead;
  const rangeStatus = $("fddRangeStatus");
  const el = $("fddLanes");
  rangeStatus.textContent = "";
  el.removeAttribute("aria-busy");
  const results = fddResults(equips.map(idOf));
  $("fddResultsPanel").hidden = !results.length;
  if (!results.length) return;
  const siteTz = siteTimeZone();
  const state = getChartRangeState("faults");
  renderRangeControl($("fddRangeControl"), {
    key: "faults", state, siteTz, onChange: () => renderScopedFddResults().catch(showErr),
  });
  const equipName = (id) => {
    const e = model.equips.find((x) => idOf(x) === id && (x.attrs || {}).siteRef === scope.site)
      || model.equips.find((x) => idOf(x) === id);
    return (e && ((e.attrs || {}).dis || e.name)) || id;
  };
  const attrsOf = (p) => p.rec.attrs || {};
  const covered = (p) => {
    const hours = formatFaultNumber(attrsOf(p).fddCoverageHours);
    return hours === "–" ? "" : ` · ${esc(hours)} h covered`;
  };
  const resultValue = (p, value) => {
    const unit = dispUnit(p), display = dispVal(p, value);
    return `${unit === "h" || unit === "%" ? formatFaultNumber(display) : fmt(display)} ${esc(unit)}`;
  };
  const when = (p) => {
    const ts = attrsOf(p).fddLastRun || (p.latest && p.latest.ts);
    return ts ? new Date(parseTs(ts)).toLocaleString(undefined, { timeZone: siteTz }) : "–";
  };
  const sensorNameOf = (p) => {
    const ref = attrsOf(p).sensorRef;
    const input = ref && model.points.find((x) => x.uuid === ref && has(x, "point"));
    return input ? (input.dis || input.name) : (p.name || p.dis);
  };
  const statusOf = (p) => attrsOf(p).fddStatus || (latestOf(p) == null ? "not-assessed" : has(p, "fault") && latestOf(p) > 0 ? "fault" : "ok");
  const faulted = (p) => statusOf(p) === "fault" || (statusOf(p) !== "not-assessed" && statusOf(p) !== "stale" && has(p, "fault") && latestOf(p) > 0);
  const ruleCell = (id) => fddRuleCellHtml(fddRuleOf(fddCatalog, id));
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
          <td>${sensors.length ? `<button class="fdd-expand" type="button" data-expand="${esc(groupId)}" aria-expanded="${fddExpandedGroups.has(groupId)}" title="Show sensor results">${fddExpandedGroups.has(groupId) ? "▾" : "▸"}</button> ` : ""}${ruleCell(ruleId)}<div class="sub">equipment summary</div></td>
          <td class="sub">${esc(equipName(equipId))}</td><td class="${hot ? "warn" : status === "ok" ? "ok" : "sub"}">${esc(status)} · ${resultValue(summary, v)}</td>
          <td class="sub">${esc(when(summary))}${covered(summary)}</td></tr>`);
      }
      const faultedOnly = $("fddFaultedOnly")?.checked;
      for (const p of sensors.sort((a, b) => Number(faulted(b)) - Number(faulted(a)) || String(attrsOf(a).roleRef || "").localeCompare(String(attrsOf(b).roleRef || "")))) {
        const v = latestOf(p), status = statusOf(p), hot = faulted(p), groupId = `${ruleId}|${equipId}`;
        if (faultedOnly && !hot) continue;
        const role = attrsOf(p).roleRef || "sensor";
        const hidden = !fddExpandedGroups.has(groupId);
        rows.push(`<tr class="clickable fdd-sensor-row" data-rule="${esc(ruleId)}" data-equip="${esc(equipId)}" data-sensor="${esc(attrsOf(p).sensorRef || "")}"${hidden ? " hidden" : ""}>
          <td>${ruleCell(ruleId)}<div class="sub">${esc(role)}</div></td><td class="sub">${esc(sensorNameOf(p))}<div class="sub">${esc(equipName(equipId))}</div></td>
          <td class="${hot ? "warn" : status === "ok" ? "ok" : "sub"}">${esc(status)} · ${resultValue(p, v)}</td>
          <td class="sub">${esc(when(p))}${covered(p)}</td></tr>`);
      }
    }
  }
  for (const p of results.filter((x) => !sweeps.has(ruleRefOf(x)))) {
    const v = latestOf(p);
    const hot = has(p, "fault") && v > 0;
    rows.push(`<tr class="clickable" data-rule="${esc(ruleRefOf(p))}" data-equip="${esc(p.equipRef)}" title="plot this rule"><td>${ruleCell(ruleRefOf(p))}</td><td class="sub">${esc(equipName(p.equipRef))}</td>
      <td class="${hot ? "warn" : "ok"}">${resultValue(p, v)}</td><td class="sub">${esc(when(p))}</td></tr>`);
  }
  $("fddResultRows").innerHTML = rows.join("");
  const sweepSensorPoints = results.filter((p) => /^SV-/.test(ruleRefOf(p)) && (attrsOf(p).fddSummary === "sensor" || attrsOf(p).sensorRef));
  const heatmapRows = results.filter((p) => has(p, "fault") && !sweepSensorPoints.some((s) => s.equipRef === p.equipRef && ruleRefOf(s) === ruleRefOf(p) && (attrsOf(p).fddSummary === "equip" || !attrsOf(p).fddSummary)));
  el.hidden = !heatmapRows.length;
  const showingHistoryError = el.classList.contains("history-error");
  if (showingHistoryError) {
    el.textContent = "";
    el.removeAttribute("role");
    el.classList.remove("history-error");
  }
  if (!heatmapRows.length) return;
  rangeStatus.textContent = "Loading fault history…";
  el.setAttribute("aria-busy", "true");
  let history;
  try {
    history = await fetchRange(heatmapRows, state, { method: "MAX", minWindowSec: 300, siteTz });
  } catch (e) {
    if (read !== faultHistoryRead) return;
    echarts.getInstanceByDom(el)?.dispose();
    el.style.height = "";
    el.textContent = `Fault history unavailable: ${e?.message || e}`;
    el.setAttribute("role", "alert");
    el.classList.add("history-error");
    return;
  } finally {
    if (read === faultHistoryRead) {
      el.removeAttribute("aria-busy");
      rangeStatus.textContent = "";
    }
  }
  if (read !== faultHistoryRead) return;
  const { series, windowSec } = history;
  const filtered = new Map(heatmapRows.map((p) => [p.uuid,
    rcxCurrentOutputSeries(p, series.get(p.uuid) || [], windowSec).filter(([, value]) => Number.isFinite(value))]));
  const faults = heatmapRows.filter((p) => {
    const { sensorRef, roleRef } = attrsOf(p);
    const assessable = sweepRoles[ruleRefOf(p)];
    const excluded = sensorRef && roleRef && assessable && !assessable.includes(roleRef);
    return filtered.get(p.uuid).length > 0 || (statusOf(p) !== "stale" && !excluded);
  });
  // Which faults happen most: rows sorted by fault time; by default only the top rows (or the selected equip's), the
  // "all rows" box widens it. Fault time (minutes) = fault hours, or fault % of each bucket.
  const faultMinutes = (p) => filtered.get(p.uuid).reduce((a, [, v]) => a + (attrsOf(p).fddOutput === "fault_hours" ? v * 60 : (v / 100) * (windowSec / 60)), 0);
  const heat = fddHeatRows(faults.map((p) => ({ key: p.uuid, p, equip: p.equipRef, faultTime: faultMinutes(p) })), { selectedEquip: fddUi.equip, showAll: fddUi.heatAll });
  const shown = heat.rows.map((r) => r.p);
  const heatNote = $("fddHeatNote");
  if (heatNote) heatNote.textContent = heat.trimmed ? `Showing the ${shown.length} most-faulted of ${heat.total} rows (sorted by fault time). Tick "all rows" or pick an equipment to see more.` : `${shown.length} row${shown.length === 1 ? "" : "s"}, sorted by fault time.`;
  const buckets = [...new Set(shown.flatMap((p) => filtered.get(p.uuid).map(([t]) => t)))].sort((a, b) => a - b);
  el.hidden = !buckets.length;
  if (!buckets.length) {
    rangeStatus.textContent = "No fault history in this range.";
    return;
  }
  // On normal rerenders keep the chart's DOM intact so ofddChart() can reuse its instance.
  const whoOf = (p) => (attrsOf(p).roleRef ? `${attrsOf(p).roleRef} · ${sensorNameOf(p)}` : equipName(p.equipRef));
  const titleOf = (p) => fddRuleTitle(fddRuleOf(fddCatalog, ruleRefOf(p)));
  const label = (p) => fddRuleRich(titleOf(p), ruleRefOf(p), whoOf(p));
  el.style.height = `${Math.max(160, 26 * shown.length + 70)}px`;
  // Heatmaps need category axes: one column per history bucket.
  const units = (p) => dispUnit(p) || (attrsOf(p).fddOutput === "fault_hours" ? "h" : "%");
  const col = new Map(buckets.map((t, i) => [t, i]));
  const row = new Map(shown.map((p, i) => [p.uuid, i]));
  const axisTime = new Intl.DateTimeFormat(undefined, { timeZone: siteTz, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const detailTime = new Intl.DateTimeFormat(undefined, { timeZone: siteTz, year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  const unitGroups = new Map();
  for (const p of shown) {
    const unit = units(p);
    if (!unitGroups.has(unit)) unitGroups.set(unit, []);
    unitGroups.get(unit).push(p);
  }
  const unitEntries = [...unitGroups];
  const heatSeries = unitEntries.map(([unit, points]) => ({ type: "heatmap", name: unit, data: points.flatMap((p) =>
    filtered.get(p.uuid).map(([t, v]) => [col.get(t), row.get(p.uuid), v])) }));
  const visualMaps = unitEntries.map(([unit, points], seriesIndex) => {
    const max = unit === "h" ? Math.max(1, ...points.map((p) => Number(attrsOf(p).fddWindowHours) || 24)) : 100;
    return { min: 0, max, seriesIndex, dimension: 2, orient: "horizontal", left: `${Math.round((seriesIndex + 1) * 100 / (unitEntries.length + 1))}%`, bottom: 0, itemHeight: 100,
      text: [`${formatFaultNumber(max)} ${unit}`, `0 ${unit}`], inRange: { color: ["rgba(239,68,68,0.05)", FAULT_LANE.lineStyle.color] } };
  });
  ofddChart(el).setOption({
    tooltip: { formatter: (x) => { const p = shown[x.value[1]], unit = units(p); return `${esc(titleOf(p))} ${fddRuleBadgeHtml(ruleRefOf(p))} · ${esc(whoOf(p))}<br>${esc(detailTime.format(buckets[x.value[0]]))}: ${formatFaultNumber(x.value[2])} ${esc(unit)}`; } },
    grid: { left: 10, right: 20, top: 10, bottom: 70, containLabel: true },
    xAxis: { type: "category", data: buckets.map((t) => axisTime.format(t)), splitArea: { show: false } },
    yAxis: { type: "category", data: shown.map(label), inverse: true, axisLabel: { rich: FDD_RULE_RICH, width: 460, overflow: "truncate" } },
    visualMap: visualMaps,
    series: heatSeries,
  }, true);
}

// ---- RCx tab ----------------------------------------------------------------------------
// ---- RCx and FDD chart tabs ----------------------------------------------------------------
// Both tabs draw rcxView() cards from rcx-*.js / fdd-plots.js; a view's `tab` says where it lives ("rcx" default, "fdd").
// Each tab has its own equipment filter. "" = all devices: fleet analytics (pies, rankings, the all-zones band) are drawn
// there and headline views (view.headline) go in a row at the top. One device selected: only that device's own charts.
// Each card renders on its own so one failing view never blanks the tab.
const viewTabRuns = { rcx: 0, fdd: 0 };
const VIEW_TABS = {
  rcx: { ui: () => rcxUi, body: "rcxBody", range: "rcxRangeControl", status: "rcxRangeStatus", key: "rcx", mode: "rcxMode", kpis: "rcxKpis" },
  fdd: { ui: () => fddUi, body: "fddBody", range: "fddChartsRangeControl", status: "fddChartsRangeStatus", key: "fddCharts", mode: "fddMode", kpis: null },
};

/**
 * "AHU on" button + the VAV -> AHU note. The filter defaults to ON whenever a feeding AHU is known (airRef, or the site's only
 * AHU assumed) and to OFF when the feed is unknown; a click makes the choice explicit (rcxUi.ahuOn true/false).
 * Returns the effective setting.
 */
function renderAhuControl(siteEquips, catalog) {
  const btn = $("rcxAhuOn"), note = $("rcxAhuNote");
  const kinds = (e) => equipKinds(e, catalog);
  const feeds = siteEquips.length ? rcxAirFeedMap(siteEquips, kinds) : new Map();
  const on = rcxUi.ahuOn == null ? feeds.size > 0 : !!rcxUi.ahuOn;
  if (!btn || !note) return on;
  const hasAhu = siteEquips.some((e) => kinds(e).includes("ahu"));
  btn.hidden = note.hidden = !hasAhu;
  if (!hasAhu) return on;
  btn.setAttribute("aria-pressed", String(on));
  btn.classList.toggle("active", on);
  const vavs = siteEquips.filter((e) => kinds(e).includes("vav"));
  const linked = [...feeds.values()].filter((f) => !f.assumed).length, assumed = feeds.size - linked;
  note.textContent = (on ? "Only times the feeding AHU's fan is running" : "All times") + (rcxUi.ahuOn == null ? (on ? " (on because the feeding AHU is known). " : " (the feeding AHU is unknown). ") : ". ")
    + (vavs.length ? `VAV → AHU: ${linked} by airRef${assumed ? `, ${assumed} assumed (the site has one AHU and no airRef)` : ""}${vavs.length - feeds.size ? `, ${vavs.length - feeds.size} unknown` : ""}.` : "");
  return on;
}

async function renderViewTab(tab) {
  const T = VIEW_TABS[tab], ui = T.ui(), run = ++viewTabRuns[tab];
  const catalog = await loadCatalog();
  wireViewTabs();
  const siteEquips = model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site);
  fillEquipPicker(`${tab}Equip`, ui, tab === "rcx" ? "All devices" : "All equipment");
  const equips = siteEquips.filter((e) => !ui.equip || idOf(e) === ui.equip), single = !!ui.equip;
  const ahuOn = tab === "rcx" ? renderAhuControl(siteEquips, catalog) : false;
  const rangeState = getChartRangeState(T.key), siteTz = siteTimeZone();
  renderRangeControl($(T.range), { key: T.key, state: rangeState, siteTz,
    onChange: () => {
      const pending = renderViewTab(tab), requested = viewTabRuns[tab];
      pending.catch((e) => { if (requested === viewTabRuns[tab]) $(T.status).textContent = `Could not load this range: ${e.message}`; });
    } });
  const rangePoints = model.points.filter((p) => p.siteRef === scope.site && has(p, "his")
    && (!ui.equip || p.equipRef === ui.equip || p.weatherStationRef));
  let range;
  try { range = await resolveChartSelection(rangePoints, rangeState, { siteTz }); }
  catch (e) {
    if (run === viewTabRuns[tab]) $(T.status).textContent = `Could not load this range: ${e.message}`;
    throw e;
  }
  if (run !== viewTabRuns[tab]) return;
  const hours = Math.max(1, (range.resolvedBounds.toMs - range.resolvedBounds.fromMs) / 3600e3);
  $(T.status).textContent = "Loading history…";
  const { ready, missing } = rcxPlan(equips, model, catalog, { tab, single });
  const cards = ready.flatMap(({ view, equips: eqs }) => (view.scope === "site" ? [{ view, eqs }] : eqs.map((eq) => ({ view, eqs: [eq] }))));
  const groupOf = (c) => (c.view.groupOf ? c.view.groupOf(c.eqs) : c.view.group);
  if (tab === "rcx") {
    $("nRcx").textContent = String(cards.length);
    $("nRcxMissing").textContent = String(missing.length);
    $("rcxMissing").innerHTML = missing.filter(({ view }) => !view.tabHidden).map(({ view, roles }) => `<tr><td>${esc(view.title)}<div class="sub">${esc(view.group)}</div></td>
      <td class="sub">${roles.length ? esc(roles.join(", ")) : `equipment kind: ${esc(view.kinds.join(" / "))}`}</td></tr>`).join("");
  }
  if ($(T.mode)) {
    const who = single ? (fddEquipOptions(model, scope.site).find((o) => o.id === ui.equip) || { label: ui.equip }).label : "";
    $(T.mode).textContent = tab === "fdd"
      ? (single ? `Single equipment: ${who}.` : "All equipment in scope.")
      : (single ? `Single device: ${who}. Only this device's own charts are shown; fleet analytics are in the all-devices view.`
        : "All devices: fleet analytics and one chart per view across every device.");
  }
  const sections = [];
  if (tab === "rcx" && cards.some((c) => c.view.headline)) sections.push({ title: "Headline", cls: " rcx-headline", cards: cards.filter((c) => c.view.headline) });
  const rest = cards.filter((c) => tab !== "rcx" || !c.view.headline);
  for (const g of [...new Set(rest.map(groupOf))]) sections.push({ title: g, cls: "", cards: rest.filter((c) => groupOf(c) === g) });
  $(T.body).innerHTML = sections.map((sec) => `<section class="panel${sec.cls}"><h2>${esc(sec.title)}</h2><div class="rcx-grid${tab === "fdd" ? " one-col" : ""}">${
    sec.cards.map((c) => `<div class="rcx-card${c.view.wide ? " rcx-wide" : ""}">
      <h3>${esc(c.view.title)}${c.view.scope === "equip" ? ` <span class="sub">· ${esc(c.eqs[0].name)}</span>` : ""}</h3>
      <div class="chart" id="${tab}-${cards.indexOf(c)}"></div><div class="sub note" id="${tab}-note-${cards.indexOf(c)}"></div></div>`).join("")}</div></section>`).join("")
    || `<section class="panel"><p class="sub">No ${tab === "rcx" ? "RCx" : "FDD"} chart has its inputs on the equipment in scope yet.</p></section>`;
  const kpis = [], maskCache = new Map();
  if (T.kpis && $(T.kpis)) $(T.kpis).innerHTML = "";
  for (const [i, c] of cards.entries()) {
    if (run !== viewTabRuns[tab]) return;                      // a newer render (range/scope change) took over
    const el = $(`${tab}-${i}`);
    try {
      const ctx = rcxContext(c.view, c.eqs, hours, model, catalog, range, siteTz, { ahuOn, kpis, maskCache, dropTitle: tab === "rcx" });
      const note = await c.view.render(el, ctx);
      if (run !== viewTabRuns[tab]) return;
      el.classList.add("rendered");
      if (note) $(`${tab}-note-${i}`).textContent = note;
      if (T.kpis && $(T.kpis) && kpis.length) $(T.kpis).innerHTML = rcxKpiHtml(kpis);
      // Fault lanes (rcxWithFaultLane) add grids under the signals: give each lane its own room instead of squeezing the
      // signal plot, unless the view already sized its chart for them (fdd-plots.js marks those with data-sized).
      const inst = window.echarts && echarts.getInstanceByDom(el);
      const lanes = inst && !(el.dataset && el.dataset.sized) ? (inst.getOption().series || []).filter((s) => s.lineStyle && s.lineStyle.color === FAULT_LANE.lineStyle.color && s.step).length : 0;
      if (lanes) { el.style.height = `${el.clientHeight + 34 * lanes}px`; inst.resize(); }
      // Drew nothing (inputs present but no usable data / not enough equips): list it with the other unavailable
      // views instead of leaving an empty box on the page.
      if (!el.querySelector("canvas, svg")) {
        /** @type {HTMLElement} */ (el.closest(".rcx-card")).hidden = true;
        if (tab === "rcx") {
          const who = c.view.scope === "equip" ? ` · ${c.eqs[0].name}` : "";
          $("rcxMissing").insertAdjacentHTML("beforeend", `<tr><td>${esc(c.view.title + who)}<div class="sub">${esc(groupOf(c))}</div></td>
            <td class="sub">${esc(note || "no data in this range")}</td></tr>`);
          $("nRcxMissing").textContent = String($("rcxMissing").rows.length);
          $("nRcx").textContent = String(Number($("nRcx").textContent) - 1);
        }
      }
    } catch (e) {
      if (run === viewTabRuns[tab]) $(`${tab}-note-${i}`).textContent = `could not draw: ${e.message}`;
    }
  }
  if (run === viewTabRuns[tab]) $(T.status).textContent = "";
}

function renderRcx() { return renderViewTab("rcx"); }

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

// ---- registering this edition's tabs with the shell ---------------------------------------
ofddTabs.fdd = () => renderFdd();
ofddTabs.rcx = () => renderRcx();
ofddTabs.export = () => ofddExport.render({ model, scope });
for (const tab of ["fdd", "rcx", "export"]) ofddEquipScoped.add(tab);     // these get an equip picker too

ofddWire.push(() => {
  $("fddRunnableOnly").onchange = () => renderFdd().catch((e) => setLive(false, e.message));
  $("fddFaultedOnly").onchange = () => renderFdd().catch((e) => setLive(false, e.message));

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
  $("unitsToggle").onclick = () => setUnits(unitSystem() === "si" ? "imperial" : "si");
  syncUnitsToggle();
});

if (typeof document !== "undefined" && document.documentElement) main().catch(showErr);
