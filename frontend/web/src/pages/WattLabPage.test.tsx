import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExportPage } from "./WattLabPage";

vi.mock("../api/jobsApi", () => ({
  listJobs: vi.fn(async () => []),
  createJob: vi.fn(async () => ({
    job_id: "job-new",
    job_name: "Export",
  })),
}));

vi.mock("../api/exportApi", () => ({
  createExport: vi.fn(async () => ({
    export_id: "export-1",
    job_id: "job-1",
    building_id: "BUILDING_100",
    profile: "summary",
    filename: "openfdd_engineering_BUILDING_100_summary.zip",
    download_url: "/api/jobs/job-1/exports/export-1/download",
  })),
  downloadExport: vi.fn(async () => undefined),
}));

vi.mock("../session", () => ({
  useSessionQuery: () => ({
    query: { jobId: "job-1", siteId: "BUILDING_100" },
    setQuery: vi.fn(),
  }),
}));

describe("ExportPage / Dump", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows two dump radios and no legacy profile picker (export-two-option)", async () => {
    render(
      <MemoryRouter initialEntries={["/export?job=job-1&site=BUILDING_100"]}>
        <ExportPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByTestId("wattlab-page"));
    expect(screen.queryByTestId("dump-related-links")).toBeNull();
    expect(screen.queryByTestId("wattlab-profile")).toBeNull();
    expect(screen.queryByTestId("wattlab-handoff")).toBeNull();
    expect(screen.getByTestId("export-dump-kind")).toBeTruthy();
    expect(screen.getByLabelText(/EnergyPlus \/ agent dump/i)).toBeTruthy();
    expect(screen.getByLabelText(/Ordinary CSV/i)).toBeTruthy();
    expect(screen.queryByTestId("export-include-faults")).toBeNull();
    expect(screen.getByTestId("wattlab-build-dump")).toBeTruthy();
  });

  it("builds energyplus dump by default", async () => {
    const { createExport, downloadExport } = await import("../api/exportApi");
    render(
      <MemoryRouter initialEntries={["/export?job=job-1&site=BUILDING_100"]}>
        <ExportPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByTestId("wattlab-build-dump"));
    fireEvent.click(
      screen.getByTestId("wattlab-build-dump").querySelector("button")!,
    );
    await waitFor(() => {
      expect(createExport).toHaveBeenCalledWith("job-1", "BUILDING_100", {
        kind: "energyplus",
        includeFaults: undefined,
      });
      expect(downloadExport).toHaveBeenCalled();
    });
  });

  it("csv mode shows faults checkbox and passes include_faults when checked", async () => {
    const { createExport } = await import("../api/exportApi");
    render(
      <MemoryRouter initialEntries={["/export?job=job-1&site=BUILDING_100"]}>
        <ExportPage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByLabelText(/Ordinary CSV/i));
    await waitFor(() => screen.getByTestId("export-include-faults"));
    fireEvent.click(
      screen
        .getByTestId("export-include-faults")
        .querySelector('input[type="checkbox"]')!,
    );
    fireEvent.click(
      screen.getByTestId("wattlab-build-dump").querySelector("button")!,
    );
    await waitFor(() => {
      expect(createExport).toHaveBeenCalledWith("job-1", "BUILDING_100", {
        kind: "csv",
        includeFaults: true,
      });
    });
  });
});
