import type { FddEquipmentItem } from "../api/analyticsApi";
import { isWeatherEquipment, isZoneTerminalEquipment } from "./overviewMetrics";

/** Mirror `plant_health::is_heat_pump_id`. */
export function isHeatPumpId(equipmentId: string): boolean {
  const u = equipmentId
    .trim()
    .toUpperCase()
    .replace(/\\/g, "/")
    .replace(/-/g, "_");
  return (
    u.startsWith("HP_") ||
    u.includes("/HP_") ||
    u.includes("HEAT_PUMP") ||
    u.includes("HEATPUMP")
  );
}

function normalizedType(equipment: FddEquipmentItem): string {
  const raw = String(
    equipment.equipment_type_raw ??
      equipment.equipType ??
      equipment.equipment_type ??
      "",
  );
  return raw.trim().toUpperCase().replace(/[\s-]+/g, "_");
}

export function isCoolingTowerEquipment(equipment: FddEquipmentItem): boolean {
  const kind = normalizedType(equipment);
  if (
    kind === "COOLING_TOWER" ||
    kind === "COOLINGTOWER" ||
    kind === "TOWER"
  ) {
    return true;
  }
  const id = String(equipment.equipment_id ?? "").trim().toUpperCase();
  return id.includes("TOWER") || id.startsWith("CT_") || id.includes("/CT_");
}

/** Rough plant group from equipment id (historian `plant_group_for`). */
export function plantGroupFor(equipmentId: string): "air" | "chiller" | "boiler" | null {
  const u = equipmentId.trim().toUpperCase().replace(/\\/g, "/");
  if (!u || isZoneTerminalId(u)) return null;
  if (u.includes("BOILER") || u.includes("HW_PUMP") || u.includes("HW-")) {
    return "boiler";
  }
  if (
    u.includes("CHILLER") ||
    u.includes("CHW") ||
    u.includes("CW_PUMP") ||
    u.includes("TOWER") ||
    u.startsWith("CH-")
  ) {
    return "chiller";
  }
  if (u.includes("AHU") || u.includes("RTU") || u.includes("MAU") || u.includes("DOAS")) {
    return "air";
  }
  return null;
}

function isZoneTerminalId(id: string): boolean {
  return (
    id.includes("VAV") || id.includes("ZONE") || id.includes("VAVFC") || id.includes("VAVH")
  );
}

export interface PlantEquipmentFamilies {
  hasAhu: boolean;
  hasChiller: boolean;
  hasCoolingTower: boolean;
  hasBoiler: boolean;
  hasHeatPump: boolean;
  hasVav: boolean;
  hasWeather: boolean;
  hasZoneOther: boolean;
}

/** Data-model driven — only show health matrices when equipment exists in package. */
export function plantEquipmentFamilies(
  equipment: FddEquipmentItem[],
): PlantEquipmentFamilies {
  const items = equipment.filter((e) => !isWeatherEquipment(e));
  let hasAhu = false;
  let hasChiller = false;
  let hasCoolingTower = false;
  let hasBoiler = false;
  let hasHeatPump = false;
  let hasVav = false;
  let hasZoneOther = false;
  const hasWeather = equipment.some((e) => isWeatherEquipment(e));

  for (const e of items) {
    const id = String(e.equipment_id ?? "");
    const kind = String(e.equipment_type ?? "").trim().toUpperCase();
    const tower = isCoolingTowerEquipment(e);
    if (kind === "VAV" || isZoneTerminalEquipment(e)) hasVav = true;
    if (
      kind === "ZONE_OTHER" ||
      kind === "ZONE OTHER" ||
      kind === "ZONEOTHER"
    ) {
      hasZoneOther = true;
    }
    if (kind === "AHU" || plantGroupFor(id) === "air") hasAhu = true;
    if (tower) hasCoolingTower = true;
    if (kind === "PLANT" && plantGroupFor(id) === "boiler") hasBoiler = true;
    if (kind === "PLANT" && plantGroupFor(id) === "chiller" && !tower) hasChiller = true;
    if (isHeatPumpId(id) || kind === "HEAT_PUMP" || kind === "HEATPUMP") {
      hasHeatPump = true;
    }
    if (plantGroupFor(id) === "chiller" && !isHeatPumpId(id) && !tower) hasChiller = true;
    if (plantGroupFor(id) === "boiler") hasBoiler = true;
  }

  return {
    hasAhu,
    hasChiller,
    hasCoolingTower,
    hasBoiler,
    hasHeatPump,
    hasVav,
    hasWeather,
    hasZoneOther,
  };
}
