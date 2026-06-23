import { describe, expect, it } from "vitest";
import { buildPointContextMenuItems } from "./jsonApiTreeMenu";
import type { JsonApiDevice, JsonApiPoint } from "../components/JsonApiPointsTree";

const device: JsonApiDevice = {
  device_key: "api.example.com",
  host: "api.example.com",
  point_count: 2,
  poll_count: 0,
  points: [],
};

const point: JsonApiPoint = {
  point_id: "json:oat",
  label: "Outside air",
  url: "https://api.example.com/weather",
  method: "GET",
  json_path: "$.main.temp",
  enabled: false,
  poll_interval_s: 0,
  poll_label: "off",
};

describe("jsonApiTreeMenu", () => {
  it("includes copy URL and remove endpoint actions", () => {
    const items = buildPointContextMenuItems({ device, point });
    expect(items.map((i) => i.id)).toContain("copy-url");
    expect(items.find((i) => i.id === "delete-pt")?.label).toBe("Remove endpoint");
  });
});
