import { ModelPayload, parseImportPayload } from "./modelImport";

export type FddRuleBinding = {
  id: string;
  name?: string;
  enabled?: boolean;
  bindings?: {
    point_ids?: string[];
    direct_point_ids?: string[];
    equipment_ids?: string[];
    brick_types?: string[];
  };
};

export type CommissioningPayload = ModelPayload & {
  version?: number;
  fdd_rules?: FddRuleBinding[];
  points: Array<Record<string, unknown> & { fdd_rule_ids?: string[] }>;
};

export function parseCommissioningPayload(input: string): CommissioningPayload {
  const raw = String(input || "").trim();
  if (!raw) {
    throw new Error("JSON input is empty.");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    const modelOnly = parseImportPayload(input);
    return { ...modelOnly, fdd_rules: [] };
  }
  if (parsed && typeof parsed === "object") {
    const obj = parsed as Record<string, unknown>;
    if (obj.import_ready_json && typeof obj.import_ready_json === "object") {
      parsed = obj.import_ready_json;
    } else if (obj.commissioning_bundle && typeof obj.commissioning_bundle === "object") {
      parsed = obj.commissioning_bundle;
    }
  }
  const base = parseImportPayload(JSON.stringify(parsed));
  const obj = parsed as Record<string, unknown>;
  const fdd_rules = Array.isArray(obj.fdd_rules) ? (obj.fdd_rules as FddRuleBinding[]) : [];
  return { ...base, version: typeof obj.version === "number" ? obj.version : 1, fdd_rules };
}

export function assignmentSummary(payload: CommissioningPayload): {
  ruleCount: number;
  boundPointCount: number;
  pointsWithRules: number;
} {
  const pointIds = new Set<string>();
  let pointsWithRules = 0;
  for (const pt of payload.points || []) {
    const ids = pt.fdd_rule_ids;
    if (Array.isArray(ids) && ids.length) {
      pointsWithRules += 1;
      pointIds.add(String(pt.id || ""));
    }
  }
  for (const rule of payload.fdd_rules || []) {
    for (const pid of rule.bindings?.point_ids || []) {
      if (pid) pointIds.add(String(pid));
    }
  }
  return {
    ruleCount: payload.fdd_rules?.length ?? 0,
    boundPointCount: pointIds.size,
    pointsWithRules,
  };
}
