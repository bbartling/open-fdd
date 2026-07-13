/** Canonical FDD six-status contract — keep in sync with Rust `fdd_rules::RuleStatus`. */
export const RULE_STATUSES = [
  "PASS",
  "FAULT",
  "SKIPPED_MISSING_ROLES",
  "SKIPPED_EQUIPMENT_OFF",
  "NOT_APPLICABLE_EQUIPMENT_TYPE",
  "ERROR",
] as const;

export type RuleStatus = (typeof RULE_STATUSES)[number];

export function isRuleStatus(v: string): v is RuleStatus {
  return (RULE_STATUSES as readonly string[]).includes(v);
}
