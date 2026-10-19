import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { ProvidersPanel } from "./ProvidersPanel";

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

function renderPanel() {
  return render(
    <MemoryRouter>
      <ProvidersPanel />
    </MemoryRouter>,
  );
}

describe("ProvidersPanel", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("shows an NF site from health and sites without painting outer ok as coverage", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") {
        return {
          ok: true,
          poll_enabled: true,
          sites: [
            {
              building_id: "NF_EDGE",
              provider: "nf",
              endpoint: "https://user:secret@portal.example/api?token=abc",
              poll_secs: 3600,
              mapped_points: 5,
              last_poll_at: null,
              last_ingested_points: 60,
              consecutive_errors: 0,
              health: { status: "ok", message: null },
            },
          ],
        };
      }
      if (path === "/api/providers/sites") {
        return {
          sites: [
            {
              building_id: "NF_EDGE",
              provider: "nf",
              endpoint: "https://user:secret@portal.example/api?token=abc",
              poll_secs: 3600,
              mapped_points: 5,
              client_id_configured: true,
            },
          ],
        };
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-status-NF_EDGE").textContent).toMatch(/Poll reported ok/);
    });
    expect(screen.getByTestId("provider-origin-NF_EDGE").textContent).toBe("https://portal.example");
    expect(screen.getByTestId("providers-health-table").textContent).not.toMatch(/secret/);
    expect(screen.getByTestId("providers-poll-enabled").textContent).toMatch(/enabled/);
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-ledger-empty").textContent).toMatch(/not on this API yet/);
    });
    expect(screen.getByTestId("provider-driver-notes").textContent).toMatch(/GET \/api\/v1\/point\/data/);
    expect(screen.getByTestId("provider-driver-notes").textContent).toMatch(/not a poll/);
    expect(screen.getByTestId("providers-gap-guarantee").textContent).toContain("403");
    expect(screen.getByTestId("providers-gap-guarantee").textContent).toContain("not gapless");
    expect(screen.getByTestId("providers-gap-statement").textContent).toContain("Gapless: no");
    expect(screen.getByTestId("providers-gap-ledger").textContent).toMatch(/does not advance coverage/);
  });

  it("renders history capability and device-hours from the gaps ledger", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") {
        return {
          ok: true,
          poll_enabled: true,
          sites: [
            {
              building_id: "NF_EDGE",
              provider: "nf",
              last_poll_at: "2026-10-19T10:05:00Z",
              consecutive_errors: 0,
              health: { status: "ok" },
              capabilities: {
                latest: "supported",
                fetch_history: {
                  support: "supported",
                  method: "GET",
                  path: "/api/v1/point/data",
                  max_window_secs: 21600,
                },
              },
            },
          ],
        };
      }
      if (path === "/api/providers/sites") return { sites: [] };
      if (path === "/api/providers/gaps") {
        return {
          gapless: true,
          guarantee: "bounded GET history; range polling is not gapless",
          reconcile_hours: 6,
          update_log: { method_path: "GET /api/v1/point/updates/data", http_status: 403 },
          sites: [
            {
              building_id: "NF_EDGE",
              ledger: {
                hours: [
                  {
                    device_id: "AHU_1",
                    model_revision: "rev-1",
                    window_start: "2026-10-19T09:00:00Z",
                    status: "committed",
                    covered: true,
                    durable: true,
                    within_reconcile_bound: true,
                  },
                ],
                devices: [
                  {
                    device_id: "AHU_1",
                    covered_through: "2026-10-19T10:00:00Z",
                    advanced_from: "durable_committed_history_window",
                  },
                ],
              },
            },
          ],
        };
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-history-NF_EDGE").textContent).toBe(
        "GET /api/v1/point/data, max 21600s",
      );
    });
    expect(screen.getByTestId("providers-gap-ledger").textContent).toMatch(/AHU_1/);
    expect(screen.getByTestId("providers-gap-ledger").textContent).toMatch(/yes/);
    expect(screen.getByTestId("providers-gap-statement").textContent).toContain("Gapless: no");
    expect(screen.getByTestId("providers-covered-through").textContent).toMatch(
      /durable_committed_history_window/,
    );
  });

  it("renders a server ledger and keeps unrecoverable windows out of a success tone", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") {
        return {
          ok: true,
          poll_enabled: false,
          sites: [
            {
              building_id: "NF_EDGE",
              provider: "nf",
              last_poll_at: "2026-10-19T10:05:00Z",
              consecutive_errors: 0,
              health: { status: "ok" },
            },
          ],
        };
      }
      if (path === "/api/providers/sites") return { sites: [] };
      if (String(path).startsWith("/api/providers/windows")) {
        return {
          windows: [
            {
              job_id: "job-9",
              device_id: "AHU_1",
              window_start: "2026-10-19T09:00:00Z",
              window_end: "2026-10-19T10:00:00Z",
              state: "permanent_failure",
              recoverable: false,
              reason: "retention expired",
              requested_points: 5,
              committed: 0,
            },
          ],
        };
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => screen.getByTestId("provider-open-NF_EDGE"));
    expect(screen.getByTestId("provider-status-NF_EDGE").textContent).toMatch(/Poll ok/);
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-ledger-table").textContent).toMatch(/Unrecoverable/);
    });
    expect(screen.getByTestId("provider-ledger-table").textContent).toMatch(/retention expired/);
    expect(screen.getByTestId("provider-backfill-note").textContent).toMatch(/not submitted/);
    expect(screen.getByRole("link", { name: "Inspect" }).getAttribute("href")).toContain("site=NF_EDGE");
    expect(screen.getByRole("link", { name: "Model" }).getAttribute("href")).toContain("eq=AHU_1");
  });
});
