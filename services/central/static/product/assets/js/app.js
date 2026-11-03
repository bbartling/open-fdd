import { clearSession, readToken, writeToken } from "./session.js";
import { apiFetch, login } from "./api.js";
import { populateSitePicker } from "./sites.js";
import {
  applyLatestFromSeries,
  displayName,
  esc,
  fmtPoint,
  GENERIC,
  has,
  isBoolRole,
  isTemp,
  roleOf,
  runSparql,
} from "./model.js";
import { loadModelFromTtl } from "./ttl-model.js";
import { loadSiteData } from "./site-data.js";
import {
  disposeSparklines,
  loadScopeHistory,
  refreshChartsTab,
  renderOverviewSpark,
  renderPointHistory,
  resizeCharts,
} from "./charts.js";
import { renderModelChecks, renderModelTree, resizeTree } from "./tree-view.js";
import { fetchInspectSeries } from "./analytics.js";
import { bindRcxTab, onRcxSiteChange, refreshRcxTab, resizeRcxCharts } from "./rcx-tab.js";
import { bindFddTab, onFddSiteChange, resizeFddCharts } from "./fdd-tab.js";
import { bindSchedulesTab, refreshSchedulesTab } from "./schedules-tab.js";
import { bindOperationsTab, refreshOperationsTab } from "./operations-tab.js";

const $ = (id) => document.getElementById(id);
let activeTab = "overview";
let scope = { site: "", equip: "" };
let ctx = null;
/** TTL-only tree for Model tab; operational points from historian/mapping elsewhere. */
let modelTree = null;
let chartState = {
  history: new Map(),
  inspectRows: [],
  rangeHours: 24,
  histHours: 24,
  heatRole: "sat",
  cardPoints: [],
  weatherPoints: [],
  statusPoints: [],
};
let selectedPointId = null;

function showErr(msg) {
  const el = $("err");
  if (!msg) {
    el.classList.remove("show");
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.add("show");
}

function setLive(ok, text) {
  $("liveDot").classList.toggle("bad", !ok);
  $("liveTxt").textContent = text;
}

function tickClock() {
  $("clock").textContent = new Date().toLocaleString();
}

function renderTab(name) {
  activeTab = name;
  document.querySelectorAll("#tabs button").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.tab === name);
  });
  document.querySelectorAll("main > section.tab").forEach((sec) => {
    sec.classList.toggle("on", sec.id === `tab-${name}`);
  });
  if (name === "charts") {
    refreshChartsTab({
      buildingId: scope.site,
      equipId: scope.equip || ctx?.model?.equips[0]?.id,
      cardPoints: chartState.cardPoints,
      history: chartState.history,
      rangeHours: chartState.rangeHours,
      heatRole: chartState.heatRole,
    }).catch((err) => showErr(err.message));
    resizeCharts();
  }
  if (name === "model") {
    renderModelTree(modelTree, scope.site, scope.equip || "", $("detail"), $("tree"));
    renderModelChecks(modelTree, scope.site, $("checks"));
    resizeTree();
  }
  if (name === "rcx") {
    refreshRcxTab().catch((err) => showErr(err.message));
    resizeRcxCharts();
  }
  if (name === "fdd") {
    resizeFddCharts();
  }
  if (name === "schedules" && scope.site) {
    const tab = $("tab-schedules");
    if (tab) tab.dataset.buildingId = scope.site;
    refreshSchedulesTab(scope.site).catch((err) => showErr(err.message));
  }
  if (name === "ops") {
    refreshOperationsTab(scope.site).catch((err) => showErr(err.message));
  }
  if (name === "points" && selectedPointId) {
    renderPointHistory(
      ctx.model.points.find((p) => p.id === selectedPointId),
      chartState.inspectRows,
      chartState.histHours,
    );
  }
}

function siteEquipIds() {
  return ctx.model.equips.map((e) => e.id);
}

function inScopeEquip(p) {
  if (!p.equipRef) return false;
  if (scope.equip) return p.equipRef === scope.equip;
  return siteEquipIds().includes(p.equipRef);
}

function rankPoint(p) {
  return (has(p, "sensor") ? 0 : 2) + (isTemp(p) ? 0 : 1);
}

function recomputeScopedSets() {
  const tagged = ctx.model.points.filter((p) => p.siteRef === scope.site);
  const equipPts = tagged.filter(inScopeEquip);
  chartState.cardPoints = equipPts
    .filter((p) => !isBoolRole(p) && (has(p, "sensor") || has(p, "sp")))
    .sort((a, b) => rankPoint(a) - rankPoint(b) || displayName(a).localeCompare(displayName(b)));
  chartState.statusPoints = equipPts
    .filter(isBoolRole)
    .sort((a, b) => a.equipRef.localeCompare(b.equipRef) || displayName(a).localeCompare(displayName(b)));
  chartState.weatherPoints = tagged
    .filter((p) => has(p, "weather") || roleOf(p) === "web_oa_t")
    .sort((a, b) => displayName(a).localeCompare(displayName(b)));
}

function fillEquipPicker() {
  const pick = $("equipPick");
  const equips = ctx.model.equips;
  pick.disabled = !equips.length;
  pick.innerHTML =
    `<option value="">all equips (${equips.length})</option>` +
    equips
      .map((e) => `<option value="${esc(e.id)}">${esc(e.name || e.id)}</option>`)
      .join("");
  pick.value = scope.equip;
}

function renderSummary() {
  const summary = $("summary");
  if (!ctx) {
    summary.innerHTML = "";
    return;
  }
  const tagged = ctx.model.points.filter((p) => p.siteRef === scope.site);
  const v = ctx.health?.version ?? "—";
  summary.innerHTML = `
    <div class="stat"><b>${esc(v)}</b><span>build</span></div>
    <div class="stat"><b>${ctx.model.equips.length}</b><span>equip</span></div>
    <div class="stat"><b>${tagged.length}</b><span>points</span></div>
    <div class="stat"><b>${chartState.cardPoints.length}</b><span>chart sensors</span></div>`;
}

function renderCards() {
  disposeSparklines();
  const cards = chartState.cardPoints.slice(0, 12);
  $("cards").innerHTML = cards
    .map(
      (p, i) => `
    <article class="card" id="card-${i}" title="${esc((p.tags || []).join(" "))}">
      <div class="name">${esc(displayName(p))}</div>
      <div class="desc">${esc(p.equipRef || "")} · ${esc(roleOf(p))}</div>
      <div class="val"><span id="val-${i}">–</span><small>${esc(p.unit || "")}</small></div>
      <div class="delta" id="delta-${i}">&nbsp;</div>
      <div class="spark" id="spark-${i}"></div>
    </article>`,
    )
    .join("");
  cards.forEach((p, i) => {
    $(`val-${i}`).textContent = fmtPoint(p);
    renderOverviewSpark(i, p, chartState.history);
  });
  $("nPoints").textContent = String(ctx.model.points.filter((p) => p.siteRef === scope.site).length);
}

function renderChips() {
  const chips = chartState.statusPoints;
  $("chips").innerHTML = chips.length
    ? chips
        .map((p) => {
          const on = (p.latest?.value ?? 0) > 0.5;
          return `<span class="chip ${on ? "on" : ""}" title="${esc(displayName(p))}">
      <span class="led"></span>${esc(displayName(p))}<span class="state">${on ? "on" : "off"}</span></span>`;
        })
        .join("")
    : `<span class="sub">No status/cmd roles on scoped equipment.</span>`;
}

function fillHeatPicker() {
  const pick = $("heatPick");
  if (!pick) return;
  pick.innerHTML = chartState.cardPoints
    .filter(isTemp)
    .map(
      (p) =>
        `<option value="${esc(roleOf(p))}">${esc(displayName(p))} (${esc(roleOf(p))})</option>`,
    )
    .join("");
  if (!pick.options.length && chartState.cardPoints[0]) {
    pick.innerHTML = `<option value="${esc(roleOf(chartState.cardPoints[0]))}">${esc(displayName(chartState.cardPoints[0]))}</option>`;
  }
  pick.value = chartState.heatRole;
}

function renderModelStats() {
  const el = $("modelStats");
  if (!el || !modelTree) return;
  el.innerHTML = `
    <div class="stat"><b>TTL</b><span>tree source</span></div>
    <div class="stat"><b>${modelTree.equips.length}</b><span>equip</span></div>
    <div class="stat"><b>${modelTree.points.length}</b><span>points</span></div>`;
}

function pointRowsFiltered() {
  const tokens = ($("pointFilter")?.value || "")
    .toLowerCase()
    .split(/[\s,]+/)
    .filter(Boolean);
  return ctx.model.points
    .filter((p) => p.siteRef === scope.site)
    .filter((p) => !scope.equip || inScopeEquip(p) || has(p, "weather"))
    .filter((p) => {
      if (!tokens.length) return true;
      return tokens.every(
        (t) =>
          (p.tags || []).some((m) => m.toLowerCase() === t) ||
          displayName(p).toLowerCase().includes(t) ||
          roleOf(p).toLowerCase().includes(t),
      );
    })
    .sort(
      (a, b) =>
        (has(b, "point") - has(a, "point")) ||
        (a.equipRef || "").localeCompare(b.equipRef || "") ||
        rankPoint(a) - rankPoint(b) ||
        displayName(a).localeCompare(displayName(b)),
    );
}

function renderPointsTable() {
  const rows = pointRowsFiltered();
  $("pointHint").textContent = `${rows.length} shown`;
  $("pointRows").innerHTML = rows
    .map((p) => {
      const tags = (p.tags || [])
        .filter((t) => !GENERIC.has(t))
        .map((t) => `<span class="tag">${esc(t)}</span>`)
        .join("");
      const ts = p.latest?.ts ? new Date(p.latest.ts).toLocaleString() : "–";
      return `<tr class="pick ${selectedPointId === p.id ? "sel" : ""}" data-id="${esc(p.id)}">
      <td>${esc(displayName(p))}<div class="sub">${esc(roleOf(p))}</div></td>
      <td><div class="tags">${tags || `<span class="sub">—</span>`}</div></td>
      <td class="num">${esc(fmtPoint(p))}</td>
      <td class="sub">${esc(p.equipRef || "—")}</td>
      <td class="sub">${ts}</td></tr>`;
    })
    .join("") || `<tr><td colspan="5" class="sub">No points match.</td></tr>`;
}

async function loadHistoryBundle() {
  const equipId = scope.equip || ctx.model.equips[0]?.id;
  if (!equipId) {
    chartState.history = new Map();
    chartState.inspectRows = [];
    return;
  }
  scope.equip = scope.equip || equipId;
  recomputeScopedSets();
  const { rows, history } = await loadScopeHistory(
    scope.site,
    equipId,
    chartState.cardPoints,
    chartState.weatherPoints,
    168,
  );
  chartState.inspectRows = rows;
  chartState.history = history;
  const roles = [...history.keys()];
  applyLatestFromSeries(ctx.model.points, rows, roles);
}

async function applySite() {
  scope.site = $("sitePick").value;
  if (!scope.site) {
    return;
  }
  setLive(true, "loading…");
  showErr("");
  try {
    const { ttl, model: ttlModel } = await loadModelFromTtl(scope.site, apiFetch);
    const siteData = await loadSiteData(scope.site);
    modelTree = ttlModel;
    ctx = {
      buildingId: scope.site,
      health: await apiFetch("/api/health"),
      ttl,
      model: siteData.model,
      mapping: siteData.mapping,
      sessionConfig: siteData.sessionConfig,
    };
    scope.equip = "";
    $("sub").textContent = `${scope.site} · ${ctx.health?.version ?? "Open-FDD"} · static UI`;
    $("ttl").textContent = ctx.ttl;
    fillEquipPicker();
    recomputeScopedSets();
    await loadHistoryBundle();
    fillHeatPicker();
    renderSummary();
    renderModelStats();
    renderCards();
    renderChips();
    renderPointsTable();
    renderModelTree(modelTree, scope.site, scope.equip, $("detail"), $("tree"));
    renderModelChecks(modelTree, scope.site, $("checks"));
    onRcxSiteChange(scope.site, ctx.mapping);
    await onFddSiteChange(scope.site, ctx);
    await refreshRcxTab().catch(() => {});
    setLive(true, `live · ${new Date().toLocaleTimeString()}`);
    if (activeTab === "charts") {
      await refreshChartsTab({
        buildingId: scope.site,
        equipId: scope.equip || ctx.model.equips[0]?.id,
        cardPoints: chartState.cardPoints,
        history: chartState.history,
        rangeHours: chartState.rangeHours,
        heatRole: chartState.heatRole,
      });
    }
    if (activeTab === "ops") {
      await refreshOperationsTab(scope.site);
    }
    if (activeTab === "schedules") {
      await refreshSchedulesTab(scope.site);
    }
  } catch (err) {
    showErr(err.message || String(err));
    setLive(false, "error");
  }
}

async function applyEquip() {
  scope.equip = $("equipPick").value;
  recomputeScopedSets();
  fillHeatPicker();
  await loadHistoryBundle();
  renderSummary();
  renderCards();
  renderChips();
  renderPointsTable();
  renderModelTree(modelTree, scope.site, scope.equip || "", $("detail"), $("tree"));
  if (activeTab === "charts") {
    await refreshChartsTab({
      buildingId: scope.site,
      equipId: scope.equip || ctx.model.equips[0]?.id,
      cardPoints: chartState.cardPoints,
      history: chartState.history,
      rangeHours: chartState.rangeHours,
      heatRole: chartState.heatRole,
    });
  }
}

async function loadSites() {
  const pick = $("sitePick");
  await populateSitePicker(pick);
  scope.site = pick.value;
  if (scope.site) {
    await applySite();
  } else {
    $("sub").textContent = "Select or import a building site";
    setLive(false, "no site");
  }
}

function bindSparql() {
  $("sparqlRun")?.addEventListener("click", async () => {
    const out = $("sparqlOut");
    if (!scope.site) {
      out.textContent = "Pick a site first.";
      return;
    }
    out.textContent = "Running…";
    try {
      const result = await runSparql(scope.site, $("sparqlQuery").value);
      out.textContent = JSON.stringify(result, null, 2);
    } catch (err) {
      out.textContent = err.message || String(err);
    }
  });
}

function bindTabs() {
  $("tabs").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-tab]");
    if (!btn) return;
    renderTab(btn.dataset.tab);
  });
  $("range")?.addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-h]");
    if (!btn) return;
    $("range").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b === btn));
    chartState.rangeHours = Number(btn.dataset.h);
    refreshChartsTab({
      buildingId: scope.site,
      equipId: scope.equip || ctx?.model?.equips[0]?.id,
      cardPoints: chartState.cardPoints,
      history: chartState.history,
      rangeHours: chartState.rangeHours,
      heatRole: chartState.heatRole,
    }).catch((err) => showErr(err.message));
  });
  $("heatPick")?.addEventListener("change", () => {
    chartState.heatRole = $("heatPick").value;
    refreshChartsTab({
      buildingId: scope.site,
      equipId: scope.equip || ctx?.model?.equips[0]?.id,
      cardPoints: chartState.cardPoints,
      history: chartState.history,
      rangeHours: chartState.rangeHours,
      heatRole: chartState.heatRole,
    }).catch((err) => showErr(err.message));
  });
  $("pointFilter")?.addEventListener("input", () => renderPointsTable());
  $("pointRows")?.addEventListener("click", async (ev) => {
    const row = ev.target.closest("tr[data-id]");
    if (!row) return;
    selectedPointId = row.dataset.id;
    renderPointsTable();
    const point = ctx.model.points.find((p) => p.id === selectedPointId);
    $("histHint").textContent = point ? `${displayName(point)} · ${roleOf(point)}` : "";
    const equipId = point?.equipRef || scope.equip || ctx.model.equips[0]?.id;
    if (point && equipId) {
      chartState.inspectRows = await fetchInspectSeries(scope.site, equipId, chartState.histHours, [
        roleOf(point),
      ]);
      applyLatestFromSeries([point], chartState.inspectRows, [roleOf(point)]);
      renderPointHistory(point, chartState.inspectRows, chartState.histHours);
    }
  });
  window.addEventListener("resize", () => {
    resizeCharts();
    resizeTree();
    resizeRcxCharts();
    resizeFddCharts();
  });
}

function bindAuth() {
  const gate = $("loginGate");
  $("loginForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("loginErr").hidden = true;
    const data = new FormData(ev.target);
    try {
      const body = await login(data.get("username"), data.get("password"));
      const token = body.token || body.access_token;
      if (!token) throw new Error("Login response missing token");
      writeToken(token);
      gate.hidden = true;
      $("logoutBtn").hidden = false;
      await bootApp();
    } catch (err) {
      $("loginErr").textContent = err.message || "Sign in failed";
      $("loginErr").hidden = false;
    }
  });
  $("logoutBtn").addEventListener("click", () => {
    clearSession();
    location.reload();
  });
  $("sitePick").addEventListener("change", () => applySite());
  $("equipPick").addEventListener("change", () => applyEquip());
}

async function bootApp() {
  tickClock();
  setInterval(tickClock, 30_000);
  bindTabs();
  bindSparql();
  bindRcxTab();
  bindFddTab();
  const schedTab = $("tab-schedules");
  if (schedTab) bindSchedulesTab(schedTab);
  const opsTab = $("tab-ops");
  if (opsTab) bindOperationsTab(opsTab);
  await loadSites();
}

async function boot() {
  bindAuth();
  if (!readToken()) {
    $("loginGate").hidden = false;
    $("logoutBtn").hidden = true;
    return;
  }
  $("loginGate").hidden = true;
  $("logoutBtn").hidden = false;
  const tabFromQuery = new URLSearchParams(location.search).get("tab");
  if (tabFromQuery) {
    renderTab(tabFromQuery);
  }
  await bootApp();
}

boot();
