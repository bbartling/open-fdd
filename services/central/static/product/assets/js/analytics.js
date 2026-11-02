import { apiFetch } from "./api.js";

export function unwrapAnalytics(payload) {
  if (payload && typeof payload === "object" && payload.analytics) {
    return payload.analytics;
  }
  return payload;
}

export async function postAnalytics(path, body) {
  const raw = await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
  return unwrapAnalytics(raw);
}

export function isoRange(hoursBack) {
  const end = new Date();
  const start = new Date(end.getTime() - hoursBack * 3600 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

/**
 * Central AnalyticsRequest uses #[serde(flatten)] on query — fields must be top-level.
 * @param {string} buildingId
 * @param {string[]} equipmentIds
 * @param {number|{start?:string,end?:string}} windowOrHours
 */
export function analyticsBody(buildingId, equipmentIds, windowOrHours, maxPoints = 2500) {
  let start;
  let end;
  if (typeof windowOrHours === "object" && windowOrHours) {
    start = windowOrHours.start;
    end = windowOrHours.end;
  } else {
    const range = isoRange(Number(windowOrHours) || 24);
    start = range.start;
    end = range.end;
  }
  const body = {
    building_id: buildingId,
    equipment_ids: equipmentIds,
    max_points: maxPoints,
  };
  if (start) body.start = start;
  if (end) body.end = end;
  return body;
}

/** Wide inspect time series for one equipment (`analytics.points` rows). */
export async function fetchInspectSeries(buildingId, equipmentId, windowOrHours, columns) {
  const body = analyticsBody(buildingId, [equipmentId], windowOrHours);
  if (columns?.length) {
    body.series = { columns };
  }
  const env = await postAnalytics("/api/analytics/inspect", body);
  return env?.points || [];
}

export async function fetchBasVsWeb(buildingId, equipmentIds, windowOrHours) {
  const body = analyticsBody(buildingId, equipmentIds, windowOrHours, 1500);
  const env = await postAnalytics("/api/analytics/bas-vs-web-oat", body);
  return env?.rows || [];
}
