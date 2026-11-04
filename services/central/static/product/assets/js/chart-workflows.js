/**
 * Chart parity workflows: visible control → bounded request → adapter → ECharts option.
 * Each ported chart-parity.json row (except dropped/internal) maps to one workflow entry.
 */
import { postAnalytics, analyticsBody } from "./analytics.js";
import { analyticsWindowFromSampling } from "./window-policy.js";
import { ECONOMIZER_DT_MIN_C, normalizeTipOverviewEnvelope } from "./tip-analytics-normalize.js";
import { expandFddPlotRoles, fddPlotOption, isOatMeteoRule, oatMeteoFddOption } from "./fdd-charts.js";
import { inspectChartOption } from "./chart-kit.js";
import { sensorHealthHeatmapOption, sensorFaultChartOption } from "./sensor-charts.js";
import {
  summaryPeerBulletOption,
  summaryPeerBarsOption,
  rankedSiteEuiOption,
  rolling12EuiOption,
  intensityHeatmapForFuelOption,
  intensityHeatmapOption,
  stackedFuelOption,
  monthlyLinesOption,
  demandHeatmapOption,
  weatherScatterOption,
  weatherResidualBarsOption,
  demandPeakDualAxisOption,
  peakVsCoolSeasonOption,
} from "./fuel-charts.js";
import {
  weeklyMotorOption,
  mechCoolingOption,
  economizerDeltaOption,
  economizerMatResidOption,
  economizerTempsOverlayOption,
  basOverlayOption,
  basHistOption,
} from "./overview-rcx-charts.js";
import {
  multiEquipmentTimeseriesOption,
  oatScatterOption,
  multiEquipmentBoxOption,
  rankingBarsOption,
  comfortDonutOption,
  meteringChartsOption,
  vavHealthWorstBarsOption,
  vavHealthDonutOption,
  rcxPresetOption,
} from "./rcx-vibe-charts.js";
import { mvChartOption } from "./mv-charts.js";
import { MV_DEMO_SEED } from "./mv-demo-seed.js";
import { REQUIRED_RCX_PRESET_IDS } from "./rcx-catalog.js";

export { REQUIRED_RCX_PRESET_IDS };

export const ANALYTICS_GROUPS = ["sensor", "fuel", "generic-rcx"];

export function parityBuilderSuffix(oldBuilder) {
  const part = String(oldBuilder || "").split("#")[1] || String(oldBuilder || "");
  if (part.includes("HealthMatrixSection")) return "HealthMatrixSection";
  if (part.includes("equipmentInspectionChart")) return "equipmentInspectionChart";
  return part.split(".")[0]?.replace(/.*\//, "") || part;
}

function wf(entry) {
  return entry;
}

/** @typedef {{ buildingId: string, equipmentId?: string, mapping?: object, ruleId?: string, roleUnitIndex?: Map, unitSystem?: string }} WorkflowContext */

const OVERVIEW_PRESET_BY_STEM = {
  ahu_motor_weekly: "ahu_motor_weekly",
  boiler_motor_weekly: "boiler_motor_weekly",
  chiller_motor_weekly: "chiller_motor_weekly",
  mech_cooling_oat_bins: "mech_cooling_oat_bins",
  economizer_free_cooling_delta: "economizer_delta",
  economizer_mat_residual: "economizer_mat_resid",
  economizer_temps_oa_damper: "economizer_temps_overlay",
  bas_vs_web_oat: "bas_vs_web_oat",
};

const FUEL_QUERY_BY_RENDERER = {
  summaryPeerBulletOption: "fuel-summary-v1",
  summaryPeerBarsOption: "fuel-summary-v1",
  rankedSiteEuiOption: "fuel-summary-v1",
  rolling12EuiOption: "fuel-stacked-v1",
  intensityHeatmapForFuelOption: "fuel-intensity-v1",
  intensityHeatmapOption: "fuel-intensity-v1",
  stackedFuelOption: "fuel-stacked-v1",
  monthlyLinesOption: "fuel-monthly-v1",
  demandHeatmapOption: "fuel-demand-v1",
  weatherScatterOption: "fuel-weather-v1",
  weatherResidualBarsOption: "fuel-weather-v1",
  demandPeakDualAxisOption: "fuel-demand-v1",
  peakVsCoolSeasonOption: "fuel-demand-v1",
};

const GENERIC_RCX_BY_RENDERER = {
  multiEquipmentTimeseriesOption: "zone_temps",
  oatScatterOption: "ahu_sat_reset_scatter",
  multiEquipmentBoxOption: "duct_static_box",
  rankingBarsOption: "zone_comfort_rank",
  comfortDonutOption: "zone_comfort_rank",
  meteringChartsOption: "meter_elec_cdd",
  vavHealthWorstBarsOption: "vav_flows",
  vavHealthDonutOption: "vav_flows",
};

function boundedWindow(mapping) {
  return analyticsWindowFromSampling(mapping?.equipment ?? []);
}

function analyticsPost(buildingId, mapping, maxPoints) {
  const window = boundedWindow(mapping);
  return {
    building_id: buildingId,
    max_points: maxPoints,
    dt_min_c: ECONOMIZER_DT_MIN_C,
    ...window,
  };
}

function fuelBody(buildingId, queryVersion, maxPoints = 2500) {
  return {
    building_id: buildingId,
    query_version: queryVersion,
    max_points: maxPoints,
  };
}

export const CHART_WORKFLOWS = [
  wf({
    builder: "ruleResultChart",
    tab: "fdd",
    controlId: "ruleList",
    group: "fdd",
    maxPoints: 1500,
    endpoint: "GET /api/fdd/plot",
    pngStem: "fdd_{rule_id}_{equipment_id}",
    renderer: fddPlotOption,
    internal: false,
    sampleOption(ctx) {
      return fddPlotOption(
        [{ timestamp_utc: "2026-01-01T00:00:00Z", zone_t: 21, confirmed_fault: 0 }],
        ["zone_t"],
        true,
        {
          ruleId: ctx.ruleId || "FC1",
          equipmentId: ctx.equipmentId || "EQ1",
        },
      )?.option;
    },
  }),
  wf({
    builder: "expandFddPlotRoles",
    tab: "fdd",
    controlId: "ruleList",
    group: "fdd",
    internal: true,
    parentBuilder: "ruleResultChart",
    maxPoints: 1500,
    endpoint: "internal",
    renderer: expandFddPlotRoles,
    sampleOption() {
      return expandFddPlotRoles("FC1", ["zone_t"], [{ zone_t: 1 }]).length >= 1 ? {} : null;
    },
  }),
  wf({
    builder: "withConfirmedFaultLane",
    tab: "fdd",
    controlId: "ruleList",
    group: "fdd",
    maxPoints: 1500,
    endpoint: "POST /api/analytics/bas-vs-web-oat + GET /api/fdd/plot",
    pngStem: "fdd_OAT-METEO_weather",
    renderer: oatMeteoFddOption,
    sampleOption() {
      return oatMeteoFddOption(
        [{ bas_oat_c: 10, web_oat_c: 11 }],
        ["2026-01-01T00:00:00Z"],
        [1],
        { ruleId: "OAT-METEO", equipmentId: "WX" },
      )?.option;
    },
  }),
  wf({
    builder: "sensorHealthHeatmap",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "sensor_health",
    group: "sensor",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/sensor-health",
    pngStem: "sensor_health",
    renderer: sensorHealthHeatmapOption,
    async fetch(buildingId, mapping) {
      return postAnalytics("/api/analytics/sensor-health", analyticsPost(buildingId, mapping, 4000));
    },
    adapt(envelope) {
      return sensorHealthHeatmapOption(envelope?.rows ?? envelope?.points ?? [], {
        pngStem: "sensor_health",
      });
    },
    sampleOption() {
      return sensorHealthHeatmapOption(
        [{ equipment_id: "AHU_1", role: "oa_t", coverage_pct: 0.9 }],
        { pngStem: "sensor_health" },
      );
    },
  }),
  wf({
    builder: "sensorFaultChart",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "sensor_fault",
    group: "sensor",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/sensor-fault",
    pngStem: "sensor_fault",
    renderer: sensorFaultChartOption,
    async fetch(buildingId, mapping) {
      return postAnalytics("/api/analytics/sensor-fault", analyticsPost(buildingId, mapping, 4000));
    },
    adapt(envelope) {
      const points = envelope?.points ?? envelope?.rows ?? [];
      return sensorFaultChartOption(points, {
        pngStem: "sensor_fault",
        sensorName: points[0]?.role ?? "sensor",
      });
    },
    sampleOption() {
      return sensorFaultChartOption(
        [{ timestamp_utc: "2026-01-01T00:00:00Z", value_f: 72, fault: 0 }],
        { pngStem: "sensor_fault", sensorName: "oa_t" },
      );
    },
  }),
  wf({
    builder: "deriveSensorFaultMasks",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "sensor_fault",
    group: "sensor",
    internal: true,
    parentBuilder: "sensorFaultChart",
    maxPoints: 4000,
    endpoint: "internal",
    renderer: null,
    sampleOption() {
      return {};
    },
  }),
  wf({
    builder: "equipmentInspectionChart",
    tab: "fdd",
    controlId: "inspectChart",
    group: "fdd",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/inspect",
    pngStem: "{equipment_id}_inspect",
    renderer: inspectChartOption,
    sampleOption(ctx) {
      return inspectChartOption(
        ctx.equipmentId || "EQ1",
        [{ timestamp_utc: "2026-01-01T00:00:00Z", zone_t: 21 }],
        ["zone_t"],
        "metric",
        ctx.roleUnitIndex ?? null,
      )?.option;
    },
  }),
  wf({
    builder: "weeklyPlantFigures",
    pngStem: "ahu_motor_weekly",
    tab: "rcx",
    controlId: "presetPick",
    pickValue: "ahu_motor_weekly",
    group: "overview-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/runtime",
    renderer: weeklyMotorOption,
    sampleOption() {
      return weeklyMotorOption(
        [
          {
            kind: "weekly_equipment",
            plant_group: "air",
            week_label: "2026-01",
            label: "AHU_1",
            run_hours: 12,
          },
        ],
        "air",
        "ahu_motor_weekly",
      )?.option;
    },
  }),
  wf({
    builder: "weeklyPlantFigures",
    pngStem: "boiler_motor_weekly",
    tab: "rcx",
    controlId: "presetPick",
    pickValue: "boiler_motor_weekly",
    group: "overview-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/runtime",
    renderer: weeklyMotorOption,
    sampleOption() {
      return weeklyMotorOption(
        [
          {
            kind: "weekly_equipment",
            plant_group: "boiler",
            week_label: "2026-01",
            label: "BLR_1",
            run_hours: 8,
          },
        ],
        "boiler",
        "boiler_motor_weekly",
      )?.option;
    },
  }),
  wf({
    builder: "weeklyPlantFigures",
    pngStem: "chiller_motor_weekly",
    tab: "rcx",
    controlId: "presetPick",
    pickValue: "chiller_motor_weekly",
    group: "overview-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/runtime",
    renderer: weeklyMotorOption,
    sampleOption() {
      return weeklyMotorOption(
        [
          {
            kind: "weekly_equipment",
            plant_group: "chiller",
            week_label: "2026-01",
            label: "CHW_1",
            run_hours: 6,
          },
        ],
        "chiller",
        "chiller_motor_weekly",
      )?.option;
    },
  }),
  wf({
    builder: "mechFigure",
    tab: "rcx",
    controlId: "presetPick",
    pickValue: "mech_cooling_oat_bins",
    group: "overview-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/mechanical-cooling",
    pngStem: "mech_cooling_oat_bins",
    renderer: mechCoolingOption,
    sampleOption() {
      return mechCoolingOption(
        [{ kind: "oat_bin", oat_bin: "10-15C", equipment_id: "CHW_1", run_hours: 12 }],
        "mech_cooling_oat_bins",
      )?.option;
    },
  }),
  wf({
    builder: "econDeltaScatter",
    tab: "rcx",
    controlId: "presetPick",
    pickValue: "economizer_delta",
    group: "overview-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/economizer",
    pngStem: "economizer_free_cooling_delta",
    renderer: economizerDeltaOption,
    sampleOption() {
      const pts = Array.from({ length: 6 }, (_, i) => ({
        identifiable: true,
        delta_or_c: -2 - i * 0.1,
        delta_mr_c: 1 + i * 0.05,
        damper_fb_pct: 30 + i,
      }));
      return economizerDeltaOption(pts, "metric", ECONOMIZER_DT_MIN_C, "economizer_free_cooling_delta")
        ?.option;
    },
  }),
  wf({
    builder: "econMatResidual",
    tab: "rcx",
    controlId: "presetPick",
    pickValue: "economizer_mat_resid",
    group: "overview-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/economizer",
    pngStem: "economizer_mat_residual",
    renderer: economizerMatResidOption,
    sampleOption() {
      const pts = Array.from({ length: 6 }, (_, i) => ({
        identifiable: true,
        equipment_id: "AHU_1",
        timestamp_utc: `2026-01-01T0${i}:00:00Z`,
        mat_resid_c: 0.5 + i * 0.1,
      }));
      return economizerMatResidOption(pts, "metric", "economizer_mat_residual")?.option;
    },
  }),
  wf({
    builder: "econTempsOverlay",
    tab: "rcx",
    controlId: "presetPick",
    pickValue: "economizer_temps_overlay",
    group: "overview-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/economizer",
    pngStem: "economizer_temps_oa_damper",
    renderer: economizerTempsOverlayOption,
    sampleOption() {
      return economizerTempsOverlayOption(
        [
          {
            equipment_id: "AHU_1",
            timestamp_utc: "2026-01-01T00:00:00Z",
            oa_t: 5,
            rat: 10,
            mat: 12,
            sat: 14,
          },
          {
            equipment_id: "AHU_1",
            timestamp_utc: "2026-01-01T01:00:00Z",
            oa_t: 6,
            rat: 11,
            mat: 13,
            sat: 15,
          },
          {
            equipment_id: "AHU_1",
            timestamp_utc: "2026-01-01T02:00:00Z",
            oa_t: 7,
            rat: 12,
            mat: 14,
            sat: 16,
          },
        ],
        "metric",
        "AHU_1",
        "economizer_temps_oa_damper",
      )?.option;
    },
  }),
  wf({
    builder: "basOverlay",
    tab: "charts",
    controlId: "chartsBasPick",
    pickValue: "bas_overlay",
    group: "charts",
    maxPoints: 1500,
    endpoint: "POST /api/analytics/bas-vs-web-oat",
    pngStem: "bas_vs_web_oat",
    renderer: basOverlayOption,
    sampleOption() {
      return basOverlayOption(
        [{ timestamp_utc: "2026-01-01T00:00:00Z", bas_oat_c: 10, web_oat_c: 11 }],
        "metric",
        2,
        "bas_vs_web_oat",
      )?.option;
    },
  }),
  wf({
    builder: "basHist",
    tab: "charts",
    controlId: "chartsBasPick",
    pickValue: "bas_hist",
    group: "charts",
    maxPoints: 1500,
    endpoint: "POST /api/analytics/bas-vs-web-oat",
    pngStem: "bas_web_oat_deviation_hist",
    renderer: basHistOption,
    sampleOption() {
      return basHistOption(
        [{ kind: "delta_hist", bin_lo_f: -1, count: 3 }],
        "metric",
        "bas_web_oat_deviation_hist",
      )?.option;
    },
  }),
  wf({
    builder: "multiEquipmentTimeseries",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_zone_temps",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    pngStem: "rcx_{family}_{preset}",
    renderer: multiEquipmentTimeseriesOption,
    presetId: "zone_temps",
    sampleOption() {
      return multiEquipmentTimeseriesOption(
        [{ equipment_id: "VAV_1", timestamp_utc: "2026-01-01T00:00:00Z", value_f: 72 }],
        { pngStem: "rcx_Zones_zone_temps" },
      );
    },
  }),
  wf({
    builder: "oatScatter",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_ahu_sat_reset_scatter",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    pngStem: "rcx_{family}_{preset}",
    renderer: oatScatterOption,
    presetId: "ahu_sat_reset_scatter",
    sampleOption() {
      return oatScatterOption([{ oat_f: 50, value_f: 60 }], { pngStem: "rcx_scatter" });
    },
  }),
  wf({
    builder: "multiEquipmentBox",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_duct_static_box",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    renderer: multiEquipmentBoxOption,
    presetId: "duct_static_box",
    sampleOption() {
      return multiEquipmentBoxOption([{ equipment_id: "AHU_1", value_f: 0.5 }], { pngStem: "rcx_box" });
    },
  }),
  wf({
    builder: "rankingBars",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_zone_comfort_rank",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    renderer: rankingBarsOption,
    presetId: "zone_comfort_rank",
    sampleOption() {
      return rankingBarsOption([{ equipment_id: "VAV_1", value_f: 2 }], { pngStem: "rcx_rank" });
    },
  }),
  wf({
    builder: "comfortDonut",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_comfort_donut",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    renderer: comfortDonutOption,
    presetId: "zone_comfort_rank",
    sampleOption() {
      return comfortDonutOption([{ label: "ok", value_f: 3 }], { pngStem: "rcx_donut" });
    },
  }),
  wf({
    builder: "meteringCharts",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_meter_elec_cdd",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    renderer: meteringChartsOption,
    presetId: "meter_elec_cdd",
    sampleOption() {
      return meteringChartsOption([{ month: "2026-01", energy: 100, dd: 20 }], { pngStem: "rcx_meter" });
    },
  }),
  wf({
    builder: "vavHealthWorstBars",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_vav_worst",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    renderer: vavHealthWorstBarsOption,
    presetId: "vav_flows",
    sampleOption() {
      return vavHealthWorstBarsOption([{ equipment_id: "VAV_1", value_f: 5 }], { pngStem: "rcx_vav" });
    },
  }),
  wf({
    builder: "vavHealthDonut",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_vav_donut",
    group: "generic-rcx",
    maxPoints: 4000,
    endpoint: "POST /api/analytics/rcx/preset",
    renderer: vavHealthDonutOption,
    presetId: "vav_flows",
    sampleOption() {
      return vavHealthDonutOption([{ label: "ok", value_f: 1 }], { pngStem: "rcx_vav_donut" });
    },
  }),
  wf({
    builder: "summaryPeerBullet",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_summary_bullet",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_summary_bullet",
    renderer: summaryPeerBulletOption,
    queryVersion: "fuel-summary-v1",
    sampleOption() {
      return summaryPeerBulletOption([{ site: "S1", eui: 50 }]);
    },
  }),
  wf({
    builder: "summaryPeerBars",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_summary_bars",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_summary_bullet",
    renderer: summaryPeerBarsOption,
    queryVersion: "fuel-summary-v1",
    sampleOption() {
      return summaryPeerBarsOption([{ site: "S1", eui: 50 }]);
    },
  }),
  wf({
    builder: "rankedSiteEui",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_ranked_eui",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_ranked_eui",
    renderer: rankedSiteEuiOption,
    queryVersion: "fuel-summary-v1",
    sampleOption() {
      return rankedSiteEuiOption([{ site: "S1", eui: 40 }]);
    },
  }),
  wf({
    builder: "rolling12Eui",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_roll12",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_roll12",
    renderer: rolling12EuiOption,
    queryVersion: "fuel-stacked-v1",
    sampleOption() {
      return rolling12EuiOption([{ month: "2026-01", kwh: 1000 }]);
    },
  }),
  wf({
    builder: "intensityHeatmapForFuel",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_intensity_elec",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_intensity_elec",
    renderer: intensityHeatmapForFuelOption,
    queryVersion: "fuel-intensity-v1",
    sampleOption() {
      return intensityHeatmapForFuelOption([{ month: "2026-01", intensity: 1.2 }]);
    },
  }),
  wf({
    builder: "intensityHeatmap",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_intensity_gas",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_intensity_gas",
    renderer: intensityHeatmapOption,
    queryVersion: "fuel-intensity-v1",
    sampleOption() {
      return intensityHeatmapOption([{ month: "2026-01", intensity: 0.8 }]);
    },
  }),
  wf({
    builder: "stackedFuel",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_stacked",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_stacked",
    renderer: stackedFuelOption,
    queryVersion: "fuel-stacked-v1",
    sampleOption() {
      return stackedFuelOption([{ month: "2026-01", fuel: "elec", value: 10 }]);
    },
  }),
  wf({
    builder: "monthlyLines",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_monthly",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_monthly",
    renderer: monthlyLinesOption,
    queryVersion: "fuel-monthly-v1",
    sampleOption() {
      return monthlyLinesOption([{ month: "2026-01", kwh: 100 }]);
    },
  }),
  wf({
    builder: "demandHeatmap",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_demand",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_demand",
    renderer: demandHeatmapOption,
    queryVersion: "fuel-demand-v1",
    sampleOption() {
      return demandHeatmapOption([{ hour: 12, dow: 1, kw: 50 }]);
    },
  }),
  wf({
    builder: "weatherScatter",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_weather_scatter",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_weather",
    renderer: weatherScatterOption,
    queryVersion: "fuel-weather-v1",
    sampleOption() {
      return weatherScatterOption([{ oat: 40, usage: 100 }]);
    },
  }),
  wf({
    builder: "weatherResidualBars",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_weather_residual",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_weather",
    renderer: weatherResidualBarsOption,
    queryVersion: "fuel-weather-v1",
    sampleOption() {
      return weatherResidualBarsOption([{ month: "2026-01", residual: 1 }], "fuel_weather");
    },
  }),
  wf({
    builder: "demandPeakDualAxis",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_demand_peak",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_demand_peak",
    renderer: demandPeakDualAxisOption,
    queryVersion: "fuel-demand-v1",
    sampleOption() {
      return demandPeakDualAxisOption([{ month: "2026-01", peak_kw: 200 }], {});
    },
  }),
  wf({
    builder: "peakVsCoolSeason",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "fuel_peak_cool",
    group: "fuel",
    maxPoints: 2500,
    endpoint: "POST /api/analytics/fuel",
    pngStem: "fuel_peak_cool",
    renderer: peakVsCoolSeasonOption,
    queryVersion: "fuel-demand-v1",
    sampleOption() {
      return peakVsCoolSeasonOption([{ year: "2026", peak_kw: 180 }], {});
    },
  }),
  wf({
    builder: "MvChangePointPanel",
    tab: "ops",
    controlId: "demoMvRun",
    group: "ops",
    maxPoints: 500,
    endpoint: "POST /api/analytics/mv",
    pngStem: "mv_change_point",
    renderer: mvChartOption,
    sampleOption() {
      return mvChartOption({ ok: true, series: MV_DEMO_SEED, savings: { pct: 5 } });
    },
  }),
  wf({
    builder: "outlierEquipmentIds",
    tab: "analytics",
    controlId: "analyticsChartPick",
    pickValue: "rcx_zone_temps",
    group: "generic-rcx",
    internal: true,
    parentBuilder: "multiEquipmentTimeseries",
    maxPoints: 4000,
    endpoint: "internal",
    renderer: null,
    sampleOption() {
      return {};
    },
  }),
];

export function workflowForParityRow(row) {
  const builder = parityBuilderSuffix(row.old_builder);
  const stem = row.png_stem ?? null;
  const matches = CHART_WORKFLOWS.filter((w) => {
    if (w.builder !== builder) return false;
    if (stem && w.pngStem && w.pngStem !== stem) return false;
    return true;
  });
  if (matches.length === 1) return matches[0];
  if (matches.length > 1 && stem) {
    const byStem = matches.find((w) => w.pngStem === stem);
    if (byStem) return byStem;
  }
  return matches[0] ?? null;
}

export function analyticsWorkflowOptions(group) {
  return CHART_WORKFLOWS.filter(
    (w) => w.group === group && w.tab === "analytics" && !w.internal && w.pickValue,
  );
}

export function optionHasSeries(option) {
  if (!option || typeof option !== "object") return false;
  const series = option.series;
  if (Array.isArray(series) && series.length) return true;
  return false;
}

export async function runAnalyticsWorkflow(workflow, buildingId, mapping, refresh = false) {
  if (!workflow || workflow.internal) {
    return { error: "Workflow not runnable" };
  }
  if (workflow.group === "fuel") {
    const body = fuelBody(buildingId, workflow.queryVersion, workflow.maxPoints);
    if (refresh) body.refresh = true;
    const envelope = await postAnalytics("/api/analytics/fuel", body);
    const rows = envelope?.rows ?? envelope?.points ?? [];
    let option = null;
    if (workflow.renderer === intensityHeatmapForFuelOption) {
      option = workflow.renderer(rows, workflow.pngStem);
    } else {
      option = workflow.renderer(rows, workflow.pngStem);
    }
    return { option, rows, envelope };
  }
  if (workflow.group === "generic-rcx") {
    const window = boundedWindow(mapping);
    const body = {
      building_id: buildingId,
      max_points: workflow.maxPoints,
      ...window,
      series: { preset_id: workflow.presetId },
      ...(refresh ? { refresh: true } : {}),
    };
    const envelope = await postAnalytics("/api/analytics/rcx/preset", body);
    const points = envelope?.points ?? envelope?.rows ?? [];
    const coverage = envelope?.coverage ?? { preset_id: workflow.presetId };
    const chart = rcxPresetOption(coverage, points, { pngStem: workflow.pngStem ?? "rcx_plot" });
    return { option: chart, rows: points, envelope, lineSeries: [] };
  }
  if (workflow.fetch) {
    const envelope = await workflow.fetch(buildingId, mapping);
    const option = workflow.adapt(envelope);
    return {
      option,
      rows: envelope?.rows ?? envelope?.points ?? [],
      envelope,
    };
  }
  return { error: "Unsupported workflow group" };
}

export async function runChartsBasWorkflow(workflow, buildingId, equipmentIds, windowOrHours) {
  const body = analyticsBody(buildingId, equipmentIds, windowOrHours, workflow.maxPoints);
  const envelope = await postAnalytics("/api/analytics/bas-vs-web-oat", body);
  const rows = envelope?.rows ?? envelope?.points ?? [];
  if (workflow.renderer === basHistOption) {
    const histRows = rows.filter((r) => r.kind === "delta_hist" || r.count != null);
    const built = basHistOption(histRows.length ? histRows : rows, "metric", workflow.pngStem);
    return { option: built?.option ?? null, rows };
  }
  const points = rows.map((row) => ({
    timestamp_utc: row.timestamp_utc ?? row.ts,
    bas_oat_c: row.bas_oa_t ?? row.bas_oat_c,
    web_oat_c: row.web_oa_t ?? row.web_oat_c,
  }));
  return {
    option: basOverlayOption(points, "metric", ECONOMIZER_DT_MIN_C, workflow.pngStem),
    rows,
  };
}

export function overviewPresetForStem(stem) {
  return OVERVIEW_PRESET_BY_STEM[stem] ?? null;
}

export function fuelQueryForRendererName(name) {
  return FUEL_QUERY_BY_RENDERER[name] ?? "fuel-summary-v1";
}

export function genericPresetForRendererName(name) {
  return GENERIC_RCX_BY_RENDERER[name] ?? "zone_temps";
}

export function assertNoVoidRenderersInAppSource(appSource) {
  const voided = [];
  const re = /void\s+([A-Za-z0-9_]+)/g;
  let m;
  while ((m = re.exec(appSource)) !== null) {
    voided.push(m[1]);
  }
  const chartFns = CHART_WORKFLOWS.filter((w) => !w.internal && w.renderer).map(
    (w) => w.renderer.name,
  );
  for (const name of voided) {
    if (chartFns.includes(name)) {
      throw new Error(`app.js voids reachable renderer ${name}`);
    }
  }
}
