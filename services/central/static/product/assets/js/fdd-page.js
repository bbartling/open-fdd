import { bindLogin, fillEquipPicker, fillSitePicker } from "./page-shell.js";
import { loadSiteData } from "./site-data.js";
import { getFddRules, getFddResults, runFdd, fetchFddPlotSeries } from "./fdd-api.js";
import {
  fddStatusBucket,
  preferredPlotRuleId,
  ruleApplicable,
  mappedRolesForEquip,
} from "./fdd-status.js";
import { analyticsWindowFromSampling } from "./window-policy.js";
import { mountChart, resizeCharts, fddPlotOption, inspectChartOption } from "./chart-kit.js";
import { fetchInspectSeries } from "./analytics.js";
import {
  DEFAULT_SERIES_PREVIEW_ROWS,
  SERIES_PREVIEW_ROW_OPTIONS,
  recentSeriesPreviewFromLines,
  renderPreviewTable,
} from "./series-preview.js";

const $ = (id) => document.getElementById(id);
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

function showErr(msg) {
  const el = $("err");
  if (!msg) {
    el?.classList.remove("show");
    if (el) el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.add("show");
}

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
  const list = filteredRules();
  const byStatus = statusMap();
  if (!selectedRuleId || !list.some((r) => r.rule_id === selectedRuleId)) {
    selectedRuleId = preferredPlotRuleId(
      list.map((r) => r.rule_id),
      byStatus,
    );
  }
  $("ruleList").innerHTML = list
    .map((rule) => {
      const st = fddStatusBucket(byStatus.get(rule.rule_id));
      const on = rule.rule_id === selectedRuleId ? " sel" : "";
      return `<button type="button" class="rule-pick${on}" data-rule="${rule.rule_id}">
        <span class="rule-id">${rule.rule_id}</span>
        <span class="pill">${st}</span>
      </button>`;
    })
    .join("") || `<p class="hint">No rules match filter / mapping.</p>`;
}

async function loadPlot() {
  if (!buildingId || !equipId || !selectedRuleId) return;
  const window = analyticsWindowFromSampling(mapping?.equipment ?? []);
  try {
    const body = await fetchFddPlotSeries(buildingId, equipId, selectedRuleId, window);
    const roles = body.roles || [];
    const rows = body.rows || [];
    const built = fddPlotOption(rows, roles, body.has_confirmed_fault);
    mountChart($("fddChart"), built.option);
    plotLineSeries = built.lineSeries;
    $("plotHint").textContent = `${roles.length} roles · ${rows.length} rows`;
    renderPreviewTable(
      $("previewTable"),
      recentSeriesPreviewFromLines(plotLineSeries, previewRows),
    );
  } catch (err) {
    showErr(err.message);
  }
}

async function loadInspect() {
  if (!buildingId || !equipId || !selectedRuleId) return;
  const rule = rules.find((r) => r.rule_id === selectedRuleId);
  const required = rule?.required_roles || [];
  const optional = rule?.optional_roles || [];
  const roles = [...required, ...optional.filter(Boolean)];
  const rows = await fetchInspectSeries(buildingId, equipId, 168, roles);
  const built = inspectChartOption(equipId, rows, roles);
  $("inspectHost").style.height = `${built.heightPx}px`;
  mountChart($("inspectChart"), built.option);
}

async function refreshResults() {
  results = await getFddResults(buildingId);
  renderRuleList();
  await loadPlot();
  await loadInspect();
}

async function onEquipChange(id) {
  equipId = id;
  renderRuleList();
  await loadPlot();
  await loadInspect();
}

let equipBound = false;

async function onSite(site) {
  buildingId = site;
  const data = await loadSiteData(buildingId);
  mapping = data.mapping;
  sessionConfig = data.sessionConfig;
  rules = await getFddRules();
  results = await getFddResults(buildingId);
  equipId = await fillEquipPicker("equipPick", data.model.equips, equipId);
  if (!equipBound) {
    equipBound = true;
    $("equipPick").addEventListener("change", () => onEquipChange($("equipPick").value));
  }
  renderRuleList();
  await loadPlot();
  await loadInspect();
}

async function boot() {
  $("statusFilter").innerHTML = ["All", "FAULT", "PASS", "SKIPPED", "Not run"]
    .map((s) => `<option value="${s}">${s}</option>`)
    .join("");
  $("statusFilter").addEventListener("change", () => {
    statusFilter = $("statusFilter").value;
    renderRuleList();
  });
  $("previewPick").innerHTML = SERIES_PREVIEW_ROW_OPTIONS.map(
    (n) => `<option value="${n}">${n}</option>`,
  ).join("");
  $("previewPick").value = String(previewRows);
  $("previewPick").addEventListener("change", () => {
    previewRows = Number($("previewPick").value);
    renderPreviewTable(
      $("previewTable"),
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
      await refreshResults();
    } catch (err) {
      $("runMsg").textContent = "failed";
      showErr(err.message);
    }
  });
  window.addEventListener("resize", () => resizeCharts());
  buildingId = await fillSitePicker("sitePick", onSite);
  if (buildingId) await onSite(buildingId);
}

if (bindLogin(boot)) boot();
