import { describe, expect, it } from "vitest";
import { buildInventoryTree, flattenVisibleInventoryTree } from "./inventoryTree";
import type { InventoryRecord } from "../api/inventoryApi";

const device: InventoryRecord = {
  kind: "device",
  device_id: "device-opaque",
  protocol: "bacnet",
  display_name: "Opaque device",
  availability: "configured",
  commandability: "unknown",
  actions: [],
};

const group: InventoryRecord = {
  kind: "group",
  group_id: "group-opaque",
  device_id: "device-opaque",
  protocol: "bacnet",
  display_name: "Object group",
  availability: "configured",
  commandability: "unknown",
  actions: [],
};

const groupedPoint: InventoryRecord = {
  kind: "point",
  point_id: "point-grouped",
  device_id: "device-opaque",
  group_id: "group-opaque",
  protocol: "bacnet",
  display_name: "Grouped point",
  availability: "configured",
  commandability: "unknown",
  actions: [],
  reference: { kind: "bacnet", device_instance: 1, object_type: "analog-value", object_instance: 1, property_id: "present-value" },
};

const directPoint: InventoryRecord = {
  ...groupedPoint,
  point_id: "point-direct",
  group_id: undefined,
  display_name: "Direct point",
};

describe("inventoryTree", () => {
  it("joins points to typed parents even when pages arrive child-first", () => {
    const tree = buildInventoryTree([groupedPoint, device, group, directPoint]);
    expect(tree.roots).toHaveLength(1);
    expect(tree.roots[0].children.map((node) => node.kind)).toEqual(["group", "point"]);
    expect(tree.roots[0].children[0].children.map((node) => node.record.kind)).toEqual(["point"]);
    expect(tree.parents.get("point:point-grouped")).toBe("group:group-opaque");
    expect(tree.parents.get("point:point-direct")).toBe("device:device-opaque");
  });

  it("keeps missing typed parents visible as explicit orphans", () => {
    const orphan: InventoryRecord = {
      ...groupedPoint,
      point_id: "point-orphan",
      device_id: "missing-device",
    };
    const tree = buildInventoryTree([orphan]);
    expect(tree.roots).toHaveLength(0);
    expect(tree.orphanPoints[0].record).toMatchObject({ point_id: "point-orphan" });
    expect(flattenVisibleInventoryTree(tree, new Set())).toHaveLength(1);
  });

  it("does not infer hierarchy from labels or id prefixes", () => {
    const unrelated: InventoryRecord = {
      ...group,
      group_id: "device-opaque-object",
      device_id: "another-device",
      display_name: "Opaque device group",
    };
    const tree = buildInventoryTree([device, unrelated]);
    expect(tree.roots[0].children).toHaveLength(0);
    expect(tree.orphanGroups).toHaveLength(1);
  });
});
