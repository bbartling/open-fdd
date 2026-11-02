import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  createWattlabHandoff,
  listReports,
  createReportDraft,
} from "./reportsApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./client";

describe("reportsApi", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("lists report records", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      records: [{ report_id: "r1", report_type: "tuning" }],
    });
    const rows = await listReports();
    expect(apiFetch).toHaveBeenCalledWith("/api/reports");
    expect(rows[0]?.report_id).toBe("r1");
  });

  it("creates draft", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, report_id: "draft-1" });
    const out = await createReportDraft({ template_id: "summary" });
    expect(apiFetch).toHaveBeenCalledWith("/api/reports/draft", expect.any(Object));
    expect(out.report_id).toBe("draft-1");
  });

  it("posts wattlab handoff", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      handoff: { handoff_id: "h1", job_id: "job-1" },
    });
    const h = await createWattlabHandoff("job-1", {
      portable_zip_uri: "workspace://exports/demo.zip",
    });
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/jobs/job-1/wattlab/handoffs",
      expect.objectContaining({ method: "POST" }),
    );
    expect(h.handoff_id).toBe("h1");
  });
});
