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
    yAxisTitle?: string;
    barmode?: "stack" | "group" | "relative" | "overlay";
    sortBy?: string;
    sortDesc?: boolean;
    maxBars?: number;
  },
): PlotlyFigure {
  let sorted = [...rows];
  if (opts.sortBy) {
    const key = opts.sortBy;
    const desc = opts.sortDesc !== false;
    sorted.sort((a, b) => {
      const av = Number(a[key]);
      const bv = Number(b[key]);
      const an = Number.isFinite(av) ? av : 0;
      const bn = Number.isFinite(bv) ? bv : 0;
      return desc ? bn - an : an - bn;
    });
  }
  if (opts.maxBars != null && opts.maxBars > 0) {
    sorted = sorted.slice(0, opts.maxBars);
  }
  const x = sorted.map((r) => String(r[opts.xKey] ?? ""));
  const traces: PlotlyTrace[] = opts.yKeys.map((key) => ({
    name: key,
    type: "bar",
    x,
    y: sorted.map((r) => {
      const v = r[key];
      if (v == null || v === "") return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    }),
  }));
  return {
    data: traces,
    layout: {
      title: opts.title,
      barmode: opts.barmode ?? "group",
      showlegend: opts.yKeys.length > 1,
      xaxis: { title: opts.xKey, tickangle: -35, autorange: true },
      yaxis: { title: opts.yAxisTitle ?? "hours", autorange: true },
      margin: { t: 48, r: 24, b: 96, l: 56 },
      uirevision: `${opts.title}:${opts.xKey}:${fingerprintJson(sorted)}`,
    },
    meta: {
      point_count: sorted.length,
      provenance: opts.provenance,
    },
  };
}

/** Short FNV-1a of JSON so Plotly `uirevision` resets when values change. */
export function fingerprintJson(value: unknown): string {
  const s = JSON.stringify(value) ?? "";
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h.toString(36);
}

/** Filter runtime rows into plant families (vibe19 Air / Heating / Cooling). */
export function plantFamily(equipmentId: string): "air" | "heating" | "cooling" | "other" {
  const id = equipmentId.toUpperCase();
  if (
    id.includes("CHILLER") ||
    id.includes("_DX") ||
    id.startsWith("DX") ||
    id.includes("VRF") ||
    id.includes("RTU")
  ) {
    return "cooling";
  }
  if (id.includes("BOILER") || id.includes("HEATING") || id.includes("HW_PUMP")) {
    return "heating";
  }
  if (
    id.includes("AHU") ||
    id.includes("FAN") ||
    id.startsWith("SF_") ||
    id.startsWith("EF_") ||
    id.includes("SUPPLY_FAN") ||
    id.includes("EXHAUST_FAN")
  ) {
    return "air";
  }
  return "other";
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
