import {
  postBasVsWebOat,
  postEconomizer,
  postMechanicalCooling,
  postRuntime,
  type AnalyticsEnvelope,
} from "./analyticsApi";
import chartContract from "./charts.contract.json";
import {
  basHist,
  basOverlay,
  econDeltaScatter,
  econMatResidual,
  econTempsOverlay,
  mechFigure,
  weeklyPlantFigures,
} from "./centralOverview";
import { analyticsWindowFromSampling } from "../lib/overviewMetrics";
import { getPackageMapping } from "./mappingApi";
import type { PlotlyFigure } from "./plotDataset";
import { rcxPresetTables, type RcxPresetTable } from "./rcxPresetTables";
import type { UnitSystem } from "./roleUnits";
import { normalizeTipOverviewEnvelope } from "./tipAnalyticsNormalize";
import { isAbortError } from "../session/scopedLoad";

export const OVERVIEW_RCX_PRESET_IDS = [
  "ahu_motor_weekly",
  "economizer_delta",
  "economizer_mat_resid",
  "economizer_temps_overlay",
  "boiler_motor_weekly",
  "chiller_motor_weekly",
  "mech_cooling_oat_bins",
  "bas_vs_web_oat",
] as const;

export function isOverviewRcxPreset(id: string): boolean {
  return (OVERVIEW_RCX_PRESET_IDS as readonly string[]).includes(id);
}

/** Canonical Plotly PNG stem for Overview-mirrored RCx presets. */
export function overviewRcxPngStem(presetId: string): string {
  const map = chartContract.png_stem_vocabulary.react_overview_rcx as Record<
    string,
    string
  >;
  return map[presetId] ?? presetId;
}

/** Companion PNG stem (BAS hist) when Overview preset has a side chart. */
export function overviewRcxCompanionPngStem(presetId: string): string | null {
  const map = chartContract.png_stem_vocabulary
    .react_overview_rcx_companion as Record<string, string>;
  return map[presetId] ?? null;
}

const PLANT_FOR: Record<string, string> = {
  ahu_motor_weekly: "air",
  boiler_motor_weekly: "boiler",
  chiller_motor_weekly: "chiller",
};

export async function loadOverviewRcxPreset(
  buildingId: string,
  presetId: string,
  overlayEq?: string | null,
  refresh?: boolean,
  unitSystem: UnitSystem = "imperial",
  signal?: AbortSignal,
): Promise<{
  figure: PlotlyFigure | null;
  companion: PlotlyFigure | null;
  env: AnalyticsEnvelope;
  tables: RcxPresetTable[];
  error?: string;
}> {
  let mapping = null;
  try {
    mapping = await getPackageMapping(buildingId, undefined, { signal });
  } catch (err) {
    if (isAbortError(err)) throw err;
  }
  const window = analyticsWindowFromSampling(mapping?.equipment ?? []);
  const body = {
    building_id: buildingId,
    max_points: 4000,
    dt_min_f: 10,
    ...window,
    ...(refresh ? { refresh: true } : {}),
  };
  if (presetId in PLANT_FOR) {
    const raw = await postRuntime(body, { signal });
    // Tip SQL emits plant_group=ahu|motor; Overview bars need air|boiler|chiller.
    const env = normalizeTipOverviewEnvelope("runtime", raw);
    const plants = weeklyPlantFigures(env.rows ?? [], unitSystem);
    const plant = plants.find((p) => p.plant_group === PLANT_FOR[presetId]);
    return {
      figure: plant?.figure ?? null,
      companion: null,
      env,
      tables: rcxPresetTables(presetId, env),
      error: plant?.figure
        ? undefined
        : env.warnings?.[0] ?? "No motor weekly series for this plant.",
    };
  }
  if (presetId === "mech_cooling_oat_bins") {
    const env = normalizeTipOverviewEnvelope(
      "mechanical-cooling",
      await postMechanicalCooling(body, { signal }),
    );
    const { figure } = mechFigure(env.rows ?? [], unitSystem);
    return {
      figure,
      companion: null,
      env,
      tables: rcxPresetTables(presetId, env),
      error: figure
        ? undefined
        : env.warnings[0] ??
          "No mechanical-cooling outdoor-air bins. Compressor or chiller status with outdoor air is required.",
    };
  }
  if (
    presetId === "economizer_delta" ||
    presetId === "economizer_mat_resid" ||
    presetId === "economizer_temps_overlay"
  ) {
    const env = normalizeTipOverviewEnvelope("economizer", await postEconomizer(body, { signal }), {
      dtMinF: body.dt_min_f,
    });
    const points = env.points ?? [];
    if (presetId === "economizer_delta") {
      const figure = econDeltaScatter(points, 10, unitSystem);
      return {
        figure,
        companion: null,
        env,
        tables: rcxPresetTables(presetId, env),
        error: figure
          ? undefined
          : env.warnings[0] ??
            "No qualified economizer samples. Fan-on proof, |OAT−RAT| ≥ 10°F, and a measured MAT are required.",
      };
    }
    if (presetId === "economizer_mat_resid") {
      const figure = econMatResidual(points, unitSystem);
      return {
        figure,
        companion: null,
        env,
        tables: rcxPresetTables(presetId, env),
        error: figure
          ? undefined
          : env.warnings[0] ??
            "No qualified economizer samples. Fan-on proof, |OAT−RAT| ≥ 10°F, and a measured MAT are required.",
      };
    }
    const overlay = econTempsOverlay(points, overlayEq ?? null, unitSystem);
    return {
      figure: overlay.figure,
      companion: null,
      env,
      tables: rcxPresetTables(presetId, env),
      error: overlay.figure
        ? undefined
        : env.warnings[0] ??
          "No qualified economizer samples. Fan-on proof, |OAT−RAT| ≥ 10°F, and a measured MAT are required.",
    };
  }
  if (presetId === "bas_vs_web_oat") {
    const env = normalizeTipOverviewEnvelope(
      "bas-vs-web-oat",
      await postBasVsWebOat(body, { signal }),
    );
    const overlay = basOverlay(env.points ?? [], 5, unitSystem);
    const hist = basHist(env.rows ?? [], unitSystem);
    return {
      figure: overlay,
      companion: hist,
      env,
      tables: rcxPresetTables(presetId, env),
      error: overlay
        ? undefined
        : env.warnings[0] ??
          "No coincident BAS and web outdoor-air samples for this site and window.",
    };
  }
  throw new Error(`Unknown Overview RCx preset ${presetId}`);
}
