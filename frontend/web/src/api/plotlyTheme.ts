/**
 * Shared Plotly presentation constants — port of vibe19 / open_fdd.analytics.charts
 * RAINBOW_PALETTE + Overview layout defaults.
 */

export const RAINBOW_PALETTE: string[] = [
  "#e11d48", // rose
  "#ea580c", // orange
  "#ca8a04", // gold
  "#16a34a", // green
  "#0d9488", // teal
  "#2563eb", // blue
  "#7c3aed", // violet
  "#db2777", // pink
  "#0891b2", // cyan
  "#65a30d", // lime
  "#9333ea", // purple
  "#dc2626", // red
];

/** Bare-min occupied hours/week for air-side weekly chart (BUILDING_100 parity). */
export const AIR_BARE_MIN_OCC_HOURS_WEEK = 60;

export function rainbowColor(index: number): string {
  return RAINBOW_PALETTE[index % RAINBOW_PALETTE.length];
}

/** Horizontal legend + white-template margins used by vibe19 Overview charts. */
export function overviewChartLayout(opts: {
  xTitle: string;
  yTitle: string;
  height?: number;
  rightAxis?: boolean;
  tickangle?: number;
  uirevision?: string;
  extra?: Record<string, unknown>;
}): Record<string, unknown> {
  const right = Boolean(opts.rightAxis);
  return {
    showlegend: true,
    legend: { orientation: "h", y: 1.14, font: { size: 10 } },
    xaxis: {
      title: opts.xTitle,
      tickangle: opts.tickangle ?? -45,
      autorange: true,
    },
    yaxis: { title: opts.yTitle, autorange: true },
    ...(right
      ? {
          yaxis2: {
            title: "Avg OAT °F",
            overlaying: "y",
            side: "right",
            showgrid: false,
            autorange: true,
          },
        }
      : {}),
    margin: { l: 50, r: right ? 60 : 20, t: 60, b: 80 },
    paper_bgcolor: "white",
    plot_bgcolor: "white",
    height: opts.height ?? 420,
    ...(opts.uirevision ? { uirevision: opts.uirevision } : {}),
    ...(opts.extra ?? {}),
  };
}
