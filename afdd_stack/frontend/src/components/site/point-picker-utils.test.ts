import { describe, it, expect } from "vitest";
import { uniquePointsForDropdown, pointGroupKey } from "./point-picker-utils";
import type { Point } from "@/types/api";

function point(id: string, equipment_id: string | null): Point {
  return {
    id,
    site_id: "site-1",
    external_id: id,
    brick_type: null,
    fdd_input: null,
    unit: null,
    description: null,
    equipment_id,
    bacnet_device_id: null,
    object_identifier: null,
    object_name: id,
    polling: true,
    created_at: new Date().toISOString(),
  };
}

describe("point-picker-utils", () => {
  describe("uniquePointsForDropdown", () => {
    it("returns no duplicate point ids so dropdown matches points table", () => {
      const input = [
        point("p1", "AHU-1"),
        point("p2", null),
        point("p1", "AHU-1"),
        point("p3", ""),
        point("p2", null),
      ];
      const result = uniquePointsForDropdown(input);
      const ids = result.map((p) => p.id);
      const uniqueIds = new Set(ids);
      expect(ids.length).toBe(uniqueIds.size);
      expect(uniqueIds.size).toBe(3);
      expect(uniqueIds.has("p1")).toBe(true);
      expect(uniqueIds.has("p2")).toBe(true);
      expect(uniqueIds.has("p3")).toBe(true);
    });

    it("dropdown option set equals the set of point ids from the table", () => {
      const input = [point("a", "eq1"), point("b", null), point("c", "eq2")];
      const result = uniquePointsForDropdown(input);
      const resultIds = new Set(result.map((p) => p.id));
      const inputIds = new Set(input.map((p) => p.id));
      expect(resultIds.size).toBe(inputIds.size);
      for (const id of inputIds) {
        expect(resultIds.has(id)).toBe(true);
      }
    });
  });

  describe("pointGroupKey", () => {
    it("normalizes null and empty string to same unassigned key so groups are not duplicated", () => {
      expect(pointGroupKey(point("x", null))).toBe("__unassigned__");
      expect(pointGroupKey(point("y", ""))).toBe("__unassigned__");
      expect(pointGroupKey(point("z", "  "))).toBe("__unassigned__");
    });

    it("uses equipment_id as key when present", () => {
      expect(pointGroupKey(point("p", "AHU-1"))).toBe("AHU-1");
    });
  });
});
