/** Shared rule-tuning params (Vibe19 session_config ↔ OpenFDD Lab/Overview). */

export const RULE_PARAMS_STORAGE_KEY = "openfdd.ui.rule_params";
export const SESSION_SCHEMA = "openfdd_session_v1";

export type RuleParamMap = Record<string, Record<string, number>>;

export function loadLocalRuleParams(): RuleParamMap {
  try {
    const raw = localStorage.getItem(RULE_PARAMS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as RuleParamMap;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function saveLocalRuleParams(map: RuleParamMap): void {
  try {
    localStorage.setItem(RULE_PARAMS_STORAGE_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

/** Drop UI-only keys and coerce numeric param bags from session_config.params. */
export function numericParamsFromSession(
  params: Record<string, unknown> | null | undefined,
): RuleParamMap {
  if (!params || typeof params !== "object") return {};
  const out: RuleParamMap = {};
  for (const [ruleId, raw] of Object.entries(params)) {
    if (ruleId === "_ui" || !raw || typeof raw !== "object" || Array.isArray(raw)) {
      continue;
    }
    const bag: Record<string, number> = {};
    for (const [key, val] of Object.entries(raw as Record<string, unknown>)) {
      if (typeof val === "number" && Number.isFinite(val)) {
        bag[key] = val;
      } else if (typeof val === "string" && val.trim() !== "" && Number.isFinite(Number(val))) {
        bag[key] = Number(val);
      }
    }
    // Vibe19 / package session uses confirm_min; keep that unit for Lab + /api/fdd/run.
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

/** Deep-merge per-rule bags; overlay wins on shared keys. */
export function mergeRuleParams(base: RuleParamMap, overlay: RuleParamMap): RuleParamMap {
  const out: RuleParamMap = { ...base };
  for (const [ruleId, bag] of Object.entries(overlay)) {
    if (ruleId === "_ui") continue;
    out[ruleId] = { ...(out[ruleId] ?? {}), ...bag };
  }
  return out;
}

/**
 * Effective tuning for FDD runs: package/session_config first (Vibe19 parity),
 * then browser local overrides from Lab sliders.
 */
export function effectiveRunParams(
  sessionParams: Record<string, unknown> | null | undefined,
  localOverrides?: RuleParamMap,
): RuleParamMap {
  return mergeRuleParams(
    numericParamsFromSession(sessionParams),
    localOverrides ?? loadLocalRuleParams(),
  );
}
