import { describe, expect, it } from "vitest";
import {
  EXPORT_OVERRIDE_REPORT_CSV_LABEL,
  genericOverrideBadgeLabel,
  operatorOverrideBadgeLabel,
  otherOverrideCount,
} from "./supervisoryOverrideUi";

describe("supervisoryOverrideUi", () => {
  it("uses clear export label instead of bare CSV", () => {
    expect(EXPORT_OVERRIDE_REPORT_CSV_LABEL).toContain("Export override report CSV");
    expect(EXPORT_OVERRIDE_REPORT_CSV_LABEL).not.toBe("CSV");
  });

  it("renders P8 and generic override badges distinctly", () => {
    expect(operatorOverrideBadgeLabel(2)).toBe("P8×2");
    expect(genericOverrideBadgeLabel()).toBe("⚠ ovrd");
  });

  it("computes other-priority override count", () => {
    expect(otherOverrideCount(5, 2)).toBe(3);
  });
});
