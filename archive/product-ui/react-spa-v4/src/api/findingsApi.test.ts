import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  getJobFindings,
  putJobDispositions,
  upsertDisposition,
} from "./findingsApi";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from "./client";

describe("findingsApi", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("gets findings document", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      findings: {
        schema_version: "1",
        findings: [
          {
            finding_id: "f1",
            correlation_key: "rule:VAV-1:equip:AHU-1",
          },
        ],
      },
    });
    const doc = await getJobFindings("job-1");
    expect(apiFetch).toHaveBeenCalledWith("/api/jobs/job-1/findings");
    expect(doc.findings[0]?.correlation_key).toMatch(/VAV-1/);
  });

  it("upserts disposition by correlation_key", () => {
    const doc = upsertDisposition(
      {
        schema_version: "1",
        dispositions: [
          { correlation_key: "a", status: "open" },
          { correlation_key: "b", status: "confirmed" },
        ],
      },
      { correlation_key: "a", status: "dismissed", notes: "ok" },
    );
    expect(doc.dispositions).toHaveLength(2);
    expect(doc.dispositions.find((d) => d.correlation_key === "a")?.status).toBe(
      "dismissed",
    );
  });

  it("puts dispositions document", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: true });
    await putJobDispositions("job-1", {
      schema_version: "1",
      dispositions: [{ correlation_key: "a", status: "confirmed" }],
    });
    expect(apiFetch).toHaveBeenCalledWith("/api/jobs/job-1/dispositions", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: expect.stringContaining("confirmed"),
    });
  });
});
