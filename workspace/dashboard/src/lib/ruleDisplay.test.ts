import { describe, expect, it } from "vitest";
import { displayRuleName } from "./ruleDisplay";

describe("displayRuleName", () => {
  it("strips Acme prefix", () => {
    expect(displayRuleName("Acme zone temp flatline 1h")).toBe("zone temp flatline 1h");
  });

  it("strips parenthetical GL36 notes", () => {
    expect(displayRuleName("AHU SAT flatline 1h (GL36 plant request input)")).toBe("AHU SAT flatline 1h");
  });

  it("leaves generic names unchanged", () => {
    expect(displayRuleName("Zone temp out of bounds")).toBe("Zone temp out of bounds");
  });
});
