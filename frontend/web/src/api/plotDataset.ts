/**
 * Plot dataset helpers — assemble React chart figures for Plotly.js.
 */

export type PlotlyTrace = {
  x: Array<string | number>;
  y: Array<number | null>;
  name: string;
  mode?: string;
  type?: string;
  marker?: Record<string, unknown>;
  line?: Record<string, unknown>;
  fill?: string;
  fillcolor?: string;
  opacity?: number;
  yaxis?: string;
  [key: string]: unknown;
};

export type PlotlyFigure = {
  data: PlotlyTrace[];
  layout?: Record<string, unknown> & {
    title?: string;
    xaxis?: { title?: string; [key: string]: unknown };
    yaxis?: { title?: string; [key: string]: unknown };
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

/** Bar chart from analytics envelope rows (generic). */
export function rowsToBarFigure(
  rows: Array<Record<string, unknown>>,
  opts: {
    xKey: string;
    yKeys: string[];
    title: string;
    provenance?: string;
  },
): PlotlyFigure {
  const x = rows.map((r) => String(r[opts.xKey] ?? ""));
  const traces: PlotlyTrace[] = opts.yKeys.map((key) => ({
    name: key,
    type: "bar",
    x,
    y: rows.map((r) => {
      const n = Number(r[key]);
      return Number.isFinite(n) ? n : null;
    }),
  }));
  return {
    data: traces,
    layout: {
      title: opts.title,
      barmode: "stack",
      showlegend: true,
      xaxis: { title: opts.xKey },
      yaxis: { title: "hours" },
    },
    meta: {
      point_count: rows.length,
      provenance: opts.provenance,
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
