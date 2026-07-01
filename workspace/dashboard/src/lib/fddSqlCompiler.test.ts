import { describe, expect, it } from "vitest";
import { expandTimeMacros } from "./fddSqlCompiler";

describe("fddSqlCompiler", () => {
  it("expands time macro for test execution", () => {
    const sql = "SELECT * FROM telemetry_pivot WHERE $__timeFilter(timestamp)";
    expect(expandTimeMacros(sql)).toContain("timestamp IS NOT NULL");
  });
});
