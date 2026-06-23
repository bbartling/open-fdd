import { describe, expect, it } from "vitest";
import { buildPointContextMenuItems } from "./modbusTreeMenu";
import type { ModbusDevice, ModbusPoint } from "../components/ModbusPointsTree";

const device: ModbusDevice = {
  device_key: "192.168.1.50:502:1",
  host: "192.168.1.50",
  port: "502",
  unit_id: "1",
  point_count: 2,
  poll_count: 0,
  points: [],
};

const point: ModbusPoint = {
  point_id: "modbus:tcp:1:40001",
  label: "Temp",
  register_address: "40001",
  function: "holding_register",
  enabled: false,
  poll_interval_s: 0,
  poll_label: "off",
};

describe("modbusTreeMenu", () => {
  it("includes refresh value and polling submenu", () => {
    const items = buildPointContextMenuItems({ device, point });
    expect(items.find((i) => i.id === "actions")?.children?.[0]?.label).toBe("Refresh value");
    expect(items.find((i) => i.id === "polling")?.children).toHaveLength(4);
  });
});
