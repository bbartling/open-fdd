import type { PlotlyFigure } from "./plotDataset";

/** Drop Plotly.py template blobs — they bloat JSON and can break newPlot. */
export function sanitizePlotlyFigure(
  figure: PlotlyFigure | null | undefined,
): PlotlyFigure | null {
  if (!figure || !Array.isArray(figure.data) || figure.data.length === 0) {
    return null;
  }
  const layout = { ...(figure.layout ?? {}) } as Record<string, unknown>;
  delete layout.template;
  return { ...figure, data: figure.data, layout };
}
