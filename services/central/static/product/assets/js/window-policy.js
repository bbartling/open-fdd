/** Analytics window from package sampling span (matches archived overviewMetrics). */

export const ANALYTICS_WINDOW_MAX_DAYS = 180;

function datasetTimeSpan(frames) {
  let start = null;
  let end = null;
  for (const row of frames || []) {
    const s = row.sampling?.start ?? row.start ?? row.history_start;
    const e = row.sampling?.end ?? row.end ?? row.history_end;
    if (s && (!start || s < start)) start = s;
    if (e && (!end || e > end)) end = e;
  }
  return { start, end };
}

export function analyticsWindowFromSampling(equipmentFrames) {
  const span = datasetTimeSpan(equipmentFrames);
  if (!span.end) return {};
  const endMs = Date.parse(span.end);
  if (!Number.isFinite(endMs)) return {};
  const maxMs = ANALYTICS_WINDOW_MAX_DAYS * 86_400_000;
  let fromMs = span.start ? Date.parse(span.start) : endMs - maxMs;
  if (!Number.isFinite(fromMs)) fromMs = endMs - maxMs;
  if (endMs - fromMs > maxMs) fromMs = endMs - maxMs;
  const endPadMs = Math.min(endMs + 3_600_000, endMs + maxMs);
  return {
    start: new Date(fromMs).toISOString(),
    end: new Date(endPadMs).toISOString(),
  };
}
