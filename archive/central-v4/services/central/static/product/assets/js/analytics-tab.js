import {
  analyticsWorkflowOptions,
  runAnalyticsWorkflow,
  ANALYTICS_GROUPS,
} from "./chart-workflows.js";
import { mountChart, disposeChart, resizeCharts } from "./chart-kit.js";
import {
  DEFAULT_SERIES_PREVIEW_ROWS,
  SERIES_PREVIEW_ROW_OPTIONS,
  recentSeriesPreviewFromLines,
  renderPreviewTable,
} from "./series-preview.js";

let buildingId = "";
let mapping = null;
let group = ANALYTICS_GROUPS[0];
let workflowKey = "";
let previewRows = DEFAULT_SERIES_PREVIEW_ROWS;
let lineSeries = [];
let analyticsBound = false;

const $ = (id) => document.getElementById(id);

function workflowsForUi() {
  return analyticsWorkflowOptions(group);
}

function selectedWorkflow() {
  return workflowsForUi().find((w) => w.pickValue === workflowKey) ?? workflowsForUi()[0];
}

function renderPickers() {
  const groupPick = $("analyticsGroupPick");
  const chartPick = $("analyticsChartPick");
  if (!groupPick || !chartPick) return;
  groupPick.innerHTML = ANALYTICS_GROUPS.map(
    (g) => `<option value="${g}">${g.replace(/-/g, " ")}</option>`,
  ).join("");
  groupPick.value = group;
  const list = workflowsForUi();
  chartPick.innerHTML = list
    .map((w) => `<option value="${w.pickValue}">${w.pickValue.replace(/_/g, " ")}</option>`)
    .join("");
  if (!list.some((w) => w.pickValue === workflowKey)) {
    workflowKey = list[0]?.pickValue ?? "";
  }
  chartPick.value = workflowKey;
}

export function bindAnalyticsTab() {
  if (analyticsBound) return;
  analyticsBound = true;
  renderPickers();
  $("analyticsGroupPick")?.addEventListener("change", () => {
    group = $("analyticsGroupPick").value;
    renderPickers();
    refreshAnalyticsTab().catch(() => {});
  });
  $("analyticsChartPick")?.addEventListener("change", () => {
    workflowKey = $("analyticsChartPick").value;
    refreshAnalyticsTab().catch(() => {});
  });
  $("analyticsPreviewPick").innerHTML = SERIES_PREVIEW_ROW_OPTIONS.map(
    (n) => `<option value="${n}">${n}</option>`,
  ).join("");
  $("analyticsPreviewPick").value = String(previewRows);
  $("analyticsPreviewPick").addEventListener("change", () => {
    previewRows = Number($("analyticsPreviewPick").value);
    renderPreviewTable(
      $("analyticsPreviewTable"),
      recentSeriesPreviewFromLines(lineSeries, previewRows),
    );
  });
  $("refreshAnalyticsBtn")?.addEventListener("click", () =>
    refreshAnalyticsTab(true).catch(() => {}),
  );
}

export function onAnalyticsSiteChange(site, siteMapping) {
  buildingId = site;
  mapping = siteMapping;
}

export async function refreshAnalyticsTab(refresh = false) {
  if (!$("analyticsChart")) return;
  renderPickers();
  if (!buildingId) {
    $("analyticsLoadMsg").textContent = "Pick a site to load analytics charts.";
    disposeChart($("analyticsChart"));
    renderPreviewTable($("analyticsPreviewTable"), null);
    return;
  }
  const workflow = selectedWorkflow();
  if (!workflow) {
    $("analyticsLoadMsg").textContent = "No chart workflow for this group.";
    return;
  }
  disposeChart($("analyticsChart"));
  $("analyticsLoadMsg").textContent = "Loading…";
  try {
    const result = await runAnalyticsWorkflow(workflow, buildingId, mapping, refresh);
    if (result.error) {
      $("analyticsLoadMsg").textContent = result.error;
      renderPreviewTable($("analyticsPreviewTable"), null);
      return;
    }
    if (!result.option || !result.option.series?.length) {
      $("analyticsLoadMsg").textContent =
        result.envelope?.warnings?.[0] ?? "No chart data for this workflow.";
      renderPreviewTable($("analyticsPreviewTable"), null);
      return;
    }
    mountChart($("analyticsChart"), result.option);
    lineSeries = result.lineSeries ?? [];
    $("analyticsLoadMsg").textContent = result.envelope?.stale ? "cached (stale)" : "ready";
    renderPreviewTable(
      $("analyticsPreviewTable"),
      recentSeriesPreviewFromLines(lineSeries, previewRows),
    );
  } catch (err) {
    $("analyticsLoadMsg").textContent = err.message || String(err);
    renderPreviewTable($("analyticsPreviewTable"), null);
  }
}

export function resizeAnalyticsCharts() {
  resizeCharts();
}
