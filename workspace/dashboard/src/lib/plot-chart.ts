/** Build Plotly traces/layout for telemetry + fault overlays (web_lambda-style). */

export type PlotReadingsResponse = {
  timestamps: string[];
  series: Record<string, (number | null)[]>;
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
};

const TEMP_PALETTE = ["#58a6ff", "#79c0ff", "#a371f7", "#ffa657"];
const RH_PALETTE = ["#3fb950", "#56d364"];

export function faultBoolY(flags: number[]): number[] {
  return flags.map((f) => (f ? 1 : 0));
}

export function buildPlotTraces(
  data: PlotReadingsResponse,
  opts: {
    enabledFaults: Set<string>;
    showBounds: boolean;
    theme: "light" | "dark";
  },
): { traces: Plotly.Data[]; layout: Partial<Plotly.Layout>; shapes: Partial<Plotly.Shape>[] } {
  const x = data.timestamps ?? [];
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

  const isDark = opts.theme === "dark";
  const grid = isDark ? "#30363d" : "#d8e0ec";
  const font = isDark ? "#e6edf3" : "#1a2332";
  const paper = "transparent";
  const plotBg = isDark ? "#161b24" : "#ffffff";

  const layout: Partial<Plotly.Layout> = {
    paper_bgcolor: paper,
    plot_bgcolor: plotBg,
    font: { color: font },
    margin: { t: 48, r: showFaultAxis ? 72 : 48, b: 48, l: 56 },
    hovermode: "x unified",
    legend: { orientation: "h", y: 1.14 },
    xaxis: { title: "Time (UTC)", gridcolor: grid },
    yaxis: {
      title: hasTemp ? "Temperature" : "Value",
      side: "left",
      gridcolor: grid,
    },
  };

  if (hasRh) {
    layout.yaxis2 = {
      title: "% RH",
      side: "right",
      overlaying: "y",
      gridcolor: grid,
    };
  }

  if (showFaultAxis) {
    const faultLayout: Partial<Plotly.LayoutAxis> = {
      side: hasRh ? "right" : "right",
      overlaying: "y",
      range: [0, 1],
      tickvals: [0, 1],
      ticktext: ["OK", "FAULT"],
      showgrid: false,
    };
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
