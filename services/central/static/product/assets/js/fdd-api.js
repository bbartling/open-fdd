import { apiFetch } from "./api.js";
import { confirmMinForRule } from "./site-data.js";

export async function getFddRules() {
  const body = await apiFetch("/api/fdd/rules");
  if (body?.ok === false) throw new Error(body.error || "Failed to list rules");
  return body.rules ?? [];
}

export async function getFddResults(buildingId) {
  const q = new URLSearchParams({ building_id: buildingId });
  const body = await apiFetch(`/api/fdd/results?${q}`);
  if (body?.ok === false) throw new Error(body.error || "Failed to load results");
  return body.results ?? [];
}

export async function runFdd(buildingId, equipmentId, ruleIds, sessionConfig, rulesMeta) {
  const params = {};
  for (const ruleId of ruleIds) {
    const meta = rulesMeta.find((r) => r.rule_id === ruleId);
    const confirmMin = confirmMinForRule(sessionConfig, ruleId, meta);
    if (confirmMin != null) {
      params[ruleId] = { confirm_min: confirmMin };
    }
  }
  const body = {
    building_id: buildingId,
    equipment_id: equipmentId,
    rule_ids: ruleIds,
    mode: "interactive",
    params,
  };
  return apiFetch("/api/fdd/run", { method: "POST", body: JSON.stringify(body) });
}

export async function fetchFddPlotSeries(buildingId, equipmentId, ruleId, window) {
  const q = new URLSearchParams({
    building_id: buildingId,
    equipment_id: equipmentId,
    rule_id: ruleId,
    max_points: "1500",
  });
  if (window?.start) q.set("window_start", window.start);
  if (window?.end) q.set("window_end", window.end);
  const body = await apiFetch(`/api/fdd/plot?${q}`);
  if (body?.ok === false) throw new Error(body.error || "Plot series failed");
  return body;
}
