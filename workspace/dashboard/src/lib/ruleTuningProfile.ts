/** Phase 1 session tuning profile — in-memory / localStorage only (no server writes). */

export const SESSION_TUNING_STORAGE_KEY = "ofdd_fdd_session_tuning_v1";

export type SessionTuningStore = Record<string, Record<string, number>>;

export type RuleParameterDef = {
  key: string;
  label?: string;
  default?: number;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  control?: string;
  sql_placeholder?: string;
  /** Present only when the server resolved tuning layers successfully. */
  effective?: number;
};

export type DisplayValueSource = "session" | "effective" | "default" | "none";

export type DisplayValue = {
  value: number | null;
  source: DisplayValueSource;
};

export function clampParam(value: number, min?: number, max?: number): number {
  let v = value;
  if (typeof min === "number" && Number.isFinite(min)) v = Math.max(min, v);
  if (typeof max === "number" && Number.isFinite(max)) v = Math.min(max, v);
  return v;
}

export function readSessionTuningStore(
  storage: Pick<Storage, "getItem"> | null = typeof localStorage !== "undefined" ? localStorage : null,
): SessionTuningStore {
  if (!storage) return {};
  try {
    const raw = storage.getItem(SESSION_TUNING_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const out: SessionTuningStore = {};
    for (const [ruleId, params] of Object.entries(parsed as Record<string, unknown>)) {
      if (!ruleId || !params || typeof params !== "object" || Array.isArray(params)) continue;
      const row: Record<string, number> = {};
      for (const [key, val] of Object.entries(params as Record<string, unknown>)) {
        if (typeof val === "number" && Number.isFinite(val)) row[key] = val;
      }
      if (Object.keys(row).length) out[ruleId] = row;
    }
    return out;
  } catch {
    return {};
  }
}

export function writeSessionTuningStore(
  store: SessionTuningStore,
  storage: Pick<Storage, "setItem" | "removeItem"> | null = typeof localStorage !== "undefined"
    ? localStorage
    : null,
): void {
  if (!storage) return;
  if (Object.keys(store).length === 0) {
    storage.removeItem(SESSION_TUNING_STORAGE_KEY);
    return;
  }
  storage.setItem(SESSION_TUNING_STORAGE_KEY, JSON.stringify(store));
}

export function getSessionOverrides(store: SessionTuningStore, ruleId: string): Record<string, number> {
  return store[ruleId] ?? {};
}

export function setSessionParam(
  store: SessionTuningStore,
  ruleId: string,
  key: string,
  value: number,
): SessionTuningStore {
  const next = { ...store };
  next[ruleId] = { ...(next[ruleId] ?? {}), [key]: value };
  return next;
}

export function clearSessionRule(store: SessionTuningStore, ruleId: string): SessionTuningStore {
  if (!(ruleId in store)) return store;
  const next = { ...store };
  delete next[ruleId];
  return next;
}

/**
 * Resolve the control value for UI.
 * Never treats registry `default` as `effective` — that label is reserved for server-resolved values.
 */
export function resolveDisplayValue(
  param: RuleParameterDef,
  sessionOverride: number | undefined,
  tuningOk: boolean,
): DisplayValue {
  if (typeof sessionOverride === "number" && Number.isFinite(sessionOverride)) {
    return {
      value: clampParam(sessionOverride, param.min, param.max),
      source: "session",
    };
  }
  if (tuningOk && typeof param.effective === "number" && Number.isFinite(param.effective)) {
    return {
      value: clampParam(param.effective, param.min, param.max),
      source: "effective",
    };
  }
  if (typeof param.default === "number" && Number.isFinite(param.default)) {
    return {
      value: clampParam(param.default, param.min, param.max),
      source: "default",
    };
  }
  return { value: null, source: "none" };
}

/** Params payload path — keep canonical rule_id (no slugify). */
export function ruleParamsPath(ruleId: string): string {
  return `/api/fdd/rules/${encodeURIComponent(ruleId)}/params`;
}
