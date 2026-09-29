import type { PlotlyFigure, PlotlyTrace } from "../api/plotDataset";

/** Operator choices for the per-plot series preview. Default is 10. */
export const SERIES_PREVIEW_ROW_OPTIONS = [10, 20, 50, 100, 500] as const;

export type SeriesPreviewLimit = (typeof SERIES_PREVIEW_ROW_OPTIONS)[number];

export const DEFAULT_SERIES_PREVIEW_ROWS: SeriesPreviewLimit = 10;

export type SeriesPreviewRow = Record<string, string>;

export type SeriesPreviewTable = {
  columns: string[];
  rows: SeriesPreviewRow[];
};

/**
 * Most recent samples from a figure already loaded for the plot.
 *
 * Walks that query window only (the arrays Plotly already holds). It does not
 * copy or refetch the historian. Rows are newest-first so the table is a
 * preview of what is live.
 */
export function recentSeriesPreview(
  figure: PlotlyFigure | null | undefined,
  limit: number,
): SeriesPreviewTable | null {
  if (!figure?.data?.length) return null;
  const traces = figure.data.filter(isSeriesTrace);
  if (!traces.length) return null;

  const n = coerceSeriesPreviewLimit(limit);
  const newest = newestTimestamps(traces, n);
  if (!newest.length) return null;

  const wanted = new Set(newest.map((stamp) => stamp.ms));
  const used = new Set<string>(["timestamp"]);
  const columns = ["timestamp"];
  const byTrace: Array<Map<number, string>> = [];
  for (const trace of traces) {
    const name = uniqueColumn(trace.name ?? "series", used);
    columns.push(name);
    byTrace.push(tailValues(trace, wanted));
  }

  const rows = newest.map((stamp) => {
    const row: SeriesPreviewRow = { timestamp: stamp.label };
    for (let i = 0; i < byTrace.length; i++) {
      row[columns[i + 1]] = byTrace[i].get(stamp.ms) ?? "";
    }
    return row;
  });
  return { columns, rows };
}

export function coerceSeriesPreviewLimit(value: number): SeriesPreviewLimit {
  for (const option of SERIES_PREVIEW_ROW_OPTIONS) {
    if (option === value) return option;
  }
  return DEFAULT_SERIES_PREVIEW_ROWS;
}

export function isSeriesPreviewLimit(value: number): value is SeriesPreviewLimit {
  return coerceSeriesPreviewLimit(value) === value;
}

function isSeriesTrace(trace: PlotlyTrace): boolean {
  const type = String(trace.type ?? "scatter");
  if (type !== "scatter" && type !== "scattergl") return false;
  const xs = trace.x ?? [];
  for (let i = 0; i < xs.length; i++) {
    if (timestampMillis(xs[i]) != null) return true;
  }
  return false;
}

/** Unique clocks in the loaded window, newest first, capped at `limit`. */
function newestTimestamps(
  traces: PlotlyTrace[],
  limit: number,
): Array<{ ms: number; label: string }> {
  const byMs = new Map<number, string>();
  for (const trace of traces) {
    const xs = trace.x ?? [];
    for (let i = 0; i < xs.length; i++) {
      const raw = xs[i];
      const ms = timestampMillis(raw);
      if (ms == null || raw == null) continue;
      // Later samples in the loaded window win when two strings share a clock.
      byMs.set(ms, String(raw));
    }
  }
  if (!byMs.size) return [];
  const ordered = [...byMs.entries()].sort((a, b) => a[0] - b[0]);
  return ordered.slice(-limit).reverse().map(([ms, label]) => ({ ms, label }));
}

/** Index only the tail clocks — not a second copy of the plot window. */
function tailValues(trace: PlotlyTrace, wanted: Set<number>): Map<number, string> {
  const out = new Map<number, string>();
  const xs = trace.x ?? [];
  const ys = trace.y ?? [];
  for (let i = 0; i < xs.length; i++) {
    const ms = timestampMillis(xs[i]);
    if (ms == null || !wanted.has(ms)) continue;
    const y = ys[i];
    out.set(ms, y == null || y === "" ? "" : String(y));
  }
  return out;
}

function uniqueColumn(name: string, used: Set<string>): string {
  const base = name.trim() || "series";
  if (!used.has(base)) {
    used.add(base);
    return base;
  }
  let i = 2;
  let next = `${base} (${i})`;
  while (used.has(next)) {
    i += 1;
    next = `${base} (${i})`;
  }
  used.add(next);
  return next;
}

function timestampMillis(value: unknown): number | null {
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value < 1e11 || value > 1e14) return null;
    return value;
  }
  if (typeof value !== "string") return null;
  const s = value.trim();
  if (/^\d{4}-\d{2}-\d{2}(?:[T ]|$)/.test(s)) {
    const ms = Date.parse(s);
    return Number.isFinite(ms) ? ms : null;
  }
  if (/^\d{13}$/.test(s)) {
    const ms = Number(s);
    return Number.isFinite(ms) ? ms : null;
  }
  return null;
}
