import { describe, expect, test } from "vitest";
import {
  inferXColumn,
  inferYColumns,
  joinFaultSignals,
  parseCsvText,
  pickFaultBucket,
} from "@/lib/plots-csv";

describe("plots-csv helpers", () => {
  test("inferXColumn prefers timestamp-like names", () => {
    expect(inferXColumn(["value", "timestamp", "temp"])).toBe("timestamp");
    expect(inferXColumn(["foo", "date_time", "bar"])).toBe("date_time");
  });

  test("inferYColumns picks mostly numeric columns", () => {
    const parsed = parseCsvText("timestamp,temp,status\n2026-01-01T00:00:00Z,70,ok\n2026-01-01T01:00:00Z,71,ok");
    const ys = inferYColumns(parsed, "timestamp");
    expect(ys).toContain("temp");
    expect(ys).not.toContain("status");
  });

  test("pickFaultBucket returns hour for short range", () => {
    expect(pickFaultBucket("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")).toBe("hour");
    expect(pickFaultBucket("2026-01-01T00:00:00Z", "2026-01-10T00:00:00Z")).toBe("day");
  });

  test("joinFaultSignals appends fault columns", () => {
    const csv = parseCsvText(
      "timestamp,temp\n2026-01-01T00:00:00Z,70\n2026-01-01T01:00:00Z,72",
    );
    const joined = joinFaultSignals(
      csv,
      "timestamp",
      [{ time: "2026-01-01T00:00:00Z", metric: "sat_high_flag", value: 1 }],
      "hour",
    );
    expect(joined.headers).toContain("fault_sat_high_flag");
    expect(joined.rows[0]["fault_sat_high_flag"]).toBe(1);
    expect(joined.rows[1]["fault_sat_high_flag"]).toBe(0);
  });

  test("joinFaultSignals handles Date objects in x column", () => {
    const csv = {
      headers: ["timestamp", "temp"],
      rows: [
        { timestamp: new Date("2026-01-01T00:00:00Z"), temp: 70 },
        { timestamp: new Date("2026-01-01T01:00:00Z"), temp: 72 },
      ],
    };
    const joined = joinFaultSignals(
      csv,
      "timestamp",
      [{ time: "2026-01-01T00:00:00Z", metric: "sat_high_flag", value: 1 }],
      "hour",
    );
    expect(joined.rows[0]["fault_sat_high_flag"]).toBe(1);
    expect(joined.rows[1]["fault_sat_high_flag"]).toBe(0);
  });
});

