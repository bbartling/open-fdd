import { describe, expect, it } from "vitest";
import type { FddRuleSummary } from "../api/fddApi";
import { defaultLabFamily, visibleRulesForLab } from "./RuleTuningPanel";

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

  it("natural-sorts FC1→FC2→…→FC10 (registry YAML order must not win)", () => {
    const rules = [
      rule("FC10"),
      rule("FC2"),
      rule("FC1"),
      rule("FC9"),
      rule("ECON-1"),
    ];
    expect(visibleRulesForLab(rules, "(all)").map((r) => r.rule_id)).toEqual([
      "ECON-1",
      "FC1",
      "FC2",
      "FC9",
      "FC10",
    ]);
  });

  it("filters by family then natural-sorts", () => {
    const rules = [rule("SV-STALE"), rule("FC1"), rule("SV-FLATLINE"), rule("SV-10")];
    expect(visibleRulesForLab(rules, "SV").map((r) => r.rule_id)).toEqual([
      "SV-10",
      "SV-FLATLINE",
      "SV-STALE",
    ]);
  });
});

describe("defaultLabFamily", () => {
  it("prefers FC over dumping (all) when present", () => {
    expect(
      defaultLabFamily([rule("VAV-1"), rule("FC1"), rule("AHU-FC2")]),
    ).toBe("FC");
  });

  it("falls back along preference then first sorted family", () => {
    expect(defaultLabFamily([rule("VAV-1"), rule("SV-STALE")])).toBe("VAV");
    expect(defaultLabFamily([rule("SV-STALE"), rule("PID-HUNT-1")])).toBe(
      "SV",
    );
    expect(defaultLabFamily([rule("PID-HUNT-1"), rule("UTIL-MONTHLY")])).toBe(
      "PID",
    );
  });

  it("groups FC1/FC10 under family FC for Lab category", () => {
    expect(
      visibleRulesForLab(
        [rule("FC10"), rule("VAV-1"), rule("FC2")],
        "FC",
      ).map((r) => r.rule_id),
    ).toEqual(["FC2", "FC10"]);
  });
});
