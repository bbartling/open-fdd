import { describe, expect, it } from "vitest";
import { mapSeriesToFaultTimelinePoints } from "./faultTimelineMap";

describe("mapSeriesToFaultTimelinePoints", () => {
  it("keeps raw/confirmed/operational and drops empty timestamps", () => {
    const out = mapSeriesToFaultTimelinePoints([
      { timestamp: "", raw: 1 },
      { timestamp: "2026-01-01T00:00:00Z", raw: 1, confirmed: 0, operational: 1 },
      { timestamp: "2026-01-01T00:05:00Z", raw: 0, confirmed: 0 },
    ]);
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual({
      timestamp: "2026-01-01T00:00:00Z",
      raw: 1,
      confirmed: 0,
      operational: 1,
    });
  });
});
