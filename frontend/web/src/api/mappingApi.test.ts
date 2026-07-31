import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  buildMappingManifest,
  buildPackageMappingPath,
  invertRolesToSessionMap,
  getPackageMapping,
  listPackageBuildings,
  updatePackageRoles,
} from "./mappingApi";

describe("mappingApi", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/buildings")) {
          return new Response(JSON.stringify({ ok: true, buildings: ["B1"] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (String(url).includes("/mapping")) {
          return new Response(
            JSON.stringify({
              ok: true,
              building_id: "B1",
              unit_system: "imperial",
              equipment_ids: ["AHU_1"],
              equipment: [
                {
                  equipment_id: "AHU_1",
                  equipment_type: "AHU",
                  ok: true,
                  roles: { SF_SPD: "fan_cmd" },
                  columns: [
                    { column: "SF_SPD", role: "fan_cmd", status: "mapped" },
                  ],
                  blockers: [],
                  warnings: [],
                },
              ],
              validation: {
                blocker_count: 0,
                warning_count: 0,
                equipment_count: 1,
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (String(url).includes("/roles")) {
          return new Response(
            JSON.stringify({
              ok: true,
              building_id: "B1",
              equipment_id: "AHU_1",
              roles: { SF_SPD: "fan_status" },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response("{}", { status: 404 });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("builds mapping query path", () => {
    expect(buildPackageMappingPath("B1", "AHU_1")).toBe(
      "/api/csv/import/package/mapping?building_id=B1&equipment_id=AHU_1",
    );
  });

  it("inverts column→role for session role_map", () => {
    expect(invertRolesToSessionMap({ SF_SPD: "fan_cmd", X: "" })).toEqual({
      fan_cmd: "SF_SPD",
    });
  });

  it("lists buildings and loads mapping", async () => {
    await expect(listPackageBuildings()).resolves.toEqual(["B1"]);
    const inv = await getPackageMapping("B1", "AHU_1");
    expect(inv.building_id).toBe("B1");
    expect(inv.equipment?.[0]?.roles?.SF_SPD).toBe("fan_cmd");
  });

  it("posts package role updates", async () => {
    const out = await updatePackageRoles("B1", "AHU_1", { SF_SPD: "fan_status" });
    expect(out.ok).toBe(true);
    expect(fetch).toHaveBeenCalled();
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (c) => String(c[0]).includes("/package/roles"),
    )!;
    expect(init.method).toBe("POST");
  });

  it("builds downloadable mapping manifest", () => {
    const json = buildMappingManifest({
      ok: true,
      building_id: "B1",
      unit_system: "metric",
      validation: { blocker_count: 1, warning_count: 2, equipment_count: 1 },
      equipment: [
        {
          equipment_id: "VAV_1",
          equipment_type: "VAV",
          parent_ahu: "AHU_1",
          ok: false,
          roles: {},
          blockers: ["no roles mapped"],
          warnings: [],
        },
      ],
    });
    const body = JSON.parse(json);
    expect(body.schema).toBe("openfdd_mapping_manifest_v1");
    expect(body.equipment[0].parent_ahu).toBe("AHU_1");
  });
});
