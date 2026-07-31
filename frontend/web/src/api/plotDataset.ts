/**
 * Plot dataset helpers — assemble React chart figures from Rust series contracts.
 * No Plotly npm yet: PlotlyHost renders an SVG line chart from this shape.
 */

export type PlotlyTrace = {
  x: Array<string | number>;
  y: Array<number | null>;
  name: string;
  mode?: string;
  type?: string;
};

export type PlotlyFigure = {
  data: PlotlyTrace[];
  layout?: {
    title?: string;
    xaxis?: { title?: string };
    yaxis?: { title?: string };
    showlegend?: boolean;
  };
  meta?: {
    equipment_id?: string;
    rule_id?: string;
    roles?: string[];
    downsampled?: boolean;
    max_points?: number;
    point_count?: number;
    provenance?: string;
  };
};

export function seriesRowsToFigure(
  rows: Array<Record<string, unknown>>,
  opts: {
    equipmentId: string;
    ruleId: string;
    roles: string[];
    downsampled?: boolean;
    maxPoints?: number;
  },
): PlotlyFigure {
  const x = rows.map((r) => String(r.timestamp_utc ?? r.timestamp ?? ""));
  const traces: PlotlyTrace[] = opts.roles.map((role) => ({
    name: role,
    mode: "lines",
    type: "scatter",
    x,
    y: rows.map((r) => {
      const v = r[role];
      if (v == null || v === "") return null;
      const n = typeof v === "number" ? v : Number(v);
      return Number.isFinite(n) ? n : null;
    }),
  }));
  return {
    data: traces,
    layout: {
      title: `${opts.ruleId} · ${opts.equipmentId}`,
      xaxis: { title: "timestamp_utc" },
      yaxis: { title: "value" },
      showlegend: true,
    },
    meta: {
      equipment_id: opts.equipmentId,
      rule_id: opts.ruleId,
      roles: opts.roles,
      downsampled: opts.downsampled ?? false,
      max_points: opts.maxPoints,
      point_count: rows.length,
      provenance: "GET /api/fdd/series (DataFusion parquet)",
    },
  };
}

/** Detect missing segments (null/NaN runs) for parity notes. */
export function missingSegmentCount(trace: PlotlyTrace): number {
  let segments = 0;
  let inGap = false;
  for (const y of trace.y) {
    const missing = y == null || !Number.isFinite(y);
    if (missing && !inGap) {
      segments += 1;
      inGap = true;
    } else if (!missing) {
      inGap = false;
    }
  }
  return segments;
}
