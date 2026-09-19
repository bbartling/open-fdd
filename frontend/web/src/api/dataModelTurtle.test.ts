import { describe, expect, it } from "vitest";
import {
  buildDataModelTurtle,
  turtleEscape,
  turtleEquipmentSubject,
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

  it("uses reversible UTF-8 enc_ segments without colliding distinct ids", () => {
    expect(turtleIriSegment("AHU_1")).toBe("AHU_1");
    expect(turtleIriSegment("AHU 1")).toBe("enc_4148552031");
    expect(turtleIriSegment("AHU:1")).not.toBe(turtleIriSegment("AHU 1"));
    expect(turtleIriSegment("site:lab/1")).toMatch(/^enc_[0-9a-f]+$/);
    expect(turtleIriSegment("AHUé")).toBe("enc_414855c3a9");
  });

  it("DM-01: reserves enc_ so literal enc_ ids stay distinct from encoded spaces", () => {
    const space = turtleIriSegment("AHU 1");
    const literal = turtleIriSegment("enc_4148552031");
    expect(space).toBe("enc_4148552031");
    expect(literal).not.toBe(space);
    expect(literal).toMatch(/^enc_[0-9a-f]+$/);
  });

  it("DM-02: building/equip tuple subjects are unambiguous", () => {
    const a = turtleEquipmentSubject("X_equip_Y", "Z");
    const b = turtleEquipmentSubject("X", "Y_equip_Z");
    expect(a).not.toBe(b);
    expect(a).toBe("ofdd:eq_X_equip_Y__Z");
    expect(b).toBe("ofdd:eq_X__Y_equip_Z");
  });

  it("keeps distinct historian ids on separate RDF subjects", () => {
    const ttl = buildDataModelTurtle({
      ok: true,
      building_id: "B1",
      equipment: [
        {
          equipment_id: "AHU 1",
          equipment_type: "AHU",
          ok: true,
          roles: { A: "sat" },
        },
        {
          equipment_id: "AHU_1",
          equipment_type: "AHU",
          ok: true,
          roles: { B: "fan_cmd" },
        },
      ],
    });
    expect(ttl).toContain("ofdd:eq_B1__enc_4148552031");
    expect(ttl).toContain("ofdd:eq_B1__AHU_1");
  });

  it("matches central non-ASCII subject IRIs", () => {
    const ttl = buildDataModelTurtle({
      ok: true,
      building_id: "Café",
      equipment: [
        {
          equipment_id: "AHUé",
          equipment_type: "AHU",
          ok: true,
          roles: { SF_SPD: "fan_cmd" },
        },
      ],
    });
    const bid = turtleIriSegment("Café");
    const eid = turtleIriSegment("AHUé");
    expect(eid).toBe("enc_414855c3a9");
    expect(ttl).toContain(`ofdd:eq_${bid}__${eid}`);
  });

  it("emits prefixes, building, AHU role binding, no phantom roles", () => {
    const ttl = buildDataModelTurtle(fixture);
    expect(ttl).toContain("@prefix ofdd:");
    expect(ttl).toContain("@prefix hs:");
    expect(ttl).toContain('ofdd:buildingId "B1"');
    expect(ttl).toContain("ofdd:eq_B1__AHU_1");
    expect(ttl).toContain('ofdd:role "fan_cmd"');
    expect(ttl).toContain('ofdd:column "SF_SPD"');
    expect(ttl).toContain("ofdd:parentAhu ofdd:eq_B1__AHU_1");
    expect(ttl).toContain('ofdd:unmappedColumn "NOISE"');
    expect(ttl).not.toMatch(/ofdd:role "duct_static"/);
    expect(ttl).not.toMatch(/phantom/);
  });

  it("DM-03: unmapped-only equipment still emits unmappedColumn", () => {
    const ttl = buildDataModelTurtle({
      ok: true,
      building_id: "B1",
      equipment: [
        {
          equipment_id: "ORPHAN",
          equipment_type: "unknown",
          ok: true,
          roles: {},
          unmapped_columns: ["RAW_X"],
        },
      ],
    });
    expect(ttl).toContain("ofdd:eq_B1__ORPHAN");
    expect(ttl).toContain('ofdd:unmappedColumn "RAW_X"');
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
