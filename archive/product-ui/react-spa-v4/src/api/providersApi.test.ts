import { describe, expect, it } from "vitest";
import { buildingIdsFromProviderSites, ingestGapsPath, ingestJobsPath } from "./providersApi";

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

  it("calls ingest jobs and gaps with site_id", () => {
    expect(ingestJobsPath("NF_EDGE")).toBe("/api/ingest/jobs?site_id=NF_EDGE");
    expect(ingestGapsPath("NF_EDGE")).toBe("/api/ingest/gaps?site_id=NF_EDGE");
    expect(ingestJobsPath("NF_EDGE")).not.toContain("providers/windows");
    expect(ingestGapsPath("NF_EDGE")).not.toContain("providers/bindings");
  });
});
