/**
 * Assemble Overview dashboard payload from central Rust `/api/analytics/*`
 * (DataFusion) + client-side Plotly figures — no Python overview-oracle.
 */
import {
  postEconomizer,
  postMechanicalCooling,
  postRuntime,
  postSchedule,
  type AnalyticsEnvelope,
} from "./analyticsApi";
import { rowsToBarFigure, type PlotlyFigure } from "./plotDataset";
import type { OverviewVibe19Response } from "./overviewOracleApi";

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function groupByType(
  rows: Array<Record<string, unknown>>,
): Array<{ type: string; count: number }> {
  const map = new Map<string, number>();
  for (const r of rows) {
    const t = String(r.equipment_type || r.type || "unknown");
    map.set(t, (map.get(t) ?? 0) + 1);
  }
  return [...map.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => a.type.localeCompare(b.type));
}

function motorFigure(rows: Array<Record<string, unknown>>): PlotlyFigure | null {
  const usable = rows.filter((r) => num(r.run_hours) != null);
  if (!usable.length) return null;
  return rowsToBarFigure(usable, {
    xKey: "equipment_id",
    yKeys: ["run_hours"],
    title: "Motor / equipment run hours",
    yAxisTitle: "run hours",
    sortBy: "run_hours",
    sortDesc: true,
    maxBars: 40,
    provenance: "POST /api/analytics/runtime (DataFusion)",
  });
}

function mechFigure(rows: Array<Record<string, unknown>>): PlotlyFigure | null {
  const usable = rows.filter((r) => num(r.history_rows) != null);
  if (!usable.length) return null;
  return rowsToBarFigure(usable, {
    xKey: "equipment_id",
    yKeys: ["history_rows"],
    title: "Mechanical cooling — historian row counts",
    yAxisTitle: "rows",
    sortBy: "history_rows",
    sortDesc: true,
    maxBars: 40,
    provenance: "POST /api/analytics/mechanical-cooling (DataFusion)",
  });
}

function econFigure(rows: Array<Record<string, unknown>>): PlotlyFigure | null {
  const usable = rows.filter(
    (r) => num(r.n_fan_on_samples) != null || num(r.n_identifiable) != null,
  );
  if (!usable.length) return null;
  return rowsToBarFigure(usable, {
    xKey: "equipment_id",
    yKeys: ["n_fan_on_samples", "n_identifiable"],
    title: "Economizer — fan-on / identifiable samples",
    yAxisTitle: "samples",
    sortBy: "n_fan_on_samples",
    sortDesc: true,
    maxBars: 40,
    provenance: "POST /api/analytics/economizer (DataFusion)",
  });
}

function scheduleFigure(rows: Array<Record<string, unknown>>): PlotlyFigure | null {
  const usable = rows.filter(
    (r) => num(r.occupied_hours) != null || num(r.unoccupied_hours) != null,
  );
  if (!usable.length) return null;
  return rowsToBarFigure(usable, {
    xKey: "equipment_id",
    yKeys: ["occupied_hours", "unoccupied_hours"],
    title: "Schedule — occupied / unoccupied hours",
    yAxisTitle: "hours",
    sortBy: "occupied_hours",
    sortDesc: true,
    maxBars: 40,
    barmode: "stack",
    provenance: "POST /api/analytics/schedule (DataFusion)",
  });
}

function warnCaption(env: AnalyticsEnvelope, fallback: string): string {
  const w = env.warnings?.filter(Boolean) ?? [];
  if (w.length) return `${fallback} · ${w[0]}`;
  return `${fallback} · engine=${env.engine || "central"}`;
}

export async function fetchCentralOverview(opts: {
  building_id: string;
  equipment?: Array<{ equipment_id: string; equipment_type?: string }>;
}): Promise<OverviewVibe19Response> {
  const t0 = performance.now();
  const building_id = opts.building_id;
  const body = { building_id };

  const [runtime, mech, econ, schedule] = await Promise.all([
    postRuntime(body),
    postMechanicalCooling(body),
    postEconomizer(body),
    postSchedule(body),
  ]);

  const runtimeRows = runtime.rows?.length ? runtime.rows : runtime.equipment;
  const mechRows = mech.rows?.length ? mech.rows : mech.equipment;
  const econRows = econ.rows?.length ? econ.rows : econ.equipment;
  const scheduleRows = schedule.rows?.length ? schedule.rows : schedule.equipment;

  const equipmentIds = [
    ...new Set(
      [
        ...runtimeRows.map((r) => String(r.equipment_id ?? "")),
        ...(opts.equipment ?? []).map((e) => String(e.equipment_id)),
      ].filter(Boolean),
    ),
  ].sort();

  const devices =
    opts.equipment?.length
      ? groupByType(
          opts.equipment.map((e) => ({
            equipment_type: e.equipment_type,
            equipment_id: e.equipment_id,
          })),
        )
      : groupByType(runtimeRows);

  const motorFig = motorFigure(runtimeRows);
  const mechFig = mechFigure(mechRows);
  const econFig = econFigure(econRows);
  const schedFig = scheduleFigure(scheduleRows);

  const elapsed_s = Math.round(((performance.now() - t0) / 1000) * 10) / 10;

  return {
    ok: true,
    building_id,
    source: "central-datafusion",
    elapsed_s,
    equipment_count: equipmentIds.length,
    equipment_ids: equipmentIds,
    has_weather: false,
    span: {
      start: null,
      end: null,
      span_hours: null,
    },
    motor_weekly: {
      caption: warnCaption(
        runtime,
        "Run hours by equipment (DataFusion historian Δt — not weekly plant bins yet)",
      ),
      plants: motorFig
        ? [
            {
              plant_group: "all",
              title: "Equipment run hours",
              caption: "Central /api/analytics/runtime",
              figure: motorFig,
              empty: false,
            },
          ]
        : [],
      table: runtimeRows.slice(0, 200),
    },
    mech_cooling: {
      caption: warnCaption(
        mech,
        "Mechanical cooling evidence from DataFusion (OAT bin histogram not ported yet)",
      ),
      figure: mechFig,
      bins: [],
      coverage: mechRows.slice(0, 200),
      n_included: mechRows.length,
      n_excluded: 0,
    },
    economizer_weather: {
      caption:
        "Economizer weather-opportunity table is not in central yet — free-cooling sample counts below.",
      table: [],
    },
    economizer_free_cooling: {
      caption: warnCaption(
        econ,
        "Economizer diagnostics from DataFusion (MAT residual / scatter need richer series)",
      ),
      metrics: econRows.slice(0, 200),
      delta_scatter: econFig,
      mat_residual: null,
      temps_overlay: schedFig,
      overlay_equipment_id: null,
      skipped: [],
    },
    bas_vs_web_oat: {
      caption:
        "BAS vs web OAT overlay is not in central DataFusion yet — use Update analytics after that family lands.",
      overlay: null,
      histogram: null,
      oat_err: 5,
    },
    devices_by_type: devices,
  };
}
