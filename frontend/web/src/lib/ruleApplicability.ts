import type { FddRuleSummary } from "../api/fddApi";
import { canonicalEquipmentKind } from "./overviewMetrics";

export type CatalogApplicability = "all" | "typed" | "unknown";

export function catalogApplicability(rule: FddRuleSummary): CatalogApplicability {
  if (rule.applicability === "unknown") return "unknown";
  if (rule.applicability === "all" && Array.isArray(rule.equipment_kinds)) {
    return "all";
  }
  if (
    rule.applicability === "typed" &&
    Array.isArray(rule.equipment_kinds) &&
    Array.isArray(rule.required_roles)
  ) {
    return "typed";
  }
  if (!Array.isArray(rule.equipment_kinds) || !Array.isArray(rule.required_roles)) {
    return "unknown";
  }
  return rule.equipment_kinds.length === 0 ? "all" : "typed";
}

export interface RuleEligibility {
  eligible: boolean;
  reason: "applicability unknown" | "equipment type" | "missing-roles" | "roles not loaded" | null;
  missing: string[];
}

/** Type and required-role gate. Unknown metadata is ineligible. */
export function ruleEligibility(
  rule: FddRuleSummary,
  equipmentType: string | null | undefined,
  mappedRoles: ReadonlySet<string> | null,
): RuleEligibility {
  const applicability = catalogApplicability(rule);
  if (applicability === "unknown") {
    return { eligible: false, reason: "applicability unknown", missing: [] };
  }
  if (mappedRoles == null) {
    return { eligible: false, reason: "roles not loaded", missing: [] };
  }
  if (applicability === "typed") {
    const kind = canonicalEquipmentKind(equipmentType);
    const kinds = rule.equipment_kinds ?? [];
    const matches =
      kind != null && kinds.some((item) => canonicalEquipmentKind(item) === kind);
    if (!matches) {
      return { eligible: false, reason: "equipment type", missing: [] };
    }
  }
  const required = (rule.required_roles ?? []).filter((role) => Boolean(role));
  const missing = required.filter((role) => !mappedRoles.has(role));
  if (missing.length) {
    return { eligible: false, reason: "missing-roles", missing };
  }
  return { eligible: true, reason: null, missing: [] };
}

export function ruleEligibilityNotice(
  rules: readonly FddRuleSummary[],
  equipmentType: string | null | undefined,
  mappedRoles: ReadonlySet<string> | null,
  skipRuleIds?: ReadonlySet<string>,
): string | null {
  if (mappedRoles == null) return null;
  const gaps: string[] = [];
  let unknown = 0;
  for (const rule of rules) {
    if (skipRuleIds?.has(rule.rule_id)) continue;
    const result = ruleEligibility(rule, equipmentType, mappedRoles);
    if (result.eligible || result.reason === "equipment type") continue;
    if (result.reason === "applicability unknown") {
      unknown += 1;
      continue;
    }
    if (result.reason === "missing-roles") {
      gaps.push(
        `${rule.rule_id} is not eligible: missing mapped roles ${result.missing.join(", ")}.`,
      );
    }
  }
  const parts = [...gaps];
  if (unknown > 0) {
    parts.push(
      unknown === 1
        ? "1 rule has unknown applicability and is not offered."
        : `${unknown} rules have unknown applicability and are not offered.`,
    );
  }
  return parts.length ? parts.join(" ") : null;
}
