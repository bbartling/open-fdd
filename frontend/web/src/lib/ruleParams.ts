/** Shared rule-tuning params (Vibe19 session_config ↔ OpenFDD Lab/Overview). */

export const RULE_PARAMS_STORAGE_KEY = "openfdd.ui.rule_params";
/** Set after a one-shot copy of the legacy global bag into a building-scoped key. */
export const RULE_PARAMS_LEGACY_MIGRATED_KEY = "openfdd.ui.rule_params.__legacy_migrated";
export const SESSION_SCHEMA = "openfdd_session_v1";

export type RuleParamMap = Record<string, Record<string, number>>;

function scopedKey(buildingId?: string | null): string {
  const bid = (buildingId ?? "").trim();
  if (!bid) return RULE_PARAMS_STORAGE_KEY;
  return `${RULE_PARAMS_STORAGE_KEY}.building=${encodeURIComponent(bid)}`;
}

/**
 * Migrate legacy global key into the first scoped building bag once.
 * Removes the legacy key so later buildings do not inherit the same overrides.
 */
function migrateLegacyIfNeeded(buildingId?: string | null): void {
  const bid = (buildingId ?? "").trim();
  if (!bid) return;
  try {
    if (localStorage.getItem(RULE_PARAMS_LEGACY_MIGRATED_KEY) === "1") return;
    const legacy = localStorage.getItem(RULE_PARAMS_STORAGE_KEY);
    if (!legacy) {
      localStorage.setItem(RULE_PARAMS_LEGACY_MIGRATED_KEY, "1");
      return;
    }
    const scoped = scopedKey(bid);
    if (!localStorage.getItem(scoped)) {
      localStorage.setItem(scoped, legacy);
    }
    localStorage.removeItem(RULE_PARAMS_STORAGE_KEY);
    localStorage.setItem(RULE_PARAMS_LEGACY_MIGRATED_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function loadLocalRuleParams(buildingId?: string | null): RuleParamMap {
  migrateLegacyIfNeeded(buildingId);
  try {
    const raw = localStorage.getItem(scopedKey(buildingId));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as RuleParamMap;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function saveLocalRuleParams(
  map: RuleParamMap,
  buildingId?: string | null,
): void {
  try {
    localStorage.setItem(scopedKey(buildingId), JSON.stringify(map));
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
 * then browser local overrides from Lab sliders (scoped by building when set).
 */
export function effectiveRunParams(
  sessionParams: Record<string, unknown> | null | undefined,
  localOverrides?: RuleParamMap,
  buildingId?: string | null,
): RuleParamMap {
  return mergeRuleParams(
    numericParamsFromSession(sessionParams),
    localOverrides ?? loadLocalRuleParams(buildingId),
  );
}
