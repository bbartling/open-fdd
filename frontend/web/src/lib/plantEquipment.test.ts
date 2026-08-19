import { describe, expect, it } from "vitest";
import { plantEquipmentFamilies } from "./plantEquipment";

describe("plantEquipmentFamilies", () => {
  it("shows only families present in package inventory", () => {
    const f = plantEquipmentFamilies([
      { equipment_id: "AHU_1", equipment_type: "AHU" },
      { equipment_id: "CHILLER_1", equipment_type: "PLANT" },
      { equipment_id: "VAV_12", equipment_type: "VAV" },
      { equipment_id: "weather", equipment_type: "WEATHER" },
    ]);
    expect(f.hasAhu).toBe(true);
    expect(f.hasChiller).toBe(true);
    expect(f.hasVav).toBe(true);
    expect(f.hasWeather).toBe(true);
    expect(f.hasHeatPump).toBe(false);
    expect(f.hasBoiler).toBe(false);
  });

  it("hides heat pump matrix when no HP refs", () => {
    const f = plantEquipmentFamilies([{ equipment_id: "AHU_2", equipment_type: "AHU" }]);
    expect(f.hasHeatPump).toBe(false);
  });
});
