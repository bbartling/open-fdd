import { describe, expect, it } from "vitest";
import { displayRuleName, formatRuleLabel } from "./ruleDisplay";

describe("displayRuleName", () => {
  it("strips Acme prefix", () => {
    expect(displayRuleName("Acme zone temp flatline 1h")).toBe("zone temp flatline 1h");
  });

  it("does not rewrite RTU in persisted display helper", () => {
    expect(displayRuleName("RTU-01 fan run hours")).toBe("RTU-01 fan run hours");
  });

  it("strips parenthetical GL36 notes", () => {
    expect(displayRuleName("AHU SAT flatline 1h (GL36 plant request input)")).toBe("AHU SAT flatline 1h");
  });

  it("leaves generic names unchanged", () => {
    expect(displayRuleName("Zone temp out of bounds")).toBe("Zone temp out of bounds");
  });
});

describe("formatRuleLabel", () => {
  it("maps RTU to AHU for UI labels only", () => {
    expect(formatRuleLabel("RTU-01 fan run hours")).toBe("AHU-01 fan run hours");
  });
});
