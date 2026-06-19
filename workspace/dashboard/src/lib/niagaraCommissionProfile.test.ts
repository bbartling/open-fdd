import { describe, expect, it } from "vitest";
import {
  addBuilding,
  addDevice,
  emptyProfile,
  organizeStationPoints,
  ordChildOf,
  suggestPointsRoot,
} from "./niagaraCommissionProfile";
import type { NiagaraTreeNode } from "./niagara-api";

const nodes: NiagaraTreeNode[] = [
  { indent: 0, name: "BacnetNetwork", ord: "slot:/Drivers/BacnetNetwork", type: "folder", status: "" },
  {
    indent: 1,
    name: "BENS BENCHTEST BOX",
    ord: "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX",
    type: "folder",
    status: "",
  },
  {
    indent: 2,
    name: "Points",
    ord: "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points",
    type: "folder",
    status: "",
  },
  {
    indent: 3,
    name: "OA-T",
    ord: "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points/OA$2dT",
    type: "point",
    status: "{ok}",
  },
];

describe("niagaraCommissionProfile", () => {
  it("ordChildOf detects hierarchy", () => {
    expect(ordChildOf("slot:/a/b/c", "slot:/a/b")).toBe(true);
    expect(ordChildOf("slot:/a/b", "slot:/a/b")).toBe(false);
  });

  it("suggests points root under device folder", () => {
    const root = suggestPointsRoot("slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX", nodes);
    expect(root).toContain("/points");
  });

  it("organizes points under building/device profile", () => {
    let profile = emptyProfile();
    profile = addBuilding(profile, nodes[0], { site_id: "demo" });
    profile = addDevice(profile, nodes[1], profile.buildings[0].id, nodes);
    const organized = organizeStationPoints({
      station_id: "bench9065",
      station_name: "Bench",
      station_url: "https://192.168.204.11",
      points: [
        {
          station_id: "bench9065",
          point_ord: nodes[3].ord,
          point_name: "OA-T",
          value: 72.5,
        },
      ],
      profile,
    });
    expect(organized.buildings).toHaveLength(1);
    expect(organized.buildings[0].devices[0].points).toHaveLength(1);
    expect(organized.unassigned).toHaveLength(0);
  });
});
