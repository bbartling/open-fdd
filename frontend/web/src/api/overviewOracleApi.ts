import { apiFetch } from "./client";
import type { PlotlyFigure } from "./plotDataset";

export interface OverviewPlantFig {
  plant_group: string;
  title: string;
  caption: string;
  figure: PlotlyFigure | null;
  empty: boolean;
}

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
    /** Single-device runtime note (vibe19 parity). */
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

export interface OverviewInspectResponse {
  ok: boolean;
  equipment_id: string;
  row_count: number;
  plottable_columns: string[];
  columns_plotted: string[];
  first_timestamp: string | null;
  last_timestamp: string | null;
  span: string;
  figure: PlotlyFigure | null;
  csv_preview?: Array<Record<string, unknown>>;
}

export async function fetchOverviewVibe19(body: {
  building_id: string;
  bare_min_occ_hours_week?: number;
  prefer_web_oat?: boolean;
  chw_leave_max_f?: number;
  use_mech_cooling_status_proof?: boolean;
  oat_err?: number;
  econ_overlay_equipment_id?: string | null;
}): Promise<OverviewVibe19Response> {
  return apiFetch<OverviewVibe19Response>("/api/overview-oracle/vibe19", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchOverviewInspect(body: {
  building_id: string;
  equipment_id: string;
  columns?: string[];
}): Promise<OverviewInspectResponse> {
  return apiFetch<OverviewInspectResponse>("/api/overview-oracle/inspect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Client-side CSV download (Streamlit download_button parity). */
export function downloadRowsCsv(
  filename: string,
  rows: Array<Record<string, unknown>>,
): void {
  if (!rows.length) return;
  const keys = Object.keys(rows[0] ?? {});
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [
    keys.join(","),
    ...rows.map((r) => keys.map((k) => esc(r[k])).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
