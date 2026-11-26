// Open-FDD (Full edition) tabs on top of the shared dashboard shell. The shell (top bar, equip pickers, tab router, Overview,
// Charts, Points, BACnet Server, Model & RDF, live loop) is shared/static/app-core.js, loaded before this file; this file only
// adds what the Full edition has on top: FDD, RCx, Export, the display-units toggle and the Run FDD button.
// Everything renders from `model` (model.js), narrowed by the site picker and the equip picker inside each tab.

const fddExpandedGroups = new Set();

// ---- FDD tab --------------------------------------------------------------------------
// Which rules from the catalog the selected equipment can run (fdd.js binds inputs by tags) and what the hook found. The
// tab has its own equipment picker (always ONE equipment, no "all"); the top bar only picks the site. Layout: a summary
// strip (Faults / Insufficient / Metrics / Pass / Skipped chips that filter the list), the rules faults-first with metric,
// pass and skipped behind "show all", one rule open at a time (plot, SI thresholds, inputs), tuning in a side drawer, and the rest
// (heat map, FDD charts, the rule-input table) under "More". Equipment, filter and open rule are kept in the URL.
const tabEquip = () => (scope.equip && scope.equip !== WEATHER_SCOPE ? scope.equip : "");
const fddEquipsInScope = () => (tabEquip() ? model.equips.filter((e) => (e.attrs || {}).siteRef === scope.site && idOf(e) === tabEquip()) : []);
const fddView = { restoreOpen: false, filter: "", showAll: false, open: /** @type {{ruleId: string, equipId: string}|null} */ (null), urlRead: false, entries: /** @type {any[]} */ ([]) };
const FDD_STATUS_ONE = { fault: "Fault", metric: "Metric", pass: "Pass", skipped: "Skipped", insufficient: "Insufficient data" };

/** One input chip: role -> bound point (got), optional and missing (opt), required and missing (miss). */
function fddChip(role, pts, optional) {
  const cls = pts.length ? "got" : optional ? "opt" : "miss";
  const title = pts.length ? pts.map((p) => p.dis).join(" · ") : optional ? "optional, not found" : "required, not found";
  const label = pts.length ? `${role} → ${pts[0].name}${pts.length > 1 ? ` (+${pts.length - 1})` : ""}` : role;
  return `<span class="tag ${cls} ${optional ? "opt" : ""}" title="${esc(title)}">${esc(label)}</span>`;
}

/** Keep equipment, filter and the open rule in the page URL (the window ranges are kept there by charts.js). */
function fddWriteUrl() {
  if (typeof location === "undefined" || activeTab !== "fdd") return;
  const href = fddUrlWith(location.href, { equip: tabEquip(), rule: fddView.open ? fddView.open.ruleId : "", filter: fddView.filter });
  if (href !== location.href) window.history.replaceState(null, "", href);
}

function renderFddSummary(entries) {
  const s = fddSummary(entries);
  const windows = entries.map((e) => Number(((e.result && e.result.rec && e.result.rec.attrs) || {}).fddWindowHours)).filter(Number.isFinite);
  const win = windows.length ? `${formatFaultNumber(Math.max(...windows))} h window` : "no FDD run yet";
  const eq = model.equips.find((e) => idOf(e) === tabEquip());
  $("fddSummary").innerHTML = FDD_STATUSES.map((k) => `<button type="button" class="fdd-chip ${k}${fddView.filter === k ? " on" : ""}" data-filter="${k}" aria-pressed="${fddView.filter === k}">
      <b>${s[k].count}</b> ${FDD_STATUS_LABELS[k]}${k === "fault" ? ` <span class="sub">· ${formatFaultNumber(s[k].hours)} fault h</span>` : ""}</button>`).join("")
    + `<span class="hint">${esc(eq ? equipLabel(eq) : "pick an equipment")} · ${esc(win)}</span>`;
}

function renderFddList(entries) {
  const panel = $("fddPlotPanel"), list = $("fddList");
  if (panel && panel.parentElement !== $("tab-fdd")) $("tab-fdd").appendChild(panel);   // keep the open-rule panel alive across redraws
  if (fddView.restoreOpen) {
    const restored = entries.find((e) => fddView.open && e.ruleId === fddView.open.ruleId && e.equipId === fddView.open.equipId);
    if (restored && !fddView.filter && ["metric", "pass", "skipped"].includes(restored.status)) fddView.showAll = true;
    fddView.restoreOpen = false;
  }
  const { shown, hidden } = fddVisibleEntries(entries, fddView);
  const all = $("fddShowAll");
  all.hidden = !!fddView.filter || (!hidden && !fddView.showAll);
  all.textContent = fddView.showAll ? "faults first only" : `show all (${hidden} more: metric, pass and skipped)`;
  all.setAttribute("aria-pressed", String(fddView.showAll));
  const isOpen = (e) => !!fddView.open && fddView.open.ruleId === e.ruleId && fddView.open.equipId === e.equipId;
  list.innerHTML = shown.map((e) => `<div class="fdd-item ${e.status}${isOpen(e) ? " open" : ""}" data-status="${e.status}" data-rule="${esc(e.ruleId)}" data-equip="${esc(e.equipId)}">
      <button type="button" class="fdd-row" aria-expanded="${isOpen(e)}">
        <span class="fdd-badge ${e.status}">${esc(FDD_STATUS_ONE[e.status])}</span>
        <span class="fdd-title">${fddRuleCellHtml(e.rule)} <span class="sub">${esc(e.rule.description || "")}</span></span>
        <span class="fdd-hours">${e.status === "fault" || e.status === "pass" ? `${formatFaultNumber(e.faultHours ?? 0)} h` : e.status === "metric" ? esc(fddMetricText(e, unitSystem())) : ""}</span>
        ${e.reason ? `<span class="fdd-reason">${esc(e.reason)}</span>` : ""}
      </button><div class="fdd-slot"></div></div>`).join("")
    || `<p class="sub">${!tabEquip() ? "Pick an equipment to see its rules." : fddView.filter ? `No ${esc(FDD_STATUS_LABELS[fddView.filter].toLowerCase())} rules on this equipment.` : "No faults or data problems on this equipment. Use show all for metric, passing and skipped rules."}</p>`;
  const openItem = shown.find(isOpen);
  if (fddView.open && !openItem) closeRulePlot();
  else if (openItem) {
    const slot = list.querySelector(`.fdd-item.open .fdd-slot`);
    if (slot && panel) slot.appendChild(panel);
    if (!activeRulePlot || activeRulePlot.ruleId !== openItem.ruleId || activeRulePlot.equipId !== openItem.equipId || panel.hidden) {
      showRulePlot(openItem.ruleId, openItem.equipId).catch((err) => ($("fddPlotNote").textContent = `could not draw: ${err.message}`));
    }
  }
}
const renderScopedFddResults = () => renderFddResults(fddEquipsInScope(), fddCatalog?.sensor_sweep_roles);

let viewTabsWired = false;
/** One-time wiring of the FDD / RCx tab controls (equipment filter, heat-map rows, "AHU on"). */
function wireViewTabs() {
  if (viewTabsWired) return;
  viewTabsWired = true;
  const fail = (e) => setLive(false, e.message);
  const on = (id, event, fn) => { const el = $(id); if (el) el[event] = fn; };
  on("fddMore", "ontoggle", () => { if (/** @type {HTMLDetailsElement} */ (/** @type {unknown} */ ($("fddMore"))).open) requestAnimationFrame(ofddResizeAll); });
  on("fddHeatAll", "onchange", (e) => { fddUi.heatAll = e.target.checked; renderScopedFddResults().catch(fail); });
  on("rcxAhuOn", "onclick", (e) => { rcxUi.ahuOn = e.currentTarget.getAttribute("aria-pressed") !== "true"; renderRcx().catch(fail); });
}

async function renderFdd() {
  const catalog = await loadCatalog();
  wireViewTabs();
  if (!fddView.urlRead) {            // first render: equipment, filter and open rule from the URL (reload / shared link)
    fddView.urlRead = true;
    const u = fddUrlState();
    if (u.equip && u.equip !== scope.equip && equipChoices(model, scope.site).some((c) => c.value === u.equip)) { scope.equip = u.equip; fillPickers(); }
    fddView.filter = u.filter;
    if (u.rule) { fddView.open = { ruleId: u.rule, equipId: u.equip || tabEquip() }; fddView.restoreOpen = true; }
  }
  const equips = fddEquipsInScope();
  if (fddView.open && !equips.some((e) => idOf(e) === fddView.open.equipId)) fddView.open = null;
  // The rule plot and its Tuners belong to one equipment: when the selection moves off it, close them (#1613).
  if (activeRulePlot && !equips.some((e) => idOf(e) === activeRulePlot.equipId)) closeRulePlot();
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
  const chip = fddChip;
  fddView.entries = rows.map((r) => fddEntryOf(r, rcxRuleResultPoint(model, r.equip, r.rule.id)));
  renderFddSummary(fddView.entries);
  renderFddList(fddView.entries);
  fddWriteUrl();
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
      const runs = (await api(`/api/v1/apps/${APP_ID}/hooks/fdd/runs?page_size=5&include_results=true&include_logs=true`)).runs || [];
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

function closeRulePlot() {
  fddPlotRead += 1;   // a range read still in flight for the old plot draws nothing
  activeRulePlot = null;
  fddView.open = null;
  if ($("fddPlotPanel")) $("fddPlotPanel").hidden = true;
  if ($("fddDrawer")) $("fddDrawer").hidden = true;
  document.querySelectorAll?.("#fddList .fdd-item.open").forEach((el) => { el.classList.remove("open"); el.querySelector(".fdd-row")?.setAttribute("aria-expanded", "false"); });
  fddWriteUrl();
  if (typeof ofddTuning !== "undefined" && ofddTuning && ofddTuning.cancelInline) ofddTuning.cancelInline();
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
  activeRulePlot = { ruleId, equipId };
  fddView.open = { ruleId, equipId };
  $("fddPlotPanel").hidden = false;
  const controls = (globalThis.ofddPlotSpecData?.rule_tuning?.rules || {})[ruleId]?.controls || null;
  const si = fddSiParameters(row.rule, controls);
  $("fddSiParams").innerHTML = si.length ? `<p class="sub">${esc(row.rule.description || "")} (shipped values; the drawer shows this site's)</p><ul>${si.map((x) =>
    `<li><span>${esc(x.name)}</span> <b>${esc(String(x.value))}</b> ${esc(x.unit)}</li>`).join("")}</ul>` : `<p class="sub">${esc(row.rule.description || "")} · no tunable thresholds</p>`;
  $("fddInputs").innerHTML = (row.required || []).map((x) => fddChip(x, row.bound[x] || [], false)).join("") + (row.optional || []).map((x) => fddChip(x, row.bound[x] || [], true)).join("");
  if ($("fddDrawerTitle")) $("fddDrawerTitle").innerHTML = `Tune ${fddRuleCellHtml(row.rule)} <span class="sub">· ${esc(equipLabel(equipRec))}</span>`;
  fddWriteUrl();
  if (typeof ofddTuning !== "undefined" && ofddTuning && ofddTuning.renderInline) {
    ofddTuning.renderInline({ site: scope.site, equip: equipId, equipLabel: equipLabel(equipRec), ruleId, bound: row.bound, catalog });
  }
  $("fddPlotTitle").innerHTML = `${fddRuleCellHtml(row.rule)} <span class="sub">· ${esc(equipLabel(equipRec))}</span>`;
  $("fddPlotNote").textContent = row.rule.description || "";
  $("fddPlotRangeStatus").textContent = "Resolving range…";
  if (typeof $("fddPlotPanel").scrollIntoView === "function") $("fddPlotPanel").scrollIntoView({ behavior: "smooth", block: "nearest" });
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
let activeRulePlot = null;

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
  const heat = fddHeatRows(faults.map((p) => ({ key: p.uuid, p, equip: p.equipRef, faultTime: faultMinutes(p) })), { selectedEquip: tabEquip(), showAll: fddUi.heatAll });
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

// ---- RCx dashboard (on Overview) and FDD charts ------------------------------------------------
// Both draw rcxView() cards from rcx-*.js / fdd-plots.js; a view's `tab` says where it lives ("rcx" = the Overview RCx
// dashboard, "fdd"). The RCx dashboard has NO device picker: every modeled device of the site at once (each AHU's run hours
// and cooling bins together, all zones together); a view draws only when the model has its equipment and roles, and a
// card that drew nothing is removed, so a site without a chiller / hot-water plant / DX / zones simply has no such panel.
// The FDD charts follow the FDD tab's one selected equipment. Each card renders on its own so one failing view never
// blanks the page.
const viewTabRuns = { rcx: 0, fdd: 0 };
// Overview (#1643): the fleet dashboard draws a card only when it comes near the viewport, a few at a time, so opening
// Overview no longer requests history for every panel on the site at once. Holds the running queue's stop().
/** @type {Record<string, (() => void) | null>} */
const viewTabObservers = { rcx: null, fdd: null };
const LAZY_CARD_MARGIN = "600px 0px", LAZY_CARD_CONCURRENCY = 2;
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
  const fleet = tab === "rcx";                                  // the RCx dashboard: every device, never one picked
  // Weather checks still bind their outdoor-air pair from the site's model, but must never draw equipment plots.
  const weatherOnly = !fleet && scope.equip === WEATHER_SCOPE;
  const equips = fleet || weatherOnly ? siteEquips : fddEquipsInScope(), single = !fleet && !!tabEquip();
  const ahuOn = tab === "rcx" ? renderAhuControl(siteEquips, catalog) : false;
  const rangeState = getChartRangeState(T.key), siteTz = siteTimeZone();
  renderRangeControl($(T.range), { key: T.key, state: rangeState, siteTz,
    onChange: () => {
      const pending = renderViewTab(tab), requested = viewTabRuns[tab];
      pending.catch((e) => { if (requested === viewTabRuns[tab]) $(T.status).textContent = `Could not load this range: ${e.message}`; });
    } });
  const rangePoints = model.points.filter((p) => p.siteRef === scope.site && has(p, "his")
    && (fleet || !tabEquip() || p.equipRef === tabEquip() || p.weatherStationRef));
  let range;
  try { range = await resolveChartSelection(rangePoints, rangeState, { siteTz }); }
  catch (e) {
    if (run === viewTabRuns[tab]) $(T.status).textContent = `Could not load this range: ${e.message}`;
    throw e;
  }
  if (run !== viewTabRuns[tab]) return;
  const hours = Math.max(1, (range.resolvedBounds.toMs - range.resolvedBounds.fromMs) / 3600e3);
  $(T.status).textContent = "Loading history…";
  const plan = rcxPlan(equips, model, catalog, { tab, single });
  const { missing } = plan;
  const ready = weatherOnly ? plan.ready.filter(({ view }) => view.id === "bas-vs-web-oat" || view.id === "bas-vs-web-oat-hist") : plan.ready;
  const cards = ready.flatMap(({ view, equips: eqs }) => (view.scope === "site" ? [{ view, eqs }] : eqs.map((eq) => ({ view, eqs: [eq] }))));
  const groupOf = (c) => (c.view.groupOf ? c.view.groupOf(c.eqs) : c.view.group);
  void missing;                                                  // unbound views are hidden, never listed
  if (fleet && $("overviewRcx")) $("overviewRcx").hidden = !cards.length;
  if ($(T.mode)) {
    const who = single ? (fddEquipOptions(model, scope.site).find((o) => o.id === tabEquip()) || { label: tabEquip() }).label : "";
    $(T.mode).textContent = tab === "fdd"
      ? (single ? `Equipment: ${who}.` : scope.equip === WEATHER_SCOPE ? "Weather: the site's outdoor-air checks." : "Pick an equipment.")
      : `${cards.length} panel${cards.length === 1 ? "" : "s"} from the ${siteEquips.length} modeled device${siteEquips.length === 1 ? "" : "s"} of this site.`;
  }
  const sections = [];
  if (tab === "rcx" && cards.some((c) => c.view.headline)) sections.push({ title: "Headline", cls: " rcx-headline", cards: cards.filter((c) => c.view.headline) });
  const rest = cards.filter((c) => tab !== "rcx" || !c.view.headline);
  for (const g of [...new Set(rest.map(groupOf))]) sections.push({ title: g, cls: "", cards: rest.filter((c) => groupOf(c) === g) });
  $(T.body).innerHTML = sections.map((sec) => `<section class="panel${sec.cls}"><h2>${esc(sec.title)}</h2><div class="rcx-grid${tab === "fdd" ? " one-col" : ""}">${
    sec.cards.map((c) => `<div class="rcx-card${c.view.wide ? " rcx-wide" : ""}" data-view="${esc(c.view.id)}">
      <h3>${esc(c.view.title)}${c.view.scope === "equip" ? ` <span class="sub">· ${esc(c.eqs[0].name)}</span>` : ""}</h3>
      <div class="chart" id="${tab}-${cards.indexOf(c)}"></div><div class="sub note" id="${tab}-note-${cards.indexOf(c)}"></div></div>`).join("")}</div></section>`).join("")
    || (fleet ? "" : `<section class="panel"><p class="sub">No FDD chart has its inputs on the equipment in scope yet.</p></section>`);
  const kpis = [], maskCache = new Map();
  if (T.kpis && $(T.kpis)) $(T.kpis).innerHTML = "";
  const drawCard = async (i) => {
    const c = cards[i];
    if (run !== viewTabRuns[tab]) return;                      // a newer render (range/scope change) took over
    const el = $(`${tab}-${i}`);
    if (!el) return;
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
        const card = /** @type {HTMLElement} */ (el.closest(".rcx-card"));
        card.hidden = true;
        const sec = /** @type {HTMLElement|null} */ (card.closest("section.panel"));
        if (sec && ![...sec.querySelectorAll(".rcx-card")].some((x) => !/** @type {HTMLElement} */ (x).hidden)) sec.hidden = true;   // an empty group goes too
      }
    } catch (e) {
      if (run === viewTabRuns[tab]) $(`${tab}-note-${i}`).textContent = `could not draw: ${e.message}`;
    } finally {
      if (el.classList) el.classList.add("done");             // ends the card's loading placeholder
    }
  };
  const finish = () => {
    if (run !== viewTabRuns[tab]) return;
    $(T.status).textContent = "";
    const body = $(T.body);
    if (fleet && $("overviewRcx") && body && typeof body.querySelectorAll === "function") {
      $("overviewRcx").hidden = ![...body.querySelectorAll(".rcx-card")].some((x) => !/** @type {HTMLElement} */ (x).hidden);
    }
  };
  if (viewTabObservers[tab]) { viewTabObservers[tab](); viewTabObservers[tab] = null; }
  if (fleet && cards.length && typeof IntersectionObserver === "function" && typeof lazyDrawCards === "function") {
    // Lazy (lazy-cards.js): a card fetches its history when it nears the viewport, LAZY_CARD_CONCURRENCY at once.
    // Leaving Overview stops the queue; coming back re-renders the dashboard as a new run.
    $(T.status).textContent = "";                               // each card shows its own loading placeholder
    viewTabObservers[tab] = lazyDrawCards({
      els: cards.map((_, i) => $(`${tab}-${i}`)), draw: drawCard, onDone: finish,
      isLive: () => run === viewTabRuns[tab] && activeTab === "overview",
      concurrency: LAZY_CARD_CONCURRENCY, rootMargin: LAZY_CARD_MARGIN,
    });
    return;
  }
  for (let i = 0; i < cards.length; i++) {
    if (run !== viewTabRuns[tab]) return;
    await drawCard(i);
  }
  finish();
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
  if (activeTab === "fdd" && activeRulePlot && $("fddPlotPanel") && !$("fddPlotPanel").hidden) {
    showRulePlot(activeRulePlot.ruleId, activeRulePlot.equipId).catch(() => {});
  }
}

// ---- registering this edition's tabs with the shell ---------------------------------------
ofddTabs.fdd = () => renderFdd();
ofddTabs.overview = async () => {
  if (globalThis.ofddOccupancyEditor) await globalThis.ofddOccupancyEditor.render({ site: scope.site,
    timezone: resolveSiteTimeZone(model.sites.find((s) => idOf(s) === scope.site)).zone, onChange: () => renderRcx() });
  return renderRcx();
};   // the RCx dashboard is part of Overview (the RCx tab is gone; #rcx opens Overview)
const timescaleHistoryState = { disabled: false, reason: "" };
// The history hook takes at most 200 uuids per run (hooks/lib/timescale.js MAX_UUIDS); a chart or export with more
// points is sent in batches and the rows merged, instead of one refused run that silently drops the long-range fill.
const TIMESCALE_HISTORY_BATCH = 200;
async function queryTimescaleHistory({ uuids, fromMs, toMs, bucket }) {
  if (timescaleHistoryState.disabled) {
    return { ok: true, skipped: true, reason: timescaleHistoryState.reason || "timescale unavailable" };
  }
  const cleanIds = [...new Set((uuids || []).map((u) => String(u || "").trim()).filter(Boolean))];
  if (!cleanIds.length) return { ok: true, skipped: true, reason: "no numeric uuids" };
  if (cleanIds.length <= TIMESCALE_HISTORY_BATCH) return queryTimescaleHistoryBatch({ cleanIds, fromMs, toMs, bucket });
  /** @type {any} */
  let merged = null;
  const widths = new Set();
  for (let i = 0; i < cleanIds.length; i += TIMESCALE_HISTORY_BATCH) {
    const part = /** @type {any} */ (await queryTimescaleHistoryBatch({ cleanIds: cleanIds.slice(i, i + TIMESCALE_HISTORY_BATCH), fromMs, toMs, bucket }));
    if (!part || part.ok === false || part.skipped) return part;
    if (part.bucket != null) widths.add(String(part.bucket));
    if (!merged) merged = { ...part, rows: [...(part.rows || [])] };
    else {
      merged.rows.push(...(part.rows || []));
      merged.truncated = !!(merged.truncated || part.truncated);
      merged.coarsened = !!(merged.coarsened || part.coarsened);
      if (typeof merged.total === "number" && typeof part.total === "number") merged.total += part.total;
      const a = merged.coverage, c = part.coverage;
      if (a && c) {
        merged.coverage = {
          ...a, requested: (a.requested || 0) + (c.requested || 0), with_data: (a.with_data || 0) + (c.with_data || 0),
          without_data: [...(a.without_data || []), ...(c.without_data || [])],
          points: { ...(a.points || {}), ...(c.points || {}) },
        };
      }
    }
  }
  if (merged.coverage) merged.coverage.complete = !merged.truncated;
  // each batch coarsens on its own uuid count: one width when they agree, else say so (rows keep their own buckets)
  merged.buckets = [...widths];
  if (widths.size > 1) merged.bucket = "mixed (" + merged.buckets.join(", ") + ")";
  merged.row_count = merged.rows.length;
  merged.batches = Math.ceil(cleanIds.length / TIMESCALE_HISTORY_BATCH);
  return merged;
}
/** One history hook run for at most 200 uuids. */
async function queryTimescaleHistoryBatch({ cleanIds, fromMs, toMs, bucket, oldest = false }) {
  // NF StartHook takes the hook args as a flat string->string map (same as the tuning hook); wrapping them in
  // {args: ...} makes NF answer HTTP 500 and the long-range Timescale fill silently never runs.
  /** @type {Record<string, string>} */
  const body = oldest ? { uuids: JSON.stringify(cleanIds), oldest: "true" } : {
    uuids: JSON.stringify(cleanIds),
    from: new Date(fromMs).toISOString(),
    to: new Date(toMs).toISOString(),
    ...(bucket ? { bucket: String(bucket) } : {}),
  };
  let pid;
  try {
    const started = await api(`/api/v1/apps/${APP_ID}/hooks/history`, body);
    pid = started && started.pid;
  } catch (e) {
    const msg = String((e && e.message) || e);
    if (/HTTP (401|403|404)/.test(msg)) {
      timescaleHistoryState.disabled = true;
      timescaleHistoryState.reason = msg;
      return { ok: false, error: msg, status: Number((msg.match(/HTTP (\d+)/) || [])[1] || 0) };
    }
    throw e;
  }
  const deadline = Date.now() + 25e3;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 400));
    const runs = (await api(`/api/v1/apps/${APP_ID}/hooks/history/runs?page_size=5&include_results=true&include_logs=true`)).runs || [];
    const hit = runs.find((r) => r.pid === pid || (r.run && r.run.pid === pid));
    if (!hit) continue;
    const status = String(hit.status || hit.state || "").toUpperCase();
    if (/RUNNING|PENDING|ENQUEUED|SCHEDULED/.test(status)) continue;
    // The hook logs its answer as one JSON event line (NF leaves returnValue empty); events can land a poll late.
    const events = Object.values(hit.results || {}).flatMap((g) => (g && g.events) || []);
    const lastJson = [...events].reverse().find((e) => e && typeof e.message === "string" && e.message.trim().startsWith("{"));
    if (!lastJson && status.includes("SUCCESS") && Date.now() < deadline - 20e3) continue;
    const rawOut = lastJson ? lastJson.message : (hit.result ?? hit.output ?? (Array.isArray(hit.logs) ? hit.logs.at(-1) : null));
    let parsed = rawOut;
    if (typeof rawOut === "string") {
      try { parsed = JSON.parse(rawOut); } catch { parsed = null; }
    }
    if (parsed && typeof parsed === "object") {
      if (parsed.skipped && /timescale not configured/i.test(String(parsed.reason || ""))) {
        timescaleHistoryState.disabled = true;
        timescaleHistoryState.reason = parsed.reason;
      }
      return parsed;
    }
    if (status.includes("FAIL") || status.includes("ERROR")) {
      return { ok: false, error: hit.error || "history hook failed" };
    }
    return { ok: false, error: "history hook returned no structured result" };
  }
  return { ok: false, error: "history hook timed out waiting for result" };
}
/**
 * The oldest Timescale sample per point (the "All" range start on Full, #1612), in batches of TIMESCALE_HISTORY_BATCH.
 * {ok, complete, oldest: {uuid: ISO | null}}; complete is false when a batch failed (the others still count).
 * @param {string[]} uuids
 */
async function queryTimescaleOldest(uuids) {
  if (timescaleHistoryState.disabled) return { ok: false, skipped: true, reason: timescaleHistoryState.reason };
  const cleanIds = [...new Set((uuids || []).filter((u) => typeof u === "string" && u))];
  /** @type {Record<string, string | null>} */
  const oldest = {};
  let okBatches = 0, error = "";
  for (let i = 0; i < cleanIds.length; i += TIMESCALE_HISTORY_BATCH) {
    const ids = cleanIds.slice(i, i + TIMESCALE_HISTORY_BATCH);
    let ans;
    try { ans = await queryTimescaleHistoryBatch({ cleanIds: ids, fromMs: 0, toMs: 0, bucket: null, oldest: true }); }
    catch (e) { ans = { ok: false, error: String((e && e.message) || e) }; }
    if (ans && ans.ok && ans.oldest) { okBatches += 1; Object.assign(oldest, ans.oldest); }
    else error ||= (ans && (ans.error || ans.reason)) || "no answer";
  }
  if (!okBatches) return { ok: false, error: error || "no uuids" };
  return { ok: true, complete: !error && okBatches * TIMESCALE_HISTORY_BATCH >= cleanIds.length, oldest, ...(error ? { error } : {}) };
}
if (typeof globalThis !== "undefined") {
  globalThis.ofddTimescaleHistory = queryTimescaleHistory;
  globalThis.ofddTimescaleOldest = queryTimescaleOldest;
}

ofddTabs.export = () => ofddExport.render({ model, scope: { ...scope, equip: exportEquipId() }, timescaleHistory: queryTimescaleHistory });
for (const tab of ["fdd", "export"]) ofddEquipScoped.add(tab);     // these get an equip picker too (never an "all" choice)

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
      if (!tr) return;
      // the More tables open the rule in the list (show all, so the row is there)
      fddView.filter = ""; fddView.showAll = true; closeRulePlot();
      fddView.open = { ruleId: tr.dataset.rule, equipId: tr.dataset.equip };
      renderFddSummary(fddView.entries); renderFddList(fddView.entries);
      if (!activeRulePlot) showRulePlot(tr.dataset.rule, tr.dataset.equip).catch(plotErr);
    };
  }
  $("fddPlotClose").onclick = () => { closeRulePlot(); renderFddList(fddView.entries); };
  // the summary chips filter the list; "show all" adds the passing and skipped rules; a row opens (one at a time)
  $("fddSummary").onclick = (ev) => {
    const b = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest("[data-filter]"));
    if (!b) return;
    fddView.filter = fddView.filter === b.dataset.filter ? "" : b.dataset.filter;
    renderFddSummary(fddView.entries); renderFddList(fddView.entries); fddWriteUrl();
  };
  $("fddShowAll").onclick = () => { fddView.showAll = !fddView.showAll; renderFddList(fddView.entries); };
  $("fddList").onclick = (ev) => {
    const item = /** @type {HTMLElement} */ (/** @type {HTMLElement} */ (ev.target).closest(".fdd-item"));
    if (!item || !(/** @type {HTMLElement} */ (ev.target).closest(".fdd-row"))) return;
    const same = fddView.open && fddView.open.ruleId === item.dataset.rule && fddView.open.equipId === item.dataset.equip;
    if (same) closeRulePlot();
    else { closeRulePlot(); fddView.open = { ruleId: item.dataset.rule, equipId: item.dataset.equip }; }
    renderFddList(fddView.entries);
    fddWriteUrl();
  };
  $("fddTuneOpen").onclick = () => { $("fddDrawer").hidden = false; };
  $("fddDrawerClose").onclick = () => { $("fddDrawer").hidden = true; };
  $("fddRunNow").onclick = () => runFddNow().catch((e) => ($("fddRunState").textContent = `could not start: ${e.message}`));
  $("unitsToggle").onclick = () => setUnits(unitSystem() === "si" ? "imperial" : "si");
  syncUnitsToggle();
});

if (typeof document !== "undefined" && document.documentElement) main().catch(showErr);
