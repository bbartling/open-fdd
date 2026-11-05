/** FDD plot status buckets (archived fddPlotStatus.ts). */

export function fddStatusBucket(status) {
  const s = String(status ?? "").trim().toUpperCase();
  if (!s || s === "NOT_RUN" || s === "NOT RUN") return "Not run";
  if (s === "FAULT" || s === "WARNING" || s === "FAIL") return "FAULT";
  if (s === "PASS" || s === "OK") return "PASS";
  if (
    s.includes("SKIP") ||
    s.includes("N/A") ||
    s.includes("NOT_APPLICABLE") ||
    s.includes("NOT APPLICABLE")
  ) {
    return "SKIPPED";
  }
  return "SKIPPED";
}

export function preferredPlotRuleId(ruleIds, statusByRule) {
  const fault = ruleIds.find((id) => fddStatusBucket(statusByRule.get(id)) === "FAULT");
  if (fault) return fault;
  const ran = ruleIds.find((id) => {
    const raw = statusByRule.get(id);
    return raw != null && fddStatusBucket(raw) !== "Not run";
  });
  return ran ?? ruleIds[0] ?? "";
}

export function ruleApplicable(rule, mappedRoles) {
  const required = rule.required_roles || [];
  if (!required.length) return rule.applicability !== "typed";
  return required.every((r) => mappedRoles.has(r));
}

export function mappedRolesForEquip(mapping, equipmentId) {
  const roles = new Set();
  const eq = (mapping?.equipment || []).find((e) => e.equipment_id === equipmentId);
  for (const col of eq?.columns || []) {
    const role = col.role || col.column;
    if (role) roles.add(role);
  }
  return roles;
}
