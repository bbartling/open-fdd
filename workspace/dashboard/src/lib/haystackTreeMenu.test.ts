import { describe, expect, it } from "vitest";
import { buildPointContextMenuItems } from "./haystackTreeMenu";
import type { HaystackDevice, HaystackPoint } from "../components/HaystackPointsTree";

const device: HaystackDevice = {
  device_key: "site:demo",
  host: "site:demo",
  site_id: "site:demo",
  point_count: 1,
  poll_count: 0,
  points: [],
};

const point: HaystackPoint = {
  point_id: "point:sat",
  label: "SAT",
  haystack_id: "point:sat",
  enabled: false,
  poll_interval_s: 0,
  poll_label: "off",
  mapping_status: "mapped",
};

describe("haystackTreeMenu", () => {
  it("includes refresh, tags, map, and polling actions", () => {
    const items = buildPointContextMenuItems({ device, point });
    expect(items.map((i) => i.id)).toEqual(["actions", "polling", "copy-id", "copy-tags", "delete-pt"]);
    expect(items.find((i) => i.id === "actions")?.children?.map((c) => c.id)).toEqual([
      "refresh-point",
      "read-tags",
      "map-equip",
    ]);
  });
});
