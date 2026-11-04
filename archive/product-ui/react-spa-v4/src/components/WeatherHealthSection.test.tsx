import { describe, expect, it } from "vitest";

import type { FddResultRow } from "../api/fddApi";
import { aggregateWxFaultTriState } from "./WeatherHealthSection";

function row(partial: Partial<FddResultRow>): FddResultRow {
  return partial as FddResultRow;
}

describe("aggregateWxFaultTriState", () => {
  it("returns unknown when every child is unknown", () => {
    const rows = [
      row({ status: "INTERVAL_UNKNOWN", fault_hours: null }),
      row({ status: "NOT_ASSESSED", fault_hours: undefined }),
    ];
    expect(aggregateWxFaultTriState(rows)).toBe("unknown");
  });

  it("returns unknown when mixed false and unknown", () => {
    const rows = [
      row({ status: "PASS", fault_hours: 0 }),
      row({ status: "INTERVAL_UNKNOWN", fault_hours: null }),
    ];
    expect(aggregateWxFaultTriState(rows)).toBe("unknown");
  });

  it("returns false when all known and none fault", () => {
    const rows = [
      row({ status: "PASS", fault_hours: 0 }),
      row({ status: "PASS", fault_hours: 0 }),
    ];
    expect(aggregateWxFaultTriState(rows)).toBe("false");
  });

  it("returns true when any child is a real fault", () => {
    const rows = [
      row({ status: "PASS", fault_hours: 0 }),
      row({ status: "FAULT", fault_hours: 2.5 }),
    ];
    expect(aggregateWxFaultTriState(rows)).toBe("true");
  });
});
