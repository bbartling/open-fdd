import { describe, expect, it } from "vitest";
import {
  buildAssignmentRows,
  mergeBind,
  ruleBindsTarget,
  rulesBoundToTarget,
  unbindTarget,
} from "./ruleBindings";
import type { SavedRule } from "./ruleBindings";

const rules: SavedRule[] = [
  {
    id: "r1",
    name: "SAT high",
    enabled: true,
    bindings: { point_ids: ["p1"], equipment_ids: [], brick_types: [] },
  },
  {
    id: "r2",
    name: "Zone flatline",
    enabled: true,
    bindings: { point_ids: [], equipment_ids: ["eq1"], brick_types: ["Zone_Air_Temperature_Sensor"] },
  },
];

describe("ruleBindings", () => {
  it("detects point binding", () => {
    const t = { kind: "point" as const, id: "p1", label: "p1" };
    expect(rulesBoundToTarget(rules, t).map((r) => r.id)).toEqual(["r1"]);
  });

  it("merges point and mass point ids", () => {
    const next = mergeBind({}, "brick_type", "Supply_Air_Temperature_Sensor", ["p2", "p3"]);
    expect(next.brick_types).toContain("Supply_Air_Temperature_Sensor");
    expect(next.point_ids).toEqual(["p2", "p3"]);
  });

  it("unbinds equipment and its points", () => {
    const prev = {
      point_ids: ["p1", "p2"],
      equipment_ids: ["eq1"],
      brick_types: [],
    };
    const next = unbindTarget(prev, {
      kind: "equipment",
      id: "eq1",
      label: "eq1",
      pointIds: ["p1", "p2"],
    });
    expect(next.equipment_ids).toEqual([]);
    expect(next.point_ids).toEqual([]);
  });

  it("builds assignment summary rows", () => {
    const rows = buildAssignmentRows(rules);
    expect(rows).toHaveLength(2);
    expect(rows[0].pointCount + rows[1].pointCount).toBeGreaterThan(0);
  });

  it("ruleBindsTarget for brick type", () => {
    expect(
      ruleBindsTarget(rules[1], {
        kind: "brick_type",
        id: "Zone_Air_Temperature_Sensor",
        label: "zone",
      }),
    ).toBe(true);
  });
});
