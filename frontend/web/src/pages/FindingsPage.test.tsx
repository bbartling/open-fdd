import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { FindingsPage } from "./FindingsPage";

vi.mock("../api/jobsApi", () => ({
  listJobs: vi.fn(async () => [
    {
      schema_version: 1,
      job_id: "job-1",
      job_name: "Alpha",
      status: "active",
      archived: false,
      created_at: "",
      updated_at: "",
      tags: [],
      meta_revision: "rev-1",
      revisions: {},
    },
  ]),
}));

vi.mock("../api/findingsApi", async () => {
  const actual = await vi.importActual<typeof import("../api/findingsApi")>(
    "../api/findingsApi",
  );
  return {
    ...actual,
    getJobFindings: vi.fn(async () => ({
      schema_version: "1",
      findings: [
        {
          finding_id: "f1",
          correlation_key: "rule:VAV-1:equip:AHU-1",
          run_id: "run-1",
        },
      ],
    })),
    getJobDispositions: vi.fn(async () => ({
      schema_version: "1",
      dispositions: [
        { correlation_key: "rule:VAV-1:equip:AHU-1", status: "open" },
      ],
    })),
    putJobDispositions: vi.fn(async () => undefined),
    putJobFindings: vi.fn(async () => undefined),
  };
});

import { putJobDispositions } from "../api/findingsApi";

function renderPage(entry = "/findings?job=job-1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <FindingsPage />
    </MemoryRouter>,
  );
}

describe("FindingsPage dispositions", () => {
  beforeEach(() => {
    vi.mocked(putJobDispositions).mockClear();
  });

  it("loads findings for ?job= and shows count", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("findings-count").textContent).toMatch(
        /1 finding/,
      );
      expect(screen.getByTestId("findings-table")).toBeTruthy();
    });
  });

  it("saves disposition for selected correlation_key", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("findings-count").textContent).toMatch(
        /1 finding/,
      );
    });
    fireEvent.click(
      screen
        .getByTestId("findings-pick-rule:VAV-1:equip:AHU-1")
        .querySelector("button")!,
    );
    const status = screen
      .getByTestId("findings-status")
      .querySelector("select") as HTMLSelectElement;
    fireEvent.change(status, { target: { value: "confirmed" } });
    fireEvent.click(
      screen.getByTestId("findings-save-disp").querySelector("button")!,
    );
    await waitFor(() => {
      expect(putJobDispositions).toHaveBeenCalled();
      expect(screen.getByTestId("findings-notice").textContent).toMatch(
        /Saved disposition/,
      );
    });
  });
});
