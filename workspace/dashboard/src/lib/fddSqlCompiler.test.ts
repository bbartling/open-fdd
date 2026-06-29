import { describe, expect, it } from "vitest";
import { compileNaturalLanguagePrompt, expandTimeMacros } from "./fddSqlCompiler";
import type { FddInput, SchemaTable } from "../components/sqlFdd/types";

const inputs: FddInput[] = [
  { id: "oa_t", label: "OA temperature", unit: "degF" },
  { id: "sat", label: "Supply Air Temp", unit: "degF" },
];

const schema: SchemaTable[] = [
  {
    name: "telemetry_pivot",
    columns: [
      { name: "timestamp", type: "TIMESTAMP", is_primary: true },
      { name: "equipment_id", type: "VARCHAR" },
      { name: "oa_t", type: "DOUBLE", fdd_input: true },
      { name: "sat", type: "DOUBLE", fdd_input: true },
    ],
  },
];

describe("fddSqlCompiler", () => {
  it("compiles fault-style NL to read-only SQL with fault_raw", () => {
    const out = compileNaturalLanguagePrompt({
      userPrompt: "Show OA temperature above 110 fault for this AHU",
      equipmentId: "equip:ahu-1",
      schema,
      fddInputs: inputs,
    });
    expect(out.ok).toBe(true);
    expect(out.sql).toContain("fault_raw");
    expect(out.sql).toContain("oa_t > 110");
    expect(out.sql).toContain("equip:ahu-1");
    expect(out.dialect).toBe("DataFusion");
  });

  it("rejects unknown columns", () => {
    const out = compileNaturalLanguagePrompt({
      userPrompt: "show mystery_col above 1",
      equipmentId: "equip:ahu-1",
      schema: [{ name: "telemetry_pivot", columns: ["timestamp", "equipment_id"] }],
      fddInputs: [{ id: "mystery_col", label: "Mystery" }],
    });
    expect(out.ok).toBe(false);
    expect(out.error).toMatch(/not in telemetry_pivot/i);
  });

  it("expands time macro for test execution", () => {
    const sql = "SELECT * FROM telemetry_pivot WHERE $__timeFilter(timestamp)";
    expect(expandTimeMacros(sql)).toContain("timestamp IS NOT NULL");
  });
});
