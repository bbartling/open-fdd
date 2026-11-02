import {
  loadOverviewRcxPreset,
  OVERVIEW_RCX_PRESET_IDS,
} from "./rcx-presets.js";
import { mountChart, resizeCharts, disposeChart } from "./chart-kit.js";
import {
  DEFAULT_SERIES_PREVIEW_ROWS,
  SERIES_PREVIEW_ROW_OPTIONS,
  recentSeriesPreviewFromLines,
  renderPreviewTable,
} from "./series-preview.js";

let presetId = OVERVIEW_RCX_PRESET_IDS[0];
let previewRows = DEFAULT_SERIES_PREVIEW_ROWS;
let lineSeries = [];
let mapping = null;
let buildingId = "";
let rcxTabBound = false;

const $ = (id) => document.getElementById(id);

export function bindRcxTab() {
  const pick = $("presetPick");
  if (!pick || rcxTabBound) return;
  rcxTabBound = true;
  pick.innerHTML = OVERVIEW_RCX_PRESET_IDS.map(
    (id) => `<option value="${id}">${id.replace(/_/g, " ")}</option>`,
  ).join("");
  pick.value = presetId;
  pick.addEventListener("change", () => {
    presetId = pick.value;
    refreshRcxTab().catch(() => {});
  });
  $("rcxPreviewPick").innerHTML = SERIES_PREVIEW_ROW_OPTIONS.map(
    (n) => `<option value="${n}">${n}</option>`,
  ).join("");
  $("rcxPreviewPick").value = String(previewRows);
  $("rcxPreviewPick").addEventListener("change", () => {
    previewRows = Number($("rcxPreviewPick").value);
    renderPreviewTable(
      $("rcxPreviewTable"),
      recentSeriesPreviewFromLines(lineSeries, previewRows),
    );
  });
  $("refreshRcxBtn")?.addEventListener("click", () =>
    refreshRcxTab(true).catch(() => {}),
  );
}

export function onRcxSiteChange(site, siteMapping) {
  buildingId = site;
  mapping = siteMapping;
}

export async function refreshRcxTab(refresh = false) {
  if (!buildingId || !$("mainChart")) return;
  disposeChart($("mainChart"));
  disposeChart($("companionChart"));
  $("companionPanel").hidden = true;
  $("rcxLoadMsg").textContent = "Loading…";
  const result = await loadOverviewRcxPreset(buildingId, presetId, mapping, refresh);
  if (result.error) {
    $("rcxLoadMsg").textContent = result.error;
    renderPreviewTable($("rcxPreviewTable"), null);
    return;
  }
  $("rcxLoadMsg").textContent = result.env?.stale ? "cached (stale)" : "ready";
  if (result.chart?.option) {
    mountChart($("mainChart"), result.chart.option);
    lineSeries = result.lineSeries || [];
  }
  if (result.companion?.option) {
    $("companionPanel").hidden = false;
    mountChart($("companionChart"), result.companion.option);
  }
  renderPreviewTable(
    $("rcxPreviewTable"),
    recentSeriesPreviewFromLines(lineSeries, previewRows),
  );
}

export function resizeRcxCharts() {
  resizeCharts();
}
