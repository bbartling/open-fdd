import { describe, it, expect } from "vitest";
import {
  faultAppliesToDevice,
  computeFaultMatrixCellStatus,
  matrixCellKey,
} from "./fault-matrix-utils";
import type { BacnetDevice, FaultDefinition, FaultState } from "@/types/api";

describe("fault-matrix-utils", () => {
  describe("faultAppliesToDevice", () => {
    it("returns true when definition has no equipment_types", () => {
      const def: FaultDefinition = {
        fault_id: "bad_sensor",
        name: "Bad sensor",
        description: null,
        severity: "warning",
        category: "sensor",
        equipment_types: null,
      };
      const device: BacnetDevice = {
        site_id: "s1",
        site_name: "Site1",
        bacnet_device_id: "123",
        equipment_id: "e1",
        equipment_name: "AHU-1",
        equipment_type: "AHU",
      };
      expect(faultAppliesToDevice(def, device)).toBe(true);
    });

    it("returns true when definition has empty equipment_types", () => {
      const def: FaultDefinition = {
        fault_id: "x",
        name: "X",
        description: null,
        severity: "warning",
        category: "general",
        equipment_types: [],
      };
      const device: BacnetDevice = {
        site_id: "s1",
        site_name: "Site1",
        bacnet_device_id: "123",
        equipment_id: "e1",
        equipment_name: "VAV-1",
        equipment_type: "VAV",
      };
      expect(faultAppliesToDevice(def, device)).toBe(true);
    });

    it("returns true when device equipment_type is in definition equipment_types (case insensitive)", () => {
      const def: FaultDefinition = {
        fault_id: "ahu_short",
        name: "AHU Short",
        description: null,
        severity: "warning",
        category: "ahu",
        equipment_types: ["AHU", "VAV_AHU"],
      };
      const device: BacnetDevice = {
        site_id: "s1",
        site_name: "Site1",
        bacnet_device_id: "123",
        equipment_id: "e1",
        equipment_name: "AHU-1",
        equipment_type: "AHU",
      };
      expect(faultAppliesToDevice(def, device)).toBe(true);
      const deviceLower: BacnetDevice = { ...device, equipment_type: "ahu" };
      expect(faultAppliesToDevice(def, deviceLower)).toBe(true);
    });

    it("returns false when device equipment_type is not in definition equipment_types", () => {
      const def: FaultDefinition = {
        fault_id: "ahu_short",
        name: "AHU Short",
        description: null,
        severity: "warning",
        category: "ahu",
        equipment_types: ["AHU", "VAV_AHU"],
      };
      const device: BacnetDevice = {
        site_id: "s1",
        site_name: "Site1",
        bacnet_device_id: "123",
        equipment_id: "e1",
        equipment_name: "VAV-1",
        equipment_type: "VAV",
      };
      expect(faultAppliesToDevice(def, device)).toBe(false);
    });

    it("returns false when device has no equipment_type and definition filters by equipment_types", () => {
      const def: FaultDefinition = {
        fault_id: "ahu_short",
        name: "AHU Short",
        description: null,
        severity: "warning",
        category: "ahu",
        equipment_types: ["AHU"],
      };
      const device: BacnetDevice = {
        site_id: "s1",
        site_name: "Site1",
        bacnet_device_id: "123",
        equipment_id: "e1",
        equipment_name: "Unknown",
        equipment_type: null,
      };
      expect(faultAppliesToDevice(def, device)).toBe(false);
    });
  });

  describe("matrixCellKey", () => {
    it("produces stable key from device and fault_id", () => {
      const device: BacnetDevice = {
        site_id: "site-uuid",
        site_name: "TestSite",
        bacnet_device_id: "3456789",
        equipment_id: "equip-uuid",
        equipment_name: "AHU-1",
        equipment_type: "AHU",
      };
      expect(matrixCellKey(device, "bad_sensor")).toBe(
        "site-uuid-3456789-equip-uuid-bad_sensor",
      );
      expect(matrixCellKey({ ...device, equipment_id: null }, "bad_sensor")).toBe(
        "site-uuid-3456789--bad_sensor",
      );
    });
  });

  describe("computeFaultMatrixCellStatus", () => {
    it("returns n_a for (device, fault) when fault does not apply to device", () => {
      const devices: BacnetDevice[] = [
        {
          site_id: "s1",
          site_name: "Site1",
          bacnet_device_id: "123",
          equipment_id: "e1",
          equipment_name: "VAV-1",
          equipment_type: "VAV",
        },
      ];
      const definitions: FaultDefinition[] = [
        {
          fault_id: "ahu_short",
          name: "AHU Short",
          description: null,
          severity: "warning",
          category: "ahu",
          equipment_types: ["AHU"],
        },
      ];
      const status = computeFaultMatrixCellStatus(devices, definitions, []);
      expect(status.get(matrixCellKey(devices[0], "ahu_short"))).toBe("n_a");
    });

    it("returns active when fault_state has matching active row", () => {
      const devices: BacnetDevice[] = [
        {
          site_id: "s1",
          site_name: "Site1",
          bacnet_device_id: "123",
          equipment_id: "e1",
          equipment_name: "AHU-1",
          equipment_type: "AHU",
        },
      ];
      const definitions: FaultDefinition[] = [
        {
          fault_id: "bad_sensor",
          name: "Bad sensor",
          description: null,
          severity: "warning",
          category: "sensor",
          equipment_types: null,
        },
      ];
      const state: FaultState[] = [
        {
          id: "fs1",
          site_id: "Site1",
          equipment_id: "e1",
          fault_id: "bad_sensor",
          active: true,
          last_changed_ts: "2026-01-01T00:00:00Z",
          last_evaluated_ts: null,
          context: null,
        },
      ];
      const status = computeFaultMatrixCellStatus(devices, definitions, state);
      expect(status.get(matrixCellKey(devices[0], "bad_sensor"))).toBe("active");
    });

    it("returns not_active when fault applies but no active state (or state cleared)", () => {
      const devices: BacnetDevice[] = [
        {
          site_id: "s1",
          site_name: "Site1",
          bacnet_device_id: "123",
          equipment_id: "e1",
          equipment_name: "AHU-1",
          equipment_type: "AHU",
        },
      ];
      const definitions: FaultDefinition[] = [
        {
          fault_id: "bad_sensor",
          name: "Bad sensor",
          description: null,
          severity: "warning",
          category: "sensor",
          equipment_types: null,
        },
      ];
      const state: FaultState[] = [
        {
          id: "fs1",
          site_id: "Site1",
          equipment_id: "e1",
          fault_id: "bad_sensor",
          active: false,
          last_changed_ts: "2026-01-01T00:00:00Z",
          last_evaluated_ts: null,
          context: null,
        },
      ];
      const status = computeFaultMatrixCellStatus(devices, definitions, state);
      expect(status.get(matrixCellKey(devices[0], "bad_sensor"))).toBe(
        "not_active",
      );
    });

    it("matches state by site_name when device has site_id uuid", () => {
      const devices: BacnetDevice[] = [
        {
          site_id: "uuid-site-1",
          site_name: "TestBenchSite",
          bacnet_device_id: "3456789",
          equipment_id: "equip-1",
          equipment_name: "AHU-1",
          equipment_type: "AHU",
        },
      ];
      const definitions: FaultDefinition[] = [
        {
          fault_id: "bad_sensor",
          name: "Bad sensor",
          description: null,
          severity: "warning",
          category: "sensor",
          equipment_types: null,
        },
      ];
      const state: FaultState[] = [
        {
          id: "fs1",
          site_id: "TestBenchSite",
          equipment_id: "AHU-1",
          fault_id: "bad_sensor",
          active: true,
          last_changed_ts: "2026-01-01T00:00:00Z",
          last_evaluated_ts: null,
          context: null,
        },
      ];
      const status = computeFaultMatrixCellStatus(devices, definitions, state);
      expect(status.get(matrixCellKey(devices[0], "bad_sensor"))).toBe("active");
    });
  });
});
