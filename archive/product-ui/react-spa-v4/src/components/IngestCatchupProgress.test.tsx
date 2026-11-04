import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { IngestCatchupProgress } from "./IngestCatchupProgress";

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

import { apiFetch } from "../api/client";

describe("IngestCatchupProgress", () => {
  it("T1423-5 renders catch-up progress from the ingest catchup API", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      providers: [
        {
          provider_instance_id: "nf:edge",
          devices: [
            {
              device_id: "AHU_1",
              mode: "asap",
              last_stored_ts: "2026-06-01T08:00:00Z",
              missing_windows: 12,
              rows_per_minute: 120,
              eta_seconds: 360,
              throttle: { state: "ready", tokens_remaining: 30 },
            },
          ],
        },
      ],
    });

    render(<IngestCatchupProgress siteId="SITE_A" />);

    await waitFor(() => {
      expect(screen.getByTestId("ingest-catchup-table")).toBeTruthy();
    });
    expect(screen.getByTestId("ingest-catchup-mode").textContent).toBe("ASAP catch-up");
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/ingest/catchup?site_id=SITE_A",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
});
