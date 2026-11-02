import {
  getFddRules,
  getFddResults,
  runFdd,
  fetchFddPlotSeries,
  rerunFddAfterRuleUpdate,
  fetchSessionConfig,
} from "./fdd-api.js";
import {
  fddStatusBucket,
  preferredPlotRuleId,
  ruleApplicable,
  mappedRolesForEquip,
} from "./fdd-status.js";
import { analyticsWindowFromSampling } from "./window-policy.js";
import { mountChart, resizeCharts, fddPlotOption, inspectChartOption } from "./chart-kit.js";
import { fetchInspectSeries } from "./analytics.js";
import { RULES_UPDATED } from "./rule-params.js";
import {
  DEFAULT_SERIES_PREVIEW_ROWS,
  SERIES_PREVIEW_ROW_OPTIONS,
  recentSeriesPreviewFromLines,
  renderPreviewTable,
} from "./series-preview.js";

let buildingId = "";
let equipId = "";
let sessionConfig = null;
let mapping = null;
let rules = [];
let results = [];
let statusFilter = "All";
let selectedRuleId = "";
let previewRows = DEFAULT_SERIES_PREVIEW_ROWS;
let plotLineSeries = [];
let rulesBound = false;
let fddTabBound = false;

const $ = (id) => document.getElementById(id);

function statusMap() {
  const m = new Map();
  for (const r of results) {
    if (r.equipment_id !== equipId) continue;
    m.set(r.rule_id, r.status);
  }
  return m;
}

function filteredRules() {
  const roles = mappedRolesForEquip(mapping, equipId);
  const byStatus = statusMap();
  return rules.filter((rule) => {
    if (!ruleApplicable(rule, roles)) return false;
    if (statusFilter === "All") return true;
    return fddStatusBucket(byStatus.get(rule.rule_id)) === statusFilter;
  });
}

function renderRuleList() {
  const host = $("ruleList");
  if (!host) return;
  host.replaceChildren();
  const list = filteredRules();
  const byStatus = statusMap();
  if (!selectedRuleId || !list.some((r) => r.rule_id === selectedRuleId)) {
    selectedRuleId = preferredPlotRuleId(
      list.map((r) => r.rule_id),
      byStatus,
    );
  }
  if (!list.length) {
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = "No rules match filter / mapping.";
    host.appendChild(p);
    return;
  }
  for (const rule of list) {
    const st = fddStatusBucket(byStatus.get(rule.rule_id));
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `rule-pick${rule.rule_id === selectedRuleId ? " sel" : ""}`;
    btn.dataset.rule = rule.rule_id;
    const idSpan = document.createElement("span");
    idSpan.className = "rule-id";
    idSpan.textContent = rule.rule_id;
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.textContent = st;
    btn.appendChild(idSpan);
    btn.appendChild(pill);
    host.appendChild(btn);
  }
}

async function loadPlot() {
  if (!buildingId || !equipId || !selectedRuleId) return;
  const window = analyticsWindowFromSampling(mapping?.equipment ?? []);
  const body = await fetchFddPlotSeries(buildingId, equipId, selectedRuleId, window);
  const roles = body.roles || [];
  const rows = body.rows || [];
  const built = fddPlotOption(rows, roles, body.has_confirmed_fault);
  mountChart($("fddChart"), built.option);
  plotLineSeries = built.lineSeries;
  $("plotHint").textContent = `${roles.length} roles · ${rows.length} rows`;
  renderPreviewTable(
    $("fddPreviewTable"),
    recentSeriesPreviewFromLines(plotLineSeries, previewRows),
  );
}

async function loadInspect() {
  if (!buildingId || !equipId || !selectedRuleId) return;
  const rule = rules.find((r) => r.rule_id === selectedRuleId);
  const required = rule?.required_roles || [];
  const optional = rule?.optional_roles || [];
  const roles = [...required, ...optional.filter(Boolean)].filter(
    (r) => r !== "confirmed_fault" && r !== "fault",
  );
  const window = analyticsWindowFromSampling(mapping?.equipment ?? []);
  const rows = await fetchInspectSeries(buildingId, equipId, window, roles);
  const built = inspectChartOption(equipId, rows, roles);
  $("inspectHost").style.height = `${built.heightPx}px`;
  mountChart($("inspectChart"), built.option);
}

async function refreshFddData() {
  results = await getFddResults(buildingId);
  renderRuleList();
  await loadPlot();
  await loadInspect();
}

export function bindFddTab() {
  if (fddTabBound) return;
  fddTabBound = true;
  $("statusFilter").innerHTML = ["All", "FAULT", "PASS", "SKIPPED", "Not run"]
    .map((s) => `<option value="${s}">${s}</option>`)
    .join("");
  $("statusFilter").addEventListener("change", () => {
    statusFilter = $("statusFilter").value;
    renderRuleList();
  });
  $("fddPreviewPick").innerHTML = SERIES_PREVIEW_ROW_OPTIONS.map(
    (n) => `<option value="${n}">${n}</option>`,
  ).join("");
  $("fddPreviewPick").value = String(previewRows);
  $("fddPreviewPick").addEventListener("change", () => {
    previewRows = Number($("fddPreviewPick").value);
    renderPreviewTable(
      $("fddPreviewTable"),
      recentSeriesPreviewFromLines(plotLineSeries, previewRows),
    );
  });
  $("ruleList").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-rule]");
    if (!btn) return;
    selectedRuleId = btn.dataset.rule;
    renderRuleList();
    await loadPlot();
    await loadInspect();
  });
  $("runBtn").addEventListener("click", async () => {
    const list = filteredRules();
    const ids = selectedRuleId ? [selectedRuleId] : list.map((r) => r.rule_id);
    $("runMsg").textContent = "Running…";
    try {
      await runFdd(buildingId, equipId, ids, sessionConfig, rules);
      $("runMsg").textContent = "done";
      await refreshFddData();
    } catch (err) {
      $("runMsg").textContent = "failed";
      $("err").textContent = err.message || String(err);
      $("err").classList.add("show");
    }
  });
  $("rerunRuleBtn")?.addEventListener("click", async () => {
    if (!selectedRuleId) return;
    $("runMsg").textContent = "Re-running with session confirm_min…";
    try {
      await rerunFddAfterRuleUpdate(buildingId, equipId, selectedRuleId, rules);
      sessionConfig = await fetchSessionConfig(buildingId);
      await refreshFddData();
      $("runMsg").textContent = "session applied";
    } catch (err) {
      $("runMsg").textContent = "failed";
    }
  });
  window.addEventListener(RULES_UPDATED, async () => {
    if (!selectedRuleId || !buildingId) return;
    sessionConfig = await fetchSessionConfig(buildingId);
    await rerunFddAfterRuleUpdate(buildingId, equipId, selectedRuleId, rules);
    await refreshFddData();
  });
}

export async function onFddSiteChange(site, ctx) {
  buildingId = site;
  mapping = ctx.mapping;
  sessionConfig = ctx.sessionConfig;
  rules = await getFddRules();
  results = await getFddResults(buildingId);
  const equips = ctx.model?.equips || [];
  if (!equipId || !equips.some((e) => e.id === equipId)) {
    equipId = equips[0]?.id || "";
  }
  const pick = $("fddEquipPick");
  if (pick && !rulesBound) {
    rulesBound = true;
    pick.addEventListener("change", async () => {
      equipId = pick.value;
      renderRuleList();
      await loadPlot();
      await loadInspect();
    });
  }
  if (pick) {
    pick.innerHTML =
      `<option value="">— select —</option>` +
      equips.map((e) => `<option value="${e.id}">${e.name || e.id}</option>`).join("");
    pick.value = equipId;
  }
  renderRuleList();
  await loadPlot();
  await loadInspect();
}

export function resizeFddCharts() {
  resizeCharts();
}
