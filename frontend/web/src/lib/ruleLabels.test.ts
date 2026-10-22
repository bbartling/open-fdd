import { describe, expect, it } from "vitest";
import { healthColumnHeader } from "./cookbookRuleCatalog";
import {
  mergeRuleDescriptionsFromApi,
  ruleLabelPlotTitle,
  ruleLabelStandard,
  ruleLabelShort,
} from "./ruleLabels";

describe("ruleLabels", () => {
  it("uses seeded FC1 description before API merge", () => {
    expect(ruleLabelStandard("FC1")).toBe("FC1 — Duct static below SP at full fan");
  });

  it("merges API descriptions over seeds", () => {
    mergeRuleDescriptionsFromApi([
      { rule_id: "FC1", description: "Custom FC1 label" },
    ]);
    expect(ruleLabelStandard("FC1")).toBe("FC1 — Custom FC1 label");
    mergeRuleDescriptionsFromApi([
      { rule_id: "FC1", description: "Duct static below SP at full fan" },
    ]);
  });

  it("plot title includes equipment", () => {
    expect(ruleLabelPlotTitle("FC1", "AHU_1")).toBe(
      "FC1 — Duct static below SP at full fan · AHU_1",
    );
  });

  it("short label is rule id", () => {
    expect(ruleLabelShort("FC1")).toBe("FC1");
  });

  it("labels FC5, FC6, and FC8 from the registry, including required roles", () => {
    expect(
      ruleLabelStandard("FC5", "SAT cold when heating commanded (GL36 D)"),
    ).toBe("FC5 — SAT cold when heating commanded (GL36 D)");
    expect(ruleLabelStandard("FC6", "Estimated OA fraction mismatch")).toBe(
      "FC6 — Estimated OA fraction mismatch",
    );
    expect(ruleLabelStandard("FC8", "SAT vs MAT while economizing")).toBe(
      "FC8 — SAT vs MAT while economizing",
    );
    expect(ruleLabelStandard("FC5")).toBe(
      "FC5 — SAT cold when heating commanded (GL36 D)",
    );
    expect(ruleLabelStandard("FC6")).toBe("FC6 — Estimated OA fraction mismatch");
    expect(ruleLabelStandard("FC8")).toBe("FC8 — SAT vs MAT while economizing");
    expect(healthColumnHeader("FC5")).toBe(
      "FC5 — SAT cold when heating commanded (GL36 D)",
    );

    mergeRuleDescriptionsFromApi([
      {
        rule_id: "FC5",
        description: "SAT cold when heating commanded (GL36 D)",
        required_roles: ["sat", "mat", "htg_valve_pct", "fan_cmd"],
      },
      {
        rule_id: "FC6",
        description: "Estimated OA fraction mismatch",
        required_roles: ["mat", "rat", "oa_t", "fan_cmd", "vav_total_flow"],
      },
      {
        rule_id: "FC8",
        description: "SAT vs MAT while economizing",
        required_roles: ["sat", "mat", "oa_damper_pct", "clg_valve_pct"],
      },
    ]);
    expect(healthColumnHeader("FC5")).toBe(
      "FC5 — SAT cold when heating commanded (GL36 D) · sat, mat, htg_valve_pct, fan_cmd",
    );
    expect(healthColumnHeader("FC6")).toContain("vav_total_flow");
    expect(healthColumnHeader("FC8")).toContain("oa_damper_pct");
    expect(healthColumnHeader("FC5")).not.toMatch(/hotWater|Boiler/);
    expect(healthColumnHeader("FC6")).not.toMatch(/hotWater|Boiler/);
    expect(healthColumnHeader("FC8")).not.toMatch(/hotWater|Boiler/);
  });
});
