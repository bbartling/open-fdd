import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setStoredToken } from "./authApi";
import { createDump, downloadDump } from "./wattlabApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./client";

describe("wattlabApi", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    setStoredToken("jwt-1");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setStoredToken(null);
  });

  it("creates a summary dump for a job and building", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      dump: {
        dump_id: "dump-1",
        job_id: "job-1",
        building_id: "BUILDING_100",
        profile: "summary",
        filename: "wattlab_dump_BUILDING_100.zip",
        download_url: "/api/jobs/job-1/wattlab/dumps/dump-1/download",
      },
    });

    const dump = await createDump("job-1", "BUILDING_100");

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/jobs/job-1/wattlab/dumps",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          building_id: "BUILDING_100",
          profile: "summary",
        }),
      }),
    );
    expect(dump.dump_id).toBe("dump-1");
  });

  it("downloads the zip with the stored bearer token", async () => {
    const click = vi.fn();
    const remove = vi.fn();
    const anchor = { href: "", download: "", click, remove };
    vi.spyOn(document, "createElement").mockReturnValue(
      anchor as unknown as HTMLAnchorElement,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(new Blob(["PK"]), {
          status: 200,
          headers: { "Content-Type": "application/zip" },
        }),
      ),
    );
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:dump"),
      revokeObjectURL: vi.fn(),
    });

    await downloadDump("job-1", "dump-1", "dump.zip");

    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs/job-1/wattlab/dumps/dump-1/download",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer jwt-1",
        }),
      }),
    );
    expect(anchor.download).toBe("dump.zip");
    expect(click).toHaveBeenCalledOnce();
  });
});
