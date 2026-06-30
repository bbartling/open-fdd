import { describe, expect, it } from "vitest";
import { DEFAULT_TELEMETRY_PIVOT_SQL, formatSql } from "./formatSql";

describe("formatSql", () => {
  it("formats a one-line SELECT with CASE block", () => {
    const input =
      "select timestamp, equipment_id, oa_t, case when oa_t is null then false when oa_t < 40.0 then true when oa_t > 110.0 then true else false end as fault_raw from telemetry_pivot where equipment_id = 'equip:validation'";
    expect(formatSql(input)).toBe(
      `SELECT
  timestamp,
  equipment_id,
  oa_t,
  CASE
    WHEN oa_t IS NULL THEN false
    WHEN oa_t < 40.0 THEN true
    WHEN oa_t > 110.0 THEN true
    ELSE false
  END AS fault_raw
FROM telemetry_pivot
WHERE equipment_id = 'equip:validation'`,
    );
  });

  it("leaves already-formatted SQL stable", () => {
    expect(formatSql(DEFAULT_TELEMETRY_PIVOT_SQL)).toBe(DEFAULT_TELEMETRY_PIVOT_SQL);
  });
});
