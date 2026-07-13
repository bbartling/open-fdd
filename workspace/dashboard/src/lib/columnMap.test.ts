import { describe, expect, it } from "vitest";
import {
  emptyColumnMapDocument,
  exportColumnMapJson,
  normalizeColumnMapDocument,
  parseColumnMapJson,
  validateColumnMapDocument,
} from "./columnMap";

describe("columnMap", () => {
  it("empty scaffold has no invented roles", () => {
    const doc = emptyColumnMapDocument("ds-a");
    expect(doc.version).toBe(1);
    expect(doc.dataset_id).toBe("ds-a");
    expect(doc.column_map).toEqual({});
  });

  it("rejects missing required fields", () => {
    const v = validateColumnMapDocument(emptyColumnMapDocument());
    expect(v.ok).toBe(false);
    expect(v.errors.some((e) => e.includes("dataset_id"))).toBe(true);
    expect(v.errors.some((e) => e.includes("timezone"))).toBe(true);
    expect(v.errors.some((e) => e.includes("timestamp_column"))).toBe(true);
    expect(v.errors.some((e) => e.includes("equipment"))).toBe(true);
  });

  it("rejects duplicate roles", () => {
    const v = validateColumnMapDocument({
      version: 1,
      dataset_id: "ds1",
      timezone: "UTC",
      timestamp_column: "ts",
      equipment: "equip:ahu-1",
      column_map: { OA: "oa_t", Outside: "oa_t" },
    });
    expect(v.ok).toBe(false);
    expect(v.errors[0]).toMatch(/duplicate role/);
  });

  it("accepts explicit mapping", () => {
    const doc = {
      version: 1,
      dataset_id: "ds1",
      timezone: "America/Chicago",
      timestamp_column: "Date",
      equipment: "equip:ahu-1",
      column_map: { "OA Temp": "oa_t", SAT: "sat" },
    };
    expect(validateColumnMapDocument(doc).ok).toBe(true);
  });

  it("round-trips import/export without inventing keys", () => {
    const text = exportColumnMapJson({
      version: 1,
      dataset_id: "ds1",
      timezone: "UTC",
      timestamp_column: "ts",
      equipment: "equip:ahu-1",
      column_map: { A: "oa_t" },
    });
    const parsed = parseColumnMapJson(text);
    expect(parsed.column_map).toEqual({ A: "oa_t" });
    expect(Object.keys(parsed.column_map)).toHaveLength(1);
  });

  it("normalize drops empty roles instead of inventing", () => {
    const n = normalizeColumnMapDocument({
      version: 1,
      dataset_id: "x",
      timezone: "UTC",
      timestamp_column: "ts",
      equipment: "equip:x",
      column_map: { Keep: "sat", Drop: "  " },
    });
    expect(n.column_map).toEqual({ Keep: "sat" });
  });
});
