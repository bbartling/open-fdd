import { describe, expect, it } from "vitest";
import { NODE_CATALOG, NODE_CATEGORIES, accentForNodeType, catalogByCategory } from "./nodeCatalog";

describe("wiresheet nodeCatalog", () => {
  it("covers all declared categories", () => {
    const grouped = catalogByCategory();
    for (const cat of NODE_CATEGORIES) {
      expect(grouped.get(cat)?.length).toBeGreaterThan(0);
    }
  });

  it("has unique palette labels per category bucket", () => {
    const labels = NODE_CATALOG.map((e) => `${e.category}:${e.label}`);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("assigns accent colors by node family", () => {
    expect(accentForNodeType("sql_rule")).toMatch(/^#/);
    expect(accentForNodeType("model_point")).toMatch(/^#/);
    expect(accentForNodeType("fault_output")).toMatch(/^#/);
  });
});
