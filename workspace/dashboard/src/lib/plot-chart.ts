/** Build Plotly traces/layout for telemetry + fault overlays (web_lambda-style). */

import { getPlotlyThemeLayout, type ChartTheme } from "./plotly-theme";

export type PlotReadingsResponse = {
  timestamps: string[];
  series: Record<string, (number | null)[]>;
  aux_series?: Record<string, (number | null)[]>;
  series_kinds?: Record<string, string>;
  labels?: Record<string, string>;
  fault_plots?: Record<string, number[]>;
  fault_panels?: { key: string; title: string; color: string; fault_code?: string }[];
  fault_totals?: Record<string, number>;
  chart_guides?: Record<string, number>;
  chart_truncated?: boolean;
  chart_stride?: number;
  hours?: number;
  site_id?: string;
  rolling_avg_minutes?: number;
  rolling_avg_minutes_allowed?: number[];
  show_rolling_avg?: boolean;
};

const TEMP_PALETTE = ["#58a6ff", "#79c0ff", "#a371f7", "#ffa657"];
const RH_PALETTE = ["#3fb950", "#56d364"];

export function faultBoolY(flags: number[]): number[] {
  return flags.map((f) => (f ? 1 : 0));
}

export type PlotAxisLimit = { min?: number; max?: number };

export function parsePlotAxisLimit(minRaw: string, maxRaw: string): PlotAxisLimit | null {
  const minText = minRaw.trim();
  const maxText = maxRaw.trim();
  if (!minText && !maxText) return null;
  const min = minText ? Number(minText) : undefined;
  const max = maxText ? Number(maxText) : undefined;
  if (minText && !Number.isFinite(min)) return null;
  if (maxText && !Number.isFinite(max)) return null;
  if (min != null && max != null && min >= max) return null;
  return { min, max };
}

function applyAxisRange(
  axis: Partial<Plotly.LayoutAxis>,
  limit: PlotAxisLimit | null | undefined,
): Partial<Plotly.LayoutAxis> {
  if (!limit || (limit.min == null && limit.max == null)) {
    return axis;
  }
  const next = { ...axis, autorange: false as const };
  if (limit.min != null && limit.max != null) {
    next.range = [limit.min, limit.max];
  } else if (limit.min != null) {
    next.range = [limit.min, limit.max ?? limit.min + 1];
  } else if (limit.max != null) {
    next.range = [(limit.max ?? 0) - 1, limit.max];
  }
  return next;
}

export function buildPlotTraces(
  data: PlotReadingsResponse,
  opts: {
    enabledFaults: Set<string>;
    showBounds: boolean;
    showRollingAvg: boolean;
    theme: ChartTheme;
    yLeftLimit?: PlotAxisLimit | null;
    yRightLimit?: PlotAxisLimit | null;
    yFaultLimit?: PlotAxisLimit | null;
  },
): { traces: Plotly.Data[]; layout: Partial<Plotly.Layout>; shapes: Partial<Plotly.Shape>[] } {
  const x = (data.timestamps ?? []).map((t) => {
    const s = String(t ?? "").trim();
    if (!s) return s;
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.replace(" ", "T");
    return s;
  });
  const kinds = data.series_kinds ?? {};
  const labels = data.labels ?? {};
  const traces: Plotly.Data[] = [];
  let ti = 0;
  let hi = 0;
  let hasTemp = false;
  let hasRh = false;

  for (const [col, vals] of Object.entries(data.series ?? {})) {
    const kind = kinds[col] || "temperature";
    if (kind === "humidity") {
      hasRh = true;
      traces.push({
        x,
        y: vals,
        name: labels[col] || col,
        type: "scatter",
        mode: "lines",
        line: { color: RH_PALETTE[hi % RH_PALETTE.length], width: 2 },
        yaxis: "y2",
        connectgaps: true,
        hovertemplate: `%{y:.1f} %RH · ${col}<extra></extra>`,
      });
      hi += 1;
    } else {
      hasTemp = true;
      traces.push({
        x,
        y: vals,
        name: labels[col] || col,
        type: "scatter",
        mode: "lines",
        line: { color: TEMP_PALETTE[ti % TEMP_PALETTE.length], width: 2 },
        yaxis: "y",
        connectgaps: true,
        hovertemplate: `%{y:.2f} · ${col}<extra></extra>`,
      });
      ti += 1;
    }
  }

  if (opts.showRollingAvg && data.aux_series && Object.keys(data.aux_series).length) {
    const rollMin = data.rolling_avg_minutes ?? 5;
    for (const [key, vals] of Object.entries(data.aux_series)) {
      const baseCol = key.replace(/__rolling_\d+m$/, "");
      const label = data.labels?.[baseCol] || baseCol;
      traces.push({
        x,
        y: vals,
        name: `${label} (${rollMin} min avg)`,
        type: "scatter",
        mode: "lines",
        line: { color: "#8b949e", width: 2, dash: "dot" },
        yaxis: "y",
        connectgaps: true,
        opacity: 0.85,
        hovertemplate: `%{y:.2f} · ${rollMin} min avg<extra></extra>`,
      });
    }
  }

  const panels = (data.fault_panels ?? []).filter((p) => opts.enabledFaults.has(p.key));
  const showFaultAxis = panels.length > 0;
  const faultAxis = hasRh ? "y3" : "y2";

  for (const panel of panels) {
    const flags = data.fault_plots?.[panel.key] ?? x.map(() => 0);
    const total = data.fault_totals?.[panel.key] ?? 0;
    traces.push({
      x,
      y: faultBoolY(flags),
      name: `${panel.title} (${total})`,
      type: "scatter",
      mode: "lines",
      line: { color: panel.color, width: 2, shape: "hv" },
      yaxis: showFaultAxis ? faultAxis : "y",
      opacity: 0.92,
      hovertemplate: `${panel.title}<extra></extra>`,
    });
  }

  const themed = getPlotlyThemeLayout(opts.theme);
  const layout: Partial<Plotly.Layout> = {
    ...themed,
    hovermode: "x unified",
    xaxis: { ...themed.xaxis, title: "Time (UTC)", automargin: true },
    yaxis: applyAxisRange(
      {
        ...themed.yaxis,
        title: hasTemp ? "Temperature" : "Value",
        side: "left",
        automargin: true,
      },
      opts.yLeftLimit,
    ),
  };
  layout.margin = { ...themed.margin, r: showFaultAxis ? 88 : themed.margin.r };

  if (hasRh) {
    layout.yaxis2 = applyAxisRange(
      {
        ...themed.yaxis,
        title: "% RH",
        side: "right",
        overlaying: "y",
        automargin: true,
      },
      opts.yRightLimit,
    );
  }

  if (showFaultAxis) {
    const faultLayout: Partial<Plotly.LayoutAxis> = applyAxisRange(
      {
        ...themed.yaxis,
        title: "Faults (0/1)",
        side: "right",
        overlaying: "y",
        range: [-0.08, 1.08],
        tickvals: [0, 1],
        ticktext: ["OK", "FAULT"],
        showgrid: false,
        automargin: true,
      },
      opts.yFaultLimit,
    );
    if (hasRh) {
      layout.yaxis3 = { ...faultLayout, position: 0.98 };
    } else {
      layout.yaxis2 = faultLayout;
    }
  }

  const shapes: Partial<Plotly.Shape>[] = [];
  if (opts.showBounds && data.chart_guides) {
    const g = data.chart_guides;
    if (g.bounds_low != null) {
      shapes.push({
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y",
        y0: g.bounds_low,
        y1: g.bounds_low,
        line: { color: "#d29922", width: 1, dash: "dash" },
      });
    }
    if (g.bounds_high != null) {
      shapes.push({
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y",
        y0: g.bounds_high,
        y1: g.bounds_high,
        line: { color: "#d29922", width: 1, dash: "dash" },
      });
    }
    if (g.bounds_low_rh != null && hasRh) {
      shapes.push({
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y2",
        y0: g.bounds_low_rh,
        y1: g.bounds_low_rh,
        line: { color: "#3fb950", width: 1, dash: "dot" },
      });
    }
    if (g.bounds_high_rh != null && hasRh) {
      shapes.push({
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y2",
        y0: g.bounds_high_rh,
        y1: g.bounds_high_rh,
        line: { color: "#3fb950", width: 1, dash: "dot" },
      });
    }
  }

  if (shapes.length) {
    layout.shapes = shapes;
  }

  return { traces, layout, shapes };
}

// Minimal Plotly types for compile without @types/plotly.js
namespace Plotly {
  export type Data = Record<string, unknown>;
  export type Layout = Record<string, unknown>;
  export type LayoutAxis = Record<string, unknown>;
  export type Shape = Record<string, unknown>;
}
