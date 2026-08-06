import type { PlotlyFigure } from "./plotDataset";

/** Overview plant weekly figure slot (DataFusion runtime → client Plotly). */
export interface OverviewPlantFig {
  plant_group: string;
  title: string;
  caption: string;
  figure: PlotlyFigure | null;
  empty: boolean;
}

/** Overview dashboard assembled by fetchCentralOverview (no oracle / no pandas). */
export interface OverviewVibe19Response {
  ok: boolean;
  building_id: string;
  source: string;
  elapsed_s: number;
  equipment_count: number;
  equipment_ids: string[];
  has_weather: boolean;
  span: {
    start: string | null;
    end: string | null;
    span_hours?: number | null;
  };
  motor_weekly: {
    caption: string;
    plants: OverviewPlantFig[];
    table: Array<Record<string, unknown>>;
  };
  mech_cooling: {
    caption: string;
    figure: PlotlyFigure | null;
    bins: Array<Record<string, unknown>>;
    coverage: Array<Record<string, unknown>>;
    n_included: number | null;
    n_excluded: number | null;
    callout?: string | null;
  };
  economizer_weather: {
    caption: string;
    table: Array<Record<string, unknown>>;
  };
  economizer_free_cooling: {
    caption: string;
    metrics: Array<Record<string, unknown>>;
    delta_scatter: PlotlyFigure | null;
    mat_residual: PlotlyFigure | null;
    temps_overlay: PlotlyFigure | null;
    overlay_equipment_id: string | null;
    skipped: Array<Record<string, string>>;
    dt_min_f?: number;
  };
  bas_vs_web_oat: {
    caption: string;
    overlay: PlotlyFigure | null;
    histogram: PlotlyFigure | null;
    oat_err: number;
  };
  devices_by_type: Array<{ type: string; count: number }>;
  error?: string;
}
