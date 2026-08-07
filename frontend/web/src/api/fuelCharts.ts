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

function peerP50(row: Record<string, unknown>): number | null {
  const flat = num(row.peer_p50);
  if (flat != null) return flat;
  const peer = row.peer;
  if (peer && typeof peer === "object" && !Array.isArray(peer)) {
    return num((peer as Record<string, unknown>).p50);
  }
  return null;
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
 * (oat / hdd / cdd vs usage).
 */
export function weatherScatter(
  points: Array<Record<string, unknown>>,
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
    data.push({
      type: "scatter",
      mode: "markers",
      name: fuel,
      x: rows.map((r) =>
        num(r.x ?? r.hdd ?? r.cdd ?? r.oat ?? r.mean_oat_f),
      ),
      y: rows.map((r) => num(r.y ?? r.usage ?? r.kbtu)),
      marker: { size: 8, opacity: 0.75, color: rainbowColor(i) },
      text: rows.map((r) => String(r.month ?? "")),
    });
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
