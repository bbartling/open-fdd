import type { FddEquipmentItem } from "../api/analyticsApi";
import { equipmentKind, isWeatherEquipment } from "./overviewMetrics";

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

/** Show a health matrix only when a recognized equipment kind is present. */
export function plantEquipmentFamilies(
  equipment: FddEquipmentItem[],
): PlantEquipmentFamilies {
  let hasAhu = false;
  let hasChiller = false;
  let hasCoolingTower = false;
  let hasBoiler = false;
  let hasHeatPump = false;
  let hasVav = false;
  let hasZoneOther = false;
  const hasWeather = equipment.some((e) => isWeatherEquipment(e));

  for (const e of equipment) {
    if (isWeatherEquipment(e)) continue;
    switch (equipmentKind(e)) {
      case "vav":
      case "baseboard":
        hasVav = true;
        break;
      case "zone_other":
        hasZoneOther = true;
        break;
      case "ahu":
        hasAhu = true;
        break;
      case "cooling_tower":
        hasCoolingTower = true;
        break;
      case "chiller":
        hasChiller = true;
        break;
      case "boiler":
        hasBoiler = true;
        break;
      case "heatpump":
        hasHeatPump = true;
        break;
      default:
        break;
    }
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
