import { describe, expect, it } from "vitest";
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
});
