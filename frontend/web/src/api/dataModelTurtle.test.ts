import { describe, expect, it } from "vitest";
import {
  buildDataModelTurtle,
  turtleEscape,
  turtleIriSegment,
} from "./dataModelTurtle";
import type { PackageMappingResponse } from "./mappingApi";

const fixture: PackageMappingResponse = {
  ok: true,
  building_id: "B1",
  unit_system: "imperial",
  equipment: [
    {
      equipment_id: "AHU_1",
      equipment_type: "AHU",
      ok: true,
      parent_ahu: null,
      roles: { SF_SPD: "fan_cmd", DA_T: "sat" },
      columns: [
        { column: "SF_SPD", role: "fan_cmd", status: "mapped" },
        { column: "DA_T", role: "sat", status: "mapped" },
        { column: "NOISE", role: "", status: "unmapped" },
      ],
      unmapped_columns: ["NOISE"],
    },
    {
      equipment_id: "VAV_1",
      equipment_type: "VAV",
      ok: true,
      parent_ahu: "AHU_1",
      roles: { ZN_T: "zone_air_temp" },
      columns: [],
      unmapped_columns: [],
    },
  ],
};

describe("dataModelTurtle", () => {
  it("escapes quotes in literals", () => {
    expect(turtleEscape('a"b')).toBe('a\\"b');
  });

  it("sanitizes IRI segments", () => {
    expect(turtleIriSegment("site:lab/1")).toBe("site_lab_1");
  });

  it("emits prefixes, building, AHU role binding, no phantom roles", () => {
    const ttl = buildDataModelTurtle(fixture);
    expect(ttl).toContain("@prefix ofdd:");
    expect(ttl).toContain("@prefix hs:");
    expect(ttl).toContain('ofdd:buildingId "B1"');
    expect(ttl).toContain("ofdd:building_B1_equip_AHU_1");
    expect(ttl).toContain('ofdd:role "fan_cmd"');
    expect(ttl).toContain('ofdd:column "SF_SPD"');
    expect(ttl).toContain("ofdd:parentAhu ofdd:building_B1_equip_AHU_1");
    expect(ttl).toContain('ofdd:unmappedColumn "NOISE"');
    expect(ttl).not.toMatch(/ofdd:role "duct_static"/);
    expect(ttl).not.toMatch(/phantom/);
  });

  it("omits empty role strings", () => {
    const ttl = buildDataModelTurtle({
      ok: true,
      building_id: "X",
      equipment: [
        {
          equipment_id: "E1",
          equipment_type: "AHU",
          ok: true,
          roles: { A: "", B: "sat" },
        },
      ],
    });
    expect(ttl).toContain('ofdd:role "sat"');
    expect(ttl).not.toMatch(/ofdd:column "A"/);
  });
});
