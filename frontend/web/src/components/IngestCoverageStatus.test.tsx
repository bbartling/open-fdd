import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { IngestCoverageStatus } from "./IngestCoverageStatus";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn(),
  ApiClientError: class ApiClientError extends Error {
    status: number;
    code = "http";
    retryable = false;
    requestId = "test";
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

import { ApiClientError, apiFetch } from "../api/client";

describe("IngestCoverageStatus", () => {
  it("shows the schedule, horizon, points, and a not-verified cursor", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      state: "behind",
      providers: [
        {
          tenant_id: "lab",
          schedule: { mode: "periodic", timezone: null },
          planned_through: "2026-10-27T01:00:00Z",
          next_run: "2026-10-27T02:05:00Z",
          schedule_error: null,
          gap_scan_truncated: false,
          status: {
            provider_instance_id: "nf:nf-site-a",
            approved_points: 1,
            withheld_points: 0,
            discovered_points: 1,
            verified_through: null,
            oldest_gap: null,
            state: "behind",
          },
        },
      ],
    });
    render(<IngestCoverageStatus siteId="SITE_A" />);
    const row = await screen.findByTestId("ingest-coverage-row-nf:nf-site-a");
    expect(vi.mocked(apiFetch).mock.calls[0]?.[0]).toBe(
      "/api/ingest/gaps?site_id=SITE_A&view=status",
    );
    expect(row.textContent).toMatch(/periodic/);
    expect(row.textContent).toMatch(/2026-10-27T02:05:00Z/);
    expect(row.textContent).toMatch(/1 of 1 \(0 withheld\)/);
    expect(row.textContent).toMatch(/Behind schedule/);
    expect(screen.getByTestId("ingest-coverage-verified").textContent).toBe("Not verified");
    expect(screen.getByTestId("ingest-coverage-oldest-gap").textContent).toBe("None recorded");
  });

  it("shows a prominent not assessed banner with the reason", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      state: "not_assessed",
      state_reason: "cadence_not_bound",
      providers: [
        {
          tenant_id: "lab",
          schedule: { mode: "periodic", timezone: null },
          planned_through: null,
          next_run: null,
          schedule_error: null,
          gap_scan_truncated: false,
          status: {
            provider_instance_id: "nf:nf-site-a",
            approved_points: 4,
            withheld_points: 1,
            discovered_points: 5,
            verified_through: null,
            oldest_gap: null,
            state: "not_assessed",
            state_reason: "cadence_not_bound",
          },
        },
      ],
    });
    render(<IngestCoverageStatus siteId="SITE_A" />);
    const banner = await screen.findByTestId("ingest-coverage-not-assessed");
    expect(banner.textContent).toMatch(/Not assessed/);
    expect(banner.textContent).toMatch(/cadence binding/i);
  });

  it("shows an API error instead of an empty table", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiClientError("queue unavailable", 503));
    render(<IngestCoverageStatus siteId="SITE_A" />);
    await waitFor(() => {
      expect(screen.getByTestId("ingest-coverage-error").textContent).toBe("queue unavailable");
    });
    expect(screen.queryByTestId("ingest-coverage-table")).toBeNull();
  });
});
