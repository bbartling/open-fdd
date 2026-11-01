import type { HistorianPoint } from "../api/historianApi";
import { naturalCompare } from "./naturalSort";

export interface DeviceTreeEquipment {
  /** Exact equipment id from `point_map`; empty when the series has none. */
  equipmentId: string;
  equipType: string | null;
  points: HistorianPoint[];
  orphaned: number;
}

/** Group historian series by exact equipment id. No id text matching. */
export function groupDeviceTree(points: readonly HistorianPoint[]): DeviceTreeEquipment[] {
  const groups = new Map<string, DeviceTreeEquipment>();
  for (const point of points) {
    const equipmentId = point.equipment_id ?? "";
    let group = groups.get(equipmentId);
    if (!group) {
      group = { equipmentId, equipType: point.equip_type, points: [], orphaned: 0 };
      groups.set(equipmentId, group);
    }
    if (!group.equipType && point.equip_type) group.equipType = point.equip_type;
    group.points.push(point);
    if (!point.referenced) group.orphaned += 1;
  }
  const out = [...groups.values()];
  for (const group of out) {
    group.points.sort((a, b) => naturalCompare(a.openfdd_key, b.openfdd_key));
  }
  return out.sort((a, b) => {
    if (!a.equipmentId) return 1;
    if (!b.equipmentId) return -1;
    return naturalCompare(a.equipmentId, b.equipmentId);
  });
}
