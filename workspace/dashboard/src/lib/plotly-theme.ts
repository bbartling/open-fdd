/** Shared Plotly layout theming — single source of truth for light/dark charts. */

export type ChartTheme = "light" | "dark";

export type PlotlyThemeLayout = {
  paper_bgcolor: string;
  plot_bgcolor: string;
  font: { color: string; family?: string; size?: number };
  xaxis: Record<string, unknown>;
  yaxis: Record<string, unknown>;
  legend: Record<string, unknown>;
  hoverlabel: Record<string, unknown>;
  margin: { t: number; r: number; b: number; l: number };
  colorway: string[];
};

const LIGHT = {
  paper: "transparent",
  plot: "#ffffff",
  font: "#1a2332",
  grid: "#d8e0ec",
  line: "#b8c4d4",
  hoverBg: "#ffffff",
  hoverFont: "#1a2332",
};

const DARK = {
  paper: "transparent",
  plot: "#161b24",
  font: "#e6edf3",
  grid: "#30363d",
  line: "#3d4654",
  hoverBg: "#1b2230",
  hoverFont: "#e6edf3",
};

export function getPlotlyThemeLayout(
  theme: ChartTheme,
  overrides: Partial<PlotlyThemeLayout> = {},
): PlotlyThemeLayout {
  const pal = theme === "dark" ? DARK : LIGHT;
  const base: PlotlyThemeLayout = {
    paper_bgcolor: pal.paper,
    plot_bgcolor: pal.plot,
    font: { color: pal.font, size: 12 },
    xaxis: {
      gridcolor: pal.grid,
      linecolor: pal.line,
      tickfont: { color: pal.font },
      titlefont: { color: pal.font },
      zerolinecolor: pal.grid,
    },
    yaxis: {
      gridcolor: pal.grid,
      linecolor: pal.line,
      tickfont: { color: pal.font },
      titlefont: { color: pal.font },
      zerolinecolor: pal.grid,
    },
    legend: {
      orientation: "h" as const,
      y: 1.12,
      font: { color: pal.font, size: 11 },
      bgcolor: "rgba(0,0,0,0)",
    },
    hoverlabel: {
      bgcolor: pal.hoverBg,
      font: { color: pal.hoverFont, size: 11 },
      bordercolor: pal.grid,
    },
    margin: { t: 48, r: 48, b: 48, l: 56 },
    colorway: ["#3b6de0", "#2d9a52", "#c9870a", "#a371f7", "#c53d3d", "#58a6ff"],
  };
  return { ...base, ...overrides };
}

export function mergePlotLayout(
  theme: ChartTheme,
  layout: Record<string, unknown>,
): Record<string, unknown> {
  const themed = getPlotlyThemeLayout(theme);
  return {
    ...themed,
    ...layout,
    font: { ...themed.font, ...(layout.font as object) },
    xaxis: { ...themed.xaxis, ...(layout.xaxis as object) },
    yaxis: { ...themed.yaxis, ...(layout.yaxis as object) },
    legend: { ...themed.legend, ...(layout.legend as object) },
    hoverlabel: { ...themed.hoverlabel, ...(layout.hoverlabel as object) },
    margin: { ...themed.margin, ...(layout.margin as object) },
  };
}
