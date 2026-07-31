import { describe, expect, it } from "vitest";
import {
  missingSegmentCount,
  seriesRowsToFigure,
} from "./plotDataset";

describe("plotDataset", () => {
  it("builds figure traces from series rows", () => {
    const fig = seriesRowsToFigure(
      [
        { timestamp_utc: "t0", zone_t: 70, sat: 55 },
        { timestamp_utc: "t1", zone_t: 71, sat: null },
        { timestamp_utc: "t2", zone_t: 72, sat: 56 },
      ],
      {
        equipmentId: "AHU_1",
        ruleId: "VAV-1",
        roles: ["zone_t", "sat"],
        downsampled: false,
        maxPoints: 5000,
      },
    );
    expect(fig.data).toHaveLength(2);
    expect(fig.data[0].y).toEqual([70, 71, 72]);
    expect(fig.data[1].y).toEqual([55, null, 56]);
    expect(fig.meta?.point_count).toBe(3);
    expect(fig.meta?.provenance).toMatch(/fdd\/series/);
  });

  it("counts missing segments", () => {
    expect(
      missingSegmentCount({
        name: "x",
        x: [1, 2, 3, 4, 5],
        y: [1, null, null, 2, null],
      }),
    ).toBe(2);
  });
});
