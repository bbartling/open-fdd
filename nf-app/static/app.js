// Open-FDD (Full edition) tabs on top of the shared dashboard shell. The shell (top bar, equip pickers, tab router, Overview,
// Charts, Points, BACnet Server, Model & RDF, live loop) is shared/static/app-core.js, loaded before this file; this file only
// adds what the Full edition has on top: FDD, RCx, Export, the display-units toggle and the Run FDD button.
// Everything renders from `model` (model.js), narrowed by the site picker and the equip picker inside each tab.

const fddExpandedGroups = new Set();

// ---- FDD tab --------------------------------------------------------------------------
// Which rules from the catalog each equip in scope can run (fdd.js binds inputs by tags).
const fddEquipsInScope = () => model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site && (!scope.equip || idOf(e) === scope.equip));
const renderScopedFddResults = () => renderFddResults(fddEquipsInScope(), fddCatalog?.sensor_sweep_roles);
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
  $("fddPlotTitle").textContent = `${ruleId} · ${equipLabel(equipRec)}`;
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
          <td><span class="rule-id">${esc(ruleId)}</span><div class="sub">${esc(role)}</div></td><td class="sub">${esc(sensorNameOf(p))}<div class="sub">${esc(equipName(equipId))}</div></td>
          <td class="${hot ? "warn" : status === "ok" ? "ok" : "sub"}">${esc(status)} · ${resultValue(p, v)}</td>
          <td class="sub">${esc(when(p))}${covered(p)}</td></tr>`);
      }
    }
  }
  for (const p of results.filter((x) => !sweeps.has(ruleRefOf(x)))) {
    const v = latestOf(p);
    const hot = has(p, "fault") && v > 0;
    rows.push(`<tr class="clickable" data-rule="${esc(ruleRefOf(p))}" data-equip="${esc(p.equipRef)}" title="plot this rule"><td><span class="rule-id">${esc(ruleRefOf(p))}</span></td><td class="sub">${esc(equipName(p.equipRef))}</td>
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
  const buckets = [...new Set(faults.flatMap((p) => filtered.get(p.uuid).map(([t]) => t)))].sort((a, b) => a - b);
  el.hidden = !buckets.length;
  if (!buckets.length) {
    rangeStatus.textContent = "No fault history in this range.";
    return;
  }
  // On normal rerenders keep the chart's DOM intact so ofddChart() can reuse its instance.
  const label = (p) => `${ruleRefOf(p)} · ${attrsOf(p).roleRef ? `${attrsOf(p).roleRef} · ${sensorNameOf(p)}` : equipName(p.equipRef)}`;
  el.style.height = `${Math.max(160, 26 * faults.length + 70)}px`;
  // Heatmaps need category axes: one column per history bucket.
  const units = (p) => dispUnit(p) || (attrsOf(p).fddOutput === "fault_hours" ? "h" : "%");
  const col = new Map(buckets.map((t, i) => [t, i]));
  const row = new Map(faults.map((p, i) => [p.uuid, i]));
  const axisTime = new Intl.DateTimeFormat(undefined, { timeZone: siteTz, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const detailTime = new Intl.DateTimeFormat(undefined, { timeZone: siteTz, year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  const unitGroups = new Map();
  for (const p of faults) {
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
    tooltip: { formatter: (x) => { const p = faults[x.value[1]], unit = units(p); return `${esc(label(p))}<br>${esc(detailTime.format(buckets[x.value[0]]))}: ${formatFaultNumber(x.value[2])} ${esc(unit)}`; } },
    grid: { left: 200, right: 20, top: 10, bottom: 70 },
    xAxis: { type: "category", data: buckets.map((t) => axisTime.format(t)), splitArea: { show: false } },
    yAxis: { type: "category", data: faults.map(label), inverse: true },
    visualMap: visualMaps,
    series: heatSeries,
  }, true);
}

// ---- RCx tab ----------------------------------------------------------------------------
// Views come from rcx-*.js modules (rcxView registry in rcx.js). One card per bound equip
// (scope "equip") or one per site (scope "site"); each card renders on its own so one
// failing view never blanks the tab.
let rcxRun = 0;
async function renderRcx() {
  const run = ++rcxRun;
  const catalog = await loadCatalog();
  const equips = model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site && (!scope.equip || idOf(e) === scope.equip));
  const rangeState = getChartRangeState("rcx"), siteTz = siteTimeZone();
  renderRangeControl($("rcxRangeControl"), { key: "rcx", state: rangeState, siteTz,
    onChange: () => {
      const pending = renderRcx(), requested = rcxRun;
      pending.catch((e) => { if (requested === rcxRun) $("rcxRangeStatus").textContent = `Could not load this range: ${e.message}`; });
    } });
  const rangePoints = model.points.filter((p) => p.siteRef === scope.site && has(p, "his")
    && (!scope.equip || p.equipRef === scope.equip || p.weatherStationRef));
  let range;
  try { range = await resolveChartSelection(rangePoints, rangeState, { siteTz }); }
  catch (e) {
    if (run === rcxRun) $("rcxRangeStatus").textContent = `Could not load this range: ${e.message}`;
    throw e;
  }
  if (run !== rcxRun) return;
  const hours = Math.max(1, (range.resolvedBounds.toMs - range.resolvedBounds.fromMs) / 3600e3);
  const hoursFor = (_view) => hours;
  $("rcxRangeStatus").textContent = "Loading history…";
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
      const note = await c.view.render(el, rcxContext(c.view, c.eqs, hoursFor(c.view), model, catalog, range, siteTz));
      if (run !== rcxRun) return;
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
      if (run === rcxRun) $(`rcx-note-${i}`).textContent = `could not draw: ${e.message}`;
    }
  }
  if (run === rcxRun) $("rcxRangeStatus").textContent = "";
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
