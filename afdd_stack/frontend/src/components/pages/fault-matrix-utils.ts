/**
 * Pure logic for the BACnet devices × fault definitions matrix.
 * Kept in a separate module so it can be unit-tested and not regress
 * when the Faults page UI is changed.
 */
import type { BacnetDevice, FaultDefinition, FaultState } from "@/types/api";

export type FaultCellStatus = "active" | "not_active" | "n_a";

/** Fault applies to device when definition has no equipment_types filter, or device's equipment_type is in the list. */
export function faultAppliesToDevice(
  def: FaultDefinition,
  device: BacnetDevice,
): boolean {
  if (!def.equipment_types || def.equipment_types.length === 0) return true;
  const et = device.equipment_type?.trim();
  if (!et) return false;
  return def.equipment_types.some(
    (t) => t.trim().toLowerCase() === et.toLowerCase(),
  );
}

export function matrixCellKey(
  device: BacnetDevice,
  faultId: string,
): string {
  return `${device.site_id}-${device.bacnet_device_id}-${device.equipment_id ?? ""}-${faultId}`;
}

/** Row key for a device in the matrix (same as TableRow key). */
export function deviceRowKey(device: BacnetDevice): string {
  return `${device.site_id}-${device.bacnet_device_id}`;
}

/**
 * Last time any fault state changed for each device (max of last_changed_ts across fault_state rows).
 * Used to show "Last known fault" per device without hardcoding.
 */
export function computeDeviceLastFaultTs(
  devices: BacnetDevice[],
  state: FaultState[],
): Map<string, string | null> {
  const out = new Map<string, string | null>();
  devices.forEach((d) => {
    const siteMatches = (s: FaultState) =>
      s.site_id === d.site_id || s.site_id === d.site_name;
    const equipMatches = (s: FaultState) =>
      s.equipment_id === (d.equipment_id ?? "") ||
      s.equipment_id === d.equipment_name;
    const relevant = state.filter(
      (s) => siteMatches(s) && equipMatches(s),
    );
    if (relevant.length === 0) {
      out.set(deviceRowKey(d), null);
      return;
    }
    const latest = relevant.reduce((best, s) => {
      const ts = s.last_changed_ts ?? "";
      return ts > (best ?? "") ? ts : best;
    }, null as string | null);
    out.set(deviceRowKey(d), latest);
  });
  return out;
}

/**
 * Compute cell status for every (device, definition) in the matrix.
 * Used by FaultMatrixTable so the logic is testable and stable.
 */
export function computeFaultMatrixCellStatus(
  devices: BacnetDevice[],
  definitions: FaultDefinition[],
  state: FaultState[],
): Map<string, FaultCellStatus> {
  const out = new Map<string, FaultCellStatus>();
  devices.forEach((d) => {
    definitions.forEach((def) => {
      const key = matrixCellKey(d, def.fault_id);
      if (!faultAppliesToDevice(def, d)) {
        out.set(key, "n_a");
        return;
      }
      const siteMatches = (s: FaultState) =>
        s.site_id === d.site_id || s.site_id === d.site_name;
      const equipMatches = (s: FaultState) =>
        s.equipment_id === (d.equipment_id ?? "") ||
        s.equipment_id === d.equipment_name;
      const relevant = state.filter(
        (s) =>
          siteMatches(s) && equipMatches(s) && s.fault_id === def.fault_id,
      );
      const activeRow = relevant.find((r) => r.active);
      out.set(key, activeRow ? "active" : "not_active");
    });
  });
  return out;
}
