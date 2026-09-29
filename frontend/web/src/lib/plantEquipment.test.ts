import { describe, expect, it } from "vitest";
import { plantEquipmentFamilies } from "./plantEquipment";

describe("plantEquipmentFamilies", () => {
  it("shows only families present in package inventory", () => {
    const f = plantEquipmentFamilies([
      { equipment_id: "AC_1", equipment_type: "AHU", equipment_type_raw: "ahu" },
      {
        equipment_id: "CHILLER_1",
        equipment_type: "PLANT",
        equipment_type_raw: "chwPlant",
      },
      { equipment_id: "jci_vav_1", equipment_type: "VAV" },
      { equipment_id: "OA_REF", equipment_type: "WEATHER" },
    ]);
    expect(f.hasAhu).toBe(true);
    expect(f.hasChiller).toBe(true);
    expect(f.hasCoolingTower).toBe(false);
    expect(f.hasVav).toBe(true);
    expect(f.hasWeather).toBe(true);
    expect(f.hasHeatPump).toBe(false);
    expect(f.hasBoiler).toBe(false);
  });

  it("separates cooling towers from chillers by stamp", () => {
    const f = plantEquipmentFamilies([
      {
        equipment_id: "CT_opaque",
        equipment_type: "PLANT",
        equipment_type_raw: "cooling_tower",
      },
    ]);
    expect(f.hasCoolingTower).toBe(true);
    expect(f.hasChiller).toBe(false);
  });

  it("does not treat a tower-like id as a cooling tower without a stamp", () => {
    const f = plantEquipmentFamilies([
      { equipment_id: "TOWER_1", equipment_type: "PLANT" },
    ]);
    expect(f.hasCoolingTower).toBe(false);
    expect(f.hasChiller).toBe(false);
  });

  it("keeps a stamped chiller out of the heat-pump matrix", () => {
    const f = plantEquipmentFamilies([
      {
        equipment_id: "HP_HEAT_PUMP_X",
        equipment_type: "PLANT",
        equipment_type_raw: "chiller",
      },
    ]);
    expect(f.hasChiller).toBe(true);
    expect(f.hasHeatPump).toBe(false);
  });

  it("does not admit an unstamped zone id to the VAV matrix", () => {
    const f = plantEquipmentFamilies([
      { equipment_id: "bldg2-zone-loopback" },
      { equipment_id: "jci_vav_2", equipment_type: "VAV" },
    ]);
    expect(f.hasVav).toBe(true);
    expect(f.hasAhu).toBe(false);
  });

  it("hides heat pump matrix when no HP refs", () => {
    const f = plantEquipmentFamilies([{ equipment_id: "AHU_2", equipment_type: "AHU" }]);
    expect(f.hasHeatPump).toBe(false);
    expect(f.hasAhu).toBe(true);
  });

  it("recognizes Zone Other stamps for MQTT / generic zone section", () => {
    const f = plantEquipmentFamilies([
      { equipment_id: "hosted-weather", equipment_type: "Zone Other" },
      { equipment_id: "FEC_1", equipment_type: "zone_other" },
    ]);
    expect(f.hasZoneOther).toBe(true);
    expect(f.hasAhu).toBe(false);
    expect(f.hasWeather).toBe(false);
  });
});
