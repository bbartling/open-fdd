export type FddStatusFilter = "All" | "FAULT" | "PASS" | "SKIPPED" | "Not run";

/** vibe19 `filter_status_bucket`. */
export function fddStatusBucket(status: string | undefined | null): Exclude<
  FddStatusFilter,
  "All"
> {
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

export function preferredPlotRuleId(
  ruleIds: string[],
  statusByRule: Map<string, string>,
): string {
  const fault = ruleIds.find((id) => {
    const b = fddStatusBucket(statusByRule.get(id));
    return b === "FAULT";
  });
  if (fault) return fault;
  const ran = ruleIds.find((id) => {
    const raw = statusByRule.get(id);
    return raw != null && fddStatusBucket(raw) !== "Not run";
  });
  return ran ?? ruleIds[0] ?? "";
}
