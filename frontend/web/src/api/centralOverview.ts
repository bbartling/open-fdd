/**
 * Assemble Overview dashboard payload from central Rust `/api/analytics/*`
 * (DataFusion) + client-side Plotly figures — vibe19 Overview chart parity,
 * no Python/pandas.
 */
import {
  postBasVsWebOat,
  postEconomizer,
  postMechanicalCooling,
  postRuntime,
  type AnalyticsEnvelope,
} from "./analyticsApi";
import {
  fingerprintJson,
  rowsToBarFigure,
  type PlotlyFigure,
  type PlotlyTrace,
} from "./plotDataset";
import type {
  OverviewPlantFig,
  OverviewVibe19Response,
} from "./overviewTypes";
import {
  AIR_BARE_MIN_OCC_HOURS_WEEK,
  overviewChartLayout,
  rainbowColor,
} from "./plotlyTheme";

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

/** Weekly plant bars + optional avg OAT on y2 (vibe19 motor_weekly_runtime_chart). */
function weeklyPlantFigures(
  rows: Array<Record<string, unknown>>,
): OverviewPlantFig[] {
  const weekly = rows.filter(
    (r) => r.kind === "weekly_equipment" || r.kind === "weekly_plant",
  );
  if (!weekly.length) return [];
  const byPlant = new Map<string, Array<Record<string, unknown>>>();
  for (const r of weekly) {
    const g = String(r.plant_group || "other");
    const list = byPlant.get(g) ?? [];
    list.push(r);
    byPlant.set(g, list);
  }
  const titles: Record<string, string> = {
    air: "Air side — supply fans",
    boiler: "Boiler plant — HW pumps",
    chiller: "Chiller plant — chillers, CHW/CW pumps, towers",
  };
  return [...byPlant.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([plant_group, plantRows]) => {
      const sorted = [...plantRows].sort((a, b) => {
        const w = String(a.week_label).localeCompare(String(b.week_label));
        if (w !== 0) return w;
        const la = String(a.label ?? a.equipment_id ?? "");
        const lb = String(b.label ?? b.equipment_id ?? "");
        return la.localeCompare(lb);
      });
      const weeks = [
        ...new Set(sorted.map((r) => String(r.week_label ?? ""))),
      ].sort((a, b) => a.localeCompare(b));

      const perEq = new Map<string, Array<Record<string, unknown>>>();
      for (const r of sorted) {
        const lab = String(r.label ?? r.equipment_id ?? "run hours");
        const list = perEq.get(lab) ?? [];
        list.push(r);
        perEq.set(lab, list);
      }

      const data: PlotlyTrace[] = [];
      let colorIdx = 0;
      // Prefer multi-series equipment labels; fall back to single plant total.
      const labels = [...perEq.keys()].sort((a, b) => a.localeCompare(b));
      for (const lab of labels) {
        const eqRows = perEq.get(lab) ?? [];
        const byWeek = new Map(
          eqRows.map((r) => [String(r.week_label ?? ""), num(r.run_hours)]),
        );
        data.push({
          type: "bar",
          name: lab,
          x: weeks,
          y: weeks.map((w) => byWeek.get(w) ?? null),
          marker: { color: rainbowColor(colorIdx) },
        });
        colorIdx += 1;
      }

      // Avg OAT while on: mean across equipment that reported OAT that week.
      const oatByWeek = new Map<string, { sum: number; n: number }>();
      for (const r of sorted) {
        const o = num(r.avg_oat_f);
        if (o == null) continue;
        const w = String(r.week_label ?? "");
        const e = oatByWeek.get(w) ?? { sum: 0, n: 0 };
        e.sum += o;
        e.n += 1;
        oatByWeek.set(w, e);
      }
      const oat = weeks.map((w) => {
        const e = oatByWeek.get(w);
        return e && e.n > 0 ? e.sum / e.n : null;
      });
      const hasOat = oat.some((v) => v != null);
      if (hasOat) {
        data.push({
          type: "scatter",
          mode: "lines+markers",
          name: "Avg OAT °F (while on)",
          x: weeks,
          y: oat,
          yaxis: "y2",
          line: { width: 2, color: "#333333", dash: "dot" },
          marker: { size: 7, color: "#333333" },
        });
      }

      const isAir = plant_group === "air";
      const shapes = isAir
        ? [
            {
              type: "line",
              xref: "paper",
              x0: 0,
              x1: 1,
              yref: "y",
              y0: AIR_BARE_MIN_OCC_HOURS_WEEK,
              y1: AIR_BARE_MIN_OCC_HOURS_WEEK,
              line: { color: "#c45c26", width: 1.5, dash: "dash" },
            },
          ]
        : undefined;
      const annotations = isAir
        ? [
            {
              xref: "paper",
              x: 1,
              y: AIR_BARE_MIN_OCC_HOURS_WEEK,
              yref: "y",
              text: `Bare-min occupied hours/week (${AIR_BARE_MIN_OCC_HOURS_WEEK}h)`,
              showarrow: false,
              xanchor: "right",
              yanchor: "bottom",
              font: { size: 10, color: "#c45c26" },
            },
          ]
        : undefined;

      const figure: PlotlyFigure = {
        data,
        layout: overviewChartLayout({
          xTitle: "Week starting (Mon)",
          yTitle: "Run hours",
          rightAxis: hasOat,
          height: Math.max(420, 60 + 18 * Math.min(labels.length, 12)),
          uirevision: `weekly:${plant_group}:${fingerprintJson(sorted)}`,
          extra: {
            barmode: "group",
            ...(shapes ? { shapes } : {}),
            ...(annotations ? { annotations } : {}),
          },
        }),
        meta: {
          point_count: sorted.length,
          provenance: "POST /api/analytics/runtime (runtime-weekly-v2)",
        },
      };
      return {
        plant_group,
        title: titles[plant_group] ?? plant_group,
        caption: "Central weekly plant bins (DataFusion)",
        figure,
        empty: !sorted.length,
      };
    });
}

function mechFigure(rows: Array<Record<string, unknown>>): {
  figure: PlotlyFigure | null;
  bins: Array<Record<string, unknown>>;
  callout: string | null;
} {
  const oatBins = rows.filter((r) => r.kind === "oat_bin");
  if (!oatBins.length) {
    // Never promote historian row-counts as the primary mech product chart.
    return { figure: null, bins: [], callout: null };
  }

  const individuals = oatBins.filter(
    (r) =>
      !r.series_kind ||
      r.series_kind === "individual_device" ||
      (r.series_kind !== "aggregate_device_hours" &&
        r.series_kind !== "aggregate_active_hours"),
  );
  const totals = oatBins.filter(
    (r) => r.series_kind === "aggregate_device_hours",
  );
  const anyActive = oatBins.filter(
    (r) => r.series_kind === "aggregate_active_hours",
  );

  const binOrder = [
    ...new Set(
      oatBins
        .map((r) => ({
          label: String(r.bin_label ?? ""),
          lo: num(r.bin_lo_f) ?? 0,
        }))
        .sort((a, b) => a.lo - b.lo)
        .map((b) => b.label),
    ),
  ];

  const byEq = new Map<string, Array<Record<string, unknown>>>();
  for (const r of individuals) {
    const eq = String(r.equipment_id ?? "device");
    if (eq === "ALL" || eq === "ANY") continue;
    const list = byEq.get(eq) ?? [];
    list.push(r);
    byEq.set(eq, list);
  }
  const devices = [...byEq.keys()].sort((a, b) => a.localeCompare(b));

  const data: PlotlyTrace[] = [];
  devices.forEach((eq, i) => {
    const eqRows = byEq.get(eq) ?? [];
    const byBin = new Map(
      eqRows.map((r) => [String(r.bin_label ?? ""), num(r.hours)]),
    );
    data.push({
      type: "bar",
      name: eq,
      x: binOrder,
      y: binOrder.map((b) => byBin.get(b) ?? null),
      marker: { color: rainbowColor(i) },
    });
  });

  if (totals.length) {
    const byBin = new Map(
      totals.map((r) => [String(r.bin_label ?? ""), num(r.hours)]),
    );
    data.push({
      type: "scatter",
      mode: "lines+markers",
      name: "Total compressor device-hours",
      x: binOrder,
      y: binOrder.map((b) => byBin.get(b) ?? null),
      line: { width: 2.2, color: "#111827" },
      marker: { size: 7, color: "#111827" },
    });
  }
  if (anyActive.length) {
    const byBin = new Map(
      anyActive.map((r) => [String(r.bin_label ?? ""), num(r.hours)]),
    );
    data.push({
      type: "scatter",
      mode: "lines+markers",
      name: "Any compressor active",
      x: binOrder,
      y: binOrder.map((b) => byBin.get(b) ?? null),
      line: { width: 2.2, color: "#6b7280", dash: "dash" },
      marker: { size: 7, color: "#6b7280", symbol: "circle-open" },
    });
  }

  // Fallback: legacy single-series oat_bin without series_kind / equipment_id.
  if (!data.length) {
    const sorted = [...oatBins].sort(
      (a, b) => (num(a.bin_lo_f) ?? 0) - (num(b.bin_lo_f) ?? 0),
    );
    return {
      figure: rowsToBarFigure(sorted, {
        xKey: "bin_label",
        yKeys: ["hours"],
        title: "Mechanical cooling run hours by outdoor-air temperature (5°F bins)",
        yAxisTitle: "Run hours",
        maxBars: 40,
        provenance: "POST /api/analytics/mechanical-cooling (OAT bins)",
      }),
      bins: sorted,
      callout: null,
    };
  }

  let callout: string | null = null;
  if (devices.length === 1) {
    callout = `Only ${devices[0]} had observed compressor runtime during this period. Total compressor device-hours therefore equal ${devices[0]} runtime.`;
  }

  const figure: PlotlyFigure = {
    data,
    layout: overviewChartLayout({
      xTitle: "OAT bin °F",
      yTitle: "Run hours",
      height: 420,
      tickangle: 0,
      uirevision: `mech-oat:${fingerprintJson(oatBins)}`,
      extra: {
        barmode: "stack",
        xaxis: {
          title: "OAT bin °F",
          categoryorder: "array",
          categoryarray: binOrder,
          autorange: true,
        },
      },
    }),
    meta: {
      point_count: oatBins.length,
      provenance: "POST /api/analytics/mechanical-cooling (OAT bins v2)",
    },
  };
  return { figure, bins: oatBins, callout };
}

/** vibe19 economizer_delta_scatter: (MAT−RAT) vs (OAT−RAT) + OA-fraction refs. */
function econDeltaScatter(
  points: Array<Record<string, unknown>>,
  dtMinF: number,
): PlotlyFigure | null {
  const usable = points.filter(
    (p) =>
      (p.identifiable === true || p.identifiable === "true") &&
      num(p.delta_or_f) != null &&
      num(p.delta_mr_f) != null,
  );
  if (usable.length < 5) return null;

  const xs = usable.map((p) => num(p.delta_or_f) as number);
  const xLo = Math.min(...xs);
  const xHi = Math.max(...xs);
  const lo = Number.isFinite(xLo) ? xLo : -20;
  const hi = Number.isFinite(xHi) ? xHi : 20;
  const span = hi === lo ? 20 : hi - lo;
  const refX: number[] = [];
  for (let i = 0; i <= 40; i++) {
    refX.push(lo + (span * i) / 40);
  }
  const data: PlotlyTrace[] = [];
  for (const [frac, label] of [
    [0, "0% OA"],
    [0.25, "25%"],
    [0.5, "50%"],
    [0.75, "75%"],
    [1, "100% OA"],
  ] as const) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: label,
      x: refX,
      y: refX.map((x) => frac * x),
      line: { width: 1, dash: "dot", color: "#94a3b8" },
      hoverinfo: "skip",
      showlegend: true,
    });
  }

  const byEq = new Map<string, Array<Record<string, unknown>>>();
  for (const p of usable) {
    const eq = String(p.equipment_id || "AHU");
    const list = byEq.get(eq) ?? [];
    list.push(p);
    byEq.set(eq, list);
  }
  let eqIdx = 0;
  for (const [eq, rows] of byEq) {
    const hasDamper = rows.some((r) => num(r.damper_fb_pct) != null);
    data.push({
      type: "scatter",
      mode: "markers",
      name: eq,
      x: rows.map((r) => num(r.delta_or_f) as number),
      y: rows.map((r) => num(r.delta_mr_f)),
      marker: hasDamper
        ? {
            size: 7,
            opacity: 0.75,
            color: rows.map((r) => num(r.damper_fb_pct)),
            colorscale: "Viridis",
            showscale: true,
            colorbar: { title: "OA damper %", thickness: 12 },
          }
        : {
            size: 6,
            opacity: 0.7,
            color: rainbowColor(eqIdx),
          },
    });
    eqIdx += 1;
  }

  return {
    data,
    layout: {
      title: `Economizer free-cooling delta scatter (fan on, |OAT−RAT|≥${dtMinF.toFixed(0)}°F)`,
      xaxis: { title: "OAT − RAT (°F)", autorange: true },
      yaxis: { title: "MAT − RAT (°F)", autorange: true },
      legend: { orientation: "h" },
      height: 420,
      uirevision: `econ-delta:${fingerprintJson(usable.slice(0, 200))}`,
    },
    meta: {
      point_count: usable.length,
      provenance: "POST /api/analytics/economizer (DataFusion points)",
    },
  };
}

/** vibe19 economizer_mat_residual_chart. */
function econMatResidual(
  points: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  const usable = points.filter(
    (p) =>
      (p.identifiable === true || p.identifiable === "true") &&
      num(p.mat_resid_f) != null,
  );
  if (usable.length < 5) return null;
  const byEq = new Map<string, Array<Record<string, unknown>>>();
  for (const p of usable) {
    const eq = String(p.equipment_id || "AHU");
    const list = byEq.get(eq) ?? [];
    list.push(p);
    byEq.set(eq, list);
  }
  const data: PlotlyTrace[] = [];
  let colorIdx = 0;
  for (const [eq, rows] of byEq) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: eq,
      x: rows.map((r) => String(r.timestamp_utc ?? "")),
      y: rows.map((r) => num(r.mat_resid_f)),
      line: { width: 1.4, color: rainbowColor(colorIdx) },
    });
    colorIdx += 1;
  }
  return {
    data,
    layout: {
      title: "MAT residual (meas − mixing model from OA damper) — fan on, identifiable",
      xaxis: { title: "time", autorange: true },
      yaxis: { title: "MAT residual °F", autorange: true },
      legend: { orientation: "h" },
      height: 320,
      uirevision: `econ-mat:${fingerprintJson(usable.slice(0, 200))}`,
    },
    meta: {
      point_count: usable.length,
      provenance: "POST /api/analytics/economizer (DataFusion points)",
    },
  };
}

/** vibe19 economizer_temps_overlay for one AHU. */
function econTempsOverlay(
  points: Array<Record<string, unknown>>,
  equipmentId: string | null,
): { figure: PlotlyFigure | null; equipmentId: string | null } {
  if (!points.length) return { figure: null, equipmentId: null };
  const eq =
    equipmentId &&
    points.some((p) => String(p.equipment_id) === equipmentId)
      ? equipmentId
      : String(points[0].equipment_id ?? "");
  if (!eq) return { figure: null, equipmentId: null };
  const rows = points.filter((p) => String(p.equipment_id) === eq);
  if (rows.length < 3) return { figure: null, equipmentId: eq };
  const x = rows.map((r) => String(r.timestamp_utc ?? ""));
  // vibe19 fixed palette indices: OAT[0], RAT[5], MAT[3], SAT[6], damper[1] dash.
  const data: PlotlyTrace[] = [
    {
      type: "scatter",
      mode: "lines",
      name: "OAT",
      x,
      y: rows.map((r) => num(r.oat_f)),
      line: { width: 1.5, color: rainbowColor(0) },
    },
    {
      type: "scatter",
      mode: "lines",
      name: "RAT",
      x,
      y: rows.map((r) => num(r.rat_f)),
      line: { width: 1.5, color: rainbowColor(5) },
    },
    {
      type: "scatter",
      mode: "lines",
      name: "MAT",
      x,
      y: rows.map((r) => num(r.mat_f)),
      line: { width: 1.5, color: rainbowColor(3) },
    },
  ];
  if (rows.some((r) => num(r.sat_f) != null)) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: "SAT",
      x,
      y: rows.map((r) => num(r.sat_f)),
      line: { width: 1.5, color: rainbowColor(6) },
    });
  }
  if (rows.some((r) => num(r.damper_fb_pct) != null)) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: "OA damper %",
      x,
      y: rows.map((r) => num(r.damper_fb_pct)),
      yaxis: "y2",
      line: { width: 1.5, color: rainbowColor(1), dash: "dot" },
    });
  }
  return {
    equipmentId: eq,
    figure: {
      data,
      layout: {
        title: `Free-cooling temps + OA damper (fan on) — ${eq}`,
        xaxis: { title: "time", autorange: true },
        yaxis: { title: "°F", autorange: true },
        yaxis2: {
          title: "damper %",
          overlaying: "y",
          side: "right",
          range: [0, 100],
          autorange: false,
        },
        legend: { orientation: "h" },
        height: 360,
        uirevision: `econ-temps:${eq}:${fingerprintJson(rows.slice(0, 100))}`,
      },
      meta: {
        equipment_id: eq,
        point_count: rows.length,
        provenance: "POST /api/analytics/economizer (DataFusion points)",
      },
    },
  };
}

/** vibe19 bas_vs_web_oat_overlay with ±oat_err band. */
function basOverlay(
  points: Array<Record<string, unknown>>,
  oatErr: number,
): PlotlyFigure | null {
  if (!points.length) return null;
  const x = points.map((p) => String(p.timestamp_utc ?? ""));
  const bas = points.map((p) => num(p.bas_oat_f));
  const web = points.map((p) => num(p.web_oat_f));
  const hi = web.map((v) => (v == null ? null : v + oatErr));
  const lo = web.map((v) => (v == null ? null : v - oatErr));
  const data: PlotlyTrace[] = [
    {
      type: "scatter",
      mode: "lines",
      name: `web +${oatErr}°F`,
      x,
      y: hi,
      line: { width: 0 },
      showlegend: false,
    },
    {
      type: "scatter",
      mode: "lines",
      name: `±${oatErr}°F band`,
      x,
      y: lo,
      fill: "tonexty",
      fillcolor: "rgba(234,179,8,0.18)",
      line: { width: 0 },
    },
    {
      type: "scatter",
      mode: "lines",
      name: "Web OAT",
      x,
      y: web,
      line: { width: 1.4, color: rainbowColor(3) },
    },
    {
      type: "scatter",
      mode: "lines",
      name: "BAS oa_t",
      x,
      y: bas,
      line: { width: 1.4, color: rainbowColor(0) },
    },
  ];
  return {
    data,
    layout: {
      title: `BAS vs web outdoor-air temperature (±${oatErr}°F band)`,
      xaxis: { title: "time", autorange: true },
      yaxis: { title: "°F", autorange: true },
      legend: { orientation: "h" },
      uirevision: `bas-overlay:${fingerprintJson(points.slice(0, 100))}`,
    },
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/bas-vs-web-oat",
    },
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
      title: "BAS vs web outdoor-air temperature deviation (°F)",
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
  econ_overlay_equipment_id?: string | null;
  oat_err?: number;
  dt_min_f?: number;
}): Promise<OverviewVibe19Response> {
  const t0 = performance.now();
  const building_id = opts.building_id;
  const oatErr = opts.oat_err ?? 5;
  const dtMin = opts.dt_min_f ?? 10;
  const body = { building_id, max_points: 4000, dt_min_f: dtMin };

  const [runtime, mech, econ, bas] = await Promise.all([
    postRuntime(body),
    postMechanicalCooling(body),
    postEconomizer(body),
    postBasVsWebOat(body),
  ]);

  const runtimeRows = runtime.rows?.length ? runtime.rows : runtime.equipment;
  const equipmentTotals =
    runtime.equipment?.length ? runtime.equipment : runtimeRows;
  const mechRows = mech.rows?.length ? mech.rows : mech.equipment;
  const econRows = econ.rows?.length ? econ.rows : econ.equipment;
  const econPoints = econ.points ?? [];

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
    equipmentTotals.filter(
      (r) => r.kind !== "weekly_plant" && r.kind !== "weekly_equipment",
    ),
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

  const {
    figure: mechFig,
    bins: mechBins,
    callout: mechCallout,
  } = mechFigure(mechRows);
  const deltaScatter = econDeltaScatter(econPoints, dtMin);
  const matResidual = econMatResidual(econPoints);
  const { figure: tempsOverlay, equipmentId: overlayEq } = econTempsOverlay(
    econPoints,
    opts.econ_overlay_equipment_id ?? null,
  );
  const basPoints = bas.points ?? [];
  const basOverlayFig = basOverlay(basPoints, oatErr);
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
          : mechFig
            ? "Mechanical cooling evidence from DataFusion"
            : "No compressor×OAT intervals in historian (need chiller proof + site OAT)",
      ),
      figure: mechFig,
      bins: mechBins,
      coverage: mechRows
        .filter((r) => r.kind !== "oat_bin" && num(r.history_rows) != null)
        .slice(0, 200),
      n_included: mechBins.filter((r) => r.series_kind === "individual_device")
        .length
        ? new Set(
            mechBins
              .filter((r) => r.series_kind === "individual_device")
              .map((r) => String(r.equipment_id)),
          ).size
        : mechBins.length || null,
      n_excluded: 0,
      callout: mechCallout,
    },
    economizer_weather: {
      caption:
        "Economizer weather-opportunity (dewpoint hours) needs web dewpoint on historian — not yet wired in central DataFusion.",
      table: [],
    },
    economizer_free_cooling: {
      caption: warnCaption(
        econ,
        deltaScatter
          ? "Economizer free-cooling plots from DataFusion historian points"
          : econPoints.length
            ? "Economizer points present but fewer than 5 identifiable |OAT−RAT| samples for scatter"
            : "Economizer plot points unavailable (need fan-on + OAT/RAT/MAT)",
      ),
      metrics: econRows.slice(0, 200),
      // Never substitute count bars or schedule bars for missing econ figures.
      delta_scatter: deltaScatter,
      mat_residual: matResidual,
      temps_overlay: tempsOverlay,
      overlay_equipment_id: overlayEq,
      skipped: [],
      dt_min_f: dtMin,
    },
    bas_vs_web_oat: {
      caption: warnCaption(
        bas,
        basOverlayFig
          ? "BAS vs web OAT from DataFusion historian (site-broadcast join)"
          : "BAS vs web OAT unavailable (need both oa_t and web OAT columns)",
      ),
      overlay: basOverlayFig,
      histogram: basHistFig,
      oat_err: oatErr,
    },
    devices_by_type: devices,
  };
}
