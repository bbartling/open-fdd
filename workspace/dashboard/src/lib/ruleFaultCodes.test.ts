import { describe, expect, it } from "vitest";
import { faultCodesFromRule, primaryFaultCode } from "./ruleFaultCodes";

describe("faultCodesFromRule", () => {
  it("prefers fault_codes array", () => {
    expect(faultCodesFromRule({ fault_codes: ["VAV-C", "AHU-B"], fault_code: "BLD-A" })).toEqual([
      "VAV-C",
      "AHU-B",
    ]);
  });

  it("falls back to fault_code", () => {
    expect(faultCodesFromRule({ fault_code: "dc-c" })).toEqual(["DC-C"]);
  });

  it("returns empty when unset", () => {
    expect(faultCodesFromRule({})).toEqual([]);
  });
});

describe("primaryFaultCode", () => {
  it("returns first code", () => {
    expect(primaryFaultCode(["VAV-C", "AHU-B"])).toBe("VAV-C");
  });
});
