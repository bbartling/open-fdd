import { describe, it, expect } from "vitest";
import { displayRangeUpdater } from "./plots-display-range";

describe("PlotsPage display range updater", () => {
  it("returns same reference when start and end are unchanged", () => {
    const prev = { start: "2025-01-01T00:00:00.000Z", end: "2025-01-07T00:00:00.000Z" };
    const result = displayRangeUpdater(prev, prev.start, prev.end);
    expect(result).toBe(prev);
    expect(result).toEqual(prev);
  });

  it("returns new object when start or end changes", () => {
    const prev = { start: "2025-01-01T00:00:00.000Z", end: "2025-01-07T00:00:00.000Z" };
    const result = displayRangeUpdater(prev, "2025-01-02T00:00:00.000Z", prev.end);
    expect(result).not.toBe(prev);
    expect(result).toEqual({ start: "2025-01-02T00:00:00.000Z", end: prev.end });
  });

  it("returns new object when prev is null", () => {
    const result = displayRangeUpdater(null, "2025-01-01T00:00:00.000Z", "2025-01-07T00:00:00.000Z");
    expect(result).toEqual({ start: "2025-01-01T00:00:00.000Z", end: "2025-01-07T00:00:00.000Z" });
  });
});
