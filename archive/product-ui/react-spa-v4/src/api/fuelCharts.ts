/**
 * Fuel dashboard Plotly builders — vibe20-colored via RAINBOW_PALETTE.
 */
import {
  fingerprintJson,
  type PlotlyFigure,
  type PlotlyTrace,
} from "./plotDataset";
import { overviewChartLayout, rainbowColor } from "./plotlyTheme";

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function peerBand(row: Record<string, unknown>): {
  p20: number | null;
  p50: number | null;
  p80: number | null;
} {
  const peer =
    row.peer && typeof row.peer === "object" && !Array.isArray(row.peer)
      ? (row.peer as Record<string, unknown>)
      : {};
  return {
    p20: num(row.peer_p20 ?? peer.p20),
    p50: num(row.peer_p50 ?? peer.p50),
    p80: num(row.peer_p80 ?? peer.p80),
  };
}

/** Site EUI markers with same-type p20–p80 band (vibe20 bullet). */
export function summaryPeerBullet(
  rows: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const labels = rows.map(buildingLabel);
  const eui = rows.map(siteEui);
  if (!eui.some((v) => v != null)) return null;

  // Prefer per-row bands; fall back to first row's band for campus chart.
  const bands = rows.map(peerBand);
  const p20 = bands.map((b) => b.p20);
  const p50 = bands.map((b) => b.p50);
  const p80 = bands.map((b) => b.p80);
  const hasBand = p20.some((v) => v != null) && p80.some((v) => v != null);

  const data: PlotlyTrace[] = [];
  if (hasBand) {
    // Midpoint + half-width box via error bars (upright band).
    data.push({
      type: "bar",
      name: "p20–p80 band",
      x: labels,
      y: labels.map((_, i) => {
        const lo = p20[i];
        const hi = p80[i];
        if (lo == null || hi == null) return null;
        return (lo + hi) / 2;
      }),
      marker: { color: "rgba(46,125,50,0.28)" },
      error_y: {
        type: "data",
        symmetric: false,
        array: labels.map((_, i) => {
          const lo = p20[i];
          const hi = p80[i];
          if (lo == null || hi == null) return 0;
          return (hi - lo) / 2;
        }),
        arrayminus: labels.map((_, i) => {
          const lo = p20[i];
          const hi = p80[i];
          if (lo == null || hi == null) return 0;
          return (hi - lo) / 2;
        }),
        color: "rgba(46,125,50,0.55)",
        thickness: 0,
        width: 0,
      },
      hovertemplate: "%{x}: band p20–p80<extra></extra>",
    } as PlotlyTrace);
    data.push({
      type: "scatter",
      mode: "markers",
      name: "peer p50",
      x: labels,
      y: p50,
      marker: {
        size: 10,
        symbol: "line-ew",
        color: "#2e7d32",
        line: { width: 2, color: "#2e7d32" },
      },
    });
  }
  data.push({
    type: "scatter",
    mode: "markers+text",
    name: "site_eui",
    x: labels,
    y: eui,
    text: eui.map((v) => (v != null ? v.toFixed(1) : "")),
    textposition: "top center",
    marker: {
      size: 14,
      symbol: "diamond",
      color: rainbowColor(0),
      line: { width: 1, color: "#333" },
    },
  });

  return {
    data,
    layout: overviewChartLayout({
      xTitle: "building",
      yTitle: "Site EUI (kBtu/ft²·yr)",
      height: Math.max(420, 360 + 16 * Math.min(rows.length, 12)),
      tickangle: -20,
      uirevision: `fuel-peer-bullet:${fingerprintJson(labels)}`,
      extra: {
        title: "Site EUI vs same-type band (p20–p80)",
        barmode: "overlay",
        bargap: 0.35,
      },
    }),
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/fuel · fuel-summary-v1",
    },
  };
}

/** Ranked site EUI horizontal bars (highest first). */
export function rankedSiteEui(
  rows: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const ranked = [...rows]
    .map((r) => ({ label: buildingLabel(r), eui: siteEui(r) }))
    .filter((r) => r.eui != null)
    .sort((a, b) => (b.eui ?? 0) - (a.eui ?? 0));
  if (!ranked.length) return null;
  return {
    data: [
      {
        type: "bar",
        name: "site_eui",
        orientation: "h",
        y: ranked.map((r) => r.label),
        x: ranked.map((r) => r.eui),
        marker: { color: rainbowColor(1) },
      },
    ],
    layout: overviewChartLayout({
      xTitle: "kBtu/ft²·yr",
      yTitle: "building",
      height: Math.max(320, 36 * ranked.length + 80),
      tickangle: 0,
      uirevision: `fuel-ranked:${fingerprintJson(ranked.map((r) => r.label))}`,
      extra: { title: "Ranked site EUI (kBtu/ft²)" },
    }),
    meta: {
      point_count: ranked.length,
      provenance: "POST /api/analytics/fuel · fuel-summary-v1",
    },
  };
}

/** Rolling 12-month site EUI from stacked/monthly kBtu totals. */
export function rolling12Eui(
  rows: Array<Record<string, unknown>>,
  floorAreaFt2?: number | null,
): PlotlyFigure | null {
  if (!rows.length || !floorAreaFt2 || floorAreaFt2 <= 0) return null;
  const byMonth = new Map<string, number>();
  for (const r of rows) {
    const month = String(r.month ?? "");
    const kbtu = num(r.kbtu ?? r.usage);
    if (!month || kbtu == null) continue;
    byMonth.set(month, (byMonth.get(month) ?? 0) + kbtu);
  }
  const months = [...byMonth.keys()].sort();
  if (months.length < 12) return null;
  const series = months.map((m) => byMonth.get(m) ?? 0);
  const roll: Array<number | null> = series.map((_, i) => {
    if (i < 11) return null;
    let sum = 0;
    for (let j = i - 11; j <= i; j++) sum += series[j]!;
    return sum / floorAreaFt2;
  });
  if (!roll.some((v) => v != null)) return null;
  return {
    data: [
      {
        type: "scatter",
        mode: "lines+markers",
        name: "roll_12_eui",
        x: months,
        y: roll,
        connectgaps: false,
        line: { width: 1.8, color: rainbowColor(2) },
        marker: { size: 5, color: rainbowColor(2) },
      },
    ],
    layout: overviewChartLayout({
      xTitle: "month",
      yTitle: "kBtu/ft²",
      height: 320,
      tickangle: -35,
      uirevision: `fuel-roll12:${fingerprintJson(months.slice(0, 12))}`,
      extra: { title: "Rolling 12-month site EUI" },
    }),
    meta: {
      point_count: months.length,
      provenance: "POST /api/analytics/fuel · fuel-stacked-v1 / fuel-monthly-v1",
    },
  };
}

/** Intensity heatmap filtered to one fuel (Portfolio layout columns). */
export function intensityHeatmapForFuel(
  rows: Array<Record<string, unknown>>,
  fuel: string,
): PlotlyFigure | null {
  const filtered = rows.filter((r) =>
    String(r.fuel ?? "")
      .toLowerCase()
      .includes(fuel.toLowerCase()),
  );
  if (!filtered.length) return null;
  const fig = intensityHeatmap(filtered);
  if (!fig) return null;
  const title =
    fuel.toLowerCase().startsWith("elec")
      ? "Elec kBtu/ft²"
      : fuel.toLowerCase().startsWith("gas")
        ? "Gas kBtu/ft²"
        : `Intensity · ${fuel}`;
  return {
    ...fig,
    layout: {
      ...fig.layout,
      title,
    },
    meta: {
      ...fig.meta,
      provenance: `${fig.meta?.provenance ?? ""} · fuel=${fuel}`,
    },
  };
}

function siteEui(row: Record<string, unknown>): number | null {
  return num(row.site_eui ?? row.site_eui_kbtu_ft2);
}

function buildingLabel(row: Record<string, unknown>): string {
  return String(row.building_id ?? row.label ?? row.building ?? "building");
}

function intensityValue(row: Record<string, unknown>): number | null {
  return num(row.kbtu_ft2 ?? row.intensity_kbtu_ft2);
}

function peerP50(row: Record<string, unknown>): number | null {
  return peerBand(row).p50;
}

/** Site EUI vs peer p50 grouped bars. */
export function summaryPeerBars(
  rows: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const labels = rows.map(buildingLabel);
  const site = rows.map(siteEui);
  const peer = rows.map(peerP50);
  if (!site.some((v) => v != null) && !peer.some((v) => v != null)) return null;
  return {
    data: [
      {
        type: "bar",
        name: "site_eui",
        x: labels,
        y: site,
        marker: { color: rainbowColor(0) },
      },
      {
        type: "bar",
        name: "peer_p50",
        x: labels,
        y: peer,
        marker: { color: rainbowColor(5) },
      },
    ],
    layout: overviewChartLayout({
      xTitle: "building",
      yTitle: "kBtu/ft²·yr",
      height: 400,
      tickangle: -25,
      uirevision: `fuel-summary:${fingerprintJson(labels)}`,
      extra: { title: "Site EUI vs peer p50", barmode: "group" },
    }),
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/fuel · fuel-summary-v1",
    },
  };
}

/** Month vs kBtu stacked by fuel. */
export function stackedFuel(
  rows: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const months = [
    ...new Set(rows.map((r) => String(r.month ?? ""))),
  ]
    .filter(Boolean)
    .sort();
  const fuels = [
    ...new Set(rows.map((r) => String(r.fuel ?? "fuel"))),
  ].sort();
  if (!months.length || !fuels.length) return null;

  const lookup = new Map<string, number>();
  for (const r of rows) {
    const month = String(r.month ?? "");
    const fuel = String(r.fuel ?? "fuel");
    const kbtu = num(r.kbtu);
    if (!month || kbtu == null) continue;
    lookup.set(`${month}\0${fuel}`, kbtu);
  }

  const data: PlotlyTrace[] = fuels.map((fuel, i) => ({
    type: "bar",
    name: fuel,
    x: months,
    y: months.map((m) => lookup.get(`${m}\0${fuel}`) ?? null),
    marker: { color: rainbowColor(i) },
  }));

  return {
    data,
    layout: overviewChartLayout({
      xTitle: "month",
      yTitle: "kBtu",
      height: 420,
      tickangle: -45,
      uirevision: `fuel-stacked:${fingerprintJson(months.slice(0, 12))}`,
      extra: { title: "Stacked fuel (kBtu)", barmode: "stack" },
    }),
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/fuel · fuel-stacked-v1",
    },
  };
}

/** Usage (or kBtu) by meter over month. */
export function monthlyLines(
  rows: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const byMeter = new Map<string, Array<Record<string, unknown>>>();
  for (const r of rows) {
    const id = String(r.meter_id ?? r.fuel ?? "meter");
    const list = byMeter.get(id) ?? [];
    list.push(r);
    byMeter.set(id, list);
  }
  const data: PlotlyTrace[] = [];
  let i = 0;
  for (const [meterId, meterRows] of [...byMeter.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    const sorted = [...meterRows].sort((a, b) =>
      String(a.month ?? "").localeCompare(String(b.month ?? "")),
    );
    data.push({
      type: "scatter",
      mode: "lines+markers",
      name: meterId,
      x: sorted.map((r) => String(r.month ?? "")),
      y: sorted.map((r) => num(r.usage ?? r.kbtu)),
      line: { width: 1.6, color: rainbowColor(i) },
      marker: { size: 5, color: rainbowColor(i) },
    });
    i += 1;
  }
  if (!data.length) return null;
  return {
    data,
    layout: overviewChartLayout({
      xTitle: "month",
      yTitle: "usage",
      height: Math.max(380, 40 + 14 * Math.min(byMeter.size, 16)),
      tickangle: -35,
      uirevision: `fuel-monthly:${fingerprintJson([...byMeter.keys()])}`,
      extra: { title: "Monthly utility by meter" },
    }),
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/fuel · fuel-monthly-v1",
    },
  };
}

/** Intensity heatmap (month × fuel or year × month). */
export function intensityHeatmap(
  rows: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const hasIntensity = rows.some((r) => intensityValue(r) != null);
  if (!hasIntensity) return null;

  const hasYearMonth = rows.every(
    (r) => r.year != null && (r.month != null || r.mon != null),
  );

  if (hasYearMonth) {
    const years = [
      ...new Set(rows.map((r) => String(r.year ?? ""))),
    ]
      .filter(Boolean)
      .sort();
    const months = [
      ...new Set(
        rows.map((r) => {
          const m = String(r.month ?? "");
          if (/^\d{4}-\d{2}$/.test(m)) return m.slice(5);
          const mon = num(r.mon);
          return mon != null ? String(mon).padStart(2, "0") : m;
        }),
      ),
    ]
      .filter(Boolean)
      .sort();
    const fuels = [...new Set(rows.map((r) => String(r.fuel ?? "")))].filter(
      Boolean,
    );
    // Prefer fuel on y when multiple fuels; else year.
    if (fuels.length > 1) {
      const z = fuels.map((fuel) =>
        months.map((mo) => {
          const hit = rows.find((r) => {
            const rm = String(r.month ?? "");
            const mon =
              /^\d{4}-\d{2}$/.test(rm)
                ? rm.slice(5)
                : String(num(r.mon) ?? "").padStart(2, "0");
            return String(r.fuel ?? "") === fuel && mon === mo;
          });
          return hit ? intensityValue(hit) : null;
        }),
      );
      return {
        data: [
          {
            type: "heatmap",
            name: "intensity",
            x: months,
            y: fuels,
            z,
            colorscale: [
              [0, rainbowColor(5)],
              [0.5, rainbowColor(2)],
              [1, rainbowColor(0)],
            ],
            colorbar: { title: "kBtu/ft²" },
            hoverongaps: false,
          } as PlotlyTrace,
        ],
        layout: overviewChartLayout({
          xTitle: "month",
          yTitle: "fuel",
          height: Math.max(360, 48 * fuels.length),
          tickangle: 0,
          uirevision: `fuel-intensity:${fingerprintJson(months.slice(0, 12))}`,
          extra: { title: "Energy intensity (kBtu/ft²)", showlegend: false },
        }),
        meta: {
          point_count: rows.length,
          provenance: "POST /api/analytics/fuel · fuel-intensity-v1",
        },
      };
    }

    const z = years.map((year) =>
      months.map((mo) => {
        const hit = rows.find((r) => {
          const rm = String(r.month ?? "");
          const mon =
            /^\d{4}-\d{2}$/.test(rm)
              ? rm.slice(5)
              : String(num(r.mon) ?? "").padStart(2, "0");
          return String(r.year ?? "") === year && mon === mo;
        });
        return hit ? intensityValue(hit) : null;
      }),
    );
    return {
      data: [
        {
          type: "heatmap",
          name: "intensity",
          x: months,
          y: years,
          z,
          colorscale: [
            [0, rainbowColor(5)],
            [0.5, rainbowColor(2)],
            [1, rainbowColor(0)],
          ],
          colorbar: { title: "kBtu/ft²" },
          hoverongaps: false,
        } as PlotlyTrace,
      ],
      layout: overviewChartLayout({
        xTitle: "month",
        yTitle: "year",
        height: Math.max(360, 40 * years.length),
        tickangle: 0,
        uirevision: `fuel-intensity-ym:${fingerprintJson(years)}`,
        extra: { title: "Energy intensity (kBtu/ft²)", showlegend: false },
      }),
      meta: {
        point_count: rows.length,
        provenance: "POST /api/analytics/fuel · fuel-intensity-v1",
      },
    };
  }

  // Fallback: scatter-style month vs intensity colored by fuel
  const byFuel = new Map<string, Array<Record<string, unknown>>>();
  for (const r of rows) {
    const fuel = String(r.fuel ?? "fuel");
    const list = byFuel.get(fuel) ?? [];
    list.push(r);
    byFuel.set(fuel, list);
  }
  const data: PlotlyTrace[] = [];
  let i = 0;
  for (const [fuel, fuelRows] of [...byFuel.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: fuel,
      x: fuelRows.map((r) => String(r.month ?? "")),
      y: fuelRows.map((r) => intensityValue(r)),
      marker: { size: 10, color: rainbowColor(i), opacity: 0.85 },
    });
    i += 1;
  }
  return {
    data,
    layout: overviewChartLayout({
      xTitle: "month",
      yTitle: "kBtu/ft²",
      height: 400,
      tickangle: -35,
      uirevision: `fuel-intensity-sc:${fingerprintJson([...byFuel.keys()])}`,
      extra: { title: "Energy intensity" },
    }),
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/fuel · fuel-intensity-v1",
    },
  };
}

/** Demand (kW) heatmap — meter × month. */
export function demandHeatmap(
  rows: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const meters = [
    ...new Set(rows.map((r) => String(r.meter_id ?? "meter"))),
  ].sort();
  const months = [
    ...new Set(rows.map((r) => String(r.month ?? ""))),
  ]
    .filter(Boolean)
    .sort();
  if (!meters.length || !months.length) return null;

  const z = meters.map((meter) =>
    months.map((month) => {
      const hit = rows.find(
        (r) =>
          String(r.meter_id ?? "meter") === meter &&
          String(r.month ?? "") === month,
      );
      return hit ? num(hit.demand_kw) : null;
    }),
  );

  return {
    data: [
      {
        type: "heatmap",
        name: "demand_kw",
        x: months,
        y: meters,
        z,
        colorscale: [
          [0, rainbowColor(4)],
          [0.5, rainbowColor(1)],
          [1, rainbowColor(0)],
        ],
        colorbar: { title: "kW" },
        hoverongaps: false,
      } as PlotlyTrace,
    ],
    layout: overviewChartLayout({
      xTitle: "month",
      yTitle: "meter",
      height: Math.max(360, 36 * Math.min(meters.length, 20)),
      tickangle: -40,
      uirevision: `fuel-demand:${fingerprintJson(months.slice(0, 12))}`,
      extra: { title: "Peak demand (kW)", showlegend: false },
    }),
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/fuel · fuel-demand-v1",
    },
  };
}

/**
 * Weather / baseline scatter from analytics points
 * (oat / hdd / cdd vs usage), with optional OLS fit lines from `fits`.
 */
export function weatherScatter(
  points: Array<Record<string, unknown>>,
  fits?: Array<Record<string, unknown>>,
): PlotlyFigure | null {
  if (!points.length) return null;
  const byFuel = new Map<string, Array<Record<string, unknown>>>();
  for (const p of points) {
    const fuel = String(p.fuel ?? "fuel");
    const list = byFuel.get(fuel) ?? [];
    list.push(p);
    byFuel.set(fuel, list);
  }
  const data: PlotlyTrace[] = [];
  let i = 0;
  const xNames = new Set<string>();
  for (const [fuel, rows] of [...byFuel.entries()].sort((a, b) =>
    a[0].localeCompare(b[0]),
  )) {
    const xName = String(rows[0]?.x_name ?? rows[0]?.xName ?? "degree-days");
    xNames.add(xName);
    const xs = rows.map((r) =>
      num(r.x ?? r.hdd ?? r.cdd ?? r.oat ?? r.mean_oat_f),
    );
    const ys = rows.map((r) => num(r.y ?? r.usage ?? r.kbtu));
    data.push({
      type: "scatter",
      mode: "markers",
      name: fuel,
      x: xs,
      y: ys,
      marker: { size: 8, opacity: 0.75, color: rainbowColor(i) },
      text: rows.map((r) => String(r.month ?? "")),
    });

    const fit = (fits ?? []).find(
      (f) => String(f.fuel ?? "").toLowerCase() === fuel.toLowerCase(),
    );
    const slope = fit ? num(fit.slope) : null;
    const intercept = fit ? num(fit.intercept) : null;
    const finiteXs = xs.filter((v): v is number => v != null);
    if (slope != null && intercept != null && finiteXs.length >= 2) {
      const xmin = Math.min(...finiteXs);
      const xmax = Math.max(...finiteXs);
      const lineX: number[] = [];
      const lineY: number[] = [];
      for (let k = 0; k <= 40; k++) {
        const x = xmin + ((xmax - xmin) * k) / 40;
        lineX.push(x);
        lineY.push(slope * x + intercept);
      }
      const r2 = num(fit?.r2);
      data.push({
        type: "scatter",
        mode: "lines",
        name: `${fuel} fit${r2 != null ? ` R²=${r2.toFixed(3)}` : ""}`,
        x: lineX,
        y: lineY,
        line: { width: 2, color: rainbowColor(i), dash: "solid" },
      });
    }
    i += 1;
  }
  if (!data.some((t) => (t.x ?? []).some((v) => v != null))) return null;
  const xTitle =
    xNames.size === 1
      ? [...xNames][0]!
      : "HDD / CDD / OAT";
  return {
    data,
    layout: overviewChartLayout({
      xTitle,
      yTitle: "usage",
      height: 420,
      tickangle: 0,
      uirevision: `fuel-weather:${fingerprintJson(points.slice(0, 30))}`,
      extra: { title: "Weather vs usage" },
    }),
    meta: {
      point_count: points.length,
      provenance: "POST /api/analytics/fuel · fuel-weather-v1",
    },
  };
}

/** Residual bars (actual − predicted) for one fuel using OLS fit. */
export function weatherResidualBars(
  points: Array<Record<string, unknown>>,
  fit: Record<string, unknown>,
): PlotlyFigure | null {
  const fuel = String(fit.fuel ?? "");
  const slope = num(fit.slope);
  const intercept = num(fit.intercept);
  if (slope == null || intercept == null) return null;
  const rows = points
    .filter((p) => String(p.fuel ?? "").toLowerCase() === fuel.toLowerCase())
    .map((p) => {
      const x = num(p.x ?? p.hdd ?? p.cdd ?? p.oat ?? p.mean_oat_f);
      const y = num(p.y ?? p.usage ?? p.kbtu);
      const month = String(p.month ?? "");
      if (x == null || y == null || !month) return null;
      return { month, residual: y - (slope * x + intercept) };
    })
    .filter((r): r is { month: string; residual: number } => r != null)
    .sort((a, b) => a.month.localeCompare(b.month));
  if (!rows.length) return null;
  return {
    data: [
      {
        type: "bar",
        name: `${fuel} residual`,
        x: rows.map((r) => r.month),
        y: rows.map((r) => r.residual),
        marker: { color: rainbowColor(3) },
      },
    ],
    layout: overviewChartLayout({
      xTitle: "month",
      yTitle: "residual",
      height: 280,
      tickangle: -35,
      uirevision: `fuel-resid:${fuel}:${fingerprintJson(rows.slice(0, 12))}`,
      extra: { title: `${fuel} residuals` },
    }),
    meta: {
      point_count: rows.length,
      provenance: "POST /api/analytics/fuel · fuel-weather-v1 fits",
    },
  };
}

/**
 * Peak demand by year (bars) with optional cool-season avg high on y2.
 * Cool-season values may come from demand rows (`cool_season_avg_high`) or a map.
 */
export function demandPeakDualAxis(
  rows: Array<Record<string, unknown>>,
  coolSeasonByYear?: Record<string, number | null | undefined>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const peakByYear = new Map<string, number>();
  const coolFromRows = new Map<string, number>();
  for (const r of rows) {
    const year = String(
      r.year ?? String(r.month ?? "").slice(0, 4) ?? "",
    );
    if (!/^\d{4}$/.test(year)) continue;
    const d = num(r.demand_kw);
    if (d != null) {
      peakByYear.set(year, Math.max(peakByYear.get(year) ?? 0, d));
    }
    const cool = num(
      r.cool_season_avg_high ?? r.cooling_season_avg_high ?? r.cool_avg_high_f,
    );
    if (cool != null) coolFromRows.set(year, cool);
  }
  const years = [...peakByYear.keys()].sort();
  if (!years.length) return null;
  const peaks = years.map((y) => peakByYear.get(y) ?? null);
  const cools = years.map((y) => {
    if (coolSeasonByYear && coolSeasonByYear[y] != null) {
      return num(coolSeasonByYear[y]);
    }
    return coolFromRows.get(y) ?? null;
  });
  const hasCool = cools.some((v) => v != null);

  const data: PlotlyTrace[] = [
    {
      type: "bar",
      name: "Peak kW",
      x: years,
      y: peaks,
      marker: { color: rainbowColor(0) },
    },
  ];
  if (hasCool) {
    data.push({
      type: "scatter",
      mode: "lines+markers",
      name: "Cool-season avg high °F",
      x: years,
      y: cools,
      yaxis: "y2",
      line: { width: 2, color: rainbowColor(6) },
      marker: { size: 7, color: rainbowColor(6) },
    });
  }

  return {
    data,
    layout: overviewChartLayout({
      xTitle: "year",
      yTitle: "peak_kw",
      height: 380,
      tickangle: 0,
      uirevision: `fuel-peak-year:${fingerprintJson(years)}`,
      extra: {
        title: hasCool
          ? "Peak demand by year + cooling-season avg high"
          : "Peak demand by year",
        yaxis2: hasCool
          ? {
              title: "Avg daily-max °F",
              overlaying: "y",
              side: "right",
              showgrid: false,
            }
          : undefined,
      },
    }),
    meta: {
      point_count: years.length,
      provenance: "POST /api/analytics/fuel · fuel-demand-v1",
    },
  };
}

/** Peak kW vs cool-season avg high scatter when ≥2 paired years. */
export function peakVsCoolSeason(
  rows: Array<Record<string, unknown>>,
  coolSeasonByYear?: Record<string, number | null | undefined>,
): PlotlyFigure | null {
  if (!rows.length) return null;
  const peakByYear = new Map<string, number>();
  const coolFromRows = new Map<string, number>();
  for (const r of rows) {
    const year = String(r.year ?? String(r.month ?? "").slice(0, 4) ?? "");
    if (!/^\d{4}$/.test(year)) continue;
    const d = num(r.demand_kw);
    if (d != null) peakByYear.set(year, Math.max(peakByYear.get(year) ?? 0, d));
    const cool = num(
      r.cool_season_avg_high ?? r.cooling_season_avg_high ?? r.cool_avg_high_f,
    );
    if (cool != null) coolFromRows.set(year, cool);
  }
  const xs: number[] = [];
  const ys: number[] = [];
  const texts: string[] = [];
  for (const year of [...peakByYear.keys()].sort()) {
    const peak = peakByYear.get(year);
    const cool =
      coolSeasonByYear?.[year] != null
        ? num(coolSeasonByYear[year])
        : (coolFromRows.get(year) ?? null);
    if (peak == null || cool == null) continue;
    xs.push(cool);
    ys.push(peak);
    texts.push(year);
  }
  if (xs.length < 2) return null;
  return {
    data: [
      {
        type: "scatter",
        mode: "markers+text",
        name: "year",
        x: xs,
        y: ys,
        text: texts,
        textposition: "top center",
        marker: { size: 10, color: rainbowColor(0) },
      },
    ],
    layout: overviewChartLayout({
      xTitle: "Cooling-season avg high °F",
      yTitle: "Peak kW",
      height: 360,
      tickangle: 0,
      uirevision: `fuel-peak-cool:${fingerprintJson(texts)}`,
      extra: { title: "Peak kW vs cooling-season avg high" },
    }),
    meta: {
      point_count: xs.length,
      provenance: "POST /api/analytics/fuel · fuel-demand-v1",
    },
  };
}

