import { apiFetch } from "./api";

export type RuleBindings = {
  point_ids?: string[];
  /** Points bound explicitly (not via equipment/brick mass-bind). */
  direct_point_ids?: string[];
  equipment_ids?: string[];
  brick_types?: string[];
};

export type SavedRule = {
  id: string;
  name: string;
  severity?: string;
  enabled?: boolean;
  bindings?: RuleBindings;
};

export type BindKind = "point" | "equipment" | "brick_type";

export type BindTarget = {
  kind: BindKind;
  id: string;
  label: string;
  pointIds?: string[];
};

export function normalizeBindings(raw?: RuleBindings): Required<RuleBindings> {
  const point_ids = [...(raw?.point_ids ?? [])];
  const direct =
    raw?.direct_point_ids !== undefined
      ? [...raw.direct_point_ids]
      : [...point_ids];
  return {
    point_ids,
    direct_point_ids: direct,
    equipment_ids: [...(raw?.equipment_ids ?? [])],
    brick_types: [...(raw?.brick_types ?? [])],
  };
}

export function ruleBindsTarget(rule: SavedRule, target: BindTarget): boolean {
  const b = normalizeBindings(rule.bindings);
  if (target.kind === "point") return b.point_ids.includes(target.id);
  if (target.kind === "equipment") return b.equipment_ids.includes(target.id);
  return b.brick_types.includes(target.id);
}

export function rulesBoundToTarget(rules: SavedRule[], target: BindTarget): SavedRule[] {
  return rules.filter((r) => r.enabled !== false && ruleBindsTarget(r, target));
}

export function mergeBind(
  prev: RuleBindings | undefined,
  kind: BindKind,
  id: string,
  extraPointIds: string[] = [],
): RuleBindings {
  const next = normalizeBindings(prev);
  if (kind === "point") {
    if (!next.point_ids.includes(id)) next.point_ids.push(id);
    if (!next.direct_point_ids.includes(id)) next.direct_point_ids.push(id);
  }
  if (kind === "equipment" && !next.equipment_ids.includes(id)) next.equipment_ids.push(id);
  if (kind === "brick_type" && !next.brick_types.includes(id)) next.brick_types.push(id);
  for (const pid of extraPointIds) {
    if (pid && !next.point_ids.includes(pid)) next.point_ids.push(pid);
  }
  return next;
}

export function unbindTarget(prev: RuleBindings | undefined, target: BindTarget): RuleBindings {
  const next = normalizeBindings(prev);
  const direct = new Set(next.direct_point_ids);
  if (target.kind === "point") {
    next.point_ids = next.point_ids.filter((x) => x !== target.id);
    next.direct_point_ids = next.direct_point_ids.filter((x) => x !== target.id);
  } else if (target.kind === "equipment") {
    next.equipment_ids = next.equipment_ids.filter((x) => x !== target.id);
    const drop = new Set(target.pointIds ?? []);
    if (drop.size) {
      next.point_ids = next.point_ids.filter((x) => !drop.has(x) || direct.has(x));
    }
  } else {
    next.brick_types = next.brick_types.filter((x) => x !== target.id);
    const drop = new Set(target.pointIds ?? []);
    if (drop.size) {
      next.point_ids = next.point_ids.filter((x) => !drop.has(x) || direct.has(x));
    }
  }
  return next;
}

export async function fetchSavedRules(): Promise<SavedRule[]> {
  const res = await apiFetch<{ rules: SavedRule[] }>("/api/rules/saved");
  return (res.rules ?? []).filter((r) => r.enabled !== false);
}

export async function persistRuleBindings(rule: SavedRule, bindings: RuleBindings): Promise<SavedRule> {
  const norm = normalizeBindings(bindings);
  const body = {
    rule_id: rule.id,
    point_ids: norm.point_ids,
    direct_point_ids: norm.direct_point_ids,
    equipment_ids: norm.equipment_ids,
    brick_types: norm.brick_types,
  };
  const res = await apiFetch<{ rule: SavedRule }>("/api/rules/bindings", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return res.rule;
}

export async function bindRuleToTarget(
  rule: SavedRule,
  kind: BindKind,
  id: string,
  extraPointIds: string[] = [],
): Promise<SavedRule> {
  const bindings = mergeBind(rule.bindings, kind, id, extraPointIds);
  return persistRuleBindings(rule, bindings);
}

/** Bind many points and optionally the parent equipment in one write. */
export async function bindRuleToEquipmentPoints(
  rule: SavedRule,
  equipmentId: string,
  pointIds: string[],
): Promise<SavedRule> {
  let bindings = normalizeBindings(rule.bindings);
  for (const pid of pointIds) {
    if (pid && !bindings.point_ids.includes(pid)) bindings.point_ids.push(pid);
  }
  if (equipmentId && !bindings.equipment_ids.includes(equipmentId)) {
    bindings.equipment_ids.push(equipmentId);
  }
  return persistRuleBindings(rule, bindings);
}

export async function unbindRuleFromTarget(rule: SavedRule, target: BindTarget): Promise<SavedRule> {
  const bindings = unbindTarget(rule.bindings, target);
  return persistRuleBindings(rule, bindings);
}

export async function unbindAllRulesFromTarget(
  rules: SavedRule[],
  target: BindTarget,
): Promise<void> {
  const bound = rulesBoundToTarget(rules, target);
  await Promise.all(bound.map((r) => unbindRuleFromTarget(r, target)));
}

export type AssignmentRow = {
  ruleId: string;
  ruleName: string;
  severity: string;
  pointIds: string[];
  equipmentIds: string[];
  brickTypes: string[];
  pointCount: number;
  equipmentCount: number;
  brickCount: number;
};

export function buildAssignmentRows(rules: SavedRule[]): AssignmentRow[] {
  return rules
    .map((r) => {
      const b = normalizeBindings(r.bindings);
      return {
        ruleId: r.id,
        ruleName: r.name,
        severity: r.severity || "warning",
        pointIds: b.point_ids,
        equipmentIds: b.equipment_ids,
        brickTypes: b.brick_types,
        pointCount: b.point_ids.length,
        equipmentCount: b.equipment_ids.length,
        brickCount: b.brick_types.length,
      };
    })
    .filter((row) => row.pointCount + row.equipmentCount + row.brickCount > 0)
    .sort((a, b) => a.ruleName.localeCompare(b.ruleName));
}
