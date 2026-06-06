import { describe, expect, it } from "vitest";
import {
  buildDeviceContextMenuItems,
  buildPointContextMenuItems,
  formatBacnetValue,
} from "./bacnetTreeMenu";
import type { DriverDevice, DriverPoint } from "../components/BacnetPointsTree";

const device: DriverDevice = {
  device_instance: "100",
  device_address: "10.0.0.1",
  point_count: 2,
  poll_count: 0,
  points: [],
};

const commandablePoint: DriverPoint = {
  point_id: "p1",
  object_identifier: "analog-value,1",
  object_name: "Setpoint",
  object_type: "analog-value",
  enabled: false,
  poll_interval_s: 0,
  poll_label: "",
  commandable: true,
};

const readOnlyPoint: DriverPoint = {
  ...commandablePoint,
  point_id: "p2",
  object_identifier: "analog-input,1",
  object_name: "SAT",
  object_type: "analog-input",
  commandable: false,
};

function findChild(items: ReturnType<typeof buildPointContextMenuItems>, id: string) {
  const parent = items.find((i) => i.id === "actions");
  return parent?.children?.find((c) => c.id === id);
}

describe("buildPointContextMenuItems", () => {
  it("groups Actions and Polling submenus", () => {
    const items = buildPointContextMenuItems({ device, point: commandablePoint });
    expect(items.map((i) => i.id)).toEqual(["actions", "polling", "copy-oid", "delete-pt"]);
    expect(items.find((i) => i.id === "actions")?.children?.map((c) => c.id)).toEqual([
      "refresh-pv",
      "read-priority-array",
    ]);
    expect(items.find((i) => i.id === "polling")?.children).toHaveLength(4);
  });

  it("disables read priority array when point is not commandable", () => {
    const items = buildPointContextMenuItems({ device, point: readOnlyPoint });
    const readPa = findChild(items, "read-priority-array");
    expect(readPa?.disabled).toBe(true);
  });

  it("enables read priority array for commandable points", () => {
    const items = buildPointContextMenuItems({ device, point: commandablePoint });
    const readPa = findChild(items, "read-priority-array");
    expect(readPa?.disabled).toBe(false);
  });

  it("enables read priority array for analog-value even when commandable flag is false", () => {
    const avPoint: DriverPoint = {
      ...readOnlyPoint,
      object_identifier: "analog-value,1168",
      object_type: "analog-value",
      commandable: false,
    };
    expect(pointIsCommandable(avPoint)).toBe(true);
    const readPa = findChild(buildPointContextMenuItems({ device, point: avPoint }), "read-priority-array");
    expect(readPa?.disabled).toBe(false);
  });
});

describe("buildDeviceContextMenuItems", () => {
  it("puts device poll options under Polling submenu", () => {
    const items = buildDeviceContextMenuItems({ device });
    const polling = items.find((i) => i.id === "polling");
    expect(polling?.children?.map((c) => c.id)).toEqual([
      "dev-poll-60",
      "dev-poll-300",
      "dev-poll-600",
      "dev-poll-900",
      "poll-off-all",
    ]);
  });
});

describe("formatBacnetValue", () => {
  it("stringifies objects and null", () => {
    expect(formatBacnetValue(null)).toBe("—");
    expect(formatBacnetValue(72.5)).toBe("72.5");
    expect(formatBacnetValue({ x: 1 })).toBe('{"x":1}');
  });
});
