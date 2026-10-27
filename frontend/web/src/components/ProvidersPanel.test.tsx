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

function job(overrides: Record<string, unknown> = {}) {
  return {
    job_id: "11111111-1111-1111-1111-111111111111",
    tenant_id: "tenant-a",
    canonical_site: "NF_EDGE",
    provider_instance_id: "portal-a",
    device_id: "device-a",
    model_revision: "rev-1",
    logical_window_start: "2026-10-19T09:00:00Z",
    logical_window_end: "2026-10-19T10:00:00Z",
    state: "committed",
    attempt: 1,
    safe_error_code: null,
    coverage: "not_assessed",
    counts: { fetched: 4, accepted: 4, rejected: 0, inserted: 4, updated: 0, unchanged: 0 },
    ...overrides,
  };
}

function jobsEnvelope(jobs: unknown[]) {
  return { ok: true, coverage: "not_assessed", jobs };
}

function gapsEnvelope(gaps: unknown[]) {
  return {
    ok: true,
    coverage: "not_assessed",
    guarantee: "bounded_windows_only",
    update_log: "not_claimed",
    gaps,
  };
}

function healthBody(coverageGapless = false) {
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
        last_poll_at: "2026-10-19T10:05:00Z",
        last_ingested_points: 60,
        consecutive_errors: 0,
        health: {
          status: "ok",
          message: null,
          last_success_at: "2026-10-19T10:00:00Z",
          last_error_at: null,
        },
        coverage_ledger: {
          gapless: coverageGapless,
          guarantee: { statement: "Range polling is not gapless.", gapless: coverageGapless },
          axes: [],
        },
      },
    ],
  };
}

function assertBoundedCoverage() {
  const coverage = screen.getByTestId("provider-ledger-coverage").textContent ?? "";
  expect(coverage).toMatch(/Bounded-window coverage/);
  expect(coverage).toMatch(/Coverage is not assessed/);
  expect(coverage).toMatch(/not a gap-free ingest claim/);
  expect(screen.getByTestId("coverage-gapless").textContent).not.toMatch(/Gapless:\s*yes/i);
  expect(screen.getByTestId("coverage-gapless").textContent).toMatch(/does not establish gap-free ingest/);
  expect(document.body.textContent).not.toMatch(/N5 have not landed/);
  expect(document.body.textContent).not.toMatch(/Gapless:\s*yes/i);
}

describe("ProvidersPanel", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("shows an NF site and a missing ingest contract without a gap-free claim", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") return healthBody(true);
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
              transport: "rest",
            },
          ],
        };
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-status-NF_EDGE").textContent).toMatch(/Poll ok/);
    });
    expect(screen.getByTestId("provider-origin-NF_EDGE").textContent).toBe("https://portal.example");
    expect(screen.getByTestId("provider-connection-NF_EDGE").textContent).toBe("Portal (HTTPS)");
    expect(screen.getByTestId("provider-last-success-NF_EDGE").textContent).toBe(
      "2026-10-19T10:00:00Z",
    );
    expect(screen.getByTestId("provider-last-ingested-NF_EDGE").textContent).toBe("60");
    expect(screen.getByTestId("provider-last-ingested-NF_EDGE").textContent).not.toMatch(/1970|T\d{2}:/);
    expect(screen.getByTestId("provider-last-error-NF_EDGE").textContent).toBe("—");
    expect(screen.getByTestId("providers-health-table").textContent).not.toMatch(/secret/);
    expect(screen.getByTestId("providers-poll-enabled").textContent).toMatch(/enabled/);
    expect(screen.getByTestId("coverage-gapless").textContent).not.toMatch(/Gapless:\s*yes/i);
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-ledger-empty").textContent).toMatch(
        /ingest jobs or gaps endpoint is not on this API/,
      );
    });
    expect(screen.getByTestId("provider-ledger-empty").textContent).toMatch(/not a gap-free ingest/);
    expect(screen.queryByTestId("provider-driver-notes")).toBeNull();
    expect(screen.queryByTestId("provider-registry")).toBeNull();
    expect(screen.getByText(/Poll status is separate from history coverage/)).toBeTruthy();
    expect(screen.queryByTestId("provider-ledger-jobs")).toBeNull();
    const paths = vi.mocked(apiFetch).mock.calls.map((call) => String(call[0]));
    expect(paths.some((path) => path.startsWith("/api/ingest/jobs?site_id=NF_EDGE"))).toBe(true);
    expect(paths.some((path) => path.startsWith("/api/ingest/gaps?site_id=NF_EDGE"))).toBe(true);
    expect(paths.some((path) => path.includes("/api/providers/windows"))).toBe(false);
  });

  it("labels bounded-window coverage when gaps are present", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") return healthBody(false);
      if (path === "/api/providers/sites") return { sites: [], poll_enabled: false };
      if (String(path).startsWith("/api/ingest/jobs")) {
        return jobsEnvelope([
          job(),
          job({
            job_id: "22222222-2222-2222-2222-222222222222",
            state: "partial",
            attempt: 2,
            safe_error_code: "upstream_timeout",
            logical_window_start: "2026-10-19T10:00:00Z",
            logical_window_end: "2026-10-19T11:00:00Z",
            counts: { fetched: 3, accepted: 1, rejected: 2, inserted: 0, updated: 0, unchanged: 0 },
          }),
        ]);
      }
      if (String(path).startsWith("/api/ingest/gaps")) {
        return gapsEnvelope([
          {
            recoverable: false,
            job: job({
              job_id: "33333333-3333-3333-3333-333333333333",
              state: "permanent_failure",
              safe_error_code: "retention_exceeded",
              logical_window_start: "2026-10-19T08:00:00Z",
              logical_window_end: "2026-10-19T09:00:00Z",
            }),
          },
          {
            recoverable: true,
            job: job({
              job_id: "22222222-2222-2222-2222-222222222222",
              state: "partial",
              safe_error_code: "upstream_timeout",
            }),
          },
        ]);
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => screen.getByTestId("provider-open-NF_EDGE"));
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-ledger-gaps").textContent).toMatch(/Unrecoverable/);
    });
    assertBoundedCoverage();
    expect(screen.getByTestId("provider-ledger-gaps").textContent).toMatch(/retention_exceeded/);
    expect(screen.getByTestId("provider-ledger-gaps").textContent).toMatch(/Partial/);
    expect(screen.getByTestId("provider-ledger-jobs").textContent).toMatch(/Committed/);
    expect(screen.getByTestId("provider-ledger-gaps-note").textContent).toMatch(
      /not a device-hour completeness proof/,
    );
    const inspect = screen.getAllByRole("link", { name: "Inspect" });
    expect(inspect[0]?.getAttribute("href")).toContain("site=NF_EDGE");
    expect(screen.getAllByRole("link", { name: "Model" })[0]?.getAttribute("href")).toContain(
      "eq=device-a",
    );
    expect(screen.getByTestId("coverage-gapless").textContent).toMatch(/does not establish gap-free/);
  });

  it("keeps an empty gap list from claiming gap-free ingest", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") return healthBody(false);
      if (path === "/api/providers/sites") return { sites: [] };
      if (String(path).startsWith("/api/ingest/jobs")) return jobsEnvelope([job()]);
      if (String(path).startsWith("/api/ingest/gaps")) return gapsEnvelope([]);
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => screen.getByTestId("provider-open-NF_EDGE"));
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-ledger-gaps-note").textContent).toMatch(
        /No gaps in the returned windows/,
      );
    });
    assertBoundedCoverage();
    expect(screen.getByTestId("provider-ledger-gaps-note").textContent).toMatch(
      /empty gap list is not gap-free ingest/,
    );
    expect(screen.getByTestId("provider-ledger-jobs").textContent).toMatch(/Committed/);
    expect(screen.queryByTestId("provider-ledger-gaps")).toBeNull();
  });

  it("shows an ingest API error without an empty success ledger", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") return healthBody(false);
      if (path === "/api/providers/sites") return { sites: [] };
      if (String(path).startsWith("/api/ingest/jobs") || String(path).startsWith("/api/ingest/gaps")) {
        throw new ApiClientError("shared ingest queue is unavailable", 503);
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => screen.getByTestId("provider-open-NF_EDGE"));
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-ledger-error").textContent).toMatch(/unavailable/);
    });
    expect(screen.getByTestId("provider-ledger-empty").textContent).toMatch(/could not be loaded/);
    expect(screen.getByTestId("provider-ledger-empty").textContent).toMatch(/not a gap-free result/);
    expect(screen.queryByTestId("provider-ledger-jobs")).toBeNull();
    expect(screen.queryByTestId("provider-ledger-coverage")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Gapless:\s*yes/i);
    expect(document.body.textContent).not.toMatch(/N5 have not landed/);
  });

  it("renders a count in Last ingested points and keeps a healthy message out of Last error", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") {
        return {
          ...healthBody(false),
          sites: [
            {
              ...healthBody(false).sites[0],
              last_ingested_points: 1500,
              health: {
                status: "ok",
                message: "committed; update log not claimed",
                last_success_at: "2026-10-19T10:00:00Z",
                last_error_at: null,
              },
            },
          ],
        };
      }
      if (path === "/api/providers/sites") return { sites: [] };
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-status-NF_EDGE").textContent).toMatch(/Poll ok/);
    });
    const ingested = screen.getByTestId("provider-last-ingested-NF_EDGE");
    const errorCell = screen.getByTestId("provider-last-error-NF_EDGE");
    expect(ingested.textContent).toBe("1,500");
    expect(ingested.textContent).not.toMatch(/1970|T\d{2}:/);
    expect(errorCell.textContent).toBe("—");
    expect(errorCell.textContent).not.toMatch(/committed/);
    expect(screen.getByTestId("providers-health-table").textContent).toMatch(/Last ingested points/);
  });

  it("shows LAN (gRPC) for a gRPC site and not reported when config is missing", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") return healthBody(false);
      if (path === "/api/providers/sites") {
        return { sites: [{ building_id: "NF_EDGE", provider: "nf", transport: "grpc" }] };
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-connection-NF_EDGE").textContent).toBe("LAN (gRPC)");
    });
    expect(screen.getByTestId("providers-health-table").textContent).toMatch(/Connection/);
    expect(screen.getByTestId("providers-health-table").textContent).not.toMatch(/Portal \(HTTPS\)/);
  });

  it("does not guess a connection when the sites config is unavailable", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") return healthBody(false);
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-connection-NF_EDGE").textContent).toBe("not reported");
    });
  });

  it("shows an error status message under Last error", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") {
        return {
          ...healthBody(false),
          sites: [
            {
              ...healthBody(false).sites[0],
              consecutive_errors: 2,
              health: {
                status: "error",
                message: "history_failed",
                last_success_at: null,
                last_error_at: "2026-10-19T11:00:00Z",
              },
            },
          ],
        };
      }
      if (path === "/api/providers/sites") return { sites: [] };
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-last-error-NF_EDGE").textContent).toBe("history_failed");
    });
  });

  it("reads complete and incomplete job coverage without a gap-free claim", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") return healthBody(false);
      if (path === "/api/providers/sites") return { sites: [] };
      if (String(path).startsWith("/api/ingest/jobs")) {
        return {
          ok: true,
          coverage: "incomplete",
          jobs: [
            job({ coverage: "complete", state: "committed" }),
            job({
              job_id: "22222222-2222-2222-2222-222222222222",
              state: "partial",
              coverage: "incomplete",
              safe_error_code: "upstream_timeout",
            }),
          ],
        };
      }
      if (String(path).startsWith("/api/ingest/gaps")) {
        return {
          ok: true,
          coverage: "incomplete",
          guarantee: "bounded_windows_only",
          update_log: "not_claimed",
          gaps: [
            {
              recoverable: true,
              job: job({
                job_id: "22222222-2222-2222-2222-222222222222",
                state: "partial",
                coverage: "incomplete",
                safe_error_code: "upstream_timeout",
              }),
            },
          ],
        };
      }
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => screen.getByTestId("provider-open-NF_EDGE"));
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-ledger-jobs").textContent).toMatch(/Complete/);
    });
    const jobs = screen.getByTestId("provider-ledger-jobs").textContent ?? "";
    const gaps = screen.getByTestId("provider-ledger-gaps").textContent ?? "";
    const coverage = screen.getByTestId("provider-ledger-coverage").textContent ?? "";
    expect(jobs).toMatch(/Incomplete/);
    expect(jobs).toMatch(/Committed/);
    expect(gaps).toMatch(/Partial/);
    expect(gaps).not.toMatch(/Complete/);
    expect(coverage).toMatch(/Job coverage is incomplete/);
    expect(coverage).toMatch(/not a gap-free ingest claim/);
    expect(screen.getByTestId("provider-ledger-gaps-note").textContent).toMatch(
      /Gaps coverage is incomplete/,
    );
    expect(screen.getByTestId("provider-ledger-gaps-note").textContent).not.toMatch(
      /Job coverage is incomplete/,
    );
  });

  it("shows approved and withheld point counts with reasons", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/api/providers/health") {
        return {
          ...healthBody(false),
          sites: [
            {
              ...healthBody(false).sites[0],
              approved_points: 4,
              withheld_points: 1,
              withheld_point_reasons: [
                {
                  equipment_id: "AHU_1",
                  semantic_point_id: "mixed-air-temp",
                  reason: "provisional",
                },
              ],
            },
          ],
        };
      }
      if (path === "/api/providers/sites") return { sites: [] };
      throw new ApiClientError("missing", 404);
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("provider-approved-NF_EDGE").textContent).toBe("4");
      expect(screen.getByTestId("provider-withheld-NF_EDGE").textContent).toBe("1");
    });
    fireEvent.click(screen.getByTestId("provider-open-NF_EDGE"));
    await waitFor(() => {
      expect(screen.getByTestId("provider-withheld-reasons").textContent).toMatch(/provisional/);
      expect(screen.getByTestId("provider-withheld-reasons").textContent).toMatch(
        /mixed-air-temp/,
      );
    });
  });
});
