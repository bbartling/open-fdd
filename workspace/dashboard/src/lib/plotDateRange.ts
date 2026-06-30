/** Plot window presets — relative hours, YTD, or full historian span. */

export type PlotRangePreset =
  | "1h"
  | "6h"
  | "24h"
  | "3d"
  | "7d"
  | "30d"
  | "90d"
  | "365d"
  | "ytd"
  | "all"
  | "custom";

export type PlotRangeState =
  | { mode: "relative"; preset: Exclude<PlotRangePreset, "custom" | "all" | "ytd"> }
  | { mode: "ytd" }
  | { mode: "all" }
  | { mode: "custom"; afterUtc: string; beforeUtc: string };

export const PLOT_RANGE_PRESETS: {
  id: PlotRangePreset;
  label: string;
  hours?: number;
}[] = [
  { id: "1h", label: "1 hour", hours: 1 },
  { id: "6h", label: "6 hours", hours: 6 },
  { id: "24h", label: "24 hours", hours: 24 },
  { id: "3d", label: "3 days", hours: 72 },
  { id: "7d", label: "7 days", hours: 168 },
  { id: "30d", label: "30 days", hours: 720 },
  { id: "90d", label: "90 days", hours: 2160 },
  { id: "365d", label: "1 year", hours: 8760 },
  { id: "ytd", label: "Year to date" },
  { id: "all", label: "All data" },
  { id: "custom", label: "Custom range…" },
];

const DEFAULT_RANGE: PlotRangeState = { mode: "relative", preset: "24h" };

export function defaultPlotRange(): PlotRangeState {
  return DEFAULT_RANGE;
}

/** RFC3339 midnight UTC for Jan 1 of the current calendar year. */
export function yearToDateStartUtc(): string {
  const y = new Date().getUTCFullYear();
  return `${y}-01-01T00:00:00Z`;
}

export function utcNowIso(): string {
  return new Date().toISOString();
}

/** Trim ISO string for `<input type="datetime-local">` (local wall time). */
export function isoToDatetimeLocal(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Parse datetime-local value as UTC ISO (browser local → ISO). */
export function datetimeLocalToUtcIso(local: string): string {
  if (!local) return "";
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString();
}

export function plotRangeLabel(range: PlotRangeState): string {
  if (range.mode === "all") return "all data";
  if (range.mode === "ytd") return "YTD";
  if (range.mode === "custom") {
    const a = range.afterUtc.slice(0, 10);
    const b = range.beforeUtc.slice(0, 10);
    if (a && b) return `${a} → ${b}`;
    if (a) return `from ${a}`;
    if (b) return `until ${b}`;
    return "custom";
  }
  const preset = PLOT_RANGE_PRESETS.find((p) => p.id === range.preset);
  return preset?.label.toLowerCase() ?? `${range.preset}`;
}

/** Query params for `/api/timeseries/readings` and export. */
export function plotRangeQueryParams(range: PlotRangeState): Record<string, string> {
  if (range.mode === "all") return { all: "true" };
  if (range.mode === "ytd") {
    return { after_utc: yearToDateStartUtc(), before_utc: utcNowIso() };
  }
  if (range.mode === "custom") {
    const out: Record<string, string> = {};
    if (range.afterUtc) out.after_utc = range.afterUtc;
    if (range.beforeUtc) out.before_utc = range.beforeUtc;
    return out;
  }
  const preset = PLOT_RANGE_PRESETS.find((p) => p.id === range.preset);
  return { hours: String(preset?.hours ?? 24) };
}

export function plotRangeFromPreset(id: PlotRangePreset, bounds?: DataBounds): PlotRangeState {
  if (id === "custom") {
    return {
      mode: "custom",
      afterUtc: bounds?.earliest ?? "",
      beforeUtc: bounds?.latest ?? utcNowIso(),
    };
  }
  if (id === "all") return { mode: "all" };
  if (id === "ytd") return { mode: "ytd" };
  return { mode: "relative", preset: id };
}

export type DataBounds = {
  earliest?: string;
  latest?: string;
};

export function formatDataBoundsHint(bounds: DataBounds | null): string {
  if (!bounds?.earliest && !bounds?.latest) return "";
  const a = bounds.earliest?.slice(0, 10) ?? "…";
  const b = bounds.latest?.slice(0, 10) ?? "…";
  return `Historian span: ${a} → ${b}`;
}
