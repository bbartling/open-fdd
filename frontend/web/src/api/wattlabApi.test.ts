import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setStoredToken } from "./authApi";
import { createDump, downloadDump } from "./wattlabApi";

vi.mock("./exportApi", () => ({
  createExport: vi.fn(),
  downloadExport: vi.fn(),
}));

import { createExport, downloadExport } from "./exportApi";

describe("wattlabApi", () => {
  beforeEach(() => {
    vi.mocked(createExport).mockReset();
    vi.mocked(downloadExport).mockReset();
    setStoredToken("jwt-1");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setStoredToken(null);
  });

  it("creates a summary dump for a job and building", async () => {
    vi.mocked(createExport).mockResolvedValue({
      export_id: "export-1",
      job_id: "job-1",
      building_id: "BUILDING_100",
      profile: "summary",
      filename: "openfdd_engineering_BUILDING_100_summary.zip",
      download_url: "/api/jobs/job-1/exports/export-1/download",
    });

    const dump = await createDump("job-1", "BUILDING_100");

    expect(createExport).toHaveBeenCalledWith(
      "job-1",
      "BUILDING_100",
      "summary",
    );
    expect(dump.dump_id).toBe("export-1");
  });

  it("downloads the zip via export API (maps dump- id to export-)", async () => {
    vi.mocked(downloadExport).mockResolvedValue(undefined);

    await downloadDump("job-1", "dump-1", "dump.zip");

    expect(downloadExport).toHaveBeenCalledWith(
      "job-1",
      "export-1",
      "dump.zip",
    );
  });
});
