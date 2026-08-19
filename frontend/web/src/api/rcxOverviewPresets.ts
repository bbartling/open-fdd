import {
  postBasVsWebOat,
  postEconomizer,
  postMechanicalCooling,
  postRuntime,
  type AnalyticsEnvelope,
} from "./analyticsApi";
import {
  basHist,
  basOverlay,
  econDeltaScatter,
  econMatResidual,
  econTempsOverlay,
  mechFigure,
  weeklyPlantFigures,
} from "./centralOverview";
import type { PlotlyFigure } from "./plotDataset";
import { rcxPresetTables, type RcxPresetTable } from "./rcxPresetTables";

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

const PLANT_FOR: Record<string, string> = {
  ahu_motor_weekly: "air",
  boiler_motor_weekly: "boiler",
  chiller_motor_weekly: "chiller",
};

export async function loadOverviewRcxPreset(
  buildingId: string,
  presetId: string,
  overlayEq?: string | null,
): Promise<{
  figure: PlotlyFigure | null;
  companion: PlotlyFigure | null;
  env: AnalyticsEnvelope;
  tables: RcxPresetTable[];
  error?: string;
}> {
  const body = { building_id: buildingId, max_points: 4000, dt_min_f: 10 };
  if (presetId in PLANT_FOR) {
    const env = await postRuntime(body);
    const plants = weeklyPlantFigures(env.rows ?? []);
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
    const env = await postMechanicalCooling(body);
    const { figure } = mechFigure(env.rows ?? []);
    return {
      figure,
      companion: null,
      env,
      tables: rcxPresetTables(presetId, env),
      error: figure ? undefined : env.warnings?.[0],
    };
  }
  if (
    presetId === "economizer_delta" ||
    presetId === "economizer_mat_resid" ||
    presetId === "economizer_temps_overlay"
  ) {
    const env = await postEconomizer(body);
    const points = env.points ?? [];
    if (presetId === "economizer_delta") {
      const figure = econDeltaScatter(points, 10);
      return {
        figure,
        companion: null,
        env,
        tables: rcxPresetTables(presetId, env),
        error: figure ? undefined : env.warnings?.[0],
      };
    }
    if (presetId === "economizer_mat_resid") {
      const figure = econMatResidual(points);
      return {
        figure,
        companion: null,
        env,
        tables: rcxPresetTables(presetId, env),
        error: figure ? undefined : env.warnings?.[0],
      };
    }
    const overlay = econTempsOverlay(points, overlayEq ?? null);
    return {
      figure: overlay.figure,
      companion: null,
      env,
      tables: rcxPresetTables(presetId, env),
      error: overlay.figure ? undefined : env.warnings?.[0],
    };
  }
  if (presetId === "bas_vs_web_oat") {
    const env = await postBasVsWebOat(body);
    const overlay = basOverlay(env.points ?? [], 5);
    const hist = basHist(env.rows ?? []);
    return {
      figure: overlay,
      companion: hist,
      env,
      tables: rcxPresetTables(presetId, env),
      error: overlay ? undefined : env.warnings?.[0],
    };
  }
  throw new Error(`Unknown Overview RCx preset ${presetId}`);
}
