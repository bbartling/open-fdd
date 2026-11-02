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

export function analyticsBody(buildingId, equipmentIds, hoursBack, maxPoints = 2500) {
  const { start, end } = isoRange(hoursBack);
  return {
    query: {
      building_id: buildingId,
      equipment_ids: equipmentIds,
      start,
      end,
      max_points: maxPoints,
    },
  };
}

/** Wide inspect time series for one equipment (`analytics.points` rows). */
export async function fetchInspectSeries(buildingId, equipmentId, hoursBack, columns) {
  const body = analyticsBody(buildingId, [equipmentId], hoursBack);
  if (columns?.length) {
    body.series = { columns };
  }
  const env = await postAnalytics("/api/analytics/inspect", body);
  return env?.points || [];
}

export async function fetchBasVsWeb(buildingId, equipmentIds, hoursBack) {
  const body = analyticsBody(buildingId, equipmentIds, hoursBack, 1500);
  const env = await postAnalytics("/api/analytics/bas-vs-web-oat", body);
  return env?.rows || [];
}
