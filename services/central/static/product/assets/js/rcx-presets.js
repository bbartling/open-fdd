import { postAnalytics } from "./analytics.js";
import { analyticsWindowFromSampling } from "./window-policy.js";
import { ECONOMIZER_DT_MIN_C, normalizeTipOverviewEnvelope } from "./tip-analytics-normalize.js";
import {
  weeklyMotorOption,
  mechCoolingOption,
  economizerDeltaOption,
  economizerMatResidOption,
  economizerTempsOverlayOption,
  basOverlayOption,
  basHistOption,
} from "./overview-rcx-charts.js";

export { ECONOMIZER_DT_MIN_C };

export const OVERVIEW_RCX_PRESET_IDS = [
  "ahu_motor_weekly",
  "economizer_delta",
  "economizer_mat_resid",
  "economizer_temps_overlay",
  "boiler_motor_weekly",
  "chiller_motor_weekly",
  "mech_cooling_oat_bins",
  "bas_vs_web_oat",
];

const PLANT_FOR = {
  ahu_motor_weekly: "air",
  boiler_motor_weekly: "boiler",
  chiller_motor_weekly: "chiller",
};

const PNG_STEMS = {
  ahu_motor_weekly: "ahu_motor_weekly",
  boiler_motor_weekly: "boiler_motor_weekly",
  chiller_motor_weekly: "chiller_motor_weekly",
  mech_cooling_oat_bins: "mech_cooling_oat_bins",
  economizer_delta: "economizer_free_cooling_delta",
  economizer_mat_resid: "economizer_mat_residual",
  economizer_temps_overlay: "economizer_temps_oa_damper",
  bas_vs_web_oat: "bas_vs_web_oat",
};

function analyticsPostBody(buildingId, window, refresh) {
  return {
    building_id: buildingId,
    max_points: 4000,
    dt_min_c: ECONOMIZER_DT_MIN_C,
    ...window,
    ...(refresh ? { refresh: true } : {}),
  };
}

function econEmptyMessage() {
  return `No qualified economizer samples. Fan-on proof, |OAT−RAT| ≥ ${ECONOMIZER_DT_MIN_C.toFixed(1)} °C, and a measured MAT are required.`;
}

function wrap(chart) {
  if (!chart?.option) return null;
  return { option: chart.option, lineSeries: chart.lineSeries ?? [] };
}

export async function loadOverviewRcxPreset(buildingId, presetId, mapping, refresh) {
  const window = analyticsWindowFromSampling(mapping?.equipment ?? []);
  const body = analyticsPostBody(buildingId, window, refresh);
  const unitSystem = "metric";
  const stem = PNG_STEMS[presetId];

  if (presetId in PLANT_FOR) {
    const env = normalizeTipOverviewEnvelope(
      "runtime",
      await postAnalytics("/api/analytics/runtime", body),
    );
    const chart = wrap(weeklyMotorOption(env.rows ?? [], PLANT_FOR[presetId], stem));
    return {
      chart,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env.warnings?.[0] ?? "No motor weekly series for this plant.",
      env,
    };
  }
  if (presetId === "mech_cooling_oat_bins") {
    const env = normalizeTipOverviewEnvelope(
      "mechanical-cooling",
      await postAnalytics("/api/analytics/mechanical-cooling", body),
    );
    const chart = wrap(mechCoolingOption(env.rows ?? [], stem));
    return {
      chart,
      lineSeries: [],
      error: chart
        ? undefined
        : env.warnings?.[0] ??
          "No mechanical-cooling outdoor-air bins. Compressor or chiller status with outdoor air is required.",
      env,
    };
  }
  if (
    presetId === "economizer_delta" ||
    presetId === "economizer_mat_resid" ||
    presetId === "economizer_temps_overlay"
  ) {
    const env = normalizeTipOverviewEnvelope(
      "economizer",
      await postAnalytics("/api/analytics/economizer", body),
      { dtMinC: body.dt_min_c },
    );
    const points = env.points ?? [];
    if (presetId === "economizer_delta") {
      const chart = wrap(economizerDeltaOption(points, unitSystem, body.dt_min_c, stem));
      return {
        chart,
        lineSeries: [],
        error: chart ? undefined : env.warnings?.[0] ?? econEmptyMessage(),
        env,
      };
    }
    if (presetId === "economizer_mat_resid") {
      const chart = wrap(economizerMatResidOption(points, unitSystem, stem));
      return {
        chart,
        lineSeries: chart?.lineSeries ?? [],
        error: chart ? undefined : env.warnings?.[0] ?? econEmptyMessage(),
        env,
      };
    }
    const chart = wrap(economizerTempsOverlayOption(points, unitSystem, null, stem));
    return {
      chart,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env.warnings?.[0] ?? econEmptyMessage(),
      env,
    };
  }
  if (presetId === "bas_vs_web_oat") {
    const raw = await postAnalytics("/api/analytics/bas-vs-web-oat", body);
    const env = normalizeTipOverviewEnvelope("bas-vs-web-oat", raw);
    const chart = wrap(basOverlayOption(env.points ?? [], unitSystem, 2, stem));
    const companion = wrap(basHistOption(raw.rows ?? [], unitSystem, "bas_web_oat_deviation_hist"));
    return {
      chart,
      companion,
      lineSeries: chart?.lineSeries ?? [],
      error: chart ? undefined : env.warnings?.[0] ?? "No coincident BAS and web outdoor-air samples for this site and window.",
      env,
    };
  }
  return { chart: null, lineSeries: [], error: "Unknown preset.", env: null };
}
