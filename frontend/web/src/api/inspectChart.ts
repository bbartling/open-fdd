/**
 * vibe19 equipment_inspection_chart — stacked subplots of raw historian columns.
 */
import { fingerprintJson, type PlotlyFigure, type PlotlyTrace } from "./plotDataset";
import { rainbowColor } from "./plotlyTheme";

export function equipmentInspectionChart(
  points: Array<Record<string, unknown>>,
  opts: {
    equipmentId: string;
    columns: string[];
    rowHeight?: number;
    maxHeight?: number;
  },
): PlotlyFigure | null {
  if (!points.length || !opts.columns.length) return null;
  const x = points.map((p) => String(p.timestamp_utc ?? ""));
  const cols = opts.columns.filter((c) =>
    points.some((p) => {
      const v = p[c];
      if (v == null || v === "") return false;
      const n = typeof v === "number" ? v : Number(v);
      return Number.isFinite(n) || typeof v === "boolean";
    }),
  );
  if (!cols.length) return null;

  const n = cols.length;
  const rowH = opts.rowHeight ?? 140;
  const height = Math.min(opts.maxHeight ?? 2400, Math.max(420, rowH * n + 80));
  const data: PlotlyTrace[] = [];
  const layout: Record<string, unknown> = {
    title: `Inspection — ${opts.equipmentId}`,
    height,
    showlegend: false,
    paper_bgcolor: "white",
    plot_bgcolor: "white",
    margin: { t: 48, r: 24, b: 40, l: 56 },
    uirevision: `inspect:${opts.equipmentId}:${fingerprintJson(cols)}`,
  };

  cols.forEach((col, i) => {
    const axis = i === 0 ? "y" : `y${i + 1}`;
    const xaxis = i === 0 ? "x" : `x${i + 1}`;
    data.push({
      type: "scatter",
      mode: "lines",
      name: col,
      x,
      y: points.map((p) => {
        const v = p[col];
        if (typeof v === "boolean") return v ? 1 : 0;
        if (v == null || v === "") return null;
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? n : null;
      }),
      xaxis,
      yaxis: axis,
      line: { width: 1.4, color: rainbowColor(i) },
    });
    const domainH = 1 / n;
    const y0 = 1 - (i + 1) * domainH + 0.02;
    const y1 = 1 - i * domainH - 0.01;
    layout[axis === "y" ? "yaxis" : `yaxis${i + 1}`] = {
      title: col,
      domain: [Math.max(0, y0), Math.min(1, y1)],
      autorange: true,
      showgrid: true,
    };
    layout[xaxis === "x" ? "xaxis" : `xaxis${i + 1}`] = {
      anchor: axis,
      domain: [0, 1],
      showticklabels: i === n - 1,
      matches: i === 0 ? undefined : "x",
      autorange: true,
    };
  });

  return {
    data,
    layout,
    meta: {
      equipment_id: opts.equipmentId,
      point_count: points.length,
      provenance: "POST /api/analytics/inspect",
    },
  };
}
