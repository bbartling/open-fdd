/**
 * Assemble Overview dashboard payload from central Rust `/api/analytics/*`
 * (DataFusion) + client-side Plotly figures — no Python overview-oracle.
 */
import {
  postBasVsWebOat,
  postEconomizer,
  postMechanicalCooling,
  postRuntime,
  postSchedule,
  type AnalyticsEnvelope,
} from "./analyticsApi";
import { rowsToBarFigure, type PlotlyFigure } from "./plotDataset";
import type {
  OverviewPlantFig,
  OverviewVibe19Response,
} from "./overviewOracleApi";

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

function weeklyPlantFigures(
  rows: Array<Record<string, unknown>>,
): OverviewPlantFig[] {
  const weekly = rows.filter((r) => r.kind === "weekly_plant");
  if (!weekly.length) return [];
  const byPlant = new Map<string, Array<Record<string, unknown>>>();
  for (const r of weekly) {
    const g = String(r.plant_group || "other");
    const list = byPlant.get(g) ?? [];
    list.push(r);
    byPlant.set(g, list);
  }
  const titles: Record<string, string> = {
    air: "Air handlers / RTUs",
    boiler: "Boiler plant",
    chiller: "Chiller / tower plant",
  };
  return [...byPlant.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([plant_group, plantRows]) => {
      const sorted = [...plantRows].sort((a, b) =>
        String(a.week_label).localeCompare(String(b.week_label)),
      );
      const figure = rowsToBarFigure(sorted, {
        xKey: "week_label",
        yKeys: ["run_hours"],
        title: `${titles[plant_group] ?? plant_group} — weekly run hours`,
        yAxisTitle: "run hours",
        maxBars: 52,
        provenance: "POST /api/analytics/runtime (runtime-weekly-v1)",
      });
      return {
        plant_group,
        title: titles[plant_group] ?? plant_group,
        caption: "Central weekly plant bins (DataFusion)",
        figure,
        empty: !figure,
      };
    });
}

function mechFigure(rows: Array<Record<string, unknown>>): {
  figure: PlotlyFigure | null;
  bins: Array<Record<string, unknown>>;
} {
  const oatBins = rows.filter((r) => r.kind === "oat_bin");
  if (oatBins.length) {
    const sorted = [...oatBins].sort(
      (a, b) => (num(a.bin_lo_f) ?? 0) - (num(b.bin_lo_f) ?? 0),
    );
    return {
      figure: rowsToBarFigure(sorted, {
        xKey: "bin_label",
        yKeys: ["hours"],
        title: "Mechanical cooling — hours by OAT bin",
        yAxisTitle: "hours",
        maxBars: 40,
        provenance: "POST /api/analytics/mechanical-cooling (OAT bins)",
      }),
      bins: sorted,
    };
  }
  const usable = rows.filter((r) => num(r.history_rows) != null);
  if (!usable.length) return { figure: null, bins: [] };
  return {
    figure: rowsToBarFigure(usable, {
      xKey: "equipment_id",
      yKeys: ["history_rows"],
      title: "Mechanical cooling — historian row counts",
      yAxisTitle: "rows",
      sortBy: "history_rows",
      sortDesc: true,
      maxBars: 40,
      provenance: "POST /api/analytics/mechanical-cooling (DataFusion)",
    }),
    bins: [],
  };
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

function basOverlay(points: Array<Record<string, unknown>>): PlotlyFigure | null {
  if (!points.length) return null;
  const x = points.map((p) => String(p.timestamp_utc ?? ""));
  const bas = points.map((p) => num(p.bas_oat_f));
  const web = points.map((p) => num(p.web_oat_f));
  return {
    data: [
      {
        type: "scatter",
        mode: "lines",
        name: "BAS oa_t",
        x,
        y: bas,
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Web OAT",
        x,
        y: web,
      },
    ],
    layout: {
      title: "BAS vs web OAT",
      xaxis: { title: "time" },
      yaxis: { title: "°F" },
      legend: { orientation: "h" },
    },
    meta: { provenance: "POST /api/analytics/bas-vs-web-oat" },
  };
}

function basHist(rows: Array<Record<string, unknown>>): PlotlyFigure | null {
  const usable = rows.filter((r) => r.kind === "delta_hist" || num(r.count) != null);
  if (!usable.length) return null;
  const sorted = [...usable].sort(
    (a, b) => (num(a.bin_lo_f) ?? 0) - (num(b.bin_lo_f) ?? 0),
  );
  return rowsToBarFigure(
    sorted.map((r) => ({
      ...r,
      bin_label: `${num(r.bin_lo_f) ?? 0}`,
    })),
    {
      xKey: "bin_label",
      yKeys: ["count"],
      title: "BAS − web OAT (°F) histogram",
      yAxisTitle: "count",
      maxBars: 60,
      provenance: "POST /api/analytics/bas-vs-web-oat",
    },
  );
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

  const [runtime, mech, econ, schedule, bas] = await Promise.all([
    postRuntime(body),
    postMechanicalCooling(body),
    postEconomizer(body),
    postSchedule(body),
    postBasVsWebOat(body),
  ]);

  const runtimeRows = runtime.rows?.length ? runtime.rows : runtime.equipment;
  const equipmentTotals =
    runtime.equipment?.length ? runtime.equipment : runtimeRows;
  const mechRows = mech.rows?.length ? mech.rows : mech.equipment;
  const econRows = econ.rows?.length ? econ.rows : econ.equipment;
  const scheduleRows = schedule.rows?.length ? schedule.rows : schedule.equipment;

  const equipmentIds = [
    ...new Set(
      [
        ...equipmentTotals.map((r) => String(r.equipment_id ?? "")),
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
      : groupByType(equipmentTotals);

  const weeklyPlants = weeklyPlantFigures(runtimeRows);
  const motorFig = motorFigure(
    equipmentTotals.filter((r) => r.kind !== "weekly_plant"),
  );
  const plants: OverviewPlantFig[] =
    weeklyPlants.length > 0
      ? weeklyPlants
      : motorFig
        ? [
            {
              plant_group: "all",
              title: "Equipment run hours",
              caption: "Central /api/analytics/runtime",
              figure: motorFig,
              empty: false,
            },
          ]
        : [];

  const { figure: mechFig, bins: mechBins } = mechFigure(mechRows);
  const econFig = econFigure(econRows);
  const schedFig = scheduleFigure(scheduleRows);
  const basPoints = bas.points ?? [];
  const basOverlayFig = basOverlay(basPoints);
  const basHistFig = basHist(bas.rows ?? []);

  const elapsed_s = Math.round(((performance.now() - t0) / 1000) * 10) / 10;

  return {
    ok: true,
    building_id,
    source: "central-datafusion",
    elapsed_s,
    equipment_count: equipmentIds.length,
    equipment_ids: equipmentIds,
    has_weather: Boolean(basOverlayFig),
    span: {
      start: null,
      end: null,
      span_hours: null,
    },
    motor_weekly: {
      caption: warnCaption(
        runtime,
        weeklyPlants.length
          ? "Weekly plant run hours (DataFusion historian Δt)"
          : "Run hours by equipment (DataFusion historian Δt)",
      ),
      plants,
      table: equipmentTotals.slice(0, 200),
    },
    mech_cooling: {
      caption: warnCaption(
        mech,
        mechBins.length
          ? "Mechanical cooling OAT bin hours from DataFusion"
          : "Mechanical cooling evidence from DataFusion",
      ),
      figure: mechFig,
      bins: mechBins,
      coverage: mechRows.filter((r) => r.kind !== "oat_bin").slice(0, 200),
      n_included: mechBins.length || mechRows.length,
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
      caption: warnCaption(
        bas,
        basOverlayFig
          ? "BAS vs web OAT from DataFusion historian"
          : "BAS vs web OAT unavailable (need both oa_t and web OAT columns)",
      ),
      overlay: basOverlayFig,
      histogram: basHistFig,
      oat_err: 5,
    },
    devices_by_type: devices,
  };
}
