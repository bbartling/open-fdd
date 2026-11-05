import { analyticsWindowFromSampling, ANALYTICS_WINDOW_MAX_DAYS } from "./window-policy.js";
import { parseTimestampMillis } from "./timestamp-adapter.js";

export { analyticsWindowFromSampling, ANALYTICS_WINDOW_MAX_DAYS };

export const ALL_EQUIP_HISTORY_CAP = 6;

export function dataEndMsFromHistory(history) {
  let end = null;
  for (const series of history?.values?.() ?? []) {
    for (const [t] of series || []) {
      const ms = parseTimestampMillis(t);
      if (ms != null && (end == null || ms > end)) end = ms;
    }
  }
  return end;
}

/** Filter loaded series to the last N hours ending at dataEndMs (not wall clock). */
export function filterSeriesByRangeHours(series, rangeHours, dataEndMs) {
  if (!series?.length || !rangeHours) return series || [];
  const end = dataEndMs ?? parseTimestampMillis(series[series.length - 1]?.[0]);
  if (end == null) return series;
  const cut = end - rangeHours * 3_600_000;
  return series.filter(([t]) => {
    const ms = parseTimestampMillis(t);
    return ms != null && ms >= cut && ms <= end + 60_000;
  });
}

export function chartDataState({ loading, error, history, cardPoints, assessable }) {
  if (loading) return { kind: "loading", message: "Loading historian window…" };
  if (error) return { kind: "error", message: error };
  if (assessable === false) return { kind: "no-assessable", message: "No assessable roles in this scope." };
  const endMs = dataEndMsFromHistory(history);
  if (!cardPoints?.length) return { kind: "empty", message: "No chart roles mapped for this equipment." };
  if (endMs == null) return { kind: "empty", message: "No samples in the selected historian window." };
  return { kind: "ready", message: "" };
}
