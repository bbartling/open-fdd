import { describe, expect, it } from "vitest";
import { fddStatusBucket, preferredPlotRuleId } from "./fddPlotStatus";

describe("fddPlotStatus", () => {
  it("buckets vibe19 statuses", () => {
    expect(fddStatusBucket("FAULT")).toBe("FAULT");
    expect(fddStatusBucket("PASS")).toBe("PASS");
    expect(fddStatusBucket("SKIPPED_MISSING_ROLES")).toBe("SKIPPED");
    expect(fddStatusBucket(undefined)).toBe("Not run");
  });

  it("prefers FAULT then any result", () => {
    const status = new Map([
      ["A", "PASS"],
      ["B", "FAULT"],
    ]);
    expect(preferredPlotRuleId(["A", "B"], status)).toBe("B");
  });
});
