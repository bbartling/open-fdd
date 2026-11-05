import { apiFetch } from "./api.js";
import { effectiveRunParams, confirmMinForRule } from "./rule-params.js";

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

export async function fetchSessionConfig(buildingId) {
  return apiFetch(`/api/fdd/session-config?building_id=${encodeURIComponent(buildingId)}`).catch(
    () => null,
  );
}

export async function getFddRuleParams(ruleId) {
  const body = await apiFetch(`/api/fdd/rules/${encodeURIComponent(ruleId)}/params`);
  if (body?.ok === false) throw new Error(body.error || "Failed to load rule params");
  return body.params ?? {};
}

export async function putSessionConfig(buildingId, config) {
  const payload = { building_id: buildingId, config };
  const body = await apiFetch("/api/fdd/session-config", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (body?.ok === false) throw new Error(body.error || "Failed to save session config");
  return body;
}

export async function runFdd(buildingId, equipmentId, ruleIds, sessionConfig, rulesMeta) {
  const sessionParams = effectiveRunParams(sessionConfig, buildingId);
  const params = {};
  for (const ruleId of ruleIds) {
    const meta = rulesMeta.find((r) => r.rule_id === ruleId);
    const fromBag = sessionParams[ruleId]?.confirm_min;
    const confirmMin =
      fromBag != null && Number.isFinite(fromBag)
        ? fromBag
        : confirmMinForRule(sessionConfig, ruleId, meta, buildingId);
    if (confirmMin != null) {
      params[ruleId] = { ...sessionParams[ruleId], confirm_min: confirmMin };
    } else if (sessionParams[ruleId]) {
      params[ruleId] = { ...sessionParams[ruleId] };
    }
  }
  const body = {
    building_id: buildingId,
    equipment_id: equipmentId,
    rule_ids: ruleIds,
    mode: "registry",
    params,
  };
  return apiFetch("/api/fdd/run", { method: "POST", body: JSON.stringify(body) });
}

/** After Lab rule update: refetch session_config and re-run with confirm_min. */
export async function rerunFddAfterRuleUpdate(buildingId, equipmentId, ruleId, rulesMeta) {
  const sessionConfig = await fetchSessionConfig(buildingId);
  return runFdd(buildingId, equipmentId, [ruleId], sessionConfig, rulesMeta);
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
