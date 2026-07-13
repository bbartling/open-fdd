import { describe, expect, it } from "vitest";
import { summarizeZipManifest, type ZipPackageManifest } from "./csvZipPackage";

describe("csvZipPackage", () => {
  it("summarizes manifest with mapping status", () => {
    const m: ZipPackageManifest = {
      csv_files: ["AHU_1/history_wide.csv", "weather/history_wide.csv"],
      equipment: { AHU_1: ["AHU_1/history_wide.csv"] },
      mapping_status: { present: true, valid: true, errors: [] },
    };
    expect(summarizeZipManifest(m)).toContain("2 CSV");
    expect(summarizeZipManifest(m)).toContain("mapping valid");
  });

  it("notes missing mapping", () => {
    const m: ZipPackageManifest = {
      csv_files: ["a.csv"],
      equipment: {},
      mapping_status: { present: false, valid: false, errors: ["mapping missing"] },
    };
    expect(summarizeZipManifest(m)).toContain("mapping missing");
  });
});
