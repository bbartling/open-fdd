import { describe, expect, it } from "vitest";
import { buildingIdsFromProviderSites } from "./providersApi";

describe("buildingIdsFromProviderSites", () => {
  it("omits sites with no mapped points", () => {
    const ids = buildingIdsFromProviderSites({
      sites: [
        { building_id: "ACME", mapped_points: 0 },
        { building_id: "BOSSPI", mapped_points: 4 },
      ],
      health: [{ building_id: "ACME", mapped_points: 0 }],
    });
    expect(ids).toEqual(["BOSSPI"]);
  });
});
