import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ProviderBindingsPanel } from "./ProviderBindingsPanel";

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

function job(overrides: Record<string, unknown> = {}) {
  return {
    job_id: "11111111-1111-1111-1111-111111111111",
    provider_instance_id: "portal-a",
    device_id: "device-a",
    model_revision: "rev-1",
    logical_window_start: "2026-10-19T09:00:00Z",
    logical_window_end: "2026-10-19T10:00:00Z",
    state: "committed",
    attempt: 1,
    safe_error_code: null,
    coverage: "not_assessed",
    counts: { fetched: 1, accepted: 1, rejected: 0, inserted: 1, updated: 0, unchanged: 0 },
    ...overrides,
  };
}

function mockLedger(jobs: unknown[], gaps: unknown[]) {
  vi.mocked(apiFetch).mockImplementation(async (path: string) => {
    if (String(path).startsWith("/api/ingest/jobs")) {
      return { ok: true, coverage: "not_assessed", jobs };
    }
    if (String(path).startsWith("/api/ingest/gaps")) {
      return {
        ok: true,
        coverage: "not_assessed",
        guarantee: "bounded_windows_only",
        update_log: "not_claimed",
        gaps,
      };
    }
    throw new ApiClientError("missing", 404);
  });
}

describe("ProviderBindingsPanel", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it("shows queue identity and gap windows without a typed-point claim", async () => {
    mockLedger(
      [job(), job({ job_id: "22222222-2222-2222-2222-222222222222", state: "partial" })],
      [
        {
          recoverable: true,
          job: job({
            job_id: "22222222-2222-2222-2222-222222222222",
            state: "partial",
            safe_error_code: "upstream_timeout",
          }),
        },
      ],
    );
    render(<ProviderBindingsPanel buildingId="NF_EDGE" />);
    await waitFor(() => {
      expect(screen.getByTestId("provider-bindings-table").textContent).toMatch(/portal-a/);
    });
    expect(screen.getByTestId("provider-bindings-table").textContent).toMatch(/device-a/);
    expect(screen.getByTestId("provider-bindings-table").textContent).toMatch(/rev-1/);
    expect(screen.getByTestId("provider-bindings-table").textContent).toMatch(/2/);
    expect(screen.getByTestId("provider-bindings-coverage").textContent).toMatch(
      /Bounded-window coverage/,
    );
    expect(screen.getByTestId("provider-bindings-coverage").textContent).toMatch(
      /not a gap-free ingest claim/,
    );
    expect(screen.getByTestId("provider-bindings-gaps").textContent).toMatch(
      /not a device-hour completeness proof/,
    );
    expect(screen.getByTestId("provider-bindings-scope").textContent).toMatch(
      /does not build a history request/,
    );
    const paths = vi.mocked(apiFetch).mock.calls.map((call) => String(call[0]));
    expect(paths.some((path) => path.startsWith("/api/ingest/jobs?site_id=NF_EDGE"))).toBe(true);
    expect(paths.some((path) => path.startsWith("/api/ingest/gaps?site_id=NF_EDGE"))).toBe(true);
    expect(paths.some((path) => path.includes("/api/providers/bindings"))).toBe(false);
    expect(document.body.textContent).not.toMatch(/N3/);
  });

  it("does not treat an empty gap list as gap-free ingest", async () => {
    mockLedger([job()], []);
    render(<ProviderBindingsPanel buildingId="NF_EDGE" />);
    await waitFor(() => {
      expect(screen.getByTestId("provider-bindings-gaps").textContent).toMatch(
        /No gaps in the returned windows/,
      );
    });
    expect(screen.getByTestId("provider-bindings-gaps").textContent).toMatch(
      /not gap-free ingest/,
    );
    expect(screen.getByTestId("provider-bindings-coverage").textContent).toMatch(
      /Coverage is not assessed/,
    );
  });

  it("shows an API error instead of an empty binding success", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (String(path).startsWith("/api/ingest/")) {
        throw new ApiClientError("shared ingest queue is unavailable", 503);
      }
      throw new ApiClientError("missing", 404);
    });
    render(<ProviderBindingsPanel buildingId="NF_EDGE" />);
    await waitFor(() => {
      expect(screen.getByTestId("provider-bindings-error").textContent).toMatch(/unavailable/);
    });
    expect(screen.getByTestId("provider-bindings-empty").textContent).toMatch(/could not be loaded/);
    expect(screen.getByTestId("provider-bindings-empty").textContent).toMatch(/not a gap-free result/);
    expect(screen.queryByTestId("provider-bindings-table")).toBeNull();
    expect(screen.queryByTestId("provider-bindings-coverage")).toBeNull();
    expect(document.body.textContent).not.toMatch(/N3/);
  });
});
