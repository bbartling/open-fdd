/** Session + local rule params (port of archive ruleParams.ts). */

export const RULES_UPDATED = "openfdd:rules-updated";

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

export function effectiveRunParams(sessionConfig) {
  return numericParamsFromSession(sessionConfig?.config?.params);
}

export function confirmMinForRule(sessionConfig, ruleId, ruleMeta) {
  const fromSession = effectiveRunParams(sessionConfig)[ruleId]?.confirm_min;
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
