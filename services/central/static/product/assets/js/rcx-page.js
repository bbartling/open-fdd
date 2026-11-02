import { bindLogin, fillEquipPicker, fillSitePicker } from "./page-shell.js";
import { loadSiteData } from "./site-data.js";
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

const $ = (id) => document.getElementById(id);
let buildingId = "";
let mapping = null;
let presetId = OVERVIEW_RCX_PRESET_IDS[0];
let previewRows = DEFAULT_SERIES_PREVIEW_ROWS;
let lineSeries = [];

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

function fillPresetPicker() {
  const pick = $("presetPick");
  pick.innerHTML = OVERVIEW_RCX_PRESET_IDS.map(
    (id) => `<option value="${id}">${id.replace(/_/g, " ")}</option>`,
  ).join("");
  pick.value = presetId;
}

function fillPreviewPicker() {
  const pick = $("previewPick");
  pick.innerHTML = SERIES_PREVIEW_ROW_OPTIONS.map(
    (n) => `<option value="${n}">${n}</option>`,
  ).join("");
  pick.value = String(previewRows);
}

async function loadPreset() {
  showErr("");
  $("loadMsg").textContent = "Loading…";
  disposeChart($("mainChart"));
  disposeChart($("companionChart"));
  $("companionPanel").hidden = true;
  try {
    const result = await loadOverviewRcxPreset(buildingId, presetId, mapping, false);
    if (result.error) {
      $("loadMsg").textContent = result.error;
      $("mainChart").innerHTML = "";
      renderPreviewTable($("previewTable"), null);
      return;
    }
    $("loadMsg").textContent = result.env?.stale ? "cached (stale)" : "ready";
    if (result.chart?.option) {
      mountChart($("mainChart"), result.chart.option);
      lineSeries = result.lineSeries || result.chart.lineSeries || [];
    }
    if (result.companion?.option) {
      $("companionPanel").hidden = false;
      mountChart($("companionChart"), result.companion.option);
    }
    const table = recentSeriesPreviewFromLines(lineSeries, previewRows);
    renderPreviewTable($("previewTable"), table);
  } catch (err) {
    showErr(err.message || String(err));
    $("loadMsg").textContent = "error";
  }
}

async function onSite(site) {
  buildingId = site;
  if (!buildingId) return;
  const data = await loadSiteData(buildingId);
  mapping = data.mapping;
  await fillEquipPicker("equipPick", data.model.equips, "");
  await loadPreset();
}

async function boot() {
  fillPresetPicker();
  fillPreviewPicker();
  $("presetPick").addEventListener("change", () => {
    presetId = $("presetPick").value;
    loadPreset();
  });
  $("previewPick").addEventListener("change", () => {
    previewRows = Number($("previewPick").value);
    renderPreviewTable(
      $("previewTable"),
      recentSeriesPreviewFromLines(lineSeries, previewRows),
    );
  });
  $("refreshBtn").addEventListener("click", async () => {
    try {
      const result = await loadOverviewRcxPreset(buildingId, presetId, mapping, true);
      if (result.chart?.option) mountChart($("mainChart"), result.chart.option);
      lineSeries = result.lineSeries || [];
      renderPreviewTable(
        $("previewTable"),
        recentSeriesPreviewFromLines(lineSeries, previewRows),
      );
      $("loadMsg").textContent = "refreshed";
    } catch (err) {
      showErr(err.message);
    }
  });
  window.addEventListener("resize", () => resizeCharts());
  buildingId = await fillSitePicker("sitePick", onSite);
  if (buildingId) await onSite(buildingId);
}

if (bindLogin(boot)) boot();
