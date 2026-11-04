/** Session + local rule params (port of archive ruleParams.ts). */

export const RULES_UPDATED = "openfdd:rules-updated";
export const RULE_PARAMS_STORAGE_KEY = "openfdd.ui.rule_params";
export const OPERATIONAL_GATE_KEY = "require_operational_gate";
const VALUE_EPS = 1e-9;

function scopedStorageKey(buildingId) {
  const bid = (buildingId ?? "").trim();
  if (!bid) return RULE_PARAMS_STORAGE_KEY;
  return `${RULE_PARAMS_STORAGE_KEY}.building=${encodeURIComponent(bid)}`;
}

export function loadLocalRuleParams(buildingId) {
  try {
    const raw = localStorage.getItem(scopedStorageKey(buildingId));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function saveLocalRuleParams(map, buildingId) {
  try {
    localStorage.setItem(scopedStorageKey(buildingId), JSON.stringify(map));
  } catch {
    /* ignore quota */
  }
}

export function mergeRuleParams(base, overlay) {
  const out = { ...base };
  for (const [ruleId, bag] of Object.entries(overlay || {})) {
    if (ruleId === "_ui" || !bag || typeof bag !== "object") continue;
    out[ruleId] = { ...(out[ruleId] ?? {}), ...bag };
  }
  return out;
}

export function ruleNeedsRun(entries, draft, applied, opsGate) {
  return entries.some(([key, def]) => {
    const draftValue =
      key === OPERATIONAL_GATE_KEY ? (opsGate ? 1 : 0) : (draft[key] ?? def.default);
    const appliedValue = applied[key] ?? def.default;
    return Math.abs(draftValue - appliedValue) > VALUE_EPS;
  });
}

export function stampOperationalGate(params, ruleId, declaresGate, proof) {
  if (!declaresGate) return params;
  return {
    ...params,
    [ruleId]: {
      ...(params[ruleId] ?? {}),
      [OPERATIONAL_GATE_KEY]: proof ? 1 : 0,
    },
  };
}

export function numericParamsFromSession(params) {
  if (!params || typeof params !== "object") return {};
  const out = {};
  for (const [ruleId, raw] of Object.entries(params)) {
    if (ruleId === "_ui" || !raw || typeof raw !== "object" || Array.isArray(raw)) continue;
    const bag = {};
    for (const [key, val] of Object.entries(raw)) {
      if (typeof val === "number" && Number.isFinite(val)) {
        bag[key] = val;
      } else if (typeof val === "string" && val.trim() !== "" && Number.isFinite(Number(val))) {
        bag[key] = Number(val);
      }
    }
    if (
      bag.confirm_min == null &&
      typeof bag.confirm_seconds === "number" &&
      Number.isFinite(bag.confirm_seconds)
    ) {
      bag.confirm_min = bag.confirm_seconds / 60;
      delete bag.confirm_seconds;
    }
    if (Object.keys(bag).length) out[ruleId] = bag;
  }
  return out;
}

export function effectiveRunParams(sessionConfig, buildingId) {
  return mergeRuleParams(
    numericParamsFromSession(sessionConfig?.config?.params),
    loadLocalRuleParams(buildingId),
  );
}

export function confirmMinForRule(sessionConfig, ruleId, ruleMeta, buildingId) {
  const fromSession = effectiveRunParams(sessionConfig, buildingId)[ruleId]?.confirm_min;
  if (fromSession != null && Number.isFinite(fromSession)) return fromSession;
  if (ruleMeta?.confirm_min != null && Number.isFinite(Number(ruleMeta.confirm_min))) {
    return Number(ruleMeta.confirm_min);
  }
  if (ruleMeta?.confirm_seconds != null && Number.isFinite(Number(ruleMeta.confirm_seconds))) {
    return Number(ruleMeta.confirm_seconds) / 60;
  }
  return undefined;
}

export function notifyRulesUpdated() {
  window.dispatchEvent(new CustomEvent(RULES_UPDATED));
}
