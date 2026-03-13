import { describe, it, expect } from "vitest";
import { parseLongCsv, pivotForChart } from "./csv";

describe("parseLongCsv", () => {
  it("returns empty array for empty string", () => {
    expect(parseLongCsv("")).toEqual([]);
  });
  it("returns empty for header only", () => {
    expect(parseLongCsv("ts,point_key,value")).toEqual([]);
  });
  it("parses one row", () => {
    const csv = "ts,point_key,value\n2025-03-04T12:00:00Z,temp,72.5";
    const out = parseLongCsv(csv);
    expect(out).toEqual([
      {
        timestamp: new Date("2025-03-04T12:00:00Z").getTime(),
        pointKey: "temp",
        value: 72.5,
      },
    ]);
  });
});

describe("pivotForChart", () => {
  it("pivots long rows to wide by timestamp", () => {
    const rows = [
      {
        timestamp: new Date("2025-03-04T12:00:00Z").getTime(),
        pointKey: "a",
        value: 1,
      },
      {
        timestamp: new Date("2025-03-04T12:00:00Z").getTime(),
        pointKey: "b",
        value: 2,
      },
      {
        timestamp: new Date("2025-03-04T13:00:00Z").getTime(),
        pointKey: "a",
        value: 3,
      },
    ];
    const out = pivotForChart(rows);
    expect(out).toHaveLength(2);
    expect(out[0].timestamp).toBe(new Date("2025-03-04T12:00:00Z").getTime());
    expect(out[0].a).toBe(1);
    expect(out[0].b).toBe(2);
    expect(out[1].a).toBe(3);
  });
});
