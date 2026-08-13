import { describe, expect, it } from "vitest";
import type { FddRuleSummary } from "../api/fddApi";
import { visibleRulesForLab } from "./RuleTuningPanel";

function rule(rule_id: string): FddRuleSummary {
  return {
    rule_id,
    description: rule_id,
    equipment_kinds: ["ahu"],
    required_roles: [],
    optional_roles: [],
  };
}

describe("visibleRulesForLab", () => {
  it("sorts rule_id A–Z for Lab UX (not registry YAML order)", () => {
    const rules = [rule("VAV-1"), rule("FC1"), rule("PID-HUNT-1"), rule("AHU-FC2")];
    expect(visibleRulesForLab(rules, "(all)").map((r) => r.rule_id)).toEqual([
      "AHU-FC2",
      "FC1",
      "PID-HUNT-1",
      "VAV-1",
    ]);
  });

  it("filters by family then sorts", () => {
    const rules = [rule("SV-STALE"), rule("FC1"), rule("SV-FLATLINE")];
    expect(visibleRulesForLab(rules, "SV").map((r) => r.rule_id)).toEqual([
      "SV-FLATLINE",
      "SV-STALE",
    ]);
  });
});
